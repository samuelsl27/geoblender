# SPDX-License-Identifier: GPL-3.0-or-later
"""El plan de una congelación y la congelación por pasos (spec 009; RF-009-06, RF-009-07,
RF-009-08; plan 009 A5, A7, §5.2.4, D-16, D-18, D-27, D-37, D-40 y D-41).

:func:`freeze_plan` dice qué se congelaría en la revisión abierta de una versión
(:class:`FreezePlan`), **sin escribir nada** y leyendo la base en **una sola instantánea** (una
transacción de lectura: de la conexión que se le da o de una suya). Lo usan el diálogo de
«Nueva revisión…» (lo que hay que aceptar y lo que lo impide, antes de empezar) y
:func:`freeze_steps`, que congela de verdad: el plan, la copia (A6, ``core.versions.copy``) y
la confirmación (A7, al final de este docstring).

1. **Lo que se congela** (:attr:`FreezePlan.items`, cada cosa en su parte, :class:`ItemPart`):
   las operaciones hechas de la versión (de cualquiera de sus revisiones, D-23) que escribieron
   el contenido actual de un dato vivo suyo o una cifra suya vigente «en curso» (lo
   **producido**) y, hacia arriba por el grafo, lo que consumieron y quién lo escribió: los
   datos de la versión (producidos, igual), los datos del proyecto derivados o editables a mano
   con su operación (**aguas arriba**, y lo suyo), lo importado con su entrada y su importación
   (**inmutable**, D-18) y lo congelado de la revisión de la que parte la versión, sin subir más
   (**heredado**, ``Use.frozen``, D-27); los parámetros, cada fila con la ``rev`` de su
   historial que usó la última operación que la leyó; y las cifras vigentes de la versión. El
   productor de lo que consumió una operación es el de la 008
   (:meth:`.provenance.graph.ProvenanceGraph.producer`): quien escribió el contenido actual del
   dato si es ese y, si no, la última que escribió ese contenido.
2. **Lo que se copia** (:attr:`FreezePlan.to_copy`, :class:`CopyItem`): el contenido actual de
   lo producido y de lo de aguas arriba, en un GeoPackage (``snapshots/V10.r2/V10.r2.gpkg``, la
   tabla con su nombre), ``rasters/`` y ``meshes/`` (con su ruta en el proyecto), si no está ya
   copiado en otra revisión congelada y no alterada (con el mismo lector y normalizador): eso se
   **referencia** (:attr:`FreezePlan.referenced`) a la copia de la otra; dentro del plan, cada
   contenido se copia una vez. Lo inmutable y lo heredado se anotan sin copiar; un modelo de
   bloques (``duckdb``, hasta R-22) se anota sin copiar y «no reproducible» (D-37).
3. **Lo que hay que aceptar** (:attr:`FreezePlan.accept`, RF-009-08): los datos obsoletos de lo
   congelado (salvo los de una operación que espera revisión a mano), las operaciones obsoletas
   que solo dejan cifras y las que esperan revisión a mano (las de la 008: «! n obsoletos») y las
   entradas no localizables, con su estado y su texto. Cada elemento lleva el estado que tiene
   (:class:`ItemState`); una operación que consumió un contenido que ya no existe ni está
   congelado en ninguna revisión (ni copiado aquí), «no reproducible» (spec §8).
4. **Lo que lo impide** (:attr:`FreezePlan.blockers`, sin aceptación posible; D-40): el proyecto
   en solo lectura, la comprobación de apertura sin terminar, otra congelación en curso (su
   carpeta temporal ``snapshots/<revisión>.congelando-<8 hex>``), una operación de la versión en
   curso y una entrada aguas arriba cambiada sin decidir (RF-008-10). Una versión SUPERADO o
   DESCARTADO no tiene revisión abierta: ``VersionError`` («Versión no editable», RF-009-04).
5. **El espacio**: lo que se copia (los ficheros, con su tamaño; las tablas, estimadas por sus
   valores) más un 10 %, como la copia de la 002 (:attr:`FreezePlan.space_needed`; el
   GeoPackage, que se arma en la caché, :attr:`FreezePlan.cache_needed`).

:func:`freeze_steps` (A5 → A6 → A7) hace el plan al llamarla y se niega, sin escribir nada, si
algo lo impide o si hay algo que aceptar que el usuario no aceptó (:class:`Acceptance`); después
copia la instantánea por pasos a su carpeta temporal, ``snapshots/V10.r2.congelando-<8 hex>``
(``core.versions.freezing``: el barrido de restos de la apertura no aparta la de esta sesión), y la
**confirma en una transacción corta**: comprueba que lo congelado sigue siendo lo vigente (el
hash de contenido de cada dato y ninguna operación nueva de la versión desde el plan, D-40: si
no, se cancela y no queda nada), escribe lo congelado (``gb_revision_item``, en sentencias de 500
filas), la revisión congelada (su carpeta, la huella de su manifiesto, sus bytes, la versión de
Geoblender, lo aceptado, quién y cuándo), la siguiente abierta con el motivo dado y los eventos
``revision_frozen`` y ``revision_opened``, y da a la temporal su nombre (``snapshots/V10.r2``)
antes del ``COMMIT``. Después, la cabecera con su inventario (§5.2.4); si no se puede escribir,
la base manda: se avisa y se regenera al abrir. Una revisión vacía se congela con su manifiesto
solo (D-41). Cerrar los pasos antes del final (Esc), ``cancelled`` o un fallo no dejan nada; si
Blender se cierra a medias, la temporal (o la carpeta ya renombrada sin su fila) la aparta a
``orphans/`` la comprobación de apertura (``core.datasets.orphans``).

Python puro (ADR-0004): el plan lee la base del proyecto y los metadatos de las fuentes de sus
entradas (RF-008-13) y de ``snapshots/``, sin abrir ni escribir ningún fichero.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ..content.builtin import _selector as selector_condition
from ..datasets.model import RECORD_COLUMNS, DatasetRecord, DatasetStatus, Store
from ..errors import GeoblenderError
from ..hashing import canonical_json
from ..ids import new_uid
from ..inputs import registry as input_registry
from ..inputs.check import probe_input, table_changes
from ..inputs.model import FileAnchor, InputRecord, InputStatus
from ..paths import find_absolute_paths
from ..project.copytree import SPACE_MARGIN
from ..project.events import EventKind, log_event, record_event
from ..project.model import Progress
from ..project.session import WriteAttempt, WriteState
from ..provenance import messages as provenance_messages
from ..provenance import stale
from ..provenance.lineage import figures_in
from ..timeutil import format_utc
from . import freezing as freezing_registry
from . import read
from .model import (
    FREEZING_MARK,
    SNAPSHOTS_DIR,
    ItemKind,
    ItemPart,
    ItemState,
    Revision,
    RevisionItem,
    RevisionState,
    Version,
    VersionError,
    ensure_editable,
    render,
)

if TYPE_CHECKING:
    from ..project.model import ProjectRecord
    from ..provenance.gate import CheckState
    from ..sysinfo import SessionInfo
    from ..timeutil import Clock
    from ..userdata import UserData
    from .copy import SnapshotCopy, SnapshotFile

COPIED_STORES: tuple[Store, ...] = (Store.GPKG, Store.RASTERS, Store.MESHES)
"""Los almacenes cuyo contenido copia una instantánea (ADR-0026: GeoPackage, GeoTIFF y npz)."""
GPKG_BASE_BYTES = 48 * 1024
"""Lo que ocupa, estimado, el GeoPackage de una instantánea sin tablas (su estructura 1.4 y
el CRS del proyecto: 40 KiB medidos con ``core.gpkg.base``, redondeado por arriba)."""
TABLE_BYTES = 8 * 1024
"""… lo que añade cada tabla sin filas (su definición y sus páginas: unos 4,5 KiB medidos)."""
ROW_BYTES = 8
"""… lo que añade cada fila además de sus valores (la cabecera de la celda y su ``fid``)."""
QUERY_TAG = "/* core.versions.freeze */"
"""Lo que llevan delante las consultas de este módulo (las pruebas miran su plan)."""

_LIVE = ", ".join(f"'{status}'" for status in (
    DatasetStatus.CURRENT, DatasetStatus.MISSING, DatasetStatus.BLOCKED, DatasetStatus.DAMAGED))
_UNREADABLE: frozenset[DatasetStatus] = frozenset(
    {DatasetStatus.MISSING, DatasetStatus.BLOCKED, DatasetStatus.DAMAGED})
"""Los estados de un dato cuyo contenido registrado ya no se puede leer."""
_ACTIVE_INPUTS: frozenset[InputStatus] = frozenset(
    {InputStatus.CURRENT, InputStatus.CHANGED, InputStatus.KEPT})
_RANK: Mapping[ItemPart, int] = {ItemPart.PRODUCED: 0, ItemPart.UPSTREAM: 1,
                                 ItemPart.IMMUTABLE: 2, ItemPart.INHERITED: 3}
"""Para lo que llega por varios caminos, la parte más propia de la versión."""
_CHUNK = 500
_DATASET_COLUMNS = ", ".join(RECORD_COLUMNS)
_OPERATION_COLUMNS = (
    "fid, uid, op_type, repeatable, status, superseded_by, revision_uid, finished_at"
)
_OWN_OPERATIONS = (  # por gb_operation_revision
    f"{QUERY_TAG} SELECT {_OPERATION_COLUMNS} FROM gb_operation "
    "WHERE revision_uid IN ({marks}) AND revision_uid <> '' ORDER BY fid"
)
_OPERATIONS = f"{QUERY_TAG} SELECT {_OPERATION_COLUMNS} FROM gb_operation WHERE uid IN ({{marks}})"
_OWN_DATA = (  # por gb_dataset_version
    f"{QUERY_TAG} SELECT {_DATASET_COLUMNS}, version_uid FROM gb_dataset "
    f"WHERE version_uid = ? AND version_uid <> '' AND status IN ({_LIVE}) ORDER BY fid"
)
_DATA = (
    f"{QUERY_TAG} SELECT {_DATASET_COLUMNS}, version_uid FROM gb_dataset "
    "WHERE uid IN ({marks})"
)
_CONSUMED = (  # por el índice único de (operation_uid, direction, …)
    f"{QUERY_TAG} SELECT operation_uid, item_kind, item_uid, content_sha256 "
    "FROM gb_operation_io WHERE operation_uid IN ({marks}) AND direction = 'in' ORDER BY fid"
)
_WRITERS = (  # por gb_operation_io_version y el uid de la operación
    f"{QUERY_TAG} SELECT io.operation_uid FROM gb_operation_io AS io "
    "CROSS JOIN gb_operation AS op ON op.uid = io.operation_uid "
    "WHERE io.item_uid = ? AND io.content_sha256 = ? AND io.direction = 'out' "
    "AND io.item_kind = 'dataset' AND op.status = 'done' ORDER BY op.finished_at, op.fid"
)
_USES = (  # por el índice único de (operation_uid, parameter_uid)
    f"{QUERY_TAG} SELECT operation_uid, parameter_uid, rev, value_sha256 "
    "FROM gb_operation_param WHERE operation_uid IN ({marks}) ORDER BY fid"
)
_PARAMETERS = f"{QUERY_TAG} SELECT uid, value_sha256 FROM gb_parameter WHERE uid IN ({{marks}})"
_STALE = (
    f"{QUERY_TAG} SELECT DISTINCT item_uid FROM gb_stale "
    "WHERE item_kind = ? AND item_uid IN ({marks})"
)
_COPIED = (  # por gb_revision_item_copy: un contenido ya copiado en una congelada no alterada
    f"{QUERY_TAG} SELECT i.snapshot_path, i.snapshot_layer, i.file_sha256, i.file_size "
    "FROM gb_revision_item AS i CROSS JOIN gb_revision AS r ON r.uid = i.revision_uid "
    "CROSS JOIN gb_dataset AS d ON d.uid = i.item_uid "
    "WHERE i.content_sha256 = ? AND i.copied AND i.item_kind = 'dataset' "
    "AND r.state = 'frozen' AND r.altered_at IS NULL AND d.reader = ? AND d.normalizer = ? "
    "ORDER BY i.fid LIMIT 1"
)
_FROZEN_ITEM = (  # por el índice único de (revision_uid, item_kind, item_uid)
    f"{QUERY_TAG} SELECT snapshot_path, snapshot_layer, file_sha256, file_size "
    "FROM gb_revision_item WHERE revision_uid = ? AND item_kind = 'dataset' AND item_uid = ?"
)
_RUNNING = (  # por gb_operation_revision
    f"{QUERY_TAG} SELECT op_type FROM gb_operation WHERE revision_uid = ? "
    "AND revision_uid <> '' AND status = 'running' ORDER BY fid"
)
_TABLE_SIZE = f'{QUERY_TAG} SELECT count(*), total({{values}}) FROM "{{table}}"{{where}}'


# --- Lo que da el plan ----------------------------------------------------------------------


class BlockReason(StrEnum):
    """Lo que impide congelar (plan A5 (1); D-40), en el orden en que se dice."""

    READ_ONLY = "read_only"  # el proyecto en solo lectura
    OPEN_CHECK = "open_check"  # la comprobación de apertura sin terminar (RF-008-58)
    FREEZING = "freezing"  # otra congelación en curso
    RUNNING = "running"  # una operación de la versión en curso
    INPUT_CHANGED = "input_changed"  # una entrada aguas arriba cambiada sin decidir (RF-008-10)


_BLOCK_MESSAGES: Mapping[BlockReason, str] = {
    BlockReason.READ_ONLY: "core.version_freeze_read_only",
    BlockReason.OPEN_CHECK: "core.version_freeze_checking",
    BlockReason.FREEZING: "core.version_freeze_in_progress",
    BlockReason.RUNNING: "core.version_freeze_running",
    BlockReason.INPUT_CHANGED: "core.version_freeze_input_changed",
}


@dataclass(frozen=True, slots=True)
class Blocker:
    """Lo que impide congelar: su motivo, lo que nombra (operaciones, entradas, carpetas) y su
    texto en español."""

    reason: BlockReason
    names: tuple[str, ...]
    text: str

    @property
    def code(self) -> str:
        """El código de su mensaje (``core.version_freeze_…``), para decirlo en otro idioma
        con ``model.render`` (marcadores ``revision`` y ``names``)."""
        return _BLOCK_MESSAGES[self.reason]


@dataclass(frozen=True, slots=True)
class AcceptItem:
    """Lo que hay que aceptar para congelar (RF-009-08): un dato obsoleto, una operación
    obsoleta que solo deja cifras o que espera revisión a mano, o una entrada no localizable,
    con su nombre (el del dato, el tipo de la operación o el nombre lógico de la entrada), su
    estado (:class:`ItemState`) y su texto («Obsoleto: cambió …», «No se encuentra la fuente
    …»)."""

    item_kind: ItemKind
    item_uid: str
    name: str
    state: ItemState
    text: str


@dataclass(frozen=True)
class CopyItem:
    """Un dato cuyo contenido actual copia la instantánea: su registro (con su almacén, su
    ubicación, su selector, su lector, su normalizador y su hash de contenido), su parte, dónde
    queda la copia (ruta relativa al proyecto y, en el GeoPackage, su tabla) y lo que se estima
    que ocupa (un fichero, su tamaño; una tabla, sus valores)."""

    record: DatasetRecord
    part: ItemPart
    snapshot_path: str
    snapshot_layer: str | None
    size: int


@dataclass(frozen=True)
class FreezePlan:
    """El plan de una congelación (véase el módulo): la versión y su revisión abierta, lo que
    se congela (:attr:`items`), lo que se copia y lo que se referencia, lo que hay que aceptar,
    lo que lo impide, los bytes que se copian y el espacio que hace falta (con su 10 %)."""

    version: Version
    revision: Revision
    items: tuple[RevisionItem, ...]
    to_copy: tuple[CopyItem, ...]
    referenced: tuple[RevisionItem, ...]
    accept: tuple[AcceptItem, ...]
    blockers: tuple[Blocker, ...]
    bytes_to_copy: int
    space_needed: int

    @property
    def label(self) -> str:
        """La revisión que se congela («V10.r2»)."""
        return self.revision.label(self.version.code)

    @property
    def snapshot_dir(self) -> str:
        """Su carpeta en el proyecto, relativa («snapshots/V10.r2»)."""
        return f"{SNAPSHOTS_DIR}/{self.label}"

    @property
    def blocked(self) -> bool:
        """Si algo impide congelarla ahora."""
        return bool(self.blockers)

    @property
    def needs_acceptance(self) -> bool:
        """Si hay algo que aceptar antes de congelarla (RF-009-08)."""
        return bool(self.accept)

    @property
    def not_reproducible(self) -> tuple[RevisionItem, ...]:
        """Lo que queda «no reproducible», en el orden de :attr:`items`."""
        return tuple(item for item in self.items if item.state is ItemState.NOT_REPRODUCIBLE)

    @property
    def cache_needed(self) -> int:
        """El espacio que hace falta en la caché para armar el GeoPackage de la instantánea
        (sus tablas más un 10 %); 0 si no copia ninguna."""
        tables = [copy.size for copy in self.to_copy if copy.record.store is Store.GPKG]
        return _with_margin(sum(tables) + GPKG_BASE_BYTES) if tables else 0


class PlanProject(Protocol):
    """Lo que usa el plan del proyecto (``core.project.Project``): su raíz y su base, si se
    puede escribir, una conexión de lectura y los datos de usuario (las fuentes de las
    entradas, RF-002-19)."""

    @property
    def root(self) -> Path: ...

    @property
    def database_path(self) -> Path: ...

    @property
    def writable(self) -> bool: ...

    @property
    def userdata(self) -> UserData: ...

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


def _with_margin(size: int) -> int:
    """``size`` más el margen de la copia de la 002 (10 %, redondeado por arriba)."""
    return size + math.ceil(size * SPACE_MARGIN) if size else 0


# --- El plan --------------------------------------------------------------------------------


def freeze_plan(project: PlanProject, version_uid: str, *, conn: sqlite3.Connection | None = None,
                pending: CheckState | None = None) -> FreezePlan:
    """El plan de congelar la revisión abierta de la versión ``version_uid`` (uid o código):
    véase el módulo. ``conn``, una conexión a la base del proyecto (si no, una de lectura
    suya); ``pending``, lo que la comprobación de apertura aún no ha comprobado (``None``: ya
    terminó). No escribe nada. ``VersionError``: ``core.version_unknown`` si la versión no
    está y ``core.version_not_editable`` si es SUPERADO o DESCARTADO (no tiene revisión que
    congelar); ``TypeError`` si ``version_uid`` no es un texto."""
    if not isinstance(version_uid, str):
        raise TypeError(f"la versión se indica por su uid o su código, no {version_uid!r}")
    with _reading(project, conn) as reading:
        found = read.version(reading, version_uid)
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version_uid,
                               version=version_uid)
        ensure_editable(found)
        revision = read.open_revision(reading, found.uid)
        if revision is None:  # pragma: no cover - la base exige una abierta (RF-009-06)
            raise VersionError("core.version_not_editable", field="estado",
                               value=found.status.value, version=found.code,
                               state=found.status)
        return _Planner(project, reading, found, revision, pending).plan()


@contextmanager
def _reading(project: PlanProject,
             conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """Una conexión en una instantánea de la base: la de ``conn`` (si no está ya en una
    transacción, en una de lectura que se deshace al salir) o una de lectura del proyecto."""
    if conn is not None:
        with _snapshot(conn):
            yield conn
        return
    with project.read() as reading, _snapshot(reading):
        yield reading


@contextmanager
def _snapshot(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    began = not conn.in_transaction
    if began:
        conn.execute("BEGIN")
    try:
        yield conn
    finally:
        if began:
            conn.execute("ROLLBACK")


@dataclass(frozen=True, slots=True)
class _Operation:
    fid: int
    uid: str
    op_type: str
    repeatable: bool
    status: str
    superseded_by: str | None
    revision_uid: str
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class _Use:
    item_kind: str
    uid: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class _Data:
    record: DatasetRecord
    version_uid: str


@dataclass(frozen=True, slots=True)
class _Copy:
    """Dónde está o estará el contenido de un dato: en esta instantánea (``copied``) o en
    otra."""

    copied: bool
    path: str
    layer: str | None
    file_sha256: str | None = None
    file_size: int | None = None


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class _Planner:
    """Una pasada del plan sobre la instantánea ``conn`` (véase el módulo)."""

    def __init__(self, project: PlanProject, conn: sqlite3.Connection, version: Version,
                 revision: Revision, pending: CheckState | None) -> None:
        self.project = project
        self.conn = conn
        self.version = version
        self.revision = revision
        self.pending = pending
        self.label = revision.label(version.code)
        self.folder = f"{SNAPSHOTS_DIR}/{self.label}"
        self.operations: dict[str, _Operation] = {}
        self.consumed: dict[str, list[_Use]] = defaultdict(list)
        self.uses: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
        self.data: dict[str, _Data] = {}
        # De cada productor, los datos por los que se llegó a él (su parte, _operation_parts).
        self.reached: dict[str, set[str]] = defaultdict(set)
        self.copies: dict[tuple[str, str, str], _Copy | None] = {}
        self.parent = (None if not version.parent_revision_uid
                       else read.revision(conn, version.parent_revision_uid))
        # Lo obsoleto de lo del plan (_read_staleness).
        self.stale_ops: set[str] = set()
        self.stale_data: set[str] = set()
        self.review: set[str] = set()
        self.figure_only: set[str] = set()

    # --- Lecturas ----------------------------------------------------------------------------

    def _select(self, sql: str, values: Iterable[str],
                before: tuple[Any, ...] = ()) -> Iterator[tuple[Any, ...]]:
        items = sorted(set(values))
        for start in range(0, len(items), _CHUNK):
            chunk = items[start:start + _CHUNK]
            yield from self.conn.execute(sql.format(marks=", ".join("?" for _ in chunk)),
                                         (*before, *chunk))

    def _take_operations(self, rows: Iterable[tuple[Any, ...]]) -> None:
        for fid, uid, op_type, repeatable, status, superseded, revision, finished in rows:
            self.operations[str(uid)] = _Operation(
                int(fid), str(uid), str(op_type), bool(repeatable), str(status),
                None if superseded is None else str(superseded), str(revision),
                None if finished is None else str(finished))

    def _load_operations(self, uids: Iterable[str]) -> None:
        self._take_operations(self._select(_OPERATIONS, set(uids) - set(self.operations)))

    def _take_data(self, rows: Iterable[tuple[Any, ...]]) -> None:
        for row in rows:
            record = DatasetRecord.from_row(tuple(row[:-1]))
            self.data[record.uid] = _Data(record, str(row[-1]))

    def _load_data(self, uids: Iterable[str]) -> None:
        self._take_data(self._select(_DATA, set(uids) - set(self.data)))

    def _done(self, op_uid: str) -> bool:
        if op_uid not in self.operations:
            self._load_operations((op_uid,))
        found = self.operations.get(op_uid)
        return found is not None and found.status == "done"

    def _frozen_use(self, op_uid: str, dataset_uid: str) -> bool:
        """Si la operación de versión ``op_uid`` consumió ``dataset_uid``, de otra versión,
        congelado (``Use.frozen``, D-27: :meth:`.provenance.graph.ProvenanceGraph.frozen_use`)."""
        operation = self.operations[op_uid]
        data = self.data.get(dataset_uid)
        return (bool(operation.revision_uid) and data is not None and bool(data.version_uid)
                and data.version_uid != self.version.uid)

    def _producer(self, dataset_uid: str, content_sha256: str, excluding: str) -> str | None:
        """Quien escribió esa versión del dato (como en la 008): el que escribió su contenido
        actual si es esa; si no, el último que la escribió (sin ``excluding``)."""
        data = self.data.get(dataset_uid)
        if data is not None:
            record = data.record
            if (record.content_sha256 == content_sha256 and record.operation_uid != excluding
                    and self._done(record.operation_uid)):
                return record.operation_uid
        writers = [str(row[0]) for row in self.conn.execute(_WRITERS,
                                                            (dataset_uid, content_sha256))]
        writers = [uid for uid in writers if uid != excluding]
        return writers[-1] if writers else None

    def _existing_copy(self, content_sha256: str, reader: str, normalizer: str) -> _Copy | None:
        """La copia de ese contenido en otra revisión congelada y no alterada (D-28)."""
        key = (content_sha256, reader, normalizer)
        if key not in self.copies:
            row = self.conn.execute(_COPIED, key).fetchone()
            self.copies[key] = (None if row is None else _Copy(
                False, str(row[0]), None if row[1] is None else str(row[1]),
                None if row[2] is None else str(row[2]),
                None if row[3] is None else int(row[3])))
        return self.copies[key]

    # --- El grafo, hacia arriba ------------------------------------------------------------

    def _climb(self, roots: set[str]) -> tuple[list[str], set[str]]:
        """Las operaciones del plan (las raíces y, hacia arriba, quien escribió lo que
        consumieron), en orden de registro, y las entradas que consumieron directamente."""
        visited: set[str] = set()
        inputs: set[str] = set()
        frontier = {uid for uid in roots if self._done(uid)}
        while frontier:
            visited |= frontier
            self._load_operations(frontier)
            for op_uid, kind, uid, sha in self._select(_CONSUMED, frontier):
                self.consumed[str(op_uid)].append(_Use(str(kind), str(uid), str(sha)))
            for op_uid, parameter_uid, rev, sha in self._select(_USES, frontier):
                self.uses[str(op_uid)].append((str(parameter_uid), int(rev), str(sha)))
            self._load_data(use.uid for op_uid in frontier for use in self.consumed[op_uid]
                            if use.item_kind == "dataset")
            following: set[str] = set()
            for op_uid in frontier:
                for use in self.consumed[op_uid]:
                    if use.item_kind != "dataset":
                        inputs.add(use.uid)
                    elif not self._frozen_use(op_uid, use.uid):
                        producer = self._producer(use.uid, use.content_sha256, op_uid)
                        if producer is not None:
                            following.add(producer)
                            self.reached[producer].add(use.uid)
            frontier = following - visited
        ordered = sorted(visited, key=lambda uid: self.operations[uid].fid)
        return ordered, inputs

    # --- El plan -----------------------------------------------------------------------------

    def plan(self) -> FreezePlan:
        """El plan entero, en la instantánea de :attr:`conn`."""
        own_revisions = [revision.uid for revision in read.revisions(self.conn, self.version.uid)]
        self._take_operations(self._select(_OWN_OPERATIONS, own_revisions))
        self._take_data(self.conn.execute(_OWN_DATA, (self.version.uid,)))
        own_data = [uid for uid, data in self.data.items()
                    if data.version_uid == self.version.uid]
        figures = figures_in(self.conn, self.version.uid)
        roots = {self.data[uid].record.operation_uid for uid in own_data}
        roots |= {figure.operation_uid for figure in figures}
        ordered, consumed_inputs = self._climb(roots)
        datasets = list(dict.fromkeys([*own_data, *(
            use.uid for op_uid in ordered for use in self.consumed[op_uid]
            if use.item_kind == "dataset" and use.uid in self.data)]))
        self._read_staleness(ordered, datasets)
        parts = {uid: self._part(self.data[uid]) for uid in datasets}
        places, to_copy = self._places(datasets, parts)
        unavailable = {uid for uid in datasets if not self._readable(uid, parts[uid], places)}
        op_states = {op_uid: self._operation_state(op_uid, parts, places, unavailable)
                     for op_uid in ordered}
        op_parts = self._operation_parts(ordered, parts)

        items: list[RevisionItem] = []
        accept: list[AcceptItem] = []
        for uid in datasets:
            item, entry = self._dataset_item(uid, parts[uid], places[uid], uid in unavailable)
            items.append(item)
            if entry is not None:
                accept.append(entry)
        accept.sort(key=lambda entry: (entry.name, entry.item_uid))
        for op_uid in ordered:
            items.append(self._item(ItemKind.OPERATION, op_uid, op_parts[op_uid],
                                    op_states[op_uid]))
            if op_uid in self.review or op_uid in self.figure_only:
                state = ItemState.REVIEW if op_uid in self.review else ItemState.STALE
                accept.append(AcceptItem(ItemKind.OPERATION, op_uid,
                                         self.operations[op_uid].op_type, state,
                                         self._stale_text("operation", op_uid)))
        items.extend(self._parameters(ordered, op_parts))
        input_items, input_accept, changed = self._inputs(datasets, consumed_inputs)
        items.extend(input_items)
        accept.extend(input_accept)
        items.extend(self._item(ItemKind.FIGURE, figure.uid, ItemPart.PRODUCED,
                                op_states.get(figure.operation_uid, ItemState.CURRENT))
                     for figure in figures)

        referenced = tuple(item for item in items if item.item_kind is ItemKind.DATASET
                           and not item.copied and item.snapshot_path is not None
                           and item.part is not ItemPart.INHERITED)
        size = sum(copy.size for copy in to_copy)
        if any(copy.record.store is Store.GPKG for copy in to_copy):
            size += GPKG_BASE_BYTES
        return FreezePlan(
            version=self.version, revision=self.revision, items=tuple(items),
            to_copy=tuple(to_copy), referenced=referenced, accept=tuple(accept),
            blockers=self._blockers(changed), bytes_to_copy=size, space_needed=_with_margin(size),
        )

    def _read_staleness(self, ordered: list[str], datasets: list[str]) -> None:
        """Lo obsoleto de lo del plan según la caché de la 008: las operaciones y los datos
        con causas, las que esperan revisión a mano y las que solo dejan cifras."""
        planned = set(ordered)
        self.stale_ops = {str(row[0]) for row in self._select(_STALE, planned, ("operation",))}
        self.stale_data = {str(row[0]) for row in self._select(_STALE, datasets, ("dataset",))}
        self.review = set(stale.review_operations(self.conn)) & planned
        self.figure_only = set(stale.figure_only_operations(self.conn)) & planned

    def _places(self, datasets: list[str], parts: Mapping[str, ItemPart]
                ) -> tuple[dict[str, _Copy | None], list[CopyItem]]:
        """Dónde queda el contenido de cada dato del plan (``None``: en ninguna instantánea)
        y lo que se copia en esta: lo producido y lo de aguas arriba que no está ya copiado,
        una vez cada contenido; lo heredado, donde lo dejó la padre."""
        places: dict[str, _Copy | None] = {}
        to_copy: list[CopyItem] = []
        planned: dict[tuple[str, str, str], _Copy] = {}
        layers: set[str] = set()
        for uid in datasets:
            record = self.data[uid].record
            part = parts[uid]
            if part is ItemPart.INHERITED:
                places[uid] = self._inherited(uid)
                continue
            if part is ItemPart.IMMUTABLE or record.store not in COPIED_STORES:
                places[uid] = None
                continue
            key = (record.content_sha256, record.reader, record.normalizer)
            place = self._existing_copy(*key)
            if place is None and key in planned:  # el mismo contenido, ya en el plan
                place = _Copy(False, planned[key].path, planned[key].layer)
            elif place is None and record.status is DatasetStatus.CURRENT:
                place = planned[key] = self._place(record, layers)
                to_copy.append(CopyItem(record, part, place.path, place.layer,
                                        self._size(record)))
            places[uid] = place
        return places, to_copy

    def _operation_state(self, op_uid: str, parts: Mapping[str, ItemPart],
                         places: Mapping[str, _Copy | None], unavailable: set[str]) -> ItemState:
        """«No reproducible» si consumió un contenido que no queda guardado; si no, el de la
        caché (revisar a mano, obsoleta o al día)."""
        if any(not self._available(use, parts, places, unavailable)
               for use in self.consumed[op_uid] if use.item_kind == "dataset"):
            return ItemState.NOT_REPRODUCIBLE
        if op_uid in self.review:
            return ItemState.REVIEW
        return ItemState.STALE if op_uid in self.stale_ops else ItemState.CURRENT

    def _dataset_item(self, uid: str, part: ItemPart, place: _Copy | None, unavailable: bool
                      ) -> tuple[RevisionItem, AcceptItem | None]:
        """El elemento de un dato y, si es un obsoleto que hay que aceptar, su entrada (no la
        del que escribió una operación que espera revisión a mano: se acepta ella)."""
        record = self.data[uid].record
        stale_here = part is not ItemPart.INHERITED and uid in self.stale_data
        review = record.operation_uid in self.review
        if unavailable:
            state = ItemState.NOT_REPRODUCIBLE
        elif stale_here:
            state = ItemState.REVIEW if review else ItemState.STALE
        else:
            state = ItemState.CURRENT
        content = (self._inherited_content(uid) if part is ItemPart.INHERITED
                   else record.content_sha256)
        item = RevisionItem(self.revision.uid, ItemKind.DATASET, uid, part, None, content,
                            place is not None and place.copied,
                            None if place is None else place.path,
                            None if place is None else place.layer,
                            None if place is None else place.file_sha256,
                            None if place is None else place.file_size, state)
        if not stale_here or review:
            return item, None
        return item, AcceptItem(ItemKind.DATASET, uid, record.name, ItemState.STALE,
                                self._stale_text("dataset", uid))

    def _item(self, kind: ItemKind, uid: str, part: ItemPart, state: ItemState, *,
              rev: int | None = None, content: str | None = None) -> RevisionItem:
        """Un elemento sin copia (operación, cifra, parámetro o entrada)."""
        return RevisionItem(self.revision.uid, kind, uid, part, rev, content, False, None, None,
                            None, None, state)

    def _part(self, data: _Data) -> ItemPart:
        if data.version_uid == self.version.uid:
            return ItemPart.PRODUCED
        if data.version_uid:
            return ItemPart.INHERITED
        return ItemPart.IMMUTABLE if data.record.immutable else ItemPart.UPSTREAM

    def _operation_parts(self, ordered: list[str],
                         parts: Mapping[str, ItemPart]) -> dict[str, ItemPart]:
        """Las de la versión, producidas; las demás, la parte más propia de los datos por los
        que se llegó a ellas (lo derivado, aguas arriba; lo importado, inmutable)."""
        found: dict[str, ItemPart] = {}
        for op_uid in ordered:
            if self.operations[op_uid].revision_uid:
                found[op_uid] = ItemPart.PRODUCED
                continue
            mine = [parts[uid] for uid in self.reached.get(op_uid, ()) if uid in parts]
            found[op_uid] = min(mine or [ItemPart.UPSTREAM], key=_RANK.__getitem__)
        return found

    def _inherited(self, dataset_uid: str) -> _Copy | None:
        """Dónde está lo congelado de la padre (``gb_revision_item`` de la revisión de la que
        parte la versión): ``None`` si no está o la revisión está alterada (D-27)."""
        if self.parent is None or self.parent.altered:
            return None
        row = self.conn.execute(_FROZEN_ITEM, (self.parent.uid, dataset_uid)).fetchone()
        if row is None or row[0] is None:
            return None
        return _Copy(False, str(row[0]), None if row[1] is None else str(row[1]),
                     None if row[2] is None else str(row[2]),
                     None if row[3] is None else int(row[3]))

    def _inherited_content(self, dataset_uid: str) -> str:
        """El contenido congelado que consumieron de la padre las operaciones de la versión."""
        for uses in self.consumed.values():
            for use in uses:
                if use.uid == dataset_uid:
                    return use.content_sha256
        return self.data[dataset_uid].record.content_sha256  # pragma: no cover

    def _place(self, record: DatasetRecord, layers: set[str]) -> _Copy:
        """Dónde queda en esta instantánea la copia de ``record``: una tabla, en su GeoPackage
        con su nombre (otro, si ya lo lleva otra: un dato con selector, D-29); un fichero, con
        su ruta en el proyecto."""
        if record.store is Store.GPKG:
            layer = record.locator
            if layer in layers:
                layer = f"{record.locator}_{record.uid[:8]}"
            layers.add(layer)
            return _Copy(True, f"{self.folder}/{self.label}.gpkg", layer)
        return _Copy(True, f"{self.folder}/{record.locator}", None)

    def _size(self, record: DatasetRecord) -> int:
        """Lo que se estima que ocupa la copia: un fichero, su tamaño (el registrado si ya no
        está); una tabla, sus valores, una cabecera por fila y sus páginas."""
        if record.store is not Store.GPKG:
            try:
                return os.stat(Path(self.project.root, *record.locator.split("/"))).st_size
            except OSError:
                return int(record.tracked_size or 0)
        names = [str(row[1]) for row in self.conn.execute(
            f"PRAGMA table_info({_quote(record.locator)})")]
        if not names:
            return TABLE_BYTES
        condition, values = selector_condition(self.conn, record.selector, names,
                                               record.locator)
        size = " + ".join(
            f"CASE typeof({_quote(name)}) WHEN 'null' THEN 0 WHEN 'integer' THEN 8 "
            f"WHEN 'real' THEN 8 ELSE length(CAST({_quote(name)} AS BLOB)) END"
            for name in names)
        rows, total = self.conn.execute(_TABLE_SIZE.format(
            values=size, table=record.locator.replace('"', '""'),
            where=f" WHERE {condition}" if condition else ""), values).fetchone()
        return TABLE_BYTES + int(rows) * ROW_BYTES + int(total or 0)

    def _readable(self, uid: str, part: ItemPart, places: Mapping[str, _Copy | None]) -> bool:
        """Si el contenido de un dato del plan queda guardado: copiado o referenciado, lo
        inmutable que aún se puede leer o lo heredado de la padre."""
        record = self.data[uid].record
        if record.store is Store.DUCKDB:
            return False  # D-37: hasta R-22
        if part is ItemPart.IMMUTABLE:
            return record.status not in _UNREADABLE
        return places.get(uid) is not None

    def _available(self, use: _Use, parts: Mapping[str, ItemPart],
                   places: Mapping[str, _Copy | None], unavailable: set[str]) -> bool:
        """Si lo que consumió una operación queda guardado: el contenido que consumió es el
        que guarda el plan de ese dato, o está copiado en otra revisión congelada."""
        data = self.data.get(use.uid)
        if data is None:
            return False
        record = data.record
        if use.uid not in unavailable:
            if parts.get(use.uid) is ItemPart.INHERITED:
                return True
            if record.content_sha256 == use.content_sha256:
                return True
        if record.store is Store.DUCKDB:
            return False
        return self._existing_copy(use.content_sha256, record.reader,
                                   record.normalizer) is not None

    def _parameters(self, ordered: list[str],
                    op_parts: Mapping[str, ItemPart]) -> list[RevisionItem]:
        """Cada fila de parámetro que leyeron las operaciones del plan: la ``rev`` que leyó la
        última que la leyó, su ``value_sha256`` y la parte más propia de quien la leyó;
        obsoleta si hoy vale otra cosa."""
        chosen: dict[str, tuple[int, str]] = {}
        part_of: dict[str, ItemPart] = {}
        for op_uid in ordered:
            for parameter_uid, rev, sha in self.uses[op_uid]:
                chosen[parameter_uid] = (rev, sha)
                part = op_parts[op_uid]
                previous = part_of.get(parameter_uid)
                part_of[parameter_uid] = part if previous is None else min(
                    previous, part, key=_RANK.__getitem__)
        current = {str(uid): str(sha) for uid, sha in self._select(_PARAMETERS, chosen)}
        return [self._item(ItemKind.PARAMETER, uid, part_of[uid],
                           ItemState.STALE if current.get(uid, sha) != sha else ItemState.CURRENT,
                           rev=rev, content=sha)
                for uid, (rev, sha) in chosen.items()]

    def _inputs(self, datasets: list[str], consumed: set[str]
                ) -> tuple[list[RevisionItem], list[AcceptItem], list[str]]:
        """Las entradas de lo importado del plan y las que consumieron sus operaciones: cada
        una, inmutable con su contenido; las activas cuya fuente no se encuentra, no
        localizables (RF-008-13), y las cambiadas sin decidir, lo que impide congelar."""
        wanted = [self.data[uid].record.input_uid for uid in datasets
                  if self.data[uid].record.immutable and self.data[uid].record.input_uid]
        records: list[InputRecord] = []
        for uid in dict.fromkeys([*(str(uid) for uid in wanted), *sorted(consumed)]):
            record = input_registry.get(self.conn, uid)
            if record is not None:
                records.append(record)
        records.sort(key=lambda record: (record.name.casefold(), record.uid))
        tables: dict[str, str | None] | None = None
        items: list[RevisionItem] = []
        accept: list[AcceptItem] = []
        changed: list[str] = []
        for record in records:
            state = ItemState.CURRENT
            if record.status in _ACTIVE_INPUTS:
                if tables is None and any(item.anchor is FileAnchor.PROJECT_TABLE
                                          for item in record.files):
                    tables = table_changes(self.conn)
                probe = probe_input(self.project, record, tables=tables)
                if probe.missing is not None:
                    state = ItemState.UNLOCATABLE
                    accept.append(AcceptItem(ItemKind.INPUT, record.uid, record.name, state,
                                             provenance_messages.render(
                                                 "core.input_unreachable", name=record.name,
                                                 file=probe.missing)))
            if record.status is InputStatus.CHANGED:
                changed.append(record.name)
            items.append(self._item(ItemKind.INPUT, record.uid, ItemPart.IMMUTABLE, state,
                                    content=record.content_sha256))
        return items, accept, changed

    def _stale_text(self, item_kind: str, uid: str) -> str:
        return stale.item_text(self.conn, item_kind, uid) or ""

    def _blockers(self, changed: list[str]) -> tuple[Blocker, ...]:
        found: list[tuple[BlockReason, tuple[str, ...]]] = []
        if not self.project.writable:
            found.append((BlockReason.READ_ONLY, ()))
        if self.pending is not None and self.pending.running:
            found.append((BlockReason.OPEN_CHECK, ()))
        freezing = self._freezing()
        if freezing:
            found.append((BlockReason.FREEZING, freezing))
        running = tuple(dict.fromkeys(str(row[0]) for row in self.conn.execute(
            _RUNNING, (self.revision.uid,))))
        if running:
            found.append((BlockReason.RUNNING, running))
        if changed:
            found.append((BlockReason.INPUT_CHANGED, tuple(changed)))
        return tuple(Blocker(reason, names, render(
            _BLOCK_MESSAGES[reason], revision=self.label,
            names=", ".join(f"«{name}»" for name in names))) for reason, names in found)

    def _freezing(self) -> tuple[str, ...]:
        """Las carpetas temporales de una congelación en curso en ``snapshots/``."""
        folder = Path(self.project.root, SNAPSHOTS_DIR)
        try:
            with os.scandir(folder) as entries:
                return tuple(sorted(entry.name for entry in entries
                                    if FREEZING_MARK in entry.name and entry.is_dir()))
        except OSError:
            return ()


# --- Congelar: el plan, la copia y la confirmación (A5 → A6 → A7) ---------------------------

CONFIRM_PHASE = "confirmación"
"""La fase de la confirmación (A7), tras las de la copia (``core.versions.copy.PHASES``)."""
STEP_BUDGET_S = 0.05
"""El trabajo entre dos progresos de la copia (como el modal de la 010)."""
_ROWS_PER_STATEMENT = 500
"""Las filas de ``gb_revision_item`` de cada ``INSERT`` (trampa §6: no una sentencia por
fila; 12 columnas: 6 000 parámetros)."""
_ITEM_COLUMNS = (
    "revision_uid, item_kind, item_uid, part, item_rev, content_sha256, copied, snapshot_path, "
    "snapshot_layer, file_sha256, file_size, state"
)
_REVISION_OPERATIONS = (  # por gb_operation_revision
    f"{QUERY_TAG} SELECT uid, op_type, status FROM gb_operation WHERE revision_uid = ? "
    "AND revision_uid <> '' ORDER BY fid"
)
_CONTENTS = f"{QUERY_TAG} SELECT uid, name, content_sha256 FROM gb_dataset WHERE uid IN ({{marks}})"


@dataclass(frozen=True)
class Acceptance:
    """Lo que el usuario aceptó al congelar (RF-009-08): cada elemento de la lista que vio
    (:attr:`FreezePlan.accept`), por su clase (``dataset``, ``operation``, ``input``) y su uid.
    Congelar exige que cubra todo lo que el plan pide aceptar en ese momento."""

    items: frozenset[tuple[str, str]]

    @classmethod
    def of(cls, plan: FreezePlan) -> Acceptance:
        """La aceptación de todo lo que pide aceptar ``plan`` («Aceptar y congelar»)."""
        return cls(frozenset((str(entry.item_kind), entry.item_uid) for entry in plan.accept))

    def covers(self, plan: FreezePlan) -> bool:
        """Si acepta todo lo que pide aceptar ``plan``."""
        return Acceptance.of(plan).items <= self.items


@dataclass(frozen=True)
class FreezeOutcome:
    """El final de una congelación (:func:`freeze_steps`): la revisión (``label``, «V10.r2»),
    la congelada y la siguiente, abierta (``None`` las dos si se canceló), los ficheros que
    copió su instantánea y lo que suman (sin el manifiesto), lo que referencia a otra
    instantánea (D-28), los avisos (la cabecera que no se pudo escribir) y si se canceló."""

    label: str
    frozen: Revision | None
    opened: Revision | None
    files: tuple[SnapshotFile, ...]
    copied_bytes: int
    referenced: tuple[RevisionItem, ...]
    warnings: tuple[str, ...] = ()
    cancelled: bool = False


class FreezeProject(PlanProject, Protocol):
    """Lo que usa :func:`freeze_steps` del proyecto (``core.project.Project``): lo del plan y
    lo de la copia (su identidad, su registro, la sesión y el reloj, su caché) y escribir con
    reintento y regenerar la cabecera."""

    @property
    def uid(self) -> str: ...

    record: ProjectRecord | None
    session: SessionInfo
    clock: Clock

    def cache_dir(self) -> Path: ...

    def try_write(self, work: Callable[[sqlite3.Connection], Any]) -> WriteAttempt: ...

    def refresh_header(self) -> bool: ...


def _budget(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"el presupuesto de un paso es un número de segundos, no {value!r}")
    if not value > 0:
        raise ValueError(f"el presupuesto de un paso es positivo, no {value!r}")
    return float(value)


def _reason(value: object) -> str:
    """El motivo de la revisión nueva (RF-009-06: obligatorio), sin rutas absolutas."""
    if value is not None and not isinstance(value, str):
        raise TypeError(f"el motivo es un texto, no {type(value).__name__} ({value!r})")
    text = (value or "").strip()
    if not text:
        raise VersionError("core.version_freeze_reason", field="motivo", value=value)
    if find_absolute_paths(text):
        raise VersionError("core.version_text_path", field="motivo", value=value, text=text)
    return text


def _names(names: Iterable[str]) -> str:
    return ", ".join(f"«{name}»" for name in names)


def freeze_steps(project: FreezeProject, version_uid: str, *, reason: str,
                 accepted: Acceptance | None = None, pending: CheckState | None = None,
                 budget_s: float = STEP_BUDGET_S,
                 cancelled: Callable[[], bool] | None = None) -> Iterator[Progress]:
    """Congela la revisión abierta de la versión ``version_uid`` (uid o código) y abre la
    siguiente con el motivo ``reason`` (RF-009-06, RF-009-07; plan A5 → A6 → A7): véase el
    módulo. Los pasos son ``core.project.model.Progress`` en las fases de la copia
    (``core.versions.copy.PHASES``, cada ``budget_s`` s de trabajo) y, al final, en
    :data:`CONFIRM_PHASE`; el último lleva el :class:`FreezeOutcome`. ``accepted``: lo que el
    usuario aceptó (RF-009-08); ``pending``: lo que la comprobación de apertura aún no ha
    comprobado (si sigue, lo impide, D-40); ``cancelled()``, si se consulta verdadero tras un
    paso, cancela como cerrar los pasos (Esc), pero termina con un :class:`FreezeOutcome`
    cancelado. Cancelar, fallar o un cambio en lo congelado no dejan nada.

    Al llamarla, sin escribir nada: los rechazos de :func:`freeze_plan`; ``VersionError``
    sin motivo (``core.version_freeze_reason``) o con una ruta absoluta en él
    (``core.version_text_path``), con algo que lo impide (el código de lo primero que lo
    impide: ``core.version_freeze_read_only``, ``…_checking``, ``…_in_progress``,
    ``…_running`` o ``…_input_changed``) o con algo que aceptar que ``accepted`` no cubre
    (``core.version_freeze_accept``); :class:`TypeError` o :class:`ValueError` con un
    argumento mal dado. Al confirmar: ``core.version_freeze_operation`` si se registró una
    operación de la versión mientras se copiaba y ``core.version_freeze_changed`` si cambió el
    contenido de algo congelado (D-40); los de la copia (``core.versions.copy.copy_steps``),
    tal cual."""
    text = _reason(reason)
    budget = _budget(budget_s)
    if accepted is not None and not isinstance(accepted, Acceptance):
        raise TypeError(f"lo aceptado es una Acceptance, no {accepted!r}")
    if cancelled is not None and not callable(cancelled):
        raise TypeError(f"«cancelled» es una función sin argumentos, no {cancelled!r}")
    with project.read() as conn:
        conn.execute("BEGIN")  # el plan y las operaciones de la revisión, en una instantánea
        try:
            plan = freeze_plan(project, version_uid, conn=conn, pending=pending)
            stamp = frozenset((str(uid), str(status)) for uid, _op_type, status
                              in conn.execute(_REVISION_OPERATIONS, (plan.revision.uid,)))
        finally:
            conn.execute("ROLLBACK")
    if plan.blockers:
        blocker = plan.blockers[0]
        raise VersionError(_BLOCK_MESSAGES[blocker.reason], field="revisión", value=plan.label,
                           version=plan.version.code, revision=plan.label,
                           names=_names(blocker.names))
    if plan.accept and (accepted is None or not accepted.covers(plan)):
        raise VersionError("core.version_freeze_accept", field="aceptación", value=plan.label,
                           version=plan.version.code, revision=plan.label,
                           names=_names(dict.fromkeys(entry.name for entry in plan.accept)))
    return _freeze(project, plan, stamp, reason=text, budget=budget, cancelled=cancelled)


def _freeze(project: FreezeProject, plan: FreezePlan, stamp: frozenset[tuple[str, str]], *,
            reason: str, budget: float,
            cancelled: Callable[[], bool] | None) -> Iterator[Progress]:
    # Aquí: core.versions.copy importa este módulo (ARQ-08).
    from .copy import (
        SnapshotCopy,
        _failed,
        _size_text,
        acceptance,
        copy_steps,
        discard,
        rename_snapshot,
        temporary_path,
    )

    root = Path(project.root)
    temporary = temporary_path(root, plan.label)
    final = root.joinpath(*plan.snapshot_dir.split("/"))
    copied: SnapshotCopy | None = None
    renamed = False
    freezing_registry.register(project, temporary)
    try:
        steps = copy_steps(project, plan, temporary, project.cache_dir(), budget_s=budget,
                           accepted=acceptance(plan, reason=reason))
        stopped = False
        total = 1
        try:
            for step in steps:
                total = step.total
                if isinstance(step.result, SnapshotCopy):
                    copied = step.result
                    step = Progress(step.phase, step.done, step.total, step.message)
                yield step
                if cancelled is not None and cancelled():
                    stopped = True
                    break
        finally:
            steps.close()  # a medias, la copia no deja nada
        if stopped or copied is None:
            yield Progress(CONFIRM_PHASE, 0, total,
                           "Congelación cancelada: no ha quedado nada a medias",
                           FreezeOutcome(plan.label, None, None, (), 0, (), cancelled=True))
            return
        snapshot = copied

        def work(conn: sqlite3.Connection) -> tuple[Revision, Revision]:
            nonlocal renamed
            revisions = _confirm(conn, project, plan, snapshot, stamp, reason=reason)
            rename_snapshot(temporary, final, clock=project.clock)  # antes del COMMIT (A6 (4))
            renamed = True
            return revisions

        yield Progress(CONFIRM_PHASE, total, total, f"Confirmando {plan.label}…")
        while True:
            attempt = project.try_write(work)
            if attempt.state is WriteState.DONE:
                break
            if renamed:  # otro programa leía: la transacción no se confirmó; otra vez
                try:
                    os.rename(final, temporary)
                except OSError as exc:
                    raise _failed(plan.label, exc, plan.snapshot_dir, plan.version.code) from exc
                renamed = False
            yield Progress(CONFIRM_PHASE, total, total, attempt.message)
        frozen, opened = attempt.value
    finally:
        freezing_registry.unregister(temporary)
        if copied is not None and not renamed:
            discard(temporary, clock=project.clock)
    warnings: list[str] = []
    try:
        project.refresh_header()
    except (GeoblenderError, OSError) as exc:
        message = (f"La revisión {plan.label} está congelada, pero no se ha podido actualizar la "
                   f"cabecera (manifest.json): {exc}. Se regenerará desde la base de datos al "
                   "abrir el proyecto.")
        log_event(EventKind.WRITE_FAILED, message, project=project.uid)
        warnings.append(message)
    referenced = tuple(item for item in snapshot.items if item.item_kind is ItemKind.DATASET
                       and not item.copied and item.snapshot_path is not None
                       and item.part is not ItemPart.INHERITED)
    shown = f"{_size_text(snapshot.copied_bytes)} copiados"
    if referenced:
        shown += f"; {len(referenced)} contenidos ya congelados, referenciados"
    yield Progress(CONFIRM_PHASE, total, total,
                   f"{plan.label} congelada ({shown}); "
                   f"{opened.label(plan.version.code)} abierta",
                   FreezeOutcome(plan.label, frozen, opened, snapshot.files,
                                 snapshot.copied_bytes, referenced, tuple(warnings)))


def _confirm(conn: sqlite3.Connection, project: FreezeProject, plan: FreezePlan,
             snapshot: SnapshotCopy, stamp: frozenset[tuple[str, str]], *,
             reason: str) -> tuple[Revision, Revision]:
    """A7 en la transacción ``conn``: lo congelado sigue siendo lo vigente; sus elementos; la
    revisión congelada; la siguiente, abierta; sus eventos. Devuelve las dos revisiones."""
    version = read.version(conn, plan.version.uid)
    if version is None:  # pragma: no cover - nada se borra
        raise VersionError("core.version_unknown", field="versión", value=plan.version.code,
                           version=plan.version.code)
    ensure_editable(version)  # descartada mientras se copiaba
    current = read.open_revision(conn, version.uid)
    if current is None or current.uid != plan.revision.uid:  # pragma: no cover - un escritor
        raise VersionError("core.version_freeze_changed", field="revisión", value=plan.label,
                           version=version.code, revision=plan.label, dataset=plan.label)
    _check_current(conn, plan, snapshot.items, stamp)
    now = format_utc(project.clock.now())
    user = project.session.user_host
    items = [_item_row(item) for item in snapshot.items]
    for start in range(0, len(items), _ROWS_PER_STATEMENT):
        chunk = items[start:start + _ROWS_PER_STATEMENT]
        marks = ", ".join("(" + ", ".join("?" * 12) + ")" for _ in chunk)
        conn.execute(f"INSERT INTO gb_revision_item ({_ITEM_COLUMNS}) VALUES {marks}",
                     [value for row in chunk for value in row])
    accepted = (None if snapshot.accepted is None
                else canonical_json(snapshot.accepted).decode("utf-8"))
    conn.execute(
        "UPDATE gb_revision SET state = ?, closed_at = ?, closed_by = ?, snapshot_dir = ?, "
        "snapshot_sha256 = ?, snapshot_bytes = ?, geoblender_version = ?, accepted = ? "
        "WHERE uid = ?",
        (RevisionState.FROZEN.value, snapshot.frozen_at, snapshot.frozen_by, plan.snapshot_dir,
         snapshot.manifest_sha256, snapshot.copied_bytes, snapshot.geoblender_version, accepted,
         plan.revision.uid))
    following = new_uid()
    conn.execute(
        "INSERT INTO gb_revision (uid, version_uid, number, state, reason, created_at, "
        "created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (following, version.uid, plan.revision.number + 1, RevisionState.OPEN.value, reason, now,
         user))
    _record(conn, project, plan, snapshot, version, following, reason=reason, now=now)
    frozen, opened = read.revision(conn, plan.revision.uid), read.revision(conn, following)
    if frozen is None or opened is None:  # pragma: no cover - se acaban de escribir
        raise RuntimeError(f"la revisión {plan.label} no se ha podido leer tras congelarla")
    return frozen, opened


def _check_current(conn: sqlite3.Connection, plan: FreezePlan, items: Iterable[RevisionItem],
                   stamp: frozenset[tuple[str, str]]) -> None:
    """Lo congelado sigue siendo lo vigente (A7, D-40): ninguna operación de la revisión nueva
    o que cambió de estado desde el plan, y el mismo contenido en cada dato congelado (lo
    heredado de la padre está congelado en ella)."""
    for uid, op_type, status in conn.execute(_REVISION_OPERATIONS, (plan.revision.uid,)):
        if (str(uid), str(status)) not in stamp:
            raise VersionError("core.version_freeze_operation", field="operación",
                               value=str(op_type), version=plan.version.code,
                               revision=plan.label, op_type=str(op_type))
    wanted = {item.item_uid: item.content_sha256 for item in items
              if item.item_kind is ItemKind.DATASET and item.part is not ItemPart.INHERITED}
    uids = sorted(wanted)
    for start in range(0, len(uids), _CHUNK):
        chunk = uids[start:start + _CHUNK]
        for uid, name, content in conn.execute(
                _CONTENTS.format(marks=", ".join("?" for _ in chunk)), chunk):
            if str(content) != wanted[str(uid)]:
                raise VersionError("core.version_freeze_changed", field="dato", value=str(name),
                                   version=plan.version.code, revision=plan.label,
                                   dataset=str(name))


def _item_row(item: RevisionItem) -> tuple[Any, ...]:
    return (item.revision_uid, str(item.item_kind), item.item_uid, str(item.part), item.item_rev,
            item.content_sha256, int(item.copied), item.snapshot_path, item.snapshot_layer,
            item.file_sha256, item.file_size, str(item.state))


def _record(conn: sqlite3.Connection, project: FreezeProject, plan: FreezePlan,
            snapshot: SnapshotCopy, version: Version, following: str, *, reason: str,
            now: str) -> None:
    """Los eventos ``revision_frozen`` (con lo copiado; lo referenciado, cuántos en su texto:
    cada uno, con su ruta y su capa, ya está en ``gb_revision_item``, T33) y
    ``revision_opened`` (con su motivo), sin rutas absolutas."""
    from .copy import _size_text

    user = project.session.user_host
    referenced = sum(1 for item in snapshot.items
                     if item.item_kind is ItemKind.DATASET and not item.copied
                     and item.snapshot_path is not None and item.part is not ItemPart.INHERITED)
    accepted = 0 if snapshot.accepted is None else len(snapshot.accepted.get("items", ()))
    message = (f"Revisión {plan.label} congelada por {user}: {len(snapshot.files)} fichero(s) "
               f"copiado(s) ({_size_text(snapshot.copied_bytes)}), {referenced} "
               f"contenido(s) ya congelado(s), referenciado(s), y {len(snapshot.items)} "
               "elemento(s) anotado(s)")
    if accepted:
        message += f"; aceptado(s) {accepted}: {snapshot.accepted['reason']}"  # type: ignore[index]
    record_event(conn, EventKind.REVISION_FROZEN, message, session=project.session, at=now,
                 entity_kind="revision", entity_uid=plan.revision.uid, data={
                     "version": version.code, "revision": plan.label,
                     "snapshot_dir": plan.snapshot_dir,
                     "snapshot_sha256": snapshot.manifest_sha256,
                     "snapshot_bytes": snapshot.copied_bytes,
                     "geoblender_version": snapshot.geoblender_version,
                     "items": len(snapshot.items),
                     "copied": [{"path": item.path, "size": item.size}
                                for item in snapshot.files],
                     "accepted": accepted,
                 })
    label = f"{version.code}.r{plan.revision.number + 1}"
    record_event(conn, EventKind.REVISION_OPENED,
                 f"Revisión {label} abierta por {user} tras congelar {plan.label}. Motivo: "
                 f"{reason}", session=project.session, at=now, entity_kind="revision",
                 entity_uid=following, data={"version": version.code, "revision": label,
                                             "previous": plan.label, "reason": reason})
