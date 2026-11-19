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
``des.surface_mismatch``, ``des.surface_other_version``) y el nombre de un dato (``des.operation_name_repeated`` y ``_project``). Lo
que se rechaza de **un** acopio (la marca no da celdas sobre el umbral, falta terreno en su huella o su corona…, o **se solapa con otra
marca**) no es de la preparación: el cálculo lo informa en el resumen sin registrarlo (RF-016-04). Las marcas **solapadas** se apartan
al armar el trabajo (:func:`detection_job`, ``StockpileJob.refused``; spec 016, T48: antes rechazaban toda la detección, y con 100
marcas un solape bloqueaba 98): solo esas dos se rechazan, **nombrando las dos** (``des.stockpile_marks_overlap``, un aviso), y las demás
siguen.

**Calcular por pasos y el resumen** (T12; RF-016-04 a 08, RF-015-03, RF-015-13, RF-015-29, RNF-016-03 y 05): el homólogo de
``entity_store.platform_compute_steps`` y de ``platform_summary``.

- :func:`detection_compute_steps`: el cálculo que **comparten «Calcular», el recálculo y la reproducción**, sobre
  ``design.stockpiles.detect_steps`` (cada marca en su ventana de trabajo, A0, y todo por pasos de ``budget_s`` como mucho):
  sin proyecto y sin escribir nada; cerrar el generador a mitad lo cierra todo y no deja nada. **Devuelve** (``yield from``) el
  ``StockpileOutcome``.
- :func:`stockpile_summary` (puro) y :func:`detection_summary` (con el proyecto, para lo obsoleto): el
  :class:`~.preview.StockpileSummary` de lo calculado: la cabecera, las marcas **rechazadas** (marca, caso y lugar; no se
  registran), cada acopio con su plano, huella, volumen, espesor máximo y sus avisos y notas (RF-016-05, 06 y 07, una vez, con
  su lugar), los candidatos y **lo que quedará obsoleto al crear** (:func:`detection_obsolete`: con el mecanismo de la 015,
  ``entity_store._dependents``, lo que depende de lo que escribió la detección a la que sustituye).

**Crear, repetir y decidir** (T13; RF-016-02, RF-016-08, RF-016-09, RF-016-10, RF-015-01, RF-015-02, RF-015-04, RF-015-16;
RNF-016-03 y 07; D-15, D-23; P-14):

- :func:`create_detection_steps` (y :func:`create_detection`, de una vez; ``Calculation.create`` y ``create_steps``): prepara
  por pasos cada salida de la detección en su temporal —la tabla de acopios ``des_stk_`` y la de candidatos ``des_stc_``
  (:func:`stockpile_rows`, :func:`candidate_rows`), por material la base y el espesor dispersos ``des_stb_`` y ``des_stt_``, el
  terreno sin acopios ``des_stg_`` y la superficie con que se detectó ``des_stp_`` (solo en las huellas, P-4 y P-5) y el informe
  ``des_prp_`` (:func:`detection_report_rows`)— y las registra en **una** transacción con los parámetros de la entidad (todas
  sus filas, con su origen), la operación, los datos y las cifras con su ámbito (el acopio y el material). Es **la misma**
  operación en el proyecto y en una versión: el escritor de su ámbito (``design_writer``) es lo único que cambia. Sin ningún
  acopio no hay base, espesor, terreno ni superficie (``DesignWriter.omit``). **No modifica ninguna capa de entrada.**
- **Repetir** (RF-016-10): la identidad de un acopio es su marca (su clave): se calcula con el código de la entidad y
  sustituyendo a la operación vigente (``supersedes``); lo que dependía de lo que escribió queda obsoleto con su causa por la
  008 (el dato cambió) y los datos que la nueva ya no escribe (el material que dejó de tener acopios) pasan a «sustituidos»
  (:func:`_retire_vanished`).
- **Decidir** (RF-016-08, RF-016-10; P-14): las decisiones sobre los candidatos son el parámetro de texto ``decisions`` de la
  entidad (:func:`format_decisions`, :func:`parse_decisions`; sin decidir, :data:`EMPTY_DECISIONS`: toda detección lo lee), con
  la huella en tramos de cada candidato al decidir (:class:`CandidateDecision`). :func:`decide_candidate` lo cambia (historial,
  decisor y motivo; la detección queda obsoleta con su causa) y :func:`detection_compute_steps` las aplica: cada candidato tiene
  su clave ``c03`` y su estado (``StockpileOutcome.states``); el que comparte más de la mitad del área de cada huella con una
  decisión conserva su clave y su decisión (:func:`~.stockpiles.carry_decisions`); el convertido es un acopio más (una marca
  más del trabajo, con su clave) y deja de ser candidato.

