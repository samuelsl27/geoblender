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
(:func:`platform_obsolete`, del grafo de la 008: lo vigente de la versión, también lo registrado en una
revisión que luego se congeló; los elementos de la congelada no cambian ni se marcan, RF-009-19).

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
su huella, y se registran **aunque no apoyen nada**. :func:`detected_supports` lo enseña antes de crear. **En un acopio** (spec 016,
T15; RF-016-14, P-1): :func:`survey_supports` mide además sobre **cada acopio** de las detecciones de acopios de la versión
(:func:`read_stockpile_footprints`: la huella de cada fila de su ``des_stk_``), todos sobre la superficie con que se detectó
(``des_stp_``), y cada uno que recibe relleno es un :class:`~.entities.Support` con su clave; también los de las detecciones **del proyecto** (T45, S-1:
:func:`_with_project_detections`). **Insertar
antes o después de otra** (T31; RF-015-05): con ``insert_before`` (la entidad que hoy parte de la misma superficie) la
preparación no rechaza esa partida ocupada y lleva en ``PreparedPlatform.insertion`` el cambio de la partida de esa
entidad (``entities.insert_before``, con su motivo); :func:`apply_insertion` lo escribe con el gancho de «Crear», en la
misma transacción que la entidad —el parámetro ``start`` de la sucesora, con su historial y su decisor—, y la 008 deja
obsoleta a la sucesora y, en cascada, a las que la siguen (también antes de la primera de una cadena).

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
ella recalcula por el grafo. **Nunca una plataforma que protege sin su restricción vigente** (T38; RF-015-10, RF-015-29,
CE-015-04; hallazgo E-1): si Esc o un fallo cortan la cadena **antes de escribir la primera declaración de la
versión**, no hay tabla que la compilación no haya consumido (el hueco H-1 no lo ve) y la entidad quedaría protegiendo
sin su restricción en ningún sitio, con las máscaras «al día»; :func:`declaration_pending` dice si una entidad viva que
protege no tiene su fila en la declaración vigente y :data:`DECLARATION_HOOK` lo da a ``gis.masks.access``
(``gis.masks.declaring``; lo registra ``bl``): mientras sea así las máscaras están obsoletas (``DECLARED_NEW``) y quien
las pide declara antes de compilar (``gis.masks.access.declare_pending_steps``).

**La capa de entidades** (T30; RF-015-27, D-13; plan 015 §5.2.3, §5.3.2 y P-7; ADR-0030 §5): la operación de la versión
``des.entity_layer`` (repetible, no reproducible: su contenido incluye el estado de cada entidad, que deduce el grafo)
pone en ``des_enl_<vNN>`` una fila por entidad **calculada** —el contorno de su huella (``des_epr_``), su tipo, su
nombre, su estado, de qué parte, en qué se apoya, su cadena y sus cifras principales—, una capa de QGIS **no editable a
mano** y con su estilo por tipo y por estado (:mod:`.entity_layer`, T22). :func:`layer_sources` lee las entidades (el
registro de la versión, con las dependencias y la cadena de cada una), :func:`entity_layer_rows_steps` es el cálculo
de las filas (sin proyecto dentro: recibe lo leído) y :func:`prepare_entity_layer`, :func:`run_entity_layer`,
:func:`entity_layer_steps` y :func:`recompute_entity_layer` la preparan, la registran en **una** transacción
reescribiendo la tabla entera y la repiten. La orden de una entidad la regenera como **etapa aparte**
(:func:`after_entity_change`); si falla, la capa queda como estaba y el aviso lo dice. **Su estado es el del registro**
(T43; hallazgo E-4 / C-11): la capa escribe el que deduce el grafo al escribirla, y :func:`layer_pending` dice, sin leer
geometrías, si ya no es el del registro de las entidades (la marca: tras cambiar un parámetro, recalcular una entidad con
la misma salida, dar por bueno un apoyo o cerrar con Esc lo que sigue a una orden); :func:`layer_sync_steps` la regenera
solo si está marcada y :func:`layers_sync_steps`, la de cada versión editable (lo hace ``bl`` al terminar «Recalcular lo
obsoleto» y :func:`release_support`, en sus mismos pasos). **La tabla de la entidad editada fuera de Geoblender**
(T43; hallazgo B-2; RF-015-11): la declaración y la capa leen la huella de ``des_epr_`` con :func:`_usable_footprint`, que
se niega con la entidad (``des.entity_footprint_blocked`` o ``_unusable``) si la 008 la tiene bloqueada, falta, está
dañada o ya no es la tabla de una entidad.

**Descartar, «apoyo retirado» y soltar el apoyo** (T25; RF-015-17, RF-009-12; D-12; plan 015 §5.4 A7, P-6; ADR-0030 §4):
:func:`discard_plan` es **la lista** que se enseña antes de descartar (una sola: lo que se apoya en la entidad y lo que
parte de ella, con sus m³: ``entities.dependents``) y :func:`discard_entity` descarta —los datos que escribió pasan a
``DISCARDED`` y **nada se borra**; una entidad sin calcular, con su parámetro ``discarded``—, con un evento y el
motivo; lo que se le apoyaba queda en «apoyo retirado» y «Recalcular lo obsoleto» no lo recalcula
(``core.recompute_no_successor``). Después la orden encadena :func:`after_entity_change` (la restricción de lo
descartado sale de la declaración y de las máscaras). :func:`release_support` **da por bueno** lo que perdió el apoyo
repitiéndolo con ``supersedes`` sin esa entrada, con el motivo y el decisor en sus ajustes
(``provenance.SUPPORTS_RELEASED``) y un evento: su salida no cambia, así que lo que dependía de ella no se
recalcula (RF-008-26).

**Traer las entidades de otra versión** (T26; RF-015-18, RF-009-01; D-18; plan 015 P-4): :func:`bring_entities` copia a la
versión editable las **definiciones** de las entidades de cualquier otra —sus parámetros ``des.platform.{e}.*`` con su
decisor, su fecha y su origen y un historial «Traído de V09.r2», como «Heredado de…» de ``ParameterStore.inherit``, que
es lo que recibe la versión que parte de otra—, **sin resultados ni cifras**, «sin calcular»; reasigna el código si está
ocupado (y las referencias entre las traídas), cambia el nombre si choca, deja **sin valor** la partida que era un
resultado de la otra versión o la de la que ya parte otra entidad, no trae las descartadas y escribe todo en una
transacción. Al calcularlas (:func:`create_platform` con su código), sus dependencias se detectan de nuevo.

**Leer solo la ventana** (T37; RNF-015-03, RNF-015-08; plan 015 §5.4 A0): la preparación de una plataforma lee la
superficie de partida (y la de apoyo) y las máscaras **solo en la ventana que el cálculo va a tocar**
(:func:`~.platform.reading_window`: la caja de su geometría con el ancho, el alcance y dos celdas), con unas
máscaras sin cargar si no se le dan cargadas (:func:`~geoblender.gis.masks.access.open_masks`): la llamada que
empieza la operación al recalcular (:func:`run_platform`, una llamada del hilo de Blender) no decodifica las 98
teselas de 2,81 M de celdas para tocar unas pocas. La rejilla entera de la partida, que solo hace falta para
escribir la superficie de salida, se lee **por pasos** dentro del cálculo (:func:`compute_platform_steps`). Lo que la
ventana no basta para decidir (el rango de cotas de RF-015-08, una ventana sin dato) cae a leer la rejilla entera
(:class:`~.platform.NeedsWholeSurface`), con el mismo resultado y el mismo rechazo: el resultado es **igual bit a bit**
al de leerla entera.

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
import logging
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
from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.constraints.declared import (
    DeclaredConstraint,
    content_sha256_of,
    declared_code,
    declared_uid,
    names_in_version,
)
from ..core.constraints.model import ConstraintType
from ..core.constraints.store import constraint_names
from ..core.datasets import external as dataset_external
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import FINAL_STATUSES, DatasetStatus
from ..core.errors import GeoblenderError
from ..core.params import (
    DEFAULT_DECIDER,
    PROJECT_SCOPE,
    VERSION_SCOPE,
    ParameterRecord,
    ParameterStore,
    ParamKind,
    definition,
)
from ..core.params.store import default_reason
from ..core.project.events import EventKind, record_event
from ..core.project.model import Progress
from ..core.timeutil import format_utc
from ..core.provenance.graph import DATASET
from ..core.provenance.operations import OperationHandle, OperationStatus, Use
from ..core.provenance.recompute import RecomputeRequest
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from ..gis.masks import access, declaring
from ..gis.masks import provenance as masks_provenance
from ..gis.masks.store import CANCELLED_REASON, StoredMasks
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S, Change
from ..gis.raster import Raster
from ..gis.store import StoreProject, load_features, project_references
from ..gis.vector import FeatureLayer
from . import entities, pipeline, provenance
from .compose import admitted_pair
from .entities import EntityKind, EntityRecord, EntityRegistry, EntityState
from .entity_layer import LAYER_STATES, EntityLayerRow
from .envelopes import reach_steps
from .messages import DesignError, render
from .model import (
    PLANE_FIELD,
    BenchSense,
    LayerField,
    Metric,
    PlatformFields,
    PlatformMode,
    PlatformRequest,
)
from .params import (
    PLATFORM_PARAMS,
    BodyParam,
    PlatformParam,
    RoadParam,
    check_entity_param,
    entity_key,
    entity_params,
    entity_params_of,
    entity_segment,
    parse_entity_key,
)
from .platform import (
    Footprint,
    NeedsWholeSurface,
    PlatformGeometry,
    PlatformJob,
    PlatformOutcome,
    QuarryOrder,
    Window,
    _drain,
    _window_grid,
    apply_platform_steps,
    platform_edge_steps,
    platform_footprint_units,
    platform_outcome,
    reading_window,
    summary_notices,
    window_part,
)
from .preview import (
    Notice,
    Obsolete,
    ObsoleteKind,
    PlatformSummary,
    held_notices,
    obsolete_names,
    obsolete_notices,
)
from .quarry import _level_column
from .report import Previous
from .sectors import design_sectors, refuse_pending
from .seeds import pace_progress, sector_layout
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
    recompute_run,
    require_version,
)
from .surfaces import SurfaceWindow, project_frame, read_surface, read_surface_steps, read_surface_window

if TYPE_CHECKING:
    from .removal import RemovedStockpile, Resting
    from .supported_store import PlatformOrigin

LOGGER = logging.getLogger(__name__)

__all__ = [
    "LAYER_FIELDS",
    "LAYER_FIGURES",
    "Brought",
    "BroughtEntity",
    "ChainFailure",
    "ChainStage",
    "DeclaredSource",
    "DiscardPlan",
    "DiscardResult",
    "Discarded",
    "EntityChain",
    "EntityFootprint",
    "EntityParamRow",
    "EntitySurface",
    "LayerSource",
    "PreparedDeclaration",
    "PreparedEntityLayer",
    "PreparedPlatform",
    "SupportSurvey",
    "add_supports",
    "after_entity_change",
    "apply_insertion",
    "bring_entities",
    "check_parameter_change",
    "compute_platform_steps",
    "create_platform",
    "declaration_diverges",
    "declaration_pending",
    "declare_constraints_steps",
    "declared_rows_steps",
    "declared_supports",
    "declared_sources",
    "detected_supports",
    "discard_entity",
    "discard_entity_steps",
    "discard_plan",
    "entity_layer_rows_steps",
    "entity_layer_steps",
    "entity_parameters",
    "entity_request",
    "entity_surfaces",
    "entity_values",
    "feature_index",
    "footprint_runs",
    "geometry_sha256",
    "layer_pending",
    "layer_sources",
    "layer_sync_steps",
    "layer_values",
    "layers_sync_steps",
    "platform_compute_steps",
    "platform_entity_rows",
    "platform_obsolete",
    "platform_parameters",
    "platform_previous",
    "platform_report_rows",
    "platform_summary",
    "prepare_declaration",
    "prepare_entity_layer",
    "prepare_platform",
    "prepare_platform_units",
    "quarry_order",
    "read_entity_footprint",
    "read_geometry",
    "operation_table",
    "read_entity_report",
    "read_stockpile_footprints",
    "recompute_declaration",
    "recompute_entity_layer",
    "recompute_platform",
    "release_support",
    "run_declaration",
    "run_entity_layer",
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
    (:func:`set_entity_params`). De **cualquier tipo** de entidad (spec 016, T04): ``des.<tipo>.{e}.<valor>``, con
    ``param`` el valor de su familia (un :class:`~.params.PlatformParam` o, de otro tipo, su nombre)."""

    key: str
    param: PlatformParam | str
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
    vez sus parámetros. ``insertion`` (T31; RF-015-05): si es una **inserción** (``insert_before``), el cambio
    de la partida de la entidad que pasa a partir de la nueva (``entities.ParamChange``, con su motivo); lo
    escribe «Crear» en la misma transacción que la entidad y deja obsoleta, por la cascada de la 008, a la
    sucesora y a las que la siguen.

    **Retirar un acopio «como plataforma»** (spec 016, T21; RF-016-16): ``removed`` es el acopio cuya huella es la geometría del trabajo
    (con lo que lee de su detección, ``origin``: :class:`~.supported_store.PlatformOrigin`) y ``resting`` la lista, única, de **lo que se le
    apoyaba** (A7, RF-016-14: :func:`~.removal.resting_on`, antes de calcular), que no se retira sin la confirmación expresa
    (:meth:`~.steps.Calculation.confirm_removal`); ``None`` y vacía en la plataforma de una capa, que no cambia."""

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
    insertion: tuple[entities.ParamChange, ...] = ()
    removed: RemovedStockpile | None = None
    origin: PlatformOrigin | None = None
    resting: tuple[Resting, ...] = ()

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
    _check_name(registry, request.name, chosen, version.code)
    return chosen, registry


def _entity_object(code: str, name: str) -> str:
    """El objeto de un rechazo sobre la entidad de código ``code`` y nombre ``name``, con el nombre de su tipo para las personas:
    ``Plataforma «P1»``, ``Retirada de acopio «R1»``, ``Contrafuerte «C1»`` (spec 016, T47: lo que comparten crear y cambiar el
    parámetro de cualquier tipo; el de la plataforma, el de siempre)."""
    return f"{entity_params_of(code).label or 'Entidad'} «{name}»"


def _check_name(registry: EntityRegistry, name: str, code: str, version_code: str) -> None:
    """RF-015-01: ninguna otra entidad del ``registry`` (la de código ``code`` no cuenta consigo misma) tiene el
    nombre ``name`` —también el de una sin calcular o descartada— ni uno que dé el mismo nombre de dato
    (``des.entity_name_repeated``, con la que lo tiene). Lo comparten crear, recalcular y cambiar el parámetro
    ``name`` de **cualquier tipo** (:func:`check_parameter_change`, T39 y T47)."""
    wanted = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, name)
    for entry in registry:
        other = entry.record.name
        if entry.record.code != code and (
                other == name or provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, other) == wanted):
            raise DesignError("des.entity_name_repeated", obj=_entity_object(code, name),
                              field=entity_key(code, PlatformParam.NAME), value=name,
                              other=other, version=version_code)


def _check_surface_left(registry: EntityRegistry, name: str, code: str, ref: str | None, field: str, *, obj: str) -> None:
    """**Nadie parte de la superficie de un cuerpo «bajo un techo»** (spec 016, T25; decisión de la sesión principal del 18/11/2026;
    H-9, RF-016-20): ese cuerpo no cambia la superficie y no la escribe, así que una entidad que parte de ``entity:<su código>``
    (``ref``, la partida o la superficie conocida de la entidad ``code`` de nombre ``name``) se rechaza con ``des.chainless_start``
    nombrando las dos, **antes de calcular nada y sin escribir nada**. El de un tipo sin cadena (la detección) lo rechaza
    :func:`~.entities.check_chain` por su tipo; este es el rechazo **por instancia**, de un tipo que encadena y cuya instancia no
    tiene partida. Una referencia que no es de una entidad de ``registry``, o de una que deja su superficie, pasa (la rechaza, si
    hace falta, :func:`_surface_dataset`). ``field`` es la clave de lo que se rechaza."""
    target = entities.ref_code(ref)
    if target is None:
        return
    entry = registry.get(target)
    if entry is not None and entry.record.kind is EntityKind.BODY and entry.record.start is None:
        raise DesignError("des.chainless_start", obj=obj, field=field, value=ref, entity=name, other=entry.record.name)


def _check_chain(registry: EntityRegistry, request: PlatformRequest, code: str,
                 insert_before: str | None = None) -> None:
    """RF-015-04: de cada superficie parte como mucho una entidad (``des.entity_start_taken``, con la
    que ya parte) y la cadena no da la vuelta (``des.entity_chain_cycle``); la entidad ``code`` no
    cuenta consigo misma. Con ``insert_before`` (RF-015-05: la entidad de código o nombre que pasará a
    partir de la superficie de la nueva), la entidad nueva parte de la **misma** superficie que ella y
    no choca con ella: la cadena se comprueba con ella ya re-apuntada a la nueva (``ValueError``, error
    del programa, si no existe o parte de otra superficie)."""
    _check_chain_of(registry, request.name, request.start, request.support, code, insert_before)


def _check_chain_of(registry: EntityRegistry, name: str, start: str | None, support: str | None, code: str,
                    insert_before: str | None = None) -> None:
    """:func:`_check_chain` de la entidad ``code`` de nombre ``name`` con su partida ``start`` y su apoyo
    ``support``: lo que comparten crear, recalcular y cambiar el parámetro ``start`` de cualquier tipo que encadena (T39 y T47: el
    tipo es el del código de la entidad)."""
    obj = _entity_object(code, name)
    _check_surface_left(registry, name, code, start, entity_key(code, PlatformParam.START), obj=obj)
    records = [item for item in registry.records if item.code != code]
    if insert_before is None:
        other = entities.start_conflict(registry.records, start, ignoring=code)
        if other is not None:
            raise DesignError("des.entity_start_taken", obj=obj,
                              field=entity_key(code, PlatformParam.START), value=start,
                              entity=name, other=other.name)
    else:
        successor = entities.find_entity(records, insert_before)
        if successor is None:
            raise ValueError(f"la versión no tiene ninguna entidad con el código o el nombre "
                             f"{insert_before!r}: no se puede insertar la plataforma "
                             f"«{name}» antes de ella")
        if (successor.start or "").strip() != (start or "").strip():
            raise ValueError(
                f"la plataforma «{name}» se inserta antes de «{successor.name}», que parte de "
                f"{successor.start!r}, pero ella parte de {start!r}: la insertada parte de la "
                "misma superficie (entities.insertion_start)")
        records = [replace(item, start=entities.surface_ref(code)) if item is successor else item
                   for item in records]
    this = EntityRecord(code, name, entities.kind_of_code(code), start, support)
    entities.check_chain([*records, this])


def _insertion(registry: EntityRegistry, request: PlatformRequest, code: str,
               insert_before: str | None) -> tuple[entities.ParamChange, ...]:
    """El cambio de la partida de la entidad ``insert_before`` (RF-015-05; T31), que pasa a partir de la
    superficie de la plataforma ``request`` de código ``code`` que se inserta antes de ella: el de
    ``entities.insert_before``, con su motivo en español (sin escribir nada). Sin ``insert_before``, nada.
    Lo que comprueba :func:`_check_chain` (que existe y parte de la misma superficie) no se repite aquí."""
    if insert_before is None:
        return ()
    others = [item for item in registry.records if item.code != code]
    new = EntityRecord(code, request.name, EntityKind.PLATFORM, request.start, request.support)
    return entities.insert_before(others, insert_before, new)


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


_NOT_CALCULATED = frozenset({PlatformParam.SUPPORTS, PlatformParam.DISCARDED})
"""Los valores de la entidad que **no** entran en el cálculo ni se piden al calcularla: lo que declara la persona
(``supports``, RF-015-15) y si se descartó sin calcular (``discarded``, RF-015-17); los resuelve quien los usa."""


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
        PlatformParam.REASON: request.reason, PlatformParam.STOCKPILE: request.stockpile}
    required = {PlatformParam.WIDTH: line, PlatformParam.GUARD: request.protect}
    values: dict[str, Any] = {}
    for param in PlatformParam:
        if param in _NOT_CALCULATED or (param is PlatformParam.WIDTH and not line):
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


def _stockpile_rows(rows: tuple[EntityParamRow, ...], origin: PlatformOrigin, name: str) -> tuple[EntityParamRow, ...]:
    """Las filas de los parámetros de una plataforma que retira un acopio «como plataforma» (spec 016, T21; RF-016-16, RF-008-01) con **su
    procedencia**: la cota inicial y la pendiente salen **del plano de la base del acopio** y la capa y la marca, **de la marca del acopio**
    (ni una ni otra de una capa de plataformas: informativas, no las lee la operación); el acopio y lo demás, lo que eligió la persona. Los
    mismos valores y las mismas claves."""
    plane = f"plano de la base del acopio «{origin.item.name}» ({origin.ref}), ajustado a su huella"
    mark = f"marca del acopio «{origin.item.name}» ({origin.ref})"
    found: list[EntityParamRow] = []
    for row in rows:
        if str(row.param) in (PlatformParam.START_LEVEL.value, PlatformParam.GRADIENT.value):
            row = replace(row, source=plane, source_kind="algorithm",
                          reason=f"Del plano de la base del acopio «{origin.item.name}» al retirarlo como plataforma «{name}»")
        elif str(row.param) in (PlatformParam.LAYER.value, PlatformParam.FEATURE.value):
            row = replace(row, source=mark, source_kind="algorithm",
                          reason=f"De la marca del acopio «{origin.item.name}» al retirarlo como plataforma «{name}»")
        found.append(row)
    return tuple(found)


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
                   role: str, grid: Grid, found: SurfaceWindow, cells: np.ndarray, window: tuple[slice, slice]
                   ) -> None:
    """RF-015-09: ninguna celda de la huella ``cells`` (de la ventana ``window`` de la rejilla ``grid``) sin dato en la
    superficie de nombre ``surface`` (``found``: lo leído de ella, de su ventana o entera; ``ValueError`` si
    ``window`` no está dentro de lo leído): si no, ``des.entity_nodata`` con la entidad, la superficie, su ``role``
    (partida o apoyo), el área sin dato (m²) y el centro absoluto de la primera celda (de norte a sur y de oeste a
    este)."""
    missing = cells & ~np.isfinite(window_part(found.values, found.window, window))
    if not missing.any():
        return
    rows, cols = np.nonzero(missing)
    x = float(grid.west + (int(cols[0]) + window[1].start + 0.5) * grid.dx)
    y = float(grid.north - (int(rows[0]) + window[0].start + 0.5) * grid.dy)
    raise DesignError("des.entity_nodata", obj=_object(request), field=entity_key(code, param),
                      value=surface, entity=request.name, area=round(rows.size * grid.cell_area, 2),
                      surface=surface, role=role, x=x, y=y)


def _check_has_data(request: PlatformRequest, code: str, param: PlatformParam, surface: str,
                    role: str, grid: Grid, found: SurfaceWindow) -> None:
    """Una superficie sin ninguna celda con dato no tiene huella que comprobar (ni cotas con que
    comprobar las de la rasante): ``des.entity_nodata`` con toda la rejilla (``found`` es entera: una ventana sin
    dato no se queda en ella, :func:`_read_surface`)."""
    if np.isfinite(found.values).any():
        return
    full = (slice(0, grid.nrows), slice(0, grid.ncols))
    _check_no_data(request, code, param, surface, role, grid, found, np.ones(grid.shape, dtype=bool), full)


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


def _surface_owners(registry: EntityRegistry, surface: str | None) -> set[str]:
    """Los códigos de las entidades de ``registry`` cuya superficie es ``surface``: ``entity:<código>`` es la de esa
    entidad y el nombre de un dato (``des_psf_<nombre>``), la de la entidad de ese nombre (también el que da el
    mismo nombre de dato). Sin superficie, o si es la de una que no es de una entidad (el terreno, una de diseño),
    ninguna."""
    if surface is None or not surface.strip():
        return set()
    wanted = surface.strip()
    code = entities.ref_code(wanted)
    if code is not None:
        return {code} if registry.get(code) is not None else set()
    return {entry.record.code for entry in registry
            if provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, entry.record.name) == wanted}


def _check_support_cycle(registry: EntityRegistry, name: str, code: str, support: str | None, field: str,
                         version_code: str, insert_before: str | None = None) -> None:
    """RF-015-15, RF-015-05 (T39; hallazgo A-1): la superficie de apoyo ``support`` de la entidad ``code`` (``name``) no
    es la suya ni la de una entidad que parte de la suya (:func:`~.entities.unsupportable`: aguas abajo de su cadena y,
    al **insertarla** ante otra, esa y las que la siguen, que pasarán a partir de ella): apoyarse en ellas sería un
    ciclo (``des.entity_supports_unknown`` con el motivo y la entidad). ``field`` es la clave de lo que se
    rechaza (``des.platform.{e}.support``)."""
    cyclic = _surface_owners(registry, support) & entities.unsupportable(
        registry.records, code, insert_before=insert_before)
    if cyclic:
        target = min(cyclic, key=entities.code_order)
        raise DesignError("des.entity_supports_unknown", obj=_entity_object(code, name), field=field, value=support,
                          entity=name, target=target,
                          reason=_SUPPORT_ITSELF if target == code else _SUPPORT_CYCLE, version=version_code)


