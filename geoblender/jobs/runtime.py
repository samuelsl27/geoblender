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
  en la línea de órdenes (plan §5.3.3 y §5.4.7).

Nada de esto crea, descarga ni borra el motor (RF-004-19): solo lo hace el trabajo que se
lanza con el consentimiento. Este módulo no usa la red ni toca ``sys.path``.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.sysinfo import host_name, user_name
from ..core.timeutil import format_utc, parse_utc
from . import catalog
from .messages import JobError
from .paths import BYTES_PER_MB
from .protocol import JobRequest, JsonValue, new_request

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
    disco ni la red; ninguno de sus métodos crea, descarga ni borra el motor (RF-004-19)."""

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


def _install_label() -> str:
    """El nombre visible del tipo de trabajo ``runtime_install``, en español."""
    info = next(info for info in catalog.BUILTIN_WORKERS if info.name == INSTALL_WORKER)
    return catalog.CATALOG_ES.get(info.label_msgid, info.label_msgid)


def _refused(job: str, detail: str) -> JobError:
    return JobError("request_invalid", job=job,
                    detail=f"{detail} (vuelva a pedir la instalación)")
