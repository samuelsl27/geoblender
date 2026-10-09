# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos del proyecto cambiados fuera de Geoblender (spec 008; RF-008-21, RF-008-52,
RF-008-53, RF-008-56, RF-008-57, RF-008-58; ADR-0025 §4 y §6; plan 008 §5.2.2, §5.3.1,
§5.4.2, §5.4.6 y §5.4.9).

Un dato del proyecto se comprueba en dos tiempos (ADR-0025 §6), por piezas que usan la puerta
antes de operar (``core.provenance.gate``, T30) y la comprobación de los datos del proyecto
(:func:`external_check_steps`):

1. **Prefiltro** (:func:`probe_dataset`), sin leer el contenido: de una tabla de
   ``project.gpkg``, su ``gpkg_contents.last_change``, la huella de su SQL y sus disparadores
   (:func:`~.tracking.table_states`) frente a lo anotado tras la última escritura de Geoblender
   (``tracked_*``); de un fichero, su tamaño y su fecha. Una tabla que ya no está (ni en
   ``sqlite_master`` ni en ``gpkg_contents``) o un fichero que no está **falta**; lo importado de
   una tabla sin sus disparadores de protección está **dañado** sin más (ADR-0025 §4). Un dato
   que faltaba y vuelve a estar se hashea siempre.
2. **Hash de contenido** de lo que salta (:func:`~.registry.content_digest`, con el lector y el
   normalizador del dato), y **veredicto** (:func:`assess`): el mismo contenido (cambió solo el
   contenedor, un ``VACUUM``, la tabla rehecha; o lo que faltaba vuelve igual), otro contenido
   en un dato no inmutable (**edición externa**, RF-008-21) o en lo importado (**dañado**).
3. **Registro** (:func:`record`), en la transacción de escritura de quien llama: el mismo
   contenido deja el seguimiento al día (y repone los disparadores de una tabla rehecha); una
   edición externa es una operación ``core.external_edit`` hecha fuera (ejecutor ``external``)
   que consume la versión anterior y produce la nueva, con su cambio y su evento, sin deshacer
   nada; lo que depende del dato queda obsoleto por la caché de la región. Si su módulo no lo
   declara editable a mano, además queda **bloqueado** (RF-008-56) hasta aceptar la edición
   con un motivo (:func:`accept_edit`), recalcularlo o reimportarlo (lo que se ofrece:
   :func:`offers`). Lo que falta (:func:`mark_missing`), lo que vuelve con su contenido
   (:func:`restore`) y lo dañado cambian de estado con su evento; lo dañado ya no sale de ahí:
   solo se reimporta (nunca se acepta, se marca «falta» ni vuelve a vigente).

:func:`external_check_steps` repasa así, por pasos que el temporizador de ``bl`` avanza
(ninguno pasa de ``budget_s``; el trabajo de cada paso se planea para la mitad), todos los datos
seguidos (ni ``exports`` ni ``duckdb``) vigentes, bloqueados o que faltan, y los **originales**
de las entradas (``originals/``, RF-008-53): su tamaño y su fecha frente a lo guardado y, si
cambian, su huella; con otra fecha y la misma huella se anota la fecha; con otra huella o si
faltan, se avisa (evento ``original_altered``) y no sirven para reimportar
(:func:`original_usable`; I-13). Las escrituras van juntas en una transacción al final
(``Project.try_write``, con reintento en el paso siguiente si otro programa lee), y lo que
cambió mientras se comprobaba —lo que escribió esta sesión después de la foto, o lo que otro
programa volvió a cambiar después de hashearlo— no se registra: queda para la próxima (I-5).
Tampoco se miran los ficheros que reclama una operación en curso de esta sesión. En **solo
lectura** se detecta y se avisa, sin escribir nada.

Un fichero se hashea por trozos, entre pasos; una tabla, en una lectura (una instantánea), en un
solo paso. Python puro (ADR-0004): al importarse no importa ``core.provenance`` ni
``core.project``, que se cargan al registrar (``core.provenance`` importa ``core.datasets``).
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import sqlite3
import stat
import time
from collections.abc import Callable, Generator, Iterator, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from ..content.encoder import ContentDigest
from ..content.readers import read_steps
from ..content.readers import reader as content_reader
from ..errors import GeoblenderError, ValidationError
from ..hashing import sha256_file
from ..paths import ABSOLUTE_PATH
from ..timeutil import format_utc
from . import registry, tracking
from .model import DATASET_DECLARATIONS, RECORD_COLUMNS, DatasetRecord, DatasetStatus, Store
from .registry import content_digest, spec_of
from .tracking import TableState, table_states

if TYPE_CHECKING:
    from ..provenance.operations import OperationProject
    from ..sysinfo import SessionInfo
    from ..timeutil import Clock

EDITED_ROLE = "edited"
"""El papel del dato en su operación ``core.external_edit`` (lo que consume y lo que
produce)."""
CHECKED_STATUSES: tuple[DatasetStatus, ...] = (DatasetStatus.CURRENT, DatasetStatus.BLOCKED)
"""Los estados de un dato que se comprueban antes de operar: lo que falta o está dañado no se
vuelve a mirar ahí."""
SURVEYED_STATUSES: tuple[DatasetStatus, ...] = (*CHECKED_STATUSES, DatasetStatus.MISSING)
"""Los estados de un dato que repasa :func:`external_check_steps`: además, lo que falta (por si
vuelve). Lo dañado espera a reimportarse."""
STEP_BUDGET_S = 0.020
"""Lo que puede durar un paso de la comprobación (plan 008 §2: ≤ 20 ms por tic)."""
WORK_FRACTION = 0.5
"""La parte del presupuesto de un paso que se planea para mirar y leer."""
PHASES: tuple[str, ...] = ("prefiltro", "contenido", "registro")
"""Las fases de los pasos (``core.project.model.Progress``)."""
CHUNK_BYTES = 1 << 20
"""El trozo con que se lee un original para su huella."""
MAX_REASON_CHARS = 300
"""Largo máximo del motivo de un dato que no se puede leer."""