def _support_inputs(project: StoreProject, version: Version, request: PlatformRequest, code: str,
                    registry: EntityRegistry, support_name: str | None, released: Collection[str] = (),
                    insert_before: str | None = None) -> tuple[tuple[str, ...], tuple[Use, ...], bool]:
    """Las entradas ``supported_on`` que la plataforma ``code`` **ya** tiene al prepararla, sin esperar al
    resultado (RF-015-15; T23): los datos de las superficies en las que se apoya —la de apoyo de la petición
    (``support_name``) y las que declara la persona (:func:`declared_supports`), cada una **con la tabla de su
    huella**, ``support_footprint``, que es lo que permite reproducir lo apoyado sin el proyecto— como
    ``(superficies, tablas)`` (los nombres de los datos, que :func:`~.provenance.platform_inputs` anota, y las
    entradas de las tablas). Una declarada que no existe, no está calculada, se descartó, es ella misma o
    parte de ella (un ciclo) se rechaza: ``des.entity_supports_unknown``, sin escribir nada. El tercer valor
    dice si la entidad tiene la fila ``supports`` en la versión: solo entonces la operación **lee** ese
    parámetro (``begin_operation`` crearía en el proyecto una fila «sin confirmar» por cada entidad que no
    declara nada: trampa de la T04) y cambiar lo declarado la deja obsoleta (RF-015-16). Lo declarado en una
    entidad que la persona **dio por buena sin su apoyo** (``released``: los códigos que sueltan los ajustes de la
    operación que se sustituye y los de la nueva, T25; RF-015-17) se salta: ni se pide ni se rechaza (se descartó).
    **La superficie de apoyo de la petición** (``support_name``) se comprueba igual (T39; hallazgo A-1): no puede ser la
    de la propia entidad ni la de una que parte de la suya, y con ``insert_before`` (la entidad ante la que se inserta la
    nueva) tampoco la de esa ni la de las que la siguen, que pasarán a partir de ella
    (:func:`_check_support_cycle`: ``des.entity_supports_unknown``)."""
    _check_support_cycle(registry, request.name, code, request.support, entity_key(code, PlatformParam.SUPPORT),
                         version.code, insert_before)
    row = _declared_row(project, version, code)
    declared = tuple(target for target in _declared(row) if target not in released)
    with project.read() as conn:
        found = entity_surfaces(conn, registry)
    skip = _unsupportable(registry, code, (), insert_before)
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


def _read_surface(project: StoreProject, name: str, version: Version, frame: Any, role: str,
                  window: Window | None) -> SurfaceWindow:
    """La superficie ``name`` tal como está en su fichero, comparada con la rejilla del proyecto (``frame``) **antes de
    leer una celda** (RF-013-16): solo las celdas de ``window`` (las teselas que la tocan) o, sin ventana, la rejilla
    entera. Una ventana **sin ninguna celda con dato** no basta para saber si la superficie tiene alguna
    (``gis.raster_empty``) ni para decidir sobre una huella sin dato: se lee entera (T37)."""
    if window is not None:
        found = read_surface_window(project, name, window, version_uid=version.uid, expect=frame, role=role)
        if np.isfinite(found.values).any():
            return found
    raster = read_surface(project, name, version_uid=version.uid, expect=frame, role=role)
    return SurfaceWindow(name, (slice(0, raster.grid.nrows), slice(0, raster.grid.ncols)), raster.values)


def _surfaces(project: StoreProject, version: Version, request: PlatformRequest, code: str,
              registry: EntityRegistry, masks: access.MaskSet | access.MaskSource, window: Window | None
              ) -> tuple[str, SurfaceWindow, str | None, SurfaceWindow | None]:
    """El dato y las celdas de la superficie de partida y, si se pide, los de la de apoyo, leídos tal como están
    en su fichero y comparados con la rejilla del proyecto (RF-011-02, RF-011-03: ni se remuestrean ni se
    interpolan) y con la de las máscaras: solo en ``window`` (:func:`_read_surface`) o, sin ella, enteros."""
    frame = project_frame(project)
    start = _surface_dataset(registry, version, request, code, PlatformParam.START, request.start)
    found = _read_surface(project, start, version, frame, "superficie de partida", window)
    support = rest = None
    if request.support is not None:
        support = _surface_dataset(registry, version, request, code, PlatformParam.SUPPORT,
                                   request.support)
        rest = _read_surface(project, support, version, frame, "superficie de apoyo", window)
    if not frame.grid.same_geometry(masks.grid):
        raise ValueError("la rejilla de las máscaras no es la del proyecto")
    return start, found, support, rest


def _covers(read: Window, needed: Window) -> bool:
    """Si la ventana leída ``read`` contiene la que se necesita."""
    return all(have.start <= want.start and want.stop <= have.stop for have, want in zip(read, needed, strict=True))


def _stockpile_cut(item: RemovedStockpile, masks: access.MaskSet | access.MaskSource, read: Window) -> np.ndarray:
    """**La excepción de D-5** (spec 016, T21; RF-016-16, RF-016-11): bajar un acopio a su base **no es cortar terreno**, así que la huella del
    acopio se corta donde el **dominio por defecto** de la 012 (perímetro ∩ límite legal − intocables) lo admite, aunque su corte no esté admitido
    (RF-015-06): una máscara de la ventana ``read`` (de la forma de lo leído) con las celdas de su huella dentro del dominio. Lo de fuera de la
    huella, el borde de la plataforma, sí corta terreno y sigue las máscaras de siempre."""
    from . import supported_store

    rows, cols = np.divmod(item.cells, masks.grid.ncols)
    inside = np.zeros((read[0].stop - read[0].start, read[1].stop - read[1].start), dtype=bool)
    keep = (rows >= read[0].start) & (rows < read[0].stop) & (cols >= read[1].start) & (cols < read[1].stop)
    inside[rows[keep] - read[0].start, cols[keep] - read[1].start] = True
    return inside & supported_store.default_domain(masks, read)


def _platform_job(project: StoreProject, version: Version, request: PlatformRequest, code: str,
                  registry: EntityRegistry, masks: access.MaskSet | access.MaskSource,
                  geometry: PlatformGeometry, values: Mapping[str, Any], window: Window | None,
                  origin: PlatformOrigin | None = None
                  ) -> Generator[None, None, tuple[str, str | None, PlatformJob, Footprint]]:
    """Lo que depende de lo que se lee de las rejillas, **en** ``window`` (o enteras, sin ella): las superficies, la
    falta de dato de la partida, el trabajo con las máscaras de esa ventana, la huella (que comprueba la geometría y
    las cotas) y la falta de dato en la huella de la partida y de la de apoyo, en este orden y con las unidades de
    :func:`prepare_platform_units`. Devuelve el nombre de la partida y de la de apoyo, el trabajo y la huella.
    :class:`~.platform.NeedsWholeSurface` si la ventana no basta para decidir (el rango de cotas de RF-015-08 es el de
    la rejilla entera) o no contiene la ventana de trabajo de la huella (no pasa: :func:`~.platform.reading_window` la
    contiene siempre; es la red de seguridad): quien llama repite con la rejilla entera."""
    start_name, start, support_name, support = _surfaces(project, version, request, code, registry, masks, window)
    _check_has_data(request, code, PlatformParam.START, start_name, _START_ROLE, masks.grid, start)
    yield
    read = start.window
    cut, fill = admitted_pair(masks, read)
    if origin is not None:  # RF-016-16, D-5: la huella del acopio se baja a su plano donde el dominio por defecto lo admite
        cut = cut | _stockpile_cut(origin.item, masks, read)
    job = PlatformJob(request, code, masks.grid, start.values, geometry, values, cut, fill, region=read)
    footprint = yield from platform_footprint_units(job)
    if not all(_covers(found.window, footprint.window) for found in (start, support) if found is not None):
        raise NeedsWholeSurface("la ventana leída no contiene la de trabajo de la huella")
    yield
    _check_no_data(request, code, PlatformParam.START, start_name, _START_ROLE, masks.grid, start,
                   footprint.cells, footprint.window)
    if support is not None and support_name is not None:
        _check_no_data(request, code, PlatformParam.SUPPORT, support_name, _SUPPORT_ROLE, masks.grid, support,
                       footprint.cells, footprint.window)
    return start_name, support_name, job, footprint


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
    movable = np.isfinite(distance) & (job.cut_in(window) | job.fill_in(window))
    return footprint.cells | movable


def _released_codes(project: StoreProject, supersedes: str | None,
                    released: Iterable[provenance.ReleasedSupport]) -> frozenset[str]:
    """Los códigos de las entidades que la operación que se prepara da por buenas sin su apoyo (RF-015-17, T25): las
    que suelta ahora (``released``) y las que ya soltaba la operación que sustituye (``supersedes``; sus ajustes)."""
    found = {item.entity for item in released}
    if supersedes is not None:
        with project.read() as conn:
            row = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?", (supersedes,)).fetchone()
        if row is not None and row[0]:
            found |= {item.entity for item in provenance.released_supports(json.loads(str(row[0])))}
    return frozenset(found)


def prepare_platform_units(project: StoreProject, request: PlatformRequest, version: Version,
                           masks: access.MaskSet | access.MaskSource, *, code: str | None = None,
                           supersedes: str | None = None, insert_before: str | None = None,
                           released: Sequence[provenance.ReleasedSupport] = ()
                           ) -> Generator[None, None, PreparedPlatform]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan la
    plataforma ``request`` de la versión editable ``version`` con sus ``masks`` ya al día
    (:func:`~.store.masks_steps`; RF-015-06): el nombre único y el código (``code``: el de una entidad
    que ya está en la versión, que no choca consigo misma; si no, el siguiente, ``PLT-001``), la
    partida y la cadena, la capa con su geometría y sus campos, los parámetros resueltos, las
    superficies de partida y de apoyo, la huella (que comprueba la geometría), la falta de dato, los
    sectores con la búsqueda pendiente y lo que anotará la operación. Lee las superficies y las máscaras **solo en la
    ventana que el cálculo toca** (T37; :func:`~.platform.reading_window`; ``masks`` puede ser un
    :class:`~geoblender.gis.masks.access.MaskSource`, sin celdas) y cae a leerlas enteras si la ventana no basta para
    decidir: el trabajo (``job.region``) es de esa ventana, el resultado, el mismo. ``supersedes``: la operación hecha
    a la que sustituye (un recálculo). ``insert_before`` (spec 015, T12; RF-015-05): la entidad que
    hoy parte de la misma superficie y que pasará a partir de la de la nueva (una inserción: sin ello,
    esa superficie ocupada se rechaza). ``released`` (T25; RF-015-17, A7): las entidades descartadas que la
    nueva da por buenas sin su apoyo (las declaradas en ``supports`` no se piden ni se rechazan: se suman a las
    que ya soltaba la operación que sustituye). Devuelve la :class:`PreparedPlatform`. **Nada se escribe**;
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
    insertion = _insertion(registry, request, chosen, insert_before)
    yield
    origin: PlatformOrigin | None = None
    from_layer: dict[PlatformParam, float] = {}
    layer_fields: dict[PlatformParam, str] = {}
    if request.stockpile is not None:
        # RF-016-16 (T21, H-5): la geometría de la plataforma es la huella de un acopio —un dato producido de la versión: su detección—, no una
        # capa del proyecto, y su cota inicial y su pendiente salen del plano de su base: ni la capa ni sus campos intervienen
        from . import supported_store

        origin = supported_store.read_platform_origin(project, version, request, chosen)
        request = replace(request, fields=replace(request.fields, layer=origin.layer), feature=str(origin.source_fid))
        line = False
        geometry = origin.platform.geometry
        from_layer = {PlatformParam.START_LEVEL: origin.platform.start_level_m,
                      PlatformParam.GRADIENT: origin.platform.gradient_pct}
        fid = origin.source_fid
    else:
        layer = _layer(project, request.layer)
        index = feature_index(layer, request, chosen)
        line = layer.kind == "line"
        geometry = read_geometry(lambda name: _layer(project, name), layer, index, request)
        fields = request.fields
        kept = {} if code is None else _kept_numbers(project, version, chosen)
        corrected = _corrected(request)
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
    wanted = reading_window(geometry, values, masks.grid)
    try:
        start_name, support_name, job, footprint = yield from _platform_job(
            project, version, request, chosen, registry, masks, geometry, values, wanted, origin)
    except NeedsWholeSurface:
        if wanted is None:  # la rejilla entera no puede pedir más: un error del programa
            raise
        start_name, support_name, job, footprint = yield from _platform_job(
            project, version, request, chosen, registry, masks, geometry, values, None, origin)
    sectors = design_sectors(project, version.uid)
    if any(item.pending for item in sectors):
        zone = yield from _pending_zone(job, footprint, values)
        refs, labels = sector_layout(project, masks)
        touched = pipeline.touched_in(refs, labels[footprint.window], zone)
        refuse_pending(item for item in sectors if item.code in touched)  # RF-015-07
    yield
    common = _common(project, version)
    supported, footprints, reads = _support_inputs(
        project, version, request, chosen, registry, support_name,
        _released_codes(project, supersedes, released), insert_before)
    inputs = provenance.platform_inputs(request, start_name, masks.uses(), supported,
                                        () if origin is None else origin.removed)
    inputs = (*inputs, *(use for use in footprints if use not in inputs))
    begun = _start(project, provenance.PLATFORM, request.name, version, masks,
                   provenance.platform_settings(request, chosen), inputs,
                   provenance.platform_params(chosen, request, supports=reads), supersedes)
    yield
    rows = _rows(request, chosen, values, layer_fields)
    resting: tuple[Resting, ...] = ()
    if origin is not None:  # RF-016-14, A7: lo que se apoyaba en el acopio, una sola lista, antes de calcular
        from . import removal

        rows = _stockpile_rows(rows, origin, request.name)
        resting = removal.resting_on(project, version, origin.item, start_name, detected_on=origin.detected_on)
        listed = removal.resting_record(resting)
        if listed:  # lo que se le apoyaba, anotado: «apoyo retirado» lo lee sin las cifras del relleno (T45; S-1, B-1)
            begun = replace(begun, settings={**begun.settings, provenance.REMOVAL_RESTING: listed})
        yield
    return PreparedPlatform(job, footprint, begun, chosen, fid, rows, MappingProxyType(common),
                            start_name, support_name, code is not None, insertion,
                            None if origin is None else origin.item, origin, resting)


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


def _row_kind(row: EntityParamRow) -> str:
    """El tipo del valor de ``row`` (MEDIDO, ADOPTADO o HIPÓTESIS): el de la plantilla de su familia, la del tipo de su
    clave (``des.<tipo>.{e}.<valor>``). ``ValueError`` si no es la clave de un valor de una entidad."""
    found = parse_entity_key(row.key)
    if found is None:
        raise ValueError(f"«{row.key}» no es la clave de un valor de una entidad (des.<tipo>.<código>.<valor>)")
    return entity_params(found[1]).template(found[2]).kind


def _write_param(store: ParameterStore, target: sqlite3.Connection, row: EntityParamRow, who: str,
                 decided_at: Any, version: str | None) -> ParameterRecord:
    """Escribe ``row`` en ``version`` o, sin ella, **en el proyecto** (T04). Una fila del proyecto que ya existe **sin
    confirmar y con el decisor por defecto** la dejó ``begin_operation`` al abrir la operación de una entidad **de una
    versión** del mismo código (``docs/trampas.md`` §6: crea la de cada clave que lee): no es una entidad y no impide
    crear la del proyecto, así que se convierte en la de la persona (``ParameterStore.change``: queda su historial, el
    valor por defecto y el cambio). Cualquier otra fila que exista no se pisa (``core.param_exists``)."""
    kind = _row_kind(row)
    if version is None:
        existing = store.get(row.key, conn=target)
        if existing is not None and existing.unconfirmed and existing.decided_by == DEFAULT_DECIDER:
            return store.change(
                target, row.key, value=row.value, kind=kind, source=row.source, source_kind=row.source_kind,
                decided_by=who, decided_at=decided_at, reason=row.reason)
    return store.create(
        target, row.key, row.value, kind=kind, source=row.source, source_kind=row.source_kind, decided_by=who,
        decided_at=decided_at, reason=row.reason, version=version)


