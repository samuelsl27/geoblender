# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar, calcular, crear, recalcular y reproducir la **retirada de un acopio** (spec 016, T20; HU-016-2; RF-016-11 a RF-016-15,
RF-015-02, RF-015-03, RF-015-07, RF-015-29; RNF-016-05 y 07; plan 016 §5.1, §5.2.3, §5.3.2, §5.4 A6 a A8, §5.7 P-9 y P-12; ADR-0031 §4).

El homólogo, para la retirada, de ``design.stockpile_store`` (la detección) y de ``design.entity_store`` (la plataforma): **fija el
patrón que siguen el cuerpo apoyado (T25) y el contrafuerte (T27)**. Dominio puro (nivel 8), con numpy. Es un módulo pesado de la
016: lo importan las órdenes al usarlo, no ``bl`` al registrarse.

- **Preparar** (:func:`prepare_removal_units`, por unidades; :func:`prepare_removal`, de una vez): **solo lee** y rechaza **antes de
  calcular** sin registrar nada: la versión (``VersionError``), el nombre y el código ``RMV-nnn`` (``des.entity_name_repeated``), la
  cadena (``des.entity_start_taken``, ``des.entity_chain_cycle``), los parámetros (``des.entity_param_missing`` —el ángulo de
  transición no tiene valor por defecto: D-2—, ``_range`` y ``_choice``), **el acopio y su detección** (``des.removal_stockpile_unknown``;
  con la detección **obsoleta**, ``des.removal_detection_stale`` nombrando el acopio y lo que cambió: RF-016-12), la partida
  (``des.entity_start_unknown``, ``des.surface_*``), un sector con la búsqueda de intocables pendiente (``des.sector_pending``:
  :func:`~.sectors.refuse_pending` **se llama explícitamente**, RF-015-07: la retirada mueve celdas y la detección no) y el nombre de
  un dato. Lee **solo la ventana** del acopio (A0: :func:`~.removal.removal_window`) de la partida, del dominio y de lo que lee de su
  detección (la superficie con que se detectó y la base de su material, dispersas) y atribuye **lo que se le apoyaba**
  (:func:`~.removal.resting_on`, **una sola lista** antes de calcular).
- **Calcular** (:func:`removal_compute_steps`, que **comparten «Calcular», el recálculo y la reproducción**, y
  :func:`compute_removal_steps`, que deja además la superficie, la huella y el informe en los temporales del escritor): A6 y A8
  (``removal.removal_steps`` y ``wall_steps``) por pasos de ``budget_s`` como mucho, sin escribir nada en el proyecto. El resumen
  (:func:`removal_summary`) lleva las cifras, la lista de lo apoyado, la pared y lo que pide confirmar.
- **Crear** (:func:`create_removal`; lo llama ``Calculation.create``): **una** transacción con los parámetros de la entidad (todas sus
  filas, con su origen y su decisor), la operación ``des.stockpile_removal`` con sus entradas —la superficie de partida (``surface``) y,
  con el papel ``removed_stockpile``, lo que lee del acopio: su tabla, su base y la superficie con que se detectó— y los parámetros que
  lee (**el acopio, tal como lo leyó: es lo que lee P-9** para dejar «apoyo retirado» lo que se le apoyaba), la superficie entera
  (``des_psf_``, P-12), la huella (``des_epr_``), el informe (``des_prp_``) y las cifras ``des.rmv_*``. **No se crea sin la confirmación
  expresa** de lo que se le apoyaba (:func:`~.removal.check_resting_confirmed`) ni de la pared
  (:func:`~.removal.check_wall_confirmed`, con su motivo si pasa de CA-9), **sin escribir nada y sin cerrar el cálculo**; el decisor y la
  fecha de la confirmación, el volumen apoyado, la altura y la inclinación de la pared y su motivo quedan en los ajustes de la operación
  (:data:`CONFIRMED`; como la contrapendiente de la 015) y el motivo, además, como parámetro ``wall_reason`` con su historial.
- **Recalcular y reproducir** (:func:`run_removal`, :func:`recompute_removal`; ``design.reproduce.reproduce_stockpile_removal``):
  una operación nueva que sustituye a la anterior con los parámetros vigentes de su entidad, **sin confirmar por la persona** (reutiliza
  lo confirmado mientras lo nuevo no pase de ello: si pasa, vuelve a pedirlo) y, de lo congelado, la misma superficie, huella e informe
  bit a bit.

**La detección del acopio** se busca en la versión y, si no está, en el proyecto (una versión puede consumir un dato del proyecto,
RF-009-05): el código ``STK-001`` es correlativo por ámbito y, si lo tienen los dos, manda el de la versión. La retirada de una
detección **del proyecto** no deja «apoyo retirado» a nadie en la versión (nada se apoya en ella por el registro de la versión;
la lista de :func:`~.removal.resting_on` es lo único que la nombra).
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.params import ParameterStore
from ..core.params.store import default_reason
from ..core.project.model import Progress
from ..core.provenance.operations import OperationHandle
from ..core.provenance.recompute import RecomputeRequest
from ..core.provenance.stale import OPERATION as STALE_OPERATION
from ..core.provenance.stale import item_text
from ..core.timeutil import format_utc
from ..core.versions.model import Version
from ..gis.grid import Grid
from ..gis.masks import access
from ..gis.masks.combine import ClassBit
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.raster import Raster
from ..gis.store import StoreProject
from . import entities, entity_store, pipeline, provenance, removal, stockpile_store
from .entities import EntityKind
from .entity_store import EntityParamRow, entity_parameters, set_entity_params
from .messages import DesignError
from .model import RemovalRequest
from .params import RemovalParam, StockpileParam, check_entity_param, entity_key, entity_params
from .preview import Obsolete, ObsoleteKind, RemovalSummary, RestingLine, obsolete_notices
from .removal import RemovalJob, RemovalOutcome, Resting
from .sectors import design_sectors, refuse_pending
from .seeds import pace_progress, sector_layout
from .stockpile_store import Detection, DetectionMaterial
from .store import (
    DesignWriter,
    OperationStart,
    Row,
    Stored,
    _notice_text,
    _real,
    _result_of,
    _start,
    _store_steps,
    require_version,
)
from .surfaces import project_frame, read_surface_steps, read_surface_window

