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
  escribió el contenido actual de un dato vivo o una cifra vigente (RF-008-27); una que se
  repite sola **solo deja cifras** si no está sustituida, no escribió el contenido actual de
  ningún dato vivo y sí una cifra vigente (RF-008-28, spec 0.3: cuenta en «! n obsoletos»);
- la **cifra vigente** de una clave y un ámbito es la de la operación más reciente (sin
  sustituir) que no está obsoleta; si todas lo están, la más reciente.

:func:`deduce_region` hace el mismo cálculo **por región** (plan §5.4.3): solo para las
operaciones de una región cerrada hacia abajo (lo que consume lo que producen y su ejecución de
grupo), con las causas ya conocidas (la caché) de las de fuera de las que depende; con ellas
exactas, da lo mismo que :func:`deduce` (lo prueba una propiedad en grafos aleatorios). La
región y su carga desde la base, con los índices, son de :mod:`.stale`.

**Por pasos** (la comprobación de apertura, T65; RNF-008-12): :class:`CauseScan` mira en la
base, por páginas y sin cargar el grafo, si alguna operación hecha tiene una causa directa (sin
ninguna, nada está obsoleto); :class:`GraphPages` lee el grafo por páginas de ``fid`` de cada
tabla, en una o varias lecturas, y :func:`deduce_steps` deduce por trozos. Paran cuando lo pide
``lap`` (el ritmo de quien los lleva, :data:`Lap`); :func:`load_graph` y :func:`deduce` son los
dos últimos sin parar.

**Con versiones** (spec 009, plan A4; RF-009-19, D-23, D-27; solo en una base que las tiene,
:func:`versioned`): el grafo lleva la revisión de cada operación de versión, la versión de cada
dato de versión y las revisiones con el estado de su versión (:class:`RevisionNode`).

1. Las operaciones de una versión SUPERADO o DESCARTADO (:meth:`ProvenanceGraph.closed`) **no
   entran en la cascada**: no tienen causas, no reciben ni propagan ninguna y no se cuentan.
2. Las de una versión BORRADOR o VIGENTE se evalúan como siempre, también las registradas en una
   revisión ya congelada (lo «en curso» de su revisión abierta, D-23): lo congelado es el
   registro de la revisión (sus elementos, con el estado que tenían al congelarse), que no cambia.
3. Un dato de otra versión que consumió una operación de versión es lo **congelado** de la
   revisión de la que parte su versión (``Use.frozen``, D-27; :meth:`ProvenanceGraph.frozen_use`):
   ni su contenido de hoy ni lo de aguas arriba cuentan (no es aguas arriba suyo en la cascada,
   :meth:`ProvenanceGraph.upstream`); solo si esa revisión está **alterada**, la causa
   ``dataset_damaged`` sobre ese dato («lo congelado de «…» está alterado»).
4. Una operación de versión que leyó un parámetro de otra fila (la del proyecto) cuando su
   versión tiene ya la suya queda obsoleta: ``parameter_changed`` sobre la fila de la versión.
5. La cifra vigente de una clave y un ámbito se elige entre las del proyecto
   (:attr:`Staleness.current_figures`) o entre las de cada versión
   (:attr:`Staleness.current_version_figures`).

Cada causa (:class:`Cause`) es lo que guarda la caché ``gb_stale`` (clase y sujeto; T27) y se
presenta con :meth:`Staleness.text` o :func:`stale_text` («Obsoleto: cambió Producción»). Una
causa directa de una operación que cambió **mientras se calculaba** (entre su principio y su
final, el de un trabajo de la 004 al incorporarlo) se presenta así, «cambió Producción
mientras se calculaba» (RF-008-20; plan §5.4.3): lo dice :func:`changes_while_running`, que
el grafo lleva en :attr:`ProvenanceGraph.during` si se carga para presentarlo
(``load_graph(conn, during=True)``, :func:`stale_state`). Python puro (ADR-0004): solo lee el
proyecto.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from collections.abc import Callable, Generator, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypeVar

from ..params.model import parameter_label
from ..versions.model import EDITABLE, revision_label
from .contract import OPERATIONS, parse_version
from .messages import render
from .schema import LIVE_DATASET_STATUSES

DONE = "done"
"""El estado de una operación hecha (``gb_operation.status``): las únicas del grafo."""
DATASET = "dataset"
INPUT = "input"
CAUSE_SEPARATOR = "; "
"""Entre las causas de un elemento en su texto."""
PAGE_ROWS = 500
"""Las filas de cada página al leer el grafo por pasos (:class:`GraphPages`)."""
_RELEASED = 64  # nodos que se sueltan entre dos llamadas a ``lap`` (GraphPages.release)

Lap = Callable[[], bool]
"""El ritmo de quien lleva un cálculo por pasos: se llama tras cada unidad de trabajo y dice si
el paso tiene que acabar ya (la comprobación de apertura: ≤ 20 ms por paso, RNF-008-12)."""

_T = TypeVar("_T")