def set_entity_params(project: StoreProject, rows: Iterable[EntityParamRow], *, version: str | None,
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
    la entidad ya tiene alguna (no se pisa nada), ``VersionError`` si la versión no se edita.

    **En el ámbito de la operación** (spec 016, T04; D-15, H-3): ``version`` ``None`` escribe **los parámetros del
    proyecto**, los de una entidad cuya operación es de proyecto (la detección de acopios sobre una superficie del
    proyecto), con las mismas filas y la misma procedencia; y las filas **de cualquier tipo** de entidad (la clave dice
    el tipo: ``des.stockpile.stk_001.margin_m``). Las filas «sin confirmar» que una operación de versión dejó en el
    proyecto con el mismo código se convierten en las de la entidad (:func:`_write_param`)."""
    items = tuple(rows)
    store = ParameterStore(project)
    who = decided_by or project.session.user_host

    def write(target: sqlite3.Connection) -> tuple[ParameterRecord, ...]:
        return tuple(_write_param(store, target, row, who, decided_at, version) for row in items)

    if conn is not None:
        return write(conn)
    with project.write_transaction() as writing:
        return write(writing)


# --- Cambiar un parámetro de una entidad (spec 015, T39; spec 016, T47; RF-015-01, RF-015-04, RF-015-12) -------

_COMMON_RULED = frozenset({PlatformParam.NAME.value, PlatformParam.LAYER.value, PlatformParam.FEATURE.value,
                           PlatformParam.START.value, PlatformParam.SUPPORT.value, PlatformParam.MODE.value,
                           PlatformParam.PROTECT.value, PlatformParam.GUARD.value})
"""Los parámetros de una entidad de **cualquier tipo** cuyo cambio pasa por las reglas **entre** entidades que se aplican al
crearla (:func:`check_parameter_change`): los que dan su identidad y su sitio en la cadena (``name``, ``layer``, ``feature``,
``start`` y ``support``) y los que dan lo que declara (``mode``, ``protect`` y ``guard_m``), de los tipos que los tienen. El tipo,
el rango y las opciones de cada valor, y los demás parámetros, los comprueba su definición (``core.params.ParamDef``)."""
_KNOWN_SURFACES: Mapping[str, BodyParam] = MappingProxyType({"body": BodyParam.SURFACE})
"""El valor que es **una referencia más a una superficie** de los tipos que lo tienen, por tipo (spec 016, T47; hallazgos D-2 y C-4): la
superficie conocida del cuerpo apoyado (``des.body.{e}.surface``: el terreno, una superficie de diseño o ``entity:<código>``). Cambiarla
pasa por las reglas del apoyo (:func:`check_parameter_change`) y traer las entidades de otra versión la re-apunta como la partida y el
apoyo (:func:`bring_entities`). La superficie de una detección de acopios no está aquí: es el dato sobre el que se detecta, no una
referencia de la cadena."""


def _ruled(kind: str, param: str) -> bool:
    """Si el cambio del valor ``param`` de una entidad de tipo ``kind`` pasa por las reglas entre entidades (:data:`_COMMON_RULED` y
    la superficie conocida de los tipos que la tienen, :data:`_KNOWN_SURFACES`)."""
    return param in _COMMON_RULED or (kind in _KNOWN_SURFACES and param == _KNOWN_SURFACES[kind].value)


def _has_type(kind: str, param: str, value: object) -> bool:
    """Si ``value`` es del tipo del parámetro ``param`` de una entidad de tipo ``kind`` (un texto, o ``None``; un sí/no; un número): lo
    demás es cosa de la definición del parámetro, que lo rechaza con su propio texto."""
    if value is None:
        return True
    value_type = str(entity_params(kind).template(param).value_type)
    if value_type == "text":
        return isinstance(value, str)
    if value_type == "bool":
        return isinstance(value, bool)
    return isinstance(value, int | float) and not isinstance(value, bool)


def check_parameter_change(project: StoreProject, key: str, value: object, *, version: Version | str | None) -> None:
    """**Las reglas de crear, al cambiar un parámetro de una entidad** (spec 015, T39; spec 016, T47; RF-015-01, RF-015-04,
    RF-015-05, RF-015-08, RF-015-12, RF-015-15; hallazgos A-2, A-1 y B-1 de la 015 y D-2 de la 016): «Cambiar parámetro…» de la 008
    (``geoblender.core_set_parameter``) solo comprobaba el tipo y el rango de la definición, y dejaba una versión que ni preparaba,
    ni congelaba, ni declaraba; y desde la T39 solo lo hacía con las plataformas. Si ``key`` es ``des.<tipo>.{e}.<valor>`` de una
    entidad **de cualquier tipo registrado** (la plataforma, la detección de acopios, la retirada, el contrafuerte o el cuerpo apoyado)
    de la versión ``version`` (uid o código) y el valor es uno de los que tienen reglas (:data:`_COMMON_RULED`, y la superficie conocida
    del cuerpo, :data:`_KNOWN_SURFACES`), comprueba que el ``value`` nuevo (ya leído, en la unidad del parámetro) **no rompe** lo que
    se exige al crearla y la nombra en el rechazo (con la capa, el campo y el valor):

    - ``name``: no vacío (``des.entity_param_missing``) y único en la versión, también como nombre de dato
      (``des.entity_name_repeated``; :func:`_check_name`). ``layer`` y ``feature``: no vacíos, en los tipos que los tienen.
    - ``start``, en los tipos que encadenan: no vacía (salvo en el cuerpo «bajo un techo»), de ella parte como mucho otra entidad
      (``des.entity_start_taken``), la cadena no da la vuelta (``des.entity_chain_cycle``; :func:`_check_chain_of`) y nadie parte de
      la superficie de un cuerpo «bajo un techo» (``des.chainless_start``).
    - ``support`` (y la superficie conocida del cuerpo): ni la superficie de la propia entidad ni la de una que parte de la suya
      (``des.entity_supports_unknown``: un ciclo; :func:`_check_support_cycle`); y, en el contrafuerte y en el cuerpo, tampoco la de
      un cuerpo «bajo un techo» (``des.chainless_start``), como al crearlos.
    - ``mode``, ``protect`` y ``guard_m``: con lo que quedaría la entidad, no protege en «en corte y relleno»
      (``des.platform_protect_cut_fill``; solo la plataforma tiene modo) ni sin resguardo (``des.entity_param_missing``;
      :func:`_check_protection`: lo mismo que comprueba al declarar). Y **``protect`` verdadero solo en un tipo que declara** algo
      (:data:`_DECLARES`: la plataforma y el contrafuerte): en la retirada, el cuerpo y la detección de acopios se rechaza con
      ``des.protect_unsupported`` (spec 016, T48; observación (6) de la T47: la declaración haría ``_DECLARES[tipo]`` con un ``KeyError``).
      **La pista y la accesibilidad** (spec 017, T03) no tienen ``protect`` ni resguardo: cambiar su ``mode`` (el de la pista no es el de la
      plataforma) no comprueba nada de lo que declara (sin esa salida era un ``KeyError``).

    Una entidad descartada es un registro: solo se le comprueba el nombre, la capa y la geometría. **Solo lee**:
    se llama **antes** de abrir la transacción que escribe (el rechazo no deja ninguna). No hace nada si ``version``
    es ``None`` o no existe (lo dice el almacén de parámetros), si la clave no es de una entidad de la versión o si el
    valor no es del tipo del parámetro (lo dice su definición)."""
    found = parse_entity_key(key)
    if found is None or version is None:
        return
    code, kind, param = found
    if not _ruled(kind, param) or not _has_type(kind, param, value):
        return
    spec = entity_params(kind)
    with _consistent(project) as conn:
        chosen = version if isinstance(version, Version) else versions_read.version(conn, version)
        if chosen is None:
            return
        registry = entities.registry(project, chosen.uid, conn=conn)
        entry = registry.get(code)
        if entry is None or entry.record.code != code:
            return
        keys = {entity_key(code, item): item for item in (PlatformParam.LAYER, PlatformParam.PROTECT,
                                                          PlatformParam.MODE, PlatformParam.GUARD)
                if item.value in spec.names}
        resolved = ParameterStore(project).resolve_many(
            conn, tuple(keys), (VERSION_SCOPE, PROJECT_SCOPE), version=chosen.uid)
    now = {item: (resolved[name].value if resolved.get(name) is not None else spec.template(item.value).default)
           for name, item in keys.items()}
    record = entry.record
    layer = str(now[PlatformParam.LAYER]) if now.get(PlatformParam.LAYER) else _NO_VALUE
    if param == PlatformParam.NAME:
        _check_name(registry, str(check_entity_param(record.name, code, param, value, layer=layer)), code, chosen.code)
        return
    if param in (PlatformParam.LAYER, PlatformParam.FEATURE):
        check_entity_param(record.name, code, param, value, layer=layer)
        return
    if record.state is EntityState.DISCARDED:
        return
    obj = _entity_object(code, record.name)
    if param == PlatformParam.START:
        start = check_entity_param(record.name, code, param, value, layer=layer)
        _check_chain_of(registry, record.name, None if start is None else str(start), record.support, code)
    elif param == PlatformParam.SUPPORT:
        support = check_entity_param(record.name, code, param, value, layer=layer)
        if kind == EntityKind.BUTTRESS:  # como al crearlo: nadie se apoya en lo que un cuerpo «bajo un techo» no deja
            _check_surface_left(registry, record.name, code, None if support is None else str(support), key, obj=obj)
        _check_support_cycle(registry, record.name, code, None if support is None else str(support), key, chosen.code)
    elif kind in _KNOWN_SURFACES and param == _KNOWN_SURFACES[kind]:
        surface = str(check_entity_param(record.name, code, param, value, layer=layer))
        _check_surface_left(registry, record.name, code, surface, key, obj=obj)
        _check_support_cycle(registry, record.name, code, surface, key, chosen.code)
    else:
        if param == PlatformParam.PROTECT and value is True and kind not in _DECLARES:  # lo que no declara nada no protege (T48)
            words = _NO_DECLARATION.get(kind, (kind, kind))
            raise DesignError("des.protect_unsupported", obj=obj, field=key, value=value, entity=record.name, kind=words[0],
                              kind_en=words[1])
        if PlatformParam.PROTECT.value not in spec.names:
            return  # la pista (``mode`` es el suyo, no el de la plataforma) no declara nada: sin ``protect`` ni resguardo (spec 017, T03)
        after = {**now, param: value}  # lo que quedaría la entidad con el valor nuevo
        guard = after[PlatformParam.GUARD]
        _check_protection(record.name, code, layer, bool(after[PlatformParam.PROTECT]),
                          str(after.get(PlatformParam.MODE, PlatformMode.CUT.value)),
                          None if guard is None else float(guard))  # type: ignore[arg-type]


# --- Calcular (spec 015, T12; RF-015-03, RF-015-29) ---------------------------------------------

_COMPUTE_PHASE = "platform_compute"


def platform_compute_steps(job: PlatformJob, common: Mapping[str, object], *,
                           footprint: Footprint | None = None,
                           confirm_counterslope: bool = False, previous: Previous | None = None,
                           operation: str = "", quarry: QuarryOrder | None = None,
                           removed: RemovedStockpile | None = None,
                           budget_s: float = STEP_BUDGET_S
                           ) -> Generator[Progress, None, PlatformOutcome]:
    """Los pasos que calculan la plataforma de ``job`` (RF-015-03, RF-015-29; plan 015 §5.3.1: el
    ``platform_compute_steps`` que **comparten «Calcular», el recálculo y la reproducción**), sin
    proyecto y sin escribir nada (``yield from``; cerrar el generador no deja nada): la huella y la
    rasante (``footprint``, si ya se calculó al preparar; si no, aquí, por pasos:
    :func:`~.platform.platform_footprint_units`), aplicarla
    (``apply_platform_steps``), el borde (``platform_edge_steps``) y el perfil con las cifras y los
    avisos (``platform_outcome``), por pasos de ``budget_s`` como mucho. ``common`` son los parámetros del
    proyecto que lee el cálculo (``provenance.PLATFORM_COMMON_PARAMS``: la tolerancia de cara, el umbral de
    magnitud, el espesor mínimo y el salto creado, ya resueltos). ``confirm_counterslope``, ``previous``
    (con qué se compara la magnitud), ``operation`` (el nombre que da la nota de que no hay con qué
    compararla) y ``quarry`` (la otra superficie de la cantera, RF-015-14) son los de
    ``platform.platform_outcome``. Los rechazos son los de esas funciones y salen al avanzar. El perfil no
    se parte (37 ms con 1,2 M celdas): es una unidad; la huella sí (T44, hallazgos D-2 y A-3: un eje
    digitalizado de muchos vértices tardaba segundos de una sola llamada).

    **Retirar un acopio «como plataforma»** (spec 016, T21; RF-016-16, A9): ``removed`` es el acopio cuya huella es la geometría de ``job``
    (:func:`~.removal.platform_of_stockpile`); el resultado lleva además lo de una retirada (:class:`~.removal.PlatformRemoval`: lo retirado, lo
    apoyado y lo que las máscaras no dejan cortar, con las cifras ``des.rmv_*``), que comparten «Calcular», el recálculo y la reproducción.
    Sin él, **nada cambia** (la plataforma de una capa).
    Devuelve el :class:`~.platform.PlatformOutcome`."""
    name = job.request.name
    yield Progress(_COMPUTE_PHASE, 0, 1, f"Calculando la plataforma «{name}»…")
    if footprint is None:
        footprint = yield from pipeline.forward(pace_progress(
            platform_footprint_units(job), budget_s, phase=_COMPUTE_PHASE,
            running=f"Calculando la plataforma «{name}»…",
            finished=f"Huella de la plataforma «{name}» calculada"))
        yield Progress(_COMPUTE_PHASE, 0, 1, f"Huella de la plataforma «{name}» calculada")
    applied = yield from pipeline.forward(apply_platform_steps(job, footprint, budget_s=budget_s))
    edge = yield from pipeline.forward(
        platform_edge_steps(job, footprint, applied, common, budget_s=budget_s))
    yield Progress(_COMPUTE_PHASE, 1, 1, f"Perfil de la plataforma «{name}»…")
    outcome = platform_outcome(job, footprint, applied, edge, common,
                               confirm_counterslope=confirm_counterslope, previous=previous,
                               operation=operation, quarry=quarry)
    if removed is not None:  # RF-016-16: la misma operación es la retirada del acopio
        from . import removal  # el dominio de la retirada solo se carga al retirar «como plataforma»

        outcome = removal.with_removal(outcome, job, removed)
    return outcome


def _whole_start_steps(project: StoreProject, prepared: PreparedPlatform, budget_s: float
                       ) -> Generator[Progress, None, np.ndarray]:
    """La superficie de partida **entera** (un array nuevo que el llamador puede modificar), por pasos: la copia del
    trabajo si leyó la rejilla entera o, si solo leyó su ventana (T37: lo que basta para calcular), la rejilla
    entera de la partida leída por bandas de filas dentro del cálculo, que es lo que hace falta para escribir la
    superficie de salida. La ventana leída antes ha de ser **igual** a la de ahora (bit a bit, el NaN incluido): si
    el dato cambió en medio, ``des.input_changed`` (RF-013-17, D-14) y no se escribe nada."""
    job = prepared.job
    if job.whole:
        return np.array(job.start, dtype=np.float64, copy=True)
    name = prepared.job.request.name
    raster = yield from pipeline.forward(pace_progress(
        read_surface_steps(project, prepared.start_surface, version_uid=prepared.start.version_uid,
                           expect=project_frame(project), role="superficie de partida"),
        budget_s, phase=_COMPUTE_PHASE, running=f"Leyendo la superficie de partida de «{name}»…",
        finished="Superficie de partida leída"))
    whole = np.array(raster.values, dtype=np.float64, copy=False)
    region = job.window
    if not np.array_equal(whole[region], job.start, equal_nan=True):
        raise DesignError("des.input_changed", obj=f"Superficie «{prepared.start_surface}»", field="entradas",
                          value=prepared.start_surface)
    return whole


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
        quarry=quarry, removed=prepared.removed, budget_s=budget_s)
    surface = yield from _whole_start_steps(writer.project, prepared, budget_s)
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
    if geometry.given_axis is not None:  # el eje de la huella de un acopio «como plataforma» (T21): tal cual
        feed("given", ((np.asarray(geometry.given_axis.vertices, dtype=np.float64),),))
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
    rasante) y lo que la rejilla le recorta (T46: las celdas y el área de huella fuera de la rejilla, con el
    lugar de la primera en la nota); lo aplicado (corte y relleno, celdas, lo que las máscaras no dejan
    mover, lo que no queda en la rasante y lo que no se mueve) con una fila por grupo de celdas por encima o por debajo
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
    scalar("footprint_outside_cells", footprint.outside_cells, "-")
    scalar("footprint_outside_area_m2", footprint.outside_area_m2, "m2",
           _place(footprint.outside_x, footprint.outside_y, "footprint_outside"))
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
    if outcome.removal is not None:  # retirar un acopio «como plataforma» (T21; RF-016-16, RF-016-13)
        removed = outcome.removal
        for key, value, unit in (
                ("rmv_removed_m3", removed.removed_m3, "m3"), ("rmv_resting_m3", removed.resting_m3, "m3"),
                ("rmv_transition_m3", removed.transition_m3, "m3"), ("rmv_kept_m3", removed.kept_m3, "m3"),
                ("rmv_above_base_m3", removed.above_base_m3, "m3"), ("rmv_transition_m2", removed.transition_m2, "m2")):
            scalar(key, value, unit)
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
    "AND io.role IN ({roles}) AND io.operation_uid IN ({marks})")


@dataclass(frozen=True, slots=True)
class EntitySurface:
    """Lo que hace falta de una entidad viva y calculada para apoyar algo en ella (RF-015-15, plan 015 A6):
    su ``code``, el nombre del dato de su superficie (``surface``, ``des_psf_``), el de su tabla (``table``,
    ``des_epr_``) y la ubicación de esa tabla (``locator``) con su huella; y, desde la 016 (T02), su tipo
    (``kind``) y el uid de su operación vigente (``operation_uid``), con cuyos papeles se leyó."""

    code: str
    surface: str
    table: str
    locator: str
    kind: entities.EntityKind = entities.EntityKind.PLATFORM
    operation_uid: str = ""


def entity_surfaces(conn: sqlite3.Connection, registry: EntityRegistry, *,
                    skip: Iterable[str] = (), kinds: Iterable[entities.EntityKind | str] | None = None
                    ) -> dict[str, EntitySurface]:
    """Las entidades de ``registry`` en las que se puede apoyar algo (:data:`_SUPPORTABLE`), salvo las de
    ``skip``, cada una con su superficie y su tabla vigentes (las que escribió su operación vigente), por
    código (tipo y número). Una consulta por cada 400 entidades. Solo lee.

    **Por tipo** (spec 016, T02; plan 016 §2.1): cada entidad se lee con los **papeles de su tipo**
    (:attr:`~.entities.EntityType.surface_role` y ``table_role``: los de la plataforma son ``entity_surface`` y
    ``entity``; un tipo que no deja una superficie en la que apoyarse, sin papeles, no sale) y por el uid de su
    operación vigente; ``kinds`` (los tipos o sus valores) deja solo los de esos tipos (:class:`ValueError` si
    alguno no está registrado). Dos entidades de **una misma operación** salen las dos (cada una con su
    ``operation_uid``): el dato se busca por la operación, no se queda con el de la última."""
    omitted = set(skip)
    wanted = None if kinds is None else {entities.EntityKind(kind) for kind in kinds}
    live: dict[str, list[tuple[str, entities.EntityKind]]] = {}
    for entry in registry:
        kind = entities.EntityKind(entry.record.kind)
        if (entry.operation_uid is None or entry.record.state not in _SUPPORTABLE
                or entry.record.code in omitted or (wanted is not None and kind not in wanted)
                or entities.entity_type(kind).surface_role is None):
            continue
        live.setdefault(entry.operation_uid, []).append((entry.record.code, kind))
    roles = sorted({role for owners in live.values() for _code, kind in owners
                    for role in (entities.entity_type(kind).surface_role, entities.entity_type(kind).table_role)
                    if role is not None})
    found: dict[str, dict[str, tuple[str, str]]] = {}
    uids = sorted(live)
    for first in range(0, len(uids), 400):
        part = uids[first:first + 400]
        sql = _SUPPORT_DATA.format(roles=", ".join("?" for _ in roles), marks=", ".join("?" for _ in part))
        for uid, role, name, locator in conn.execute(sql, (DATASET, *roles, *part)):
            for code, _kind in live[str(uid)]:
                found.setdefault(code, {})[str(role)] = (str(name), str(locator))
    by_code = {code: (uid, kind) for uid, owners in live.items() for code, kind in owners}
    result: dict[str, EntitySurface] = {}
    for code in sorted(found, key=entities.code_order):
        data = found[code]
        uid, kind = by_code[code]
        spec = entities.entity_type(kind)
        surface = data.get(spec.surface_role) if spec.surface_role is not None else None
        table = data.get(spec.table_role) if spec.table_role is not None else None
        if surface is not None and table is not None:
            result[code] = EntitySurface(code, surface[0], table[0], table[1], kind, uid)
    return result


def _unsupportable(registry: EntityRegistry, own_code: str | None, written: Collection[str],
                   insert_before: str | None = None) -> set[str]:
    """Las entidades en las que una operación **no** se apoya (RF-015-15): ella misma si es una entidad
    (``own_code``) y las que parten de su superficie, aguas abajo de la cadena (con ``insert_before``, la entidad
    ante la que se inserta la nueva y las que la siguen: :func:`~.entities.unsupportable`); y, de una operación que no
    es una entidad, las que parten de alguna de las superficies que escribe (``written``) y las que les
    siguen: apoyarse en ellas sería un ciclo en el grafo."""
    records = registry.records
    skip: set[str] = set()
    if own_code is not None:
        skip |= entities.unsupportable(records, own_code, insert_before=insert_before)
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
        """El volumen apoyado (m³) en cada entidad de ``supports``, por su referencia: su código (``PLT-001``) o, de un
        **acopio** (spec 016, T15; P-1), el de su detección y la clave de su marca (``STK-001#m07``)."""
        return {item.ref: item.volume_m3 for item in self.supports}

    def uses(self, have: Iterable[tuple[str, str]] = ()) -> tuple[Use, ...]:
        """Las entradas que la operación ha de anotar por cada entidad de ``supports`` —su superficie con el
        papel ``supported_on`` y su tabla con el ``support_footprint``, con la que se reproduce lo apoyado— y
        que aún no tiene (``have``: pares ``(dato, papel)`` de sus entradas). Los acopios de una detección **comparten**
        la superficie con que se detectó y la tabla de sus acopios: se anotan una sola vez (spec 016, T15)."""
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
        """Las cifras ``des.supported_m3`` de la operación ``name`` (una por entidad apoyada y, de una detección de acopios, **una por
        acopio**, con su clave en el ámbito: RF-016-14)."""
        return provenance.supported_figures(name, self.volumes)


def survey_supports(project: StoreProject, version: Version, results: Sequence[np.ndarray], start: str, *,
                    own_code: str | None = None, written: Collection[str] = (),
                    inputs: Iterable[tuple[str, str]] = (), start_values: np.ndarray | None = None,
                    released: Collection[str] = ()) -> SupportSurvey:
    """**Lo que apoya una operación sobre las entidades de su versión** (spec 015, T23; RF-015-15, D-11;
    plan 015 A6): la operación que deja las superficies ``results`` (``(filas, columnas)`` en la rejilla del
    proyecto) desde la de partida ``start`` (el nombre del dato; ``start_values`` si ya está leída) se apoya
    en cada entidad viva y calculada de ``version`` (:data:`_SUPPORTABLE`) en cuya huella rellena más del
    espesor mínimo de la 012 por encima de ``máx(partida, entidad)`` (:func:`~.entities.detect_supports`,
    con el volumen), y en las que ya lo eran (``inputs``: los pares ``(dato, papel)`` de lo que consume; las
    que declara la persona, la de apoyo de la petición y las que arrastra un recálculo) **aunque no apoye
    nada**. No se apoya en sí misma (``own_code``) ni en lo que parte de ella o de lo que escribe
    (``written``: los datos de sus superficies; :func:`_unsupportable`) ni en las que da por buenas sin su
    apoyo (``released``: los códigos que soltó la persona, T25; RF-015-17: el gancho no vuelve a registrarlas).
    De varias superficies (las de una cantera, las de un ajuste) cuenta la que más apoya
    (:func:`~.entities.strongest`).

    **Los acopios** (spec 016, T15; RF-016-14, P-1; plan 016 A13): una detección de acopios de la versión se mide **por acopio** (una
    fila de su ``des_stk_`` cada uno, :func:`_footprints_of`), todos sobre la superficie con que se detectó (``des_stp_``, que se lee
    una sola vez), y cada acopio que recibe relleno es un :class:`~.entities.Support` con su clave. Lo que la operación ya tenía como
    entrada de una detección no se «declara» acopio por acopio (la entrada no dice cuáles se apoyaban): un acopio sobre el que ya no se
    rellena no sale. **Las detecciones del proyecto** (spec 016, T45; hallazgo S-1; D-15) se miden igual (:func:`_with_project_detections`: sus acopios,
    con la superficie y la tabla **del proyecto** como entradas), salvo las que tapa una de la versión del mismo código o con un dato del mismo nombre.

    **Coste:** con la versión sin entidades, ni se llama (``design.store`` lo comprueba con una consulta).
    Si no hay celdas que suban más del espesor mínimo y nada declarado, solo se lee el registro; las huellas
    se leen solo si las hay, y la superficie de una entidad solo si su huella tiene relleno encima o ya era
    una entrada. Solo lee."""
    held = {name for name, role in inputs if role == provenance.SUPPORTED_ON_ROLE}
    with _consistent(project) as conn:
        found = entities.registry(project, version.uid, conn=conn)
        skipped = {*_unsupportable(found, own_code, set(written)), *released}
        wanted = entity_surfaces(conn, found, skip=skipped)
        wanted = _with_project_detections(project, conn, version, found, wanted, skipped)
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
    # Lo que la operación ya tenía como entrada se registra aunque no apoye nada, salvo en una detección de acopios (spec 016, T15): sus
    # acopios comparten la superficie con que se detectó y la entrada no dice **cuáles** se apoyaban; uno que ya no se apoya no sale.
    registered = {code for code, where in wanted.items()
                  if where.surface in held and where.kind is not entities.EntityKind.STOCKPILE}
    candidates = list(wanted) if filled.any() else sorted(registered, key=entities.code_order)
    if not candidates:
        return SupportSurvey()
    cells: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    with project.read() as conn:
        for code in candidates:
            for ref, runs in _footprints_of(conn, wanted[code]).items():
                rows, cols = entities.runs_cells(runs)
                inside = (rows.size > 0 and int(rows.max()) < ground.shape[0]
                          and int(cols.max()) < ground.shape[1])
                if inside and (ref in registered or bool(filled[rows, cols].any())):
                    cells[ref] = (rows, cols)
    if not cells:
        return SupportSurvey()
    read: dict[str, np.ndarray] = {}  # la superficie de una detección es una sola para todos sus acopios
    surfaces: dict[str, np.ndarray] = {}
    for ref in cells:
        where = wanted[provenance.split_support_ref(ref)[0]]
        if where.surface not in read:
            read[where.surface] = read_surface(project, where.surface, version_uid=version.uid, expect=frame,
                                               role="superficie de apoyo").values
        surfaces[ref] = read[where.surface]
    area = float(frame.grid.cell_area)
    best = entities.strongest(
        item for array in arrays for item in entities.detect_supports(
            array, ground, surfaces, cells, thickness, area, declared=sorted(registered & set(cells))))
    return SupportSurvey(best, MappingProxyType({item.code: wanted[item.code] for item in best}))


def _with_project_detections(project: StoreProject, conn: sqlite3.Connection, version: Version, listed: EntityRegistry,
                             wanted: dict[str, EntitySurface], skip: Collection[str]) -> dict[str, EntitySurface]:
    """``wanted`` (lo vivo en lo que puede apoyarse algo en ``version``: :func:`entity_surfaces`) **más las detecciones de acopios del proyecto**
    (spec 016, T45; RF-015-15, RF-016-14; D-15, hallazgo S-1): detectar sobre una superficie del proyecto —el terreno— es lo normal, y lo que se
    rellena en una versión sobre un acopio suyo se apoya en él como si la detección fuera de la versión (``stockpile_store.detections_on`` da las
    dos). Sin detecciones del proyecto, ``wanted`` igual y una consulta de más. **La de la versión tapa a la del proyecto de su mismo código**
    (``supported_store._locate``: ``STK-001`` es correlativo por ámbito) y la que tiene un dato (su superficie o su tabla) **del mismo nombre que uno
    de la versión** tampoco se mide: la operación consume por nombre, el de la versión antes que el del proyecto (``docs/trampas.md`` §6), y
    anotaría el que no es. Ninguna de las dos se mide a medias: no se apoya en ella. Las ``skip`` (lo que soltó la persona) tampoco."""
    registry = entities.project_registry(project, conn=conn)
    if not len(registry):
        return wanted
    shadowed = {entry.record.code for entry in listed}
    extra: dict[str, EntitySurface] = {}
    for code, where in entity_surfaces(conn, registry, skip={*skip, *shadowed}, kinds=(entities.EntityKind.STOCKPILE,)).items():
        names = (where.surface, where.table)
        if not any((own := dataset_registry.get(conn, name, version_uid=version.uid)) is not None and own.live for name in names):
            extra[code] = where
    if not extra:
        return wanted
    return dict(sorted({**wanted, **extra}.items(), key=lambda item: entities.code_order(item[0])))


def _footprints_of(conn: sqlite3.Connection, where: EntitySurface) -> dict[str, tuple[tuple[int, int, int], ...]]:
    """La huella en tramos de lo que se puede apoyar en la entidad ``where``, por la referencia de cada cosa (spec 016, T15; A13): la de
    una plataforma (y de la retirada, el contrafuerte y el cuerpo), la huella de su fila de ``des_epr_`` por su código; la de una
    **detección de acopios**, la de **cada fila** de su ``des_stk_`` por ``STK-001#clave``, en el orden de la tabla. Solo lee."""
    if where.kind is entities.EntityKind.STOCKPILE:
        return {provenance.support_ref(where.code, key): runs
                for key, runs in read_stockpile_footprints(conn, where.locator)[1].items()}
    return {where.code: read_entity_footprint(conn, where.locator).runs}


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
    job = prepared.job
    ground = job.start if job.whole else read_surface(
        project, prepared.start_surface, version_uid=prepared.start.version_uid,
        expect=project_frame(project), role="superficie de partida").values  # lo leído es solo la ventana
    surface = np.array(ground, dtype=np.float64, copy=True)
    surface[outcome.footprint.window] = outcome.result
    version = require_version(project, prepared.start.version_uid, provenance.PLATFORM)
    written = {provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, prepared.job.request.name)}
    return survey_supports(
        project, version, [surface], prepared.start_surface, own_code=prepared.code, written=written,
        inputs=[(use.item, str(use.role)) for use in prepared.start.inputs],
        start_values=ground).supports


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


def _with_resting_confirmation(project: StoreProject, start: OperationStart, prepared: PreparedPlatform, confirmed: bool,
                               decided_by: str | None) -> OperationStart:
    """``start`` con lo que se le apoyaba al acopio que se retira «como plataforma» **confirmado** en sus ajustes (T21; RF-016-14, error 59):
    ``des.removal_resting_unconfirmed`` si la persona no lo confirmó (``confirmed``); si lo hizo, quién (``decided_by``; por defecto, quien
    tiene abierto el proyecto), cuándo (ahora, UTC) y los m³ (``supported_store.Confirmed``)."""
    from . import removal, supported_store

    assert prepared.origin is not None
    removal.check_resting_confirmed(prepared.origin.item.name, prepared.resting, confirmed=confirmed)
    found = supported_store.Confirmed(decided_by or project.session.user_host, format_utc(project.clock.now()),
                                      math.fsum(row.volume_m3 for row in prepared.resting))
    return replace(start, settings={**start.settings, supported_store.CONFIRMED: found.settings()})


def _reuse_resting_confirmation(prepared: PreparedPlatform, confirmed: Any) -> PreparedPlatform:
    """``prepared`` de un **recálculo** de la plataforma que retira un acopio, con lo apoyado que la persona confirmó al crearla
    (``confirmed``: ``supported_store.Confirmed`` de los ajustes de la operación que se sustituye) **si lo apoyado de ahora no pasa de ello**; si
    lo pasa, o no había confirmada, ``des.removal_resting_unconfirmed`` y la operación anterior sigue vigente (un recálculo no confirma por la
    persona: T20, RF-016-14). Sin nada apoyado, ``prepared``."""
    if not prepared.resting:
        return prepared
    from . import removal, supported_store

    assert prepared.origin is not None
    total = math.fsum(row.volume_m3 for row in prepared.resting)
    covered = confirmed is not None and confirmed.covers_resting(total)
    removal.check_resting_confirmed(prepared.origin.item.name, prepared.resting, confirmed=covered)
    return replace(prepared, start=replace(prepared.start, settings={
        **prepared.start.settings, supported_store.CONFIRMED: confirmed.settings()}))


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


def apply_insertion(project: StoreProject, prepared: PreparedPlatform, *, version: str,
                    decided_by: str | None = None, conn: sqlite3.Connection) -> tuple[ParameterRecord, ...]:
    """**Aplica la inserción** de una plataforma (spec 015, T31; RF-015-05; RF-008-02, RF-008-24): cambia, en la
    transacción ``conn`` de quien crea la entidad, la partida de la sucesora (``prepared.insertion``: el
    parámetro ``start`` de la entidad que pasa a partir de la nueva, ADOPTADO, de ``decided_by`` —por defecto, quien
    tiene abierto el proyecto— con **su motivo**, el de ``entities.insert_after`` o ``insert_before``, y su
    historial). El cambio pone al día en la misma transacción la obsolescencia de la 008: la sucesora y, en
    cascada, las que la siguen quedan obsoletas con su causa, y las demás no. Sin inserción, nada. Devuelve los
    parámetros cambiados. ``ParamError`` si la sucesora ya parte de esa superficie (``core.param_unchanged``) o no
    tiene el parámetro: un error del programa, y nada queda a medias (la transacción es de quien llama)."""
    store = ParameterStore(project)
    who = _decider(decided_by, project)
    return tuple(store.change(conn, change.key, value=change.new,
                              source=_INSERT_SOURCE.format(name=prepared.job.request.name),
                              source_kind="person", decided_by=who, reason=change.reason, version=version)
                 for change in prepared.insertion)


def create_platform(project: StoreProject, writer: DesignWriter, prepared: PreparedPlatform,
                    outcome: PlatformOutcome, *, decided_by: str | None = None,
                    confirmed_resting: bool = False) -> Stored:
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
    mientras la nueva no pase de la confirmada más la tolerancia (T15).

    **Retirar un acopio «como plataforma»** (spec 016, T21; RF-016-16, RF-016-14): con algo apoyado en el acopio (``prepared.resting``), no se
    crea sin ``confirmed_resting`` (``des.removal_resting_unconfirmed``, antes de escribir nada) y la confirmación —quién, cuándo y cuántos m³—
    queda en los ajustes de la operación (``supported_store.CONFIRMED``), como la de una retirada."""
    outcome.ensure_creatable()
    start = prepared.start
    confirmed = _confirmation(project, outcome, decided_by)
    if confirmed is not None:  # RF-015-23: quién la confirmó, cuánto y cuándo, para el recálculo (T15)
        start = _with_confirmation(start, confirmed)
    if prepared.resting:
        start = _with_resting_confirmation(project, start, prepared, confirmed_resting, decided_by)

    def parameters(conn: sqlite3.Connection) -> None:
        key = entity_key(prepared.code, PlatformParam.NAME)
        if prepared.existing:
            if ParameterStore(project).get(key, version=start.version_uid, conn=conn) is None:
                raise ValueError(f"la entidad {prepared.code} no tiene sus parámetros en la versión: no "
                                 "está en ella (se prepara sin su código)")
        else:
            set_entity_params(project, prepared.rows, version=start.version_uid,
                              decided_by=decided_by, conn=conn)
        apply_insertion(project, prepared, version=start.version_uid, decided_by=decided_by, conn=conn)

    return writer.commit(start, figures=outcome.figures, message=outcome.message,
                         before_begin=parameters)


# --- Recalcular (spec 015, T14; RF-015-02, RF-015-16, RF-008-26) ---------------------------------


def entity_parameters(project: StoreProject, code: str, *, version: Version | None = None) -> dict[str, Any]:
    """Los parámetros vigentes de la entidad de código ``code`` (de cualquier tipo registrado) **en su ámbito** (spec 016,
    T04; D-15, H-3), por último segmento de su clave (:func:`~.provenance.supported_values`): los resuelve una operación
    que empezara ahora, sin los que no tienen valor. En una ``version``, el de la fila de la versión y, si no la tiene,
    el del proyecto (versión → proyecto, RF-009-24); **sin versión, el del proyecto** (la detección de acopios de una
    superficie del proyecto). Es la definición de la entidad (sus parámetros, no la capa ni los ajustes de la operación
    anterior) con la que se recalcula. Solo lee. ``ValueError`` si ``code`` no es el de una entidad de un tipo
    registrado."""
    keys = {entity_key(code, name): name for name in entity_params_of(code).names}
    store = ParameterStore(project)
    with project.read() as conn:
        found = (store.resolve_many(conn, tuple(keys), (PROJECT_SCOPE,)) if version is None
                 else store.resolve_many(conn, tuple(keys), (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid))
    return {name: item.value for key, name in keys.items()
            if (item := found.get(key)) is not None and item.value is not None}


def platform_parameters(project: StoreProject, version: Version, code: str) -> dict[str, Any]:
    """Los parámetros vigentes de la entidad de código ``code`` en la versión ``version``, por último
    segmento de su clave (:func:`~.provenance.platform_values`): los resuelve una operación que empezara
    ahora (el de la fila de la versión y, si no la tiene, el del proyecto), sin los que no tienen valor.
    Es la definición de la entidad (RF-015-01: sus parámetros de versión, no la capa ni los ajustes de la
    operación anterior) con la que se recalcula. Solo lee. Es :func:`entity_parameters` de una plataforma."""
    return entity_parameters(project, code, version=version)


_CALCULATED_FROM = (PlatformParam.LAYER, PlatformParam.FEATURE, PlatformParam.START)
"""Los parámetros sin los que una entidad sin calcular no tiene de dónde salir (su capa, su geometría y su
partida): :func:`entity_request` pide que los tenga."""


def entity_request(project: StoreProject, version: Version | str, code: str, *, start_level_field: str,
                   gradient_field: str, width_field: str) -> PlatformRequest:
    """**La petición de una entidad sin calcular** de la versión editable ``version`` (``Version``, uid o código; spec 015,
    T41; RF-015-18, CE-015-01; hallazgo C-12): la que dejan «Traer las entidades de…» y la versión que parte de otra, con sus
    parámetros y **ningún resultado**, a partir de lo que **ya tiene la versión** —sus parámetros vigentes,
    :func:`platform_parameters` (el nombre, la capa, la geometría, la partida, el apoyo, el modo, el borde, lo que protege)—
    como :func:`recompute_platform` hace con una entidad calculada. Es lo que se da a :func:`run_platform` (o a
    ``design.steps.platform_run`` con ``code=``) para calcularla: con su **código**, sin crear otra entidad ni escribir
    ningún parámetro (la cota inicial, la pendiente y el ancho salen de su fila de la versión, no de la capa), de modo que
    su historial es el de siempre y la dependencia «se apoya en» se detecta de nuevo al crearla (el gancho de
    ``DesignWriter.commit``).

    Los campos de la capa (``start_level_field``, ``gradient_field`` y, de una capa de líneas, ``width_field``) no son
    parámetros de la entidad —solo marcan de dónde salieron sus valores—: los da quien llama (los de por defecto del diálogo
    de «Plataforma…»); una capa de polígonos no lleva ancho ni **eje enlazado** (el campo y la capa del eje tampoco son
    parámetros: una plataforma de polígono que lo tenía se calcula con el eje principal del polígono, con su aviso).

    Solo lee. Rechazos, sin escribir nada: los de :func:`~.store.require_version` (``VersionError``, RF-009-21),
    ``des.entity_already_discarded`` (una descartada es un registro, no se calcula), ``des.entity_calculate_done`` (la
    entidad ya tiene resultado: se rehace con «Recalcular lo obsoleto») y ``des.entity_calculate_missing`` (sin capa,
    geometría o partida: la partida de una entidad traída que no existía en la versión queda sin valor); :class:`ValueError`
    si la versión no tiene ninguna entidad con ese código o nombre."""
    found = require_version(project, version.uid if isinstance(version, Version) else version, provenance.PLATFORM)
    entry = entities.registry(project, found.uid).get(code)
    if entry is None:
        raise ValueError(f"la versión {found.code} no tiene ninguna entidad con el código o el nombre {code!r}")
    record = entry.record
    obj = f"Plataforma «{record.name}»"
    if record.state is EntityState.DISCARDED:
        raise DesignError("des.entity_already_discarded", obj=obj, field="estado", value=str(record.state),
                          entity=record.name, version=found.code)
    if record.state is not EntityState.UNCALCULATED:
        raise DesignError("des.entity_calculate_done", obj=obj, field="estado", value=str(record.state),
                          entity=record.name, code=record.code, version=found.code)
    values = platform_parameters(project, found, record.code)
    stockpile = values.get(PlatformParam.STOCKPILE.value)
    of_stockpile = isinstance(stockpile, str) and bool(stockpile.strip())  # retira un acopio «como plataforma» (T21): sin capa ni geometría
    for param in ((PlatformParam.START,) if of_stockpile else _CALCULATED_FROM):
        text = values.get(param.value)
        if not isinstance(text, str) or not text.strip():
            raise DesignError("des.entity_calculate_missing", obj=obj, field=entity_key(record.code, param),
                              value=None, entity=record.name, code=record.code, version=found.code)
    if of_stockpile:
        settings = {"name": record.name, "code": record.code,
                    "fields": {"start_level_field": PLANE_FIELD, "gradient_field": PLANE_FIELD, "width_field": None,
                               "axis_field": None, "axis_layer": None}}
        return provenance.platform_request(settings, values)
    line = _layer(project, str(values[PlatformParam.LAYER.value])).kind == "line"
    settings = {"name": record.name, "code": record.code,
                "fields": {"start_level_field": start_level_field, "gradient_field": gradient_field,
                           "width_field": width_field if line else None, "axis_field": None, "axis_layer": None}}
    return provenance.platform_request(settings, values)


def _masks_to_read(project: StoreProject, version: Version, masks: access.MaskSet | None
                   ) -> access.MaskSet | access.MaskSource:
    """Las máscaras con que se prepara una plataforma que se calcula de una vez (:func:`run_platform`): las que se
    dan (al día: :func:`~.store._loaded_masks`) o, sin ellas, las de la versión **sin cargar sus celdas**
    (:func:`~geoblender.gis.masks.access.open_masks`: la preparación lee solo la ventana de la plataforma, T37;
    RNF-015-03) y, si no están al día, como siempre: se compilan por pasos y se cargan (RF-013-04)."""
    if masks is not None:
        return _loaded_masks(project, version, masks)
    try:
        return access.open_masks(project, version.uid)
    except access.MaskError:
        return _loaded_masks(project, version, None)


def run_platform(project: StoreProject, request: PlatformRequest, *, version: str | None,
                 code: str, masks: access.MaskSet | None = None, supersedes: str | None = None,
                 confirmed: provenance.CounterslopeConfirmation | None = None,
                 budget_s: float = STEP_BUDGET_S, released: Sequence[provenance.ReleasedSupport] = (),
                 resting_confirmed: Any = None) -> tuple[OperationHandle, Iterator[Progress]]:
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
    (``des.platform_counter_unconfirmed``) y la operación que sustituye sigue vigente.

    ``released`` (T25; RF-015-17, A7, P-6): las entidades descartadas que la operación nueva **da por buenas sin su
    apoyo**: no lleva sus entradas, lo declarado en ``supports`` sobre ellas no se rechaza y el motivo y el decisor
    van en sus ajustes (``provenance.SUPPORTS_RELEASED``, acumulados con los de la que sustituye).

    **Retirar un acopio «como plataforma»** (T21; RF-016-16, RF-016-14): con algo apoyado en el acopio, el recálculo **reutiliza lo que la persona
    confirmó al crear** (``resting_confirmed``: ``supported_store.Confirmed`` de los ajustes de la operación que se sustituye) mientras lo apoyado
    de ahora no pase de ello; si lo pasa, o no había confirmación, ``des.removal_resting_unconfirmed`` y la anterior sigue vigente."""
    found = require_version(project, version, provenance.PLATFORM)
    loaded = _masks_to_read(project, found, masks)
    prepared: PreparedPlatform = _result_of(prepare_platform_units(
        project, request, found, loaded, code=code, supersedes=supersedes, released=released))
    if confirmed is not None:  # se arrastra a la operación nueva (la misma decisión, no una nueva)
        prepared = replace(prepared, start=_with_confirmation(prepared.start, confirmed))
    if prepared.origin is not None:
        prepared = _reuse_resting_confirmation(prepared, resting_confirmed)
    handle = prepared.start.with_released(released).begin(project)
    return handle, _platform_run(project, handle, prepared, budget_s, confirmed)


def recompute_platform(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S,
                       released: Sequence[provenance.ReleasedSupport] = ()
                       ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.platform`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo
    obsoleto», RF-008-26; spec 015, T14; RF-015-02, RF-015-16): la plataforma de sus ajustes (el nombre, el
    código y los campos de su capa) con los **parámetros vigentes de su entidad en su versión**
    (:func:`platform_parameters`) y no los que leyó la operación que sustituye: una entidad se define por
    sus parámetros (RF-015-01). Devuelve lo de :func:`run_platform`; ``released``, también (T25: lo que da por
    bueno sin su apoyo). ``ValueError`` si los ajustes no son los de una plataforma o la petición no es de una
    versión."""
    project: StoreProject = request.project  # type: ignore[assignment]
    code = provenance.platform_code(request.settings)
    found = require_version(project, request.version, provenance.PLATFORM)
    asked = provenance.platform_request(request.settings,
                                        platform_parameters(project, found, code))
    resting = None
    if asked.stockpile is not None:  # lo apoyado que la persona confirmó al crear la retirada como plataforma (T21)
        from . import supported_store

        resting = supported_store.confirmed_of(request.settings)
    return run_platform(project, asked, version=found.uid, code=code,
                        supersedes=request.operation_uid,
                        confirmed=provenance.counterslope_confirmed(request.settings),
                        budget_s=budget_s, released=released, resting_confirmed=resting)


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


def quarry_order(project: StoreProject, version: Version, prepared: Any) -> QuarryOrder | None:
    """La otra superficie de la cantera de la 014 cuando la entidad parte de una de sus dos
    superficies (RF-015-14; ``des_fin_`` o ``des_exp_``), para comprobar ``final ≤ explotación ≤
    terreno`` con lo que ella cambia; ``None`` si parte de otra cosa (el terreno, un diseño de la 013, la
    superficie de otra entidad) o no cambia ninguna superficie. La lee del proyecto en la rejilla del proyecto
    (RF-011-02). Solo lee. ``prepared`` es lo que se preparó para calcularla —la plataforma
    (:class:`PreparedPlatform`) o, spec 016, T46, la retirada, el contrafuerte y el cuerpo «sobre una base»—: solo se
    lee su ``start_surface`` (``None``, el cuerpo «bajo un techo»: no cambia la superficie)."""
    start = prepared.start_surface
    if start is None:
        return None
    with project.read() as conn:
        origin = design_surface_of(conn, start, version.uid)
    if origin is None or origin.op_type != provenance.QUARRY:
        return None
    name, side, _order = _quarry_link(origin)
    other = _other_surface(name, side)
    found = read_surface(project, other, version_uid=version.uid, expect=project_frame(project),
                         role="otra superficie de la cantera")
    assert side is not None  # lo es de una cantera
    return QuarryOrder(name, side, start, other, found.values)


_CONSUMERS = (
    "SELECT DISTINCT o.fid, o.uid, o.op_type, o.settings FROM gb_operation_io AS io "
    "JOIN gb_operation AS o ON o.uid = io.operation_uid "
    "JOIN gb_revision AS r ON r.uid = o.revision_uid "
    "WHERE io.direction = 'in' AND io.item_kind = 'dataset' AND io.item_uid IN ({marks}) "
    "AND o.status = 'done' AND o.superseded_by IS NULL AND r.version_uid = ?")
_CONSUMERS_ANYWHERE = (
    "SELECT DISTINCT o.fid, o.uid, o.op_type, o.settings FROM gb_operation_io AS io "
    "JOIN gb_operation AS o ON o.uid = io.operation_uid "
    "WHERE io.direction = 'in' AND io.item_kind = 'dataset' AND io.item_uid IN ({marks}) "
    "AND o.status = 'done' AND o.superseded_by IS NULL")
"""Lo mismo que :data:`_CONSUMERS` **sin acotar a una versión** (spec 016, T12): las operaciones vigentes del proyecto y de
cualquier versión. Es la pregunta de lo que depende de un dato **del proyecto** (el de una detección de acopios sobre una
superficie del proyecto, D-15), que consumen operaciones del proyecto (la cubicación de la 011) y de las versiones."""
_OUTPUTS = (
    "SELECT DISTINCT item_uid FROM gb_operation_io WHERE direction = 'out' "
    "AND item_kind = 'dataset' AND operation_uid IN ({marks})")
_CHUNK = 400
"""Los uid por consulta (el límite de variables de SQLite es mayor)."""


_OPERATION_LABELS = {
    provenance.ENTITY_LAYER: "des.entity_layer_name",
    provenance.DECLARE_CONSTRAINTS: "des.entity_declaration_name",
}
"""Las operaciones de la versión sin nombre en sus ajustes y el mensaje que las nombra para una persona (spec 015, T51; H3-1)."""


def _consumer(kind: ObsoleteKind, uid: str, op_type: str, name: str) -> Obsolete:
    """Una operación que queda obsoleta: la de ``op_type`` que no trae nombre (``name`` es el de su tipo) lleva el mensaje que la
    nombra (``Obsolete.label``), no el identificador de su tipo."""
    label = _OPERATION_LABELS.get(op_type, "") if name == op_type else ""
    return Obsolete(kind, name, op_type, uid, label)


def _name_of(op_type: str, settings: object) -> str:
    """El nombre de una operación hecha: el ``name`` de sus ajustes o, sin él, su tipo."""
    try:
        found = json.loads(str(settings)) if settings else {}
    except ValueError:
        found = {}
    name = found.get("name") if isinstance(found, dict) else None
    return name if isinstance(name, str) and name else op_type


def _dependents(conn: sqlite3.Connection, datasets: Iterable[str], version_uid: str | None, *,
                exclude: Iterable[str | None] = ()) -> list[tuple[str, str, str]]:
    """Lo que depende de los datos ``datasets`` en la versión ``version_uid`` (RF-015-16; la 008): las
    operaciones **vigentes** de la versión (hechas y no sustituidas, estén en la revisión que estén: lo
    registrado en una revisión que luego se congeló sigue siendo lo vigente, y el grafo de la 008 lo marca
    obsoleto en la revisión abierta, D-23 de la 009) que los consumen y, en cascada, las que consumen lo que
    escribieron esas, por orden de registro; como ``(uid, tipo, nombre)``. Sin las de ``exclude``. Lo
    **congelado** (los elementos de una revisión congelada) no cambia ni se marca (RF-009-19). Con
    ``version_uid`` ``None`` (spec 016, T12: los datos son **del proyecto**) las operaciones vigentes del proyecto y de
    cualquier versión (:data:`_CONSUMERS_ANYWHERE`). Solo lee."""
    skip = {uid for uid in exclude if uid is not None}
    found: dict[str, tuple[int, str, str]] = {}
    frontier = list(dict.fromkeys(datasets))
    seen = set(frontier)
    while frontier:
        fresh: list[str] = []
        for first in range(0, len(frontier), _CHUNK):
            part = frontier[first:first + _CHUNK]
            sql = (_CONSUMERS_ANYWHERE if version_uid is None else _CONSUMERS).format(
                marks=", ".join("?" for _ in part))
            for fid, uid, op_type, settings in conn.execute(sql, part if version_uid is None
                                                            else (*part, version_uid)):
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
    RF-015-16; del grafo de la 008, sin escribir; lo vigente de la versión aunque lo registrara una revisión
    ya congelada, cuyos elementos no cambian ni se marcan, RF-009-19): si
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
                found.append(_consumer(ObsoleteKind.CONSUMER, uid, op_type, name))
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
                found.append(_consumer(ObsoleteKind.DEPENDENT, uid, op_type, name))
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
    notas. Solo lee. Si retira un acopio «como plataforma» (spec 016, T21), antes de todo, el aviso de lo que se le apoyaba (RF-016-14:
    **una** nota con el total y los nombres de lo que lo puso, que no se retira sin la confirmación expresa)."""
    names, declared = _restrictions(project, version)
    held = held_notices(
        outcome.name, masks, outcome.footprint.window, cut=outcome.applied.cut_denied,
        fill=outcome.applied.fill_denied, edge=outcome.edge.held, names=names, declared=declared)
    obsolete = platform_obsolete(project, version, prepared, masks, insert_before=insert_before,
                                 supersedes=supersedes)
    resting: tuple[Notice, ...] = ()
    if prepared.origin is not None and prepared.resting:
        from . import removal

        resting = removal.resting_notices(prepared.origin.item.name, prepared.resting)
    notices = (*resting, *summary_notices(outcome.notices), *held,
               *obsolete_notices(outcome.name, version.code, obsolete))
    return PlatformSummary(outcome.name, outcome.code, version.code, outcome.figures, notices,
                           obsolete)


# --- La declaración de restricciones (spec 015, T17; RF-015-10, RF-015-12, RF-012-29) ------------------

_DECLARE_PHASE = "declare_constraints"
_DECLARES: Mapping[EntityKind, ConstraintType] = MappingProxyType({
    EntityKind.PLATFORM: ConstraintType.NO_FILL, EntityKind.BUTTRESS: ConstraintType.NO_CUT})
"""Lo que declara cada tipo de entidad cuando protege su zona (D-4; D-1 de la 016): la plataforma, «sin relleno» y, de la 016 (T27), el
contrafuerte, «sin corte» (sobre su zona de coronación: :func:`~.entities.declaration_runs`). Los demás tipos no declaran nada por defecto
(la retirada y el cuerpo escriben ``protect`` falso)."""
_NO_DECLARATION: Mapping[str, tuple[str, str]] = MappingProxyType({
    "stockpile": ("una detección de acopios", "a stockpile detection"), "removal": ("una retirada de acopio", "a stockpile removal"),
    "body": ("un cuerpo apoyado", "a supported body")})
"""Cómo se dice, en español y en inglés, cada tipo de entidad que **no declara** ninguna restricción (:data:`_DECLARES` no lo tiene): lo que nombra
``des.protect_unsupported`` (spec 016, T48)."""
_LIVE_STATES = frozenset({EntityState.CURRENT, EntityState.STALE, EntityState.SUPPORT_REMOVED})
"""Los estados de una entidad **viva y calculada** (RF-015-25): tiene operación vigente y datos que no están
descartados. Una «sin calcular» no tiene huella y una «descartada» ya no es de la versión: ninguna declara."""


def _has_footprint(entry: entities.EntityEntry) -> bool:
    """Si la entidad de ``entry`` es de un tipo que deja la tabla de su huella (:attr:`~.entities.EntityType.has_footprint`): solo esas
    declaran restricciones y salen en la capa de entidades. **La detección de acopios no** (spec 016, T21): lee ``des_epr_`` de
    toda entidad viva y una detección no la tiene (un acopio es una fila de su tabla ``des_stk_``)."""
    return entities.entity_type(entry.record.kind).has_footprint


def _can_declare(entry: entities.EntityEntry) -> bool:
    """Si la entidad de ``entry`` es de un tipo que **puede declarar** una restricción: deja la tabla de su huella (:func:`_has_footprint`) y tiene el parámetro ``protect``
    (spec 017, T22b; RF-017-01, D-15). **La pista no lo tiene**: no declara nada (su zona se corta y se rellena a la vez) y la declaración no la recoge —ni su ``protect`` ni la
    huella que leería—; sin esto, ``declaration_pending`` y ``declared_sources`` pedían la clave ``des.road.{e}.protect``, que no existe, y toda orden de entidades que declara
    fallaba en su primera etapa con una plataforma o un contrafuerte en la versión."""
    spec = entities.entity_type(entry.record.kind)
    return spec.has_footprint and PlatformParam.PROTECT.value in spec.params.names


_DECISION_PARAMS = (PlatformParam.NAME, PlatformParam.PROTECT, PlatformParam.GUARD, PlatformParam.REASON)
"""Los parámetros de los que sale lo que declara una entidad (su nombre, si protege, su resguardo y su
motivo): la decisión de la restricción es la más reciente de ellos (``decided_by`` y ``decided_at`` de su
historial)."""
_ENTITY_DATA = (
    "SELECT d.locator, d.name, d.status FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = ? AND io.role = ? "
    "ORDER BY io.fid")
_UNUSABLE_STATUSES = frozenset(str(status) for status in dataset_external.UNUSABLE_STATUSES)
"""Los estados de un dato que no se puede usar (``core.datasets.external.UNUSABLE_STATUSES``): lo editado fuera sin ser
editable a mano (``blocked``), lo que falta y lo dañado."""


@dataclass(frozen=True, slots=True)
class EntityFootprint:
    """Lo que la declaración lee de la tabla ``des_epr_`` de una entidad (:func:`read_entity_footprint`):
    su ``code``, el ``name`` con que se calculó (el de su dato ``des_epr_<nombre>``), su ``kind``, la
    ``layer`` de su geometría de origen y su huella en ``runs`` (tramos de fila ``(fila, col0, col1)`` de la
    rejilla entera, ``col1`` excluida: :func:`footprint_runs`) y, aparte (T28: lo dibuja la vista,
    ``bl.scene.entity_views``), los vértices de su eje en ``axis`` (``(x, y)`` absolutos, float64) y, **de un contrafuerte** (spec 016, T27;
    P-8, H-6), su zona de coronación en ``zone`` (tramos de fila, como ``runs``: lo que declara «sin corte»; ``None`` en los tipos sin zona
    propia: declaran su huella)."""

    code: str
    name: str
    kind: str
    layer: str
    runs: tuple[tuple[int, int, int], ...]
    axis: tuple[tuple[float, float], ...] = ()
    zone: tuple[tuple[int, int, int], ...] | None = None


def read_entity_footprint(conn: sqlite3.Connection, table: str) -> EntityFootprint:
    """La fila de la tabla ``des_epr_`` ``table`` (``conn`` la ve: la del proyecto o la congelada): su
    código, su nombre, su tipo, su capa, su huella en tramos y los vértices de su eje. ``ValueError`` si no
    tiene exactamente una fila o su huella no son tramos."""
    rows = conn.execute(f'SELECT code, name, kind, layer, footprint, axis FROM "{table}"').fetchall()
    if len(rows) != 1:
        raise ValueError(f"la tabla de una entidad «{table}» tiene una fila, no {len(rows)}")
    ((code, name, kind, layer, footprint, axis),) = rows
    runs = tuple((int(row), int(first), int(last)) for row, first, last in json.loads(footprint))
    vertices = tuple((float(x), float(y)) for x, y in json.loads(axis))
    zone: tuple[tuple[int, int, int], ...] | None = None
    if entities.entity_type(str(kind)).own_zone:  # un contrafuerte: además, su zona de coronación (spec 016, T27)
        found = conn.execute(f'SELECT zone FROM "{table}"').fetchone()
        zone = tuple((int(row), int(first), int(last)) for row, first, last in json.loads(found[0]))
    return EntityFootprint(str(code), str(name), str(kind), str(layer), runs, vertices, zone)


_TABLE_OF = (
    "SELECT d.locator FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = ? AND io.role = ? ORDER BY io.fid")


def operation_table(conn: sqlite3.Connection, operation_uid: str, role: str) -> str | None:
    """El localizador (la tabla del GeoPackage) del dato que escribió la operación ``operation_uid`` con el papel ``role`` (``stockpiles``,
    ``stockpile_candidates``, ``entity_report``…; spec 016, T33): la tabla **de su operación vigente**, no la de un dato anterior que una
    vista tenga cargado; ``None`` si no escribió ninguno. Solo lee."""
    found = conn.execute(_TABLE_OF, (operation_uid, DATASET, role)).fetchone()
    return None if found is None else str(found[0])


def read_entity_report(conn: sqlite3.Connection, operation_uid: str) -> tuple[tuple[str, float | None, str | None, str | None], ...]:
    """El informe (``des_prp_``: formato largo, ``quantity, value, unit_code, note``) que escribió la operación ``operation_uid`` de una
    entidad, en su orden (spec 016, T33; RF-015-25: lo que la barra N dice de la pared de una retirada, del pie cortado de un contrafuerte y
    de lo lejano de un cuerpo); ``()`` si la operación no escribió ninguno. Una cantidad puede repetirse (``wall_stretch``, ``warning``, ``note``).
    Solo lee."""
    table = operation_table(conn, operation_uid, provenance.ENTITY_REPORT_ROLE)
    if table is None:
        return ()
    rows = conn.execute(f'SELECT quantity, value, unit_code, note FROM "{table}" ORDER BY fid').fetchall()
    return tuple((str(quantity), None if value is None else float(value), None if unit is None else str(unit),
                  None if note is None else str(note)) for quantity, value, unit, note in rows)


def read_stockpile_footprints(conn: sqlite3.Connection, table: str
                              ) -> tuple[str, dict[str, tuple[tuple[int, int, int], ...]]]:
    """La huella de **cada acopio** de la tabla de acopios ``table`` de una detección (``des_stk_``; ``conn`` la ve: la del proyecto o la
    congelada; spec 016, T15; RF-016-14, P-1): el código de la detección (``code``, ``STK-001``: lo dice la tabla, como la
    ``des_epr_`` de una entidad) y, de cada acopio, su clave (la de su marca) → su huella en tramos de fila ``(fila, col0, col1)``
    absolutos, ``col1`` excluida (``footprint``, JSON), en el orden de la tabla. Es lo que se apoya sobre cada acopio
    (:func:`~.entities.detect_supports`). Una tabla sin filas da ``("", {})``. ``ValueError`` si una clave se repite, las filas
    son de más de una detección o una huella no son tramos. Solo lee."""
    found: dict[str, tuple[tuple[int, int, int], ...]] = {}
    codes: set[str] = set()
    for code, key, footprint in conn.execute(f'SELECT code, key, footprint FROM "{table}" ORDER BY fid').fetchall():
        if str(key) in found:
            raise ValueError(f"la tabla de acopios «{table}» tiene la clave «{key}» más de una vez")
        codes.add(str(code))
        found[str(key)] = tuple((int(row), int(first), int(last)) for row, first, last in json.loads(footprint))
    if len(codes) > 1:
        raise ValueError(f"la tabla de acopios «{table}» tiene las filas de {len(codes)} detecciones "
                         f"({', '.join(sorted(codes))}), no de una")
    return (next(iter(codes)) if codes else ""), found


def _usable_footprint(conn: sqlite3.Connection, entry: entities.EntityEntry, version: Version
                      ) -> EntityFootprint:
    """La huella de la entidad **viva y calculada** ``entry`` (:func:`read_entity_footprint` de su ``des_epr_`` vigente),
    de la que salen su zona declarada y su fila de la capa, **si se puede usar** (spec 015, T43; RF-015-11, RF-008-56,
    RF-008-57; hallazgo B-2): el equivalente, para la tabla de la entidad, de ``core.constraints.declared.require_usable``.
    La tabla es una **salida** de la entidad, no editable a mano: si la 008 la tiene **bloqueada** (se editó en QGIS) la
    declaración no la lee —se editó la huella de la que sale una restricción— y lo dice con la entidad
    (``des.entity_footprint_blocked``: aceptar la edición con un motivo o recalcular la entidad); si falta, está dañada
    o ya no es la tabla de una entidad (QGIS borró su fila, o ya no existe), ``des.entity_footprint_unusable``. Su
    ``name`` es el del **dato registrado** (el ``des_epr_<nombre>`` que escribió la operación) aunque el atributo de la
    tabla se haya cambiado a mano: de él sale el dato que consume la declaración. Solo lee."""
    record = entry.record
    rows = conn.execute(_ENTITY_DATA, (entry.operation_uid, DATASET, provenance.ENTITY_ROLE)).fetchall()
    if len(rows) != 1:
        raise ValueError(f"la operación {entry.operation_uid} de la entidad {record.code} escribió "
                         f"{len(rows)} tablas de la entidad, no una")
    ((table, dataset, status),) = rows
    where = {"obj": f"Entidad «{record.name}»", "field": "huella", "value": str(table), "entity": record.name,
             "table": str(table), "version": version.code}
    if str(status) == DatasetStatus.BLOCKED.value:
        raise DesignError("des.entity_footprint_blocked", **where)
    if str(status) in _UNUSABLE_STATUSES:
        raise DesignError("des.entity_footprint_unusable", **where)
    try:
        data = read_entity_footprint(conn, str(table))
    except (ValueError, TypeError, KeyError, sqlite3.Error) as error:  # la fila que falta o la huella que no son tramos
        raise DesignError("des.entity_footprint_unusable", **where) from error
    try:
        written = provenance.dataset_name(provenance.ENTITY_TABLE, data.name) == dataset
    except GeoblenderError:  # un nombre sin ninguna letra ni cifra
        written = False
    if not written:  # el atributo ``name`` cambiado a mano: el dato es el registrado
        prefix = provenance.dataset_name(provenance.ENTITY_TABLE, "x")[:-1]
        data = replace(data, name=str(dataset).removeprefix(prefix))
    return data


@dataclass(frozen=True, slots=True)
class DeclaredSource:
    """Lo que la declaración sabe de una entidad viva y calculada de la versión (RF-015-10): su ``code`` y su
    ``kind``, el ``name`` de ahora (``calc_name`` es el con que se calculó: el de su dato ``des_epr_``), la
    ``layer`` de su geometría de origen, si protege (``protect``), su ``mode`` (``cut`` o ``cut_fill``), su
    resguardo (``guard_m``, sin valor por defecto: D-19), el motivo que editó la persona (``reason``; ``None``:
    el generado), quién la creó o cambió y cuándo se decidió (``decided_by`` y ``decided_on``: la decisión más
    reciente de :data:`_DECISION_PARAMS`, no la fecha de ahora), su huella en tramos (``runs``) y, de un tipo con **zona propia** (el
    contrafuerte, spec 016, T27; P-8, H-6), esa zona en ``zone`` (lo que declara: :func:`~.entities.declaration_runs`)."""

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
    zone: tuple[tuple[int, int, int], ...] | None = None


def _check_declares(source: DeclaredSource) -> None:
    """Lo que una entidad que protege ha de cumplir para declarar (RF-015-10, RF-015-12): su resguardo, sin
    valor por defecto y obligatorio (D-19: ``des.entity_param_missing`` o ``des.entity_param_range``, con la
    entidad, el campo y el valor), y no proteger en el modo «en corte y relleno», en el que rellena su propia
    huella y su restricción «sin relleno» prohibiría su propio movimiento (D-21: ``des.platform_protect_cut_fill``;
    defensa en profundidad: la preparación ya lo rechaza al crearla, y el cambio de sus parámetros, desde la T39).
    No escribe nada."""
    _check_protection(source.name, source.code, source.layer, source.protect, source.mode, source.guard_m)


def _check_protection(name: str, code: str, layer: str, protect: bool, mode: str, guard_m: float | None) -> None:
    """Lo de :func:`_check_declares` de la entidad ``code`` de nombre ``name`` y capa ``layer`` con lo que protege
    (``protect``), su modo y su resguardo, sin la fuente de la declaración: lo comparten declarar y el cambio de
    los parámetros ``protect``, ``mode`` y ``guard_m`` (:func:`check_parameter_change`, T39; RF-015-12)."""
    if not protect:
        return
    check_entity_param(name, code, PlatformParam.GUARD, guard_m, layer=layer, required=True)
    if mode == PlatformMode.CUT_FILL.value:
        raise DesignError("des.platform_protect_cut_fill", obj=f"Plataforma «{name}»",
                          field=entity_key(code, PlatformParam.MODE), value=mode, layer=layer, entity=name)


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
        zone = entities.declared_zone_of_runs(entities.declaration_runs(source.kind, source.runs, source.zone), grid, source.guard_m)
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
    descartar (:data:`_LIVE_STATES`: no declaran ni una «sin calcular» ni una descartada) y de un tipo que **puede declarar**
    (:func:`_can_declare`: **no la pista**, que no tiene ``protect``; spec 017, T22b), cada una con sus
    parámetros vigentes en la versión (si protege, su modo, su resguardo y el motivo que editó la persona,
    :func:`~.entity_store.platform_parameters`), su decisor y la fecha de su decisión (:func:`_decision`) y su
    huella, leída de su tabla ``des_epr_`` vigente (:func:`read_entity_footprint`). Por orden de código.
    ``conn`` es una conexión de lectura de quien llama; sin ella, una propia."""
    if conn is None:
        with _consistent(project) as reading:
            return declared_sources(project, version, conn=reading)
    registry = entities.registry(project, version.uid, conn=conn)
    live = [entry for entry in registry
            if entry.operation_uid is not None and entry.record.state in _LIVE_STATES and _can_declare(entry)]
    keys = {entity_key(entry.record.code, param): (entry.record.code, param)
            for entry in live for param in (PlatformParam.PROTECT, PlatformParam.MODE,
                                            PlatformParam.GUARD, PlatformParam.REASON)
            if param.value in entities.entity_type(entry.record.kind).params.names}  # el modo es de la plataforma (spec 016, T21)
    found = ParameterStore(project).resolve_many(
        conn, tuple(keys), (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid)
    values: dict[tuple[str, PlatformParam], Any] = {
        (entry.record.code, param): _default(param) for entry in live
        for param in (PlatformParam.PROTECT, PlatformParam.MODE, PlatformParam.GUARD, PlatformParam.REASON)}
    for key, (code, param) in keys.items():
        resolved = found.get(key)
        if resolved is not None:
            values[code, param] = resolved.value
    store = ParameterStore(project)
    sources: list[DeclaredSource] = []
    for entry in live:
        record = entry.record
        code = record.code
        data = _usable_footprint(conn, entry, version)
        protect = bool(values[code, PlatformParam.PROTECT])
        guard, reason = values[code, PlatformParam.GUARD], values[code, PlatformParam.REASON]
        who, when = _decision(store, conn, version, code) if protect else (None, None)
        sources.append(DeclaredSource(
            code=code, kind=EntityKind(record.kind), name=record.name, calc_name=data.name,
            layer=data.layer, protect=protect, mode=str(values[code, PlatformParam.MODE]),
            guard_m=None if guard is None else float(guard),
            reason=(reason.strip() or None) if isinstance(reason, str) else None, decided_by=who,
            decided_on=when, runs=data.runs, zone=data.zone))
    return tuple(sources)


@dataclass(frozen=True, slots=True, eq=False)
class PreparedDeclaration:
    """Lo que se lee y se comprueba antes de declarar (:func:`prepare_declaration`): la ``version``, las
    entidades vivas que recoge (``sources``, todas: de las que no protegen solo se lee que protegen o no, su
    parámetro ``protect``; su dato ``des_epr_`` no es entrada de la operación), la rejilla del proyecto
    (``grid``) y lo que anotará la operación (``start``)."""

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
    anotará la operación: **solo de las entidades vivas calculadas que protegen** (plan 015 §5.2.3; corregido
    en la T26: antes eran las de todas, y una que no protegía, retirada o descartada, dejaba obsoleta en
    cascada la declaración, las máscaras y lo que las usó), su dato ``des_epr_`` como entrada (papel
    ``entity``) y sus ajustes (las entidades, la versión y su decisor y la fecha de su decisión); y los
    parámetros que lee, de **todas** las vivas (``protect`` y ``name``; ``mode`` y ``guard_m`` de las que
    protegen; ``reason`` de las que editaron su motivo: :func:`~.provenance.declare_params`), de modo que
    cambiar el ``protect`` de una la deja obsoleta. No pide máscaras al día
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
    # Solo las que protegen aportan su dato (plan 015 §5.2.3): una que no protege, retirada o descartada, no
    # deja obsoleta la declaración, ni en cascada las máscaras y lo que las usó. Lo que cambia si una pasa a
    # proteger o deja de hacerlo es su parámetro ``protect``, que sí lee la operación de todas las vivas.
    protecting_sources = [source for source in sources if source.protect]
    protecting = [source.code for source in protecting_sources]
    settings = provenance.declare_settings(
        [(source.code, source.calc_name) for source in protecting_sources], version_uid=found.uid,
        decisions={source.code: (source.decided_by, source.decided_on) for source in protecting_sources
                   if source.decided_by is not None and source.decided_on is not None})
    inputs = provenance.declare_inputs(source.calc_name for source in protecting_sources)
    params = provenance.declare_params(
        [source.code for source in sources], protecting=protecting,
        reasoned=[source.code for source in protecting_sources if source.reason is not None])
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
            if PlatformParam.MODE.value in entities.entity_type(source.kind).params.names:  # el modo es de la plataforma (spec 016, T27)
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


def declaration_pending(project: StoreProject, conn: sqlite3.Connection, version_uid: str) -> bool:
    """Si una entidad **viva y calculada** de la versión ``version_uid`` (su uid) que **protege** no tiene su
    restricción (``dec__<entidad>``) en la declaración vigente —la versión no tiene tabla viva, o a la suya le falta
    su fila— (spec 015, T38; RF-015-10, RF-015-29, CE-015-04; hallazgo E-1): lo que deja «Crear» si Esc o un fallo
    cortan lo que sigue antes de que se escriba la primera declaración. Es lo que ``gis.masks.access`` pregunta
    (por el gancho :data:`DECLARATION_HOOK`, que registra ``bl``) cada vez que mira el estado de las máscaras, también
    al dibujar la interfaz: **barata** y de solo lectura (con la instantánea de ``conn``). Sin ninguna operación
    ``des.platform`` ni ``des.buttress`` vigente en la versión (los tipos que declaran, spec 016, T35: antes solo la plataforma, y en una
    versión con **solo** un contrafuerte que protege un Esc entre crearlo y declararlo dejaba las máscaras al día sin su restricción),
    una sola consulta (:func:`~.provenance.has_declaring_operation`); con
    ellas, el registro de las entidades (``entities.registry``), el parámetro ``protect`` de las vivas y los
    códigos de la tabla de declaradas, **sin leer su geometría ni la huella de nadie**. Compara con **lo que falta**,
    no con lo que difiere: que una fila declare un resguardo anterior lo dice el hash de la tabla (el grafo de la
    008, :func:`declaration_diverges`). Una entidad ``UNCALCULATED`` o ``DISCARDED`` no declara (:data:`_LIVE_STATES`,
    como :func:`declared_sources`), ni la pista (:func:`_can_declare`, spec 017, T22b). Si no se puede saber (un registro roto: ``des.entity_name_missing``, una tabla
    ilegible), **está pendiente**: lo seguro es no dar las máscaras por buenas, y la operación que lo intente
    declarar dirá el motivo."""
    if not provenance.has_declaring_operation(conn, version_uid):
        return False
    try:
        registry = entities.registry(project, version_uid, conn=conn)
        live = [entry.record.code for entry in registry
                if entry.operation_uid is not None and entry.record.state in _LIVE_STATES and _can_declare(entry)]
        if not live:
            return False
        keys = {entity_key(code, PlatformParam.PROTECT): code for code in live}
        found = ParameterStore(project).resolve_many(
            conn, tuple(keys), (VERSION_SCOPE, PROJECT_SCOPE), version=version_uid)
        wanted = {declared_code(code) for key, code in keys.items()
                  if bool(found[key].value if found.get(key) is not None else _default(PlatformParam.PROTECT))}
        return bool(wanted) and not wanted <= set(names_in_version(conn, version_uid))
    except (DesignError, ValueError, sqlite3.Error):
        return True


def _declare_for_masks(project: StoreProject, version_uid: str, budget_s: float
                       ) -> Generator[Progress, None, None]:
    """Los pasos de declarar las restricciones de las entidades de la versión ``version_uid`` que da el gancho a
    ``gis.masks.access`` (:func:`declare_constraints_steps`; el último paso lleva el ``Stored``)."""
    return declare_constraints_steps(project, version_uid, budget_s=budget_s)


DECLARATION_HOOK = declaring.DeclarationHook(pending=declaration_pending, declare=_declare_for_masks)
"""El gancho de la declaración (``gis.masks.declaring``; spec 015, T38; hallazgo E-1): **lo que registra ``bl`` al
habilitar Geoblender** (con funciones que importan este módulo al usarlas, no al habilitar) y lo que registran las
pruebas de ``design``. Con él, las máscaras de una versión no están al día mientras una entidad viva que protege no
tenga su restricción en la declaración vigente, y quien las pide declara antes de compilar."""


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


# --- La capa de entidades (spec 015, T30; RF-015-27; D-13; plan 015 §5.2.3, §5.3.2 y P-7; ADR-0030 §5) -------

_LAYER_PHASE = "entity_layer"
_LAYER_LANGUAGE = "es"
"""El idioma del texto de la capa (en qué se apoya la entidad): es un dato del proyecto, como el motivo de una
restricción declarada, y no cambia con el idioma de la interfaz."""
_LAYER_FIGURES: tuple[tuple[str, str], ...] = (
    ("area_m2", "des.plat_area_m2"), ("cut_m3", "des.plat_cut_m3"), ("fill_m3", "des.plat_fill_m3"),
    ("edge_cut_m3", "des.edge_cut_m3"), ("edge_fill_m3", "des.edge_fill_m3"))
"""Las cifras principales de la capa: la columna de ``des_enl_<vNN>`` y la cifra de la operación de la entidad de
la que sale (``gb_figure``)."""
LAYER_FIGURES: Mapping[str, tuple[tuple[str, str], ...]] = MappingProxyType({
    EntityKind.PLATFORM.value: _LAYER_FIGURES,
    EntityKind.STOCKPILE.value: (("area_m2", "des.stk_area_m2"), ("volume_m3", "des.stk_volume_m3"),
                                 ("thickness_max_m", "des.stk_thickness_max_m")),
    EntityKind.REMOVAL.value: (("volume_m3", "des.rmv_removed_m3"), ("thickness_max_m", "des.rmv_wall_max_m")),
    EntityKind.BUTTRESS.value: (("area_m2", "des.btr_area_m2"), ("volume_m3", "des.btr_volume_m3"),
                                ("thickness_max_m", "des.btr_height_max_m"), ("cutoff_m3", "des.btr_cutoff_m3")),
    EntityKind.BODY.value: (("volume_m3", "des.bdy_volume_m3"), ("thickness_max_m", "des.bdy_thickness_max_m")),
    EntityKind.ROAD.value: (("area_m2", "des.road_area_m2"), ("cut_m3", "des.road_cut_m3"), ("fill_m3", "des.road_fill_m3"),
                            ("edge_cut_m3", "des.road_edge_cut_m3"), ("edge_fill_m3", "des.road_edge_fill_m3")),
})
"""Las cifras principales de la capa **por tipo de entidad** (spec 016, T34): para cada tipo, la columna de
``des_enl_<vNN>`` y la cifra que la llena. La plataforma, las cinco de la 015; el acopio, su área, su volumen sobre su
base y su espesor máximo (las de su fila de ``des_stk_``, que usan las claves de ``des.stk_*``); la retirada, lo retirado
y la mayor pared; el contrafuerte, su área, su volumen, su mayor altura y el pie que el borde cortó; el cuerpo, su volumen
y su espesor máximo; la pista (017, T03), su área grabada y su corte y relleno de la sección y del borde, como la plataforma. Las
demás columnas del tipo quedan sin valor. Un tipo registrado que no está aquí (el de una prueba) y la accesibilidad (que no tiene
huella y no sale en la capa) no llevan cifras."""
_FIGURES_OF = ("SELECT operation_uid, key, value FROM gb_figure WHERE key IN ({keys}) "
               "AND operation_uid IN ({marks})")
_CHAIN_ARROW = " → "
_DISCARDED_TEXT = "descartada"


@dataclass(frozen=True, slots=True)
class LayerSource:
    """Lo que la capa de entidades sabe de una entidad **calculada** de la versión (:func:`layer_sources`): su
    ``code``, su ``name`` de ahora (``calc_name`` es el con que se calculó: el de su dato ``des_epr_``), su ``kind``,
    su ``state`` (el que deduce el grafo: al día, obsoleta, con el apoyo retirado o descartada), de qué superficie
    parte (``start``: el nombre de la entidad si parte de la de otra, o la superficie tal cual), su huella en tramos
    (``runs``), en qué se apoya (``supports``, un texto), su cadena (``chain``) y sus cifras principales
    (``figures``: la clave de la cifra de la operación → su valor)."""

    code: str
    name: str
    calc_name: str
    kind: EntityKind
    state: EntityState
    start: str | None
    runs: tuple[tuple[int, int, int], ...]
    supports: str
    chain: str
    figures: Mapping[str, float]

    @property
    def live(self) -> bool:
        """Si sus datos están vivos: una entidad **descartada** sale en la capa (es un registro, atenuada) pero
        sus datos ya no son entrada de ninguna operación."""
        return self.state is not EntityState.DISCARDED


def _start_text(listed: EntityRegistry, record: EntityRecord) -> str | None:
    """De qué parte la entidad ``record``, para la capa: el nombre de la entidad de cuya superficie parte (con el
    código si no se encuentra) o la superficie tal cual; ``None`` si no tiene partida."""
    if record.start is None:
        return None
    code = entities.ref_code(record.start)
    if code is None:
        return record.start
    before = listed.get(code)
    return code if before is None else before.record.name


def _chain_text(listed: EntityRegistry, record: EntityRecord) -> str:
    """La cadena de la entidad ``record`` como texto, «partida → … → última» (RF-015-04, RF-015-27): de la superficie
    de la que parte la primera de su cadena (el terreno, una de diseño o la de una entidad **descartada**, con
    «(descartada)») y, una tras otra, las entidades que parten de la superficie de la anterior, hasta la última. Es la
    misma para todas las de una cadena. Si los datos de la cadena no son válidos (un ciclo, dos entidades desde la
    misma superficie), lo dice en lugar de la cadena: no impide ponerla al día (la capa enseña lo que hay)."""
    records = listed.records
    try:
        head, seen = record, {record.code}
        while True:
            before = entities.predecessor_of(records, head.code)
            if before is None or before.code in seen or before.state is EntityState.DISCARDED:
                break
            head = before
            seen.add(head.code)
        names = [item.name for item in entities.chain_of(records, head.code)]
        discarded = entities.predecessor_of(records, head.code)
    except DesignError as error:
        return f"cadena no válida: {error}"
    if discarded is not None and discarded.code not in seen:
        origin: str | None = f"{discarded.name} ({_DISCARDED_TEXT})"
    else:
        origin = _start_text(listed, head)
    return _CHAIN_ARROW.join([origin, *names] if origin else names)


def _layer_figures(conn: sqlite3.Connection, operations: Iterable[str]) -> dict[str, dict[str, float]]:
    """Las cifras principales (:data:`LAYER_FIGURES`, las de todos los tipos) de cada operación de ``operations``, por su uid (una consulta
    por cada 400 operaciones); las que no tiene, no salen."""
    keys = sorted({key for pairs in LAYER_FIGURES.values() for _column, key in pairs})
    found: dict[str, dict[str, float]] = {}
    uids = sorted(set(operations))
    for first in range(0, len(uids), _CHUNK):
        part = uids[first:first + _CHUNK]
        sql = _FIGURES_OF.format(keys=", ".join("?" for _ in keys), marks=", ".join("?" for _ in part))
        for uid, key, value in conn.execute(sql, (*keys, *part)):
            if value is not None:
                found.setdefault(str(uid), {})[str(key)] = float(value)
    return found


_ON_STOCKPILE = "sobre el acopio «{stockpile}»"
"""Lo que dice la capa de la entidad que se apoya **en un acopio** de una detección (spec 016, T34; RF-016-14): en cuál de ellos."""


def _support_text(item: entities.Dependent) -> str:
    """Una fila de «en qué se apoya» de la capa: la de la entidad (:meth:`~.entities.Dependent.text`: el nombre, el tipo y los m³) y,
    si se apoya en **un acopio** de una detección, en cuál (``· sobre el acopio «Acopio 4»``)."""
    text = item.text(_LAYER_LANGUAGE)
    return f"{text} · {_ON_STOCKPILE.format(stockpile=item.stockpile)}" if item.stockpile else text


def _layer_entries(listed: EntityRegistry) -> list[entities.EntityEntry]:
    """Las entidades **calculadas** del registro que salen en la capa (:data:`~.entity_layer.LAYER_STATES`): las de un tipo
    con tabla de huella y, de la 016 (T34), las **detecciones de acopios**, de las que sale una fila por acopio."""
    return [entry for entry in listed
            if entry.operation_uid is not None and EntityState(entry.record.state) in LAYER_STATES
            and (_has_footprint(entry) or entry.record.kind == EntityKind.STOCKPILE)]


_STOCKPILE_ROWS = 'SELECT key, name, area_m2, volume_m3, thickness_max_m, footprint FROM "{table}" ORDER BY fid'


def _stockpile_table(conn: sqlite3.Connection, entry: entities.EntityEntry, version: Version) -> tuple[str, str]:
    """La tabla de acopios (``des_stk_``) de la detección ``entry`` y el nombre con que se calculó (el de su dato, sin el
    prefijo), si se puede usar (como :func:`_usable_footprint`: lo editado fuera, lo que falta o lo dañado se rechazan con
    ``des.entity_footprint_blocked`` o ``_unusable``). Solo lee."""
    record = entry.record
    rows = conn.execute(_ENTITY_DATA, (entry.operation_uid, DATASET, provenance.STOCKPILES_ROLE)).fetchall()
    if len(rows) != 1:
        raise ValueError(f"la operación {entry.operation_uid} de la detección {record.code} escribió "
                         f"{len(rows)} tablas de acopios, no una")
    ((table, dataset, status),) = rows
    where = {"obj": f"Detección de acopios «{record.name}»", "field": "huella", "value": str(table),
             "entity": record.name, "table": str(table), "version": version.code}
    if str(status) == DatasetStatus.BLOCKED.value:
        raise DesignError("des.entity_footprint_blocked", **where)
    if str(status) in _UNUSABLE_STATUSES:
        raise DesignError("des.entity_footprint_unusable", **where)
    prefix = provenance.dataset_name(provenance.STOCKPILES_TABLE, "x")[:-1]
    return str(table), str(dataset).removeprefix(prefix)


def _stockpile_sources(conn: sqlite3.Connection, entry: entities.EntityEntry, version: Version) -> list[LayerSource]:
    """Las filas de la capa de la detección de acopios ``entry`` (spec 016, T34; RF-016-09, RF-015-27; plan 016 §5.1 «la
    capa con una fila por acopio»): **una por acopio** de su tabla ``des_stk_``, con su referencia (``STK-001#m07``: el código
    de la detección y la clave de la marca) como código, el nombre del acopio, **el estado de la detección** (es una operación),
    sin partida, sin cadena (un tipo sin cadena) ni apoyo (un acopio no se apoya en nada: lo apoyado **en él** es de lo
    demás), su huella y sus cifras (área, volumen sobre su base y espesor máximo: las de su fila, con las claves de
    ``des.stk_*``). Solo lee."""
    record = entry.record
    table, calc_name = _stockpile_table(conn, entry, version)
    found: list[LayerSource] = []
    try:
        stored = conn.execute(_STOCKPILE_ROWS.format(table=table)).fetchall()
        for key, name, area, volume, thickness, footprint in stored:
            runs = tuple((int(row), int(first), int(last)) for row, first, last in json.loads(footprint))
            figures = {"des.stk_area_m2": area, "des.stk_volume_m3": volume, "des.stk_thickness_max_m": thickness}
            found.append(LayerSource(
                code=provenance.support_ref(record.code, str(key)), name=str(name), calc_name=calc_name,
                kind=EntityKind.STOCKPILE, state=EntityState(record.state), start=None, runs=runs, supports="", chain="",
                figures={figure: float(value) for figure, value in figures.items() if value is not None}))
    except (ValueError, TypeError, KeyError, sqlite3.Error) as error:  # una tabla que ya no es la de acopios
        raise DesignError("des.entity_footprint_unusable", obj=f"Detección de acopios «{record.name}»", field="huella",
                          value=table, entity=record.name, table=table, version=version.code) from error
    return found


def layer_sources(project: StoreProject, version: Version, *, conn: sqlite3.Connection | None = None
                  ) -> tuple[LayerSource, ...]:
    """Las entidades **calculadas** de la versión ``version`` como las ve la capa de entidades (RF-015-27; solo lee):
    las del registro de la versión (``entities.registry``) con operación vigente y huella (:data:`~.entity_layer.
    LAYER_STATES`: al día, obsoletas, con el apoyo retirado y **descartadas**, que siguen en el proyecto; no las «sin
    calcular», que no tienen geometría), cada una con su estado, de qué parte, **en qué se apoya** (lo que
    ``entities.dependencies_of`` dice que apoya con el papel ``supported_on``, con sus m³), su cadena
    (:func:`_chain_text`), sus cifras principales y su huella, leída de su tabla ``des_epr_`` vigente
    (:func:`read_entity_footprint`; la de una descartada, de su dato descartado, que sigue en el proyecto). De la 016
    (T34), de cada **detección de acopios** una fila **por acopio** (:func:`_stockpile_sources`). Por orden de código.
    ``conn`` es una conexión de lectura de quien llama (una instantánea); sin ella, una propia."""
    if conn is None:
        with _consistent(project) as reading:
            return layer_sources(project, version, conn=reading)
    listed = entities.registry(project, version.uid, conn=conn)
    shown = _layer_entries(listed)
    figures = _layer_figures(conn, (str(entry.operation_uid) for entry in shown))
    found: list[LayerSource] = []
    for entry in shown:
        record = entry.record
        if record.kind == EntityKind.STOCKPILE:
            found += _stockpile_sources(conn, entry, version)
            continue
        data = _usable_footprint(conn, entry, version)
        rests = entities.dependencies_of(project, version.uid, record.code, conn=conn, listed=listed)
        found.append(LayerSource(
            code=record.code, name=record.name, calc_name=data.name, kind=EntityKind(record.kind),
            state=EntityState(record.state), start=_start_text(listed, record), runs=data.runs,
            supports="; ".join(_support_text(item) for item in rests if provenance.SUPPORTED_ON_ROLE in item.roles),
            chain=_chain_text(listed, record), figures=figures.get(str(entry.operation_uid), {})))
    return tuple(found)


def _row_order(code: str) -> tuple[tuple[str, int], int, str]:
    """La clave de orden de una fila de la capa: la de su entidad (``entities.code_order``) y, de un acopio, su clave."""
    entity, key = provenance.split_support_ref(code)
    return entities.code_order(entity), 0 if key is None else 1, key or ""


def entity_layer_rows_steps(sources: Sequence[LayerSource], grid: Grid
                            ) -> Generator[Progress, None, tuple[EntityLayerRow, ...]]:
    """**El cálculo de la capa de entidades**, compartido por la orden, el recálculo y lo que sigue a cada orden de
    entidades (sin proyecto dentro: recibe lo leído): de cada entidad de ``sources`` una
    :class:`~.entity_layer.EntityLayerRow` con el contorno de su huella en la rejilla ``grid``
    (``entities.declared_zone_of_runs`` con resguardo 0: las celdas, con sus huecos, con coordenadas exactas desde
    ``grid.west`` y ``grid.north``) y lo demás de su fuente, **por código** y una por paso. Lo mismo da la misma
    tabla (el mismo hash)."""
    ordered = sorted(sources, key=lambda item: _row_order(item.code))
    rows: list[EntityLayerRow] = []
    for index, source in enumerate(ordered):
        yield Progress(_LAYER_PHASE, index, len(ordered), f"Capa de entidades: «{source.name}»…")
        zone = entities.declared_zone_of_runs(source.runs, grid, 0.0)
        rows.append(EntityLayerRow(
            code=source.code, name=source.name, kind=source.kind, state=source.state, start=source.start,
            supports=source.supports, chain=source.chain, parts=zone.parts,
            **{column: source.figures.get(key) for column, key in LAYER_FIGURES.get(source.kind.value, ())}))
    return tuple(rows)


@dataclass(frozen=True, slots=True, eq=False)
class PreparedEntityLayer:
    """Lo que se lee antes de poner al día la capa de entidades (:func:`prepare_entity_layer`): la ``version``, las
    entidades calculadas (``sources``), la rejilla del proyecto (``grid``) y lo que anotará la operación (``start``)."""

    version: Version
    sources: tuple[LayerSource, ...]
    grid: Grid
    start: OperationStart


def _live_layer(conn: sqlite3.Connection, version: Version) -> str | None:
    """El uid de la operación que escribió la capa vigente de la versión (``des_enl``), la que sustituye la nueva;
    ``None`` si todavía no se escribió. Si la capa se editó fuera de Geoblender, la última operación de Geoblender
    que la escribió (``core.datasets.external.last_writer``)."""
    record = dataset_registry.get(conn, provenance.dataset_name(provenance.ENTITY_MAP_TABLE),
                                  version_uid=version.uid)
    if record is None or not record.live:
        return None
    return dataset_external.last_writer(conn, record.uid)


def prepare_entity_layer(project: StoreProject, version: Version | str | None, *,
                         supersedes: str | None = None) -> PreparedEntityLayer:
    """Prepara ``des.entity_layer`` en la versión editable ``version`` (spec 015, T30; RF-015-27): lee las entidades
    calculadas (:func:`layer_sources`) y arma lo que anotará la operación: sus ajustes (las entidades que recoge) y, como
    entradas, el dato ``des_epr_`` (papel ``entity``: la huella) y el informe ``des_prp_`` (papel ``entity_report``: las
    cifras) de las **vivas**; la descartada sale en la capa pero no es entrada (sus datos están descartados). No lee
    parámetros: lo que cambia una entidad (sus parámetros, su partida, lo que se apoya, su estado) cambia sus datos o
    la deja obsoleta, y la capa, que los consume, también (la cascada de la 008). ``supersedes``: la capa que
    sustituye (por defecto, la vigente de la versión, si la hay).

    Rechazos, sin escribir nada: los de :func:`~.store.require_version` (RF-009-21: sin versión activa,
    desconocida o no editable)."""
    wanted = version.uid if isinstance(version, Version) else version
    found = require_version(project, wanted, provenance.ENTITY_LAYER)
    with _consistent(project) as conn:
        sources = layer_sources(project, found, conn=conn)
        before = _live_layer(conn, found) if supersedes is None else supersedes
    named = list(dict.fromkeys((provenance.split_support_ref(source.code)[0], source.calc_name) for source in sources))
    settings = provenance.entity_layer_settings(named)
    inputs = provenance.entity_layer_inputs(
        (source.calc_name for source in sources if source.live and source.kind != EntityKind.STOCKPILE),
        list(dict.fromkeys(source.calc_name for source in sources if source.live and source.kind == EntityKind.STOCKPILE)))
    begun = _start(project, provenance.ENTITY_LAYER, "", found, None, settings, inputs, (), before)
    return PreparedEntityLayer(found, sources, project_frame(project).grid, begun)


def _layer_message(count: int, version_code: str) -> str:
    """El mensaje de la operación: cuántas entidades enseña la capa de la versión."""
    if count == 0:
        return f"La capa de entidades de {version_code} no tiene ninguna entidad calculada"
    if count == 1:
        return f"La capa de entidades de {version_code} enseña 1 entidad"
    return f"La capa de entidades de {version_code} enseña {count} entidades"


def _layer_run(project: StoreProject, handle: OperationHandle, prepared: PreparedEntityLayer, budget_s: float
               ) -> Generator[Progress, None, None]:
    with DesignWriter(project, provenance.ENTITY_LAYER, "", version=handle.version_uid, handle=handle) as writer:
        rows = yield from entity_layer_rows_steps(prepared.sources, prepared.grid)
        yield from pipeline.forward(_store_steps(
            writer.entity_layer_steps(rows), budget_s, "la capa de entidades"))
        message = _layer_message(len(rows), prepared.version.code)
        stored = writer.commit(message=message)
        yield Progress(_STORE_PHASE, 1, 1, message, result=stored)


def run_entity_layer(project: StoreProject, *, version: Version | str | None, supersedes: str | None = None,
                     budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Pone al día la capa de entidades de la versión ``version`` **de una vez**, sin pedir confirmación (spec 015, T30;
    RF-015-27; plan 015 §5.3.2: una operación aparte que cada orden de entidades hace en su propia transacción): empieza
    la operación ``des.entity_layer`` —si ``supersedes`` es la de una capa anterior (por defecto, la vigente de la
    versión), la sustituye— con lo que lee hoy y devuelve su ``OperationHandle`` «en curso» y sus pasos, que avanza
    quien la llama: calculan las filas (:func:`entity_layer_rows_steps`), reescriben la tabla entera ``des_enl_<vNN>`` con
    su fila de estilo y completan la operación en **una** transacción; el último lleva el :class:`~.store.Stored`.
    Cerrarlos antes, o un fallo, no dejan nada y la operación queda cancelada o fallida. Al llamar, sin empezar nada:
    los rechazos de :func:`prepare_entity_layer`."""
    prepared = prepare_entity_layer(project, version, supersedes=supersedes)
    handle = prepared.start.begin(project)
    return handle, _layer_run(project, handle, prepared, budget_s)


def entity_layer_steps(project: StoreProject, version: Version | str | None, *, supersedes: str | None = None,
                       budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, None]:
    """Los pasos de **poner al día la capa de entidades** de la versión ``version`` (spec 015, T30; RF-015-27; plan 015
    §5.3.2: es lo que las órdenes de entidades encadenan tras su commit, :func:`after_entity_change`): lo de
    :func:`run_entity_layer` empezando al avanzar, sin devolver el ``OperationHandle``; el último paso lleva el
    :class:`~.store.Stored`. Repetirla con las mismas entidades da la misma tabla y el mismo hash y sustituye a la vigente."""
    _handle, work = run_entity_layer(project, version=version, supersedes=supersedes, budget_s=budget_s)
    yield from work


def recompute_entity_layer(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S
                           ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.entity_layer`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto»,
    RF-008-26; spec 015, T30; RF-015-27): la capa es de la **versión**, no de una entidad, así que se rehace entera con las
    entidades calculadas de la versión y sus estados de hoy, sustituyendo a la que se repite (lo descartado sale de sus
    entradas: ``OperationDef.drops_discarded``). Devuelve lo de :func:`run_entity_layer`. ``VersionError`` si la petición
    no es de una versión editable."""
    project: StoreProject = request.project  # type: ignore[assignment]
    return run_entity_layer(project, version=request.version, supersedes=request.operation_uid, budget_s=budget_s)


def layer_pending(project: StoreProject, conn: sqlite3.Connection, version_uid: str) -> bool:
    """Si la capa de entidades de la versión ``version_uid`` (su uid) **no dice lo que dice el registro** de sus
    entidades (spec 015, T43; RF-015-27, RF-015-29; hallazgo E-4 / C-11): alguna entidad calculada no tiene su fila
    (la tabla ni existe, si es la primera de la versión), o la fila de alguna tiene otro nombre u otro **estado**
    (al día, obsoleta, con el apoyo retirado o descartada), o queda una fila de lo que ya no sale en la capa. Es **la
    marca** de una capa atrasada: la capa escribe el estado que deduce el grafo en el momento de escribirla, y el
    grafo cambia después por vías que no la regeneran (cambiar un parámetro, recalcular una entidad con la misma
    salida —la 008 no toca lo que depende de lo que no cambió—, dar por bueno un apoyo, o cerrar con Esc o un fallo lo
    que sigue a crear una entidad antes de la capa). Quien la pone al día es :func:`layer_sync_steps`.
    Barata y de solo lectura (con la instantánea de ``conn``): sin ninguna operación ``des.platform`` vigente en la
    versión, una consulta; con ellas, el registro de las entidades y la columna de código, nombre y estado de la
    tabla, **sin leer su geometría**. Una capa que no se puede usar (editada fuera de Geoblender y bloqueada, o
    dañada) no se marca: no es de la capa decidirlo, y la 008 ofrece resolverla. Si no se puede saber (un registro
    roto, una tabla ilegible), **está marcada**: lo seguro es no darla por buena, y quien intente ponerla al día dirá
    el motivo."""
    if not provenance.has_entity_operation(conn, version_uid):
        return False
    try:
        listed = entities.registry(project, version_uid, conn=conn)
        wanted: dict[str, tuple[str, str]] = {}
        for entry in _layer_entries(listed):
            state = str(EntityState(entry.record.state))
            if entry.record.kind != EntityKind.STOCKPILE:
                wanted[entry.record.code] = (entry.record.name, state)
                continue
            table = conn.execute(_ENTITY_DATA, (entry.operation_uid, DATASET, provenance.STOCKPILES_ROLE)).fetchone()
            if table is None:
                raise ValueError(f"la detección {entry.record.code} no tiene su tabla de acopios")
            for key, name in conn.execute(f'SELECT key, name FROM "{table[0]}" ORDER BY fid').fetchall():
                wanted[provenance.support_ref(entry.record.code, str(key))] = (str(name), state)
        record = dataset_registry.get(conn, provenance.dataset_name(provenance.ENTITY_MAP_TABLE),
                                      version_uid=version_uid)
        if record is None or not record.live:
            return bool(wanted)
        if str(record.status) in _UNUSABLE_STATUSES:
            return False
        shown = {str(code): (str(name), str(state)) for code, name, state in conn.execute(
            f'SELECT code, name, state FROM "{record.locator}"')}
        return shown != wanted
    except (DesignError, ValueError, sqlite3.Error):
        return True


def layer_sync_steps(project: StoreProject, version: Version | str | None, *, budget_s: float = STEP_BUDGET_S
                     ) -> Generator[Progress, None, bool]:
    """Los pasos de **poner al día la capa de entidades de la versión** ``version`` **si está marcada**
    (:func:`layer_pending`; spec 015, T43; RF-015-27, RF-015-29): lo de :func:`entity_layer_steps` solo si la capa no
    dice lo que el registro y, si no, **nada** (ni un paso: no se escribe ninguna operación). Devuelve si la
    regeneró. Lo hacen, tras lo suyo, :func:`release_support` (la 008 no recalcula lo que dependía de lo que se dio por
    bueno) y, por ``bl``, «Recalcular lo obsoleto» (:func:`layers_sync_steps`). Cada paso es de ``budget_s`` como mucho y
    cerrarlos (Esc) no deja nada a medias (una operación y una transacción). Rechazos, sin escribir nada: los de
    :func:`~.store.require_version` (RF-009-21)."""
    wanted = None if version is None else (version.uid if isinstance(version, Version) else version)
    found = require_version(project, wanted, provenance.ENTITY_LAYER)
    with _consistent(project) as conn:
        if not layer_pending(project, conn, found.uid):
            return False
    yield from entity_layer_steps(project, found, budget_s=budget_s)
    return True


def layers_sync_steps(project: StoreProject, *, budget_s: float = STEP_BUDGET_S
                      ) -> Generator[Progress, None, tuple[str, ...]]:
    """Los pasos de poner al día la capa de entidades **de cada versión editable del proyecto que la tenga marcada**
    (:func:`layer_sync_steps`; spec 015, T43; RF-015-27, RF-015-29): lo que hace ``bl`` al terminar «Recalcular lo
    obsoleto», que rehace las entidades por el grafo de la 008 sin pasar por lo que sigue a una orden de entidades.
    Devuelve los códigos de las versiones cuya capa regeneró (``()`` si todas decían lo que el registro: no se escribe
    nada). Una capa que no se puede regenerar (un rechazo, el disco) se deja como estaba, **marcada**, y queda en el
    registro técnico: no impide las demás ni lo que ya terminó."""
    with _consistent(project) as conn:
        due = [found for found in versions_read.versions(conn)
               if found.editable and layer_pending(project, conn, found.uid)]
    refreshed: list[str] = []
    for found in due:
        try:
            if (yield from layer_sync_steps(project, found, budget_s=budget_s)):
                refreshed.append(found.code)
        except _STAGE_ERRORS:
            LOGGER.warning("No se pudo poner al día la capa de entidades de %s: sigue marcada", found.code,
                           exc_info=True)
    return tuple(refreshed)


# --- Tras la orden de una entidad (spec 015, T19; RF-015-10, RF-015-16, RF-012-06; plan 015 §5.3.2) ---

_CHAIN_PHASE = "entity_chain"
_CHAIN_TOTAL = 100
"""El total de los pasos de :func:`after_entity_change`: un porcentaje (cada etapa tiene su tramo)."""
_CHAIN_DECLARE_SHARE = 40
"""El tramo, de ese porcentaje, que ocupa la declaración (de 0 a 40 %)."""
_CHAIN_MASKS_END = 90
"""Dónde acaba el tramo de la compilación de las máscaras (de 40 a 90 %); el resto, hasta 100 %, es de la capa de
entidades (T30)."""
_STAGE_ERRORS = (GeoblenderError, sqlite3.Error, OSError, ValueError)
"""Lo que una etapa de :func:`after_entity_change` da por un fallo suyo (un rechazo, el disco, la base): se
cuenta en el resultado y no se lanza; lo demás (un error del programa) sigue."""
_CHAIN_OWN = frozenset({provenance.DECLARE_CONSTRAINTS, masks_provenance.COMPILE, provenance.ENTITY_LAYER})
"""Las operaciones que hace la propia cadena: no se cuentan como «lo que quedó obsoleto». Con una entidad que
protege, el grafo da también por obsoletas la declaración, las máscaras y la capa de entidades que acaba de hacer
(el eco del ciclo entidad → declarada → máscaras → entidad, D-21): se ponen al día cuando se recalcula la entidad."""
_STALE_OPERATIONS = (
    "SELECT o.uid, o.op_type, o.settings FROM gb_operation AS o "
    "JOIN gb_revision AS r ON r.uid = o.revision_uid "
    "WHERE o.status = 'done' AND o.superseded_by IS NULL AND r.version_uid = ? "
    "AND EXISTS (SELECT 1 FROM gb_stale AS s WHERE s.item_kind = 'operation' AND s.item_uid = o.uid) "
    "ORDER BY o.fid")


class ChainStage(StrEnum):
    """Una etapa de :func:`after_entity_change`: declarar las restricciones de las entidades, recompilar las
    máscaras con ellas o poner al día la capa de entidades (T30)."""

    DECLARE = "declare"
    MASKS = "masks"
    LAYER = "layer"


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
    por ella (``obsolete``: las operaciones vigentes de la versión que usaron las máscaras anteriores, como
    ``ObsoleteKind.CONSUMER``, y lo que depende de ellas), el estado de las máscaras al terminar
    (``masks_state``) y lo que falló de la declaración o las máscaras (``failure``). De la capa de entidades
    (T30), aparte: cuántas entidades enseña ahora (``layer``; ``None`` si no se pudo poner al día), si su
    contenido **cambió** (``layer_changed``) y lo que falló (``layer_failure``)."""

    version: str
    declared: int | None
    declaration_changed: bool
    masks_compiled: bool
    changes: tuple[Change, ...] = ()
    obsolete: tuple[Obsolete, ...] = ()
    masks_state: access.MaskState = access.MaskState.CURRENT
    failure: ChainFailure | None = None
    layer: int | None = None
    layer_changed: bool = False
    layer_failure: ChainFailure | None = None

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
            found.append(Notice("des.entity_chain_obsolete", {
                "operations": len(self.obsolete), "items": obsolete_names(self.obsolete, self.version)}))
        if self.failure is not None:
            code = ("des.entity_chain_declare_failed" if self.failure.stage is ChainStage.DECLARE
                    else "des.entity_chain_masks_failed")
            found.append(Notice(code, {"version": self.version, "reason": self.failure.reason}))
        if self.layer_failure is not None:
            found.append(Notice("des.entity_chain_layer_failed",
                                {"version": self.version, "reason": self.layer_failure.reason}))
        return tuple(found)


def _stale_operations(conn: sqlite3.Connection, version: Version) -> dict[str, Obsolete]:
    """Las operaciones **obsoletas** de ``version`` (las vigentes: hechas y sin sustituir, estén en la revisión que
    estén, y con alguna causa en la caché de la 008, ``gb_stale``), por su uid, como ``Obsolete`` (``CONSUMER``).
    Lo congelado (los elementos de una revisión congelada) no cambia ni se marca (RF-009-19). Solo lee."""
    return {str(uid): _consumer(ObsoleteKind.CONSUMER, str(uid), str(op_type), _name_of(str(op_type), settings))
            for uid, op_type, settings in conn.execute(_STALE_OPERATIONS, (version.uid,))}


def _scaled(steps: Iterator[Progress], low: int, high: int) -> Generator[Progress, None, Any]:
    """Los pasos de una etapa (``steps``: ``Progress``, el último con su ``result``) como un tramo ``low`` a
    ``high`` del porcentaje de :func:`after_entity_change`; devuelve el resultado. El porcentaje **no retrocede**
    (una etapa con dos fases, como calcular las filas y guardarlas, cuenta cada una de 0 a 1). Cerrar el generador
    cierra ``steps``."""
    shown = low
    with closing(steps):  # type: ignore[type-var]
        for step in steps:
            if step.result is not None:
                return step.result
            fraction = min(max(step.done / step.total, 0.0), 1.0) if step.total else 0.0
            shown = max(shown, low + int((high - low) * fraction))  # no retrocede aunque la etapa cambie de fase
            yield Progress(_CHAIN_PHASE, shown, _CHAIN_TOTAL, step.message)
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
    (``gis.masks.access.compile_masks_steps``) y cuenta **qué quedó obsoleto con ello** (las operaciones vigentes
    de la versión que usaron las máscaras anteriores: la propia plataforma que protege, cuya restricción
    cambió lo que consumió, es lo esperado, CE-015-04 y D-21; «Recalcular lo obsoleto» la rehace y quita la
    marca de lo que dependía de ella si su salida no cambia, RF-008-26) y **lo ganado y lo perdido por
    restricción** (RF-012-06: el informe de la compilación). Sin cambio, no recompila. **(c)** Pone al día la
    **capa de entidades** de la versión (T30; RF-015-27: :func:`entity_layer_steps`, ``des_enl_<vNN>`` entera con
    todas las entidades calculadas), siempre: es independiente de las otras dos etapas (no depende de lo declarado
    ni de las máscaras), así que se hace aunque una de ellas falle.

    Cada etapa es una operación propia y **una transacción propia** (P-7): si una falla (un rechazo, el
    disco), no queda nada a medias de ella y el fallo va en el resultado (:class:`ChainFailure`) en lugar de
    lanzarse; si fueron las máscaras, quedan **obsoletas con su causa** y se compilan de nuevo antes de que un
    operador las use (``ensure_masks_steps``) o con «Compilar las máscaras»; si fue la capa de entidades,
    **conserva lo que tenía** (``layer_failure``): si lo que falló es el cambio de una entidad que enseña, la 008 la
    da por obsoleta **con su causa** (consume los datos de la entidad que cambió) y «Recalcular lo obsoleto» la
    rehace; si falló al crear una entidad nueva, no es entrada de la capa de antes y no hay causa en el grafo (el aviso
    lo dice): la rehace la orden siguiente de entidades. Cerrar el generador a mitad
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
                    _CHAIN_DECLARE_SHARE, _CHAIN_MASKS_END)
                compiled = True
                changes = recompiled.result.changes
            except _STAGE_ERRORS as error:
                failure = ChainFailure(ChainStage.MASKS, error)
    layer: int | None = None
    layer_changed = False
    layer_failure: ChainFailure | None = None
    yield Progress(_CHAIN_PHASE, _CHAIN_MASKS_END, _CHAIN_TOTAL, "Poniendo al día la capa de entidades…")
    with project.read() as conn:
        layer_before = dataset_registry.get(conn, provenance.dataset_name(provenance.ENTITY_MAP_TABLE),
                                            version_uid=found.uid)
    try:  # (c) la capa de entidades
        written: Stored = yield from _scaled(
            entity_layer_steps(project, found, budget_s=budget_s), _CHAIN_MASKS_END, _CHAIN_TOTAL)
        (record,) = written.records
        with project.read() as conn:
            (layer,) = conn.execute(f'SELECT COUNT(*) FROM "{record.locator}"').fetchone()
        layer_changed = layer_before is None or layer_before.content_sha256 != record.content_sha256
    except _STAGE_ERRORS as error:
        layer_failure = ChainFailure(ChainStage.LAYER, error)
    with project.read() as conn:
        now = _stale_operations(conn, found)
    after, _pending = access.mask_state(project, found.uid)
    chain = EntityChain(
        found.code, declared, changed, compiled, changes,
        tuple(item for uid, item in now.items()
              if uid not in stale and item.op_type not in _CHAIN_OWN), after, failure, layer, layer_changed,
        layer_failure)
    done = failure is None and layer_failure is None
    yield Progress(_CHAIN_PHASE, _CHAIN_TOTAL, _CHAIN_TOTAL,
                   "Restricciones declaradas, máscaras y capa de entidades al día" if done
                   else "Restricciones declaradas, máscaras y capa de entidades: no se pudo terminar",
                   result=chain)


