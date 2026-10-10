# SPDX-License-Identifier: GPL-3.0-or-later
"""Puerta antes de operar (spec 008; RF-008-09, RF-008-10, RF-008-12, RF-008-21, RF-008-56,
RF-008-57, RF-008-58; ADR-0025 §5 y §6; plan 008 §5.3.1, §5.4.2, §5.4.5 y §5.4.9).

:func:`can_run` dice, antes de empezar una operación con lo que va a consumir, si se puede
ejecutar (:class:`Ready`), si se niega y por qué (:class:`Blocked`) o si hay que esperar
(:class:`Pending`). La llama ``bl`` antes de ``begin_operation`` (``ensure_ready``, T48, con el
diálogo de una entrada cambiada) y se puede repetir: lo que registra, ya registrado, no vuelve
a escribirse.

1. **La cadena**: recorre aguas arriba lo que consume —los datos, quien escribió su contenido
   actual y lo que esa operación consumió, hasta las importaciones— y reúne sus datos y sus
   entradas activas (también las de un dato acumulado de una tabla común).
2. **Lo aún sin comprobar** (RF-008-58): lo que la comprobación de apertura no ha comprobado
   todavía (:class:`CheckState`) o cuyo hash largo ya está pedido no se comprueba aquí: la
   puerta espera («Comprobando el proyecto…: espere a que termine»).
3. **Prefiltro y hash de lo demás** (RF-008-09, RF-008-21; I-4): de cada dato seguido de la
   cadena, su ``last_change``, el SQL y los disparadores de su tabla o el tamaño y la fecha de
   su fichero (``core.datasets.external``); de cada entrada, el tamaño y la fecha de su fuente
   (``core.inputs.check.probe_input``). Lo que salta se hashea en el hilo con su lector y su
   normalizador mientras quede tiempo de la puerta (:data:`HASH_LIMIT_S`); lo que no cabe (o
   una fuente externa que su lector estima en más) queda pedido a :class:`CheckState` y la
   puerta devuelve «pendiente» (:class:`PendingReason.HASHING`).
4. **Registro antes de operar**: una entrada con otro contenido queda «cambiada» (o vuelve a
   «vigente»), y un dato, con su edición externa (``core.external_edit``), «falta» o «dañado»;
   lo que depende de él queda obsoleto en la caché y la operación lo ve (:attr:`Ready.stale`).
   En **solo lectura** se detecta igual sin escribir nada, y la operación se niega.
5. **Se niega** (:class:`Blocked`, con un :class:`BlockReason` por motivo) con una entrada
   cambiada sin decidir en la cadena —el aviso de la spec §8 y sus tres salidas, Actualizar,
   Mantener la copia y Cancelar (RF-008-10)— y con un dato que consume directamente que falta
   (RF-008-57), está bloqueado (RF-008-56, con el texto de la spec §8) o dañado, o que no se
   puede leer para comprobarlo. «Cambiada · se mantiene la copia» se ejecuta (RF-008-12).

Lo que se registró o no se pudo comprobar va en los avisos (:class:`Notice`). Python puro
(ADR-0004).
"""

from __future__ import annotations

import sqlite3
import time
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from ..content.readers import INLINE_LIMIT_S, JOB, READERS, ReadCancelled, plan_hash, read_steps
from ..content.readers import reader as content_reader
from ..datasets import external
from ..datasets import registry as dataset_registry
from ..datasets.model import DatasetRecord, DatasetStatus, Store
from ..datasets.tracking import table_states
from ..errors import GeoblenderError
from ..inputs import registry as input_registry
from ..inputs.check import (
    CheckMode,
    InputFinding,
    Probe,
    Verdict,
    assess,
    dependents,
    probe_input,
    record_findings,
    table_changes,
)
from ..inputs.model import FileAnchor, InputRecord, InputStatus
from .contract import operation_def
from .messages import render
from .operations import (
    READ_ONLY_PREFIX,
    Consumed,
    ItemKind,
    _clean,
    _require_writable,
    _resolve_use,
    _uses,
)

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo
    from ..timeutil import Clock
    from ..userdata import UserData

