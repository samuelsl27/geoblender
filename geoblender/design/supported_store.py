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

**El cuerpo apoyado** (spec 016, T25; HU-016-4; RF-016-20 a RF-016-22, RF-015-02, RF-015-03, RF-015-29; RNF-016-07; plan 016 §5.2.3,
§5.3.2, §5.4 A11): el mismo patrón —:func:`prepare_body_units` → :func:`body_compute_steps` (puro, compartido con la reproducción) →
:func:`compute_body_steps` → :func:`create_body` → :func:`run_body` / :func:`recompute_body`— con ``design.thickness`` como cálculo. Lee
la huella (un polígono de una capa de entidades), los datos de espesor (:func:`read_thickness`: el campo de los puntos o de los
polígonos de una capa de entidades, o la Z de los vértices de una capa de líneas 3D; **la M no llega al proyecto**: la importación de
capas la descarta, ``des.body_data_m``) y la superficie conocida; rechaza **antes de calcular** un espesor negativo o que falta, con
capa, entidad, campo y valor, y la distancia máxima sin valor (D-9). «Sobre una base» deja la superficie (``des_psf_``) con el techo y
el espesor (``des_bdt_``), parte de una superficie y encadena; «bajo un techo» deja la base y el espesor dispersos (``des_bds_`` y
``des_bdt_``), **no cambia la superficie, no tiene partida y nadie parte de él** (``des.chainless_start``). Una sola transacción.

**El contrafuerte** (spec 016, T27; HU-016-3; RF-016-17, RF-016-18, RF-015-10, RF-015-12; plan 016 §5.2.3, §5.4 A10, §5.7 P-8, §5.8 H-6): el
mismo patrón —:func:`prepare_buttress_units` → :func:`buttress_compute_steps` (puro, compartido con la reproducción) →
:func:`compute_buttress_steps` → :func:`create_buttress` → :func:`run_buttress` / :func:`recompute_buttress`— con ``design.buttress`` como
cálculo. Lee la zona de coronación (un polígono de una capa de entidades), **rechaza la cota fuera del ancla de su perfil antes de leer
ninguna superficie** (con la cota del ancla más próxima), pide la cota de coronación y, porque **protege por defecto** («sin corte»: D-1),
su resguardo (D-19) y lee la partida **entera** una vez para saber hasta dónde llega la envolvente (A0: ``buttress_work_window``; con el
alcance fijado, solo su ventana). Deja la superficie entera (``des_psf_``), la huella con **dos geometrías** (``des_epr_``: ``footprint``,
toda la huella, y ``zone``, la zona de coronación, que es la que declara «sin corte», P-8 y H-6: :data:`~.store.BUTTRESS_ENTITY_COLUMNS`)
y el informe, y **no declara** la restricción: la declara ``des.declare_constraints`` (``entity_store.after_entity_change``), que lee la
zona propia del tipo (:func:`~.entities.declaration_runs`). Una sola transacción.
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

from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterStore, definition
from ..core.params.store import default_reason
from ..core.project.model import Progress
from ..core.provenance.operations import OperationHandle
from ..core.provenance.recompute import RecomputeRequest
from ..core.provenance.stale import OPERATION as STALE_OPERATION
from ..core.provenance.stale import item_text
from ..core.timeutil import format_utc
from ..core.versions import read as versions_read
from ..core.gpkg.wkb import decode_geometry
from ..core.versions.model import Version, VersionError
from ..gis.grid import Grid
from ..gis.masks import access
from ..gis.masks.combine import ClassBit
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.provenance import BREAKLINES, CONTOUR_LINES, FAMILIES_BY_CODE, FEATURES, POINTS
from ..gis.raster import Raster
from ..gis.store import StoreProject, load_features, read_features
from ..gis.vector import FeatureLayer
from . import buttress, entities, entity_store, pipeline, provenance, removal, stockpile_store, thickness, zones
from .compose import admitted_in
from .entities import EntityKind
from .entity_store import EntityParamRow, entity_parameters, set_entity_params
from .messages import DesignError
from .buttress import ButtressJob, ButtressOutcome
from .model import (
    BenchSense,
    BodyRequest,
    BodySense,
    ButtressRequest,
    LayerField,
    Metric,
    PlatformRequest,
    RemovalRequest,
    ThicknessSource,
)
from .params import BodyParam, ButtressParam, RemovalParam, StockpileParam, check_entity_param, entity_key, entity_params
from .preview import BodySummary, ButtressSummary, Obsolete, ObsoleteKind, RemovalSummary, RestingLine, obsolete_notices
from .removal import RemovalJob, RemovalOutcome, Resting
from .sectors import design_sectors, refuse_pending
from .seeds import pace_progress, sector_layout
from .stockpile_store import Detection, DetectionMaterial
from .thickness import BodyJob, BodyOutcome, ThicknessData
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
    "PlatformOrigin",
    "PreparedBody",
    "PreparedButtress",
    "PreparedRemoval",
    "StockpileChoice",
    "body_compute_steps",
    "body_entity_rows",
    "body_report_rows",
    "body_summary",
    "body_values",
    "buttress_compute_steps",
    "buttress_entity_rows",
    "buttress_report_rows",
    "buttress_summary",
    "buttress_values",
    "buttress_work_window",
    "check_removal_confirmed",
    "compute_body_steps",
    "compute_buttress_steps",
    "compute_removal_steps",
    "confirmed_of",
    "create_body",
    "create_buttress",
    "create_removal",
    "default_domain",
    "frozen_thickness_data",
    "prepare_body",
    "prepare_body_units",
    "prepare_buttress",
    "prepare_buttress_units",
    "prepare_removal",
    "prepare_removal_units",
    "read_platform_origin",
    "read_removed",
    "read_thickness",
    "recompute_body",
    "recompute_buttress",
    "recompute_removal",
    "removal_compute_steps",
    "removal_entity_rows",
    "removal_report_rows",
    "removal_summary",
    "removal_values",
    "removable_stockpiles",
    "resting_preview",
    "run_body",
    "run_buttress",
    "run_removal",
    "thickness_from_features",
    "thickness_from_lines",
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


def _locate(project: StoreProject, version: Version, request: RemovalRequest | PlatformRequest, code: str) -> _Located:
    """La detección del acopio ``request.stockpile`` (``STK-001#Acopio 1``), **al día**, en la versión o, si no, en el proyecto, y la fila
    del acopio en su tabla. ``des.removal_stockpile_unknown`` si la referencia no la tiene, la detección no existe, está sin calcular
    o descartada o no tiene ese acopio; ``des.removal_detection_stale`` (RF-016-12) si **está obsoleta**, nombrando el acopio, la
    detección y lo que cambió (la causa de la 008). Solo lee. Lo mismo para la retirada de un acopio que para la plataforma que lo retira
    «como plataforma» (``PlatformRequest.stockpile``; T21: la clave del campo es la del parámetro ``stockpile`` de su tipo)."""
    assert request.stockpile is not None
    obj, field = f"Retirada «{request.name}»", entity_key(code, "stockpile")

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


def _removed_of(project: StoreProject, found: _Located, frame: Any) -> removal.RemovedStockpile:
    """El acopio de ``found`` (:func:`_locate`) como lo retira la retirada (:func:`read_removed`): su base y la superficie con que se
    detectó se leen **por la ventana** que se les pide, del proyecto o de la versión de su detección. Solo lee. Lo comparten preparar la
    retirada y la lista de lo que se le apoya (:func:`resting_preview`)."""
    detection = found.detection
    assert detection.detected is not None

    def of_detection(name: str, what: str) -> Callable[[tuple[slice, slice]], np.ndarray]:
        return lambda window: read_surface_window(project, name, window, version_uid=detection.version_uid, expect=frame,
                                                  role=what).values

    return read_removed(found.row, frame.grid, of_detection(found.material.base.name, f"base del acopio «{found.row['key']}»"),
                        of_detection(detection.detected.name, f"superficie con que se detectó «{found.row['key']}»"))


def default_domain(masks: access.MaskSet | access.MaskSource, window: tuple[slice, slice]) -> np.ndarray:
    """El dominio por defecto de las máscaras (``MaskSet.default_domain``: perímetro ∩ límite legal − intocables, donde se puede
    retirar un acopio aunque su corte no esté admitido: D-5) **en la ventana** ``window``, de las clases de esa ventana."""
    classes = masks.classes_window(window)

    def bit(found: ClassBit) -> np.ndarray:
        return (classes & np.uint16(int(found))) != 0

    return bit(ClassBit.PERIMETER) & bit(ClassBit.LEGAL) & ~bit(ClassBit.UNTOUCHABLE)


# --- Retirar «como plataforma» (spec 016, T21; RF-016-16; plan 016 §5.4 A9, P-3, H-5) -----------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PlatformOrigin:
    """Lo que lee de un acopio la plataforma que lo retira **«como plataforma»** (:func:`read_platform_origin`; RF-016-16, A9): el ``item``
    (:class:`~.removal.RemovedStockpile`: su huella, su base y la superficie con que se detectó), su ``platform`` (el plano de su base, el
    contorno de su huella y su eje: :func:`~.removal.platform_of_stockpile`), la referencia del acopio (``ref``, ``STK-001#Acopio 7``), el código de
    su detección (``detection``) y su ámbito (``scope``: ``version`` o ``project``), la superficie sobre la que se detectó (``detected_on``),
    los **nombres de los datos de la detección que lee** (``removed``: su tabla ``des_stk_``, la base de su material ``des_stb_`` y la
    superficie con que se detectó ``des_stp_``: las tres entradas ``removed_stockpile`` de la operación) y de dónde sale su huella en
    ``des_epr_`` (``layer`` y ``source_fid``: los de su marca; el código de su detección si salió de un candidato, que no tiene capa: es lo único que la
    reproducción, sin el proyecto, sabe de ella)."""

    item: removal.RemovedStockpile
    platform: removal.StockpilePlatform
    ref: str
    detection: str
    scope: str
    detected_on: str
    removed: tuple[str, str, str]
    layer: str
    source_fid: int


def read_platform_origin(project: StoreProject, version: Version, request: PlatformRequest, code: str) -> PlatformOrigin:
    """**Lee el acopio** que retira ``request`` «como plataforma» (``request.stockpile``: ``STK-001#Acopio 7``) de su detección **al día** (de la
    versión o, si no, del proyecto) y da lo que la plataforma necesita de él (:class:`PlatformOrigin`): solo la ventana de su huella de su base y de
    la superficie con que se detectó, y su plano. Solo lee. Los rechazos son los de preparar una retirada: ``des.removal_stockpile_unknown`` (el
    acopio o su detección no existen o no están calculados) y ``des.removal_detection_stale`` (RF-016-12: la detección está obsoleta, nombrando
    lo que cambió); y ``des.removal_platform_no_plane`` si su base no es un plano (una base propia, RF-016-03)."""
    found = _locate(project, version, request, code)
    frame = project_frame(project)
    item = _removed_of(project, found, frame)
    flat = removal.platform_of_stockpile(item, frame.grid)
    detection = found.detection
    assert detection.detected is not None
    row = found.row
    return PlatformOrigin(
        item, flat, request.stockpile or "", detection.code, stockpile_store.PROJECT if detection.version_uid == "" else stockpile_store.VERSION,
        found.detected_on, (detection.stockpiles.name, found.material.base.name, detection.detected.name),
        str(row["layer"] or detection.code), int(row["source_fid"] or 0))


