# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que la vista dice de un dato del proyecto (spec 006, T27; RF-006-29; plan 006 §5.6.7).

Al cargar un dato en la vista de Blender, cada objeto lleva en ``Object.geoblender`` lo que el
proyecto sabe de él en ese momento: su registro de ``gb_dataset`` (uid, nombre, módulo, estado
y hash de contenido ``gbch/1``), si está obsoleto según la caché ``gb_stale`` de la 008
(``core.provenance.stale``; la marca en vivo y «Refrescar» son de la 009) y la fecha en que
terminó la operación que escribió su contenido. :func:`dataset_view` lo lee de un dato vivo
(vigente, que falta, bloqueado o dañado) y :func:`live_datasets` lista los vivos de todos los
módulos (lo que el diálogo de «Cargar en la vista…» ofrece si su módulo registró su cargador).

Solo lee, en una instantánea: cargar o descargar de la vista no escribe nada en el proyecto ni
registra ninguna operación (plan 006 §5.6.4). Python puro (ADR-0004).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Protocol

from ..datasets import registry as dataset_registry
from ..datasets.model import LIVE_STATUSES, RECORD_COLUMNS, DatasetRecord
from .stale import DATASET, item_causes

__all__ = ["DatasetView", "dataset_view", "live_datasets"]


class ReadableProject(Protocol):
    """Lo que se usa del proyecto: una conexión de lectura."""

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


@dataclass(frozen=True, slots=True)
class DatasetView:
    """Lo que la vista dice de un dato vivo: su registro (``gb_dataset``), si está obsoleto
    según la caché ``gb_stale`` y ``date``, la fecha (UTC, ``AAAA-MM-DDTHH:MM:SS.mmmZ``) en que
    terminó la operación que escribió su contenido (vacía si el proyecto no la tiene)."""

    record: DatasetRecord
    stale: bool
    date: str


@contextmanager
def _reading(project: ReadableProject,
             conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """Una conexión de lectura (la de quien llama o una nueva) con todas las lecturas en la
    misma instantánea."""
    if conn is not None:
        yield conn
        return
    with project.read() as reading:
        reading.execute("BEGIN")
        try:
            yield reading
        finally:
            reading.execute("ROLLBACK")


def dataset_view(project: ReadableProject, ref: str, *,
                 conn: sqlite3.Connection | None = None) -> DatasetView | None:
    """Lo que la vista dice del dato vivo ``ref`` (su uid o su nombre), o ``None`` si el
    proyecto no tiene ningún dato vivo así (uno sustituido o descartado ya no se muestra).
    ``conn``: una conexión de lectura de quien llama (por defecto, una nueva)."""
    if not isinstance(ref, str):
        raise TypeError(f"un dato se indica por su uid o su nombre, no {ref!r}")
    with _reading(project, conn) as reading:
        record = dataset_registry.get(reading, ref)
        if record is None or not record.live:
            return None
        stale = bool(item_causes(reading, DATASET, record.uid))
        found = reading.execute("SELECT finished_at FROM gb_operation WHERE uid = ?",
                                (record.operation_uid,)).fetchone()
    date = "" if found is None or found[0] is None else str(found[0])
    return DatasetView(record, stale, date)


def live_datasets(project: ReadableProject, *,
                  conn: sqlite3.Connection | None = None) -> list[DatasetRecord]:
    """Los datos vivos del proyecto (vigentes, que faltan, bloqueados o dañados) de todos los
    módulos, por nombre."""
    live = tuple(str(status) for status in LIVE_STATUSES)
    with _reading(project, conn) as reading:
        rows = reading.execute(
            f"SELECT {', '.join(RECORD_COLUMNS)} FROM gb_dataset WHERE status IN "
            f"({', '.join('?' for _ in live)}) ORDER BY name", live).fetchall()
    return [DatasetRecord.from_row(row) for row in rows]
