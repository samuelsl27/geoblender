# SPDX-License-Identifier: GPL-3.0-or-later
"""Ficha de un dato del proyecto y cifras de varios datos (spec 010; RF-010-06, RF-010-08;
ADR-0025; plan 010 §5.3.1, A6, A8, D-16 y D-17; con las versiones de la spec 009: RF-009-20,
RF-009-30, D-9, plan 009 §5.3.2 y A11).

:func:`item_card` lee, en una instantánea y sin escribir nada, lo que enseña N ▸ Proyecto ▸
Elemento activo de un dato (:class:`ItemCard`):

- su registro (nombre, tipo, estado…) y si está obsoleto (la caché ``gb_stale``; solo un dato
  vivo puede estarlo, como «! n obsoletos» de la 008);
- su versión: la de un dato de versión, «V01 · Definitiva» (su código y su título), y su
  revisión (:class:`RevisionMark`): lo «en curso», la revisión abierta de su versión, si el
  dato está vivo (D-23: su contenido de hoy es lo de la abierta, también si se calculó en una
  ya congelada); lo «vigente», su última revisión congelada (D-9), con su marca «alterada»; y,
  en una versión SUPERADO o DESCARTADO, la revisión cerrada al superarse («en curso (r2) ·
  vigente: r1», «cerrada (r2) · congelada: r1»). Un dato del proyecto (y todo en un proyecto
  del esquema 2 abierto en solo lectura, sin versiones), ninguna: ``None`` («—»);
- la operación que escribió su contenido actual (:class:`OperationSummary`: su tipo, la versión
  de su algoritmo, cuándo terminó, la versión de Geoblender y de sus bibliotecas y dónde se
  ejecutó);
- ↑ sus entradas (:class:`Link`): lo que consumió esa operación (``gb_operation_io``,
  ``direction = 'in'``), cada uno con el hash que consumió y su papel, y, si es lo importado de
  una entrada, esa entrada, que registró su operación (con su hash y el papel
  :data:`IMPORTED_ROLE`); de cada una, su nombre y su estado de hoy;
- ↓ sus derivados: los datos vivos que escribieron las operaciones vivas (hechas y sin
  sustituir) que lo consumen, en cualquiera de sus versiones (las que consumieron una anterior
  son las obsoletas), cada uno con su hash de hoy y su papel de salida en esa operación;
- la marca de obsoleto de cada uno;
- sus cifras: las que registró la operación que escribió su contenido, con su unidad y su tipo,
  sin marcas (las marcas leen el grafo entero: D-16). Una cifra de una operación que no escribe
  datos (el área de un límite) no es de ningún dato;
- de un dato de versión, las cifras vigentes de su versión: las de su última revisión congelada,
  tal como quedaron anotadas al congelarla (``core.versions.read.version_figures``; D-9), no
  las «en curso» (RF-009-20).

Es el primer nivel de la procedencia, por consultas directas (2,5 ms con D-13, plan §2.2); la
cadena entera es la de la 008 (``core.provenance.lineage.lineage``), a un clic.

:func:`dataset_figures` da las cifras de varios datos (las de la operación que escribió el
contenido actual de cada uno, como la ficha) con sus marcas (RF-008-31,
``core.provenance.lineage.figure_marks``, que lee el grafo entero: «Cifras de la selección» es
una orden explícita) o sin ellas (lo que se anota en cada objeto al cargarlo y al refrescar,
D-17). Nada se mide.

Ninguna consulta recorre entera ``gb_operation_io`` ni ``gb_stale``: van por sus índices y por la
clave de ``gb_stale``, con el orden de las uniones fijado con ``CROSS JOIN`` (``docs/trampas.md``
§6). ``gb_figure`` no tiene índice por operación (esta spec no cambia el esquema): sus cifras se
leen con un recorrido por cada :data:`~.state.CHUNK` operaciones. Python puro (ADR-0004).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from ..datasets.model import DatasetRecord
from ..provenance.figures import RECORD_COLUMNS as FIGURE_COLUMNS
from ..provenance.figures import FigureRecord
from ..provenance.graph import DATASET, INPUT, versioned
from ..provenance.importer import IMPORTED_ROLE
from ..provenance.lineage import FigureMarks, figure_marks
from ..provenance.operations import OperationStatus
from ..versions import read as versions_read
from ..versions.model import EDITABLE, RevisionState, VersionStatus, render
from .state import _chunks, _records, _snapshot, _stale

__all__ = [
    "DATASET",
    "IMPORTED_ROLE",
    "INPUT",
    "DatasetFigures",
    "ItemCard",
    "Link",
    "OperationSummary",
    "RevisionMark",
    "dataset_figures",
    "item_card",
]

_DONE = str(OperationStatus.DONE)
_OPERATION = (
    "SELECT uid, op_type, op_version, finished_at, geoblender_version, software, executor "
    "FROM gb_operation WHERE uid = ?"
)
_CONSUMED = (
    "SELECT item_kind, item_uid, content_sha256, role FROM gb_operation_io "
    "WHERE operation_uid = ? AND direction = 'in' ORDER BY fid"
)
_INPUTS = "SELECT uid, name, status, content_sha256 FROM gb_input WHERE uid IN ({marks})"
# Las salidas de las operaciones vivas que consumieron el dato, de él a la operación y de ella a
# lo que escribió, por los índices de gb_operation_io (el CROSS JOIN fija ese orden).
_DERIVED = (
    "SELECT made.item_uid, made.role FROM gb_operation_io AS used "
    "CROSS JOIN gb_operation AS op ON op.uid = used.operation_uid "
    "CROSS JOIN gb_operation_io AS made ON made.operation_uid = used.operation_uid "
    "WHERE used.item_kind = 'dataset' AND used.item_uid = ? AND used.direction = 'in' "
    f"AND op.status = '{_DONE}' AND op.superseded_by IS NULL "
    "AND made.direction = 'out' AND made.item_kind = 'dataset' AND made.item_uid <> ? "
    "ORDER BY op.fid, made.fid"
)
_FIGURES = f"SELECT {FIGURE_COLUMNS} FROM gb_figure WHERE operation_uid IN ({{marks}}) ORDER BY fid"


class ReadableProject(Protocol):
    """Lo que se usa del proyecto: una conexión de lectura."""

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


@dataclass(frozen=True)
class Link:
    """Una entrada o un derivado de un dato en su ficha: ``kind``, :data:`DATASET` (un dato) o
    :data:`INPUT` (una entrada registrada); su uid, su nombre y su estado de hoy (en minúsculas,
    como los guarda el proyecto); ``content_sha256``, el hash que consumió la operación del dato
    (una entrada) o el de hoy (un derivado); ``role``, su papel en esa operación (de un derivado,
    su papel de salida; de la entrada de lo importado, :data:`IMPORTED_ROLE`); ``stale``, si está
    obsoleto (solo un dato vivo puede estarlo)."""

    kind: str
    uid: str
    name: str
    status: str
    content_sha256: str
    role: str
    stale: bool


@dataclass(frozen=True)
class OperationSummary:
    """La operación que escribió el contenido de un dato: su uid, su tipo, la versión de su
    algoritmo, cuándo terminó (UTC; ``None`` si no terminó), la versión de Geoblender, las de sus
    bibliotecas (``{nombre: versión}``) y dónde se ejecutó (``blender``, ``job_thread``…)."""

    uid: str
    op_type: str
    op_version: str
    finished_at: str | None
    geoblender_version: str
    software: Mapping[str, str]
    executor: str


@dataclass(frozen=True)
class RevisionMark:
    """La versión de un dato de versión y sus revisiones en su ficha (spec 009; RF-009-20, D-9,
    D-23; plan A11): el uid, el código, el título y el estado de la versión; ``in_progress``,
    el número de su revisión abierta si el dato está vivo (lo «en curso»); ``current``, el de
    su última revisión congelada (lo vigente de la versión, D-9) y ``current_altered``, si está
    marcada «alterada» (RF-009-09); ``closed``, el de la revisión cerrada al superarse o
    descartarse la versión (RF-009-25). ``None``, si no la hay."""

    version_uid: str
    code: str
    title: str
    status: VersionStatus
    in_progress: int | None
    current: int | None
    current_altered: bool
    closed: int | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", VersionStatus(self.status))

    @property
    def label(self) -> str:
        """«V01 · Definitiva»."""
        return f"{self.code} · {self.title}"

    def text(self, language: str = "es") -> str:
        """Sus revisiones en ``language`` (``"es"`` o ``"en"``): lo abierto, «en curso (r2)»,
        o, sin abierta, la cerrada al superarse, «cerrada (r2)»; y lo último congelado,
        «vigente: r1» en una versión BORRADOR o VIGENTE y «congelada: r1» en una SUPERADO o
        DESCARTADO, con «(alterada)» si lo está; separados por « · »; sin revisiones, «».
        :class:`ValueError` con un idioma que no es de Geoblender."""
        parts: list[str] = []
        if self.in_progress is not None:
            parts.append(render("core.version_revision_in_progress", language=language,
                                revision=f"r{self.in_progress}"))
        elif self.closed is not None:
            parts.append(render("core.version_revision_closed", language=language,
                                revision=f"r{self.closed}"))
        if self.current is not None:
            shown = f"r{self.current}"
            if self.current_altered:
                shown = render("core.version_revision_altered", language=language,
                               revision=shown)
            code = ("core.version_revision_current" if self.status in EDITABLE
                    else "core.version_revision_frozen")
            parts.append(render(code, language=language, revision=shown))
        return " · ".join(parts)

    def heading(self, language: str = "es") -> str:
        """La versión con sus revisiones: «V01 · Definitiva — en curso (r2) · vigente: r1»
        (sin revisiones, solo la versión)."""
        text = self.text(language)
        return f"{self.label} — {text}" if text else self.label


@dataclass(frozen=True)
class ItemCard:
    """La ficha de un dato (véase el módulo): su registro, si está obsoleto, su versión
    («V01 · Definitiva»; ``None``, del proyecto), la operación que escribió su contenido
    (``None`` si el proyecto no la tiene), sus entradas (``upstream``), sus derivados
    (``downstream``) y las cifras de su operación, en su orden; de un dato de versión, su
    revisión (``revision``: lo «en curso» y lo vigente) y las cifras vigentes de su versión
    (``frozen_figures``, las de su última revisión congelada, D-9)."""

    record: DatasetRecord
    stale: bool
    version: str | None
    operation: OperationSummary | None
    upstream: tuple[Link, ...]
    downstream: tuple[Link, ...]
    figures: tuple[FigureRecord, ...]
    revision: RevisionMark | None = None
    frozen_figures: tuple[FigureRecord, ...] = ()


@dataclass(frozen=True)
class DatasetFigures:
    """Las cifras de un dato (las de la operación que escribió su contenido), en su orden, y sus
    marcas por uid de cifra (vacías si no se pidieron)."""

    record: DatasetRecord
    figures: tuple[FigureRecord, ...]
    marks: Mapping[str, FigureMarks]


def _uid(value: object, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{what}: un dato se indica por su uid, un texto no vacío, no {value!r}")
    return value


def _uid_list(values: object) -> list[str]:
    """Los uid de ``values``, sin repetir y en su orden."""
    if isinstance(values, str | bytes) or not isinstance(values, Iterable):
        raise TypeError(f"dataset_figures: una lista de uid de datos, no {values!r}")
    return list(dict.fromkeys(_uid(value, "dataset_figures") for value in values))


def _operation(conn: sqlite3.Connection, uid: str) -> OperationSummary | None:
    row = conn.execute(_OPERATION, (uid,)).fetchone()
    if row is None:
        return None
    op_uid, op_type, op_version, finished_at, geoblender_version, software, executor = row
    libraries = {str(name): str(version) for name, version in json.loads(software).items()}
    return OperationSummary(str(op_uid), str(op_type), str(op_version),
                            None if finished_at is None else str(finished_at),
                            str(geoblender_version), MappingProxyType(libraries), str(executor))


def _figures(conn: sqlite3.Connection,
             operations: Collection[str]) -> dict[str, tuple[FigureRecord, ...]]:
    """Las cifras de cada operación de ``operations``, en su orden (un recorrido de
    ``gb_figure`` por trozo)."""
    found: dict[str, list[FigureRecord]] = {}
    for chunk in _chunks(operations):
        sql = _FIGURES.format(marks=", ".join("?" for _ in chunk))
        for row in conn.execute(sql, chunk):
            figure = FigureRecord.from_row(row)
            found.setdefault(figure.operation_uid, []).append(figure)
    return {uid: tuple(figures) for uid, figures in found.items()}


def _inputs(conn: sqlite3.Connection,
            uids: Collection[str]) -> dict[str, tuple[str, str, str]]:
    """El nombre, el estado y el hash de hoy de cada entrada de ``uids``."""
    found: dict[str, tuple[str, str, str]] = {}
    for chunk in _chunks(uids):
        sql = _INPUTS.format(marks=", ".join("?" for _ in chunk))
        for uid, name, status, content in conn.execute(sql, chunk):
            found[str(uid)] = (str(name), str(status), str(content))
    return found


def _consumed(conn: sqlite3.Connection,
              record: DatasetRecord) -> list[tuple[str, str, str, str]]:
    """Lo que consumió la operación que escribió ``record`` (clase, uid, hash consumido y
    papel), en su orden, y al final, si es lo importado de una entrada que no está ya entre ello,
    esa entrada con su hash de hoy (se completa al leerla)."""
    rows = [(str(kind), str(uid), str(content), str(role))
            for kind, uid, content, role in conn.execute(_CONSUMED, (record.operation_uid,))]
    if record.input_uid is not None and (INPUT, record.input_uid) not in {
            (kind, uid) for kind, uid, _content, _role in rows}:
        rows.append((INPUT, record.input_uid, "", IMPORTED_ROLE))
    return rows


def _derived(conn: sqlite3.Connection, uid: str) -> list[tuple[str, str]]:
    """Los datos (uid y papel de salida) que escribieron las operaciones vivas que consumieron
    ``uid``, sin repetir y en su orden."""
    found: dict[str, str] = {}
    for item_uid, role in conn.execute(_DERIVED, (uid, uid)):
        found.setdefault(str(item_uid), str(role))
    return list(found.items())


def _version_of(conn: sqlite3.Connection, record: DatasetRecord
                ) -> tuple[RevisionMark | None, tuple[FigureRecord, ...]]:
    """La versión del dato ``record`` con sus revisiones y las cifras vigentes de la versión
    (D-9); ``None`` y ninguna, si es del proyecto o el proyecto no tiene versiones."""
    if not versioned(conn):
        return None, ()
    version_uid = versions_read.dataset_versions(conn, (record.uid,)).get(record.uid, "")
    version = versions_read.version(conn, version_uid) if version_uid else None
    if version is None:
        return None, ()
    revisions = versions_read.revisions(conn, version.uid)
    opened = [revision.number for revision in revisions if revision.state is RevisionState.OPEN]
    closed = [revision.number for revision in revisions
              if revision.state is RevisionState.CLOSED]
    frozen = [revision for revision in revisions if revision.state is RevisionState.FROZEN]
    current = frozen[-1] if frozen else None  # por número: la última
    mark = RevisionMark(version.uid, version.code, version.title, version.status,
                        opened[-1] if opened and record.live else None,
                        None if current is None else current.number,
                        current is not None and current.altered,
                        closed[-1] if closed else None)
    if current is None:
        return mark, ()
    return mark, versions_read.version_figures(conn, version.uid)


def item_card(project: ReadableProject, dataset_uid: str, *,
              conn: sqlite3.Connection | None = None) -> ItemCard | None:
    """La ficha del dato ``dataset_uid`` (véase el módulo), leída en una instantánea (la de
    ``conn``, una conexión de lectura de quien llama, o una nueva) sin escribir nada; ``None``
    si el proyecto no tiene ese dato. :class:`TypeError` si ``dataset_uid`` no es un texto no
    vacío."""
    uid = _uid(dataset_uid, "item_card")
    with _snapshot(project, conn) as reading:
        record = _records(reading, (uid,)).get(uid)
        if record is None:
            return None
        operation = _operation(reading, record.operation_uid)
        consumed = _consumed(reading, record)
        upstream_data = _records(reading, {item for kind, item, _c, _r in consumed
                                           if kind == DATASET})
        entries = _inputs(reading, {item for kind, item, _c, _r in consumed if kind == INPUT})
        derived = _derived(reading, uid)
        downstream_data = {item: found for item, found in
                           _records(reading, {item for item, _role in derived}).items()
                           if found.live}
        live = {item for item, found in (*upstream_data.items(), *downstream_data.items(),
                                         (uid, record)) if found.live}
        stale = _stale(reading, live) if live else frozenset()
        figures = _figures(reading, (record.operation_uid,)).get(record.operation_uid, ())
        mark, frozen_figures = _version_of(reading, record)
    upstream: list[Link] = []
    for kind, item, content, role in consumed:
        if kind == DATASET:
            found = upstream_data.get(item)
            name, status = (item, "") if found is None else (found.name, str(found.status))
            upstream.append(Link(DATASET, item, name, status, content, role, item in stale))
        else:
            name, status, current = entries.get(item, (item, "", content))
            upstream.append(Link(INPUT, item, name, status, content or current, role, False))
    downstream = tuple(
        Link(DATASET, item, found.name, str(found.status), found.content_sha256, role,
             item in stale)
        for item, role in derived if (found := downstream_data.get(item)) is not None
    )
    return ItemCard(record, uid in stale, None if mark is None else mark.label, operation,
                    tuple(upstream), downstream, figures, mark, frozen_figures)


def dataset_figures(project: ReadableProject, dataset_uids: Iterable[str], *,
                    marks: bool = True,
                    conn: sqlite3.Connection | None = None) -> tuple[DatasetFigures, ...]:
    """Las cifras de los datos ``dataset_uids`` (las de la operación que escribió el contenido
    actual de cada uno), en el orden pedido, sin repetir y sin los que el proyecto no tiene,
    leídas en una instantánea (la de ``conn`` o una nueva) sin escribir nada. Con ``marks``, las
    marcas de cada cifra según el estado de hoy de lo de aguas arriba (RF-008-31; lee el grafo
    entero, en la misma instantánea); sin ellas, vacías. :class:`TypeError` si ``dataset_uids``
    no es una lista de uid o ``marks`` no es verdadero o falso."""
    wanted = _uid_list(dataset_uids)
    if not isinstance(marks, bool):
        raise TypeError(f"marks es verdadero o falso, no {marks!r}")
    if not wanted:
        return ()
    with _snapshot(project, conn) as reading:
        records = _records(reading, wanted)
        by_operation = _figures(reading, {record.operation_uid for record in records.values()})
        found_marks: Mapping[str, FigureMarks] = {}
        if marks:
            found_marks = figure_marks(
                project, [figure.uid for figures in by_operation.values() for figure in figures],
                conn=reading)
    result: list[DatasetFigures] = []
    for uid in wanted:
        record = records.get(uid)
        if record is None:
            continue
        figures = by_operation.get(record.operation_uid, ())
        shown: dict[str, FigureMarks] = {figure.uid: found_marks[figure.uid]
                                         for figure in figures} if marks else {}
        result.append(DatasetFigures(record, figures, MappingProxyType(shown)))
    return tuple(result)
