# SPDX-License-Identifier: GPL-3.0-or-later
"""Motor de cálculo de los workers (spec 004 §4.5; plan 004 §5.2.5, §5.2.6 y §5.4.7;
ADR-0009 y ADR-0017).

El motor de cálculo es una carpeta ``runtime/<lock_id>/site`` en los datos de usuario de
Geoblender con los paquetes que fija el **lock** (``runtime_lock.toml``, junto a este
módulo: se empaqueta con la extensión). Esta parte (T24) lee el lock:

- :func:`read_lock` lee y valida ``runtime_lock.toml`` (por defecto :data:`LOCK_PATH`) y
  devuelve un :class:`RuntimeLock` con sus :class:`LockedPackage`; si el fichero no
  existe o no cumple el esquema ``geoblender.runtime_lock/1``, :class:`LockError` (un
  ``ValueError``) dice qué falla.
- :func:`compute_lock_id`: los 12 primeros hexadecimales del sha256 de
  :func:`canonical_lock`, el JSON con claves ordenadas de ``schema``, ``python``,
  ``platform`` y la lista ``{name, version, sha256}`` de los paquetes, ordenada por nombre
  (normalizado según PEP 503). Reordenar los paquetes o cambiar lo que no los identifica
  (url, tamaños, licencias, ``required_by``) no lo cambia; una huella o una versión, sí.
  Dos locks iguales dan la misma carpeta del motor (plan 004 §6).

Las licencias del lock (ADR-0017) las comprueba ``tools/check_licenses.py``; los campos
que salen de PyPI y de la rueda los escribe ``tools/lock_runtime.py``. Este módulo no usa
la red ni toca ``sys.path``.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCK_FILE = "runtime_lock.toml"
LOCK_PATH = Path(__file__).with_name(LOCK_FILE)
LOCK_SCHEMA = "geoblender.runtime_lock/1"
LOCK_ID_LENGTH = 12
PACKAGE_TABLE = "package"
LOCK_KEYS: tuple[str, ...] = ("schema", "python", "platform", PACKAGE_TABLE)
PACKAGE_KEYS: tuple[str, ...] = (
    "name",
    "version",
    "filename",
    "url",
    "sha256",
    "size",
    "installed_size",
    "license",
    "bundled_licenses",
    "required_by",
)

_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_NAME_SEPARATORS = re.compile(r"[-_.]+")


class LockError(ValueError):
    """El lock del motor de cálculo no se puede leer o no cumple su esquema: el mensaje
    dice qué falla y dónde."""


def normalize_name(name: str) -> str:
    """Nombre de un paquete normalizado (PEP 503): ``Py_Proj`` → ``py-proj``."""
    return _NAME_SEPARATORS.sub("-", name).lower()


@dataclass(frozen=True, slots=True, kw_only=True)
class LockedPackage:
    """Un paquete del lock: la rueda de PyPI que se instala en el motor (plan 004
    §5.2.5). ``size`` e ``installed_size`` en bytes; ``sha256`` en minúsculas."""

    name: str
    version: str
    filename: str
    url: str
    sha256: str
    size: int
    installed_size: int
    license: str
    bundled_licenses: tuple[str, ...] = ()
    required_by: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        """El nombre normalizado (PEP 503), con el que se ordena y se busca."""
        return normalize_name(self.name)


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeLock:
    """El lock del motor de cálculo: cabecera y paquetes, en el orden del fichero."""

    schema: str
    python: str
    platform: str
    packages: tuple[LockedPackage, ...]

    @property
    def lock_id(self) -> str:
        """El identificador del lock (:func:`compute_lock_id`): nombre de la carpeta del
        motor."""
        return compute_lock_id(self)

    @property
    def download_size(self) -> int:
        """Bytes de todas las ruedas."""
        return sum(package.size for package in self.packages)

    @property
    def installed_size(self) -> int:
        """Bytes del motor instalado."""
        return sum(package.installed_size for package in self.packages)

    def package(self, name: str) -> LockedPackage | None:
        """El paquete de nombre ``name`` (sin distinguir ``-``, ``_``, ``.`` ni
        mayúsculas), o ``None``."""
        key = normalize_name(name)
        return next((p for p in self.packages if p.key == key), None)


def canonical_lock(lock: RuntimeLock) -> str:
    """La forma canónica del lock (plan 004 §5.2.5): JSON compacto con claves ordenadas
    de ``schema``, ``python``, ``platform`` y ``package``, la lista ``{name, version,
    sha256}`` ordenada por nombre normalizado."""
    payload = {
        "schema": lock.schema,
        "python": lock.python,
        "platform": lock.platform,
        PACKAGE_TABLE: [
            {"name": package.key, "version": package.version, "sha256": package.sha256}
            for package in sorted(lock.packages, key=lambda item: item.key)
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_lock_id(lock: RuntimeLock) -> str:
    """Los :data:`LOCK_ID_LENGTH` primeros hexadecimales del sha256 de
    :func:`canonical_lock`."""
    digest = hashlib.sha256(canonical_lock(lock).encode("utf-8")).hexdigest()
    return digest[:LOCK_ID_LENGTH]


def _text(entry: dict[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LockError(f"{where}: «{key}» debe ser un texto no vacío")
    return value


def _size(entry: dict[str, Any], key: str, where: str) -> int:
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LockError(f"{where}: «{key}» debe ser un número entero de bytes (≥ 0)")
    return value


def _texts(entry: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = entry.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LockError(f"{where}: «{key}» debe ser una lista de textos")
    return tuple(value)


def _package(entry: object, index: int) -> LockedPackage:
    where = f"paquete n.º {index + 1} del lock"
    if not isinstance(entry, dict):
        raise LockError(f"{where}: debe ser una tabla [[{PACKAGE_TABLE}]]")
    name = entry.get("name")
    if isinstance(name, str) and name.strip():
        where = f"paquete «{name}» del lock"
    unknown = sorted(key for key in entry if key not in PACKAGE_KEYS)
    if unknown:
        raise LockError(f"{where}: clave desconocida «{unknown[0]}»")
    missing = [key for key in PACKAGE_KEYS if key not in entry]
    if missing:
        raise LockError(f"{where}: falta «{missing[0]}»")
    sha256 = _text(entry, "sha256", where)
    if not _SHA256.fullmatch(sha256):
        raise LockError(f"{where}: «sha256» debe tener 64 hexadecimales")
    filename = _text(entry, "filename", where)
    if not filename.endswith(".whl") or "/" in filename or "\\" in filename:
        raise LockError(f"{where}: «filename» debe ser el nombre de un fichero «.whl»")
    return LockedPackage(
        name=_text(entry, "name", where),
        version=_text(entry, "version", where),
        filename=filename,
        url=_text(entry, "url", where),
        sha256=sha256.lower(),
        size=_size(entry, "size", where),
        installed_size=_size(entry, "installed_size", where),
        license=_text(entry, "license", where),
        bundled_licenses=_texts(entry, "bundled_licenses", where),
        required_by=_texts(entry, "required_by", where),
    )


def parse_lock(data: dict[str, Any]) -> RuntimeLock:
    """El :class:`RuntimeLock` de un lock ya leído como TOML; :class:`LockError` si no
    cumple el esquema."""
    if not isinstance(data, dict):
        raise LockError("el lock debe ser una tabla TOML")
    schema = data.get("schema")
    if schema != LOCK_SCHEMA:
        raise LockError(f"«schema» vale {schema!r} y esta versión lee «{LOCK_SCHEMA}»")
    unknown = sorted(key for key in data if key not in LOCK_KEYS)
    if unknown:
        raise LockError(f"clave desconocida «{unknown[0]}» en la cabecera del lock")
    python = _text(data, "python", "cabecera del lock")
    platform = _text(data, "platform", "cabecera del lock")
    entries = data.get(PACKAGE_TABLE)
    if not isinstance(entries, list) or not entries:
        raise LockError(f"el lock no tiene ningún paquete ([[{PACKAGE_TABLE}]])")
    packages = tuple(_package(entry, index) for index, entry in enumerate(entries))
    seen: set[str] = set()
    for package in packages:
        if package.key in seen:
            raise LockError(f"el paquete «{package.name}» está repetido en el lock")
        seen.add(package.key)
    return RuntimeLock(schema=schema, python=python, platform=platform, packages=packages)


def read_lock(path: Path = LOCK_PATH) -> RuntimeLock:
    """Lee el lock de ``path`` (UTF-8, TOML); :class:`LockError` con el motivo y la ruta
    si no existe, no se lee o no cumple el esquema."""
    try:
        text = Path(path).read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise LockError(f"no existe el lock del motor de cálculo «{path}»") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise LockError(f"no se puede leer el lock «{path}»: {exc}") from None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise LockError(f"el lock «{path}» no es TOML válido: {exc}") from None
    try:
        return parse_lock(data)
    except LockError as exc:
        raise LockError(f"{path}: {exc}") from None
