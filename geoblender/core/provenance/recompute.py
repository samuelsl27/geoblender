# SPDX-License-Identifier: GPL-3.0-or-later
"""«Recalcular lo obsoleto» y «dar por buena» (spec 008; RF-008-25, RF-008-26, RF-008-27;
ADR-0025 §5; plan 008 §5.1, §5.3.1, §5.4.4 y D8).

:func:`plan_recompute` decide, sobre el grafo de la procedencia (:mod:`.graph`) y su
obsolescencia deducida, **qué** se recalcula y **en qué orden**, sin ejecutar ni escribir
nada; :func:`recompute_steps` lo ejecuta por unidades y :func:`accept_review` «da por buena»
una operación que espera revisión a mano (al final del módulo). Nada se recalcula sin que el
usuario lo pida (D-4): el plan responde a «Recalcular lo obsoleto».

- **Qué hay que rehacer**: las operaciones obsoletas sin sustituir que escribieron el contenido
  actual de un dato vivo o la cifra vigente de su clave y su ámbito (el mismo criterio que la
  revisión a mano de :func:`.graph.deduce`). Una obsoleta cuyo resultado ya reescribió otra no
  tiene nada que rehacer: recalcularla borraría lo de la otra (una edición a mano, por ejemplo).
- **Unidades** (:class:`RecomputeUnit`): una ejecución de un grupo acoplado entera (sus
  operaciones obsoletas sin sustituir), en el orden de su :class:`~.contract.CoupledGroupDef`
  (si el grupo no está registrado, en el que se ejecutó), o una operación sola (RF-008-25).
- **Dependencia**: una operación necesita antes a quien escribió las versiones que consumió
  (por ahí le llega lo obsoleto) y a quien escribió el contenido actual de esos datos (lo que
  leerá al recalcularse con las entradas vigentes). Las unidades van en orden topológico de
  todo lo obsoleto y, entre las que no dependen unas de otras, por orden de registro; las de un
  ciclo (una que reescribe lo que leyó otra que lee lo suyo), por orden de registro.
- **Lo que se deja fuera, con su motivo** (:class:`Skipped`, :class:`SkipReason`): la que no
  se repite sola («revisar a mano», RF-008-27); la de un tipo que no está instalado
  (``core.operation_unregistered``) y la calculada con una versión de su algoritmo mayor que la
  instalada («Calculado con gis.resample 1.1: actualice Geoblender», RF-008-26); las demás de
  su ejecución de grupo (RF-008-25); y lo que depende de cualquiera de ellas aguas abajo,
  también indirectamente y aunque esté fuera del ámbito («espera»): recalcularlo leería algo que
  sigue obsoleto, y RF-008-27 lo prohíbe hasta que se revise.
- **Ámbitos**: todo (:data:`SCOPE_ALL`); una causa (:class:`~.graph.Cause`, «lo que depende de
  un cambio»: las operaciones que la tienen); o un elemento, el uid de un dato o de una
  operación: lo que necesita para quedar al día (la operación que escribió el dato, o esa
  operación, y lo obsoleto que tiene aguas arriba). Las unidades llevan siempre toda su
  ejecución de grupo.

**Ejecutar el plan** (:func:`recompute_steps`, por pasos que avanza el temporizador de ``bl``,
con progreso y cancelación):

- antes de cada unidad **vuelve a planificar** (un recálculo que dio el mismo contenido deja a
  sus consumidores sin causa: lo que dependía solo de él ya no está en el plan, sin
  recalcularse) y toma la primera unidad que no espera a nada que en esta ejecución no se
  recalculó (la que se negó o falló, y lo recalculado que volvió a quedar obsoleto);
- **al empezarla** comprueba que sus entradas siguen vigentes: si una entrada de aguas arriba
  cambió y no se ha decidido (RF-008-10), o consume un dato que falta, está bloqueado o
  dañado, o uno descartado sin sucesor, no se ejecuta y sigue obsoleta, con el motivo
  (:attr:`UnitStatus.REFUSED`), y lo que depende de ella espera;
- cada operación se repite con la función de recálculo de su tipo
  (``OperationDef.recompute``), que recibe una :class:`RecomputeRequest` (los mismos
  ajustes, lo que consumió en sus versiones vigentes —el sucesor de lo sustituido— y las
  claves de sus parámetros, que se resuelven vigentes al empezar) y crea una operación nueva
  que **sustituye** a la anterior, que queda como historia (D-6); las de un grupo acoplado,
  en su orden y en una ejecución de grupo nueva. Si la calcula un trabajo de la 004, la
  operación vuelve «en curso» y se espera, paso a paso, a que termine. Si falla, la unidad
  queda :attr:`UnitStatus.FAILED` con su motivo y lo anterior sigue vigente;
- cancelar (``cancelled``) para al acabar la unidad en curso: lo ya recalculado queda (cada
  operación es completa) y lo demás sigue obsoleto (:class:`RecomputeOutcome`).

**Dar por buena** (:func:`accept_review`, D8): una operación nueva ``core.accept_review``, con
el motivo, que consume las versiones vigentes de lo que consumía la revisada (menos lo que
ella misma escribió: es lo que se da por bueno), «produce» las mismas versiones de sus datos
vigentes y su cifra vigente (el mismo contenido) y la sustituye, en una sola transacción y con
su evento ``review_accepted``; lo de aguas abajo deja de esperar. No se da por buena mientras
lo que consume siga obsoleto, ni lo importado de una entrada (se actualiza o se reimporta).

Python puro (ADR-0004).
"""

from __future__ import annotations

import heapq
import json
import sqlite3
from collections import defaultdict, deque
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, NamedTuple, Protocol