def drain(steps: Generator[Any, None, _T]) -> _T:
    """Lleva ``steps`` hasta el final de una vez y devuelve su resultado."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


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
    """Una operación hecha con lo que consumió, lo que produjo y los parámetros que leyó;
    ``revision_uid``, la revisión en que se registró una operación de versión (spec 009;
    ``''`` de proyecto, o si no se cargó)."""

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
    revision_uid: str = ""

    @property
    def current(self) -> bool:
        """Si no está sustituida (las sustituidas quedan como historia)."""
        return self.superseded_by is None


@dataclass(frozen=True, slots=True)
class DatasetNode:
    """Un dato del proyecto en su estado actual (``gb_dataset``); ``version_uid``, la versión
    de un dato de versión (spec 009; ``''`` del proyecto, o si no se cargó)."""

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
    version_uid: str = ""

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
    """Un parámetro en su estado actual (``gb_parameter``): una fila de su ámbito (``scope``
    y ``scope_uid``: ``''`` en el proyecto, el uid de la versión en una de versión)."""

    uid: str
    key: str
    scope: str
    value_sha256: str
    kind: str
    unconfirmed: bool
    scope_uid: str = ""


VERSION_SCOPE = "version"
"""El ámbito de un parámetro propio de una versión (``gb_parameter.scope``, spec 009)."""


@dataclass(frozen=True, slots=True)
class RevisionNode:
    """Una revisión de una versión (spec 009; ``gb_revision`` y su ``gb_version``): su versión
    y su etiqueta («V10.r2»), su estado (``open``, ``frozen`` o ``closed``), si está alterada
    (RF-009-09), el estado de su versión y la revisión congelada de la que parte su versión
    (``''`` si no parte de ninguna)."""

    uid: str
    version_uid: str
    label: str
    state: str
    altered: bool
    version_status: str
    parent_revision_uid: str

    @property
    def closed(self) -> bool:
        """Si su versión es SUPERADO o DESCARTADO: lo suyo no entra en la cascada (A4 (1))."""
        return self.version_status not in EDITABLE


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
    cifras, todo de solo lectura. :attr:`during`: de cada operación, lo que consumió y cambió
    mientras se calculaba (:func:`changes_while_running`; vacío si no se cargó), que solo
    cambia cómo se presentan sus causas. :attr:`revisions`: las revisiones de las versiones
    (spec 009; vacío sin versiones o si no se cargaron)."""

    def __init__(
        self,
        operations: Iterable[OperationNode],
        datasets: Iterable[DatasetNode] = (),
        inputs: Iterable[InputNode] = (),
        parameters: Iterable[ParameterNode] = (),
        figures: Iterable[FigureNode] = (),
        *,
        during: Mapping[str, Iterable[Cause]] | None = None,
        revisions: Iterable[RevisionNode] = (),
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
        self.during: Mapping[str, frozenset[Cause]] = MappingProxyType(
            {uid: frozenset(causes) for uid, causes in (during or {}).items()})
        self.revisions: Mapping[str, RevisionNode] = MappingProxyType(
            {node.uid: node for node in revisions})
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
        self._own_rows = _own_rows(self.parameters.values())

    @classmethod
    def _assembled(cls, operations: dict[str, OperationNode], datasets: dict[str, DatasetNode],
                   inputs: dict[str, InputNode], parameters: dict[str, ParameterNode],
                   figures: tuple[FigureNode, ...], during: Mapping[str, Iterable[Cause]] | None,
                   writers: dict[tuple[str, str], tuple[str, ...]],
                   groups: dict[str, tuple[str, ...]],
                   revisions: dict[str, RevisionNode] | None = None) -> ProvenanceGraph:
        """El grafo con lo que ya armó :class:`GraphPages` (las operaciones en orden de ``fid``,
        las cifras también, y quién escribió cada versión y los miembros de cada grupo en el
        orden de :meth:`__init__`), sin volver a recorrerlo."""
        graph = cls.__new__(cls)
        graph.operations = MappingProxyType(operations)
        graph.datasets = MappingProxyType(datasets)
        graph.inputs = MappingProxyType(inputs)
        graph.parameters = MappingProxyType(parameters)
        graph.figures = figures
        graph.during = MappingProxyType(
            {uid: frozenset(causes) for uid, causes in (during or {}).items()})
        graph.revisions = MappingProxyType(revisions or {})
        graph._writers = writers
        graph._groups = groups
        graph._own_rows = _own_rows(parameters.values())
        return graph

    # --- Versiones (spec 009, A4) ------------------------------------------------------------

    def revision(self, op_uid: str) -> RevisionNode | None:
        """La revisión en que se registró la operación ``op_uid``; ``None`` si es de proyecto
        (o no se cargó)."""
        node = self.operations.get(op_uid)
        if node is None or not node.revision_uid:
            return None
        return self.revisions.get(node.revision_uid)

    def version_of(self, op_uid: str) -> str:
        """La versión (uid) de la operación ``op_uid``; ``''`` si es de proyecto."""
        found = self.revision(op_uid)
        return "" if found is None else found.version_uid

    def closed(self, op_uid: str) -> bool:
        """Si la operación ``op_uid`` es de una versión SUPERADO o DESCARTADO: no entra en la
        cascada (A4 (1))."""
        found = self.revision(op_uid)
        return found is not None and found.closed

    def frozen_use(self, node: OperationNode, dataset_uid: str) -> bool:
        """Si la operación ``node`` consumió el dato ``dataset_uid`` **congelado**: es de
        versión y el dato es de otra versión (lo único que admite ``begin_operation`` así es lo
        congelado de la revisión de la que parte su versión, ``Use.frozen``; D-27)."""
        if not node.revision_uid:
            return False
        dataset = self.datasets.get(dataset_uid)
        if dataset is None or not dataset.version_uid:
            return False
        own = self.revisions.get(node.revision_uid)
        return own is not None and dataset.version_uid != own.version_uid

    def frozen_source(self, node: OperationNode) -> RevisionNode | None:
        """La revisión congelada de la que parte la versión de ``node`` (de la que toma lo
        congelado); ``None`` si no la hay o no se cargó."""
        own = self.revisions.get(node.revision_uid) if node.revision_uid else None
        if own is None or not own.parent_revision_uid:
            return None
        return self.revisions.get(own.parent_revision_uid)

    def own_row(self, key: str, version_uid: str) -> str | None:
        """La fila (uid) del parámetro ``key`` propia de la versión ``version_uid``; ``None``
        si no la tiene (vale la del proyecto)."""
        return self._own_rows.get((key, version_uid))

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
        ella misma), sin repetir y en el orden de lo consumido; sin lo que consumió congelado
        (:meth:`frozen_use`: por ahí no le llega nada, A4 (3))."""
        node = self.operations[op_uid]
        found: list[str] = []
        for version in node.consumed:
            if version.item_kind != DATASET or self.frozen_use(node, version.uid):
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
PARAMETER_COLUMNS = "uid, key, scope, value_sha256, kind, unconfirmed, scope_uid"
"""Las columnas de ``gb_parameter`` de un :class:`ParameterNode`, en su orden."""
VERSIONED_OPERATION_COLUMNS = f"{OPERATION_COLUMNS}, revision_uid"
"""… las de un :class:`OperationNode` con su revisión (solo en una base con versiones)."""
VERSIONED_DATASET_COLUMNS = f"{DATASET_COLUMNS}, version_uid"
"""… las de un :class:`DatasetNode` con su versión (solo en una base con versiones)."""
REVISION_NODES = (
    "SELECT r.fid, r.uid, r.version_uid, v.code, r.number, r.state, r.altered_at IS NOT NULL, "
    "v.status, coalesce(v.parent_revision_uid, '') FROM gb_revision AS r "
    "CROSS JOIN gb_version AS v ON v.uid = r.version_uid"
)
"""Las revisiones con su versión (:func:`revision_node`, sin su ``fid``): pocas (20 versiones
con 10 revisiones, spec §7), por el ``fid`` de ``gb_revision`` y el uid de su versión."""


def versioned(conn: sqlite3.Connection) -> bool:
    """Si la base de ``conn`` tiene versiones (el esquema 3 o posterior, spec 009): un proyecto
    del esquema 2 abierto en solo lectura no las tiene, y el grafo se lee como antes."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'gb_version'"
    ).fetchone() is not None


def revision_node(row: tuple[Any, ...]) -> RevisionNode:
    """Una :class:`RevisionNode` de una fila de :data:`REVISION_NODES` sin su ``fid``."""
    uid, version_uid, code, number, state, altered, status, parent = row
    return RevisionNode(str(uid), str(version_uid), revision_label(str(code), int(number)),
                        str(state), bool(altered), str(status), str(parent))


