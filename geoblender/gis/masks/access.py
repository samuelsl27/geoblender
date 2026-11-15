# SPDX-License-Identifier: GPL-3.0-or-later
"""El contrato de los operadores: pedir las máscaras de una versión (spec 012; RF-012-10,
RF-012-17; plan 012 §5.3.1, A12, D-15, D-26, D-43; ADR-0028 §4 y §5).

Un operador de otro módulo (diseño, verificación…) pide las máscaras **solo** por aquí:

- :func:`mask_state`: el estado de las máscaras de una versión (:class:`MaskState`: al día,
  obsoletas o sin compilar) y los sectores sin búsqueda vigente, calculados al vuelo (A12).
  Están al día si los datos de la última ``gis.compile_constraints`` hecha y no sustituida de la
  versión siguen vivos y ni ellos ni la operación tienen causa en la caché de la obsolescencia de
  la 008 (``gb_stale``): cambiar una restricción, un sector, una búsqueda o un parámetro que
  consumió las deja obsoletas. **El hueco H-1** (spec 015, T19; plan 015 §5.8; ADR-0030 §3): el
  grafo de la 008 solo deduce de lo que una operación **consumió**, así que un dato nuevo no deja
  obsoleto lo que ya se calculó; una tabla de restricciones declaradas por las entidades de la
  versión (``des_decl_<vNN>``, RF-012-29) que llega después de compilar no marcaría las máscaras
  y los operadores diseñarían sin su prohibición (el error 51). Por eso, con una tabla de
  declaradas **viva** que la compilación vigente no consumió, las máscaras están **obsoletas** con
  su causa (:class:`MaskCause` ``DECLARED_NEW``, :func:`mask_cause`; el mensaje
  ``core.constraint_masks_declared_new``). Es **por versión** (la tabla de V01 no es de V02) y una
  versión compilada antes de la 015, sin tabla viva, sigue al día; una compilación que la
  consumió, aunque esté vacía, está al día mientras su hash no cambie (eso lo da el grafo).
  **Editar la tabla fuera de Geoblender** (spec 015, T20; RF-015-11, RF-008-56): si la tabla de declaradas viva
  de la versión está **bloqueada** por una edición hecha en QGIS (o falta o está dañada), las máscaras están
  obsoletas con su causa (:class:`MaskCause` ``DECLARED_BLOCKED``; ``core.constraint_masks_declared_blocked``) y
  **no se compilan** mientras tanto (``gis.masks.store.gather_steps`` se niega con
  ``core.constraint_declared_blocked`` antes de leer la tabla) hasta que la persona acepte la edición con un
  motivo o la entidad la vuelva a poner.
  **La primera declaración de una versión** (spec 015, T38; hallazgo E-1 de la verificación única): mientras no se
  escribe la tabla no hay nada que la compilación no haya consumido, y la plataforma que protege (cuya orden de
  crear ya hizo su commit) quedaría sin su restricción en ningún sitio si Esc o un fallo cortan lo que sigue antes
  de declararla. Por eso, con un :class:`~.declaring.DeclarationHook` registrado (lo da ``design`` a través de
  ``bl``; ``gis`` no puede importarlo), las máscaras también están **obsoletas** con la misma causa
  (``DECLARED_NEW``) mientras una entidad viva que protege **no tenga su restricción en la declaración
  vigente** (:func:`_declared_pending`): nunca al día sin la zona de una entidad que protege.
- :func:`mask_cause`: por qué están obsoletas, si es por lo que no ve el grafo (H-1) o por una tabla de
  declaradas que no se puede usar.
- :func:`require_current`: ``MaskError`` si las máscaras de una versión no están al día, con la
  causa nombrada; lo que usan los operadores antes de registrar nada.
- :func:`load_masks`: el :class:`MaskSet` de una versión al día (la rejilla, cada máscara por su
  tipo desde la rejilla de clases, cada zona por su código, el peso de las «preferible no
  afectar», su estado y la marca de búsqueda pendiente con los códigos y los nombres de los
  sectores); :class:`MaskError` si no lo están: nunca se entregan máscaras obsoletas.
- :func:`open_masks` (spec 015, T37; RNF-015-03): lo mismo que :func:`load_masks` **sin leer las celdas**: comprueba
  que están al día (los mismos rechazos) y da un :class:`MaskSource` con lo que las identifica (la rejilla, la
  versión, la compilación y sus ``Use``); ``classes_window`` lee de la rejilla de clases **solo las teselas de una
  ventana** (y :meth:`MaskSet.classes_window`, lo mismo de las ya cargadas). Es lo que usa una plataforma para
  empezar su operación en una llamada del hilo de Blender sin leer 2,81 M de celdas para tocar unas pocas.
- :func:`mask_uses` (o :meth:`MaskSet.uses`): sus ``Use``, para registrarlas como **entradas**
  de la operación que las usa, que así queda obsoleta cuando lo quedan ellas (ADR-0025).
- :func:`ensure_masks_steps` (D-15, D-43): si no están al día, **declara antes lo que una entidad que protege
  aún no declaró** (:func:`declare_pending_steps`, T38: la próxima operación que las use lo pone al día) y
  empieza una ``gis.compile_constraints`` propia y da sus pasos; el último ``Progress`` lleva el
  :class:`MaskSet`. Si no se pueden compilar, se rechaza con lo mismo que la compilación
  (``gis.masks.store.begin_compile``), antes de dar ningún paso de ella y sin registrar nada de ella (lo único
  que puede haber escrito antes es esa declaración, que es de una operación propia y no depende de si se
  compila).
- :func:`compile_masks_steps` (T19): lo mismo sin cargarlas: la compilación propia por pasos; el último
  ``Progress`` lleva su :class:`~.store.StoredMasks` (con el informe de lo ganado y perdido por
  restricción, RF-012-06); lo que usa la orden de una entidad al recompilar tras declarar.

**El ciclo entidad → declarada → máscaras → entidad** (D-21, ADR-0030 §3; T19): una entidad que protege
consume las máscaras, que consumen la declaración, que consume lo que escribe la entidad. El grafo de la 008
propaga una obsolescencia por ese ciclo y da por obsoletos a la vez la declaración, las máscaras y las demás
entidades, y entonces nada podría recalcularse (una entidad pide las máscaras al día). Por eso unas máscaras
cuya compilación consumió la tabla de declaradas viva **sin que cambiara su contenido** y que no tienen **ninguna
causa directa** (un dato que consumió con otro contenido o estado, un parámetro con otro valor, la fila propia de
la versión de uno, otra versión de su algoritmo: lo de ``core.provenance.graph.direct_causes``) se entregan
aunque el grafo las dé por obsoletas por herencia (:func:`_only_through_declared`); «Recalcular lo obsoleto»
rehace las entidades y lo que dependía de ellas pierde su marca si su salida no cambia (RF-008-26). Sin
declaradas vivas, todo es como en la 012.
- :func:`sector_states` (T13): el estado de cada sector de búsqueda ahora (el perímetro si no
  hay sectores), con su búsqueda vigente o pendiente (``core.constraints.store.SectorState``).

Negarse a diseñar en un sector pendiente es cosa de cada operador (D-9; ADR-0028 §5).

Python puro (nivel 2).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator, Iterator, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

import numpy as np

from ...core.constraints import declared as declared_store
from ...core.constraints.messages import ConstraintError
from ...core.constraints.store import SectorState
from ...core.datasets import registry as dataset_registry
from ...core.datasets.model import DatasetRecord, DatasetStatus
from ...core.project.model import Progress
from ...core.provenance.contract import OPERATIONS, parse_version
from ...core.provenance.graph import DATASET_STATUS_CAUSES, INACTIVE_CAUSES
from ...core.provenance.operations import OperationStatus, Use
from ...core.versions import read as versions_read
from ...core.versions.model import Version, VersionError
from ..geotiff.reader import GeoTiffHeader, read_header, read_rows, read_window
from ..grid import Grid
from ..store import StoreProject
from . import declaring
from . import provenance as declared
from .combine import ClassBit
from .compile import STEP_BUDGET_S, pace_units
from .store import StoredMasks, begin_compile_steps, compile_run, current_pending, read_report
from .store import sector_states_now
from .store import zone_runs_steps
from .zones import Runs

__all__ = [
    "MASK_FAMILIES",
    "MaskCause",
    "MaskError",
    "MaskSet",
    "MaskSource",
    "MaskState",
    "compile_masks_steps",
    "declare_pending_steps",
    "ensure_masks_steps",
    "load_masks",
    "load_masks_steps",
    "mask_cause",
    "mask_state",
    "mask_uses",
    "open_masks",
    "require_current",
    "sector_states",
]

MASK_FAMILIES: tuple[str, ...] = (declared.CLASSES, declared.ZONES, declared.REPORT)
"""Las familias de datos que lee un :class:`MaskSet` (y que consume quien lo usa)."""
_ROLE_PREFIX = "masks_"
_READ_ROWS = 256
"""Las filas de la rejilla de clases que se leen en cada unidad de :func:`load_masks_steps`."""


class MaskState(StrEnum):
    """El estado de las máscaras de una versión."""

    CURRENT = "current"  # al día
    STALE = "stale"  # obsoletas: cambió algo que consumió la compilación
    MISSING = "missing"  # sin compilar (o sus datos ya no están)


class MaskCause(StrEnum):
    """Por qué están obsoletas unas máscaras cuando **no** lo dice el grafo de la 008 (H-1, spec 015, T19)."""

    DECLARED_NEW = "declared_new"
    """La versión tiene una tabla de restricciones declaradas por sus entidades (``des_decl_<vNN>``) viva que
    la compilación vigente no consumió: una declarada nueva (RF-012-29)."""
    DECLARED_BLOCKED = "declared_blocked"
    """La tabla de restricciones declaradas de la versión está **bloqueada** por una edición hecha fuera de
    Geoblender (o falta o está dañada): no se compilan las máscaras con ella hasta que la persona acepte la
    edición con un motivo o la entidad la vuelva a poner (RF-015-11, RF-008-56)."""


class MaskError(ConstraintError):
    """Las máscaras pedidas no están al día (RF-012-17): ``core.constraint_masks_missing``,
    ``core.constraint_masks_stale`` o, si lo que falta es una restricción declarada por una entidad
    (:class:`MaskCause`), ``core.constraint_masks_declared_new`` (una nueva) o
    ``core.constraint_masks_declared_blocked`` (la tabla se editó fuera de Geoblender), con la versión y la
    orden de compilar."""


@dataclass(frozen=True, slots=True)
class _Use:
    uid: str
    name: str
    role: str


Window = tuple[slice, slice]
"""Una ventana de la rejilla: sus filas y sus columnas (``slice`` de enteros, sin paso)."""


def _bounds(window: Window, shape: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    """Las filas ``(desde, hasta)`` y las columnas de ``window``, comprobadas contra una rejilla de ``shape``:
    ``ValueError`` (un error del programa) si no son enteros sin paso, si están vacías o se salen de ella."""
    found: list[tuple[int, int]] = []
    for part, size in zip(window, shape, strict=True):
        start, stop = part.start, part.stop
        if (part.step not in (None, 1) or isinstance(start, bool) or isinstance(stop, bool)
                or not isinstance(start, int) or not isinstance(stop, int) or not 0 <= start < stop <= size):
            raise ValueError(f"la ventana {window!r} no es de filas y columnas enteras dentro de la rejilla "
                             f"de {shape[0]} × {shape[1]}")
        found.append((start, stop))
    return found[0], found[1]


def _classes_of(values: np.ndarray) -> np.ndarray:
    """La rejilla de clases (``uint16``) de lo leído del GeoTIFF: el sin dato, 0."""
    return np.where(np.isfinite(values), values, 0.0).astype(np.uint16)


def _used_of(records: Mapping[str, DatasetRecord]) -> tuple[_Use, ...]:
    return tuple(_Use(record.uid, record.name,
                      _ROLE_PREFIX + declared.FAMILIES_BY_CODE[family].role)
                 for family, record in records.items())


@dataclass(frozen=True, slots=True, eq=False)
class MaskSet:
    """Las máscaras de una versión al día, como las recibe un operador (ADR-0028 §4): la
    rejilla, la versión, la compilación de la que salen, su estado, los sectores sin búsqueda
    vigente (códigos; ``""`` = el perímetro como sector único) y sus nombres, y la rejilla de
    clases (``uint16``, bits de :class:`~.combine.ClassBit`, fila 0 al norte); además, sus zonas,
    los pesos, lo que se consume y el tipo de cada restricción con zona."""

    grid: Grid
    version_uid: str
    operation_uid: str
    state: MaskState
    pending_sectors: tuple[str, ...]
    classes: np.ndarray = field(repr=False)
    pending_names: tuple[str, ...] = ()
    zones: Mapping[str, Runs] = field(default_factory=lambda: MappingProxyType({}), repr=False)
    weights: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    used: tuple[_Use, ...] = field(default=(), repr=False)
    ctypes: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """El tipo de cada restricción con zona (código → valor de ``ConstraintType``), del
    informe: lo que necesita quien verifica por recinto (``reserves.compliance``)."""

    def _bit(self, bit: ClassBit) -> np.ndarray:
        return (self.classes & np.uint16(int(bit))) != 0

    def default_domain(self) -> np.ndarray:
        """El dominio por defecto: perímetro ∩ límite legal − intocables y exclusiones."""
        return (self._bit(ClassBit.PERIMETER) & self._bit(ClassBit.LEGAL)
                & ~self._bit(ClassBit.UNTOUCHABLE))

    def cut_allowed(self) -> np.ndarray:
        """Las celdas con corte admitido."""
        return self._bit(ClassBit.CUT_ALLOWED)

    def fill_allowed(self) -> np.ndarray:
        """Las celdas con relleno admitido."""
        return self._bit(ClassBit.FILL_ALLOWED)

    def fill_strip(self) -> np.ndarray:
        """La franja de solo relleno."""
        return self._bit(ClassBit.FILL_STRIP)

    def zone(self, code: str) -> Runs:
        """La zona de la restricción ``code`` (``<código>:inner``: la banda hacia dentro de un
        límite legal); ``KeyError`` si no la hay."""
        return self.zones[code]

    def avoid_weights(self) -> Mapping[str, tuple[Runs, float]]:
        """Las zonas «preferible no afectar» con su peso (código → (zona, peso))."""
        return MappingProxyType({code: (self.zones.get(code, Runs.empty()), weight)
                                 for code, weight in self.weights.items()})

    def uses(self) -> tuple[Use, ...]:
        """Sus ``Use``, para registrarlas como entradas de la operación que las usa."""
        return tuple(Use(item.uid, item.role) for item in self.used)

    def classes_window(self, window: Window) -> np.ndarray:
        """Las celdas de la rejilla de clases (``uint16``) en ``window`` (filas y columnas de la rejilla): una
        vista, no una copia (spec 015, T37). ``ValueError`` si la ventana está vacía o se sale de la rejilla."""
        _bounds(window, self.classes.shape)
        return self.classes[window]


@dataclass(frozen=True, slots=True, eq=False)
class MaskSource:
    """Las máscaras de una versión al día **sin sus celdas** (spec 015, T37; RNF-015-03; :func:`open_masks`): lo que
    las identifica —la rejilla (``grid``), la versión, la compilación de la que salen (``operation_uid``), su estado
    (siempre al día), los sectores sin búsqueda vigente y sus nombres y lo que consumen (``used``)— y el modo de
    leer de la rejilla de clases **solo la ventana** que se pide (:meth:`classes_window`). No lleva las zonas ni los
    pesos: quien los necesita carga el :class:`MaskSet`. Da, bit a bit, lo que
    ``load_masks(...).classes[ventana]``."""

    grid: Grid
    version_uid: str
    operation_uid: str
    state: MaskState
    pending_sectors: tuple[str, ...]
    pending_names: tuple[str, ...]
    used: tuple[_Use, ...] = field(repr=False)
    path: Path = field(repr=False)
    header: GeoTiffHeader = field(repr=False)

    def uses(self) -> tuple[Use, ...]:
        """Sus ``Use``, para registrarlas como entradas de la operación que las usa (como :meth:`MaskSet.uses`)."""
        return tuple(Use(item.uid, item.role) for item in self.used)

    def classes_window(self, window: Window) -> np.ndarray:
        """Las celdas de la rejilla de clases (``uint16``, fila 0 al norte) en ``window``, leyendo **solo** las
        teselas que la tocan (un array nuevo de la forma de la ventana). ``ValueError`` si la ventana está vacía o se
        sale de la rejilla; ``GisError`` si un bloque está dañado."""
        rows, cols = _bounds(window, self.grid.shape)
        with self.path.open("rb") as stream:
            return _classes_of(read_window(stream, self.header, rows, cols))


def mask_uses(masks: MaskSet) -> tuple[Use, ...]:
    """Los ``Use`` de ``masks`` (:meth:`MaskSet.uses`)."""
    return masks.uses()


# --- El estado ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Found:
    version: Version
    state: MaskState
    records: Mapping[str, DatasetRecord]
    operation_uid: str | None
    pending: tuple[str, ...]
    names: tuple[str, ...]
    cause: MaskCause | None = None


def _version(conn: sqlite3.Connection, version_uid: str) -> Version:
    found = versions_read.version(conn, version_uid)
    if found is None:
        raise VersionError("core.version_unknown", field="versión", value=version_uid,
                           version=version_uid)
    return found


_CONSUMED_DECLARED = (
    "SELECT 1 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.item_kind = 'dataset' "
    "AND d.name = ? AND d.version_uid = ? LIMIT 1")


def _declared_unseen(conn: sqlite3.Connection, version_uid: str, operation: str) -> bool:
    """El hueco H-1 (véase el módulo): la versión ``version_uid`` tiene la tabla de sus restricciones
    declaradas **viva** (:func:`~...core.constraints.declared.live_table`) y la compilación ``operation`` no
    consumió ningún dato de esa tabla (``des_decl`` de esta versión, el que fuera: si consumió uno que
    después cambió, lo dice el grafo de la 008). Sin tabla viva, o con la de otra versión, no."""
    if declared_store.live_table(conn, version_uid) is None:
        return False
    return conn.execute(_CONSUMED_DECLARED, (operation, declared.DECLARED_NAME,
                                             version_uid)).fetchone() is None


def _declared_pending(conn: sqlite3.Connection, project: StoreProject, version_uid: str) -> bool:
    """El hueco H-1 **de la primera declaración** (spec 015, T38; hallazgo E-1; véase :mod:`.declaring`): una
    entidad viva de la versión que protege **no tiene su restricción en la declaración vigente** (la versión no
    tiene tabla viva, o a la suya le falta su fila), según el gancho que registró ``design``
    (:class:`~.declaring.DeclarationHook`); sin gancho, nunca. Mientras sea así, unas máscaras compiladas sin ella
    no pueden estar al día: serían las de una entidad que protege **sin su prohibición**."""
    hook = declaring.current()
    return hook is not None and hook.pending(project, conn, version_uid)


def _state(conn: sqlite3.Connection, project: StoreProject,
           records: Mapping[str, DatasetRecord | None], version_uid: str
           ) -> tuple[MaskState, str | None, MaskCause | None]:
    if any(record is None for record in records.values()):
        return MaskState.MISSING, None, None
    found = {str(record.operation_uid) for record in records.values() if record is not None}
    if len(found) != 1:
        return MaskState.STALE, None, None
    (operation,) = found
    row = conn.execute("SELECT op_type, status, superseded_by FROM gb_operation WHERE uid = ?",
                       (operation,)).fetchone()
    if (row is None or row[0] != declared.COMPILE or row[1] != OperationStatus.DONE
            or row[2] is not None):
        return MaskState.MISSING, None, None
    raster = records[declared.CLASSES]
    assert raster is not None
    if not Path(project.root, *raster.locator.split("/")).is_file():
        return MaskState.MISSING, None, None
    if declared_store.unusable_record(conn, version_uid) is not None:  # RF-015-11: la tabla, editada fuera
        return MaskState.STALE, operation, MaskCause.DECLARED_BLOCKED
    if _declared_unseen(conn, version_uid, operation):  # H-1: lo que el grafo no ve
        return MaskState.STALE, operation, MaskCause.DECLARED_NEW
    if _declared_pending(conn, project, version_uid):  # H-1, la primera declaración (T38): aún no está escrita
        return MaskState.STALE, operation, MaskCause.DECLARED_NEW
    uids = [operation, *(record.uid for record in records.values() if record is not None)]
    marks = ", ".join("?" for _ in uids)
    stale = conn.execute(f"SELECT 1 FROM gb_stale WHERE item_uid IN ({marks}) LIMIT 1",
                         uids).fetchone()
    if any(record is not None and record.status != DatasetStatus.CURRENT
           for record in records.values()):
        return MaskState.STALE, operation, None
    if stale is not None and not _only_through_declared(conn, version_uid, operation):
        return MaskState.STALE, operation, None
    return MaskState.CURRENT, operation, None


_CAUSE_STATUSES = ", ".join(f"'{status}'" for status in (*DATASET_STATUS_CAUSES, *INACTIVE_CAUSES))
_DIRECT_DATA = (
    "SELECT 1 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.item_kind = 'dataset' "
    f"AND (d.status IN ({_CAUSE_STATUSES}) OR d.content_sha256 <> io.content_sha256) LIMIT 1")
_DIRECT_PARAMETERS = (
    "SELECT 1 FROM gb_operation_param AS p JOIN gb_parameter AS cur ON cur.uid = p.parameter_uid "
    "WHERE p.operation_uid = ? AND cur.value_sha256 <> p.value_sha256 LIMIT 1")
_DIRECT_OWN_ROWS = (
    "SELECT 1 FROM gb_operation_param AS p JOIN gb_parameter AS own ON own.key = p.key "
    "AND own.scope = 'version' AND own.scope_uid = ? WHERE p.operation_uid = ? "
    "AND own.uid <> p.parameter_uid LIMIT 1")


def _only_through_declared(conn: sqlite3.Connection, version_uid: str, operation: str) -> bool:
    """Si las causas de obsolescencia de la compilación ``operation`` (y de sus datos) **llegan solo por la
    declaración**: la versión tiene una tabla de declaradas viva que la compilación consumió y **ninguna de sus
    propias entradas ha cambiado** (ningún dato que consumió tiene otro contenido ni estado, ningún parámetro
    que leyó otro valor, ni la fila propia de la versión de uno, ni otra versión de su algoritmo: las causas
    **directas** de la 008, ``core.provenance.graph.direct_causes``, que aquí se miran sin cargar el grafo).

    Es el ciclo entidad → declarada → máscaras → entidad (D-21, ADR-0030 §3): una entidad obsoleta deja
    obsoleta su declaración (consumió su ``des_epr_``) y la declaración, las máscaras que la consumieron, y a su
    vez lo que usó las máscaras, **la propia entidad**: el grafo da por obsoleto todo el ciclo mientras no se
    recalcule, y nadie podría recalcular nada (una entidad necesita las máscaras al día, y las máscaras no lo
    están mientras ella no se recalcule). La declaración que consumieron es **la de ahora** (su contenido no
    cambió: si cambia, es una causa directa de la compilación), así que las máscaras son las que dan las
    restricciones de hoy; «Recalcular lo obsoleto» rehace la entidad y, si su salida no cambia, quita la marca de
    lo que dependía de ella (RF-008-26). Una causa directa de la compilación (una restricción, un sector, un
    parámetro, la propia declaración con otro contenido) sí las deja obsoletas.

    Es **la excepción a RF-012-17 que Samuel aprobó el 15/11/2026** («Mantén la excepción»; spec 012 0.4,
    RF-012-17, que la dice con este mismo alcance): solo vale con una tabla de declaradas viva y sin ninguna
    causa directa, y sin declaradas todo es como en la 012."""
    if declared_store.live_table(conn, version_uid) is None or _declared_unseen(conn, version_uid, operation):
        return False
    if conn.execute(_DIRECT_DATA, (operation,)).fetchone() is not None:
        return False
    if conn.execute(_DIRECT_PARAMETERS, (operation,)).fetchone() is not None:
        return False
    if conn.execute(_DIRECT_OWN_ROWS, (version_uid, operation)).fetchone() is not None:
        return False
    row = conn.execute("SELECT op_version FROM gb_operation WHERE uid = ?", (operation,)).fetchone()
    registered = OPERATIONS.get(declared.COMPILE)
    if row is not None and registered is not None:
        try:
            if parse_version(registered.version) > parse_version(str(row[0])):
                return False
        except ValueError:
            return False
    return True


def _find(project: StoreProject, version_uid: str) -> _Found:
    with project.read() as conn:
        version = _version(conn, version_uid)
        records = {family: dataset_registry.get(conn, declared.dataset_name(family),
                                                version_uid=version.uid)
                   for family in MASK_FAMILIES}
        state, operation, cause = _state(conn, project, records, version.uid)
        pending, names = current_pending(conn, project, version.uid)
    live = {family: record for family, record in records.items() if record is not None}
    return _Found(version, state, MappingProxyType(live), operation, pending, names, cause)


def mask_state(project: StoreProject, version_uid: str) -> tuple[MaskState, tuple[str, ...]]:
    """El estado de las máscaras de la versión ``version_uid`` (uid o código) y los códigos de
    los sectores sin búsqueda vigente ahora (RF-012-10; véase el módulo). Solo lee."""
    found = _find(project, version_uid)
    return found.state, found.pending


def mask_cause(project: StoreProject, version_uid: str) -> MaskCause | None:
    """Por qué las máscaras de la versión ``version_uid`` (uid o código) están obsoletas **cuando no lo
    dice el grafo de la 008** (el hueco H-1; véase el módulo): ``MaskCause.DECLARED_NEW`` si tiene una tabla
    de declaradas viva que la compilación no consumió; ``MaskCause.DECLARED_BLOCKED`` si esa tabla está
    bloqueada por una edición fuera de Geoblender (o falta o está dañada); ``None`` en cualquier otro caso (al
    día, sin compilar, u obsoletas por una causa del grafo, que está en ``gb_stale``). Solo lee."""
    return _find(project, version_uid).cause


# --- Entregar ----------------------------------------------------------------------------------


def _refuse(found: _Found) -> MaskError:
    if found.state is MaskState.MISSING:
        code = "core.constraint_masks_missing"
    elif found.cause is MaskCause.DECLARED_NEW:
        code = "core.constraint_masks_declared_new"
    elif found.cause is MaskCause.DECLARED_BLOCKED:
        code = "core.constraint_masks_declared_blocked"
    else:
        code = "core.constraint_masks_stale"
    return MaskError(code, field="máscaras", value=found.state.value,
                     version=found.version.code, command=declared.COMMAND)


def require_current(project: StoreProject, version_uid: str) -> None:
    """``MaskError`` si las máscaras de la versión ``version_uid`` (uid o código) no están al día
    (``core.constraint_masks_missing``, ``core.constraint_masks_stale`` o, por el hueco H-1,
    ``core.constraint_masks_declared_new`` y, por una tabla de declaradas editada fuera,
    ``core.constraint_masks_declared_blocked``: RF-012-17; véase el módulo), con la versión y la orden de
    compilar. Solo lee: es lo que comprueba un operador antes de registrar nada."""
    found = _find(project, version_uid)
    if found.state is not MaskState.CURRENT:
        raise _refuse(found)


def load_masks(project: StoreProject, version_uid: str) -> MaskSet:
    """El :class:`MaskSet` de la versión ``version_uid`` (uid o código) si sus máscaras están
    al día; si no, :class:`MaskError` (RF-012-17). Solo lee."""
    steps = load_masks_steps(project, version_uid)
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


def load_masks_steps(project: StoreProject, version_uid: str) -> Generator[None, None, MaskSet]:
    """:func:`load_masks` por pasos (T36; RNF-012-06): una unidad por el estado de las máscaras,
    por cada trozo de filas de sus zonas (cada una con su propia lectura, sin sostener ninguna
    entre unidades), por cada banda de la rejilla de clases y por cada trozo de zonas que se
    normaliza. Devuelve el mismo :class:`MaskSet`; cerrarlo a mitad no deja nada."""
    found = _find(project, version_uid)
    if found.state is not MaskState.CURRENT or found.operation_uid is None:
        raise _refuse(found)
    yield None
    records = found.records
    with project.read() as conn:
        (settings,) = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?",
                                   (found.operation_uid,)).fetchone()
        report = read_report(conn, records[declared.REPORT].locator)
    weights = {code: float(value) for code, quantity, value, _unit, _note in report
               if quantity == "weight" and value is not None}
    ctypes = {code: str(note) for code, quantity, _value, _unit, note in report
              if quantity == "zone_area" and note is not None}
    grid = declared.grid_of(json.loads(settings))
    yield None
    zones = yield from zone_runs_steps(project, records[declared.ZONES].locator)
    raster = records[declared.CLASSES]
    path = Path(project.root, *raster.locator.split("/"))
    classes = np.empty(grid.shape, dtype=np.uint16)
    with path.open("rb") as stream:
        header = read_header(stream, path.stat().st_size, path.name)
        if (header.height, header.width) != grid.shape:
            raise _refuse(_Found(found.version, MaskState.STALE, records, None, (), ()))
        for top in range(0, grid.nrows, _READ_ROWS):
            stop = min(top + _READ_ROWS, grid.nrows)
            values = read_rows(stream, header, top, stop)
            classes[top:stop] = _classes_of(values)
            yield None
    used = _used_of(records)
    return MaskSet(grid, found.version.uid, found.operation_uid, MaskState.CURRENT,
                   found.pending, classes, found.names, MappingProxyType(zones),
                   MappingProxyType(weights), used, MappingProxyType(ctypes))


def open_masks(project: StoreProject, version_uid: str) -> MaskSource:
    """Las máscaras de la versión ``version_uid`` (uid o código) al día **sin leer sus celdas** (spec 015, T37;
    RNF-015-03): lo mismo que :func:`load_masks` menos las zonas y la rejilla de clases, que se leen por ventanas
    (:meth:`MaskSource.classes_window`). Los mismos rechazos: :class:`MaskError` si no están al día
    (``core.constraint_masks_missing``, ``_stale``, ``_declared_new`` o ``_declared_blocked``) y, si la rejilla de
    clases no es la de la compilación, ``core.constraint_masks_stale``. Solo lee la cabecera de la rejilla de
    clases."""
    found = _find(project, version_uid)
    if found.state is not MaskState.CURRENT or found.operation_uid is None:
        raise _refuse(found)
    records = found.records
    with project.read() as conn:
        (settings,) = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?",
                                   (found.operation_uid,)).fetchone()
    grid = declared.grid_of(json.loads(settings))
    path = Path(project.root, *records[declared.CLASSES].locator.split("/"))
    with path.open("rb") as stream:
        header = read_header(stream, path.stat().st_size, path.name)
    if (header.height, header.width) != grid.shape:
        raise _refuse(_Found(found.version, MaskState.STALE, records, None, (), ()))
    return MaskSource(grid, found.version.uid, found.operation_uid, MaskState.CURRENT, found.pending,
                      found.names, _used_of(records), path, header)


def ensure_masks_steps(project: StoreProject, version_uid: str, *,
                       budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Las máscaras de la versión ``version_uid`` al día (D-15, D-43): si no lo están, empieza
    una ``gis.compile_constraints`` propia y da sus pasos; el último ``Progress`` lleva el
    :class:`MaskSet`. Al llamar solo se mira su estado; la lectura de lo que se compila y la
    comprobación de cada restricción (``gis.masks.store.begin_compile_steps``: sus rechazos, sin
    registrar nada) son los primeros pasos, y la operación empieza en el último de ellos (T31;
    RNF-012-06: empezar de una vez tardaba más de 0,2 s con 500 restricciones)."""
    state, _pending = mask_state(project, version_uid)
    return _ensure(project, version_uid, state is not MaskState.CURRENT, budget_s)


