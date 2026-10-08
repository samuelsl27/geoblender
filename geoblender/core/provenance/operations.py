# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de las operaciones en dos pasos (spec 008; RF-008-04, RF-008-05, RF-008-18,
RF-008-19, RF-008-23, RF-008-51; ADR-0025 §3; plan 008 §5.3.1, §5.3.4 y §5.4.7).

Toda operación que produce resultados (cálculo, importación, edición o exportación) se
registra en ``gb_operation`` **en dos pasos** (ADR-0025 §3); los módulos nunca escriben en las
tablas ``gb_*``, llaman a esta API:

1. :func:`begin_operation`, antes de ejecutarla y en su propia transacción: la deja «en curso»
   con su tipo y la versión de su algoritmo (de su :class:`~.contract.OperationDef`), sus
   ajustes (JSON canónico y su huella), los parámetros que lee resueltos por su ámbito
   (RF-008-05; los que el proyecto aún no tiene, registrados antes con su valor por defecto
   «sin confirmar» en **esa misma transacción**, RF-008-04), cada dato o entrada que consume
   con su hash de contenido y su papel (:class:`Use`), quién la lanza, cuándo, desde qué
   sesión y en qué equipo, y la versión de Geoblender (RF-008-51).
2. :meth:`OperationHandle.complete`, en la transacción **del módulo**, la que escribe sus
   resultados (el punto de confirmación): registra cada salida (``core.datasets``: un dato
   nuevo o el contenido nuevo de uno vivo con su nombre, con su hash y su papel) y cada cifra
   (:mod:`.figures`, RF-008-30), y la deja «hecha» con las versiones de las bibliotecas que
   influyen en sus cifras, dónde se ejecutó (hilo de Blender o trabajo de la 004, con su
   identificador y su intérprete) y su mensaje (RF-008-18). No confirma: si la transacción
   del módulo se deshace, no queda nada de la operación terminada y sigue «en curso». Un
   resultado que no está guardado en el proyecto (un fichero que solo está en la caché o en
   la carpeta de un trabajo, una tabla que no se escribió) no se acepta (RF-008-23). Si
   sustituye a otra (un recálculo, una reimportación), la anota en ella (``superseded_by``),
   una vez.

Mientras tanto, :meth:`OperationHandle.claim_paths` reclama los ficheros del proyecto que
escribe (temporales y finales), para que el barrido de restos no los aparte: constan en
:func:`claimed_paths` mientras la operación está «en curso» en el proyecto (ADR-0025 §3). En el
hilo de Blender, :func:`operation` hace los dos pasos como gestor de contexto: si el bloque
falla, la operación queda «fallida» con el motivo (o «cancelada», si se paró una lectura o una
huella: :data:`CANCELLATIONS`); si termina sin completar el registro, «fallida», y lo dice
(``core.operation_not_completed``).

Una operación que no termina bien queda registrada sin salidas, como auditoría, y nunca deja
un dato registrado como bueno (RF-008-19; sus salidas solo se registran al completarla):

- :meth:`OperationHandle.fail` y :meth:`OperationHandle.cancel`: «fallida» o «cancelada» con
  el motivo, en su propia transacción;
- :func:`interrupt_orphaned`, al abrir en escritura: «interrumpida», con su evento, toda
  operación «en curso» de otra sesión, que ya no tiene el cerrojo y no pudo registrar su final
  (Blender se cerró, cayó la red de ``Z:`` u otro equipo forzó el cerrojo);
- :func:`mark_not_ingested`: «no incorporada», con el motivo y su evento, la operación «en
  curso» cuyo trabajo de la 004 se borró sin incorporarlo (RF-008-23).

Todo se comprueba **antes** de escribir: un rechazo para el usuario es un
:class:`~.messages.ProvenanceError` (o el ``ParamError`` / ``ValidationError`` de los
parámetros y los datos) y un error del programa, :class:`ValueError` o :class:`TypeError`;
ninguno deja el proyecto en solo lectura. En solo lectura, todo lo que escribiría lanza
``core.read_only`` sin tocar nada.