__all__ = [
    "CHECKED_STATUSES",
    "EDITED_ROLE",
    "PHASES",
    "STEP_BUDGET_S",
    "SURVEYED_STATUSES",
    "DatasetFinding",
    "DatasetProbe",
    "DatasetVerdict",
    "ExternalOutcome",
    "ExternalProject",
    "Offer",
    "OriginalFinding",
    "OriginalVerdict",
    "Signal",
    "accept_edit",
    "assess",
    "checkable",
    "content_digest",
    "external_check_steps",
    "mark_missing",
    "offer_label",
    "offers",
    "original_usable",
    "probe_dataset",
    "record",
    "restore",
    "spec_of",
]


class ExternalProject(Protocol):
    """Lo que usa del proyecto (``core.project.Project``) la comprobación de los datos: su
    nombre, su raíz, su base, el reloj, la sesión, si se puede escribir, leer y escribir con
    reintento (y, al registrar una edición externa, lo de ``OperationProject``)."""

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

    def read(self) -> AbstractContextManager[Any]: ...

    def try_write(self, work: Callable[[Any], Any]) -> Any: ...


class Signal(StrEnum):
    """Lo que ve el prefiltro de un dato (:func:`probe_dataset`)."""

    UNCHANGED = "unchanged"  # todo como tras la última escritura de Geoblender
    MOVED = "moved"  # cambió algo del contenedor (o faltaba y está): hay que hashearlo
    MISSING = "missing"  # la tabla o el fichero ya no están (RF-008-57)
    UNPROTECTED = "unprotected"  # lo importado sin sus disparadores de protección


class DatasetVerdict(StrEnum):
    """Lo que se concluye de un dato (:func:`assess`)."""

    UNCHANGED = "unchanged"  # el prefiltro no saltó (o lo que falta sigue faltando)
    SAME = "same"  # mismo contenido: solo cambió el contenedor
    EDITED = "edited"  # otro contenido en un dato no inmutable: edición externa (RF-008-21)
    MISSING = "missing"  # falta (RF-008-57)
    DAMAGED = "damaged"  # lo importado cambió o perdió su protección (ADR-0025 §4)
    RESTORED = "restored"  # lo que faltaba vuelve con su contenido registrado (RF-008-57)
    UNREADABLE = "unreadable"  # no se puede leer para comprobarlo


_CODES: Mapping[DatasetVerdict, str] = MappingProxyType({
    DatasetVerdict.EDITED: "core.external_edit",
    DatasetVerdict.MISSING: "core.dataset_missing",
    DatasetVerdict.DAMAGED: "core.dataset_damaged",
    DatasetVerdict.RESTORED: "core.dataset_restored",
    DatasetVerdict.UNREADABLE: "core.dataset_unreadable",
})


@dataclass(frozen=True)
class DatasetProbe:
    """El prefiltro de un dato: su registro, lo que se vio (:class:`Signal`) y, de un fichero,
    su tamaño y su fecha; de una tabla, su estado (:class:`~.tracking.TableState`)."""

    record: DatasetRecord
    signal: Signal
    size: int | None = None
    mtime_ns: int | None = None
    table: TableState | None = None

    @property
    def needs_hash(self) -> bool:
        """Si hay que calcular su hash de contenido para decidir."""
        return self.signal is Signal.MOVED

    @property
    def observed(self) -> object:
        """Lo que se vio de su contenedor, para saber después si cambió: el estado de su
        tabla, o el tamaño y la fecha de su fichero (``None`` si no está)."""
        if self.record.store is Store.GPKG:
            return self.table
        if self.signal is Signal.MISSING:
            return None
        return (self.size, self.mtime_ns)


@dataclass(frozen=True)
class DatasetFinding:
    """Lo que se concluyó de un dato: su registro (antes), el veredicto, su estado después, el
    hash visto, si se registró una edición externa, su operación, el nombre de su entrada (de
    lo importado) y, si no se pudo leer, el motivo."""

    record: DatasetRecord
    verdict: DatasetVerdict
    status: DatasetStatus
    digest: ContentDigest | None = None
    operation_uid: str | None = None
    input_name: str | None = None
    reason: str | None = None

    @property
    def changed(self) -> bool:
        """Si hay algo que registrar (más que el seguimiento al día)."""
        return self.verdict in (DatasetVerdict.EDITED, DatasetVerdict.MISSING,
                                DatasetVerdict.DAMAGED, DatasetVerdict.RESTORED)

    @property
    def code(self) -> str | None:
        """El mensaje del aviso (``core.provenance.messages``): edición externa, falta, dañado,
        vuelve o no se puede leer; ``None`` si no hay nada que avisar."""
        return _CODES.get(self.verdict)

    def values(self, input_name: str | None = None) -> dict[str, Any]:
        """Los valores de su aviso: su nombre, su ubicación, la entrada de lo importado y el
        motivo de no poder leerlo."""
        chosen = input_name if input_name is not None else self.input_name
        return {"name": self.record.name, "locator": self.record.locator,
                "input": chosen if chosen is not None else self.record.input_uid,
                "reason": self.reason}

    def text(self, language: str = "es") -> str | None:
        """El aviso en ``language`` (el de una capa que no se edita a mano lleva además el
        bloqueo de la spec §8); ``None`` si no hay nada que avisar."""
        code = self.code
        if code is None:
            return None
        shown = _render(code, language=language, **self.values())
        if self.verdict is DatasetVerdict.EDITED and self.status is DatasetStatus.BLOCKED:
            shown += " " + _render("core.dataset_blocked", language=language,
                                   name=self.record.name)
        return shown


def checkable(record: DatasetRecord) -> bool:
    """Si el dato se comprueba antes de operar: seguido y vigente o bloqueado."""
    return record.tracked and record.status in CHECKED_STATUSES


def _path(project: Any, record: DatasetRecord) -> Path:
    return Path(project.root, *record.locator.split("/"))


def _stat(path: Path) -> tuple[int, int] | None:
    """El tamaño y la fecha de un fichero, o ``None`` si no está (o no es un fichero)."""
    try:
        found = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    if not stat.S_ISREG(found.st_mode):
        return None
    return found.st_size, found.st_mtime_ns


