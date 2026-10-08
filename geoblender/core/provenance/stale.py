# SPDX-License-Identifier: GPL-3.0-or-later
"""Caché de la obsolescencia deducida, sus recuentos y su lista (spec 008; RF-008-24,
RF-008-28; ADR-0025 §5; plan 008 §5.1, §5.3.1, §5.4.3 y D3).

La obsolescencia se deduce del grafo (:mod:`.graph`); la tabla ``gb_stale`` es su **caché**:
una fila por causa de cada operación obsoleta (también las sustituidas, la historia, que el
cálculo por región necesita) y de cada dato vivo obsoleto (:func:`expected_rows`). Se escribe
**por diferencias** (una causa que sigue conserva su fecha, ``since``; la nueva lleva la del
cambio; la que ya no está se borra) en la **misma transacción** de cada camino que escribe:

- :func:`refresh_region`, con lo que acaba de cambiar (operaciones hechas, datos con otro
  contenido o estado, parámetros con otro valor, entradas sustituidas, descartadas o
  mantenidas): busca con los índices de ``gb_operation_io`` y ``gb_operation_param`` la
  **región** (lo que consumió lo cambiado y, en cascada, lo que consume lo que producen y su
  ejecución de grupo), carga solo esa parte del grafo y quién escribió lo que consume, toma de
  la caché las causas de lo de fuera de las que depende y reescribe las filas de la región y de
  sus datos (:func:`.graph.deduce_region`). La llaman ``ParameterStore.change`` y ``confirm``,
  ``OperationHandle.complete`` (también la edición externa, ``core.external_edit``), el estado
  de un dato (``core.datasets.set_status`` y ``supersede``: falta, bloqueado, dañado, vigente,
  descartado, sustituido) y ``core.inputs.supersede``, ``discard`` y ``keep_copy``;
- :func:`refresh_all`, la completa (la comprobación de apertura, tras cambiar la versión
  instalada de un algoritmo o si alguien alteró la caché).

Para la interfaz (sin recalcular nada): :func:`counts` («! n obsoletos» = datos vivos
obsoletos más operaciones que esperan revisión a mano; «⚠ n entradas» = las cambiadas sin
decidir) y :func:`stale_items` (lo obsoleto y lo que espera revisión a mano, con su causa, su
módulo, la operación que lo escribió y desde cuándo). Python puro (ADR-0004).
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol

from ..timeutil import parse_utc
from .graph import (
    DATASET_COLUMNS,
    INPUT_NODE_COLUMNS,
    IO_COLUMNS,
    OPERATION_COLUMNS,
    PARAM_USE_COLUMNS,
    PARAMETER_COLUMNS,
    Cause,
    CauseKind,
    DatasetNode,
    OperationNode,
    ParamUse,
    ProvenanceGraph,
    Staleness,
    Version,
    dataset_node,
    deduce,
    deduce_region,
    input_node,
    installed_versions,
    load_graph,
    operation_node,
    param_use_of,
    parameter_node,
    root_causes,
    stale_text,
    version_of,
)
from .schema import LIVE_DATASET_STATUSES

OPERATION = "operation"
DATASET = "dataset"
ITEM_KINDS: tuple[str, ...] = (DATASET, OPERATION)
"""Lo que guarda la caché (``gb_stale.item_kind``), en el orden de la lista."""
CHANGED_INPUT = "changed"
"""El estado de una entrada cambiada sin decidir (``gb_input.status``): «⚠ n entradas»."""
CHUNK = 500
"""Cuántos uid van, como mucho, en cada ``IN (…)`` de una consulta."""

_LIVE = ", ".join(f"'{status}'" for status in LIVE_DATASET_STATUSES)
_DONE = "op.status = 'done'"

_DONE_OPERATIONS = "SELECT uid FROM gb_operation WHERE status = 'done' AND uid IN ({marks})"
_CONSUMERS = (
    "SELECT DISTINCT io.operation_uid FROM gb_operation_io AS io JOIN gb_operation AS op "
    f"ON op.uid = io.operation_uid WHERE io.item_kind = ? AND io.direction = 'in' AND {_DONE} "
    "AND io.item_uid IN ({marks})"
)
_PARAMETER_CONSUMERS = (
    "SELECT DISTINCT p.operation_uid FROM gb_operation_param AS p JOIN gb_operation AS op "
    f"ON op.uid = p.operation_uid WHERE {_DONE} AND p.parameter_uid IN ({{marks}})"
)
_INPUT_DATASETS = "SELECT uid FROM gb_dataset WHERE input_uid IN ({marks})"
_PRODUCED = (  # «+item_kind»: por el índice de (operation_uid, direction), no el de item_kind
    "SELECT DISTINCT item_uid FROM gb_operation_io WHERE direction = 'out' "
    "AND +item_kind = 'dataset' AND operation_uid IN ({marks})"
)
_GROUPS = (
    "SELECT DISTINCT group_uid FROM gb_operation WHERE group_uid IS NOT NULL "
    "AND uid IN ({marks})"
)
_GROUP_MEMBERS = "SELECT uid FROM gb_operation WHERE status = 'done' AND group_uid IN ({marks})"
_WRITERS = (
    "SELECT DISTINCT io.operation_uid FROM gb_operation_io AS io JOIN gb_operation AS op "
    "ON op.uid = io.operation_uid WHERE io.item_kind = 'dataset' AND io.direction = 'out' "
    f"AND {_DONE} AND io.item_uid IN ({{marks}})"
)
_OPERATIONS = (
    f"SELECT {OPERATION_COLUMNS} FROM gb_operation WHERE status = 'done' "
    "AND uid IN ({marks})"
)
_OPERATIONS_OF_GROUPS = (
    f"SELECT {OPERATION_COLUMNS} FROM gb_operation WHERE status = 'done' "
    "AND group_uid IN ({marks})"
)
_OPERATIONS_OF_TYPES = (
    f"SELECT {OPERATION_COLUMNS} FROM gb_operation WHERE status = 'done' "
    "AND op_type IN ({marks})"
)
_IO = f"SELECT {IO_COLUMNS} FROM gb_operation_io WHERE operation_uid IN ({{marks}}) ORDER BY fid"
_IO_OUT = (
    f"SELECT {IO_COLUMNS} FROM gb_operation_io WHERE direction = 'out' "
    "AND operation_uid IN ({marks}) ORDER BY fid"
)
_USES = (
    f"SELECT {PARAM_USE_COLUMNS} FROM gb_operation_param WHERE operation_uid IN ({{marks}}) "
    "ORDER BY fid"
)
_DATASETS = f"SELECT {DATASET_COLUMNS} FROM gb_dataset WHERE uid IN ({{marks}})"
_INPUTS = f"SELECT {INPUT_NODE_COLUMNS} FROM gb_input WHERE uid IN ({{marks}})"
_PARAMETERS = f"SELECT {PARAMETER_COLUMNS} FROM gb_parameter WHERE uid IN ({{marks}})"
_CACHED = (
    "SELECT item_kind, item_uid, cause_kind, subject_uid FROM gb_stale "
    "WHERE item_kind = ? AND item_uid IN ({marks})"
)
_REVIEW_CANDIDATES = (
    "SELECT DISTINCT op.uid FROM gb_stale AS s JOIN gb_operation AS op ON op.uid = s.item_uid "
    f"WHERE s.item_kind = '{OPERATION}' AND {_DONE} AND op.superseded_by IS NULL "
    "AND op.repeatable = 0"
)
_LIVE_WRITERS = (
    "SELECT DISTINCT d.operation_uid FROM gb_operation_io AS io JOIN gb_dataset AS d "
    "ON d.uid = io.item_uid WHERE io.direction = 'out' AND io.item_kind = 'dataset' "
    f"AND d.operation_uid = io.operation_uid AND d.status IN ({_LIVE}) "
    "AND io.operation_uid IN ({marks})"
)
_FIGURE_KEYS = "SELECT DISTINCT key, scope_key FROM gb_figure WHERE operation_uid IN ({marks})"
_FIGURES_OF_KEY = (
    "SELECT f.operation_uid, EXISTS (SELECT 1 FROM gb_stale AS s "
    f"WHERE s.item_kind = '{OPERATION}' AND s.item_uid = f.operation_uid) "
    "FROM gb_figure AS f JOIN gb_operation AS op ON op.uid = f.operation_uid "
    f"WHERE {_DONE} AND op.superseded_by IS NULL AND f.key = ? AND f.scope_key = ? "
    "ORDER BY f.fid"
)


class StaleRow(NamedTuple):
    """Una fila de la caché ``gb_stale`` sin su fecha: el elemento (``operation`` o
    ``dataset`` y su uid) y una de sus causas (clase y sujeto)."""

    item_kind: str
    item_uid: str
    cause_kind: str
    subject_uid: str

    @property
    def cause(self) -> Cause:
        """La causa de la fila."""
        return Cause(CauseKind(self.cause_kind), self.subject_uid)


@dataclass(frozen=True, slots=True)
class CacheUpdate:
    """Lo que hizo una puesta al día de la caché: las operaciones y los datos cuyas filas se
    rehicieron (la región y sus datos; todo, en la completa) y las filas añadidas y
    borradas."""

    operations: frozenset[str]
    datasets: frozenset[str]
    added: frozenset[StaleRow]
    removed: frozenset[StaleRow]


@dataclass(frozen=True, slots=True)
class Counts:
    """Los recuentos de la barra de estado (RF-008-28; RF-008-16): ``stale``, los datos
    vivos obsoletos; ``review``, las operaciones que esperan revisión a mano;
    ``inputs_changed``, las entradas cambiadas sin decidir («⚠ n entradas»)."""

    stale: int
    review: int
    inputs_changed: int

    @property
    def obsolete(self) -> int:
        """El número de «! n obsoletos»: datos obsoletos más operaciones que esperan
        revisión a mano."""
        return self.stale + self.review


@dataclass(frozen=True, slots=True)
class StaleItem:
    """Un elemento de la lista de lo obsoleto (RF-008-28): un dato vivo obsoleto
    (``dataset``: su nombre y su módulo) o una operación que espera revisión a mano
    (``operation``: su tipo y su módulo), con la operación que escribió el dato (o ella
    misma) y su tipo, si espera revisión a mano (la del dato, la de su operación), sus causas,
    su texto («Obsoleto: cambió Producción») y desde cuándo (la causa más antigua)."""

    item_kind: str
    uid: str
    name: str
    module: str
    operation_uid: str
    op_type: str
    review: bool
    causes: frozenset[Cause]
    text: str
    since: str


@dataclass(frozen=True, slots=True)
class StaleReport:
    """La lista de lo obsoleto: los datos (por nombre) y después las operaciones que esperan
    revisión a mano (por orden de registro), con los recuentos."""

    items: tuple[StaleItem, ...]
    counts: Counts


class ReadableProject(Protocol):
    """Lo que la lista y los recuentos usan del proyecto: una conexión de lectura."""

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


# --- Consultas ------------------------------------------------------------------------------


def _select(conn: sqlite3.Connection, sql: str, values: Collection[str],
            before: tuple[Any, ...] = ()) -> Iterator[tuple[Any, ...]]:
    """Las filas de ``sql`` (con ``{marks}`` en el lugar de la lista) para ``values``, por
    trozos de :data:`CHUNK`; ``before``, los argumentos anteriores a la lista."""
    items = sorted(values)
    for start in range(0, len(items), CHUNK):
        chunk = items[start:start + CHUNK]
        yield from conn.execute(sql.format(marks=", ".join("?" for _ in chunk)),
                                (*before, *chunk))


def _column(conn: sqlite3.Connection, sql: str, values: Collection[str],
            before: tuple[Any, ...] = ()) -> set[str]:
    """La primera columna de :func:`_select`, como conjunto de textos."""
    return {str(row[0]) for row in _select(conn, sql, values, before)}


def _uids(values: Iterable[str], what: str) -> frozenset[str]:
    if isinstance(values, str):
        raise TypeError(f"{what}: una lista de uid, no el texto {values!r}")
    found = frozenset(values)
    for value in found:
        if not isinstance(value, str) or not value:
            raise TypeError(f"{what}: los uid son textos no vacíos, no {value!r}")
    return found


def _writing(conn: object, what: str) -> sqlite3.Connection:
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError(f"{what} recibe la conexión de una transacción de escritura, no "
                        f"{conn!r}")
    if not conn.in_transaction:
        raise ValueError(f"{what} se llama dentro de la transacción de escritura del camino "
                         "que cambió el proyecto (la caché se escribe en ella)")
    return conn


@contextmanager
def _snapshot(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Todas las lecturas en la misma instantánea (si la conexión no está ya en una
    transacción)."""
    began = not conn.in_transaction
    if began:
        conn.execute("BEGIN")
    try:
        yield conn
    finally:
        if began:
            conn.execute("ROLLBACK")