__all__ = [
    "CONFIRMED",
    "Confirmed",
    "PreparedRemoval",
    "check_removal_confirmed",
    "compute_removal_steps",
    "confirmed_of",
    "create_removal",
    "default_domain",
    "prepare_removal",
    "prepare_removal_units",
    "read_removed",
    "recompute_removal",
    "removal_compute_steps",
    "removal_entity_rows",
    "removal_report_rows",
    "removal_summary",
    "removal_values",
    "run_removal",
]

_COMPUTE_PHASE = "removal_compute"
_DIALOG = "diálogo de «Retirada de un acopio»"
"""El origen de lo que elige la persona en el diálogo de la orden (la entidad al final)."""
_PROTECTS = "una retirada no declara restricciones (D-1): «protect» no es una opción de su diálogo"
CONFIRMED = "removal_confirmed"
"""La clave de los ajustes de ``des.stockpile_removal`` donde queda **lo que la persona confirmó expresamente** al crearla
(:class:`Confirmed`): lo apoyado (``resting``: los m³) y la pared (``wall``: su altura, su inclinación y su motivo), con quién lo
confirmó y cuándo. No es de :func:`~.provenance.removal_settings` (que no la conoce: se confirma después de calcular): la añade
:func:`create_removal` y la arrastra el recálculo (como ``COUNTERSLOPE_CONFIRMED`` de la plataforma)."""
_EPS = 1e-9
_TABLE_COLUMNS = ("code", "key", "name", "origin", "layer", "source_fid", "material", "base_surface", "footprint")


# --- Lo que se prepara --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PreparedRemoval:
    """Lo que se lee y se comprueba antes de calcular una retirada (:func:`prepare_removal_units`): el ``job``
    (``design.removal.RemovalJob``: todo lo leído de la ventana del acopio y nada del proyecto), lo que anotará la operación
    (``start``), el ``code`` de la entidad (``RMV-001``) y su ``version``, el acopio (``ref``: ``STK-001#Acopio 1``; ``detection``: el
    código de su detección; ``scope``: ``version`` o ``project``) y la superficie sobre la que se detectó (``detected_on``), las
    ``rows`` de los parámetros de la entidad —**todas**: sin su fila, ``begin_operation`` crearía la del valor por defecto en el
    proyecto— y sus ``values`` resueltos, los nombres de los datos de la superficie de partida (``start_surface``) y de apoyo
    (``support_surface``; ``None`` sin ella), **la lista única de lo que se le apoyaba** (``resting``), los parámetros del proyecto que
    lee el cálculo (``common``: los de ``provenance.PLATFORM_COMMON_PARAMS``) y de dónde sale su huella en ``des_epr_`` (``layer`` y
    ``source_fid`` de su marca y ``runs``: su huella en tramos de fila). ``existing``: la entidad ya estaba en la versión (se preparó con
    su ``code``: recalcularla), así que «Crear» no escribe otra vez sus parámetros."""

    job: RemovalJob
    start: OperationStart
    code: str
    version: Version
    ref: str
    detection: str
    scope: str
    detected_on: str
    rows: tuple[EntityParamRow, ...]
    values: Mapping[str, Any]
    start_surface: str
    support_surface: str | None
    resting: tuple[Resting, ...]
    common: Mapping[str, float]
    layer: str
    source_fid: int
    runs: tuple[tuple[int, int, int], ...]
    existing: bool = False

    @property
    def op_type(self) -> str:
        """El tipo de la operación (``des.stockpile_removal``)."""
        return self.start.op_type


# --- Lo que confirma la persona ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Confirmed:
    """Lo que la persona confirmó **expresamente** al crear la retirada (RF-016-14, RF-016-15): quién (``decided_by``) y cuándo
    (``decided_on``, UTC), los m³ apoyados que confirmó (``resting_m3``; ``None``: nada que confirmar) y la pared (``wall_height_m`` y
    ``wall_angle_deg`` del tramo más alto, ``wall_reason`` su motivo si lo pidió CA-9; ``None``: sin pared). Un recálculo lo reutiliza
    mientras lo nuevo no pase de ello (:meth:`covers_resting`, :meth:`covers_wall`); si pasa, vuelve a pedirlo."""

    decided_by: str
    decided_on: str
    resting_m3: float | None = None
    wall_height_m: float | None = None
    wall_angle_deg: float | None = None
    wall_reason: str | None = None

    def covers_resting(self, volume_m3: float) -> bool:
        """Si ``volume_m3`` apoyados entran en lo confirmado."""
        return self.resting_m3 is not None and volume_m3 <= self.resting_m3 * (1.0 + _EPS) + _EPS

    def covers_wall(self, height_m: float) -> bool:
        """Si una pared de ``height_m`` entra en la confirmada (con su motivo, si la confirmada lo llevó)."""
        return self.wall_height_m is not None and height_m <= self.wall_height_m + _EPS

    def settings(self) -> dict[str, Any]:
        """Lo que se anota en los ajustes de la operación (JSON): ``resting`` y ``wall``, cada uno si se confirmó, con su decisor y su
        fecha."""
        found: dict[str, Any] = {}
        who = {"decided_by": self.decided_by, "decided_on": self.decided_on}
        if self.resting_m3 is not None:
            found["resting"] = {"volume_m3": self.resting_m3, **who}
        if self.wall_height_m is not None:
            wall: dict[str, Any] = {"height_m": self.wall_height_m, "angle_deg": self.wall_angle_deg}
            if self.wall_reason is not None:
                wall["reason"] = self.wall_reason
            found["wall"] = {**wall, **who}
        return found