def probe_dataset(project: Any, record: DatasetRecord,
                  tables: Mapping[str, TableState]) -> DatasetProbe:
    """El prefiltro del dato ``record`` (véase el módulo, paso 1): ``tables``, el estado de las
    tablas de ``project.gpkg`` (:func:`~.tracking.table_states`; hace falta el de la suya si es
    una tabla). Del proyecto usa su raíz (``root``). No escribe ni lee el contenido.
    :class:`ValueError` si el dato no se sigue."""
    if not record.tracked:
        raise ValueError(f"el dato «{record.name}» no se sigue ({record.store}): no se comprueba")
    was_missing = record.status is DatasetStatus.MISSING
    if record.store is Store.GPKG:
        state = tables.get(record.locator)
        if state is None:
            raise ValueError(f"falta el estado de la tabla «{record.locator}» del dato "
                             f"«{record.name}» (table_states)")
        if not (state.registered and state.exists):
            return DatasetProbe(record, Signal.MISSING, table=state)
        if record.immutable:
            selector = record.selector if record.selector and "equals" in record.selector else None
            names = tracking.protection_trigger_names(record.locator, selector)
            if any(name not in state.triggers for name in names):
                return DatasetProbe(record, Signal.UNPROTECTED, table=state)
        moved = (was_missing
                 or state.last_change != record.tracked_last_change
                 or state.schema_sha256 != record.tracked_schema_sha256
                 or not state.tracked)
        return DatasetProbe(record, Signal.MOVED if moved else Signal.UNCHANGED, table=state)
    seen = _stat(_path(project, record))
    if seen is None:
        return DatasetProbe(record, Signal.MISSING)
    moved = was_missing or seen != (record.tracked_size, record.tracked_mtime_ns)
    return DatasetProbe(record, Signal.MOVED if moved else Signal.UNCHANGED, *seen)


def assess(probe: DatasetProbe, digest: ContentDigest | None = None) -> DatasetFinding:
    """El veredicto de un dato (véase el módulo, paso 2) con su prefiltro y, si saltó, el hash
    de su contenido actual (:func:`~.registry.content_digest`). No escribe nada.
    :class:`ValueError` si hacía falta el hash y no se da."""
    record = probe.record
    if probe.signal is Signal.MISSING:
        if record.status is DatasetStatus.MISSING:
            return DatasetFinding(record, DatasetVerdict.UNCHANGED, record.status)
        return DatasetFinding(record, DatasetVerdict.MISSING, DatasetStatus.MISSING)
    if probe.signal is Signal.UNPROTECTED:
        return DatasetFinding(record, DatasetVerdict.DAMAGED, DatasetStatus.DAMAGED)
    if probe.signal is Signal.UNCHANGED:
        return DatasetFinding(record, DatasetVerdict.UNCHANGED, record.status)
    if digest is None:
        raise ValueError(f"el dato «{record.name}» necesita su hash de contenido: el prefiltro "
                         "saltó")
    if digest.content_sha256 == record.content_sha256:
        if record.status is DatasetStatus.MISSING:
            return DatasetFinding(record, DatasetVerdict.RESTORED, DatasetStatus.CURRENT, digest)
        return DatasetFinding(record, DatasetVerdict.SAME, record.status, digest)
    if record.immutable:
        return DatasetFinding(record, DatasetVerdict.DAMAGED, DatasetStatus.DAMAGED, digest)
    status = DatasetStatus.CURRENT if record.qgis_editable else DatasetStatus.BLOCKED
    return DatasetFinding(record, DatasetVerdict.EDITED, status, digest)


# --- Registro --------------------------------------------------------------------------------


def _event(conn: sqlite3.Connection, project: Any, kind: str, uid: str, message: str,
           data: Mapping[str, Any], at: str, *, entity_kind: str = "dataset") -> None:
    """Su evento en ``gb_event`` (``kind``: el nombre de ``core.project.events.EventKind``).
    Se importa aquí: ``core.project`` pasa por ``core.provenance``, que importa este
    paquete."""
    from ..project.events import EventKind, record_event

    record_event(conn, EventKind[kind], message, session=project.session, at=at,
                 entity_kind=entity_kind, entity_uid=uid, data=dict(data))


def _render(code: str, *, language: str = "es", **values: Any) -> str:
    from ..provenance.messages import render

    return render(code, language=language, **values)


def _error(code: str, **values: Any) -> Exception:
    from ..provenance.messages import ProvenanceError

    return ProvenanceError(code, **values)


def _input_name(conn: sqlite3.Connection, record: DatasetRecord) -> str | None:
    if record.input_uid is None:
        return None
    row = conn.execute("SELECT name FROM gb_input WHERE uid = ?", (record.input_uid,)).fetchone()
    return record.input_uid if row is None else str(row[0])


def _required(conn: sqlite3.Connection, key: object) -> DatasetRecord:
    """El dato con el uid ``key`` (o el vivo con ese nombre)."""
    if not isinstance(key, str):
        raise TypeError(f"un dato se indica por su uid o su nombre, no {key!r}")
    found = registry.get(conn, key)
    if found is None:
        raise ValidationError("core.dataset_unknown",
                              "no hay ningún dato con ese identificador o ese nombre en el "
                              "proyecto", obj="Dato del proyecto", field="uid", value=key)
    return found


def _keep_tracking(conn: sqlite3.Connection, project: Any, record: DatasetRecord,
                   now: str) -> None:
    """El seguimiento al día tras ver que el contenido no cambió: los disparadores de una
    tabla (los repone si se rehízo) y lo anotado (``tracked_*``) y cuándo (``checked_at``)."""
    if record.store is Store.GPKG:
        tracking.ensure_triggers(conn, [record.locator])
        state = tracking.table_states(conn, [record.locator])[record.locator]
        values: dict[str, object] = {"tracked_last_change": state.last_change,
                                     "tracked_schema_sha256": state.schema_sha256}
    else:
        found = os.stat(_path(project, record))
        values = {"tracked_size": found.st_size, "tracked_mtime_ns": found.st_mtime_ns}
    values["checked_at"] = now
    conn.execute(
        f"UPDATE gb_dataset SET {', '.join(f'{column} = ?' for column in values)} WHERE uid = ?",
        (*values.values(), record.uid),
    )


def _status_data(record: DatasetRecord) -> dict[str, Any]:
    return {"name": record.name, "store": str(record.store), "locator": record.locator,
            "input_uid": record.input_uid}


