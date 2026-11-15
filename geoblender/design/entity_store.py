# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar la plataforma —lo que se lee y se rechaza antes de calcular—, calcularla, crearla y recalcularla, y
declarar las restricciones de las entidades de una versión (spec 015, T11 a T14 y T17; HU-015-1, HU-015-2, HU-015-3; RF-015-01, RF-015-02, RF-015-03, RF-015-04, RF-015-06,
RF-015-07, RF-015-08, RF-015-09, RF-015-10, RF-015-12, RF-015-13, RF-015-16, RF-015-29; plan 015 §5.1, §5.2.1,
§5.2.2, §5.2.3, §5.3.1 y §5.3.2; ADR-0030).

El homólogo, para las entidades de diseño, de ``prepare_quarry`` y ``prepare_quarry_units`` de
``design.store``: **solo lee**. Nada se escribe en el proyecto (RF-015-03: hasta que el usuario
confirme), salvo las máscaras de la versión si no estaban al día (una operación propia, RF-013-04) y,
por una orden aparte y explícita, los parámetros de la entidad (:func:`set_entity_params`).

- :func:`prepare_platform_units` (por unidades, para componerlas con ``pace_units``): la versión
  editable (RF-009-21), el nombre único y el código ``PLT-nnn`` de la entidad (``design.entities``),
  la partida (de cada superficie parte como mucho una entidad, sin ciclos: RF-015-04), la capa y la
  geometría elegida (por su nombre o su ``fid``: ``gis.store.load_features``) con los campos de la
  capa (la cota inicial, la pendiente y, de una línea, el ancho; de un polígono, el enlace con su
  eje), los parámetros resueltos y comprobados (RF-015-08) y la superficie de partida y la de apoyo
  (``design.surfaces.read_surface``, en la rejilla del proyecto: RF-011-02, RF-011-03), con las
  máscaras de la versión (``masks_steps``, registradas como entradas: RF-015-06; el corte y el relleno
  admitidos son los de ``design.compose.admitted``, RF-012-13: el relleno incluye la franja de solo
  relleno). Rechaza antes de
  calcular, sin escribir nada: la geometría que no es válida (``platform_footprint``), una cota
  fuera de las del terreno ± 1.000 m, la pendiente máxima (D-6: «es una rampa»), proteger en el modo
  «en corte y relleno» (RF-015-12), la falta de dato en la huella de la superficie de partida o de
  la de apoyo (RF-015-09: la entidad, la superficie y el área sin dato con el lugar de su primera
  celda) y un sector sin búsqueda de intocables vigente que toca la huella o una celda que la
  plataforma puede mover (RF-015-07: **``refuse_pending`` se llama aquí**, nada lo hace solo). Da una
  :class:`PreparedPlatform`: el ``PlatformJob`` listo para calcular (todo lo leído y nada del
  proyecto), la huella, lo que anotará la operación (``OperationStart``) y las filas de los parámetros
  de la entidad (:class:`EntityParamRow`).
- :func:`prepare_platform`: la misma preparación entera, que da solo la ``OperationStart``
  (plan 015 §5.3.1).
- :func:`set_entity_params`: escribe las filas de la entidad como **parámetros de la versión**, cada
  una con su tipo (ADOPTADO), su origen y su decisor. Un cálculo no cambia parámetros por su cuenta
  (ADR-0025 §5): lo hace quien crea la entidad (T13, en la transacción del ``commit``, antes de
  abrir la operación). **Todas** las filas, también las de los valores por defecto: con una clave de
  la familia ``des.platform.{e}.*`` con valor por defecto y sin fila en la versión
  (``mode``, ``mesh_factor``, ``counter_tol_m``, ``metric``, ``protect``), ``begin_operation`` la
  crea **en el proyecto** y la entidad llegaría a toda versión (trampa de la T04, ``docs/trampas.md``).

**Calcular** (T12; RF-015-03, RF-015-29): :func:`platform_compute_steps` es el cálculo —la huella, aplicar,
el borde, el perfil y las cifras de ``design.platform``— por pasos de ≤ 0,05 s, **sin proyecto dentro**
(recibe lo ya leído): lo comparten «Calcular», el recálculo y la reproducción. :func:`compute_platform_steps`
lo hace sobre un ``DesignWriter`` y deja la superficie (``des_psf_``) en un temporal; **no hay operación, ni
dato, ni cifra todavía**. Del resumen (:func:`platform_summary`: las cifras, los avisos y lo que quedará
obsoleto al crearla), lo que sale del proyecto: con qué se compara la magnitud (:func:`platform_previous`, la
revisión congelada más reciente), el orden de la cantera de la 014 (:func:`quarry_order`), qué restricción
impide mover unas celdas (nombres y entidades que declaran, ``preview.held_notices``) y lo obsoleto
(:func:`platform_obsolete`, del grafo de la 008: no se marca nada de una revisión congelada, RF-009-19).

**Crear** (T13; RF-015-01, RF-015-02, RF-015-04): :func:`create_platform` registra lo calculado en **una**
transacción del ``DesignWriter`` (:meth:`~.store.DesignWriter.commit`): los parámetros de la entidad como
filas de la versión (:func:`set_entity_params`, con el gancho ``before_begin`` del ``commit``, antes de abrir la
operación), la operación con sus entradas y ajustes, la superficie ``des_psf_``, la tabla ``des_epr_``
(:func:`platform_entity_rows`: una fila con los atributos de la entidad, su huella en tramos de fila
—:func:`footprint_runs`, :func:`runs_mask`—, su eje y el hash de su geometría de origen,
:func:`geometry_sha256`), el informe ``des_prp_`` (:func:`platform_report_rows`) y las cifras con el ámbito
de la entidad. «Calcular» deja ya preparadas las tres salidas (:func:`compute_platform_steps`: el hash de
las tablas se calcula fuera de la transacción, R4). Una plataforma que parte de otra consume su superficie
(``des_psf_<nombre>``) como entrada ``surface``, y cambiar un parámetro de la primera deja obsoleta la
segunda con la causa (la 008). **Lo que se apoya en otras entidades** (T23; RF-015-15, D-11): el gancho
genérico de ``DesignWriter.commit`` (:func:`survey_supports`, con ``design.entities.detect_supports``) añade, al
crearla, las entradas ``supported_on`` y ``support_footprint`` de cada entidad en cuya huella rellena y la cifra
``des.supported_m3``; lo que declara la persona (``des.platform.{e}.supports``, :func:`declared_supports`) y la
superficie de apoyo de la petición ya son entradas al preparar (:func:`prepare_platform_units`), con la tabla de
su huella, y se registran **aunque no apoyen nada**. :func:`detected_supports` lo enseña antes de crear.

**Recalcular** (T14; RF-015-02, RF-015-16, RF-008-26): :func:`recompute_platform` repite la operación con
los **parámetros vigentes de su entidad en su versión** (:func:`platform_parameters`: la definición de una
entidad, RF-015-01, no la capa ni lo que leyó la operación anterior) por :func:`run_platform`: la prepara
(con su ``code``: la cota inicial, la pendiente y el ancho salen de **su fila de la versión**, no de la capa),
empieza la operación que sustituye a la anterior, calcula con :func:`platform_compute_steps` y completa sin
escribir parámetros de la entidad. Lo llama ``design.store.recompute_run``. El recálculo no confirma una
contrapendiente por la persona (``des.platform_counter_unconfirmed``) y solo reutiliza la que ella confirmó al
crear (T15: ``counterslope_confirmed`` de los ajustes) si la nueva no pasa de la confirmada más la tolerancia.
La reproducción desde lo congelado, sin proyecto, es
``design.reproduce.reproduce_platform``, con el mismo cálculo (:func:`platform_compute_steps`,
:func:`entity_values` y :func:`read_geometry`).

**Declarar** (T17; RF-015-10, RF-015-12, RF-012-29; plan 015 §5.2.3, §5.3.2 y §5.4 A8): la declaración de
restricciones es una operación **de la versión** (``des.declare_constraints``, repetible), no de una entidad:
:func:`declared_sources` lee las entidades vivas y calculadas de la versión —cada una con sus parámetros
vigentes, su decisor y la fecha de su decisión y su huella—, :func:`declared_rows_steps` es el cálculo
(compartido con la reproducción) de una restricción por entidad que protege —«sin relleno», el contorno de su
huella, su resguardo obligatorio (D-19), el motivo generado o el que editó la persona, el decisor y la fecha de
**la decisión**, no la de ahora— y :func:`prepare_declaration`, :func:`run_declaration`,
:func:`declare_constraints_steps` y :func:`recompute_declaration` la preparan (rechazando proteger sin
resguardo y proteger en «corte y relleno», RF-015-12), la registran en **una** transacción reescribiendo la
tabla entera ``des_decl_<vNN>`` y la repiten. El mismo contenido de entidades da el mismo hash. La reproducción
desde lo congelado, ``design.reproduce.reproduce_declare_constraints``. **Editarla fuera de Geoblender** (T20;
RF-015-11, RF-008-56): la tabla es de las entidades, así que una edición en QGIS la bloquea y no se compilan las
máscaras con ella hasta que se acepte con un motivo o la entidad la vuelva a poner (declarar o recalcular la
declaración, que reescribe la tabla entera); :func:`declaration_diverges` dice, sin recalcular, si lo vigente
—p. ej. tras aceptar una edición— difiere de lo que declaran las entidades.

**Tras la orden de una entidad** (T19; RF-015-10, RF-015-16, RF-012-06; P-7; D-21): :func:`after_entity_change` es
lo que encadena cada orden de entidades tras su commit —y, con la misma función, descartar y retirar (T25, T26)—,
por pasos con progreso y Esc: repite la declaración y, si las máscaras ya no están al día (la declaración cambió, o
la compilación vigente no la había consumido nunca: el hueco H-1 de ``gis.masks.access``), las compila de nuevo y
da un :class:`EntityChain` con lo que quedó obsoleto y el área ganada y perdida por restricción. Cada etapa es una
operación y una transacción propias: si una falla, queda dicho (:class:`ChainFailure`) y las máscaras, obsoletas
con su causa. «Recalcular lo obsoleto» no la encadena: la declaración y las máscaras son operaciones de la 008 que
ella recalcula por el grafo.

La capa solo da la **geometría** y los **valores iniciales**: se copian a parámetros de la entidad
(con el origen «capa X, campo Y, entidad Z») y cambian después en ella; la capa no se modifica. Del
terreno (RF-015-09) se comprueba la superficie de partida y la de apoyo, que son las que lee el
cálculo: el terreno es la de partida salvo en una cadena (la de otra entidad nace de él).

Python puro (nivel 8), con numpy. ``design.entity_store`` es un módulo pesado de la 015: lo importan
las órdenes al usarlo, no ``bl`` al registrarse
(``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import (
    Callable,
    Collection,
    Generator,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.constraints.declared import (
    DeclaredConstraint,
    content_sha256_of,
    declared_code,
    declared_uid,
)
from ..core.constraints.model import ConstraintType
from ..core.constraints.store import constraint_names
from ..core.datasets import external as dataset_external
from ..core.datasets import registry as dataset_registry
from ..core.errors import GeoblenderError
from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterRecord, ParameterStore, definition
from ..core.params.store import default_reason
from ..core.project.model import Progress
from ..core.timeutil import format_utc
from ..core.provenance.graph import DATASET
from ..core.provenance.operations import OperationHandle, OperationStatus, Use
from ..core.provenance.recompute import RecomputeRequest
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from ..gis.masks import access
from ..gis.masks import provenance as masks_provenance
from ..gis.masks.store import StoredMasks
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S, Change
from ..gis.raster import Raster
from ..gis.store import StoreProject, load_features, project_references
from ..gis.vector import FeatureLayer
from . import entities, pipeline, provenance
from .compose import admitted
from .entities import EntityKind, EntityRecord, EntityRegistry, EntityState
from .envelopes import reach_steps
from .messages import DesignError
from .model import (
    BenchSense,
    LayerField,
    Metric,
    PlatformFields,
    PlatformMode,
    PlatformRequest,
)
from .params import (
    PLATFORM_PARAMS,
    PlatformParam,
    check_entity_param,
    entity_key,
    entity_segment,
)
from .platform import (
    Footprint,
    PlatformGeometry,
    PlatformJob,
    PlatformOutcome,
    QuarryOrder,
    _drain,
    _window_grid,
    apply_platform_steps,
    platform_edge_steps,
    platform_footprint,
    platform_outcome,
    summary_notices,
)
from .preview import (
    SUMMARY_ITEMS,
    Notice,
    Obsolete,
    ObsoleteKind,
    PlatformSummary,
    held_notices,
    obsolete_notices,
)
from .quarry import _level_column
from .report import Previous
from .sectors import design_sectors, refuse_pending
from .seeds import sector_layout
from .store import (
    _STORE_PHASE,
    DesignWriter,
    OperationStart,
    Row,
    Stored,
    _check_014_params,
    _loaded_masks,
    _min_thickness,
    _notice_text,
    _other_surface,
    _quarry_link,
    _real,
    _result_of,
    _seen,
    _start,
    _store_steps,
    design_surface_of,
    number,
    require_version,
)
from .surfaces import project_frame, read_surface

__all__ = [
    "LAYER_FIELDS",
    "ChainFailure",
    "ChainStage",
    "DeclaredSource",
    "EntityChain",
    "EntityFootprint",
    "EntityParamRow",
    "EntitySurface",
    "PreparedDeclaration",
    "PreparedPlatform",
    "SupportSurvey",
    "add_supports",
    "after_entity_change",
    "compute_platform_steps",
    "create_platform",
    "declaration_diverges",
    "declare_constraints_steps",
    "declared_rows_steps",
    "declared_supports",
    "declared_sources",
    "detected_supports",
    "entity_surfaces",
    "entity_values",
    "feature_index",
    "footprint_runs",
    "geometry_sha256",
    "layer_values",
    "platform_compute_steps",
    "platform_entity_rows",
    "platform_obsolete",
    "platform_parameters",
    "platform_previous",
    "platform_report_rows",
    "platform_summary",
    "prepare_declaration",
    "prepare_platform",
    "prepare_platform_units",
    "quarry_order",
    "read_entity_footprint",
    "read_geometry",
    "recompute_declaration",
    "recompute_platform",
    "run_declaration",
    "run_platform",
    "runs_mask",
    "set_entity_params",
    "survey_supports",
]

_KINDS_ES = MappingProxyType({"point": "puntos", "line": "líneas", "polygon": "polígonos"})
_NAME_FIELDS = ("nombre", "name")
"""Los campos de una capa de entidades que dan el nombre de cada geometría (sin distinguir
mayúsculas): por él se elige la geometría de una plataforma (el otro camino es su ``fid``)."""
_NO_VALUE = "—"
_START_ROLE = "partida"
_SUPPORT_ROLE = "apoyo"
_DIALOG = "diálogo de «Plataforma…»"
"""El origen de lo que elige la persona en el diálogo de la orden (entidad al final)."""
LAYER_FIELDS: Mapping[PlatformParam, str] = MappingProxyType({
    PlatformParam.START_LEVEL: "start_level_field", PlatformParam.GRADIENT: "gradient_field",
    PlatformParam.WIDTH: "width_field"})
"""Los valores que se copian de un campo de la capa y el atributo de
:class:`~.model.PlatformFields` que da su campo."""


# --- Lo que se prepara --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EntityParamRow:
    """Una fila de la familia ``des.platform.{e}.*`` que ha de tener la versión (RF-015-01): su
    ``key`` completa (``des.platform.plt_001.width_m``), el ``param``, su ``value`` ya comprobado y
    su procedencia (RF-008-01): el ``source`` (el origen, «capa X, campo Y, entidad Z» si se copió
    de la capa), su clase (``source_kind``: ``person``; ``algorithm`` el valor por defecto de su
    definición) y el ``reason`` de la fila nueva. Siempre ADOPTADO; el decisor es quien la escribe
    (:func:`set_entity_params`)."""

    key: str
    param: PlatformParam
    value: float | str | bool
    source: str
    source_kind: str
    reason: str


@dataclass(frozen=True, slots=True, eq=False)
class PreparedPlatform:
    """Lo que se lee y se comprueba antes de calcular una plataforma
    (:func:`prepare_platform_units`): el ``job`` (``design.platform.PlatformJob``: todo lo leído y
    nada del proyecto), su ``footprint`` (A0 y A1: huella, rasante y ventana de trabajo, ya
    calculadas para comprobarla), lo que anotará la operación (``start``), el ``code`` de la entidad
    (``PLT-001``), el ``fid`` de su geometría en su capa, las ``rows`` de sus parámetros, los
    parámetros del proyecto que lee el cálculo (``common``: clave → valor, los de
    :data:`~.provenance.PLATFORM_COMMON_PARAMS`, el ``project`` de ``platform_edge`` y
    ``platform_outcome``) y los nombres de los datos de la superficie de partida
    (``start_surface``) y de apoyo (``support_surface``; ``None`` sin ella), ya resueltos.
    ``existing`` (spec 015, T13): la entidad ya estaba en la versión (se preparó con su ``code``:
    recalcularla o calcular la que dejó «Traer las entidades de…»), así que «Crear» no escribe otra
    vez sus parámetros."""

    job: PlatformJob
    footprint: Footprint
    start: OperationStart
    code: str
    fid: int
    rows: tuple[EntityParamRow, ...]
    common: Mapping[str, float]
    start_surface: str
    support_surface: str | None
    existing: bool = False

    @property
    def values(self) -> Mapping[str, object]:
        """Los parámetros resueltos de la entidad, por último segmento de su clave."""
        return self.job.values


# --- El nombre, el código y la cadena -----------------------------------------------------------


def _object(request: PlatformRequest) -> str:
    return f"Plataforma «{request.name}»"


def _identify(project: StoreProject, version: Version, request: PlatformRequest, code: str | None
              ) -> tuple[str, EntityRegistry]:
    """El código de la entidad (``code`` si se da: una entidad que ya está en la versión; si no, el
    siguiente de su tipo, ``entities.next_code``) y el registro de las entidades de la versión.
    RF-015-01: el nombre es único en la versión (también el de una entidad sin calcular o
    descartada, que sigue en ella, y el que da el mismo nombre de dato): ``DesignError``
    ``des.entity_name_repeated`` con la entidad que lo tiene."""
    registry = entities.registry(project, version.uid)
    chosen = code if code is not None else entities.next_code(
        EntityKind.PLATFORM, (entry.record.code for entry in registry))
    entity_segment(chosen)  # un código que no es de una entidad es un error del programa
    wanted = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, request.name)
    for entry in registry:
        other = entry.record.name
        if entry.record.code != chosen and (
                other == request.name
                or provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, other) == wanted):
            raise DesignError("des.entity_name_repeated", obj=_object(request),
                              field=entity_key(chosen, PlatformParam.NAME), value=request.name,
                              other=other, version=version.code)
    return chosen, registry