# --- Descartar, «apoyo retirado» y soltar el apoyo (spec 015, T25; RF-015-17, RF-009-12; D-12; A7, P-6) --------

_OUTPUTS_OF = (
    "SELECT d.uid, d.name, d.status FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = ? ORDER BY io.fid")
_FINAL = frozenset(str(status) for status in FINAL_STATUSES)
_DISCARD_SOURCE = "orden «Descartar…», entidad «{name}»"
_INSERT_SOURCE = "orden «Insertar antes o después de…», entidad «{name}»"
"""El origen del parámetro ``discarded`` de una entidad sin calcular (RF-008-01): quién y desde dónde."""
_OPERATION_ROW = (
    "SELECT o.uid, o.op_type, o.settings FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
    "WHERE r.version_uid = ? AND o.status = 'done' AND o.superseded_by IS NULL ORDER BY o.fid")


def _version_in(conn: sqlite3.Connection, version: Version | str) -> Version:
    """La versión ``version`` (``Version``, uid o código) leída con ``conn``; ``VersionError``
    (``core.version_unknown``) si no existe."""
    wanted = version.uid if isinstance(version, Version) else version
    found = versions_read.version(conn, wanted)
    if found is None:
        raise VersionError("core.version_unknown", field="versión", value=wanted, version=wanted)
    return found