_COMPILE_PHASE = "compile"
_COMPILE_TEXT = "Compilando las restricciones…"
_DECLARE_TEXT = "Declarando las restricciones de las entidades…"


def declare_pending_steps(project: StoreProject, version_uid: str, *, budget_s: float = STEP_BUDGET_S
                          ) -> Generator[Progress, None, bool]:
    """**Declara antes de compilar** (spec 015, T38; RF-015-10, RF-015-29, CE-015-04; hallazgo E-1; véase
    :mod:`.declaring`): si una entidad viva de la versión ``version_uid`` (uid o código) que protege no tiene su
    restricción en la declaración vigente —la cadena que sigue a «Crear» se cortó con Esc o falló antes de escribir
    la primera tabla—, la declara ahora (``des.declare_constraints``: una operación y una transacción propias) para
    que la compilación que sigue la lea. Da un ``Progress`` sin resultado por cada paso de la declaración y devuelve
    si declaró algo. Sin gancho registrado o sin nada pendiente, no hace nada, y **tampoco con la tabla de las
    declaradas bloqueada** por una edición hecha en QGIS (RF-015-11: lo que la persona editó no se pisa sin que
    lo acepte o la entidad lo vuelva a poner; la compilación se niega con su motivo). Los rechazos de declarar (proteger sin
    resguardo o en «corte y relleno», una versión que no se puede editar…) salen tal cual, nombrando la entidad:
    es lo que impide diseñar con una protección que no se puede declarar. Cerrar el generador a mitad no deja nada
    a medias (la declaración es una sola transacción)."""
    hook = declaring.current()
    if hook is None:
        return False
    with project.read() as conn:
        version = _version(conn, version_uid)
        if declared_store.unusable_record(conn, version.uid) is not None:
            return False  # editada fuera (RF-015-11): no se pisa; la compilación se niega, con su motivo
        pending = hook.pending(project, conn, version.uid)
    if not pending:
        return False
    steps = hook.declare(project, version.uid, budget_s)
    with closing(steps):
        for _step in steps:
            yield Progress(_COMPILE_PHASE, 0, 1, _DECLARE_TEXT)
    return True