def _external_edit(conn: sqlite3.Connection, project: OperationProject,
                   finding: DatasetFinding, now: str) -> DatasetFinding:
    """La edición externa (RF-008-21, D9): una operación ``core.external_edit`` que consume la
    versión anterior del dato y produce la nueva, completada en ``conn``; si su módulo no lo
    declara editable a mano, el dato queda bloqueado (RF-008-56). Con su evento."""
    from ..provenance.contract import EXTERNAL_EDIT
    from ..provenance.operations import Executor, Use, begin_in_transaction

    record = finding.record
    blocked = finding.status is DatasetStatus.BLOCKED
    text = finding.text() or ""
    handle = begin_in_transaction(
        conn, project, EXTERNAL_EDIT, settings={"dataset": record.name},
        inputs=[Use(record.uid, EDITED_ROLE)], executor=Executor.EXTERNAL,
    )
    (written,) = handle.complete(conn, outputs=[spec_of(record, role=EDITED_ROLE,
                                                        content=finding.digest)],
                                 message=text)
    if blocked:
        written = registry.set_status(conn, project, record.uid, DatasetStatus.BLOCKED)
    _event(conn, project, "EXTERNAL_EDIT", record.uid, text, {
        "name": record.name,
        "from_sha256": record.content_sha256,
        "to_sha256": written.content_sha256,
        "operation_uid": handle.uid,
        "editable": record.qgis_editable,
        "blocked": blocked,
    }, now)
    return replace(finding, operation_uid=handle.uid)


def mark_missing(conn: sqlite3.Connection, project: Any, uid: str) -> DatasetRecord:
    """Marca «falta» el dato seguido ``uid`` (RF-008-57; su fichero o su tabla ya no está),
    con su evento, en la transacción de escritura ``conn`` de quien llama; lo que lo consume
    queda obsoleto (caché de la región). Lo que ya falta no se vuelve a escribir.
    :class:`ValueError` (un error del programa) con un dato dañado (solo se reimporta),
    sustituido, descartado o sin seguimiento."""
    current = _required(conn, uid)
    if current.status is DatasetStatus.MISSING:
        return current
    if current.status not in CHECKED_STATUSES or not current.tracked:
        raise ValueError(f"el dato «{current.name}» está «{current.status}» (seguido: "
                         f"{current.tracked}): solo falta un dato seguido vigente o bloqueado; "
                         "lo dañado solo se reimporta")
    now = format_utc(project.clock.now())
    written = registry.set_status(conn, project, current.uid, DatasetStatus.MISSING)
    finding = DatasetFinding(current, DatasetVerdict.MISSING, DatasetStatus.MISSING,
                             input_name=_input_name(conn, current))
    _event(conn, project, "DATASET_MISSING", current.uid, finding.text() or "",
           _status_data(current), now)
    return written


def restore(conn: sqlite3.Connection, project: Any, uid: str, *,
            digest: ContentDigest | None = None) -> DatasetRecord:
    """Vuelve a dar por vigente el dato ``uid``, que faltaba y vuelve a estar con su contenido
    registrado (RF-008-57), con su seguimiento al día y su evento, en la transacción de
    escritura ``conn`` de quien llama; lo que lo consume deja de estar obsoleto por ello.
    ``digest``: su hash ya calculado (si no, se calcula aquí). :class:`ValueError` (un error del
    programa) si no faltaba (nunca un dato dañado), si sigue sin estar o perdió su protección,
    o si su contenido no es el registrado (eso es una edición externa o un daño)."""
    current = _required(conn, uid)
    if current.status is not DatasetStatus.MISSING:
        raise ValueError(f"solo vuelve a estar vigente un dato que falta, no «{current.name}», "
                         f"que está «{current.status}» (lo dañado solo se reimporta)")
    states = table_states(conn, [current.locator]) if current.store is Store.GPKG else {}
    if probe_dataset(project, current, states).signal is not Signal.MOVED:
        raise ValueError(f"el dato «{current.name}» sigue sin estar o perdió su protección: no "
                         "vuelve a estar vigente")
    seen = digest if digest is not None else content_digest(conn, project, current)
    if seen.content_sha256 != current.content_sha256:
        raise ValueError(f"el dato «{current.name}» no tiene su contenido registrado: no vuelve "
                         "a estar vigente (es una edición externa o está dañado)")
    now = format_utc(project.clock.now())
    _keep_tracking(conn, project, current, now)
    written = registry.set_status(conn, project, current.uid, DatasetStatus.CURRENT)
    _event(conn, project, "DATASET_RESTORED", current.uid,
           _render("core.dataset_restored", name=current.name),
           {**_status_data(current), "content_sha256": current.content_sha256}, now)
    return written


def _mark_damaged(conn: sqlite3.Connection, project: Any, finding: DatasetFinding,
                  now: str) -> None:
    current = finding.record
    registry.set_status(conn, project, current.uid, DatasetStatus.DAMAGED)
    data = _status_data(current)
    if finding.digest is not None:
        data["seen_sha256"] = finding.digest.content_sha256
    shown = replace(finding, input_name=_input_name(conn, current))
    _event(conn, project, "DATASET_DAMAGED", current.uid, shown.text() or "", data, now)


def record(conn: sqlite3.Connection, project: OperationProject,
           finding: DatasetFinding) -> DatasetFinding:
    """Registra lo concluido de un dato (véase el módulo, paso 3) en la transacción de
    escritura ``conn`` de quien llama (no la confirma) y lo devuelve (con la operación de la
    edición externa, si la hubo). Lo que no saltó o no se pudo leer no escribe nada. Las
    comprobaciones de ``core.provenance.operations`` (``core.read_only``,
    ``core.operation_unregistered`` si no está registrado ``core.external_edit``) y de
    ``core.datasets`` rechazan sin escribir."""
    current = finding.record
    now = format_utc(project.clock.now())
    verdict = finding.verdict
    if verdict in (DatasetVerdict.UNCHANGED, DatasetVerdict.UNREADABLE):
        return finding
    if verdict is DatasetVerdict.SAME:
        _keep_tracking(conn, project, current, now)
    elif verdict is DatasetVerdict.EDITED:
        return _external_edit(conn, project, finding, now)
    elif verdict is DatasetVerdict.RESTORED:
        restore(conn, project, current.uid, digest=finding.digest)
    elif verdict is DatasetVerdict.MISSING:
        mark_missing(conn, project, current.uid)
    else:
        _mark_damaged(conn, project, finding, now)
    return finding