def confirmed_of(settings: Mapping[str, Any]) -> Confirmed | None:
    """Lo confirmado que guardan los ajustes ``settings`` de una operación ``des.stockpile_removal`` (:data:`CONFIRMED`), o ``None`` si
    no lo llevan (no hubo nada que confirmar). ``ValueError`` si lo llevan y no es una confirmación (nombrando el campo)."""
    found = settings.get(CONFIRMED) if isinstance(settings, Mapping) else None
    if found is None:
        return None
    if not isinstance(found, Mapping):
        raise ValueError(f"los ajustes de una retirada, «{CONFIRMED}», son un diccionario, no {found!r}")
    resting, wall = found.get("resting"), found.get("wall")
    kept = [item for item in (resting, wall) if isinstance(item, Mapping)]
    if not kept:
        return None
    who, when = kept[0].get("decided_by"), kept[0].get("decided_on")
    if not isinstance(who, str) or not isinstance(when, str):
        raise ValueError(f"los ajustes de una retirada, «{CONFIRMED}», no dicen quién confirmó ni cuándo")
    reason = wall.get("reason") if isinstance(wall, Mapping) else None
    return Confirmed(
        who, when, None if not isinstance(resting, Mapping) else float(resting["volume_m3"]),
        None if not isinstance(wall, Mapping) else float(wall["height_m"]),
        None if not isinstance(wall, Mapping) else float(wall["angle_deg"]),
        reason if isinstance(reason, str) else None)


def check_removal_confirmed(prepared: PreparedRemoval, outcome: RemovalOutcome, *, resting: bool, wall: bool) -> None:
    """**No se crea la retirada sin la confirmación expresa** (RF-016-14, RF-016-15; errores 47 y 59): con algo apoyado en el acopio
    y sin ``resting``, ``des.removal_resting_unconfirmed``; con una pared y sin ``wall``, ``des.removal_wall_unconfirmed`` y, de más
    de 45° y 3 m (CA-9) y sin el motivo de la petición (``wall_reason``), ``des.removal_wall_reason``. No escribe nada."""
    name = prepared.job.stockpile.name
    removal.check_resting_confirmed(name, prepared.resting, confirmed=resting)
    if outcome.wall is not None:
        removal.check_wall_confirmed(name, outcome.wall, confirmed=wall, reason=prepared.job.request.wall_reason)


def _confirmation(project: StoreProject, prepared: PreparedRemoval, outcome: RemovalOutcome, *, resting: bool, wall: bool,
                  decided_by: str | None) -> Confirmed | None:
    """Lo que se confirma al crear (con ``resting`` y ``wall``, de lo que haya): quién (``decided_by``; por defecto, quien tiene abierto
    el proyecto), cuándo (ahora, UTC), lo apoyado, la pared y su motivo; ``None`` si no había nada que confirmar."""
    found = outcome.wall
    walled = found is not None and found.needs_confirmation and wall
    rests = bool(prepared.resting) and resting
    if not walled and not rests:
        return None
    worst = None if found is None else found.worst
    return Confirmed(
        decided_by or project.session.user_host, format_utc(project.clock.now()),
        math.fsum(row.volume_m3 for row in prepared.resting) if rests else None,
        worst.height_m if walled and worst is not None else None, worst.angle_deg if walled and worst is not None else None,
        (prepared.job.request.wall_reason or "").strip() or None if walled else None)


# --- Los parámetros -----------------------------------------------------------------------------


def removal_values(request: RemovalRequest, code: str) -> tuple[dict[str, Any], frozenset[str]]:
    """Los parámetros resueltos y comprobados de la retirada ``request`` de código ``code`` (RF-015-08; por último segmento de su
    clave) y **los nombres de los que se dejaron por su valor por defecto**: el ángulo de transición no tiene ninguno (D-2: la
    petición no lleva ninguna cifra minera; ``des.entity_param_missing``); el factor de malla y la métrica, sí (1,0 y la euclídea exacta;
    ``des.entity_param_range`` y ``_choice``). La «capa» de los mensajes es el acopio que se retira. **Sin proyecto**: lo comparten
    preparar y reproducir. ``ValueError`` si pide declarar restricciones (``protect``: no es una opción de la retirada)."""
    if request.protect:
        raise ValueError(_PROTECTS)
    spec = entity_params("removal")
    layer = request.stockpile
    defaulted: set[str] = set()
    asked: dict[RemovalParam, object] = {
        RemovalParam.NAME: request.name, RemovalParam.STOCKPILE: request.stockpile, RemovalParam.START: request.start,
        RemovalParam.SUPPORT: request.support, RemovalParam.TRANSITION: request.transition_deg,
        RemovalParam.WALL_REASON: request.wall_reason, RemovalParam.GUARD: request.guard_m, RemovalParam.REASON: request.reason}
    for param, given in ((RemovalParam.MESH_FACTOR, request.mesh_factor),
                         (RemovalParam.METRIC, None if request.metric is None else str(request.metric))):
        if given is None:
            given = spec.template(param.value).default
            defaulted.add(param.value)
        asked[param] = given
    asked[RemovalParam.PROTECT] = False
    defaulted.add(RemovalParam.PROTECT.value)
    values: dict[str, Any] = {}
    for param in RemovalParam:
        if param in (RemovalParam.SUPPORTS, RemovalParam.DISCARDED):
            continue
        checked = check_entity_param(request.name, code, param.value, asked[param], layer=layer,
                                     required=False if param is RemovalParam.GUARD else None)
        if checked is not None:
            values[param.value] = checked
    return values, frozenset(defaulted)


def _rows(request: RemovalRequest, code: str, values: Mapping[str, Any], defaulted: frozenset[str]
          ) -> tuple[EntityParamRow, ...]:
    """Las filas de los parámetros de la entidad con su procedencia (RF-008-01): lo que no se pidió, con la de su valor por defecto;
    el resto, lo que eligió la persona en el diálogo. **Todas** (también las de los valores por defecto)."""
    spec = entity_params("removal")
    rows: list[EntityParamRow] = []
    for param in RemovalParam:
        value = values.get(param.value)
        if value is None:
            continue
        if param.value in defaulted:
            declared = spec.template(param.value)
            source, kind, reason = declared.source, str(declared.source_kind), default_reason(declared)
        else:
            source, kind = f"{_DIALOG}, entidad «{request.name}»", "person"
            reason = f"Elegido al crear la retirada de acopio «{request.name}»"
        rows.append(EntityParamRow(entity_key(code, param), param.value, value, source, kind, reason))
    return tuple(rows)


# --- El acopio y su detección ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class _Located:
    """La detección del acopio que se retira, ya leída: la ``detection``, la ``row`` del acopio en su tabla, su ``material``
    (la base de su material) y la superficie sobre la que se detectó."""

    detection: Detection
    row: Mapping[str, Any]
    material: DetectionMaterial
    detected_on: str