# --- Lo que ofrece el diálogo (spec 016, T20 (b); plan 016 §5.3.3; RF-016-11, RF-016-12, RF-016-14) ----------------


@dataclass(frozen=True, slots=True)
class StockpileChoice:
    """Un acopio que el diálogo de la retirada ofrece (:func:`removable_stockpiles`): su ``ref`` (``STK-001#Acopio 1``, lo que lleva
    :class:`~.model.RemovalRequest`), la clave de su marca (``key``), su ``name``, la detección de la que sale (``detection``: su código;
    ``detection_name``), su ``scope`` (:data:`~.stockpile_store.VERSION` o :data:`~.stockpile_store.PROJECT`), su ``material`` (``None``:
    sin él), su área y su volumen (``area_m2``, ``volume_m3``: los de la tabla de su detección) y el ``state`` de su detección
    (``CURRENT`` o ``STALE``: una obsoleta se ofrece y su cálculo se rechaza nombrando lo que cambió, RF-016-12)."""

    ref: str
    key: str
    name: str
    detection: str
    detection_name: str
    scope: str
    material: str | None
    area_m2: float
    volume_m3: float
    state: entities.EntityState


def removable_stockpiles(project: StoreProject, version: Version | str, *, conn: sqlite3.Connection | None = None
                         ) -> tuple[StockpileChoice, ...]:
    """Los acopios que se pueden retirar en la versión ``version`` (uid, código o ``Version``; spec 016, T20 (b); plan 016 §5.3.3 «el acopio»
    del diálogo), **sin escribir nada**: los de las tablas ``des_stk_`` de las detecciones **de la versión** y, después, **del proyecto**
    (D-15: una versión consume un dato del proyecto, RF-009-05) cuya operación vigente existe y no está descartada, cada uno con la
    referencia de su detección y su clave (``STK-001#Acopio 1``) y en el orden de su tabla. Una detección **obsoleta** se ofrece, con su
    estado: calcular la retirada se rechaza nombrando lo que cambió (RF-016-12); la sin calcular o descartada, no. Si el código de una
    detección del proyecto lo tiene también una de la versión, manda la de la versión (:func:`_locate`) y la del proyecto no se ofrece.
    ``VersionError`` (``core.version_unknown``) si la versión no existe; ``conn`` es una conexión de lectura de quien llama."""

    def read(reading: sqlite3.Connection) -> tuple[StockpileChoice, ...]:
        found = version if isinstance(version, Version) else versions_read.version(reading, str(version))
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version, version=version)
        offered: list[StockpileChoice] = []
        taken: set[str] = set()
        for scope in (found, None):
            registry = (entities.registry(project, found.uid, conn=reading) if scope is not None
                        else entities.project_registry(project, conn=reading))
            for entry in registry:
                record = entry.record
                if record.kind != EntityKind.STOCKPILE or record.code in taken:
                    continue
                taken.add(record.code)  # la de la versión tapa a la del proyecto de su mismo código, sea cual sea su estado (_locate)
                if entry.operation_uid is None or record.state in (entities.EntityState.UNCALCULATED, entities.EntityState.DISCARDED):
                    continue
                table = stockpile_store.read_detection_table(
                    project, provenance.STOCKPILES_TABLE, record.name, version_uid="" if scope is None else found.uid,
                    conn=reading)
                offered.extend(StockpileChoice(
                    provenance.support_ref(record.code, str(row["key"])), str(row["key"]), str(row["name"]), record.code,
                    record.name, stockpile_store.PROJECT if scope is None else stockpile_store.VERSION,
                    None if row["material"] is None else str(row["material"]), float(row["area_m2"]), float(row["volume_m3"]),
                    entities.EntityState(record.state)) for row in table)
        return tuple(offered)

    if conn is not None:
        return read(conn)
    with project.read() as reading:
        return read(reading)


_PREVIEW_NAME = "Lista de lo que se apoya"
"""El nombre de la petición con que :func:`resting_preview` localiza el acopio (no se registra: nada se escribe)."""


def resting_preview(project: StoreProject, version: Version | str, stockpile: str, start: str) -> tuple[Resting, ...]:
    """**La lista de lo que se apoya** en el acopio ``stockpile`` (``STK-001#Acopio 1``) de la superficie de partida ``start`` (un dato o
    ``entity:<código>``) de la versión ``version`` **antes de calcular** (spec 016, T20 (b); RF-016-14, A7; la lista única de RF-015-17), lo
    que enseña el diálogo de la retirada: la de :func:`~.removal.resting_on` con el acopio y su partida tal como los leerá
    :func:`prepare_removal_units`, **sin escribir nada** y leyendo solo la ventana de su huella. Los rechazos son los de preparar: el
    acopio sin detección o con la detección obsoleta (``des.removal_stockpile_unknown``, ``des.removal_detection_stale``) y la partida
    que no existe (``des.entity_start_unknown``, ``des.surface_*``)."""
    with project.read() as conn:
        found = version if isinstance(version, Version) else versions_read.version(conn, str(version))
    if found is None:
        raise VersionError("core.version_unknown", field="versión", value=version, version=version)
    registry = entities.registry(project, found.uid)
    code = entities.next_code(EntityKind.REMOVAL, (entry.record.code for entry in registry))
    asked = RemovalRequest(name=_PREVIEW_NAME, stockpile=stockpile, start=start)
    located = _locate(project, found, asked, code)
    start_name = entity_store._surface_dataset(registry, found, asked, code, RemovalParam.START, start)  # type: ignore[arg-type]
    item = _removed_of(project, located, project_frame(project))
    return removal.resting_on(project, found, item, start_name, detected_on=located.detected_on)


# --- Preparar -----------------------------------------------------------------------------------


def _check_chain(registry: entities.EntityRegistry, request: RemovalRequest, code: str) -> None:
    """RF-015-04: de cada superficie parte como mucho una entidad (``des.entity_start_taken``, con la que ya parte) y la cadena no da
    la vuelta (``des.entity_chain_cycle``); la retirada ``code`` no cuenta consigo misma. Y nadie parte de la superficie de un cuerpo
    «bajo un techo», que no la escribe (T25: ``des.chainless_start``)."""
    entity_store._check_surface_left(registry, request.name, code, request.start, entity_key(code, RemovalParam.START),
                                     obj=f"Retirada «{request.name}»")
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
    assert detection.detected is not None
    item = _removed_of(project, found, frame)
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


# =================================================================================================================
# El cuerpo apoyado (spec 016, T25; HU-016-4; RF-016-20 a RF-016-22, RF-015-02, RF-015-03, RF-015-29; RNF-016-07;
# plan 016 §5.2.3, §5.3.2, §5.4 A11): el patrón de la retirada, con ``design.thickness`` como cálculo
# =================================================================================================================

_BODY_PHASE = "body_compute"
_BODY_DIALOG = "diálogo de «Cuerpo apoyado…»"
_BODY_PROTECTS = ("un cuerpo apoyado no declara restricciones (D-1): «protect» no es una opción de su diálogo")
_BODY_SUPPORT = ("un cuerpo apoyado no lleva una superficie de apoyo aparte: la superficie conocida (surface) es su apoyo "
                 "(«sobre una base») o su techo («bajo un techo»)")
_FEATURE_PREFIX = FAMILIES_BY_CODE[FEATURES].prefix
_LINES_PREFIX = FAMILIES_BY_CODE[BREAKLINES].prefix
_OTHER_KINDS = ((BREAKLINES, "líneas 3D"), (POINTS, "puntos 3D"), (CONTOUR_LINES, "curvas de nivel"))


@dataclass(frozen=True, slots=True, eq=False)
class PreparedBody:
    """Lo que se lee y se comprueba antes de calcular un cuerpo apoyado (:func:`prepare_body_units`): el ``job``
    (``design.thickness.BodyJob``: todo lo leído de la ventana de la huella y nada del proyecto), lo que anotará la operación
    (``start``), el ``code`` de la entidad (``BDY-001``) y su ``version``, las ``rows`` de los parámetros de la entidad —**todas**:
    sin su fila, ``begin_operation`` crearía la del valor por defecto en el proyecto— y sus ``values`` resueltos, el nombre del dato
    de la superficie conocida (``surface_name``: el apoyo «sobre una base» y el techo «bajo un techo»), el de la superficie de
    partida (``start_surface``; ``None`` «bajo un techo»: no cambia la superficie), la capa de la huella y el ``fid`` de su geometría
    (``fid``), la huella en tramos de fila (``runs``) y el tipo de los datos (``sections``: son de líneas). ``existing``: la entidad
    ya estaba en la versión (se preparó con su ``code``: recalcularla), así que «Crear» no escribe otra vez sus parámetros."""

    job: BodyJob
    start: OperationStart
    code: str
    version: Version
    rows: tuple[EntityParamRow, ...]
    values: Mapping[str, Any]
    surface_name: str
    start_surface: str | None
    fid: int
    runs: tuple[tuple[int, int, int], ...]
    existing: bool = False

    @property
    def op_type(self) -> str:
        """El tipo de la operación (``des.body``)."""
        return self.start.op_type

    @property
    def sense(self) -> BodySense:
        """«Sobre una base» o «bajo un techo»."""
        return self.job.request.sense  # type: ignore[return-value]


# --- Los parámetros ------------------------------------------------------------------------------------------------


