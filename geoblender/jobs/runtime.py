# SPDX-License-Identifier: GPL-3.0-or-later
"""Motor de cálculo de los workers (spec 004 §4.5; plan 004 §5.2.5, §5.2.6 y §5.4.7;
ADR-0009 y ADR-0017).

El motor de cálculo es una carpeta ``runtime/<lock_id>/site`` en los datos de usuario de
Geoblender con los paquetes que fija el **lock** (``runtime_lock.toml``, junto a este
módulo: se empaqueta con la extensión). El lock (T24):

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
que salen de PyPI y de la rueda los escribe ``tools/lock_runtime.py``.

El motor de un lock (T26), :class:`ComputeEnvironment`:

- su carpeta ``<datos de usuario>/runtime/<lock_id>/`` (:attr:`~ComputeEnvironment.path`),
  con los paquetes en ``site/`` y ``runtime.json`` (``geoblender.runtime/1``: lock, origen,
  consentimiento y última verificación; lo escribe la adopción tras verificar, T28);
- :meth:`~ComputeEnvironment.status`: ``missing`` (no existe la carpeta del lock vigente),
  ``broken`` (existe sin una verificación válida) o ``ready`` (plan §5.2.6). Una carpeta
  ``<lock_id>.partial`` (instalación a medias) nunca cuenta. ``outdated`` (falta la del
  lock vigente pero queda otra) llega con T29;
- :meth:`~ComputeEnvironment.plan_install`: el :class:`InstallPlan` que el diálogo de
  consentimiento enseña antes de hacer nada (RF-004-20): origen (:class:`WheelSource`,
  almacén de ruedas o PyPI), paquetes con su versión y sus licencias, MB de descarga y en
  disco (del lock), carpeta de destino y la huella ``digest`` del plan. Nunca usa la red:
  PyPI con el acceso en línea de Blender desactivado es ``network_not_allowed``
  (RF-004-23); con el almacén solo mira que estén sus ruedas (``wheel_not_found``,
  RF-004-24);
- :meth:`~ComputeEnvironment.install_request`: con el :class:`Consent` del usuario
  (usuario, equipo, hora y la huella del plan que vio), la petición del trabajo
  ``runtime_install`` (RF-004-19). Las rutas (el almacén, el destino) no van en ella: viajan
  en la línea de órdenes (plan §5.3.3 y §5.4.7), con las de
  :meth:`~ComputeEnvironment.install_paths` (``JobRunner.submit(..., paths=…)``).

Nada de esto crea, descarga ni borra el motor (RF-004-19): solo lo hace el trabajo que se
lanza con el consentimiento.

La instalación (T27), que ejecuta ese trabajo (``workers/runtime_install.py``) con el
Python de Blender en un proceso aparte (plan §5.4.7):

- :func:`install_task`: lo que pide la petición (:class:`InstallTask`), con las rutas de la
  línea de órdenes; los paquetes van a ``<runtime>/<lock_id>.partial/site``
  (:func:`partial_dir`), hermana de la carpeta final, que solo la adopción (T28) convierte
  en el motor.
- :func:`fetch_wheel`: copia la rueda del almacén o la descarga de la URL del lock con
  ``urllib`` (``https``; ``file`` para las pruebas), calculando su sha256 mientras la lee:
  si no es la del lock, ``wheel_hash_mismatch`` y no queda nada (RF-004-21). ``pip`` no ve
  una rueda sin comprobar.
- :func:`write_requirements` y :func:`run_pip_install`: ``requirements.txt`` con la huella de
  cada paquete y el ``pip`` del Python de Blender con la orden de :func:`pip_install_command`
  (``--isolated``: no lee las variables ``PIP_*`` ni la configuración del usuario;
  ``--no-index`` y ``--find-links``: solo las ruedas comprobadas; ``--no-cache-dir``: ninguna
  caché fuera del trabajo). Se cancela matando ``pip``.

La verificación y la adopción (T28; RF-004-22, plan §5.4.7):

- :func:`probe_environment`, dentro del trabajo ``runtime_check``
  (``workers/runtime_check.py``, entorno ``compute``: el Python de Blender con ``-I -S`` y,
  como única carpeta de paquetes, la que se verifica): la versión de cada paquete del lock
  según sus ``*.dist-info`` (``importlib.metadata``), que numpy se carga desde esa carpeta y
  no desde Blender, que su BLAS no es ``auto``, los s del producto float64 2000 × 2000 (el
  mejor de 3) y la longitud máxima de ruta (RNF-004-08). Lo que no cumple va en
  ``problems`` con su código del §8 (:func:`check_errors`); el trabajo falla con el primero.
- :meth:`ComputeEnvironment.adopt`: solo con una verificación que pasó, escribe
  ``runtime.json`` (lock, paquetes con su versión y su huella, origen, consentimiento y la
  verificación) en la carpeta parcial y la convierte en el motor con
  ``os.replace(<lock_id>.partial → <lock_id>)`` (un motor anterior del mismo lock, roto,
  se aparta antes y se borra después).
- :class:`RuntimeSetup`: la cadena en el lanzador. :meth:`RuntimeSetup.install`: instalar
  (``runtime_install``) → verificar la carpeta parcial (``runtime_check`` con
  ``site_override``) → adoptar; si algo falla, o se cancela, borra la carpeta parcial y no
  adopta nada (RF-004-21). :meth:`RuntimeSetup.verify`: verifica el motor instalado y anota
  el resultado en su ``runtime.json`` (:meth:`ComputeEnvironment.record_check` o
  :meth:`ComputeEnvironment.record_failed_check`): si no pasa, queda ``broken`` y los
  trabajos que lo necesitan no se lanzan hasta repararlo (RF-004-25).

Solo :func:`fetch_wheel` usa la red (la URL del lock, con el consentimiento del usuario, desde
el trabajo de instalación). Este módulo no toca ``sys.path``: es el único que construye la
orden de ``pip``.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import http.client
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import time
import tomllib
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import IO, Any, Protocol

from ..core.sysinfo import host_name, user_name
from ..core.timeutil import format_utc, parse_utc
from . import catalog

# ``_remove_retrying`` y ``_pause``: los mismos reintentos que la limpieza de los trabajos.
from .cleanup import REMOVE_RETRIES, _pause, _remove_retrying
from .messages import JobError, Message
from .paths import BYTES_PER_MB, PARTIAL_SUFFIX
from .protocol import JobRequest, JsonValue, new_request, plain_json
from .records import LOGGER
from .worker_api import CANCELLED_TEXT, JobCancelled, JobFailed, blas_name

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

    def to_json(self) -> dict[str, JsonValue]:
        """El paquete como una tabla ``[[package]]`` del lock (:data:`PACKAGE_KEYS`)."""
        return {
            "name": self.name,
            "version": self.version,
            "filename": self.filename,
            "url": self.url,
            "sha256": self.sha256,
            "size": self.size,
            "installed_size": self.installed_size,
            "license": self.license,
            "bundled_licenses": list(self.bundled_licenses),
            "required_by": list(self.required_by),
        }


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

    def to_json(self) -> dict[str, JsonValue]:
        """El lock como su TOML leído: :func:`parse_lock` lo devuelve igual (así viaja en la
        petición de ``runtime_check``)."""
        return {
            "schema": self.schema,
            "python": self.python,
            "platform": self.platform,
            PACKAGE_TABLE: [package.to_json() for package in self.packages],
        }


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


# --- El motor instalado y su plan de instalación (T26) ---------------------------------------

RUNTIME_DIR = "runtime"
"""Carpeta de los motores dentro de los datos de usuario de Geoblender."""
SITE_DIR = "site"
"""Carpeta de los paquetes de un motor (destino de la instalación, ``--site`` del worker)."""
RUNTIME_FILE = "runtime.json"
RUNTIME_SCHEMA = "geoblender.runtime/1"
VERIFICATION_KEY = "verification"
"""Clave de ``runtime.json`` con la última verificación; vale si su ``ok`` es ``true``."""

STATUS_MISSING = "missing"
STATUS_OUTDATED = "outdated"
STATUS_BROKEN = "broken"
STATUS_READY = "ready"
STATUSES: tuple[str, ...] = (STATUS_MISSING, STATUS_OUTDATED, STATUS_BROKEN, STATUS_READY)
"""Los estados de un motor (plan §5.2.6)."""

SOURCE_WHEELHOUSE = "wheelhouse"
SOURCE_PYPI = "pypi"
SOURCE_AUTO = "auto"
SOURCE_KINDS: tuple[str, ...] = (SOURCE_WHEELHOUSE, SOURCE_PYPI)
"""Los orígenes de las ruedas: el almacén de ruedas (una carpeta) o PyPI."""
SOURCE_CHOICES: tuple[str, ...] = (SOURCE_AUTO, SOURCE_WHEELHOUSE, SOURCE_PYPI)
"""Lo que se elige en las preferencias (``runtime_source``, en minúsculas)."""

PLAN_SCHEMA = "geoblender.runtime_plan/1"
"""Esquema de la forma canónica del plan, de la que sale su huella."""
INSTALL_WORKER = "runtime_install"
INSTALL_OWNER = "jobs"


@dataclass(frozen=True, slots=True, kw_only=True)
class WheelSource:
    """De dónde salen las ruedas del motor: ``kind`` es :data:`SOURCE_WHEELHOUSE` (con
    ``folder``, la carpeta del almacén, ruta completa) o :data:`SOURCE_PYPI` (sin carpeta;
    las URL del lock). :class:`ValueError` si no cumple."""

    kind: str
    folder: Path | None = None

    def __post_init__(self) -> None:
        if self.kind not in SOURCE_KINDS:
            raise ValueError(
                f"el origen de las ruedas {self.kind!r} no es uno de {', '.join(SOURCE_KINDS)}"
            )
        if self.kind == SOURCE_PYPI:
            if self.folder is not None:
                raise ValueError("el origen PyPI no lleva carpeta")
            return
        if self.folder is None:
            raise ValueError("el almacén de ruedas necesita su carpeta")
        folder = Path(self.folder)
        if not folder.is_absolute():
            raise ValueError(
                f"la carpeta del almacén de ruedas «{folder}» no es una ruta completa"
            )
        object.__setattr__(self, "folder", folder)

    @classmethod
    def pypi(cls) -> WheelSource:
        """PyPI: las URL del lock (necesita el acceso en línea de Blender)."""
        return cls(kind=SOURCE_PYPI)

    @classmethod
    def wheelhouse(cls, folder: Path) -> WheelSource:
        """El almacén de ruedas de la carpeta ``folder`` (local o del NAS)."""
        return cls(kind=SOURCE_WHEELHOUSE, folder=Path(folder))


def choose_source(choice: str, *, wheelhouse_dir: Path | None) -> WheelSource:
    """El origen de las ruedas según la preferencia ``choice`` (``auto``, ``wheelhouse`` o
    ``pypi``, sin distinguir mayúsculas) y la carpeta del almacén configurada
    (``wheelhouse_dir``; ``None`` o vacía, ninguna). ``auto``: el almacén si hay carpeta y,
    si no, PyPI; un almacén configurado que no se alcanza no pasa a PyPI sin preguntar
    (spec §8). ``wheelhouse`` sin carpeta, u otra elección, :class:`ValueError`."""
    key = choice.lower() if isinstance(choice, str) else choice
    if key not in SOURCE_CHOICES:
        raise ValueError(
            f"el origen {choice!r} no es uno de {', '.join(SOURCE_CHOICES)}"
        )
    if key == SOURCE_PYPI:
        return WheelSource.pypi()
    if wheelhouse_dir is None or not str(wheelhouse_dir).strip():
        if key == SOURCE_AUTO:
            return WheelSource.pypi()
        raise ValueError("se eligió el almacén de ruedas y no hay ninguna carpeta configurada")
    return WheelSource.wheelhouse(Path(wheelhouse_dir))


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedPackage:
    """Un paquete del plan: lo que dice el lock (nombre, versión, licencia y las de lo que
    incluye su rueda, fichero, huella y bytes) y su ``origin``: la URL del lock (PyPI) o la
    ruta de la rueda en el almacén."""

    name: str
    version: str
    license: str
    bundled_licenses: tuple[str, ...]
    filename: str
    sha256: str
    size: int
    origin: str

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "version": self.version,
            "license": self.license,
            "bundled_licenses": list(self.bundled_licenses),
            "filename": self.filename,
            "sha256": self.sha256,
            "size": self.size,
            "origin": self.origin,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class InstallPlan:
    """Lo que se va a instalar y dónde, antes de hacer nada (RF-004-20; plan §5.3.1): el
    ``lock_id``, el origen, los paquetes, los bytes de las ruedas (``download_size``) y del
    motor instalado (``installed_size``, del lock), la carpeta de destino y ``digest``, el
    sha256 de su forma canónica (:func:`plan_digest`), que firma el consentimiento. Lo crea
    :meth:`ComputeEnvironment.plan_install`."""

    lock_id: str
    source: WheelSource
    packages: tuple[PlannedPackage, ...]
    download_size: int
    installed_size: int
    destination: Path
    digest: str

    @property
    def download_mb(self) -> float:
        """MB de las ruedas (lo que se descarga o se copia del almacén)."""
        return self.download_size / BYTES_PER_MB

    @property
    def disk_mb(self) -> float:
        """MB del motor instalado."""
        return self.installed_size / BYTES_PER_MB

    def to_json(self) -> dict[str, JsonValue]:
        """La forma JSON del plan, con su huella (la que guardará ``runtime.json``)."""
        return dict(_plan_payload(self), digest=self.digest)


def _plan_payload(plan: InstallPlan) -> dict[str, JsonValue]:
    folder = plan.source.folder
    return {
        "schema": PLAN_SCHEMA,
        "lock_id": plan.lock_id,
        "source": {"kind": plan.source.kind, "folder": None if folder is None else str(folder)},
        "packages": [package.to_json() for package in plan.packages],
        "download_size": plan.download_size,
        "installed_size": plan.installed_size,
        "destination": str(plan.destination),
    }


def plan_digest(plan: InstallPlan) -> str:
    """La huella del plan: sha256 (64 hexadecimales) de su forma canónica, JSON compacto con
    claves ordenadas de todo menos ``digest``. Cualquier cambio en lo que el usuario vio
    (origen, paquetes, licencias, tamaños, destino) la cambia."""
    text = json.dumps(_plan_payload(plan), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class Consent:
    """El consentimiento del usuario a un plan (RF-004-19; plan §5.3.1): quién
    (``user``), en qué equipo (``host``), cuándo (``given_at``, UTC ISO 8601) y la huella
    del plan que vio (``plan_digest``). :class:`ValueError` si falta algo."""

    user: str
    host: str
    given_at: str
    plan_digest: str

    def __post_init__(self) -> None:
        for name in ("user", "host"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"el consentimiento no dice su {name} ({value!r})")
        parse_utc(self.given_at)  # ValueError si no es UTC ISO 8601
        if not isinstance(self.plan_digest, str) or not _DIGEST.fullmatch(self.plan_digest):
            raise ValueError(
                f"la huella del plan {self.plan_digest!r} no tiene 64 hexadecimales"
            )

    @classmethod
    def given(
        cls,
        plan: InstallPlan,
        *,
        user: str | None = None,
        host: str | None = None,
        now: dt.datetime | None = None,
    ) -> Consent:
        """El consentimiento que el usuario da ahora (``now``, con zona) a ``plan``: sin
        ``user`` ni ``host``, los de esta sesión de Windows."""
        moment = dt.datetime.now(dt.UTC) if now is None else now
        return cls(
            user=user_name() if user is None else user,
            host=host_name() if host is None else host,
            given_at=format_utc(moment),
            plan_digest=plan.digest,
        )

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "user": self.user,
            "host": self.host,
            "given_at": self.given_at,
            "plan_digest": self.plan_digest,
        }


_DIGEST = re.compile(r"[0-9a-f]{64}")


def read_runtime_info(folder: Path) -> dict[str, Any] | None:
    """El ``runtime.json`` de la carpeta de un motor si es un objeto JSON en UTF-8 con el
    esquema :data:`RUNTIME_SCHEMA`; si falta o no se puede leer, ``None``."""
    try:
        data = json.loads((Path(folder) / RUNTIME_FILE).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != RUNTIME_SCHEMA:
        return None
    return data


class ComputeEnvironment:
    """El motor de cálculo del lock ``lock`` en los datos de usuario ``user_dir`` (ruta
    completa; la calcula ``bl/``): carpeta ``user_dir/runtime/<lock_id>/`` (plan §5.2.6).
    Cumple ``interpreter.ComputeRuntime`` (lo que necesita el lanzador). Crearlo no toca el
    disco ni la red; ninguno de sus métodos crea, descarga ni borra el motor (RF-004-19),
    salvo :meth:`adopt`, que solo convierte en el motor lo que instaló y verificó la cadena
    lanzada con el consentimiento del usuario (:class:`RuntimeSetup`), y los que anotan su
    verificación en ``runtime.json``."""

    def __init__(self, user_dir: Path, lock: RuntimeLock) -> None:
        if not isinstance(lock, RuntimeLock):
            raise TypeError(f"se esperaba un RuntimeLock, no {type(lock).__name__}")
        folder = Path(user_dir)
        if not folder.is_absolute():
            raise ValueError(
                f"la carpeta de datos de usuario «{folder}» no es una ruta completa"
            )
        self._user_dir = folder
        self._lock = lock
        self._lock_id = lock.lock_id

    @property
    def lock(self) -> RuntimeLock:
        """El lock de esta versión de Geoblender."""
        return self._lock

    @property
    def lock_id(self) -> str:
        return self._lock_id

    @property
    def user_dir(self) -> Path:
        return self._user_dir

    @property
    def runtime_dir(self) -> Path:
        """``<datos de usuario>/runtime``: la carpeta de todos los motores."""
        return self._user_dir / RUNTIME_DIR

    @property
    def path(self) -> Path:
        """``<datos de usuario>/runtime/<lock_id>``: la carpeta del motor de este lock."""
        return self.runtime_dir / self._lock_id

    def site_dir(self) -> Path:
        """La carpeta de los paquetes del motor (``--site`` de los workers ``compute``)."""
        return self.path / SITE_DIR

    @property
    def partial_path(self) -> Path:
        """``<datos de usuario>/runtime/<lock_id>.partial``: donde instala el trabajo
        ``runtime_install`` (en su ``site/``) antes de verificar y adoptar el motor. Nunca se
        usa para calcular (:meth:`status` no la mira)."""
        return partial_dir(self.runtime_dir, self._lock_id)

    @property
    def staged_site(self) -> Path:
        """``<datos de usuario>/runtime/<lock_id>.partial/site``: los paquetes recién
        instalados, que se verifican antes de adoptarlos (:meth:`adopt`)."""
        return self.partial_path / SITE_DIR

    def install_paths(self, plan: InstallPlan) -> dict[str, Path]:
        """Las rutas del trabajo ``runtime_install`` de ``plan``, que viajan en la línea de
        órdenes (``JobRunner.submit(..., paths=…)``) y no en la petición: la carpeta de los
        motores (:data:`PATH_RUNTIME`) y, con el almacén de ruedas, su carpeta
        (:data:`PATH_WHEELHOUSE`). :class:`ValueError` si el plan es de otro lock o de otra
        carpeta."""
        if not isinstance(plan, InstallPlan):
            raise TypeError(f"se esperaba un InstallPlan, no {type(plan).__name__}")
        if plan.lock_id != self._lock_id or plan.destination != self.path:
            raise ValueError("el plan de instalación es de otro motor o de otra carpeta")
        paths = {PATH_RUNTIME: self.runtime_dir}
        if plan.source.folder is not None:
            paths[PATH_WHEELHOUSE] = Path(plan.source.folder)
        return paths

    def __repr__(self) -> str:
        return f"ComputeEnvironment({str(self._user_dir)!r}, lock_id={self._lock_id!r})"

    def status(self) -> str:
        """El estado del motor (plan §5.2.6): :data:`STATUS_MISSING` si no existe su
        carpeta; :data:`STATUS_BROKEN` si existe pero su ``runtime.json`` no se lee, es de
        otro lock, su verificación no tiene ``ok`` verdadero o falta ``site/``;
        :data:`STATUS_READY` si no. Solo lee: no crea ni repara nada."""
        if not self.path.is_dir():
            return STATUS_MISSING
        info = read_runtime_info(self.path)
        if info is None or info.get("lock_id") != self._lock_id:
            return STATUS_BROKEN
        verification = info.get(VERIFICATION_KEY)
        if not isinstance(verification, dict) or verification.get("ok") is not True:
            return STATUS_BROKEN
        if not self.site_dir().is_dir():
            return STATUS_BROKEN
        return STATUS_READY

    def plan_install(self, source: WheelSource, *, online_access: bool) -> InstallPlan:
        """El plan de instalar el motor desde ``source`` (RF-004-20, RF-004-23,
        RF-004-24), sin usar la red ni escribir nada:

        - PyPI: con ``online_access`` falso (``bpy.app.online_access``),
          :class:`~.messages.JobError` ``network_not_allowed``, que explica las dos salidas;
          si no, el origen de cada paquete es la URL del lock.
        - Almacén de ruedas: el origen de cada paquete es su rueda en la carpeta, que tiene
          que estar (si no, o si la carpeta no se alcanza, ``wheel_not_found`` con el
          fichero y la carpeta); no necesita el acceso en línea. Su huella la comprueba la
          instalación.
        """
        if not isinstance(source, WheelSource):
            raise TypeError(f"se esperaba un WheelSource, no {type(source).__name__}")
        if not isinstance(online_access, bool):
            raise TypeError(f"online_access debe ser True o False, no {online_access!r}")
        packages = self._lock.packages
        if source.kind == SOURCE_PYPI:
            if not online_access:
                raise JobError("network_not_allowed")
            origins = [package.url for package in packages]
        else:
            folder = Path(source.folder)  # un almacén siempre tiene carpeta (WheelSource)
            origins = []
            for package in packages:
                wheel = folder / package.filename
                if not os.path.isfile(wheel):  # False también si no se alcanza la carpeta
                    raise JobError("wheel_not_found", file=package.filename, folder=folder)
                origins.append(str(wheel))
        plan = InstallPlan(
            lock_id=self._lock_id,
            source=source,
            packages=tuple(
                PlannedPackage(
                    name=package.name,
                    version=package.version,
                    license=package.license,
                    bundled_licenses=package.bundled_licenses,
                    filename=package.filename,
                    sha256=package.sha256,
                    size=package.size,
                    origin=origin,
                )
                for package, origin in zip(packages, origins, strict=True)
            ),
            download_size=self._lock.download_size,
            installed_size=self._lock.installed_size,
            destination=self.path,
            digest="",
        )
        return dataclasses.replace(plan, digest=plan_digest(plan))

    def install_request(
        self, plan: InstallPlan, consent: Consent, *, label: str | None = None
    ) -> JobRequest:
        """La petición del trabajo ``runtime_install`` que instala ``plan`` con el
        consentimiento ``consent`` (RF-004-19, RF-004-20; plan §5.4.7), con el nombre
        visible ``label`` (por defecto, el del tipo de trabajo en español). Lleva el
        ``lock_id``, el origen (``wheelhouse`` o ``pypi``), los paquetes del lock (nombre,
        versión, fichero, huella, bytes y URL), la huella del plan y el consentimiento; las
        rutas (el almacén y el destino) no: viajan en la línea de órdenes. El entorno y el
        tiempo máximo los pone el lanzador con los del tipo de trabajo.

        :class:`~.messages.JobError` ``request_invalid``, sin crear nada, si el plan es de
        otro lock o de otra carpeta, si cambió después de calcular su huella o si el
        consentimiento es de otro plan."""
        if not isinstance(plan, InstallPlan):
            raise TypeError(f"se esperaba un InstallPlan, no {type(plan).__name__}")
        if not isinstance(consent, Consent):
            raise TypeError(f"se esperaba un Consent, no {type(consent).__name__}")
        job = _install_label() if label is None else label
        if plan.lock_id != self._lock_id:
            raise _refused(job, f"el plan de instalación es del motor {plan.lock_id} y el "
                                f"de esta versión de Geoblender es {self._lock_id}")
        if plan.destination != self.path:
            raise _refused(job, "el plan de instalación es de otra carpeta de destino")
        if plan_digest(plan) != plan.digest:
            raise _refused(job, "el plan de instalación cambió después de enseñarlo")
        if consent.plan_digest != plan.digest:
            raise _refused(job, "el consentimiento es de otro plan de instalación")
        params: dict[str, JsonValue] = {
            "lock_id": self._lock_id,
            "source": plan.source.kind,
            "packages": [
                {
                    "name": package.name,
                    "version": package.version,
                    "filename": package.filename,
                    "sha256": package.sha256,
                    "size": package.size,
                    "url": package.url,
                }
                for package in self._lock.packages
            ],
            "plan_digest": plan.digest,
            "consent": consent.to_json(),
        }
        return new_request(INSTALL_WORKER, label=job, owner=INSTALL_OWNER, params=params)

    def verify_request(
        self, *, staged_site: Path | None = None, label: str | None = None
    ) -> JobRequest:
        """La petición del trabajo ``runtime_check`` que verifica el motor (RF-004-22): el
        recién instalado en ``staged_site`` (que solo puede ser :attr:`staged_site`; otra
        carpeta es :class:`ValueError`) o, sin ella, el instalado. Lleva el ``lock_id`` y el
        lock entero (contra él se comprueba), no la carpeta: esa viaja en la línea de
        órdenes (``--path site=…``) y es el ``site_override`` del lanzador, la única carpeta
        de paquetes del intérprete (:class:`RuntimeSetup` lo hace así)."""
        if staged_site is not None and Path(staged_site) != self.staged_site:
            raise ValueError(f"solo se verifica antes de adoptar la carpeta {self.staged_site}, "
                             f"no {staged_site}")
        params: dict[str, JsonValue] = {
            "lock_id": self._lock_id,
            "lock": self._lock.to_json(),
            "staged": staged_site is not None,
        }
        job = _worker_label(CHECK_WORKER) if label is None else label
        return new_request(CHECK_WORKER, label=job, owner=INSTALL_OWNER, params=params)

    def adopt(
        self,
        staged_site: Path,
        check: Mapping[str, Any],
        plan: InstallPlan,
        consent: Consent,
    ) -> None:
        """Convierte en el motor los paquetes de ``staged_site`` (:attr:`staged_site`)
        verificados por ``check`` (el resumen de ``runtime_check``) e instalados según
        ``plan`` con el consentimiento ``consent`` (RF-004-22; plan §5.4.7): escribe
        ``runtime.json`` en la carpeta parcial (lock, paquetes con su versión y su huella,
        origen, huella del plan, consentimiento, hora y la verificación, con la longitud
        máxima de ruta ya en la carpeta final) y la renombra con ``os.replace`` a
        :attr:`path`. Un motor anterior del mismo lock (roto, al repararlo) se aparta antes
        y se borra después.

        Solo se adopta una verificación que pasó: si ``check`` no pasó, es de otro lock o
        encontró otra versión de un paquete, si el plan es de otro motor o cambió, si el
        consentimiento es de otro plan o si ``staged_site`` es otra carpeta,
        :class:`ValueError` sin tocar nada. Un fallo del sistema al renombrar (un programa
        retiene el motor anterior) es :class:`OSError` y deja el motor anterior como
        estaba."""
        if not isinstance(plan, InstallPlan):
            raise TypeError(f"se esperaba un InstallPlan, no {type(plan).__name__}")
        if not isinstance(consent, Consent):
            raise TypeError(f"se esperaba un Consent, no {type(consent).__name__}")
        staged = Path(staged_site)
        if staged != self.staged_site:
            raise ValueError(f"solo se adopta la carpeta {self.staged_site}, no {staged}")
        problem = self._check_problem(check)
        if problem is not None:
            raise ValueError(f"no se adopta el motor de cálculo: {problem}")
        if (plan.lock_id != self._lock_id or plan.destination != self.path
                or plan_digest(plan) != plan.digest):
            raise ValueError("el plan de instalación es de otro motor o cambió después de "
                             "enseñarlo")
        if consent.plan_digest != plan.digest:
            raise ValueError("el consentimiento es de otro plan de instalación")
        if not staged.is_dir():
            raise FileNotFoundError(f"no está la instalación que se verificó ({staged})")
        folder = plan.source.folder
        info: dict[str, JsonValue] = {
            "schema": RUNTIME_SCHEMA,
            "lock_id": self._lock_id,
            "packages": [
                {"name": package.name, "version": package.version, "sha256": package.sha256}
                for package in self._lock.packages
            ],
            "source": {"kind": plan.source.kind,
                       "folder": None if folder is None else str(folder)},
            "plan_digest": plan.digest,
            "consent": consent.to_json(),
            "installed_at": format_utc(dt.datetime.now(dt.UTC)),
            VERIFICATION_KEY: _verification(check, self.site_dir()),
        }
        _write_json(self.partial_path / RUNTIME_FILE, info)
        self._take_partial()

    def record_check(self, check: Mapping[str, Any]) -> None:
        """Anota en ``runtime.json`` del motor instalado la verificación ``check`` (el resumen
        de un ``runtime_check`` que pasó), conservando lo demás. :class:`ValueError` si no
        pasó o si el motor no tiene un ``runtime.json`` de este lock (hay que repararlo)."""
        problem = self._check_problem(check)
        if problem is not None:
            raise ValueError(f"la verificación no se anota como correcta: {problem}")
        self._record(_verification(check, self.site_dir()))

    def record_failed_check(self, code: str, text: str) -> None:
        """Anota en ``runtime.json`` del motor instalado que su verificación falló ahora con
        el código ``code`` y el mensaje ``text``: el motor queda ``broken`` (RF-004-25)
        hasta repararlo. :class:`ValueError` si no tiene un ``runtime.json`` de este lock
        (ya está ``broken``)."""
        self._record({
            "ok": False,
            "checked_at": format_utc(dt.datetime.now(dt.UTC)),
            "code": code,
            "text": text,
        })

    def _check_problem(self, check: object) -> str | None:
        """Por qué ``check`` no es una verificación que pasó para este lock, o ``None``."""
        if not isinstance(check, Mapping):
            return "la verificación no tiene resumen"
        if check.get("ok") is not True:
            return "la verificación no pasó"
        if check.get("lock_id") != self._lock_id:
            return f"la verificación es del motor {check.get('lock_id')}, no del {self._lock_id}"
        found: dict[str, object] = {}
        for entry in check.get("packages") or ():
            if isinstance(entry, Mapping) and isinstance(entry.get("name"), str):
                found[normalize_name(entry["name"])] = entry.get("installed")
        for package in self._lock.packages:
            installed = found.get(package.key)
            if installed != package.version:
                return (f"la verificación encontró {package.name} {installed or NO_VERSION} y "
                        f"el lock exige {package.version}")
        if self._lock.package(LOCK_NUMPY) is not None and check.get("numpy_in_site") is not True:
            return "la verificación no cargó numpy desde el motor"
        return None

    def _record(self, verification: dict[str, JsonValue]) -> None:
        info = read_runtime_info(self.path)
        if info is None or info.get("lock_id") != self._lock_id:
            raise ValueError(f"el motor de cálculo de {self.path} no tiene un runtime.json de "
                             "este lock: hay que repararlo")
        info[VERIFICATION_KEY] = verification
        _write_json(self.path / RUNTIME_FILE, info)

    def _take_partial(self) -> None:
        """``os.replace(<lock_id>.partial → <lock_id>)``, apartando antes el motor que
        hubiera (``<lock_id>.old``, que se borra al final; si no se puede, nunca se usa)."""
        final, staged = self.path, self.partial_path
        aside: Path | None = None
        if final.exists():
            aside = final.with_name(final.name + OLD_SUFFIX)
            remove_tree(aside)
            _replace_retrying(final, aside)
        try:
            _replace_retrying(staged, final)
        except OSError:
            if aside is not None:
                try:
                    os.replace(aside, final)
                except OSError:
                    LOGGER.exception("No se pudo devolver a su sitio el motor de cálculo "
                                     "anterior (%s)", aside)
            raise
        if aside is not None and not remove_tree(aside):
            LOGGER.warning("No se pudo borrar el motor de cálculo anterior %s; no se usa",
                           aside)


def _worker_label(name: str) -> str:
    """El nombre visible del tipo de trabajo ``name`` de la 004, en español."""
    info = next(info for info in catalog.BUILTIN_WORKERS if info.name == name)
    return catalog.CATALOG_ES.get(info.label_msgid, info.label_msgid)


def _install_label() -> str:
    """El nombre visible del tipo de trabajo ``runtime_install``, en español."""
    return _worker_label(INSTALL_WORKER)


def _refused(job: str, detail: str) -> JobError:
    return JobError("request_invalid", job=job,
                    detail=f"{detail} (vuelva a pedir la instalación)")


# --- La instalación: ruedas con huella y pip en la carpeta parcial (T27) --------------------

PATH_RUNTIME = "runtime"
"""Nombre de la ruta de la línea de órdenes (``--path runtime=…``) con la carpeta de los
motores, ``<datos de usuario>/runtime``."""
PATH_WHEELHOUSE = "wheelhouse"
"""Nombre de la ruta de la línea de órdenes con la carpeta del almacén de ruedas."""
WHEELS_DIR = "wheels"
"""Carpeta de ``out/`` del trabajo de instalación con las ruedas ya comprobadas (se borra al
acabar)."""
REQUIREMENTS_FILE = "requirements.txt"
INSTALLING_TEXT = "Instalando los paquetes del motor de cálculo"
"""Mensaje del avance mientras se instalan los paquetes (después de comprobar las ruedas)."""
FETCH_BLOCK_BYTES = 1 << 20
DOWNLOAD_TIMEOUT_S = 60.0
"""Lo que se espera a que responda el servidor de una rueda antes de dar la descarga por
fallida (``network_error``)."""
DOWNLOAD_SCHEMES: tuple[str, ...] = ("https", "file")
"""De dónde se descarga una rueda: PyPI (``https``) o un fichero (``file``, las pruebas)."""
INSTALL_POLL_S = 0.05
"""Cada cuánto se mira la cancelación mientras instala ``pip``."""
INSTALL_KILL_WAIT_S = 5.0
"""Lo que se espera a que termine ``pip`` después de matarlo."""
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LOCK_ID = re.compile(rf"[0-9a-f]{{{LOCK_ID_LENGTH}}}")
_WHEEL_KEYS = frozenset({"name", "version", "filename", "sha256", "size", "url"})

_INSTALL_CATALOG: tuple[Message, ...] = (
    Message(
        "runtime_install_failed",
        "The compute engine could not be installed: the installer ended with code "
        "{exit_code}. Details in its log.",
        "No se pudo instalar el motor de cálculo: el instalador terminó con el código "
        "{exit_code}. Detalles en su registro.",
    ),
    Message(
        "runtime_partial_busy",
        "The half-finished installation in {path} could not be deleted: close the programs "
        "that use it and try again.",
        "No se pudo borrar la instalación a medias de {path}: cierre los programas que la "
        "usen y vuelva a intentarlo.",
    ),
    Message(
        "runtime_adopt_failed",
        "The verified compute engine could not be put in place in {path}: {detail}. Close "
        "the calculations that use it and try again.",
        "No se pudo dejar listo el motor de cálculo verificado en {path}: {detail}. Cierre "
        "los cálculos que lo usen y vuelva a intentarlo.",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in _INSTALL_CATALOG})
"""Los errores propios de la instalación del motor, por código (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType({m.msgid: m.es for m in _INSTALL_CATALOG})
"""``msgid`` → texto en español, para ``core.i18n.install`` (solo lectura)."""


def install_failure(code: str, **values: JsonValue) -> JobFailed:
    """El fallo propio de la instalación ``code`` (:data:`MESSAGES`) con sus valores."""
    message = MESSAGES[code]
    return JobFailed(code, msgid=message.msgid, text=message.es.format(**values),
                     values=values)


class WheelRef(Protocol):
    """Lo que se necesita de un paquete para traer su rueda: nombre, versión, fichero, huella,
    bytes y URL (:class:`LockedPackage` o :class:`RequestedWheel`)."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def filename(self) -> str: ...

    @property
    def sha256(self) -> str: ...

    @property
    def size(self) -> int: ...

    @property
    def url(self) -> str: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestedWheel:
    """Un paquete de la petición ``runtime_install`` (los del lock que el usuario consintió):
    nombre, versión, fichero de la rueda, huella sha256 (minúsculas), bytes y URL."""

    name: str
    version: str
    filename: str
    sha256: str
    size: int
    url: str


@dataclass(frozen=True, slots=True, kw_only=True)
class InstallTask:
    """Lo que tiene que hacer el trabajo ``runtime_install`` (:func:`install_task`): el
    ``lock_id``, el origen de las ruedas, los paquetes y la carpeta de los motores
    ``runtime_dir`` (ruta completa, de la línea de órdenes)."""

    lock_id: str
    source: WheelSource
    packages: tuple[RequestedWheel, ...]
    runtime_dir: Path

    @property
    def partial_path(self) -> Path:
        """``<runtime>/<lock_id>.partial``: la carpeta de la instalación a medias."""
        return partial_dir(self.runtime_dir, self.lock_id)

    @property
    def site_dir(self) -> Path:
        """``<runtime>/<lock_id>.partial/site``: el destino de ``pip --target``."""
        return self.partial_path / SITE_DIR


def partial_dir(runtime_dir: Path, lock_id: str) -> Path:
    """La carpeta ``<runtime_dir>/<lock_id>.partial`` de una instalación sin adoptar."""
    return Path(runtime_dir) / f"{lock_id}{PARTIAL_SUFFIX}"


def install_task(
    params: Mapping[str, Any], paths: Mapping[str, Path], *, job: str
) -> InstallTask:
    """Lo que pide el trabajo ``runtime_install`` ``job``: sus parámetros (los de
    :meth:`ComputeEnvironment.install_request`) y sus rutas de la línea de órdenes
    (:data:`PATH_RUNTIME` y, con el almacén, :data:`PATH_WHEELHOUSE`, rutas completas). Sin
    un consentimiento con la huella del plan, o con algo que no vale,
    :class:`~.messages.JobError` ``request_invalid``: no se instala nada."""

    def invalid(detail: str) -> JobError:
        return JobError("request_invalid", job=job, detail=detail)

    lock_id = params.get("lock_id")
    if not isinstance(lock_id, str) or not _LOCK_ID.fullmatch(lock_id):
        raise invalid(f"el lock_id {lock_id!r} no tiene {LOCK_ID_LENGTH} hexadecimales")
    digest = params.get("plan_digest")
    consent = params.get("consent")
    if (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
            or not isinstance(consent, Mapping) or consent.get("plan_digest") != digest):
        raise invalid("falta el consentimiento del usuario al plan de instalación")
    kind = params.get("source")
    if kind not in SOURCE_KINDS:
        raise invalid(f"el origen {kind!r} no es uno de {', '.join(SOURCE_KINDS)}")
    entries = params.get("packages")
    if not isinstance(entries, list) or not entries:
        raise invalid("no hay paquetes que instalar")
    packages = tuple(_requested_wheel(entry, invalid) for entry in entries)

    def folder(name: str) -> Path:
        value = paths.get(name)
        if value is None or not Path(value).is_absolute():
            raise invalid(f"falta la ruta completa «{name}» en la línea de órdenes (--path)")
        return Path(value)

    source = (WheelSource.pypi() if kind == SOURCE_PYPI
              else WheelSource.wheelhouse(folder(PATH_WHEELHOUSE)))
    return InstallTask(lock_id=lock_id, source=source, packages=packages,
                       runtime_dir=folder(PATH_RUNTIME))


def _requested_wheel(entry: object, invalid: Callable[[str], JobError]) -> RequestedWheel:
    if not isinstance(entry, Mapping) or set(entry) != _WHEEL_KEYS:
        raise invalid(f"un paquete no tiene exactamente {', '.join(sorted(_WHEEL_KEYS))}")
    texts = {key: entry[key] for key in ("name", "version", "filename", "sha256", "url")}
    if not all(isinstance(value, str) and value.strip() for value in texts.values()):
        raise invalid(f"un paquete tiene un texto vacío: {texts}")
    filename = texts["filename"]
    if not filename.endswith(".whl") or any(c in filename for c in "/\\:"):
        raise invalid(f"«{filename}» no es el nombre de un fichero «.whl»")
    if not _SHA256.fullmatch(texts["sha256"]):
        raise invalid(f"la huella de {filename} no tiene 64 hexadecimales")
    size = entry["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise invalid(f"el tamaño de {filename} no es un número entero de bytes")
    return RequestedWheel(name=texts["name"], version=texts["version"], filename=filename,
                          sha256=texts["sha256"].lower(), size=size, url=texts["url"])


def remove_tree(path: Path) -> bool:
    """Borra ``path`` (carpeta o fichero; lo de solo lectura también), reintentando si otro
    programa retiene algo un momento. Dice si ya no está."""
    return _remove_retrying(Path(path))


def fetch_wheel(
    pkg: WheelRef,
    source: WheelSource,
    dest_dir: Path,
    *,
    progress: Callable[[int], object] | None = None,
    cancelled: Callable[[], object] | None = None,
) -> Path:
    """Trae la rueda de ``pkg`` a ``dest_dir`` (que crea) y devuelve su ruta
    (RF-004-21, RF-004-24; plan §5.4.7): del almacén de ``source``, una copia; de PyPI, la
    descarga de ``pkg.url`` (``https``; ``file`` en las pruebas) con ``urllib``. La lee por
    bloques en ``<fichero>.partial`` calculando su sha256 y la deja con su nombre solo si
    coincide con la del lock.

    - Otra huella, o más bytes de los del lock: :class:`~.messages.JobError`
      ``wheel_hash_mismatch`` con el fichero.
    - Sin la rueda en el almacén (o el almacén inalcanzable): ``wheel_not_found`` con el
      fichero y la carpeta. Una descarga que falla o una URL que no es ``https`` ni
      ``file``: ``network_error`` con el paquete.
    - ``progress(bytes leídos)`` tras cada bloque; ``cancelled()`` antes de cada bloque:
      si devuelve verdadero, :class:`~.worker_api.JobCancelled` (o la que lance, como
      ``WorkerContext.check_cancelled``).

    Si algo falla, o se cancela, no queda nada de esta rueda en ``dest_dir``."""
    if not isinstance(source, WheelSource):
        raise TypeError(f"se esperaba un WheelSource, no {type(source).__name__}")
    folder = Path(dest_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / pkg.filename
    temporary = target.with_name(target.name + PARTIAL_SUFFIX)
    target.unlink(missing_ok=True)
    expected = pkg.sha256.lower()
    try:
        _check_cancelled(cancelled)
        digest = hashlib.sha256()
        done = 0
        with _open_wheel(pkg, source) as stream, temporary.open("wb") as out:
            while True:
                _check_cancelled(cancelled)
                block = _read_block(stream, pkg, source)
                if not block:
                    break
                done += len(block)
                if done > pkg.size:
                    raise JobError("wheel_hash_mismatch", file=pkg.filename)
                digest.update(block)
                out.write(block)
                if progress is not None:
                    progress(done)
        if digest.hexdigest() != expected:
            raise JobError("wheel_hash_mismatch", file=pkg.filename)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _open_wheel(pkg: WheelRef, source: WheelSource) -> IO[bytes]:
    if source.kind == SOURCE_WHEELHOUSE:
        folder = Path(source.folder)  # un almacén siempre tiene carpeta (WheelSource)
        try:
            return (folder / pkg.filename).open("rb")
        except OSError:
            raise JobError("wheel_not_found", file=pkg.filename, folder=folder) from None
    scheme = urllib.parse.urlsplit(pkg.url).scheme.lower()
    if scheme not in DOWNLOAD_SCHEMES:
        raise JobError("network_error", package=pkg.name,
                       detail=f"la dirección {pkg.url} no es https")
    try:
        return urllib.request.urlopen(pkg.url, timeout=DOWNLOAD_TIMEOUT_S)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise JobError("network_error", package=pkg.name, detail=_reason(exc)) from None


def _read_block(stream: IO[bytes], pkg: WheelRef, source: WheelSource) -> bytes:
    try:
        return stream.read(FETCH_BLOCK_BYTES)
    except (OSError, http.client.HTTPException) as exc:
        if source.kind == SOURCE_WHEELHOUSE:
            raise JobError("wheel_not_found", file=pkg.filename,
                           folder=source.folder) from None
        raise JobError("network_error", package=pkg.name, detail=_reason(exc)) from None


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    text = str(reason if reason is not None else exc).strip()
    return text or type(exc).__name__


def _check_cancelled(cancelled: Callable[[], object] | None) -> None:
    """:class:`~.worker_api.JobCancelled` si ``cancelled()`` dice que hay que parar (también
    sale la que lance la propia función)."""
    if cancelled is not None and cancelled():
        raise JobCancelled(CANCELLED_TEXT)


def write_requirements(packages: Iterable[WheelRef], path: Path) -> Path:
    """Escribe en ``path`` (UTF-8, «\\n») el ``requirements.txt`` de ``packages``: una línea
    ``<nombre>==<versión> --hash=sha256:<huella>`` por paquete (``pip --require-hashes``).
    Crea su carpeta y devuelve la ruta. Sin paquetes, :class:`ValueError`."""
    lines = [f"{p.name}=={p.version} --hash=sha256:{p.sha256.lower()}\n" for p in packages]
    if not lines:
        raise ValueError("no hay paquetes para requirements.txt")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes("".join(lines).encode("utf-8"))
    return target


def pip_install_command(
    python: Path, wheels_dir: Path, requirements: Path, target: Path
) -> list[str]:
    """La orden de ``pip`` que instala el motor (plan §5.4.7)::

        <python> -I -B -m pip --isolated install --no-index --find-links <ruedas>
            --require-hashes --no-deps --only-binary=:all: --target <destino> --no-cache-dir
            --disable-pip-version-check --no-input --progress-bar off -r <requirements.txt>

    ``-I``: sin variables ``PYTHON*`` ni el ``site-packages`` del usuario; ``--isolated``:
    ``pip`` no lee sus variables ``PIP_*`` ni la configuración del usuario; ``--no-index`` y
    ``--find-links``: solo las ruedas ya comprobadas, sin red; ``--no-cache-dir``: ninguna
    caché."""
    return [
        str(python), "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index",
        "--find-links", str(wheels_dir), "--require-hashes", "--no-deps",
        "--only-binary=:all:", "--target", str(target), "--no-cache-dir",
        "--disable-pip-version-check", "--no-input", "--progress-bar", "off",
        "-r", str(requirements),
    ]


def run_pip_install(
    python: Path,
    wheels_dir: Path,
    requirements: Path,
    target: Path,
    *,
    cancelled: Callable[[], object] | None = None,
    log: IO[Any] | int | None = None,
) -> None:
    """Instala con ``pip`` (:func:`pip_install_command`, el ``pip`` de ``python``) los
    paquetes de ``requirements`` desde ``wheels_dir`` en ``target`` y espera a que acabe,
    mirando ``cancelled()`` cada :data:`INSTALL_POLL_S` s (como en :func:`fetch_wheel`): si
    hay que parar, mata ``pip`` y lanza :class:`~.worker_api.JobCancelled`. Su salida va a
    ``log`` (un fichero o un descriptor; sin él, la de este proceso: en el worker,
    ``job.log``). Hereda el entorno de este proceso; con ``--isolated`` da igual que traiga
    variables ``PIP_*``.

    Si ``pip`` no arranca, :class:`~.messages.JobError` ``interpreter_not_found`` o
    ``interpreter_failed``; si termina con un código distinto de 0,
    :class:`~.worker_api.JobFailed` ``runtime_install_failed`` (:data:`MESSAGES`)."""
    command = pip_install_command(python, wheels_dir, requirements, target)
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=log,
            stderr=None if log is None else subprocess.STDOUT,
            creationflags=_CREATE_NO_WINDOW,
        )
    except OSError as exc:
        code = ("interpreter_not_found" if isinstance(exc, FileNotFoundError)
                else "interpreter_failed")
        raise JobError(code, path=str(python), detail=exc.strerror or str(exc)) from None
    try:
        while True:
            try:
                exit_code = process.wait(timeout=INSTALL_POLL_S)
            except subprocess.TimeoutExpired:
                _check_cancelled(cancelled)
            else:
                break
    except BaseException:
        _stop(process)
        raise
    if exit_code != 0:
        raise install_failure("runtime_install_failed", exit_code=exit_code)


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Mata ``process`` y espera a que termine (sus ficheros quedan libres)."""
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=INSTALL_KILL_WAIT_S)
    except subprocess.TimeoutExpired:
        pass