Python puro (nivel 8), con numpy. ``design.stockpile_store`` es un módulo pesado de la 016: lo importan las órdenes al
usarlo, no ``bl`` al registrarse (``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.constraints.messages import ConstraintError
from ..core.constraints.model import ConstraintParam, GeometryKind, is_code
from ..core.constraints.params import param_key
from ..core.constraints.store import CONSTRAINT_LAYERS
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import LIVE_STATUSES
from ..core.errors import GeoblenderError
from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterRecord, ParameterStore, definition
from ..core.params.store import default_reason
from ..core.project.model import Progress
from ..core.provenance.operations import OperationHandle, Use
from ..core.provenance.recompute import RecomputeRequest
from ..core.provenance.stale import OPERATION as STALE_OPERATION
from ..core.provenance.stale import item_text
from ..core.timeutil import format_utc
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from ..gis.grid import Grid
from ..gis.masks import access
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.masks.combine import LEGAL_COMMAND, ClassBit, IncompleteConstraints
from ..gis.masks.provenance import CONSTRAINT_ROLES
from ..gis.masks.store import available_tables, declared_limits
from ..gis.masks.zones import limit_runs
from ..gis.messages import GisError
from ..gis.polygons import overlay, problem_steps
from ..gis.provenance import dataset_slug
from ..gis.raster import Raster
from ..gis.store import StoreProject, load_features
from ..gis.vector import FeatureLayer
from . import entities, pipeline, provenance
from .entities import EntityKind, EntityRegistry
from .entity_store import EntityParamRow, _consumer, _dependents, entity_parameters, set_entity_params
from .messages import DesignError
from .model import StockpileRequest
from .params import ANTHROPIC_PRESENCE, StockpileParam, check_entity_param, entity_key, entity_params
from .morphology import dilate
from .preview import (
    SUMMARY_ITEMS,
    CandidateCounts,
    CandidateLine,
    MarkPreview,
    Notice,
    Obsolete,
    ObsoleteKind,
    RejectedLine,
    StockpileLine,
    StockpilePreview,
    StockpileSummary,
    stockpile_obsolete_notices,
    zone_rings,
)
from .stockpiles import (
    CANDIDATE_CONVERTED,
    CANDIDATE_DISCARDED,
    CANDIDATE_PENDING,
    Candidate,
    CandidateParams,
    CandidateState,
    FootprintParams,
    PlaneParams,
    Stockpile,
    StockpileJob,
    StockpileMark,
    StockpileOutcome,
    _figures,
    _window_cells,
    carry_decisions,
    detect_steps,
    footprint_runs,
    refuse_overlaps,
    runs_cells,
)
from .store import (
    DesignWriter,
    OperationStart,
    Stored,
    _loaded_masks,
    _start,
    _store_steps,
    columns_of,
    design_writer,
    require_version,
)
from .surfaces import find_surface, project_frame, read_surface_steps
from .zones import _paint, _polygon_spans, to_cell_units

__all__ = [
    "EMPTY_DECISIONS",
    "PROJECT",
    "VERSION",
    "CandidateDecision",
    "Detection",
    "DetectionData",
    "DetectionMaterial",
    "ExcludedDetection",
    "PreparedDetection",
    "candidate_decision",
    "candidate_row_notice",
    "candidate_rows",
    "create_detection",
    "create_detection_steps",
    "decide_candidate",
    "detection_compute_steps",
    "detection_job",
    "detection_obsolete",
    "detection_report_rows",
    "detection_scope",
    "detection_summary",
    "detection_values",
    "detections_excluded",
    "detections_on",
    "format_decisions",
    "mark_cells",
    "marks_of_layer",
    "material_dataset",
    "material_label",
    "parse_decisions",
    "prepare_detection",
    "prepare_detection_units",
    "preview_marks_units",
    "read_detection_table",
    "read_stored_rows",
    "recompute_detection",
    "run_detection",
    "stockpile_rows",
    "stockpile_row_notice",
    "stockpile_rows_of",
    "stockpile_summary",
    "stored_notes",
    "version_perimeter",
]

EXCLUDED_OTHER_SURFACE = "other_surface"
"""Por qué una detección no se usa sobre una superficie: se hizo sobre otra (:class:`ExcludedDetection`)."""
EXCLUDED_STALE = "stale"
"""Por qué una detección no se usa sobre una superficie: está obsoleta (:class:`ExcludedDetection`)."""
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
_COMPUTE_PHASE = "stockpile_compute"
_DECIDE_PHASE = "stockpile_decide"
_DECIDE_SOURCE = "lista de candidatos de la detección «{name}»"


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
    «Crear» no escribe otra vez sus parámetros. ``decisions``: las decisiones sobre los candidatos de la entidad (el parámetro
    ``decisions``, P-14), que aplica el cálculo (:func:`detection_compute_steps`)."""

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
    decisions: tuple[CandidateDecision, ...] = ()

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
    decisions = request.decisions
    if decisions is None:  # sin decisiones: el texto vacío válido, que la operación lee (cambiarlo la deja obsoleta)
        decisions = EMPTY_DECISIONS
        defaulted.add(StockpileParam.DECISIONS.value)
    asked: dict[StockpileParam, object] = {
        StockpileParam.NAME: request.name, StockpileParam.LAYER: layer, StockpileParam.SURFACE: request.surface,
        StockpileParam.CANDIDATES: bool(request.candidates), StockpileParam.DECISIONS: decisions,
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
    return _polygon_layer(load_features(project, name), name)


def _polygon_layer(found: object, name: str) -> FeatureLayer:
    """``found`` (la capa de marcas ``name``) como capa de **polígonos** (``des.layer_not_polygons``); ``ValueError`` si no es
    una capa de entidades. Lo comparten preparar (del proyecto) y reproducir (de lo congelado)."""
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


def _read_marks(project: StoreProject, request: StockpileRequest, grid: Grid, *, candidates: bool
                ) -> Generator[None, None, tuple[tuple[StockpileMark, ...], Mapping[str, int]]]:
    """Las marcas de la capa de la petición como ``StockpileMark`` (rasterizadas, con su margen, material y base) y el
    ``fid`` de cada una por su clave, con los rechazos de la capa, sus campos, sus nombres, sus márgenes, sus polígonos y
    una capa sin marcas ni candidatos (:func:`prepare_detection_units` da el orden)."""
    layer = _marks_layer(project, request.fields.layer)
    return (yield from marks_of_layer(layer, request, grid, candidates=candidates))


def marks_of_layer(layer: object, request: StockpileRequest, grid: Grid, *, candidates: bool
                   ) -> Generator[None, None, tuple[tuple[StockpileMark, ...], Mapping[str, int]]]:
    """Las marcas de ``layer`` —la capa de marcas de la petición, leída del proyecto (:func:`prepare_detection_units`) o de
    lo congelado (``design.reproduce``: el mismo cálculo)— como ``StockpileMark`` (rasterizadas en ``grid``, con su margen,
    material y base) y el ``fid`` de cada una por su clave. Los rechazos son los de :func:`_read_marks`."""
    fields, layer_name = request.fields, request.fields.layer
    layer = _polygon_layer(layer, layer_name)
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


def version_perimeter(masks: access.MaskSet | access.MaskSource, grid: Grid) -> np.ndarray:
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


def _check_materials(marks: Sequence[StockpileMark], layer: str) -> None:
    """Los materiales de las marcas dan, cada uno, un nombre de dato distinto (D-19: una base y un espesor por material, un
    dato cada uno): «Estéril» y «estéril» darían el mismo (``des_stb_<det>_esteril``) y se pisarían al crear. También el que
    daría «sin material» a los acopios sin él. ``des.stockpile_material_repeated`` nombrando los dos."""
    seen = {dataset_slug(_NO_MATERIAL): _NO_MATERIAL}
    for mark in marks:
        if mark.material is None:
            continue
        slug = dataset_slug(mark.material)
        other = seen.setdefault(slug, mark.material)
        if other != mark.material:
            raise DesignError("des.stockpile_material_repeated", obj=f"Marca «{mark.name}»", field="material",
                              value=mark.material, other=other, layer=layer)


# --- Preparar -----------------------------------------------------------------------------------


def detection_job(request: StockpileRequest, code: str, values: Mapping[str, Any], grid: Grid, surface: np.ndarray,
                  marks: Sequence[StockpileMark], bases: Mapping[str, np.ndarray], perimeter: np.ndarray | None,
                  threshold: float) -> StockpileJob:
    """El ``StockpileJob`` de la detección ``request`` de código ``code``: todo lo leído y nada del proyecto. ``values``
    son los parámetros resueltos (:func:`detection_values`), ``surface`` y ``bases`` las rejillas leídas, ``marks`` las marcas
    rasterizadas, ``perimeter`` el de actuación (solo si se piden candidatos) y ``threshold`` el umbral de la huella de la 011.
    Lo comparten preparar (del proyecto) y reproducir (de lo congelado): el mismo trabajo, el mismo cálculo. **Las marcas que se solapan se
    apartan aquí** (RF-016-04, spec 016, T48: :func:`~.stockpiles.refuse_overlaps`; ``StockpileJob.refused``): solo esas dos se rechazan y las
    demás siguen, y como lo hace este paso lo hacen igual preparar y reproducir."""
    plane = PlaneParams(
        values[StockpileParam.CROWN_INNER.value], values[StockpileParam.CROWN_OUTER.value],
        values[StockpileParam.CROWN_SLOPE.value], values[StockpileParam.CROWN_FLAT_MIN.value],
        values[StockpileParam.MAX_RESIDUAL.value], values[StockpileParam.FIT_ROUNDS.value],
        values[StockpileParam.TILT_MAX.value], values[StockpileParam.SUPPORT_QUANTILE.value])
    footprint = FootprintParams(plane, values[StockpileParam.MARGIN.value], values[StockpileParam.TURNS.value],
                                threshold)
    wanted = None if not values[StockpileParam.CANDIDATES.value] else CandidateParams(
        values[StockpileParam.OPEN_DIAMETER.value], values[StockpileParam.MIN_HEIGHT.value],
        values[StockpileParam.MIN_AREA.value], values[StockpileParam.MAX_AREA.value], footprint)
    kept, refused = refuse_overlaps(marks, grid)
    return StockpileJob(request.name, code, grid, surface, kept, footprint, bases, wanted, perimeter, refused)


def prepare_detection_units(project: StoreProject, request: StockpileRequest, *, version: str | None,
                            masks: access.MaskSet | access.MaskSource | None = None, code: str | None = None,
                            supersedes: str | None = None) -> Generator[None, None, PreparedDetection]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan la detección ``request``:
    su ámbito por la superficie (:func:`detection_scope`; ``version``, uid o código de la versión activa, o ``None``), el
    código y el nombre único (:func:`_identify`; ``code``: el de una entidad que ya está en su ámbito, que no choca consigo
    misma), la capa de marcas con sus campos y sus marcas rasterizadas (:func:`mark_cells`), los parámetros resueltos
    (:func:`detection_values`), la superficie de detección y las de base propia de las marcas leídas por pasos y
    comparadas con la rejilla del proyecto antes de leer una celda (``design.surfaces.read_surface_steps``), las marcas
    el perímetro (con candidatos) y lo que anotará la operación (las marcas solapadas se apartan en el trabajo, T48). En una detección **de versión** las máscaras
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
    _check_materials(marks, layer_name)
    values, defaulted = detection_values(request, chosen)
    decisions = parse_decisions(values[StockpileParam.DECISIONS.value], entity=request.name)
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
    perimeter: np.ndarray | None = None
    perimeter_uses: tuple[Use, ...] = ()
    perimeter_params: tuple[str, ...] = ()
    if found is not None:
        loaded = masks if masks is not None else _loaded_masks(project, found, None)
        if candidates:
            perimeter = version_perimeter(loaded, grid)
    else:
        loaded = None
        if candidates:
            perimeter, keys = _project_perimeter(project, grid)
            perimeter_uses, perimeter_params = _perimeter_inputs(project, keys)
    yield
    job = detection_job(request, chosen, values, grid, surface.values, marks, bases, perimeter, threshold)
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
                             MappingProxyType(values), code is not None, decisions)


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


# --- La vista previa de las marcas (spec 016, T32; RF-016-23, RF-015-26) ---------------------------------------


def _mark_preview(mark: StockpileMark, grid: Grid, default_margin_m: float) -> MarkPreview:
    """La :class:`~.preview.MarkPreview` de ``mark`` (rasterizada en ``grid``): el contorno de sus celdas y el de la marca ampliada por su
    margen (el de su campo o ``default_margin_m``: la dilatación de sus celdas con un disco de ese radio, :func:`~.morphology.dilate`,
    en una ventana con el margen de sobra y recortada a la rejilla). Sin margen, la ampliada es la marca y no se dibuja dos veces."""
    margin = default_margin_m if mark.margin_m is None else float(mark.margin_m)
    rows, cols = np.divmod(mark.cells, grid.ncols)
    top, bottom = int(rows.min()), int(rows.max()) + 1
    left, right = int(cols.min()), int(cols.max()) + 1
    reach = math.ceil(margin / grid.dx) + 1
    first, last = max(0, top - reach), min(grid.nrows, bottom + reach)
    west, east = max(0, left - reach), min(grid.ncols, right + reach)
    window = np.zeros((last - first, east - west), dtype=bool)
    window[rows - first, cols - west] = True
    own = zone_rings(entities.declared_zone(window, grid, 0.0, offset=(first, west)))
    enlarged: tuple[np.ndarray, ...] = ()
    enlarged_cells = int(mark.cells.size)
    if margin > 0.0:
        grown = dilate(window, margin, grid.dx)
        enlarged = zone_rings(entities.declared_zone(grown, grid, 0.0, offset=(first, west)))
        enlarged_cells = int(np.count_nonzero(grown))
    return MarkPreview(
        mark.key, str(mark.name), mark.material, mark.base, margin, mark.margin_m is not None, int(mark.cells.size),
        float(mark.cells.size) * grid.cell_area, own, enlarged, enlarged_cells,
        float(grid.west + (left + right) / 2.0 * grid.dx), float(grid.north - (top + bottom) / 2.0 * grid.dy))


def preview_marks_units(project: StoreProject, request: StockpileRequest, *, version: str | None
                        ) -> Generator[None, None, StockpilePreview]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan la **vista previa de las marcas** de la
    detección ``request`` (RF-016-23; ``design.preview.stockpile_preview_steps``): lo que leerá la detección de su capa de marcas, sin
    calcular nada. Es el principio de :func:`prepare_detection_units` —el ámbito por la superficie, el código y el nombre únicos, la
    capa, sus campos, sus polígonos rasterizados, los materiales, los parámetros, en el mismo orden y con los
    mismos mensajes— **sin leer la superficie ni las bases ni el perímetro ni cargar las máscaras** (la detección de una versión las
    compilaría, y esto no escribe) y con el contorno de cada marca y de su ampliada por el margen (:func:`_mark_preview`). Lo que de
    eso rechazaría la preparación (``GeoblenderError``) no se lanza: sale en ``StockpilePreview.refusal``, sin marcas. **Las marcas
    solapadas no son un rechazo** (RF-016-04, T48: solo esas dos se rechazan al calcular): se dibujan todas y se **avisa de cada pareja**
    (``des.stockpile_marks_overlap``, el mismo aviso y el mismo texto que «Calcular», una vez por pareja). **Nada se escribe.**"""
    scope, code, found = "", "", None
    try:
        scope, found = detection_scope(project, request, version)
        code = _identify(project, request, found, None)
        yield
        grid = project_frame(project).grid
        candidates = bool(request.candidates)
        marks, _fids = yield from _read_marks(project, request, grid, candidates=candidates)
        _check_materials(marks, request.fields.layer)
        values, _defaulted = detection_values(request, code)
    except GeoblenderError as refused:  # lo que rechazaría «Calcular»: es el aviso de la vista previa
        return StockpilePreview(request.name, code, scope, "" if found is None else found.code,
                                request.surface, request.fields.layer, refusal=refused)
    yield
    margin = float(values[StockpileParam.MARGIN.value])
    drawn: list[MarkPreview] = []
    for mark in marks:
        drawn.append(_mark_preview(mark, grid, margin))
        yield
    where = "" if found is None else found.code
    header = {"entity": request.name, "code": code, "marks": len(drawn), "area": sum(item.area_m2 for item in drawn),
              "surface": request.surface, "margin": margin}
    notices = [Notice("des.preview_stockpile_project" if found is None else "des.preview_stockpile",
                      header if found is None else {**header, "version": where})]
    told: set[int] = set()
    for item in refuse_overlaps(marks, grid)[1]:  # las marcas solapadas se rechazarán al calcular: se dicen, una vez por pareja (T48)
        if id(item.notice) not in told:
            told.add(id(item.notice))
            notices.append(item.notice)
    if candidates:
        notices.append(Notice("des.preview_stockpile_candidates"))
    return StockpilePreview(request.name, code, scope, where, request.surface, request.fields.layer, tuple(drawn), margin, candidates,
                            float(max(grid.dx, grid.dy)), tuple(notices))


# --- Calcular por pasos (spec 016, T12; RF-016-04, 05, 08, RF-015-29, RNF-016-03, 05) ------------


def detection_compute_steps(job: StockpileJob, *, decisions: Sequence[CandidateDecision] = (),
                            budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, StockpileOutcome]:
    """Los pasos que calculan la detección de ``job`` (RF-016-04, 05, 08, RF-015-29; plan 016 §5.3.2: el
    ``detection_compute_steps`` que **comparten «Calcular», el recálculo y la reproducción**, como
    ``entity_store.platform_compute_steps`` lo es de la plataforma), sin proyecto y sin escribir nada (``yield from``;
    cerrar el generador no deja nada y no toca ninguna entrada): ``design.stockpiles.detect_steps`` —cada marca en su ventana de
    trabajo (A0), el reparto de las celdas comunes, las bases, los espesores y el terreno sin acopios y, si se piden, los
    candidatos— por pasos de ``budget_s`` como mucho. El primer paso sale antes de calcular nada. Los acopios que no se
    pueden formar (RF-016-04) **no paran** el cálculo: salen en ``StockpileOutcome.rejected``. Un ``job`` que no es un
    ``StockpileJob`` es un ``TypeError`` (un error del programa) al avanzar. Devuelve el
    :class:`~.stockpiles.StockpileOutcome`.

    ``decisions`` (spec 016, T13; RF-016-08, RF-016-10, D-23): las decisiones de las personas sobre los candidatos (el
    parámetro ``decisions`` de la entidad, :func:`parse_decisions`). Con candidatos pedidos, cada uno recibe su clave y su
    estado (``StockpileOutcome.states``) y los convertidos pasan a ser acopios de la detección (:func:`_decide_steps`);
    sin ellas, todos son ``pending`` con las claves ``c01``…"""
    if not isinstance(job, StockpileJob):
        raise TypeError(f"la detección calcula un StockpileJob, no {job!r}")
    name = job.name
    yield Progress(_COMPUTE_PHASE, 0, 1, f"Detectando los acopios de «{name}»…")
    outcome: StockpileOutcome = yield from pipeline.forward(detect_steps(job, budget_s=budget_s))
    outcome = yield from _decide_steps(job, outcome, tuple(decisions), budget_s)
    yield Progress(_COMPUTE_PHASE, 1, 1, f"Acopios de «{name}» detectados")
    return outcome


# --- El resumen (spec 016, T12; RF-016-04 a 08, RF-015-03, RF-015-13) ----------------------------


def detection_obsolete(project: StoreProject, prepared: PreparedDetection, *, supersedes: str | None = None
                       ) -> tuple[Obsolete, ...]:
    """**Lo que quedará obsoleto al crear** la detección ``prepared`` (RF-015-03, RF-016-10, RF-015-16; del grafo de la 008,
    sin escribir; con el mecanismo de la 015, ``entity_store._dependents``): una detección nueva no deja obsoleto nada; la que
    **sustituye** una operación (``supersedes``: un recálculo o repetirla) deja obsoleto lo que dependía de lo que escribió, en
    cascada (``ObsoleteKind.DEPENDENT``: una retirada, un contrafuerte, una plataforma sobre su huella, la cubicación…), sin la
    propia sustituida. Si la detección es **de una versión**, las operaciones vigentes de esa versión; si es **del proyecto**,
    las del proyecto y las de cualquier versión (una versión puede consumir un dato del proyecto, no al revés, RF-009-05). Solo
    lee."""
    if supersedes is None:
        return ()
    with project.read() as conn:
        written = [str(row[0]) for row in conn.execute(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' "
            "AND item_kind = 'dataset' ORDER BY fid", (supersedes,))]
        found = _dependents(conn, written, prepared.version_uid, exclude=(supersedes,))
    if prepared.version is None:  # sin versión no hay a qué versión llamar «la capa de entidades de V01»
        return tuple(Obsolete(ObsoleteKind.DEPENDENT, name, op_type, uid) for uid, op_type, name in found)
    return tuple(_consumer(ObsoleteKind.DEPENDENT, uid, op_type, name) for uid, op_type, name in found)


def _stockpile_line(item: Stockpile) -> StockpileLine:
    """El renglón de un acopio registrado."""
    return StockpileLine(item.key, item.name, item.material, item.base_surface, item.area_m2, item.volume_m3,
                         item.thickness_max_m, item.plane_level_m, item.plane_slope_percent, item.plane_azimuth_deg,
                         item.plane_tilt_deg, item.x, item.y, item.notes)


def _candidate_line(number: int, item: Candidate) -> CandidateLine:
    """El renglón de un candidato: su huella, su volumen y su plano en el centro (``Candidate.footprint``)."""
    plane = item.footprint.plane
    assert plane is not None  # un candidato se forma como una marca: con plano (la base propia es de las marcas)
    x, y = item.centre
    return CandidateLine(number, item.footprint.area_m2, item.footprint.volume_m3, float(plane.at(x, y)),
                         plane.slope_percent, plane.azimuth_deg, x, y)


def _item_notice(item: Stockpile) -> Notice:
    """La línea del resumen de un acopio: su huella, volumen y espesor máximo y su plano o la superficie de su base."""
    values: dict[str, object] = {
        "mark": item.name, "material": _NO_VALUE if item.material is None else item.material, "area": item.area_m2,
        "volume": item.volume_m3, "thickness": item.thickness_max_m, "x": item.x, "y": item.y}
    if item.plane is None:
        return Notice("des.stockpile_item_own_base", {**values, "base": str(item.base_surface)})
    return Notice("des.stockpile_item", {**values, "level": item.plane_level_m, "slope": item.plane_slope_percent,
                                         "azimuth": item.plane_azimuth_deg})


def stockpile_row_notice(row: Mapping[str, Any]) -> Notice:
    """La línea de un acopio **guardado** (una fila de ``des_stk_``, :func:`read_stored_rows`; spec 016, T33; RF-015-25): la misma nota que da
    el resumen de «Calcular» (:func:`_item_notice`: huella, volumen, espesor máximo y plano de base o la superficie de su base propia), con
    lo que dice la tabla. Una nota (``des.stockpile_item`` o ``des.stockpile_item_own_base``): su texto, en el idioma de quien la lea."""
    values: dict[str, object] = {
        "mark": row["name"], "material": _NO_VALUE if row["material"] is None else row["material"], "area": row["area_m2"],
        "volume": row["volume_m3"], "thickness": row["thickness_max_m"], "x": row["x"], "y": row["y"]}
    if row["plane_level_m"] is None:  # con una base propia no hay plano ajustado
        return Notice("des.stockpile_item_own_base", {**values, "base": str(row["base_surface"])})
    return Notice("des.stockpile_item", {**values, "level": row["plane_level_m"], "slope": row["plane_slope_percent"],
                                         "azimuth": row["plane_azimuth_deg"]})


def candidate_row_notice(row: Mapping[str, Any]) -> Notice:
    """La línea de un candidato **guardado** (una fila de ``des_stc_``; spec 016, T33; RF-016-08): su clave (``c03``), su huella, su volumen y su
    plano en el centro, como la nota ``des.stockpile_candidate_item`` del resumen de «Calcular» (que lo numera; aquí, por su clave)."""
    return Notice("des.stockpile_candidate_item", {
        "candidate": row["key"], "area": row["area_m2"], "volume": row["volume_m3"], "level": row["plane_level_m"],
        "slope": row["plane_slope_percent"], "azimuth": row["plane_azimuth_deg"], "x": row["x"], "y": row["y"]})


def stored_notes(row: Mapping[str, Any]) -> tuple[Notice, ...]:
    """Los avisos y notas **guardados** de un acopio (``notes`` de su fila de ``des_stk_``: JSON con el código, la gravedad y los valores, no el
    texto; :func:`stockpile_rows_of`) como :class:`~.preview.Notice`, en su orden; ``()`` si no tiene. ``ValueError`` si no es una lista de
    avisos. Su texto, en el idioma de quien lo lea (:meth:`~.preview.Notice.text`)."""
    found = json.loads(str(row["notes"]))
    if not isinstance(found, list):
        raise ValueError(f"las notas de un acopio son una lista, no {found!r}")
    notices: list[Notice] = []
    for item in found:
        if not isinstance(item, dict) or not isinstance(item.get("code"), str) or not isinstance(item.get("values", {}), dict):
            raise ValueError(f"una nota de un acopio es un código con sus valores, no {item!r}")
        notices.append(Notice(item["code"], item.get("values", {})))
    return tuple(notices)


def _candidate_notices(lines: tuple[CandidateLine, ...], counts: CandidateCounts) -> tuple[Notice, ...]:
    """Las notas de los candidatos: cuántos hay y qué se descartó sin listarlo, los :data:`SUMMARY_ITEMS` primeros y una nota
    con los que faltan."""
    found = [Notice("des.stockpile_candidates", {
        "candidates": len(lines), "zones": counts.zones, "on_marks": counts.on_marks, "out_of_range": counts.filtered,
        "rejected": counts.rejected})]
    for line in lines[:SUMMARY_ITEMS]:
        found.append(Notice("des.stockpile_candidate_item", {
            "candidate": line.number, "area": line.area_m2, "volume": line.volume_m3, "level": line.plane_level_m,
            "slope": line.plane_slope_percent, "azimuth": line.plane_azimuth_deg, "x": line.x, "y": line.y}))
    if len(lines) > SUMMARY_ITEMS:
        found.append(Notice("des.stockpile_more_candidates", {"candidates": len(lines) - SUMMARY_ITEMS}))
    return tuple(found)


def stockpile_summary(outcome: StockpileOutcome, *, version: str | None, scope: str,
                      obsolete: Iterable[Obsolete] = ()) -> StockpileSummary:
    """El resumen de «Calcular» la detección ``outcome`` (RF-015-03, RF-016-04 a 08; puro: sin proyecto): la cabecera, las
    marcas **rechazadas** nombrando marca, caso y lugar (no se registran), cada acopio con su línea (huella, volumen, espesor
    máximo y plano o base propia) y sus avisos y notas (RF-016-05, 06 y 07; los del reparto de celdas, **una vez** aunque estén en
    los dos acopios), los candidatos (si se pidieron: cuántos, lo que se descartó sin listarlo y los primeros
    :data:`~.preview.SUMMARY_ITEMS`) y, al final, lo que quedará obsoleto (``obsolete``: :func:`detection_obsolete`). ``version``
    es el código de la versión (``None``: es del proyecto) y ``scope``, :data:`PROJECT` o :data:`VERSION`."""
    kept = tuple(obsolete)
    lines = tuple(_stockpile_line(item) for item in outcome.stockpiles)
    rejected = tuple(RejectedLine(item.key, item.name, item.notice) for item in outcome.rejected)
    candidates: tuple[CandidateLine, ...] | None = None
    counts: CandidateCounts | None = None
    found = outcome.candidates
    if found is not None:
        candidates = tuple(_candidate_line(number, item) for number, item in enumerate(found.items, start=1))
        counts = CandidateCounts(found.zones, found.on_marks, found.too_small, found.too_large, found.rejected)
    head: dict[str, object] = {
        "entity": outcome.name, "code": outcome.code, "stockpiles": len(lines),
        "area": math.fsum(item.area_m2 for item in outcome.stockpiles),
        "volume": math.fsum(item.volume_m3 for item in outcome.stockpiles), "rejected": len(rejected)}
    if candidates is not None:
        head["candidates"] = len(candidates)
    notices: list[Notice] = [Notice("des.stockpile_summary", head)]
    told: set[int] = set()
    for line in rejected:  # dos marcas rechazadas por solaparse comparten el aviso de su pareja: una sola línea (T48)
        if id(line.notice) not in told:
            told.add(id(line.notice))
            notices.append(line.notice)
    for item in outcome.stockpiles:
        notices.append(_item_notice(item))
        for note in item.notes:
            if id(note) not in told:  # el aviso de dos acopios que se reparten celdas es uno, y está en los dos
                told.add(id(note))
                notices.append(note)
    if candidates is not None and counts is not None:
        notices.extend(_candidate_notices(candidates, counts))
    notices.extend(stockpile_obsolete_notices(outcome.name, version or "", kept))
    return StockpileSummary(outcome.name, outcome.code, version, scope, outcome.figures, lines, rejected, candidates,
                            counts, tuple(notices), kept)


def detection_summary(project: StoreProject, prepared: PreparedDetection, outcome: StockpileOutcome, *,
                      supersedes: str | None = None) -> StockpileSummary:
    """El resumen de «Calcular» la detección ``prepared`` (RF-015-03, RF-016-04 a 08): :func:`stockpile_summary` de su
    ``outcome``, con lo que quedará obsoleto al crearla (:func:`detection_obsolete`: lo que dependía de la operación
    ``supersedes``, si la hay). Solo lee."""
    obsolete = detection_obsolete(project, prepared, supersedes=supersedes)
    return stockpile_summary(outcome, version=None if prepared.version is None else prepared.version.code,
                             scope=prepared.scope, obsolete=obsolete)


# --- Las decisiones sobre los candidatos (spec 016, T13; RF-016-08, RF-016-10, D-23; plan 016 P-14) --------------------


EMPTY_DECISIONS = '{"decisions":[]}'
"""El valor del parámetro ``decisions`` de una detección **sin** decisiones: un texto válido (no en blanco: el almacén de
parámetros no guarda un texto vacío) con la lista vacía. Toda detección lo lleva desde que se crea, así que decidir sobre un
candidato es **cambiar** un parámetro que la operación ya lee y la deja obsoleta con su causa."""
_CANDIDATE_KEY = re.compile(r"^c\d{2,}$")
_DECISION_STATES = (CANDIDATE_CONVERTED, CANDIDATE_DISCARDED)
_NO_MATERIAL = "sin material"
"""La etiqueta del dato de la base y del espesor de los acopios sin material (los de las marcas que no lo dan y los
candidatos convertidos)."""
_CANDIDATE_NAME = "Candidato {key}"


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    """La decisión de una persona sobre un candidato sin marca (RF-016-08, RF-016-10; P-14): su ``key`` (``c03``), el
    ``state`` (:data:`~.stockpiles.CANDIDATE_CONVERTED` —pasa a ser un acopio de la detección con esa clave— o
    :data:`~.stockpiles.CANDIDATE_DISCARDED`), el ``reason`` (siempre), el decisor, la fecha (``decided_on``, ISO) y **la
    huella en tramos** (``runs``: ``(fila, primera columna, columna final excluida)``) que tenía el candidato al decidir: con
    ella se reconoce al repetir la detección (D-23: más de la mitad del área de cada huella), sin el proyecto ni la operación
    anterior."""

    key: str
    state: str
    reason: str
    decided_by: str
    decided_on: str
    runs: tuple[tuple[int, int, int], ...]

    def cells(self, ncols: int) -> np.ndarray:
        """Las celdas de la huella (``fila · ncols + columna``, ``int64``) en una rejilla de ``ncols`` columnas."""
        return runs_cells(np.array(self.runs, dtype=np.int64).reshape(-1, 3), ncols)


def _invalid_decisions(entity: str, detail: str) -> DesignError:
    return DesignError("des.stockpile_decisions_invalid", obj=f"Detección de acopios «{entity}»",
                       field=StockpileParam.DECISIONS.value, value=None, entity=entity, detail=detail)


def _decision_from(entity: str, found: object) -> CandidateDecision:
    """Una decisión leída del JSON ``found`` (``des.stockpile_decisions_invalid`` si no lo es)."""
    if not isinstance(found, dict):
        raise _invalid_decisions(entity, "cada decisión es un objeto")
    texts = []
    for name in ("key", "state", "reason", "decided_by", "decided_on"):
        value = found.get(name)
        if not isinstance(value, str) or not value.strip():
            raise _invalid_decisions(entity, f"falta «{name}» o no es un texto")
        texts.append(value)
    key, state, reason, who, when = texts
    if _CANDIDATE_KEY.match(key) is None:
        raise _invalid_decisions(entity, f"«{key}» no es la clave de un candidato (c01, c02…)")
    if state not in _DECISION_STATES:
        raise _invalid_decisions(entity, f"el estado de «{key}» es «{state}»: es «{CANDIDATE_CONVERTED}» o "
                                         f"«{CANDIDATE_DISCARDED}»")
    runs = found.get("runs")
    if not isinstance(runs, list):
        raise _invalid_decisions(entity, f"la huella de «{key}» no es una lista de tramos")
    parsed: list[tuple[int, int, int]] = []
    for run in runs:
        if (not isinstance(run, list) or len(run) != 3
                or any(isinstance(item, bool) or not isinstance(item, int) for item in run)
                or run[0] < 0 or not 0 <= run[1] < run[2]):
            raise _invalid_decisions(entity, f"un tramo de la huella de «{key}» no es [fila, columna primera, columna "
                                             "final] (0 ≤ primera < final)")
        parsed.append((run[0], run[1], run[2]))
    return CandidateDecision(key, state, reason, who, when, tuple(parsed))


def parse_decisions(text: str | None, *, entity: str = _NO_VALUE) -> tuple[CandidateDecision, ...]:
    """Las decisiones del texto del parámetro ``decisions`` (:data:`EMPTY_DECISIONS` o lo que da
    :func:`format_decisions`): ``None``, un texto en blanco y la lista vacía no tienen ninguna. ``des.stockpile_decisions_invalid``
    (nombrando ``entity`` y qué falla) si no es JSON, no es la lista de decisiones, una decisión no lleva sus campos o su
    estado es otro que convertido o descartado, o dos llevan la misma clave."""
    if text is None or not text.strip():
        return ()
    try:
        loaded = json.loads(text)
    except ValueError:
        raise _invalid_decisions(entity, "no es JSON") from None
    items = loaded.get("decisions") if isinstance(loaded, dict) else None
    if not isinstance(items, list):
        raise _invalid_decisions(entity, "falta la lista «decisions»")
    found = tuple(_decision_from(entity, item) for item in items)
    keys = [item.key for item in found]
    for key in keys:
        if keys.count(key) > 1:
            raise _invalid_decisions(entity, f"la clave «{key}» está dos veces")
    return found


def format_decisions(decisions: Iterable[CandidateDecision]) -> str:
    """El texto del parámetro ``decisions`` con ``decisions`` (JSON compacto y estable: :func:`parse_decisions` lo lee
    igual, en el mismo orden)."""
    return json.dumps({"decisions": [
        {"key": item.key, "state": item.state, "reason": item.reason, "decided_by": item.decided_by,
         "decided_on": item.decided_on, "runs": [list(run) for run in item.runs]} for item in decisions]},
        separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def candidate_decision(item: CandidateState, ncols: int, *, state: str, reason: str, decided_by: str,
                       decided_on: str) -> CandidateDecision:
    """La decisión ``state`` (convertido o descartado) con su ``reason`` de ``decided_by`` el día ``decided_on`` (ISO) sobre
    el candidato ``item`` (``StockpileOutcome.states``), con su huella en tramos en una rejilla de ``ncols`` columnas.
    ``ValueError`` si el estado no es convertido ni descartado o falta el motivo."""
    if state not in _DECISION_STATES:
        raise ValueError(f"se decide «{CANDIDATE_CONVERTED}» o «{CANDIDATE_DISCARDED}», no «{state}»")
    if not reason.strip():
        raise ValueError("una decisión sobre un candidato lleva su motivo")
    runs = tuple((int(row), int(first), int(last)) for row, first, last in footprint_runs(item.candidate.cells, ncols))
    return CandidateDecision(item.key, state, reason.strip(), decided_by, decided_on, runs)


def _decide_steps(job: StockpileJob, outcome: StockpileOutcome, decisions: Sequence[CandidateDecision], budget_s: float
                  ) -> Generator[Progress, None, StockpileOutcome]:
    """Da su clave y su estado a cada candidato de ``outcome`` (spec 016, T13; RF-016-08, RF-016-10, D-23) y convierte en
    acopios los que se decidió convertir: un candidato nuevo cuya huella comparte **más de la mitad del área de cada una**
    con la de una decisión (:func:`~.stockpiles.carry_decisions`, una decisión una sola vez) **conserva su clave y su
    decisión**; los demás son ``pending`` con la primera clave libre (``c01``, ``c02``… sin ninguna de las de las
    decisiones, que no se reutilizan aunque no coincidan con nadie). Cada convertido pasa a ser una **marca más** del
    trabajo (su zona, con la clave del candidato) y se detecta otra vez con ella (A2 a A5 y el reparto de las celdas: el mismo
    plano, la misma huella y el mismo volumen que como candidato, y el reparto con las demás marcas si se tocan); los
    candidatos que quedan son los no convertidos (los descartados siguen en la lista) y la zona del convertido cuenta como
    «con marca». Sin candidatos pedidos, el resultado no cambia."""
    found = outcome.candidates
    if found is None:
        return outcome
    yield Progress(_DECIDE_PHASE, 0, 1, "Aplicando las decisiones sobre los candidatos…")
    items, ncols = found.items, job.grid.ncols
    try:
        previous = [decision.cells(ncols) for decision in decisions]
    except ValueError as error:
        raise _invalid_decisions(job.name, str(error)) from None
    kept = carry_decisions([item.cells for item in items], previous)
    used = {decision.key for decision in decisions}
    states: list[CandidateState] = []
    number = 0
    for index, item in enumerate(items):
        carried = kept[index]
        if carried is not None:
            chosen = decisions[carried]
            states.append(CandidateState(chosen.key, chosen.state, item, chosen.reason, chosen.decided_by,
                                         chosen.decided_on))
            continue
        while True:
            number += 1
            key = f"c{number:02d}"
            if key not in used:
                break
        used.add(key)
        states.append(CandidateState(key, CANDIDATE_PENDING, item))
    converted = [state for state in states if state.state == CANDIDATE_CONVERTED]
    if not converted:
        return replace(outcome, states=tuple(states))
    taken = {mark.key for mark in job.marks} | {item.mark.key for item in job.refused}  # también las apartadas por solaparse (T48)
    marks = []
    for state in converted:
        if state.key in taken:
            raise DesignError("des.stockpile_candidate_key_taken", obj=f"Marca «{state.key}»", field="nombre",
                              value=state.key)
        item = state.candidate
        marks.append(StockpileMark(state.key, _window_cells(item.zone, item.window, ncols),
                                   name=_CANDIDATE_NAME.format(key=state.key)))
    again = replace(job, marks=(*job.marks, *marks), candidates=None, perimeter=None)
    detected: StockpileOutcome = yield from pipeline.forward(detect_steps(again, budget_s=budget_s))
    rest = replace(found, items=tuple(state.candidate for state in states if state.state != CANDIDATE_CONVERTED),
                   on_marks=found.on_marks + len(converted))
    return replace(detected, candidates=rest, figures=_figures(again, detected.stockpiles, rest), states=tuple(states))


# --- Crear (spec 016, T13; RF-016-02, RF-016-08, RF-016-09, RF-015-01, RF-015-02, RF-015-04; RNF-016-03 y 07) ------------


_STORE_PHASE = "stockpile_store"


def _json(value: object) -> str:
    """``value`` como JSON compacto y estable (``allow_nan`` falso: nada que no sea finito; un escalar de numpy, su valor)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=_plain)


def _plain(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"el valor {value!r} no se puede guardar como JSON")


def _finite(value: float | None, what: str) -> float | None:
    """``value`` como real finito (``None`` si no lo hay); ``ValueError`` si es NaN o infinito: lo guardado nunca lo es."""
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} no es un número finito: {value!r}")
    return number


def _notice_json(notice: Notice) -> dict[str, object]:
    return {"code": notice.code, "severity": notice.severity, "values": dict(notice.values)}


def stockpile_rows(prepared: PreparedDetection, outcome: StockpileOutcome) -> list[tuple[Any, ...]]:
    """Las filas de ``des_stk_`` (:data:`~.store.STOCKPILE_COLUMNS`; RF-016-02, RF-016-09) de la detección ``prepared`` con su
    resultado ``outcome``: **una por acopio**, en su orden, con su procedencia (``mark`` y la capa, el ``fid`` y el margen que
    se le aplicó, o ``candidate`` si salió de convertir un candidato), el plano en el centro de su huella, la huella en
    tramos y sus avisos y notas con su código (no su texto). Nada es NaN ni infinito (``ValueError``)."""
    return stockpile_rows_of(prepared.job, prepared.layer, prepared.fids, outcome)


def stockpile_rows_of(job: StockpileJob, layer: str, fids: Mapping[str, int], outcome: StockpileOutcome
                      ) -> list[tuple[Any, ...]]:
    """:func:`stockpile_rows` de un trabajo ``job`` con la capa de marcas ``layer`` y el ``fid`` de cada marca en ella
    (``fids``), sin la preparación: lo que reproducir (``design.reproduce``) tiene de lo congelado."""
    marks = {mark.key: mark for mark in job.marks}
    default_margin = job.params.margin_m
    rows: list[tuple[Any, ...]] = []
    for item in outcome.stockpiles:
        mark = marks.get(item.key)
        origin = "candidate" if mark is None else "mark"
        margin = default_margin if mark is None or mark.margin_m is None else mark.margin_m
        rows.append((
            job.code, item.key, item.name, origin, layer if mark is not None else None,
            fids.get(item.key) if mark is not None else None, item.material, item.base_surface,
            _finite(margin, "el margen"), int(item.cells.size), _finite(item.area_m2, "el área"),
            _finite(item.volume_m3, "el volumen"), _finite(item.thickness_max_m, "el espesor máximo"),
            _finite(item.x, "x"), _finite(item.y, "y"), _finite(item.plane_level_m, "la cota del plano"),
            _finite(item.plane_slope_percent, "la pendiente del plano"),
            _finite(item.plane_azimuth_deg, "el azimut del plano"),
            _finite(item.plane_tilt_deg, "la inclinación del plano"), int(item.turns), int(bool(item.converged)),
            _json(item.runs.tolist()), _json([_notice_json(note) for note in item.notes])))
    return rows


def candidate_rows(outcome: StockpileOutcome, ncols: int) -> list[tuple[Any, ...]]:
    """Las filas de ``des_stc_`` (:data:`~.store.CANDIDATE_COLUMNS`; RF-016-08, RF-016-10) del resultado ``outcome``: **una
    por candidato** que pasó los filtros (los pendientes, los descartados y los convertidos: nunca los que no los pasan), con
    su clave, su estado y la decisión, su huella en tramos (``ncols``, las columnas de la rejilla) y su plano en el centro.
    Sin candidatos pedidos, ninguna."""
    rows: list[tuple[Any, ...]] = []
    for state in outcome.states:
        item = state.candidate
        plane = item.footprint.plane
        assert plane is not None  # un candidato se forma como una marca: con plano
        x, y = item.centre
        rows.append((
            state.key, state.state, state.reason, state.decided_by, state.decided_on, int(item.cells.size),
            _finite(item.footprint.area_m2, "el área"), _finite(item.footprint.volume_m3, "el volumen"),
            _finite(x, "x"), _finite(y, "y"), _finite(float(plane.at(x, y)), "la cota del plano"),
            _finite(plane.slope_percent, "la pendiente del plano"), _finite(plane.azimuth_deg, "el azimut del plano"),
            _json(footprint_runs(item.cells, ncols).tolist())))
    return rows


def detection_report_rows(outcome: StockpileOutcome) -> list[tuple[Any, ...]]:
    """Las filas de ``des_prp_`` (formato largo: ``quantity, value, unit_code, note``; RF-016-04 a 08) del resultado
    ``outcome``: los acopios, su área y su volumen, las marcas rechazadas, los candidatos (los que salieron, los que
    descartó el filtro del área y las zonas con marca o rechazadas, **contadas y sin listar**, y cuántos se convirtieron y se
    descartaron) y, al final, **cada aviso y nota con su código y sus valores** en JSON (no su texto), en su orden."""
    found = outcome.stockpiles
    rows: list[tuple[Any, ...]] = [
        ("stockpiles", float(len(found)), "-", None),
        ("area_m2", _finite(math.fsum(item.area_m2 for item in found), "el área"), "m2", None),
        ("volume_m3", _finite(math.fsum(item.volume_m3 for item in found), "el volumen"), "m3", None),
        ("rejected_marks", float(len(outcome.rejected)), "-", None)]
    if outcome.candidates is not None:
        counts = outcome.candidates
        decided = Counter(state.state for state in outcome.states)
        rows += [("candidates", float(len(counts.items)), "-", None), ("candidate_zones", float(counts.zones), "-", None),
                 ("candidates_on_marks", float(counts.on_marks), "-", None),
                 ("candidates_filtered", float(counts.filtered), "-", None),
                 ("candidates_rejected", float(counts.rejected), "-", None),
                 ("candidates_converted", float(decided[CANDIDATE_CONVERTED]), "-", None),
                 ("candidates_discarded", float(decided[CANDIDATE_DISCARDED]), "-", None)]
    for notice in outcome.notices:
        rows.append((notice.severity, None, None, _json(_notice_json(notice))))
    return rows


def material_label(material: str | None) -> str:
    """La etiqueta del material en el nombre de los datos de la base y del espesor (``des_stb_<det>_<mat>``): el material y,
    sin él, «sin material»."""
    return _NO_MATERIAL if material is None else material


def material_dataset(family: str, detection: str, material: str | None) -> str:
    """El nombre del dato de la familia ``family`` (``stb`` o ``stt``: la base o el espesor) de los acopios de ``material`` de
    la detección ``detection`` (``des_stb_<det>_<mat>``): lo que busca quien lee un material por su papel."""
    return provenance.dataset_name(family, f"{detection} {material_label(material)}")


def _grid_units(writer: DesignWriter, grid: Grid, family: str, make: Callable[[], np.ndarray], part: str | None
                ) -> Generator[None, None, Any]:
    """Las unidades de preparar una rejilla dispersa: montarla de los índices y los valores de cada acopio (una unidad) y
    escribirla en su temporal con su hash (:meth:`~.store.DesignWriter.grid_steps`: una unidad por banda)."""
    values = make()
    yield
    raster = Raster(grid, values, writer.crs, writer.vertical)
    return (yield from writer.grid_steps(family, raster, part=part))


def create_detection_steps(project: StoreProject, writer: DesignWriter, prepared: PreparedDetection,
                           outcome: StockpileOutcome, *, decided_by: str | None = None, budget_s: float = STEP_BUDGET_S
                           ) -> Generator[Progress, None, Stored]:
    """**«Crear» una detección de acopios** por pasos (spec 016, T13; RF-016-02, RF-016-08, RF-016-09, RF-015-01, RF-015-02,
    RF-015-04; RNF-016-03 y 07): prepara cada salida en su temporal —la tabla de acopios (``des_stk_``), la de candidatos
    (``des_stc_``), por material la base y el espesor dispersos (``des_stb_`` y ``des_stt_``), el terreno sin acopios y la
    superficie con que se detectó, solo en las huellas (``des_stg_`` y ``des_stp_``) y el informe (``des_prp_``)—, cada una
    montada y escrita por pasos de ``budget_s`` como mucho, y las registra en **una** transacción
    (:meth:`~.store.DesignWriter.commit` de ``writer``, el del ámbito de la detección: ``design_writer``): **los parámetros
    de la entidad** —todas sus filas, con su origen y el decisor ``decided_by`` (por defecto quien tiene abierto el
    proyecto)—, la operación con sus entradas y ajustes, los datos, las cifras con su ámbito (el acopio y el material) y el
    mensaje. Es **la misma** operación en el proyecto (``des.stockpile_detect_project``: datos y parámetros del proyecto, sin
    código de versión) y en una versión (``des.stockpile_detect``): lo único que cambia es dónde se escribe (D-15).

    Sin ningún acopio (todas las marcas se rechazaron y los candidatos, si se pidieron, no se convirtieron) no hay base,
    espesor, terreno ni superficie que guardar y se omiten. Una entidad que ya estaba en su ámbito (``prepared.existing``:
    repetirla, T14) no vuelve a escribir sus parámetros. Si algo falla, o lo que consume cambió desde que se calculó, no queda
    nada y el error sigue; **no modifica ninguna capa de entrada**. Cerrar el generador antes de que termine borra los
    temporales. Devuelve lo guardado (:class:`~.store.Stored`)."""
    if not isinstance(outcome, StockpileOutcome):
        raise TypeError(f"se crea la detección de un StockpileOutcome, no {outcome!r}")
    grid = prepared.job.grid
    ncols = grid.ncols
    yield Progress(_STORE_PHASE, 0, 1, f"Guardando la detección «{prepared.job.name}»…")
    chosen = outcome.stockpiles
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.STOCKPILES_TABLE, stockpile_rows(prepared, outcome)), budget_s,
        "la tabla de acopios"))
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.STOCKPILE_CANDIDATES_TABLE, candidate_rows(outcome, ncols)), budget_s,
        "la tabla de candidatos"))
    if chosen:
        for material in outcome.materials:
            part = material_label(material)
            yield from pipeline.forward(_store_steps(_grid_units(
                writer, grid, provenance.STOCKPILE_BASE_GRID, lambda material=material: outcome.base_grid(material), part),
                budget_s, f"la base de los acopios de «{part}»"))
            yield from pipeline.forward(_store_steps(_grid_units(
                writer, grid, provenance.STOCKPILE_THICKNESS_GRID, lambda material=material: outcome.thickness_grid(material),
                part), budget_s, f"el espesor de los acopios de «{part}»"))
        yield from pipeline.forward(_store_steps(_grid_units(
            writer, grid, provenance.STOCKPILE_GROUND_GRID, outcome.ground_grid, None), budget_s,
            "el terreno sin acopios"))
        yield from pipeline.forward(_store_steps(_grid_units(
            writer, grid, provenance.STOCKPILE_SURFACE_GRID, outcome.surface_grid, None), budget_s,
            "la superficie con que se detectó"))
    else:
        writer.omit(provenance.STOCKPILE_BASE_GRID, provenance.STOCKPILE_THICKNESS_GRID,
                    provenance.STOCKPILE_GROUND_GRID, provenance.STOCKPILE_SURFACE_GRID)
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.ENTITY_REPORT_TABLE, detection_report_rows(outcome)), budget_s,
        "el informe de la detección"))
    yield Progress(_STORE_PHASE, 1, 1, f"Registrando la detección «{prepared.job.name}»…")
    resumed = writer.handle is not None  # un recálculo: la operación empezó antes de calcular (``run_detection``)
    supersedes = writer.supersedes if resumed else prepared.start.supersedes

    def parameters(conn: sqlite3.Connection) -> None:
        if prepared.existing:
            if ParameterStore(project).get(entity_key(prepared.code, StockpileParam.NAME), version=prepared.version_uid,
                                           conn=conn) is None:
                raise ValueError(f"la entidad {prepared.code} no tiene sus parámetros en su ámbito: no está en él (se "
                                 "prepara sin su código)")
        else:
            set_entity_params(project, prepared.rows, version=prepared.version_uid, decided_by=decided_by, conn=conn)
        if supersedes is not None:
            _retire_vanished(project, conn, supersedes, {spec.name for spec in writer.specs})

    return writer.commit(None if resumed else prepared.start, figures=outcome.figures, message=outcome.message,
                         before_begin=parameters)


def _retire_vanished(project: StoreProject, conn: sqlite3.Connection, supersedes: str, written: set[str]) -> None:
    """Retira, en la transacción de «Crear», los datos vigentes que escribió la operación ``supersedes`` y **la nueva no
    escribe** (spec 016, T13; RF-016-10, RF-015-16): al repetir una detección, la base y el espesor de un material que ya no
    tiene ningún acopio (la marca cambió de material, el candidato dejó de estar convertido…) quedarían vigentes en el proyecto
    sin operación que los respalde, y quien lee por su papel (la 011, la 012, R-18) los tomaría por una unidad de acopios. Pasan a
    «sustituidos» (conservan su contenido como historia) y lo que los consumía queda obsoleto con su causa."""
    live = tuple(str(status) for status in LIVE_STATUSES)
    rows = conn.execute(
        "SELECT d.uid, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
        f"WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' AND d.status IN "
        f"({', '.join('?' for _ in live)}) ORDER BY io.fid", (supersedes, *live)).fetchall()
    for uid, name in rows:
        if name not in written:
            dataset_registry.supersede(conn, project, str(uid))


def create_detection(project: StoreProject, writer: DesignWriter, prepared: PreparedDetection,
                     outcome: StockpileOutcome, *, decided_by: str | None = None) -> Stored:
    """:func:`create_detection_steps` de una vez (sin ceder el hilo): lo guardado (:class:`~.store.Stored`), con los mismos
    rechazos y la misma transacción."""
    work = create_detection_steps(project, writer, prepared, outcome, decided_by=decided_by)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: Stored = stop.value
            return result


# --- Recalcular (spec 016, T14; RF-016-10, RF-015-02, RF-015-04, RF-015-16; CE-016-01) -----------------------------------


def run_detection(project: StoreProject, request: StockpileRequest, *, version: str | None, code: str,
                  masks: access.MaskSet | access.MaskSource | None = None, supersedes: str | None = None,
                  op_type: str | None = None, budget_s: float = STEP_BUDGET_S
                  ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Calcula y registra ``request`` —la detección de la entidad ``code``, que ya está en su ámbito— de **una vez**, sin
    pedir confirmación (el recálculo de lo obsoleto, :func:`~.store.recompute_run`; el «Crear» tras «Calcular» es
    :meth:`~.steps.Calculation.create`): prepara (:func:`prepare_detection`: la entidad se reconoce por su ``code``), empieza la
    operación **antes de calcular** —sustituye a ``supersedes``, quedándose con los nombres de sus datos— con lo que lee hoy
    (la capa de marcas, la superficie, las bases, el umbral de la huella y, en una versión, sus máscaras) y devuelve su
    ``OperationHandle`` «en curso» y sus pasos, que avanza quien la llama: calculan (:func:`detection_compute_steps`, con las
    decisiones de la entidad), escriben cada salida en su temporal y completan la operación en una transacción
    (:func:`create_detection_steps` con el escritor reanudado: no escribe los parámetros, que ya están); el último paso lleva
    lo guardado (:class:`~.store.Stored`). Cerrarlos antes, o un fallo, no dejan nada y la operación queda cancelada o fallida.

    Es **la misma** operación en el proyecto (``des.stockpile_detect_project``, ``version`` ``None``) y en una versión
    (``des.stockpile_detect``): el escritor de su ámbito. ``op_type``, si se da, es el de la operación que se repite: la
    detección no puede cambiar de ámbito al recalcularla.

    Al llamar, sin empezar nada: ``des.stockpile_scope_changed`` (la superficie de la entidad es ahora de otro ámbito que la
    operación: se comprueba antes de preparar, para no rechazar por un nombre que ya es de otro ámbito) y los rechazos de
    :func:`prepare_detection`. Al avanzar, antes de escribir nada, ``des.input_changed`` si un parámetro cambió entre
    prepararla y empezar la operación."""
    if op_type is not None:
        scope, _found = detection_scope(project, request, version)
        if (provenance.STOCKPILE_DETECT_PROJECT if scope == PROJECT else provenance.STOCKPILE_DETECT) != op_type:
            raise DesignError("des.stockpile_scope_changed", obj=f"Detección de acopios «{request.name}»", field="surface",
                              value=request.surface, name=request.name, surface=request.surface)
    prepared = prepare_detection(project, request, version=version, masks=masks, code=code, supersedes=supersedes)
    handle = prepared.start.begin(project)
    return handle, _detection_run(project, handle, prepared, budget_s)


def recompute_detection(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S
                        ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.stockpile_detect`` o ``des.stockpile_detect_project`` de ``request``
    (:func:`~.store.recompute_run`; «Recalcular lo obsoleto», RF-008-26; spec 016, T14; RF-016-10, RF-015-02, RF-015-16): la
    detección de sus ajustes (el nombre, el código y los campos de su capa de marcas) con los **parámetros vigentes de su
    entidad en su ámbito** (:func:`~.entity_store.entity_parameters`: la capa, la superficie, los candidatos, los umbrales de
    D-3 y las decisiones sobre los candidatos; los de la versión y, si no, los del proyecto, y en una detección **del proyecto**
    los del proyecto) y no los que leyó la operación que sustituye: una entidad se define por sus parámetros (RF-015-01). El
    umbral de la huella (``res.anthropic_presence_m``), la capa de marcas (su geometría) y la superficie son entradas de la
    operación: cambiar una la deja obsoleta **entera** y recalcular la repite con lo nuevo. Es el camino de las operaciones de
    proyecto que ya hay (``gis``, ``reserves``): ``RecomputeRequest.version`` ``None`` y la operación sin revisión. Devuelve lo de
    :func:`run_detection`. ``ValueError`` si los ajustes no son los de una detección o la petición no es de su tipo."""
    if not isinstance(request, RecomputeRequest):
        raise TypeError(f"se recalcula una RecomputeRequest, no {request!r}")
    if request.op_type not in provenance.STOCKPILE_DETECT_TYPES:
        raise ValueError(f"recompute_detection repite {', '.join(provenance.STOCKPILE_DETECT_TYPES)}, no «{request.op_type}»")
    project: StoreProject = request.project  # type: ignore[assignment]
    code = provenance.supported_code(request.settings)
    found = None
    if request.op_type == provenance.STOCKPILE_DETECT:
        found = require_version(project, request.version, request.op_type)
    asked = provenance.stockpile_request(request.settings, entity_parameters(project, code, version=found))
    return run_detection(project, asked, version=None if found is None else found.uid, code=code,
                         supersedes=request.operation_uid, op_type=request.op_type, budget_s=budget_s)


def _check_recorded(handle: OperationHandle, prepared: PreparedDetection) -> None:
    """Los parámetros que anotó la operación al empezar son los que leyó el cálculo al prepararse (RF-013-17, D-14): si uno
    cambió entre las dos cosas, el resultado ya no le corresponde (``des.input_changed``, con el parámetro)."""
    read: dict[str, object] = {entity_key(prepared.code, StockpileParam(name)): value
                               for name, value in prepared.values.items()}
    read[ANTHROPIC_PRESENCE] = prepared.job.params.threshold_m
    for param in handle.params:
        if param.key in read and param.value != read[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»", field="parámetros", value=param.key)


def _detection_run(project: StoreProject, handle: OperationHandle, prepared: PreparedDetection, budget_s: float
                   ) -> Generator[Progress, None, None]:
    with design_writer(project, handle.op_type, prepared.job.name, version=handle.version_uid, handle=handle) as writer:
        _check_recorded(handle, prepared)
        outcome: StockpileOutcome = yield from detection_compute_steps(prepared.job, decisions=prepared.decisions,
                                                                      budget_s=budget_s)
        stored: Stored = yield from create_detection_steps(project, writer, prepared, outcome, budget_s=budget_s)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


# --- Leer lo guardado y decidir (spec 016, T13; RF-016-10, P-14) ---------------------------------------------------


def _check_detection_family(family: str) -> None:
    """``ValueError`` si ``family`` no es una tabla de la detección de acopios (``stk``, ``stc`` o ``prp``)."""
    if family not in (provenance.STOCKPILES_TABLE, provenance.STOCKPILE_CANDIDATES_TABLE, provenance.ENTITY_REPORT_TABLE):
        raise ValueError(f"«{family}» no es una tabla de la detección de acopios")


def read_stored_rows(conn: sqlite3.Connection, family: str, locator: str) -> tuple[dict[str, Any], ...]:
    """Las filas de la tabla ``family`` (``stk``, ``stc`` o ``prp``) de una detección que está en ``locator`` (la tabla de su GeoPackage: lo
    que dice su registro, :attr:`~core.datasets.DatasetRecord.locator`; spec 016, T33; RF-015-25), cada una por el nombre de su columna y en el
    orden de la tabla (``fid``). Lo que lee el cargador de la vista, que conoce **el dato** y no el nombre de la detección (con ese nombre,
    :func:`read_detection_table` busca el dato vigente). Solo lee; ``ValueError`` si ``family`` no es una tabla de la detección."""
    _check_detection_family(family)
    columns = [column.name for column in columns_of(provenance.STOCKPILE_DETECT, family)]
    found = conn.execute(f'SELECT {", ".join(columns)} FROM "{locator}" ORDER BY fid').fetchall()
    return tuple(dict(zip(columns, row, strict=True)) for row in found)


def read_detection_table(project: StoreProject, family: str, name: str, *, version_uid: str = "",
                         conn: sqlite3.Connection | None = None) -> tuple[dict[str, Any], ...]:
    """Las filas de la tabla ``family`` (``stk``, ``stc`` o ``prp``) de la detección ``name`` **vigente** en el ámbito
    (``version_uid`` vacío: el proyecto), cada una por el nombre de su columna (``STOCKPILE_COLUMNS``, ``CANDIDATE_COLUMNS``
    o ``REPORT_COLUMNS``), en su orden. Las huellas (``footprint``) son JSON de tramos y las rejillas dispersas se leen
    por su papel con :func:`~.surfaces.read_surface`. Solo lee. ``ValueError`` si ``family`` no es una tabla de la detección
    y ``des.stockpile_decisions_invalid`` no: si el dato no está, ``gis.dataset_unknown``."""
    _check_detection_family(family)
    dataset = provenance.dataset_name(family, name)

    def read(reading: sqlite3.Connection) -> tuple[dict[str, Any], ...]:
        record = dataset_registry.get(reading, dataset, version_uid=version_uid)
        if record is None or not record.live:
            raise GisError("gis.dataset_unknown", obj=dataset, field="nombre", value=dataset, name=dataset)
        return read_stored_rows(reading, family, record.locator)

    if conn is not None:
        return read(conn)
    with project.read() as reading:
        return read(reading)


def decide_candidate(project: StoreProject, code: str, key: str, state: str, reason: str, *,
                     version: Version | None = None, decided_by: str | None = None,
                     decided_at: Any = None) -> ParameterRecord:
    """**Decide** sobre el candidato ``key`` (``c03``) de la lista vigente de la detección de código ``code`` en su ámbito
    (la ``version`` o, sin ella, el proyecto; spec 016, T13; RF-016-08, RF-016-10; P-14): ``state`` es
    :data:`~.stockpiles.CANDIDATE_CONVERTED`, :data:`~.stockpiles.CANDIDATE_DISCARDED` o
    :data:`~.stockpiles.CANDIDATE_PENDING` (volver a preguntar: quita la decisión), siempre con su ``reason``. Es un **cambio del
    parámetro** ``decisions`` de la entidad (con su historial, su decisor ``decided_by`` —por defecto quien tiene abierto el
    proyecto— y su fecha ``decided_at``): la detección lo lee, así que **queda obsoleta con su causa** (RF-015-16) y se
    repite con la decisión aplicada (:func:`detection_compute_steps`; el recálculo, T14). La decisión guarda la huella del
    candidato **tal como la enseña la lista** (la tabla ``des_stc_`` vigente), con la que se reconoce al repetir (D-23).
    ``des.stockpile_decisions_invalid`` si la detección no tiene ningún candidato con esa clave; ``ValueError`` si el
    estado es otro o falta el motivo."""
    if state not in (*_DECISION_STATES, CANDIDATE_PENDING):
        raise ValueError(f"se decide «{CANDIDATE_CONVERTED}», «{CANDIDATE_DISCARDED}» o «{CANDIDATE_PENDING}», no «{state}»")
    if not reason.strip():
        raise ValueError("una decisión sobre un candidato lleva su motivo")
    values = entity_parameters(project, code, version=version)
    name = values.get(StockpileParam.NAME.value)
    if not isinstance(name, str):
        raise ValueError(f"la detección {code} no tiene nombre en su ámbito")
    version_uid = "" if version is None else version.uid
    parameter = entity_key(code, StockpileParam.DECISIONS)
    who = decided_by or project.session.user_host
    store = ParameterStore(project)
    with project.write_transaction() as conn:
        rows = read_detection_table(project, provenance.STOCKPILE_CANDIDATES_TABLE, name, version_uid=version_uid,
                                    conn=conn)
        current = parse_decisions(values.get(StockpileParam.DECISIONS.value), entity=name)
        others = tuple(item for item in current if item.key != key)
        if state != CANDIDATE_PENDING:
            row = next((item for item in rows if item["key"] == key), None)
            if row is None:
                raise _invalid_decisions(name, f"la detección no tiene ningún candidato «{key}»")
            runs = tuple((int(a), int(b), int(c)) for a, b, c in json.loads(row["footprint"]))
            stamp = (format_utc(project.clock.now()) if decided_at is None
                     else decided_at if isinstance(decided_at, str) else decided_at.isoformat())
            when = stamp[:10]
            others = (*others, CandidateDecision(key, state, reason.strip(), who, when, runs))
        text = format_decisions(others)
        if text == format_decisions(current):  # nada que cambiar (volver a preguntar lo que no estaba decidido)
            unchanged = store.get(parameter, version=None if version is None else version.uid, conn=conn)
            assert unchanged is not None
            return unchanged
        return store.change(conn, parameter, value=text, source=_DECIDE_SOURCE.format(name=name),
                            source_kind="person", decided_by=who, decided_at=decided_at, reason=reason.strip(),
                            version=version.uid if version is not None else None)


# --- Consultar (spec 016, T14; RF-016-10; plan 016 §5.3.1: lo que leen la 012, la 011 y las entidades) ---------------------


@dataclass(frozen=True, slots=True)
class DetectionData:
    """Un dato que escribió una detección: su ``uid``, su ``name`` (``des_stb_acopios_mineral``), su ``locator`` —dónde está en
    el proyecto: la tabla de su GeoPackage o la ruta relativa de su GeoTIFF (``rasters/des_stb_acopios_mineral_v01.tif``)— y el
    ``role`` con que lo anotó la operación (``stockpile_base``…), que es por lo que lo lee quien lo consume."""

    uid: str
    name: str
    locator: str
    role: str


@dataclass(frozen=True, slots=True)
class DetectionMaterial:
    """La base y el espesor de los acopios de un ``material`` de una detección (``None``: los que no lo tienen, «sin
    material»), dispersos: solo tienen dato en las huellas de esos acopios (NaN fuera de ellas)."""

    material: str | None
    base: DetectionData
    thickness: DetectionData


@dataclass(frozen=True, slots=True)
class Detection:
    """Una detección de acopios **al día** (spec 016, T14; plan 016 §5.3.1; :func:`detections_on`) con lo que necesitan sus
    consumidores: su ``code`` (``STK-001``), su ``name``, su ``scope`` (:data:`PROJECT` o :data:`VERSION`), la ``version`` (el
    código de la versión de la detección; ``None`` si es del proyecto) y su ``version_uid`` (``""`` en el proyecto: lo que
    reciben ``design.surfaces.read_surface`` y :func:`read_detection_table` para leer sus datos), la ``operation`` (el uid de la
    vigente, la que los escribió) y la ``surface`` sobre la que se detectó (el nombre de su dato). Y sus datos
    (:class:`DetectionData`, por su papel): la tabla de acopios (``stockpiles``; una fila por acopio, con su clave), la de
    candidatos, el informe, y de lo que hay acopio, **por material y en el orden de los acopios** su base y su espesor
    (``materials``), el terreno sin acopios en las huellas (``ground``) y la superficie con que se detectó, también en las
    huellas (``detected``; la 015 y la 011 la componen entera con la superficie de la que parte). Una detección sin ningún
    acopio no tiene ``materials``, ``ground`` ni ``detected``."""

    code: str
    name: str
    scope: str
    version: str | None
    version_uid: str
    operation: str
    surface: str
    stockpiles: DetectionData
    candidates: DetectionData
    report: DetectionData
    materials: tuple[DetectionMaterial, ...] = ()
    ground: DetectionData | None = None
    detected: DetectionData | None = None


_DETECTION_OUTPUTS = (
    "SELECT d.uid, d.name, d.locator, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid")


def detections_on(project: StoreProject, version: str | None, surface: str, *, conn: sqlite3.Connection | None = None
                  ) -> tuple[Detection, ...]:
    """Las detecciones de acopios **al día** hechas sobre la superficie ``surface`` (el nombre de su dato) que ve la
    ``version`` (su uid o su código; ``None``: solo el proyecto) (spec 016, T14; RF-016-10, RF-015-16; plan 016 §5.3.1; lo que leen
    la T15 —los acopios apoyables— y la T30 —la verificación de la 012— y la 011): las del **proyecto** (D-15; una versión puede
    consumir un dato del proyecto, RF-009-05) y, después, las de la versión, que son de una superficie suya. Solo cuenta la
    operación vigente de cada entidad (``entities.registry``/``project_registry``) y solo si está **al día**: una obsoleta (un
    umbral, la capa o la superficie cambiaron: la 008 le da causas), descartada o sin calcular no se da, que es lo que protege a
    quien la lee de una base que ya no vale. La superficie es la de **su parámetro** ``surface``, que coincide con la que
    consumió la operación mientras está al día. Solo lee; ``conn`` es una conexión de lectura de quien llama (con su
    instantánea). ``VersionError`` (``core.version_unknown``) si la versión no existe; ``ValueError`` si una detección al día
    no tiene alguno de sus datos (un proyecto dañado: no se lista a medias)."""

    def read(reading: sqlite3.Connection) -> tuple[Detection, ...]:
        return tuple(
            _detection_of(project, reading, scope, entry.record.code, entry.record.name, str(entry.operation_uid), surface)
            for scope, entry, detected_on in _stockpile_entries(project, reading, version)
            if entry.record.state == entities.EntityState.CURRENT and detected_on == surface)

    if conn is not None:
        return read(conn)
    with project.read() as reading:
        return read(reading)


def _stockpile_entries(project: StoreProject, reading: sqlite3.Connection, version: str | None
                       ) -> Iterator[tuple[Version | None, entities.EntityEntry, Any]]:
    """Las detecciones de acopios **con operación vigente** que ve la ``version`` (uid o código; ``None``: solo el proyecto) con
    el ámbito de cada una (``None``: del proyecto), su entrada del registro y el valor de su parámetro ``surface`` (``None`` si
    no tiene): las del proyecto y, después, las de la versión, cada una en su orden de código. Lo comparten
    :func:`detections_on` y :func:`detections_excluded`. ``VersionError`` (``core.version_unknown``) si la versión no existe."""
    found = None if version is None else versions_read.version(reading, str(version))
    if version is not None and found is None:
        raise VersionError("core.version_unknown", field="versión", value=version, version=version)
    store = ParameterStore(project)
    for scope in (None,) if found is None else (None, found):
        if scope is None:
            registry = entities.project_registry(project, conn=reading)
        else:
            registry = entities.registry(project, scope.uid, conn=reading)
        for entry in registry.entries:
            if entry.record.kind != EntityKind.STOCKPILE or entry.operation_uid is None:
                continue
            parameter = store.get(entity_key(entry.record.code, StockpileParam.SURFACE),
                                  version=None if scope is None else scope.uid, conn=reading)
            yield scope, entry, None if parameter is None else parameter.value


@dataclass(frozen=True, slots=True)
class ExcludedDetection:
    """Una detección de acopios que ve una versión y que **no se usa** sobre una superficie (spec 016, T30; RF-012-31): su ``code``
    (``STK-001``), su ``name``, su ``scope`` (:data:`PROJECT` o :data:`VERSION`), la ``version`` (el código de la versión de la
    detección; ``None`` si es del proyecto), la ``surface`` sobre la que está hecha (el nombre de su dato; vacío si no tiene), el
    ``reason`` (:data:`EXCLUDED_OTHER_SURFACE`: se hizo sobre otra superficie; :data:`EXCLUDED_STALE`: está obsoleta) y, de una
    obsoleta, su ``cause`` en español y su ``cause_en`` en inglés (lo que cambió, según la 008: spec 016, T48, hallazgo D-5; quien la
    muestra elige la del idioma de la interfaz)."""

    code: str
    name: str
    scope: str
    version: str | None
    surface: str
    reason: str
    cause: str = ""
    cause_en: str = ""


def detections_excluded(project: StoreProject, version: str | None, surface: str | None, *,
                        conn: sqlite3.Connection | None = None) -> tuple[ExcludedDetection, ...]:
    """Las detecciones de acopios que ve la ``version`` (uid o código; ``None``: solo el proyecto) y que **no** da
    :func:`detections_on` para ``surface``, con su causa (spec 016, T30; RF-012-31; plan 016 §5.4 A12): las **hechas sobre otra
    superficie** (:data:`EXCLUDED_OTHER_SURFACE`, estén al día o no) y las **obsoletas** sobre ``surface``
    (:data:`EXCLUDED_STALE`, con lo que cambió: la causa de la 008). Con ``surface`` ``None`` (una superficie que no es el dato
    de ninguna detección: una cota constante, un dato congelado), todas son de otra superficie. Una descartada, una sin calcular o
    una con su entrada descartada no se avisa: no son una base que se esperaba. Las del proyecto y, después, las de la versión.
    Solo lee; ``conn`` y los errores, como en :func:`detections_on`."""

    def read(reading: sqlite3.Connection) -> tuple[ExcludedDetection, ...]:
        found: list[ExcludedDetection] = []
        for scope, entry, detected_on in _stockpile_entries(project, reading, version):
            record, state = entry.record, entry.record.state
            if state not in (entities.EntityState.CURRENT, entities.EntityState.STALE):
                continue
            on_it = surface is not None and detected_on == surface
            if state == entities.EntityState.CURRENT and on_it:
                continue  # la que se usa
            where = (PROJECT if scope is None else VERSION, None if scope is None else scope.code)
            if not on_it:
                found.append(ExcludedDetection(record.code, record.name, *where, "" if detected_on is None else str(detected_on),
                                               EXCLUDED_OTHER_SURFACE))
                continue
            uid = str(entry.operation_uid)
            cause = item_text(reading, STALE_OPERATION, uid, language="es") or "cambió algo de lo que lee"
            cause_en = item_text(reading, STALE_OPERATION, uid, language="en") or "something it reads changed"
            found.append(ExcludedDetection(record.code, record.name, *where, str(surface), EXCLUDED_STALE, cause, cause_en))
        return tuple(found)

    if conn is not None:
        return read(conn)
    with project.read() as reading:
        return read(reading)


def _detection_of(project: StoreProject, conn: sqlite3.Connection, scope: Version | None, code: str, name: str,
                  operation: str, surface: str) -> Detection:
    """La :class:`Detection` de la entidad ``code`` cuya operación vigente es ``operation``: sus datos por su papel y, por
    material, su base y su espesor (los nombres que da :func:`material_dataset` a los materiales de su tabla de acopios)."""
    written = [DetectionData(str(uid), str(found), str(locator), str(role))
               for uid, found, locator, role in conn.execute(_DETECTION_OUTPUTS, (operation,)).fetchall()]
    by_name = {item.name: item for item in written}

    def one(role: str) -> DetectionData:
        found = [item for item in written if item.role == role]
        if len(found) != 1:
            raise ValueError(f"la detección {code} («{name}») tiene {len(found)} datos con el papel «{role}» en su "
                             f"operación {operation}: tiene que tener uno")
        return found[0]

    def named(family: str, material: str | None) -> DetectionData:
        wanted = material_dataset(family, name, material)
        if wanted not in by_name:
            raise ValueError(f"la detección {code} («{name}») no tiene el dato «{wanted}» de los acopios de "
                             f"«{material_label(material)}» en su operación {operation}")
        return by_name[wanted]

    stockpiles = one(provenance.STOCKPILES_ROLE)
    version_uid = "" if scope is None else scope.uid
    rows = read_detection_table(project, provenance.STOCKPILES_TABLE, name, version_uid=version_uid, conn=conn)
    materials = tuple(DetectionMaterial(material, named(provenance.STOCKPILE_BASE_GRID, material),
                                        named(provenance.STOCKPILE_THICKNESS_GRID, material))
                      for material in dict.fromkeys(row["material"] for row in rows))
    ground = one(provenance.STOCKPILE_GROUND_ROLE) if rows else None
    detected = one(provenance.STOCKPILE_SURFACE_ROLE) if rows else None
    return Detection(code, name, PROJECT if scope is None else VERSION, None if scope is None else scope.code, version_uid,
                     operation, surface, stockpiles, one(provenance.STOCKPILE_CANDIDATES_ROLE),
                     one(provenance.ENTITY_REPORT_ROLE), materials, ground, detected)
