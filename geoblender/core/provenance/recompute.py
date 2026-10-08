# SPDX-License-Identifier: GPL-3.0-or-later
"""Plan de «Recalcular lo obsoleto» (spec 008; RF-008-25, RF-008-26, RF-008-27; ADR-0025 §5;
plan 008 §5.1, §5.3.1 y §5.4.4).

:func:`plan_recompute` decide, sobre el grafo de la procedencia (:mod:`.graph`) y su
obsolescencia deducida, **qué** se recalcula y **en qué orden**. No ejecuta ni escribe nada:
ejecutar el plan por unidades y «dar por buena» llegan con T29. Nada se recalcula sin que el
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

Python puro (ADR-0004).
"""

from __future__ import annotations

import heapq
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import NamedTuple

from .contract import GROUPS, parse_version
from .graph import DATASET, Cause, OperationNode, ProvenanceGraph, Staleness, deduce
from .messages import render

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
    targets = _targets(graph, scope)
    planner = _Planner(deduce(graph, versions=versions))
    if isinstance(scope, Cause):
        wanted = {uid for uid in planner.relevant if scope in planner.stale[uid]}
    elif targets is None:
        wanted = set(planner.relevant)
    else:
        wanted = planner.upstream_of(targets) & planner.relevant
    return planner.plan(scope, wanted)


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