# --- La verificación y la adopción (T28) -----------------------------------------------------

CHECK_WORKER = "runtime_check"
PATH_SITE = "site"
"""Nombre de la ruta de la línea de órdenes (``--path site=…``) con la carpeta ``site`` que
verifica ``runtime_check`` (la misma que el ``site_override`` de su intérprete)."""
LOCK_NUMPY = "numpy"
MATMUL_N = 2000
MATMUL_REPEATS = 3
"""El producto float64 ``MATMUL_N × MATMUL_N`` de la verificación: el mejor de
``MATMUL_REPEATS`` (RF-004-22)."""
UNOPTIMIZED_BLAS = "auto"
"""La BLAS de un numpy sin BLAS optimizada (el de Blender): el motor no la puede tener."""
NO_VERSION = "ninguna"
"""La versión que consta de un paquete del lock que no está en el motor."""
OLD_SUFFIX = ".old"
"""Sufijo con que se aparta un motor anterior del mismo lock mientras se adopta el nuevo."""
CHECKED_TEXT = "Motor de cálculo verificado"

STEP_INSTALL = "install"
STEP_CHECK = "check"
SETUP_INSTALL = "install"
SETUP_VERIFY = "verify"
SETUP_RUNNING = "running"
SETUP_SUCCEEDED = "succeeded"
SETUP_FAILED = "failed"
SETUP_CANCELLED = "cancelled"
_VERIFICATION_KEYS: tuple[str, ...] = (
    "checked_at", "python", "numpy", "numpy_in_site", "blas", "matmul_n", "matmul_repeats",
    "matmul_s",
)