def _check_chain(registry: EntityRegistry, request: PlatformRequest, code: str,
                 insert_before: str | None = None) -> None:
    """RF-015-04: de cada superficie parte como mucho una entidad (``des.entity_start_taken``, con la
    que ya parte) y la cadena no da la vuelta (``des.entity_chain_cycle``); la entidad ``code`` no
    cuenta consigo misma. Con ``insert_before`` (RF-015-05: la entidad de código o nombre que pasará a
    partir de la superficie de la nueva), la entidad nueva parte de la **misma** superficie que ella y
    no choca con ella: la cadena se comprueba con ella ya re-apuntada a la nueva (``ValueError``, error
    del programa, si no existe o parte de otra superficie)."""
    records = [item for item in registry.records if item.code != code]
    if insert_before is None:
        other = entities.start_conflict(registry.records, request.start, ignoring=code)
        if other is not None:
            raise DesignError("des.entity_start_taken", obj=_object(request),
                              field=entity_key(code, PlatformParam.START), value=request.start,
                              entity=request.name, other=other.name)
    else:
        successor = entities.find_entity(records, insert_before)
        if successor is None:
            raise ValueError(f"la versión no tiene ninguna entidad con el código o el nombre "
                             f"{insert_before!r}: no se puede insertar la plataforma "
                             f"«{request.name}» antes de ella")
        if (successor.start or "").strip() != (request.start or "").strip():
            raise ValueError(
                f"la plataforma «{request.name}» se inserta antes de «{successor.name}», que parte de "
                f"{successor.start!r}, pero ella parte de {request.start!r}: la insertada parte de la "
                "misma superficie (entities.insertion_start)")
        records = [replace(item, start=entities.surface_ref(code)) if item is successor else item
                   for item in records]
    this = EntityRecord(code, request.name, EntityKind.PLATFORM, request.start, request.support)
    entities.check_chain([*records, this])


def _surface_dataset(registry: EntityRegistry, version: Version, request: PlatformRequest,
                     code: str, param: PlatformParam, ref: str) -> str:
    """El nombre del dato de la superficie ``ref`` de la entidad (``start`` o ``support``): el
    nombre de una superficie, tal cual; ``entity:<código>``, la superficie de esa entidad
    (``des_psf_<nombre>``), que ha de estar calculada y no descartada (``des.entity_start_unknown``
    si no existe, está sin calcular o se descartó: no deja ninguna superficie que leer)."""
    target = entities.ref_code(ref)
    if target is None:
        return ref
    entry = registry.get(target)
    if entry is None or entry.record.state in (EntityState.UNCALCULATED, EntityState.DISCARDED):
        raise DesignError("des.entity_start_unknown", obj=_object(request),
                          field=entity_key(code, param), value=ref, entity=request.name,
                          version=version.code)
    return provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, entry.record.name)


# --- La capa y su geometría ---------------------------------------------------------------------


def _layer(project: StoreProject, name: str) -> FeatureLayer:
    """La capa de entidades ``name`` del proyecto (solo lee); ``ValueError`` si no es una capa de
    entidades (``gis_fea_``)."""
    found = load_features(project, name)
    if not isinstance(found, FeatureLayer):
        raise ValueError(f"«{name}» no es una capa de entidades del proyecto (gis_fea_)")
    return found


def _names(layer: FeatureLayer) -> tuple[str | None, ...]:
    """El nombre de cada geometría de la capa (su campo de nombre, :data:`_NAME_FIELDS`; ``None``
    sin él)."""
    for column in layer.columns:
        if column.sql_type == "TEXT" and column.field.casefold() in _NAME_FIELDS:
            return tuple(None if found is None else str(found).strip()
                         for found in layer.values[column.column])
    return (None,) * len(layer)


def feature_index(layer: FeatureLayer, request: PlatformRequest, code: str) -> int:
    """El índice (en el orden de la capa) de la geometría que elige la petición, por su ``fid`` (un
    número que está en la capa) o por su nombre. ``des.entity_param_missing`` si no se eligió
    ninguna, ``des.entity_feature_unknown`` si la capa no la tiene y ``des.entity_feature_ambiguous``
    si varias llevan ese nombre (con sus ``fid``: se elige por uno de ellos)."""
    check_entity_param(request.name, code, PlatformParam.FEATURE, request.feature,
                       layer=request.layer)
    wanted = request.feature
    if wanted.isascii() and wanted.isdigit() and int(wanted) in layer.fids:
        return layer.fids.index(int(wanted))
    found = [index for index, name in enumerate(_names(layer)) if name == wanted]
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise DesignError("des.entity_feature_ambiguous", obj=_object(request),
                          field=entity_key(code, PlatformParam.FEATURE), value=wanted,
                          layer=request.layer, fids=", ".join(str(layer.fids[i]) for i in found))
    raise DesignError("des.entity_feature_unknown", obj=_object(request),
                      field=entity_key(code, PlatformParam.FEATURE), value=wanted,
                      layer=request.layer)


def _field_value(layer: FeatureLayer, index: int, name: str, request: PlatformRequest
                 ) -> object:
    """El valor del campo numérico ``name`` de la geometría ``index`` de la capa
    (``des.quarry_layer_field`` con los campos que tiene si no es uno numérico suyo)."""
    column = _level_column(layer, LayerField(request.layer, name))
    return layer.values[column][index]


def _layer_number(layer: FeatureLayer, index: int, name: str, request: PlatformRequest) -> float:
    """El número que da el campo ``name`` de la geometría ``index``: ``des.entity_field_value`` (la
    capa, la entidad, el campo y el valor) si falta o no es finito: no se elige ninguno por ella."""
    value = _field_value(layer, index, name, request)
    number_: float | None = None
    if value is not None and not isinstance(value, bool):
        try:
            number_ = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            number_ = None
    if number_ is None or not math.isfinite(number_):
        shown = _NO_VALUE if value is None else value
        raise DesignError("des.entity_field_value", obj=_object(request), field=name, value=shown,
                          layer=request.layer, entity=request.name)
    return number_


def _layer_number_or_none(layer: FeatureLayer, index: int, name: str, request: PlatformRequest
                          ) -> float | None:
    """Como :func:`_layer_number`, pero ``None`` si el campo no tiene valor en esa geometría (la capa no
    da la cota, la pendiente o el ancho y la persona los escribió en el diálogo, T15); un campo que la
    capa no tiene o no es numérico se rechaza igual (``des.quarry_layer_field``)."""
    try:
        return _layer_number(layer, index, name, request)
    except DesignError as error:
        if error.code == "des.entity_field_value":
            return None
        raise


def layer_values(project: StoreProject, fields: PlatformFields, feature: str
                 ) -> dict[PlatformParam, float | None]:
    """Los valores iniciales que da la capa de ``fields`` de su geometría ``feature`` (su nombre o su
    ``fid``): la cota inicial, la pendiente y, de una capa de líneas, el ancho (los de
    :data:`LAYER_FIELDS`), por parámetro; ``None`` el que la geometría no tiene (sin valor en su campo o
    sin campo). Es lo que **propone** el diálogo de «Plataforma…» (T15; RF-015-19: la persona lo corrige
    o lo deja) y no rechaza lo que falta: lo rechaza el cálculo. Solo lee. ``DesignError``
    ``des.entity_feature_unknown`` o ``_ambiguous`` si la capa no tiene esa geometría (o varias llevan
    ese nombre), ``des.quarry_layer_field`` si un campo no es numérico suyo y ``ValueError`` si no es
    una capa de entidades."""
    layer = _layer(project, fields.layer)
    asked = PlatformRequest("Propuesta", fields, feature, "Propuesta")
    index = feature_index(layer, asked, "PLT-001")
    found: dict[PlatformParam, float | None] = {}
    for param, attribute in LAYER_FIELDS.items():
        field = getattr(fields, attribute)
        found[param] = None if field is None else _layer_number_or_none(layer, index, field, asked)
    return found


def _corrected(request: PlatformRequest) -> dict[PlatformParam, float]:
    """Los valores iniciales que la persona corrigió en el diálogo (``PlatformRequest.start_level_m``,
    ``gradient_pct`` y ``width_m``), por parámetro; los que no corrigió, no salen (se leen de la capa)."""
    asked = {PlatformParam.START_LEVEL: request.start_level_m,
             PlatformParam.GRADIENT: request.gradient_pct, PlatformParam.WIDTH: request.width_m}
    return {param: value for param, value in asked.items() if value is not None}


def _linked_axis(layers: Callable[[str], FeatureLayer], layer: FeatureLayer, index: int,
                 request: PlatformRequest) -> tuple[Any, str] | None:
    """El eje que enlaza el campo ``eje`` del polígono: las partes de su línea en la capa de ejes
    (``layers(nombre)``: la del proyecto al preparar, la congelada al reproducir) y su nombre; ``None`` si
    el campo va vacío (sin eje enlazado: el principal, con su aviso). La capa de ejes ha de ser de
    líneas (``des.corridor_not_lines``) y tener esa línea (``des.entity_feature_unknown``)."""
    fields = request.fields
    assert fields.axis_field is not None and fields.axis_layer is not None
    link = _field_value(layer, index, fields.axis_field, request)
    if link is None:
        return None
    axes = layers(fields.axis_layer)
    if axes.kind != "line":
        raise DesignError("des.corridor_not_lines", obj=f"Capa de líneas «{fields.axis_layer}»",
                          field="geometría", value=_KINDS_ES.get(axes.kind, axes.kind),
                          layer=fields.axis_layer)
    wanted = _layer_number(layer, index, fields.axis_field, request)
    if not wanted.is_integer():
        raise DesignError("des.entity_field_value", obj=_object(request), field=fields.axis_field,
                          value=link, layer=request.layer, entity=request.name)
    if int(wanted) not in axes.fids:
        raise DesignError("des.entity_feature_unknown", obj=_object(request),
                          field=fields.axis_field, value=int(wanted), layer=fields.axis_layer)
    at = axes.fids.index(int(wanted))
    return axes.parts[at], _names(axes)[at] or str(axes.fids[at])


def read_geometry(layers: Callable[[str], FeatureLayer], layer: FeatureLayer, index: int,
                  request: PlatformRequest) -> PlatformGeometry:
    """La geometría de la plataforma: la de la capa y, de un polígono con eje enlazado, la de su
    línea (que da ``layers``, :func:`_linked_axis`: la capa de ejes del proyecto al preparar, la
    congelada al reproducir, T14). Una capa de puntos no es de plataformas
    (``des.platform_layer_kind``); un ancho en una capa de polígonos o un enlace en una de líneas son un
    error del programa (``ValueError``: el diálogo no los ofrece)."""
    fields = request.fields
    if layer.kind == "point":
        raise DesignError("des.platform_layer_kind", obj=_object(request), field="geometría",
                          value=_KINDS_ES["point"], layer=request.layer)
    if layer.kind == "polygon" and fields.width_field is not None:
        raise ValueError("una plataforma de polígono no lleva ancho (RF-015-19): su capa "
                         f"«{request.layer}» no tiene campo de ancho")
    if layer.kind == "line" and fields.axis_field is not None:
        raise ValueError("una plataforma de línea no lleva eje enlazado (RF-015-19): su eje es "
                         f"la propia línea de la capa «{request.layer}»")
    parts = layer.parts[index]
    if layer.kind == "polygon" and fields.axis_field is not None:
        linked = _linked_axis(layers, layer, index, request)
        if linked is not None:
            return PlatformGeometry("polygon", parts, axis_parts=linked[0], axis_name=linked[1])
    return PlatformGeometry(layer.kind, parts)


# --- Los parámetros de la entidad ---------------------------------------------------------------


def _default(param: PlatformParam) -> Any:
    return PLATFORM_PARAMS[param.value].default


def entity_values(request: PlatformRequest, code: str, fid: int,
                  from_layer: Mapping[PlatformParam, float], *, line: bool) -> dict[str, Any]:
    """Los parámetros resueltos y comprobados de la entidad, por último segmento de su clave
    (RF-015-08): lo que se pide, lo que sale de la capa (la cota inicial, la pendiente y, de una
    línea, el ancho: ``from_layer``; al recalcular o reproducir, los de la fila de la versión, que ya se
    copiaron de ella) y, de lo que no se pide, el valor por defecto de su parámetro (D-4, D-5, D-7, D-8
    y D-22); sin él, ``des.entity_param_missing`` (no se elige ninguno por la persona). Un número
    fuera de su rango es ``des.entity_param_range``; la pendiente que pasa de la máxima fijada
    (D-6, ``des.platform_max_slope``: es una rampa) y proteger en el modo «en corte y relleno»
    (RF-015-12, ``des.platform_protect_cut_fill``) se rechazan después. Es lo que comparten preparar y
    reproducir (T14: sin proyecto)."""
    mode = request.mode.value if request.mode is not None else _default(PlatformParam.MODE)
    asked: dict[PlatformParam, object] = {
        PlatformParam.NAME: request.name, PlatformParam.LAYER: request.layer,
        PlatformParam.FEATURE: str(fid), PlatformParam.START: request.start,
        PlatformParam.SUPPORT: request.support,
        PlatformParam.WIDTH: from_layer.get(PlatformParam.WIDTH),
        PlatformParam.START_LEVEL: from_layer.get(PlatformParam.START_LEVEL),
        PlatformParam.GRADIENT: from_layer.get(PlatformParam.GRADIENT),
        PlatformParam.MAX_SLOPE: request.max_slope_pct, PlatformParam.MODE: mode,
        PlatformParam.EDGE_ANGLE: request.edge_angle_deg, PlatformParam.REACH: request.reach_m,
        PlatformParam.MESH_FACTOR: (_default(PlatformParam.MESH_FACTOR)
                                    if request.mesh_factor is None else request.mesh_factor),
        PlatformParam.COUNTER_TOL: (_default(PlatformParam.COUNTER_TOL)
                                    if request.counter_tol_m is None else request.counter_tol_m),
        PlatformParam.METRIC: (_default(PlatformParam.METRIC) if request.metric is None
                               else request.metric.value),
        PlatformParam.PROTECT: request.protect, PlatformParam.GUARD: request.guard_m,
        PlatformParam.REASON: request.reason}
    required = {PlatformParam.WIDTH: line, PlatformParam.GUARD: request.protect}
    values: dict[str, Any] = {}
    for param in PlatformParam:
        if param is PlatformParam.SUPPORTS or (param is PlatformParam.WIDTH and not line):
            continue
        checked = check_entity_param(request.name, code, param, asked[param], layer=request.layer,
                                     required=required.get(param))
        if checked is not None:
            values[param.value] = checked
    gradient = values["gradient_pct"]
    maximum = values.get(PlatformParam.MAX_SLOPE.value)
    if maximum is not None and abs(gradient) > maximum:
        raise DesignError("des.platform_max_slope", obj=_object(request),
                          field=request.fields.gradient_field, value=gradient,
                          layer=request.layer, entity=request.name, maximum=maximum)
    if values["protect"] and PlatformMode(values["mode"]) is PlatformMode.CUT_FILL:
        raise DesignError("des.platform_protect_cut_fill", obj=_object(request),
                          field=entity_key(code, PlatformParam.MODE), value=values["mode"],
                          layer=request.layer, entity=request.name)
    return values