HASH_LIMIT_S = INLINE_LIMIT_S
"""El tiempo que puede pasar la puerta hasheando en el hilo lo que saltó (plan §5.4.5: «si
cabe en ≤ 1 s»); lo demás queda pedido y la puerta devuelve «pendiente»."""

_WRITERS_OF = (
    "SELECT operation_uid FROM gb_operation_io WHERE item_uid = ? AND direction = 'out' "
    "ORDER BY fid"
)
"""Las operaciones que escribieron alguna versión de un dato (por ellas, las entradas cuya
importación escribió un dato acumulado)."""
_CONSUMED_BY = (
    "SELECT item_kind, item_uid, content_sha256 FROM gb_operation_io WHERE operation_uid = ? "
    "AND direction = 'in' ORDER BY fid"
)
_PRODUCERS = (
    "SELECT io.operation_uid FROM gb_operation_io AS io JOIN gb_operation AS o "
    "ON o.uid = io.operation_uid WHERE io.item_uid = ? AND io.content_sha256 = ? "
    "AND io.direction = 'out' AND o.status = 'done' ORDER BY io.fid"
)
"""Las operaciones hechas que escribieron una versión (dato, hash) de un dato."""
_UNUSABLE: Mapping[DatasetStatus, tuple[str, str]] = MappingProxyType({
    DatasetStatus.MISSING: ("dataset_missing", "core.dataset_missing"),
    DatasetStatus.BLOCKED: ("dataset_blocked", "core.dataset_blocked"),
    DatasetStatus.DAMAGED: ("dataset_damaged", "core.dataset_damaged"),
})