# --- Aceptar una edición y lo que se ofrece ----------------------------------------------------


class Offer(StrEnum):
    """Lo que se ofrece para resolver un dato bloqueado, que falta o dañado (RF-008-56,
    RF-008-57), en este orden."""

    ACCEPT = "accept"  # aceptar la edición externa con un motivo (solo un dato bloqueado)
    RECOMPUTE = "recompute"  # recalcularlo con su operación, si se puede repetir
    REIMPORT = "reimport"  # reimportar la entrada de lo importado (o cuya importación lo escribió)


def offer_label(offer: Offer | str, language: str = "es") -> str:
    """El texto de lo que se ofrece en ``language`` («Aceptar la edición», «Recalcular»,
    «Reimportar»)."""
    return _render(f"core.offer_{Offer(offer)}", language=language)


_LAST_WRITER = (
    "SELECT o.uid, o.repeatable FROM gb_operation_io AS io JOIN gb_operation AS o "
    "ON o.uid = io.operation_uid WHERE io.item_uid = ? AND io.direction = 'out' "
    "AND +io.item_kind = 'dataset' AND o.status = 'done' AND o.executor <> 'external' "
    "ORDER BY io.fid DESC LIMIT 1"
)
"""La última operación hecha en Geoblender (no una edición externa) que escribió un dato."""


def offers(conn: sqlite3.Connection, key: str) -> tuple[Offer, ...]:
    """Lo que se ofrece para el dato ``key`` (uid o nombre de un dato vivo): de uno bloqueado,
    aceptar la edición; de uno bloqueado o que falta, recalcularlo si la última operación de
    Geoblender que lo escribió se puede repetir, y reimportarlo si es lo importado de una
    entrada o lo escribió una importación; de lo dañado, solo reimportarlo (ADR-0025 §4); de lo
    demás, nada. Solo lee. ``ValidationError`` (``core.dataset_unknown``) si no está."""
    current = _required(conn, key)
    if current.status is DatasetStatus.DAMAGED:
        return (Offer.REIMPORT,)
    if current.status not in (DatasetStatus.BLOCKED, DatasetStatus.MISSING):
        return ()
    found: list[Offer] = []
    if current.status is DatasetStatus.BLOCKED:
        found.append(Offer.ACCEPT)
    writer = conn.execute(_LAST_WRITER, (current.uid,)).fetchone()
    if writer is not None and writer[1]:
        found.append(Offer.RECOMPUTE)
    imported = current.input_uid is not None or (writer is not None and conn.execute(
        "SELECT 1 FROM gb_input WHERE operation_uid = ?", (writer[0],)).fetchone() is not None)
    if imported:
        found.append(Offer.REIMPORT)
    return tuple(found)


def accept_edit(conn: sqlite3.Connection, project: Any, key: str, reason: str) -> DatasetRecord:
    """Acepta con ``reason`` la edición externa del dato bloqueado ``key`` (uid o nombre de un
    dato vivo; RF-008-56), en la transacción de escritura ``conn`` de quien llama: vuelve a
    vigente, con el evento ``edit_accepted`` (quién, cuándo y el motivo, sin rutas absolutas);
    lo que lo consume sigue obsoleto por el cambio de su contenido, pero ya no por el bloqueo.

    ``ProvenanceError`` sin escribir nada: ``core.dataset_damaged`` (lo dañado solo se
    reimporta), ``core.accept_edit_not_blocked`` y ``core.accept_edit_reason_missing`` (motivo
    vacío); ``ValidationError`` (``core.dataset_unknown``) si no está; :class:`TypeError` si
    ``reason`` no es un texto."""
    if not isinstance(reason, str):
        raise TypeError(f"el motivo de aceptar una edición es un texto, no {reason!r}")
    current = _required(conn, key)
    if current.status is DatasetStatus.DAMAGED:
        raise _error("core.dataset_damaged", name=current.name, locator=current.locator,
                     input=_input_name(conn, current))
    if current.status is not DatasetStatus.BLOCKED:
        raise _error("core.accept_edit_not_blocked", name=current.name)
    from ..provenance.operations import _clean

    text = _clean(reason.strip())
    if not text:
        raise _error("core.accept_edit_reason_missing", name=current.name)
    now = format_utc(project.clock.now())
    written = registry.set_status(conn, project, current.uid, DatasetStatus.CURRENT)
    _event(conn, project, "EDIT_ACCEPTED", current.uid,
           _render("core.edit_accepted", name=current.name, reason=text), {
               "name": current.name,
               "reason": text,
               "accepted_by": project.session.user_host,
               "content_sha256": current.content_sha256,
               "operation_uid": current.operation_uid,
           }, now)
    return written


# --- Originales --------------------------------------------------------------------------------


class OriginalVerdict(StrEnum):
    """Lo que se encuentra de un original de ``originals/`` (RF-008-53; I-13)."""

    UNCHANGED = "unchanged"  # su tamaño y su fecha, los guardados
    SAME = "same"  # otra fecha y la misma huella: se anota la fecha
    ALTERED = "altered"  # otra huella: no sirve para reimportar
    MISSING = "missing"  # ya no está: no sirve para reimportar


@dataclass(frozen=True)
class OriginalFinding:
    """Lo que se encontró del original ``path`` (``originals/<uid>/<nombre>``) del fichero
    ``ord`` de la entrada ``input_uid`` (``name``): el veredicto y lo que se vio (tamaño, fecha
    y, si se calculó, su huella)."""

    input_uid: str
    name: str
    ord: int
    path: str
    verdict: OriginalVerdict
    size: int | None = None
    mtime_ns: int | None = None
    sha256: str | None = None

    @property
    def file(self) -> str:
        """El nombre del fichero."""
        return PurePosixPath(self.path).name

    @property
    def usable(self) -> bool:
        """Si sirve para reimportar: sigue con su huella."""
        return self.verdict in (OriginalVerdict.UNCHANGED, OriginalVerdict.SAME)

    @property
    def code(self) -> str | None:
        """El mensaje del aviso, o ``None`` si sirve."""
        return {OriginalVerdict.ALTERED: "core.original_altered",
                OriginalVerdict.MISSING: "core.original_missing"}.get(self.verdict)

    def text(self, language: str = "es") -> str | None:
        """El aviso en ``language``; ``None`` si sirve."""
        code = self.code
        return None if code is None else _render(code, language=language, name=self.name,
                                                 file=self.file)