def _locate(project: StoreProject, version: Version, request: RemovalRequest, code: str) -> _Located:
    """La detección del acopio ``request.stockpile`` (``STK-001#Acopio 1``), **al día**, en la versión o, si no, en el proyecto, y la fila
    del acopio en su tabla. ``des.removal_stockpile_unknown`` si la referencia no la tiene, la detección no existe, está sin calcular
    o descartada o no tiene ese acopio; ``des.removal_detection_stale`` (RF-016-12) si **está obsoleta**, nombrando el acopio, la
    detección y lo que cambió (la causa de la 008). Solo lee."""
    obj, field = f"Retirada «{request.name}»", entity_key(code, RemovalParam.STOCKPILE)

    def unknown(where: str) -> DesignError:
        return DesignError("des.removal_stockpile_unknown", obj=obj, field=field, value=request.stockpile, entity=request.name,
                           where=where)

    try:
        detection_code, key = provenance.split_support_ref(request.stockpile)
    except ValueError:
        raise unknown(version.code) from None
    if key is None:
        raise unknown(version.code)
    with project.read() as conn:
        for scope in (version, None):
            registry = (entities.registry(project, version.uid, conn=conn) if scope is not None
                        else entities.project_registry(project, conn=conn))
            entry = registry.get(detection_code)
            if entry is None or entry.record.kind != EntityKind.STOCKPILE or entry.record.code != detection_code:
                continue
            where = version.code if scope is not None else "el proyecto"
            if entry.operation_uid is None or entry.record.state in (entities.EntityState.UNCALCULATED, entities.EntityState.DISCARDED):
                raise unknown(where)
            if entry.record.state is not entities.EntityState.CURRENT:
                cause = item_text(conn, STALE_OPERATION, entry.operation_uid, language="es") or "cambió algo de lo que lee"
                raise DesignError("des.removal_detection_stale", obj=obj, field=field, value=request.stockpile,
                                  stockpile=key, detection=entry.record.name, cause=cause)
            surface = ParameterStore(project).get(entity_key(detection_code, StockpileParam.SURFACE),
                                                  version=None if scope is None else version.uid, conn=conn)
            detected_on = "" if surface is None or surface.value is None else str(surface.value)
            found = stockpile_store._detection_of(project, conn, scope, detection_code, entry.record.name, entry.operation_uid,
                                                  detected_on)
            table = stockpile_store.read_detection_table(project, provenance.STOCKPILES_TABLE, found.name,
                                                         version_uid=found.version_uid, conn=conn)
            row = next((item for item in table if item["key"] == key), None)
            if row is None:
                raise unknown(where)
            material = next((item for item in found.materials if item.material == row["material"]), None)
            if material is None or found.detected is None:
                raise unknown(where)
            return _Located(found, row, material, detected_on)
    raise unknown(version.code)


def read_removed(row: Mapping[str, Any], grid: Grid, base: Callable[[tuple[slice, slice]], np.ndarray],
                 detected: Callable[[tuple[slice, slice]], np.ndarray]) -> removal.RemovedStockpile:
    """El acopio de la fila ``row`` de la tabla de acopios de su detección (``des_stk_``: su clave, su nombre y su huella en tramos) tal
    como lo retira la retirada (:class:`~.removal.RemovedStockpile`): las celdas de su huella (``fila · columnas + columna``,
    crecientes) y, **en ellas**, la base de su material (``base``) y la superficie con que se detectó (``detected``), cada una **una
    función de la ventana** de la rejilla (filas y columnas) que da sus celdas: la preparación lee solo esa ventana del fichero y la
    reproducción la corta de la rejilla congelada. Lo que comparten las dos: el mismo acopio. ``ValueError`` si no hay celdas."""
    runs = tuple(tuple(int(value) for value in run) for run in json.loads(str(row["footprint"])))
    rows, cols = entities.runs_cells(runs)
    if rows.size == 0:
        raise ValueError(f"el acopio «{row['key']}» no tiene celdas en su huella")
    window = (slice(int(rows.min()), int(rows.max()) + 1), slice(int(cols.min()), int(cols.max()) + 1))
    inside = (rows - window[0].start, cols - window[1].start)
    return removal.RemovedStockpile(
        str(row["key"]), str(row["name"]), rows.astype(np.int64) * grid.ncols + cols, base(window)[inside], detected(window)[inside])


def default_domain(masks: access.MaskSet | access.MaskSource, window: tuple[slice, slice]) -> np.ndarray:
    """El dominio por defecto de las máscaras (``MaskSet.default_domain``: perímetro ∩ límite legal − intocables, donde se puede
    retirar un acopio aunque su corte no esté admitido: D-5) **en la ventana** ``window``, de las clases de esa ventana."""
    classes = masks.classes_window(window)

    def bit(found: ClassBit) -> np.ndarray:
        return (classes & np.uint16(int(found))) != 0

    return bit(ClassBit.PERIMETER) & bit(ClassBit.LEGAL) & ~bit(ClassBit.UNTOUCHABLE)


# --- Preparar -----------------------------------------------------------------------------------


def _check_chain(registry: entities.EntityRegistry, request: RemovalRequest, code: str) -> None:
    """RF-015-04: de cada superficie parte como mucho una entidad (``des.entity_start_taken``, con la que ya parte) y la cadena no da
    la vuelta (``des.entity_chain_cycle``); la retirada ``code`` no cuenta consigo misma."""
    other = entities.start_conflict(registry.records, request.start, ignoring=code)
    if other is not None:
        raise DesignError("des.entity_start_taken", obj=f"Retirada «{request.name}»",
                          field=entity_key(code, RemovalParam.START), value=request.start, entity=request.name, other=other.name)
    records = [item for item in registry.records if item.code != code]
    entities.check_chain([*records, entities.EntityRecord(code, request.name, EntityKind.REMOVAL, request.start, request.support)])