def _rows(request: PlatformRequest, code: str, values: Mapping[str, Any],
          fields: Mapping[PlatformParam, str]) -> tuple[EntityParamRow, ...]:
    """Las filas de los parámetros de la entidad con su procedencia: los valores de la capa, con su
    origen «capa X, campo Y, entidad Z»; lo que no se pidió (``request``: modo, factor de malla,
    tolerancia, métrica y no proteger), con la procedencia de su valor por defecto; el resto, lo que
    eligió la persona en el diálogo. ``fields``: el campo de la capa de cada valor que se copia."""
    name, layer = request.name, request.layer
    defaults = {
        PlatformParam.MODE: request.mode is None,
        PlatformParam.MESH_FACTOR: request.mesh_factor is None,
        PlatformParam.COUNTER_TOL: request.counter_tol_m is None,
        PlatformParam.METRIC: request.metric is None,
        PlatformParam.PROTECT: not request.protect}
    rows: list[EntityParamRow] = []
    for param in PlatformParam:
        value = values.get(param.value)
        if value is None:
            continue
        if param in fields:
            source = f"capa «{layer}», campo «{fields[param]}», entidad «{name}»"
            kind = "person"
            reason = (f"Copiado de la capa «{layer}», campo «{fields[param]}», al crear la "
                      f"plataforma «{name}»")
        elif defaults.get(param):
            declared = PLATFORM_PARAMS[param.value]
            source, kind, reason = declared.source, str(declared.source_kind), default_reason(
                declared)
        else:
            source, kind = f"{_DIALOG}, entidad «{name}»", "person"
            reason = f"Elegido al crear la plataforma «{name}»"
        rows.append(EntityParamRow(entity_key(code, param), param, value, source, kind, reason))
    return tuple(rows)


def _kept_numbers(project: StoreProject, version: Version, code: str
                  ) -> dict[PlatformParam, float]:
    """Los valores que se copiaron de la capa (:data:`LAYER_FIELDS`: la cota inicial, la pendiente y el
    ancho) de la entidad ``code``, tal como están **en la versión** (su fila propia, no la del proyecto:
    una versión sin valor propio no tiene el de la entidad); los que no tienen fila, no salen (se leen de la
    capa). Solo lee."""
    store = ParameterStore(project)
    found: dict[PlatformParam, float] = {}
    with project.read() as conn:
        for param in LAYER_FIELDS:
            record = store.get(entity_key(code, param), version=version.uid, conn=conn)
            value = None if record is None else record.value
            if isinstance(value, int | float) and not isinstance(value, bool) \
                    and math.isfinite(float(value)):
                found[param] = float(value)
    return found


def _common(project: StoreProject, version: Version) -> dict[str, float]:
    """Los parámetros del proyecto que lee el cálculo de toda plataforma
    (:data:`~.provenance.PLATFORM_COMMON_PARAMS`: la tolerancia de cara, el umbral de aviso de
    magnitud, el espesor mínimo y el salto creado), como los lee una operación que empezara ahora
    (versión → proyecto, valor por defecto de su definición), sin escribir nada. El salto admitido y
    su porcentaje, fuera de rango: ``des.quarry_param_missing`` o ``_range`` (RF-013-19)."""
    _check_014_params(project, version, provenance.CREATED_STEP_PARAMS)
    keys = provenance.PLATFORM_COMMON_PARAMS
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(
            conn, keys, (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid)
    values: dict[str, object] = {}
    for key in keys:
        resolved = found.get(key)
        declared = definition(key) if resolved is None else None
        values[key] = (resolved.value if resolved is not None
                       else (None if declared is None else declared.default))
    return {key: number(values, key) for key in keys}


# --- La falta de dato (RF-015-09) ---------------------------------------------------------------


def _check_no_data(request: PlatformRequest, code: str, param: PlatformParam, surface: str,
                   role: str, raster: Raster, cells: np.ndarray, window: tuple[slice, slice]
                   ) -> None:
    """RF-015-09: ninguna celda de la huella ``cells`` (de la ventana ``window``) sin dato en la
    superficie ``raster`` (de nombre ``surface``): si no, ``des.entity_nodata`` con la entidad, la
    superficie, su ``role`` (partida o apoyo), el área sin dato (m²) y el centro absoluto de la
    primera celda (de norte a sur y de oeste a este)."""
    grid = raster.grid
    missing = cells & ~np.isfinite(raster.values[window])
    if not missing.any():
        return
    rows, cols = np.nonzero(missing)
    x = float(grid.west + (int(cols[0]) + window[1].start + 0.5) * grid.dx)
    y = float(grid.north - (int(rows[0]) + window[0].start + 0.5) * grid.dy)
    raise DesignError("des.entity_nodata", obj=_object(request), field=entity_key(code, param),
                      value=surface, entity=request.name, area=round(rows.size * grid.cell_area, 2),
                      surface=surface, role=role, x=x, y=y)


def _check_has_data(request: PlatformRequest, code: str, param: PlatformParam, surface: str,
                    role: str, raster: Raster) -> None:
    """Una superficie sin ninguna celda con dato no tiene huella que comprobar (ni cotas con que
    comprobar las de la rasante): ``des.entity_nodata`` con toda la rejilla."""
    if np.isfinite(raster.values).any():
        return
    grid = raster.grid
    full = (slice(0, grid.nrows), slice(0, grid.ncols))
    _check_no_data(request, code, param, surface, role, raster,
                   np.ones(grid.shape, dtype=bool), full)


# --- Preparar ------------------------------------------------------------------------------------


def declared_supports(project: StoreProject, version: Version, code: str) -> tuple[str, ...]:
    """Los códigos de las entidades en las que la persona **declara** que se apoya la entidad ``code`` en
    la versión ``version`` (RF-015-15; ``des.platform.{e}.supports``: códigos separados por comas, sin
    repetir y en el orden en que se declararon; sin fila o vacío, ninguno). Solo lee."""
    return _declared(_declared_row(project, version, code))


def _declared_row(project: StoreProject, version: Version, code: str) -> str | None:
    """El texto de la fila ``des.platform.{e}.supports`` propia de la versión de la entidad ``code``
    (``None`` si no la tiene: la entidad no declara ni ha declarado nada)."""
    record = ParameterStore(project).get(entity_key(code, PlatformParam.SUPPORTS), version=version.uid)
    return None if record is None else ("" if record.value is None else str(record.value))


def _declared(text: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in (text or "").split(",") if part.strip()))


_SUPPORT_MISSING = "no existe en la versión, no está calculada o se descartó"
_SUPPORT_ITSELF = "es la propia entidad"
_SUPPORT_CYCLE = "parte de la superficie de esta entidad, o de lo que ella deja: sería un ciclo"


def _support_inputs(project: StoreProject, version: Version, request: PlatformRequest, code: str,
                    registry: EntityRegistry, support_name: str | None
                    ) -> tuple[tuple[str, ...], tuple[Use, ...], bool]:
    """Las entradas ``supported_on`` que la plataforma ``code`` **ya** tiene al prepararla, sin esperar al
    resultado (RF-015-15; T23): los datos de las superficies en las que se apoya —la de apoyo de la petición
    (``support_name``) y las que declara la persona (:func:`declared_supports`), cada una **con la tabla de su
    huella**, ``support_footprint``, que es lo que permite reproducir lo apoyado sin el proyecto— como
    ``(superficies, tablas)`` (los nombres de los datos, que :func:`~.provenance.platform_inputs` anota, y las
    entradas de las tablas). Una declarada que no existe, no está calculada, se descartó, es ella misma o
    parte de ella (un ciclo) se rechaza: ``des.entity_supports_unknown``, sin escribir nada. El tercer valor
    dice si la entidad tiene la fila ``supports`` en la versión: solo entonces la operación **lee** ese
    parámetro (``begin_operation`` crearía en el proyecto una fila «sin confirmar» por cada entidad que no
    declara nada: trampa de la T04) y cambiar lo declarado la deja obsoleta (RF-015-16)."""
    row = _declared_row(project, version, code)
    declared = _declared(row)
    with project.read() as conn:
        found = entity_surfaces(conn, registry)
    skip = _unsupportable(registry, code, ())
    names = [] if support_name is None else [support_name]
    tables: list[Use] = []
    for target in declared:
        where = found.get(target)
        if where is None or target in skip:
            reason = (_SUPPORT_ITSELF if target == code else _SUPPORT_CYCLE if where is not None
                      else _SUPPORT_MISSING)
            raise DesignError("des.entity_supports_unknown", obj=_object(request),
                              field=entity_key(code, PlatformParam.SUPPORTS), value=", ".join(declared),
                              entity=request.name, target=target, reason=reason, version=version.code)
        names.append(where.surface)
        tables.append(Use(where.table, provenance.SUPPORT_FOOTPRINT_ROLE))
    for where in found.values():  # la de apoyo de la petición, si es la de una entidad
        if support_name is not None and where.surface == support_name and where.code not in skip:
            tables.append(Use(where.table, provenance.SUPPORT_FOOTPRINT_ROLE))
    return tuple(dict.fromkeys(names)), tuple(dict.fromkeys(tables)), row is not None


def _surfaces(project: StoreProject, version: Version, request: PlatformRequest, code: str,
              registry: EntityRegistry, masks: access.MaskSet
              ) -> tuple[str, Raster, str | None, Raster | None]:
    """El dato y la rejilla de la superficie de partida y, si se pide, los de la de apoyo, leídos
    tal como están en su fichero y comparados con la rejilla del proyecto (RF-011-02, RF-011-03: ni
    se remuestrean ni se interpolan) y con la de las máscaras."""
    frame = project_frame(project)
    start = _surface_dataset(registry, version, request, code, PlatformParam.START, request.start)
    found = read_surface(project, start, version_uid=version.uid, expect=frame,
                         role="superficie de partida")
    support = rest = None
    if request.support is not None:
        support = _surface_dataset(registry, version, request, code, PlatformParam.SUPPORT,
                                   request.support)
        rest = read_surface(project, support, version_uid=version.uid, expect=frame,
                            role="superficie de apoyo")
    if not found.grid.same_geometry(masks.grid):
        raise ValueError("la rejilla de las máscaras no es la del proyecto")
    return start, found, support, rest


def _pending_zone(job: PlatformJob, footprint: Footprint, values: Mapping[str, Any]
                  ) -> Generator[None, None, np.ndarray]:
    """La zona de la ventana de trabajo donde la plataforma puede mover algo (RF-015-07): su huella
    y lo que alcanza su borde (las celdas a ≤ alcance de la huella con la métrica de la entidad)
    donde las máscaras admiten el corte o el relleno. Es lo que pueden mover el cálculo; una celda
    que ninguna máscara deja mover no cuenta."""
    window, grid = footprint.window, job.grid
    origin = np.where(footprint.cells, 0.0, np.nan)
    distance = yield from _drain(reach_steps(
        origin, _window_grid(grid, window), float(values["reach_m"]), Metric(values["metric"]),
        name=f"{job.request.name} (alcance)"))
    movable = np.isfinite(distance) & (job.cut_allowed[window] | job.fill_allowed[window])
    return footprint.cells | movable