def _own_rows(parameters: Iterable[ParameterNode]) -> dict[tuple[str, str], str]:
    """La fila propia de cada versión de cada parámetro: (clave, versión) → uid."""
    return {(node.key, node.scope_uid): node.uid for node in parameters
            if node.scope == VERSION_SCOPE and node.scope_uid}


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
    """Un :class:`OperationNode` de una fila de :data:`OPERATION_COLUMNS` (o de
    :data:`VERSIONED_OPERATION_COLUMNS`, con su revisión) y lo que consumió, produjo y leyó."""
    (fid, uid, op_type, op_version, module, repeatable, group_name, group_uid, supersedes_uid,
     superseded_by, started_at, finished_at, *revision) = row
    return OperationNode(
        int(fid), str(uid), str(op_type), str(op_version), str(module), bool(repeatable),
        group_name, group_uid, supersedes_uid, superseded_by, str(started_at), str(finished_at),
        tuple(consumed), tuple(produced), tuple(params),
        str(revision[0]) if revision else "",
    )


def dataset_node(row: tuple[Any, ...]) -> DatasetNode:
    """Un :class:`DatasetNode` de una fila de :data:`DATASET_COLUMNS` (o de
    :data:`VERSIONED_DATASET_COLUMNS`, con su versión)."""
    fid, uid, name, module, kind, status, sha, normalizer, operation_uid, input_uid, *version = row
    return DatasetNode(int(fid), str(uid), str(name), str(module), str(kind), str(status),
                       str(sha), str(normalizer), str(operation_uid), input_uid,
                       str(version[0]) if version else "")


def input_node(row: tuple[Any, ...]) -> InputNode:
    """Un :class:`InputNode` de una fila de :data:`INPUT_NODE_COLUMNS`."""
    return InputNode(*(str(value) for value in row))


def parameter_node(row: tuple[Any, ...]) -> ParameterNode:
    """Un :class:`ParameterNode` de una fila de :data:`PARAMETER_COLUMNS`."""
    uid, key, scope, value_sha256, kind, unconfirmed, scope_uid = row
    return ParameterNode(str(uid), str(key), str(scope), str(value_sha256), str(kind),
                         bool(unconfirmed), str(scope_uid))


def load_graph(conn: sqlite3.Connection, *, during: bool = False) -> ProvenanceGraph:
    """El grafo de la procedencia del proyecto de ``conn`` (de lectura o la transacción de
    escritura de quien llama: ve lo aún no confirmado), leído en una sola instantánea; con
    ``during``, también lo que cambió mientras se calculaba cada operación
    (:func:`changes_while_running`, para presentar sus causas; deducir no lo necesita). No
    escribe nada."""
    began = not conn.in_transaction
    if began:
        conn.execute("BEGIN")  # todas las lecturas en la misma instantánea
    try:
        return _load(conn, changes_while_running(conn) if during else None)
    finally:
        if began:
            conn.execute("ROLLBACK")


# Un parámetro que leyó una operación hecha y cuyo valor, cuando la operación terminó (la
# última revisión de su historial hasta su final), ya no era el que leyó: cambió mientras se
# calculaba. Solo los que hoy tienen otro valor (las causas; la revisión leída es anterior).
_PARAMETERS_DURING = (
    "SELECT p.operation_uid, p.parameter_uid FROM gb_operation_param AS p "
    "JOIN gb_operation AS op ON op.uid = p.operation_uid "
    "JOIN gb_parameter AS cur ON cur.uid = p.parameter_uid "
    "WHERE op.status = 'done' AND cur.value_sha256 <> p.value_sha256{only} "
    "AND (SELECT h.value_sha256 FROM gb_parameter_history AS h "
    "WHERE h.parameter_uid = p.parameter_uid AND h.rev > p.rev "
    "AND h.changed_at <= op.finished_at ORDER BY h.rev DESC LIMIT 1) <> p.value_sha256"
)
# Un dato que consumió una operación hecha y cuyo contenido, cuando la operación terminó (el de
# la última que lo escribió entre su principio y su final, sin contarla a ella), ya no era el
# que consumió: otra lo reescribió mientras se calculaba. Lo escrito antes de empezar no
# cuenta (al empezar, el contenido era el consumido), aunque su hora sea posterior a la de
# otra escritura (otro equipo con el reloj adelantado). Solo los que hoy tienen otro contenido
# (las causas); por el índice de gb_operation_io (item_kind, item_uid, direction).
_DATASETS_DURING = (
    "SELECT io.operation_uid, io.item_uid FROM gb_operation_io AS io "
    "JOIN gb_operation AS op ON op.uid = io.operation_uid "
    "JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.direction = 'in' AND io.item_kind = 'dataset' AND op.status = 'done' "
    "AND d.content_sha256 <> io.content_sha256{only} "
    "AND (SELECT w.content_sha256 FROM gb_operation_io AS w "
    "JOIN gb_operation AS x ON x.uid = w.operation_uid "
    "WHERE w.item_kind = 'dataset' AND w.item_uid = io.item_uid AND w.direction = 'out' "
    "AND w.operation_uid <> io.operation_uid AND x.status = 'done' "
    "AND x.finished_at >= op.started_at AND x.finished_at <= op.finished_at "
    "ORDER BY x.finished_at DESC, x.fid DESC LIMIT 1) <> io.content_sha256"
)
_DURING_CHUNK = 500
"""Cuántos uid van, como mucho, en cada ``IN (…)`` de :func:`changes_while_running`."""


def _chunks(values: Iterable[str]) -> list[list[str]]:
    uids = sorted(set(values))
    return [uids[start:start + _DURING_CHUNK] for start in range(0, len(uids), _DURING_CHUNK)]


