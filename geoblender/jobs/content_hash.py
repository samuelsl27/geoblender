# SPDX-License-Identifier: GPL-3.0-or-later
"""El trabajo de hash de contenido ``core_content_hash`` (spec 008; RF-008-09; RNF-008-11;
plan 008 §5.3.3, §5.4.1, D6 y D17; ADR-0010; ADR-0025 §2 y §7).

El hash de contenido de una **fuente externa** cuyo lector estima más de 1 s
(``core.content.plan_hash``) se calcula en un trabajo de la 004, no en el hilo de Blender. Nada
del proyecto llega a un trabajo: solo fuentes externas, y sus rutas van en la línea de órdenes
del worker (``JobRunner.submit(paths=…)``, ``--path source_<papel>=<ruta>``), nunca en
``request.json``.

- :func:`new_job` y :func:`job_paths`: la petición del trabajo para una ``HashRequest`` de
  ``core.provenance.checks`` (``params``: ``reader``, ``kind``, ``declarations``, ``settings``,
  ``normalizer``, ``roles`` —el nombre de la ruta de cada papel, ``{"main": "source_main"}``— y
  ``size``, los bytes de la fuente, para la estimación) y sus rutas aparte.
- :func:`run`: la función del trabajo (``WorkerInfo.run``), **la misma** en el hilo de Blender
  y en proceso aparte (``workers/core_content_hash.py`` la envuelve tras registrar los lectores
  de su lista estática). Toma la fuente de ``ctx.paths`` y la lee en su sitio o, si su lector
  lo pide —``needs_copy`` (una base Access), o una fuente SQLite con su ``-wal`` o su
  ``-journal``—, la copia antes a ``in/`` con ``JobDir.copy_input`` (huella antes, durante y
  después: ``source_changed`` si cambia), con su ``-wal`` o su diario junto a ella (y, si el
  fichero principal cambió mientras se copiaban, también ``source_changed``: un volcado del
  ``-wal`` entre las dos copias), con su avance cada MiB en el tramo [0, :data:`COPY_SHARE`]
  (spec 005, T43). Avanza el lector registrado con el progreso (tras una copia, de
  :data:`COPY_SHARE` a 1; si no, de 0 a 1: nunca retrocede) y la cancelación del contexto
  (cada trozo, y cada aviso de la copia, es un punto de cancelación) y devuelve
  ``{"data_sha256", "content_sha256", "normalizer", "reader", "bytes"}`` (``bytes``: lo que
  medía cada fichero leído, por papel; el ``-wal`` como ``main-wal``). Si la fuente ya no está,
  falla con :data:`SOURCE_MISSING`; si su lector no la puede leer, con :data:`UNREADABLE`.
- :data:`WORKER_INFO`: su tipo de trabajo (automático, en el entorno de Blender, con la
  estimación de su lector para el tamaño de la fuente: en un hilo de Blender si cabe en 5 s y,
  si no o no se sabe, en proceso aparte, RF-004-03). Lo registra ``bl/ops/core_provenance.py``.
- :class:`ContentHashJobs`: el ``HashJobs`` de ``core.provenance.checks`` sobre un lanzador de
  trabajos (``JobRunner``): ``submit`` lanza el trabajo (o dice que no, ``None``, y la fuente se
  hashea en el hilo: sin lanzador, sin el tipo de trabajo registrado o con un fichero dentro de
  una ruta prohibida del lanzador, la raíz del proyecto), ``poll`` da su
  ``HashResult`` (:func:`hash_result`) y lo da por incorporado (``mark_ingested``: se borran
  sus copias), y ``cancel`` lo cancela.

Cancelar para en ≤ 2 s (RNF-008-11): el trabajo mira la cancelación antes de copiar, en cada
aviso de la copia verificada y entre dos trozos del lector; si no llega a mirarla, el lanzador
lo termina al vencer su plazo de gracia (:data:`CANCEL_GRACE_S`).

``core`` no importa ``jobs`` (ADR-0004 R4): ``HashRequest`` y ``HashResult`` se importan al
usarlos (importar este módulo no carga las comprobaciones). Python puro (ADR-0004).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from ..core.content.encoder import ContentDigest
from ..core.content.readers import MAIN_ROLE, READERS, ContentReader, ReadRequest, read_steps
from ..core.errors import GeoblenderError
from ..core.gpkg.header import side_file
from ..core.i18n import tr
from ..core.paths import is_within
from .catalog import WORKERS, WorkerInfo
from .messages import JobError, Message
from .paths import JobDir
from .protocol import JobRequest, JsonValue, new_request
from .worker_api import JobFailed

if TYPE_CHECKING:
    from ..core.provenance.checks import HashRequest, HashResult
    from .runner import JobHandle, JobResult, JobRunner

LOGGER = logging.getLogger("geoblender.jobs")

WORKER = "core_content_hash"
"""El nombre del tipo de trabajo (y de su módulo de ``workers/``)."""
OWNER = "core"
"""El módulo dueño de sus trabajos."""
LABEL_MSGID = "Content hash"
"""Su nombre visible (``msgid``; «Hash de contenido»)."""
PATH_PREFIX = "source_"
"""Las rutas de la fuente en la línea de órdenes: ``source_<papel>`` (``source_main``)."""
SIDE_SUFFIXES: tuple[str, ...] = ("-wal", "-journal")
"""Lo que se copia junto a una fuente SQLite: su ``-wal`` o su diario (el ``-shm`` no hace
falta: es un índice en memoria compartida)."""
CANCEL_GRACE_S = 1.0
"""Plazo de gracia de sus trabajos (el mínimo de la 004): cancelar para en ≤ 2 s
(RNF-008-11) también si el worker está copiando la fuente."""
SUCCEEDED = "succeeded"
PARAM_KEYS: frozenset[str] = frozenset(
    {"reader", "kind", "declarations", "settings", "normalizer", "roles", "size"})
"""Los parámetros de su petición (todos obligatorios)."""

SOURCE_MISSING = "content_hash_source_missing"
"""Código del fallo de una fuente que ya no está: la comprobación la da por no localizable."""
UNREADABLE = "content_hash_unreadable"
"""Código del fallo de una fuente que su lector no puede leer."""

COPYING_TEXT = "Copiando la fuente…"
READING_TEXT = "Calculando el hash de contenido…"
COPY_SHARE = 0.1
"""La parte del avance que es la copia verificada de la fuente, si su lector la pide (spec 005,
T43): la lectura sigue desde ahí hasta 1 (sin copia, va de 0 a 1)."""

_CATALOG: tuple[Message, ...] = (
    Message(
        SOURCE_MISSING,
        "The source of job «{job}» no longer exists: {path}.",
        "La fuente del trabajo «{job}» ya no existe: {path}.",
    ),
    Message(
        UNREADABLE,
        "Job «{job}» could not read its source with «{reader}»: {reason}.",
        "El trabajo «{job}» no ha podido leer su fuente con «{reader}»: {reason}.",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in _CATALOG})
"""Los fallos propios del trabajo de hash, por código (solo lectura)."""

_LABELS: tuple[tuple[str, str], ...] = (
    (LABEL_MSGID, "Hash de contenido"),
    ("Content hash of «{name}»", "Hash de contenido de «{name}»"),
)

CATALOG_ES: Mapping[str, str] = MappingProxyType(
    dict(_LABELS) | {m.msgid: m.es for m in _CATALOG})
"""``msgid`` → español de su nombre visible y de sus fallos, para ``core.i18n.install``."""


class _Context(Protocol):
    """Lo que :func:`run` usa del ``WorkerContext`` (``jobs/worker_api.py``)."""

    @property
    def request(self) -> JobRequest: ...

    @property
    def job_dir(self) -> JobDir: ...

    @property
    def paths(self) -> Mapping[str, Path]: ...

    def progress(self, frac: float, msg: str = "") -> None: ...

    def check_cancelled(self) -> None: ...


# --- La petición -------------------------------------------------------------------------------


def path_name(role: str) -> str:
    """El nombre de la ruta del fichero de papel ``role`` en la línea de órdenes."""
    return f"{PATH_PREFIX}{role}"


def new_job(request: HashRequest, *, label: str | None = None) -> JobRequest:
    """La petición del trabajo de hash de la fuente de ``request`` (una ``HashRequest``): sus
    parámetros, sin rutas, con un plazo de gracia de :data:`CANCEL_GRACE_S`; ``label`` (si
    falta, «Hash de contenido de «<entrada>»» en el idioma de Geoblender). ``JobError``
    ``request_invalid`` si algo no es JSON."""
    roles = {role: path_name(role) for role in request.files}
    params: dict[str, Any] = {
        "reader": request.reader,
        "kind": request.kind,
        "declarations": request.declarations,
        "settings": request.settings,
        "normalizer": request.normalizer,
        "roles": roles,
        "size": int(request.size),
    }
    shown = label or tr("Content hash of «{name}»", name=request.name)
    return new_request(WORKER, label=shown, owner=OWNER, params=params,
                       grace_s=CANCEL_GRACE_S)


def job_paths(request: HashRequest) -> dict[str, Path]:
    """Las rutas de los ficheros de la fuente de ``request`` por su nombre en la línea de
    órdenes (``{"source_main": …}``)."""
    return {path_name(role): Path(path) for role, path in request.files.items()}


@dataclass(frozen=True)
class _Params:
    """Los parámetros de una petición del trabajo, comprobados."""

    reader: str
    kind: str
    declarations: Mapping[str, Any]
    settings: Mapping[str, Any]
    normalizer: str
    roles: Mapping[str, str]
    size: int

    @classmethod
    def of(cls, params: Mapping[str, Any], job: str) -> _Params:
        missing = sorted(PARAM_KEYS - set(params))
        extra = sorted(str(key) for key in params if key not in PARAM_KEYS)
        if missing or extra:
            detail = "; ".join(part for part in (
                f"faltan {', '.join(missing)}" if missing else "",
                f"sobran {', '.join(extra)}" if extra else "") if part)
            raise JobError("request_invalid", job=job, detail=detail)
        for key in ("reader", "kind", "normalizer"):
            if not isinstance(params[key], str) or not params[key]:
                raise JobError("request_invalid", job=job, detail=f"«{key}» no es un texto")
        for key in ("declarations", "settings", "roles"):
            if not isinstance(params[key], Mapping):
                raise JobError("request_invalid", job=job,
                               detail=f"«{key}» no es un objeto JSON")
        roles = params["roles"]
        if MAIN_ROLE not in roles or not all(
                isinstance(name, str) and name for name in roles.values()):
            raise JobError("request_invalid", job=job,
                           detail=f"«roles» tiene que nombrar la ruta de cada papel, también "
                                  f"la de «{MAIN_ROLE}»")
        size = params["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise JobError("request_invalid", job=job,
                           detail="«size» no es un número de bytes")
        return cls(params["reader"], params["kind"], params["declarations"],
                   params["settings"], params["normalizer"], roles, size)


def estimate_s(params: Mapping[str, Any]) -> float | None:
    """La duración estimada en s del hash de una fuente de ``params["size"]`` bytes con su
    lector registrado (``ContentReader.estimate_s``); ``None`` si no se sabe (sin lector, sin
    estimación o sin tamaño): va a proceso aparte."""
    found = READERS.get(params.get("reader"))  # type: ignore[arg-type]
    size = params.get("size")
    if found is None or found.estimate_s is None:
        return None
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        return None
    value = found.estimate_s(size)
    return None if value is None else float(value)


# --- La función del trabajo -----------------------------------------------------------------


def run(ctx: _Context) -> dict[str, JsonValue]:
    """El hash de contenido de la fuente de la petición (véase el módulo). ``JobError``
    ``request_invalid`` si la petición no vale o falta una ruta; :class:`JobFailed`
    :data:`SOURCE_MISSING` o :data:`UNREADABLE`; ``JobError`` ``source_changed`` si cambia
    mientras se copia; ``JobCancelled`` si se pide parar."""
    request = ctx.request
    job = _job_name(request)
    params = _Params.of(request.params, job)
    found = READERS.get(params.reader)
    if found is None:
        raise JobError("request_invalid", job=job,
                       detail=f"el lector «{params.reader}» no está en la lista de este trabajo")
    files: dict[str, Path] = {}
    for role, name in params.roles.items():
        path = ctx.paths.get(name)
        if path is None:
            raise JobError("request_invalid", job=job,
                           detail=f"falta la ruta «{name}» del fichero «{role}» (--path)")
        files[role] = Path(path)
    ctx.check_cancelled()
    sides = _sides(files[MAIN_ROLE]) if found.sqlite else {}
    sizes: dict[str, JsonValue] = {}
    for key, path in (*files.items(), *((f"{MAIN_ROLE}{s}", p) for s, p in sides.items())):
        try:
            sizes[key] = path.stat().st_size
        except FileNotFoundError:
            raise _missing(job, path) from None
        if not path.is_file():
            raise _missing(job, path)
    start = 0.0
    if found.needs_copy or sides:
        ctx.progress(0.0, COPYING_TEXT)
        files = _copies(ctx, files, sides, job, sizes)
        start = COPY_SHARE
    try:
        read = found.request(params.kind, params.declarations, files, params.settings,
                             normalizer=params.normalizer)
    except (GeoblenderError, ValueError, TypeError) as exc:
        raise JobError("request_invalid", job=job, detail=str(exc)) from None
    digest = _read(ctx, found, read, job, start)
    return {
        "data_sha256": digest.data_sha256,
        "content_sha256": digest.content_sha256,
        "normalizer": digest.normalizer,
        "reader": digest.reader,
        "bytes": sizes,
    }


def _sides(main: Path) -> dict[str, Path]:
    """El ``-wal`` y el diario que tiene ahora junto a sí la fuente SQLite ``main``."""
    return {suffix: side_file(main, suffix) for suffix in SIDE_SUFFIXES
            if side_file(main, suffix).is_file()}


def _copies(ctx: _Context, files: Mapping[str, Path], sides: Mapping[str, Path],
            job: str, sizes: Mapping[str, JsonValue]) -> dict[str, Path]:
    """Las copias verificadas de la fuente en ``in/`` (``in/source_<papel><extensión>``), con
    el ``-wal`` o el diario de la principal junto a su copia (``in/source_main.gpkg-wal``),
    con su avance (:class:`_Copying`; ``sizes``, los bytes de cada fichero como en el
    resumen)."""
    folder = ctx.job_dir
    main = files[MAIN_ROLE]
    before = _stamp(main)
    copying = _Copying(ctx, sizes)
    copies = {role: folder.path / folder.copy_input(path, path_name(role), job=job,
                                                    progress=copying.file(role))
              for role, path in files.items()}
    for suffix, path in sides.items():
        ctx.check_cancelled()
        copy = folder.path / folder.copy_input(path, path_name(MAIN_ROLE), job=job,
                                               progress=copying.file(f"{MAIN_ROLE}{suffix}"))
        if copy != side_file(copies[MAIN_ROLE], suffix):
            raise JobError("request_invalid", job=job,
                           detail=f"la fuente SQLite «{main.name}» no tiene extensión: no se "
                                  f"puede copiar con su «{suffix}»")
    if sides and _stamp(main) != before:
        raise JobError("source_changed", job=job, path=main)
    return copies


class _Copying:
    """El avance de las copias verificadas de una fuente (``JobDir.copy_input`` avisa tras
    cada MiB de sus tres lecturas): sus ficheros (``sizes``: los bytes de cada uno, por
    papel), uno tras otro y cada uno por su tamaño, en el tramo [0, :data:`COPY_SHARE`] con
    :data:`COPYING_TEXT`. Cada aviso es un punto de cancelación (``ctx.progress``): una fuente
    grande o en la red no deja de avisar ni de poder pararse mientras se copia (spec 005,
    T43; RNF-008-11)."""

    def __init__(self, ctx: _Context, sizes: Mapping[str, JsonValue]) -> None:
        self._ctx = ctx
        self._sizes = {key: max(1, int(value)) for key, value in sizes.items()
                       if isinstance(value, int) and not isinstance(value, bool)}
        self._total = sum(self._sizes.values()) or 1
        self._done = 0

    def file(self, key: str) -> Callable[[float], None]:
        """``progress(fracción)`` de la copia del fichero ``key`` (la siguiente)."""
        size = self._sizes.get(key, 1)
        offset = self._done
        self._done += size

        def progress(fraction: float) -> None:
            done = (offset + min(1.0, max(0.0, fraction)) * size) / self._total
            self._ctx.progress(COPY_SHARE * min(1.0, done), COPYING_TEXT)

        return progress


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_size, info.st_mtime_ns


def _read(ctx: _Context, found: ContentReader, request: ReadRequest,
          job: str, start: float = 0.0) -> ContentDigest:
    """Avanza el lector con el progreso (de ``start``, tras la copia, a 1) y la cancelación
    del contexto."""
    steps = read_steps(found, request)
    try:
        ctx.check_cancelled()
        for done in steps:
            ctx.progress(start + (1.0 - start) * done, READING_TEXT)
    except FileNotFoundError as exc:
        raise _missing(job, Path(exc.filename or request.files[MAIN_ROLE])) from None
    except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
        raise _failed(UNREADABLE, job=job, reader=found.id, reason=str(exc)) from None
    finally:
        steps.close()
    return request.hasher.digest()


def _missing(job: str, path: Path) -> JobFailed:
    return _failed(SOURCE_MISSING, job=job, path=str(path))


def _failed(code: str, **values: JsonValue) -> JobFailed:
    message = MESSAGES[code]
    return JobFailed(code, msgid=message.msgid, text=message.es.format(**values),
                     values=values)


def _job_name(request: JobRequest) -> str:
    for candidate in (request.label, request.worker, request.job_uid):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return WORKER


WORKER_INFO = WorkerInfo(
    WORKER,
    LABEL_MSGID,
    policy="auto",
    environment="blender",
    estimate_s=estimate_s,
    run=run,
)
"""El tipo de trabajo ``core_content_hash`` (plan §5.3.3), para ``jobs.catalog.register_worker``
desde ``bl``."""


# --- Los trabajos de hash de la comprobación ---------------------------------------------------


def hash_result(result: JobResult) -> HashResult:
    """El ``HashResult`` de ``core.provenance.checks`` con que terminó un trabajo de hash: su
    hash si terminó bien; ``gone`` si la fuente ya no estaba (:data:`SOURCE_MISSING`); si no,
    el error (con su texto en español: lo que falló, se canceló o se interrumpió)."""
    from ..core.provenance.checks import HashResult

    if result.state == SUCCEEDED:
        summary = result.summary
        try:
            digest = ContentDigest(summary["data_sha256"], summary["content_sha256"],
                                   summary["normalizer"], summary["reader"])
        except (KeyError, TypeError, ValueError) as exc:
            return HashResult(error=f"el trabajo de hash terminó sin un hash válido ({exc})")
        return HashResult(digest=digest)
    if result.error_code == SOURCE_MISSING:
        return HashResult(gone=True)
    return HashResult(error=result.error_text or result.error_code or result.state)


type Submit = Callable[["JobRunner", JobRequest, Mapping[str, Path]], "JobHandle"]
"""Cómo se lanza un trabajo: ``submit(lanzador, petición, rutas) -> JobHandle``."""


def _runner_submit(runner: JobRunner, request: JobRequest,
                   paths: Mapping[str, Path]) -> JobHandle:
    return runner.submit(request, paths=paths)


class ContentHashJobs:
    """Los trabajos de hash de las fuentes externas grandes (el ``HashJobs`` de
    ``core.provenance.checks``) sobre el lanzador que da ``runner()`` (``None``: ninguno).
    ``submit`` lanza cada uno con ``submit(lanzador, petición, rutas)`` (por defecto,
    ``JobRunner.submit``; ``bl`` pasa el de su monitor, que lo sigue en la barra de estado).
    Sus resguardos son los ``JobHandle`` del lanzador."""

    def __init__(self, runner: Callable[[], JobRunner | None], *,
                 submit: Submit | None = None) -> None:
        self._runner = runner
        self._submit = _runner_submit if submit is None else submit

    def submit(self, request: HashRequest) -> JobHandle | None:
        """Lanza el trabajo de hash de la fuente de ``request``; ``None`` (se hashea en el hilo)
        sin lanzador abierto, sin el tipo de trabajo registrado, con un fichero dentro de una
        ruta prohibida del lanzador (la raíz del proyecto: nada del proyecto llega a un
        trabajo) o si no se puede lanzar."""
        runner = self._runner()
        if runner is None or runner.closed or WORKER not in WORKERS:
            return None
        files = job_paths(request)
        if any(is_within(path, root) for path in files.values()
               for root in runner.forbidden_roots):
            return None
        try:
            return self._submit(runner, new_job(request), files)
        except (GeoblenderError, ValueError, OSError, RuntimeError):
            LOGGER.warning("No se pudo lanzar el hash de contenido de «%s»: se hará en el "
                           "hilo", request.name, exc_info=True)
            return None

    def poll(self, ticket: JobHandle) -> HashResult | None:
        """Cómo terminó el trabajo (``None`` mientras sigue). Al recogerlo, queda incorporado
        (``mark_ingested``: se borran su copia y sus resultados)."""
        result = ticket.result()
        if result is None:
            return None
        runner = self._runner()
        if runner is not None:
            try:
                runner.mark_ingested(ticket.job_uid)
            except (ValueError, OSError):
                LOGGER.debug("El trabajo de hash %s no se pudo dar por incorporado",
                             ticket.job_uid, exc_info=True)
        return hash_result(result)

    def cancel(self, ticket: JobHandle) -> None:
        """Pide parar el trabajo (al cerrar la comprobación a medias)."""
        try:
            ticket.cancel()
        except (ValueError, OSError, RuntimeError):
            LOGGER.warning("No se pudo cancelar el trabajo de hash %s", ticket.job_uid,
                           exc_info=True)