from ..datasets import registry as dataset_registry
from ..datasets.model import DatasetSpec, DatasetStatus
from ..errors import GeoblenderError
from ..ids import new_uid
from ..project.model import Progress
from ..timeutil import format_utc
from .contract import ACCEPT_REVIEW, GROUPS, operation_def, parse_version
from .figures import RECORD_COLUMNS as FIGURE_COLUMNS
from .figures import FigureRecord, FigureSpec
from .graph import (
    DATASET,
    DATASET_STATUS_CAUSES,
    Cause,
    OperationNode,
    ProvenanceGraph,
    Staleness,
    deduce,
    load_graph,
)
from .messages import ProvenanceError, render
from .operations import (
    Executor,
    ItemKind,
    OperationHandle,
    OperationProject,
    OperationStatus,
    Use,
    _clean,
    _record,
    _require_writable,
    begin_in_transaction,
    begin_operation,
)
from .operations import operation as run_operation

SCOPE_ALL = "all"
"""El ámbito «todo lo obsoleto»."""

type Scope = str | Cause
"""Un ámbito de :func:`plan_recompute`: :data:`SCOPE_ALL`, una :class:`~.graph.Cause` o el uid
de un dato o de una operación."""


class SkipReason(StrEnum):
    """Por qué una operación obsoleta se deja fuera del plan."""

    REVIEW = "review"  # no se repite sola: espera revisión a mano (RF-008-27)
    UNKNOWN_TYPE = "unknown_type"  # su tipo no está instalado (o no está activo su módulo)
    NEWER_ALGORITHM = "newer_algorithm"  # calculada con un algoritmo mayor que el instalado
    GROUP = "group"  # otra de su ejecución de grupo no se puede recalcular (RF-008-25)
    WAITS = "waits"  # depende, aguas arriba, de una que no se recalcula ahora


BLOCKING_REASONS: frozenset[SkipReason] = frozenset({
    SkipReason.REVIEW, SkipReason.UNKNOWN_TYPE, SkipReason.NEWER_ALGORITHM,
})
"""Los motivos propios de una operación: lo que depende de ella aguas abajo espera."""

REASON_CODES: Mapping[SkipReason, str] = MappingProxyType({
    SkipReason.REVIEW: "core.recompute_review",
    SkipReason.UNKNOWN_TYPE: "core.operation_unregistered",
    SkipReason.NEWER_ALGORITHM: "core.recompute_newer_algorithm",
    SkipReason.GROUP: "core.recompute_group",
    SkipReason.WAITS: "core.recompute_waits",
})
"""El mensaje (``core.provenance.messages``) de cada motivo."""


class OperationRef(NamedTuple):
    """Una operación por la que espera otra: su uid y su tipo."""

    uid: str
    op_type: str


@dataclass(frozen=True, slots=True)
class RecomputeUnit:
    """Lo que se recalcula junto: una operación sola o una ejecución de un grupo acoplado
    (``group_uid``, ``group_name``) entera, en su orden; ``op_types``, sus tipos."""

    operations: tuple[str, ...]
    op_types: tuple[str, ...]
    group_uid: str | None = None
    group_name: str | None = None


@dataclass(frozen=True, slots=True)
class Skipped:
    """Una operación obsoleta que el plan deja fuera: su tipo y la versión de su algoritmo,
    el motivo, sus causas de obsolescencia (lo que cambió), las operaciones por las que espera
    (``WAITS``: las de aguas arriba que no se recalculan; ``GROUP``: las de su grupo) y su
    grupo."""

    operation_uid: str
    op_type: str
    op_version: str
    reason: SkipReason
    causes: frozenset[Cause]
    waits_for: tuple[OperationRef, ...] = ()
    group: str | None = None

    def text(self, *, language: str = "es") -> str:
        """El motivo como lo lee una persona, en ``language`` («Calculado con res.step_a 1.9:
        actualice Geoblender»)."""
        names = ", ".join(dict.fromkeys(f"«{ref.op_type}»" for ref in self.waits_for))
        return render(REASON_CODES[self.reason], language=language, op_type=self.op_type,
                      version=self.op_version, operations=names, group=self.group)


@dataclass(frozen=True, slots=True)
class RecomputePlan:
    """El plan de «Recalcular lo obsoleto» en un ámbito: las unidades en orden y lo que se
    deja fuera, con su motivo, por orden de registro."""

    scope: Scope
    units: tuple[RecomputeUnit, ...]
    skipped: tuple[Skipped, ...]

    @property
    def operations(self) -> tuple[str, ...]:
        """Las operaciones que se recalculan, en orden."""
        return tuple(uid for unit in self.units for uid in unit.operations)


# --- Plan ---------------------------------------------------------------------------------------


def plan_recompute(graph: ProvenanceGraph, *, scope: Scope = SCOPE_ALL,
                   versions: Mapping[str, str] | None = None) -> RecomputePlan:
    """El plan de «Recalcular lo obsoleto» de ``graph`` en ``scope`` (véase el módulo), con
    la obsolescencia de :func:`.graph.deduce` y ``versions``, la versión instalada de cada
    tipo de operación (por defecto, la de los registrados); un tipo que no está, no se
    recalcula. Solo lee ``graph``.

    :class:`TypeError` si ``graph`` no es un grafo o ``scope`` no es :data:`SCOPE_ALL`, una
    causa ni un texto; :class:`ValueError` si el texto no es una operación ni un dato del
    grafo, o si una versión no es «M.m»."""
    if not isinstance(graph, ProvenanceGraph):
        raise TypeError(f"plan_recompute recibe el grafo de la procedencia, no {graph!r}")
    return _plan(graph, scope, versions)[1]