def prepare_removal_units(project: StoreProject, request: RemovalRequest, version: Version,
                          masks: access.MaskSet | access.MaskSource, *, code: str | None = None,
                          supersedes: str | None = None, released: Sequence[provenance.ReleasedSupport] = ()
                          ) -> Generator[None, None, PreparedRemoval]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan la retirada ``request`` de la versión editable
    ``version`` con sus ``masks`` ya al día (:func:`~.store.masks_steps`; ``MaskSet`` o ``MaskSource``, que no lleva las celdas):
    el código (``code``: el de una entidad que ya está en la versión, que no choca consigo misma; si no, el siguiente, ``RMV-001``), el
    nombre único y la cadena, los parámetros resueltos, **el acopio y su detección** (obsoleta: RF-016-12), la partida y las
    ventanas de lo que lee, el dominio, los sectores con la búsqueda pendiente, lo que se le apoyaba y lo que anotará la operación.
    ``supersedes``: la operación hecha a la que sustituye (un recálculo); ``released``: lo que da por bueno sin su apoyo. Devuelve la
    :class:`PreparedRemoval`. **Nada se escribe**; los rechazos salen al avanzar, en el orden de la documentación del módulo."""
    require_version(project, version.uid, provenance.STOCKPILE_REMOVAL)
    registry = entities.registry(project, version.uid)
    chosen = code if code is not None else entities.next_code(EntityKind.REMOVAL, (entry.record.code for entry in registry))
    entity_store._check_name(registry, request.name, chosen, version.code)
    _check_chain(registry, request, chosen)
    yield
    values, defaulted = removal_values(request, chosen)
    found = _locate(project, version, request, chosen)
    yield
    frame = project_frame(project)
    grid = frame.grid
    start_name = entity_store._surface_dataset(registry, version, request, chosen, RemovalParam.START, request.start)  # type: ignore[arg-type]
    support_name = (None if request.support is None else entity_store._surface_dataset(
        registry, version, request, chosen, RemovalParam.SUPPORT, request.support))  # type: ignore[arg-type]
    detection = found.detection

    def of_detection(name: str, what: str) -> Callable[[tuple[slice, slice]], np.ndarray]:
        return lambda window: read_surface_window(project, name, window, version_uid=detection.version_uid, expect=frame,
                                                  role=what).values

    assert detection.detected is not None
    item = read_removed(found.row, grid, of_detection(found.material.base.name, f"base del acopio «{found.row['key']}»"),
                        of_detection(detection.detected.name, f"superficie con que se detectó «{found.row['key']}»"))
    window = removal.removal_window(item, grid)
    yield
    start = read_surface_window(project, start_name, window, version_uid=version.uid, expect=frame,
                                role="superficie de partida")
    domain = default_domain(masks, window)
    yield
    sectors = design_sectors(project, version.uid)
    if any(sector.pending for sector in sectors):  # RF-015-07: la retirada mueve celdas (la detección no)
        refs, labels = sector_layout(project, masks)  # type: ignore[arg-type]
        rows, cols = np.divmod(item.cells, grid.ncols)
        footprint = np.zeros(domain.shape, dtype=bool)
        footprint[rows - window[0].start, cols - window[1].start] = True
        touched = pipeline.touched_in(refs, labels[window], footprint)
        refuse_pending(sector for sector in sectors if sector.code in touched)
    yield
    common = entity_store._common(project, version)
    job = RemovalJob(request, chosen, grid, start.values, item, domain, MappingProxyType(dict(values)), window)
    resting = removal.resting_on(project, version, item, start_name, detected_on=found.detected_on)
    yield
    supported, footprints, reads = entity_store._support_inputs(
        project, version, request, chosen, registry, support_name,  # type: ignore[arg-type]
        entity_store._released_codes(project, supersedes, released))
    removed = (detection.stockpiles.name, found.material.base.name, detection.detected.name)
    inputs = provenance.removal_inputs(request, start_name, removed, masks.uses(), supported)
    inputs = (*inputs, *(use for use in footprints if use not in inputs))
    begun = _start(project, provenance.STOCKPILE_REMOVAL, request.name, version, masks,  # type: ignore[arg-type]
                   provenance.removal_settings(request, chosen), inputs,
                   provenance.removal_params(chosen, request, supports=reads), supersedes)
    yield
    row = found.row
    runs = tuple(tuple(int(value) for value in run) for run in json.loads(str(row["footprint"])))
    return PreparedRemoval(
        job, begun, chosen, version, request.stockpile, detection.code, stockpile_store.PROJECT if detection.version_uid == ""
        else stockpile_store.VERSION, found.detected_on, _rows(request, chosen, values, defaulted), MappingProxyType(values),
        start_name, support_name, resting, MappingProxyType(common), str(row["layer"] or detection.name),
        int(row["source_fid"] or 0), runs, code is not None)  # type: ignore[arg-type]


def prepare_removal(project: StoreProject, request: RemovalRequest, *, version: str | None,
                    masks: access.MaskSet | None = None, code: str | None = None,
                    supersedes: str | None = None) -> PreparedRemoval:
    """La preparación entera de :func:`prepare_removal_units` de una vez (sin ceder el hilo; las máscaras que no se dan se abren sin
    cargar sus celdas: ``entity_store._masks_to_read``): la :class:`PreparedRemoval`, con los mismos rechazos y sin escribir nada."""
    found = require_version(project, version, provenance.STOCKPILE_REMOVAL)
    loaded = entity_store._masks_to_read(project, found, masks)
    return _result_of(prepare_removal_units(project, request, found, loaded, code=code, supersedes=supersedes))


# --- Calcular (RF-015-03, RF-015-29, RNF-016-05) ----------------------------------------------------


def removal_compute_steps(job: RemovalJob, common: Mapping[str, object], *, budget_s: float = STEP_BUDGET_S
                          ) -> Generator[Progress, None, RemovalOutcome]:
    """Los pasos que calculan la retirada de ``job`` (RF-016-11, RF-016-13, RF-016-15, RF-015-29; plan 016 §5.3.2: el
    ``removal_compute_steps`` que **comparten «Calcular», el recálculo y la reproducción**, como ``entity_store.platform_compute_steps``),
    sin proyecto y sin escribir nada (``yield from``; cerrar el generador no deja nada): A6, la transición y el dominio
    (``removal.removal_steps``) y A8, la pared (``removal.wall_steps``), por pasos de ``budget_s`` como mucho. ``common`` son los
    parámetros del proyecto que lee la pared (``provenance.PLATFORM_COMMON_PARAMS``). Devuelve el :class:`~.removal.RemovalOutcome`."""
    name = job.request.name
    yield Progress(_COMPUTE_PHASE, 0, 1, f"Calculando la retirada «{name}»…")
    outcome: RemovalOutcome = yield from pipeline.forward(removal.removal_steps(job, budget_s=budget_s))
    outcome = yield from pipeline.forward(removal.wall_steps(job, outcome, common, budget_s=budget_s))
    yield Progress(_COMPUTE_PHASE, 1, 1, f"Retirada «{name}» calculada")
    return outcome


def _whole_start_steps(project: StoreProject, prepared: PreparedRemoval, budget_s: float) -> Generator[Progress, None, np.ndarray]:
    """La superficie de partida **entera** (un array nuevo que el llamador puede modificar), leída por bandas de filas dentro del
    cálculo —lo que hace falta para escribir la superficie de salida (P-12)—. La ventana leída antes ha de ser **igual** a la de ahora
    (bit a bit, el NaN incluido): si el dato cambió en medio, ``des.input_changed`` y no se escribe nada."""
    job = prepared.job
    name = job.request.name
    raster = yield from pipeline.forward(pace_progress(
        read_surface_steps(project, prepared.start_surface, version_uid=prepared.start.version_uid,
                           expect=project_frame(project), role="superficie de partida"),
        budget_s, phase=_COMPUTE_PHASE, running=f"Leyendo la superficie de partida de «{name}»…",
        finished="Superficie de partida leída"))
    whole = np.array(raster.values, dtype=np.float64, copy=True)
    if not np.array_equal(whole[job.window], job.start, equal_nan=True):
        raise DesignError("des.input_changed", obj=f"Superficie «{prepared.start_surface}»", field="entradas",
                          value=prepared.start_surface)
    return whole


def removal_entity_rows(job: RemovalJob, outcome: RemovalOutcome, *, layer: str, source_fid: int,
                        runs: Sequence[Sequence[int]], start_surface: str, support_surface: str | None) -> list[Row]:
    """La fila de ``des_epr_`` (columnas de :data:`~.store.ENTITY_COLUMNS`) de la retirada de ``job`` con su ``outcome`` (RF-015-01):
    **una**, con los atributos de la entidad —su código, su nombre, su tipo ``removal``, los datos de su superficie de partida y de
    apoyo, **la capa y el ``fid`` de la marca del acopio** (lo que sale de su fila de ``des_stk_``), el hash de su huella, el modo
    ``removal`` y las celdas de la huella—, su ventana de trabajo, **la huella del acopio entera** en tramos de fila y ningún eje.
    Solo depende de lo que se lee para calcular, no del proyecto: lo repite la reproducción desde lo congelado."""
    text = json.dumps([list(run) for run in runs], separators=(",", ":"), allow_nan=False)
    rows, cols = outcome.window
    return [(job.code, job.request.name, EntityKind.REMOVAL.value, start_surface, support_surface, layer, int(source_fid),
             hashlib.sha256(text.encode()).hexdigest(), "removal", int(job.stockpile.cells.size), 0,
             json.dumps([int(rows.start), int(rows.stop), int(cols.start), int(cols.stop)], separators=(",", ":")), text, "[]")]


def removal_report_rows(outcome: RemovalOutcome) -> list[Row]:
    """Las filas de ``des_prp_`` (formato largo: ``quantity, value, unit_code, note``; RF-016-13, RF-016-15) de la retirada
    ``outcome``, en este orden: la huella (celdas, las que se retiran y las que no se admiten), las cifras (retirado, apoyado,
    transición, no retirado, el área de la transición y lo que había sobre la base), el ángulo y el factor de malla, la pared (la
    altura de la mayor con su lugar, el límite, la tolerancia de cara, el espesor mínimo, el salto admitido, las parejas y **los dos
    umbrales de CA-9 copiados**, una fila por tramo) y, al final, los avisos y notas (``warning`` y ``note`` con su código y sus
    valores en JSON). Un valor que no es finito es un error del programa (``ValueError``). Solo depende del resultado: lo repite
    la reproducción."""
    rows: list[Row] = []

    def scalar(key: str, value: float, unit: str, note: str | None = None) -> None:
        rows.append((key, _real(key, value), unit, note))

    scalar("footprint_cells", int(outcome.footprint.sum()), "-")
    scalar("admitted_cells", int(outcome.admitted.sum()), "-")
    scalar("held_cells", int(outcome.held.sum()), "-")
    for key, value, unit in (("removed_m3", outcome.removed_m3, "m3"), ("resting_m3", outcome.resting_m3, "m3"),
                             ("transition_m3", outcome.transition_m3, "m3"), ("kept_m3", outcome.kept_m3, "m3"),
                             ("transition_m2", outcome.transition_m2, "m2"), ("above_base_m3", outcome.above_base_m3, "m3"),
                             ("transition_deg", outcome.transition_deg, "deg"), ("mesh_factor", outcome.mesh_factor, "-")):
        scalar(key, value, unit)
    wall = outcome.wall
    if wall is not None:
        worst = wall.worst
        place = None if worst is None else f"{_real('wall.x', worst.x)!r};{_real('wall.y', worst.y)!r}"
        scalar("wall_max_m", wall.height_m, "m", place)
        for key, value, unit in (("wall_limit_deg", wall.limit_deg, "deg"), ("wall_tolerance_deg", wall.tolerance_deg, "deg"),
                                 ("wall_min_thickness_m", wall.thickness_m, "m"), ("wall_jump_m", wall.jump_m, "m"),
                                 ("wall_pairs", wall.pairs, "-"), ("wall_over_pairs", wall.over, "-"),
                                 ("wall_reason_min_angle_deg", wall.reason_min_angle_deg, "deg"),
                                 ("wall_reason_min_height_m", wall.reason_min_height_m, "m")):
            scalar(key, value, unit)
        for stretch in wall.stretches:
            scalar("wall_stretch", stretch.height_m, "m", json.dumps({
                "stretch": stretch.stretch, "pairs": stretch.pairs, "angle_deg": _real("wall_stretch.angle", stretch.angle_deg),
                "step_m": _real("wall_stretch.step", stretch.step_m), "x": _real("wall_stretch.x", stretch.x),
                "y": _real("wall_stretch.y", stretch.y)}, separators=(",", ":"), allow_nan=False))
    for notice in outcome.notices:
        rows.append((notice.severity, None, None, _notice_text(notice)))
    return rows


def compute_removal_steps(writer: DesignWriter, prepared: PreparedRemoval, *, budget_s: float = STEP_BUDGET_S
                          ) -> Generator[Progress, None, RemovalOutcome]:
    """Lo que hace «Calcular» sobre el ``writer`` (RF-015-03, RF-015-29; patrón de ``entity_store.compute_platform_steps``): calcula la
    retirada preparada (:func:`removal_compute_steps`), deja su superficie —la de partida, entera, con el resultado en la ventana del
    acopio— en el temporal de ``writer`` (``des_psf_``, con su hash) y prepara, con su hash en memoria, la huella (``des_epr_``) y el
    informe (``des_prp_``), **sin confirmar**: lo que falta para crearla (:func:`create_removal`) es una sola transacción. Devuelve el
    :class:`~.removal.RemovalOutcome`."""
    job = prepared.job
    outcome = yield from removal_compute_steps(job, prepared.common, budget_s=budget_s)
    surface = yield from _whole_start_steps(writer.project, prepared, budget_s)
    surface[outcome.window] = outcome.surface
    yield from pipeline.forward(_store_steps(
        writer.grid_steps(provenance.ENTITY_SURFACE_GRID, Raster(job.grid, surface, writer.crs, writer.vertical)), budget_s,
        "la superficie de la retirada"))
    entity = removal_entity_rows(job, outcome, layer=prepared.layer, source_fid=prepared.source_fid, runs=prepared.runs,
                                 start_surface=prepared.start_surface, support_surface=prepared.support_surface)
    yield from pipeline.forward(_store_steps(writer.table_steps(provenance.ENTITY_TABLE, entity), budget_s,
                                             "la huella de la retirada"))
    yield from pipeline.forward(_store_steps(writer.table_steps(provenance.ENTITY_REPORT_TABLE, removal_report_rows(outcome)),
                                             budget_s, "el informe de la retirada"))
    return outcome


# --- El resumen (RF-015-03, RF-016-13 a 15) -------------------------------------------------------


def removal_obsolete(project: StoreProject, prepared: PreparedRemoval, *, supersedes: str | None = None) -> tuple[Obsolete, ...]:
    """**Lo que quedará obsoleto al crear** la retirada ``prepared`` (RF-015-03, RF-015-16): una retirada nueva no deja obsoleto nada
    (lo que se le apoyaba queda en «apoyo retirado», que es la lista de :attr:`PreparedRemoval.resting`); la que **sustituye** una
    operación (``supersedes``: un recálculo) deja obsoleto lo que dependía de lo que escribió, en cascada. Solo lee."""
    if supersedes is None:
        return ()
    with project.read() as conn:
        written = [str(row[0]) for row in conn.execute(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' AND item_kind = 'dataset' "
            "ORDER BY fid", (supersedes,))]
        found = entity_store._dependents(conn, written, prepared.version.uid, exclude=(supersedes,))
    return tuple(entity_store._consumer(ObsoleteKind.DEPENDENT, uid, op_type, name) for uid, op_type, name in found)


def removal_summary(project: StoreProject, prepared: PreparedRemoval, outcome: RemovalOutcome, *,
                    supersedes: str | None = None) -> RemovalSummary:
    """El resumen de «Calcular» la retirada ``prepared`` (RF-015-03, RF-016-13 a 15): las cifras que se registrarán, **la lista de lo
    que se le apoyaba** (antes de calcular, sin escribir nada), la pared y qué pide confirmar, y los avisos en el orden en que se
    enseñan (lo apoyado, los de la retirada y lo que quedará obsoleto). Solo lee."""
    name = prepared.job.stockpile.name
    kept = removal_obsolete(project, prepared, supersedes=supersedes)
    wall = outcome.wall
    worst = None if wall is None else wall.worst
    notices = (*removal.resting_notices(name, prepared.resting), *outcome.notices,
               *obsolete_notices(prepared.job.request.name, prepared.version.code, kept))
    return RemovalSummary(
        prepared.job.request.name, prepared.code, prepared.version.code, prepared.ref, name, outcome.figures,
        tuple(RestingLine(row.name, row.kind(), row.volume_m3, row.cells) for row in prepared.resting),
        None if worst is None else worst.height_m, None if worst is None else worst.angle_deg, bool(prepared.resting),
        wall is not None and wall.needs_confirmation, wall is not None and wall.needs_reason, notices, kept)


# --- Crear (RF-016-11, RF-016-13 a 15, RF-015-01, RF-015-02; RNF-016-07) ----------------------------------


def create_removal(project: StoreProject, writer: DesignWriter, prepared: PreparedRemoval, outcome: RemovalOutcome, *,
                   resting: bool = False, wall: bool = False, decided_by: str | None = None) -> Stored:
    """**«Crear» una retirada** (RF-016-11, RF-016-13 a 15, RF-015-01, RF-015-02): registra en **una** transacción
    (:meth:`~.store.DesignWriter.commit` de ``writer``, el de «Calcular», con sus tres salidas preparadas) los parámetros de la entidad
    —una fila de la versión por parámetro, con su origen y su decisor ``decided_by`` (por defecto, quien tiene abierto el proyecto)—,
    la operación ``des.stockpile_removal`` con sus entradas (la superficie de partida, lo que lee del acopio con el papel
    ``removed_stockpile`` y las máscaras) y sus parámetros (entre ellos **el acopio: lo que lee P-9**), las tres salidas y las cifras
    con el ámbito de la entidad. **No se crea sin la confirmación expresa** (``resting`` de lo que se le apoyaba, ``wall`` de la pared y,
    de más de 45° y 3 m, su motivo, ``RemovalRequest.wall_reason``): ``DesignError`` ``des.removal_resting_unconfirmed``,
    ``des.removal_wall_unconfirmed`` o ``des.removal_wall_reason`` **antes de escribir nada**. Lo confirmado queda en los ajustes de la
    operación (:data:`CONFIRMED`: quién, cuándo, lo apoyado, la altura y la inclinación de la pared y su motivo). Una entidad que ya estaba en la versión (``prepared.existing``) no vuelve a escribir sus parámetros. Si algo falla,
    o lo que consume cambió desde que se calculó (``des.input_changed``), no queda nada y el error sigue; **no modifica ninguna
    entrada**."""
    check_removal_confirmed(prepared, outcome, resting=resting, wall=wall)
    start = prepared.start
    carried = _confirmation(project, prepared, outcome, resting=resting, wall=wall, decided_by=decided_by)
    if carried is not None:
        start = replace(start, settings={**start.settings, CONFIRMED: carried.settings()})

    def parameters(conn: sqlite3.Connection) -> None:
        if prepared.existing:
            if ParameterStore(project).get(entity_key(prepared.code, RemovalParam.NAME), version=start.version_uid,
                                           conn=conn) is None:
                raise ValueError(f"la entidad {prepared.code} no tiene sus parámetros en la versión: no está en ella (se prepara "
                                 "sin su código)")
        else:
            set_entity_params(project, prepared.rows, version=start.version_uid, decided_by=decided_by, conn=conn)

    return writer.commit(start, figures=outcome.figures, message=outcome.message, before_begin=parameters)


# --- Recalcular (RF-015-02, RF-015-16, RF-008-26) ------------------------------------------------------


def _check_recorded(handle: OperationHandle, prepared: PreparedRemoval) -> None:
    """Los parámetros que anotó la operación al empezar son los que leyó el cálculo al prepararse (RF-013-17, D-14): si uno cambió entre
    las dos cosas, el resultado ya no le corresponde (``des.input_changed``, con el parámetro)."""
    read: dict[str, object] = {entity_key(prepared.code, RemovalParam(name)): value for name, value in prepared.values.items()}
    read.update(prepared.common)
    for param in handle.params:
        if param.key in read and param.value != read[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»", field="parámetros", value=param.key)


def run_removal(project: StoreProject, request: RemovalRequest, *, version: str | None, code: str,
                masks: access.MaskSet | None = None, supersedes: str | None = None, confirmed: Confirmed | None = None,
                budget_s: float = STEP_BUDGET_S, released: Sequence[provenance.ReleasedSupport] = ()
                ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Calcula y registra ``request`` —una retirada que ya está en la versión ``version``: su ``code``— de **una vez**, sin pedir
    confirmación a la persona (RF-015-02, RF-015-16; el recálculo de lo obsoleto, :func:`~.store.recompute_run`; el «Crear» tras
    «Calcular» es :meth:`~.steps.Calculation.create`): empieza la operación ``des.stockpile_removal`` —si ``supersedes`` es la de una
    anterior, la sustituye, quedándose con los nombres de sus datos— con lo que lee hoy y devuelve su ``OperationHandle`` «en curso» y
    sus pasos, que avanza quien la llama: calculan (:func:`removal_compute_steps`), escriben la superficie, la huella y el informe y
    completan la operación en una transacción; el último lleva el :class:`~.store.Stored`. No escribe parámetros de la entidad (ya están).
    **Un recálculo no confirma por la persona**: reutiliza lo que ella confirmó al crear (``confirmed``) mientras lo apoyado y la pared
    nuevos no pasen de ello; si pasan, ``des.removal_resting_unconfirmed`` o ``des.removal_wall_unconfirmed`` y la operación que
    sustituye sigue vigente. Cerrarlos antes, o un fallo, no dejan nada y la operación queda cancelada o fallida. Al llamar, sin
    empezar nada: los rechazos de :func:`prepare_removal_units` (también la detección obsoleta, RF-016-12)."""
    found = require_version(project, version, provenance.STOCKPILE_REMOVAL)
    loaded = entity_store._masks_to_read(project, found, masks)
    prepared = _result_of(prepare_removal_units(project, request, found, loaded, code=code, supersedes=supersedes,
                                                released=released))
    start = prepared.start
    if confirmed is not None:  # se arrastra a la operación nueva (la misma decisión, no una nueva)
        start = replace(start, settings={**start.settings, CONFIRMED: confirmed.settings()})
    handle = start.with_released(released).begin(project)
    return handle, _removal_run(project, handle, prepared, budget_s, confirmed)


