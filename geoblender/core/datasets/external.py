# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos del proyecto cambiados fuera de Geoblender (spec 008; RF-008-21, RF-008-56,
RF-008-57; ADR-0025 §4 y §6; plan 008 §5.4.2 y §5.4.9).

Un dato del proyecto se comprueba en dos tiempos (ADR-0025 §6), por piezas que usan la puerta
antes de operar (``core.provenance.gate``, T30) y la comprobación de los datos del proyecto
(T32):

1. **Prefiltro** (:func:`probe_dataset`), sin leer el contenido: de una tabla de
   ``project.gpkg``, su ``gpkg_contents.last_change``, la huella de su SQL y sus disparadores
   (:func:`~.tracking.table_states`) frente a lo anotado tras la última escritura de Geoblender
   (``tracked_*``); de un fichero, su tamaño y su fecha. Una tabla que ya no está (ni en
   ``sqlite_master`` ni en ``gpkg_contents``) o un fichero que no está **falta**; lo importado de
   una tabla sin sus disparadores de protección está **dañado** sin más (ADR-0025 §4).
2. **Hash de contenido** de lo que salta (:func:`~.registry.content_digest`, con el lector y el
   normalizador del dato, cancelable entre trozos), y **veredicto** (:func:`assess`): el mismo
   contenido (cambió solo el contenedor, un ``VACUUM``, la tabla rehecha), otro contenido en un
   dato no inmutable (**edición externa**, RF-008-21) o en lo importado (**dañado**).
3. **Registro** (:func:`record`), en la transacción de escritura de quien llama: el mismo
   contenido deja el seguimiento al día (y repone los disparadores de una tabla rehecha); una
   edición externa es una operación ``core.external_edit`` hecha fuera (ejecutor ``external``)
   que consume la versión anterior y produce la nueva, con su cambio y su evento, sin deshacer
   nada; lo que depende del dato queda obsoleto por la caché de la región. Si su módulo no lo
   declara editable a mano, además queda **bloqueado** (RF-008-56) hasta aceptar la edición
   con un motivo, recalcularlo o reimportarlo (T32). Lo que falta y lo dañado cambian de estado
   con su evento.