def _verification(check: Mapping[str, Any], site_dir: Path) -> dict[str, JsonValue]:
    """Lo que ``runtime.json`` guarda de una verificación que pasó, con la longitud máxima de
    ruta bajo ``site_dir`` (la carpeta final, RNF-004-08)."""
    record: dict[str, JsonValue] = {"ok": True}
    for key in _VERIFICATION_KEYS:
        record[key] = plain_json(check.get(key), key)
    longest = check.get("longest_relative")
    site_length = len(str(site_dir))
    record["max_path_length"] = (site_length + 1 + longest
                                 if isinstance(longest, int) and longest > 0 else site_length)
    return record


def _write_json(path: Path, data: Mapping[str, JsonValue]) -> None:
    """Escribe ``data`` en ``path`` (UTF-8, sangrado) a través de ``<path>.partial``."""
    temporary = path.with_name(path.name + PARTIAL_SUFFIX)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    try:
        temporary.write_bytes(text.encode("utf-8"))
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _replace_retrying(source: Path, target: Path) -> None:
    """``os.replace(source, target)``, reintentando si otro programa (un antivirus que mira lo
    recién instalado) retiene algo un momento."""
    for attempt in range(REMOVE_RETRIES + 1):
        try:
            os.replace(source, target)
            return
        except FileNotFoundError:
            raise
        except OSError:
            if attempt == REMOVE_RETRIES:
                raise
            _pause()


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckTask:
    """Lo que tiene que hacer el trabajo ``runtime_check`` (:func:`check_task`): el lock contra
    el que se verifica, la carpeta ``site`` (ruta completa, de la línea de órdenes) y si es
    una instalación sin adoptar (``staged``)."""

    lock: RuntimeLock
    site_dir: Path
    staged: bool


