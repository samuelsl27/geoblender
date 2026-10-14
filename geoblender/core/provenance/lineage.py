# SPDX-License-Identifier: GPL-3.0-or-later
"""Procedencia de una cifra o un dato, marcas de las cifras, cifra vigente y estado de lo
mostrado (spec 008; RF-008-23, RF-008-29, RF-008-30, RF-008-31; plan 008 §5.3.1, §5.3.4 y
§5.4.10).

Todo aquí **solo lee** el proyecto, en una instantánea (la de ``conn``, si se da: también la
transacción de escritura de quien llama, que ve lo aún no confirmado):

- :func:`lineage` (RF-008-29): la cadena de una cifra, un dato o una operación hasta sus
  entradas (:class:`LineageTree`). Empieza en la operación de la cifra, en la que escribió el
  contenido actual del dato o en la operación pedida y sube por las **versiones** que consumió
  cada operación (dato, hash: la que la escribió, :meth:`.graph.ProvenanceGraph.producer`)
  hasta las importaciones y sus entradas. Así la procedencia de una cifra antigua lleva a las
  versiones y a las entradas con que se calculó, aunque hoy estén sustituidas (spec §8,
  «Actualizar dos veces una entrada»). Cada operación (:class:`OperationLink`) va con los
  parámetros que leyó (:class:`ParameterLink`: valor, unidad, tipo, «sin confirmar», quién lo
  decidió y su estado de hoy), las versiones de su algoritmo, de Geoblender y de sus
  bibliotecas, quién, cuándo y dónde, si está obsoleta, con su causa, y los ajustes de su
  orden que enseña su tipo (:func:`settings_text`, ``OperationDef.settings``: la
  equidistancia tecleada de unas curvas, no su nombre ni su fichero; spec 006, T58); cada
  entrada (:class:`InputLink`), con su estado (también «cambiada · se mantiene la copia» y
  «sustituida»). :meth:`LineageTree.rows` la da como filas sangradas para el panel (una
  operación a la que se llega por dos caminos sale una vez; la segunda, marcada). Solo lee
  lo que está aguas arriba de lo pedido (:func:`.stale.upstream_region`, RNF-008-03), una vez,
  con el mismo resultado que sobre el grafo entero.
- :func:`figure_marks` (RF-008-31): las marcas de cada cifra (:class:`FigureMarks`), según el
  estado **de hoy** de lo de aguas arriba: «depende de una hipótesis» si algún parámetro que
  leyó su operación o una de aguas arriba es hoy HIPÓTESIS (pasarlo a ADOPTADO con el mismo
  valor la quita, y al revés la pone, sin dejar nada obsoleto), «depende de un valor sin
  confirmar» si alguno está hoy «sin confirmar» (RF-008-04) y «obsoleta» si lo está su
  operación. Los parámetros de aguas arriba de cada operación se calculan una vez por consulta
  como conjuntos de bits, por componentes fuertemente conexas (plan §5.4.10).
- :func:`current_figure` (RF-008-30): la cifra **vigente** de una clave y un ámbito, la de la
  operación más reciente (sin sustituir) que no está obsoleta; si todas lo están, la más
  reciente (que lleva su marca).
- :func:`result_state` (RF-008-23): cómo se presenta lo que se muestra (:class:`ResultStatus`):
  «resultado» si está guardado en el proyecto; «pendiente de incorporar» si es de un trabajo de
  la 004 aún en curso; «no incorporada», con el motivo, si se borró su trabajo; «vista previa,
  sin guardar» o «medición, no registrada» si solo está en la vista. Nada que el proyecto no
  tenga como hecho se presenta como resultado: lo de una operación que falló o lo que el
  proyecto no conoce es «vista previa, sin guardar».
- :func:`search_items` (T55; plan §5.5, la búsqueda del panel de la procedencia): las cifras
  vigentes cuya clave, cuyo nombre o cuyo ámbito contienen un texto y los datos vivos cuyo
  nombre lo contiene (:class:`LineageMatch`), para pedir su procedencia sin saber su uid.

La obsolescencia y la revisión a mano se leen de la caché ``gb_stale`` (:mod:`.stale`), como
la lista de lo obsoleto y «! n obsoletos»: la mantienen todos los caminos que escriben y la
comprobación de apertura la corrige entera. Python puro (ADR-0004).
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict, deque
from collections.abc import Collection, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from operator import itemgetter
from types import MappingProxyType
from typing import Any, Protocol

from ..i18n import LANGUAGES, translate
from ..inputs.model import InputStatus
from ..params.model import ParamKind, ParamValue
from ..params.store import decode_value
from ..units import DIMENSIONLESS
from .contract import FIGURES, OPERATIONS
from .figures import RECORD_COLUMNS as FIGURE_COLUMNS
from .figures import FigureRecord, ScopeValue, _local_date, _shown, scope_key
from .graph import (
    DATASET,
    DATASET_COLUMNS,
    INPUT,
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
    Version,
    changes_while_running,
    dataset_node,
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
from .messages import ProvenanceError, render
from .operations import JOB_EXECUTORS, OperationStatus
from .recompute import strong_components
from .schema import LIVE_DATASET_STATUSES
from .stale import (
    _OPERATIONS_OF_GROUPS,
    _OPERATIONS_OF_TYPES,
    OPERATION,
    _named,
    _reading,
    _select,
    _subjects,
    review_operations,
    upstream_region,
)


class LineageKind(StrEnum):
    """Lo que es una fila de la procedencia (:class:`LineageRow`) o lo que se pidió."""

    FIGURE = "figure"  # una cifra (gb_figure)
    DATASET = "dataset"  # un dato (gb_dataset), en una versión
    OPERATION = "operation"  # una operación (gb_operation)
    INPUT = "input"  # una entrada (gb_input)
    PARAMETER = "parameter"  # un parámetro que leyó una operación (gb_operation_param)
    SETTINGS = "settings"  # los ajustes de la orden de una operación (spec 006, T58)


class Mark(StrEnum):
    """Una marca de una cifra (RF-008-31), en el orden en que se muestran."""

    HYPOTHESIS = "hypothesis"  # depende de una hipótesis
    UNCONFIRMED = "unconfirmed"  # depende de un valor sin confirmar
    STALE = "stale"  # obsoleta


class ResultState(StrEnum):
    """Cómo se presenta lo que se muestra (RF-008-23)."""

    RESULT = "result"  # guardado en el proyecto
    PENDING = "pending"  # de un trabajo de la 004 aún sin incorporar
    NOT_INGESTED = "not_ingested"  # su trabajo se borró sin incorporarlo (con el motivo)
    PREVIEW = "preview"  # vista previa, sin guardar
    MEASUREMENT = "measurement"  # medición, no registrada


VIEW_STATES: tuple[ResultState, ...] = (ResultState.PREVIEW, ResultState.MEASUREMENT)
"""Lo que solo está en la vista: lo dice quien lo muestra (``view`` de :func:`result_state`)."""

_LIVE = ", ".join(f"'{status}'" for status in LIVE_DATASET_STATUSES)
_DONE = str(OperationStatus.DONE)
_HYPOTHESIS = ParamKind.HIPOTESIS


class ReadableProject(Protocol):
    """Lo que la procedencia usa del proyecto: una conexión de lectura y su nombre (para el
    rechazo)."""

    @property
    def name(self) -> str: ...

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


# --- Lo que se devuelve ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResultStatus:
    """Cómo se presenta lo que se muestra (RF-008-23): su estado, lo que se pidió, la
    operación de la que sale (si se sabe) y el motivo (el de «no incorporada» o el de una
    operación que no terminó bien)."""

    state: ResultState
    item_uid: str | None = None
    operation_uid: str | None = None
    reason: str | None = None

    @property
    def saved(self) -> bool:
        """Si es un resultado guardado en el proyecto (lo único que se presenta como tal)."""
        return self.state is ResultState.RESULT

    def text(self, *, language: str = "es") -> str:
        """«resultado», «pendiente de incorporar», «no incorporada: <motivo>», «vista previa,
        sin guardar» o «medición, no registrada», en ``language``."""
        return render(f"core.result_{self.state}", language=language, reason=self.reason)


@dataclass(frozen=True, slots=True)
class FigureMarks:
    """Las marcas de una cifra (RF-008-31; o de un dato o una operación, en su procedencia):
    las claves de los parámetros de aguas arriba que hoy son HIPÓTESIS (``hypotheses``) y que
    hoy están «sin confirmar» (``unconfirmed_params``), por clave; las causas de su
    obsolescencia (las de su operación; vacías si está al día) y si es la vigente de su clave y
    su ámbito (``current``; de un dato, si está vivo; de una operación, si no está
    sustituida)."""

    uid: str
    hypotheses: tuple[str, ...]
    unconfirmed_params: tuple[str, ...]
    causes: frozenset[Cause]
    current: bool

    @property
    def hypothesis(self) -> bool:
        """«depende de una hipótesis»."""
        return bool(self.hypotheses)

    @property
    def unconfirmed(self) -> bool:
        """«depende de un valor sin confirmar»."""
        return bool(self.unconfirmed_params)

    @property
    def stale(self) -> bool:
        """«obsoleta»."""
        return bool(self.causes)

    @property
    def marks(self) -> tuple[Mark, ...]:
        """Las marcas que lleva, en su orden."""
        return tuple(mark for mark, present in ((Mark.HYPOTHESIS, self.hypothesis),
                                                (Mark.UNCONFIRMED, self.unconfirmed),
                                                (Mark.STALE, self.stale)) if present)

    def texts(self, *, language: str = "es") -> tuple[str, ...]:
        """Los textos de sus marcas en ``language`` («depende de una hipótesis»…)."""
        return tuple(render(f"core.mark_{mark}", language=language) for mark in self.marks)


@dataclass(frozen=True, slots=True)
class ParameterLink:
    """Un parámetro que leyó una operación: lo que leyó (``rev``, ``value``, ``unit``,
    ``kind``, ``unconfirmed``; quién lo decidió, cuándo y su origen en esa revisión) y su
    estado de hoy (``current_*``); ``changed``, si hoy tiene otro valor o unidad (lo que deja
    obsoleta la operación). De uno CALCULADO, la operación de la cifra que se adoptó y si hoy
    está obsoleta (``source_*``: el panel lo dice sin cambiar nada)."""

    uid: str
    key: str
    scope: str
    rev: int
    value: ParamValue | None
    unit: str
    kind: ParamKind
    unconfirmed: bool
    decided_by: str | None
    decided_at: str | None
    source: str | None
    current_rev: int
    current_value: ParamValue | None
    current_unit: str
    current_kind: ParamKind
    current_unconfirmed: bool
    changed: bool
    source_operation_uid: str | None
    source_stale: bool

    @property
    def hypothesis(self) -> bool:
        """Si hoy es HIPÓTESIS."""
        return self.current_kind is _HYPOTHESIS

    def value_text(self, *, language: str = "es") -> str:
        """El valor que leyó con su unidad, como lo lee una persona («2,5 t/m³»)."""
        return _shown(self.value, self.unit, language)

    def current_value_text(self, *, language: str = "es") -> str:
        """El valor de hoy con su unidad."""
        return _shown(self.current_value, self.current_unit, language)


@dataclass(frozen=True, slots=True)
class InputUse:
    """Una entrada de una operación: la que consumió directamente, con su papel, o la que
    registró (su importación: ``role`` es ``None``)."""

    uid: str
    role: str | None


@dataclass(frozen=True, slots=True)
class InputLink:
    """Una entrada de la cadena en su estado de hoy (``gb_input``), con quién y cuándo se
    decidió ese estado, su registro, su entrega, su hash de contenido, sus CRS declarados, su
    importación y las entradas que sustituye y que la sustituyen."""

    uid: str
    name: str
    kind: str
    module: str
    status: InputStatus
    status_at: str | None
    status_by: str | None
    status_reason: str | None
    registered_by: str
    registered_at: str
    received_at: str | None
    received_from: str | None
    content_sha256: str
    crs_h: Mapping[str, Any]
    crs_v: Mapping[str, Any]
    operation_uid: str
    previous_uid: str | None
    successor_uid: str | None

    def status_text(self, *, language: str = "es") -> str:
        """«vigente», «cambiada», «cambiada · se mantiene la copia», «sustituida» o
        «descartada · registro, no usar»."""
        return render(f"core.input_status_{self.status}", language=language)

    def text(self, *, language: str = "es") -> str:
        """«Limites_v1: cambiada · se mantiene la copia (samuel@PC-01, 24/09/2026)»: su
        nombre, su estado y, si no está vigente, quién lo decidió y cuándo (día local)."""
        shown = f"{self.name}: {self.status_text(language=language)}"
        if self.status is not InputStatus.CURRENT and self.status_by and self.status_at:
            shown += f" ({self.status_by}, {_local_date(self.status_at)})"
        return shown


@dataclass(frozen=True, slots=True)
class DatasetLink:
    """Un dato en la versión que consumió una operación (o el dato pedido, en su versión
    actual): su estado y su hash de hoy, el papel con que se consumió, la operación que
    escribió esa versión (``producer_uid``), su entrada (lo importado) y su sucesor."""

    uid: str
    name: str
    module: str
    kind: str
    status: str
    content_sha256: str
    current_sha256: str
    role: str | None
    producer_uid: str | None
    input_uid: str | None
    superseded_by: str | None

    @property
    def current(self) -> bool:
        """Si esa versión es hoy el contenido de un dato vivo."""
        return self.status in LIVE_DATASET_STATUSES and self.content_sha256 == self.current_sha256


@dataclass(frozen=True, slots=True)
class OperationLink:
    """Un eslabón de la cadena: una operación con su tipo, la versión de su algoritmo, su
    estado, sus ajustes de grupo y de sustitución, la versión de Geoblender y de sus
    bibliotecas (``software``), dónde se ejecutó (``executor``, ``job_uid``, ``interpreter``,
    ``host``), quién la lanzó y cuándo; los parámetros que leyó, los datos que consumió (en su
    versión) y sus entradas; las operaciones de las que depende (``upstream``), sus causas de
    obsolescencia con su texto («Obsoleto: cambió Producción»), si espera revisión a mano y
    cómo se presenta lo suyo (:class:`ResultStatus`). Y los ajustes de su orden
    (``settings``, los de ``gb_operation.settings``) con el texto de los que enseña su tipo
    (``settings_text``: «Ajustes: Equidistancia = 2 m · Cota base = 0 m», o ``None``;
    :func:`settings_text`; spec 006, T58)."""

    uid: str
    op_type: str
    op_version: str
    module: str
    status: str
    status_reason: str | None
    repeatable: bool
    group_name: str | None
    group_uid: str | None
    supersedes_uid: str | None
    superseded_by: str | None
    geoblender_version: str
    software: Mapping[str, Any]
    executor: str
    job_uid: str | None
    interpreter: Mapping[str, Any] | None
    user_host: str
    host: str
    started_at: str
    finished_at: str | None
    settings: Mapping[str, Any]
    params: tuple[ParameterLink, ...]
    consumed: tuple[DatasetLink, ...]
    inputs: tuple[InputUse, ...]
    upstream: tuple[str, ...]
    causes: frozenset[Cause]
    stale_text: str | None
    review: bool
    result: ResultStatus
    settings_text: str | None

    @property
    def stale(self) -> bool:
        """Si el eslabón está obsoleto."""
        return bool(self.causes)


type LineageNode = FigureRecord | OperationLink | DatasetLink | InputLink | ParameterLink


@dataclass(frozen=True, slots=True)
class LineageRow:
    """Una fila sangrada de la procedencia (``depth``) con lo que muestra (``node``; la de
    los ajustes de una operación, la operación), el papel con que se consumió (un dato o una
    entrada) y si es una operación ya mostrada más arriba (``repeated``: sin sus ramas)."""

    depth: int
    kind: LineageKind
    node: LineageNode
    role: str | None = None
    repeated: bool = False

    @property
    def uid(self) -> str:
        """El uid de lo que muestra."""
        return self.node.uid


@dataclass(frozen=True, slots=True)
class LineageTree:
    """La procedencia de ``uid`` (``kind``: una cifra, un dato o una operación): la
    operación de la que sale (``root``), la cifra o el dato pedidos, cada operación de la
    cadena por orden de distancia (``operations``), sus entradas (``inputs``), las marcas de
    lo pedido y cómo se presenta (:class:`ResultStatus`)."""

    kind: LineageKind
    uid: str
    root: str
    figure: FigureRecord | None
    dataset: DatasetLink | None
    operations: Mapping[str, OperationLink]
    inputs: Mapping[str, InputLink]
    marks: FigureMarks
    result: ResultStatus

    @property
    def stale_operations(self) -> tuple[str, ...]:
        """Los eslabones obsoletos, por orden de distancia."""
        return tuple(uid for uid, node in self.operations.items() if node.stale)

    def rows(self) -> tuple[LineageRow, ...]:
        """La cadena como filas sangradas, de lo pedido hacia sus entradas: bajo cada
        operación, sus ajustes (una fila, la de :attr:`OperationLink.settings_text`, si su tipo
        enseña alguno; T58), sus parámetros, sus entradas y los datos que consumió, cada uno
        seguido de la operación que escribió su versión. Una operación a la que se llega otra
        vez sale marcada como repetida y sin sus ramas."""
        found: list[LineageRow] = []
        depth = 0
        if self.figure is not None:
            found.append(LineageRow(0, LineageKind.FIGURE, self.figure))
            depth = 1
        elif self.dataset is not None:
            found.append(LineageRow(0, LineageKind.DATASET, self.dataset))
            depth = 1
        shown: set[str] = set()
        pending: list[tuple[int, LineageKind, LineageNode, str | None]] = [
            (depth, LineageKind.OPERATION, self.operations[self.root], None)]
        while pending:
            level, kind, node, role = pending.pop()
            if isinstance(node, OperationLink) and kind is LineageKind.OPERATION:
                if node.uid in shown:
                    found.append(LineageRow(level, kind, node, repeated=True))
                    continue
                shown.add(node.uid)
                found.append(LineageRow(level, kind, node))
                below = level + 1
                children: list[tuple[int, LineageKind, LineageNode, str | None]] = [
                    *(((below, LineageKind.SETTINGS, node, None),) if node.settings_text
                      else ()),
                    *((below, LineageKind.PARAMETER, used, None) for used in node.params),
                    *((below, LineageKind.INPUT, self.inputs[use.uid], use.role)
                      for use in node.inputs),
                    *((below, LineageKind.DATASET, version, version.role)
                      for version in node.consumed),
                ]
                pending.extend(reversed(children))
                continue
            found.append(LineageRow(level, kind, node, role))
            if isinstance(node, DatasetLink) and node.producer_uid in self.operations:
                pending.append((level + 1, LineageKind.OPERATION,
                                self.operations[node.producer_uid], None))
        return tuple(found)


# --- Consultas ------------------------------------------------------------------------------

_FIGURE = f"SELECT {FIGURE_COLUMNS} FROM gb_figure WHERE uid = ?"
_FIGURES = f"SELECT {FIGURE_COLUMNS} FROM gb_figure WHERE uid IN ({{marks}})"
_DATASET_BY_UID = "SELECT uid, operation_uid FROM gb_dataset WHERE uid = ?"
_DATASET_BY_NAME = (
    f"SELECT uid, operation_uid FROM gb_dataset WHERE name = ? AND status IN ({_LIVE}) "
    "ORDER BY fid DESC LIMIT 1"
)
_OPERATION_STATE = "SELECT uid, status, executor, status_reason FROM gb_operation WHERE uid = ?"
_LOOSE_OPERATION = f"SELECT {OPERATION_COLUMNS} FROM gb_operation WHERE uid = ?"
_LOOSE_IO = f"SELECT {IO_COLUMNS} FROM gb_operation_io WHERE operation_uid = ? ORDER BY fid"
_LOOSE_PARAMS = (
    f"SELECT {PARAM_USE_COLUMNS} FROM gb_operation_param WHERE operation_uid = ? ORDER BY fid"
)
_DETAIL_COLUMNS = (
    "uid, op_type, op_version, module, status, status_reason, repeatable, group_name, "
    "group_uid, supersedes_uid, superseded_by, geoblender_version, software, executor, job_uid, "
    "interpreter, user_host, host, started_at, finished_at, settings"
)
_OPERATION_DETAILS = f"SELECT {_DETAIL_COLUMNS} FROM gb_operation WHERE uid IN ({{marks}})"
_USED_PARAMS = (
    "SELECT operation_uid, parameter_uid, key, scope, rev, value, unit, kind, unconfirmed, "
    "value_sha256 FROM gb_operation_param WHERE operation_uid IN ({marks}) ORDER BY fid"
)
_PARAMETERS_NOW = (
    "SELECT uid, rev, value, unit, kind, unconfirmed, value_sha256, operation_uid "
    "FROM gb_parameter WHERE uid IN ({marks})"
)
_DECISIONS = (
    "SELECT parameter_uid, rev, decided_by, decided_at, source FROM gb_parameter_history "
    "WHERE parameter_uid IN ({marks})"
)
_INPUT_DETAILS = (
    "SELECT uid, name, kind, module, status, status_at, status_by, status_reason, "
    "registered_by, registered_at, received_at, received_from, content_sha256, crs_h, crs_v, "
    "operation_uid, previous_uid FROM gb_input WHERE uid IN ({marks})"
)
_SUCCESSORS = "SELECT previous_uid, uid FROM gb_input WHERE previous_uid IN ({marks}) ORDER BY fid"
_SUPERSEDED_DATA = "SELECT uid, superseded_by FROM gb_dataset WHERE uid IN ({marks})"
_CACHED = (
    "SELECT item_uid, cause_kind, subject_uid FROM gb_stale WHERE item_kind = ? "
    "AND item_uid IN ({marks})"
)
_FIGURES_OF_KEY = (
    "SELECT f.uid, EXISTS (SELECT 1 FROM gb_stale AS s "
    f"WHERE s.item_kind = '{OPERATION}' AND s.item_uid = f.operation_uid) "
    "FROM gb_figure AS f JOIN gb_operation AS op ON op.uid = f.operation_uid "
    f"WHERE op.status = '{_DONE}' AND op.superseded_by IS NULL AND f.key = ? "
    "AND f.scope_key = ? ORDER BY f.fid"
)
# La región aguas arriba (_load_upstream): sus operaciones con todo lo que muestra la
# procedencia (y su fid), lo que consumen, quién escribió alguna versión de los datos que
# consumen, los datos con su sucesor y, enteras, las entradas y los parámetros del proyecto.
_REGION_OPERATIONS = f"SELECT fid, {_DETAIL_COLUMNS} FROM gb_operation WHERE uid IN ({{marks}})"
_REGION_CONSUMED = (
    f"SELECT {IO_COLUMNS} FROM gb_operation_io WHERE direction = 'in' "
    "AND operation_uid IN ({marks}) ORDER BY fid"
)
_WRITTEN = (  # sin orden: el grafo ordena a quién escribió cada versión
    f"SELECT {IO_COLUMNS} FROM gb_operation_io WHERE item_kind = '{DATASET}' "
    "AND direction = 'out' AND item_uid IN ({marks})"
)
_REGION_DATA = f"SELECT {DATASET_COLUMNS}, superseded_by FROM gb_dataset WHERE uid IN ({{marks}})"
_ALL_INPUTS = f"SELECT {INPUT_NODE_COLUMNS} FROM gb_input ORDER BY fid"
_ALL_PARAMETERS = f"SELECT {PARAMETER_COLUMNS} FROM gb_parameter ORDER BY fid"
_REGION_COLUMNS = ("fid, " + _DETAIL_COLUMNS).split(", ")
_head = itemgetter(*(_REGION_COLUMNS.index(column)
                     for column in OPERATION_COLUMNS.split(", ")))
"""Las columnas de :data:`OPERATION_COLUMNS` de una fila de ``_REGION_OPERATIONS``."""
_STATUS = _REGION_COLUMNS.index("status")


def _version(row: tuple[Any, ...]) -> Version:
    """La versión de una fila de :data:`IO_COLUMNS` (como :func:`.graph.version_of`)."""
    return Version(str(row[2]), str(row[3]), str(row[4]), str(row[5]))


@dataclass(frozen=True, slots=True)
class _Found:
    """Lo que se pidió: su clase, su uid, la operación de la que sale y la cifra."""

    kind: LineageKind
    uid: str
    operation_uid: str
    figure: FigureRecord | None = None


def _name(project: object) -> str:
    return str(getattr(project, "name", "?"))


def _item(item: object) -> str:
    if not isinstance(item, str) or not item:
        raise TypeError(f"se pide la procedencia de un uid (o del nombre de un dato vivo), no "
                        f"{item!r}")
    return item


def _find(conn: sqlite3.Connection, item: str) -> _Found | None:
    """La cifra, el dato (por uid o por el nombre de uno vivo) o la operación ``item``."""
    row = conn.execute(_FIGURE, (item,)).fetchone()
    if row is not None:
        figure = FigureRecord.from_row(row)
        return _Found(LineageKind.FIGURE, figure.uid, figure.operation_uid, figure)
    row = (conn.execute(_DATASET_BY_UID, (item,)).fetchone()
           or conn.execute(_DATASET_BY_NAME, (item,)).fetchone())
    if row is not None:
        return _Found(LineageKind.DATASET, str(row[0]), str(row[1]))
    row = conn.execute(_OPERATION_STATE, (item,)).fetchone()
    if row is not None:
        return _Found(LineageKind.OPERATION, str(row[0]), str(row[0]))
    return None


def _operation_status(item_uid: str, uid: str, status: object, executor: object,
                      reason: object) -> ResultStatus:
    """Cómo se presenta lo de una operación por su estado: hecha, «resultado»; en curso en un
    trabajo, «pendiente de incorporar»; «no incorporada» con el motivo; lo demás (en curso en
    el hilo de Blender, fallida, cancelada, interrumpida) no es un resultado: «vista previa,
    sin guardar», con su motivo."""
    text = None if reason is None else str(reason)
    if status == _DONE:
        return ResultStatus(ResultState.RESULT, item_uid, uid)
    if status == OperationStatus.NOT_INGESTED:
        return ResultStatus(ResultState.NOT_INGESTED, item_uid, uid, text)
    if status == OperationStatus.RUNNING and executor in JOB_EXECUTORS:
        return ResultStatus(ResultState.PENDING, item_uid, uid)
    return ResultStatus(ResultState.PREVIEW, item_uid, uid, text)


def _item_status(conn: sqlite3.Connection, found: _Found) -> ResultStatus:
    if found.kind is not LineageKind.OPERATION:
        return ResultStatus(ResultState.RESULT, found.uid, found.operation_uid)
    _uid, status, executor, reason = conn.execute(_OPERATION_STATE, (found.uid,)).fetchone()
    return _operation_status(found.uid, found.uid, status, executor, reason)


def _cached(conn: sqlite3.Connection, item_kind: str,
            uids: Collection[str]) -> dict[str, frozenset[Cause]]:
    """Las causas en la caché ``gb_stale`` de ``uids`` (``operation`` o ``dataset``); los
    que no tienen, al día."""
    found: dict[str, set[Cause]] = defaultdict(set)
    for uid, cause_kind, subject in _select(conn, _CACHED, uids, (item_kind,)):
        found[str(uid)].add(Cause(cause_kind, str(subject)))
    return {uid: frozenset(causes) for uid, causes in found.items()}


def _current_of(conn: sqlite3.Connection, key: str, wanted: str) -> str | None:
    """La cifra vigente (uid) de ``key`` en el ámbito ``wanted`` (``scope_key``): la de la
    operación hecha y sin sustituir más reciente que no está obsoleta según la caché; si todas
    lo están, la más reciente; ``None`` si no hay ninguna."""
    rows = [(str(uid), bool(stale)) for uid, stale in conn.execute(_FIGURES_OF_KEY,
                                                                    (key, wanted))]
    if not rows:
        return None
    fresh = [uid for uid, stale in rows if not stale]
    return (fresh or [uid for uid, _stale in rows])[-1]


def _json_mapping(text: object) -> Mapping[str, Any]:
    return MappingProxyType(dict(json.loads(str(text))))


def _setting(settings: Mapping[str, Any], key: str) -> tuple[bool, Any]:
    """Si ``settings`` tiene el ajuste ``key`` («.» entra en uno anidado) y su valor."""
    found: Any = settings
    for part in key.split("."):
        if not isinstance(found, Mapping) or part not in found:
            return False, None
        found = found[part]
    return True, found


def settings_text(op_type: str, settings: Mapping[str, Any], *,
                  language: str = "es") -> str | None:
    """Los ajustes de la orden de una operación de ``op_type`` que enseña su procedencia
    (RF-008-29; spec 006, T58): los que declara su tipo registrado (``OperationDef.settings``,
    en su orden) y guardó la operación (``settings``), cada uno con su nombre y su valor en
    ``language`` («Ajustes: Equidistancia = 2 m · Cota base = 0 m»): un número con su unidad
    y una elección con el nombre de la elegida (una que su tipo no declara, tal cual). Un
    número sin valor o que no es un número, un valor que no es de JSON simple y lo que el
    tipo no declara (nombres, ficheros, uids…) no se enseñan. ``None`` si no queda ninguno o
    si el tipo no está registrado."""
    defn = OPERATIONS.get(op_type)
    if defn is None:
        return None
    shown: list[str] = []
    for declared in defn.settings:
        present, value = _setting(settings, declared.key)
        if not present:
            continue
        if declared.unit is not None:
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            text = _shown(value, declared.unit, language)
        else:
            msgid = declared.choice_msgid(value)
            if msgid is not None:
                text = translate(language, msgid)
            elif value is not None and isinstance(value, str | int | float | bool):
                text = _shown(value, DIMENSIONLESS, language)
            else:
                continue
        shown.append(f"{translate(language, declared.label_msgid)} = {text}")
    if not shown:
        return None
    return render("core.operation_settings", language=language, settings=" · ".join(shown))


class _Decoded:
    """Lo decodificado de un texto JSON, una vez por texto en cada consulta (en una cadena
    larga se repiten los mismos ajustes, bibliotecas y valores); lo que da es inmutable."""

    def __init__(self) -> None:
        self._mappings: dict[str, Mapping[str, Any]] = {}
        self._values: dict[str, ParamValue | None] = {}

    def mapping(self, text: object) -> Mapping[str, Any]:
        key = str(text)
        found = self._mappings.get(key)
        if found is None:
            found = self._mappings[key] = _json_mapping(key)
        return found

    def value(self, text: str | None) -> ParamValue | None:
        if text is None:
            return None
        if text not in self._values:
            self._values[text] = decode_value(text)
        return self._values[text]


def _producers(graph: ProvenanceGraph, node: OperationNode) -> tuple[str, ...]:
    """Las operaciones que escribieron las versiones de dato que consumió ``node`` (sin ella
    misma), sin repetir y en su orden: :meth:`.graph.ProvenanceGraph.upstream`, también para
    una operación que no está hecha (no está en el grafo)."""
    found: list[str] = []
    for version in node.consumed:
        if version.item_kind != DATASET:
            continue
        producer = graph.producer(version.uid, version.content_sha256, excluding=node.uid)
        if producer is not None and producer not in found:
            found.append(producer)
    return tuple(found)


def _param_marks(graph: ProvenanceGraph,
                 parameter_uids: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """De los parámetros ``parameter_uids``, las claves de los que hoy son HIPÓTESIS y de los
    que hoy están «sin confirmar», ordenadas."""
    hypotheses: set[str] = set()
    unconfirmed: set[str] = set()
    for uid in parameter_uids:
        node = graph.parameters.get(uid)
        if node is None:
            continue
        if node.kind == _HYPOTHESIS:
            hypotheses.add(node.key)
        if node.unconfirmed:
            unconfirmed.add(node.key)
    return tuple(sorted(hypotheses)), tuple(sorted(unconfirmed))


# --- Procedencia ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Upstream:
    """Lo leído de la región aguas arriba de lo pedido (:func:`_load_upstream`): la parte del
    grafo que necesita su procedencia y, para no volver a leerlo, de cada operación de la región
    su fila de ``_OPERATION_DETAILS`` (``details``) y las de los parámetros que leyó, en su
    orden (``used``); las que no están hechas (la pedida, si no lo está: ``loose``); el sucesor
    de cada dato cargado y las causas de la caché de las operaciones de la región."""

    graph: ProvenanceGraph
    region: frozenset[str]
    details: Mapping[str, tuple[Any, ...]]
    used: Mapping[str, list[tuple[Any, ...]]]
    loose: Mapping[str, OperationNode]
    successors: Mapping[str, str | None]
    causes: Mapping[str, frozenset[Cause]]


def _load_upstream(conn: sqlite3.Connection, found: _Found) -> _Upstream:
    """Lo que necesita la procedencia de ``found``, de su región aguas arriba
    (:func:`.stale.upstream_region`) y sin nada de lo demás (RNF-008-03), en la instantánea de
    ``conn``:

    - las operaciones hechas de la región con lo que consumieron y leyeron, y lo que hace
      falta para que el productor de cada versión que consumieron
      (:meth:`.graph.ProvenanceGraph.producer`) sea el mismo que en el grafo entero;
    - esos datos (y el pedido), todas las entradas y todos los parámetros (los del proyecto:
      pocos);
    - para contar las causas de la caché de sus operaciones como el grafo entero
      (:func:`.graph.stale_text`): los datos que nombran, las operaciones de sus grupos y de sus
      algoritmos (sin lo que consumen) y lo que cambió mientras se calculaba cada una con
      causas (:attr:`.graph.ProvenanceGraph.during`).

    No sirve para deducir la obsolescencia: no tiene lo de aguas abajo ni todo lo que
    produjeron."""
    region = upstream_region(conn, (found.operation_uid,))
    ordered = sorted(region)  # una vez: _select ordena lo que recibe en cada consulta
    details: dict[str, tuple[Any, ...]] = {}
    heads: dict[str, tuple[Any, ...]] = {}
    done: set[str] = set()
    for row in _select(conn, _REGION_OPERATIONS, ordered):
        uid = str(row[1])
        details[uid] = row[1:]
        heads[uid] = _head(row)
        if row[_STATUS] == _DONE:
            done.add(uid)
    consumed: dict[str, list[Version]] = defaultdict(list)
    for row in _select(conn, _REGION_CONSUMED, ordered):
        consumed[str(row[0])].append(_version(row))
    data = {version.uid for found_versions in consumed.values() for version in found_versions
            if version.item_kind == DATASET}
    causes = _cached(conn, OPERATION, ordered)
    subjects = _subjects(causes.values())
    if found.kind is LineageKind.DATASET:
        data.add(found.uid)
    current: dict[str, DatasetNode] = {}
    successors: dict[str, str | None] = {}
    for row in _select(conn, _REGION_DATA, data | _named(subjects)):
        node = current[str(row[1])] = dataset_node(row[:-1])
        successors[node.uid] = None if row[-1] is None else str(row[-1])
    # Quién escribió cada versión solo hace falta (ProvenanceGraph.producer) si la consumida no
    # es el contenido actual del dato, o lo escribió quien la consume (o alguien que no está
    # hecho): si no, su productor es quien escribió el contenido actual.
    produced: dict[str, list[Version]] = defaultdict(list)
    for row in _select(conn, _WRITTEN, {
        version.uid for op_uid, found_versions in consumed.items() for version in found_versions
        if version.item_kind == DATASET and (
            (dataset := current.get(version.uid)) is None
            or dataset.content_sha256 != version.content_sha256
            or dataset.operation_uid == op_uid or dataset.operation_uid not in done)
    }):
        if (op_uid := str(row[0])) in done:
            produced[op_uid].append(_version(row))
    used: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    uses: dict[str, list[ParamUse]] = defaultdict(list)
    for row in _select(conn, _USED_PARAMS, ordered):
        op_uid = str(row[0])
        used[op_uid].append(row)
        uses[op_uid].append(ParamUse(str(row[1]), str(row[2]), int(row[4]), str(row[9])))
    nodes = {uid: operation_node(head, consumed[uid], produced[uid], uses[uid])
             for uid, head in heads.items()}
    named = {str(row[1]): operation_node(row) for row in (
        *_select(conn, _OPERATIONS_OF_GROUPS, subjects.get(CauseKind.GROUP, set())),
        *_select(conn, _OPERATIONS_OF_TYPES, subjects.get(CauseKind.ALGORITHM, set())),
    ) if str(row[1]) not in done}
    graph = ProvenanceGraph(
        [*(nodes[uid] for uid in done), *named.values()], current.values(),
        [input_node(row) for row in conn.execute(_ALL_INPUTS)],
        [parameter_node(row) for row in conn.execute(_ALL_PARAMETERS)],
        during=changes_while_running(conn, causes.keys()),
    )
    return _Upstream(
        graph=graph, region=region, details=details, used=used,
        loose={uid: node for uid, node in nodes.items() if uid not in done},
        successors=successors, causes=causes,
    )


class _Builder:
    """Construye la :class:`LineageTree` de lo pedido sobre el grafo cargado: con
    ``upstream`` (:func:`_load_upstream`), con lo ya leído de su región; sin él (sobre el grafo
    entero, por ejemplo), lee lo que le falta."""

    def __init__(self, conn: sqlite3.Connection, graph: ProvenanceGraph,
                 versions: Mapping[str, str], language: str,
                 upstream: _Upstream | None = None) -> None:
        self.conn = conn
        self.graph = graph
        self.versions = versions
        self.language = language
        self.upstream = upstream
        self.decoded = _Decoded()

    def _loose(self, uid: str) -> OperationNode:
        """Una operación que no está hecha (en curso, no incorporada…), con lo que consumió y
        leyó, para subir por su cadena."""
        row = self.conn.execute(_LOOSE_OPERATION, (uid,)).fetchone()
        consumed: list[Version] = []
        produced: list[Version] = []
        for io_row in self.conn.execute(_LOOSE_IO, (uid,)):
            _op_uid, out, version = version_of(io_row)
            (produced if out else consumed).append(version)
        used: list[ParamUse] = [param_use_of(use_row)[1]
                                for use_row in self.conn.execute(_LOOSE_PARAMS, (uid,))]
        return operation_node(row, consumed, produced, used)

    def walk(self, root: str) -> tuple[dict[str, OperationNode], dict[str, tuple[str, ...]]]:
        """Las operaciones de la cadena de ``root`` por orden de distancia (en anchura) y de
        cada una, las que escribieron lo que consumió."""
        start = self.graph.operations.get(root)
        if start is None:
            start = self._loose(root) if self.upstream is None else self.upstream.loose[root]
        nodes: dict[str, OperationNode] = {root: start}
        upstream: dict[str, tuple[str, ...]] = {}
        queue = deque([root])
        while queue:
            uid = queue.popleft()
            found = _producers(self.graph, nodes[uid])
            upstream[uid] = found
            for producer in found:
                if producer not in nodes:
                    nodes[producer] = self.graph.operations[producer]
                    queue.append(producer)
        return nodes, upstream

    def inputs(self, uids: Collection[str]) -> dict[str, InputLink]:
        successors = {str(previous): str(uid)
                      for previous, uid in _select(self.conn, _SUCCESSORS, uids)}
        found: dict[str, InputLink] = {}
        for row in _select(self.conn, _INPUT_DETAILS, uids):
            (uid, name, kind, module, status, status_at, status_by, status_reason,
             registered_by, registered_at, received_at, received_from, content_sha256, crs_h,
             crs_v, operation_uid, previous_uid) = row
            found[str(uid)] = InputLink(
                str(uid), str(name), str(kind), str(module), InputStatus(status), status_at,
                status_by, status_reason, str(registered_by), str(registered_at), received_at,
                received_from, str(content_sha256), self.decoded.mapping(crs_h),
                self.decoded.mapping(crs_v),
                str(operation_uid), previous_uid, successors.get(str(uid)),
            )
        return found

    def parameters(self, rows: Iterable[tuple[Any, ...]], now: Mapping[str, tuple[Any, ...]],
                   causes: Mapping[str, frozenset[Cause]]) -> dict[str, list[ParameterLink]]:
        """Los parámetros que leyó cada operación (``rows``, de ``gb_operation_param``; por el
        uid de la operación), con su estado de hoy (``now``, de ``gb_parameter``) y quién
        decidió la revisión que leyó."""
        decisions = {(str(uid), int(rev)): (decided_by, decided_at, source)
                     for uid, rev, decided_by, decided_at, source
                     in _select(self.conn, _DECISIONS, now)}
        found: dict[str, list[ParameterLink]] = defaultdict(list)
        decoded = self.decoded
        for (op_uid, parameter_uid, key, scope, rev, value, unit, kind, unconfirmed,
             value_sha256) in rows:
            (_uid, current_rev, current_value, current_unit, current_kind,
             current_unconfirmed, current_sha256, source_op) = now[str(parameter_uid)]
            decided_by, decided_at, source = decisions.get((str(parameter_uid), int(rev)),
                                                           (None, None, None))
            found[str(op_uid)].append(ParameterLink(
                str(parameter_uid), str(key), str(scope), int(rev), decoded.value(value),
                str(unit), ParamKind(kind), bool(unconfirmed), decided_by, decided_at, source,
                int(current_rev), decoded.value(current_value), str(current_unit),
                ParamKind(current_kind), bool(current_unconfirmed),
                str(current_sha256) != str(value_sha256),
                None if source_op is None else str(source_op),
                source_op is not None and bool(causes.get(str(source_op))),
            ))
        return found

    def tree(self, found: _Found) -> LineageTree:
        nodes, upstream = self.walk(found.operation_uid)
        conn, graph, read = self.conn, self.graph, self.upstream
        if read is None:
            used_rows = list(_select(conn, _USED_PARAMS, nodes))
        else:
            used_rows = [row for uid in nodes for row in read.used.get(uid, ())]
        now = {str(row[0]): row for row in _select(conn, _PARAMETERS_NOW,
                                                   {str(row[1]) for row in used_rows})}
        sources = {str(row[7]) for row in now.values() if row[7] is not None}
        if read is None:
            causes = _cached(conn, OPERATION, set(nodes) | sources)
        else:
            causes = {**_cached(conn, OPERATION, sources - read.region), **read.causes}
        review = review_operations(conn)
        params = self.parameters(used_rows, now, causes)
        uses: dict[str, list[InputUse]] = defaultdict(list)
        for entry in graph.inputs.values():
            if entry.operation_uid in nodes:
                uses[entry.operation_uid].append(InputUse(entry.uid, None))
        for uid, node in nodes.items():
            uses[uid].extend(InputUse(version.uid, version.role) for version in node.consumed
                             if version.item_kind == INPUT)
        details = self.inputs({use.uid for found_uses in uses.values() for use in found_uses})
        entries = {use.uid: details[use.uid] for uid in nodes for use in uses[uid]
                   if use.uid in details}
        successors: Mapping[str, str | None]
        if read is None:
            consumed_data = {version.uid for node in nodes.values()
                             for version in node.consumed if version.item_kind == DATASET}
            if found.kind is LineageKind.DATASET:
                consumed_data.add(found.uid)
            successors = {str(uid): None if by is None else str(by)
                          for uid, by in _select(conn, _SUPERSEDED_DATA, consumed_data)}
            rows: Iterable[tuple[Any, ...]] = _select(conn, _OPERATION_DETAILS, nodes)
        else:
            successors = read.successors
            rows = (read.details[uid] for uid in nodes)
        links: dict[str, OperationLink] = {}
        for row in rows:
            link = self._operation(row, nodes, upstream, params, uses, entries, successors,
                                   causes, review)
            links[link.uid] = link
        ordered = MappingProxyType({uid: links[uid] for uid in nodes})
        hypotheses, unconfirmed = _param_marks(
            graph, {use.parameter_uid for node in nodes.values() for use in node.params})
        dataset = None
        if found.kind is LineageKind.DATASET:
            dataset = self._dataset(found.uid, None, found.operation_uid, successors)
            cached = _cached(conn, DATASET, {found.uid}).get(found.uid)
            item_causes = cached if cached is not None else (
                frozenset() if dataset.status in LIVE_DATASET_STATUSES
                else root_causes(causes.get(found.operation_uid, ())))
            current = dataset.status in LIVE_DATASET_STATUSES
        else:
            item_causes = causes.get(found.operation_uid, frozenset())
            if found.figure is not None:
                current = _current_of(conn, found.figure.key,
                                      found.figure.scope_key) == found.figure.uid
            else:
                root = ordered[found.operation_uid]
                current = root.status == _DONE and root.superseded_by is None
        return LineageTree(
            kind=found.kind, uid=found.uid, root=found.operation_uid, figure=found.figure,
            dataset=dataset, operations=ordered, inputs=MappingProxyType(entries),
            marks=FigureMarks(found.uid, hypotheses, unconfirmed, frozenset(item_causes),
                              current),
            result=_item_status(conn, found),
        )

    def _dataset(self, uid: str, role: str | None, producer: str | None,
                 successors: Mapping[str, str | None],
                 content_sha256: str | None = None) -> DatasetLink:
        """El dato ``uid`` en la versión ``content_sha256`` (por defecto, la actual)."""
        node = self.graph.datasets[uid]
        return DatasetLink(
            node.uid, node.name, node.module, node.kind, node.status,
            node.content_sha256 if content_sha256 is None else content_sha256,
            node.content_sha256, role, producer, node.input_uid, successors.get(uid),
        )

    def _operation(self, row: tuple[Any, ...], nodes: Mapping[str, OperationNode],
                   upstream: Mapping[str, tuple[str, ...]],
                   params: Mapping[str, list[ParameterLink]],
                   uses: Mapping[str, list[InputUse]], entries: Mapping[str, InputLink],
                   successors: Mapping[str, str | None],
                   causes: Mapping[str, frozenset[Cause]],
                   review: frozenset[str]) -> OperationLink:
        (uid, op_type, op_version, module, status, status_reason, repeatable, group_name,
         group_uid, supersedes_uid, superseded_by, geoblender_version, software, executor,
         job_uid, interpreter, user_host, host, started_at, finished_at, settings) = row
        uid = str(uid)
        node = nodes[uid]
        consumed = tuple(
            self._dataset(version.uid, version.role,
                          self.graph.producer(version.uid, version.content_sha256,
                                              excluding=uid),
                          successors, version.content_sha256)
            for version in node.consumed
            if version.item_kind == DATASET and version.uid in self.graph.datasets
        )
        found_causes = causes.get(uid, frozenset())
        stored = self.decoded.mapping(settings)
        return OperationLink(
            uid=uid, op_type=str(op_type), op_version=str(op_version), module=str(module),
            status=str(status), status_reason=status_reason, repeatable=bool(repeatable),
            group_name=group_name, group_uid=group_uid, supersedes_uid=supersedes_uid,
            superseded_by=superseded_by, geoblender_version=str(geoblender_version),
            software=self.decoded.mapping(software), executor=str(executor),
            job_uid=job_uid,
            interpreter=None if interpreter is None else self.decoded.mapping(interpreter),
            user_host=str(user_host), host=str(host), started_at=str(started_at),
            finished_at=finished_at, settings=stored, params=tuple(params.get(uid, ())),
            consumed=consumed,
            inputs=tuple(use for use in uses.get(uid, ()) if use.uid in entries),
            upstream=upstream[uid], causes=found_causes,
            stale_text=stale_text(self.graph, self.versions, found_causes,
                                  language=self.language, operation=uid)
            if found_causes else None,
            review=uid in review,
            result=_operation_status(uid, uid, status, executor, status_reason),
            settings_text=settings_text(str(op_type), stored, language=self.language),
        )


def lineage(project: ReadableProject, item: str, *, conn: sqlite3.Connection | None = None,
            language: str = "es", versions: Mapping[str, str] | None = None) -> LineageTree:
    """La procedencia de ``item`` (RF-008-29; véase el módulo): el uid de una cifra, de un dato
    (o el nombre de uno vivo) o de una operación (también una aún sin incorporar), leída en una
    instantánea (de ``conn``, si se da) sin escribir nada. Los textos de las causas, en
    ``language``; la versión instalada de cada algoritmo, la de ``versions`` (por defecto, la
    de los tipos registrados). :class:`~.messages.ProvenanceError` ``core.lineage_unknown`` si
    el proyecto no tiene ``item``; :class:`TypeError`/:class:`ValueError` con un argumento mal
    formado."""
    wanted = _item(item)
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    chosen = dict(installed_versions() if versions is None else versions)
    with _reading(project, conn) as reading:
        found = _find(reading, wanted)
        if found is None:
            raise ProvenanceError("core.lineage_unknown", item=wanted, project=_name(project))
        read = _load_upstream(reading, found)
        return _Builder(reading, read.graph, chosen, language, read).tree(found)


# --- Marcas y cifra vigente -----------------------------------------------------------------


def _upstream_params(graph: ProvenanceGraph, starts: Iterable[str]) -> dict[str, int]:
    """De cada operación de ``starts`` y de su cadena, el conjunto de bits de los parámetros
    que leyeron ella y las de aguas arriba (plan §5.4.10): una vez por consulta, por
    componentes fuertemente conexas (las versiones pueden formar ciclos), cada una después de
    las que necesita. El bit de cada parámetro es su posición en :attr:`ProvenanceGraph`
    ``.parameters``."""
    bits = {uid: 1 << position for position, uid in enumerate(graph.parameters)}
    upstream: dict[str, tuple[str, ...]] = {}
    queue = deque(uid for uid in starts if uid in graph.operations)
    for uid in queue:
        upstream[uid] = ()
    while queue:
        uid = queue.popleft()
        found = graph.upstream(uid)
        upstream[uid] = found
        for producer in found:
            if producer not in upstream:
                upstream[producer] = ()
                queue.append(producer)
    own = {uid: _mask(bits, graph.operations[uid].params) for uid in upstream}
    masks: dict[str, int] = {}
    for component in strong_components(list(upstream), upstream):
        members = set(component)
        mask = 0
        for uid in component:
            mask |= own[uid]
            for producer in upstream[uid]:
                if producer not in members:
                    mask |= masks[producer]
        for uid in component:
            masks[uid] = mask
    return masks


def _mask(bits: Mapping[str, int], uses: Iterable[ParamUse]) -> int:
    mask = 0
    for use in uses:
        mask |= bits.get(use.parameter_uid, 0)
    return mask


def _uid_list(values: object, what: str) -> list[str]:
    if isinstance(values, str | bytes) or not isinstance(values, Iterable):
        raise TypeError(f"{what}: una lista de uid, no {values!r}")
    found = list(dict.fromkeys(values))
    for value in found:
        if not isinstance(value, str) or not value:
            raise TypeError(f"{what}: los uid son textos no vacíos, no {value!r}")
    return found


def figure_marks(project: ReadableProject, figure_uids: Iterable[str], *,
                 conn: sqlite3.Connection | None = None) -> dict[str, FigureMarks]:
    """Las marcas de cada cifra de ``figure_uids`` (RF-008-31; :class:`FigureMarks`), según
    el estado de hoy de lo de aguas arriba, leídas en una instantánea (de ``conn``, si se da)
    sin escribir nada. :class:`~.messages.ProvenanceError` ``core.lineage_unknown`` si una no
    está en el proyecto; :class:`TypeError` si no es una lista de uid."""
    wanted = _uid_list(figure_uids, "figure_marks")
    if not wanted:
        return {}
    with _reading(project, conn) as reading:
        records = {record.uid: record for record in (
            FigureRecord.from_row(row) for row in _select(reading, _FIGURES, wanted))}
        missing = [uid for uid in wanted if uid not in records]
        if missing:
            raise ProvenanceError("core.lineage_unknown", item=missing[0],
                                  project=_name(project))
        graph = load_graph(reading)
        operations = {record.operation_uid for record in records.values()}
        masks = _upstream_params(graph, operations)
        causes = _cached(reading, OPERATION, operations)
        current = {pair: _current_of(reading, *pair) for pair in {
            (record.key, record.scope_key) for record in records.values()}}
    by_bit = list(graph.parameters)
    found: dict[str, FigureMarks] = {}
    for uid in wanted:
        record = records[uid]
        mask = masks.get(record.operation_uid, 0)
        parameters = [by_bit[bit] for bit in range(mask.bit_length()) if mask >> bit & 1]
        hypotheses, unconfirmed = _param_marks(graph, parameters)
        found[uid] = FigureMarks(
            uid, hypotheses, unconfirmed, causes.get(record.operation_uid, frozenset()),
            current[(record.key, record.scope_key)] == uid,
        )
    return found


def current_figure(project: ReadableProject, key: str,
                   scope: Mapping[str, ScopeValue] | None = None, *,
                   conn: sqlite3.Connection | None = None) -> FigureRecord | None:
    """La cifra vigente de ``key`` en ``scope`` (RF-008-30; sin ámbito, toda la operación):
    la de la operación hecha y sin sustituir más reciente que no está obsoleta; si todas lo
    están, la más reciente; ``None`` si no hay ninguna. :class:`TypeError`/:class:`ValueError`
    si la clave no es un texto o el ámbito está mal formado."""
    if not isinstance(key, str) or not key:
        raise TypeError(f"la clave de una cifra es un texto, no {key!r}")
    wanted = scope_key({} if scope is None else scope)
    with _reading(project, conn) as reading:
        uid = _current_of(reading, key, wanted)
        if uid is None:
            return None
        row = reading.execute(_FIGURE, (uid,)).fetchone()
    return FigureRecord.from_row(row)


# --- Estado de lo mostrado ------------------------------------------------------------------


def result_state(project: ReadableProject, item: str | None = None, *,
                 view: ResultState | str | None = None,
                 conn: sqlite3.Connection | None = None) -> ResultStatus:
    """Cómo se presenta lo que se muestra (RF-008-23; :class:`ResultStatus`):

    - con ``view`` (``preview`` o ``measurement``), lo que solo está en la vista: «vista
      previa, sin guardar» o «medición, no registrada», sin leer el proyecto (``item``, si se
      da, es de lo que sale);
    - si no, ``item`` es el uid de lo que muestra (una cifra, un dato o el nombre de uno vivo,
      una operación): lo guardado en el proyecto es «resultado»; lo de un trabajo de la 004 en
      curso, «pendiente de incorporar»; lo de uno borrado sin incorporar, «no incorporada» con
      el motivo; lo de una operación que no terminó bien o lo que el proyecto no tiene, «vista
      previa, sin guardar» (nunca un resultado).

    :class:`ValueError` con otra ``view``; :class:`TypeError` sin ``item`` ni ``view``."""
    if view is not None:
        state = ResultState(view)
        if state not in VIEW_STATES:
            raise ValueError(f"lo que solo está en la vista es {', '.join(VIEW_STATES)}, no "
                             f"{view!r}")
        if item is not None and not isinstance(item, str):
            raise TypeError(f"lo mostrado se indica por un uid, no {item!r}")
        return ResultStatus(state, item)
    if item is None:
        raise TypeError("result_state necesita el uid de lo que se muestra o, si solo está en "
                        "la vista, view")
    wanted = _item(item)
    with _reading(project, conn) as reading:
        found = _find(reading, wanted)
        if found is None:
            return ResultStatus(ResultState.PREVIEW, wanted)
        return _item_status(reading, found)


# --- Búsqueda (T55) -------------------------------------------------------------------------

SEARCH_LIMIT = 20
"""Lo que da como mucho una búsqueda de la procedencia (:func:`search_items`)."""

# Cada clave y ámbito de las cifras, por orden de su primer registro (con MIN, SQLite da las
# demás columnas de esa fila).
_FIGURE_PAIRS = (
    "SELECT key, scope_key, label, scope, MIN(fid) AS first FROM gb_figure "
    "GROUP BY key, scope_key ORDER BY first"
)
_LIVE_DATA = (
    f"SELECT uid, name FROM gb_dataset WHERE status IN ({_LIVE}) "
    "ORDER BY name COLLATE NOCASE, fid"
)


@dataclass(frozen=True, slots=True)
class LineageMatch:
    """Lo que encuentra la búsqueda de la procedencia (:func:`search_items`): una cifra
    vigente o un dato vivo (``kind``), su uid y cómo se lee (de una cifra,
    :meth:`.figures.FigureRecord.text`; de un dato, su nombre)."""

    kind: LineageKind
    uid: str
    text: str


def search_items(project: ReadableProject, text: str, *, limit: int = SEARCH_LIMIT,
                 conn: sqlite3.Connection | None = None,
                 language: str = "es") -> tuple[LineageMatch, ...]:
    """Lo que contiene ``text`` (sin distinguir mayúsculas), leído en una instantánea sin
    escribir nada (plan §5.5): primero las cifras **vigentes** (:func:`current_figure`) cuya
    clave, cuyo nombre (en español o en inglés) o el valor de alguno de cuyos ámbitos lo
    contienen, por el orden en que se registró por primera vez esa clave y ese ámbito; después
    los datos vivos cuyo nombre lo contiene, por nombre. Como mucho ``limit``; nada si
    ``text`` está vacío. Los textos, en ``language``. :class:`TypeError`/:class:`ValueError`
    con un argumento mal formado."""
    if not isinstance(text, str):
        raise TypeError(f"se busca un texto, no {text!r}")
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"la búsqueda da al menos un resultado, no {limit!r}")
    wanted = text.strip().casefold()
    if not wanted:
        return ()
    found: list[LineageMatch] = []
    with _reading(project, conn) as reading:
        for key, wanted_scope, label, scope, _first in reading.execute(_FIGURE_PAIRS):
            declared = FIGURES.get(str(key))
            words = [str(key), str(label), "" if declared is None else declared.label_msgid,
                     *(str(value) for value in json.loads(scope).values())]
            if wanted not in " ".join(words).casefold():
                continue
            uid = _current_of(reading, str(key), str(wanted_scope))
            if uid is None:
                continue
            record = FigureRecord.from_row(reading.execute(_FIGURE, (uid,)).fetchone())
            found.append(LineageMatch(LineageKind.FIGURE, uid, record.text(language=language)))
            if len(found) >= limit:
                return tuple(found)
        for uid, name in reading.execute(_LIVE_DATA):
            if wanted in str(name).casefold():
                found.append(LineageMatch(LineageKind.DATASET, str(uid), str(name)))
                if len(found) >= limit:
                    break
    return tuple(found)