``complete`` pone al día, en la misma transacción, la caché de la obsolescencia por región
(:mod:`.stale`). Pendiente de otras tareas de la 008: la puerta antes de operar
(``gate.can_run``, T30) e incorporar un trabajo (``ingest_job``, T31). Python puro (ADR-0004):
al importarse no importa ``core.project`` (que importa ``core.provenance.schema``); sus
eventos, solo al registrarlos.
"""

from __future__ import annotations

import json
import ntpath
import os
import re
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import KW_ONLY, dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from ..content.readers import ReadCancelled
from ..datasets import registry as dataset_registry
from ..datasets.model import DatasetRecord, DatasetSpec, Store
from ..datasets.tracking import table_states
from ..errors import GeoblenderError
from ..hashing import HashCancelled, canonical_json, sha256_bytes
from ..ids import new_uid
from ..params.store import ParameterStore, ResolvedParam
from ..paths import ABSOLUTE_PATH, find_absolute_paths
from ..timeutil import Clock, format_utc
from .contract import OperationDef, operation_def
from .figures import FigureSpec, prepare_figures, write_figures
from .messages import ProvenanceError
from .schema import INACTIVE_INPUT_STATUSES, RUNNING
from .stale import refresh_region

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo


class OperationStatus(StrEnum):
    """El estado de una operación (``gb_operation.status``)."""

    RUNNING = "running"  # en curso: registrada al empezar (RF-008-51)
    DONE = "done"  # hecha, con sus salidas (RF-008-18)
    CANCELLED = "cancelled"  # cancelada (RF-008-19)
    FAILED = "failed"  # fallida (RF-008-19)
    INTERRUPTED = "interrupted"  # interrumpida: su sesión perdió el cerrojo (RF-008-19)
    NOT_INGESTED = "not_ingested"  # su trabajo se borró sin incorporarlo (RF-008-23)


class Executor(StrEnum):
    """Dónde se ejecuta una operación (``gb_operation.executor``; RF-008-18)."""

    BLENDER = "blender"  # en el hilo de Blender
    JOB_THREAD = "job_thread"  # en un trabajo de la 004, en un hilo
    JOB_PROCESS = "job_process"  # en un trabajo de la 004, en un proceso aparte
    EXTERNAL = "external"  # fuera de Geoblender (una edición de QGIS, D9)


JOB_EXECUTORS: tuple[Executor, ...] = (Executor.JOB_THREAD, Executor.JOB_PROCESS)
"""Los ejecutores de un trabajo de la 004: llevan su identificador (``job_uid``)."""


class ItemKind(StrEnum):
    """Lo que consume o produce una operación (``gb_operation_io.item_kind``)."""

    DATASET = "dataset"  # un dato del proyecto (``gb_dataset``)
    INPUT = "input"  # una entrada registrada (``gb_input``)


READ_ONLY_PREFIX = "Solo lectura: "
"""El principio del estado de un proyecto en solo lectura (``core.project.session``), que se
quita para nombrar el motivo en ``core.read_only``."""
NOT_COMPLETED_REASON = (
    "terminó sin completar su registro (OperationHandle.complete): sus resultados no se dan "
    "por buenos"
)
"""El motivo de una operación de :func:`operation` cuyo bloque termina sin completarla."""
FAILURE_REASON_PREFIX = "error durante la operación: "
"""El principio del motivo de una operación de :func:`operation` cuyo bloque falla."""
CANCEL_REASON_PREFIX = "cancelada durante la operación: "
"""El principio del motivo de una operación de :func:`operation` cuyo bloque se para por una
cancelación (:data:`CANCELLATIONS`)."""
INTERRUPTED_REASON = (
    "la sesión de {user_host} que la ejecutaba ya no tiene el cerrojo del proyecto (Blender se "
    "cerró, se cayó la red u otro equipo forzó el cerrojo) y no pudo registrar su final"
)
"""El motivo de una operación «interrumpida» (:func:`interrupt_orphaned`), con «usuario@equipo»
de su sesión."""
MAX_REASON_CHARS = 500
"""Largo máximo del motivo que se guarda (el resto se corta con «…»)."""

CANCELLATIONS: tuple[type[BaseException], ...] = (ReadCancelled, HashCancelled)
"""Los errores con los que se para una lectura o una huella a petición de la persona (entre
dos trozos): en :func:`operation`, la operación queda «cancelada», no «fallida». Un trabajo de
la 004 cancelado lo traduce quien lo incorpora (``ingest_job``, T31)."""

_ROLE = re.compile(r"[a-z][a-z0-9_]*")


class OperationProject(Protocol):
    """Lo que las operaciones usan del proyecto (``core.project.Project``): su identidad, su
    raíz y su base, el reloj, la sesión (quién, desde qué equipo y con qué Geoblender), si se
    puede escribir y por qué no, y sus conexiones de lectura y de escritura."""

    @property
    def uid(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def root(self) -> Path: ...

    @property
    def database_path(self) -> Path: ...

    @property
    def clock(self) -> Clock: ...

    @property
    def session(self) -> SessionInfo: ...

    @property
    def writable(self) -> bool: ...

    @property
    def closed(self) -> bool: ...

    @property
    def status(self) -> Any: ...

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...

    def write_transaction(self) -> AbstractContextManager[sqlite3.Connection]: ...


# --- Lo que consume una operación ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Use:
    """Un dato o una entrada que consume una operación, con su papel (``"terrain"``,
    ``"boundary"``…; ``gb_operation_io.role``). ``item`` es su uid o su nombre: el de un dato
    vivo o el nombre lógico de una entrada activa. ``kind``: :attr:`ItemKind.DATASET` (por
    defecto) o :attr:`ItemKind.INPUT`."""

    item: str
    role: str
    _: KW_ONLY
    kind: ItemKind = ItemKind.DATASET

    def __post_init__(self) -> None:
        if not isinstance(self.item, str):
            raise TypeError(f"lo que consume una operación se indica por su uid o su nombre, "
                            f"no {self.item!r}")
        if not self.item.strip():
            raise ValueError("lo que consume una operación no puede quedar vacío")
        if not isinstance(self.role, str) or _ROLE.fullmatch(self.role) is None:
            raise ValueError(f"el papel de lo que consume una operación es un nombre en "
                             f"minúsculas («terrain»), no {self.role!r}")
        try:
            kind = ItemKind(self.kind)
        except ValueError:
            raise ValueError(f"una operación consume un dato o una entrada "
                             f"({', '.join(ItemKind)}), no {self.kind!r}") from None
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True, slots=True)
class Consumed:
    """Lo que anotó una operación al empezar de cada cosa que consume: su clase, su uid, su
    nombre, su hash de contenido y su papel (``gb_operation_io``, ``direction = 'in'``)."""

    kind: ItemKind
    uid: str
    name: str
    content_sha256: str
    role: str


# --- Comprobaciones -----------------------------------------------------------------------


def _no_paths(what: str, value: object) -> None:
    """Ninguna ruta absoluta en lo que se guarda en el proyecto (ADR-0006 §5)."""
    found = find_absolute_paths(value)
    if found:
        raise ValueError(f"{what} de una operación no pueden llevar rutas absolutas: se guardan "
                         f"en el proyecto (ADR-0006 §5): {found}")


def _sequence(value: object, what: str) -> tuple[Any, ...]:
    if isinstance(value, str | bytes | Mapping) or not isinstance(value, Iterable):
        raise TypeError(f"{what} de una operación son una lista, no {value!r}")
    return tuple(value)


def _optional_text(value: object, what: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    if not value.strip():
        raise ValueError(f"{what} no puede quedar vacío")
    return value


def _settings(settings: object) -> str:
    """Los ajustes de la orden como JSON canónico (sin rutas absolutas)."""
    if not isinstance(settings, Mapping):
        raise TypeError(f"los ajustes de una operación son un diccionario, no {settings!r}")
    text = canonical_json(dict(settings)).decode("utf-8")
    _no_paths("los ajustes", json.loads(text))
    return text


def _executor(value: object) -> Executor:
    if not isinstance(value, str):
        raise TypeError(f"el ejecutor de una operación es un texto, no {value!r}")
    try:
        return Executor(value)
    except ValueError:
        raise ValueError(f"el ejecutor de una operación es uno de {', '.join(Executor)}, no "
                         f"{value!r}") from None


def _check_job(executor: Executor, job_uid: str | None, *, required: bool) -> None:
    """Un trabajo de la 004 lleva su identificador (al completar; al empezar aún puede no
    tenerlo) y lo demás no lo lleva."""
    if executor in JOB_EXECUTORS:
        if job_uid is None and required:
            raise ValueError(f"una operación ejecutada en un trabajo ({executor}) lleva su "
                             "identificador (job_uid) al completarse (RF-008-18)")
    elif job_uid is not None:
        raise ValueError(f"solo una operación de un trabajo lleva job_uid, no una "
                         f"«{executor}» ({job_uid!r})")


def _group_uid(definition: OperationDef, group_uid: object) -> str | None:
    """La ejecución del grupo acoplado: la dada, o una nueva si la operación es de un grupo
    (la primera de esa ejecución); ninguna si no es de un grupo."""
    chosen = _optional_text(group_uid, "la ejecución del grupo (group_uid)")
    if definition.group is None:
        if chosen is not None:
            raise ValueError(f"la operación «{definition.op_type}» no es de ningún grupo "
                             f"acoplado: no lleva group_uid ({chosen!r})")
        return None
    return new_uid() if chosen is None else chosen


def _uses(inputs: object) -> tuple[Use, ...]:
    uses = _sequence(inputs, "las entradas (inputs)")
    for use in uses:
        if not isinstance(use, Use):
            raise TypeError(f"lo que consume una operación se declara con Use, no {use!r}")
    return uses


def _keys(params: object) -> tuple[str, ...]:
    keys = _sequence(params, "los parámetros (params)")
    for key in keys:
        if not isinstance(key, str):
            raise TypeError(f"un parámetro se indica por su clave, no {key!r}")
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    if repeated:
        raise ValueError(f"una operación lee cada parámetro una vez: {repeated} se repite")
    return keys


def _software(definition: OperationDef, software: object) -> str:
    """Las versiones de las bibliotecas que influyen en sus cifras (RF-008-18): las que
    declara su :class:`~.contract.OperationDef`, todas y solas, como JSON canónico."""
    given: object = {} if software is None else software
    if not isinstance(given, Mapping):
        raise TypeError(f"las bibliotecas de una operación son {{nombre: versión}}, no "
                        f"{software!r}")
    values = dict(given)
    for name, version in values.items():
        if not isinstance(name, str) or not isinstance(version, str):
            raise TypeError(f"cada biblioteca es nombre: versión, en texto, no "
                            f"{name!r}: {version!r}")
        if not version.strip():
            raise ValueError(f"falta la versión de la biblioteca «{name}»")
    declared = definition.libraries
    missing = [name for name in declared if name not in values]
    extra = sorted(name for name in values if name not in declared)
    if missing or extra:
        raise ValueError(
            f"la operación «{definition.op_type}» declara que influyen en sus cifras "
            f"{list(declared)!r} (OperationDef.libraries): falta la versión de {missing!r} y "
            f"sobran {extra!r}"
        )
    _no_paths("las bibliotecas", values)
    return canonical_json(values).decode("utf-8")


def _interpreter(interpreter: object) -> str | None:
    """El intérprete de un trabajo (``InterpreterInfo`` de la 004) como JSON canónico."""
    if interpreter is None:
        return None
    if not isinstance(interpreter, Mapping):
        raise TypeError(f"el intérprete de una operación es un diccionario, no "
                        f"{interpreter!r}")
    text = canonical_json(dict(interpreter)).decode("utf-8")
    _no_paths("el intérprete", json.loads(text))
    return text


def _message(message: object) -> str | None:
    if message is None:
        return None
    if not isinstance(message, str):
        raise TypeError(f"el mensaje de una operación es un texto, no {message!r}")
    _no_paths("el mensaje", message)
    return message if message.strip() else None


def _outputs(outputs: object) -> tuple[DatasetSpec, ...]:
    specs = _sequence(outputs, "las salidas (outputs)")
    for spec in specs:
        if not isinstance(spec, DatasetSpec):
            raise TypeError(f"una salida se declara con DatasetSpec, no {spec!r}")
    names = [spec.name for spec in specs]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValueError(f"una operación escribe cada dato una vez: {repeated} se repite")
    return specs


def _in_transaction(conn: object, what: str) -> sqlite3.Connection:
    """La conexión de una transacción de escritura abierta por quien llama."""
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError(f"{what} recibe la conexión de una transacción de escritura, no "
                        f"{conn!r}")
    if not conn.in_transaction:
        raise ValueError(f"{what} se llama dentro de una transacción de escritura "
                         "(Project.write_transaction)")
    return conn


def _require_writable(project: OperationProject) -> None:
    """En solo lectura no se registra nada (``core.read_only``, plan §5.3.1)."""
    if project.writable:
        return
    if project.closed:
        reason = "cerrado"
    else:
        reason = str(project.status.message).removeprefix(READ_ONLY_PREFIX)
    raise ProvenanceError("core.read_only", project=project.name, reason=reason)


# --- Lecturas del registro ----------------------------------------------------------------


def _check_supersedes(conn: sqlite3.Connection, definition: OperationDef,
                      previous: str) -> None:
    """Solo se sustituye una operación hecha, una vez (``superseded_by`` se escribe una vez):
    ni una ya sustituida ni una que otra «en curso» está sustituyendo."""
    row = conn.execute("SELECT status, superseded_by FROM gb_operation WHERE uid = ?",
                       (previous,)).fetchone()
    values = {"op_type": definition.op_type, "supersedes": previous}
    if row is None:
        raise ProvenanceError("core.operation_supersedes_unknown", **values)
    if row[0] != OperationStatus.DONE:
        raise ProvenanceError("core.operation_supersedes_not_done", **values)
    other = conn.execute(
        "SELECT 1 FROM gb_operation WHERE supersedes_uid = ? AND status IN (?, ?)",
        (previous, str(OperationStatus.RUNNING), str(OperationStatus.DONE)),
    ).fetchone()
    if row[1] is not None or other is not None:
        raise ProvenanceError("core.operation_already_superseded", **values)


def _resolve_use(conn: sqlite3.Connection, definition: OperationDef, use: Use) -> Consumed:
    """Lo que consume ``use`` con su hash de contenido actual. Lo sustituido o descartado
    queda como historia y no se consume (su sucesor, sí)."""
    values = {"op_type": definition.op_type, "item": use.item}
    if use.kind is ItemKind.DATASET:
        record = dataset_registry.get(conn, use.item)
        if record is None:
            raise ProvenanceError("core.operation_dataset_unknown", **values)
        if not record.live:
            raise ProvenanceError("core.operation_dataset_not_live", **values)
        return Consumed(ItemKind.DATASET, record.uid, record.name, record.content_sha256,
                        use.role)
    columns = "uid, name, content_sha256, status"
    row = conn.execute(f"SELECT {columns} FROM gb_input WHERE uid = ?", (use.item,)).fetchone()
    if row is None:
        marks = ", ".join("?" for _ in INACTIVE_INPUT_STATUSES)
        row = conn.execute(
            f"SELECT {columns} FROM gb_input WHERE name = ? AND status NOT IN ({marks})",
            (use.item, *INACTIVE_INPUT_STATUSES),
        ).fetchone()
    if row is None:
        raise ProvenanceError("core.operation_input_unknown", **values)
    if row[3] in INACTIVE_INPUT_STATUSES:
        raise ProvenanceError("core.operation_input_not_live", **values)
    return Consumed(ItemKind.INPUT, str(row[0]), str(row[1]), str(row[2]), use.role)


def _check_repeated(consumed: Sequence[Consumed]) -> None:
    seen: set[tuple[str, str, str]] = set()
    for item in consumed:
        key = (str(item.kind), item.uid, item.role)
        if key in seen:
            raise ValueError(f"una operación consume «{item.name}» con el papel «{item.role}» "
                             "una sola vez")
        seen.add(key)


def _statuses(conn: sqlite3.Connection, uids: Sequence[str]) -> dict[str, str]:
    if not uids:
        return {}
    marks = ", ".join("?" for _ in uids)
    return {
        str(uid): str(status)
        for uid, status in conn.execute(
            f"SELECT uid, status FROM gb_operation WHERE uid IN ({marks})", tuple(uids)
        )
    }


def _check_saved(conn: sqlite3.Connection, project: OperationProject, op_type: str,
                 specs: Sequence[DatasetSpec]) -> None:
    """Cada salida está guardada en el proyecto antes de completar (RF-008-23): su tabla en
    ``project.gpkg`` (registrada en ``gpkg_contents``) o su fichero en su carpeta. Un modelo
    de ``blocks.duckdb`` lo comprueba su módulo con su hash."""
    tables = [spec.locator for spec in specs if spec.store is Store.GPKG]
    states = table_states(conn, tables) if tables else {}
    for spec in specs:
        if spec.store is Store.GPKG:
            state = states[spec.locator]
            saved = state.registered and state.exists
        elif spec.store is Store.DUCKDB:
            saved = True
        else:
            saved = Path(project.root, *spec.locator.split("/")).is_file()
        if not saved:
            raise ProvenanceError("core.operation_output_not_saved", name=spec.name,
                                  op_type=op_type, locator=spec.locator)


# --- Rutas reclamadas ---------------------------------------------------------------------

_LOCK = threading.Lock()
_HANDLES: dict[str, OperationHandle] = {}


def _handles_of(project: OperationProject) -> list[OperationHandle]:
    """Las operaciones abiertas de este proceso en ``project`` con su sesión."""
    session = project.session.session_uid
    with _LOCK:
        return [
            handle for handle in _HANDLES.values()
            if handle.project_uid == project.uid and handle.session_uid == session
        ]


def _forget(handle: OperationHandle) -> None:
    with _LOCK:
        handle._closed = True
        _HANDLES.pop(handle.uid, None)


def _prune(project: OperationProject, conn: sqlite3.Connection) -> None:
    """Olvida las operaciones de ``project`` que ya no están «en curso» en lo confirmado
    (``conn`` recién abierta) y las de proyectos ya cerrados."""
    with _LOCK:
        closed = [handle for handle in _HANDLES.values() if handle.project.closed]
    for handle in closed:
        _forget(handle)
    handles = _handles_of(project)
    statuses = _statuses(conn, [handle.uid for handle in handles])
    for handle in handles:
        if statuses.get(handle.uid) != OperationStatus.RUNNING:
            _forget(handle)


def _claim(root: str, path: object) -> Path:
    raw = os.fspath(path)  # type: ignore[arg-type]
    if not isinstance(raw, str):
        raise TypeError(f"una ruta reclamada es un texto o una ruta, no {path!r}")
    full = os.path.normpath(os.path.join(root, raw))
    outer = os.path.normcase(root).rstrip("\\/")
    if not os.path.normcase(full).startswith(outer + os.sep):
        raise ValueError(f"una operación solo reclama ficheros dentro del proyecto, no "
                         f"{raw!r}")
    return Path(full)


def claimed_paths(project: OperationProject, *,
                  conn: sqlite3.Connection | None = None) -> frozenset[Path]:
    """Las rutas que reclaman las operaciones de esta sesión en ``project`` que siguen «en
    curso» según ``conn`` (sin ella, una conexión de lectura: lo confirmado). El barrido de
    restos no las aparta (RF-008-22; ADR-0025 §3)."""
    handles = _handles_of(project)
    if not handles:
        return frozenset()
    reading = nullcontext(conn) if conn is not None else project.read()
    with reading as opened:
        statuses = _statuses(opened, [handle.uid for handle in handles])
    found: set[Path] = set()
    for handle in handles:
        if statuses.get(handle.uid) == OperationStatus.RUNNING:
            found |= handle.claims
    return frozenset(found)


# --- La operación en curso ----------------------------------------------------------------


class OperationHandle:
    """Una operación registrada «en curso» por :func:`begin_operation`: su uid, su tipo
    (:attr:`definition`), lo que anotó al empezar (:attr:`inputs`, :attr:`params`,
    :attr:`settings`…), las rutas que reclama y :meth:`complete`."""

    def __init__(
        self,
        project: OperationProject,
        definition: OperationDef,
        uid: str,
        *,
        settings: str,
        group_uid: str | None,
        supersedes: str | None,
        executor: Executor,
        job_uid: str | None,
        started_at: str,
        inputs: tuple[Consumed, ...],
        params: tuple[ResolvedParam, ...],
    ) -> None:
        self.project = project
        self.project_uid = project.uid
        self.session_uid = project.session.session_uid
        self.definition = definition
        self.uid = uid
        self.settings: Mapping[str, Any] = MappingProxyType(json.loads(settings))
        self.group_uid = group_uid
        self.supersedes = supersedes
        self.executor = executor
        self.job_uid = job_uid
        self.started_at = started_at
        self.inputs = inputs
        self.params = params
        self._claims: set[Path] = set()
        self._closed = False

    def __repr__(self) -> str:
        return f"<OperationHandle {self.op_type} {self.uid}>"

    @property
    def op_type(self) -> str:
        """El tipo de la operación (``res.balance``)."""
        return self.definition.op_type

    @property
    def claims(self) -> frozenset[Path]:
        """Las rutas que reclama (absolutas, normalizadas, dentro del proyecto)."""
        with _LOCK:
            return frozenset(self._claims)

    def claim_paths(self, *paths: str | os.PathLike[str]) -> None:
        """Reclama los ficheros del proyecto que escribe la operación, temporales y finales
        (relativos a la raíz del proyecto o absolutos dentro de él): mientras esté «en curso»,
        el barrido de restos no los aparta (ADR-0025 §3). :class:`ValueError` con una ruta
        fuera del proyecto; :class:`RuntimeError` si :func:`operation` ya la cerró."""
        root = os.path.normpath(os.fspath(self.project.root))
        found = [_claim(root, path) for path in paths]
        with _LOCK:
            if self._closed:
                raise RuntimeError(f"la operación «{self.op_type}» ({self.uid}) ya terminó: no "
                                   "reclama rutas")
            self._claims.update(found)

    def complete(
        self,
        conn: sqlite3.Connection,
        *,
        outputs: Sequence[DatasetSpec] = (),
        figures: Sequence[FigureSpec] = (),
        software: Mapping[str, str] | None = None,
        interpreter: Mapping[str, Any] | None = None,
        message: str | None = None,
        executor: Executor | str | None = None,
        job_uid: str | None = None,
    ) -> tuple[DatasetRecord, ...]:
        """Termina la operación en la transacción del módulo ``conn`` (la que escribe sus
        resultados; no la confirma) y devuelve sus salidas registradas, en su orden
        (RF-008-18):

        - cada salida de ``outputs`` (``DatasetSpec``) ya guardada en el proyecto, como dato
          nuevo o como contenido nuevo del dato vivo con su nombre, con su hash y su papel;
        - cada cifra de ``figures`` (``FigureSpec``), con su tipo, su unidad y su ámbito
          (RF-008-30; :func:`~.figures.record_figure`): las que calculan un parámetro dejan
          su aviso si difieren de él (:func:`~.figures.divergences`), y ningún parámetro
          cambia (RF-008-59);
        - «hecha», con su hora, ``software`` (la versión de cada biblioteca que declara su
          ``OperationDef.libraries``, todas y solas), ``executor`` y ``job_uid`` (si cambian
          desde el principio; un trabajo lleva su identificador), ``interpreter`` (el de un
          trabajo de la 004) y ``message``;
        - si sustituye a otra, la anota en ella (``superseded_by``);
        - la obsolescencia por región de ella y de lo que leía lo que escribió, en la caché
          (:func:`~.stale.refresh_region`, RF-008-24): nace obsoleta si consumió algo que ya
          lo estaba o que cambió mientras se calculaba.

        ``ProvenanceError`` si ya no está «en curso» (``core.operation_not_running``) o si una
        salida no está guardada en el proyecto (``core.operation_output_not_saved``,
        RF-008-23); los rechazos de ``core.datasets`` y los de las cifras (que se comprueban
        todas antes de escribir nada); ``ValueError``/``TypeError`` con un argumento mal
        formado o fuera de una transacción. En todos, sin escribir nada."""
        if not isinstance(conn, sqlite3.Connection):
            raise TypeError(f"complete recibe la conexión de la transacción del módulo, no "
                            f"{conn!r}")
        if not conn.in_transaction:
            raise ValueError("complete se llama dentro de la transacción de escritura del "
                             "módulo (Project.write_transaction), la que guarda sus resultados")
        row = conn.execute("SELECT status FROM gb_operation WHERE uid = ?",
                           (self.uid,)).fetchone()
        if row is None:
            raise ProvenanceError("core.operation_unknown", operation=self.uid,
                                  project=self.project.name)
        if row[0] != OperationStatus.RUNNING:
            raise ProvenanceError("core.operation_not_running", op_type=self.op_type,
                                  operation=self.uid)
        specs = _outputs(outputs)
        software_json = _software(self.definition, software)
        interpreter_json = _interpreter(interpreter)
        text = _message(message)
        chosen = self.executor if executor is None else _executor(executor)
        job = self.job_uid if job_uid is None else _optional_text(job_uid, "job_uid")
        _check_job(chosen, job, required=True)
        prepared = prepare_figures(conn, self, figures)
        _check_saved(conn, self.project, self.op_type, specs)
        records: list[DatasetRecord] = []
        for spec in specs:
            existing = dataset_registry.get(conn, spec.name)
            if existing is not None and existing.live and existing.name == spec.name:
                record = dataset_registry.set_content(conn, self.project, existing.uid, spec,
                                                      operation_uid=self.uid)
            else:
                record = dataset_registry.register_dataset(conn, self.project, spec,
                                                           operation_uid=self.uid)
            records.append(record)
        write_figures(conn, self, prepared)
        finished = format_utc(self.project.clock.now())
        conn.execute(
            "UPDATE gb_operation SET status = ?, finished_at = ?, software = ?, executor = ?, "
            "job_uid = ?, interpreter = ?, message = ? WHERE uid = ?",
            (str(OperationStatus.DONE), finished, software_json, str(chosen), job,
             interpreter_json, text, self.uid),
        )
        if self.supersedes is not None:
            conn.execute(
                "UPDATE gb_operation SET superseded_by = ? WHERE uid = ? "
                "AND superseded_by IS NULL",
                (self.uid, self.supersedes),
            )
        # La región sigue lo que escribió (sus datos y lo que los consumía).
        refresh_region(conn, now=finished, operations=[self.uid])
        return tuple(records)

    # --- Final sin completar (RF-008-19) -----------------------------------------------------

    def fail(self, reason: str) -> None:
        """La deja «fallida» con ``reason`` (texto no vacío; sus rutas absolutas se quedan en
        el nombre del fichero y se corta a :data:`MAX_REASON_CHARS`) y su hora, en su propia
        transacción, sin salidas, y suelta sus rutas (RF-008-19). ``ProvenanceError``:
        ``core.read_only`` en solo lectura (sigue «en curso» y quedará «interrumpida» al
        abrirlo en escritura) y ``core.operation_not_running`` si ya terminó (una operación
        terminada no cambia); ``TypeError``/``ValueError`` sin motivo. Sin escribir nada."""
        self._stop(OperationStatus.FAILED, reason)

    def cancel(self, reason: str) -> None:
        """La deja «cancelada» con ``reason`` (la persona la paró o, al incorporar un trabajo,
        la 004 lo canceló): lo mismo que :meth:`fail` (RF-008-19)."""
        self._stop(OperationStatus.CANCELLED, reason)

    def _stop(self, status: OperationStatus, reason: object) -> None:
        text = _reason(reason)
        _require_writable(self.project)
        if not self._end(status, text):
            raise ProvenanceError("core.operation_not_running", op_type=self.op_type,
                                  operation=self.uid)

    def _running(self) -> bool:
        """Si sigue «en curso» en lo confirmado del proyecto."""
        with self.project.read() as conn:
            return _statuses(conn, [self.uid]).get(self.uid) == OperationStatus.RUNNING

    def _end(self, status: OperationStatus, reason: str) -> bool:
        """Si sigue «en curso», la deja en ``status`` con ``reason`` y su hora, en su propia
        transacción, y suelta sus rutas; dice si la cambió."""
        with self.project.write_transaction() as conn:
            running = _statuses(conn, [self.uid]).get(self.uid) == OperationStatus.RUNNING
            if running:
                conn.execute(
                    "UPDATE gb_operation SET status = ?, status_reason = ?, finished_at = ? "
                    "WHERE uid = ?",
                    (str(status), reason, format_utc(self.project.clock.now()), self.uid),
                )
        _forget(self)
        return running

    def _abandon(self, error: BaseException) -> None:
        """El bloque de :func:`operation` falló: «fallida» con el motivo, o «cancelada» si se
        paró una lectura o una huella (:data:`CANCELLATIONS`); si el módulo ya la terminó, no
        cambia. Si no se puede escribir (solo lectura, red), se dice en el error, que sigue:
        quedará «interrumpida» al abrirlo en escritura (RF-008-19)."""
        if isinstance(error, CANCELLATIONS):
            status, reason, what = OperationStatus.CANCELLED, cancel_reason(error), "cancelación"
        else:
            status, reason, what = OperationStatus.FAILED, failure_reason(error), "fallo"
        try:
            self._end(status, reason)
        except (GeoblenderError, OSError, sqlite3.Error) as exc:
            error.add_note(
                f"La operación «{self.op_type}» ({self.uid}) sigue «en curso» en el proyecto: "
                f"no se pudo registrar su {what} ({exc})."
            )


def _shorten(path: str) -> str:
    """El nombre final de una ruta absoluta (para no guardarla en el proyecto)."""
    return ntpath.basename(path.rstrip("\\/")) or "…"


def _clean(text: str) -> str:
    """Un motivo como se guarda en el proyecto: sus rutas absolutas, solo con el nombre de su
    fichero (ADR-0006 §5), y de :data:`MAX_REASON_CHARS` como mucho."""
    shown = ABSOLUTE_PATH.sub(lambda match: _shorten(match.group(0)), text)
    if len(shown) > MAX_REASON_CHARS:
        shown = shown[: MAX_REASON_CHARS - 1] + "…"
    return shown


def _reason(reason: object) -> str:
    """El motivo dado por el módulo, que es obligatorio (RF-008-19)."""
    if not isinstance(reason, str):
        raise TypeError(f"el motivo de una operación que no termina bien es un texto, no "
                        f"{reason!r}")
    text = reason.strip()
    if not text:
        raise ValueError("falta el motivo: una operación que no termina bien queda registrada "
                         "con él (RF-008-19)")
    return _clean(text)


def failure_reason(error: BaseException) -> str:
    """El motivo que se guarda de un error: su clase y su texto, sin rutas absolutas (solo el
    nombre de su fichero) y de :data:`MAX_REASON_CHARS` como mucho."""
    text = str(error).strip()
    shown = f"{type(error).__name__}: {text}" if text else type(error).__name__
    return _clean(FAILURE_REASON_PREFIX + shown)


def cancel_reason(error: BaseException) -> str:
    """El motivo que se guarda de una cancelación (:data:`CANCELLATIONS`): su texto, como el
    de :func:`failure_reason`."""
    return _clean(CANCEL_REASON_PREFIX + (str(error).strip() or type(error).__name__))


# --- Empezar ------------------------------------------------------------------------------


def begin_operation(
    project: OperationProject,
    op_type: str,
    *,
    settings: Mapping[str, Any],
    inputs: Sequence[Use] = (),
    params: Sequence[str] = (),
    executor: Executor | str,
    job_uid: str | None = None,
    group_uid: str | None = None,
    supersedes: str | None = None,
) -> OperationHandle:
    """Registra «en curso» una operación de tipo ``op_type`` antes de ejecutarla, en su
    propia transacción (RF-008-51), y devuelve su :class:`OperationHandle`:

    - ``settings``: los ajustes de la orden (JSON, sin rutas absolutas);
    - ``inputs``: lo que consume (:class:`Use`), anotado con su hash de contenido actual;
    - ``params``: las claves de los parámetros que lee; los que el proyecto aún no tiene se
      registran antes con su valor por defecto «sin confirmar» (RF-008-04) y todos se anotan
      resueltos por su ámbito, con la revisión de su historial (RF-008-05);
    - ``executor`` (:class:`Executor`) y ``job_uid`` (un trabajo puede recibirlo al
      completar); ``group_uid``: la ejecución de su grupo acoplado (si la operación es de uno
      y no se da, se abre otra: :attr:`OperationHandle.group_uid`); ``supersedes``: la
      operación hecha a la que sustituye (un recálculo, una reimportación).

    Rechazos, sin escribir nada: ``ProvenanceError`` (``core.operation_unregistered``,
    ``core.read_only``, ``core.operation_dataset_unknown``/``_not_live``,
    ``core.operation_input_unknown``/``_not_live``, ``core.operation_supersedes_unknown``/
    ``_not_done``, ``core.operation_already_superseded``), ``ParamError``
    (``core.param_undefined``) y ``ValueError``/``TypeError`` con un argumento mal formado."""
    definition = operation_def(op_type)
    _require_writable(project)
    settings_json = _settings(settings)
    chosen = _executor(executor)
    job = _optional_text(job_uid, "job_uid")
    _check_job(chosen, job, required=False)
    group = _group_uid(definition, group_uid)
    uses = _uses(inputs)
    keys = _keys(params)
    previous = _optional_text(supersedes, "la operación sustituida (supersedes)")
    session = project.session
    store = ParameterStore(project)
    with project.write_transaction() as conn:
        _prune(project, conn)
        if previous is not None:
            _check_supersedes(conn, definition, previous)
        consumed = tuple(_resolve_use(conn, definition, use) for use in uses)
        _check_repeated(consumed)
        resolved: list[ResolvedParam] = []
        for key in keys:
            store.ensure_default(conn, key, geoblender_version=session.geoblender_version)
            resolved.append(store.resolve(conn, key))
        uid = new_uid()
        started = format_utc(project.clock.now())
        row: dict[str, object] = {
            "uid": uid,
            "op_type": definition.op_type,
            "op_version": definition.version,
            "module": definition.module,
            "scope": definition.scope,
            "repeatable": int(definition.repeatable),
            "group_name": definition.group,
            "group_uid": group,
            "settings": settings_json,
            "settings_sha256": sha256_bytes(settings_json.encode("utf-8")),
            "status": str(OperationStatus.RUNNING),
            "supersedes_uid": previous,
            "geoblender_version": session.geoblender_version,
            "software": "{}",
            "executor": str(chosen),
            "job_uid": job,
            "user_host": session.user_host,
            "host": session.host,
            "session_uid": session.session_uid,
            "started_at": started,
        }
        conn.execute(
            f"INSERT INTO gb_operation ({', '.join(row)}) "
            f"VALUES ({', '.join('?' for _ in row)})",
            tuple(row.values()),
        )
        conn.executemany(
            "INSERT INTO gb_operation_io (operation_uid, direction, item_kind, item_uid, "
            "content_sha256, role) VALUES (?, 'in', ?, ?, ?, ?)",
            [(uid, str(item.kind), item.uid, item.content_sha256, item.role)
             for item in consumed],
        )
        conn.executemany(
            "INSERT INTO gb_operation_param (operation_uid, parameter_uid, key, scope, rev, "
            "value, unit, kind, unconfirmed, value_sha256) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(uid, param.parameter_uid, param.key, param.scope, param.rev, param.value_json,
              param.unit, str(param.kind), int(param.unconfirmed), param.value_sha256)
             for param in resolved],
        )
    handle = OperationHandle(
        project, definition, uid, settings=settings_json, group_uid=group,
        supersedes=previous, executor=chosen, job_uid=job, started_at=started,
        inputs=consumed, params=tuple(resolved),
    )
    with _LOCK:
        _HANDLES[uid] = handle
    return handle


@contextmanager
def operation(
    project: OperationProject,
    op_type: str,
    *,
    executor: Executor | str = Executor.BLENDER,
    **kw: Any,
) -> Iterator[OperationHandle]:
    """Una operación en el hilo de Blender: :func:`begin_operation` (con los mismos
    argumentos; por defecto, ``executor="blender"``) al entrar; dentro, el módulo reclama sus
    rutas, calcula y, en su transacción de escritura, guarda sus resultados y llama a
    :meth:`OperationHandle.complete`. Si el bloque falla, la operación queda «fallida» con el
    motivo (:func:`failure_reason`) y el error sigue; si termina sin completarla, queda
    «fallida» y lanza ``ProvenanceError`` (``core.operation_not_completed``): sus resultados
    no se dan por buenos (RF-008-23). Al salir ya no reclama rutas."""
    handle = begin_operation(project, op_type, executor=executor, **kw)
    try:
        yield handle
    except BaseException as error:
        handle._abandon(error)
        raise
    if handle._running():
        handle._end(OperationStatus.FAILED, NOT_COMPLETED_REASON)
        raise ProvenanceError("core.operation_not_completed", op_type=handle.op_type)
    _forget(handle)


# --- Operaciones que su sesión no pudo terminar -------------------------------------------


def _record(conn: sqlite3.Connection, project: OperationProject, kind: str, operation_uid: str,
            message: str, data: Mapping[str, object], at: str) -> None:
    """Su evento en ``gb_event`` (``kind``: el nombre de ``core.project.events.EventKind``),
    con la sesión que lo registra. Se importa aquí: ``core.project`` importa
    ``core.provenance`` (su esquema) y este módulo no lo carga al importarse."""
    from ..project.events import EventKind, record_event

    record_event(conn, EventKind[kind], message, session=project.session, at=at,
                 entity_kind="operation", entity_uid=operation_uid, data=dict(data))


def _interrupt(conn: sqlite3.Connection, project: OperationProject) -> list[str]:
    rows = conn.execute(
        "SELECT uid, op_type, session_uid, user_host, started_at, job_uid FROM gb_operation "
        "WHERE status = ? AND session_uid <> ? ORDER BY fid",
        (str(OperationStatus.RUNNING), project.session.session_uid),
    ).fetchall()
    found: list[str] = []
    at = format_utc(project.clock.now())
    for uid, op_type, session_uid, user_host, started_at, job_uid in rows:
        reason = _clean(INTERRUPTED_REASON.format(user_host=user_host))
        conn.execute(
            "UPDATE gb_operation SET status = ?, status_reason = ?, finished_at = ? WHERE uid = ?",
            (str(OperationStatus.INTERRUPTED), reason, at, uid),
        )
        _record(conn, project, "OPERATION_INTERRUPTED", uid,
                f"Operación «{op_type}» interrumpida: {reason}",
                {"op_type": op_type, "session_uid": session_uid, "user_host": user_host,
                 "started_at": started_at, "job_uid": job_uid, "reason": reason}, at)
        found.append(str(uid))
    return found


def interrupt_orphaned(project: OperationProject, *,
                       conn: sqlite3.Connection | None = None) -> list[str]:
    """Al abrir ``project`` en escritura: deja «interrumpida», con su motivo, su hora y un
    evento ``operation_interrupted``, toda operación «en curso» de **otra** sesión (en
    escritura, el cerrojo es de esta: la suya lo perdió sin poder registrar su final) y
    devuelve sus uid, en orden (RF-008-19). Las «en curso» de esta sesión siguen así, y lo que
    escribieron a medias no queda registrado como bueno (sus salidas solo se registran al
    completarlas): sus ficheros sin registro, a restos (RF-008-22). Con ``conn`` escribe en esa
    transacción de escritura de quien llama (las comprobaciones de apertura agrupan sus
    escrituras); sin ella, en una propia. ``core.read_only`` en solo lectura, sin tocar nada."""
    _require_writable(project)
    if conn is not None:
        return _interrupt(_in_transaction(conn, "interrupt_orphaned"), project)
    with project.write_transaction() as opened:
        return _interrupt(opened, project)


def mark_not_ingested(project: OperationProject, op_uid: str, reason: str) -> bool:
    """Deja «no incorporada», con ``reason`` (como el de :meth:`OperationHandle.fail`), su hora
    y un evento ``operation_not_ingested``, la operación ``op_uid`` de un trabajo de la 004 que
    sigue «en curso» y cuyo trabajo se borró sin incorporar su resultado (descartarlo, limpiar o
    la purga por antigüedad, RF-004-17), y suelta sus rutas (RF-008-23); dice si la cambió:
    una ya terminada no cambia (falso). Rechazos, sin escribir nada: ``ProvenanceError``
    (``core.read_only`` en solo lectura, ``core.operation_unknown``), ``ValueError`` si no es
    de un trabajo y ``TypeError``/``ValueError`` sin motivo."""
    if not isinstance(op_uid, str):
        raise TypeError(f"una operación se indica por su uid, no {op_uid!r}")
    text = _reason(reason)
    _require_writable(project)
    with project.write_transaction() as conn:
        row = conn.execute("SELECT op_type, status, executor, job_uid FROM gb_operation "
                           "WHERE uid = ?", (op_uid,)).fetchone()
        if row is None:
            raise ProvenanceError("core.operation_unknown", operation=op_uid,
                                  project=project.name)
        op_type, status, executor, job_uid = row
        if executor not in JOB_EXECUTORS:
            raise ValueError(f"la operación «{op_type}» ({op_uid}) no se ejecuta en un trabajo "
                             f"de la 004 ({executor}): no tiene trabajo que incorporar")
        if status != OperationStatus.RUNNING:
            return False
        at = format_utc(project.clock.now())
        conn.execute(
            "UPDATE gb_operation SET status = ?, status_reason = ?, finished_at = ? WHERE uid = ?",
            (str(OperationStatus.NOT_INGESTED), text, at, op_uid),
        )
        _record(conn, project, "OPERATION_NOT_INGESTED", op_uid,
                f"Operación «{op_type}» no incorporada: {text}",
                {"op_type": op_type, "job_uid": job_uid, "reason": text}, at)
    with _LOCK:
        handle = _HANDLES.get(op_uid)
    if handle is not None:
        _forget(handle)
    return True