def check_task(params: Mapping[str, Any], paths: Mapping[str, Path], *, job: str) -> CheckTask:
    """Lo que pide el trabajo ``runtime_check`` ``job``: sus parámetros (los de
    :meth:`ComputeEnvironment.verify_request`) y la carpeta :data:`PATH_SITE` de la línea de
    órdenes. Un lock que no se lee o que no es el del ``lock_id``, o sin carpeta,
    :class:`~.messages.JobError` ``request_invalid``."""

    def invalid(detail: str) -> JobError:
        return JobError("request_invalid", job=job, detail=detail)

    lock_id = params.get("lock_id")
    if not isinstance(lock_id, str) or not _LOCK_ID.fullmatch(lock_id):
        raise invalid(f"el lock_id {lock_id!r} no tiene {LOCK_ID_LENGTH} hexadecimales")
    data = params.get("lock")
    try:
        lock = parse_lock(plain_json(data, "lock") if isinstance(data, Mapping) else data)
    except (LockError, ValueError) as exc:
        raise invalid(f"el lock de la petición no vale: {exc}") from None
    if lock.lock_id != lock_id:
        raise invalid(f"el lock de la petición es el {lock.lock_id}, no el {lock_id}")
    staged = params.get("staged")
    if not isinstance(staged, bool):
        raise invalid(f"staged = {staged!r} no es verdadero ni falso")
    site = paths.get(PATH_SITE)
    if site is None or not Path(site).is_absolute():
        raise invalid(f"falta la ruta completa «{PATH_SITE}» en la línea de órdenes (--path)")
    return CheckTask(lock=lock, site_dir=Path(site), staged=staged)