def _plan(graph: ProvenanceGraph, scope: Scope,
          versions: Mapping[str, str] | None) -> tuple[_Planner, RecomputePlan]:
    """El plan de ``graph`` en ``scope`` y su planificador (lo que necesita cada unidad)."""
    targets = _targets(graph, scope)
    planner = _Planner(deduce(graph, versions=versions))
    if isinstance(scope, Cause):
        wanted = {uid for uid in planner.relevant if scope in planner.stale[uid]}
    elif targets is None:
        wanted = set(planner.relevant)
    else:
        wanted = planner.upstream_of(targets) & planner.relevant
    return planner, planner.plan(scope, wanted)


def _targets(graph: ProvenanceGraph, scope: object) -> set[str] | None:
    """Las operaciones de un elemento (``None``: todo o una causa)."""
    if isinstance(scope, Cause):
        return None
    if type(scope) is not str:  # ni un enumerado: SCOPE_ALL, una causa o un uid
        raise TypeError(f"el ámbito de «Recalcular lo obsoleto» es «{SCOPE_ALL}», una causa o "
                        f"el uid de un dato o de una operación, no {scope!r}")
    if scope == SCOPE_ALL:
        return None
    if scope in graph.operations:
        return {scope}
    dataset = graph.datasets.get(scope)
    if dataset is None:
        raise ValueError(f"«{scope}» no es ninguna operación hecha ni ningún dato del proyecto")
    return {dataset.operation_uid}


def needs(graph: ProvenanceGraph, uid: str) -> set[str]:
    """Las operaciones que necesita antes la operación ``uid`` para recalcularse: quien
    escribió las versiones de dato que consumió y quien escribió el contenido actual de esos
    datos (sin ella misma)."""
    node = graph.operations[uid]
    found = set(graph.upstream(uid))
    for version in node.consumed:
        dataset = graph.datasets.get(version.uid) if version.item_kind == DATASET else None
        if dataset is not None and dataset.operation_uid in graph.operations:
            found.add(dataset.operation_uid)
    found.discard(uid)
    return found


def _own_reason(node: OperationNode, relevant: frozenset[str],
                installed: Mapping[str, tuple[int, int]]) -> tuple[bool, SkipReason | None]:
    """Si la operación ``node`` impide recalcular su unidad y su motivo propio: la que no se
    repite sola, «revisar a mano» si hay algo que revisar (si no, sin motivo: su resultado ya
    lo reescribió otra); la de un tipo sin instalar o con un algoritmo mayor que el
    instalado."""
    if not node.repeatable:
        return True, SkipReason.REVIEW if node.uid in relevant else None
    target = installed.get(node.op_type)
    if target is None:
        return True, SkipReason.UNKNOWN_TYPE
    if target < parse_version(node.op_version):
        return True, SkipReason.NEWER_ALGORITHM
    return False, None