def prepare_platform_units(project: StoreProject, request: PlatformRequest, version: Version,
                           masks: access.MaskSet, *, code: str | None = None,
                           supersedes: str | None = None, insert_before: str | None = None
                           ) -> Generator[None, None, PreparedPlatform]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan la
    plataforma ``request`` de la versión editable ``version`` con sus ``masks`` ya al día
    (:func:`~.store.masks_steps`; RF-015-06): el nombre único y el código (``code``: el de una entidad
    que ya está en la versión, que no choca consigo misma; si no, el siguiente, ``PLT-001``), la
    partida y la cadena, la capa con su geometría y sus campos, los parámetros resueltos, las
    superficies de partida y de apoyo, la huella (que comprueba la geometría), la falta de dato, los
    sectores con la búsqueda pendiente y lo que anotará la operación. ``supersedes``: la operación hecha
    a la que sustituye (un recálculo). ``insert_before`` (spec 015, T12; RF-015-05): la entidad que
    hoy parte de la misma superficie y que pasará a partir de la de la nueva (una inserción: sin ello,
    esa superficie ocupada se rechaza). Devuelve la :class:`PreparedPlatform`. **Nada se escribe**;
    los rechazos salen al avanzar, en este orden: versión (``VersionError``), nombre y partida
    (``des.entity_name_repeated``, ``des.entity_start_taken``, ``des.entity_chain_cycle``), capa y
    geometría (``des.entity_feature_unknown`` y ``_ambiguous``, ``des.quarry_layer_field``,
    ``des.entity_field_value``, ``des.platform_layer_kind``), parámetros (``des.entity_param_*``,
    ``des.platform_max_slope``, ``des.platform_protect_cut_fill``), superficies
    (``des.entity_start_unknown``, ``des.surface_*``, ``gis.dataset_unknown``), la geometría y las
    cotas (``platform_footprint``: ``des.platform_*``), la falta de dato (``des.entity_nodata``) y
    un sector pendiente (``des.sector_pending``) o el nombre de un dato
    (``des.operation_name_repeated``)."""
    require_version(project, version.uid, provenance.PLATFORM)
    chosen, registry = _identify(project, version, request, code)
    _check_chain(registry, request, chosen, insert_before)
    yield
    layer = _layer(project, request.layer)
    index = feature_index(layer, request, chosen)
    line = layer.kind == "line"
    geometry = read_geometry(lambda name: _layer(project, name), layer, index, request)
    fields = request.fields
    kept = {} if code is None else _kept_numbers(project, version, chosen)
    corrected = _corrected(request)
    from_layer: dict[PlatformParam, float] = {}
    layer_fields: dict[PlatformParam, str] = {}
    for param, attribute in LAYER_FIELDS.items():
        field = getattr(fields, attribute)
        if field is not None:  # sin campo (un polígono no tiene ancho): el valor no sale de la capa
            # Una entidad que ya está en la versión (recalcularla, o la que dejó «Traer…») tiene ya sus
            # valores de la capa como parámetros, con su historial (P-3): manda su fila, no la capa.
            if param in kept:
                from_layer[param], layer_fields[param] = kept[param], field
                continue
            asked = corrected.get(param)
            if asked is None:
                from_layer[param], layer_fields[param] = _layer_number(
                    layer, index, field, request), field
                continue
            # Lo que corrige el diálogo manda sobre la capa y se copia con su origen; si es igual al de la
            # capa, conserva el origen de la capa.
            from_layer[param] = asked
            if _layer_number_or_none(layer, index, field, request) == asked:
                layer_fields[param] = field
    fid = layer.fids[index]
    values = entity_values(request, chosen, fid, from_layer, line=line)
    yield
    start_name, start_raster, support_name, support_raster = _surfaces(
        project, version, request, chosen, registry, masks)
    _check_has_data(request, chosen, PlatformParam.START, start_name, _START_ROLE, start_raster)
    yield
    job = PlatformJob(request, chosen, masks.grid, start_raster.values, geometry, values,
                      admitted(masks, BenchSense.CUT), admitted(masks, BenchSense.FILL))
    footprint = platform_footprint(job)
    yield
    _check_no_data(request, chosen, PlatformParam.START, start_name, _START_ROLE, start_raster,
                   footprint.cells, footprint.window)
    if support_raster is not None and support_name is not None:
        _check_no_data(request, chosen, PlatformParam.SUPPORT, support_name, _SUPPORT_ROLE,
                       support_raster, footprint.cells, footprint.window)
    sectors = design_sectors(project, version.uid)
    if any(item.pending for item in sectors):
        zone = yield from _pending_zone(job, footprint, values)
        refs, labels = sector_layout(project, masks)
        touched = pipeline.touched_in(refs, labels[footprint.window], zone)
        refuse_pending(item for item in sectors if item.code in touched)  # RF-015-07
    yield
    common = _common(project, version)
    supported, footprints, reads = _support_inputs(project, version, request, chosen, registry,
                                                   support_name)
    inputs = provenance.platform_inputs(request, start_name, masks.uses(), supported)
    inputs = (*inputs, *(use for use in footprints if use not in inputs))
    begun = _start(project, provenance.PLATFORM, request.name, version, masks,
                   provenance.platform_settings(request, chosen), inputs,
                   provenance.platform_params(chosen, request, supports=reads), supersedes)
    yield
    rows = _rows(request, chosen, values, layer_fields)
    return PreparedPlatform(job, footprint, begun, chosen, fid, rows, MappingProxyType(common),
                            start_name, support_name, code is not None)


def prepare_platform(project: StoreProject, request: PlatformRequest, *, version: str | None,
                     masks: access.MaskSet | None = None, code: str | None = None,
                     supersedes: str | None = None) -> OperationStart:
    """Lo que anotará ``des.platform`` para ``request`` en la versión ``version`` (uid o código)
    cuando se confirme, sin escribir nada (salvo compilar las máscaras si no están al día, que es una
    operación propia): los ajustes de ``provenance.platform_settings``, las entradas de
    ``platform_inputs`` (la capa, la de su eje, la superficie de partida, las máscaras de la versión
    —``masks``; sin ellas, las de ``access.ensure_masks_steps``— y la superficie de apoyo) y los
    parámetros que lee (``platform_params``). Es la preparación entera de
    :func:`prepare_platform_units` (que da además el ``PlatformJob``) de una vez.

    Rechazos, todos **sin escribir nada** y nombrando la capa, la entidad, el campo y el valor: los de
    :func:`~.store.require_version` (RF-009-21: sin versión activa, desconocida o no editable),
    ``MaskError`` si las máscaras que se dan ya no están al día y los de
    :func:`prepare_platform_units`."""
    found = require_version(project, version, provenance.PLATFORM)
    loaded = _loaded_masks(project, found, masks)
    prepared: PreparedPlatform = _result_of(prepare_platform_units(
        project, request, found, loaded, code=code, supersedes=supersedes))
    return prepared.start


# --- Escribir los parámetros --------------------------------------------------------------------


def set_entity_params(project: StoreProject, rows: Iterable[EntityParamRow], *, version: str,
                      decided_by: str | None = None, decided_at: Any = None,
                      conn: sqlite3.Connection | None = None) -> tuple[ParameterRecord, ...]:
    """Escribe ``rows`` (``PreparedPlatform.rows``) como **parámetros de la versión** ``version`` (uid
    o código): una fila nueva por parámetro, ADOPTADO, con su origen y su clase, el decisor
    ``decided_by`` (por defecto, quien tiene abierto el proyecto), la fecha de la decisión
    (``decided_at``; sin ella, ahora) y su motivo (RF-008-01, RF-009-29). Es un paso **explícito**:
    un cálculo no cambia parámetros por su cuenta (ADR-0025 §5) y ``prepare_platform`` no escribe;
    lo llama quien crea la entidad, **antes** de abrir la operación, para que ``begin_operation`` lea
    todos de la versión (también los de los valores por defecto: sin su fila, los crearía en el
    proyecto; trampa de la T04). Con ``conn`` (la transacción de quien llama, la del ``commit``), en
    ella; si no, en una propia. Devuelve las filas escritas. ``ParamError`` ``core.param_exists`` si
    la entidad ya tiene alguna (no se pisa nada), ``VersionError`` si la versión no se edita."""
    items = tuple(rows)
    store = ParameterStore(project)
    who = decided_by or project.session.user_host

    def write(target: sqlite3.Connection) -> tuple[ParameterRecord, ...]:
        return tuple(store.create(
            target, row.key, row.value, kind=PLATFORM_PARAMS[row.param.value].kind,
            source=row.source, source_kind=row.source_kind, decided_by=who,
            decided_at=decided_at, reason=row.reason, version=version) for row in items)

    if conn is not None:
        return write(conn)
    with project.write_transaction() as writing:
        return write(writing)


# --- Calcular (spec 015, T12; RF-015-03, RF-015-29) ---------------------------------------------

_COMPUTE_PHASE = "platform_compute"


def platform_compute_steps(job: PlatformJob, common: Mapping[str, object], *,
                           footprint: Footprint | None = None,
                           confirm_counterslope: bool = False, previous: Previous | None = None,
                           operation: str = "", quarry: QuarryOrder | None = None,
                           budget_s: float = STEP_BUDGET_S
                           ) -> Generator[Progress, None, PlatformOutcome]:
    """Los pasos que calculan la plataforma de ``job`` (RF-015-03, RF-015-29; plan 015 §5.3.1: el
    ``platform_compute_steps`` que **comparten «Calcular», el recálculo y la reproducción**), sin
    proyecto y sin escribir nada (``yield from``; cerrar el generador no deja nada): la huella y la
    rasante (``footprint``, si ya se calculó al preparar; si no, aquí), aplicarla
    (``apply_platform_steps``), el borde (``platform_edge_steps``) y el perfil con las cifras y los
    avisos (``platform_outcome``), por pasos de ``budget_s`` como mucho. ``common`` son los parámetros del
    proyecto que lee el cálculo (``provenance.PLATFORM_COMMON_PARAMS``: la tolerancia de cara, el umbral de
    magnitud, el espesor mínimo y el salto creado, ya resueltos). ``confirm_counterslope``, ``previous``
    (con qué se compara la magnitud), ``operation`` (el nombre que da la nota de que no hay con qué
    compararla) y ``quarry`` (la otra superficie de la cantera, RF-015-14) son los de
    ``platform.platform_outcome``. Los rechazos son los de esas funciones y salen al avanzar. La huella
    y el perfil no se parten (7 ms una línea de 300 m, 37 ms 1,2 M celdas): son una unidad cada uno.
    Devuelve el :class:`~.platform.PlatformOutcome`."""
    name = job.request.name
    yield Progress(_COMPUTE_PHASE, 0, 1, f"Calculando la plataforma «{name}»…")
    if footprint is None:
        footprint = platform_footprint(job)
        yield Progress(_COMPUTE_PHASE, 0, 1, f"Huella de la plataforma «{name}» calculada")
    applied = yield from pipeline.forward(apply_platform_steps(job, footprint, budget_s=budget_s))
    edge = yield from pipeline.forward(
        platform_edge_steps(job, footprint, applied, common, budget_s=budget_s))
    yield Progress(_COMPUTE_PHASE, 1, 1, f"Perfil de la plataforma «{name}»…")
    return platform_outcome(job, footprint, applied, edge, common,
                            confirm_counterslope=confirm_counterslope, previous=previous,
                            operation=operation, quarry=quarry)


def compute_platform_steps(writer: DesignWriter, prepared: PreparedPlatform, *,
                           confirm_counterslope: bool = False, previous: Previous | None = None,
                           operation: str = "", quarry: QuarryOrder | None = None,
                           budget_s: float = STEP_BUDGET_S
                           ) -> Generator[Progress, None, PlatformOutcome]:
    """Lo que hace «Calcular» sobre el ``writer`` (spec 015, T12 y T13; RF-015-03, RF-015-29): calcula la
    plataforma preparada (:func:`platform_compute_steps`, con la huella de ``prepared`` y los
    parámetros del proyecto que lee), deja su superficie —la de partida, entera, con el resultado en
    la ventana de la huella— en el temporal de ``writer`` (``des_psf_``, con su hash) y prepara, con su
    hash en memoria, la tabla de la entidad (``des_epr_``, :func:`platform_entity_rows`) y su informe
    (``des_prp_``, :func:`platform_report_rows`), **sin confirmar**: lo que falta para crearla
    (:func:`create_platform`, T13) es una sola transacción. Devuelve el
    :class:`~.platform.PlatformOutcome`."""
    outcome = yield from platform_compute_steps(
        prepared.job, prepared.common, footprint=prepared.footprint,
        confirm_counterslope=confirm_counterslope, previous=previous, operation=operation,
        quarry=quarry, budget_s=budget_s)
    surface = np.array(prepared.job.start, dtype=np.float64, copy=True)
    surface[outcome.footprint.window] = outcome.result
    raster = Raster(prepared.job.grid, surface, writer.crs, writer.vertical)
    yield from pipeline.forward(_store_steps(
        writer.grid_steps(provenance.ENTITY_SURFACE_GRID, raster), budget_s,
        "la superficie de la plataforma"))
    entity = platform_entity_rows(prepared.job, outcome, fid=prepared.fid,
                                  start_surface=prepared.start_surface,
                                  support_surface=prepared.support_surface)
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.ENTITY_TABLE, entity), budget_s,
        "la tabla de la plataforma"))
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.ENTITY_REPORT_TABLE, platform_report_rows(outcome)),
        budget_s, "el informe de la plataforma"))
    return outcome


# --- Las tablas de la entidad (spec 015, T13; RF-015-01, RF-015-02) -----------------------------

_OUTSIDE_NOTICES = frozenset({
    "des.magnitude_cut", "des.magnitude_fill", "des.magnitude_no_reference",
    "des.entity_quarry_order"})
"""Los avisos del resultado que **no** van al informe ``des_prp_``: dependen de algo que la operación no
consume —la revisión congelada anterior con que se compara la magnitud y la otra superficie de la
cantera— y el informe se reproduce sin el proyecto (RF-015-02: bit a bit desde lo congelado). El
resumen de «Calcular» sí los lleva."""


def _json(value: object) -> str:
    """``value`` como JSON compacto y estable (``allow_nan`` falso: nada que no sea finito)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def footprint_runs(cells: np.ndarray, window: tuple[slice, slice]
                   ) -> list[tuple[int, int, int]]:
    """La huella ``cells`` (booleana, de la forma de su ventana de trabajo ``window``) en **tramos de
    fila** ``(fila, col0, col1)`` de la **rejilla entera**: la fila y las columnas absolutas, ``col1``
    excluida (como un ``slice``), de norte a sur y de oeste a este. Es lo que guarda ``des_epr_``
    (``footprint``) y de lo que salen la zona declarada, el cargador y la capa de entidades; sin bucle
    por celda (los inicios y finales de cada tramo salen de la diferencia de cada fila).
    ``ValueError`` (error del programa) si ``cells`` no es de la forma de la ventana."""
    mask = np.asarray(cells, dtype=bool)
    rows, cols = window
    if mask.ndim != 2 or mask.shape != (rows.stop - rows.start, cols.stop - cols.start):
        raise ValueError(f"la huella es de la forma de su ventana "
                         f"({rows.stop - rows.start}, {cols.stop - cols.start}), no {mask.shape}")
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    edges = np.diff(padded, axis=1)
    first_rows, first = np.nonzero(edges == 1)
    _last_rows, last = np.nonzero(edges == -1)  # una por inicio y en el mismo orden
    return [(int(row) + rows.start, int(start) + cols.start, int(stop) + cols.start)
            for row, start, stop in zip(first_rows, first, last, strict=True)]


def runs_mask(runs: Iterable[Sequence[int]], shape: tuple[int, int]) -> np.ndarray:
    """La máscara booleana de la rejilla entera (``shape``: filas y columnas) que dicen los tramos
    ``runs`` de :func:`footprint_runs` (``(fila, col0, col1)`` absolutos, ``col1`` excluida): la huella
    de una entidad leída de su tabla. ``ValueError`` si un tramo no cabe en la rejilla o no tiene celdas."""
    height, width = shape
    found = np.zeros(shape, dtype=bool)
    for run in runs:
        row, first, last = (int(value) for value in run)
        if not (0 <= row < height and 0 <= first < last <= width):
            raise ValueError(f"el tramo ({row}, {first}, {last}) no cabe en una rejilla de "
                             f"{height} × {width} celdas")
        found[row, first:last] = True
    return found


def geometry_sha256(geometry: PlatformGeometry) -> str:
    """El hash de la geometría de origen de una plataforma (SHA-256 en hexadecimal; RF-015-01): su tipo,
    el número de sus partes y de sus caminos y los vértices **tal cual** (X e Y absolutas en float64,
    ``<f8``: el último bit cuenta) y, de un polígono con eje enlazado, los de su eje. Lo que guarda
    ``des_epr_`` (``geometry_sha256``) para saber si la geometría de la capa es la de la entidad."""
    digest = hashlib.sha256()

    def feed(tag: str, parts: Sequence[Sequence[np.ndarray]]) -> None:
        digest.update(f"{tag}:{len(parts)};".encode())
        for part in parts:
            digest.update(f"part:{len(part)};".encode())
            for path in part:
                array = np.ascontiguousarray(path, dtype="<f8")
                digest.update(f"path:{array.shape[0]};".encode())
                digest.update(array.tobytes())

    feed(geometry.kind, geometry.parts)
    if geometry.axis_parts is not None:
        feed("axis", geometry.axis_parts)
    return digest.hexdigest()


def platform_entity_rows(job: PlatformJob, outcome: PlatformOutcome, *, fid: int,
                         start_surface: str, support_surface: str | None) -> list[Row]:
    """La fila de ``des_epr_`` (columnas de :data:`~.store.ENTITY_COLUMNS`) de la plataforma de ``job``
    con su ``outcome`` (RF-015-01): **una**, con los atributos de la entidad —su código, su nombre, su
    tipo, los datos de su superficie de partida (``start_surface``) y de apoyo, la capa y el ``fid`` de
    su geometría de origen y el hash de esa geometría (:func:`geometry_sha256`), el modo y las celdas de
    su huella—, su ventana de trabajo, la huella en tramos de fila (:func:`footprint_runs`) y los
    vértices de su eje (absolutos, float64, exactos). Solo depende de lo que se lee para calcular, no del
    proyecto: lo repite la reproducción desde lo congelado."""
    footprint = outcome.footprint
    window = footprint.window
    mode = PlatformMode(job.values.get(PlatformParam.MODE.value,
                                       _default(PlatformParam.MODE))).value
    runs = footprint_runs(footprint.cells, window)
    return [(job.code, job.request.name, EntityKind.PLATFORM.value, start_surface, support_surface,
             job.request.layer, int(fid), geometry_sha256(job.geometry), mode,
             footprint.cell_count, int(footprint.axis.principal),
             _json([int(window[0].start), int(window[0].stop), int(window[1].start),
                    int(window[1].stop)]),
             _json([list(run) for run in runs]),
             _json([[x, y] for x, y in footprint.axis.vertices]))]


def _place(x: float | None, y: float | None, what: str) -> str | None:
    """El lugar absoluto ``x;y`` de una cifra (float64 en texto, como el de la 013 y la 014), o
    ``None`` sin él."""
    if x is None or y is None:
        return None
    return f"{_real(f'{what}.x', x)!r};{_real(f'{what}.y', y)!r}"


def platform_report_rows(outcome: PlatformOutcome) -> list[Row]:
    """Las filas de ``des_prp_`` (``quantity, value, unit_code, note``, formato largo como ``des_rpt_`` y
    ``des_qrp_``) de la plataforma ``outcome`` (RF-015-02, RF-015-13, RF-015-23, RF-015-24), en este
    orden: lo de la huella (área, celdas, longitudes del eje y de la huella, las cotas y la pendiente de la
    rasante); lo aplicado (corte y relleno, celdas, lo que las máscaras no dejan mover, lo que no queda en
    la rasante y lo que no se mueve) con una fila por grupo de celdas por encima o por debajo
    (``off_level_above`` y ``off_level_below``) y por grupo de lo que no se mueve (``held_group``), con su
    número, causa, celdas, área y lugar en la nota (JSON); el borde (su ángulo, factor de malla, alcance y
    límite, su corte y relleno, las celdas movidas, las que no se mueven, las más empinadas y las que llegan
    al borde de la rejilla o a celdas sin dato, la altura de su pared con su lugar y una fila ``edge_wall`` por
    causa); el salto creado de la 014 (``created_*``, con una fila ``created_stretch`` por tramo); el perfil
    longitudinal (la tolerancia, los tramos con contrapendiente y la diferencia máxima, una fila ``profile``
    por tramo de una celda de abscisa y una fila ``counter_slope`` por cada uno que pasa de la tolerancia); y,
    al final, los avisos y notas (``warning`` y ``note``, con su código y sus valores en JSON) menos los de
    :data:`_OUTSIDE_NOTICES`. Un valor que no es un número finito es un error del programa
    (``ValueError``): nada se escribe. Solo depende del resultado: lo repite la reproducción."""
    footprint, applied, edge, profile = (outcome.footprint, outcome.applied, outcome.edge,
                                         outcome.profile)
    rows: list[Row] = []

    def scalar(key: str, value: float, unit: str, note: str | None = None) -> None:
        rows.append((key, _real(key, value), unit, note))

    for key, value, unit in (
            ("area_m2", footprint.area_m2, "m2"), ("footprint_cells", footprint.cell_count, "-"),
            ("axis_m", footprint.axis.length_m, "m"), ("footprint_m", footprint.length_m, "m"),
            ("start_level_m", footprint.start_level_m, "m"),
            ("end_level_m", footprint.end_level_m, "m"),
            ("gradient_pct", footprint.gradient_pct, "%"),
            ("cut_m3", applied.cut_m3, "m3"), ("fill_m3", applied.fill_m3, "m3"),
            ("cut_cells", applied.cut_cells, "-"), ("fill_cells", applied.fill_cells, "-"),
            ("blocked_cells", applied.blocked_cells, "-"),
            ("blocked_area_m2", applied.blocked_area_m2, "m2"),
            ("off_level_area_m2", outcome.off_level_area_m2, "m2"),
            ("off_level_max_m", outcome.off_level_max_m, "m"),
            ("held_cells", outcome.held_cells, "-"), ("held_area_m2", outcome.held_area_m2, "m2")):
        scalar(key, value, unit)
    for side, groups in (("above", applied.above), ("below", applied.below)):
        for item in groups:
            scalar(f"off_level_{side}", item.max_m, "m", _json({
                "group": item.group, "cause": item.cause.value, "cells": item.cells,
                "area_m2": _real("off_level.area_m2", item.area_m2),
                "x": _real("off_level.x", item.x), "y": _real("off_level.y", item.y)}))
    for group in outcome.held_groups:
        scalar("held_group", group.area_m2, "m2", _json({
            "group": group.group, "cells": group.cells, "footprint_cells": group.footprint_cells,
            "edge_cells": group.edge_cells, "x": _real("held_group.x", group.x),
            "y": _real("held_group.y", group.y)}))
    for key, value, unit in (
            ("edge_angle_deg", edge.angle_deg, "deg"), ("edge_mesh_factor", edge.mesh_factor, "-"),
            ("edge_reach_m", edge.reach_m, "m"), ("edge_limit_deg", edge.limit_deg, "deg"),
            ("edge_cut_m3", edge.cut_m3, "m3"), ("edge_fill_m3", edge.fill_m3, "m3"),
            ("edge_cut_cells", edge.cut_cells, "-"), ("edge_fill_cells", edge.fill_cells, "-"),
            ("edge_changed_cells", edge.changed_cells, "-"),
            ("edge_held_cells", edge.held_cells, "-"),
            ("edge_held_area_m2", edge.held_area_m2, "m2"),
            ("edge_steep_cells", edge.steep_cells, "-"),
            ("edge_outside_cells", edge.outside_cells, "-"),
            ("edge_outside_area_m2", edge.outside_area_m2, "m2")):
        scalar(key, value, unit)
    scalar("edge_wall_max_m", edge.wall_max_m, "m", _place(edge.wall_x, edge.wall_y, "edge_wall"))
    for wall in edge.walls:
        scalar("edge_wall", wall.max_deg, "deg", _json({
            "cause": wall.cause.value, "cells": wall.cells,
            "area_m2": _real("edge_wall.area_m2", wall.area_m2),
            "x": _real("edge_wall.x", wall.x), "y": _real("edge_wall.y", wall.y)}))
    created = edge.created
    for key, value, unit in (
            ("created_pairs", created.pairs, "-"), ("created_over_pairs", created.over, "-"),
            ("created_over_pct", created.over_pct, "%"),
            ("created_within_pct", created.within_pct, "%")):
        scalar(key, value, unit)
    scalar("created_step_max_m", created.maximum_m, "m", _place(created.x, created.y, "created_step"))
    for key, value, unit in (("created_threshold_m", created.threshold_m, "m"),
                             ("created_min_share_pct", created.min_share_pct, "%"),
                             ("created_min_thickness_m", created.min_thickness_m, "m")):
        scalar(key, value, unit)
    for stretch in created.stretches:
        scalar("created_stretch", stretch.maximum_m, "m", _json({
            "stretch": stretch.stretch, "pairs": stretch.pairs,
            "x": _real("created_stretch.x", stretch.x),
            "y": _real("created_stretch.y", stretch.y)}))
    scalar("counter_tolerance_m", profile.tolerance_m, "m")
    scalar("counter_sections", profile.counter_sections, "-")
    scalar("profile_spread_m", profile.spread_m, "m")
    for index in range(profile.section.size):
        where = {"section": int(profile.section[index]),
                 "chainage_m": _real("profile.chainage_m", profile.chainage_m[index]),
                 "x": _real("profile.x", profile.x[index]),
                 "y": _real("profile.y", profile.y[index])}
        scalar("profile", profile.level_m[index], "m",
               _json({**where, "rise_m": _real("profile.rise_m", profile.rise_m[index])}))
    for index in np.flatnonzero(profile.flagged):
        scalar("counter_slope", profile.rise_m[index], "m", _json({
            "section": int(profile.section[index]),
            "chainage_m": _real("counter_slope.chainage_m", profile.chainage_m[index]),
            "x": _real("counter_slope.x", profile.x[index]),
            "y": _real("counter_slope.y", profile.y[index])}))
    for notice in outcome.notices:
        if notice.code not in _OUTSIDE_NOTICES:
            rows.append((notice.severity, None, None, _notice_text(notice)))
    return rows