@contextmanager
def _reading(project: ReadableProject,
             conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    if conn is not None:
        with _snapshot(conn):
            yield conn
        return
    with project.read() as reading, _snapshot(reading):
        yield reading


def _rows(item_kind: str, uid: str, causes: Iterable[Cause]) -> Iterator[StaleRow]:
    for cause in causes:
        yield StaleRow(item_kind, uid, str(cause.kind), cause.subject)


def expected_rows(state: Staleness) -> frozenset[StaleRow]:
    """Las filas de la caché que corresponden a la obsolescencia deducida ``state``: las
    causas de cada operación obsoleta (también las sustituidas) y las de cada dato vivo
    obsoleto."""
    return frozenset({
        *(row for uid, found in state.causes.items() for row in _rows(OPERATION, uid, found)),
        *(row for uid, found in state.datasets.items() for row in _rows(DATASET, uid, found)),
    })


def cached_rows(conn: sqlite3.Connection) -> frozenset[StaleRow]:
    """Las filas de la caché ``gb_stale`` (sin su fecha)."""
    return frozenset(StaleRow(*(str(value) for value in row)) for row in conn.execute(
        "SELECT item_kind, item_uid, cause_kind, subject_uid FROM gb_stale"))


def _write(conn: sqlite3.Connection, now: str, items: Mapping[str, Collection[str]],
           desired: set[StaleRow] | frozenset[StaleRow],
           existing: set[StaleRow] | frozenset[StaleRow] | None = None) -> CacheUpdate:
    """Escribe por diferencias las filas de ``items`` (por clase de elemento) para que sean
    ``desired``: borra las que sobran y añade las que faltan con la fecha ``now``."""
    if existing is None:
        existing = {StaleRow(*(str(value) for value in row))
                    for kind, uids in items.items()
                    for row in _select(conn, _CACHED, uids, (kind,))}
    removed = frozenset(existing - desired)
    added = frozenset(desired - existing)
    conn.executemany(
        "DELETE FROM gb_stale WHERE item_kind = ? AND item_uid = ? AND cause_kind = ? "
        "AND subject_uid = ?", sorted(removed),
    )
    conn.executemany(
        "INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, since) "
        "VALUES (?, ?, ?, ?, ?)", [(*row, now) for row in sorted(added)],
    )
    return CacheUpdate(frozenset(items.get(OPERATION, ())), frozenset(items.get(DATASET, ())),
                       added, removed)


def _check_now(now: object) -> str:
    if not isinstance(now, str):
        raise TypeError(f"la fecha de la caché es un texto UTC, no {now!r}")
    parse_utc(now)
    return now


# --- Por región -----------------------------------------------------------------------------


def _region(conn: sqlite3.Connection, operations: frozenset[str], datasets: frozenset[str],
            parameters: frozenset[str],
            inputs: frozenset[str]) -> tuple[frozenset[str], frozenset[str]]:
    """La región de lo cambiado (operaciones hechas) y los datos cambiados (con lo importado
    de las entradas): lo que consumió algo cambiado y, hasta cerrarla, lo que consume
    cualquier versión de lo que producen sus operaciones y su ejecución de grupo."""
    changed = set(datasets)
    if inputs:
        changed |= _column(conn, _INPUT_DATASETS, inputs)
    seeds = _column(conn, _DONE_OPERATIONS, operations)
    seeds |= _column(conn, _CONSUMERS, changed, (DATASET,))
    seeds |= _column(conn, _CONSUMERS, inputs, ("input",))
    seeds |= _column(conn, _PARAMETER_CONSUMERS, parameters)
    region: set[str] = set()
    followed = set(changed)  # datos cuyos consumidores ya están en la región
    groups: set[str] = set()
    frontier = seeds
    while frontier:
        region |= frontier
        produced = _column(conn, _PRODUCED, frontier) - followed
        followed |= produced
        found = _column(conn, _CONSUMERS, produced, (DATASET,))
        new_groups = _column(conn, _GROUPS, frontier) - groups
        groups |= new_groups
        found |= _column(conn, _GROUP_MEMBERS, new_groups)
        frontier = found - region
    return frozenset(region), frozenset(changed)


def _operations(conn: sqlite3.Connection, uids: Collection[str], *,
                full: bool) -> list[OperationNode]:
    """Las operaciones hechas ``uids``: con lo que consumen, producen y leen (``full``) o
    solo con lo que producen (quién escribió cada versión)."""
    consumed: dict[str, list[Version]] = defaultdict(list)
    produced: dict[str, list[Version]] = defaultdict(list)
    used: dict[str, list[ParamUse]] = defaultdict(list)
    for row in _select(conn, _IO if full else _IO_OUT, uids):
        op_uid, out, version = version_of(row)
        (produced if out else consumed)[op_uid].append(version)
    if full:
        for row in _select(conn, _USES, uids):
            op_uid, use = param_use_of(row)
            used[op_uid].append(use)
    return [operation_node(row, consumed[str(row[1])], produced[str(row[1])],
                           used[str(row[1])])
            for row in _select(conn, _OPERATIONS, uids)]


def _cached_causes(conn: sqlite3.Connection,
                   uids: Collection[str]) -> dict[str, frozenset[Cause]]:
    """Las causas en la caché de las operaciones ``uids`` (las que no tienen, al día)."""
    found: dict[str, set[Cause]] = defaultdict(set)
    for row in _select(conn, _CACHED, uids, (OPERATION,)):
        stored = StaleRow(*(str(value) for value in row))
        found[stored.item_uid].add(stored.cause)
    return {uid: frozenset(causes) for uid, causes in found.items()}


def refresh_region(
    conn: sqlite3.Connection,
    *,
    now: str,
    operations: Iterable[str] = (),
    datasets: Iterable[str] = (),
    parameters: Iterable[str] = (),
    inputs: Iterable[str] = (),
    versions: Mapping[str, str] | None = None,
) -> CacheUpdate:
    """Pone al día la caché por región (véase el módulo), en la transacción de escritura
    ``conn`` del camino que cambió el proyecto (no la confirma), con lo que acaba de cambiar:
    ``operations`` (las que terminó; las que no están hechas no cuentan), ``datasets`` (con
    otro contenido o estado), ``parameters`` (con otro valor o unidad) e ``inputs``
    (sustituidas, descartadas o mantenidas; con lo importado de ellas). Las filas nuevas
    llevan la fecha ``now`` (texto UTC). ``versions``, como en :func:`.graph.deduce`.

    Exige que la caché de lo de fuera de la región esté al día (la mantienen todos los
    caminos que escriben y la completa de la apertura). ``TypeError``/``ValueError`` con un
    argumento mal formado o fuera de una transacción, sin escribir nada."""
    _writing(conn, "refresh_region")
    _check_now(now)
    changed_operations = _uids(operations, "operations")
    changed_datasets = _uids(datasets, "datasets")
    changed_parameters = _uids(parameters, "parameters")
    changed_inputs = _uids(inputs, "inputs")
    region, changed = _region(conn, changed_operations, changed_datasets, changed_parameters,
                              changed_inputs)
    nodes = _operations(conn, region, full=True)
    consumed = {version.uid for node in nodes for version in node.consumed
                if version.item_kind == DATASET}
    entries = {version.uid for node in nodes for version in node.consumed
               if version.item_kind != DATASET}
    produced = {version.uid for node in nodes for version in node.produced
                if version.item_kind == DATASET}
    writers = _column(conn, _WRITERS, consumed) - region
    graph = ProvenanceGraph(
        [*nodes, *_operations(conn, writers, full=False)],
        [dataset_node(row) for row in _select(conn, _DATASETS, consumed | produced | changed)],
        [input_node(row) for row in _select(conn, _INPUTS, entries)],
        [parameter_node(row) for row in _select(
            conn, _PARAMETERS, {use.parameter_uid for node in nodes for use in node.params})],
    )
    refreshed = set(changed) | {uid for uid in produced if uid in graph.datasets
                                and graph.datasets[uid].operation_uid in region}
    outside = writers | {graph.datasets[uid].operation_uid for uid in changed
                         if uid in graph.datasets}
    known = _cached_causes(conn, outside - region)
    result = deduce_region(graph, region, known, versions=versions)
    desired: set[StaleRow] = set()
    for uid in region:
        desired.update(_rows(OPERATION, uid, result.causes.get(uid, ())))
    for uid in refreshed:
        dataset: DatasetNode | None = graph.datasets.get(uid)
        if dataset is None or not dataset.live:
            continue
        producer = dataset.operation_uid
        roots = (result.roots.get(producer, frozenset()) if producer in region
                 else root_causes(known.get(producer, ())))
        desired.update(_rows(DATASET, uid, roots))
    return _write(conn, now, {OPERATION: region, DATASET: refreshed}, desired)


def refresh_all(conn: sqlite3.Connection, *, now: str,
                versions: Mapping[str, str] | None = None) -> CacheUpdate:
    """Rehace la caché con la obsolescencia **completa** (:func:`.graph.deduce`), por
    diferencias, en la transacción de escritura ``conn`` (no la confirma): lo que sigue
    conserva su fecha y lo nuevo lleva ``now``. Corrige una caché alterada o que no sabe de
    otra versión instalada de un algoritmo."""
    _writing(conn, "refresh_all")
    _check_now(now)
    state = deduce(load_graph(conn), versions=versions)
    return _write(conn, now, {OPERATION: state.graph.operations.keys(),
                              DATASET: state.graph.datasets.keys()},
                  expected_rows(state), cached_rows(conn))


# --- Recuentos y lista ----------------------------------------------------------------------


def review_operations(conn: sqlite3.Connection) -> frozenset[str]:
    """Las operaciones que esperan revisión a mano según la caché (RF-008-27): obsoletas, sin
    sustituir, que no se repiten solas y que escribieron el contenido actual de un dato vivo
    o la cifra vigente de su clave y su ámbito (la más reciente de una operación al día o, si
    todas están obsoletas, la más reciente)."""
    candidates = {str(row[0]) for row in conn.execute(_REVIEW_CANDIDATES)}
    found = _column(conn, _LIVE_WRITERS, candidates)
    rest = candidates - found
    for key, scope_key in sorted({tuple(row) for row in _select(conn, _FIGURE_KEYS, rest)}):
        figures = [(str(op_uid), bool(stale)) for op_uid, stale in conn.execute(
            _FIGURES_OF_KEY, (key, scope_key))]
        fresh = [op_uid for op_uid, stale in figures if not stale]
        current = (fresh or [op_uid for op_uid, _stale in figures])[-1]
        if current in rest:
            found.add(current)
    return frozenset(found)


def counts(project: ReadableProject, *, conn: sqlite3.Connection | None = None) -> Counts:
    """Los recuentos de la barra de estado (:class:`Counts`), leídos de la caché y del
    registro de entradas en una instantánea (de ``conn``, si se da)."""
    with _reading(project, conn) as reading:
        stale = reading.execute(
            "SELECT COUNT(DISTINCT s.item_uid) FROM gb_stale AS s JOIN gb_dataset AS d "
            f"ON d.uid = s.item_uid WHERE s.item_kind = '{DATASET}' AND d.status IN ({_LIVE})"
        ).fetchone()[0]
        review = review_operations(reading)
        changed = reading.execute("SELECT COUNT(*) FROM gb_input WHERE status = ?",
                                  (CHANGED_INPUT,)).fetchone()[0]
    return Counts(int(stale), len(review), int(changed))


def stale_items(project: ReadableProject, *, conn: sqlite3.Connection | None = None,
                language: str = "es",
                versions: Mapping[str, str] | None = None) -> StaleReport:
    """La lista de lo obsoleto (:class:`StaleReport`) según la caché, con los textos en
    ``language`` y, para un algoritmo, la versión instalada (``versions``; por defecto, la de
    los tipos registrados)."""
    with _reading(project, conn) as reading:
        causes: dict[tuple[str, str], set[Cause]] = defaultdict(set)
        since: dict[tuple[str, str], str] = {}
        for item_kind, item_uid, cause_kind, subject_uid, at in reading.execute(
                "SELECT item_kind, item_uid, cause_kind, subject_uid, since FROM gb_stale"):
            key = (str(item_kind), str(item_uid))
            causes[key].add(Cause(CauseKind(cause_kind), str(subject_uid)))
            since[key] = min(since.get(key, str(at)), str(at))
        review = review_operations(reading)
        found = counts(project, conn=reading)
        subjects: dict[CauseKind, set[str]] = defaultdict(set)
        for found_causes in causes.values():
            for cause in found_causes:
                subjects[cause.kind].add(cause.subject)
        named = {uid for kind, uids in subjects.items() if kind.startswith("dataset_")
                 for uid in uids}
        data = {node.uid: node for node in (dataset_node(row) for row in _select(
            reading, _DATASETS, {uid for kind, uid in causes if kind == DATASET} | named))}
        shown = sorted((node for (kind, uid) in causes if kind == DATASET
                        and (node := data.get(uid)) is not None and node.live),
                       key=lambda node: (node.name, node.uid))
        writers = review | {node.operation_uid for node in shown}
        operations = {node.uid: node for node in (
            *(operation_node(row) for row in _select(reading, _OPERATIONS, writers)),
            *(operation_node(row) for row in _select(reading, _OPERATIONS_OF_GROUPS,
                                                     subjects[CauseKind.GROUP])),
            *(operation_node(row) for row in _select(reading, _OPERATIONS_OF_TYPES,
                                                     subjects[CauseKind.ALGORITHM])),
        )}
        entries = subjects[CauseKind.INPUT_UPDATED] | subjects[CauseKind.INPUT_DISCARDED]
        graph = ProvenanceGraph(
            operations.values(), data.values(),
            [input_node(row) for row in _select(reading, _INPUTS, entries)],
            [parameter_node(row) for row in _select(reading, _PARAMETERS,
                                                    subjects[CauseKind.PARAMETER_CHANGED])],
        )
    chosen = dict(installed_versions() if versions is None else versions)
    items: list[StaleItem] = []
    for node in shown:
        writer = graph.operations.get(node.operation_uid)
        found_causes = frozenset(causes[(DATASET, node.uid)])
        items.append(StaleItem(
            DATASET, node.uid, node.name, node.module, node.operation_uid,
            "" if writer is None else writer.op_type, node.operation_uid in review,
            found_causes, str(stale_text(graph, chosen, found_causes, language=language)),
            since[(DATASET, node.uid)],
        ))
    for operation in sorted((graph.operations[uid] for uid in review),
                            key=lambda node: node.fid):
        found_causes = frozenset(causes[(OPERATION, operation.uid)])
        items.append(StaleItem(
            OPERATION, operation.uid, operation.op_type, operation.module, operation.uid,
            operation.op_type, True, found_causes,
            str(stale_text(graph, chosen, found_causes, language=language)),
            since[(OPERATION, operation.uid)],
        ))
    return StaleReport(tuple(items), found)