class _Planner:
    """Lo obsoleto de una :class:`~.graph.Staleness` por unidades: qué hay que rehacer, qué
    necesita cada unidad, qué la impide, por qué espera y en qué orden van."""

    def __init__(self, state: Staleness) -> None:
        graph = state.graph
        self.graph = graph
        self.stale: Mapping[str, frozenset[Cause]] = state.operations
        figures = {figure.uid: figure.operation_uid for figure in graph.figures}
        writers = {dataset.operation_uid for dataset in graph.datasets.values() if dataset.live}
        writers |= {figures[uid] for uid in state.current_figures.values()}
        self.relevant = frozenset(uid for uid in self.stale if uid in writers)
        members: dict[str, list[OperationNode]] = defaultdict(list)
        for uid in self.stale:
            node = graph.operations[uid]
            members[node.group_uid if node.group_uid is not None else uid].append(node)
        self.units: dict[str, tuple[str, ...]] = {
            key: _in_group_order(nodes) for key, nodes in members.items()
        }
        self.unit_of = {uid: key for key, uids in self.units.items() for uid in uids}
        self.needs = {uid: {dep for dep in needs(graph, uid) if dep in self.stale}
                      for uid in self.stale}
        self.unit_needs = {
            key: {self.unit_of[dep] for uid in uids for dep in self.needs[uid]} - {key}
            for key, uids in self.units.items()
        }
        installed = {op_type: parse_version(version)
                     for op_type, version in state.versions.items()}
        self.own: dict[str, SkipReason] = {}
        self.stuck: dict[str, tuple[str, ...]] = {}
        for key in {self.unit_of[uid] for uid in self.relevant}:  # las que hay que rehacer
            found: list[str] = []
            for uid in self.units[key]:
                blocks, reason = _own_reason(graph.operations[uid], self.relevant, installed)
                if blocks:
                    found.append(uid)
                if reason is not None:
                    self.own[uid] = reason
            if found:
                self.stuck[key] = tuple(found)
        self.waits = self._waits()
        self.order = self._order()

    def _waits(self) -> dict[str, set[str]]:
        """Por qué operaciones espera cada unidad: las de aguas arriba con un motivo propio,
        también indirectamente (hasta un punto fijo; los conjuntos solo crecen)."""
        downstream: dict[str, list[str]] = defaultdict(list)
        for key, deps in self.unit_needs.items():
            for dep in deps:
                downstream[dep].append(key)
        refs = {key: {uid for uid in uids if uid in self.own}
                for key, uids in self.stuck.items()}
        waits: dict[str, set[str]] = defaultdict(set)
        pending = deque(key for key, found in refs.items() if found)
        queued = set(pending)
        while pending:
            key = pending.popleft()
            queued.discard(key)
            out = refs.get(key, set()) | waits[key]
            for other in downstream[key]:
                if out <= waits[other]:
                    continue
                waits[other] |= out
                if other not in queued:
                    queued.add(other)
                    pending.append(other)
        return waits

    def _rank(self, key: str) -> int:
        return min(self.graph.operations[uid].fid for uid in self.units[key])

    def _order(self) -> list[str]:
        """Las unidades en orden topológico de sus componentes fuertemente conexas (Kahn sobre
        ellas, por orden de registro entre las listas); dentro de un ciclo, por orden de
        registro."""
        keys = sorted(self.units, key=self._rank)
        components = strong_components(keys, self.unit_needs)
        component_of = {key: n for n, members in enumerate(components) for key in members}
        rank = {key: n for n, key in enumerate(keys)}
        first = [min(rank[key] for key in members) for members in components]
        component_needs = [
            {component_of[dep] for key in members for dep in self.unit_needs[key]} - {n}
            for n, members in enumerate(components)
        ]
        missing = [len(found) for found in component_needs]
        downstream: dict[int, list[int]] = defaultdict(list)
        for n, found in enumerate(component_needs):
            for dep in found:
                downstream[dep].append(n)
        ready = [(first[n], n) for n, count in enumerate(missing) if not count]
        heapq.heapify(ready)
        order: list[str] = []
        while ready:
            _first, n = heapq.heappop(ready)
            order.extend(sorted(components[n], key=rank.__getitem__))
            for other in downstream[n]:
                missing[other] -= 1
                if not missing[other]:
                    heapq.heappush(ready, (first[other], other))
        return order

    def upstream_of(self, targets: Iterable[str]) -> set[str]:
        """Las operaciones obsoletas ``targets`` y lo obsoleto que necesitan aguas arriba, con
        sus ejecuciones de grupo."""
        pending = [uid for uid in targets if uid in self.stale]
        seen: set[str] = set()
        while pending:
            uid = pending.pop()
            if uid in seen:
                continue
            seen.add(uid)
            pending.extend(self.needs[uid])
            pending.extend(self.units[self.unit_of[uid]])
        return seen

    def held(self, uids: Iterable[str]) -> set[str]:
        """Las unidades (sus claves) de las operaciones obsoletas ``uids`` y las que dependen
        de ellas aguas abajo, también indirectamente."""
        downstream: dict[str, list[str]] = defaultdict(list)
        for key, deps in self.unit_needs.items():
            for dep in deps:
                downstream[dep].append(key)
        pending = [self.unit_of[uid] for uid in uids if uid in self.unit_of]
        seen: set[str] = set()
        while pending:
            key = pending.pop()
            if key not in seen:
                seen.add(key)
                pending.extend(downstream[key])
        return seen

    def key_of(self, unit: RecomputeUnit) -> str:
        """La clave de la unidad ``unit`` del plan."""
        return self.unit_of[unit.operations[0]]

    def _ref(self, uid: str) -> OperationRef:
        return OperationRef(uid, self.graph.operations[uid].op_type)

    def _refs(self, uids: Iterable[str]) -> tuple[OperationRef, ...]:
        ordered = sorted(uids, key=lambda uid: self.graph.operations[uid].fid)
        return tuple(self._ref(uid) for uid in ordered)

    def _skipped(self, uid: str, reason: SkipReason,
                 waits_for: Iterable[str] = ()) -> Skipped:
        node = self.graph.operations[uid]
        return Skipped(uid, node.op_type, node.op_version, reason, self.stale[uid],
                       self._refs(waits_for), node.group_name or node.group_uid)

    def _left_out(self, key: str) -> list[Skipped] | None:
        """Lo que se deja fuera de la unidad ``key``; ``None`` si se recalcula."""
        uids = self.units[key]
        stuck = self.stuck.get(key)
        if stuck:
            found: list[Skipped] = []
            for uid in uids:
                reason = self.own.get(uid)
                if reason is not None:
                    found.append(self._skipped(uid, reason))
                elif uid in stuck:  # no se repite sola y no tiene nada que revisar
                    continue
                else:
                    found.append(self._skipped(uid, SkipReason.GROUP, stuck))
            return found
        if self.waits[key]:
            return [self._skipped(uid, SkipReason.WAITS, self.waits[key]) for uid in uids]
        return None

    def plan(self, scope: Scope, wanted: set[str]) -> RecomputePlan:
        """El plan de las unidades de las operaciones ``wanted`` (en el ámbito ``scope``)."""
        chosen = {self.unit_of[uid] for uid in wanted}
        units: list[RecomputeUnit] = []
        skipped: list[Skipped] = []
        for key in self.order:
            if key not in chosen:
                continue
            left_out = self._left_out(key)
            if left_out is not None:
                skipped.extend(left_out)
                continue
            nodes = [self.graph.operations[uid] for uid in self.units[key]]
            group_uid = nodes[0].group_uid
            units.append(RecomputeUnit(
                tuple(node.uid for node in nodes), tuple(node.op_type for node in nodes),
                group_uid, nodes[0].group_name if group_uid is not None else None,
            ))
        skipped.sort(key=lambda item: self.graph.operations[item.operation_uid].fid)
        return RecomputePlan(scope, tuple(units), tuple(skipped))


