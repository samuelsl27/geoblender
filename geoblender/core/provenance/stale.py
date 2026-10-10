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

Hacia arriba, para la procedencia (RNF-008-03): :func:`upstream_region` da en una consulta
recursiva la región **aguas arriba** de unas operaciones (las que escribieron lo que consumen,
hasta cerrarla); la procedencia (:mod:`.lineage`) carga solo esa parte del grafo.

Para la interfaz (sin recalcular nada): :func:`counts` («! n obsoletos» = datos vivos
obsoletos más operaciones que esperan revisión a mano; «⚠ n entradas» = las cambiadas sin
decidir), :func:`stale_items` (lo obsoleto y lo que espera revisión a mano, con su causa, su
módulo, la operación que lo escribió y desde cuándo) e :func:`item_causes` e
:func:`item_text` (las causas y el texto de una operación o un dato, los que da la
incorporación de un trabajo). Los textos dicen «… mientras se calculaba» de lo que cambió
mientras se calculaba la operación o la que escribió el dato (RF-008-20;
:func:`.graph.changes_while_running`). Python puro (ADR-0004).
"""

from __future__ import annotations

import json
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
    changes_while_running,
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
_STALE_COUNT = (
    "SELECT COUNT(DISTINCT s.item_uid) FROM gb_stale AS s JOIN gb_dataset AS d "
    f"ON d.uid = s.item_uid WHERE s.item_kind = '{DATASET}' AND d.status IN ({_LIVE})"
)
_CHANGED_INPUTS = "SELECT COUNT(*) FROM gb_input WHERE status = ?"
# Las causas de cada elemento de la caché en una lista JSON de [clase, sujeto] (se memorizan
# por conjunto: muchos elementos tienen las mismas) y desde cuándo (la más antigua).
_GROUPED = (
    "SELECT item_uid, json_group_array(json_array(cause_kind, subject_uid)) AS causes, "
    "min(since) AS since FROM gb_stale WHERE item_kind = '{kind}'{only} GROUP BY item_uid"
)
# La lista: cada dato vivo con causas, por nombre, con el tipo de la operación hecha que
# escribió su contenido actual (vacío si no lo es). El CROSS JOIN fija el orden (de las causas
# agrupadas al dato, por su uid): sin él, el planificador puede recorrer los datos por nombre y
# las causas agrupadas por cada uno.
_STALE_DATASETS = (
    "SELECT d.uid, d.name, d.module, d.operation_uid, op.op_type, s.causes, s.since "
    f"FROM ({_GROUPED.format(kind=DATASET, only='')}) AS s "
    "CROSS JOIN gb_dataset AS d ON d.uid = s.item_uid "
    f"LEFT JOIN gb_operation AS op ON op.uid = d.operation_uid AND {_DONE} "
    f"WHERE d.status IN ({_LIVE}) ORDER BY d.name, d.uid"
)
# … y las operaciones que esperan revisión a mano, con sus causas.
_STALE_OPERATIONS = (
    "SELECT op.fid, op.uid, op.op_type, op.module, s.causes, s.since "
    f"FROM ({_GROUPED.format(kind=OPERATION, only=' AND item_uid IN ({marks})')}) AS s "
    "CROSS JOIN gb_operation AS op ON op.uid = s.item_uid"
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


# --- Aguas arriba (la procedencia) ----------------------------------------------------------

# La región aguas arriba de las operaciones de la lista JSON: ellas y, hasta cerrarla, las que
# escribieron alguna versión de un dato que consume una de la región. Basta con eso para tener
# quién escribió el contenido actual de cada dato (gb_dataset.operation_uid), porque se
# registran juntos (register_dataset y set_content anotan su salida en gb_operation_io). Sin
# mirar el estado: lo que no está hecho no tiene salidas registradas (complete las escribe en
# la transacción que la da por hecha) y, si lo tuviera, solo sobraría. Los CROSS JOIN fijan el
# orden de cada paso (de la operación a lo que consume y de ahí a quién lo escribió, por los
# índices): sin ellos, el planificador recorre gb_operation_io por cada operación de la región
# (3 s con 100).
_UPSTREAM = (
    "WITH RECURSIVE up(uid) AS (SELECT value FROM json_each(?) "
    "UNION SELECT w.operation_uid FROM up "
    "CROSS JOIN gb_operation_io AS c ON c.operation_uid = up.uid AND c.direction = 'in' "
    "AND c.item_kind = 'dataset' "
    "CROSS JOIN gb_operation_io AS w ON w.item_kind = 'dataset' AND w.item_uid = c.item_uid "
    "AND w.direction = 'out') "
    "SELECT uid FROM up"
)


def upstream_region(conn: sqlite3.Connection, roots: Iterable[str]) -> frozenset[str]:
    """La región **aguas arriba** de las operaciones ``roots`` (también las que no están
    hechas): ellas y, hasta cerrarla, las operaciones que escribieron alguna versión de un dato
    que consume una de la región. Tiene la cadena de la procedencia de cada
    una (quién escribió cada versión que consumió, :meth:`.graph.ProvenanceGraph.producer`,
    también el contenido actual de un dato) y, además, quién escribió las otras versiones de
    esos datos (la historia) y lo de aguas arriba de ellas. Una consulta recursiva; solo lee."""
    wanted = _uids(roots, "roots")
    if not wanted:
        return frozenset()
    return frozenset(str(row[0]) for row in conn.execute(_UPSTREAM,
                                                          (json.dumps(sorted(wanted)),)))


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


def _changed_inputs(conn: sqlite3.Connection) -> int:
    return int(conn.execute(_CHANGED_INPUTS, (CHANGED_INPUT,)).fetchone()[0])


def counts(project: ReadableProject, *, conn: sqlite3.Connection | None = None) -> Counts:
    """Los recuentos de la barra de estado (:class:`Counts`), leídos de la caché y del
    registro de entradas en una instantánea (de ``conn``, si se da)."""
    with _reading(project, conn) as reading:
        stale = reading.execute(_STALE_COUNT).fetchone()[0]
        review = review_operations(reading)
        changed = _changed_inputs(reading)
    return Counts(int(stale), len(review), changed)


_NOTHING: frozenset[Cause] = frozenset()


class _Causes:
    """Las causas de los elementos de la lista, una vez por conjunto: las listas JSON de la
    caché que ya se leyeron (muchos elementos tienen las mismas) y los textos ya compuestos
    por conjunto de causas y lo que de ellas cambió mientras se calculaba la operación."""

    def __init__(self) -> None:
        self.parsed: dict[str, frozenset[Cause]] = {}
        self.texts: dict[tuple[frozenset[Cause], frozenset[Cause]], str] = {}

    def of(self, listed: str) -> frozenset[Cause]:
        found = self.parsed.get(listed)
        if found is None:
            found = self.parsed[listed] = frozenset(
                Cause(CauseKind(kind), str(subject)) for kind, subject in json.loads(listed))
        return found

    def text(self, graph: ProvenanceGraph, versions: Mapping[str, str],
             causes: frozenset[Cause], operation: str, language: str) -> str:
        """El texto de :func:`.graph.stale_text` de ``causes`` de la operación ``operation``
        (o del dato que escribió), compuesto una vez por clave: solo cambia con lo que de
        ellas cambió mientras se calculaba."""
        during = graph.during.get(operation)
        key = (causes, causes & during if during else _NOTHING)
        found = self.texts.get(key)
        if found is None:
            found = self.texts[key] = str(stale_text(graph, versions, causes, language=language,
                                                     operation=operation))
        return found


def stale_items(project: ReadableProject, *, conn: sqlite3.Connection | None = None,
                language: str = "es",
                versions: Mapping[str, str] | None = None) -> StaleReport:
    """La lista de lo obsoleto (:class:`StaleReport`) según la caché, con los textos en
    ``language`` y, para un algoritmo, la versión instalada (``versions``; por defecto, la de
    los tipos registrados).

    No rehace lo que ya tiene (RNF-008-02): lee los datos que se muestran con sus causas, ya
    agrupadas y por nombre, en una consulta; cada conjunto de causas se lee y su texto se
    compone una sola vez; y para los textos solo crea los nodos que nombran las causas de lo
    que se muestra (los datos, las entradas y los parámetros que cambiaron y las operaciones
    de sus grupos y sus algoritmos), con lo que de esas causas cambió mientras se calculaba
    cada operación."""
    sets = _Causes()
    with _reading(project, conn) as reading:
        review = review_operations(reading)
        data = [(str(uid), str(name), str(module), str(op_uid),
                 "" if op_type is None else str(op_type), sets.of(listed), str(since))
                for uid, name, module, op_uid, op_type, listed, since
                in reading.execute(_STALE_DATASETS)]
        operations = sorted(
            ((int(fid), str(uid), str(op_type), str(module), sets.of(listed), str(since))
             for fid, uid, op_type, module, listed, since
             in _select(reading, _STALE_OPERATIONS, review)),
            key=lambda row: row[0])  # por orden de registro
        found = Counts(len(data), len(review), _changed_inputs(reading))
        shown = sets.parsed.values()
        writers = {row[3] for row in data} | review
        graph = _text_graph(reading, _subjects(shown), changes_while_running(
            reading, writers, causes={cause for causes in shown for cause in causes}))
    chosen = dict(installed_versions() if versions is None else versions)
    items = [
        StaleItem(DATASET, uid, name, module, op_uid, op_type, op_uid in review, causes,
                  sets.text(graph, chosen, causes, op_uid, language), since)
        for uid, name, module, op_uid, op_type, causes, since in data
    ]
    items.extend(
        StaleItem(OPERATION, uid, op_type, module, uid, op_type, True, causes,
                  sets.text(graph, chosen, causes, uid, language), since)
        for _fid, uid, op_type, module, causes, since in operations
    )
    return StaleReport(tuple(items), found)


def item_causes(conn: sqlite3.Connection, item_kind: str, uid: str) -> frozenset[Cause]:
    """Las causas de la operación o del dato ``uid`` (``item_kind``: ``operation`` o
    ``dataset``) en la caché de ``conn`` (vacío si está al día)."""
    if item_kind not in ITEM_KINDS:
        raise ValueError(f"la caché guarda {', '.join(ITEM_KINDS)}, no {item_kind!r}")
    return frozenset(StaleRow(*(str(value) for value in row)).cause for row in conn.execute(
        "SELECT item_kind, item_uid, cause_kind, subject_uid FROM gb_stale "
        "WHERE item_kind = ? AND item_uid = ?", (item_kind, uid)))


def item_text(conn: sqlite3.Connection, item_kind: str, uid: str, *, language: str = "es",
              versions: Mapping[str, str] | None = None) -> str | None:
    """«Obsoleto: …» de la operación o del dato ``uid`` según la caché de ``conn`` (también
    la transacción de escritura de quien llama, que ve lo aún no confirmado), como en la
    lista de lo obsoleto (:func:`stale_items`): con «… mientras se calculaba» lo que cambió
    mientras se calculaba la operación (o la que escribió el dato); ``None`` si está al día."""
    with _snapshot(conn):
        causes = item_causes(conn, item_kind, uid)
        if not causes:
            return None
        writer: str | None = uid
        if item_kind == DATASET:
            found = conn.execute("SELECT operation_uid FROM gb_dataset WHERE uid = ?",
                                 (uid,)).fetchone()
            writer = None if found is None else str(found[0])
        graph = _text_graph(conn, _subjects([causes]), changes_while_running(
            conn, () if writer is None else (writer,)))
    chosen = dict(installed_versions() if versions is None else versions)
    return stale_text(graph, chosen, causes, language=language, operation=writer)


def review_item(conn: sqlite3.Connection, operation_uid: str, *, language: str = "es",
                versions: Mapping[str, str] | None = None) -> StaleItem | None:
    """La operación ``operation_uid`` como fila de lo que espera revisión a mano (como en
    :func:`stale_items`: su tipo, su módulo, sus causas, su «Obsoleto: …» y desde cuándo) si la
    espera según la caché de ``conn``; ``None`` si no (lo que muestra «Dar por buena…», T54;
    RF-008-27)."""
    with _snapshot(conn):
        if operation_uid not in review_operations(conn):
            return None
        rows = list(_select(conn, _STALE_OPERATIONS, {operation_uid}))
        text = item_text(conn, OPERATION, operation_uid, language=language, versions=versions)
    if not rows:  # pragma: no cover - en revisión, tiene causas en la caché
        return None
    _fid, uid, op_type, module, listed, since = rows[0]
    causes = _Causes().of(listed)
    return StaleItem(OPERATION, str(uid), str(op_type), str(module), str(uid), str(op_type),
                     True, causes, text or "", str(since))


def _subjects(causes: Iterable[Iterable[Cause]]) -> dict[CauseKind, set[str]]:
    """Los sujetos de ``causes``, por clase de causa."""
    subjects: dict[CauseKind, set[str]] = defaultdict(set)
    for found in causes:
        for cause in found:
            subjects[cause.kind].add(cause.subject)
    return subjects


def _named(subjects: Mapping[CauseKind, Collection[str]]) -> set[str]:
    """Los datos que nombran las causas de ``subjects`` (cambiado, que falta, bloqueado o
    dañado)."""
    return {uid for kind, uids in subjects.items() if kind.startswith("dataset_")
            for uid in uids}


def _dataset_nodes(conn: sqlite3.Connection, uids: Collection[str]) -> dict[str, DatasetNode]:
    return {node.uid: node for node in (dataset_node(row) for row in _select(
        conn, _DATASETS, uids))}


def _text_graph(conn: sqlite3.Connection, subjects: Mapping[CauseKind, set[str]],
                during: Mapping[str, Iterable[Cause]]) -> ProvenanceGraph:
    """El grafo con solo lo que nombran los textos de las causas de ``subjects`` (los datos,
    las entradas y los parámetros que cambiaron y las operaciones de sus grupos y de sus
    tipos de algoritmo: :func:`.graph.describe_cause`) y lo que cambió mientras se calculaba
    cada operación (``during``)."""
    operations = {node.uid: node for node in (
        *(operation_node(row) for row in _select(conn, _OPERATIONS_OF_GROUPS,
                                                 subjects.get(CauseKind.GROUP, set()))),
        *(operation_node(row) for row in _select(conn, _OPERATIONS_OF_TYPES,
                                                 subjects.get(CauseKind.ALGORITHM, set()))),
    )}
    entries = (subjects.get(CauseKind.INPUT_UPDATED, set())
               | subjects.get(CauseKind.INPUT_DISCARDED, set()))
    return ProvenanceGraph(
        operations.values(), _dataset_nodes(conn, _named(subjects)).values(),
        [input_node(row) for row in _select(conn, _INPUTS, entries)],
        [parameter_node(row) for row in _select(
            conn, _PARAMETERS, subjects.get(CauseKind.PARAMETER_CHANGED, set()))],
        during=during,
    )