def _decider(person: str | None, project: StoreProject) -> str:
    """Quien decide: ``person`` o, sin él, quien tiene abierto el proyecto."""
    return (person or "").strip() or project.session.user_host


def _need_reason(reason: object, code: str, entity: str) -> str:
    """El motivo de una decisión (``reason``, sin los espacios de los extremos): ``DesignError`` ``code`` si falta
    (una decisión sin motivo no se registra). :class:`TypeError` si no es un texto."""
    if not isinstance(reason, str):
        raise TypeError(f"el motivo es un texto, no {reason!r}")
    if not reason.strip():
        raise DesignError(code, obj=f"Entidad «{entity}»", field="motivo", value=reason, entity=entity)
    return reason.strip()


@dataclass(frozen=True, slots=True)
class DiscardPlan:
    """**Lo que se enseña antes de descartar** una entidad (RF-015-17): su ``code``, su ``name``, su tipo (``kind``),
    su estado (``state``), si está calculada (``calculated``: si no, no tiene datos que descartar) y **una sola
    lista** de lo que se le apoya y de lo que parte de ella (``dependents``: nombre, tipo y volumen apoyado en m³ de
    cada uno, la de ``entities.dependents``)."""

    code: str
    name: str
    kind: EntityKind
    state: EntityState
    calculated: bool
    dependents: tuple[entities.Dependent, ...]

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """La lista, una línea por fila, en ``language`` («Sobre la balsa (Plataforma): 8 000 m³ apoyados»)."""
        return tuple(row.text(language) for row in self.dependents)