def installed_versions(site_dir: Path) -> dict[str, tuple[str, ...]]:
    """Las versiones de los paquetes instalados en ``site_dir`` según sus ``*.dist-info``
    (``importlib.metadata``, sin importarlos), por nombre normalizado (PEP 503); dos
    ``*.dist-info`` del mismo paquete dan dos versiones."""
    found: dict[str, set[str]] = {}
    for dist in importlib.metadata.distributions(path=[str(site_dir)]):
        try:
            metadata = dist.metadata
        except (OSError, TypeError, ValueError):  # un *.dist-info sin METADATA legible
            continue
        name = metadata.get("Name") if metadata is not None else None
        if not name:
            continue
        version = metadata.get("Version") or NO_VERSION
        found.setdefault(normalize_name(name), set()).add(str(version))
    return {key: tuple(sorted(versions)) for key, versions in found.items()}


def probe_environment(
    lock: RuntimeLock,
    site_dir: Path,
    *,
    progress: Callable[[float, str], object] | None = None,
    matmul_n: int = MATMUL_N,
    repeats: int = MATMUL_REPEATS,
) -> dict[str, JsonValue]:
    """Verifica el motor de ``site_dir`` contra ``lock`` (RF-004-22; plan §5.4.7) **dentro
    del worker** ``runtime_check``, cuyo intérprete solo tiene esa carpeta de paquetes:

    - la versión de cada paquete del lock en sus ``*.dist-info`` (:func:`installed_versions`;
      si falta o es otra, ``runtime_package_mismatch``);
    - que numpy se importa y se carga desde ``site_dir`` (si no, ``runtime_missing`` o
      ``runtime_numpy_wrong``) y que su BLAS no es :data:`UNOPTIMIZED_BLAS`
      (``runtime_blas_missing``);
    - con eso bien, los s del producto float64 ``matmul_n × matmul_n``, el mejor de
      ``repeats`` (sin BLAS optimizada se omite: tardaría minutos);
    - la longitud máxima de ruta bajo ``site_dir`` (RNF-004-08; ``longest_relative``, sin
      la carpeta, para medirla también en la carpeta final).

    Devuelve el resumen JSON (``ok`` y ``problems``, cada uno ``{code, values}`` en el orden
    anterior; :func:`check_errors`). ``progress(frac, mensaje)`` avisa del avance (en el
    worker, ``WorkerContext.progress``, que también para si se cancela)."""
    site = Path(site_dir)
    report = progress if progress is not None else _no_progress
    report(0.0, "Comprobando las versiones de los paquetes del motor")
    installed = installed_versions(site)
    problems: list[dict[str, JsonValue]] = []
    packages: list[JsonValue] = []
    for package in lock.packages:
        versions = installed.get(package.key, ())
        shown = ", ".join(versions) if versions else None
        packages.append({"name": package.name, "locked": package.version, "installed": shown})
        if versions != (package.version,):
            problems.append(_problem("runtime_package_mismatch", package=package.name,
                                     actual=shown or NO_VERSION, locked=package.version))
    report(0.1, "Comprobando numpy y su BLAS")
    numpy_version: str | None = None
    blas: str | None = None
    in_site = False
    matmul_s: float | None = None
    try:
        import numpy as np  # el del motor: el intérprete del worker no tiene otro
    except ImportError:
        problems.append(_problem("runtime_missing"))
    else:
        where = getattr(np, "__file__", None)
        in_site = bool(where) and _inside(str(where), site)
        numpy_version = str(getattr(np, "__version__", "") or "") or None
        blas = blas_name(np)
        if not in_site:
            folder = os.path.dirname(os.path.realpath(where)) if where else "?"
            problems.append(_problem("runtime_numpy_wrong", path=folder))
        elif blas == UNOPTIMIZED_BLAS:
            problems.append(_problem("runtime_blas_missing", blas=blas))
        else:
            matmul_s = _matmul_seconds(np, matmul_n, repeats, report)
    report(0.9, "Midiendo las rutas del motor")
    longest = _longest_relative(site)
    return {
        "lock_id": lock.lock_id,
        "ok": not problems,
        "checked_at": format_utc(dt.datetime.now(dt.UTC)),
        "python": platform.python_version(),
        "packages": packages,
        "numpy": numpy_version,
        "numpy_in_site": in_site,
        "blas": blas,
        "matmul_n": matmul_n,
        "matmul_repeats": repeats,
        "matmul_s": matmul_s,
        "longest_relative": longest,
        "max_path_length": len(str(site)) + 1 + longest if longest else len(str(site)),
        "problems": problems,
    }