def _compile(project: StoreProject, version_uid: str, budget_s: float
             ) -> Generator[Progress, None, tuple[StoredMasks, int]]:
    """Una ``gis.compile_constraints`` propia de la versión ``version_uid`` por pasos: la declaración de lo que una
    entidad que protege aún no declaró (:func:`declare_pending_steps`, T38), sus rechazos y la lectura de lo que
    se compila (:func:`~.store.begin_compile_steps`, sin registrar nada) y la compilación
    (:func:`~.store.compile_run`). Devuelve lo guardado (:class:`~.store.StoredMasks`) y el total de pasos
    que dio, para seguir contándolos."""
    total = 1
    yield from declare_pending_steps(project, version_uid, budget_s=budget_s)
    begin = begin_compile_steps(project, version=version_uid)
    with closing(begin):
        while True:
            try:
                next(begin)
            except StopIteration as stop:
                handle = stop.value
                break
            yield Progress(_COMPILE_PHASE, 0, total, _COMPILE_TEXT)
    steps = compile_run(project, handle, budget_s=budget_s)
    with closing(steps):
        for step in steps:
            total = step.total + 1
            if step.result is not None:
                return step.result, total  # type: ignore[return-value]
            yield Progress(step.phase, step.done, total, step.message)
    raise RuntimeError("la compilación de las máscaras terminó sin dar su resultado")