def body_values(request: BodyRequest, code: str, fid: int | str) -> tuple[dict[str, Any], frozenset[str]]:
    """Los parámetros resueltos y comprobados del cuerpo ``request`` de código ``code`` (RF-015-08; por último segmento de su clave) y
    **los nombres de los que se dejaron por su valor por defecto**: la distancia máxima a los datos no tiene ninguno (D-9: la petición
    no lleva ninguna cifra minera; ``des.entity_param_missing``, o ``_range`` si no es positiva), el «cero en el borde» es falso
    sin valor y la partida es obligatoria «sobre una base» (y no la lleva «bajo un techo»). La «capa» de los mensajes es la de la huella
    y la geometría es la de **su ``fid``** (``fid``: el de su capa; lo que recalcular y reproducir leen). **Sin proyecto**: lo comparten
    preparar y reproducir. ``ValueError`` si pide declarar restricciones (``protect``) o una superficie de apoyo aparte."""
    if request.protect:
        raise ValueError(_BODY_PROTECTS)
    if request.support is not None:
        raise ValueError(_BODY_SUPPORT)
    spec = entity_params("body")
    on_base = request.sense is BodySense.ON_BASE
    defaulted = {BodyParam.PROTECT.value}
    zero = request.zero_at_edge
    if zero is None:
        zero = spec.template(BodyParam.ZERO_AT_EDGE.value).default  # type: ignore[assignment]
        defaulted.add(BodyParam.ZERO_AT_EDGE.value)
    asked: dict[BodyParam, object] = {
        BodyParam.NAME: request.name, BodyParam.LAYER: request.layer, BodyParam.FEATURE: str(fid),
        BodyParam.DATA_LAYER: request.data_layer, BodyParam.DATA_FIELD: request.data_field,
        BodyParam.DATA_FROM: request.data_from.value, BodyParam.SURFACE: request.surface,  # type: ignore[union-attr]
        BodyParam.SENSE: request.sense.value, BodyParam.START: request.start,  # type: ignore[union-attr]
        BodyParam.MAX_DISTANCE: request.max_distance_m, BodyParam.ZERO_AT_EDGE: zero, BodyParam.SUPPORT: None,
        BodyParam.GUARD: request.guard_m, BodyParam.REASON: request.reason, BodyParam.PROTECT: False}
    values: dict[str, Any] = {}
    for param in BodyParam:
        if param in (BodyParam.SUPPORTS, BodyParam.DISCARDED):
            continue
        required = True if param is BodyParam.START and on_base else False if param is BodyParam.GUARD else None
        checked = check_entity_param(request.name, code, param.value, asked[param], layer=request.layer, required=required)
        if checked is not None:
            values[param.value] = checked
    return values, frozenset(defaulted)


def _body_rows(request: BodyRequest, code: str, values: Mapping[str, Any], defaulted: frozenset[str]
               ) -> tuple[EntityParamRow, ...]:
    """Las filas de los parámetros de la entidad con su procedencia (RF-008-01): lo que no se pidió, con la de su valor por defecto;
    el resto, lo que eligió la persona en el diálogo. **Todas** (también las de los valores por defecto)."""
    spec = entity_params("body")
    rows: list[EntityParamRow] = []
    for param in BodyParam:
        value = values.get(param.value)
        if value is None:
            continue
        if param.value in defaulted:
            declared = spec.template(param.value)
            source, kind, reason = declared.source, str(declared.source_kind), default_reason(declared)
        else:
            source, kind = f"{_BODY_DIALOG}, entidad «{request.name}»", "person"
            reason = f"Elegido al crear el cuerpo apoyado «{request.name}»"
        rows.append(EntityParamRow(entity_key(code, param), param.value, value, source, kind, reason))
    return tuple(rows)


# --- Los datos de espesor (RF-016-20) -------------------------------------------------------------------------------


def _body_object(request: BodyRequest) -> str:
    return f"Cuerpo apoyado «{request.name}»"


def _kind_text(name: str, layer: FeatureLayer | None = None) -> str:
    """Lo que tiene la capa de datos ``name`` (para decir por qué no se lee de ella): puntos, líneas o polígonos de una capa de
    entidades (``layer``), líneas 3D, puntos 3D, curvas de nivel u otro tipo de dato."""
    if layer is not None:
        return entity_store._KINDS_ES.get(layer.kind, layer.kind)
    for code, text in _OTHER_KINDS:
        if name.startswith(FAMILIES_BY_CODE[code].prefix):
            return text
    return "datos de otro tipo"


def _kind_error(request: BodyRequest, kind: str) -> DesignError:
    return DesignError("des.body_data_kind", obj=_body_object(request), field=entity_key("BDY-001", BodyParam.DATA_FROM),
                       value=str(request.data_from), entity=request.name, layer=request.data_layer, kind=kind)


def _m_error(request: BodyRequest) -> DesignError:
    return DesignError("des.body_data_m", obj=_body_object(request), field=entity_key("BDY-001", BodyParam.DATA_FROM),
                       value=str(request.data_from), entity=request.name, layer=request.data_layer)


def _datum_problem(value: object, request: BodyRequest, field: str) -> DesignError | float:
    """El espesor ``value`` de un dato del campo ``field`` como número (finito y **no negativo**: RF-016-01, RF-015-08) o, si falta, no
    es un número, no es finito o es negativo, el ``des.entity_field_value`` que lo rechaza, con la capa de los datos, el cuerpo, el campo
    y el valor: no se elige ninguno por la persona."""
    number: float | None = None
    if value is not None and not isinstance(value, bool):
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            number = None
    if number is None or not math.isfinite(number) or number < 0.0:
        shown = "—" if value is None else value
        return DesignError("des.entity_field_value", obj=_body_object(request), field=field, value=shown,
                           layer=request.data_layer, entity=request.name)
    return number


def _datum(value: object, request: BodyRequest, field: str) -> float:
    """:func:`_datum_problem` lanzando el rechazo: el espesor de un dato, antes de construir los datos del cálculo."""
    found = _datum_problem(value, request, field)
    if isinstance(found, DesignError):
        raise found
    return found


def thickness_from_features(layer: FeatureLayer, request: BodyRequest) -> ThicknessData:
    """Los datos de espesor de una capa de entidades ``layer`` (puntos o polígonos) leídos **del campo** ``request.data_field``
    (RF-016-20): un dato por punto con el valor de su entidad y, de un polígono, **el espesor constante en cada uno** (cada parte,
    con el valor de su entidad). Un espesor negativo, que falta o que no es un número se rechaza **antes** con la capa, el cuerpo, el
    campo y el valor (``des.entity_field_value``, RF-015-08); un campo que la capa no tiene o no es numérico, ``des.quarry_layer_field``;
    una capa de líneas, o leer la Z de una capa de entidades (que no la guarda), ``des.body_data_kind``, y la M, ``des.body_data_m``.
    Solo depende de lo leído: lo comparten preparar y reproducir."""
    if request.data_from is ThicknessSource.M:
        raise _m_error(request)
    if request.data_from is not ThicknessSource.FIELD or layer.kind == "line":
        raise _kind_error(request, _kind_text(request.data_layer, layer))
    column = entity_store._level_column(layer, LayerField(request.data_layer, request.data_field))
    values = layer.values[column]
    points: list[tuple[float, float, float]] = []
    polygons: list[tuple[tuple[np.ndarray, ...], float]] = []
    for index in range(len(layer)):
        found = _datum(values[index], request, request.data_field)
        for part in layer.parts[index]:
            if layer.kind == "point":
                x, y = part[0][0]
                points.append((float(x), float(y), found))
            else:
                polygons.append((tuple(part), found))
    return ThicknessData(np.array(points, dtype=np.float64).reshape(-1, 3), tuple(polygons))


def thickness_from_lines(geometries: Sequence[np.ndarray], request: BodyRequest) -> ThicknessData:
    """Los datos de espesor de unas **líneas 3D** (``geometries``: de cada una, sus vértices ``(n, d)`` ABSOLUTOS en float64: X, Y y Z
    y, si la fuente la llevara, M) leídos **de la Z o de la M declaradas** (``request.data_from``; RF-016-20: no se supone ninguna): un
    dato por vértice (``ThicknessData.sections``: son secciones). Un espesor negativo o que no es un número se rechaza antes con la
    capa, el cuerpo, el campo (``Z`` o ``M``) y el valor (``des.entity_field_value``); líneas sin Z, ``des.body_data_kind``; **sin M
    en los vértices, ``des.body_data_m``** (ni el GeoPackage del proyecto ni la importación de capas la guardan). Leer de un campo
    una capa de líneas es ``des.body_data_kind``. Solo depende de lo leído: lo comparten preparar y reproducir."""
    source = request.data_from
    if source is ThicknessSource.FIELD:
        raise _kind_error(request, _kind_text(request.data_layer))
    column = 2 if source is ThicknessSource.Z else 3
    label = "Z" if source is ThicknessSource.Z else "M"
    found: list[np.ndarray] = []
    for geometry in geometries:
        array = np.asarray(geometry, dtype=np.float64)
        array = array.reshape(-1, array.shape[-1]) if array.size else array.reshape(0, 3)
        if array.shape[1] <= column:
            if source is ThicknessSource.M:
                raise _m_error(request)
            raise _kind_error(request, "líneas sin Z")
        values = array[:, column]
        bad = np.flatnonzero(~np.isfinite(values) | (values < 0.0))
        if bad.size:
            problem = _datum_problem(float(values[bad[0]]), request, label)
            assert isinstance(problem, DesignError)
            raise problem
        found.append(np.column_stack([array[:, 0], array[:, 1], values]))
    points = np.concatenate(found) if found else np.empty((0, 3), dtype=np.float64)
    return ThicknessData(points, (), sections=True)


def read_thickness(project: StoreProject, request: BodyRequest) -> ThicknessData:
    """Los datos de espesor de la capa ``request.data_layer`` del proyecto (RF-016-20): **el campo** de los puntos o de los polígonos de
    una capa de entidades (``gis_fea_``; ``data_from`` ``field``) o **la Z de los vértices de una capa de líneas 3D** (``gis_brk_``;
    ``data_from`` ``z``: la Z que guarda el proyecto), como :func:`thickness_from_features` y :func:`thickness_from_lines`. Otra
    clase de dato, ``des.body_data_kind``; la M, ``des.body_data_m``. Solo lee y no modifica la capa (principio 7)."""
    name = request.data_layer
    if name.startswith(_FEATURE_PREFIX):
        return thickness_from_features(entity_store._layer(project, name), request)
    if name.startswith(_LINES_PREFIX):
        if request.data_from is ThicknessSource.FIELD:
            raise _kind_error(request, _kind_text(name))
        stored = load_features(project, name)
        return thickness_from_lines(stored.geometries, request)  # type: ignore[union-attr]
    raise _kind_error(request, _kind_text(name))


def frozen_thickness_data(conn: sqlite3.Connection, table: str, request: BodyRequest) -> ThicknessData:
    """Lo mismo que :func:`read_thickness` de la tabla ``table`` de la conexión ``conn`` (la copia congelada de la capa de datos
    ``request.data_layer``), **sin el proyecto**: al reproducir lo congelado. Solo lee."""
    name = request.data_layer
    if name.startswith(_FEATURE_PREFIX):
        return thickness_from_features(read_features(conn, table), request)
    if name.startswith(_LINES_PREFIX):
        if request.data_from is ThicknessSource.FIELD:
            raise _kind_error(request, _kind_text(name))
        geometries = [np.asarray(decode_geometry(blob).coords, dtype=np.float64)
                      for (blob,) in conn.execute(f'SELECT "geom" FROM "{table}" ORDER BY fid')]
        return thickness_from_lines(geometries, request)
    raise _kind_error(request, _kind_text(name))


# --- Preparar ------------------------------------------------------------------------------------------------------