def strong_components(keys: Iterable[str],
                      edges: Mapping[str, Iterable[str]]) -> list[list[str]]:
    """Las componentes fuertemente conexas del grafo ``edges`` (de cada nudo de ``keys``, los
    que necesita), con el algoritmo de Tarjan sin recursión (un grafo de 10 000 operaciones en
    cadena no cabe en la pila de Python). Cada componente sale después de las que necesita."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[list[str]] = []
    for root in keys:
        if root in index:
            continue
        index[root] = low[root] = len(index)
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(edges[root]))]
        while work:
            node, pending = work[-1]
            for nxt in pending:
                if nxt not in index:
                    index[nxt] = low[nxt] = len(index)
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(edges[nxt])))
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    members: list[str] = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        members.append(member)
                        if member == node:
                            break
                    found.append(members)
    return found


def _in_group_order(nodes: list[OperationNode]) -> tuple[str, ...]:
    """Las operaciones de una unidad: las de una ejecución de grupo en el orden de su
    :class:`~.contract.CoupledGroupDef` (las de un tipo que no está en él, después) o, si el
    grupo no está registrado, en el que se ejecutaron (registro)."""
    name = nodes[0].group_name
    group = GROUPS.get(name) if name is not None else None
    order = group.op_types if group is not None else ()

    def key(node: OperationNode) -> tuple[int, int]:
        position = order.index(node.op_type) if node.op_type in order else len(order)
        return position, node.fid

    return tuple(node.uid for node in sorted(nodes, key=key))


# --- Ejecutar el plan (RF-008-26) -------------------------------------------------------------

RECOMPUTE_PHASE = "recompute"
"""La fase del progreso de «Recalcular lo obsoleto» (``Progress.phase``)."""

CHANGED_INPUT = "changed"
"""Una entrada cambiada sin decidir (``gb_input.status``): lo que la tiene aguas arriba no se
recalcula (RF-008-10)."""
DISCARDED_INPUT = "discarded"
INACTIVE_INPUTS: tuple[str, ...] = ("superseded", DISCARDED_INPUT)
"""Los estados de una entrada que ya no se consume (``core.provenance.schema``)."""


class RecomputeHandle(Protocol):
    """Lo que devuelve la función de recálculo de un tipo: la operación nueva (su
    ``OperationHandle``), terminada o, si la calcula un trabajo de la 004, aún en curso."""

    @property
    def uid(self) -> str: ...


@dataclass(frozen=True, slots=True)
class RecomputeRequest:
    """Lo que recibe la función de recálculo de un tipo (``OperationDef.recompute``) para
    repetir la operación ``operation_uid`` (RF-008-26):

    - ``project``, el proyecto; ``op_type`` y ``settings``, su tipo y los mismos ajustes;
    - ``inputs``: lo que consumió, en sus versiones vigentes (el sucesor de lo sustituido),
      con su papel;
    - ``params``: las claves de los parámetros que leyó (al empezar se resuelven los
      vigentes);
    - ``group_uid``: la ejecución nueva de su grupo acoplado, la misma para toda la unidad
      (``None`` si no es de un grupo).

    La función empieza la operación nueva con :meth:`begin` o :meth:`operation` (que la
    anotan como sustituta de la antigua), la ejecuta, la completa y la devuelve
    (:class:`RecomputeHandle`); si la calcula un trabajo de la 004, la devuelve en curso."""

    project: OperationProject
    operation_uid: str
    op_type: str
    settings: Mapping[str, Any]
    inputs: tuple[Use, ...]
    params: tuple[str, ...]
    group_uid: str | None = None

    def arguments(self) -> dict[str, Any]:
        """Los argumentos de :func:`~.operations.begin_operation` (sin el ejecutor) de la
        operación nueva, que sustituye a la antigua."""
        return {"settings": dict(self.settings), "inputs": self.inputs, "params": self.params,
                "group_uid": self.group_uid, "supersedes": self.operation_uid}

    def begin(self, *, executor: Executor | str = Executor.BLENDER,
              job_uid: str | None = None) -> OperationHandle:
        """:func:`~.operations.begin_operation` de la operación nueva (para un trabajo)."""
        return begin_operation(self.project, self.op_type, executor=executor, job_uid=job_uid,
                               **self.arguments())

    def operation(self, *, executor: Executor | str = Executor.BLENDER
                  ) -> AbstractContextManager[OperationHandle]:
        """:func:`~.operations.operation` de la operación nueva (en el hilo de Blender)."""
        return run_operation(self.project, self.op_type, executor=executor, **self.arguments())


class UnitStatus(StrEnum):
    """Cómo terminó una unidad de «Recalcular lo obsoleto»."""

    DONE = "done"  # recalculada: operaciones nuevas que sustituyen a las anteriores
    REFUSED = "refused"  # no se ejecutó: al empezar, sus entradas no seguían vigentes
    FAILED = "failed"  # su función de recálculo o su operación falló (o se canceló su trabajo)


@dataclass(frozen=True, slots=True)
class UnitResult:
    """Lo que pasó con una unidad: su estado, las operaciones nuevas hechas (en el orden de la
    unidad) y, si no se recalculó, el motivo (código del catálogo y sus valores)."""

    unit: RecomputeUnit
    status: UnitStatus
    operations: tuple[str, ...] = ()
    code: str | None = None
    values: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def reason(self) -> str | None:
        """El motivo en español (``None`` si se recalculó)."""
        return self.text()

    def text(self, *, language: str = "es") -> str | None:
        """El motivo en ``language`` (``None`` si se recalculó)."""
        if self.code is None:
            return None
        return render(self.code, language=language, **self.values)


@dataclass(frozen=True, slots=True)
class RecomputeOutcome:
    """El final de «Recalcular lo obsoleto»: cada unidad intentada, en orden; el plan de lo
    que queda (lo que sigue obsoleto, con lo que se deja fuera y su motivo); y si se canceló."""

    results: tuple[UnitResult, ...]
    remaining: RecomputePlan
    cancelled: bool = False


def recompute_steps(
    project: OperationProject,
    *,
    scope: Scope = SCOPE_ALL,
    versions: Mapping[str, str] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Iterator[Progress]:
    """Ejecuta «Recalcular lo obsoleto» en ``scope`` (como :func:`plan_recompute`) por
    unidades, en pasos que avanza el temporizador de ``bl`` (véase el módulo): cada paso
    ejecuta una unidad (o espera a su trabajo) y da un ``Progress`` (fase
    :data:`RECOMPUTE_PHASE`, unidades hechas de un total que se reajusta al volver a
    planificar); el último lleva el :class:`RecomputeOutcome`. ``cancelled()`` se consulta
    antes de cada unidad. Cerrar el generador a medias deja lo hecho.

    Al llamarla, sin escribir nada: ``ProvenanceError`` (``core.read_only``) en solo lectura;
    :class:`TypeError` o :class:`ValueError` con un ámbito que no vale."""
    _require_writable(project)
    with project.read() as conn:
        _planner, plan = _plan(load_graph(conn), scope, versions)
    return _steps(project, scope, versions, cancelled, len(plan.units))


def _steps(project: OperationProject, scope: Scope, versions: Mapping[str, str] | None,
           cancelled: Callable[[], bool] | None, total: int) -> Iterator[Progress]:
    yield Progress(RECOMPUTE_PHASE, 0, total, "Recalculando lo obsoleto…")
    results: list[UnitResult] = []
    blocked: set[str] = set()  # lo intentado y lo creado en esta ejecución
    stopped = False
    while project.writable:
        if cancelled is not None and cancelled():
            stopped = True
            break
        with project.read() as conn:
            graph = load_graph(conn)
            planner, plan = _plan(graph, scope, versions)
            held = planner.held(blocked)
            ready = [unit for unit in plan.units if planner.key_of(unit) not in held]
            if not ready:
                break
            unit = ready[0]
            group_uid = None if unit.group_uid is None else new_uid()
            built = [_request(conn, project, graph, uid, group_uid) for uid in unit.operations]
        total = len(results) + len(ready)
        result = _refusal(graph, unit, built)
        if result is None:
            result = yield from _execute(project, unit, [request for request, _ in built],
                                         len(results), total)
        results.append(result)
        blocked.update(unit.operations)
        blocked.update(result.operations)
        yield Progress(RECOMPUTE_PHASE, len(results), total,
                       f"Recalculando lo obsoleto ({len(results)} de {total})…")
    with project.read() as conn:
        remaining = _plan(load_graph(conn), scope, versions)[1]
    done = len(results)
    message = "Recalcular lo obsoleto: cancelado." if stopped else "Recalculado lo obsoleto."
    yield Progress(RECOMPUTE_PHASE, done, done, message,
                   RecomputeOutcome(tuple(results), remaining, stopped))


def _input_successor(conn: sqlite3.Connection, uid: str) -> str | None:
    """La entrada activa que sigue a ``uid``: ella misma si está activa; si está sustituida,
    la que la actualiza, y así hasta una activa; ``None`` si está descartada o no la hay."""
    seen: set[str] = set()
    current: str | None = uid
    while current is not None and current not in seen:
        seen.add(current)
        row = conn.execute("SELECT status FROM gb_input WHERE uid = ?", (current,)).fetchone()
        if row is None or row[0] == DISCARDED_INPUT:
            return None
        if row[0] not in INACTIVE_INPUTS:
            return current
        following = conn.execute(
            "SELECT uid FROM gb_input WHERE previous_uid = ? ORDER BY fid DESC LIMIT 1",
            (current,),
        ).fetchone()
        current = None if following is None else str(following[0])
    return None


def _request(conn: sqlite3.Connection, project: OperationProject, graph: ProvenanceGraph,
             uid: str, group_uid: str | None) -> tuple[RecomputeRequest, str | None]:
    """La petición de recálculo de la operación ``uid`` y, si consumió algo descartado sin
    sucesor, su nombre."""
    node = graph.operations[uid]
    (settings,) = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?",
                               (uid,)).fetchone()
    uses: list[Use] = []
    dropped: str | None = None
    for version in node.consumed:
        known: Any
        if version.item_kind == DATASET:
            record = dataset_registry.successor(conn, version.uid)
            use = None if record is None else Use(record.uid, version.role)
            known = graph.datasets.get(version.uid)
        else:
            following = _input_successor(conn, version.uid)
            use = None if following is None else Use(following, version.role,
                                                     kind=ItemKind.INPUT)
            known = graph.inputs.get(version.uid)
        if use is None:
            dropped = dropped or (version.uid if known is None else known.name)
        elif use not in uses:
            uses.append(use)
    request = RecomputeRequest(
        project, uid, node.op_type, MappingProxyType(json.loads(settings)), tuple(uses),
        tuple(dict.fromkeys(param.key for param in node.params)), group_uid,
    )
    return request, dropped


def _changed_upstream(graph: ProvenanceGraph, uses: Iterable[Use]) -> str | None:
    """El nombre de la primera entrada cambiada sin decidir aguas arriba de ``uses`` (las
    que consume y las de lo que escribió el contenido vigente de lo que consume, hasta sus
    importaciones); ``None`` si no hay."""
    chosen = tuple(uses)
    datasets = [use.item for use in chosen if use.kind is ItemKind.DATASET]
    found = [use.item for use in chosen if use.kind is ItemKind.INPUT]
    seen: set[str] = set()
    visited: set[str] = set()
    while datasets:
        uid = datasets.pop()
        node = graph.datasets.get(uid)
        if uid in seen or node is None:
            continue
        seen.add(uid)
        if node.input_uid is not None:
            found.append(node.input_uid)
        writer = graph.operations.get(node.operation_uid)
        if writer is None or writer.uid in visited:
            continue
        visited.add(writer.uid)
        for version in writer.consumed:
            (datasets if version.item_kind == DATASET else found).append(version.uid)
    for uid in dict.fromkeys(found):
        entry = graph.inputs.get(uid)
        if entry is not None and entry.status == CHANGED_INPUT:
            return entry.name
    return None


def _refusal(graph: ProvenanceGraph, unit: RecomputeUnit,
             built: list[tuple[RecomputeRequest, str | None]]) -> UnitResult | None:
    """Si la unidad no se ejecuta al empezar (sus entradas ya no siguen vigentes), su
    resultado con el motivo; si se ejecuta, ``None``."""
    for _request_item, dropped in built:
        if dropped is not None:
            return UnitResult(unit, UnitStatus.REFUSED, (), "core.recompute_no_successor",
                              MappingProxyType({"name": dropped}))
    for request, _dropped in built:
        for use in request.inputs:
            node = graph.datasets.get(use.item) if use.kind is ItemKind.DATASET else None
            if node is not None and node.status in DATASET_STATUS_CAUSES:
                return UnitResult(unit, UnitStatus.REFUSED, (),
                                  "core.recompute_dataset_unusable",
                                  MappingProxyType({"name": node.name}))
        changed = _changed_upstream(graph, request.inputs)
        if changed is not None:
            return UnitResult(unit, UnitStatus.REFUSED, (), "core.recompute_input_changed",
                              MappingProxyType({"name": changed}))
    return None


def _error_text(error: Exception) -> str:
    """El motivo de un fallo de la función de recálculo: el texto de un error para el usuario
    o la clase y el texto de otro, sin rutas absolutas."""
    if isinstance(error, GeoblenderError):
        return _clean(str(error))
    text = str(error).strip()
    return _clean(f"{type(error).__name__}: {text}" if text else type(error).__name__)


def _failed(unit: RecomputeUnit, created: list[str], op_type: str, reason: str) -> UnitResult:
    return UnitResult(unit, UnitStatus.FAILED, tuple(created), "core.recompute_failed",
                      MappingProxyType({"op_type": op_type, "reason": reason}))


def _operation_state(project: OperationProject, uid: str) -> tuple[str, str | None, str | None]:
    """El estado, el motivo y a quién sustituye la operación ``uid``."""
    with project.read() as conn:
        row = conn.execute("SELECT status, status_reason, supersedes_uid FROM gb_operation "
                           "WHERE uid = ?", (uid,)).fetchone()
    if row is None:
        raise ValueError(f"la función de recálculo devolvió la operación {uid}, que no está en "
                         "el proyecto")
    return str(row[0]), row[1], row[2]


def _execute(project: OperationProject, unit: RecomputeUnit, requests: list[RecomputeRequest],
             done: int, total: int) -> Generator[Progress, None, UnitResult]:
    """Repite las operaciones de ``unit`` en su orden con la función de recálculo de su tipo;
    mientras la operación nueva sigue en curso (un trabajo), da un paso de espera."""
    created: list[str] = []
    for request in requests:
        try:
            function = operation_def(request.op_type).recompute
            if function is None:  # una que no se repite sola no llega al plan
                raise ValueError(f"la operación «{request.op_type}» no tiene función de "
                                 "recálculo")
            handle = function(request)
        except Exception as error:  # el fallo del módulo deja la unidad fallida
            return _failed(unit, created, request.op_type, _error_text(error))
        uid = getattr(handle, "uid", None)
        if not isinstance(uid, str):
            raise TypeError(f"la función de recálculo de «{request.op_type}» devuelve la "
                            f"operación nueva (su OperationHandle), no {handle!r}")
        while True:
            status, reason, supersedes = _operation_state(project, uid)
            if status != OperationStatus.RUNNING:
                break
            yield Progress(RECOMPUTE_PHASE, done, total, f"Esperando a «{request.op_type}»…")
        if supersedes != request.operation_uid:
            raise ValueError(f"la operación nueva de «{request.op_type}» ({uid}) no sustituye a "
                             f"la que se recalcula ({request.operation_uid}): empiécela con "
                             "RecomputeRequest.begin u .operation")
        if status != OperationStatus.DONE:
            return _failed(unit, created, request.op_type, reason or status)
        created.append(uid)
    return UnitResult(unit, UnitStatus.DONE, tuple(created))


# --- Dar por buena (RF-008-27; D8) ------------------------------------------------------------


def accept_review(project: OperationProject, op_uid: str, reason: str) -> str:
    """«Dar por buena», con ``reason``, la operación ``op_uid``, que espera revisión a mano
    (véase el módulo), en una transacción; devuelve el uid de la operación
    ``core.accept_review`` que la sustituye.

    Rechazos, sin escribir nada (``ProvenanceError``): ``core.read_only``,
    ``core.operation_unknown``, ``core.accept_review_reason_missing`` (motivo vacío),
    ``core.accept_review_not_review`` (no espera revisión), ``core.accept_review_imported``
    (escribió lo importado de una entrada), ``core.accept_review_output`` (un dato suyo falta,
    está bloqueado o dañado), ``core.accept_review_upstream`` (lo que consume sigue obsoleto),
    ``core.accept_review_changed`` (su dato ya no tiene el contenido que escribió) y los de
    sus cifras; :class:`TypeError` si ``op_uid`` o ``reason`` no son textos."""
    if not isinstance(op_uid, str):
        raise TypeError(f"una operación se indica por su uid, no {op_uid!r}")
    if not isinstance(reason, str):
        raise TypeError(f"el motivo de dar por buena una operación es un texto, no {reason!r}")
    _require_writable(project)
    with project.write_transaction() as conn:
        graph = load_graph(conn)
        node = graph.operations.get(op_uid)
        if node is None:
            raise ProvenanceError("core.operation_unknown", operation=op_uid,
                                  project=project.name)
        if not reason.strip():
            raise ProvenanceError("core.accept_review_reason_missing", op_type=node.op_type)
        text = _clean(reason.strip())
        state = deduce(graph)
        if op_uid not in state.review:
            raise ProvenanceError("core.accept_review_not_review", op_type=node.op_type,
                                  operation=op_uid)
        outputs = _accepted_outputs(conn, graph, node)
        uses = _accepted_uses(conn, state, node, {uid for uid, _spec, _sha in outputs})
        handle = begin_in_transaction(
            conn, project, ACCEPT_REVIEW, settings={"accepted": op_uid, "reason": text},
            inputs=uses, params=tuple(dict.fromkeys(use.key for use in node.params)),
            executor=Executor.BLENDER, supersedes=op_uid,
        )
        records = handle.complete(conn, outputs=[spec for _uid, spec, _sha in outputs],
                                  figures=_accepted_figures(conn, state, node))
        for record, (_uid, _spec, expected) in zip(records, outputs, strict=True):
            if record.content_sha256 != expected:
                raise ProvenanceError("core.accept_review_changed", name=record.name,
                                      op_type=node.op_type)
        _record(conn, project, "REVIEW_ACCEPTED", op_uid,
                f"Operación «{node.op_type}» dada por buena: {text}",
                {"op_type": node.op_type, "accepted_by": handle.uid, "reason": text},
                format_utc(project.clock.now()))
    return handle.uid


def _accepted_outputs(conn: sqlite3.Connection, graph: ProvenanceGraph,
                      node: OperationNode) -> list[tuple[str, DatasetSpec, str]]:
    """Los datos vivos cuyo contenido vigente escribió la operación ``node``, como salidas de
    la que la da por buena (uid, ``DatasetSpec`` y el hash que tiene que dar)."""
    found: list[tuple[str, DatasetSpec, str]] = []
    for dataset in sorted(graph.datasets.values(), key=lambda item: item.fid):
        if not dataset.live or dataset.operation_uid != node.uid:
            continue
        record = dataset_registry.get(conn, dataset.uid)
        if record is None:  # pragma: no cover - el grafo y la base son la misma instantánea
            continue
        if record.immutable:
            entry = graph.inputs.get(str(record.input_uid))
            raise ProvenanceError("core.accept_review_imported", op_type=node.op_type,
                                  name=record.input_uid if entry is None else entry.name)
        if record.status is not DatasetStatus.CURRENT:
            raise ProvenanceError("core.accept_review_output", name=record.name,
                                  op_type=node.op_type)
        roles = [version.role for version in node.produced
                 if version.item_kind == DATASET and version.uid == record.uid]
        spec = DatasetSpec(
            record.name, record.module, record.kind, record.store, record.locator,
            reader=record.reader, role=roles[-1], selector=record.selector,
            crs_epsg=record.crs_epsg, input_uid=record.input_uid,
            qgis_editable=record.qgis_editable,
        )
        found.append((record.uid, spec, record.content_sha256))
    return found


def _accepted_uses(conn: sqlite3.Connection, state: Staleness, node: OperationNode,
                   own: set[str]) -> tuple[Use, ...]:
    """Lo que consume la que da por buena a ``node``: las versiones vigentes de lo que
    consumió (sin lo que ella misma escribió y da por bueno, ni lo descartado sin sucesor).
    ``core.accept_review_upstream`` si algo de ello sigue obsoleto (nacería obsoleta)."""
    uses: list[Use] = []
    stale: list[str] = []
    for version in node.consumed:
        if version.item_kind == DATASET:
            if version.uid in own:
                continue
            record = dataset_registry.successor(conn, version.uid)
            if record is None:
                continue
            if record.status in DATASET_STATUS_CAUSES or record.uid in state.datasets:
                stale.append(record.name)
            use = Use(record.uid, version.role)
        else:
            following = _input_successor(conn, version.uid)
            if following is None:
                continue
            use = Use(following, version.role, kind=ItemKind.INPUT)
        if use not in uses:
            uses.append(use)
    if stale:
        names = ", ".join(f"«{name}»" for name in dict.fromkeys(stale))
        raise ProvenanceError("core.accept_review_upstream", op_type=node.op_type, names=names)
    return tuple(uses)


def _accepted_figures(conn: sqlite3.Connection, state: Staleness,
                      node: OperationNode) -> list[FigureSpec]:
    """Las cifras vigentes de la operación ``node``, que vuelve a dar la que la da por buena
    (las demás quedan como historia)."""
    graph = state.graph
    current = set(state.current_figures.values())
    uids = [figure.uid for figure in graph.figures
            if figure.operation_uid == node.uid and figure.uid in current]
    if not uids:
        return []
    marks = ", ".join("?" for _ in uids)
    specs: list[FigureSpec] = []
    for row in conn.execute(f"SELECT {FIGURE_COLUMNS} FROM gb_figure WHERE uid IN ({marks}) "
                            "ORDER BY fid", uids):
        record = FigureRecord.from_row(row)
        parameter = (None if record.parameter_uid is None
                     else graph.parameters.get(record.parameter_uid))
        specs.append(FigureSpec(record.key, record.value, record.unit, kind=record.kind,
                                scope=dict(record.scope),
                                parameter_key=None if parameter is None else parameter.key))
    return specs