def compile_masks_steps(project: StoreProject, version_uid: str, *, budget_s: float = STEP_BUDGET_S
                        ) -> Iterator[Progress]:
    """Compila las máscaras de la versión ``version_uid`` (uid o código) **ahora**, como operación propia y por
    pasos, sin cargarlas (spec 015, T19; RF-012-06; ADR-0030 §5): lo que hace :func:`ensure_masks_steps`
    cuando no están al día, sin lo de cargarlas. El último ``Progress`` lleva el :class:`~.store.StoredMasks`
    (la compilación y su informe: lo ganado y perdido por restricción, ``result.changes``). Los rechazos de
    la compilación (``gis.masks.store.begin_compile_steps``: restricciones incompletas, sin límite legal,
    versión no editable…) salen al avanzar y sin registrar nada; cerrarlo a mitad no deja nada (RF-012-28)."""
    return _compile_result(project, version_uid, budget_s)


def _compile_result(project: StoreProject, version_uid: str, budget_s: float
                    ) -> Generator[Progress, None, None]:
    stored, total = yield from _compile(project, version_uid, budget_s)
    yield Progress(_COMPILE_PHASE, total, total, "Máscaras compiladas", result=stored)


def _ensure(project: StoreProject, version_uid: str, compile_first: bool, budget_s: float
            ) -> Iterator[Progress]:
    total = 1
    if compile_first:
        _stored, total = yield from _compile(project, version_uid, budget_s)
    loading = pace_units(load_masks_steps(project, version_uid), budget_s)
    done = total
    while True:  # cargar las máscaras, en pasos cortos
        try:
            next(loading)
        except StopIteration as stop:
            masks = stop.value
            break
        done += 1
        total = max(total, done + 1)
        yield Progress("masks", done, total, "Cargando las máscaras…")
    yield Progress("masks", total, total, "Máscaras al día", result=masks)


def sector_states(project: StoreProject, version_uid: str | None = None
                  ) -> tuple[SectorState, ...]:
    """El estado de cada sector de búsqueda ahora (RF-012-09, RF-012-10; A12, D-26), en su
    orden: los declarados o, sin ellos, el perímetro (código ``""``, «el perímetro de
    actuación», con el perímetro activo en la versión ``version_uid``, uid o código, o en el
    proyecto); cada uno con su búsqueda vigente o pendiente. Solo lee."""
    with project.read() as conn:
        return sector_states_now(conn, project, version_uid)