# --- Crear (spec 015, T13; RF-015-01, RF-015-02, RF-015-04) -------------------------------------


_SUPPORTABLE = frozenset({EntityState.CURRENT, EntityState.STALE, EntityState.SUPPORT_REMOVED})
"""Los estados de una entidad **en la que se puede apoyar** algo (RF-015-15): tiene operación vigente y su
superficie existe (RF-015-25). Una «sin calcular» no tiene superficie y una «descartada» ya no es de la
versión."""
_SUPPORT_DATA = (
    "SELECT io.operation_uid, io.role, d.name, d.locator FROM gb_operation_io AS io "
    "JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.direction = 'out' AND io.item_kind = ? "
    "AND io.role IN (?, ?) AND io.operation_uid IN ({marks})")


@dataclass(frozen=True, slots=True)
class EntitySurface:
    """Lo que hace falta de una entidad viva y calculada para apoyar algo en ella (RF-015-15, plan 015 A6):
    su ``code``, el nombre del dato de su superficie (``surface``, ``des_psf_``), el de su tabla (``table``,
    ``des_epr_``) y la ubicación de esa tabla (``locator``) con su huella."""

    code: str
    surface: str
    table: str
    locator: str


def entity_surfaces(conn: sqlite3.Connection, registry: EntityRegistry, *,
                    skip: Iterable[str] = ()) -> dict[str, EntitySurface]:
    """Las entidades de ``registry`` en las que se puede apoyar algo (:data:`_SUPPORTABLE`), salvo las de
    ``skip``, cada una con su superficie y su tabla vigentes (las que escribió su operación vigente), por
    código. Una consulta por cada 400 entidades. Solo lee."""
    omitted = set(skip)
    live = {entry.operation_uid: entry.record.code for entry in registry
            if entry.operation_uid is not None and entry.record.state in _SUPPORTABLE
            and entry.record.code not in omitted}
    found: dict[str, dict[str, tuple[str, str]]] = {}
    uids = sorted(live)
    for first in range(0, len(uids), 400):
        part = uids[first:first + 400]
        sql = _SUPPORT_DATA.format(marks=", ".join("?" for _ in part))
        for uid, role, name, locator in conn.execute(
                sql, (DATASET, provenance.ENTITY_SURFACE_ROLE, provenance.ENTITY_ROLE, *part)):
            found.setdefault(live[str(uid)], {})[str(role)] = (str(name), str(locator))
    result: dict[str, EntitySurface] = {}
    for code in sorted(found, key=entities.code_order):
        data = found[code]
        surface, table = data.get(provenance.ENTITY_SURFACE_ROLE), data.get(provenance.ENTITY_ROLE)
        if surface is not None and table is not None:
            result[code] = EntitySurface(code, surface[0], table[0], table[1])
    return result


def _unsupportable(registry: EntityRegistry, own_code: str | None, written: Collection[str]) -> set[str]:
    """Las entidades en las que una operación **no** se apoya (RF-015-15): ella misma si es una entidad
    (``own_code``) y las que parten de su superficie, aguas abajo de la cadena; y, de una operación que no
    es una entidad, las que parten de alguna de las superficies que escribe (``written``) y las que les
    siguen: apoyarse en ellas sería un ciclo en el grafo."""
    records = registry.records
    skip: set[str] = set()
    if own_code is not None:
        skip.add(own_code)
        if entities.find_entity(records, own_code) is not None:
            skip |= {item.code for item in entities.chain_of(records, own_code)}
    for item in records:
        if item.start is not None and item.start in written:
            skip |= {other.code for other in entities.chain_of(records, item.code)}
    return skip


@dataclass(frozen=True, slots=True)
class SupportSurvey:
    """Lo que apoya una operación sobre las entidades de su versión (:func:`survey_supports`): los
    ``supports`` (los detectados y los que ya eran entradas suyas, por orden de código) y, de cada entidad
    de ellos, su superficie y su tabla (``surfaces``)."""

    supports: tuple[entities.Support, ...] = ()
    surfaces: Mapping[str, EntitySurface] = MappingProxyType({})

    @property
    def volumes(self) -> dict[str, float]:
        """El volumen apoyado (m³) en cada entidad de ``supports``, por su código."""
        return {item.code: item.volume_m3 for item in self.supports}

    def uses(self, have: Iterable[tuple[str, str]] = ()) -> tuple[Use, ...]:
        """Las entradas que la operación ha de anotar por cada entidad de ``supports`` —su superficie con el
        papel ``supported_on`` y su tabla con el ``support_footprint``, con la que se reproduce lo apoyado— y
        que aún no tiene (``have``: pares ``(dato, papel)`` de sus entradas)."""
        held = set(have)
        found: list[Use] = []
        for item in self.supports:
            where = self.surfaces[item.code]
            for name, role in ((where.surface, provenance.SUPPORTED_ON_ROLE),
                               (where.table, provenance.SUPPORT_FOOTPRINT_ROLE)):
                if (name, role) not in held:
                    found.append(Use(name, role))
                    held.add((name, role))
        return tuple(found)

    def figures(self, name: str) -> tuple[Any, ...]:
        """Las cifras ``des.supported_m3`` de la operación ``name`` (una por entidad apoyada)."""
        return provenance.supported_figures(name, self.volumes)


def survey_supports(project: StoreProject, version: Version, results: Sequence[np.ndarray], start: str, *,
                    own_code: str | None = None, written: Collection[str] = (),
                    inputs: Iterable[tuple[str, str]] = (), start_values: np.ndarray | None = None
                    ) -> SupportSurvey:
    """**Lo que apoya una operación sobre las entidades de su versión** (spec 015, T23; RF-015-15, D-11;
    plan 015 A6): la operación que deja las superficies ``results`` (``(filas, columnas)`` en la rejilla del
    proyecto) desde la de partida ``start`` (el nombre del dato; ``start_values`` si ya está leída) se apoya
    en cada entidad viva y calculada de ``version`` (:data:`_SUPPORTABLE`) en cuya huella rellena más del
    espesor mínimo de la 012 por encima de ``máx(partida, entidad)`` (:func:`~.entities.detect_supports`,
    con el volumen), y en las que ya lo eran (``inputs``: los pares ``(dato, papel)`` de lo que consume; las
    que declara la persona, la de apoyo de la petición y las que arrastra un recálculo) **aunque no apoye
    nada**. No se apoya en sí misma (``own_code``) ni en lo que parte de ella o de lo que escribe
    (``written``: los datos de sus superficies; :func:`_unsupportable`). De varias superficies (las de una
    cantera, las de un ajuste) cuenta la que más apoya (:func:`~.entities.strongest`).

    **Coste:** con la versión sin entidades, ni se llama (``design.store`` lo comprueba con una consulta).
    Si no hay celdas que suban más del espesor mínimo y nada declarado, solo se lee el registro; las huellas
    se leen solo si las hay, y la superficie de una entidad solo si su huella tiene relleno encima o ya era
    una entrada. Solo lee."""
    held = {name for name, role in inputs if role == provenance.SUPPORTED_ON_ROLE}
    with _consistent(project) as conn:
        found = entities.registry(project, version.uid, conn=conn)
        wanted = entity_surfaces(conn, found, skip=_unsupportable(found, own_code, set(written)))
        thickness = _min_thickness(conn, project, version)
    if not wanted:
        return SupportSurvey()
    frame = project_frame(project)
    ground = (start_values if start_values is not None else read_surface(
        project, start, version_uid=version.uid, expect=frame, role="superficie de partida").values)
    arrays = [np.asarray(item, dtype=np.float64) for item in results]
    filled = np.zeros(ground.shape, dtype=bool)
    with np.errstate(invalid="ignore"):
        for array in arrays:
            if array.shape != ground.shape:
                raise ValueError(f"la superficie resultante {array.shape} no es de la forma de la de "
                                 f"partida {ground.shape}")
            filled |= (array - ground) > thickness
    registered = {code for code, where in wanted.items() if where.surface in held}
    candidates = list(wanted) if filled.any() else sorted(registered, key=entities.code_order)
    if not candidates:
        return SupportSurvey()
    cells: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    with project.read() as conn:
        for code in candidates:
            rows, cols = entities.runs_cells(read_entity_footprint(conn, wanted[code].locator).runs)
            inside = (rows.size > 0 and int(rows.max()) < ground.shape[0]
                      and int(cols.max()) < ground.shape[1])
            if inside and (code in registered or bool(filled[rows, cols].any())):
                cells[code] = (rows, cols)
    if not cells:
        return SupportSurvey()
    surfaces = {code: read_surface(project, wanted[code].surface, version_uid=version.uid, expect=frame,
                                   role="superficie de apoyo").values for code in cells}
    area = float(frame.grid.cell_area)
    best = entities.strongest(
        item for array in arrays for item in entities.detect_supports(
            array, ground, surfaces, cells, thickness, area, declared=sorted(registered & set(cells))))
    return SupportSurvey(best, MappingProxyType({item.code: wanted[item.code] for item in best}))


def add_supports(project: StoreProject, start: OperationStart, survey: SupportSurvey) -> OperationStart:
    """``start`` con las entradas de ``survey`` que aún no lleva (:meth:`SupportSurvey.uses`; una operación
    hecha es inmutable: se añaden aquí, antes de abrirla, con ``dataclasses.replace``) y el hash que tiene
    cada una ahora, para que ``des.input_changed`` las vigile como las demás. Sin nada nuevo, ``start``."""
    extra = survey.uses((use.item, str(use.role)) for use in start.inputs)
    if not extra:
        return start
    version = require_version(project, start.version_uid, start.op_type)
    with project.read() as conn:
        seen = {**start.seen, **_seen(conn, extra, version)}
    return replace(start, inputs=(*start.inputs, *extra), seen=MappingProxyType(seen))


def detected_supports(project: StoreProject, prepared: PreparedPlatform, outcome: PlatformOutcome
                      ) -> tuple[entities.Support, ...]:
    """**Lo que apoyaría la plataforma** calculada (``prepared`` y ``outcome``) sobre las demás entidades de
    su versión (RF-015-15, T23): :func:`survey_supports` con la superficie que dejaría (la de partida con
    su resultado en la ventana de la huella) y lo que ya consume. Es lo que añade ``DesignWriter.commit`` al
    crearla (el gancho genérico de ``design.store``: sus entradas ``supported_on`` y la cifra
    ``des.supported_m3``); sirve para enseñarlo antes. Solo lee."""
    surface = np.array(prepared.job.start, dtype=np.float64, copy=True)
    surface[outcome.footprint.window] = outcome.result
    version = require_version(project, prepared.start.version_uid, provenance.PLATFORM)
    written = {provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, prepared.job.request.name)}
    return survey_supports(
        project, version, [surface], prepared.start_surface, own_code=prepared.code, written=written,
        inputs=[(use.item, str(use.role)) for use in prepared.start.inputs],
        start_values=prepared.job.start).supports


def _confirmation(project: StoreProject, outcome: PlatformOutcome, decided_by: str | None
                  ) -> provenance.CounterslopeConfirmation | None:
    """La contrapendiente que la persona confirmó expresamente (``outcome.confirmed``) y que se anota en los
    ajustes al crear (RF-015-23; T15): la cuantía y la abscisa de su peor tramo, quién la confirmó
    (``decided_by``; por defecto, quien tiene abierto el proyecto) y cuándo (ahora, UTC). ``None`` si el
    resultado no tiene contrapendiente que pase de la tolerancia: no hay nada que confirmar."""
    profile = outcome.profile
    index = profile.worst
    if index is None or not outcome.confirmed:
        return None
    return provenance.counterslope_confirmation(
        float(profile.rise_m[index]), float(profile.chainage_m[index]),
        decided_by or project.session.user_host, format_utc(project.clock.now()))


def _with_confirmation(start: OperationStart, confirmed: provenance.CounterslopeConfirmation
                       ) -> OperationStart:
    """``start`` con la contrapendiente confirmada en sus ajustes (:data:`~.provenance.COUNTERSLOPE_CONFIRMED`)."""
    return replace(start, settings={**start.settings,
                                    provenance.COUNTERSLOPE_CONFIRMED: confirmed.settings()})


def _reuse_confirmation(outcome: PlatformOutcome, confirmed: provenance.CounterslopeConfirmation | None
                        ) -> PlatformOutcome:
    """El ``outcome`` de un recálculo con la contrapendiente ya confirmada por la persona, **si la nueva no
    pasa de la confirmada más la tolerancia de la entidad** (T15; RF-015-23): ``outcome.confirm()``. Si
    la pasa, o no había confirmada, el mismo ``outcome``: ``ensure_creatable`` vuelve a pedirla."""
    index = outcome.profile.worst
    if index is None or confirmed is None:
        return outcome
    if confirmed.covers(float(outcome.profile.rise_m[index]), outcome.profile.tolerance_m):
        return outcome.confirm()
    return outcome


