# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar y rechazar la detección de acopios: lo que se lee y se comprueba **antes de calcular** (spec 016, T11; HU-016-1;
RF-016-02, RF-016-03, RF-016-04, RF-015-08, RF-015-09; plan 016 §5.2.1, §5.2.2, §5.3.1, §5.7 P-2 y §8; ADR-0031 §2; D-15,
D-17, D-20).

El homólogo, para la detección de acopios, de ``design.entity_store.prepare_platform_units``: **solo lee**. Nada se escribe
en el proyecto (RF-015-03) salvo las máscaras de la versión si no estaban al día (una operación propia, RF-013-04, y solo
si no se dan cargadas). La detección **no llama a** ``refuse_pending`` (``design.sectors``): no mueve ninguna celda, y la
búsqueda de intocables solo importa a quien las mueve (RF-015-07; caso límite de la spec §8).

- :func:`detection_scope`: el **ámbito** de la detección por su superficie (D-15, P-2; ADR-0031 §2): **del proyecto** si la
  superficie es del proyecto (también sin versión activa: tipo ``des.stockpile_detect_project``) y **de la versión** si es de
  una versión (tipo ``des.stockpile_detect``; entonces se exige versión editable, RF-009-21, ``VersionError``). Una
  superficie de una versión que no está activa, o de otra, es ``des.surface_other_version``; sin versión activa, la
  de una versión pide la versión (``core.version_required``). Una operación **de proyecto no consume un dato de versión**
  (RF-009-05): la superficie y las bases son del proyecto por construcción (una base de una versión se rechaza con
  ``des.surface_other_version``) y, antes de calcular, lo dice quien prepara; ``core`` lo vuelve a comprobar al abrir la
  operación.
- :func:`prepare_detection_units` (por unidades, para componerlas con ``pace_units``) y :func:`prepare_detection`: el
  código ``STK-nnn`` (correlativo **por ámbito**: el registro del proyecto o el de la versión) y el nombre único en su
  ámbito, la capa de marcas, la superficie y su rejilla (RF-011-02 y RF-011-03: ni se remuestrea ni se interpola; el CRS y el
  datum vertical se comparan antes de leer una celda), el umbral de la huella ``res.anthropic_presence_m`` leído **por su
  clave** (D-17), los parámetros resueltos y comprobados (RF-015-08), el perímetro de actuación si se piden candidatos (las
  máscaras de la versión; en el proyecto, la restricción del proyecto, RF-012-13: el perímetro activo o, sin él, el límite
  legal) y lo que anotará la operación. Da una :class:`PreparedDetection`: el ``StockpileJob`` listo para calcular (todo lo
  leído y nada del proyecto), ``start`` (la ``OperationStart``) y las filas de los parámetros de la entidad
  (:class:`~.entity_store.EntityParamRow`), todas.

**La capa de marcas** (plan 016 §5.2.1). Una capa de polígonos del proyecto (``gis_fea_``) con los campos que elige la
persona (``StockpileFields``): ``name_field`` (de texto: la clave de la marca, única; sin él, su ``fid``), ``margin_field``
(numérico, m, opcional), ``material_field`` (de texto, opcional) y ``base_field`` (de texto, opcional: el **nombre del
dato** de una superficie del proyecto en su rejilla, RF-016-03). Cada marca se **rasteriza** a las celdas de la rejilla del
proyecto cuyo **centro** queda dentro de su polígono (par-impar, D-16 de la 013), como índices planos
(``fila · columnas + columna``, ``int64``, ordenados: lo que recibe ``StockpileMark``), con la caja de la marca y no la
rejilla entera (100 marcas no son 100 máscaras de 2,81 M de celdas). **Dos marcas se solapan si alguna celda tiene su
centro en las dos** (decisión de la sesión principal, 18/11/2026): las que solo se tocan por el borde no se rechazan (sus
huellas se reparten, RF-016-06).

**Rechazos** (sin escribir nada; el primero que se encuentra, en este orden): la versión (``VersionError``: sin versión
activa en una superficie de versión, no editable), la superficie (``gis.dataset_unknown``, ``des.surface_other_version``,
``des.surface_is_tin``), el nombre de la detección (``des.entity_name_repeated`` en la versión,
``des.stockpile_name_repeated_project`` en el proyecto), la capa (``des.layer_not_polygons``), sus campos
(``des.stockpile_layer_field``), el nombre de las marcas (``des.entity_field_value`` si falta;
``des.stockpile_mark_repeated``), el valor de cada margen (``des.entity_field_value``, ``des.entity_param_range``), su
polígono (``des.stockpile_mark_geometry``, ``des.stockpile_mark_no_cells``), una capa sin marcas ni candidatos
(``des.stockpile_no_marks``), los parámetros (``des.entity_param_missing``, ``_range`` y ``_choice``), la rejilla y la
falta de dato de la superficie (``des.surface_mismatch``, ``gis.raster_empty``), las bases (``gis.dataset_unknown``,
``des.surface_mismatch``, ``des.surface_other_version``), las marcas solapadas **nombrando las dos**
(``des.stockpile_marks_overlap``) y el nombre de un dato (``des.operation_name_repeated`` y ``_project``). Lo que se
rechaza de **un** acopio al calcularlo (la marca no da celdas sobre el umbral, falta terreno en su huella o su corona…) no
es de la preparación: el cálculo lo informa en el resumen sin registrarlo (RF-016-04).

