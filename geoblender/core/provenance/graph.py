# SPDX-License-Identifier: GPL-3.0-or-later
"""Grafo de operaciones por versiones y obsolescencia deducida (spec 008; RF-008-24,
RF-008-25; ADR-0024 §6; ADR-0025 §5; plan 008 §5.4.3, D3 y D4).

La obsolescencia **se deduce, no se apunta** (ADR-0025 §5): se calcula sobre el grafo de la
procedencia, que :func:`load_graph` carga del proyecto en una sola lectura.

- **Nodos**: las operaciones hechas (:class:`OperationNode`; las sustituidas quedan como
  historia) y las **versiones** de dato (dato, hash de contenido) y de parámetro (parámetro,
  ``value_sha256``) que consumen o producen (D4: por versiones, no por dato, para que una
  edición o una acumulación en el mismo dato no pierda la historia).
- **Aristas**: una operación consume y produce versiones de dato (``gb_operation_io``) y solo
  consume versiones de parámetro (``gb_operation_param``: ningún cálculo escribe un
  parámetro, S-1). El **productor** de una versión de dato es la operación que la escribió
  (:meth:`ProvenanceGraph.producer`): la que escribió el contenido actual del dato, si es esa
  versión; si no, la última que la escribió (un recálculo o «dar por buena» que da el mismo
  hash pasa a ser su productor).

:func:`deduce` calcula la obsolescencia **completa** (:class:`Staleness`):

- causas directas de una operación (:func:`direct_causes`): un dato consumido que falta, está
  bloqueado o dañado; lo importado de una entrada sustituida o descartada (o la entrada que
  consumió directamente); otro hash de un dato consumido que ella no escribió (una edición
  propia no cuenta; los dos hashes, con el normalizador del dato, ADR-0024 §6); otro valor o
  unidad de un parámetro (``value_sha256``: un cambio solo de tipo no cuenta, D10); una
  versión instalada de su algoritmo mayor que la registrada (un tipo que no está instalado,
  nada);
- causas raíz: las directas más las de los productores de lo que consumió, hasta un punto
  fijo; en un **grupo acoplado** (una ejecución, ``group_uid``), si una tiene causas, todas
  las reciben, con la causa ``group`` (RF-008-25), y con ellas lo que depende de cualquiera;
- un dato vivo está obsoleto si lo está la operación que escribió su contenido actual; una
  operación obsoleta que no se repite sola espera **revisión a mano** si no está sustituida y
  escribió el contenido actual de un dato vivo o una cifra vigente (RF-008-27);
- la **cifra vigente** de una clave y un ámbito es la de la operación más reciente (sin
  sustituir) que no está obsoleta; si todas lo están, la más reciente.

:func:`deduce_region` hace el mismo cálculo **por región** (plan §5.4.3): solo para las
operaciones de una región cerrada hacia abajo (lo que consume lo que producen y su ejecución de
grupo), con las causas ya conocidas (la caché) de las de fuera de las que depende; con ellas
exactas, da lo mismo que :func:`deduce` (lo prueba una propiedad en grafos aleatorios). La
región y su carga desde la base, con los índices, son de :mod:`.stale`.

Cada causa (:class:`Cause`) es lo que guarda la caché ``gb_stale`` (clase y sujeto; T27) y se
presenta con :meth:`Staleness.text` o :func:`stale_text` («Obsoleto: cambió Producción»).
Python puro (ADR-0004): solo lee el proyecto.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..i18n import translate
from ..params.model import DEFINITIONS
from .contract import OPERATIONS, parse_version
from .messages import render
from .schema import LIVE_DATASET_STATUSES

DONE = "done"
"""El estado de una operación hecha (``gb_operation.status``): las únicas del grafo."""
DATASET = "dataset"
INPUT = "input"
CAUSE_SEPARATOR = "; "
"""Entre las causas de un elemento en su texto."""


class CauseKind(StrEnum):
    """La clase de una causa de obsolescencia (``gb_stale.cause_kind``)."""

    DATASET_CHANGED = "dataset_changed"  # otro contenido de un dato que consumió
    PARAMETER_CHANGED = "parameter_changed"  # otro valor o unidad de un parámetro
    INPUT_UPDATED = "input_updated"  # entrada sustituida (o lo importado de ella)
    INPUT_DISCARDED = "input_discarded"  # entrada descartada (o lo importado de ella)
    DATASET_MISSING = "dataset_missing"  # dato que falta (RF-008-57)
    DATASET_BLOCKED = "dataset_blocked"  # dato bloqueado por una edición externa (RF-008-56)
    DATASET_DAMAGED = "dataset_damaged"  # lo importado dañado (ADR-0025 §4)
    ALGORITHM = "algorithm"  # versión instalada del algoritmo mayor que la registrada
    GROUP = "group"  # otra operación de su grupo acoplado está obsoleta (RF-008-25)


_ORDER: Mapping[CauseKind, int] = MappingProxyType({kind: n for n, kind in enumerate(CauseKind)})

DATASET_STATUS_CAUSES: Mapping[str, CauseKind] = MappingProxyType({
    "missing": CauseKind.DATASET_MISSING,
    "blocked": CauseKind.DATASET_BLOCKED,
    "damaged": CauseKind.DATASET_DAMAGED,
})
"""La causa de un dato consumido por su estado (sigue vivo)."""
INACTIVE_CAUSES: Mapping[str, CauseKind] = MappingProxyType({
    "superseded": CauseKind.INPUT_UPDATED,
    "discarded": CauseKind.INPUT_DISCARDED,
})
"""La causa de una entrada sustituida o descartada (y de lo importado de ella)."""


@dataclass(frozen=True, slots=True, order=True)
class Cause:
    """Una causa de obsolescencia: su clase y su sujeto, lo que cambió (el uid de un dato, de
    un parámetro o de una entrada, el tipo de operación de un algoritmo o la ejecución
    ``group_uid`` de un grupo acoplado)."""

    kind: CauseKind
    subject: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", CauseKind(self.kind))
        if not isinstance(self.subject, str) or not self.subject:
            raise ValueError(f"el sujeto de una causa es un texto no vacío, no "
                             f"{self.subject!r}")


@dataclass(frozen=True, slots=True)
class Version:
    """Una versión que consume o produce una operación: ``item_kind`` (``dataset`` o
    ``input``), su uid, su hash de contenido y su papel (``gb_operation_io``)."""

    item_kind: str
    uid: str
    content_sha256: str
    role: str


@dataclass(frozen=True, slots=True)
class ParamUse:
    """Una versión de parámetro que leyó una operación (``gb_operation_param``)."""

    parameter_uid: str
    key: str
    rev: int
    value_sha256: str


@dataclass(frozen=True, slots=True)
class OperationNode:
    """Una operación hecha con lo que consumió, lo que produjo y los parámetros que leyó."""

    fid: int
    uid: str
    op_type: str
    op_version: str
    module: str
    repeatable: bool
    group_name: str | None
    group_uid: str | None
    supersedes_uid: str | None
    superseded_by: str | None
    started_at: str
    finished_at: str
    consumed: tuple[Version, ...]
    produced: tuple[Version, ...]
    params: tuple[ParamUse, ...]

    @property
    def current(self) -> bool:
        """Si no está sustituida (las sustituidas quedan como historia)."""
        return self.superseded_by is None


@dataclass(frozen=True, slots=True)
class DatasetNode:
    """Un dato del proyecto en su estado actual (``gb_dataset``)."""

    fid: int
    uid: str
    name: str
    module: str
    kind: str
    status: str
    content_sha256: str
    normalizer: str
    operation_uid: str
    input_uid: str | None

    @property
    def live(self) -> bool:
        """Si está vivo: vigente, que falta, bloqueado o dañado."""
        return self.status in LIVE_DATASET_STATUSES


@dataclass(frozen=True, slots=True)
class InputNode:
    """Una entrada registrada en su estado actual (``gb_input``)."""

    uid: str
    name: str
    status: str
    operation_uid: str


@dataclass(frozen=True, slots=True)
class ParameterNode:
    """Un parámetro en su estado actual (``gb_parameter``)."""

    uid: str
    key: str
    scope: str
    value_sha256: str
    kind: str
    unconfirmed: bool


@dataclass(frozen=True, slots=True)
class FigureNode:
    """Una cifra registrada (``gb_figure``): su clave, su ámbito y su operación."""

    fid: int
    uid: str
    key: str
    scope_key: str
    operation_uid: str


class ProvenanceGraph:
    """El grafo de la procedencia (véase el módulo): operaciones hechas en orden de registro
    (:attr:`operations`) y el estado actual de los datos, las entradas, los parámetros y las
    cifras, todo de solo lectura."""

    def __init__(
        self,
        operations: Iterable[OperationNode],
        datasets: Iterable[DatasetNode] = (),
        inputs: Iterable[InputNode] = (),
        parameters: Iterable[ParameterNode] = (),
        figures: Iterable[FigureNode] = (),
    ) -> None:
        ops = {node.uid: node for node in sorted(operations, key=lambda node: node.fid)}
        self.operations: Mapping[str, OperationNode] = MappingProxyType(ops)
        self.datasets: Mapping[str, DatasetNode] = MappingProxyType(
            {node.uid: node for node in datasets})
        self.inputs: Mapping[str, InputNode] = MappingProxyType(
            {node.uid: node for node in inputs})
        self.parameters: Mapping[str, ParameterNode] = MappingProxyType(
            {node.uid: node for node in parameters})
        self.figures: tuple[FigureNode, ...] = tuple(sorted(figures, key=lambda node: node.fid))
        writers: dict[tuple[str, str], list[str]] = defaultdict(list)
        groups: dict[str, list[str]] = defaultdict(list)
        for node in sorted(ops.values(), key=lambda node: (node.finished_at, node.fid)):
            for version in node.produced:
                if version.item_kind == DATASET:
                    writers[(version.uid, version.content_sha256)].append(node.uid)
        for node in ops.values():
            if node.group_uid is not None:
                groups[node.group_uid].append(node.uid)
        self._writers = {version: tuple(found) for version, found in writers.items()}
        self._groups = {group: tuple(found) for group, found in groups.items()}

    def producer(self, dataset_uid: str, content_sha256: str, *,
                 excluding: str | None = None) -> str | None:
        """La operación que escribió la versión (``dataset_uid``, ``content_sha256``), sin
        contar ``excluding`` (la que la consume): la que escribió el contenido actual del
        dato si es esa versión; si no, la última que la escribió (por orden de terminación);
        ``None`` si no la escribió ninguna operación hecha."""
        dataset = self.datasets.get(dataset_uid)
        if (dataset is not None and dataset.content_sha256 == content_sha256
                and dataset.operation_uid != excluding and dataset.operation_uid in self.operations):
            return dataset.operation_uid
        writers = [uid for uid in self._writers.get((dataset_uid, content_sha256), ())
                   if uid != excluding]
        return writers[-1] if writers else None

    def upstream(self, op_uid: str) -> tuple[str, ...]:
        """Los productores de las versiones de dato que consumió la operación ``op_uid`` (sin
        ella misma), sin repetir y en el orden de lo consumido."""
        node = self.operations[op_uid]
        found: list[str] = []
        for version in node.consumed:
            if version.item_kind != DATASET:
                continue
            producer = self.producer(version.uid, version.content_sha256, excluding=op_uid)
            if producer is not None and producer not in found:
                found.append(producer)
        return tuple(found)

    def group(self, group_uid: str) -> tuple[str, ...]:
        """Las operaciones hechas de la ejecución ``group_uid`` de un grupo acoplado."""
        return self._groups.get(group_uid, ())


# --- Carga --------------------------------------------------------------------------------

OPERATION_COLUMNS = (
    "fid, uid, op_type, op_version, module, repeatable, group_name, group_uid, supersedes_uid, "
    "superseded_by, started_at, finished_at"
)
"""Las columnas de ``gb_operation`` de un :class:`OperationNode`, en su orden."""
IO_COLUMNS = "operation_uid, direction, item_kind, item_uid, content_sha256, role"
"""Las columnas de ``gb_operation_io`` de una :class:`Version`, con su operación y su sentido."""
PARAM_USE_COLUMNS = "operation_uid, parameter_uid, key, rev, value_sha256"
"""Las columnas de ``gb_operation_param`` de un :class:`ParamUse`, con su operación."""
DATASET_COLUMNS = (
    "fid, uid, name, module, kind, status, content_sha256, normalizer, operation_uid, input_uid"
)
"""Las columnas de ``gb_dataset`` de un :class:`DatasetNode`, en su orden."""
INPUT_NODE_COLUMNS = "uid, name, status, operation_uid"
"""Las columnas de ``gb_input`` de un :class:`InputNode`, en su orden."""
PARAMETER_COLUMNS = "uid, key, scope, value_sha256, kind, unconfirmed"
"""Las columnas de ``gb_parameter`` de un :class:`ParameterNode`, en su orden."""


def version_of(row: tuple[Any, ...]) -> tuple[str, bool, Version]:
    """De una fila de :data:`IO_COLUMNS`: su operación, si es una salida y la versión."""
    op_uid, direction, item_kind, item_uid, sha, role = row
    return str(op_uid), direction == "out", Version(str(item_kind), str(item_uid), str(sha),
                                                    str(role))


def param_use_of(row: tuple[Any, ...]) -> tuple[str, ParamUse]:
    """De una fila de :data:`PARAM_USE_COLUMNS`: su operación y la versión que leyó."""
    op_uid, parameter_uid, key, rev, value_sha256 = row
    return str(op_uid), ParamUse(str(parameter_uid), str(key), int(rev), str(value_sha256))


def operation_node(row: tuple[Any, ...], consumed: Iterable[Version] = (),
                   produced: Iterable[Version] = (),
                   params: Iterable[ParamUse] = ()) -> OperationNode:
    """Un :class:`OperationNode` de una fila de :data:`OPERATION_COLUMNS` y lo que consumió,
    produjo y leyó."""
    (fid, uid, op_type, op_version, module, repeatable, group_name, group_uid, supersedes_uid,
     superseded_by, started_at, finished_at) = row
    return OperationNode(
        int(fid), str(uid), str(op_type), str(op_version), str(module), bool(repeatable),
        group_name, group_uid, supersedes_uid, superseded_by, str(started_at), str(finished_at),
        tuple(consumed), tuple(produced), tuple(params),
    )


def dataset_node(row: tuple[Any, ...]) -> DatasetNode:
    """Un :class:`DatasetNode` de una fila de :data:`DATASET_COLUMNS`."""
    return DatasetNode(int(row[0]), *(str(value) for value in row[1:9]), row[9])


def input_node(row: tuple[Any, ...]) -> InputNode:
    """Un :class:`InputNode` de una fila de :data:`INPUT_NODE_COLUMNS`."""
    return InputNode(*(str(value) for value in row))


def parameter_node(row: tuple[Any, ...]) -> ParameterNode:
    """Un :class:`ParameterNode` de una fila de :data:`PARAMETER_COLUMNS`."""
    uid, key, scope, value_sha256, kind, unconfirmed = row
    return ParameterNode(str(uid), str(key), str(scope), str(value_sha256), str(kind),
                         bool(unconfirmed))


def load_graph(conn: sqlite3.Connection) -> ProvenanceGraph:
    """El grafo de la procedencia del proyecto de ``conn`` (de lectura o la transacción de
    escritura de quien llama: ve lo aún no confirmado), leído en una sola instantánea. No
    escribe nada."""
    began = not conn.in_transaction
    if began:
        conn.execute("BEGIN")  # todas las lecturas en la misma instantánea
    try:
        return _load(conn)
    finally:
        if began:
            conn.execute("ROLLBACK")


def _load(conn: sqlite3.Connection) -> ProvenanceGraph:
    consumed: dict[str, list[Version]] = defaultdict(list)
    produced: dict[str, list[Version]] = defaultdict(list)
    io_columns = ", ".join(f"io.{column}" for column in IO_COLUMNS.split(", "))
    for row in conn.execute(
        f"SELECT {io_columns} FROM gb_operation_io AS io JOIN gb_operation AS op "
        "ON op.uid = io.operation_uid WHERE op.status = ? ORDER BY io.fid", (DONE,)
    ):
        op_uid, out, version = version_of(row)
        (produced if out else consumed)[op_uid].append(version)
    used: dict[str, list[ParamUse]] = defaultdict(list)
    use_columns = ", ".join(f"p.{column}" for column in PARAM_USE_COLUMNS.split(", "))
    for row in conn.execute(
        f"SELECT {use_columns} FROM gb_operation_param AS p JOIN gb_operation AS op "
        "ON op.uid = p.operation_uid WHERE op.status = ? ORDER BY p.fid", (DONE,)
    ):
        op_uid, use = param_use_of(row)
        used[op_uid].append(use)
    operations = [
        operation_node(row, consumed[row[1]], produced[row[1]], used[row[1]])
        for row in conn.execute(
            f"SELECT {OPERATION_COLUMNS} FROM gb_operation WHERE status = ? ORDER BY fid",
            (DONE,),
        )
    ]
    datasets = [dataset_node(row) for row in conn.execute(
        f"SELECT {DATASET_COLUMNS} FROM gb_dataset ORDER BY fid")]
    inputs = [input_node(row) for row in conn.execute(
        f"SELECT {INPUT_NODE_COLUMNS} FROM gb_input ORDER BY fid")]
    parameters = [parameter_node(row) for row in conn.execute(
        f"SELECT {PARAMETER_COLUMNS} FROM gb_parameter ORDER BY fid")]
    figures = [
        FigureNode(int(fid), str(uid), str(key), str(scope_key), str(operation_uid))
        for fid, uid, key, scope_key, operation_uid in conn.execute(
            "SELECT fid, uid, key, scope_key, operation_uid FROM gb_figure ORDER BY fid"
        )
    ]
    return ProvenanceGraph(operations, datasets, inputs, parameters, figures)


# --- Obsolescencia ------------------------------------------------------------------------


def installed_versions() -> dict[str, str]:
    """La versión del algoritmo de cada tipo de operación registrado (el Geoblender
    instalado, con sus módulos activos)."""
    return {op_type: definition.version for op_type, definition in OPERATIONS.items()}


def _dataset_causes(graph: ProvenanceGraph, version: Version,
                    written: set[str]) -> list[Cause]:
    dataset = graph.datasets.get(version.uid)
    if dataset is None:
        return []
    found: list[Cause] = []
    kind = DATASET_STATUS_CAUSES.get(dataset.status)
    if kind is not None:
        found.append(Cause(kind, dataset.uid))
    kind = INACTIVE_CAUSES.get(dataset.status)
    if kind is not None:  # lo importado de una entrada sustituida o descartada
        found.append(Cause(kind, dataset.input_uid) if dataset.input_uid is not None
                     else Cause(CauseKind.DATASET_CHANGED, dataset.uid))
    if dataset.content_sha256 != version.content_sha256 and dataset.uid not in written:
        found.append(Cause(CauseKind.DATASET_CHANGED, dataset.uid))
    return found


def direct_causes(graph: ProvenanceGraph, node: OperationNode,
                  installed: Mapping[str, tuple[int, int]]) -> set[Cause]:
    """Las causas directas de la operación ``node`` (véase el módulo), con ``installed``,
    la versión instalada ``(M, m)`` de cada tipo de operación."""
    found: set[Cause] = set()
    written = {version.uid for version in node.produced if version.item_kind == DATASET}
    for version in node.consumed:
        if version.item_kind == DATASET:
            found.update(_dataset_causes(graph, version, written))
        elif version.item_kind == INPUT:
            entry = graph.inputs.get(version.uid)
            kind = None if entry is None else INACTIVE_CAUSES.get(entry.status)
            if kind is not None:
                found.add(Cause(kind, version.uid))
    for use in node.params:
        current = graph.parameters.get(use.parameter_uid)
        if current is not None and current.value_sha256 != use.value_sha256:
            found.add(Cause(CauseKind.PARAMETER_CHANGED, use.parameter_uid))
    target = installed.get(node.op_type)
    if target is not None:
        try:
            registered = parse_version(node.op_version)
        except ValueError:  # pragma: no cover - el esquema la guarda de su OperationDef
            registered = None
        if registered is not None and target > registered:
            found.add(Cause(CauseKind.ALGORITHM, node.op_type))
    return found


def root_causes(causes: Iterable[Cause]) -> frozenset[Cause]:
    """Las causas raíz de las causas de una operación (las de la caché): sin la de su grupo,
    que solo va en las operaciones del grupo y no se propaga ni pasa a sus datos."""
    return frozenset(cause for cause in causes if cause.kind is not CauseKind.GROUP)


def _installed(versions: Mapping[str, str] | None) -> tuple[dict[str, str],
                                                             dict[str, tuple[int, int]]]:
    chosen = dict(installed_versions() if versions is None else versions)
    return chosen, {op_type: parse_version(version) for op_type, version in chosen.items()}


def _roots(graph: ProvenanceGraph, members: Iterable[str],
           known: Mapping[str, Iterable[Cause]],
           installed: Mapping[str, tuple[int, int]]) -> dict[str, set[Cause]]:
    """Las causas raíz de las operaciones ``members``: las directas, las ya conocidas
    (``known``) de las de fuera de las que dependen y lo que se propaga entre ellas."""
    roots = {uid: direct_causes(graph, graph.operations[uid], installed) for uid in members}
    upstream = {uid: graph.upstream(uid) for uid in roots}
    for uid, producers in upstream.items():
        for producer in producers:
            if producer not in roots:
                roots[uid] |= root_causes(known.get(producer, ()))
    _propagate(graph, roots, upstream)
    return roots


def _propagate(graph: ProvenanceGraph, roots: dict[str, set[Cause]],
               upstream: Mapping[str, tuple[str, ...]]) -> None:
    """Lleva las causas raíz de cada operación de ``roots`` a lo que depende de ella y a las
    de su ejecución de grupo (todas en ``roots``), hasta un punto fijo (los conjuntos solo
    crecen)."""
    downstream: dict[str, list[str]] = defaultdict(list)
    for uid, producers in upstream.items():
        for producer in producers:
            if producer in roots:
                downstream[producer].append(uid)
    pending = deque(uid for uid, found in roots.items() if found)
    queued = set(pending)
    while pending:
        uid = pending.popleft()
        queued.discard(uid)
        found = roots[uid]
        group_uid = graph.operations[uid].group_uid
        siblings = graph.group(group_uid) if group_uid is not None else ()
        for target in (*downstream.get(uid, ()), *siblings):
            mine = roots[target]
            if target == uid or found <= mine:
                continue
            mine |= found
            if target not in queued:
                queued.add(target)
                pending.append(target)


def _current_figures(graph: ProvenanceGraph,
                     causes: Mapping[str, frozenset[Cause]]) -> dict[tuple[str, str], str]:
    by_key: dict[tuple[str, str], list[FigureNode]] = defaultdict(list)
    for figure in graph.figures:
        node = graph.operations.get(figure.operation_uid)
        if node is not None and node.current:
            by_key[(figure.key, figure.scope_key)].append(figure)
    current: dict[tuple[str, str], str] = {}
    for key, found in by_key.items():
        fresh = [figure for figure in found if figure.operation_uid not in causes]
        current[key] = (fresh or found)[-1].uid
    return current


def _with_group(graph: ProvenanceGraph,
                roots: Mapping[str, set[Cause]]) -> dict[str, frozenset[Cause]]:
    """Las causas de cada operación obsoleta: las raíz y, en una ejecución de un grupo
    acoplado con más de una, la del grupo."""
    causes: dict[str, frozenset[Cause]] = {}
    for uid, found in roots.items():
        if not found:
            continue
        group_uid = graph.operations[uid].group_uid
        if group_uid is not None and len(graph.group(group_uid)) > 1:
            found = found | {Cause(CauseKind.GROUP, group_uid)}
        causes[uid] = frozenset(found)
    return causes


def deduce(graph: ProvenanceGraph, *, versions: Mapping[str, str] | None = None) -> Staleness:
    """La obsolescencia completa de ``graph`` (véase el módulo). ``versions``: la versión
    instalada de cada tipo de operación (por defecto, la de los registrados,
    :func:`installed_versions`); un tipo que no está, no cambia de algoritmo.
    :class:`ValueError` si una versión no es «M.m»."""
    chosen, installed = _installed(versions)
    roots = _roots(graph, graph.operations, {}, installed)
    causes = _with_group(graph, roots)
    data = {
        dataset.uid: frozenset(roots[dataset.operation_uid])
        for dataset in graph.datasets.values()
        if dataset.live and roots.get(dataset.operation_uid)
    }
    current_figures = _current_figures(graph, causes)
    figure_operations = {figure.uid: figure.operation_uid for figure in graph.figures}
    writers = {dataset.operation_uid for dataset in graph.datasets.values() if dataset.live}
    writers |= {figure_operations[uid] for uid in current_figures.values()}
    operations = {uid: found for uid, found in causes.items()
                  if graph.operations[uid].current}
    review = frozenset(uid for uid in operations
                       if not graph.operations[uid].repeatable and uid in writers)
    return Staleness(
        graph=graph,
        versions=MappingProxyType(chosen),
        causes=MappingProxyType(causes),
        operations=MappingProxyType(operations),
        datasets=MappingProxyType(data),
        review=review,
        current_figures=MappingProxyType(current_figures),
    )


def stale_state(conn: sqlite3.Connection, *,
                versions: Mapping[str, str] | None = None) -> Staleness:
    """:func:`deduce` sobre :func:`load_graph` de ``conn``."""
    return deduce(load_graph(conn), versions=versions)


@dataclass(frozen=True, slots=True)
class Staleness:
    """La obsolescencia deducida de un grafo:

    - ``causes``: las causas de cada operación hecha obsoleta, también las sustituidas (la
      historia); ``operations``: solo las que no están sustituidas;
    - ``datasets``: las causas de cada dato vivo obsoleto (las raíz de la operación que
      escribió su contenido actual);
    - ``review``: las operaciones que esperan revisión a mano (RF-008-27);
    - ``current_figures``: la cifra vigente (uid) de cada clave y ámbito (``scope_key``);
    - ``versions``: las versiones instaladas de los algoritmos con que se dedujo.
    """

    graph: ProvenanceGraph
    versions: Mapping[str, str]
    causes: Mapping[str, frozenset[Cause]]
    operations: Mapping[str, frozenset[Cause]]
    datasets: Mapping[str, frozenset[Cause]]
    review: frozenset[str]
    current_figures: Mapping[tuple[str, str], str]

    def of(self, uid: str) -> frozenset[Cause]:
        """Las causas de la operación o del dato ``uid`` (vacío si no está obsoleto)."""
        return self.causes.get(uid) or self.datasets.get(uid) or frozenset()

    def describe(self, cause: Cause, *, language: str = "es") -> str:
        """Una causa como la lee una persona, en ``language`` («cambió Producción»)."""
        return describe_cause(self.graph, self.versions, cause, language=language)

    def text(self, uid: str, *, language: str = "es") -> str | None:
        """«Obsoleto: …» con las causas de la operación o del dato ``uid``, por clase y por
        nombre; ``None`` si no está obsoleto."""
        return stale_text(self.graph, self.versions, self.of(uid), language=language)


def describe_cause(graph: ProvenanceGraph, versions: Mapping[str, str], cause: Cause, *,
                   language: str = "es") -> str:
    """Una causa como la lee una persona, en ``language`` («cambió Producción»), con los
    nombres de ``graph`` (el del dato, la entrada, el parámetro o el grupo; su uid si no
    está) y, para un algoritmo, la versión instalada de ``versions`` y las anteriores
    registradas en ``graph``."""
    kind, subject = cause.kind, cause.subject
    values: dict[str, object] = {"name": subject}
    if kind is CauseKind.PARAMETER_CHANGED:
        values["name"] = _parameter_name(graph, subject, language)
    elif kind in (CauseKind.INPUT_UPDATED, CauseKind.INPUT_DISCARDED):
        entry = graph.inputs.get(subject)
        values["name"] = subject if entry is None else entry.name
    elif kind is CauseKind.ALGORITHM:
        installed = versions.get(subject)
        older = [] if installed is None else sorted(
            {node.op_version for node in graph.operations.values()
             if node.op_type == subject
             and parse_version(node.op_version) < parse_version(installed)},
            key=parse_version,
        )
        values = {"op_type": subject, "registered": ", ".join(older) or None,
                  "installed": installed}
    elif kind is CauseKind.GROUP:
        names = sorted({str(graph.operations[uid].group_name) for uid in graph.group(subject)})
        values = {"group": ", ".join(names) or subject}
    else:
        dataset = graph.datasets.get(subject)
        values["name"] = subject if dataset is None else dataset.name
    return render(f"core.cause_{kind}", language=language, **values)


def stale_text(graph: ProvenanceGraph, versions: Mapping[str, str], causes: Iterable[Cause],
               *, language: str = "es") -> str | None:
    """«Obsoleto: …» con ``causes`` (:func:`describe_cause`), por clase y por nombre;
    ``None`` sin causas."""
    shown = sorted((_ORDER[cause.kind], describe_cause(graph, versions, cause,
                                                       language=language))
                   for cause in causes)
    if not shown:
        return None
    return render("core.stale", language=language,
                  causes=CAUSE_SEPARATOR.join(text for _order, text in shown))


def _parameter_name(graph: ProvenanceGraph, uid: str, language: str) -> str:
    """El nombre visible de un parámetro (su etiqueta, o su clave si no la tiene)."""
    node = graph.parameters.get(uid)
    key = uid if node is None else node.key
    definition = DEFINITIONS.get(key)
    msgid = None if definition is None else definition.label_msgid
    return key if msgid is None else translate(language, msgid)


# --- Por región (plan §5.4.3) ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegionStaleness:
    """La obsolescencia de las operaciones de una región (:func:`deduce_region`): ``roots``,
    las causas raíz de cada una (vacías si está al día; son las de los datos que escribió) y
    ``causes``, las de cada obsoleta, con la de su grupo."""

    region: frozenset[str]
    roots: Mapping[str, frozenset[Cause]]
    causes: Mapping[str, frozenset[Cause]]


def deduce_region(graph: ProvenanceGraph, region: Iterable[str],
                  known: Mapping[str, Iterable[Cause]], *,
                  versions: Mapping[str, str] | None = None) -> RegionStaleness:
    """La obsolescencia de las operaciones de ``region`` (plan §5.4.3), igual que la de
    :func:`deduce` si:

    - ``region`` está cerrada hacia abajo: tiene lo que consume lo que producen sus
      operaciones y toda la ejecución de grupo de cada una (lo segundo se comprueba:
      :class:`ValueError`);
    - ``known`` tiene las causas exactas (las de la caché, con o sin la del grupo) de las
      operaciones de fuera de las que depende alguna de dentro;
    - ``graph`` tiene esas operaciones con lo que consumen, producen y leen, los datos,
      entradas y parámetros que nombran y quién escribió cada versión que consumen (puede ser
      una parte del proyecto).

    ``versions``, como en :func:`deduce`."""
    members = frozenset(region)
    missing = sorted(members - graph.operations.keys())
    if missing:
        raise ValueError(f"la región tiene operaciones que no están en el grafo: {missing}")
    for uid in members:
        group_uid = graph.operations[uid].group_uid
        outside = [] if group_uid is None else sorted(set(graph.group(group_uid)) - members)
        if outside:
            raise ValueError(f"la región tiene la operación {uid} de la ejecución de grupo "
                             f"{group_uid} sin las demás: {outside}")
    _chosen, installed = _installed(versions)
    roots = _roots(graph, members, known, installed)
    return RegionStaleness(
        region=members,
        roots=MappingProxyType({uid: frozenset(found) for uid, found in roots.items()}),
        causes=MappingProxyType(_with_group(graph, roots)),
    )