def _check_body_chain(registry: entities.EntityRegistry, request: BodyRequest, code: str, version: Version) -> None:
    """RF-015-04, RF-015-15, H-9: **nadie parte de la superficie de un cuerpo «bajo un techo»**, que no la escribe
    (``des.chainless_start``: ni la partida ni la superficie conocida); «sobre una base», de su partida parte como mucho una entidad
    (``des.entity_start_taken``) y la cadena no da la vuelta (``des.entity_chain_cycle``); y la superficie conocida no es la de la
    propia entidad ni la de una que parte de la suya (``des.entity_supports_unknown``: sería un ciclo). El cuerpo ``code`` no
    cuenta consigo mismo."""
    obj = _body_object(request)
    entity_store._check_surface_left(registry, request.name, code, request.surface, entity_key(code, BodyParam.SURFACE), obj=obj)
    if request.sense is BodySense.ON_BASE:
        entity_store._check_surface_left(registry, request.name, code, request.start, entity_key(code, BodyParam.START), obj=obj)
        other = entities.start_conflict(registry.records, request.start, ignoring=code)
        if other is not None:
            raise DesignError("des.entity_start_taken", obj=obj, field=entity_key(code, BodyParam.START), value=request.start,
                              entity=request.name, other=other.name)
        records = [item for item in registry.records if item.code != code]
        entities.check_chain([*records, entities.EntityRecord(code, request.name, EntityKind.BODY, request.start, None)])
    entity_store._check_support_cycle(registry, request.name, code, request.surface, entity_key(code, BodyParam.SURFACE),
                                      version.code)