@dataclass(frozen=True)
class _Original:
    """Un original guardado, como está registrado (``gb_input_file.original_*``)."""

    input_uid: str
    name: str
    ord: int
    path: str
    sha256: str
    size: int
    mtime_ns: int


_ORIGINALS = (
    "SELECT f.input_uid, i.name, f.ord, f.original_path, f.original_sha256, f.original_size, "
    "f.original_mtime_ns FROM gb_input_file AS f JOIN gb_input AS i ON i.uid = f.input_uid "
    "WHERE f.original_path IS NOT NULL"
)


def _originals(conn: sqlite3.Connection, input_uid: str | None = None) -> list[_Original]:
    """Los originales guardados (de una entrada o de todas), por orden de registro."""
    where = "" if input_uid is None else " AND f.input_uid = ?"
    args: tuple[Any, ...] = () if input_uid is None else (input_uid,)
    return [_Original(str(uid), str(name), int(ord_), str(path), str(sha), int(size), int(ns))
            for uid, name, ord_, path, sha, size, ns in conn.execute(
                f"{_ORIGINALS}{where} ORDER BY i.fid, f.ord", args)]


def _original_path(project: Any, item: _Original) -> Path:
    return Path(project.root, *item.path.split("/"))


def original_usable(project: Any, input_uid: str, *,
                    conn: sqlite3.Connection | None = None) -> bool:
    """Si los originales guardados de la entrada ``input_uid`` sirven para reimportarla: los
    tiene (``gb_input_file.original_*``, que se escriben con ``gb_input.original = stored``) y
    cada uno está con su huella (su tamaño y su fecha y, si cambian, su huella; I-13). Solo
    lee (con ``conn``, en esa conexión). ``ProvenanceError`` (``core.input_unknown``) si la
    entrada no está."""
    reading = nullcontext(conn) if conn is not None else project.read()
    with reading as opened:
        found = opened.execute("SELECT 1 FROM gb_input WHERE uid = ?", (input_uid,)).fetchone()
        if found is None:
            raise _error("core.input_unknown", input=input_uid, project=project.name)
        items = _originals(opened, input_uid)
    if not items:
        return False
    for item in items:
        path = _original_path(project, item)
        seen = _stat(path)
        if seen is None:
            return False
        if seen == (item.size, item.mtime_ns):
            continue
        if seen[0] != item.size or sha256_file(path) != item.sha256:
            return False
    return True


def _already_warned(conn: sqlite3.Connection, found: OriginalFinding) -> bool:
    """Si el último aviso registrado del original ya era de lo que se ve ahora (la misma
    huella o que falta): no se repite el evento."""
    for (text,) in conn.execute(
        "SELECT data FROM gb_event WHERE kind = 'original_altered' AND entity_uid = ? "
        "ORDER BY fid DESC", (found.input_uid,)
    ):
        data = json.loads(text) if text else {}
        if data.get("ord") != found.ord:
            continue
        return (bool(data.get("missing")) == (found.verdict is OriginalVerdict.MISSING)
                and data.get("seen_sha256") == found.sha256)
    return False


# --- Comprobación de los datos del proyecto ----------------------------------------------------


@dataclass(frozen=True)
class ExternalOutcome:
    """El resultado de :func:`external_check_steps`: lo encontrado de cada dato (lo que no
    saltó, no), de cada original (ídem), si quedó registrado en el proyecto (``False`` en solo
    lectura), lo que cambió mientras se comprobaba (``stale``: uid de los datos y rutas de los
    originales; no se registra y se comprueba la próxima vez) y los uid de los datos
    comprobados (``checked``)."""

    findings: tuple[DatasetFinding, ...]
    originals: tuple[OriginalFinding, ...]
    recorded: bool
    stale: tuple[str, ...] = ()
    checked: tuple[str, ...] = ()

    def texts(self, language: str = "es") -> tuple[str, ...]:
        """Los avisos, en orden: los de los datos y los de los originales."""
        found = [item.text(language) for item in self.findings]
        found += [item.text(language) for item in self.originals]
        return tuple(text for text in found if text)

    @property
    def warnings(self) -> tuple[str, ...]:
        """Los avisos en español."""
        return self.texts("es")


class _Pacer:
    """Mide un paso: termina cuando lo hecho más lo más lento del paso pasaría de su parte del
    presupuesto (siempre al menos una unidad de trabajo)."""

    def __init__(self, budget_s: float) -> None:
        self.target = budget_s * WORK_FRACTION
        self.restart()

    def restart(self) -> None:
        self.start = self.last = time.perf_counter()
        self.slowest = 0.0

    def lap(self) -> bool:
        now = time.perf_counter()
        self.slowest = max(self.slowest, now - self.last)
        self.last = now
        return now - self.start + self.slowest > self.target


def _budget(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"el presupuesto de un paso es un número de segundos, no {value!r}")
    if not value > 0:
        raise ValueError(f"el presupuesto de un paso es positivo, no {value!r}")
    return float(value)


def _reason(error: BaseException) -> str:
    """Por qué no se pudo leer: sin rutas absolutas (solo el nombre de su fichero) y no muy
    largo."""
    shown = ABSOLUTE_PATH.sub(
        lambda match: ntpath.basename(match.group(0).rstrip("\\/")) or "…", str(error))
    if len(shown) > MAX_REASON_CHARS:
        shown = shown[: MAX_REASON_CHARS - 1] + "…"
    return shown


@dataclass
class _Check:
    """Un dato en la comprobación: su registro en la foto, lo que se vio de su contenedor al
    decidir (la base con que se registra) y lo concluido."""

    record: DatasetRecord
    input_name: str | None
    basis: object = None
    finding: DatasetFinding | None = None
    stale: bool = False

    def conclude(self, finding: DatasetFinding) -> None:
        self.finding = replace(finding, input_name=self.input_name)

    @property
    def pending(self) -> bool:
        """Si algo queda por registrar."""
        return (not self.stale and self.finding is not None
                and self.finding.verdict not in (DatasetVerdict.UNCHANGED,
                                                 DatasetVerdict.UNREADABLE))