@dataclass(frozen=True, slots=True)
class Discarded:
    """Lo que hizo :func:`discard_entity`: la entidad (``code``, ``name``) de la versión ``version`` (su código), la
    operación que la había calculado (``operation_uid``; ``None`` si no estaba calculada), los datos que pasaron a
    ``DISCARDED`` (``datasets``, sus nombres; ninguno si no estaba calculada), la lista de lo que se le apoyaba
    (``dependents``: la que se enseñó antes) y el motivo y el decisor."""

    code: str
    name: str
    version: str
    operation_uid: str | None
    datasets: tuple[str, ...]
    dependents: tuple[entities.Dependent, ...]
    reason: str
    decided_by: str


def discard_plan(project: StoreProject, version: Version | str, code: str) -> DiscardPlan:
    """**La lista de antes de descartar** la entidad ``code`` (código o nombre) de la versión ``version`` (``Version``,
    uid o código; RF-015-17): **una sola lista** de lo que se le apoya y de lo que parte de ella —nombre, tipo y
    volumen apoyado en m³, entidades y diseños de la 013 y la 014: ``entities.dependents``— y su estado. Solo lee
    (no pide una versión editable). :class:`ValueError` si la entidad no es de la versión;
    ``VersionError`` si la versión no existe."""
    with _consistent(project) as conn:
        found = _version_in(conn, version)
        entry = entities.registry(project, found.uid, conn=conn).get(code)
        if entry is None:
            raise ValueError(f"la entidad «{code}» no es de la versión {found.code}")
        record = entry.record
        listed = entities.dependents(project, found.uid, record.code, conn=conn)
        return DiscardPlan(record.code, record.name, EntityKind(record.kind), EntityState(record.state),
                           entry.operation_uid is not None, listed)