def prepare_body_units(project: StoreProject, request: BodyRequest, version: Version,
                       masks: access.MaskSet | access.MaskSource, *, code: str | None = None,
                       supersedes: str | None = None, released: Sequence[provenance.ReleasedSupport] = ()
                       ) -> Generator[None, None, PreparedBody]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan el cuerpo ``request`` de la versión
    editable ``version`` con sus ``masks`` ya al día (:func:`~.store.masks_steps`): el código (``code``: el de una entidad que ya está
    en la versión, que no choca consigo misma; si no, el siguiente, ``BDY-001``), el nombre único y la cadena, la huella (un polígono
    de una capa de entidades) y los parámetros resueltos, los datos de espesor (**un espesor negativo o que falta se rechaza aquí**, con
    capa, cuerpo, campo y valor), la ventana de la huella (A0) con la superficie conocida —y, «sobre una base», la partida y el relleno
    admitido—, los sectores con la búsqueda pendiente (solo «sobre una base»: mueve celdas; RF-015-07) y lo que anotará la operación.
    ``supersedes``: la operación hecha a la que sustituye (un recálculo); ``released``: lo que da por bueno sin su apoyo. Devuelve la
    :class:`PreparedBody`. **Nada se escribe**; los rechazos salen al avanzar, en el orden de la documentación del módulo."""
    require_version(project, version.uid, provenance.BODY)
    registry = entities.registry(project, version.uid)
    chosen = code if code is not None else entities.next_code(EntityKind.BODY, (entry.record.code for entry in registry))
    entity_store._check_name(registry, request.name, chosen, version.code)
    _check_body_chain(registry, request, chosen, version)
    yield
    layer = entity_store._layer(project, request.layer)
    if layer.kind != "polygon":
        raise DesignError("des.layer_not_polygons", obj=f"Capa «{request.layer}»", field="geometría",
                          value=entity_store._KINDS_ES.get(layer.kind, layer.kind), layer=request.layer)
    index = entity_store.feature_index(layer, request, chosen)  # type: ignore[arg-type]
    fid = layer.fids[index]
    values, defaulted = body_values(request, chosen, fid)
    yield
    data = read_thickness(project, request)
    yield
    frame = project_frame(project)
    grid = frame.grid
    whole = zones.polygons_cells(tuple(tuple(part) for part in layer.parts[index]), grid)
    window = thickness.body_window(whole, grid)
    if window is None:
        raise thickness.no_data_error(request)
    footprint = whole[window]
    on_base = request.sense is BodySense.ON_BASE
    known_name = entity_store._surface_dataset(registry, version, request, chosen, BodyParam.SURFACE, request.surface)  # type: ignore[arg-type]
    known = read_surface_window(project, known_name, window, version_uid=version.uid, expect=frame, role="superficie conocida")
    yield
    start_name: str | None = None
    start_values: np.ndarray | None = None
    fill: np.ndarray | None = None
    if on_base:
        assert request.start is not None
        start_name = entity_store._surface_dataset(registry, version, request, chosen, BodyParam.START, request.start)  # type: ignore[arg-type]
        start_values = read_surface_window(project, start_name, window, version_uid=version.uid, expect=frame,
                                           role="superficie de partida").values
        fill = admitted_in(masks, BenchSense.FILL, window)
    yield
    if on_base:
        sectors = design_sectors(project, version.uid)
        if any(sector.pending for sector in sectors):  # RF-015-07: el cuerpo «sobre una base» mueve celdas
            refs, labels = sector_layout(project, masks)  # type: ignore[arg-type]
            touched = pipeline.touched_in(refs, labels[window], footprint)
            refuse_pending(sector for sector in sectors if sector.code in touched)
    job = BodyJob(request, chosen, grid, frame.crs, frame.vertical, known.values, footprint, data,
                  MappingProxyType(dict(values)), start=start_values, fill_allowed=fill, region=window)
    yield
    supported, footprints, reads = entity_store._support_inputs(
        project, version, request, chosen, registry, known_name if on_base else None,  # type: ignore[arg-type]
        entity_store._released_codes(project, supersedes, released))
    inputs = provenance.body_inputs(request, start_name if on_base else known_name, masks.uses(), supported)  # type: ignore[arg-type]
    inputs = (*inputs, *(use for use in footprints if use not in inputs))
    begun = _start(project, provenance.BODY, request.name, version, masks,  # type: ignore[arg-type]
                   provenance.body_settings(request, chosen), inputs,
                   provenance.body_params(chosen, request, supports=reads), supersedes)
    yield
    runs = tuple(tuple(int(value) for value in run) for run in entity_store.footprint_runs(footprint, window))
    return PreparedBody(job, begun, chosen, version, _body_rows(request, chosen, values, defaulted), MappingProxyType(values),
                        known_name, start_name, int(fid), runs, code is not None)


def prepare_body(project: StoreProject, request: BodyRequest, *, version: str | None,
                 masks: access.MaskSet | None = None, code: str | None = None,
                 supersedes: str | None = None) -> PreparedBody:
    """La preparación entera de :func:`prepare_body_units` de una vez (sin ceder el hilo; las máscaras que no se dan se abren sin
    cargar sus celdas: ``entity_store._masks_to_read``): la :class:`PreparedBody`, con los mismos rechazos y sin escribir nada."""
    found = require_version(project, version, provenance.BODY)
    loaded = entity_store._masks_to_read(project, found, masks)
    return _result_of(prepare_body_units(project, request, found, loaded, code=code, supersedes=supersedes))


# --- Calcular (RF-015-03, RF-015-29, RNF-016-02) ---------------------------------------------------------------------


def body_compute_steps(job: BodyJob, *, budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, BodyOutcome]:
    """Los pasos que calculan el cuerpo de ``job`` (RF-016-01, RF-016-20 a RF-016-22, RF-015-29; plan 016 §5.3.2: el
    ``body_compute_steps`` que **comparten «Calcular», el recálculo y la reproducción**), sin proyecto y sin escribir nada
    (``yield from``; cerrar el generador no deja nada): A11 (``thickness.body_steps``) por pasos de ``budget_s`` como mucho. Los
    rechazos de RF-016-22 (sin datos en la huella o todo lejos) y de la distancia máxima salen al avanzar. Devuelve el
    :class:`~.thickness.BodyOutcome`."""
    name = job.request.name
    yield Progress(_BODY_PHASE, 0, 1, f"Calculando el cuerpo apoyado «{name}»…")
    outcome: BodyOutcome = yield from pipeline.forward(thickness.body_steps(job, budget_s=budget_s))
    yield Progress(_BODY_PHASE, 1, 1, f"Cuerpo apoyado «{name}» calculado")
    return outcome


def _whole_body_start_steps(project: StoreProject, prepared: PreparedBody, budget_s: float
                            ) -> Generator[Progress, None, np.ndarray]:
    """La superficie de partida **entera** (un array nuevo que el llamador puede modificar), leída por bandas de filas dentro del cálculo
    —lo que hace falta para escribir la superficie de salida «sobre una base» (P-12)—. La ventana leída antes ha de ser **igual** a la
    de ahora (bit a bit, el NaN incluido): si el dato cambió en medio, ``des.input_changed`` y no se escribe nada."""
    job = prepared.job
    name = job.request.name
    assert prepared.start_surface is not None and job.start is not None
    raster = yield from pipeline.forward(pace_progress(
        read_surface_steps(project, prepared.start_surface, version_uid=prepared.start.version_uid,
                           expect=project_frame(project), role="superficie de partida"),
        budget_s, phase=_BODY_PHASE, running=f"Leyendo la superficie de partida de «{name}»…",
        finished="Superficie de partida leída"))
    whole = np.array(raster.values, dtype=np.float64, copy=True)
    if not np.array_equal(whole[job.window], job.start, equal_nan=True):
        raise DesignError("des.input_changed", obj=f"Superficie «{prepared.start_surface}»", field="entradas",
                          value=prepared.start_surface)
    return whole


def _sparse(grid: Grid, outcome: BodyOutcome, values: np.ndarray) -> np.ndarray:
    """La rejilla **dispersa** de ``values`` (de la ventana del cuerpo): con dato solo donde hay cuerpo, ``NaN`` en el resto de la rejilla
    (P-4: unos KiB frente a 15 MiB enteros). Un array nuevo de la forma de la rejilla."""
    whole = np.full(grid.shape, np.nan, dtype=np.float64)
    whole[outcome.window] = values
    return whole


def body_entity_rows(job: BodyJob, outcome: BodyOutcome, *, layer: str, source_fid: int, runs: Sequence[Sequence[int]],
                     start_surface: str, support_surface: str | None) -> list[Row]:
    """La fila de ``des_epr_`` (columnas de :data:`~.store.ENTITY_COLUMNS`) del cuerpo de ``job`` con su ``outcome`` (RF-015-01):
    **una**, con los atributos de la entidad —su código, su nombre, su tipo ``body``, los datos de su superficie (``start_surface``: la
    de partida «sobre una base» y la conocida «bajo un techo», la que consume con el papel ``surface``) y de apoyo (la conocida «sobre
    una base»), **la capa y el ``fid`` de la huella**, el hash de su huella, el modo ``body`` y las celdas de la huella—, su ventana de
    trabajo, la huella en tramos de fila y ningún eje. Solo depende de lo que se lee para calcular, no del proyecto: lo repite la
    reproducción desde lo congelado."""
    text = json.dumps([list(run) for run in runs], separators=(",", ":"), allow_nan=False)
    rows, cols = outcome.window
    return [(job.code, job.request.name, EntityKind.BODY.value, start_surface, support_surface, layer, int(source_fid),
             hashlib.sha256(text.encode()).hexdigest(), "body", int(np.count_nonzero(outcome.footprint)), 0,
             json.dumps([int(rows.start), int(rows.stop), int(cols.start), int(cols.stop)], separators=(",", ":")), text, "[]")]


def body_report_rows(outcome: BodyOutcome) -> list[Row]:
    """Las filas de ``des_prp_`` (formato largo: ``quantity, value, unit_code, note``; RF-016-20 a RF-016-22) del cuerpo ``outcome``, en
    este orden: las celdas (la huella, las del cuerpo, las que tienen dato, las de «cero en el borde», las del TIN, las del dato más
    próximo, las directas del interior de los polígonos, los datos triangulados y las sin superficie conocida), las cifras (volumen,
    espesor máximo con su lugar, lo lejano con su área, su volumen y su lugar, la mayor distancia a un dato y lo ignorado), los dos
    valores que lo gobiernan (la distancia máxima y «cero en el borde») y, al final, los avisos y notas (``warning`` y ``note`` con su
    código y sus valores en JSON). Un valor que no es finito es un error del programa (``ValueError``). Solo depende del resultado: lo
    repite la reproducción."""
    rows: list[Row] = []

    def scalar(key: str, value: float, unit: str, note: str | None = None) -> None:
        rows.append((key, _real(key, value), unit, note))

    def place(x: float | None, y: float | None, what: str) -> str | None:
        return None if x is None or y is None else f"{_real(f'{what}.x', x)!r};{_real(f'{what}.y', y)!r}"

    for key, count in (("footprint_cells", int(np.count_nonzero(outcome.footprint))), ("body_cells", int(np.count_nonzero(outcome.body))),
                       ("data_cells", outcome.data_cells), ("zero_cells", outcome.zero_cells), ("tin_cells", outcome.tin_cells),
                       ("nearest_cells", outcome.nearest_cells), ("direct_cells", outcome.direct_cells),
                       ("tin_points", outcome.tin_points), ("unsupported_cells", outcome.unsupported_cells),
                       ("far_cells", int(np.count_nonzero(outcome.far)))):
        scalar(key, count, "-")
    scalar("volume_m3", outcome.volume_m3, "m3")
    scalar("thickness_max_m", outcome.thickness_max_m, "m", place(outcome.thickness_max_x, outcome.thickness_max_y, "thickness_max"))
    scalar("far_m2", outcome.far_m2, "m2")
    scalar("far_m3", outcome.far_m3, "m3", place(outcome.far_x, outcome.far_y, "far"))
    scalar("farthest_m", outcome.farthest_m, "m")
    scalar("ignored", outcome.ignored, "-")
    scalar("max_distance_m", outcome.max_distance_m, "m")
    scalar("zero_at_edge", int(outcome.zero_at_edge), "-")
    for notice in outcome.notices:
        rows.append((notice.severity, None, None, _notice_text(notice)))
    return rows


def compute_body_steps(writer: DesignWriter, prepared: PreparedBody, *, budget_s: float = STEP_BUDGET_S
                       ) -> Generator[Progress, None, BodyOutcome]:
    """Lo que hace «Calcular» sobre el ``writer`` (RF-015-03, RF-015-29; patrón de :func:`compute_removal_steps`): calcula el cuerpo
    preparado (:func:`body_compute_steps`) y deja en el temporal de ``writer`` **el espesor disperso** (``des_bdt_``) y, «sobre una
    base», la superficie de partida **entera** con el techo en la ventana del cuerpo (``des_psf_``, P-12) o, «bajo un techo», **la base
    dispersa** (``des_bds_``: no cambia la superficie), y prepara, con su hash en memoria, la huella (``des_epr_``) y el informe
    (``des_prp_``), **sin confirmar**: lo que falta para crearlo (:func:`create_body`) es una sola transacción. Devuelve el
    :class:`~.thickness.BodyOutcome`."""
    job = prepared.job
    grid = job.grid
    outcome = yield from body_compute_steps(job, budget_s=budget_s)
    crs, vertical = writer.crs, writer.vertical
    on_base = prepared.sense is BodySense.ON_BASE
    yield from pipeline.forward(_store_steps(
        writer.grid_steps(provenance.BODY_THICKNESS_GRID, Raster(grid, _sparse(grid, outcome, outcome.thickness), crs, vertical)),
        budget_s, "el espesor del cuerpo"))
    if on_base:
        writer.omit(provenance.BODY_BASE_GRID)
        whole = yield from _whole_body_start_steps(writer.project, prepared, budget_s)
        yield from pipeline.forward(_store_steps(
            writer.grid_steps(provenance.ENTITY_SURFACE_GRID, Raster(grid, outcome.compose(whole), crs, vertical)), budget_s,
            "la superficie del cuerpo"))
    else:
        writer.omit(provenance.ENTITY_SURFACE_GRID)
        yield from pipeline.forward(_store_steps(
            writer.grid_steps(provenance.BODY_BASE_GRID, Raster(grid, _sparse(grid, outcome, outcome.base), crs, vertical)),
            budget_s, "la base del cuerpo"))
    request = job.request
    entity = body_entity_rows(job, outcome, layer=request.layer, source_fid=prepared.fid, runs=prepared.runs,
                              start_surface=prepared.start_surface or prepared.surface_name,
                              support_surface=prepared.surface_name if on_base else None)
    yield from pipeline.forward(_store_steps(writer.table_steps(provenance.ENTITY_TABLE, entity), budget_s, "la huella del cuerpo"))
    yield from pipeline.forward(_store_steps(writer.table_steps(provenance.ENTITY_REPORT_TABLE, body_report_rows(outcome)),
                                             budget_s, "el informe del cuerpo"))
    return outcome


# --- El resumen (RF-015-03, RF-016-20 a 22) -----------------------------------------------------------------------


def body_obsolete(project: StoreProject, prepared: PreparedBody, *, supersedes: str | None = None) -> tuple[Obsolete, ...]:
    """**Lo que quedará obsoleto al crear** el cuerpo ``prepared`` (RF-015-03, RF-015-16): uno nuevo no deja obsoleto nada; el que
    **sustituye** una operación (``supersedes``: un recálculo) deja obsoleto lo que dependía de lo que escribió, en cascada. Solo lee."""
    if supersedes is None:
        return ()
    with project.read() as conn:
        written = [str(row[0]) for row in conn.execute(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' AND item_kind = 'dataset' "
            "ORDER BY fid", (supersedes,))]
        found = entity_store._dependents(conn, written, prepared.version.uid, exclude=(supersedes,))
    return tuple(entity_store._consumer(ObsoleteKind.DEPENDENT, uid, op_type, name) for uid, op_type, name in found)


def body_summary(project: StoreProject, prepared: PreparedBody, outcome: BodyOutcome, *,
                 supersedes: str | None = None) -> BodySummary:
    """El resumen de «Calcular» el cuerpo ``prepared`` (RF-015-03, RF-016-20 a 22): las cifras que se registrarán, lo lejano de los datos
    con su área, su volumen y su lugar, y los avisos en el orden en que se enseñan (los del cálculo: lo ignorado, lo lejano, lo que no
    tiene superficie conocida, lo triangulado; y lo que quedará obsoleto). Solo lee."""
    kept = body_obsolete(project, prepared, supersedes=supersedes)
    request = prepared.job.request
    notices = (*outcome.notices, *obsolete_notices(request.name, prepared.version.code, kept))
    return BodySummary(
        request.name, prepared.code, prepared.version.code, prepared.sense.value, request.data_layer, outcome.figures,
        outcome.volume_m3, outcome.thickness_max_m, outcome.thickness_max_x, outcome.thickness_max_y, outcome.far_m2,
        outcome.far_m3, outcome.far_x, outcome.far_y, notices, kept)


# --- Crear (RF-016-20, RF-015-01, RF-015-02; RNF-016-07) ------------------------------------------------------------


def create_body(project: StoreProject, writer: DesignWriter, prepared: PreparedBody, outcome: BodyOutcome, *,
                decided_by: str | None = None) -> Stored:
    """**«Crear» un cuerpo apoyado** (RF-016-20, RF-015-01, RF-015-02): registra en **una** transacción
    (:meth:`~.store.DesignWriter.commit` de ``writer``, el de «Calcular», con sus salidas preparadas) los parámetros de la entidad
    —una fila de la versión por parámetro, con su origen y su decisor ``decided_by`` (por defecto, quien tiene abierto el proyecto)—,
    la operación ``des.body`` con sus entradas (la huella, los datos de espesor con el papel ``body_data``, la superficie, las máscaras y
    lo que apoya) y sus parámetros, el espesor disperso, la superficie «sobre una base» o la base dispersa «bajo un techo», la huella
    (``des_epr_``), el informe y las cifras ``des.bdy_*`` con el ámbito de la entidad. Una entidad que ya estaba en la versión
    (``prepared.existing``) no vuelve a escribir sus parámetros. Si algo falla, o lo que consume cambió desde que se calculó
    (``des.input_changed``), no queda nada y el error sigue; **no modifica ninguna entrada**."""
    start = prepared.start

    def parameters(conn: sqlite3.Connection) -> None:
        if prepared.existing:
            if ParameterStore(project).get(entity_key(prepared.code, BodyParam.NAME), version=start.version_uid,
                                           conn=conn) is None:
                raise ValueError(f"la entidad {prepared.code} no tiene sus parámetros en la versión: no está en ella (se prepara "
                                 "sin su código)")
        else:
            set_entity_params(project, prepared.rows, version=start.version_uid, decided_by=decided_by, conn=conn)

    return writer.commit(start, figures=outcome.figures, message=outcome.message, before_begin=parameters)


# --- Recalcular (RF-015-02, RF-015-16, RF-008-26) --------------------------------------------------------------------


def _check_recorded_body(handle: OperationHandle, prepared: PreparedBody) -> None:
    """Los parámetros que anotó la operación al empezar son los que leyó el cálculo al prepararse (RF-013-17, D-14): si uno cambió entre
    las dos cosas, el resultado ya no le corresponde (``des.input_changed``, con el parámetro)."""
    read: dict[str, object] = {entity_key(prepared.code, BodyParam(name)): value for name, value in prepared.values.items()}
    for param in handle.params:
        if param.key in read and param.value != read[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»", field="parámetros", value=param.key)


def run_body(project: StoreProject, request: BodyRequest, *, version: str | None, code: str,
             masks: access.MaskSet | None = None, supersedes: str | None = None, budget_s: float = STEP_BUDGET_S,
             released: Sequence[provenance.ReleasedSupport] = ()) -> tuple[OperationHandle, Iterator[Progress]]:
    """Calcula y registra ``request`` —un cuerpo que ya está en la versión ``version``: su ``code``— de **una vez** (RF-015-02,
    RF-015-16; el recálculo de lo obsoleto, :func:`~.store.recompute_run`; el «Crear» tras «Calcular» es
    :meth:`~.steps.Calculation.create`): empieza la operación ``des.body`` —si ``supersedes`` es la de una anterior, la sustituye,
    quedándose con los nombres de sus datos— con lo que lee hoy y devuelve su ``OperationHandle`` «en curso» y sus pasos, que avanza
    quien la llama: calculan (:func:`body_compute_steps`), escriben el espesor, la superficie o la base, la huella y el informe y
    completan la operación en una transacción; el último lleva el :class:`~.store.Stored`. No escribe parámetros de la entidad (ya
    están). Cerrarlos antes, o un fallo, no dejan nada y la operación queda cancelada o fallida. Al llamar, sin empezar nada: los
    rechazos de :func:`prepare_body_units`."""
    found = require_version(project, version, provenance.BODY)
    loaded = entity_store._masks_to_read(project, found, masks)
    prepared = _result_of(prepare_body_units(project, request, found, loaded, code=code, supersedes=supersedes, released=released))
    handle = prepared.start.with_released(released).begin(project)
    return handle, _body_run(project, handle, prepared, budget_s)


def _body_run(project: StoreProject, handle: OperationHandle, prepared: PreparedBody, budget_s: float
              ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        _check_recorded_body(handle, prepared)
        outcome: BodyOutcome = yield from compute_body_steps(writer, prepared, budget_s=budget_s)
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_BODY_PHASE, 1, 1, outcome.message, result=stored)


def recompute_body(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S,
                   released: Sequence[provenance.ReleasedSupport] = ()) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.body`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto», RF-008-26;
    RF-015-02, RF-015-16): el cuerpo de sus ajustes (el nombre y el código) con los **parámetros vigentes de su entidad en su
    versión** (:func:`~.entity_store.entity_parameters`: la huella, los datos, la superficie, el sentido, la partida, la distancia
    máxima y el «cero en el borde») y no los que leyó la operación que sustituye: una entidad se define por sus parámetros
    (RF-015-01). Devuelve lo de :func:`run_body`. ``ValueError`` si los ajustes no son los de un cuerpo o la petición no es de una
    versión."""
    project: StoreProject = request.project  # type: ignore[assignment]
    code = provenance.supported_code(request.settings)
    found = require_version(project, request.version, provenance.BODY)
    asked = provenance.body_request(request.settings, entity_parameters(project, code, version=found))
    return run_body(project, asked, version=found.uid, code=code, supersedes=request.operation_uid, budget_s=budget_s,
                    released=released)