@dataclass
class _OriginalCheck:
    """Un original en la comprobación: lo registrado, lo que se vio y lo concluido."""

    item: _Original
    seen: tuple[int, int] | None = None
    finding: OriginalFinding | None = None
    stale: bool = False

    def conclude(self, verdict: OriginalVerdict, sha256: str | None = None) -> None:
        size, mtime_ns = self.seen if self.seen is not None else (None, None)
        self.finding = OriginalFinding(self.item.input_uid, self.item.name, self.item.ord,
                                       self.item.path, verdict, size, mtime_ns, sha256)

    @property
    def pending(self) -> bool:
        return (not self.stale and self.finding is not None
                and self.finding.verdict is not OriginalVerdict.UNCHANGED)


_SURVEY = (
    f"SELECT {', '.join(RECORD_COLUMNS)} FROM gb_dataset WHERE tracked = 1 AND status IN "
    f"({', '.join(f"'{status}'" for status in SURVEYED_STATUSES)}) ORDER BY fid"
)


def external_check_steps(project: ExternalProject, *,
                         budget_s: float = STEP_BUDGET_S) -> Iterator[Any]:
    """Comprueba los datos seguidos del proyecto y los originales de sus entradas (RF-008-21,
    RF-008-53, RF-008-56, RF-008-57; véase el módulo) por pasos de ``budget_s`` como mucho.
    Cada paso es un ``core.project.model.Progress``; el último lleva el
    :class:`ExternalOutcome` en ``result``. Cerrar el generador a medias no registra nada.
    :class:`TypeError` o :class:`ValueError` (al llamarla) si ``budget_s`` no es un número
    positivo; al registrar, los rechazos de :func:`record`."""
    return _check_steps(project, _budget(budget_s))


def _claimed(project: Any) -> frozenset[str]:
    """Los ficheros que reclaman las operaciones en curso de esta sesión (los escriben ellas)."""
    from ..provenance.operations import claimed_paths

    return frozenset(os.path.normcase(os.path.normpath(path)) for path in claimed_paths(project))


def _check_steps(project: ExternalProject, budget: float) -> Iterator[Any]:
    from ..project.model import Progress
    from ..project.session import WriteState

    with project.read() as conn:
        records = [DatasetRecord.from_row(row) for row in conn.execute(_SURVEY)]
        names = {str(uid): str(name)
                 for uid, name in conn.execute("SELECT uid, name FROM gb_input")}
        locators = [item.locator for item in records if item.store is Store.GPKG]
        tables = table_states(conn, locators) if locators else {}
        stored = _originals(conn)
    claimed = _claimed(project) if any(item.store is not Store.GPKG for item in records) else ()
    checks = [
        _Check(item, None if item.input_uid is None else names.get(item.input_uid))
        for item in records
        if item.store is Store.GPKG
        or os.path.normcase(os.path.normpath(_path(project, item))) not in claimed
    ]
    originals = [_OriginalCheck(item) for item in stored]
    total = len(checks) + len(originals)
    message = "Comprobando los datos del proyecto…"
    yield Progress(PHASES[0], 0, total, message)
    pacer = _Pacer(budget)
    for index, item in enumerate((*checks, *originals), start=1):
        if isinstance(item, _Check):
            _prefilter(project, item, tables)
        else:
            _prefilter_original(project, item)
        if pacer.lap() and index < total:
            yield Progress(PHASES[0], index, total, message)
            pacer.restart()
    waiting = [item for item in (*checks, *originals) if item.finding is None and not item.stale]
    for index, item in enumerate(waiting, start=1):
        if isinstance(item, _Check):
            yield from _hash_dataset(project, item, pacer, index - 1, len(waiting))
        else:
            yield from _hash_original(project, item, pacer, index - 1, len(waiting))
        if pacer.lap() and index < len(waiting):
            yield Progress(PHASES[1], index, len(waiting),
                           "Comprobando el contenido de los datos…")
            pacer.restart()
    yield Progress(PHASES[2], total, total, "Registrando la comprobación de los datos…")
    recorded = bool(project.writable)
    if recorded and any(item.pending for item in (*checks, *originals)):
        while True:
            attempt = project.try_write(lambda conn: _record_all(conn, project, checks,
                                                                 originals))
            if attempt.state is WriteState.DONE:
                break
            yield Progress(PHASES[2], total, total, attempt.message)
        late, written = attempt.value
        for item in checks:
            if item.record.uid in late:
                item.stale = True
            elif item.record.uid in written:
                item.finding = written[item.record.uid]
        for original in originals:
            if original.item.path in late:
                original.stale = True
    outcome = ExternalOutcome(
        findings=tuple(item.finding for item in checks if not item.stale
                       and item.finding is not None
                       and item.finding.verdict is not DatasetVerdict.UNCHANGED),
        originals=tuple(item.finding for item in originals if not item.stale
                        and item.finding is not None
                        and item.finding.verdict is not OriginalVerdict.UNCHANGED),
        recorded=recorded,
        stale=(tuple(item.record.uid for item in checks if item.stale)
               + tuple(item.item.path for item in originals if item.stale)),
        checked=tuple(item.record.uid for item in checks if not item.stale),
    )
    yield Progress(PHASES[2], total, total, _summary(outcome), result=outcome)


def _summary(outcome: ExternalOutcome) -> str:
    counts = {verdict: 0 for verdict in DatasetVerdict}
    for item in outcome.findings:
        counts[item.verdict] += 1
    altered = sum(1 for item in outcome.originals if not item.usable)
    return (f"Datos comprobados: {len(outcome.checked)}; editados fuera: "
            f"{counts[DatasetVerdict.EDITED]}; que faltan: {counts[DatasetVerdict.MISSING]}; "
            f"dañados: {counts[DatasetVerdict.DAMAGED]}; sin leer: "
            f"{counts[DatasetVerdict.UNREADABLE]}; originales que no sirven: {altered}.")


