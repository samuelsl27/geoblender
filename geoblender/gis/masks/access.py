# SPDX-License-Identifier: GPL-3.0-or-later
"""El contrato de los operadores: pedir las máscaras de una versión (spec 012; RF-012-10,
RF-012-17; plan 012 §5.3.1, A12, D-15, D-26, D-43; ADR-0028 §4 y §5).

Un operador de otro módulo (diseño, verificación…) pide las máscaras **solo** por aquí:

- :func:`mask_state`: el estado de las máscaras de una versión (:class:`MaskState`: al día,
  obsoletas o sin compilar) y los sectores sin búsqueda vigente, calculados al vuelo (A12).
  Están al día si los datos de la última ``gis.compile_constraints`` hecha y no sustituida de la
  versión siguen vivos y ni ellos ni la operación tienen causa en la caché de la obsolescencia de
  la 008 (``gb_stale``): cambiar una restricción, un sector, una búsqueda o un parámetro que
  consumió las deja obsoletas.
- :func:`load_masks`: el :class:`MaskSet` de una versión al día (la rejilla, cada máscara por su
  tipo desde la rejilla de clases, cada zona por su código, el peso de las «preferible no
  afectar», su estado y la marca de búsqueda pendiente con los códigos y los nombres de los
  sectores); :class:`MaskError` si no lo están: nunca se entregan máscaras obsoletas.
- :func:`mask_uses` (o :meth:`MaskSet.uses`): sus ``Use``, para registrarlas como **entradas**
  de la operación que las usa, que así queda obsoleta cuando lo quedan ellas (ADR-0025).
- :func:`ensure_masks_steps` (D-15, D-43): si no están al día, empieza una
  ``gis.compile_constraints`` propia y da sus pasos; el último ``Progress`` lleva el
  :class:`MaskSet`. Si no se pueden compilar, se rechaza con lo mismo que la compilación
  (``gis.masks.store.begin_compile``), antes de dar ningún paso y sin registrar nada.
- :func:`sector_states` (T13): el estado de cada sector de búsqueda ahora (el perímetro si no
  hay sectores), con su búsqueda vigente o pendiente (``core.constraints.store.SectorState``).

Negarse a diseñar en un sector pendiente es cosa de cada operador (D-9; ADR-0028 §5).

Python puro (nivel 2).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Iterator, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

import numpy as np

from ...core.constraints.messages import ConstraintError
from ...core.constraints.store import SectorState
from ...core.datasets import registry as dataset_registry
from ...core.datasets.model import DatasetRecord, DatasetStatus
from ...core.project.model import Progress
from ...core.provenance.operations import OperationStatus, Use
from ...core.versions import read as versions_read
from ...core.versions.model import Version, VersionError
from ..geotiff.reader import read_geotiff
from ..grid import Grid
from ..store import StoreProject
from . import provenance as declared
from .combine import ClassBit
from .compile import STEP_BUDGET_S
from .store import begin_compile, compile_run, current_pending, read_report, read_zone_runs
from .store import sector_states_now
from .zones import Runs

__all__ = [
    "MASK_FAMILIES",
    "MaskError",
    "MaskSet",
    "MaskState",
    "ensure_masks_steps",
    "load_masks",
    "mask_state",
    "mask_uses",
    "sector_states",
]

MASK_FAMILIES: tuple[str, ...] = (declared.CLASSES, declared.ZONES, declared.REPORT)
"""Las familias de datos que lee un :class:`MaskSet` (y que consume quien lo usa)."""
_ROLE_PREFIX = "masks_"


class MaskState(StrEnum):
    """El estado de las máscaras de una versión."""

    CURRENT = "current"  # al día
    STALE = "stale"  # obsoletas: cambió algo que consumió la compilación
    MISSING = "missing"  # sin compilar (o sus datos ya no están)


class MaskError(ConstraintError):
    """Las máscaras pedidas no están al día (RF-012-17): ``core.constraint_masks_missing`` o
    ``core.constraint_masks_stale``, con la versión y la orden de compilar."""


@dataclass(frozen=True, slots=True)
class _Use:
    uid: str
    name: str
    role: str


@dataclass(frozen=True, slots=True, eq=False)
class MaskSet:
    """Las máscaras de una versión al día, como las recibe un operador (ADR-0028 §4): la
    rejilla, la versión, la compilación de la que salen, su estado, los sectores sin búsqueda
    vigente (códigos; ``""`` = el perímetro como sector único) y sus nombres, y la rejilla de
    clases (``uint16``, bits de :class:`~.combine.ClassBit`, fila 0 al norte)."""

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


def _version(conn: sqlite3.Connection, version_uid: str) -> Version:
    found = versions_read.version(conn, version_uid)
    if found is None:
        raise VersionError("core.version_unknown", field="versión", value=version_uid,
                           version=version_uid)
    return found


def _state(conn: sqlite3.Connection, project: StoreProject,
           records: Mapping[str, DatasetRecord | None]) -> tuple[MaskState, str | None]:
    if any(record is None for record in records.values()):
        return MaskState.MISSING, None
    found = {str(record.operation_uid) for record in records.values() if record is not None}
    if len(found) != 1:
        return MaskState.STALE, None
    (operation,) = found
    row = conn.execute("SELECT op_type, status, superseded_by FROM gb_operation WHERE uid = ?",
                       (operation,)).fetchone()
    if (row is None or row[0] != declared.COMPILE or row[1] != OperationStatus.DONE
            or row[2] is not None):
        return MaskState.MISSING, None
    raster = records[declared.CLASSES]
    assert raster is not None
    if not Path(project.root, *raster.locator.split("/")).is_file():
        return MaskState.MISSING, None
    uids = [operation, *(record.uid for record in records.values() if record is not None)]
    marks = ", ".join("?" for _ in uids)
    stale = conn.execute(f"SELECT 1 FROM gb_stale WHERE item_uid IN ({marks}) LIMIT 1",
                         uids).fetchone()
    if stale is not None or any(record is not None and record.status != DatasetStatus.CURRENT
                                for record in records.values()):
        return MaskState.STALE, operation
    return MaskState.CURRENT, operation


def _find(project: StoreProject, version_uid: str) -> _Found:
    with project.read() as conn:
        version = _version(conn, version_uid)
        records = {family: dataset_registry.get(conn, declared.dataset_name(family),
                                                version_uid=version.uid)
                   for family in MASK_FAMILIES}
        state, operation = _state(conn, project, records)
        pending, names = current_pending(conn, project, version.uid)
    live = {family: record for family, record in records.items() if record is not None}
    return _Found(version, state, MappingProxyType(live), operation, pending, names)


def mask_state(project: StoreProject, version_uid: str) -> tuple[MaskState, tuple[str, ...]]:
    """El estado de las máscaras de la versión ``version_uid`` (uid o código) y los códigos de
    los sectores sin búsqueda vigente ahora (RF-012-10; véase el módulo). Solo lee."""
    found = _find(project, version_uid)
    return found.state, found.pending


# --- Entregar ----------------------------------------------------------------------------------


def _refuse(found: _Found) -> MaskError:
    code = ("core.constraint_masks_missing" if found.state is MaskState.MISSING
            else "core.constraint_masks_stale")
    return MaskError(code, field="máscaras", value=found.state.value,
                     version=found.version.code, command=declared.COMMAND)


def load_masks(project: StoreProject, version_uid: str) -> MaskSet:
    """El :class:`MaskSet` de la versión ``version_uid`` (uid o código) si sus máscaras están
    al día; si no, :class:`MaskError` (RF-012-17). Solo lee."""
    found = _find(project, version_uid)
    if found.state is not MaskState.CURRENT or found.operation_uid is None:
        raise _refuse(found)
    records = found.records
    with project.read() as conn:
        (settings,) = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?",
                                   (found.operation_uid,)).fetchone()
        zones = read_zone_runs(conn, records[declared.ZONES].locator)
        weights = {code: float(value) for code, quantity, value, _unit, _note
                   in read_report(conn, records[declared.REPORT].locator)
                   if quantity == "weight" and value is not None}
    grid = declared.grid_of(json.loads(settings))
    raster = records[declared.CLASSES]
    source = read_geotiff(Path(project.root, *raster.locator.split("/")), max_cells=sys.maxsize)
    values = np.asarray(source.values, dtype=np.float64)
    if values.shape != grid.shape:
        raise _refuse(_Found(found.version, MaskState.STALE, records, None, (), ()))
    classes = np.where(np.isfinite(values), values, 0.0).astype(np.uint16)
    used = tuple(_Use(record.uid, record.name,
                      _ROLE_PREFIX + declared.FAMILIES_BY_CODE[family].role)
                 for family, record in records.items())
    return MaskSet(grid, found.version.uid, found.operation_uid, MaskState.CURRENT,
                   found.pending, classes, found.names, MappingProxyType(zones),
                   MappingProxyType(weights), used)


def ensure_masks_steps(project: StoreProject, version_uid: str, *,
                       budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Las máscaras de la versión ``version_uid`` al día (D-15, D-43): si no lo están, empieza
    ya una ``gis.compile_constraints`` propia (sus rechazos, los de
    ``gis.masks.store.begin_compile``, salen aquí, sin registrar nada) y da sus pasos; el último
    ``Progress`` lleva el :class:`MaskSet`."""
    state, _pending = mask_state(project, version_uid)
    steps = None
    if state is not MaskState.CURRENT:
        handle = begin_compile(project, version=version_uid)
        steps = compile_run(project, handle, budget_s=budget_s)
    return _ensure(project, version_uid, steps)


def _ensure(project: StoreProject, version_uid: str,
            steps: Iterator[Progress] | None) -> Iterator[Progress]:
    total = 1
    if steps is not None:
        with closing(steps):
            for step in steps:
                total = step.total + 1
                if step.result is not None:
                    break
                yield Progress(step.phase, step.done, total, step.message)
    masks = load_masks(project, version_uid)
    yield Progress("masks", total, total, "Máscaras al día", result=masks)


def sector_states(project: StoreProject, version_uid: str | None = None
                  ) -> tuple[SectorState, ...]:
    """El estado de cada sector de búsqueda ahora (RF-012-09, RF-012-10; A12, D-26), en su
    orden: los declarados o, sin ellos, el perímetro (código ``""``, «el perímetro de
    actuación», con el perímetro activo en la versión ``version_uid``, uid o código, o en el
    proyecto); cada uno con su búsqueda vigente o pendiente. Solo lee."""
    with project.read() as conn:
        return sector_states_now(conn, project, version_uid)