def changes_while_running(conn: sqlite3.Connection, operations: Iterable[str] | None = None, *,
                          causes: Iterable[Cause] | None = None) -> dict[str, frozenset[Cause]]:
    """De cada operación hecha (de ``operations``; sin ellas, todas), las causas directas que
    cambiaron **mientras se calculaba** (RF-008-20): un parámetro que leyó y que al terminar
    ya tenía otro valor (la última revisión de su historial hasta su final), o un dato que
    consumió y que al terminar ya tenía otro contenido (el de la última operación que lo
    escribió entre su principio y su final, sin contarla a ella). Solo las que siguen siendo
    causa (hoy tienen otro valor o contenido); las que no tienen ninguna no están. Con
    ``causes``, solo esas, buscadas por lo que cambió (con los índices de quién lo consumió):
    lo que conviene para presentar las causas de muchas operaciones, como la lista de lo
    obsoleto (RNF-008-02). Lee ``conn`` sin escribir."""
    if isinstance(operations, str):
        raise TypeError(f"las operaciones son una lista de uid, no el texto {operations!r}")
    queries = ((_PARAMETERS_DURING, CauseKind.PARAMETER_CHANGED, "p"),
               (_DATASETS_DURING, CauseKind.DATASET_CHANGED, "io"))
    found: dict[str, set[Cause]] = defaultdict(set)
    if causes is not None:
        wanted = frozenset(causes)
        chosen = None if operations is None else set(operations)
        columns = {CauseKind.PARAMETER_CHANGED: "p.parameter_uid",
                   CauseKind.DATASET_CHANGED: "io.item_uid"}
        for sql, kind, _alias in queries:
            for chunk in _chunks(cause.subject for cause in wanted if cause.kind is kind):
                only = f" AND {columns[kind]} IN ({', '.join('?' for _ in chunk)})"
                for op_uid, subject in conn.execute(sql.format(only=only), tuple(chunk)):
                    if chosen is None or op_uid in chosen:
                        found[str(op_uid)].add(Cause(kind, str(subject)))
        return {uid: frozenset(found_causes) for uid, found_causes in found.items()}
    chunks: list[list[str]] = [[]] if operations is None else _chunks(operations)
    for chunk in chunks:
        marks = ", ".join("?" for _ in chunk)
        for sql, kind, alias in queries:
            only = f" AND {alias}.operation_uid IN ({marks})" if chunk else ""
            for op_uid, subject in conn.execute(sql.format(only=only), tuple(chunk)):
                found[str(op_uid)].add(Cause(kind, str(subject)))
    return {uid: frozenset(found_causes) for uid, found_causes in found.items()}


def _load(conn: sqlite3.Connection,
          during: Mapping[str, Iterable[Cause]] | None = None) -> ProvenanceGraph:
    """El grafo de :func:`load_graph`: :class:`GraphPages` en una sola lectura, sin páginas."""
    pages = GraphPages()
    pages.read(conn, rows=None)
    return pages.graph(during)


def _page(columns: str, table: str, where: str = "") -> str:
    return f"SELECT {columns} FROM {table} WHERE {where}fid > ? ORDER BY fid LIMIT ?"


# Cada tabla del grafo por páginas de su fid (la primera columna), en el orden en que se leen:
# lo consumido, producido y leído antes que las operaciones, que toman lo suyo al leerlas.
_PAGES: tuple[str, ...] = (
    _page(f"fid, {IO_COLUMNS}", "gb_operation_io"),
    _page(f"fid, {PARAM_USE_COLUMNS}", "gb_operation_param"),
    _page(OPERATION_COLUMNS, "gb_operation", f"status = '{DONE}' AND "),
    _page(DATASET_COLUMNS, "gb_dataset"),
    _page(f"fid, {INPUT_NODE_COLUMNS}", "gb_input"),
    _page(f"fid, {PARAMETER_COLUMNS}", "gb_parameter"),
    _page("fid, uid, key, scope_key, operation_uid", "gb_figure"),
)
# … y con versiones (spec 009): las operaciones con su revisión, los datos con su versión y,
# al final, las revisiones con su versión.
_VERSIONED_PAGES: tuple[str, ...] = (
    *_PAGES[:2],
    _page(VERSIONED_OPERATION_COLUMNS, "gb_operation", f"status = '{DONE}' AND "),
    _page(VERSIONED_DATASET_COLUMNS, "gb_dataset"),
    *_PAGES[4:],
    f"{REVISION_NODES} WHERE r.fid > ? ORDER BY r.fid LIMIT ?",
)