def _removal_run(project: StoreProject, handle: OperationHandle, prepared: PreparedRemoval, budget_s: float,
                 confirmed: Confirmed | None) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        _check_recorded(handle, prepared)
        outcome: RemovalOutcome = yield from compute_removal_steps(writer, prepared, budget_s=budget_s)
        covers_resting = confirmed is not None and confirmed.covers_resting(math.fsum(row.volume_m3 for row in prepared.resting))
        wall = outcome.wall
        covers_wall = wall is None or not wall.needs_confirmation or (confirmed is not None and confirmed.covers_wall(wall.height_m))
        check_removal_confirmed(prepared, outcome, resting=covers_resting, wall=covers_wall)
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_COMPUTE_PHASE, 1, 1, outcome.message, result=stored)


def recompute_removal(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S,
                      released: Sequence[provenance.ReleasedSupport] = ()) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.stockpile_removal`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto»,
    RF-008-26; RF-015-02, RF-015-16): la retirada de sus ajustes (el nombre y el código) con los **parámetros vigentes de su entidad
    en su versión** (:func:`~.entity_store.entity_parameters`: el acopio, la partida, el ángulo de transición, el factor de malla, la
    métrica y el motivo de la pared) y no los que leyó la operación que sustituye: una entidad se define por sus parámetros
    (RF-015-01). Devuelve lo de :func:`run_removal`, con lo que la persona confirmó al crearla. ``ValueError`` si los ajustes no son
    los de una retirada o la petición no es de una versión."""
    project: StoreProject = request.project  # type: ignore[assignment]
    code = provenance.supported_code(request.settings)
    found = require_version(project, request.version, provenance.STOCKPILE_REMOVAL)
    asked = provenance.removal_request(request.settings, entity_parameters(project, code, version=found))
    return run_removal(project, asked, version=found.uid, code=code, supersedes=request.operation_uid,
                       confirmed=confirmed_of(request.settings), budget_s=budget_s, released=released)