def _set_discarded_flag(project: StoreProject, conn: sqlite3.Connection, found: Version, code: str, name: str,
                        who: str, why: str) -> None:
    """Marca descartada una entidad (T25 y T27; RF-015-17; D-12): su parámetro de versión ``discarded`` en
    verdadero, ADOPTADO, de la persona, con su motivo y su historial. Lo único que descarta a una entidad **sin
    calcular** y, con datos, lo que hace que una versión hija (que hereda parámetros, no resultados: RF-009-01) la
    reciba descartada."""
    store = ParameterStore(project)
    key = entity_key(code, PlatformParam.DISCARDED)
    if store.get(key, version=found.uid, conn=conn) is None:
        store.create(conn, key, True, kind="ADOPTADO", source=_DISCARD_SOURCE.format(name=name),
                     source_kind="person", decided_by=who, reason=why, version=found.uid)
    else:
        store.change(conn, key, value=True, source=_DISCARD_SOURCE.format(name=name), source_kind="person",
                     decided_by=who, reason=why, version=found.uid)


def discard_entity(project: StoreProject, version: Version | str, code: str, *, reason: str,
                   decided_by: str | None = None) -> Discarded:
    """**Descarta** la entidad ``code`` (código o nombre) de la versión editable ``version`` (``Version``, uid o
    código; RF-015-17, D-12; HU-015-2) **sin borrar nada** (RF-009-12): los datos que escribió su operación
    vigente (la superficie, la tabla y el informe) pasan a ``DISCARDED`` (``core.datasets.registry.set_status``) y
    su parámetro de versión ``des.platform.{e}.discarded`` pasa a verdadero, con su historial (también si no está
    calculada: entonces es lo único que se escribe; con él, una versión hija la recibe descartada, RF-009-01). En
    **una** transacción, con un evento ``entity_discarded`` (``reason``, ``decided_by``, los
    datos y la lista de lo que se le apoyaba, con sus m³). Lo que se le apoyaba queda en «apoyo retirado» (el grafo
    de la 008 lo deduce: :func:`~.entities.retired_supports`) y «Recalcular lo obsoleto» no lo recalcula hasta que la
    persona lo rehaga sobre otra superficie, lo descarte o lo dé por bueno con un motivo (:func:`release_support`).
    **No encadena** lo que sigue (:func:`after_entity_change`: la restricción que declaraba sale de la declaración y de
    las máscaras): lo hace la orden, con su avance y Esc. ``decided_by``: por defecto, quien tiene abierto el proyecto.

    Rechazos, sin escribir nada: los de :func:`~.store.require_version` (``VersionError``, RF-009-21: la versión
    no existe o no es editable), ``des.entity_discard_reason`` (sin motivo), ``des.entity_already_discarded``;
    :class:`ValueError` si la entidad no es de la versión."""
    wanted = version.uid if isinstance(version, Version) else version
    found = require_version(project, wanted, provenance.PLATFORM)
    who = _decider(decided_by, project)
    with project.write_transaction() as conn:
        entry = entities.registry(project, found.uid, conn=conn).get(code)
        if entry is None:
            raise ValueError(f"la entidad «{code}» no es de la versión {found.code}")
        record = entry.record
        why = _need_reason(reason, "des.entity_discard_reason", record.name)
        if record.state is EntityState.DISCARDED:
            raise DesignError("des.entity_already_discarded", obj=f"Entidad «{record.name}»", field="estado",
                              value=str(record.state), entity=record.name, version=found.code)
        listed = entities.dependents(project, found.uid, record.code, conn=conn)
        datasets: list[str] = []
        # Calculada o no, el parámetro de versión ``discarded``: una versión que parte de otra hereda los
        # parámetros y no los resultados (RF-009-01), así que sin él la entidad descartada con datos llegaría
        # «viva y sin calcular» a la versión hija (T27, hallazgo de la T26).
        _set_discarded_flag(project, conn, found, record.code, record.name, who, why)
        if entry.operation_uid is not None:  # con datos: nada se borra, pasan a ``DISCARDED``
            for uid, name, status in conn.execute(_OUTPUTS_OF, (entry.operation_uid, DATASET)).fetchall():
                if str(status) not in _FINAL:
                    dataset_registry.set_status(conn, project, str(uid), "discarded")
                    datasets.append(str(name))
        data: dict[str, Any] = {
            "version": found.code, "entity": record.code, "name": record.name, "reason": why,
            "decided_by": who, "operation": entry.operation_uid, "datasets": datasets,
            "dependents": [{"operation": row.operation_uid, "name": row.name, "type": row.op_type,
                            "state": str(row.state), "volume_m3": row.volume_m3} for row in listed]}
        record_event(conn, EventKind.ENTITY_DISCARDED,
                     render("des.event_entity_discarded", language="es", name=record.name, code=record.code,
                            version=found.code, reason=why),
                     session=project.session, at=format_utc(project.clock.now()), entity_kind="entity",
                     entity_uid=record.code, data=data)
    return Discarded(record.code, record.name, found.code, entry.operation_uid, tuple(datasets), listed, why, who)


@dataclass(frozen=True, slots=True)
class DiscardResult:
    """El resultado de :func:`discard_entity_steps`: lo que se descartó (``discarded``) y lo que siguió
    (``chain``, el :class:`EntityChain` de :func:`after_entity_change`: la declaración, las máscaras y lo que quedó
    obsoleto)."""

    discarded: Discarded
    chain: EntityChain


def discard_entity_steps(project: StoreProject, version: Version | str, code: str, *, reason: str,
                         decided_by: str | None = None, budget_s: float = STEP_BUDGET_S
                         ) -> Generator[Progress, None, None]:
    """**Descartar y lo que sigue, de una vez** (spec 015, T25; RF-015-17; plan 015 §5.3.2): descarta la entidad
    (:func:`discard_entity`, **a partir del segundo paso**: el primero solo dice que empieza y antes no se escribe
    nada) y encadena
    :func:`after_entity_change` por pasos de ``budget_s`` como mucho —su restricción sale de la declaración y de las
    máscaras—; el último ``Progress`` lleva el :class:`DiscardResult`. Cerrar el generador después de descartar
    (Esc) deja la entidad **descartada** (ya está: nada se deshace) y lo que sigue sin hacer; las máscaras quedan
    obsoletas con su causa hasta que se compilen de nuevo. Los rechazos son los de :func:`discard_entity`."""
    yield Progress(_CHAIN_PHASE, 0, _CHAIN_TOTAL, "Descartando la entidad…")
    found = discard_entity(project, version, code, reason=reason, decided_by=decided_by)
    chain: EntityChain | None = None
    for step in after_entity_change(project, found.version, budget_s=budget_s):
        if isinstance(step.result, EntityChain):
            chain = step.result
            continue
        yield step
    assert chain is not None  # after_entity_change acaba siempre con su resultado
    yield Progress(_CHAIN_PHASE, _CHAIN_TOTAL, _CHAIN_TOTAL, "Entidad descartada", result=DiscardResult(found, chain))


def _operation_to_release(conn: sqlite3.Connection, listed: EntityRegistry, found: Version, target: str
                          ) -> tuple[str, str, dict[str, Any]]:
    """La operación vigente de la versión ``found`` que se da por buena: la de la entidad ``target`` (código o
    nombre) o la operación de uid ``target`` o de nombre ``target`` (un diseño de la 013 o la 014); como ``(uid,
    tipo, ajustes)``. :class:`ValueError` si no hay ninguna, es ambigua o es una entidad sin calcular."""
    entry = listed.get(target)
    if entry is not None:
        if entry.operation_uid is None:
            raise ValueError(f"la entidad «{target}» no está calculada: no hay operación que dar por buena")
        wanted = entry.operation_uid
        rows = [row for row in conn.execute(_OPERATION_ROW, (found.uid,)).fetchall() if row[0] == wanted]
    else:
        rows = [row for row in conn.execute(_OPERATION_ROW, (found.uid,)).fetchall()
                if row[0] == target or _name_of(str(row[1]), row[2]) == target]
    if len(rows) != 1:
        raise ValueError(f"«{target}» no es una operación vigente de {found.code}" if not rows else
                         f"«{target}» es el nombre de {len(rows)} operaciones vigentes de {found.code}: "
                         "indique su uid")
    ((uid, op_type, settings),) = rows
    return str(uid), str(op_type), dict(json.loads(str(settings))) if settings else {}


_ROAD_POINTS = (RoadParam.ORIGIN, RoadParam.DESTINATION, RoadParam.SUPPORT)
"""Los valores de una pista que **son** una entidad (spec 017, T24; RF-017-03): el origen (un punto de su eje, ``RDW-001@100``), el destino (``entity:PLT-001``) y la superficie de apoyo
(``entity:RDW-001``), por este orden."""


def _release_blocker(values: Mapping[str, Any], code: str) -> RoadParam | None:
    """De los valores ``values`` de una pista (por último segmento de su clave: :func:`entity_parameters`), **el primero** de :data:`_ROAD_POINTS` que es la entidad ``code`` (spec 017, T24;
    RF-015-17, RF-017-03): una pista cuyo origen está en el eje de otra pista, cuyo destino es una entidad o cuya superficie de apoyo es la de una entidad **toma de ella su lugar y su cota**, así
    que no se puede repetir sin ella cuando se descartó (se rehace con otro origen o destino, o se descarta). ``None`` si ninguno lo es; lo que solo **declara** la persona (``supports``) y la partida
    (``start``: :func:`release_support` la rechaza aparte, ``des.entity_release_start``) no cuentan."""
    for param in _ROAD_POINTS:
        text = values.get(param.value)
        if isinstance(text, str) and entities.refers_to(text) == code:
            return param
    return None


def release_support(project: StoreProject, version: Version | str, target: str, entity_code: str | None = None,
                    *, reason: str, decided_by: str | None = None, budget_s: float = STEP_BUDGET_S
                    ) -> tuple[OperationHandle, Iterator[Progress]]:
    """**Da por bueno** lo que perdió su apoyo (RF-015-17, RF-008-27; plan 015 §5.4 A7, P-6): repite la operación
    ``target`` —el código o el nombre de una entidad, o el uid o el nombre de un diseño de la 013 o la 014— de la
    versión editable ``version`` **con ``supersedes``, sin esa entrada**, sin pasar por el plan de «Recalcular lo
    obsoleto», que la rehúsa (``core.recompute_no_successor``): ``design.store.recompute_run(released=…)`` (la
    plataforma, con los parámetros vigentes de su entidad). Lo que deja de apoyar es el de ``entity_code`` (una
    entidad descartada en la que se apoyaba) o, sin él, **todo** lo que perdió: no puede conservar un apoyo
    descartado, así que soltar uno y dejar otro se rechaza (``des.entity_release_others``). El motivo y el
    decisor (``decided_by``; por defecto, quien tiene abierto el proyecto) quedan en sus **ajustes**
    (``provenance.SUPPORTS_RELEASED``, acumulados) y en un **evento** ``support_released`` al terminar. Su salida no
    cambia (los mismos hash) y lo que dependía de ella **no se recalcula** (RF-008-26).

    Devuelve la ``OperationHandle`` «en curso» de la operación nueva y sus pasos (como ``recompute_run``), que
    avanza quien la llama; el último lleva el ``Stored``. Rechazos al llamar, **sin escribir nada**: los de
    :func:`~.store.require_version`; ``des.entity_release_reason`` (sin motivo), ``des.entity_release_unknown`` y
    ``des.entity_release_nothing`` (no tiene retirado ese apoyo), ``des.entity_release_start`` (parte de la superficie
    de la entidad descartada: no se puede dar por buena; se rehace sobre otra o se descarta),
    ``des.entity_release_support_param`` (la tiene como superficie de apoyo) y ``des.entity_release_others``;
    :class:`ValueError` si ``target`` o ``entity_code`` no son de la versión.

    **Una pista** (spec 017, T24; RF-015-17, RF-017-03; P-5: sin regla nueva del grafo) se da por buena como las demás cosas que **se apoyan** sin partir de la entidad descartada (lo que
    **declaró** la persona en ``supports``, lo que rellena sobre su huella): ``design.road_store.recompute_road(released=…)`` la repite sin esa entrada. La que toma **de la entidad su origen, su
    destino o su superficie de apoyo** no: su geometría sale de ella (``des.road_release_geometry``, o ``des.entity_release_support_param`` para la superficie de apoyo); se rehace con otro
    origen o destino, o se descarta. El ramal que parte de la superficie de la pista descartada se rechaza antes (``des.entity_release_start``)."""
    wanted = version.uid if isinstance(version, Version) else version
    found = require_version(project, wanted, provenance.PLATFORM)
    with _consistent(project) as conn:
        listed = entities.registry(project, found.uid, conn=conn)
        uid, op_type, settings = _operation_to_release(conn, listed, found, target)
        chosen_entry = None
        if entity_code is not None:
            chosen_entry = listed.get(entity_code)
            if chosen_entry is None:
                raise ValueError(f"la entidad «{entity_code}» no es de la versión {found.code}")
        lost = {item.operation_uid: item for item in entities.retired_supports(project, found.uid, conn=conn)}
    name = _name_of(op_type, json.dumps(settings))
    why = _need_reason(reason, "des.entity_release_reason", name)
    who = _decider(decided_by, project)
    obj = f"Operación «{name}»"
    retired = lost.get(uid)
    if chosen_entry is None:
        if retired is None:
            raise DesignError("des.entity_release_nothing", obj=obj, field="entidad", value=None, entity=name,
                              version=found.code)
        picked = list(retired.retired)
    else:
        picked = [] if retired is None else [item for item in retired.retired if item.code == chosen_entry.record.code]
        if not picked:
            raise DesignError("des.entity_release_unknown", obj=obj, field="entidad", value=entity_code,
                              entity=name, target=chosen_entry.record.name, version=found.code)
        others = [item for item in retired.retired if item not in picked] if retired is not None else []
        if others:
            raise DesignError("des.entity_release_others", obj=obj, field="entidad", value=entity_code,
                              entity=name, others=", ".join(f"«{item.name}»" for item in others))
    for item in picked:
        if "surface" in item.roles:
            raise DesignError("des.entity_release_start", obj=obj, field="superficie de partida",
                              value=item.name, entity=name, target=item.name)
    if op_type == provenance.PLATFORM:
        code = provenance.platform_code(settings)
        support = platform_parameters(project, found, code).get(PlatformParam.SUPPORT.value)
        for item in picked:
            if item.code is not None and entities.ref_code(support if isinstance(support, str) else None) == item.code:
                raise DesignError("des.entity_release_support_param", obj=obj, field="superficie de apoyo",
                                  value=support, entity=name, target=item.name)
    elif op_type == provenance.ROAD:  # lo que la pista toma de la entidad (su lugar y su cota) no se suelta: sin ella no hay geometría (T24)
        code = provenance.supported_code(settings)
        values = entity_parameters(project, code, version=found)
        for item in picked:
            blocker = None if item.code is None else _release_blocker(values, item.code)
            if blocker is RoadParam.SUPPORT:
                raise DesignError("des.entity_release_support_param", obj=obj, field="superficie de apoyo",
                                  value=values.get(blocker.value), entity=name, target=item.name)
            if blocker is not None:
                raise DesignError("des.road_release_geometry", obj=obj, field=entity_key(code, blocker),
                                  value=values.get(blocker.value), entity=name, target=item.name)
    stamp = format_utc(project.clock.now())
    released = tuple(provenance.ReleasedSupport(str(item.code), why, who, stamp)
                     for item in picked if item.code is not None)
    request = RecomputeRequest(project, uid, op_type, settings, (), (), version=found.uid)  # type: ignore[arg-type]
    handle, work = recompute_run(request, budget_s=budget_s, released=released)
    return handle, _ReleaseSteps(project, found, handle, work, name, uid, picked, released)


