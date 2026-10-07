# SPDX-License-Identifier: GPL-3.0-or-later
"""Protocolo de los trabajos en segundo plano: la petición (spec 004; RF-004-01, RF-004-02;
plan 004 §5.2.2 y §5.3.1).

La **petición** (``request.json`` de la carpeta del trabajo, esquema ``geoblender.job/1``) es
lo que un trabajo necesita: el tipo de trabajo (``worker``), su nombre visible, el módulo
dueño, los parámetros (JSON), las entradas relativas a su carpeta (siempre dentro de
``in/``), el tiempo máximo, el plazo de gracia, el entorno (``blender`` o ``compute``), el
proyecto y la operación de origen (R-07), la versión de Geoblender y la hora de creación.
**No lleva rutas absolutas ni el intérprete**: las rutas viajan en la línea de órdenes y el
intérprete lo decide el lanzador (plan §5.3.3).

- :class:`JobRequest`: la petición (inmutable), con su forma JSON.
- :func:`new_request`: una petición nueva, con su ``job_uid``, la versión de Geoblender y la
  hora. Sin entorno ni tiempo máximo, los toma después el lanzador del tipo de trabajo.
- :func:`validate_request`: las reglas del plan §5.2.2. Un incumplimiento es un
  :class:`~.messages.JobError` (``request_invalid``, ``request_path_outside_job`` o
  ``worker_unknown``) y no escribe nada: se rechaza antes de crear ficheros o procesos.
- :func:`write_request` y :func:`read_request`: ``request.json`` de la carpeta de un
  trabajo, comprobado al escribir y al leer (también en el worker).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import numbers
import os
import re
import secrets
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from ..core.timeutil import format_utc, parse_utc
from ..core.version import geoblender_version
from .messages import JobError

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type Environment = Literal["blender", "compute"]

REQUEST_SCHEMA = "geoblender.job/1"
REQUEST_FILE = "request.json"
INPUTS_DIR = "in"
"""Carpeta de las entradas dentro de la del trabajo: toda entrada está aquí dentro."""

ENVIRONMENTS: tuple[str, ...] = ("blender", "compute")
DEFAULT_TIMEOUT_S = 3600.0
"""Tiempo máximo de un tipo de trabajo que no declara ninguno (RF-004-11)."""
MAX_TIMEOUT_S = 86_400.0
DEFAULT_GRACE_S = 5.0
MIN_GRACE_S = 1.0
MAX_GRACE_S = 60.0

JOB_UID_PATTERN = re.compile(r"[0-9]{8}_[0-9]{6}_[0-9a-f]{6}")
"""``AAAAMMDD_HHMMSS_xxxxxx``: hora UTC y 6 cifras hexadecimales al azar (con ``fullmatch``)."""
WORKER_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
"""Nombre de un tipo de trabajo: ``<código>_<acción>`` en minúsculas, igual al módulo de
``workers/`` que lo ejecuta (con ``fullmatch``): nunca un punto ni una barra."""

MAX_JSON_DEPTH = 64

_FIELDS: tuple[str, ...] = (
    "schema", "job_uid", "worker", "label", "owner", "params", "inputs", "timeout_s",
    "grace_s", "environment", "project_uid", "operation_uid", "geoblender_version",
    "created_at",
)
_TEXT_FIELDS: tuple[str, ...] = (
    "job_uid", "worker", "label", "owner", "geoblender_version", "created_at",
)
_OPTIONAL_TEXT_FIELDS: tuple[str, ...] = ("environment", "project_uid", "operation_uid")
# Caracteres que un nombre de Windows no admite (la «:», aparte: unidad o flujo alternativo).
_BAD_NAME_CHARS = frozenset('<>"|?*') | frozenset(chr(code) for code in range(32))
_SEPARATORS = re.compile(r"/+")


@dataclass(frozen=True, slots=True, kw_only=True)
class JobRequest:
    """La petición de un trabajo (``geoblender.job/1``, plan §5.2.2).

    ``environment`` y ``timeout_s`` vacíos (``None``) significan «lo que declare el tipo de
    trabajo»: el lanzador los fija antes de validarla y escribirla. ``params`` es JSON;
    ``inputs`` va de nombre a ruta relativa a la carpeta del trabajo (``in/<nombre>.npy``).
    """

    job_uid: str
    worker: str
    label: str
    owner: str
    params: Mapping[str, JsonValue] = field(default_factory=dict)
    inputs: Mapping[str, str] = field(default_factory=dict)
    timeout_s: float | None = None
    grace_s: float = DEFAULT_GRACE_S
    environment: Environment | None = None
    project_uid: str | None = None
    operation_uid: str | None = None
    geoblender_version: str
    created_at: str
    schema: str = REQUEST_SCHEMA

    def to_json(self) -> dict[str, JsonValue]:
        """La forma JSON de la petición (una copia), con las claves en el orden del plan."""
        job = _job_name(self)
        return {
            "schema": self.schema,
            "job_uid": self.job_uid,
            "worker": self.worker,
            "label": self.label,
            "owner": self.owner,
            "params": _json_copy(self.params, "params", job),
            "inputs": _json_copy(self.inputs, "inputs", job),
            "timeout_s": self.timeout_s,
            "grace_s": self.grace_s,
            "environment": self.environment,
            "project_uid": self.project_uid,
            "operation_uid": self.operation_uid,
            "geoblender_version": self.geoblender_version,
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, data: object, *, job: str = "?") -> JobRequest:
        """La petición de su forma JSON; comprueba el esquema, los campos y sus tipos (los
        valores, :func:`validate_request`). :class:`JobError` ``request_invalid`` si no;
        ``job`` nombra el trabajo en el mensaje mientras no se conoce su nombre."""
        if not isinstance(data, dict):
            raise _invalid(job, f"la petición no es un objeto JSON ({type(data).__name__})")
        label = data.get("label")
        if isinstance(label, str) and label.strip():
            job = label
        schema = data.get("schema")
        if schema != REQUEST_SCHEMA:
            raise _invalid(job, _schema_detail(schema))
        missing = [name for name in _FIELDS if name not in data]
        extra = sorted(str(name) for name in data if name not in _FIELDS)
        if missing or extra:
            parts = []
            if missing:
                parts.append(_listed("falta el campo", "faltan los campos", missing))
            if extra:
                parts.append(_listed("sobra el campo", "sobran los campos", extra))
            raise _invalid(job, "; ".join(parts))
        for name in _TEXT_FIELDS:
            if not isinstance(data[name], str):
                raise _invalid(job, f"{name} no es un texto ({_shown(data[name])})")
        for name in _OPTIONAL_TEXT_FIELDS:
            if data[name] is not None and not isinstance(data[name], str):
                raise _invalid(job, f"{name} no es un texto ni vacío ({_shown(data[name])})")
        if not isinstance(data["params"], dict):
            raise _invalid(job, "params no es un objeto JSON")
        inputs = data["inputs"]
        if not isinstance(inputs, dict) or not all(isinstance(v, str) for v in inputs.values()):
            raise _invalid(job, "inputs no es un objeto JSON de nombre a ruta (texto)")
        return cls(
            job_uid=data["job_uid"],
            worker=data["worker"],
            label=data["label"],
            owner=data["owner"],
            params=data["params"],
            inputs=dict(inputs),
            timeout_s=_as_seconds(data["timeout_s"]),
            grace_s=_as_seconds(data["grace_s"]),
            environment=data["environment"],
            project_uid=data["project_uid"],
            operation_uid=data["operation_uid"],
            geoblender_version=data["geoblender_version"],
            created_at=data["created_at"],
            schema=schema,
        )


class _HasPath(Protocol):
    """La carpeta de un trabajo como objeto (el ``JobDir`` de ``jobs/paths.py``)."""

    @property
    def path(self) -> Path: ...


type JobFolder = _HasPath | os.PathLike[str] | str
"""La carpeta de un trabajo: un objeto con ``path`` (``JobDir``) o su ruta."""


def new_request(
    worker: str,
    *,
    label: str,
    owner: str,
    params: Mapping[str, JsonValue] | None = None,
    inputs: Mapping[str, str] | None = None,
    environment: Environment | None = None,
    timeout_s: float | None = None,
    grace_s: float = DEFAULT_GRACE_S,
    project_uid: str | None = None,
    operation_uid: str | None = None,
    now: dt.datetime | None = None,
) -> JobRequest:
    """Una petición nueva (RF-004-01) con su ``job_uid`` de la hora ``now`` (UTC; la actual
    si falta), la versión de Geoblender y una copia JSON de ``params`` (las tuplas, como
    listas). ``environment`` y ``timeout_s`` vacíos los fija el lanzador con lo que declare el
    tipo de trabajo. No valida las reglas del plan (:func:`validate_request`), pero un
    parámetro que no es JSON es :class:`JobError` ``request_invalid``."""
    moment = dt.datetime.now(dt.UTC) if now is None else now
    created_at = format_utc(moment)  # ValueError si no tiene zona
    job = label if isinstance(label, str) and label.strip() else str(worker)
    copied_params = _json_copy({} if params is None else params, "params", job)
    if not isinstance(copied_params, dict):
        raise _invalid(job, "params no es un objeto JSON")
    copied_inputs = _json_copy({} if inputs is None else inputs, "inputs", job)
    if not isinstance(copied_inputs, dict):
        raise _invalid(job, "inputs no es un objeto JSON de nombre a ruta")
    return JobRequest(
        job_uid=_new_job_uid(moment),
        worker=worker,
        label=label,
        owner=owner,
        params=copied_params,
        inputs=copied_inputs,
        timeout_s=_as_seconds(timeout_s),
        grace_s=_as_seconds(grace_s),
        environment=environment,
        project_uid=project_uid,
        operation_uid=operation_uid,
        geoblender_version=geoblender_version(),
        created_at=created_at,
    )


def validate_request(
    request: JobRequest,
    *,
    catalog: Mapping[str, object],
    forbidden_roots: Sequence[Path] = (),
) -> None:
    """Comprueba ``request`` con las reglas del plan §5.2.2 (RF-004-02) sin escribir nada:

    - esquema ``geoblender.job/1``; identificador ``AAAAMMDD_HHMMSS_xxxxxx``; nombre visible,
      dueño, versión y hora presentes; parámetros JSON;
    - entorno ``blender`` o ``compute``; ``timeout_s`` en (0, 86 400] s; ``grace_s`` en
      [1, 60] s; si no, ``request_invalid``;
    - cada entrada, relativa y dentro de ``in/``: absoluta, con unidad, con «:» o con ``..``
      es ``request_path_outside_job``, y fuera de ``in/``, ``request_invalid``;
    - ningún texto de la petición (claves y valores, en profundidad) contiene una de
      ``forbidden_roots`` (la raíz del proyecto), sin distinguir mayúsculas y con «\\» y «/»
      normalizadas: ``request_path_outside_job``;
    - el tipo de trabajo está en ``catalog``: si no, ``worker_unknown``.

    Una raíz prohibida relativa es un error del programa (:class:`ValueError`).
    """
    roots = _comparable_roots(forbidden_roots)
    _check_request(request)
    job = _job_name(request)
    for text in _texts(request.to_json()):
        flat = _comparable(text)
        if any(root in flat for root in roots):
            raise JobError("request_path_outside_job", job=job, path=text)
    if request.worker not in catalog:
        raise JobError("worker_unknown", worker=request.worker)


def write_request(job_dir: JobFolder, request: JobRequest) -> None:
    """Escribe ``request.json`` en la carpeta del trabajo (que ya existe y se llama como
    su ``job_uid``): UTF-8 sin BOM, LF, sangrado, sustituyendo de forma atómica al anterior.
    Antes comprueba la petición sin el catálogo ni las raíces prohibidas (las de
    :func:`validate_request` que no los necesitan): si no es válida, :class:`JobError` y no
    se crea ningún fichero."""
    _check_request(request)
    folder = _folder(job_dir)
    _check_folder(folder, request)
    text = json.dumps(request.to_json(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    target = folder / REQUEST_FILE
    temporary = folder / f"{REQUEST_FILE}.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def read_request(job_dir: JobFolder) -> JobRequest:
    """Lee ``request.json`` de la carpeta del trabajo y lo comprueba como
    :func:`write_request`; también que sea la petición de esa carpeta. :class:`JobError`
    ``request_invalid`` (o ``worker_unknown``) si falta, no es JSON en UTF-8 sin BOM, tiene
    otro esquema o no es válida. No escribe nada."""
    folder = _folder(job_dir)
    path = folder / REQUEST_FILE
    try:
        raw = path.read_bytes()
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            reason = "no existe"
        else:
            reason = exc.strerror or type(exc).__name__
        raise _invalid(folder.name, f"no se puede leer {REQUEST_FILE}: {reason}") from None
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        detail = f"{REQUEST_FILE} no es JSON en UTF-8 sin BOM ({exc})"
        raise _invalid(folder.name, detail) from None
    request = JobRequest.from_json(data, job=folder.name)
    _check_request(request)
    _check_folder(folder, request)
    return request


# --- Comprobaciones ---------------------------------------------------------------------


def _check_request(request: JobRequest) -> None:
    """Las reglas que no necesitan el catálogo ni las raíces prohibidas."""
    job = _job_name(request)
    if request.schema != REQUEST_SCHEMA:
        raise _invalid(job, _schema_detail(request.schema))
    if not isinstance(request.job_uid, str) or not JOB_UID_PATTERN.fullmatch(request.job_uid):
        raise _invalid(
            job, f"el identificador {_shown(request.job_uid)} no es AAAAMMDD_HHMMSS_xxxxxx"
        )
    if not isinstance(request.worker, str) or not WORKER_NAME_PATTERN.fullmatch(request.worker):
        raise JobError("worker_unknown", worker=request.worker)
    if not _filled(request.label):
        raise _invalid(job, "falta el nombre visible del trabajo (label)")
    if not _filled(request.owner):
        raise _invalid(job, "falta el módulo dueño (owner)")
    if request.environment is None:
        raise _invalid(job, "falta el entorno (environment), que fija el tipo de trabajo")
    if request.environment not in ENVIRONMENTS:
        raise _invalid(
            job, f"el entorno {_shown(request.environment)} no es «blender» ni «compute»"
        )
    _check_seconds(
        job, "timeout_s", request.timeout_s, 0.0, MAX_TIMEOUT_S,
        "ser mayor que 0 s y no pasar de 86 400 s", low_included=False,
    )
    _check_seconds(
        job, "grace_s", request.grace_s, MIN_GRACE_S, MAX_GRACE_S, "estar entre 1 y 60 s"
    )
    if not _filled(request.geoblender_version):
        raise _invalid(job, "falta la versión de Geoblender (geoblender_version)")
    try:
        parse_utc(request.created_at)
    except ValueError:
        raise _invalid(
            job, f"la hora de creación {_shown(request.created_at)} no es UTC ISO 8601"
        ) from None
    for name in ("project_uid", "operation_uid"):
        value = getattr(request, name)
        if value is not None and not _filled(value):
            raise _invalid(job, f"{name} no es un texto ni vacío ({_shown(value)})")
    if not isinstance(request.params, Mapping):
        raise _invalid(job, "params no es un objeto JSON")
    _json_copy(request.params, "params", job)
    if not isinstance(request.inputs, Mapping):
        raise _invalid(job, "inputs no es un objeto JSON de nombre a ruta")
    for name, value in request.inputs.items():
        if not _filled(name):
            raise _invalid(job, f"una entrada no tiene nombre ({_shown(name)})")
        _check_input(job, name, value)


def _check_seconds(
    job: str, name: str, value: object, low: float, high: float, rule: str, *,
    low_included: bool = True,
) -> None:
    is_number = isinstance(value, int | float) and not isinstance(value, bool)
    ok = is_number and math.isfinite(value) and value <= high and (
        value >= low if low_included else value > low
    )
    if value is None:
        raise _invalid(job, f"falta {name}, que fija el tipo de trabajo: debe {rule}")
    if not ok:
        raise _invalid(job, f"{name} = {_shown(value)} s: debe {rule}")


def _check_input(job: str, name: str, value: object) -> None:
    """Una entrada: relativa, dentro de ``in/``, sin ``..``, unidad ni «:» (RF-004-02)."""
    if not isinstance(value, str) or not value:
        raise _invalid(job, f"la entrada «{name}» = {_shown(value)} no está dentro de in/")
    text = value.replace("\\", "/")
    parts = text.split("/")
    # Absoluta, de red (``//``), con unidad (``C:``) o con un flujo alternativo (``x:y``).
    if text.startswith("/") or ":" in text:
        raise JobError("request_path_outside_job", job=job, path=value)
    # ``..`` (Windows quita los puntos y espacios del final de cada nombre: ``.. `` es ``..``).
    if any(_dots_only(part) and len(part.strip()) > 1 for part in parts):
        raise JobError("request_path_outside_job", job=job, path=value)
    inside = len(parts) >= 2 and parts[0] == INPUTS_DIR and all(
        _good_name(part) for part in parts[1:]
    )
    if not inside:
        raise _invalid(job, f"la entrada «{name}» = {value} no está dentro de {INPUTS_DIR}/")


def _check_folder(folder: Path, request: JobRequest) -> None:
    if folder.name != request.job_uid:
        raise _invalid(
            _job_name(request),
            f"la carpeta {folder.name} no es la del trabajo {request.job_uid}",
        )


def _dots_only(part: str) -> bool:
    stripped = part.strip()
    return bool(stripped) and set(stripped) == {"."}


def _good_name(part: str) -> bool:
    """Un nombre de fichero o carpeta normal: no vacío, sin «.» ni espacio al final (Windows
    los quita) y sin caracteres que Windows no admite."""
    return bool(part) and not part.endswith((".", " ")) and not (
        _BAD_NAME_CHARS & set(part)
    )


def _comparable(text: str) -> str:
    """``text`` para buscar rutas: «\\» como «/», sin separadores repetidos y sin
    distinguir mayúsculas."""
    return _SEPARATORS.sub("/", text.replace("\\", "/")).casefold()


def _comparable_roots(roots: Sequence[Path]) -> list[str]:
    found: list[str] = []
    for root in roots:
        if not Path(root).is_absolute():
            raise ValueError(
                f"la raíz prohibida «{root}» no es absoluta: hace falta la ruta completa "
                "del proyecto para buscarla en la petición"
            )
        comparable = _comparable(os.fspath(root)).rstrip("/")
        if comparable:
            found.append(comparable)
    return found


def _texts(value: object) -> Iterator[str]:
    """Todos los textos de ``value`` (JSON): valores y claves, en profundidad."""
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for key, inner in item.items():
                stack.append(key)
                stack.append(inner)
        elif isinstance(item, list):
            stack.extend(item)


def _json_copy(value: object, where: str, job: str, depth: int = 0) -> JsonValue:
    """Copia JSON de ``value`` (las tuplas, como listas; los enteros y decimales de numpy,
    como los de Python). :class:`JobError` ``request_invalid`` si no es JSON."""
    if depth > MAX_JSON_DEPTH:
        raise _invalid(job, f"{where} tiene más de {MAX_JSON_DEPTH} niveles")
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid(job, f"{where} = {value!r} no es JSON (ni NaN ni infinitos)")
        return float(value)
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, Mapping):
        copied: dict[str, JsonValue] = {}
        for key, inner in value.items():
            if not isinstance(key, str):
                raise _invalid(job, f"{where} tiene una clave que no es texto ({key!r})")
            copied[key] = _json_copy(inner, f"{where}.{key}", job, depth + 1)
        return copied
    if isinstance(value, list | tuple):
        return [
            _json_copy(inner, f"{where}[{index}]", job, depth + 1)
            for index, inner in enumerate(value)
        ]
    raise _invalid(job, f"{where} es de tipo {type(value).__name__}, que no es JSON")


# --- Ayudas -----------------------------------------------------------------------------


class _UidIssuer:
    """Identificadores ``AAAAMMDD_HHMMSS_xxxxxx`` sin repetir dentro de este proceso: 6
    cifras hexadecimales al azar por segundo, y otras si ya salieron en ese segundo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stamp = ""
        self._issued: set[str] = set()

    def new(self, moment: dt.datetime) -> str:
        stamp = f"{moment.astimezone(dt.UTC):%Y%m%d_%H%M%S}"
        with self._lock:
            if stamp != self._stamp:
                self._stamp = stamp
                self._issued.clear()
            while True:
                uid = f"{stamp}_{secrets.token_hex(3)}"
                if uid not in self._issued:
                    self._issued.add(uid)
                    return uid


