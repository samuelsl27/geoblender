# SPDX-License-Identifier: GPL-3.0-or-later
"""Protocolo de los trabajos en segundo plano: la petición y los eventos (spec 004;
RF-004-01, RF-004-02, RF-004-12, RF-004-15; plan 004 §5.2.2, §5.2.3 y §5.3.1).

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

Los **eventos** (plan §5.2.3) son lo que el worker cuenta por su canal (el stdout original):
una línea JSON en UTF-8 por evento, ``{"v": 1, "t": <tipo>, "ts": <s>, …}``, de los tipos
``start``, ``progress``, ``log``, ``result``, ``error`` y ``cancelled``.

- :class:`OutputRef`: un resultado declarado (ruta relativa dentro de ``out/``, sha256,
  tamaño y papel).
- :class:`JobEvent`: un evento, siempre válido (se comprueba al crearlo); ``frac`` (avance,
  0–1) fuera de 0–1 se acota (spec §6: el avance se acota).
- :func:`encode_event`: la línea de un evento, en bytes.
- :class:`EventDecoder`: de los bytes del canal, en trozos de cualquier tamaño, los eventos
  en orden de llegada; lo que no es un evento (texto de una librería, JSON cortado, otra
  versión…) sale en su sitio como :class:`InvalidLine`, sin lanzar (RF-004-15).
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
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
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

OUTPUTS_DIR = "out"
"""Carpeta de los resultados dentro de la del trabajo: todo resultado está aquí dentro."""
EVENT_VERSION = 1
EVENT_TYPES: tuple[str, ...] = ("start", "progress", "log", "result", "error", "cancelled")
LOG_LEVELS: tuple[str, ...] = ("debug", "info", "warning", "error")
MAX_EVENT_BYTES = 1 << 20
"""Longitud máxima de una línea de evento (1 MiB): una más larga no es un evento y no se
guarda entera en memoria (una librería que escribe sin saltos de línea)."""
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
"""Huella sha256 en 64 cifras hexadecimales en minúsculas (con ``fullmatch``)."""
_SHOWN_CHARS = 200
"""Caracteres que se guardan de una línea demasiado larga."""

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
    folder = folder_path(job_dir)
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
    folder = folder_path(job_dir)
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


# --- Eventos ----------------------------------------------------------------------------

_OUTPUT_FIELDS: tuple[str, ...] = ("path", "sha256", "size", "role")
# Campos de cada tipo de evento (además de ``v``, ``t`` y ``ts``) y los obligatorios.
_EVENT_FIELDS: Mapping[str, tuple[str, ...]] = {
    "start": ("info",),
    "progress": ("frac", "msg"),
    "log": ("level", "msg"),
    "result": ("outputs", "summary"),
    "error": ("code", "msgid", "values", "msg"),
    "cancelled": ("msg",),
}
_EVENT_REQUIRED: Mapping[str, tuple[str, ...]] = {
    "start": ("info",),
    "progress": ("frac",),
    "log": ("level", "msg"),
    "result": ("outputs",),
    "error": ("code", "msgid", "msg"),
    "cancelled": (),
}


@dataclass(frozen=True, slots=True)
class OutputRef:
    """Un resultado declarado por el worker (plan §5.2.3): ``path``, relativa a la carpeta
    del trabajo y dentro de ``out/`` (se guarda con «/»); ``sha256`` del fichero, en 64
    cifras hexadecimales en minúsculas; ``size`` en bytes y ``role``, su papel para el
    módulo dueño (``"sum"``). Se comprueba al crearlo: :class:`ValueError` si no cumple.
    Que el fichero exista y case con la huella lo comprueba el lanzador (RF-004-05)."""

    path: str
    sha256: str
    size: int
    role: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise ValueError(f"la ruta del resultado {_shown(self.path)} no es un texto")
        if _relative_problem(self.path, OUTPUTS_DIR) is not None:
            raise ValueError(
                f"el resultado {_shown(self.path)} no está dentro de {OUTPUTS_DIR}/ de la "
                "carpeta del trabajo"
            )
        object.__setattr__(self, "path", self.path.replace("\\", "/"))
        if not isinstance(self.sha256, str) or not SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError(
                f"la huella {_shown(self.sha256)} del resultado {self.path} no es un sha256 "
                "(64 cifras hexadecimales en minúsculas)"
            )
        if not _is_int(self.size) or self.size < 0:
            raise ValueError(
                f"el tamaño {_shown(self.size)} del resultado {self.path} no es un número "
                "de bytes"
            )
        if not _filled(self.role):
            raise ValueError(f"el resultado {self.path} no tiene papel (role)")

    def to_json(self) -> dict[str, JsonValue]:
        """La forma JSON del resultado."""
        return {"path": self.path, "sha256": self.sha256, "size": self.size, "role": self.role}

    @classmethod
    def from_json(cls, data: object) -> OutputRef:
        """El resultado de su forma JSON (se ignoran las claves de más); :class:`ValueError`
        si no es un objeto, le falta un campo o no cumple."""
        if not isinstance(data, Mapping):
            raise ValueError(f"un resultado no es un objeto JSON ({_shown(data)})")
        missing = [name for name in _OUTPUT_FIELDS if name not in data]
        if missing:
            raise ValueError(
                _listed("al resultado le falta el campo", "al resultado le faltan los campos",
                        missing)
            )
        return cls(data["path"], data["sha256"], data["size"], data["role"])


@dataclass(frozen=True, slots=True, kw_only=True)
class JobEvent:
    """Un evento del worker (plan §5.2.3), siempre válido: se comprueba al crearlo
    (:class:`ValueError` si no cumple). Mejor con los constructores :meth:`start`,
    :meth:`progress`, :meth:`log`, :meth:`result`, :meth:`error` y :meth:`cancelled`.

    ``type`` es el tipo (``"t"`` en JSON) y ``ts`` la hora en segundos desde 1970. Cada tipo
    usa solo sus campos: ``start``, ``info`` (pid, tipo de intérprete, versiones de Python,
    numpy y BLAS); ``progress``, ``frac`` (0–1: fuera de 0–1 se acota) y ``msg``; ``log``,
    ``level`` (:data:`LOG_LEVELS`) y ``msg``; ``result``, ``outputs`` (:class:`OutputRef`) y
    ``summary``; ``error``, ``code``, ``msgid``, ``values`` y ``msg`` (el texto en español);
    ``cancelled``, ``msg``. ``info``, ``summary`` y ``values`` se guardan como copias JSON.
    """

    type: str
    ts: float
    frac: float | None = None
    msg: str = ""
    level: str | None = None
    info: Mapping[str, JsonValue] = field(default_factory=dict)
    outputs: tuple[OutputRef, ...] = ()
    summary: Mapping[str, JsonValue] = field(default_factory=dict)
    code: str | None = None
    msgid: str | None = None
    values: Mapping[str, JsonValue] = field(default_factory=dict)
    v: int = EVENT_VERSION

    def __post_init__(self) -> None:
        _check_version(self.v)
        if not isinstance(self.type, str) or self.type not in EVENT_TYPES:
            raise ValueError(
                f"tipo de evento desconocido: {_shown(self.type)} (se esperaba uno de "
                f"{', '.join(EVENT_TYPES)})"
            )
        if not _is_number(self.ts) or not math.isfinite(self.ts):
            raise ValueError(
                f"la hora del evento (ts) {_shown(self.ts)} no es un número finito de segundos"
            )
        update = object.__setattr__
        update(self, "ts", float(self.ts))
        if not isinstance(self.msg, str):
            raise ValueError(f"el mensaje (msg) {_shown(self.msg)} no es un texto")
        match self.type:
            case "start":
                update(self, "info", _json_object(self.info, "info"))
            case "progress":
                if not _is_number(self.frac) or math.isnan(self.frac):
                    raise ValueError(f"el avance (frac) {_shown(self.frac)} no es un número")
                update(self, "frac", min(1.0, max(0.0, float(self.frac))))
            case "log":
                if not isinstance(self.level, str) or self.level not in LOG_LEVELS:
                    raise ValueError(
                        f"el nivel {_shown(self.level)} no es uno de {', '.join(LOG_LEVELS)}"
                    )
            case "result":
                if not isinstance(self.outputs, list | tuple) or not all(
                    isinstance(item, OutputRef) for item in self.outputs
                ):
                    raise ValueError("los resultados (outputs) no son una lista de OutputRef")
                update(self, "outputs", tuple(self.outputs))
                update(self, "summary", _json_object(self.summary, "summary"))
            case "error":
                if not _filled(self.code):
                    raise ValueError(f"el código de error {_shown(self.code)} está vacío")
                if not _filled(self.msgid):
                    raise ValueError(f"el msgid {_shown(self.msgid)} del error está vacío")
                update(self, "values", _json_object(self.values, "values"))

    # Constructores ---------------------------------------------------------------------

    @classmethod
    def start(cls, info: Mapping[str, JsonValue], *, ts: float | None = None) -> JobEvent:
        """``start``: el worker arrancó (``info``: pid, intérprete y versiones)."""
        return cls(type="start", ts=_event_time(ts), info=info)

    @classmethod
    def progress(cls, frac: float, msg: str = "", *, ts: float | None = None) -> JobEvent:
        """``progress``: avance ``frac`` (0–1, acotado) con un mensaje."""
        return cls(type="progress", ts=_event_time(ts), frac=frac, msg=msg)

    @classmethod
    def log(cls, level: str, msg: str, *, ts: float | None = None) -> JobEvent:
        """``log``: una nota para el registro (``debug``, ``info``, ``warning``, ``error``)."""
        return cls(type="log", ts=_event_time(ts), level=level, msg=msg)

    @classmethod
    def result(
        cls,
        outputs: Iterable[OutputRef] = (),
        summary: Mapping[str, JsonValue] | None = None,
        *,
        ts: float | None = None,
    ) -> JobEvent:
        """``result``: los resultados declarados y el resumen (JSON) del trabajo."""
        return cls(type="result", ts=_event_time(ts), outputs=tuple(outputs),
                   summary={} if summary is None else summary)

    @classmethod
    def error(
        cls,
        code: str,
        *,
        msgid: str,
        msg: str,
        values: Mapping[str, JsonValue] | None = None,
        ts: float | None = None,
    ) -> JobEvent:
        """``error``: el código, el ``msgid`` en inglés, sus valores y el texto en español
        (RF-004-12)."""
        return cls(type="error", ts=_event_time(ts), code=code, msgid=msgid, msg=msg,
                   values={} if values is None else values)

    @classmethod
    def cancelled(cls, msg: str = "", *, ts: float | None = None) -> JobEvent:
        """``cancelled``: el worker atendió la cancelación."""
        return cls(type="cancelled", ts=_event_time(ts), msg=msg)

    # JSON ------------------------------------------------------------------------------

    def to_json(self) -> dict[str, JsonValue]:
        """La forma JSON del evento: ``v``, ``t`` y ``ts`` y los campos de su tipo."""
        data: dict[str, JsonValue] = {"v": self.v, "t": self.type, "ts": self.ts}
        match self.type:
            case "start":
                data["info"] = plain_json(self.info, "info")
            case "progress":
                data["frac"] = self.frac
                data["msg"] = self.msg
            case "log":
                data["level"] = self.level
                data["msg"] = self.msg
            case "result":
                data["outputs"] = [output.to_json() for output in self.outputs]
                data["summary"] = plain_json(self.summary, "summary")
            case "error":
                data["code"] = self.code
                data["msgid"] = self.msgid
                data["values"] = plain_json(self.values, "values")
                data["msg"] = self.msg
            case "cancelled":
                data["msg"] = self.msg
        return data

    @classmethod
    def from_json(cls, data: object) -> JobEvent:
        """El evento de su forma JSON. :class:`ValueError` (con el motivo en español) si no
        es un objeto, es de otra versión o de un tipo desconocido, le falta un campo de su
        tipo o no cumple. Las claves de más se ignoran."""
        if not isinstance(data, Mapping):
            raise ValueError(f"no es un objeto JSON ({type(data).__name__})")
        if "v" not in data:
            raise ValueError("falta la versión del evento («v»)")
        _check_version(data["v"])
        kind = data.get("t")
        if not isinstance(kind, str) or kind not in EVENT_TYPES:
            raise ValueError(f"tipo de evento desconocido: {_shown(kind)}")
        if "ts" not in data:
            raise ValueError("falta la hora del evento («ts»)")
        missing = [name for name in _EVENT_REQUIRED[kind] if name not in data]
        if missing:
            raise ValueError(
                _listed(f"al evento «{kind}» le falta el campo",
                        f"al evento «{kind}» le faltan los campos", missing)
            )
        values: dict[str, object] = {
            name: data[name] for name in _EVENT_FIELDS[kind] if name in data
        }
        if kind == "result":
            outputs = data["outputs"]
            if not isinstance(outputs, list):
                raise ValueError("los resultados (outputs) no son una lista")
            values["outputs"] = tuple(OutputRef.from_json(item) for item in outputs)
        return cls(type=kind, ts=data["ts"], v=data["v"], **values)


@dataclass(frozen=True, slots=True)
class InvalidLine:
    """Una línea del canal que no es un evento: ``text`` (en UTF-8, con «�» en los bytes
    que no lo son; de una línea demasiado larga, solo el principio) y ``reason``, por qué no
    lo es, en español. El lanzador la anota como aviso y el trabajo sigue (spec §6)."""

    text: str
    reason: str


def encode_event(event: JobEvent) -> bytes:
    """La línea del evento: JSON en UTF-8 (la «ñ» tal cual) y «\\n»; un salto de línea dentro
    de un texto va escapado, así que es siempre una sola línea. Un texto con sustitutos
    sueltos (un nombre de fichero mal descodificado) se escapa como ``\\udcxx``.
    :class:`ValueError` si la línea pasa de :data:`MAX_EVENT_BYTES` (el decodificador no la
    aceptaría)."""
    if not isinstance(event, JobEvent):
        raise ValueError(f"no es un evento: {type(event).__name__}")
    data = event.to_json()
    try:
        line = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except UnicodeEncodeError:
        line = json.dumps(data, ensure_ascii=True, allow_nan=False).encode("ascii")
    if len(line) > MAX_EVENT_BYTES:
        raise ValueError(
            f"el evento «{event.type}» ocupa {len(line)} bytes y no puede pasar de "
            f"{MAX_EVENT_BYTES}: guarde lo grande en out/ y declárelo como resultado"
        )
    return line + b"\n"


class EventDecoder:
    """Decodificador del canal de eventos de un worker.

    :meth:`feed` recibe los bytes tal como llegan (en trozos de cualquier tamaño: una línea
    o una «ñ» pueden llegar partidas) y devuelve, en orden de llegada, un :class:`JobEvent`
    por cada línea completa que lo es y una :class:`InvalidLine` por cada una que no; nunca
    lanza por lo que reciba. Se aceptan los finales «\\r\\n» y se saltan las líneas vacías.
    Una línea de más de ``max_line_bytes`` es una sola :class:`InvalidLine` y no se guarda
    en memoria. :meth:`close` decodifica lo que quedó sin «\\n» (un worker que murió a medias
    deja una :class:`InvalidLine`).
    """

    def __init__(self, *, max_line_bytes: int = MAX_EVENT_BYTES) -> None:
        if not _is_int(max_line_bytes) or max_line_bytes < 1:
            raise ValueError(f"max_line_bytes = {max_line_bytes!r} debe ser un entero ≥ 1")
        self._max = max_line_bytes
        self._pending = b""
        self._discarding = False
        self._closed = False

    def feed(self, data: bytes) -> list[JobEvent | InvalidLine]:
        """Los eventos y líneas inválidas que completa ``data``, en orden."""
        if self._closed:
            raise ValueError("el decodificador de eventos ya está cerrado")
        *lines, rest = (self._pending + bytes(data)).split(b"\n")
        found: list[JobEvent | InvalidLine] = []
        for line in lines:
            if self._discarding:
                # El final de una línea demasiado larga, ya anotada.
                self._discarding = False
                continue
            item = self._decode(line)
            if item is not None:
                found.append(item)
        if self._discarding:
            rest = b""
        elif len(rest) > self._max:
            found.append(self._too_long(rest))
            rest = b""
            self._discarding = True
        self._pending = rest
        return found

    def close(self) -> list[JobEvent | InvalidLine]:
        """Lo que quedó sin «\\n» al terminar el canal; después no admite más bytes."""
        if self._closed:
            return []
        self._closed = True
        rest, self._pending = self._pending, b""
        if self._discarding:
            return []
        item = self._decode(rest)
        return [] if item is None else [item]

    def _decode(self, line: bytes) -> JobEvent | InvalidLine | None:
        if line.endswith(b"\r"):
            line = line[:-1]
        if len(line) > self._max:
            return self._too_long(line)
        if not line.strip():
            return None
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            return InvalidLine(
                line.decode("utf-8", "replace"),
                f"no está en UTF-8 ({exc.reason} en el byte {exc.start})",
            )
        try:
            data = json.loads(text, parse_constant=_reject_constant)
        except (ValueError, RecursionError) as exc:
            return InvalidLine(text, f"no es JSON ({exc})")
        try:
            return JobEvent.from_json(data)
        except (ValueError, TypeError, RecursionError) as exc:
            return InvalidLine(text, f"no es un evento del protocolo: {exc}")

    def _too_long(self, line: bytes) -> InvalidLine:
        start = line[: _SHOWN_CHARS * 4].decode("utf-8", "replace")[:_SHOWN_CHARS]
        return InvalidLine(
            f"{start}…", f"la línea pasa de {self._max} bytes: no es un evento"
        )


def _check_version(version: object) -> None:
    if not _is_int(version) or version != EVENT_VERSION:
        raise ValueError(
            f"versión de evento desconocida: {_shown(version)} (esta versión de Geoblender "
            f"entiende la {EVENT_VERSION})"
        )


def _json_object(value: object, where: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} no es un objeto JSON ({_shown(value)})")
    copied = plain_json(value, where)
    if not isinstance(copied, dict):  # no ocurre: la copia de un Mapping es un dict
        raise ValueError(f"{where} no es un objeto JSON")
    return copied


def _event_time(ts: float | None) -> float:
    return time.time() if ts is None else ts


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


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
    problem = _relative_problem(value, INPUTS_DIR)
    if problem == "outside":
        raise JobError("request_path_outside_job", job=job, path=value)
    if problem is not None:
        raise _invalid(job, f"la entrada «{name}» = {value} no está dentro de {INPUTS_DIR}/")


def _relative_problem(value: str, folder: str) -> str | None:
    """Por qué ``value`` no es una ruta relativa dentro de ``folder/`` de la carpeta del
    trabajo: ``"outside"`` si sale de ella (absoluta, de red, con unidad, con «:» o con
    ``..``) y ``"elsewhere"`` si no está dentro de ``folder/``; ``None`` si lo está."""
    text = value.replace("\\", "/")
    parts = text.split("/")
    # Absoluta, de red (``//``), con unidad (``C:``) o con un flujo alternativo (``x:y``).
    if text.startswith("/") or ":" in text:
        return "outside"
    # ``..`` (Windows quita los puntos y espacios del final de cada nombre: ``.. `` es ``..``).
    if any(_dots_only(part) and len(part.strip()) > 1 for part in parts):
        return "outside"
    inside = len(parts) >= 2 and parts[0] == folder and all(
        _good_name(part) for part in parts[1:]
    )
    return None if inside else "elsewhere"


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


def _json_copy(value: object, where: str, job: str) -> JsonValue:
    """:func:`plain_json` de ``value``; :class:`JobError` ``request_invalid`` si no es JSON."""
    try:
        return plain_json(value, where)
    except ValueError as exc:
        raise _invalid(job, str(exc)) from None


def plain_json(value: object, where: str = "valor", *, depth: int = 0) -> JsonValue:
    """Copia JSON de ``value``: las tuplas, como listas; los enteros y decimales de numpy,
    como los de Python. :class:`ValueError` (que nombra ``where``) si no es JSON: NaN o
    infinitos, una clave que no es texto, otro tipo o más de :data:`MAX_JSON_DEPTH`
    niveles."""
    if depth > MAX_JSON_DEPTH:
        raise ValueError(f"{where} tiene más de {MAX_JSON_DEPTH} niveles")
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{where} = {value!r} no es JSON (ni NaN ni infinitos)")
        return float(value)
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, Mapping):
        copied: dict[str, JsonValue] = {}
        for key, inner in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{where} tiene una clave que no es texto ({key!r})")
            copied[key] = plain_json(inner, f"{where}.{key}", depth=depth + 1)
        return copied
    if isinstance(value, list | tuple):
        return [
            plain_json(inner, f"{where}[{index}]", depth=depth + 1)
            for index, inner in enumerate(value)
        ]
    raise ValueError(f"{where} es de tipo {type(value).__name__}, que no es JSON")


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


def folder_path(job_dir: JobFolder) -> Path:
    """La ruta de la carpeta de un trabajo, dada como ruta o como objeto con ``path``."""
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