def check_errors(check: Mapping[str, Any]) -> list[JobError]:
    """Los problemas de una verificación (:func:`probe_environment`), como los
    :class:`~.messages.JobError` del §8, por orden."""
    errors = []
    for problem in check.get("problems") or ():
        values = problem.get("values") or {}
        errors.append(JobError(problem["code"], **values))
    return errors


def check_text(check: Mapping[str, Any]) -> str:
    """Una línea con lo que midió la verificación (para ``job.log``): «numpy 2.5.3 · BLAS
    scipy-openblas · 2000 × 2000 en 0,041 s · ruta más larga: 180 caracteres»."""
    seconds = check.get("matmul_s")
    n = check.get("matmul_n")
    product = (f"{n} × {n} en {seconds:.3f} s".replace(".", ",")
               if isinstance(seconds, float) else f"{n} × {n} sin medir")
    return (f"numpy {check.get('numpy') or NO_VERSION} · BLAS {check.get('blas') or '?'} · "
            f"{product} · ruta más larga: {check.get('max_path_length')} caracteres")


def _no_progress(frac: float, message: str) -> None:
    return None


def _problem(code: str, **values: JsonValue) -> dict[str, JsonValue]:
    return {"code": code, "values": dict(values)}


def _inside(path: str, folder: Path) -> bool:
    """Si ``path`` está dentro de ``folder`` (rutas reales, sin distinguir mayúsculas)."""
    real = os.path.normcase(os.path.realpath(path))
    root = os.path.normcase(os.path.realpath(folder))
    try:
        return os.path.commonpath([real, root]) == root
    except ValueError:  # otra unidad
        return False