# =================================================================================================================
# El contrafuerte (spec 016, T27; HU-016-3; RF-016-17, RF-016-18, RF-015-02, RF-015-03, RF-015-10, RF-015-12, RF-015-29; plan 016
# §5.2.3, §5.3.2, §5.4 A10, §5.7 P-8, §5.8 H-6 y H-10): el patrón de la retirada y del cuerpo, con ``design.buttress`` como cálculo
# =================================================================================================================

_BUTTRESS_PHASE = "buttress_compute"
_BUTTRESS_DIALOG = "diálogo de «Contrafuerte…»"


@dataclass(frozen=True, slots=True, eq=False)
class PreparedButtress:
    """Lo que se lee y se comprueba antes de calcular un contrafuerte (:func:`prepare_buttress_units`): el ``job``
    (``design.buttress.ButtressJob``: todo lo leído de la ventana del contrafuerte y nada del proyecto), lo que anotará la operación
    (``start``), el ``code`` de la entidad (``BTR-001``) y su ``version``, las ``rows`` de los parámetros de la entidad —**todas**: sin su
    fila, ``begin_operation`` crearía la del valor por defecto en el proyecto— y sus ``values`` resueltos, el nombre del dato de la
    superficie de partida (``start_surface``) y de apoyo (``support_surface``; ``None`` sin ella), el ``fid`` de la geometría de la
    capa de zonas (``fid``) y lo que lee el cálculo de los parámetros del proyecto y del perfil (``common``: ``des.bench.{p}.*`` y los de
    ``provenance.PLATFORM_COMMON_PARAMS``). ``existing``: la entidad ya estaba en la versión (se preparó con su ``code``: recalcularla),
    así que «Crear» no escribe otra vez sus parámetros."""

    job: ButtressJob
    start: OperationStart
    code: str
    version: Version
    rows: tuple[EntityParamRow, ...]
    values: Mapping[str, Any]
    start_surface: str
    support_surface: str | None
    fid: int
    common: Mapping[str, object]
    existing: bool = False

    @property
    def op_type(self) -> str:
        """El tipo de la operación (``des.buttress``)."""
        return self.start.op_type


# --- Los parámetros -----------------------------------------------------------------------------------------------


def buttress_values(request: ButtressRequest, code: str, fid: int | str) -> tuple[dict[str, Any], frozenset[str]]:
    """Los parámetros resueltos y comprobados del contrafuerte ``request`` de código ``code`` (RF-015-08; por último segmento de su clave) y
    **los nombres de los que se dejaron por su valor por defecto**: la cota de coronación no tiene ninguno (D-21: la petición no lleva
    ninguna cifra minera; ``des.entity_param_missing``), el perfil, tampoco, el alcance es opcional, la métrica es la euclídea exacta y
    **protege por defecto** («sin corte» sobre su zona de coronación, D-1) con un **resguardo sin valor por defecto y obligatorio** si
    protege (D-19: ``des.entity_param_missing`` o ``_range``). La «capa» de los mensajes es la de las zonas y la geometría, la de **su
    ``fid``** (lo que recalcular y reproducir leen). **Sin proyecto**: lo comparten preparar y reproducir."""
    spec = entity_params("buttress")
    defaulted: set[str] = set()
    protect = request.protect
    if protect is None:
        protect = spec.template(ButtressParam.PROTECT.value).default  # type: ignore[assignment]
        defaulted.add(ButtressParam.PROTECT.value)
    metric = None if request.metric is None else str(request.metric)
    if metric is None:
        metric = spec.template(ButtressParam.METRIC.value).default  # type: ignore[assignment]
        defaulted.add(ButtressParam.METRIC.value)
    asked: dict[ButtressParam, object] = {
        ButtressParam.NAME: request.name, ButtressParam.LAYER: request.layer, ButtressParam.FEATURE: str(fid),
        ButtressParam.START: request.start, ButtressParam.SUPPORT: request.support, ButtressParam.PROFILE: request.profile,
        ButtressParam.REACH: request.reach_m, ButtressParam.CROWN: request.crown_m, ButtressParam.METRIC: metric,
        ButtressParam.PROTECT: bool(protect), ButtressParam.GUARD: request.guard_m, ButtressParam.REASON: request.reason}
    values: dict[str, Any] = {}
    for param in ButtressParam:
        if param in (ButtressParam.SUPPORTS, ButtressParam.DISCARDED):
            continue
        required = bool(protect) if param is ButtressParam.GUARD else None
        checked = check_entity_param(request.name, code, param.value, asked[param], layer=request.layer, required=required)
        if checked is not None:
            values[param.value] = checked
    return values, frozenset(defaulted)


def _buttress_rows(request: ButtressRequest, code: str, values: Mapping[str, Any], defaulted: frozenset[str]
                   ) -> tuple[EntityParamRow, ...]:
    """Las filas de los parámetros de la entidad con su procedencia (RF-008-01): lo que no se pidió, con la de su valor por defecto;
    el resto, lo que eligió la persona en el diálogo. **Todas** (también las de los valores por defecto)."""
    spec = entity_params("buttress")
    rows: list[EntityParamRow] = []
    for param in ButtressParam:
        value = values.get(param.value)
        if value is None:
            continue
        if param.value in defaulted:
            declared = spec.template(param.value)
            source, kind, reason = declared.source, str(declared.source_kind), default_reason(declared)
        else:
            source, kind = f"{_BUTTRESS_DIALOG}, entidad «{request.name}»", "person"
            reason = f"Elegido al crear el contrafuerte «{request.name}»"
        rows.append(EntityParamRow(entity_key(code, param), param.value, value, source, kind, reason))
    return tuple(rows)