def create_platform(project: StoreProject, writer: DesignWriter, prepared: PreparedPlatform,
                    outcome: PlatformOutcome, *, decided_by: str | None = None) -> Stored:
    """**«Crear» una plataforma** (spec 015, T13; RF-015-01, RF-015-02, RF-015-04): registra en **una**
    transacción de escritura (:meth:`~.store.DesignWriter.commit` de ``writer``, el de «Calcular», con sus
    tres salidas preparadas) los parámetros de la entidad —una fila de la versión por parámetro, ADOPTADO,
    con su origen, de ``decided_by`` (por defecto, quien tiene abierto el proyecto): :func:`set_entity_params`
    con el gancho ``before_begin``, **antes** de abrir la operación para que lea todos de la versión—, la
    operación ``des.platform`` con sus entradas (la capa, la superficie de partida —la de otra entidad si
    la encadena—, las máscaras y las ``supported_on`` que da :func:`detected_supports`) y sus ajustes, las
    tres salidas, las cifras con el ámbito de la entidad y el mensaje del resumen. Una entidad que ya
    estaba en la versión (``prepared.existing``) no vuelve a escribir sus parámetros (``ValueError`` si no
    los tiene). Si algo falla, o lo que consume cambió desde que se calculó (``des.input_changed``), no
    queda nada y el error sigue; **no modifica ninguna capa de entrada**. ``DesignError``
    ``des.platform_counter_unconfirmed`` si el resultado tiene una contrapendiente sin confirmar
    (RF-015-23), antes de escribir nada. Si la tiene y la persona la confirmó, queda en los ajustes de la
    operación (:data:`~.provenance.COUNTERSLOPE_CONFIRMED`: cuánto, en qué abscisa, quién la confirmó y
    cuándo; ``decided_by``, por defecto quien tiene abierto el proyecto) y un recálculo la reutiliza
    mientras la nueva no pase de la confirmada más la tolerancia (T15)."""
    outcome.ensure_creatable()
    start = prepared.start
    confirmed = _confirmation(project, outcome, decided_by)
    if confirmed is not None:  # RF-015-23: quién la confirmó, cuánto y cuándo, para el recálculo (T15)
        start = _with_confirmation(start, confirmed)

    def parameters(conn: sqlite3.Connection) -> None:
        key = entity_key(prepared.code, PlatformParam.NAME)
        if prepared.existing:
            if ParameterStore(project).get(key, version=start.version_uid, conn=conn) is None:
                raise ValueError(f"la entidad {prepared.code} no tiene sus parámetros en la versión: no "
                                 "está en ella (se prepara sin su código)")
        else:
            set_entity_params(project, prepared.rows, version=start.version_uid,
                              decided_by=decided_by, conn=conn)

    return writer.commit(start, figures=outcome.figures, message=outcome.message,
                         before_begin=parameters)


# --- Recalcular (spec 015, T14; RF-015-02, RF-015-16, RF-008-26) ---------------------------------