def _matmul_seconds(np: Any, n: int, repeats: int,
                    report: Callable[[float, str], object]) -> float:
    """Los s del mejor de ``repeats`` productos float64 ``n × n`` con el numpy ``np``."""
    matrix = np.ones((n, n), dtype=np.float64)
    best = math.inf
    for repeat in range(1, repeats + 1):
        report(0.1 + 0.8 * (repeat - 1) / repeats, f"Producto {n} × {n}: {repeat} de {repeats}")
        start = time.perf_counter()
        _product = matrix @ matrix
        best = min(best, time.perf_counter() - start)
    return max(best, 0.0)


def _longest_relative(site: Path) -> int:
    """Caracteres de la ruta más larga bajo ``site``, sin ``site`` ni el separador."""
    base = len(str(site)) + 1
    longest = 0
    for root, folders, files in os.walk(site):
        for name in (*folders, *files):
            longest = max(longest, len(os.path.join(root, name)) - base)
    return longest


class _Launcher(Protocol):
    """Lo que :class:`RuntimeSetup` necesita del lanzador (``runner.JobRunner``)."""

    @property
    def runtime(self) -> object: ...

    def submit(
        self,
        job: JobRequest,
        *,
        on_finish: Callable[[Any], object] | None = None,
        paths: Mapping[str, Path] | None = None,
        site_override: Path | None = None,
    ) -> Any: ...