Python puro (nivel 8), con numpy. ``design.stockpile_store`` es un módulo pesado de la 016: lo importan las órdenes al
usarlo, no ``bl`` al registrarse (``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import math
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.constraints.messages import ConstraintError
from ..core.constraints.model import ConstraintParam, GeometryKind, is_code
from ..core.constraints.params import param_key
from ..core.constraints.store import CONSTRAINT_LAYERS
from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterStore, definition
from ..core.params.store import default_reason
from ..core.provenance.operations import Use
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from ..gis.grid import Grid
from ..gis.masks import access
from ..gis.masks.combine import LEGAL_COMMAND, ClassBit, IncompleteConstraints
from ..gis.masks.provenance import CONSTRAINT_ROLES
from ..gis.masks.store import available_tables, declared_limits
from ..gis.masks.zones import limit_runs
from ..gis.polygons import overlay, problem_steps
from ..gis.store import StoreProject, load_features
from ..gis.vector import FeatureLayer
from . import entities, provenance
from .entities import EntityKind, EntityRegistry
from .entity_store import EntityParamRow
from .messages import DesignError
from .model import StockpileRequest
from .params import ANTHROPIC_PRESENCE, StockpileParam, check_entity_param, entity_key, entity_params
from .stockpiles import (
    CandidateParams,
    FootprintParams,
    PlaneParams,
    StockpileJob,
    StockpileMark,
)
from .store import OperationStart, _loaded_masks, _start, require_version
from .surfaces import find_surface, project_frame, read_surface_steps
from .zones import _paint, _polygon_spans, to_cell_units

__all__ = [
    "PROJECT",
    "VERSION",
    "PreparedDetection",
    "detection_scope",
    "detection_values",
    "mark_cells",
    "prepare_detection",
    "prepare_detection_units",
]

PROJECT = "project"
"""El ámbito de una detección sobre una superficie **del proyecto** (``des.stockpile_detect_project``; D-15)."""
VERSION = "version"
"""El ámbito de una detección sobre una superficie **de una versión** (``des.stockpile_detect``)."""

_KINDS_ES = MappingProxyType({"point": "puntos", "line": "líneas", "polygon": "polígonos"})
_NUMERIC = frozenset({"INTEGER", "DOUBLE"})
_FLOATS = (StockpileParam.MARGIN, StockpileParam.CROWN_INNER, StockpileParam.CROWN_OUTER, StockpileParam.CROWN_SLOPE,
           StockpileParam.CROWN_FLAT_MIN, StockpileParam.MAX_RESIDUAL, StockpileParam.TILT_MAX,
           StockpileParam.SUPPORT_QUANTILE, StockpileParam.OPEN_DIAMETER, StockpileParam.MIN_HEIGHT,
           StockpileParam.MIN_AREA, StockpileParam.MAX_AREA)
_INTEGERS = (StockpileParam.FIT_ROUNDS, StockpileParam.TURNS)
_NOT_CALCULATED = frozenset({StockpileParam.SUPPORT, StockpileParam.SUPPORTS, StockpileParam.DISCARDED})
"""Los valores de la entidad que no entran en la detección ni se piden al prepararla: en lo que se apoya (que una
detección no tiene: no cambia ninguna superficie) y si se descartó (``discarded``, RF-015-17; lo resuelve quien lo usa)."""
_DIALOG = "diálogo de «Acopio (detectar, retirar)…»"
"""El origen de lo que elige la persona en el diálogo de la orden (la entidad al final)."""
_SURFACE_ROLE = "superficie de detección"
_NO_VALUE = "—"


# --- Lo que se prepara --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PreparedDetection:
    """Lo que se lee y se comprueba antes de calcular una detección de acopios (:func:`prepare_detection_units`): el
    ``job`` (``design.stockpiles.StockpileJob``: todo lo leído y nada del proyecto, con las marcas ya **rasterizadas** y sin
    celdas en común), lo que anotará la operación (``start``: su tipo —``des.stockpile_detect`` o
    ``des.stockpile_detect_project`` según el ``scope``—, sus ajustes, entradas y parámetros), el ``code`` de la entidad
    (``STK-001``, correlativo por ámbito), el ``scope`` (:data:`PROJECT` o :data:`VERSION`), la ``version`` (la de la
    detección de versión; ``None`` en la del proyecto), el nombre de la superficie sobre la que se detecta
    (``surface``), la capa de marcas (``layer``), el ``fid`` de cada marca en su capa (``fids``: clave de la marca →
    ``fid``), las ``rows`` de los parámetros de la entidad —**todas**: sin su fila, ``begin_operation`` crearía la del valor
    por defecto en el proyecto, trampa de la T04 de la 015— y sus ``values`` resueltos y comprobados (por último segmento
    de su clave). ``existing``: la entidad ya estaba en su ámbito (se preparó con su ``code``: recalcularla), así que
    «Crear» no escribe otra vez sus parámetros."""

    job: StockpileJob
    start: OperationStart
    code: str
    scope: str
    version: Version | None
    surface: str
    layer: str
    fids: Mapping[str, int]
    rows: tuple[EntityParamRow, ...]
    values: Mapping[str, Any]
    existing: bool = False

    @property
    def op_type(self) -> str:
        """El tipo de la operación (``des.stockpile_detect`` o ``des.stockpile_detect_project``)."""
        return self.start.op_type

    @property
    def version_uid(self) -> str | None:
        """El uid de la versión de la detección (``None``: es del proyecto): lo que reciben ``design_writer`` y
        ``set_entity_params``."""
        return None if self.version is None else self.version.uid


# --- El ámbito ----------------------------------------------------------------------------------


def detection_scope(project: StoreProject, request: StockpileRequest, version: str | None
                    ) -> tuple[str, Version | None]:
    """El ámbito de la detección ``request`` (D-15; ADR-0031 §2; plan 016 P-2) y su versión: ``(PROJECT, None)`` si
    su superficie es **del proyecto** —con o sin versión activa— y ``(VERSION, la versión editable)`` si es de una
    versión (``version``: su uid o su código). Con una superficie sin nombre (un parámetro sin valor, que rechaza
    después ``des.entity_param_missing``), el de la versión si se da y, si no, el del proyecto. Solo lee.

    Rechazos: ``VersionError`` (``core.version_unknown``; ``core.version_required`` si la superficie es de una versión y
    no hay ninguna activa; ``core.version_not_editable``, RF-009-21), ``des.surface_other_version`` (de una versión que no
    es la activa), ``des.surface_is_tin`` y ``gis.dataset_unknown``."""
    active: Version | None = None
    if version is not None and str(version).strip():
        with project.read() as conn:
            active = versions_read.version(conn, str(version).strip())
        if active is None:
            raise VersionError("core.version_unknown", field="versión", value=version, version=version)
    name = request.surface
    if not name:
        return (PROJECT, None) if active is None else (VERSION, require_version(project, active.uid,
                                                                                provenance.STOCKPILE_DETECT))
    try:
        record = find_surface(project, name, version_uid="" if active is None else active.uid)
    except DesignError as error:
        if error.code == "des.surface_other_version" and active is None:
            require_version(project, None, provenance.STOCKPILE_DETECT)  # RF-009-21: una de una versión pide la versión
        raise
    with project.read() as conn:
        owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
    if not owner:
        return PROJECT, None
    assert active is not None  # find_surface solo da el dato de la versión activa
    return VERSION, require_version(project, active.uid, provenance.STOCKPILE_DETECT)


# --- Los parámetros -----------------------------------------------------------------------------


def detection_values(request: StockpileRequest, code: str) -> tuple[dict[str, Any], frozenset[str]]:
    """Los parámetros resueltos y comprobados de la detección ``request`` de código ``code`` (RF-015-08), por último
    segmento de su clave (``margin_m``), y los **nombres de los que se dejaron por su valor por defecto**: lo que se pide, y
    de lo que no se pide, el valor por defecto de su parámetro (D-3: la petición no lleva ninguna cifra minera); sin él,
    ``des.entity_param_missing``. Los candidatos que no se piden son ``False``. Un número fuera de su rango,
    ``des.entity_param_range``; el resguardo es obligatorio si protege (D-19 de la 015), y las áreas de los candidatos van
    de la mínima a la máxima. **Sin proyecto**: lo comparten preparar y reproducir."""
    spec = entity_params("stockpile")
    layer = request.fields.layer
    defaulted: set[str] = set()
    asked: dict[StockpileParam, object] = {
        StockpileParam.NAME: request.name, StockpileParam.LAYER: layer, StockpileParam.SURFACE: request.surface,
        StockpileParam.CANDIDATES: bool(request.candidates), StockpileParam.DECISIONS: request.decisions,
        StockpileParam.GUARD: request.guard_m, StockpileParam.REASON: request.reason}
    for param in (*_FLOATS, *_INTEGERS):
        given = getattr(request, param.value)
        if given is None:
            given = spec.template(param.value).default
            defaulted.add(param.value)
        asked[param] = given
    protect = request.protect
    if protect is None:
        protect = bool(spec.template(StockpileParam.PROTECT.value).default)
        defaulted.add(StockpileParam.PROTECT.value)
    asked[StockpileParam.PROTECT] = protect
    required = {StockpileParam.GUARD: protect}
    values: dict[str, Any] = {}
    for param in StockpileParam:
        if param in _NOT_CALCULATED:
            continue
        checked = check_entity_param(request.name, code, param.value, asked[param], layer=layer,
                                     required=required.get(param))
        if checked is not None:
            values[param.value] = checked
    if values[StockpileParam.CANDIDATES.value] and (
            values[StockpileParam.MIN_AREA.value] > values[StockpileParam.MAX_AREA.value]):
        raise DesignError("des.entity_param_range", obj=f"{spec.label} «{request.name}»",
                          field=entity_key(code, StockpileParam.MIN_AREA), value=values[StockpileParam.MIN_AREA.value],
                          entity=request.name, layer=layer,
                          range=f"≤ {values[StockpileParam.MAX_AREA.value]:g} m² ({StockpileParam.MAX_AREA.value})")
    return values, frozenset(defaulted)


def _rows(request: StockpileRequest, code: str, values: Mapping[str, Any], defaulted: frozenset[str]
          ) -> tuple[EntityParamRow, ...]:
    """Las filas de los parámetros de la entidad con su procedencia (RF-008-01): lo que no se pidió, con la de su valor por
    defecto (D-3: ADOPTADO «sin confirmar»; la inclinación máxima y el cuantil, HIPÓTESIS); el resto, lo que eligió la
    persona en el diálogo. **Todas** (también las de los valores por defecto)."""
    spec = entity_params("stockpile")
    rows: list[EntityParamRow] = []
    for param in StockpileParam:
        value = values.get(param.value)
        if value is None:
            continue
        if param.value in defaulted:
            declared = spec.template(param.value)
            source, kind, reason = declared.source, str(declared.source_kind), default_reason(declared)
        else:
            source, kind = f"{_DIALOG}, entidad «{request.name}»", "person"
            reason = f"Elegido al crear la detección de acopios «{request.name}»"
        rows.append(EntityParamRow(entity_key(code, param), param.value, value, source, kind, reason))
    return tuple(rows)


def _presence_threshold(project: StoreProject, version: Version | None) -> float:
    """El umbral de la huella de un acopio, el de la 011 (``res.anthropic_presence_m``, D-17), **por su clave**: el de la
    versión, el del proyecto o, sin ninguno, el de su definición (como lo leería una operación que empezara ahora); en una
    detección del proyecto, solo el del proyecto. ``ValueError`` (error del programa) si no está declarado ni
    registrado."""
    chain = (PROJECT_SCOPE,) if version is None else (VERSION_SCOPE, PROJECT_SCOPE)
    with project.read() as conn:
        resolved = ParameterStore(project).resolve_many(
            conn, (ANTHROPIC_PRESENCE,), chain, version=None if version is None else version.uid
        ).get(ANTHROPIC_PRESENCE)
    if resolved is not None:
        return float(resolved.value)
    declared = definition(ANTHROPIC_PRESENCE)
    if declared is None or declared.default is None:
        raise ValueError(f"«{ANTHROPIC_PRESENCE}» no tiene valor ni está registrado")
    return float(declared.default)


# --- El nombre y el código ---------------------------------------------------------------------


def _identify(project: StoreProject, request: StockpileRequest, version: Version | None, code: str | None
              ) -> str:
    """El código de la detección (``code`` si se da: una entidad que ya está en su ámbito; si no, el siguiente
    ``STK-nnn`` del registro de su ámbito, correlativo **por ámbito**: ``STK-001`` es la primera del proyecto y también la
    primera de cada versión) tras comprobar que su nombre es único en él (RF-015-01: también el de una entidad sin
    calcular o descartada, y el que da el mismo nombre de dato): ``des.entity_name_repeated`` en la versión y
    ``des.stockpile_name_repeated_project`` en el proyecto. ``GisError`` ``gis.dataset_name_invalid`` si el nombre no
    da ningún nombre de dato."""
    registry: EntityRegistry = (entities.project_registry(project) if version is None
                                else entities.registry(project, version.uid))
    chosen = code if code is not None else entities.next_code(
        EntityKind.STOCKPILE, (entry.record.code for entry in registry))
    wanted = provenance.dataset_name(provenance.STOCKPILES_TABLE, request.name)
    for entry in registry:
        other = entry.record.name
        if entry.record.code != chosen and (
                other == request.name or provenance.dataset_name(provenance.STOCKPILES_TABLE, other) == wanted):
            if version is None:
                raise DesignError("des.stockpile_name_repeated_project", obj=f"Detección de acopios «{request.name}»",
                                  field=entity_key(chosen, StockpileParam.NAME), value=request.name, other=other)
            raise DesignError("des.entity_name_repeated", obj=f"Detección de acopios «{request.name}»",
                              field=entity_key(chosen, StockpileParam.NAME), value=request.name, other=other,
                              version=version.code)
    return chosen


# --- La capa de marcas --------------------------------------------------------------------------


def _marks_layer(project: StoreProject, name: str) -> FeatureLayer:
    """La capa de marcas ``name`` del proyecto (solo lee): una capa de entidades de **polígonos**
    (``des.layer_not_polygons``); ``ValueError`` si no es una capa de entidades (``gis_fea_``)."""
    found = load_features(project, name)
    if not isinstance(found, FeatureLayer):
        raise ValueError(f"«{name}» no es una capa de entidades del proyecto (gis_fea_)")
    if found.kind != "polygon":
        raise DesignError("des.layer_not_polygons", obj=f"Capa «{name}»", field="geometría",
                          value=_KINDS_ES.get(found.kind, found.kind), layer=name)
    return found


def _field(layer: FeatureLayer, layer_name: str, param: str, field: str | None, *, numeric: bool) -> str | None:
    """La columna de la capa del campo ``field`` (por su nombre en la capa o por su columna), de texto o numérica;
    ``None`` si no se eligió campo. ``des.stockpile_layer_field`` (con los campos que sirven) si la capa no lo tiene, o no es
    del tipo que se lee de él (``param``: el campo de la petición, ``name_field``…)."""
    if field is None:
        return None
    fit = [column for column in layer.columns if (column.sql_type in _NUMERIC) == numeric]
    for column in fit:
        if field in (column.field, column.column):
            return column.column
    raise DesignError("des.stockpile_layer_field", obj=f"Capa «{layer_name}»", field=param, value=field,
                      layer=layer_name, fields=", ".join(column.field for column in fit) or _NO_VALUE)


def _text(value: object) -> str | None:
    """El valor de un campo de texto sin los espacios de los extremos (``None`` si falta o está en blanco)."""
    return value.strip() or None if isinstance(value, str) else None


def _names(layer: FeatureLayer, layer_name: str, column: str | None, param: str | None) -> tuple[str, ...]:
    """La clave de cada marca de la capa (la de su campo de nombre o, sin campo, su ``fid``), única:
    ``des.entity_field_value`` (con su ``fid``) si falta en una y ``des.stockpile_mark_repeated`` (con los ``fid``) si dos
    la comparten."""
    keys: list[str] = []
    for index, fid in enumerate(layer.fids):
        key = str(fid) if column is None else _text(layer.values[column][index])
        if key is None:
            raise DesignError("des.entity_field_value", obj=f"Capa «{layer_name}»", field=str(param),
                              value=_NO_VALUE, layer=layer_name, entity=f"fid {fid}")
        keys.append(key)
    for key in dict.fromkeys(keys):
        if keys.count(key) > 1:
            fids = ", ".join(str(layer.fids[index]) for index, found in enumerate(keys) if found == key)
            raise DesignError("des.stockpile_mark_repeated", obj=f"Capa «{layer_name}»", field=str(param),
                              value=key, layer=layer_name, fids=fids)
    return tuple(keys)


def _margin(layer: FeatureLayer, layer_name: str, column: str | None, param: str | None, index: int, key: str
            ) -> float | None:
    """El margen (m) de la marca ``index`` (``None`` si no lo tiene: el de la detección): un número finito dentro del
    rango de ``margin_m`` (``des.entity_field_value`` si no es un número y ``des.entity_param_range`` si está fuera: un
    margen negativo, RF-015-08)."""
    if column is None:
        return None
    raw = layer.values[column][index]
    if raw is None:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        number = math.nan
    if not math.isfinite(number):
        raise DesignError("des.entity_field_value", obj=f"Capa «{layer_name}»", field=str(param), value=raw,
                          layer=layer_name, entity=key)
    span = entity_params("stockpile").range(StockpileParam.MARGIN.value)
    assert span is not None
    if not span.contains(number):
        raise DesignError("des.entity_param_range", obj=f"Capa «{layer_name}»", field=str(param), value=number,
                          layer=layer_name, entity=key, range=span.text())
    return number


def mark_cells(parts: Sequence[Sequence[np.ndarray]], grid: Grid) -> np.ndarray:
    """Las celdas de ``grid`` cuyo **centro** está dentro de alguna de las ``parts`` de una marca (cada una, sus anillos
    ABSOLUTOS par-impar, el exterior primero y sus huecos: D-16 de la 013, ``design.zones``), como índices planos de la
    rejilla entera (``fila · columnas + columna``, ``int64``, ordenados y sin repetir): lo que recibe ``StockpileMark``.
    Se mide solo en la **caja** de la marca (recortada a la rejilla), no en toda ella. Vacío (``int64``) si no hay ninguna."""
    rings = [ring for part in parts for ring in part]
    empty = np.empty(0, dtype=np.int64)
    if not rings:
        return empty
    units = to_cell_units(rings, grid)
    columns = np.concatenate([ring[:, 0] for ring in units])
    rows = np.concatenate([ring[:, 1] for ring in units])
    top, bottom = max(0, math.floor(float(rows.min()))), min(grid.nrows, math.ceil(float(rows.max())) + 1)
    left, right = max(0, math.floor(float(columns.min()))), min(grid.ncols, math.ceil(float(columns.max())) + 1)
    if top >= bottom or left >= right:
        return empty
    box = (slice(top, bottom), slice(left, right))
    spans = _polygon_spans([tuple(part) for part in parts], grid, box=box)
    first, start, block = _paint(spans, bottom - top, right - left)
    found_rows, found_columns = np.nonzero(block)
    return (found_rows.astype(np.int64) + first) * grid.ncols + (found_columns.astype(np.int64) + start)


def _check_mark(layer: FeatureLayer, layer_name: str, index: int, key: str, grid: Grid
                ) -> Generator[None, None, np.ndarray]:
    """El polígono de la marca ``index``, comprobado, y sus celdas (:func:`mark_cells`): ``des.stockpile_mark_geometry``
    (con el problema de ``gis.polygons.PROBLEMS``) si se corta a sí mismo, no tiene área, tiene un hueco mal puesto o dos de
    sus partes se solapan, y ``des.stockpile_mark_no_cells`` si ninguna celda tiene su centro dentro."""
    parts = layer.parts[index]
    problems = (yield from problem_steps([tuple(part) for part in parts])) if parts else ()
    if problems or not parts:
        found = problems[0].problem if problems else "no_area"
        raise DesignError("des.stockpile_mark_geometry", obj=f"Capa «{layer_name}»", field="geometría", value=found,
                          layer=layer_name, entity=key)
    cells = mark_cells(parts, grid)
    if cells.size == 0:
        raise DesignError("des.stockpile_mark_no_cells", obj=f"Capa «{layer_name}»", field="geometría", value=0,
                          layer=layer_name, entity=key)
    return cells


def _check_overlaps(marks: Sequence[StockpileMark], grid: Grid) -> None:
    """RF-016-04: ninguna celda tiene su centro en dos marcas (las que solo se tocan por el borde, no se rechazan):
    ``des.stockpile_marks_overlap`` nombrando **las dos** (la primera pareja por el orden de la capa), el área común (m²) y
    el centro absoluto de las celdas comunes. Es lo que ``StockpileJob`` exige (celdas sin repetir) y lo que la preparación
    rechaza antes de calcular."""
    if len(marks) < 2:
        return
    every = np.concatenate([mark.cells for mark in marks])
    owners = np.repeat(np.arange(len(marks)), [mark.cells.size for mark in marks])
    order = np.argsort(every, kind="stable")
    sorted_cells, sorted_owners = every[order], owners[order]
    twice = np.flatnonzero(sorted_cells[1:] == sorted_cells[:-1])
    if twice.size == 0:
        return
    pairs = {(int(sorted_owners[i]), int(sorted_owners[i + 1])) for i in twice}
    first, second = min(pairs)
    shared = np.intersect1d(marks[first].cells, marks[second].cells, assume_unique=True)
    rows, cols = np.divmod(shared, grid.ncols)
    x = float((grid.west + (cols + 0.5) * grid.dx).mean())
    y = float((grid.north - (rows + 0.5) * grid.dy).mean())
    raise DesignError("des.stockpile_marks_overlap", obj=f"Marca «{marks[first].name}»", field="geometría",
                      value=marks[second].name, mark=marks[first].name, other=marks[second].name,
                      area=round(float(shared.size) * grid.cell_area, 2), x=x, y=y)


def _read_marks(project: StoreProject, request: StockpileRequest, grid: Grid, *, candidates: bool
                ) -> Generator[None, None, tuple[tuple[StockpileMark, ...], Mapping[str, int]]]:
    """Las marcas de la capa de la petición como ``StockpileMark`` (rasterizadas, con su margen, material y base) y el
    ``fid`` de cada una por su clave, con los rechazos de la capa, sus campos, sus nombres, sus márgenes, sus polígonos y
    una capa sin marcas ni candidatos (:func:`prepare_detection_units` da el orden)."""
    fields, layer_name = request.fields, request.fields.layer
    layer = _marks_layer(project, layer_name)
    name_column = _field(layer, layer_name, "name_field", fields.name_field, numeric=False)
    margin_column = _field(layer, layer_name, "margin_field", fields.margin_field, numeric=True)
    material_column = _field(layer, layer_name, "material_field", fields.material_field, numeric=False)
    base_column = _field(layer, layer_name, "base_field", fields.base_field, numeric=False)
    keys = _names(layer, layer_name, name_column, fields.name_field)
    if not keys and not candidates:
        raise DesignError("des.stockpile_no_marks", obj=f"Capa «{layer_name}»", field="capa", value=layer_name,
                          layer=layer_name)
    yield
    marks: list[StockpileMark] = []
    for index, key in enumerate(keys):
        margin = _margin(layer, layer_name, margin_column, fields.margin_field, index, key)
        cells = yield from _check_mark(layer, layer_name, index, key, grid)
        marks.append(StockpileMark(
            key, cells, margin_m=margin,
            material=None if material_column is None else _text(layer.values[material_column][index]),
            base=None if base_column is None else _text(layer.values[base_column][index])))
    return tuple(marks), MappingProxyType({key: layer.fids[index] for index, key in enumerate(keys)})


# --- El perímetro de actuación ------------------------------------------------------------------


def _version_perimeter(masks: access.MaskSet | access.MaskSource, grid: Grid) -> np.ndarray:
    """El perímetro de actuación de las máscaras de la versión (el bit ``PERIMETER`` de su rejilla de clases: las celdas
    enteras dentro del perímetro o, sin él, del límite legal, RF-012-15), como máscara de la rejilla entera."""
    classes = (masks.classes if isinstance(masks, access.MaskSet)
               else masks.classes_window((slice(0, grid.nrows), slice(0, grid.ncols))))
    return (classes & np.uint16(int(ClassBit.PERIMETER))) != 0


def _project_perimeter(project: StoreProject, grid: Grid) -> tuple[np.ndarray, tuple[str, ...]]:
    """El perímetro de actuación **de la restricción del proyecto** (RF-012-13: las máscaras son de versión y una detección
    del proyecto no las tiene): las celdas enteras dentro del perímetro de actuación activo o, sin ninguno, del límite
    legal activo (RF-012-15), como máscara de la rejilla entera, con las claves de las «activas» que ha leído (los
    parámetros de la operación). ``IncompleteConstraints`` si lo que ha de leer está incompleto o no es válido (RF-012-04) y
    ``core.constraint_no_legal_limit`` si no hay ni perímetro ni límite legal."""
    limits = declared_limits(project)
    chosen = limits.perimeter or limits.legal
    if limits.problems:
        raise IncompleteConstraints(limits.problems)
    if not chosen:
        raise ConstraintError("core.constraint_no_legal_limit", command=LEGAL_COMMAND)
    parts = tuple(part for item in chosen for part in item.parts)
    region = overlay(parts, [], "union", origin=(grid.west, grid.extent.ymin))
    mask = limit_runs(region.edges_local, grid, None).inside.mask(grid.shape)
    keys = tuple(param_key(item.code, ConstraintParam.ACTIVE) for item in chosen if is_code(item.code))
    return mask, keys


def _perimeter_inputs(project: StoreProject, keys: Sequence[str]) -> tuple[tuple[Use, ...], tuple[str, ...]]:
    """Lo que consume y lee una detección **del proyecto** del perímetro: la capa de restricciones de polígonos (papel de
    la 012) si es un dato registrado y las claves de «activa» de las restricciones que han formado el perímetro que
    tienen valor en el proyecto (``begin_operation`` solo resuelve claves del almacén)."""
    table = CONSTRAINT_LAYERS[GeometryKind.POLYGON]
    uses = ((Use(table, CONSTRAINT_ROLES[GeometryKind.POLYGON]),) if table in available_tables(project) else ())
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(conn, tuple(keys), (PROJECT_SCOPE,)) if keys else {}
    return uses, tuple(key for key in keys if key in found)


# --- Preparar -----------------------------------------------------------------------------------


def prepare_detection_units(project: StoreProject, request: StockpileRequest, *, version: str | None,
                            masks: access.MaskSet | access.MaskSource | None = None, code: str | None = None,
                            supersedes: str | None = None) -> Generator[None, None, PreparedDetection]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan la detección ``request``:
    su ámbito por la superficie (:func:`detection_scope`; ``version``, uid o código de la versión activa, o ``None``), el
    código y el nombre único (:func:`_identify`; ``code``: el de una entidad que ya está en su ámbito, que no choca consigo
    misma), la capa de marcas con sus campos y sus marcas rasterizadas (:func:`mark_cells`), los parámetros resueltos
    (:func:`detection_values`), la superficie de detección y las de base propia de las marcas leídas por pasos y
    comparadas con la rejilla del proyecto antes de leer una celda (``design.surfaces.read_surface_steps``), las marcas
    solapadas, el perímetro (con candidatos) y lo que anotará la operación. En una detección **de versión** las máscaras
    de la versión son entradas (``masks``: las ya al día; sin ellas, se cargan —y se compilan, como operación propia, si no
    lo están—); en una **del proyecto** no hay máscaras: el perímetro sale de la restricción del proyecto y no se consume
    ningún dato de versión (RF-009-05). ``supersedes``: la operación hecha a la que sustituye (un recálculo).

    **Nada se escribe** (RF-015-03) y la detección **no llama a** ``refuse_pending``: no mueve celdas. Los rechazos salen al
    avanzar, en el orden de la documentación del módulo."""
    scope, found = detection_scope(project, request, version)
    chosen = _identify(project, request, found, code)
    yield
    layer_name = request.fields.layer
    candidates = bool(request.candidates)
    frame = project_frame(project)
    grid = frame.grid
    marks, fids = yield from _read_marks(project, request, grid, candidates=candidates)
    values, defaulted = detection_values(request, chosen)
    yield
    threshold = _presence_threshold(project, found)
    surface = yield from read_surface_steps(project, request.surface, version_uid="" if found is None else found.uid,
                                            expect=frame, role=_SURFACE_ROLE)
    bases: dict[str, np.ndarray] = {}
    for mark in marks:
        if mark.base is not None and mark.base not in bases:
            raster = yield from read_surface_steps(project, mark.base, version_uid="", expect=frame,
                                                   role=f"superficie de base de la marca «{mark.key}»")
            bases[mark.base] = raster.values
    _check_overlaps(marks, grid)
    perimeter: np.ndarray | None = None
    perimeter_uses: tuple[Use, ...] = ()
    perimeter_params: tuple[str, ...] = ()
    if found is not None:
        loaded = masks if masks is not None else _loaded_masks(project, found, None)
        if candidates:
            perimeter = _version_perimeter(loaded, grid)
    else:
        loaded = None
        if candidates:
            perimeter, keys = _project_perimeter(project, grid)
            perimeter_uses, perimeter_params = _perimeter_inputs(project, keys)
    yield
    plane = PlaneParams(
        values[StockpileParam.CROWN_INNER.value], values[StockpileParam.CROWN_OUTER.value],
        values[StockpileParam.CROWN_SLOPE.value], values[StockpileParam.CROWN_FLAT_MIN.value],
        values[StockpileParam.MAX_RESIDUAL.value], values[StockpileParam.FIT_ROUNDS.value],
        values[StockpileParam.TILT_MAX.value], values[StockpileParam.SUPPORT_QUANTILE.value])
    footprint = FootprintParams(plane, values[StockpileParam.MARGIN.value], values[StockpileParam.TURNS.value],
                                threshold)
    wanted = None if not candidates else CandidateParams(
        values[StockpileParam.OPEN_DIAMETER.value], values[StockpileParam.MIN_HEIGHT.value],
        values[StockpileParam.MIN_AREA.value], values[StockpileParam.MAX_AREA.value], footprint)
    job = StockpileJob(request.name, chosen, grid, surface.values, marks, footprint, bases, wanted, perimeter)
    inputs = (*provenance.stockpile_inputs(request, request.surface, () if loaded is None else loaded.uses(),
                                           perimeter_uses),
              *(Use(base, provenance.SURFACE_ROLE) for base in bases))
    op_type = provenance.STOCKPILE_DETECT_PROJECT if found is None else provenance.STOCKPILE_DETECT
    begun = _start(project, op_type, request.name, found, None if found is None else loaded,  # type: ignore[arg-type]
                   provenance.stockpile_settings(request, chosen), tuple(dict.fromkeys(inputs)),
                   (*provenance.stockpile_params(chosen, request), *perimeter_params), supersedes)
    yield
    rows = _rows(request, chosen, values, defaulted)
    return PreparedDetection(job, begun, chosen, scope, found, request.surface, layer_name, fids, rows,
                             MappingProxyType(values), code is not None)


def prepare_detection(project: StoreProject, request: StockpileRequest, *, version: str | None,
                      masks: access.MaskSet | access.MaskSource | None = None, code: str | None = None,
                      supersedes: str | None = None) -> PreparedDetection:
    """La preparación entera de :func:`prepare_detection_units` de una vez (plan 016 §5.3.1; sin ceder el hilo): la
    :class:`PreparedDetection`, con los mismos rechazos y sin escribir nada."""
    work = prepare_detection_units(project, request, version=version, masks=masks, code=code, supersedes=supersedes)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: PreparedDetection = stop.value
            return result