def _profile_values(project: StoreProject, version: Version, profile: str) -> dict[str, object]:
    """Los cinco valores del perfil de banco ``profile`` como los leería una operación que empezara ahora (versión → proyecto, valor por
    defecto de su definición), por su clave ``des.bench.{p}.<valor>``, **sin escribir nada**."""
    keys = provenance.profile_params([profile])
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(conn, keys, (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid)
    values: dict[str, object] = {}
    for key in keys:
        resolved = found.get(key)
        declared = definition(key) if resolved is None else None
        values[key] = resolved.value if resolved is not None else (None if declared is None else declared.default)
    return values


def _lowest_of(start: np.ndarray) -> float | None:
    """La cota más baja de la partida (``None`` sin ninguna celda con dato): lo que hace falta para saber hasta dónde llega la envolvente
    (A0)."""
    found = np.isfinite(start)
    return float(start[found].min()) if found.any() else None


def buttress_work_window(request: ButtressRequest, code: str, zone: np.ndarray, grid: Grid, profile: Any, values: Mapping[str, Any],
                         lowest_m: float | None) -> tuple[slice, slice]:
    """**A0**: la ventana de trabajo del contrafuerte (la de :func:`~.buttress.buttress_window` con el alcance de
    :func:`~.buttress.buttress_reach_m`) de la zona de coronación ``zone`` (máscara de la rejilla entera). ``lowest_m`` es la cota más baja
    de la partida de la rejilla entera (no hace falta con el alcance fijado). Lo comparten preparar y reproducir: la misma ventana, los
    mismos bits. ``des.buttress_crown_below_support`` si la zona no tiene ninguna celda o la partida no tiene ningún dato."""
    crown = float(values[ButtressParam.CROWN.value])
    reach = values.get(ButtressParam.REACH.value)
    metric = Metric(values[ButtressParam.METRIC.value])
    if lowest_m is None and reach is None:
        raise buttress.below_support_error(request, code, crown)
    span = buttress.buttress_reach_m(profile, crown, lowest_m, None if reach is None else float(reach), metric)
    window = buttress.buttress_window(zone, grid, span, metric)
    if window is None:
        raise buttress.below_support_error(request, code, crown)
    return window


# --- Preparar -----------------------------------------------------------------------------------------------------


def _check_buttress_chain(registry: entities.EntityRegistry, request: ButtressRequest, code: str, version: Version) -> None:
    """RF-015-04, RF-015-15, H-9: **nadie parte de la superficie de un cuerpo «bajo un techo»** (``des.chainless_start``: ni la partida ni
    el apoyo del contrafuerte), de la superficie de la que parte solo parte una entidad (``des.entity_start_taken``), la cadena no da la
    vuelta (``des.entity_chain_cycle``) y la superficie de apoyo no es la de la propia entidad ni la de una que parte de la suya
    (``des.entity_supports_unknown``). El contrafuerte ``code`` no cuenta consigo mismo."""
    obj = f"Contrafuerte «{request.name}»"
    entity_store._check_surface_left(registry, request.name, code, request.start, entity_key(code, ButtressParam.START), obj=obj)
    if request.support is not None:
        entity_store._check_surface_left(registry, request.name, code, request.support, entity_key(code, ButtressParam.SUPPORT), obj=obj)
    other = entities.start_conflict(registry.records, request.start, ignoring=code)
    if other is not None:
        raise DesignError("des.entity_start_taken", obj=obj, field=entity_key(code, ButtressParam.START), value=request.start,
                          entity=request.name, other=other.name)
    records = [item for item in registry.records if item.code != code]
    entities.check_chain([*records, entities.EntityRecord(code, request.name, EntityKind.BUTTRESS, request.start, request.support)])
    entity_store._check_support_cycle(registry, request.name, code, request.support, entity_key(code, ButtressParam.SUPPORT),
                                      version.code)


def prepare_buttress_units(project: StoreProject, request: ButtressRequest, version: Version,
                           masks: access.MaskSet | access.MaskSource, *, code: str | None = None,
                           supersedes: str | None = None, released: Sequence[provenance.ReleasedSupport] = ()
                           ) -> Generator[None, None, PreparedButtress]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan el contrafuerte ``request`` de la versión
    editable ``version`` con sus ``masks`` ya al día (:func:`~.store.masks_steps`): el código (``code``: el de una entidad que ya está en
    la versión, que no choca consigo misma; si no, el siguiente, ``BTR-001``), el nombre único y la cadena, la capa de las zonas
    (polígonos) y su geometría, los parámetros resueltos (**sin cota de coronación o sin resguardo, rechazado**: D-21 y D-19), **el perfil
    y la cota del ancla antes de leer ninguna superficie** (RF-016-18: ``des.buttress_crown_off_anchor``), la partida y el apoyo, la
    ventana de trabajo (A0: la zona ampliada por lo que alcanza la envolvente) con lo que se lee de ella —la partida, el relleno admitido
    de las máscaras, **también en las zonas de solo restauración** (D-24)—, los sectores con la búsqueda pendiente y lo que anotará la
    operación. ``supersedes``: la operación hecha a la que sustituye (un recálculo); ``released``: lo que da por bueno sin su apoyo.
    Devuelve la :class:`PreparedButtress`. **Nada se escribe**; los rechazos salen al avanzar, en el orden de la documentación del
    módulo."""
    require_version(project, version.uid, provenance.BUTTRESS)
    registry = entities.registry(project, version.uid)
    chosen = code if code is not None else entities.next_code(EntityKind.BUTTRESS, (entry.record.code for entry in registry))
    entity_store._check_name(registry, request.name, chosen, version.code)
    _check_buttress_chain(registry, request, chosen, version)
    yield
    layer = entity_store._layer(project, request.layer)
    if layer.kind != "polygon":
        raise DesignError("des.layer_not_polygons", obj=f"Capa «{request.layer}»", field="geometría",
                          value=entity_store._KINDS_ES.get(layer.kind, layer.kind), layer=request.layer)
    index = entity_store.feature_index(layer, request, chosen)  # type: ignore[arg-type]
    fid = layer.fids[index]
    values, defaulted = buttress_values(request, chosen, fid)
    yield
    profile_values = _profile_values(project, version, request.profile)
    profile = pipeline.bench_profiles(profile_values, [request.profile])[request.profile]
    buttress.check_crown_anchor(request, chosen, profile, float(values[ButtressParam.CROWN.value]))  # RF-016-18: antes de leer nada
    yield
    frame = project_frame(project)
    grid = frame.grid
    start_name = entity_store._surface_dataset(registry, version, request, chosen, ButtressParam.START, request.start)  # type: ignore[arg-type]
    support_name = (None if request.support is None else entity_store._surface_dataset(
        registry, version, request, chosen, ButtressParam.SUPPORT, request.support))  # type: ignore[arg-type]
    whole = zones.polygons_cells(tuple(tuple(part) for part in layer.parts[index]), grid)
    full = (slice(0, grid.nrows), slice(0, grid.ncols))
    lowest: float | None = None
    whole_start: np.ndarray | None = None
    if values.get(ButtressParam.REACH.value) is None:  # sin alcance, la envolvente llega hasta la cota más baja de la partida entera
        whole_start = read_surface_window(project, start_name, full, version_uid=version.uid, expect=frame,
                                          role="superficie de partida").values
        lowest = _lowest_of(whole_start)
    window = buttress_work_window(request, chosen, whole, grid, profile, values, lowest)
    yield
    if whole_start is not None:
        start = np.array(whole_start[window], dtype=np.float64, copy=True)
        del whole_start
    else:
        start = read_surface_window(project, start_name, window, version_uid=version.uid, expect=frame,
                                    role="superficie de partida").values
    if support_name is not None:  # la de apoyo existe y es de la rejilla del proyecto; no cambia el cálculo (T26, decisión 1)
        read_surface_window(project, support_name, window, version_uid=version.uid, expect=frame, role="superficie de apoyo")
    fill = admitted_in(masks, BenchSense.FILL, window)
    yield
    sectors = design_sectors(project, version.uid)
    if any(sector.pending for sector in sectors):  # RF-015-07: el contrafuerte mueve celdas
        refs, labels = sector_layout(project, masks)  # type: ignore[arg-type]
        touched = pipeline.touched_in(refs, labels[window], fill)  # lo que puede mover: el relleno admitido de su ventana
        refuse_pending(sector for sector in sectors if sector.code in touched)
    yield
    common = {**profile_values, **entity_store._common(project, version)}
    job = ButtressJob(request, chosen, grid, profile, start, whole[window], fill, MappingProxyType(dict(values)), region=window,
                      lowest_m=lowest)
    supported, footprints, reads = entity_store._support_inputs(
        project, version, request, chosen, registry, support_name,  # type: ignore[arg-type]
        entity_store._released_codes(project, supersedes, released))
    inputs = provenance.buttress_inputs(request, start_name, masks.uses(), supported)
    inputs = (*inputs, *(use for use in footprints if use not in inputs))
    begun = _start(project, provenance.BUTTRESS, request.name, version, masks,  # type: ignore[arg-type]
                   provenance.buttress_settings(request, chosen), inputs,
                   provenance.buttress_params(chosen, request, supports=reads), supersedes)
    yield
    return PreparedButtress(job, begun, chosen, version, _buttress_rows(request, chosen, values, defaulted), MappingProxyType(values),
                            start_name, support_name, int(fid), MappingProxyType(common), code is not None)


def prepare_buttress(project: StoreProject, request: ButtressRequest, *, version: str | None,
                     masks: access.MaskSet | None = None, code: str | None = None,
                     supersedes: str | None = None) -> PreparedButtress:
    """La preparación entera de :func:`prepare_buttress_units` de una vez (sin ceder el hilo; las máscaras que no se dan se abren sin
    cargar sus celdas: ``entity_store._masks_to_read``): la :class:`PreparedButtress`, con los mismos rechazos y sin escribir nada."""
    found = require_version(project, version, provenance.BUTTRESS)
    loaded = entity_store._masks_to_read(project, found, masks)
    return _result_of(prepare_buttress_units(project, request, found, loaded, code=code, supersedes=supersedes))


# --- Calcular (RF-015-03, RF-015-29, RNF-016-02 y 03) -------------------------------------------------------------


def buttress_compute_steps(job: ButtressJob, *, budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, ButtressOutcome]:
    """Los pasos que calculan el contrafuerte de ``job`` (RF-016-17, RF-016-18, RF-015-29; plan 016 §5.3.2: el ``buttress_compute_steps`` que
    **comparten «Calcular», el recálculo y la reproducción**), sin proyecto y sin escribir nada (``yield from``; cerrar el generador no deja
    nada): A10 (``buttress.buttress_steps``) por pasos de ``budget_s`` como mucho. Los rechazos de RF-016-18 salen al llamar y al avanzar
    (``des.buttress_crown_off_anchor``, ``des.buttress_crown_below_support``) y, **si ninguna celda sube** (el relleno no está admitido
    donde llegarían sus taludes: no hay huella que declarar ni que enseñar), ``des.buttress_nothing_rises``. Devuelve el
    :class:`~.buttress.ButtressOutcome`."""
    name = job.request.name
    yield Progress(_BUTTRESS_PHASE, 0, 1, f"Calculando el contrafuerte «{name}»…")
    outcome: ButtressOutcome = yield from pipeline.forward(buttress.buttress_steps(job, budget_s=budget_s))
    if not np.any(outcome.footprint):
        raise DesignError("des.buttress_nothing_rises", obj=f"Contrafuerte «{name}»", field=entity_key(job.code, ButtressParam.CROWN),
                          value=outcome.crown_m, layer=job.request.layer, entity=name)
    yield Progress(_BUTTRESS_PHASE, 1, 1, f"Contrafuerte «{name}» calculado")
    return outcome


def _runs_text(cells: np.ndarray, window: tuple[slice, slice]) -> str:
    """Los tramos de fila de ``cells`` (de la forma de ``window``) como JSON compacto: ``[[fila, col0, col1], …]`` absolutos."""
    runs = entity_store.footprint_runs(cells, window)
    return json.dumps([list(run) for run in runs], separators=(",", ":"), allow_nan=False)


def buttress_entity_rows(job: ButtressJob, outcome: ButtressOutcome, *, layer: str, source_fid: int, start_surface: str,
                         support_surface: str | None) -> list[Row]:
    """La fila de ``des_epr_`` (columnas de :data:`~.store.BUTTRESS_ENTITY_COLUMNS`: las de :data:`~.store.ENTITY_COLUMNS` y ``zone``) del
    contrafuerte de ``job`` con su ``outcome`` (RF-015-01; P-8, H-6): **una**, con los atributos de la entidad —su código, su nombre, su
    tipo ``buttress``, los datos de su superficie de partida y de apoyo, **la capa y el ``fid`` de su zona de coronación** y el hash de
    esa zona, el modo ``buttress`` y las celdas de la huella—, su ventana de trabajo, **la huella entera** en tramos de fila (``footprint``:
    donde la superficie sube, dentro y fuera de la zona dibujada), ningún eje y **la zona de coronación** (``zone``: lo que declara «sin
    corte»). Solo depende de lo que se lee para calcular, no del proyecto: lo repite la reproducción desde lo congelado."""
    zone_text = _runs_text(outcome.zone, outcome.window)
    rows, cols = outcome.window
    return [(job.code, job.request.name, EntityKind.BUTTRESS.value, start_surface, support_surface, layer, int(source_fid),
             hashlib.sha256(zone_text.encode()).hexdigest(), "buttress", int(np.count_nonzero(outcome.footprint)), 0,
             json.dumps([int(rows.start), int(rows.stop), int(cols.start), int(cols.stop)], separators=(",", ":")),
             _runs_text(outcome.footprint, outcome.window), "[]", zone_text)]


def buttress_report_rows(outcome: ButtressOutcome) -> list[Row]:
    """Las filas de ``des_prp_`` (formato largo: ``quantity, value, unit_code, note``; RF-016-17) del contrafuerte ``outcome``, en este
    orden: las celdas (la zona de coronación, las semillas y la huella), las cifras (volumen, área y altura máxima con su lugar), los
    valores que lo gobiernan (la cota de coronación y, si se fijó, el alcance) y, al final, los avisos y notas (``warning`` y ``note`` con
    su código y sus valores en JSON). Un valor que no es finito es un error del programa (``ValueError``). Solo depende del resultado: lo
    repite la reproducción."""
    rows: list[Row] = []

    def scalar(key: str, value: float, unit: str, note: str | None = None) -> None:
        rows.append((key, _real(key, value), unit, note))

    for key, count in (("zone_cells", int(np.count_nonzero(outcome.zone))), ("seed_cells", outcome.seed_cells),
                       ("footprint_cells", int(np.count_nonzero(outcome.footprint)))):
        scalar(key, count, "-")
    scalar("volume_m3", outcome.volume_m3, "m3")
    scalar("area_m2", outcome.area_m2, "m2")
    place = (None if outcome.height_max_x is None or outcome.height_max_y is None
             else f"{_real('height_max.x', outcome.height_max_x)!r};{_real('height_max.y', outcome.height_max_y)!r}")
    scalar("height_max_m", outcome.height_max_m, "m", place)
    scalar("crown_m", outcome.crown_m, "m")
    if outcome.reach_m is not None:
        scalar("reach_m", outcome.reach_m, "m")
    for notice in outcome.notices:
        rows.append((notice.severity, None, None, _notice_text(notice)))
    return rows


def compute_buttress_steps(writer: DesignWriter, prepared: PreparedButtress, *, budget_s: float = STEP_BUDGET_S
                           ) -> Generator[Progress, None, ButtressOutcome]:
    """Lo que hace «Calcular» sobre el ``writer`` (RF-015-03, RF-015-29; patrón de :func:`compute_removal_steps`): calcula el contrafuerte
    preparado (:func:`buttress_compute_steps`), deja su superficie —la de partida, **entera**, con el resultado en la ventana del
    contrafuerte— en el temporal de ``writer`` (``des_psf_``, con su hash, P-12) y prepara, con su hash en memoria, la huella con su zona de
    coronación (``des_epr_``) y el informe (``des_prp_``), **sin confirmar**: lo que falta para crearlo (:func:`create_buttress`) es una
    sola transacción. Devuelve el :class:`~.buttress.ButtressOutcome`."""
    job = prepared.job
    outcome = yield from buttress_compute_steps(job, budget_s=budget_s)
    whole = yield from _whole_start_steps(writer.project, prepared, budget_s)  # type: ignore[arg-type]
    yield from pipeline.forward(_store_steps(
        writer.grid_steps(provenance.ENTITY_SURFACE_GRID, Raster(job.grid, outcome.compose(whole), writer.crs, writer.vertical)),
        budget_s, "la superficie del contrafuerte"))
    entity = buttress_entity_rows(job, outcome, layer=job.request.layer, source_fid=prepared.fid, start_surface=prepared.start_surface,
                                  support_surface=prepared.support_surface)
    yield from pipeline.forward(_store_steps(writer.table_steps(provenance.ENTITY_TABLE, entity), budget_s, "la huella del contrafuerte"))
    yield from pipeline.forward(_store_steps(writer.table_steps(provenance.ENTITY_REPORT_TABLE, buttress_report_rows(outcome)),
                                             budget_s, "el informe del contrafuerte"))
    return outcome


# --- El resumen (RF-015-03, RF-016-17) ----------------------------------------------------------------------------


def buttress_obsolete(project: StoreProject, prepared: PreparedButtress, *, supersedes: str | None = None) -> tuple[Obsolete, ...]:
    """**Lo que quedará obsoleto al crear** el contrafuerte ``prepared`` (RF-015-03, RF-015-16): uno nuevo no deja obsoleto nada; el que
    **sustituye** una operación (``supersedes``: un recálculo) deja obsoleto lo que dependía de lo que escribió, en cascada. Solo lee."""
    if supersedes is None:
        return ()
    with project.read() as conn:
        written = [str(row[0]) for row in conn.execute(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' AND item_kind = 'dataset' "
            "ORDER BY fid", (supersedes,))]
        found = entity_store._dependents(conn, written, prepared.version.uid, exclude=(supersedes,))
    return tuple(entity_store._consumer(ObsoleteKind.DEPENDENT, uid, op_type, name) for uid, op_type, name in found)


def buttress_summary(project: StoreProject, prepared: PreparedButtress, outcome: ButtressOutcome, *,
                     supersedes: str | None = None) -> ButtressSummary:
    """El resumen de «Calcular» el contrafuerte ``prepared`` (RF-015-03, RF-016-17): las cifras que se registrarán (volumen, área y altura
    máxima con su lugar), si declara «sin corte» sobre su zona de coronación (``protect``, con su resguardo) y los avisos en el orden en
    que se enseñan (los del cálculo y lo que quedará obsoleto). Solo lee."""
    kept = buttress_obsolete(project, prepared, supersedes=supersedes)
    request = prepared.job.request
    values = prepared.values
    guard = values.get(ButtressParam.GUARD.value)
    notices = (*outcome.notices, *obsolete_notices(request.name, prepared.version.code, kept))
    return ButtressSummary(
        request.name, prepared.code, prepared.version.code, request.layer, outcome.profile, outcome.crown_m, outcome.figures,
        outcome.volume_m3, outcome.area_m2, outcome.height_max_m, outcome.height_max_x, outcome.height_max_y,
        bool(values.get(ButtressParam.PROTECT.value)), None if guard is None else float(guard), notices, kept)


# --- Crear (RF-016-17, RF-015-01, RF-015-02) ------------------------------------------------------------------------


def create_buttress(project: StoreProject, writer: DesignWriter, prepared: PreparedButtress, outcome: ButtressOutcome, *,
                    decided_by: str | None = None) -> Stored:
    """**«Crear» un contrafuerte** (RF-016-17, RF-015-01, RF-015-02): registra en **una** transacción
    (:meth:`~.store.DesignWriter.commit` de ``writer``, el de «Calcular», con sus tres salidas preparadas) los parámetros de la entidad
    —una fila de la versión por parámetro, con su origen y su decisor ``decided_by`` (por defecto, quien tiene abierto el proyecto)—,
    la operación ``des.buttress`` con sus entradas (la capa de las zonas, la superficie de partida, las máscaras y lo que apoya) y sus
    parámetros, la superficie entera (``des_psf_``), la huella con su zona de coronación (``des_epr_``), el informe y las cifras
    ``des.btr_*`` con el ámbito de la entidad. Una entidad que ya estaba en la versión (``prepared.existing``) no vuelve a escribir sus
    parámetros. Si algo falla, o lo que consume cambió desde que se calculó (``des.input_changed``), no queda nada y el error sigue;
    **no modifica ninguna entrada**. **No declara la restricción** («sin corte»: ``des.declare_constraints``): es lo que encadena la orden
    tras el commit (``entity_store.after_entity_change``)."""
    start = prepared.start

    def parameters(conn: sqlite3.Connection) -> None:
        if prepared.existing:
            if ParameterStore(project).get(entity_key(prepared.code, ButtressParam.NAME), version=start.version_uid,
                                           conn=conn) is None:
                raise ValueError(f"la entidad {prepared.code} no tiene sus parámetros en la versión: no está en ella (se prepara "
                                 "sin su código)")
        else:
            set_entity_params(project, prepared.rows, version=start.version_uid, decided_by=decided_by, conn=conn)

    return writer.commit(start, figures=outcome.figures, message=outcome.message, before_begin=parameters)


# --- Recalcular (RF-015-02, RF-015-16, RF-008-26) --------------------------------------------------------------------


def _check_recorded_buttress(handle: OperationHandle, prepared: PreparedButtress) -> None:
    """Los parámetros que anotó la operación al empezar son los que leyó el cálculo al prepararse (RF-013-17, D-14): si uno cambió entre
    las dos cosas, el resultado ya no le corresponde (``des.input_changed``, con el parámetro)."""
    read: dict[str, object] = {entity_key(prepared.code, ButtressParam(name)): value for name, value in prepared.values.items()}
    read.update(prepared.common)
    for param in handle.params:
        if param.key in read and param.value != read[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»", field="parámetros", value=param.key)


def run_buttress(project: StoreProject, request: ButtressRequest, *, version: str | None, code: str,
                 masks: access.MaskSet | None = None, supersedes: str | None = None, budget_s: float = STEP_BUDGET_S,
                 released: Sequence[provenance.ReleasedSupport] = ()) -> tuple[OperationHandle, Iterator[Progress]]:
    """Calcula y registra ``request`` —un contrafuerte que ya está en la versión ``version``: su ``code``— de **una vez** (RF-015-02,
    RF-015-16; el recálculo de lo obsoleto, :func:`~.store.recompute_run`; el «Crear» tras «Calcular» es
    :meth:`~.steps.Calculation.create`): empieza la operación ``des.buttress`` —si ``supersedes`` es la de una anterior, la sustituye,
    quedándose con los nombres de sus datos— con lo que lee hoy y devuelve su ``OperationHandle`` «en curso» y sus pasos, que avanza
    quien la llama: calculan (:func:`buttress_compute_steps`), escriben la superficie, la huella con su zona y el informe y completan la
    operación en una transacción; el último lleva el :class:`~.store.Stored`. No escribe parámetros de la entidad (ya están). Cerrarlos
    antes, o un fallo, no dejan nada y la operación queda cancelada o fallida. Al llamar, sin empezar nada: los rechazos de
    :func:`prepare_buttress_units`."""
    found = require_version(project, version, provenance.BUTTRESS)
    loaded = entity_store._masks_to_read(project, found, masks)
    prepared = _result_of(prepare_buttress_units(project, request, found, loaded, code=code, supersedes=supersedes, released=released))
    handle = prepared.start.with_released(released).begin(project)
    return handle, _buttress_run(project, handle, prepared, budget_s)


def _buttress_run(project: StoreProject, handle: OperationHandle, prepared: PreparedButtress, budget_s: float
                  ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        _check_recorded_buttress(handle, prepared)
        outcome: ButtressOutcome = yield from compute_buttress_steps(writer, prepared, budget_s=budget_s)
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_BUTTRESS_PHASE, 1, 1, outcome.message, result=stored)


def recompute_buttress(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S,
                       released: Sequence[provenance.ReleasedSupport] = ()) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.buttress`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto», RF-008-26; RF-015-02,
    RF-015-16): el contrafuerte de sus ajustes (el nombre, el código y el campo de la cota) con los **parámetros vigentes de su entidad en
    su versión** (:func:`~.entity_store.entity_parameters`: la capa y su geometría, la partida, el apoyo, el perfil, el alcance, la cota de
    coronación y la métrica) y no los que leyó la operación que sustituye: una entidad se define por sus parámetros (RF-015-01). Devuelve
    lo de :func:`run_buttress`. ``ValueError`` si los ajustes no son los de un contrafuerte o la petición no es de una versión."""
    project: StoreProject = request.project  # type: ignore[assignment]
    code = provenance.supported_code(request.settings)
    found = require_version(project, request.version, provenance.BUTTRESS)
    asked = provenance.buttress_request(request.settings, entity_parameters(project, code, version=found))
    return run_buttress(project, asked, version=found.uid, code=code, supersedes=request.operation_uid, budget_s=budget_s,
                        released=released)