class GateProject(Protocol):
    """Lo que la puerta usa del proyecto (``core.project.Project``): lo de las operaciones
    (``OperationProject``) y sus datos de usuario (las fuentes de las entradas, RF-002-19)."""

    @property
    def uid(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def root(self) -> Path: ...

    @property
    def database_path(self) -> Path: ...

    @property
    def userdata(self) -> UserData: ...

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


# --- Lo que responde la puerta -----------------------------------------------------------------


class Choice(StrEnum):
    """Las tres salidas del aviso de una entrada cambiada (RF-008-10)."""

    UPDATE = "update"  # Actualizar: reimportarla (RF-008-11)
    KEEP = "keep"  # Mantener la copia (RF-008-12)
    CANCEL = "cancel"  # Cancelar: la operación no se ejecuta


CHANGED_INPUT_CHOICES: tuple[Choice, ...] = (Choice.UPDATE, Choice.KEEP, Choice.CANCEL)
"""Las salidas de una entrada cambiada, en su orden."""


def choice_label(choice: Choice | str, language: str = "es") -> str:
    """El texto de una salida en ``language`` («Actualizar», «Mantener la copia»,
    «Cancelar»)."""
    return render(f"core.choice_{Choice(choice)}", language=language)


class BlockKind(StrEnum):
    """Por qué se niega una operación."""

    READ_ONLY = "read_only"  # el proyecto está en solo lectura
    INPUT_CHANGED = "input_changed"  # una entrada cambiada sin decidir en la cadena (RF-008-10)
    DATASET_MISSING = "dataset_missing"  # consume un dato que falta (RF-008-57)
    DATASET_BLOCKED = "dataset_blocked"  # consume un dato bloqueado (RF-008-56)
    DATASET_DAMAGED = "dataset_damaged"  # consume lo importado dañado (ADR-0025 §4)
    DATASET_UNREADABLE = "dataset_unreadable"  # consume un dato que no se puede comprobar


class PendingReason(StrEnum):
    """Por qué hay que esperar a algo de la cadena (RF-008-58)."""

    CHECKING = "checking"  # la comprobación de apertura aún no lo ha comprobado
    HASHING = "hashing"  # su hash no cabe en la puerta: está pedido


@dataclass(frozen=True, slots=True)
class PendingItem:
    """Algo de la cadena a lo que hay que esperar: un dato o una entrada, su uid, su nombre y
    por qué."""

    item_kind: ItemKind
    uid: str
    name: str
    reason: PendingReason


@dataclass(frozen=True, slots=True)
class Notice:
    """Un aviso de la puerta: lo que registró (una edición externa, lo que falta, lo dañado)
    o no pudo comprobar (una fuente no localizable o que no se puede leer), con su mensaje
    (``core.provenance.messages``) y sus valores."""

    code: str
    values: Mapping[str, Any]

    def text(self, language: str = "es") -> str:
        """El aviso en ``language``."""
        return render(self.code, language=language, **self.values)


@dataclass(frozen=True, slots=True)
class BlockReason:
    """Un motivo para negar la operación: su clase, el dato o la entrada (``item_kind``,
    ``uid`` y ``name``; el proyecto, en solo lectura), su mensaje y sus valores, las salidas que
    se ofrecen (las tres de una entrada cambiada) y, de una entrada cambiada, lo encontrado
    (su aviso de la spec §8 en cualquier idioma)."""

    kind: BlockKind
    item_kind: ItemKind | None
    uid: str | None
    name: str
    code: str
    values: Mapping[str, Any]
    choices: tuple[Choice, ...] = ()
    finding: InputFinding | None = None

    def text(self, language: str = "es") -> str:
        """El motivo como lo lee una persona, en ``language``."""
        if self.finding is not None:
            return self.finding.render(language) or ""
        return render(self.code, language=language, **self.values)


@dataclass(frozen=True, slots=True)
class Ready:
    """Se puede ejecutar. ``notices``: lo que la puerta registró o no pudo comprobar;
    ``stale``: los datos que consume que están obsoletos (la operación los ve así)."""

    notices: tuple[Notice, ...] = ()
    stale: tuple[str, ...] = ()

    def text(self, language: str = "es") -> str:
        """Los avisos, uno por línea."""
        return "\n".join(notice.text(language) for notice in self.notices)


@dataclass(frozen=True, slots=True)
class Blocked:
    """Se niega, con sus motivos (en orden: solo lectura, entradas, datos) y los avisos."""

    reasons: tuple[BlockReason, ...]
    notices: tuple[Notice, ...] = ()

    def text(self, language: str = "es") -> str:
        """Los motivos, uno por línea."""
        return "\n".join(reason.text(language) for reason in self.reasons)


@dataclass(frozen=True, slots=True)
class Pending:
    """Hay que esperar a lo de ``items`` (la orden se puede repetir al terminar), con los
    avisos."""

    items: tuple[PendingItem, ...]
    notices: tuple[Notice, ...] = ()

    def text(self, language: str = "es") -> str:
        """«Comprobando el proyecto…: espere a que termine (…)» y, si un hash es largo,
        «Comprobando el contenido de …: espere a que termine y repita la orden.»"""
        parts: list[str] = []
        for reason, code in ((PendingReason.CHECKING, "core.gate_checking"),
                             (PendingReason.HASHING, "core.gate_hashing")):
            found = [item for item in self.items if item.reason is reason]
            if found:
                names = ", ".join(f"«{item.name}»" for item in found)
                parts.append(render(code, language=language, names=names))
        return " ".join(parts)


type GateResult = Ready | Blocked | Pending
"""Lo que responde :func:`can_run`."""


# --- Lo que la comprobación de apertura aún no ha comprobado -----------------------------------


class CheckState:
    """Lo que la comprobación de apertura (RF-008-58) aún no ha comprobado y los hashes largos
    que pidió la puerta. La tiene ``bl`` por proyecto abierto y la avanzan sus pasos (T36,
    T37), en el hilo de Blender:

    - :meth:`start`: empieza; sin listas, todo queda pendiente (antes de la foto del paso 1);
      con ellas, solo lo de cada lista (``None``: todo lo de esa clase);
    - :meth:`checked`: lo ya comprobado deja de estar pendiente; :meth:`finish`: nada;
    - :meth:`request_hash` (lo usa la puerta), :attr:`requests` y :meth:`hashed`: los hashes
      pedidos, que la cola de hashes calcula y registra (T37) y, al terminar, quita."""

    def __init__(self) -> None:
        self._all: set[ItemKind] = set()
        self._items: dict[ItemKind, set[str]] = {kind: set() for kind in ItemKind}
        self._requests: dict[tuple[ItemKind, str], PendingItem] = {}

    def __repr__(self) -> str:
        return (f"<CheckState running={self.running} "
                f"requests={len(self._requests)}>")

    @property
    def running(self) -> bool:
        """Si la comprobación de apertura tiene algo pendiente."""
        return bool(self._all) or any(self._items.values())

    def start(self, *, inputs: Iterable[str] | None = None,
              datasets: Iterable[str] | None = None) -> None:
        """Empieza (o vuelve a empezar) la comprobación de apertura con lo pendiente: los uid
        de las entradas y de los datos que comprobará (``None``: todos los de esa clase)."""
        self._all = set()
        for kind, chosen in ((ItemKind.INPUT, inputs), (ItemKind.DATASET, datasets)):
            if chosen is None:
                self._all.add(kind)
                self._items[kind] = set()
            else:
                self._items[kind] = set(_uids(chosen))

    def checked(self, *, inputs: Iterable[str] = (), datasets: Iterable[str] = ()) -> None:
        """Lo ya comprobado (por uid) deja de estar pendiente."""
        for kind, chosen in ((ItemKind.INPUT, inputs), (ItemKind.DATASET, datasets)):
            self._items[kind].difference_update(_uids(chosen))

    def finish(self) -> None:
        """Termina la comprobación de apertura: nada queda pendiente (los hashes pedidos
        siguen)."""
        self._all = set()
        for found in self._items.values():
            found.clear()

    def is_pending(self, item_kind: ItemKind | str, uid: str) -> bool:
        """Si la comprobación de apertura aún no ha comprobado el dato o la entrada ``uid``."""
        kind = ItemKind(item_kind)
        return kind in self._all or uid in self._items[kind]

    def request_hash(self, item: PendingItem) -> bool:
        """Pide el hash de ``item`` (una vez): dice si es nuevo."""
        if not isinstance(item, PendingItem):
            raise TypeError(f"se pide el hash de un PendingItem, no {item!r}")
        key = (item.item_kind, item.uid)
        if key in self._requests:
            return False
        self._requests[key] = item
        return True

    @property
    def requests(self) -> tuple[PendingItem, ...]:
        """Los hashes pedidos, en el orden en que se pidieron."""
        return tuple(self._requests.values())

    def awaiting(self, item_kind: ItemKind | str, uid: str) -> bool:
        """Si el hash del dato o la entrada ``uid`` está pedido."""
        return (ItemKind(item_kind), uid) in self._requests

    def hashed(self, item_kind: ItemKind | str, uid: str) -> None:
        """El hash pedido de ``uid`` ya se calculó y se registró: deja de esperarse."""
        self._requests.pop((ItemKind(item_kind), uid), None)


def _uids(chosen: Iterable[str]) -> list[str]:
    if isinstance(chosen, str) or not isinstance(chosen, Iterable):
        raise TypeError(f"se esperaba una lista de uid, no {chosen!r}")
    found = list(chosen)
    for uid in found:
        if not isinstance(uid, str):
            raise TypeError(f"un dato o una entrada se indica por su uid, no {uid!r}")
    return found


# --- La puerta ---------------------------------------------------------------------------------


def can_run(project: GateProject, op_type: str, inputs: Sequence[Any], *,
            pending: CheckState) -> GateResult:
    """La puerta antes de ejecutar una operación de tipo ``op_type`` que consume ``inputs``
    (``Use``, como ``begin_operation``) con lo que la comprobación de apertura aún no ha
    comprobado (``pending``); véase el módulo.

    Registra en el proyecto, cada cosa en su transacción, lo que encuentra (entradas
    cambiadas, ediciones externas, lo que falta y lo dañado); en solo lectura no escribe nada.
    ``ProvenanceError`` como ``begin_operation`` si el tipo no está registrado, si lo que
    consume no está (o no está vivo) o si el proyecto está cerrado; :class:`TypeError` si
    ``inputs`` no son ``Use`` o ``pending`` no es un :class:`CheckState`."""
    if not isinstance(pending, CheckState):
        raise TypeError(f"la puerta recibe lo pendiente de la comprobación de apertura "
                        f"(CheckState), no {pending!r}")
    definition = operation_def(op_type)
    uses = _uses(inputs)
    if project.closed:
        _require_writable(project)
    with project.read() as conn:
        consumed = tuple(_resolve_use(conn, definition, use) for use in uses)
    return _Gate(project, pending, consumed).run()


class _Gate:
    """Una pasada de la puerta: la cadena, lo que se espera, lo encontrado y los avisos."""

    def __init__(self, project: GateProject, pending: CheckState,
                 consumed: tuple[Consumed, ...]) -> None:
        self.project = project
        self.pending = pending
        self.consumed = consumed
        self.writable = bool(project.writable)
        self.deadline = time.perf_counter() + HASH_LIMIT_S
        self.datasets: dict[str, DatasetRecord] = {}
        self.inputs: dict[str, InputRecord] = {}
        self.waits: dict[tuple[ItemKind, str], PendingItem] = {}
        self.notices: list[Notice] = []
        self.dataset_status: dict[str, DatasetStatus] = {}
        self.unreadable: dict[str, str] = {}
        self.input_findings: dict[str, InputFinding] = {}
        self.input_probes: dict[str, Probe] = {}

    # --- Tiempo y esperas ------------------------------------------------------------------

    def remaining(self) -> float:
        return self.deadline - time.perf_counter()

    def late(self) -> bool:
        return self.remaining() <= 0.0

    def wait(self, item_kind: ItemKind, uid: str, name: str, reason: PendingReason) -> None:
        item = PendingItem(item_kind, uid, name, reason)
        self.waits.setdefault((item_kind, uid), item)
        if reason is PendingReason.HASHING:
            self.pending.request_hash(item)

    def waiting(self, item_kind: ItemKind, uid: str, name: str) -> bool:
        """Si hay que esperar a ``uid`` sin comprobarlo aquí (paso 2 del módulo)."""
        if self.pending.is_pending(item_kind, uid):
            self.wait(item_kind, uid, name, PendingReason.CHECKING)
            return True
        if self.pending.awaiting(item_kind, uid):
            self.wait(item_kind, uid, name, PendingReason.HASHING)
            return True
        return False

    # --- La cadena -------------------------------------------------------------------------

    def walk(self, conn: sqlite3.Connection) -> None:
        """Los datos y las entradas activas de la cadena aguas arriba de lo consumido (paso 1
        del módulo), en el orden en que se encuentran: de cada dato, la operación que escribió
        su contenido actual, y de cada versión que consumió una operación, las que la
        escribieron (una edición externa consume el mismo dato: por su versión anterior se
        sigue hasta lo que la calculó)."""
        found_inputs = [item.uid for item in self.consumed if item.kind is ItemKind.INPUT]
        operations: deque[str] = deque()
        visited: set[str] = set()
        imports = {str(operation): str(uid) for operation, uid in conn.execute(
            "SELECT operation_uid, uid FROM gb_input ORDER BY fid")}

        def add_dataset(uid: str) -> None:
            if uid in self.datasets:
                return
            record = dataset_registry.get(conn, uid)
            if record is None or record.uid != uid:
                return
            self.datasets[uid] = record
            # Lo importado y el acumulado de una tabla común los escribió la importación de
            # sus entradas.
            for (writer,) in conn.execute(_WRITERS_OF, (uid,)).fetchall():
                if writer in imports:
                    found_inputs.append(imports[writer])
            operations.append(record.operation_uid)

        for item in self.consumed:
            if item.kind is ItemKind.DATASET:
                add_dataset(item.uid)
        while operations:
            operation_uid = operations.popleft()
            if operation_uid in visited:
                continue
            visited.add(operation_uid)
            for kind, uid, sha in conn.execute(_CONSUMED_BY, (operation_uid,)).fetchall():
                if kind != ItemKind.DATASET:
                    found_inputs.append(str(uid))
                    continue
                add_dataset(str(uid))
                operations.extend(str(row[0]) for row in conn.execute(_PRODUCERS, (uid, sha)))
        for uid in dict.fromkeys(found_inputs):
            entry = input_registry.get(conn, uid)
            if entry is not None and entry.uid == uid and entry.active:
                self.inputs[uid] = entry

    # --- Paso a paso -----------------------------------------------------------------------

    def run(self) -> GateResult:
        with self.project.read() as conn:
            self.walk(conn)
            locators = [record.locator for record in self.datasets.values()
                        if record.store is Store.GPKG and external.checkable(record)]
            tables = table_states(conn, locators) if locators else {}
            changes = (table_changes(conn) if any(
                item.anchor is FileAnchor.PROJECT_TABLE
                for entry in self.inputs.values() for item in entry.files
            ) else None)
        for record in list(self.datasets.values()):
            if not external.checkable(record):
                continue
            if self.waiting(ItemKind.DATASET, record.uid, record.name):
                continue
            probe = external.probe_dataset(self.project, record, tables)
            if probe.signal is not external.Signal.UNCHANGED:
                self.settle_dataset(probe)
        for entry in list(self.inputs.values()):
            if self.waiting(ItemKind.INPUT, entry.uid, entry.name):
                continue
            probe = probe_input(self.project, entry, mode=CheckMode.QUICK, tables=changes)
            self.input_probes[entry.uid] = probe
            if probe.missing is not None:
                self.input_notice(assess(probe))
            elif probe.needs_hash:
                self.settle_input(probe)
        return self.result()

    # --- Datos -----------------------------------------------------------------------------

    def fits(self, probe: external.DatasetProbe) -> bool:
        """Si el hash del dato puede caber en lo que queda de la puerta: su lector (de un
        fichero) no estima más."""
        remaining = self.remaining()
        if remaining <= 0.0:
            return False
        found = READERS.get(probe.record.reader)
        if probe.size is None or found is None or found.estimate_s is None:
            return True
        estimate = found.estimate_s(probe.size)
        return estimate is None or estimate <= remaining

    def settle_dataset(self, probe: external.DatasetProbe) -> None:
        """El hash y el registro de un dato que saltó (pasos 3 y 4 del módulo), en una
        transacción de escritura en la que se vuelve a mirar (o en una lectura, en solo
        lectura)."""
        record = probe.record
        if probe.needs_hash and not self.fits(probe):
            self.wait(ItemKind.DATASET, record.uid, record.name, PendingReason.HASHING)
            return
        opened = self.project.write_transaction() if self.writable else self.project.read()
        finding: external.DatasetFinding | None = None
        try:
            with opened as conn:
                current = dataset_registry.get(conn, record.uid)
                if current is None or not external.checkable(current):
                    return
                states = (table_states(conn, [current.locator])
                          if current.store is Store.GPKG else {})
                fresh = external.probe_dataset(self.project, current, states)
                digest = None
                if fresh.needs_hash:
                    try:
                        digest = external.content_digest(conn, self.project, current,
                                                         cancelled=self.late)
                    except ReadCancelled:
                        raise
                    except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
                        self.unreadable[current.uid] = _clean(str(exc))
                        return
                finding = external.assess(fresh, digest)
                if self.writable:
                    finding = external.record(conn, self.project, finding)
        except ReadCancelled:
            self.wait(ItemKind.DATASET, record.uid, record.name, PendingReason.HASHING)
            return
        if finding is None:  # pragma: no cover - se sale antes por cada camino sin veredicto
            return
        self.dataset_status[record.uid] = finding.status
        if finding.code is not None:
            entry = self.inputs.get(str(record.input_uid))
            self.notices.append(Notice(finding.code, MappingProxyType(
                finding.values(None if entry is None else entry.name))))

    # --- Entradas --------------------------------------------------------------------------

    def input_notice(self, finding: InputFinding) -> None:
        """El aviso de una fuente no localizable o que no se puede leer (RF-008-13): no es un
        cambio y se sigue con lo importado."""
        if finding.verdict is Verdict.UNREACHABLE:
            self.notices.append(Notice("core.input_unreachable", MappingProxyType(
                {"name": finding.name, "file": finding.file})))
        elif finding.verdict is Verdict.UNREADABLE:
            self.notices.append(Notice("core.input_unreadable", MappingProxyType(
                {"name": finding.name, "reader": finding.reader, "reason": finding.reason})))

    def settle_input(self, probe: Probe) -> None:
        """El hash y el registro de una entrada cuya fuente saltó (pasos 3 y 4 del módulo):
        en el hilo si cabe; si no (o si su lector la manda a un trabajo), pedido."""
        entry = probe.record
        try:
            found = content_reader(entry.reader)
            request = found.request(entry.kind, entry.declarations, probe.files,
                                    dict(entry.settings), normalizer=entry.normalizer)
        except (GeoblenderError, ValueError) as exc:
            self.input_notice(assess(probe, error=_clean(str(exc))))
            return
        size = sum(seen.size or 0 for seen in probe.observed)
        remaining = self.remaining()
        where = plan_hash(found, str(entry.files[0].anchor), size)
        estimate = None if found.estimate_s is None else found.estimate_s(size)
        if remaining <= 0.0 or where == JOB or (estimate is not None and estimate > remaining):
            self.wait(ItemKind.INPUT, entry.uid, entry.name, PendingReason.HASHING)
            return
        steps = read_steps(found, request)
        try:
            for _done in steps:
                if self.late():
                    self.wait(ItemKind.INPUT, entry.uid, entry.name, PendingReason.HASHING)
                    return
            finding = assess(probe, request.hasher.digest().content_sha256)
        except FileNotFoundError:
            gone = PurePosixPath(entry.files[0].path).name
            finding = assess(replace(probe, missing=gone))
        except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
            finding = assess(probe, error=_clean(str(exc)))
        finally:
            steps.close()
        if finding.verdict not in (Verdict.SAME, Verdict.CHANGED, Verdict.RESTORED):
            self.input_notice(finding)
            return
        if self.writable:
            with self.project.write_transaction() as conn:
                if finding.status is InputStatus.CHANGED:
                    finding = replace(finding, dependents=dependents(conn, entry))
                record_findings(conn, self.project, [finding])
        self.input_findings[entry.uid] = finding

    # --- Respuesta -------------------------------------------------------------------------

    def changed_reason(self, conn: sqlite3.Connection, entry: InputRecord) -> BlockReason:
        """El motivo de una entrada cambiada sin decidir: su aviso de la spec §8 (con lo que
        depende de ella ahora y la fecha de su fuente, si se vio) y sus tres salidas."""
        finding = self.input_findings.get(entry.uid)
        probe = self.input_probes.get(entry.uid)
        if finding is None or finding.status is not InputStatus.CHANGED:
            finding = InputFinding(
                input_uid=entry.uid, name=entry.name, verdict=Verdict.CHANGED,
                before=entry.status, status=InputStatus.CHANGED,
                registered_at=entry.registered_at, registered_sha256=entry.content_sha256,
                previous_seen=entry.seen_sha256, reader=entry.reader,
                content_sha256=entry.seen_sha256,
                observed=() if probe is None else probe.observed,
                source_date=None if probe is None else probe.source_date,
            )
        finding = replace(finding, dependents=dependents(conn, entry))
        return BlockReason(BlockKind.INPUT_CHANGED, ItemKind.INPUT, entry.uid, entry.name,
                           "core.input_changed", MappingProxyType({"name": entry.name}),
                           CHANGED_INPUT_CHOICES, finding)

    def dataset_reason(self, record: DatasetRecord) -> BlockReason | None:
        """El motivo de un dato consumido que no se puede usar, o ``None``."""
        if record.uid in self.unreadable:
            return BlockReason(BlockKind.DATASET_UNREADABLE, ItemKind.DATASET, record.uid,
                               record.name, "core.dataset_unreadable", MappingProxyType(
                                   {"name": record.name, "reason": self.unreadable[record.uid]}))
        status = self.dataset_status.get(record.uid, record.status)
        unusable = _UNUSABLE.get(status)
        if unusable is None:
            return None
        kind, code = unusable
        entry = self.inputs.get(str(record.input_uid))
        values = {"name": record.name, "locator": record.locator,
                  "input": record.input_uid if entry is None else entry.name}
        return BlockReason(BlockKind(kind), ItemKind.DATASET, record.uid, record.name, code,
                           MappingProxyType(values))

    def result(self) -> GateResult:
        reasons: list[BlockReason] = []
        if not self.writable:
            reasons.append(BlockReason(
                BlockKind.READ_ONLY, None, None, self.project.name, "core.read_only",
                MappingProxyType({"project": self.project.name,
                                  "reason": str(self.project.status.message)
                                  .removeprefix(READ_ONLY_PREFIX)}),
            ))
        consumed = list(dict.fromkeys(item.uid for item in self.consumed
                                      if item.kind is ItemKind.DATASET))
        with self.project.read() as conn:
            for uid in self.inputs:
                entry = input_registry.get(conn, uid)
                if entry is None:  # pragma: no cover - una entrada no se borra
                    continue
                finding = self.input_findings.get(uid)
                status = entry.status if self.writable or finding is None else finding.status
                if status is InputStatus.CHANGED:
                    reasons.append(self.changed_reason(conn, entry))
            for uid in consumed:
                record = dataset_registry.get(conn, uid)
                reason = None if record is None else self.dataset_reason(record)
                if reason is not None:
                    reasons.append(reason)
            stale = _stale(conn, consumed)
        notices = tuple(self.notices)
        if reasons:
            return Blocked(tuple(reasons), notices)
        if self.waits:
            return Pending(tuple(self.waits.values()), notices)
        names = [self.datasets[uid].name for uid in consumed if uid in stale]
        return Ready(notices, tuple(names))


def _stale(conn: sqlite3.Connection, uids: Sequence[str]) -> frozenset[str]:
    """Los datos de ``uids`` obsoletos según la caché (``gb_stale``)."""
    if not uids:
        return frozenset()
    marks = ", ".join("?" for _ in uids)
    return frozenset(str(row[0]) for row in conn.execute(
        f"SELECT DISTINCT item_uid FROM gb_stale WHERE item_kind = 'dataset' "
        f"AND item_uid IN ({marks})", tuple(uids)))


__all__ = [
    "CHANGED_INPUT_CHOICES",
    "HASH_LIMIT_S",
    "BlockKind",
    "BlockReason",
    "Blocked",
    "CheckState",
    "Choice",
    "GateProject",
    "GateResult",
    "Notice",
    "Pending",
    "PendingItem",
    "PendingReason",
    "Ready",
    "can_run",
    "choice_label",
]
