# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar la plataforma: lo que se lee y se rechaza antes de calcular (spec 015, T11; HU-015-3;
RF-015-06, RF-015-07, RF-015-08, RF-015-09; plan 015 §5.1, §5.2.1, §5.2.2 y §5.3.1; ADR-0030).

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

La capa solo da la **geometría** y los **valores iniciales**: se copian a parámetros de la entidad
(con el origen «capa X, campo Y, entidad Z») y cambian después en ella; la capa no se modifica. Del
terreno (RF-015-09) se comprueba la superficie de partida y la de apoyo, que son las que lee el
cálculo: el terreno es la de partida salvo en una cadena (la de otra entidad nace de él).

Python puro (nivel 8), con numpy. ``design.entity_store`` es un módulo pesado de la 015: lo importan
las órdenes al usarlo, no ``bl`` al registrarse
(``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Generator, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterRecord, ParameterStore, definition
from ..core.params.store import default_reason
from ..core.versions.model import Version
from ..gis.masks import access
from ..gis.raster import Raster
from ..gis.store import StoreProject, load_features
from ..gis.vector import FeatureLayer
from . import entities, pipeline, provenance
from .compose import admitted
from .entities import EntityKind, EntityRecord, EntityRegistry, EntityState
from .envelopes import reach_steps
from .messages import DesignError
from .model import BenchSense, LayerField, Metric, PlatformMode, PlatformRequest
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
    _drain,
    _window_grid,
    platform_footprint,
)
from .quarry import _level_column
from .sectors import design_sectors, refuse_pending
from .seeds import sector_layout
from .store import (
    OperationStart,
    _check_014_params,
    _loaded_masks,
    _result_of,
    _start,
    number,
    require_version,
)
from .surfaces import project_frame, read_surface