class RuntimeSetup:
    """La cadena del motor de cálculo en el lanzador (plan §5.4.7; RF-004-21, RF-004-22,
    RF-004-25). Se crea con :meth:`install` o :meth:`verify` y avanza sola en los
    ``on_finish`` de sus trabajos (desde ``JobRunner.poll``):

    - ``install``: ``runtime_install`` en ``<lock_id>.partial/site`` → ``runtime_check`` de
      esa carpeta (``site_override``) → :meth:`ComputeEnvironment.adopt`. Si un paso no
      termina bien (o se cancela), borra la carpeta parcial: no queda ningún motor a medias.
    - ``verify``: ``runtime_check`` del motor instalado; el resultado se anota en su
      ``runtime.json``: si falla (o se agota su tiempo), el motor queda ``broken``.

    ``state``: ``running``, ``succeeded``, ``failed`` o ``cancelled``; ``step``: el trabajo
    en curso (``install`` o ``check``; ``None`` al acabar); ``check``: el resumen de la
    verificación si pasó; ``error_code`` y ``error_text``: el motivo si no (el del trabajo
    que falló, o ``runtime_adopt_failed``). ``on_done(setup)`` se llama una vez, al acabar."""

    def __init__(
        self,
        kind: str,
        runner: _Launcher,
        env: ComputeEnvironment,
        *,
        plan: InstallPlan | None = None,
        consent: Consent | None = None,
        on_done: Callable[[RuntimeSetup], object] | None = None,
    ) -> None:
        if kind not in (SETUP_INSTALL, SETUP_VERIFY):
            raise ValueError(f"la cadena {kind!r} no es «{SETUP_INSTALL}» ni «{SETUP_VERIFY}»")
        if not isinstance(env, ComputeEnvironment):
            raise TypeError(f"se esperaba un ComputeEnvironment, no {type(env).__name__}")
        if getattr(runner, "runtime", None) is not env:
            raise ValueError("el lanzador tiene que usar este motor de cálculo (runtime=…): "
                             "con él resuelve el intérprete de la verificación")
        self._kind = kind
        self._runner = runner
        self._env = env
        self._plan = plan
        self._consent = consent
        self._on_done = on_done
        self._state = SETUP_RUNNING
        self._step: str | None = None
        self._handles: list[Any] = []
        self.check: Mapping[str, JsonValue] | None = None
        self.error_code: str | None = None
        self.error_text: str | None = None

    @classmethod
    def install(
        cls,
        runner: _Launcher,
        env: ComputeEnvironment,
        plan: InstallPlan,
        consent: Consent,
        *,
        on_done: Callable[[RuntimeSetup], object] | None = None,
    ) -> RuntimeSetup:
        """Lanza la instalación de ``plan`` con ``consent`` en ``runner``, cuyo motor es
        ``env``: instalar → verificar → adoptar. Una petición que no vale
        (:meth:`ComputeEnvironment.install_request`) es :class:`~.messages.JobError`, y un
        lanzador ya cerrado, :class:`RuntimeError`, sin lanzar nada."""
        setup = cls(SETUP_INSTALL, runner, env, plan=plan, consent=consent, on_done=on_done)
        request = env.install_request(plan, consent)
        setup._submit(request, STEP_INSTALL, paths=env.install_paths(plan),
                      on_finish=setup._installed)
        return setup

    @classmethod
    def verify(
        cls,
        runner: _Launcher,
        env: ComputeEnvironment,
        *,
        on_done: Callable[[RuntimeSetup], object] | None = None,
    ) -> RuntimeSetup:
        """Lanza la verificación del motor instalado ``env`` (RF-004-22). Sin motor instalado
        (sin su carpeta, sin ``site/`` o sin un ``runtime.json`` de este lock: una carpeta
        ``.partial`` no cuenta), :class:`~.messages.JobError` ``runtime_missing`` sin lanzar
        nada: hay que instalarlo o repararlo."""
        info = read_runtime_info(env.path) if env.path.is_dir() else None
        if info is None or info.get("lock_id") != env.lock_id or not env.site_dir().is_dir():
            raise JobError("runtime_missing")
        setup = cls(SETUP_VERIFY, runner, env, on_done=on_done)
        setup._submit_check()
        return setup

    @property
    def kind(self) -> str:
        """``install`` o ``verify``."""
        return self._kind

    @property
    def state(self) -> str:
        return self._state

    @property
    def step(self) -> str | None:
        return self._step

    @property
    def done(self) -> bool:
        return self._state != SETUP_RUNNING

    @property
    def handles(self) -> tuple[Any, ...]:
        """Los ``JobHandle`` de sus trabajos, por orden."""
        return tuple(self._handles)

    @property
    def job_uids(self) -> tuple[str, ...]:
        return tuple(handle.job_uid for handle in self._handles)

    def cancel(self) -> bool:
        """Pide parar el trabajo en curso; dice si la petición tuvo efecto. La cadena acaba
        «cancelada» sin adoptar nada."""
        if self.done or not self._handles:
            return False
        return bool(self._handles[-1].cancel())

    def __repr__(self) -> str:
        return (f"RuntimeSetup({self._kind!r}, {self._env.lock_id!r}, state={self._state!r}, "
                f"step={self._step!r})")

    def _submit(self, request: JobRequest, step: str, *, on_finish: Callable[[Any], object],
                paths: Mapping[str, Path], site_override: Path | None = None) -> None:
        handle = self._runner.submit(request, on_finish=on_finish, paths=paths,
                                     site_override=site_override)
        self._step = step
        self._handles.append(handle)

    def _submit_check(self) -> None:
        staged = self._kind == SETUP_INSTALL
        site = self._env.staged_site if staged else self._env.site_dir()
        request = self._env.verify_request(staged_site=site if staged else None)
        self._submit(request, STEP_CHECK, paths={PATH_SITE: site}, site_override=site,
                     on_finish=self._checked)

    def _installed(self, result: Any) -> None:
        if result.state != "succeeded":
            self._discard_partial()
            self._end(result.state, result.error_code, result.error_text)
            return
        try:
            self._submit_check()
        except (JobError, ValueError, RuntimeError) as exc:
            # RuntimeError: el lanzador ya se cerró (Blender se cierra).
            job = _worker_label(CHECK_WORKER)
            error = (exc if isinstance(exc, JobError)
                     else JobError("job_interrupted", job=job) if isinstance(exc, RuntimeError)
                     else JobError("request_invalid", job=job, detail=str(exc)))
            self._discard_partial()
            self._end("failed", error.code, error.text)

    def _checked(self, result: Any) -> None:
        if self._kind == SETUP_INSTALL:
            self._checked_install(result)
            return
        if result.state == "succeeded":
            try:
                self._env.record_check(result.summary)
            except (ValueError, OSError) as exc:
                failure = install_failure("runtime_adopt_failed", path=str(self._env.path),
                                          detail=str(exc))
                self._end("failed", failure.code, failure.text)
                return
            self.check = result.summary
        elif result.state in ("failed", "timed_out"):
            try:
                self._env.record_failed_check(result.error_code or result.state,
                                              result.error_text or "")
            except (ValueError, OSError):
                LOGGER.exception("No se pudo anotar la verificación fallida del motor %s",
                                 self._env.path)
        self._end(result.state, result.error_code, result.error_text)

    def _checked_install(self, result: Any) -> None:
        if result.state != "succeeded":
            self._discard_partial()
            self._end(result.state, result.error_code, result.error_text)
            return
        try:
            assert self._plan is not None and self._consent is not None
            self._env.adopt(self._env.staged_site, result.summary, self._plan, self._consent)
        except (ValueError, OSError) as exc:
            self._discard_partial()
            failure = install_failure("runtime_adopt_failed", path=str(self._env.path),
                                      detail=str(exc))
            self._end("failed", failure.code, failure.text)
            return
        self.check = result.summary
        self._end("succeeded")

    def _discard_partial(self) -> None:
        """Borra ``<lock_id>.partial`` (RF-004-21); si no se puede, se borrará en el siguiente
        intento (nunca se usa)."""
        if not remove_tree(self._env.partial_path):
            LOGGER.warning("No se pudo borrar la instalación a medias %s; se borrará en el "
                           "siguiente intento", self._env.partial_path)

    def _end(self, state: str, code: str | None = None, text: str | None = None) -> None:
        if state == "succeeded":
            self._state = SETUP_SUCCEEDED
        elif state == "cancelled":
            self._state = SETUP_CANCELLED
        else:
            self._state = SETUP_FAILED
        self._step = None
        self.error_code = code
        self.error_text = text
        if self._on_done is not None:
            self._on_done(self)