Solo se comprueban los datos seguidos (ni ``exports`` ni ``duckdb``) vigentes o bloqueados: lo
que falta o está dañado espera a reimportarse (o, lo que falta, a la comprobación de T32). Python
puro (ADR-0004): al importarse no importa ``core.provenance`` ni ``core.project``, que se cargan
al registrar (``core.provenance`` importa ``core.datasets``).
"""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..content.encoder import ContentDigest
from ..timeutil import format_utc
from . import registry, tracking
from .model import DatasetRecord, DatasetStatus, Store
from .registry import content_digest, spec_of
from .tracking import TableState

if TYPE_CHECKING:
    from ..provenance.operations import OperationProject

EDITED_ROLE = "edited"
"""El papel del dato en su operación ``core.external_edit`` (lo que consume y lo que
produce)."""
CHECKED_STATUSES: tuple[DatasetStatus, ...] = (DatasetStatus.CURRENT, DatasetStatus.BLOCKED)
"""Los estados de un dato que se comprueban: lo que falta o está dañado no se vuelve a mirar
aquí."""

__all__ = [
    "CHECKED_STATUSES",
    "EDITED_ROLE",
    "DatasetFinding",
    "DatasetProbe",
    "DatasetVerdict",
    "Signal",
    "assess",
    "checkable",
    "content_digest",
    "probe_dataset",
    "record",
    "spec_of",
]


class Signal(StrEnum):
    """Lo que ve el prefiltro de un dato (:func:`probe_dataset`)."""

    UNCHANGED = "unchanged"  # todo como tras la última escritura de Geoblender
    MOVED = "moved"  # cambió algo del contenedor: hay que hashearlo
    MISSING = "missing"  # la tabla o el fichero ya no están (RF-008-57)
    UNPROTECTED = "unprotected"  # lo importado sin sus disparadores de protección


class DatasetVerdict(StrEnum):
    """Lo que se concluye de un dato (:func:`assess`)."""

    UNCHANGED = "unchanged"  # el prefiltro no saltó
    SAME = "same"  # mismo contenido: solo cambió el contenedor
    EDITED = "edited"  # otro contenido en un dato no inmutable: edición externa (RF-008-21)
    MISSING = "missing"  # falta (RF-008-57)
    DAMAGED = "damaged"  # lo importado cambió o perdió su protección (ADR-0025 §4)


@dataclass(frozen=True)
class DatasetProbe:
    """El prefiltro de un dato: su registro, lo que se vio (:class:`Signal`) y, de un fichero,
    su tamaño y su fecha."""

    record: DatasetRecord
    signal: Signal
    size: int | None = None
    mtime_ns: int | None = None

    @property
    def needs_hash(self) -> bool:
        """Si hay que calcular su hash de contenido para decidir."""
        return self.signal is Signal.MOVED


@dataclass(frozen=True)
class DatasetFinding:
    """Lo que se concluyó de un dato: su registro (antes), el veredicto, su estado después, el
    hash visto y, si se registró una edición externa, su operación."""

    record: DatasetRecord
    verdict: DatasetVerdict
    status: DatasetStatus
    digest: ContentDigest | None = None
    operation_uid: str | None = None

    @property
    def changed(self) -> bool:
        """Si hay algo que registrar (más que el seguimiento al día)."""
        return self.verdict in (DatasetVerdict.EDITED, DatasetVerdict.MISSING,
                                DatasetVerdict.DAMAGED)

    @property
    def code(self) -> str | None:
        """El mensaje del aviso (``core.provenance.messages``): edición externa, falta o
        dañado; ``None`` si no hay nada que avisar."""
        return {
            DatasetVerdict.EDITED: "core.external_edit",
            DatasetVerdict.MISSING: "core.dataset_missing",
            DatasetVerdict.DAMAGED: "core.dataset_damaged",
        }.get(self.verdict)

    def values(self, input_name: str | None = None) -> dict[str, Any]:
        """Los valores de su aviso: su nombre, su ubicación y la entrada de lo importado."""
        return {"name": self.record.name, "locator": self.record.locator,
                "input": input_name if input_name is not None else self.record.input_uid}


def checkable(record: DatasetRecord) -> bool:
    """Si el dato se comprueba aquí: seguido y vigente o bloqueado."""
    return record.tracked and record.status in CHECKED_STATUSES


def _path(project: Any, record: DatasetRecord) -> Path:
    return Path(project.root, *record.locator.split("/"))


def probe_dataset(project: Any, record: DatasetRecord,
                  tables: Mapping[str, TableState]) -> DatasetProbe:
    """El prefiltro del dato ``record`` (véase el módulo, paso 1): ``tables``, el estado de las
    tablas de ``project.gpkg`` (:func:`~.tracking.table_states`; hace falta el de la suya si es
    una tabla). Del proyecto usa su raíz (``root``). No escribe ni lee el contenido.
    :class:`ValueError` si el dato no se sigue."""
    if not record.tracked:
        raise ValueError(f"el dato «{record.name}» no se sigue ({record.store}): no se comprueba")
    if record.store is Store.GPKG:
        state = tables.get(record.locator)
        if state is None:
            raise ValueError(f"falta el estado de la tabla «{record.locator}» del dato "
                             f"«{record.name}» (table_states)")
        if not (state.registered and state.exists):
            return DatasetProbe(record, Signal.MISSING)
        if record.immutable:
            selector = record.selector if record.selector and "equals" in record.selector else None
            names = tracking.protection_trigger_names(record.locator, selector)
            if any(name not in state.triggers for name in names):
                return DatasetProbe(record, Signal.UNPROTECTED)
        moved = (state.last_change != record.tracked_last_change
                 or state.schema_sha256 != record.tracked_schema_sha256
                 or not state.tracked)
        return DatasetProbe(record, Signal.MOVED if moved else Signal.UNCHANGED)
    try:
        found = os.stat(_path(project, record))
    except FileNotFoundError:
        return DatasetProbe(record, Signal.MISSING)
    if not stat.S_ISREG(found.st_mode):
        return DatasetProbe(record, Signal.MISSING)
    moved = (found.st_size, found.st_mtime_ns) != (record.tracked_size, record.tracked_mtime_ns)
    return DatasetProbe(record, Signal.MOVED if moved else Signal.UNCHANGED, found.st_size,
                        found.st_mtime_ns)


def assess(probe: DatasetProbe, digest: ContentDigest | None = None) -> DatasetFinding:
    """El veredicto de un dato (véase el módulo, paso 2) con su prefiltro y, si saltó, el hash
    de su contenido actual (:func:`~.registry.content_digest`). No escribe nada.
    :class:`ValueError` si hacía falta el hash y no se da."""
    record = probe.record
    if probe.signal is Signal.MISSING:
        return DatasetFinding(record, DatasetVerdict.MISSING, DatasetStatus.MISSING)
    if probe.signal is Signal.UNPROTECTED:
        return DatasetFinding(record, DatasetVerdict.DAMAGED, DatasetStatus.DAMAGED)
    if probe.signal is Signal.UNCHANGED:
        return DatasetFinding(record, DatasetVerdict.UNCHANGED, record.status)
    if digest is None:
        raise ValueError(f"el dato «{record.name}» necesita su hash de contenido: el prefiltro "
                         "saltó")
    if digest.content_sha256 == record.content_sha256:
        return DatasetFinding(record, DatasetVerdict.SAME, record.status, digest)
    if record.immutable:
        return DatasetFinding(record, DatasetVerdict.DAMAGED, DatasetStatus.DAMAGED, digest)
    status = DatasetStatus.CURRENT if record.qgis_editable else DatasetStatus.BLOCKED
    return DatasetFinding(record, DatasetVerdict.EDITED, status, digest)


# --- Registro --------------------------------------------------------------------------------


def _event(conn: sqlite3.Connection, project: Any, kind: str, uid: str, message: str,
           data: Mapping[str, Any], at: str) -> None:
    """Su evento en ``gb_event`` (``kind``: el nombre de ``core.project.events.EventKind``).
    Se importa aquí: ``core.project`` pasa por ``core.provenance``, que importa este
    paquete."""
    from ..project.events import EventKind, record_event

    record_event(conn, EventKind[kind], message, session=project.session, at=at,
                 entity_kind="dataset", entity_uid=uid, data=dict(data))


def _render(code: str, **values: Any) -> str:
    from ..provenance.messages import render

    return render(code, **values)


def _input_name(conn: sqlite3.Connection, record: DatasetRecord) -> str | None:
    if record.input_uid is None:
        return None
    row = conn.execute("SELECT name FROM gb_input WHERE uid = ?", (record.input_uid,)).fetchone()
    return record.input_uid if row is None else str(row[0])


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


def _external_edit(conn: sqlite3.Connection, project: OperationProject,
                   finding: DatasetFinding, now: str) -> DatasetFinding:
    """La edición externa (RF-008-21, D9): una operación ``core.external_edit`` que consume la
    versión anterior del dato y produce la nueva, completada en ``conn``; si su módulo no lo
    declara editable a mano, el dato queda bloqueado (RF-008-56). Con su evento."""
    from ..provenance.contract import EXTERNAL_EDIT
    from ..provenance.operations import Executor, Use, begin_in_transaction

    record = finding.record
    blocked = finding.status is DatasetStatus.BLOCKED
    text = _render("core.external_edit", name=record.name)
    if blocked:
        text = f"{text} {_render('core.dataset_blocked', name=record.name)}"
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


def record(conn: sqlite3.Connection, project: OperationProject,
           finding: DatasetFinding) -> DatasetFinding:
    """Registra lo concluido de un dato (véase el módulo, paso 3) en la transacción de
    escritura ``conn`` de quien llama (no la confirma) y lo devuelve (con la operación de la
    edición externa, si la hubo). Lo que no saltó no escribe nada. Las comprobaciones de
    ``core.provenance.operations`` (``core.read_only``, ``core.operation_unregistered`` si no
    está registrado ``core.external_edit``) y de ``core.datasets`` rechazan sin escribir."""
    record_ = finding.record
    now = format_utc(project.clock.now())
    if finding.verdict is DatasetVerdict.UNCHANGED:
        return finding
    if finding.verdict is DatasetVerdict.SAME:
        _keep_tracking(conn, project, record_, now)
        return finding
    if finding.verdict is DatasetVerdict.EDITED:
        return _external_edit(conn, project, finding, now)
    registry.set_status(conn, project, record_.uid, finding.status)
    kind = "DATASET_MISSING" if finding.verdict is DatasetVerdict.MISSING else "DATASET_DAMAGED"
    values = finding.values(_input_name(conn, record_))
    data: dict[str, Any] = {"name": record_.name, "store": str(record_.store),
                            "locator": record_.locator, "input_uid": record_.input_uid}
    if finding.digest is not None:
        data["seen_sha256"] = finding.digest.content_sha256
    _event(conn, project, kind, record_.uid, _render(str(finding.code), **values), data, now)
    return finding