_UIDS = _UidIssuer()


def _new_job_uid(moment: dt.datetime) -> str:
    """``AAAAMMDD_HHMMSS_xxxxxx`` de ``moment`` en UTC, sin repetir en este proceso."""
    return _UIDS.new(moment)


def _folder(job_dir: JobFolder) -> Path:
    inner = getattr(job_dir, "path", None)
    return Path(inner if inner is not None else job_dir)


def _job_name(request: JobRequest) -> str:
    for candidate in (request.label, request.worker, request.job_uid):
        if _filled(candidate):
            return candidate
    return "?"


def _filled(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_seconds(value: object) -> object:
    """Los segundos como ``float``; lo que no es un número se deja tal cual para que la
    comprobación lo nombre."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return value


def _invalid(job: str, detail: str) -> JobError:
    return JobError("request_invalid", job=job, detail=detail)


def _schema_detail(schema: object) -> str:
    return f"el esquema {_shown(schema)} no es «{REQUEST_SCHEMA}»"


def _shown(value: object) -> str:
    """Un valor en el detalle de un mensaje: los textos entre comillas latinas y los
    decimales con coma."""
    if isinstance(value, str):
        return f"«{value}»"
    if isinstance(value, float) and math.isfinite(value):
        text = str(int(value)) if value.is_integer() else repr(value)
        return text.replace(".", ",")
    return repr(value)


def _listed(one: str, many: str, names: Sequence[str]) -> str:
    return f"{one if len(names) == 1 else many} {', '.join(names)}"


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} no es JSON")