__all__ = [
    "EntityParamRow",
    "PreparedPlatform",
    "prepare_platform",
    "prepare_platform_units",
    "set_entity_params",
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
_LAYER_FIELDS: Mapping[PlatformParam, str] = MappingProxyType({
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
    (``start_surface``) y de apoyo (``support_surface``; ``None`` sin ella), ya resueltos."""

    job: PlatformJob
    footprint: Footprint
    start: OperationStart
    code: str
    fid: int
    rows: tuple[EntityParamRow, ...]
    common: Mapping[str, float]
    start_surface: str
    support_surface: str | None

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


def _check_chain(registry: EntityRegistry, request: PlatformRequest, code: str) -> None:
    """RF-015-04: de cada superficie parte como mucho una entidad (``des.entity_start_taken``, con la
    que ya parte) y la cadena no da la vuelta (``des.entity_chain_cycle``); la entidad ``code`` no
    cuenta consigo misma."""
    other = entities.start_conflict(registry.records, request.start, ignoring=code)
    if other is not None:
        raise DesignError("des.entity_start_taken", obj=_object(request),
                          field=entity_key(code, PlatformParam.START), value=request.start,
                          entity=request.name, other=other.name)
    this = EntityRecord(code, request.name, EntityKind.PLATFORM, request.start, request.support)
    entities.check_chain([*(item for item in registry.records if item.code != code), this])


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


def _feature(layer: FeatureLayer, request: PlatformRequest, code: str) -> int:
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


def _linked_axis(project: StoreProject, layer: FeatureLayer, index: int, request: PlatformRequest
                 ) -> tuple[Any, str] | None:
    """El eje que enlaza el campo ``eje`` del polígono: las partes de su línea en la capa de ejes y
    su nombre; ``None`` si el campo va vacío (sin eje enlazado: el principal, con su aviso). La
    capa de ejes ha de ser de líneas (``des.corridor_not_lines``) y tener esa línea
    (``des.entity_feature_unknown``)."""
    fields = request.fields
    assert fields.axis_field is not None and fields.axis_layer is not None
    link = _field_value(layer, index, fields.axis_field, request)
    if link is None:
        return None
    axes = _layer(project, fields.axis_layer)
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


def _read_geometry(project: StoreProject, layer: FeatureLayer, index: int,
                   request: PlatformRequest) -> PlatformGeometry:
    """La geometría de la plataforma: la de la capa y, de un polígono con eje enlazado, la de su
    línea. Una capa de puntos no es de plataformas (``des.platform_layer_kind``); un ancho en una capa
    de polígonos o un enlace en una de líneas son un error del programa (``ValueError``: el
    diálogo no los ofrece)."""
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
        linked = _linked_axis(project, layer, index, request)
        if linked is not None:
            return PlatformGeometry("polygon", parts, axis_parts=linked[0], axis_name=linked[1])
    return PlatformGeometry(layer.kind, parts)


# --- Los parámetros de la entidad ---------------------------------------------------------------


def _default(param: PlatformParam) -> Any:
    return PLATFORM_PARAMS[param.value].default


def _entity_values(request: PlatformRequest, code: str, fid: int,
                   from_layer: Mapping[PlatformParam, float], *, line: bool) -> dict[str, Any]:
    """Los parámetros resueltos y comprobados de la entidad, por último segmento de su clave
    (RF-015-08): lo que se pide, lo que sale de la capa (la cota inicial, la pendiente y, de una
    línea, el ancho) y, de lo que no se pide, el valor por defecto de su parámetro (D-4, D-5, D-7, D-8
    y D-22); sin él, ``des.entity_param_missing`` (no se elige ninguno por la persona). Un número
    fuera de su rango es ``des.entity_param_range``; la pendiente que pasa de la máxima fijada
    (D-6, ``des.platform_max_slope``: es una rampa) y proteger en el modo «en corte y relleno»
    (RF-015-12, ``des.platform_protect_cut_fill``) se rechazan después."""
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
                           supersedes: str | None = None
                           ) -> Generator[None, None, PreparedPlatform]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan la
    plataforma ``request`` de la versión editable ``version`` con sus ``masks`` ya al día
    (:func:`~.store.masks_steps`; RF-015-06): el nombre único y el código (``code``: el de una entidad
    que ya está en la versión, que no choca consigo misma; si no, el siguiente, ``PLT-001``), la
    partida y la cadena, la capa con su geometría y sus campos, los parámetros resueltos, las
    superficies de partida y de apoyo, la huella (que comprueba la geometría), la falta de dato, los
    sectores con la búsqueda pendiente y lo que anotará la operación. ``supersedes``: la operación hecha
    a la que sustituye (un recálculo). Devuelve la :class:`PreparedPlatform`. **Nada se escribe**;
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
    _check_chain(registry, request, chosen)
    yield
    layer = _layer(project, request.layer)
    index = _feature(layer, request, chosen)
    line = layer.kind == "line"
    geometry = _read_geometry(project, layer, index, request)
    fields = request.fields
    from_layer: dict[PlatformParam, float] = {}
    layer_fields: dict[PlatformParam, str] = {}
    for param, attribute in _LAYER_FIELDS.items():
        field = getattr(fields, attribute)
        if field is not None:  # sin campo (un polígono no tiene ancho): el valor no sale de la capa
            from_layer[param] = _layer_number(layer, index, field, request)
            layer_fields[param] = field
    fid = layer.fids[index]
    values = _entity_values(request, chosen, fid, from_layer, line=line)
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
    inputs = provenance.platform_inputs(
        request, start_name, masks.uses(), () if support_name is None else (support_name,))
    begun = _start(project, provenance.PLATFORM, request.name, version, masks,
                   provenance.platform_settings(request, chosen), inputs,
                   provenance.platform_params(chosen, request), supersedes)
    yield
    rows = _rows(request, chosen, values, layer_fields)
    return PreparedPlatform(job, footprint, begun, chosen, fid, rows, MappingProxyType(common),
                            start_name, support_name)


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