def _prefilter(project: Any, item: _Check, tables: Mapping[str, TableState]) -> None:
    """El prefiltro de un dato contra la foto: lo que no hay que hashear queda concluido."""
    try:
        probe = probe_dataset(project, item.record, tables)
    except OSError as exc:
        item.conclude(DatasetFinding(item.record, DatasetVerdict.UNREADABLE, item.record.status,
                                     reason=_reason(exc)))
        return
    item.basis = probe.observed
    if not probe.needs_hash:
        item.conclude(assess(probe))


def _hash_dataset(project: Any, item: _Check, pacer: _Pacer, done: int,
                  total: int) -> Generator[Any, None, None]:
    """El hash de un dato que saltó: una tabla, en una lectura (con el estado de su tabla en
    esa lectura como base); un fichero, por trozos entre pasos (si cambia mientras se lee, queda
    para la próxima)."""
    from ..project.model import Progress

    current = item.record
    message = f"Comprobando el contenido de «{current.name}»…"
    try:
        if current.store is Store.GPKG:
            with project.read() as conn:
                state = table_states(conn, [current.locator])[current.locator]
                fresh = probe_dataset(project, current, {current.locator: state})
                digest = content_digest(conn, project, current) if fresh.needs_hash else None
            item.basis = fresh.observed
            item.conclude(assess(fresh, digest))
            return
        path = _path(project, current)
        before = _stat(path)
        if before is None:
            item.basis = None
            item.conclude(assess(DatasetProbe(current, Signal.MISSING)))
            return
        found = content_reader(current.reader)
        request = found.request(current.kind, DATASET_DECLARATIONS, {"main": path},
                                normalizer=current.normalizer)
        steps = read_steps(found, request)
        try:
            for _done in steps:
                if pacer.lap():
                    yield Progress(PHASES[1], done, total, message)
                    pacer.restart()
        finally:
            steps.close()
        if _stat(path) != before:
            item.stale = True
            return
        item.basis = before
        item.conclude(assess(DatasetProbe(current, Signal.MOVED, *before),
                             request.hasher.digest()))
    except FileNotFoundError:
        item.stale = True
    except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
        item.conclude(DatasetFinding(current, DatasetVerdict.UNREADABLE, current.status,
                                     reason=_reason(exc)))


def _prefilter_original(project: Any, item: _OriginalCheck) -> None:
    try:
        item.seen = _stat(_original_path(project, item.item))
    except OSError:
        item.stale = True
        return
    if item.seen is None:
        item.conclude(OriginalVerdict.MISSING)
    elif item.seen == (item.item.size, item.item.mtime_ns):
        item.conclude(OriginalVerdict.UNCHANGED)


def _hash_original(project: Any, item: _OriginalCheck, pacer: _Pacer, done: int,
                   total: int) -> Generator[Any, None, None]:
    """La huella de un original cuyo tamaño o fecha cambiaron, por trozos entre pasos."""
    from ..project.model import Progress

    path = _original_path(project, item.item)
    digest = hashlib.sha256()
    message = f"Comprobando el original «{PurePosixPath(item.item.path).name}»…"
    try:
        with open(path, "rb", buffering=0) as stream:
            while chunk := stream.read(CHUNK_BYTES):
                digest.update(chunk)
                if pacer.lap():
                    yield Progress(PHASES[1], done, total, message)
                    pacer.restart()
        if _stat(path) != item.seen:
            item.stale = True
            return
    except OSError:
        item.stale = True
        return
    sha = digest.hexdigest()
    item.conclude(OriginalVerdict.SAME if sha == item.item.sha256 else OriginalVerdict.ALTERED,
                  sha)


def _observation(conn: sqlite3.Connection, project: Any, current: DatasetRecord) -> object:
    """Lo que se ve ahora del contenedor de un dato (como :attr:`DatasetProbe.observed`)."""
    if current.store is Store.GPKG:
        return table_states(conn, [current.locator])[current.locator]
    return _stat(_path(project, current))


_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "status", "content_sha256", "operation_uid", "tracked_size", "tracked_mtime_ns",
    "tracked_last_change", "tracked_schema_sha256",
)
"""Lo que, si cambió desde la foto, dice que alguien registró el dato mientras tanto."""


def _record_all(conn: sqlite3.Connection, project: Any, checks: list[_Check],
                originals: list[_OriginalCheck]) -> tuple[set[str], dict[str, DatasetFinding]]:
    """El registro de lo encontrado, en la transacción de escritura ``conn``: lo que sigue como
    se vio al decidir; lo demás (lo que esta sesión registró después de la foto, lo que cambió
    después de hashearlo) queda para la próxima. Devuelve lo que se dejó (uid de datos y rutas
    de originales) y lo registrado de cada dato."""
    late: set[str] = set()
    written: dict[str, DatasetFinding] = {}
    for item in checks:
        if not item.pending or item.finding is None:
            continue
        current = registry.get(conn, item.record.uid)
        if (current is None
                or any(getattr(current, name) != getattr(item.record, name)
                       for name in _SNAPSHOT_FIELDS)
                or _observation(conn, project, current) != item.basis):
            late.add(item.record.uid)
            continue
        written[current.uid] = record(conn, project, item.finding)
    for original in originals:
        found = original.finding
        if not original.pending or found is None:
            continue
        kept = original.item
        row = conn.execute(
            "SELECT original_sha256, original_size, original_mtime_ns FROM gb_input_file "
            "WHERE input_uid = ? AND ord = ?", (kept.input_uid, kept.ord)).fetchone()
        if (row is None or tuple(row) != (kept.sha256, kept.size, kept.mtime_ns)
                or _stat(_original_path(project, kept)) != original.seen):
            late.add(kept.path)
            continue
        if found.verdict is OriginalVerdict.SAME:
            conn.execute("UPDATE gb_input_file SET original_mtime_ns = ? WHERE input_uid = ? "
                         "AND ord = ?", (found.mtime_ns, kept.input_uid, kept.ord))
        elif not _already_warned(conn, found):
            _event(conn, project, "ORIGINAL_ALTERED", kept.input_uid, found.text() or "", {
                "name": kept.name,
                "file": found.file,
                "ord": kept.ord,
                "path": kept.path,
                "original_sha256": kept.sha256,
                "seen_sha256": found.sha256,
                "size": found.size,
                "mtime_ns": found.mtime_ns,
                "missing": found.verdict is OriginalVerdict.MISSING,
            }, format_utc(project.clock.now()), entity_kind="input")
    return late, written