class _ReleaseSteps:
    """Los pasos de ``work`` (la operación repetida sin su apoyo) y, **cuando está completa** (el último trae su
    resultado), el evento ``support_released`` en su propia transacción y, tras él, **la capa de entidades puesta al
    día** si ya no dice lo que el registro (:func:`layer_sync_steps`; T43, hallazgo E-4: la salida no cambia, así que
    la 008 no toca lo que dependía de ella, y la capa decía «apoyo retirado» sobre una entidad al día); el último paso,
    el de la operación, va después. Cerrarlos antes (Esc, desactivar Geoblender) no deja evento ni operación: los pasos
    empezados ya cancelan la suya; si **no empezaron**, la operación que abrió ``recompute_run`` queda «cancelada» aquí
    (como las de la cola de ``des``). Cerrarlos **durante la capa** deja lo hecho (la operación y su evento están
    completos) y la capa marcada (:func:`layer_pending`); un fallo de la capa tampoco deshace nada."""

    def __init__(self, project: StoreProject, found: Version, handle: OperationHandle, work: Iterator[Progress],
                 name: str, superseded: str, picked: Sequence[entities.RetiredEntity],
                 released: Sequence[provenance.ReleasedSupport]) -> None:
        self._project, self._found, self._handle, self._work = project, found, handle, work
        self._name, self._superseded, self._picked, self._released = name, superseded, picked, released
        self._started = self._finished = self._completed = False
        self._held: Progress | None = None
        self._tail: Iterator[Progress] | None = None

    def __iter__(self) -> _ReleaseSteps:
        return self

    def __next__(self) -> Progress:
        if self._finished:
            raise StopIteration
        if not self._completed:
            self._started = True
            try:
                step = next(self._work)
            except BaseException:  # los pasos ya dejan la operación fallida o cancelada
                self._finished = True
                raise
            if step.result is None:
                return step
            self._completed = True
            _record_release(self._project, self._found, self._handle.uid, self._name, self._superseded,
                            self._picked, self._released)
            self._held = step
            self._tail = self._layer_steps()
        assert self._tail is not None and self._held is not None
        try:
            return next(self._tail)
        except StopIteration:
            held, self._held, self._finished = self._held, None, True
            return held

    def _layer_steps(self) -> Iterator[Progress]:
        """Los pasos de la capa (sin su resultado: el último paso es el de la operación); un rechazo o un fallo del disco
        la dejan marcada y no cambian lo que ya está hecho."""
        try:
            for step in layer_sync_steps(self._project, self._found):
                yield replace(step, result=None)
        except _STAGE_ERRORS:
            LOGGER.warning("No se pudo poner al día la capa de entidades de %s tras dar por bueno un apoyo: sigue "
                           "marcada", self._found.code, exc_info=True)

    def close(self) -> None:
        """Cierra los pasos: si no empezaron, la operación nueva queda «cancelada»; si no, la cancelan ellos (o,
        completa, queda como está)."""
        if not self._started and not self._finished:
            try:
                self._handle.cancel(CANCELLED_REASON)
            except (GeoblenderError, sqlite3.Error, OSError):  # ya no estaba en curso: nada que dejar
                pass
        self._finished = True
        for steps in (self._tail, self._work):
            close = getattr(steps, "close", None)
            if callable(close):
                close()


def _record_release(project: StoreProject, found: Version, operation: str, name: str, superseded: str,
                    picked: Sequence[entities.RetiredEntity], released: Sequence[provenance.ReleasedSupport]
                    ) -> None:
    """El evento ``support_released`` de la operación ``operation`` (la que da por bueno el apoyo): quién, por qué,
    de qué entidades y qué operación sustituye."""
    first = released[0]
    shown = ", ".join(f"«{item.name}»" for item in picked)
    data: dict[str, Any] = {
        "version": found.code, "name": name, "operation": operation, "superseded": superseded,
        "entities": [item.entity for item in released], "names": [item.name for item in picked],
        "reason": first.reason, "decided_by": first.by}
    with project.write_transaction() as conn:
        record_event(conn, EventKind.SUPPORT_RELEASED,
                     render("des.event_support_released", language="es", name=name, version=found.code,
                            entities=shown, reason=first.reason),
                     session=project.session, at=format_utc(project.clock.now()), entity_kind="operation",
                     entity_uid=operation, data=data)


# --- Traer las entidades de otra versión (spec 015, T26; RF-015-18, RF-009-01; D-18; plan 015 P-4) ---------

_BROUGHT = "Traído de {label}"
"""El motivo de la fila de historial de cada parámetro traído (como «Heredado de V10.r2» de ``inherit``)."""
_OF_VERSION = "SELECT 1 FROM gb_dataset WHERE version_uid = ? AND name = ? LIMIT 1"
"""Si la versión de origen tiene un dato **propio** con ese nombre (un resultado suyo, no del proyecto)."""
_NOT_BROUGHT = frozenset({PlatformParam.DISCARDED})
"""Los parámetros de la entidad que no se traen: ``discarded`` solo existe en las descartadas sin calcular, que no se
traen (lo descartado es un estado de la versión de origen)."""
_FOLLOW_CODES = "; sus referencias siguen los códigos de las entidades traídas"
_REFERENCES = frozenset({PlatformParam.START, PlatformParam.SUPPORT, PlatformParam.SUPPORTS, BodyParam.SURFACE, RoadParam.ORIGIN, RoadParam.DESTINATION})
_POINT_REFERENCES: Mapping[str, tuple[tuple[RoadParam, str], ...]] = MappingProxyType({
    "road": ((RoadParam.ORIGIN, "des.road_bring_origin_lost"), (RoadParam.DESTINATION, "des.road_bring_destination_lost"))})
"""Los valores que son **un texto con el código de otra entidad**, por tipo (spec 017, T22b; hallazgo C-4 con la pista), con el aviso de lo que se pierde: el origen de una pista
(``RDW-001@100,5``, un punto del eje de otra pista) y su destino (``entity:PLT-001``, una entidad). Traer las entidades de otra versión los re-apunta como la partida y el apoyo
(:func:`bring_entities`); el nombre de un punto de la capa no es una referencia y se conserva."""


@dataclass(frozen=True, slots=True)
class BroughtEntity:
    """Una entidad que trajo :func:`bring_entities`: su código (``source_code``) y su nombre (``source_name``) en la
    versión de origen, los que tiene ahora en la de destino (``code``, ``name``: otros si los de origen estaban
    ocupados), su partida (``start``) y su superficie de apoyo (``support``) **en el destino** (``None``: sin valor,
    porque eran un resultado de la versión de origen o la superficie de la que ya parte otra entidad) y cuántos
    parámetros se copiaron (``parameters``)."""

    source_code: str
    code: str
    source_name: str
    name: str
    start: str | None
    support: str | None
    parameters: int

    @property
    def recoded(self) -> bool:
        """Si el código de origen estaba ocupado en el destino y recibió el siguiente."""
        return self.code != self.source_code

    @property
    def renamed(self) -> bool:
        """Si el nombre de origen estaba ocupado en el destino (por otra entidad o por un dato con ese nombre)."""
        return self.name != self.source_name


@dataclass(frozen=True, slots=True)
class Brought:
    """Lo que hizo :func:`bring_entities`: la versión de origen (``source``, su código), la de destino (``version``), la
    revisión de la que se tomó el valor de los parámetros (``label``, «V09.r2»), las entidades traídas
    (``entities``, por el código de origen) y los avisos, en el orden en que se enseñan (``notices``: cuántas, los
    códigos y los nombres cambiados, lo que quedó sin valor)."""

    source: str
    version: str
    label: str
    entities: tuple[BroughtEntity, ...]
    notices: tuple[Notice, ...]

    @property
    def parameters(self) -> int:
        """Cuántas filas de parámetros se escribieron en el destino."""
        return sum(item.parameters for item in self.entities)


@dataclass(frozen=True, slots=True)
class _BringRow:
    """Un parámetro que se escribe en el destino: su clave nueva, la fila de la versión de origen de la que sale
    (``record``: su tipo, su origen, su decisor y la fecha de su decisión), su valor (el mismo, salvo lo que sigue
    los códigos y los nombres nuevos) y su motivo."""

    key: str
    record: ParameterRecord
    value: object
    reason: str


def _revision_label(conn: sqlite3.Connection, version: Version) -> str:
    """La revisión de ``version`` en que sus parámetros tienen hoy su valor: la abierta o, si no hay, la última
    («V09.r2»; sin revisiones, su código): lo que dice «Traído de V09.r2», como ``inherit``."""
    current = versions_read.open_revision(conn, version.uid)
    if current is not None:
        return current.label(version.code)
    known = versions_read.revisions(conn, version.uid)
    return known[-1].label(version.code) if known else version.code


def _chosen(listed: EntityRegistry, source: Version, wanted: Iterable[str] | None) -> list[entities.EntityEntry]:
    """Las entidades de la versión de origen que se traen: todas las que no están descartadas (``wanted`` ``None``) o
    las que se piden por su código o su nombre. Una descartada es un registro y no se trae
    (``des.entity_bring_discarded`` si se pide); una que no hay, ``des.entity_bring_unknown``. Por el orden de sus
    códigos."""
    if wanted is None:
        return [entry for entry in listed if entry.record.state is not EntityState.DISCARDED]
    found: dict[str, entities.EntityEntry] = {}
    for ref in wanted:
        entry = listed.get(ref)
        if entry is None:
            raise DesignError("des.entity_bring_unknown", obj=f"Versión {source.code}", field="entidad", value=ref,
                              entity=ref, source=source.code)
        if entry.record.state is EntityState.DISCARDED:
            raise DesignError("des.entity_bring_discarded", obj=f"Entidad «{entry.record.name}»", field="estado",
                              value=str(entry.record.state), entity=entry.record.name, source=source.code)
        found[entry.record.code] = entry
    return sorted(found.values(), key=lambda entry: entities.code_order(entry.record.code))


def _new_codes(chosen: Sequence[entities.EntityEntry], taken: Collection[str]) -> dict[str, str]:
    """El código que tiene cada entidad de ``chosen`` en el destino: el suyo si no está ocupado en él (``taken``: los
    de todas las entidades de la versión, también las descartadas, que siguen en ella) y, si no, el siguiente de su
    tipo (``entities.next_code``, que nunca reutiliza uno)."""
    used = set(taken)
    found = {entry.record.code: entry.record.code for entry in chosen if entry.record.code not in used}
    used.update(found)
    for entry in chosen:
        if entry.record.code not in found:
            found[entry.record.code] = entities.next_code(entry.record.kind, used)
            used.add(found[entry.record.code])
    return found


def _free_name(name: str, version: str, names: set[str], data: set[str]) -> str:
    """``name`` si el destino no lo tiene (ni otra entidad con ese nombre ni su dato de superficie, que es el mismo
    nombre en ASCII: la regla de ``_identify``) y, si no, ``name (V09)`` y, si también está ocupado, ``name (V09) 2``,
    ``3``… Lo apunta entre los nombres ocupados."""
    surface = provenance.ENTITY_SURFACE_GRID

    def taken(text: str) -> bool:
        return text in names or provenance.dataset_name(surface, text) in data

    candidate = name
    if taken(candidate):
        candidate, number = f"{name} ({version})", 1
        while taken(candidate):
            number += 1
            candidate = f"{name} ({version}) {number}"
    names.add(candidate)
    data.add(provenance.dataset_name(surface, candidate))
    return candidate


def _brought_surface(conn: sqlite3.Connection, source: Version, listed: EntityRegistry, ref: str | None,
                     new: Mapping[str, str]) -> tuple[str | None, str | None]:
    """La superficie ``ref`` (la partida o el apoyo de una entidad de la versión de origen) como vale en el destino:
    ``(valor, nombre de lo que se pierde)``. ``entity:<código>`` de una entidad que se trae pasa a su código nuevo; la
    de una que no, y el nombre de un dato propio de la versión de origen (una superficie de diseño suya), no existen
    en el destino y quedan **sin valor**, con el nombre que se enseña en el aviso (el de la entidad o el del dato); el
    terreno y lo demás del proyecto se conservan."""
    if ref is None or not ref.strip():
        return None, None
    code = entities.ref_code(ref)
    if code is not None:
        if code in new:
            return entities.surface_ref(new[code]), None
        other = listed.get(code)
        return None, other.record.name if other is not None else ref.strip()
    if conn.execute(_OF_VERSION, (source.uid, ref.strip())).fetchone() is not None:
        return None, ref.strip()
    return ref, None


def _brought_point(listed: EntityRegistry, ref: str | None, new: Mapping[str, str]) -> tuple[str | None, str | None]:
    """El origen o el destino ``ref`` de una pista de la versión de origen (``RDW-001@100,5``, ``entity:PLT-001`` o el nombre de un punto de su capa) como vale en el destino:
    ``(valor, nombre de lo que se pierde)`` (spec 017, T22b; C-4). La referencia a una entidad que se trae pasa a su código nuevo (``entities.with_code``: la abscisa se queda como estaba);
    la de una que no se trae —o que ni existe— queda **sin valor**, con el nombre de la entidad (o su código si no existe); lo demás (un punto de la capa, que es del proyecto) se
    conserva."""
    if ref is None or not ref.strip():
        return None, None
    code = entities.refers_to(ref)
    if code is None:
        return ref, None
    if code in new:
        return entities.with_code(ref, new[code]), None
    other = listed.get(code)
    return None, other.record.name if other is not None else code


def _brought_supports(text: str | None, new: Mapping[str, str]) -> tuple[str | None, tuple[str, ...]]:
    """Lo que la persona declaró que la entidad apoya (``supports``: códigos separados por comas) como vale en el
    destino: ``(texto, lo que no se trae)``. Cada código pasa al nuevo; el de una entidad que no se trae se pierde (aunque
    el destino tenga otra con ese código: no es la misma entidad)."""
    declared = _declared(text)
    kept = [new[part] for part in declared if part in new]
    return (", ".join(kept) or None), tuple(part for part in declared if part not in new)


def _entity_rows(store: ParameterStore, conn: sqlite3.Connection, source: Version, record: EntityRecord, fresh: str,
                 label: str, changed: Mapping[str, object]) -> list[_BringRow]:
    """Los parámetros de la entidad ``record`` de la versión de origen que se escriben en el destino con el código
    ``fresh``: los que tienen valor (``changed`` da el de los que cambian: el nombre, la partida, el apoyo, lo
    declarado y, del cuerpo apoyado, su superficie conocida; si es ``None``, no se escribe), con su motivo, «Traído de V09.r2» y
    lo que cambió. Los de **la familia de su tipo** (spec 016, T35: la detección de acopios, la retirada, el contrafuerte y el
    cuerpo apoyado tienen la suya, sin los valores que no son suyos: la detección no tiene ``start``). Solo lee."""
    rows: list[_BringRow] = []
    for param in entities.entity_type(record.kind).params.names:
        found = None if param in _NOT_BROUGHT else store.get(entity_key(record.code, param), version=source.uid,
                                                             conn=conn)
        if found is None or found.value is None:
            continue
        value = changed[param] if param in changed else found.value
        if value is None:
            continue
        why = _BROUGHT.format(label=label)
        if param == PlatformParam.NAME and (fresh != record.code or value != record.name):
            why += f"; era la entidad {record.code} «{record.name}» de {source.code}"
        elif param in _REFERENCES and value != found.value:
            why += _FOLLOW_CODES
        if found.kind is ParamKind.CALCULADO:
            why += f"; era CALCULADO en {source.code}: se trae su valor, no la cifra"
        rows.append(_BringRow(entity_key(fresh, param), found, value, why))
    return rows


def bring_entities(project: StoreProject, source_version: Version | str, target_version: Version | str, *,
                   codes: Iterable[str] | None = None) -> Brought:
    """**Trae a la versión editable ``target_version`` las entidades de otra versión** (``source_version``; ``Version``,
    uid o código; cualquiera: no solo la madre; spec 015, T26; RF-015-18, D-18; plan 015 P-4): copia sus **definiciones**
    —los parámetros ``des.platform.{e}.*`` de cada una con su valor, su tipo, su origen, su decisor y la fecha de su
    decisión, y una entrada de historial «Traído de V09.r2», como ``ParameterStore.inherit`` («Heredado de…»); la capa y
    la geometría de origen, que son parámetros, y lo que la persona declaró que apoya (``supports``)—, **sin sus
    resultados ni sus cifras** (RF-009-01: ni superficies, ni tablas, ni informes, ni cifras, ni las restricciones que
    declaraban, que son derivadas y se regeneran al calcular): quedan **sin calcular**, y sus dependencias se detectan de
    nuevo al calcularlas (el gancho de ``DesignWriter.commit``, :func:`create_platform` con su código). La versión que
    **parte de otra** ya las recibe así, por ``inherit`` (RF-009-01).

    ``codes``: las que se traen, por su código o su nombre en la versión de origen (por defecto, todas las que no están
    descartadas; una descartada es un registro y no se trae, y pedirla se rechaza). **Códigos y nombres**: si el código
    de una ya está ocupado en el destino (también por una descartada), recibe el siguiente (``entities.next_code``) y las
    referencias entre las traídas (``start``, ``support`` y ``supports``; y, de una pista, su **origen** en el eje de otra pista, ``RDW-001@100,5``, y su **destino** en
    una entidad, ``entity:PLT-001``: spec 017, T22b) siguen el código nuevo; si su nombre ya lo tiene
    una entidad o un dato del destino, se le añade la versión de origen entre paréntesis («Carga (V09)»; con otro
    número si también está ocupado). **Partidas**: una superficie de la versión de origen que no existe en el destino
    —la de una entidad que no se trae, o un dato suyo— queda **sin valor**, con un aviso (la entidad no se puede
    calcular hasta que se elija otra); el terreno y lo demás del proyecto se conservan; y una que ya es la de otra
    entidad del destino también (de cada superficie parte una entidad: RF-015-04). Lo declarado en ``supports`` sobre una
    entidad que no se trae se pierde, con su aviso. Y el origen o el destino de una pista que apunta a una entidad que no se trae (o que no existe) queda **sin valor**, con
    ``des.road_bring_origin_lost`` o ``des.road_bring_destination_lost``: la pista no se puede calcular hasta que se elija otro; el nombre de un punto de la capa se conserva.

    **Una sola transacción**: si algo falla, no queda nada. Nada se escribe si no hay nada que traer. No encadena la
    declaración ni las máscaras (lo que se trae no está calculado, no declara nada) ni deja ningún evento: el historial
    de cada parámetro lo dice. Rechazos, sin escribir nada: los de :func:`~.store.require_version` (``VersionError``,
    RF-009-21: el destino no existe o no es editable; el origen no existe), ``des.entity_bring_same``,
    ``des.entity_bring_unknown`` y ``des.entity_bring_discarded``."""
    wanted = target_version.uid if isinstance(target_version, Version) else target_version
    target = require_version(project, wanted, provenance.PLATFORM)
    store = ParameterStore(project)
    with project.write_transaction() as conn:
        source = _version_in(conn, source_version)
        if source.uid == target.uid:
            raise DesignError("des.entity_bring_same", obj=f"Versión {target.code}", field="versión de origen",
                              value=source.code, version=target.code)
        listed = entities.registry(project, source.uid, conn=conn)
        mine = entities.registry(project, target.uid, conn=conn)
        label = _revision_label(conn, source)
        chosen = _chosen(listed, source, (codes,) if isinstance(codes, str) else (
            None if codes is None else tuple(codes)))
        if not chosen:
            return Brought(source.code, target.code, label, (),
                           (Notice("des.entity_bring_nothing", {"source": source.code}),))
        new = _new_codes(chosen, [entry.record.code for entry in mine])
        names = {entry.record.name for entry in mine}
        data = {provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, name) for name in names}
        records = list(mine.records)
        brought: list[BroughtEntity] = []
        notices: list[Notice] = []
        rows: list[_BringRow] = []
        for entry in chosen:
            record = entry.record
            fresh = new[record.code]
            name = _free_name(record.name, source.code, names, data)
            start, lost_start = _brought_surface(conn, source, listed, record.start, new)
            support, lost_support = _brought_surface(conn, source, listed, record.support, new)
            known = _KNOWN_SURFACES.get(str(record.kind))  # la superficie conocida del cuerpo: una referencia más (T47, C-4)
            surface = lost_surface = None
            if known is not None:
                original = store.get(entity_key(record.code, known), version=source.uid, conn=conn)
                surface, lost_surface = _brought_surface(
                    conn, source, listed, None if original is None or original.value is None else str(original.value), new)
            pointed: dict[str, str | None] = {}
            lost_points: list[tuple[str, str]] = []
            for param, message in _POINT_REFERENCES.get(str(record.kind), ()):  # el origen y el destino de una pista: una referencia más (T22b, C-4)
                original = store.get(entity_key(record.code, param), version=source.uid, conn=conn)
                if original is None or original.value is None:
                    continue
                pointed[param], gone = _brought_point(listed, str(original.value), new)
                if gone is not None:
                    lost_points.append((message, gone))
            taken = entities.start_conflict(records, start)
            if taken is not None:  # de cada superficie parte una entidad: la traída no puede ser la segunda
                notices.append(Notice("des.entity_bring_start_taken", {
                    "name": name, "surface": start, "other": taken.name, "version": target.code}))
                start = None
            records.append(EntityRecord(fresh, name, record.kind, start, support))
            declared = store.get(entity_key(record.code, PlatformParam.SUPPORTS), version=source.uid, conn=conn)
            supports, lost_supports = _brought_supports(
                None if declared is None or declared.value is None else str(declared.value), new)
            made = _entity_rows(store, conn, source, record, fresh, label, {
                PlatformParam.NAME: name, PlatformParam.START: start, PlatformParam.SUPPORT: support,
                PlatformParam.SUPPORTS: supports, **({} if known is None else {known: surface}), **pointed})
            rows.extend(made)
            brought.append(BroughtEntity(record.code, fresh, record.name, name, start, support, len(made)))
            if fresh != record.code:
                notices.append(Notice("des.entity_bring_recoded", {
                    "name": name, "old": record.code, "code": fresh, "source": source.code,
                    "version": target.code}))
            if name != record.name:
                notices.append(Notice("des.entity_bring_renamed", {
                    "old": record.name, "name": name, "version": target.code}))
            for message, gone in (("des.entity_bring_start_lost", lost_start), ("des.entity_bring_support_lost", lost_support),
                                  ("des.body_bring_surface_lost", lost_surface)):
                if gone is not None:
                    notices.append(Notice(message, {
                        "name": name, "surface": gone, "source": source.code, "version": target.code}))
            for message, gone in lost_points:
                notices.append(Notice(message, {"name": name, "target": gone, "source": source.code, "version": target.code}))
            if lost_supports:
                notices.append(Notice("des.entity_bring_supports_lost", {
                    "name": name, "entities": ", ".join(f"«{part}»" for part in lost_supports)}))
        entities.check_chain(records)  # la cadena del destino sigue siendo válida: si no, no se escribe nada
        for row in rows:
            kind = ParamKind.ADOPTADO if row.record.kind is ParamKind.CALCULADO else row.record.kind
            store.create(conn, row.key, row.value, kind=kind, source=row.record.source,  # type: ignore[arg-type]
                         source_kind=row.record.source_kind, decided_by=row.record.decided_by,
                         decided_at=row.record.decided_at, reason=row.reason, version=target.uid)
    done = Notice("des.entity_bring_done", {"count": len(brought), "source": source.code, "version": target.code})
    return Brought(source.code, target.code, label, tuple(brought), (done, *notices))