def platform_parameters(project: StoreProject, version: Version, code: str) -> dict[str, Any]:
    """Los parámetros vigentes de la entidad de código ``code`` en la versión ``version``, por último
    segmento de su clave (:func:`~.provenance.platform_values`): los resuelve una operación que empezara
    ahora (el de la fila de la versión y, si no la tiene, el del proyecto), sin los que no tienen valor.
    Es la definición de la entidad (RF-015-01: sus parámetros de versión, no la capa ni los ajustes de la
    operación anterior) con la que se recalcula. Solo lee."""
    keys = {entity_key(code, param): param for param in PlatformParam}
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(
            conn, tuple(keys), (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid)
    return {param.value: item.value for key, param in keys.items()
            if (item := found.get(key)) is not None and item.value is not None}


def run_platform(project: StoreProject, request: PlatformRequest, *, version: str | None,
                 code: str, masks: access.MaskSet | None = None, supersedes: str | None = None,
                 confirmed: provenance.CounterslopeConfirmation | None = None,
                 budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Calcula y registra ``request`` —una entidad que ya está en la versión ``version``: su ``code``— de
    **una vez**, sin pedir confirmación (spec 015, T14; RF-015-02, RF-015-16; el recálculo de lo obsoleto,
    :func:`~.store.recompute_run`; el «Crear» tras «Calcular» es :meth:`~.steps.Calculation.create`):
    empieza la operación ``des.platform`` —si ``supersedes`` es la de una anterior, la sustituye, quedándose
    con los nombres de sus datos— con lo que lee hoy (las máscaras de la versión, la capa, la superficie de
    partida y de apoyo y los parámetros de la entidad: la cota, la pendiente y el ancho **de su fila de la
    versión**, no de la capa) y devuelve su ``OperationHandle`` «en curso» y sus pasos, que avanza quien la
    llama: calculan (:func:`platform_compute_steps`), escriben la superficie, la tabla y el informe y
    completan la operación en una transacción; el último lleva el :class:`~.store.Stored`. No escribe
    parámetros de la entidad (ya están). Cerrarlos antes, o un fallo, no dejan nada y la operación queda
    cancelada o fallida.

    Al llamar, sin empezar nada: los rechazos de :func:`prepare_platform_units` (la versión, la geometría,
    los campos, la partida, la falta de dato, un sector pendiente…). Al avanzar, antes de escribir: un
    parámetro que cambió entre prepararla y empezar (``des.input_changed``) y una contrapendiente que pasa de
    la tolerancia (``des.platform_counter_unconfirmed``: un recálculo **no confirma** por la persona, que
    vuelve a «Calcular» y la confirma). Con ``confirmed`` (la contrapendiente que ella confirmó al crear la
    operación que se sustituye, de sus ajustes: :func:`~.provenance.counterslope_confirmed`; T15), el
    recálculo la **reutiliza si la nueva no pasa de la confirmada más la tolerancia** (y la operación nueva
    la lleva en sus ajustes, la misma: quién la confirmó y cuándo); si la pasa, vuelve a pedirla
    (``des.platform_counter_unconfirmed``) y la operación que sustituye sigue vigente."""
    found = require_version(project, version, provenance.PLATFORM)
    loaded = _loaded_masks(project, found, masks)
    prepared: PreparedPlatform = _result_of(prepare_platform_units(
        project, request, found, loaded, code=code, supersedes=supersedes))
    if confirmed is not None:  # se arrastra a la operación nueva (la misma decisión, no una nueva)
        prepared = replace(prepared, start=_with_confirmation(prepared.start, confirmed))
    handle = prepared.start.begin(project)
    return handle, _platform_run(project, handle, prepared, budget_s, confirmed)


def recompute_platform(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S
                       ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.platform`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo
    obsoleto», RF-008-26; spec 015, T14; RF-015-02, RF-015-16): la plataforma de sus ajustes (el nombre, el
    código y los campos de su capa) con los **parámetros vigentes de su entidad en su versión**
    (:func:`platform_parameters`) y no los que leyó la operación que sustituye: una entidad se define por
    sus parámetros (RF-015-01). Devuelve lo de :func:`run_platform`. ``ValueError`` si los ajustes no son los
    de una plataforma o la petición no es de una versión."""
    project: StoreProject = request.project  # type: ignore[assignment]
    code = provenance.platform_code(request.settings)
    found = require_version(project, request.version, provenance.PLATFORM)
    asked = provenance.platform_request(request.settings,
                                        platform_parameters(project, found, code))
    return run_platform(project, asked, version=found.uid, code=code,
                        supersedes=request.operation_uid,
                        confirmed=provenance.counterslope_confirmed(request.settings),
                        budget_s=budget_s)


def _check_recorded(handle: OperationHandle, prepared: PreparedPlatform) -> None:
    """Los parámetros que anotó la operación al empezar son los que leyó el cálculo al prepararse (RF-013-17,
    D-14, como ``Calculation.create``): si uno cambió entre las dos cosas, el resultado ya no le corresponde
    (``des.input_changed``, con el parámetro)."""
    read: dict[str, object] = {entity_key(prepared.code, PlatformParam(name)): value
                               for name, value in prepared.values.items()}
    read.update(prepared.common)
    for param in handle.params:
        if param.key in read and param.value != read[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»",
                              field="parámetros", value=param.key)


def _platform_run(project: StoreProject, handle: OperationHandle, prepared: PreparedPlatform,
                  budget_s: float, confirmed: provenance.CounterslopeConfirmation | None = None
                  ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        _check_recorded(handle, prepared)
        outcome: PlatformOutcome = yield from compute_platform_steps(
            writer, prepared, operation=prepared.job.request.name, budget_s=budget_s)
        outcome = _reuse_confirmation(outcome, confirmed)
        outcome.ensure_creatable()
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


# --- Con qué se compara, y lo que sale del proyecto para el resumen -----------------------------

_MAGNITUDE_CUT =("des.plat_cut_m3", "des.edge_cut_m3")
_MAGNITUDE_FILL = ("des.plat_fill_m3", "des.edge_fill_m3")


def platform_previous(conn: sqlite3.Connection, version: Version, code: str) -> Previous | None:
    """Con qué se compara el desmonte y el terraplén de una plataforma (RF-015-13, RF-013-30, D-25): la
    operación ``des.platform`` de la entidad de código ``code`` de la revisión **congelada** más
    reciente de la versión ``version`` y sus cifras de la huella y del borde sumadas
    (``des.plat_cut_m3`` + ``des.edge_cut_m3``, y las del relleno), como ``report.Previous``
    (``operation``: su nombre; ``revision``: ``V01.r1``). Por el código y no por el nombre: es
    inmutable en la versión y sobrevive a renombrarla. ``None`` si la versión no tiene ninguna
    congelada, ninguna operación de esa entidad o sin esas cifras. Solo lee."""
    revision = versions_read.last_frozen(conn, version.uid)
    if revision is None:
        return None
    rows = conn.execute(
        "SELECT uid, settings FROM gb_operation WHERE revision_uid = ? AND op_type = ? "
        "AND status = ? ORDER BY fid DESC",
        (revision.uid, provenance.PLATFORM, OperationStatus.DONE.value)).fetchall()
    for uid, settings in rows:
        found = json.loads(settings) if settings else {}
        if found.get("code") != code:
            continue
        keys = (*_MAGNITUDE_CUT, *_MAGNITUDE_FILL)
        figures = {str(key): float(value) for key, value in conn.execute(
            f"SELECT key, value FROM gb_figure WHERE operation_uid = ? AND key IN "
            f"({', '.join('?' for _ in keys)})", (uid, *keys)) if value is not None}
        if len(figures) < len(keys):
            return None
        name = found.get("name")
        return Previous(str(name) if isinstance(name, str) and name else code,
                        f"{version.code}.r{revision.number}",
                        sum(figures[key] for key in _MAGNITUDE_CUT),
                        sum(figures[key] for key in _MAGNITUDE_FILL))
    return None


def quarry_order(project: StoreProject, version: Version, prepared: PreparedPlatform
                 ) -> QuarryOrder | None:
    """La otra superficie de la cantera de la 014 cuando la plataforma parte de una de sus dos
    superficies (RF-015-14; ``des_fin_`` o ``des_exp_``), para comprobar ``final ≤ explotación ≤
    terreno`` con lo que ella cambia; ``None`` si parte de otra cosa (el terreno, un diseño de la 013, la
    superficie de otra entidad). La lee del proyecto en la rejilla del proyecto (RF-011-02). Solo lee."""
    with project.read() as conn:
        origin = design_surface_of(conn, prepared.start_surface, version.uid)
    if origin is None or origin.op_type != provenance.QUARRY:
        return None
    name, side, _order = _quarry_link(origin)
    other = _other_surface(name, side)
    found = read_surface(project, other, version_uid=version.uid, expect=project_frame(project),
                         role="otra superficie de la cantera")
    assert side is not None  # lo es de una cantera
    return QuarryOrder(name, side, prepared.start_surface, other, found.values)


_CONSUMERS = (
    "SELECT DISTINCT o.fid, o.uid, o.op_type, o.settings FROM gb_operation_io AS io "
    "JOIN gb_operation AS o ON o.uid = io.operation_uid "
    "JOIN gb_revision AS r ON r.uid = o.revision_uid "
    "WHERE io.direction = 'in' AND io.item_kind = 'dataset' AND io.item_uid IN ({marks}) "
    "AND o.status = 'done' AND o.superseded_by IS NULL AND r.version_uid = ? "
    "AND r.state = 'open'")
_OUTPUTS = (
    "SELECT DISTINCT item_uid FROM gb_operation_io WHERE direction = 'out' "
    "AND item_kind = 'dataset' AND operation_uid IN ({marks})")
_CHUNK = 400
"""Los uid por consulta (el límite de variables de SQLite es mayor)."""


def _name_of(op_type: str, settings: object) -> str:
    """El nombre de una operación hecha: el ``name`` de sus ajustes o, sin él, su tipo."""
    try:
        found = json.loads(str(settings)) if settings else {}
    except ValueError:
        found = {}
    name = found.get("name") if isinstance(found, dict) else None
    return name if isinstance(name, str) and name else op_type


def _dependents(conn: sqlite3.Connection, datasets: Iterable[str], version_uid: str, *,
                exclude: Iterable[str | None] = ()) -> list[tuple[str, str, str]]:
    """Lo que depende de los datos ``datasets`` en la revisión **abierta** de la versión
    ``version_uid`` (RF-015-16; la 008): las operaciones hechas y no sustituidas que los consumen y,
    en cascada, las que consumen lo que escribieron esas, por orden de registro; como ``(uid, tipo,
    nombre)``. Sin las de ``exclude``. Una revisión congelada no se marca (RF-009-19). Solo lee."""
    skip = {uid for uid in exclude if uid is not None}
    found: dict[str, tuple[int, str, str]] = {}
    frontier = list(dict.fromkeys(datasets))
    seen = set(frontier)
    while frontier:
        fresh: list[str] = []
        for first in range(0, len(frontier), _CHUNK):
            part = frontier[first:first + _CHUNK]
            sql = _CONSUMERS.format(marks=", ".join("?" for _ in part))
            for fid, uid, op_type, settings in conn.execute(sql, (*part, version_uid)):
                if uid not in found and uid not in skip:
                    found[str(uid)] = (int(fid), str(op_type), _name_of(str(op_type), settings))
                    fresh.append(str(uid))
        frontier = []
        for first in range(0, len(fresh), _CHUNK):
            part = fresh[first:first + _CHUNK]
            sql = _OUTPUTS.format(marks=", ".join("?" for _ in part))
            for (dataset,) in conn.execute(sql, part):
                if dataset not in seen:
                    seen.add(str(dataset))
                    frontier.append(str(dataset))
    ordered = sorted(found.items(), key=lambda item: item[1][0])
    return [(uid, op_type, name) for uid, (_fid, op_type, name) in ordered]


def platform_obsolete(project: StoreProject, version: Version, prepared: PreparedPlatform,
                      masks: access.MaskSet, *, insert_before: str | None = None,
                      supersedes: str | None = None) -> tuple[Obsolete, ...]:
    """**Lo que quedará obsoleto al crear la plataforma** ``prepared`` en ``version`` (RF-015-03,
    RF-015-16; del grafo de la 008, sin escribir; una revisión congelada no se marca, RF-009-19): si
    **protege** (``protect``), las máscaras de la versión (declarará una restricción y se compilan de
    nuevo) y lo que las consumió, en cascada (``ObsoleteKind.MASKS`` y ``CONSUMER``); si es una
    **inserción** (``insert_before``: la entidad que pasa a partir de la nueva), esa entidad y las que le
    siguen en la cadena, las que ya tienen resultado (``SUCCESSOR``: una sin calcular no queda obsoleta);
    si **sustituye** una operación (``supersedes``), lo que dependía de lo que escribió, en cascada
    (``DEPENDENT``). Con las operaciones sustituidas no se cuenta la propia sustituida. Una operación no
    sale dos veces."""
    found: list[Obsolete] = []
    listed: set[str] = set()
    with project.read() as conn:
        if prepared.values.get("protect"):
            found.append(Obsolete(ObsoleteKind.MASKS, version.code, masks_provenance.COMPILE,
                                  masks.operation_uid))
            for uid, op_type, name in _dependents(conn, [item.uid for item in masks.used],
                                                  version.uid, exclude=(supersedes,)):
                found.append(Obsolete(ObsoleteKind.CONSUMER, name, op_type, uid))
                listed.add(uid)
        if insert_before is not None:
            registry = entities.registry(project, version.uid, conn=conn)
            for item in entities.chain_of(registry.records, insert_before):
                if item.state is EntityState.UNCALCULATED:
                    continue
                entry = registry.get(item.code)
                uid = "" if entry is None or entry.operation_uid is None else entry.operation_uid
                found.append(Obsolete(ObsoleteKind.SUCCESSOR, item.name, provenance.PLATFORM, uid))
                if uid:
                    listed.add(uid)
        if supersedes is not None:
            written = [str(row[0]) for row in conn.execute(
                "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? "
                "AND direction = 'out' AND item_kind = 'dataset' ORDER BY fid", (supersedes,))]
            for uid, op_type, name in _dependents(conn, written, version.uid,
                                                  exclude=(supersedes, *listed)):
                found.append(Obsolete(ObsoleteKind.DEPENDENT, name, op_type, uid))
    return tuple(found)


def _restrictions(project: StoreProject, version: Version
                  ) -> tuple[dict[str, str], dict[str, str]]:
    """Lo que hace falta para nombrar la restricción que impide mover unas celdas: el nombre de cada
    restricción por su código (las tres capas de la 012) y la entidad que declara cada
    ``dec__<código>`` (su nombre, del registro de la versión). Solo lee."""
    with project.read() as conn:
        named = {code: name for code, (name, _ctype) in constraint_names(conn).items()}
        registry = entities.registry(project, version.uid, conn=conn)
    declared = {declared_code(entry.record.code): entry.record.name for entry in registry}
    return named, declared


def platform_summary(project: StoreProject, version: Version, prepared: PreparedPlatform,
                     outcome: PlatformOutcome, masks: access.MaskSet, *,
                     insert_before: str | None = None, supersedes: str | None = None
                     ) -> PlatformSummary:
    """El resumen de «Calcular» la plataforma ``prepared`` (RF-015-03, RF-015-13): las cifras del
    ``outcome``, sus avisos como los enseña la cuenta (``platform.summary_notices``: los 10 primeros tramos
    del salto creado y grupos de lo que no queda en la rasante, con una nota de los que faltan), lo que
    no mueve por una restricción —con su nombre, o con la entidad que la declara
    (``preview.held_notices``)— y lo que quedará obsoleto al crearla (:func:`platform_obsolete`), en
    notas. Solo lee."""
    names, declared = _restrictions(project, version)
    held = held_notices(
        outcome.name, masks, outcome.footprint.window, cut=outcome.applied.cut_denied,
        fill=outcome.applied.fill_denied, edge=outcome.edge.held, names=names, declared=declared)
    obsolete = platform_obsolete(project, version, prepared, masks, insert_before=insert_before,
                                 supersedes=supersedes)
    notices = (*summary_notices(outcome.notices), *held,
               *obsolete_notices(outcome.name, version.code, obsolete))
    return PlatformSummary(outcome.name, outcome.code, version.code, outcome.figures, notices,
                           obsolete)


# --- La declaración de restricciones (spec 015, T17; RF-015-10, RF-015-12, RF-012-29) ------------------

_DECLARE_PHASE = "declare_constraints"
_DECLARES: Mapping[EntityKind, ConstraintType] = MappingProxyType({
    EntityKind.PLATFORM: ConstraintType.NO_FILL})
"""Lo que declara cada tipo de entidad cuando protege su zona (D-4): la plataforma, «sin relleno». Un tipo
que declara otra cosa (en la 016, el contrafuerte, «sin corte») añade aquí su fila."""
_LIVE_STATES = frozenset({EntityState.CURRENT, EntityState.STALE, EntityState.SUPPORT_REMOVED})
"""Los estados de una entidad **viva y calculada** (RF-015-25): tiene operación vigente y datos que no están
descartados. Una «sin calcular» no tiene huella y una «descartada» ya no es de la versión: ninguna declara."""
_DECISION_PARAMS = (PlatformParam.NAME, PlatformParam.PROTECT, PlatformParam.GUARD, PlatformParam.REASON)
"""Los parámetros de los que sale lo que declara una entidad (su nombre, si protege, su resguardo y su
motivo): la decisión de la restricción es la más reciente de ellos (``decided_by`` y ``decided_at`` de su
historial)."""
_ENTITY_DATA = (
    "SELECT d.locator FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = ? AND io.role = ? "
    "ORDER BY io.fid")


@dataclass(frozen=True, slots=True)
class EntityFootprint:
    """Lo que la declaración lee de la tabla ``des_epr_`` de una entidad (:func:`read_entity_footprint`):
    su ``code``, el ``name`` con que se calculó (el de su dato ``des_epr_<nombre>``), su ``kind``, la
    ``layer`` de su geometría de origen y su huella en ``runs`` (tramos de fila ``(fila, col0, col1)`` de la
    rejilla entera, ``col1`` excluida: :func:`footprint_runs`)."""

    code: str
    name: str
    kind: str
    layer: str
    runs: tuple[tuple[int, int, int], ...]


def read_entity_footprint(conn: sqlite3.Connection, table: str) -> EntityFootprint:
    """La fila de la tabla ``des_epr_`` ``table`` (``conn`` la ve: la del proyecto o la congelada): su
    código, su nombre, su tipo, su capa y su huella en tramos. ``ValueError`` si no tiene exactamente una
    fila o su huella no son tramos."""
    rows = conn.execute(f'SELECT code, name, kind, layer, footprint FROM "{table}"').fetchall()
    if len(rows) != 1:
        raise ValueError(f"la tabla de una entidad «{table}» tiene una fila, no {len(rows)}")
    ((code, name, kind, layer, footprint),) = rows
    runs = tuple((int(row), int(first), int(last)) for row, first, last in json.loads(footprint))
    return EntityFootprint(str(code), str(name), str(kind), str(layer), runs)


@dataclass(frozen=True, slots=True)
class DeclaredSource:
    """Lo que la declaración sabe de una entidad viva y calculada de la versión (RF-015-10): su ``code`` y su
    ``kind``, el ``name`` de ahora (``calc_name`` es el con que se calculó: el de su dato ``des_epr_``), la
    ``layer`` de su geometría de origen, si protege (``protect``), su ``mode`` (``cut`` o ``cut_fill``), su
    resguardo (``guard_m``, sin valor por defecto: D-19), el motivo que editó la persona (``reason``; ``None``:
    el generado), quién la creó o cambió y cuándo se decidió (``decided_by`` y ``decided_on``: la decisión más
    reciente de :data:`_DECISION_PARAMS`, no la fecha de ahora) y su huella en tramos (``runs``)."""

    code: str
    kind: EntityKind
    name: str
    calc_name: str
    layer: str
    protect: bool
    mode: str
    guard_m: float | None
    reason: str | None
    decided_by: str | None
    decided_on: date | None
    runs: tuple[tuple[int, int, int], ...]


def _check_declares(source: DeclaredSource) -> None:
    """Lo que una entidad que protege ha de cumplir para declarar (RF-015-10, RF-015-12): su resguardo, sin
    valor por defecto y obligatorio (D-19: ``des.entity_param_missing`` o ``des.entity_param_range``, con la
    entidad, el campo y el valor), y no proteger en el modo «en corte y relleno», en el que rellena su propia
    huella y su restricción «sin relleno» prohibiría su propio movimiento (D-21: ``des.platform_protect_cut_fill``;
    defensa en profundidad: la preparación ya lo rechaza al crearla). No escribe nada."""
    if not source.protect:
        return
    check_entity_param(source.name, source.code, PlatformParam.GUARD, source.guard_m,
                       layer=source.layer, required=True)
    if source.mode == PlatformMode.CUT_FILL.value:
        raise DesignError("des.platform_protect_cut_fill", obj=f"Plataforma «{source.name}»",
                          field=entity_key(source.code, PlatformParam.MODE), value=source.mode,
                          layer=source.layer, entity=source.name)


def declared_rows_steps(sources: Sequence[DeclaredSource], grid: Grid, version_uid: str
                        ) -> Generator[Progress, None, tuple[DeclaredConstraint, ...]]:
    """**El cálculo de la declaración**, compartido por «Declarar», el recálculo y la reproducción (plan 015
    §5.3.1; sin proyecto dentro: recibe lo leído): de cada entidad de ``sources`` que protege, una
    :class:`~..core.constraints.declared.DeclaredConstraint` de la versión ``version_uid`` —el tipo que
    declara su clase (``sin relleno`` una plataforma), el contorno de su huella en la rejilla ``grid``
    (``declared_zone_of_runs``, A8), su resguardo (``buffer_out_m``, obligatorio: D-19), «activa», el motivo
    que editó la persona o el generado («declarada por la plataforma P1»), su decisor, la fecha de **su
    decisión** (no la de ahora), la entidad como origen y un ``uid`` derivado de la versión y del código de la
    entidad—, **por código** y una por paso. Las que no protegen no declaran nada. Lo mismo da el mismo
    contenido de tabla (A8): repetir la declaración no cambia su hash. Rechaza lo de
    :func:`_check_declares` antes de calcular nada; ``ValueError`` si una que protege no lleva decisor o
    fecha (un error del programa)."""
    protecting = sorted((source for source in sources if source.protect), key=lambda item: item.code)
    for source in protecting:
        _check_declares(source)
    rows: list[DeclaredConstraint] = []
    for index, source in enumerate(protecting):
        yield Progress(_DECLARE_PHASE, index, len(protecting),
                       f"Restricción declarada por «{source.name}»…")
        if source.decided_by is None or source.decided_on is None or source.guard_m is None:
            raise ValueError(f"la entidad {source.code} protege y no lleva su decisor, la fecha de su "
                             "decisión o su resguardo: no se puede declarar su restricción")
        zone = entities.declared_zone_of_runs(source.runs, grid, source.guard_m)
        rows.append(DeclaredConstraint(
            uid=declared_uid(version_uid, source.code), code=declared_code(source.code),
            ctype=_DECLARES[source.kind], name=source.name,
            reason=source.reason or entities.declared_reason(source.kind, source.name),
            decided_by=source.decided_by, decided_on=source.decided_on, entity_code=source.code,
            entity_name=source.name, parts=zone.parts, buffer_out_m=source.guard_m, active=True))
    return tuple(rows)


@contextmanager
def _consistent(project: StoreProject) -> Iterator[sqlite3.Connection]:
    """Una conexión de lectura con todas las lecturas en la misma instantánea (como el registro de las
    entidades)."""
    with project.read() as conn:
        conn.execute("BEGIN")
        try:
            yield conn
        finally:
            conn.execute("ROLLBACK")


def _decision(store: ParameterStore, conn: sqlite3.Connection, version: Version, code: str
              ) -> tuple[str, date]:
    """Quién creó o cambió la entidad ``code`` y cuándo se decidió: de los parámetros que dan lo que declara
    (:data:`_DECISION_PARAMS`, propios de la versión), el de la decisión más reciente (a igual hora, el
    primero de la lista). Todos llevan su decisor y su fecha (RF-008-01): es **la fecha del parámetro**, no
    la de ahora, así que recalcular no la cambia."""
    latest: ParameterRecord | None = None
    for param in _DECISION_PARAMS:
        record = store.get(entity_key(code, param), version=version.uid, conn=conn)
        if record is not None and (latest is None or record.decided_at > latest.decided_at):
            latest = record
    if latest is None:
        raise ValueError(f"la entidad {code} no tiene ninguno de los parámetros de lo que declara en "
                         f"{version.code}")
    return latest.decided_by, date.fromisoformat(latest.decided_at[:10])


def declared_sources(project: StoreProject, version: Version, *,
                     conn: sqlite3.Connection | None = None) -> tuple[DeclaredSource, ...]:
    """Las entidades **vivas y calculadas** de la versión ``version`` como las ve la declaración (RF-015-10;
    solo lee): las del registro de la versión (``entities.registry``) con operación vigente y datos sin
    descartar (:data:`_LIVE_STATES`: no declaran ni una «sin calcular» ni una descartada), cada una con sus
    parámetros vigentes en la versión (si protege, su modo, su resguardo y el motivo que editó la persona,
    :func:`~.entity_store.platform_parameters`), su decisor y la fecha de su decisión (:func:`_decision`) y su
    huella, leída de su tabla ``des_epr_`` vigente (:func:`read_entity_footprint`). Por orden de código.
    ``conn`` es una conexión de lectura de quien llama; sin ella, una propia."""
    if conn is None:
        with _consistent(project) as reading:
            return declared_sources(project, version, conn=reading)
    registry = entities.registry(project, version.uid, conn=conn)
    live = [entry for entry in registry
            if entry.operation_uid is not None and entry.record.state in _LIVE_STATES]
    keys = {entity_key(entry.record.code, param): (entry.record.code, param)
            for entry in live for param in (PlatformParam.PROTECT, PlatformParam.MODE,
                                            PlatformParam.GUARD, PlatformParam.REASON)}
    found = ParameterStore(project).resolve_many(
        conn, tuple(keys), (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid)
    values: dict[tuple[str, PlatformParam], Any] = {}
    for key, (code, param) in keys.items():
        resolved = found.get(key)
        values[code, param] = (resolved.value if resolved is not None else _default(param))
    store = ParameterStore(project)
    sources: list[DeclaredSource] = []
    for entry in live:
        record = entry.record
        code = record.code
        tables = conn.execute(_ENTITY_DATA, (entry.operation_uid, DATASET,
                                             provenance.ENTITY_ROLE)).fetchall()
        if len(tables) != 1:
            raise ValueError(f"la operación {entry.operation_uid} de la entidad {code} escribió "
                             f"{len(tables)} tablas de la entidad, no una")
        data = read_entity_footprint(conn, str(tables[0][0]))
        protect = bool(values[code, PlatformParam.PROTECT])
        guard, reason = values[code, PlatformParam.GUARD], values[code, PlatformParam.REASON]
        who, when = _decision(store, conn, version, code) if protect else (None, None)
        sources.append(DeclaredSource(
            code=code, kind=EntityKind(record.kind), name=record.name, calc_name=data.name,
            layer=data.layer, protect=protect, mode=str(values[code, PlatformParam.MODE]),
            guard_m=None if guard is None else float(guard),
            reason=(reason.strip() or None) if isinstance(reason, str) else None, decided_by=who,
            decided_on=when, runs=data.runs))
    return tuple(sources)


@dataclass(frozen=True, slots=True, eq=False)
class PreparedDeclaration:
    """Lo que se lee y se comprueba antes de declarar (:func:`prepare_declaration`): la ``version``, las
    entidades vivas que recoge (``sources``, todas: de las que no protegen solo se anota su dato y que
    protegen o no), la rejilla del proyecto (``grid``) y lo que anotará la operación (``start``)."""

    version: Version
    sources: tuple[DeclaredSource, ...]
    grid: Grid
    start: OperationStart


def _live_declaration(conn: sqlite3.Connection, version: Version) -> str | None:
    """El uid de la operación de declaración que escribió la tabla vigente de la versión (``des_decl``), la
    que sustituye la nueva; ``None`` si todavía no se declaró. Si la tabla se editó fuera de Geoblender
    (RF-015-11: su dato lo escribió la edición externa), la última declaración de Geoblender que la escribió
    (``core.datasets.external.last_writer``): es la que repite la entidad al volver a ponerla."""
    record = dataset_registry.get(conn, provenance.dataset_name(provenance.DECLARED_TABLE),
                                  version_uid=version.uid)
    if record is None or not record.live:
        return None
    return dataset_external.last_writer(conn, record.uid)


def prepare_declaration(project: StoreProject, version: Version | str | None, *,
                        supersedes: str | None = None) -> PreparedDeclaration:
    """Prepara ``des.declare_constraints`` en la versión editable ``version`` (spec 015, T17; RF-015-10): lee
    las entidades vivas (:func:`declared_sources`), **rechaza** antes de empezar lo que no puede declarar
    (:func:`_check_declares`: proteger sin resguardo, D-19, o en «corte y relleno», RF-015-12) y arma lo que
    anotará la operación: de **todas** las entidades vivas calculadas, su dato ``des_epr_`` como entrada
    (papel ``entity``) y sus ajustes (con la versión y, de las que protegen, su decisor y la fecha de su
    decisión) y los parámetros que lee (``protect`` de cada una; ``mode`` y ``guard_m`` de las que protegen;
    ``reason`` de las que editaron su motivo: :func:`~.provenance.declare_params`). No pide máscaras al día
    (la declaración las deja obsoletas: RF-012-06; las recompila la orden, T19). ``supersedes``: la
    declaración que sustituye (por defecto, la vigente de la versión, si la hay).

    Rechazos, sin escribir nada: los de :func:`~.store.require_version` (RF-009-21: sin versión activa,
    desconocida o no editable), ``des.entity_param_missing``/``_range``, ``des.platform_protect_cut_fill`` y
    ``des.operation_name_repeated``."""
    wanted = version.uid if isinstance(version, Version) else version
    found = require_version(project, wanted, provenance.DECLARE_CONSTRAINTS)
    with _consistent(project) as conn:
        sources = declared_sources(project, found, conn=conn)
        before = _live_declaration(conn, found) if supersedes is None else supersedes
    for source in sources:
        _check_declares(source)
    protecting = [source.code for source in sources if source.protect]
    settings = provenance.declare_settings(
        [(source.code, source.calc_name) for source in sources], version_uid=found.uid,
        decisions={source.code: (source.decided_by, source.decided_on) for source in sources
                   if source.protect and source.decided_by is not None
                   and source.decided_on is not None})
    inputs = provenance.declare_inputs(source.calc_name for source in sources)
    params = provenance.declare_params(
        [source.code for source in sources], protecting=protecting,
        reasoned=[source.code for source in sources if source.protect and source.reason is not None])
    begun = _start(project, provenance.DECLARE_CONSTRAINTS, "", found, None, settings, inputs, params,
                   before)
    return PreparedDeclaration(found, sources, project_frame(project).grid, begun)


def _declaration_message(count: int, version_code: str) -> str:
    """El mensaje de la operación: cuántas restricciones declaran las entidades de la versión."""
    if count == 0:
        return f"Ninguna entidad de {version_code} declara restricciones"
    if count == 1:
        return f"1 restricción declarada por las entidades de {version_code}"
    return f"{count} restricciones declaradas por las entidades de {version_code}"


def _check_declared_recorded(handle: OperationHandle, sources: Sequence[DeclaredSource]) -> None:
    """Los parámetros que anotó la operación al empezar son los que leyó la preparación (como
    :func:`_check_recorded`): si uno cambió entre las dos cosas, las filas ya no le corresponden
    (``des.input_changed``, con el parámetro)."""
    read: dict[str, object] = {}
    for source in sources:
        read[entity_key(source.code, PlatformParam.PROTECT)] = source.protect
        if source.protect:
            read[entity_key(source.code, PlatformParam.MODE)] = source.mode
            read[entity_key(source.code, PlatformParam.GUARD)] = source.guard_m
            if source.reason is not None:
                read[entity_key(source.code, PlatformParam.REASON)] = source.reason
    for param in handle.params:
        if param.key in read and param.value != read[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»",
                              field="parámetros", value=param.key)


def _declaration_run(project: StoreProject, handle: OperationHandle, prepared: PreparedDeclaration,
                     budget_s: float) -> Generator[Progress, None, None]:
    with DesignWriter(project, provenance.DECLARE_CONSTRAINTS, "", version=handle.version_uid,
                      handle=handle) as writer:
        _check_declared_recorded(handle, prepared.sources)
        rows = yield from declared_rows_steps(prepared.sources, prepared.grid, handle.version_uid)
        yield from pipeline.forward(_store_steps(
            writer.declared_steps(rows), budget_s, "las restricciones declaradas"))
        message = _declaration_message(len(rows), prepared.version.code)
        stored = writer.commit(figures=provenance.declare_figures(len(rows)), message=message)
        yield Progress(_STORE_PHASE, 1, 1, message, result=stored)


def run_declaration(project: StoreProject, *, version: Version | str | None,
                    supersedes: str | None = None, budget_s: float = STEP_BUDGET_S
                    ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Declara y registra las restricciones de las entidades de la versión ``version`` **de una vez**, sin
    pedir confirmación (spec 015, T17; RF-015-10, RF-015-16; plan 015 §5.3.2: una orden aparte que cada
    transacción hace por su cuenta): empieza la operación ``des.declare_constraints`` —si ``supersedes`` es la
    de una declaración anterior (por defecto, la vigente de la versión), la sustituye— con lo que lee hoy y
    devuelve su ``OperationHandle`` «en curso» y sus pasos, que avanza quien la llama: calculan las filas
    (:func:`declared_rows_steps`), reescriben la tabla entera ``des_decl_<vNN>`` y completan la operación en
    **una** transacción; el último lleva el :class:`~.store.Stored`. Cerrarlos antes, o un fallo, no dejan
    nada y la operación queda cancelada o fallida. Al llamar, sin empezar nada: los rechazos de
    :func:`prepare_declaration`."""
    prepared = prepare_declaration(project, version, supersedes=supersedes)
    handle = prepared.start.begin(project)
    return handle, _declaration_run(project, handle, prepared, budget_s)


def declare_constraints_steps(project: StoreProject, version: Version | str | None, *,
                              supersedes: str | None = None, budget_s: float = STEP_BUDGET_S
                              ) -> Generator[Progress, None, None]:
    """Los pasos de **declarar** las restricciones de las entidades de la versión ``version`` (spec 015, T17;
    RF-015-10; plan 015 §5.3.2: la declaración es una operación propia, repetible, que las órdenes de
    entidades encadenan tras su commit, T19): lo de :func:`run_declaration` empezando al avanzar, sin
    devolver el ``OperationHandle``; el último paso lleva el :class:`~.store.Stored`. Repetirla con las
    mismas entidades da la misma tabla y el mismo hash (A8) y sustituye a la vigente."""
    _handle, work = run_declaration(project, version=version, supersedes=supersedes,
                                    budget_s=budget_s)
    yield from work


def declaration_diverges(project: StoreProject, version: Version | str) -> bool:
    """Si lo que hay hoy en la tabla de las declaradas de la versión ``version`` (``Version``, uid o código)
    **difiere** de lo que declararían sus entidades vivas (spec 015, T20; RF-015-11, RF-008-56; plan 015 §5.8):
    el hash de contenido registrado de ``des_decl_<vNN>`` frente al que saldría de declarar ahora
    (:func:`declared_sources` y :func:`declared_rows_steps`, escritos en un GeoPackage en memoria:
    ``core.constraints.declared.content_sha256_of``), **sin recalcular ni escribir nada**. Pasa tras **aceptar con
    un motivo una edición** hecha en QGIS: lo vigente es lo aceptado, y hasta que una entidad lo vuelva a poner
    (declarar de nuevo, lo que hace toda orden de entidades) no coincide con lo que declaran. Es la cifra que
    enseñará la barra N. ``False`` si la versión no tiene tabla viva (nada declarado: nada que difiera).
    ``VersionError`` (``core.version_unknown``) si la versión no existe; los rechazos de
    :func:`declared_rows_steps` (proteger sin resguardo o en «corte y relleno»: ``DesignError``) si lo que
    declararían las entidades hoy no se puede declarar."""
    wanted = version.uid if isinstance(version, Version) else version
    with _consistent(project) as conn:
        found = versions_read.version(conn, wanted)
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=wanted, version=wanted)
        record = dataset_registry.get(conn, provenance.dataset_name(provenance.DECLARED_TABLE),
                                      version_uid=found.uid)
        if record is None or not record.live:
            return False
        sources = declared_sources(project, found, conn=conn)
    rows = declared_rows_steps(sources, project_frame(project).grid, found.uid)
    while True:
        try:
            next(rows)
        except StopIteration as stop:
            expected = stop.value
            break
    crs, _vertical = project_references(project)
    return content_sha256_of(expected, record.locator, crs,
                             normalizer=record.normalizer) != record.content_sha256


def recompute_declaration(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S
                          ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.declare_constraints`` de ``request`` (:func:`~.store.recompute_run`;
    «Recalcular lo obsoleto», RF-008-26; spec 015, T17; RF-015-10): la declaración es de la **versión**, no
    de una entidad, así que se rehace entera con las entidades vivas de la versión y sus parámetros de hoy,
    sustituyendo a la que se repite. Devuelve lo de :func:`run_declaration`. ``VersionError`` si la petición
    no es de una versión editable."""
    project: StoreProject = request.project  # type: ignore[assignment]
    return run_declaration(project, version=request.version, supersedes=request.operation_uid,
                           budget_s=budget_s)


# --- Tras la orden de una entidad (spec 015, T19; RF-015-10, RF-015-16, RF-012-06; plan 015 §5.3.2) ---

_CHAIN_PHASE = "entity_chain"
_CHAIN_TOTAL = 100
"""El total de los pasos de :func:`after_entity_change`: un porcentaje (cada etapa tiene su tramo)."""
_CHAIN_DECLARE_SHARE = 40
"""El tramo, de ese porcentaje, que ocupa la declaración; el resto es de la compilación de las máscaras."""
_STAGE_ERRORS = (GeoblenderError, sqlite3.Error, OSError, ValueError)
"""Lo que una etapa de :func:`after_entity_change` da por un fallo suyo (un rechazo, el disco, la base): se
cuenta en el resultado y no se lanza; lo demás (un error del programa) sigue."""
_CHAIN_OWN = frozenset({provenance.DECLARE_CONSTRAINTS, masks_provenance.COMPILE})
"""Las operaciones que hace la propia cadena: no se cuentan como «lo que quedó obsoleto». Con una entidad que
protege, el grafo da también por obsoletas la declaración y las máscaras que acaba de hacer (el eco del ciclo
entidad → declarada → máscaras → entidad, D-21): se ponen al día cuando se recalcula la entidad."""
_STALE_OPERATIONS = (
    "SELECT o.uid, o.op_type, o.settings FROM gb_operation AS o "
    "JOIN gb_revision AS r ON r.uid = o.revision_uid "
    "WHERE o.status = 'done' AND o.superseded_by IS NULL AND r.version_uid = ? AND r.state = 'open' "
    "AND EXISTS (SELECT 1 FROM gb_stale AS s WHERE s.item_kind = 'operation' AND s.item_uid = o.uid) "
    "ORDER BY o.fid")


class ChainStage(StrEnum):
    """Una etapa de :func:`after_entity_change`: declarar las restricciones de las entidades o recompilar las
    máscaras con ellas."""

    DECLARE = "declare"
    MASKS = "masks"


@dataclass(frozen=True, slots=True, eq=False)
class ChainFailure:
    """La etapa que falló (``stage``) y su error. Lo que falló queda como estaba (cada etapa es una operación y
    una transacción propias: P-7) y, si fueron las máscaras, **obsoletas**, con su causa
    (``gis.masks.access.MaskCause``), hasta que quien las pida las recompile."""

    stage: ChainStage
    error: Exception

    @property
    def reason(self) -> str:
        """Por qué falló, en español, como lo da el error."""
        return str(getattr(self.error, "text", None) or getattr(self.error, "message", None) or self.error)


@dataclass(frozen=True, slots=True, eq=False)
class EntityChain:
    """Lo que hizo :func:`after_entity_change` en la versión ``version`` (su código): cuántas restricciones
    declaran ahora sus entidades (``declared``; ``None`` si no se pudo declarar), si la declaración **cambió**
    (otro hash que la anterior o la primera: ``declaration_changed``), si recompiló las máscaras
    (``masks_compiled``), lo ganado y perdido por restricción que da esa compilación (``changes``,
    RF-012-06: ``gis.masks.compile.Change`` con el área de su polígono y de su zona), lo que **quedó obsoleto**
    por ella (``obsolete``: las operaciones de la revisión abierta que usaron las máscaras anteriores, como
    ``ObsoleteKind.CONSUMER``, y lo que depende de ellas), el estado de las máscaras al terminar
    (``masks_state``) y lo que falló (``failure``)."""

    version: str
    declared: int | None
    declaration_changed: bool
    masks_compiled: bool
    changes: tuple[Change, ...] = ()
    obsolete: tuple[Obsolete, ...] = ()
    masks_state: access.MaskState = access.MaskState.CURRENT
    failure: ChainFailure | None = None

    def notices(self) -> tuple[Notice, ...]:
        """Lo que se dice al terminar la orden, en el orden en que se enseña: la declaración (si cambió), las
        máscaras recompiladas, por restricción lo ganado y perdido en m², lo que quedó obsoleto y, si falló
        una etapa, el aviso con el porqué. Ninguno si no cambió nada."""
        found: list[Notice] = []
        if self.declaration_changed and self.declared is not None:
            found.append(Notice("des.entity_chain_declared",
                                {"version": self.version, "count": self.declared}))
        if self.masks_compiled:
            found.append(Notice("des.entity_chain_masks", {"version": self.version}))
        for change in self.changes:
            found.append(Notice("des.entity_chain_change", {
                "name": change.name or change.code, "gained": round(change.polygon_gained_m2),
                "lost": round(change.polygon_lost_m2), "zone_gained": round(change.zone_gained_m2),
                "zone_lost": round(change.zone_lost_m2)}))
        if self.obsolete:
            names = [f"«{item.name}»" for item in self.obsolete]
            found.append(Notice("des.entity_chain_obsolete", {
                "operations": len(names), "items": tuple(names[:SUMMARY_ITEMS])
                + (("…",) if len(names) > SUMMARY_ITEMS else ())}))
        if self.failure is not None:
            code = ("des.entity_chain_declare_failed" if self.failure.stage is ChainStage.DECLARE
                    else "des.entity_chain_masks_failed")
            found.append(Notice(code, {"version": self.version, "reason": self.failure.reason}))
        return tuple(found)


def _stale_operations(conn: sqlite3.Connection, version: Version) -> dict[str, Obsolete]:
    """Las operaciones **obsoletas** de la revisión abierta de ``version`` (hechas, sin sustituir y con alguna
    causa en la caché de la 008, ``gb_stale``), por su uid, como ``Obsolete`` (``CONSUMER``). Una revisión
    congelada no se marca (RF-009-19). Solo lee."""
    return {str(uid): Obsolete(ObsoleteKind.CONSUMER, _name_of(str(op_type), settings), str(op_type),
                               str(uid))
            for uid, op_type, settings in conn.execute(_STALE_OPERATIONS, (version.uid,))}


def _scaled(steps: Iterator[Progress], low: int, high: int) -> Generator[Progress, None, Any]:
    """Los pasos de una etapa (``steps``: ``Progress``, el último con su ``result``) como un tramo ``low`` a
    ``high`` del porcentaje de :func:`after_entity_change`; devuelve el resultado. Cerrar el generador cierra
    ``steps``."""
    with closing(steps):  # type: ignore[type-var]
        for step in steps:
            if step.result is not None:
                return step.result
            fraction = min(max(step.done / step.total, 0.0), 1.0) if step.total else 0.0
            yield Progress(_CHAIN_PHASE, low + int((high - low) * fraction), _CHAIN_TOTAL, step.message)
    raise RuntimeError("los pasos de la etapa terminaron sin dar resultado")


def after_entity_change(project: StoreProject, version: Version | str | None, *,
                        budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, None]:
    """**Lo que sigue a cada orden de entidades** en la versión ``version`` (uid, código o ``Version``) por
    pasos de ``budget_s`` como mucho (spec 015, T19; RF-015-10, RF-015-16, RF-012-06; plan 015 §5.3.2 y P-7;
    ADR-0030 §5): tras el commit de una entidad creada, cambiada, retirada o descartada, **(a)** repite la
    declaración de las restricciones de las entidades vivas de la versión (:func:`declare_constraints_steps`:
    ``des_decl_<vNN>`` entera, que sustituye a la vigente; con las mismas entidades da el mismo hash) y **(b)**
    si las máscaras ya no están al día —la declaración cambió, o la compilación vigente no la había consumido
    nunca: el hueco H-1, ``gis.masks.access.MaskCause.DECLARED_NEW``— las compila de nuevo
    (``gis.masks.access.compile_masks_steps``) y cuenta **qué quedó obsoleto con ello** (las operaciones de la
    revisión abierta que usaron las máscaras anteriores: la propia plataforma que protege, cuya restricción
    cambió lo que consumió, es lo esperado, CE-015-04 y D-21; «Recalcular lo obsoleto» la rehace y quita la
    marca de lo que dependía de ella si su salida no cambia, RF-008-26) y **lo ganado y lo perdido por
    restricción** (RF-012-06: el informe de la compilación). Sin cambio, no recompila.

    Cada etapa es una operación propia y **una transacción propia** (P-7): si una falla (un rechazo, el
    disco), no queda nada a medias de ella y el fallo va en el resultado (:class:`ChainFailure`) en lugar de
    lanzarse; si fueron las máscaras, quedan **obsoletas con su causa** y se compilan de nuevo antes de que un
    operador las use (``ensure_masks_steps``) o con «Compilar las máscaras». Cerrar el generador a mitad
    (Esc) cierra la etapa en curso (que no deja nada) y deja lo de las anteriores. El último ``Progress``
    lleva el :class:`EntityChain`.

    Al avanzar, antes de escribir nada: los rechazos de :func:`~.store.require_version` (RF-009-21: sin
    versión activa, desconocida o no editable)."""
    found = require_version(project, None if version is None else (
        version.uid if isinstance(version, Version) else version), provenance.DECLARE_CONSTRAINTS)
    yield Progress(_CHAIN_PHASE, 0, _CHAIN_TOTAL, "Poniendo al día las restricciones declaradas…")
    with project.read() as conn:
        before = dataset_registry.get(conn, provenance.dataset_name(provenance.DECLARED_TABLE),
                                      version_uid=found.uid)
        stale = _stale_operations(conn, found)
    declared: int | None = None
    changed = compiled = False
    changes: tuple[Change, ...] = ()
    failure: ChainFailure | None = None
    try:  # (a) la declaración
        stored: Stored = yield from _scaled(
            declare_constraints_steps(project, found, budget_s=budget_s), 0, _CHAIN_DECLARE_SHARE)
        (record,) = stored.records
        with project.read() as conn:
            (declared,) = conn.execute(f'SELECT COUNT(*) FROM "{record.locator}"').fetchone()
        changed = before is None or before.content_sha256 != record.content_sha256
    except _STAGE_ERRORS as error:
        failure = ChainFailure(ChainStage.DECLARE, error)
    if failure is None:  # (b) las máscaras, si ya no están al día
        state, _pending = access.mask_state(project, found.uid)
        if state is not access.MaskState.CURRENT:
            yield Progress(_CHAIN_PHASE, _CHAIN_DECLARE_SHARE, _CHAIN_TOTAL,
                           "Compilando las máscaras con las restricciones declaradas…")
            try:
                recompiled: StoredMasks = yield from _scaled(
                    access.compile_masks_steps(project, found.uid, budget_s=budget_s),
                    _CHAIN_DECLARE_SHARE, _CHAIN_TOTAL)
                compiled = True
                changes = recompiled.result.changes
            except _STAGE_ERRORS as error:
                failure = ChainFailure(ChainStage.MASKS, error)
    with project.read() as conn:
        now = _stale_operations(conn, found)
    after, _pending = access.mask_state(project, found.uid)
    chain = EntityChain(
        found.code, declared, changed, compiled, changes,
        tuple(item for uid, item in now.items()
              if uid not in stale and item.op_type not in _CHAIN_OWN), after, failure)
    yield Progress(_CHAIN_PHASE, _CHAIN_TOTAL, _CHAIN_TOTAL,
                   "Restricciones declaradas y máscaras al día" if failure is None
                   else "Restricciones declaradas y máscaras: no se pudo terminar", result=chain)