class GraphPages:
    """El grafo de la procedencia leído por páginas del ``fid`` de cada tabla —lo consumido y
    lo producido (``gb_operation_io``), los parámetros leídos, las operaciones hechas, los
    datos, las entradas, los parámetros y las cifras, en ese orden—, en una lectura o en varias
    (:meth:`read`); :meth:`graph` lo da cuando :attr:`finished`.

    Lo consumido, producido y leído se lee en su orden de registro, sin un JOIN a
    ``gb_operation`` por cada fila (RNF-008-02): las operaciones hechas, leídas una vez, toman
    lo suyo (lo de las que no terminaron se queda sin usar) y apuntan quién escribió cada
    versión y los miembros de cada grupo, sin volver a recorrer el grafo al darlo. Leído en una
    lectura es :func:`load_graph`; en varias, es el mismo si todas ven la misma base: quien lee
    en varias lo comprueba (la comprobación de apertura, con el contador de cambios de la
    cabecera de la base)."""

    def __init__(self) -> None:
        self._table = 0
        self._last = 0
        self._pages: tuple[str, ...] | None = None  # las de la base, al empezar a leer
        self._consumed: dict[str, list[Version]] = defaultdict(list)
        self._produced: dict[str, list[Version]] = defaultdict(list)
        self._used: dict[str, list[ParamUse]] = defaultdict(list)
        self._operations: dict[str, OperationNode] = {}
        self._written: dict[tuple[str, str], tuple[tuple[str, int, str], ...]] = {}
        self._writers: dict[tuple[str, str], tuple[str, ...]] = {}
        self._groups: dict[str, list[str]] = defaultdict(list)
        self._datasets: dict[str, DatasetNode] = {}
        self._inputs: dict[str, InputNode] = {}
        self._parameters: dict[str, ParameterNode] = {}
        self._figures: list[FigureNode] = []
        self._revisions: dict[str, RevisionNode] = {}

    @property
    def finished(self) -> bool:
        """Si ya se leyó todo."""
        return self._pages is not None and self._table >= len(self._pages)

    @property
    def fraction(self) -> float:
        """Lo leído, aproximado: la parte de las tablas ya terminadas."""
        if self._pages is None:
            return 0.0
        return min(self._table / len(self._pages), 1.0)

    def read(self, conn: sqlite3.Connection, *, rows: int | None = PAGE_ROWS,
             lap: Lap | None = None) -> None:
        """Sigue leyendo de ``conn`` páginas de ``rows`` filas (``None``: cada tabla de una
        vez) hasta terminar o hasta que ``lap`` pida parar (tras cada página). Con versiones
        (:func:`versioned`, mirado al empezar), también las revisiones de las operaciones y las
        versiones de los datos y, al final, las revisiones."""
        limit = -1 if rows is None else rows
        if self._pages is None:
            self._pages = _VERSIONED_PAGES if versioned(conn) else _PAGES
        pages = self._pages
        while self._table < len(pages):
            found = conn.execute(pages[self._table], (self._last, limit)).fetchall()
            if found:
                self._TAKE[self._table](self, found)
                self._last = int(found[-1][0])
            if rows is None or len(found) < rows:
                self._table += 1
                self._last = 0
            if lap is not None and lap():
                return

    def graph(self, during: Mapping[str, Iterable[Cause]] | None = None) -> ProvenanceGraph:
        """El grafo leído (con ``during``, como en :class:`ProvenanceGraph`).
        :class:`ValueError` si aún no se ha leído todo."""
        if not self.finished:
            raise ValueError("el grafo aún no se ha leído entero")
        return ProvenanceGraph._assembled(
            self._operations, self._datasets, self._inputs, self._parameters,
            tuple(self._figures), during, self._writers,
            {group: tuple(members) for group, members in self._groups.items()},
            self._revisions,
        )

    def release(self, lap: Lap | None = None) -> Generator[None, None, None]:
        """Suelta lo leído por trozos, cediendo cuando ``lap`` lo pide (soltar de una vez el
        grafo de D-13 son unos 6 ms, que irían en un solo paso). El grafo que se dio queda
        vacío."""
        found: dict[Any, Any]
        for found in (self._written, self._writers, self._operations, self._datasets,
                      self._consumed, self._produced, self._used, self._inputs,
                      self._parameters, self._groups, self._revisions):
            count = 0
            while found:
                found.popitem()
                count += 1
                if not count % _RELEASED and lap is not None and lap():
                    yield
        self._figures.clear()

    def _take_io(self, rows: list[tuple[Any, ...]]) -> None:
        consumed, produced = self._consumed, self._produced
        for _fid, op_uid, direction, item_kind, item_uid, sha, role in rows:
            (produced if direction == "out" else consumed)[op_uid].append(
                Version(str(item_kind), str(item_uid), str(sha), str(role)))

    def _take_params(self, rows: list[tuple[Any, ...]]) -> None:
        used = self._used
        for _fid, op_uid, parameter_uid, key, rev, value_sha256 in rows:
            used[op_uid].append(ParamUse(str(parameter_uid), str(key), int(rev),
                                         str(value_sha256)))

    def _take_operations(self, rows: list[tuple[Any, ...]]) -> None:
        written, writers = self._written, self._writers
        for row in rows:
            uid = row[1]
            node = operation_node(row, self._consumed.pop(uid, ()), self._produced.pop(uid, ()),
                                  self._used.pop(uid, ()))
            self._operations[node.uid] = node
            if node.group_uid is not None:
                self._groups[node.group_uid].append(node.uid)
            entry = (node.finished_at, node.fid, node.uid)
            for version in node.produced:
                if version.item_kind != DATASET:
                    continue
                key = (version.uid, version.content_sha256)
                found = written.get(key)
                if found is None:  # casi siempre: un escritor por versión
                    written[key] = (entry,)
                    writers[key] = (node.uid,)
                else:  # en el orden en que terminaron (y de registro)
                    found = written[key] = tuple(sorted((*found, entry)))
                    writers[key] = tuple(item[2] for item in found)

    def _take_datasets(self, rows: list[tuple[Any, ...]]) -> None:
        for row in rows:
            node = dataset_node(row)
            self._datasets[node.uid] = node

    def _take_inputs(self, rows: list[tuple[Any, ...]]) -> None:
        for row in rows:
            node = input_node(row[1:])
            self._inputs[node.uid] = node

    def _take_parameters(self, rows: list[tuple[Any, ...]]) -> None:
        for row in rows:
            node = parameter_node(row[1:])
            self._parameters[node.uid] = node

    def _take_figures(self, rows: list[tuple[Any, ...]]) -> None:
        self._figures.extend(
            FigureNode(int(fid), str(uid), str(key), str(scope_key), str(operation_uid))
            for fid, uid, key, scope_key, operation_uid in rows)

    def _take_revisions(self, rows: list[tuple[Any, ...]]) -> None:
        for row in rows:
            node = revision_node(row[1:])
            self._revisions[node.uid] = node

    _TAKE: tuple[Callable[[GraphPages, list[tuple[Any, ...]]], None], ...] = (
        _take_io, _take_params, _take_operations, _take_datasets, _take_inputs,
        _take_parameters, _take_figures, _take_revisions,
    )


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
    la versión instalada ``(M, m)`` de cada tipo de operación. Ninguna si es de una versión
    SUPERADO o DESCARTADO (A4 (1)); de lo que consumió congelado, solo que su revisión esté
    alterada (A4 (3)); y la fila propia de su versión de un parámetro que leyó de otra (A4
    (4))."""
    found: set[Cause] = set()
    revision = graph.revision(node.uid)
    if revision is not None and revision.closed:
        return found
    written = {version.uid for version in node.produced if version.item_kind == DATASET}
    for version in node.consumed:
        if version.item_kind == DATASET:
            if graph.frozen_use(node, version.uid):
                source = graph.frozen_source(node)
                if source is not None and source.altered:
                    found.add(Cause(CauseKind.DATASET_DAMAGED, version.uid))
                continue
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
        own = None if revision is None else graph.own_row(use.key, revision.version_uid)
        if own is not None and own != use.parameter_uid:
            found.add(Cause(CauseKind.PARAMETER_CHANGED, own))
    target = installed.get(node.op_type)
    if target is not None:
        try:
            registered = parse_version(node.op_version)
        except ValueError:  # pragma: no cover - el esquema la guarda de su OperationDef
            registered = None
        if registered is not None and target > registered:
            found.add(Cause(CauseKind.ALGORITHM, node.op_type))
    return found


_CAUSE_STATUSES = ", ".join(f"'{status}'" for status in (*DATASET_STATUS_CAUSES,
                                                           *INACTIVE_CAUSES))
_INACTIVE = ", ".join(f"'{status}'" for status in INACTIVE_CAUSES)
# Lo que leyó una operación hecha (en un tramo de fid) y le da una causa directa
# (direct_causes): un dato que no está vigente, o con otro contenido que no escribió ella; una
# entrada sustituida o descartada; un parámetro con otro valor. Los CROSS JOIN fijan el orden
# (del tramo de gb_operation_io o gb_operation_param a la operación y a lo leído, por su uid).
_CAUSED_BY_DATA = (
    "SELECT 1 FROM gb_operation_io AS io "
    "CROSS JOIN gb_operation AS op ON op.uid = io.operation_uid "
    "CROSS JOIN gb_dataset AS d ON d.uid = io.item_uid "
    f"WHERE io.fid > ? AND io.fid <= ? AND io.direction = 'in' AND io.item_kind = '{DATASET}' "
    f"AND op.status = '{DONE}' AND (d.status IN ({_CAUSE_STATUSES}) "
    "OR (d.content_sha256 <> io.content_sha256 AND NOT EXISTS (SELECT 1 FROM gb_operation_io "
    "AS w WHERE w.operation_uid = io.operation_uid AND w.direction = 'out' "
    f"AND w.item_kind = '{DATASET}' AND w.item_uid = io.item_uid))) LIMIT 1"
)
_CAUSED_BY_INPUTS = (
    "SELECT 1 FROM gb_operation_io AS io "
    "CROSS JOIN gb_operation AS op ON op.uid = io.operation_uid "
    "CROSS JOIN gb_input AS i ON i.uid = io.item_uid "
    f"WHERE io.fid > ? AND io.fid <= ? AND io.direction = 'in' AND io.item_kind = '{INPUT}' "
    f"AND op.status = '{DONE}' AND i.status IN ({_INACTIVE}) LIMIT 1"
)
_CAUSED_BY_PARAMETERS = (
    "SELECT 1 FROM gb_operation_param AS p "
    "CROSS JOIN gb_operation AS op ON op.uid = p.operation_uid "
    "CROSS JOIN gb_parameter AS cur ON cur.uid = p.parameter_uid "
    f"WHERE p.fid > ? AND p.fid <= ? AND op.status = '{DONE}' "
    "AND cur.value_sha256 <> p.value_sha256 LIMIT 1"
)
_DONE_PAGE = (
    f"SELECT fid, uid, op_type, op_version FROM gb_operation WHERE status = '{DONE}' "
    "AND fid > ? ORDER BY fid LIMIT ?"
)
_DATASET_PAGE = "SELECT fid, uid FROM gb_dataset WHERE fid > ? ORDER BY fid LIMIT ?"
_EDITABLE = ", ".join(f"'{status}'" for status in sorted(EDITABLE))
# Con versiones (spec 009, A4 (3) y (4)), lo que da una causa directa sin pasar por lo de
# arriba: una revisión alterada (de más: basta con que haya una, y hay pocas) y la fila propia
# de una versión viva de un parámetro que una operación suya leyó de otra fila. De los
# parámetros de versión (pocos) a su versión y sus revisiones, y de ahí a sus operaciones y a lo
# que leyeron, por sus índices.
_ALTERED_REVISION = "SELECT 1 FROM gb_revision WHERE altered_at IS NOT NULL LIMIT 1"
_OWN_ROW_CAUSE = (
    "SELECT 1 FROM gb_parameter AS v "
    "CROSS JOIN gb_version AS ver ON ver.uid = v.scope_uid "
    "CROSS JOIN gb_revision AS r ON r.version_uid = ver.uid "
    "CROSS JOIN gb_operation AS op ON op.revision_uid = r.uid AND op.revision_uid <> '' "
    "CROSS JOIN gb_operation_param AS p ON p.operation_uid = op.uid AND p.key = v.key "
    f"WHERE v.scope = '{VERSION_SCOPE}' AND ver.status IN ({_EDITABLE}) "
    f"AND op.status = '{DONE}' AND p.parameter_uid <> v.uid LIMIT 1"
)


class CauseScan:
    """Si alguna operación hecha tiene una **causa directa** (:func:`direct_causes`), leído de la
    base por páginas y sin cargar el grafo (la comprobación de apertura, T65; RNF-008-12): sin
    ninguna, nada está obsoleto (las causas raíz salen de las directas y la del grupo, de las
    raíz), así que la obsolescencia completa no necesita el grafo. Lee, en una lectura o en
    varias (:meth:`read`): las operaciones hechas (su uid y la versión de su algoritmo frente a
    la instalada, ``versions`` como en :func:`deduce`), lo que leyeron por tramos de ``fid``
    de ``gb_operation_io`` y ``gb_operation_param`` y los uid de los datos; para en cuanto
    encuentra una causa (:attr:`caused`). Sin causas, :attr:`operations` y :attr:`datasets`
    tienen los uid de todas las operaciones hechas y de todos los datos, en su orden. Con
    versiones, al final, lo que da una causa sin pasar por lo anterior (una revisión alterada,
    de más; la fila propia de una versión viva de un parámetro que una operación suya leyó de
    otra fila). Puede decir que hay causas que :func:`deduce` no encuentra (las de una versión
    cerrada, que no entra en la cascada; una revisión alterada sin nadie que tome lo suyo):
    entonces se carga el grafo, que da lo mismo; nunca al revés."""

    _PHASES = 5  # las operaciones, lo leído, los parámetros, los datos y las versiones

    def __init__(self, versions: Mapping[str, str] | None = None) -> None:
        _chosen, self._installed = _installed(versions)
        self.caused = False
        self.operations: list[str] = []
        self.datasets: list[str] = []
        self._phase = 0
        self._last = 0
        self._end: int | None = None

    @property
    def finished(self) -> bool:
        """Si ya se sabe: encontró una causa o lo leyó todo."""
        return self.caused or self._phase >= self._PHASES

    @property
    def fraction(self) -> float:
        """Lo leído, aproximado: la parte de las fases ya terminadas."""
        return 1.0 if self.finished else self._phase / self._PHASES

    def read(self, conn: sqlite3.Connection, *, rows: int | None = PAGE_ROWS,
             lap: Lap | None = None) -> None:
        """Sigue leyendo de ``conn`` páginas de ``rows`` filas (o tramos de ``rows`` fid;
        ``None``: cada tabla de una vez) hasta saberlo o hasta que ``lap`` pida parar (tras cada
        página)."""
        limit = -1 if rows is None else rows
        while not self.finished:
            if self._phase == 0:
                done = self._page(conn, _DONE_PAGE, limit, self._take_operations)
            elif self._phase == 3:
                done = self._page(conn, _DATASET_PAGE, limit, self._take_datasets)
            elif self._phase == 4:
                done = self._versions(conn)
            else:
                done = self._span(conn, rows)
            if done:
                self._phase += 1
                self._last = 0
                self._end = None
            if lap is not None and lap():
                return

    def _page(self, conn: sqlite3.Connection, sql: str, limit: int,
              take: Callable[[list[tuple[Any, ...]]], None]) -> bool:
        found = conn.execute(sql, (self._last, limit)).fetchall()
        take(found)
        if found:
            self._last = int(found[-1][0])
        return limit < 0 or len(found) < limit

    def _span(self, conn: sqlite3.Connection, rows: int | None) -> bool:
        table = "gb_operation_io" if self._phase == 1 else "gb_operation_param"
        if self._end is None:
            self._end = int(conn.execute(f"SELECT MAX(fid) FROM {table}").fetchone()[0] or 0)
        upper = self._end if rows is None else min(self._last + rows, self._end)
        queries = ((_CAUSED_BY_DATA, _CAUSED_BY_INPUTS) if self._phase == 1
                   else (_CAUSED_BY_PARAMETERS,))
        for sql in queries:
            if conn.execute(sql, (self._last, upper)).fetchone() is not None:
                self.caused = True
                return True
        self._last = upper
        return upper >= self._end

    def _versions(self, conn: sqlite3.Connection) -> bool:
        if versioned(conn):
            for sql in (_ALTERED_REVISION, _OWN_ROW_CAUSE):
                if conn.execute(sql).fetchone() is not None:
                    self.caused = True
                    break
        return True

    def _take_operations(self, rows: list[tuple[Any, ...]]) -> None:
        for _fid, uid, op_type, op_version in rows:
            self.operations.append(str(uid))
            target = self._installed.get(str(op_type))
            if target is None:
                continue
            try:
                registered = parse_version(str(op_version))
            except ValueError:  # pragma: no cover - el esquema la guarda de su OperationDef
                continue
            if target > registered:
                self.caused = True
                return

    def _take_datasets(self, rows: list[tuple[Any, ...]]) -> None:
        self.datasets.extend(str(uid) for _fid, uid in rows)


def root_causes(causes: Iterable[Cause]) -> frozenset[Cause]:
    """Las causas raíz de las causas de una operación (las de la caché): sin la de su grupo,
    que solo va en las operaciones del grupo y no se propaga ni pasa a sus datos."""
    return frozenset(cause for cause in causes if cause.kind is not CauseKind.GROUP)


def _installed(versions: Mapping[str, str] | None) -> tuple[dict[str, str],
                                                             dict[str, tuple[int, int]]]:
    chosen = dict(installed_versions() if versions is None else versions)
    return chosen, {op_type: parse_version(version) for op_type, version in chosen.items()}


def _roots(graph: ProvenanceGraph, members: Iterable[str],
           known: Mapping[str, Iterable[Cause]], installed: Mapping[str, tuple[int, int]],
           lap: Lap | None = None) -> Generator[None, None, dict[str, set[Cause]]]:
    """Las causas raíz de las operaciones ``members``: las directas, las ya conocidas
    (``known``) de las de fuera de las que dependen y lo que se propaga entre ellas. Por pasos:
    para cuando ``lap`` lo pide (tras cada operación)."""
    roots: dict[str, set[Cause]] = {}
    upstream: dict[str, tuple[str, ...]] = {}
    for uid in members:
        roots[uid] = direct_causes(graph, graph.operations[uid], installed)
        # Lo de una versión cerrada no recibe nada de aguas arriba (A4 (1)).
        upstream[uid] = () if graph.closed(uid) else graph.upstream(uid)
        if lap is not None and lap():
            yield
    if known:
        for uid, producers in upstream.items():
            for producer in producers:
                if producer not in roots:
                    roots[uid] |= root_causes(known.get(producer, ()))
    yield from _propagate(graph, roots, upstream, lap)
    return roots


def _propagate(graph: ProvenanceGraph, roots: dict[str, set[Cause]],
               upstream: Mapping[str, tuple[str, ...]],
               lap: Lap | None = None) -> Generator[None, None, None]:
    """Lleva las causas raíz de cada operación de ``roots`` a lo que depende de ella y a las
    de su ejecución de grupo (todas en ``roots``), hasta un punto fijo (los conjuntos solo
    crecen). Por pasos, como :func:`_roots`."""
    downstream: dict[str, list[str]] = defaultdict(list)
    for uid, producers in upstream.items():
        for producer in producers:
            if producer in roots:
                downstream[producer].append(uid)
        if lap is not None and lap():
            yield
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
            if target == uid or found <= mine or graph.closed(target):
                continue
            mine |= found
            if target not in queued:
                queued.add(target)
                pending.append(target)
        if lap is not None and lap():
            yield


def _current_figures(graph: ProvenanceGraph, causes: Mapping[str, frozenset[Cause]]
                     ) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str, str], str]]:
    """La cifra vigente de cada clave y ámbito entre las de las operaciones de proyecto y entre
    las de cada versión (A4 (5)): la de la operación más reciente sin sustituir que no está
    obsoleta; si todas lo están, la más reciente."""
    by_key: dict[tuple[str, str, str], list[FigureNode]] = defaultdict(list)
    for figure in graph.figures:
        node = graph.operations.get(figure.operation_uid)
        if node is not None and node.current:
            by_key[(graph.version_of(node.uid), figure.key, figure.scope_key)].append(figure)
    project: dict[tuple[str, str], str] = {}
    versions: dict[tuple[str, str, str], str] = {}
    for (version_uid, key, scope_key), found in by_key.items():
        fresh = [figure for figure in found if figure.operation_uid not in causes]
        uid = (fresh or found)[-1].uid
        if version_uid:
            versions[(version_uid, key, scope_key)] = uid
        else:
            project[(key, scope_key)] = uid
    return project, versions


def _with_group(graph: ProvenanceGraph, roots: Mapping[str, set[Cause]],
                lap: Lap | None = None) -> Generator[None, None, dict[str, frozenset[Cause]]]:
    """Las causas de cada operación obsoleta: las raíz y, en una ejecución de un grupo
    acoplado con más de una, la del grupo. Por pasos, como :func:`_roots`."""
    causes: dict[str, frozenset[Cause]] = {}
    for uid, found in roots.items():
        if found:
            group_uid = graph.operations[uid].group_uid
            if group_uid is not None and len(graph.group(group_uid)) > 1:
                found = found | {Cause(CauseKind.GROUP, group_uid)}
            causes[uid] = frozenset(found)
        if lap is not None and lap():
            yield
    return causes


def deduce(graph: ProvenanceGraph, *, versions: Mapping[str, str] | None = None) -> Staleness:
    """La obsolescencia completa de ``graph`` (véase el módulo). ``versions``: la versión
    instalada de cada tipo de operación (por defecto, la de los registrados,
    :func:`installed_versions`); un tipo que no está, no cambia de algoritmo.
    :class:`ValueError` si una versión no es «M.m». Es :func:`deduce_steps` de una vez."""
    return drain(deduce_steps(graph, versions=versions))


def deduce_steps(graph: ProvenanceGraph, *, versions: Mapping[str, str] | None = None,
                 lap: Lap | None = None) -> Generator[None, None, Staleness]:
    """:func:`deduce` por pasos (la comprobación de apertura, RNF-008-12): cede cuando ``lap``
    lo pide, tras cada operación o dato (sin ``lap``, de una vez), y devuelve lo mismo.
    :class:`ValueError` (al empezar) si una versión no es «M.m»."""
    chosen, installed = _installed(versions)
    roots = yield from _roots(graph, graph.operations, {}, installed, lap)
    causes = yield from _with_group(graph, roots, lap)
    data: dict[str, frozenset[Cause]] = {}
    writers: set[str] = set()  # las que escribieron el contenido actual de un dato vivo
    for dataset in graph.datasets.values():
        if dataset.live:
            writers.add(dataset.operation_uid)
            found = roots.get(dataset.operation_uid)
            if found:
                data[dataset.uid] = frozenset(found)
        if lap is not None and lap():
            yield
    current_figures, version_figures = _current_figures(graph, causes)
    figure_operations = {figure.uid: figure.operation_uid for figure in graph.figures}
    figure_writers = {figure_operations[uid]
                      for uid in (*current_figures.values(), *version_figures.values())}
    operations: dict[str, frozenset[Cause]] = {}
    review: set[str] = set()
    figure_only: set[str] = set()
    for uid, found in causes.items():
        node = graph.operations[uid]
        if node.current:
            operations[uid] = found
            if not node.repeatable and (uid in writers or uid in figure_writers):
                review.add(uid)
            elif node.repeatable and uid in figure_writers and uid not in writers:
                figure_only.add(uid)
        if lap is not None and lap():
            yield
    return Staleness(
        graph=graph,
        versions=MappingProxyType(chosen),
        causes=MappingProxyType(causes),
        operations=MappingProxyType(operations),
        datasets=MappingProxyType(data),
        review=frozenset(review),
        figure_only=frozenset(figure_only),
        current_figures=MappingProxyType(current_figures),
        current_version_figures=MappingProxyType(version_figures),
    )


def stale_state(conn: sqlite3.Connection, *,
                versions: Mapping[str, str] | None = None) -> Staleness:
    """:func:`deduce` sobre :func:`load_graph` de ``conn``, con lo que cambió mientras se
    calculaba cada operación (para presentar sus causas)."""
    return deduce(load_graph(conn, during=True), versions=versions)


@dataclass(frozen=True, slots=True)
class Staleness:
    """La obsolescencia deducida de un grafo:

    - ``causes``: las causas de cada operación hecha obsoleta, también las sustituidas (la
      historia); ``operations``: solo las que no están sustituidas;
    - ``datasets``: las causas de cada dato vivo obsoleto (las raíz de la operación que
      escribió su contenido actual);
    - ``review``: las operaciones que esperan revisión a mano (RF-008-27);
    - ``figure_only``: las operaciones obsoletas que solo dejan cifras (RF-008-28, spec 0.3):
      sin sustituir, que se repiten solas, que no escribieron el contenido actual de ningún
      dato vivo y sí la cifra vigente de una clave y un ámbito (la que no se repite sola espera
      revisión a mano);
    - ``current_figures``: la cifra vigente (uid) de cada clave y ámbito (``scope_key``) de
      las operaciones de proyecto; ``current_version_figures``, la de cada versión (su uid,
      la clave y el ámbito; spec 009, A4 (5));
    - ``versions``: las versiones instaladas de los algoritmos con que se dedujo.
    """

    graph: ProvenanceGraph
    versions: Mapping[str, str]
    causes: Mapping[str, frozenset[Cause]]
    operations: Mapping[str, frozenset[Cause]]
    datasets: Mapping[str, frozenset[Cause]]
    review: frozenset[str]
    figure_only: frozenset[str]
    current_figures: Mapping[tuple[str, str], str]
    current_version_figures: Mapping[tuple[str, str, str], str] = MappingProxyType({})

    @property
    def current_figure_uids(self) -> frozenset[str]:
        """Las cifras vigentes (uid) del proyecto y de cada versión."""
        return frozenset((*self.current_figures.values(),
                          *self.current_version_figures.values()))

    def of(self, uid: str) -> frozenset[Cause]:
        """Las causas de la operación o del dato ``uid`` (vacío si no está obsoleto)."""
        return self.causes.get(uid) or self.datasets.get(uid) or frozenset()

    def writer(self, uid: str) -> str | None:
        """La operación de ``uid``: ella misma o la que escribió el contenido actual del
        dato; ``None`` si no es ninguna de las dos."""
        if uid in self.graph.operations:
            return uid
        dataset = self.graph.datasets.get(uid)
        return None if dataset is None else dataset.operation_uid

    def describe(self, cause: Cause, *, language: str = "es",
                 operation: str | None = None) -> str:
        """Una causa como la lee una persona, en ``language`` («cambió Producción»; de la
        operación ``operation``, «… mientras se calculaba» si cambió entonces)."""
        return describe_cause(self.graph, self.versions, cause, language=language,
                              operation=operation)

    def text(self, uid: str, *, language: str = "es") -> str | None:
        """«Obsoleto: …» con las causas de la operación o del dato ``uid``, por clase y por
        nombre (las que cambiaron mientras se calculaba la operación o la que escribió el
        dato, así); ``None`` si no está obsoleto."""
        return stale_text(self.graph, self.versions, self.of(uid), language=language,
                          operation=self.writer(uid))


def describe_cause(graph: ProvenanceGraph, versions: Mapping[str, str], cause: Cause, *,
                   language: str = "es", operation: str | None = None) -> str:
    """Una causa como la lee una persona, en ``language`` («cambió Producción»), con los
    nombres de ``graph`` (el del dato, la entrada, el parámetro o el grupo; su uid si no
    está) y, para un algoritmo, la versión instalada de ``versions`` y las anteriores
    registradas en ``graph``. Si es de las que cambiaron mientras se calculaba la operación
    ``operation`` (:attr:`ProvenanceGraph.during`), «… mientras se calculaba» (RF-008-20)."""
    text = _cause_text(graph, versions, cause, language)
    if operation is not None and cause in graph.during.get(operation, ()):
        return render("core.cause_while_running", language=language, cause=text)
    return text


def _cause_text(graph: ProvenanceGraph, versions: Mapping[str, str], cause: Cause,
                language: str) -> str:
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
        if (kind is CauseKind.DATASET_DAMAGED and dataset is not None
                and dataset.status != "damaged"):
            # No es el dato el dañado: es lo congelado de él que tomó la operación, en una
            # revisión alterada (spec 009, A4 (3)).
            return render("core.cause_frozen_altered", language=language, **values)
    return render(f"core.cause_{kind}", language=language, **values)


def stale_text(graph: ProvenanceGraph, versions: Mapping[str, str], causes: Iterable[Cause],
               *, language: str = "es", operation: str | None = None) -> str | None:
    """«Obsoleto: …» con ``causes`` (:func:`describe_cause`, de la operación
    ``operation``), por clase y por nombre; ``None`` sin causas."""
    shown = sorted((_ORDER[cause.kind], describe_cause(graph, versions, cause,
                                                       language=language,
                                                       operation=operation))
                   for cause in causes)
    if not shown:
        return None
    return render("core.stale", language=language,
                  causes=CAUSE_SEPARATOR.join(text for _order, text in shown))


def _parameter_name(graph: ProvenanceGraph, uid: str, language: str) -> str:
    """El nombre visible de un parámetro (su etiqueta, con los segmentos variables si es de
    una familia, ADR-0027; o su clave si no la tiene)."""
    node = graph.parameters.get(uid)
    key = uid if node is None else node.key
    label = parameter_label(key, language)
    return key if label is None else label


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
    roots = drain(_roots(graph, members, known, installed))
    return RegionStaleness(
        region=members,
        roots=MappingProxyType({uid: frozenset(found) for uid, found in roots.items()}),
        causes=MappingProxyType(drain(_with_group(graph, roots))),
    )
