# SPDX-License-Identifier: GPL-3.0-or-later
"""Declaraciones de procedencia de las envolventes y el escalonado (spec 013, T13; HU-013-3,
HU-013-6; RF-013-17, RF-013-31; plan 013 §5.2.3, D-26, D-28; ADR-0013, ADR-0025 §2).

Lo que ``des`` registra en la procedencia de la 008 y de la 009, declarado con tipos de ``core``.
Importar este módulo no registra nada: lo registra ``bl/ops/des.py`` (T21 y T24) con sus
funciones de recálculo y de reproducción, que son de ``bl``; las pruebas, a mano. Es ligero (no
importa los cálculos: ``bl`` lo importa al habilitar la extensión), Python puro (nivel 8).

**Dos operaciones de versión** (:data:`OPERATION_TYPES`, versión :data:`OP_VERSION`; D-26): se
repiten solas y se reproducen con :data:`FIGURE_TOLERANCE` (10⁻⁹ relativo: con otro numpy el
barrido puede cambiar el último bit). Las lanza la misma orden (:data:`COMMAND`), que encadena
las dos si se pide «Escalonar»:

- ``des.envelope`` (:data:`ENVELOPE`): una envolvente de pendiente acotada; escribe
  ``des_env_<nombre>``;
- ``des.stepped_design`` (:data:`STEPPED`): el escalonado de una envolvente; consume la anterior,
  de modo que cambiar un perfil deja obsoleta la superficie sin rehacer la envolvente que no lo
  usó. Escribe la superficie de diseño (``des_srf_``), las bermas (``des_brm_``), su tabla
  (``des_bmt_``) y el informe (``des_rpt_``).

**Datos de la versión** (:data:`FAMILIES`): ``des_<familia>_<nombre>`` (:func:`dataset_name`, con
el nombre de la operación en ASCII, ``gis.provenance.dataset_slug``) con el código de la versión
en su ubicación (:func:`dataset_locator`; D-34 de la 009). Las rejillas, GeoTIFF propio; las
tablas, ``core.gpkg_layer@1``; ninguna editable en QGIS. La superficie de diseño lleva el papel
:data:`DESIGN_SURFACE_ROLE`, que reconoce la comprobación de congelar de la 012 (D-28).

**Ajustes** (:data:`ENVELOPE_SETTINGS`, :data:`DESIGN_SETTINGS`): lo que elige la persona en cada
operación, con las funciones que lo guardan y lo leen (:func:`envelope_settings`,
:func:`envelope_request`, :func:`design_settings`, :func:`design_request`): cada clave declarada
es la que se guarda. Ni la métrica ni el alcance son parámetros del proyecto.

**Entradas** (:func:`envelope_inputs`, :func:`design_inputs`) y **parámetros** que lee cada una
(:func:`envelope_params`, :func:`design_params`): una envolvente de pendiente constante no lee
ningún perfil; por sectores lee el talud general de los perfiles que usa (no su ancla); el
escalonado lee los cinco valores de cada perfil. Las dos leen el espesor mínimo de la 012.

**Cifras** (:data:`FIGURES`; RF-013-17): :func:`envelope_figures` y :func:`design_figures` las arman.
**Ninguna cifra es NaN ni infinita**: una que no existe (sin celdas con envolvente no hay cota
mínima ni máxima; sin celdas con movimiento no hay inclinación) no se registra, y un valor que no
es finito es un error del programa (``ValueError``).

**La cantera con dos superficies** (spec 014, T05; RF-014-16, RF-014-29; plan 014 §5.2.3) declara
lo suyo **aparte** de lo de la 013 (:data:`FAMILIES`, :data:`OPERATION_TYPES` y :data:`FIGURES`
son los que nombran la ficha y la guía de la 013; la 014 los documenta en su T36), con el prefijo
``QUARRY_`` como ``design.params.QUARRY_DEFINITIONS``:

- :data:`QUARRY_FAMILIES`: el recinto (``des_rcn_``), las dos superficies (``des_exp_`` y
  ``des_fin_``, papel ``design_surface``) y sus envolventes (``des_xen_`` y ``des_fen_``), la
  clasificación (``des_cls_``, GeoTIFF con los códigos de ``CellClass``; P-1), el informe de la
  cantera (``des_qrp_``), la transición (``des_trn_``) y su salto creado (``des_erp_``) y la
  superficie ajustada (``des_adj_``). :data:`FAMILIES_BY_CODE` tiene las de las dos specs, y
  :func:`dataset_name`, :func:`dataset_locator` y :func:`dataset_spec` valen para todas.
- :data:`QUARRY_OPERATION_TYPES`: cinco tipos de la versión, cada uno con su orden del catálogo
  (entrada «014»): ``des.excavation_area`` (:data:`EXCAVATION_AREA`), ``des.quarry``
  (:data:`QUARRY`), ``des.edge_transition`` (:data:`EDGE_TRANSITION`), ``des.fill_only``
  (:data:`FILL_ONLY`) y ``des.refit`` (:data:`REFIT`). Todos se repiten solos; se reproducen
  todos salvo el ajuste, que depende del límite vigente (:data:`QUARRY_REPRODUCIBLE`).
  :func:`quarry_operation_defs` los arma con las funciones de ``bl``.
- :data:`QUARRY_FIGURES`: las cifras de cada tipo (``OperationType.figures``); «solo relleno»
  registra además las del escalonado de la 013 (:data:`DESIGN_FIGURES`). Su ámbito,
  :func:`quarry_figure_scope`: el nombre de la operación, la superficie y el sector (plan 014
  §2.1: sin él, las de dos superficies o dos sectores se pisarían).
- La cantera (``des.quarry``, T19): sus ajustes (:func:`quarry_settings`, :func:`quarry_request`),
  lo que consume con sus papeles (:func:`quarry_inputs`, :func:`side_role` y los papeles de sus
  capas, :data:`FLOORS_LAYER_ROLE`…) y los parámetros que lee (:func:`quarry_params`,
  :func:`quarry_profiles`).
- La transición con el terreno no afectado (``des.edge_transition``, T28): sus ajustes
  (:func:`transition_settings`, :func:`transition_start`), lo que consume
  (:func:`transition_inputs`: la superficie de diseño con el papel :data:`DESIGN_SURFACE_ROLE`, la
  de partida y las máscaras) y los parámetros que lee (:data:`TRANSITION_PARAMS`).
- «Solo relleno…» (``des.fill_only``, T30): sus ajustes (:func:`fill_only_settings`,
  :func:`fill_only_request`; los del escalonado de la 013 sin el sentido, con la capa de láminas
  y su campo) y lo que consume (:func:`fill_only_inputs`: lo del escalonado y la capa de láminas,
  :data:`WATER_LAYER_ROLE`); los parámetros que lee son los del escalonado (:func:`design_params`).
- «Ajustar el diseño a un límite nuevo…» (``des.refit``, T32): sus ajustes (:func:`refit_settings`,
  :func:`refit_request`: el nombre, las superficies y la de partida; y, por superficie, la cara y
  el factor de malla con que se ajustó, los que anotó la operación que hizo su diseño, T49), el
  nombre de la salida de cada superficie (:func:`refit_output`, :func:`refit_part`,
  :func:`refit_source`), lo que consume (:func:`refit_inputs`: cada superficie con el papel
  :data:`DESIGN_SURFACE_ROLE`, la de partida, las máscaras y los sectores), los parámetros que lee
  del proyecto (:func:`refit_params`: el espesor mínimo; la cara y el factor de malla no se leen
  del perfil de hoy, P-3) y el ámbito de su cifra (:func:`refit_figure_scope`).

**Las entidades de diseño** (spec 015, T04; RF-015-01, RF-015-02; plan 015 §5.2.3; ADR-0030) declaran
lo suyo **aparte** de lo de las dos specs anteriores, con el prefijo ``ENTITY_``:

- :data:`ENTITY_FAMILIES`: la superficie de una entidad (``des_psf_``, papel
  :data:`ENTITY_SURFACE_ROLE`, **no** :data:`DESIGN_SURFACE_ROLE`: la última de cada cadena la añade
  congelar, T32), su tabla (``des_epr_``, :data:`ENTITY_ROLE`) y su informe (``des_prp_``) y, **una por
  versión** y sin el nombre de una operación (``DatasetFamily.named``), la tabla de las restricciones
  que declaran las entidades (``des_decl_<vNN>``) y la capa de entidades para QGIS
  (``des_enl_<vNN>``). :data:`FAMILIES_BY_CODE` tiene las de las tres specs.
- :data:`ENTITY_OPERATION_TYPES`: tres tipos de la versión, repetibles: ``des.platform``
  (:data:`PLATFORM`), ``des.declare_constraints`` (:data:`DECLARE_CONSTRAINTS`) y ``des.entity_layer``
  (:data:`ENTITY_LAYER`), con :func:`entity_operation_defs`; se reproducen los dos primeros
  (:data:`ENTITY_REPRODUCIBLE`): la capa de entidades **no** (T30: su contenido incluye el estado de cada
  entidad, que deduce el grafo del proyecto y no se reproduce sin él: es una vista regenerable, como
  ``des.refit``). «Soltar el apoyo» (T25) no es un tipo: es una ``des.platform`` repetida con ``supersedes``.
- La plataforma (``des.platform``): sus ajustes (:func:`platform_settings`, :func:`platform_request`:
  el nombre, el código y los campos de su capa; lo demás son los **parámetros** de la entidad,
  ``des.platform.{e}.*``, :func:`platform_values`), lo que consume con su papel
  (:func:`platform_inputs`: la capa, :data:`ENTITY_LAYER_ROLE`; la superficie de partida,
  :data:`SURFACE_ROLE`; las máscaras; y, añadidas al crear, las superficies de las entidades en las
  que se apoya, :data:`SUPPORTED_ON_ROLE`) y los parámetros que lee (:func:`platform_params`).
- La declaración (``des.declare_constraints``) y la capa (``des.entity_layer``) no tienen entradas de
  capas del proyecto: consumen los datos ``des_epr_`` de las entidades vivas (:data:`ENTITY_ROLE`;
  :func:`declare_inputs`, :func:`entity_layer_inputs`; la capa, además, su informe ``des_prp_``, de donde
  salen sus cifras, :data:`ENTITY_REPORT_ROLE`), con las entidades en sus ajustes
  (:func:`declare_settings`, :func:`entity_layer_settings`, :func:`settings_entities`) y, la
  declaración, los parámetros ``protect``, ``guard_m`` y ``reason`` (:func:`declare_params`). La
  declaración anota además en sus ajustes la versión (de ella sale el ``uid`` de cada restricción
  declarada, :func:`settings_version`) y, de cada entidad que declara, su decisor y la fecha de su
  decisión (:func:`settings_decisions`): sin proyecto, la reproducción no tiene otro sitio de donde
  sacarlos (T17).
- :data:`ENTITY_FIGURES`: las cifras de la plataforma (:data:`PLATFORM_FIGURES`), la de lo apoyado
  (:data:`SUPPORT_FIGURES`: ``des.supported_m3``, también de las operaciones de la 013 y la 014 que
  rellenan sobre una entidad) y la de la declaración (:data:`DECLARE_FIGURES`). Su ámbito
  (:func:`entity_figure_scope`) lleva el nombre de la operación y el **código de la entidad**
  (``entity``); las arman :func:`platform_figures`, :func:`supported_figures` y
  :func:`declare_figures`. La cota inicial y la final de la rasante son ``des.plat_start_level_m`` y
  ``des.plat_end_level_m`` (glosario §14: la pendiente de la rasante es «gradient»).

**Los cuatro tipos de entidad de la 016** (spec 016, T03; RF-016-02 a 22; plan 016 §2.1, §5.2.3; ADR-0031 §3) declaran lo
suyo **aparte**, con el prefijo ``SUPPORTED_`` y **sin comportamiento todavía** (las tareas siguientes crean cada
operación):

- :data:`SUPPORTED_FAMILIES`: ocho familias de datos, de la detección (``des_stk_``, la tabla de acopios, papel
  ``stockpiles``; ``des_stc_``, los candidatos; ``des_stb_``, la base de cada material; ``des_stt_``, su espesor;
  ``des_stg_``, el terreno sin acopios en las huellas; ``des_stp_``, la superficie con que se detectó) y del cuerpo bajo un
  techo (``des_bdt_``, su espesor; ``des_bds_``, su base), tablas y rejillas **dispersas**, cada una con su papel (por el
  que las leen la 011, la 012 y R-18 sin importar ``design``: ADR-0031 §3). Su nombre y su ubicación valen **en los dos
  ámbitos**: :func:`dataset_locator` con el código de la versión (``rasters/des_stb_<det>_<mat>_v02.tif``) o con ``None``
  si la detección es del proyecto (``rasters/des_stb_<det>_<mat>.tif``, D-15). :data:`FAMILIES_BY_CODE` las incluye.
- :data:`SUPPORTED_OPERATION_TYPES`: cinco tipos, repetibles y reproducibles (:data:`SUPPORTED_TYPES`,
  :data:`SUPPORTED_REPRODUCIBLE`): ``des.stockpile_detect`` (:data:`STOCKPILE_DETECT`), ``des.stockpile_detect_project``
  (:data:`STOCKPILE_DETECT_PROJECT`), ``des.stockpile_removal`` (:data:`STOCKPILE_REMOVAL`), ``des.buttress``
  (:data:`BUTTRESS`) y ``des.body`` (:data:`BODY`), con :func:`supported_operation_defs`. **La detección tiene dos tipos,
  uno por ámbito** (spec 016, T04; D-15, ADR-0031 §2; decisión de la sesión principal, 18/11/2026): ``OperationDef.scope``
  es uno por tipo (contrato de ``core``, spec 009), así que la detección **del proyecto** (sobre una superficie del
  proyecto) es ``des.stockpile_detect_project``, **de proyecto**, y la de una versión es ``des.stockpile_detect``, **de
  versión**: el mismo algoritmo, las mismas salidas, los mismos ajustes y cifras, las mismas familias de parámetros y el
  mismo escritor, parametrizado por ámbito (:class:`~.store.ProjectDesignWriter` junto a :class:`~.store.DesignWriter`).
  :data:`SUPPORTED_VERSION_TYPES` son los cuatro de versión y :data:`SUPPORTED_PROJECT_TYPES`, el de proyecto;
  :data:`STOCKPILE_DETECT_TYPES`, los dos de la detección.
- Los ajustes, lo que consume y los parámetros que lee cada tipo: :func:`stockpile_settings`, :func:`stockpile_request`,
  :func:`stockpile_inputs` y :func:`stockpile_params` y los homólogos de la retirada, el contrafuerte y el cuerpo; los
  valores de la entidad por su código, :func:`supported_values` y :func:`supported_code`. El umbral de la huella (011) y el
  espesor mínimo (012) se leen por su clave, no se copian.
- :data:`SUPPORTED_FIGURES`: las cifras de los cuatro tipos (:data:`STOCKPILE_FIGURES`, :data:`REMOVAL_FIGURES`,
  :data:`BUTTRESS_FIGURES` y :data:`BODY_FIGURES`), con el ámbito de las entidades (:func:`entity_figure_scope`) y, las
  de un acopio, **su clave y su material** (:func:`stockpile_figure_scope`: sin la clave, las de dos acopios se
  pisarían); las arman :func:`stockpile_figures`, :func:`removal_figures`, :func:`buttress_figures` y
  :func:`body_figures`.
"""

from __future__ import annotations

import math
import numbers
import sqlite3
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from ..core.constraints.store import SEARCH_TABLE, SECTOR_TABLE
from ..core.content.builtin import GPKG_LAYER
from ..core.content.encoder import ContentDigest
from ..core.datasets.model import DatasetSpec, Store
from ..core.provenance.contract import (
    FigureDef,
    OperationDef,
    RecomputeFunction,
    ReproduceFunction,
    SettingDef,
    Tolerance,
)
from ..core.provenance.figures import FigureRecord, FigureSpec
from ..core.provenance.operations import Use
from ..core.versions.model import version_locator
from ..gis.content import GEOTIFF
from ..gis.masks.provenance import SEARCHES_ROLE, SECTORS_ROLE
from ..gis.provenance import dataset_slug
from .model import (
    AnchorMode,
    BenchSense,
    BodyRequest,
    BodySense,
    ButtressFields,
    ButtressRequest,
    CorridorFields,
    DesignRequest,
    Direction,
    EnvelopeRequest,
    FillOnlyRequest,
    LayerField,
    Metric,
    Order,
    PlatformFields,
    PlatformRequest,
    QuarryRequest,
    QuarrySide,
    RefitRequest,
    RemovalRequest,
    SeedKind,
    SeedSource,
    SlopeMode,
    StockpileFields,
    StockpileRequest,
    Surface,
    ToFinalMode,
    WorkDomain,
    Zone,
    ZoneKind,
)
from .params import (
    ANTHROPIC_PRESENCE,
    CONSERVE_SLOPE,
    CROWN_RING,
    EDGE_MAX_STEP,
    EDGE_MIN_SHARE,
    PLATFORM_PREFIX,
    TOLERANCE_FACE,
    UNSPLIT_MIN_AREA,
    UNSPLIT_THRESHOLD,
    VERIFY_MIN_THICKNESS,
    WARNING_RATIO,
    BenchParam,
    BodyParam,
    ButtressParam,
    PlatformParam,
    RemovalParam,
    StockpileParam,
    bench_key,
    entity_key,
    entity_params_of,
    entity_segment,
)
from .params import EDGE_TRANSITION as EDGE_TRANSITION_DEG

if TYPE_CHECKING:  # solo para los tipos: importar el informe arrastraría los cálculos
    from .report import DesignReport

__all__ = [
    "ANCHORS_ROLE",
    "AREA_FIGURES",
    "BERMS_GRID",
    "BERM_TABLE",
    "BODY",
    "BODY_BASE_GRID",
    "BODY_BASE_ROLE",
    "BODY_COMMAND",
    "BODY_DATA_ROLE",
    "BODY_FIGURES",
    "BODY_THICKNESS_GRID",
    "BODY_THICKNESS_ROLE",
    "BUTTRESS",
    "BUTTRESS_COMMAND",
    "BUTTRESS_FIGURES",
    "CLASSIFICATION_GRID",
    "CLASSIFICATION_ROLE",
    "COMMAND",
    "CONSERVE_LAYER_ROLE",
    "CORRIDORS_LAYER_ROLE",
    "CREATED_STEP_PARAMS",
    "CROWN_SEEDS",
    "CUT_M3",
    "DECLARED_COUNT",
    "DECLARED_ROLE",
    "DECLARED_TABLE",
    "DECLARE_CONSTRAINTS",
    "DECLARE_FIGURES",
    "DESIGN_FIGURES",
    "DESIGN_GRID",
    "DESIGN_SETTINGS",
    "DESIGN_SURFACE_ROLE",
    "DOMAIN_LAYER_ROLE",
    "EDGE_REPORT_ROLE",
    "EDGE_REPORT_TABLE",
    "EDGE_TRANSITION",
    "ENTITY_AXIS_LAYER_ROLE",
    "ENTITY_FAMILIES",
    "ENTITY_FIGURES",
    "ENTITY_LAYER",
    "ENTITY_LAYER_ROLE",
    "ENTITY_MAP_ROLE",
    "COUNTERSLOPE_CONFIRMED",
    "ENTITY_MAP_TABLE",
    "ENTITY_OPERATION_TYPES",
    "ENTITY_REPORT_ROLE",
    "ENTITY_REPORT_TABLE",
    "ENTITY_REPRODUCIBLE",
    "ENTITY_ROLE",
    "ENTITY_SCOPE_KEY",
    "ENTITY_SURFACE_GRID",
    "ENTITY_SURFACE_ROLE",
    "ENTITY_TABLE",
    "ENTITY_VERSION_TYPES",
    "ENVELOPE",
    "ENVELOPE_FIGURES",
    "ENVELOPE_GRID",
    "ENVELOPE_PROFILE_PARAMS",
    "ENVELOPE_ROLE",
    "ENVELOPE_SETTINGS",
    "EXCAVATION_AREA",
    "EXCAVATION_AREA_GRID",
    "EXCAVATION_AREA_ROLE",
    "EXPLOITATION_ENVELOPE_GRID",
    "EXPLOITATION_ENVELOPE_ROLE",
    "EXPLOITATION_GRID",
    "FAMILIES",
    "FAMILIES_BY_CODE",
    "FIGURES",
    "FIGURE_SCOPE_KEY",
    "FIGURE_TOLERANCE",
    "FILL_LAYER_ROLE",
    "FILL_M3",
    "FILL_ONLY",
    "FILL_ONLY_COMMAND",
    "FILL_ONLY_FIGURES",
    "FILL_ONLY_SETTINGS",
    "FINAL_ENVELOPE_GRID",
    "FINAL_ENVELOPE_ROLE",
    "FINAL_GRID",
    "FLOORS_LAYER_ROLE",
    "LIMIT_COMMAND",
    "MARKS_LAYER_ROLE",
    "MATERIAL_SCOPE_KEY",
    "MODULE",
    "OPERATION_TYPES",
    "OPERATION_TYPES_BY_NAME",
    "OP_VERSION",
    "PLATFORM",
    "PLATFORM_COMMAND",
    "PLATFORM_COMMON_PARAMS",
    "PLATFORM_FIGURES",
    "PLATFORM_SETTINGS",
    "CounterslopeConfirmation",
    "ReleasedSupport",
    "QUARRY",
    "QUARRY_COMMAND",
    "QUARRY_FAMILIES",
    "QUARRY_FIGURES",
    "QUARRY_OPERATION_TYPES",
    "QUARRY_REPORT_ROLE",
    "QUARRY_REPORT_TABLE",
    "QUARRY_REPRODUCIBLE",
    "QUARRY_SETTINGS",
    "QUARRY_VERSION_TYPES",
    "REFIT",
    "REFIT_COMMAND",
    "REFIT_FIGURES",
    "REFIT_GRID",
    "REFIT_PROFILE_PARAMS",
    "REMOVAL_COMMAND",
    "REMOVAL_FIGURES",
    "REMOVED_STOCKPILE_ROLE",
    "REPORT_TABLE",
    "REPRODUCIBLE",
    "SEARCHES_ROLE",
    "SECTORS_ROLE",
    "SECTOR_SCOPE_KEY",
    "SEEDS_GRID_ROLE",
    "STEPPED",
    "STOCKPILES_ROLE",
    "STOCKPILES_TABLE",
    "STOCKPILE_BASE_GRID",
    "STOCKPILE_BASE_ROLE",
    "STOCKPILE_CANDIDATES_ROLE",
    "STOCKPILE_CANDIDATES_TABLE",
    "STOCKPILE_COMMAND",
    "STOCKPILE_DETECT",
    "STOCKPILE_DETECT_PROJECT",
    "STOCKPILE_DETECT_TYPES",
    "STOCKPILE_FIGURES",
    "STOCKPILE_GROUND_GRID",
    "STOCKPILE_GROUND_ROLE",
    "STOCKPILE_REMOVAL",
    "STOCKPILE_SCOPE_KEY",
    "STOCKPILE_SURFACE_GRID",
    "STOCKPILE_SURFACE_ROLE",
    "STOCKPILE_THICKNESS_GRID",
    "STOCKPILE_THICKNESS_ROLE",
    "SUPPORTED_FAMILIES",
    "SUPPORTED_FIGURES",
    "SUPPORTED_M3",
    "SUPPORTED_ON_ROLE",
    "SUPPORTED_OPERATION_TYPES",
    "SUPPORTED_PROJECT_TYPES",
    "SUPPORTED_REPRODUCIBLE",
    "SUPPORTED_TYPES",
    "SUPPORTED_VERSION_TYPES",
    "SUPPORT_FIGURES",
    "SUPPORT_FOOTPRINT_ROLE",
    "SUPPORT_REF_SEPARATOR",
    "SUPPORTS_RELEASED",
    "SURFACE_ROLE",
    "SURFACE_SCOPE_KEY",
    "SURFACE_SCOPE_NAMES",
    "TO_FINAL_LAYER_ROLE",
    "TRANSITIONS_COMMAND",
    "TRANSITION_FIGURES",
    "TRANSITION_GRID",
    "TRANSITION_PARAMS",
    "TWO_SURFACES_FIGURES",
    "VERSION_TYPES",
    "WATER_LAYER_ROLE",
    "ZONE_LAYER_ROLE",
    "DatasetFamily",
    "OperationType",
    "StockpileFigures",
    "body_figures",
    "body_inputs",
    "body_params",
    "body_request",
    "body_settings",
    "buttress_figures",
    "buttress_inputs",
    "buttress_params",
    "buttress_request",
    "buttress_settings",
    "dataset_locator",
    "dataset_name",
    "dataset_spec",
    "declare_figures",
    "declare_inputs",
    "declare_params",
    "declare_settings",
    "design_figures",
    "design_inputs",
    "design_params",
    "design_request",
    "design_settings",
    "design_start",
    "entity_figure_scope",
    "entity_layer_inputs",
    "entity_layer_settings",
    "entity_operation_defs",
    "envelope_figures",
    "envelope_inputs",
    "envelope_params",
    "envelope_request",
    "envelope_settings",
    "excavation_area_inputs",
    "excavation_area_settings",
    "excavation_area_start",
    "figure_scope",
    "figure_text",
    "fill_only_inputs",
    "fill_only_request",
    "fill_only_settings",
    "counterslope_confirmation",
    "counterslope_confirmed",
    "has_platform_operation",
    "merge_released",
    "released_supports",
    "operation_def",
    "operation_defs",
    "platform_code",
    "platform_figures",
    "platform_inputs",
    "platform_params",
    "platform_request",
    "platform_settings",
    "platform_values",
    "profile_params",
    "quarry_figure_scope",
    "quarry_inputs",
    "quarry_operation_defs",
    "quarry_params",
    "quarry_profiles",
    "quarry_request",
    "quarry_settings",
    "refit_figure_scope",
    "refit_inputs",
    "refit_output",
    "refit_params",
    "refit_part",
    "refit_request",
    "refit_settings",
    "refit_source",
    "removal_figures",
    "removal_inputs",
    "removal_params",
    "removal_request",
    "removal_settings",
    "sector_inputs",
    "settings_decisions",
    "settings_entities",
    "side_role",
    "settings_pending",
    "settings_previous",
    "settings_touched",
    "settings_version",
    "stockpile_figure_scope",
    "stockpile_figures",
    "stockpile_inputs",
    "stockpile_params",
    "stockpile_request",
    "stockpile_settings",
    "split_support_ref",
    "support_ref",
    "supported_code",
    "supported_figures",
    "supported_operation_defs",
    "supported_values",
    "transition_inputs",
    "transition_settings",
    "transition_start",
]

MODULE = "des"
"""El código del diseño (``core.catalog.schema.MODULE_CODES``)."""
OP_VERSION = "1.0"
"""La versión inicial del algoritmo de cada tipo (sube cuando un cambio puede mover una cifra,
RF-008-24)."""
FIGURE_TOLERANCE = Tolerance(relative=1e-9)
"""La tolerancia de las cifras al reproducir (plan §5.2.3): con el mismo Geoblender y numpy salen
bit a bit; con otro numpy, el último bit puede cambiar."""

ENVELOPE = "des.envelope"
STEPPED = "des.stepped_design"
COMMAND = "geoblender.des_compute_envelope"
"""La orden del catálogo que lanza las dos: «Envolventes y escalonado…» (D-26: encadena el
escalonado si se pide «Escalonar»)."""

# --- Familias de datos y papeles ----------------------------------------------------------------

ENVELOPE_GRID = "env"
"""La rejilla de una envolvente (``rasters/des_env_<nombre>_<vNN>.tif``)."""
DESIGN_GRID = "srf"
"""La superficie de diseño (``rasters/des_srf_<nombre>_<vNN>.tif``)."""
BERMS_GRID = "brm"
"""La cota real de las bermas (``rasters/des_brm_<nombre>_<vNN>.tif``)."""
BERM_TABLE = "bmt"
"""La tabla de bermas por sector, perfil y cota (``des_bmt_<nombre>_<vNN>``)."""
REPORT_TABLE = "rpt"
"""El informe del diseño en formato largo (``des_rpt_<nombre>_<vNN>``)."""

ENVELOPE_ROLE = "envelope"
"""El papel de la rejilla de una envolvente: salida de ``des.envelope`` y entrada de
``des.stepped_design``."""
DESIGN_SURFACE_ROLE = "design_surface"
"""El papel de la superficie de diseño: lo que reconoce la comprobación de congelar de la 012
(``reserves.compliance_store.freeze_findings``; RF-013-31, D-28)."""
ENTITY_SURFACE_ROLE = "entity_surface"
"""El papel de la superficie que deja una entidad de diseño (spec 015, T04; plan 015 §5.2.3): **no**
cuenta como :data:`DESIGN_SURFACE_ROLE`. Las superficies intermedias de una cadena de entidades son
superficies de trabajo (P-2); la última de cada cadena (``design.entities.chain_tails``) es la de
diseño para congelar, y la comprobación de congelar la pide aparte (T32)."""
_BERMS_ROLE = "berms"
_BERM_TABLE_ROLE = "berm_table"
_REPORT_ROLE = "report"

SURFACE_ROLE = "surface"
"""El papel de la superficie de partida (las semillas salen de ella o es la que se compara)."""
SEEDS_GRID_ROLE = "seeds_grid"
"""El papel de la rejilla de cotas de las semillas."""
ZONE_LAYER_ROLE = "zone_layer"
"""El papel de la capa de polígonos que da la zona de las semillas."""
DOMAIN_LAYER_ROLE = "domain_layer"
"""El papel de la capa de polígonos que acota el dominio de trabajo."""
ANCHORS_ROLE = "anchors"
"""El papel de la rejilla de anclas del escalonado."""

_PREFIX = f"{MODULE}_"

# Los papeles de las entidades de diseño (spec 015, T04; plan 015 §5.2.3). Los de consumo de la
# plataforma son los de lo que lee: la capa de las plataformas, la superficie de la que parte
# (:data:`SURFACE_ROLE`, el de siempre), aquellas en las que se apoya y los datos de las entidades
# vivas; los demás, el papel con que sale cada dato de las familias de las entidades.
ENTITY_LAYER_ROLE = "entity_layer"
"""El papel de la capa de plataformas (la geometría y los valores iniciales de una entidad) que
consume ``des.platform``: líneas con ancho, o polígonos."""
ENTITY_AXIS_LAYER_ROLE = "entity_axis_layer"
"""El papel de la capa de líneas con el eje que enlaza un polígono (``PlatformFields.axis_layer``);
solo si el polígono lo enlaza."""
SUPPORTED_ON_ROLE = "supported_on"
"""El papel de la superficie de una entidad en la que se apoya la operación que rellena sobre ella
(RF-015-15; ADR-0030 §4): las que detecta el cálculo y las que declara el usuario, añadidas al crear
(una operación hecha es inmutable). Si ese dato se descarta, «apoyo retirado» (RF-015-17)."""
SUPPORT_FOOTPRINT_ROLE = "support_footprint"
"""El papel de la tabla ``des_epr_`` de la entidad en la que se apoya una operación (spec 015, T23): su
huella, con la que se mide el volumen apoyado (``des.supported_m3``). Va **junto a** cada entrada
:data:`SUPPORTED_ON_ROLE` de una entidad, para que lo apoyado se reproduzca sin el proyecto (la
reproducción no tiene otro sitio de donde sacar la huella) y se vigile como cualquier entrada."""
ENTITY_ROLE = "entity"
"""El papel de la tabla de una entidad (huella, eje y atributos): salida de ``des.platform`` y
entrada de la declaración y de la capa de entidades, que recogen las entidades vivas."""
ENTITY_REPORT_ROLE = "entity_report"
"""El papel del informe de una entidad (avisos, perfil, contrapendientes, borde)."""
DECLARED_ROLE = "constraints_declared"
"""El papel de la tabla de las restricciones que declaran las entidades: la salida de
``des.declare_constraints`` y, con el mismo texto, lo que consume la compilación de la 012 (T18)."""
ENTITY_MAP_ROLE = "entity_map"
"""El papel de la capa de entidades que se abre en QGIS (``des.entity_layer``)."""

# Los papeles de los cuatro tipos de la 016 (spec 016, T03; plan 016 §5.2.3; ADR-0031 §3): los de lo que producen la
# detección y el cuerpo bajo un techo, por los que leen sus datos la 011, la 012 y R-18 sin importar ``design``, y los
# de lo que consumen.
STOCKPILES_ROLE = "stockpiles"
"""El papel de la tabla de acopios de una detección (``des_stk_``: la clave, el nombre, el material, el plano, la huella
en tramos, el área, el volumen, el espesor máximo, las notas y los avisos de cada acopio)."""
STOCKPILE_CANDIDATES_ROLE = "stockpile_candidates"
"""El papel de la tabla de candidatos sin marca de una detección y su estado (``des_stc_``)."""
STOCKPILE_BASE_ROLE = "stockpile_base"
"""El papel de la base de los acopios de **un material** (``des_stb_``): la base (m) de la unidad antrópica que toma la
011 (RF-011-14) y la que lee la verificación de la 012 (RF-012-30). Dispersa: sin dato fuera de las huellas."""
STOCKPILE_THICKNESS_ROLE = "stockpile_thickness"
"""El papel del espesor de los acopios de **un material** (``des_stt_``; m, ≥ 0: RF-016-01): la rejilla de espesores de
su unidad antrópica en la 011. Dispersa."""
STOCKPILE_GROUND_ROLE = "stockpile_ground"
"""El papel del terreno sin acopios **en las huellas** (``des_stg_``: el menor de la superficie detectada y de la base;
P-5): fuera de ellas es la superficie de la que parte la detección. De él compone R-18 el terreno in situ (D-22)."""
STOCKPILE_SURFACE_ROLE = "stockpile_surface"
"""El papel de la superficie con que se detectó, en las huellas (``des_stp_``): **sobre la que se apoya** lo que
rellena encima (RF-015-15), con el contrato de ``entity_surface`` sin ser una superficie de diseño ni de una cadena."""
BODY_THICKNESS_ROLE = "body_thickness"
"""El papel del espesor de un cuerpo apoyado (``des_bdt_``; m, ≥ 0), disperso."""
BODY_BASE_ROLE = "body_base"
"""El papel de la base de un cuerpo «bajo un techo» (``des_bds_``), dispersa: el techo menos el espesor."""
MARKS_LAYER_ROLE = "marks_layer"
"""El papel de la capa de marcas de acopios que consume ``des.stockpile_detect`` (polígonos; su geometría y su hash: un
cambio de geometría en QGIS deja obsoleta la detección, uno de un campo no, P-3 de la 015)."""
REMOVED_STOCKPILE_ROLE = "removed_stockpile"
"""El papel del acopio que retira ``des.stockpile_removal``: su tabla (``des_stk_``) y su base (``des_stb_``). Si una
retirada viva lo consume, el dato del acopio cuenta como retirado para lo que se apoyaba en él (P-9, «apoyo
retirado»)."""
BODY_DATA_ROLE = "body_data"
"""El papel de la capa con los datos de espesor que consume ``des.body`` (puntos, líneas 3D o polígonos)."""


@dataclass(frozen=True, slots=True)
class DatasetFamily:
    """Una familia de datos de ``des`` (plan §5.2.3): su código (``env``), su tipo y su almacén,
    su lector (con versión), su papel de salida, la extensión de su fichero (``""`` en una tabla)
    y su nombre visible. ``named``: si cada operación tiene su dato (``des_env_<nombre>``: la
    mayoría) o es **uno por versión** (``des_decl_<vNN>``, ``des_enl_<vNN>``: sin el nombre de una
    operación, como las máscaras de la 012); en una así, el nombre del dato es la raíz sin el último
    «_» (``des_decl``) y su ubicación lleva el código de la versión."""

    code: str
    kind: str
    store: Store
    reader: str
    role: str
    extension: str
    label: str
    named: bool = True

    @property
    def prefix(self) -> str:
        """El comienzo del nombre de sus datos: ``des_<código>_``."""
        return f"{_PREFIX}{self.code}_"


FAMILIES: tuple[DatasetFamily, ...] = (
    DatasetFamily(ENVELOPE_GRID, "raster", Store.RASTERS, GEOTIFF.id, ENVELOPE_ROLE, ".tif",
                  "Envolvente"),
    DatasetFamily(DESIGN_GRID, "raster", Store.RASTERS, GEOTIFF.id, DESIGN_SURFACE_ROLE, ".tif",
                  "Superficie de diseño"),
    DatasetFamily(BERMS_GRID, "raster", Store.RASTERS, GEOTIFF.id, _BERMS_ROLE, ".tif",
                  "Cota real de las bermas"),
    DatasetFamily(BERM_TABLE, "table", Store.GPKG, GPKG_LAYER.id, _BERM_TABLE_ROLE, "",
                  "Bermas por sector, perfil y cota"),
    DatasetFamily(REPORT_TABLE, "table", Store.GPKG, GPKG_LAYER.id, _REPORT_ROLE, "",
                  "Informe del diseño"),
)
"""Las familias de datos de la versión de la 013 (plan 013 §5.2.3)."""

# Las de la cantera con dos superficies (spec 014, T05; plan 014 §5.2.3).
EXCAVATION_AREA_GRID = "rcn"
"""El recinto excavable: 1 dentro, sin dato fuera (``rasters/des_rcn_<nombre>_<vNN>.tif``)."""
EXPLOITATION_GRID = "exp"
"""La superficie de explotación (``rasters/des_exp_<nombre>_<vNN>.tif``)."""
FINAL_GRID = "fin"
"""La superficie final (``rasters/des_fin_<nombre>_<vNN>.tif``)."""
EXPLOITATION_ENVELOPE_GRID = "xen"
"""La envolvente de la superficie de explotación."""
FINAL_ENVELOPE_GRID = "fen"
"""La envolvente de la superficie final."""
CLASSIFICATION_GRID = "cls"
"""La clasificación de las dos superficies: GeoTIFF Float32 con el código de ``CellClass`` (0 sin
diferencia, 1 desdoblado, 2 relleno) y sin dato fuera del dominio (P-1)."""
QUARRY_REPORT_TABLE = "qrp"
"""El informe de la cantera en formato largo, como ``des_rpt_`` (``des_qrp_<nombre>_<vNN>``)."""
TRANSITION_GRID = "trn"
"""La superficie con la transición al terreno no afectado (RF-014-19)."""
EDGE_REPORT_TABLE = "erp"
"""El informe del salto creado en el borde: parejas, porcentaje y tramos (RF-014-20, RF-014-21)."""
REFIT_GRID = "adj"
"""Una superficie ajustada a un límite nuevo (``des_adj_<nombre>_<superficie>_<vNN>``; RF-014-27)."""

EXCAVATION_AREA_ROLE = "excavation_area"
"""El papel del recinto excavable."""
EXPLOITATION_ENVELOPE_ROLE = "exploitation_envelope"
"""El papel de la envolvente de la explotación."""
FINAL_ENVELOPE_ROLE = "final_envelope"
"""El papel de la envolvente de la final."""
CLASSIFICATION_ROLE = "classification"
"""El papel de la clasificación de las dos superficies."""
QUARRY_REPORT_ROLE = "quarry_report"
"""El papel del informe de la cantera."""
EDGE_REPORT_ROLE = "edge_report"
"""El papel del informe del salto creado."""

FLOORS_LAYER_ROLE = "floors_layer"
"""El papel de la capa de polígonos de los fondos de la cantera (RF-014-05)."""
CONSERVE_LAYER_ROLE = "conserve_layer"
"""El papel de cada capa de polígonos de las zonas a conservar (RF-014-07)."""
CORRIDORS_LAYER_ROLE = "corridors_layer"
"""El papel de la capa de líneas de los corredores (RF-014-09)."""
FILL_LAYER_ROLE = "fill_layer"
"""El papel de la capa de las zonas de restauración por relleno (RF-014-15, D-11)."""
TO_FINAL_LAYER_ROLE = "to_final_layer"
"""El papel de la capa de las zonas de «explotación hasta la final» (RF-014-18, P-2)."""
WATER_LAYER_ROLE = "water_layer"
"""El papel de la capa de polígonos de las láminas de agua de «Solo relleno…» (RF-014-24, D-10;
T30)."""

QUARRY_FAMILIES: tuple[DatasetFamily, ...] = (
    DatasetFamily(EXCAVATION_AREA_GRID, "raster", Store.RASTERS, GEOTIFF.id, EXCAVATION_AREA_ROLE,
                  ".tif", "Recinto excavable"),
    DatasetFamily(EXPLOITATION_GRID, "raster", Store.RASTERS, GEOTIFF.id, DESIGN_SURFACE_ROLE,
                  ".tif", "Superficie de explotación"),
    DatasetFamily(FINAL_GRID, "raster", Store.RASTERS, GEOTIFF.id, DESIGN_SURFACE_ROLE, ".tif",
                  "Superficie final"),
    DatasetFamily(EXPLOITATION_ENVELOPE_GRID, "raster", Store.RASTERS, GEOTIFF.id,
                  EXPLOITATION_ENVELOPE_ROLE, ".tif", "Envolvente de la explotación"),
    DatasetFamily(FINAL_ENVELOPE_GRID, "raster", Store.RASTERS, GEOTIFF.id, FINAL_ENVELOPE_ROLE,
                  ".tif", "Envolvente de la final"),
    DatasetFamily(CLASSIFICATION_GRID, "raster", Store.RASTERS, GEOTIFF.id, CLASSIFICATION_ROLE,
                  ".tif", "Clasificación de las dos superficies"),
    DatasetFamily(QUARRY_REPORT_TABLE, "table", Store.GPKG, GPKG_LAYER.id, QUARRY_REPORT_ROLE, "",
                  "Informe de la cantera"),
    DatasetFamily(TRANSITION_GRID, "raster", Store.RASTERS, GEOTIFF.id, DESIGN_SURFACE_ROLE,
                  ".tif", "Transición con el terreno no afectado"),
    DatasetFamily(EDGE_REPORT_TABLE, "table", Store.GPKG, GPKG_LAYER.id, EDGE_REPORT_ROLE, "",
                  "Salto creado en el borde"),
    DatasetFamily(REFIT_GRID, "raster", Store.RASTERS, GEOTIFF.id, DESIGN_SURFACE_ROLE, ".tif",
                  "Superficie ajustada a un límite nuevo"),
)
"""Las familias de datos de la versión de la 014 (plan 014 §5.2.3), aparte de las de la 013. Las
cuatro superficies que se pueden congelar (las dos de la cantera, la transición y la ajustada)
llevan :data:`DESIGN_SURFACE_ROLE`: congelar pide verificarlas por recinto (D-28 de la 013)."""

# Las de las entidades de diseño (spec 015, T04; plan 015 §5.2.3).
ENTITY_SURFACE_GRID = "psf"
"""La superficie que deja una entidad (``rasters/des_psf_<nombre>_<vNN>.tif``, GeoTIFF Float64;
papel :data:`ENTITY_SURFACE_ROLE`)."""
ENTITY_TABLE = "epr"
"""La tabla de una entidad: su huella, su eje y sus atributos (``des_epr_<nombre>_<vNN>``)."""
ENTITY_REPORT_TABLE = "prp"
"""El informe de una entidad en formato largo: avisos, perfil, contrapendientes y el borde
(``des_prp_<nombre>_<vNN>``)."""
DECLARED_TABLE = "decl"
"""La tabla de las restricciones que declaran las entidades de la versión (``des_decl_<vNN>``): una
capa de polígonos no editable a mano (RF-008-56) que consume la compilación de la 012."""
ENTITY_MAP_TABLE = "enl"
"""La capa de entidades de la versión para QGIS (``des_enl_<vNN>``): sus huellas con su tipo, su
nombre, su estado, su apoyo, su cadena y sus cifras principales; no editable a mano."""

ENTITY_FAMILIES: tuple[DatasetFamily, ...] = (
    DatasetFamily(ENTITY_SURFACE_GRID, "raster", Store.RASTERS, GEOTIFF.id, ENTITY_SURFACE_ROLE,
                  ".tif", "Superficie de la entidad"),
    DatasetFamily(ENTITY_TABLE, "table", Store.GPKG, GPKG_LAYER.id, ENTITY_ROLE, "",
                  "Huella, eje y atributos de la entidad"),
    DatasetFamily(ENTITY_REPORT_TABLE, "table", Store.GPKG, GPKG_LAYER.id, ENTITY_REPORT_ROLE, "",
                  "Informe de la entidad"),
    DatasetFamily(DECLARED_TABLE, "vector", Store.GPKG, GPKG_LAYER.id, DECLARED_ROLE, "",
                  "Restricciones declaradas por las entidades", named=False),
    DatasetFamily(ENTITY_MAP_TABLE, "vector", Store.GPKG, GPKG_LAYER.id, ENTITY_MAP_ROLE, "",
                  "Capa de entidades", named=False),
)
"""Las familias de datos de la versión de la 015 (plan 015 §5.2.3), aparte de las de la 013 y la 014.
La superficie de una entidad lleva :data:`ENTITY_SURFACE_ROLE` y **no** :data:`DESIGN_SURFACE_ROLE`:
las de una cadena son de trabajo, y la última la añade congelar (P-2, T32). La tabla de la entidad es
una tabla (``table``: su huella y su eje van como columnas); las de las restricciones declaradas y la
capa de entidades son capas (``vector``) para QGIS, una por versión."""
# Las de la detección de acopios y el cuerpo bajo un techo (spec 016, T03; plan 016 §5.2.3; ADR-0031 §3; P-4, P-5).
STOCKPILES_TABLE = "stk"
"""La tabla de acopios de una detección (``des_stk_<detección>``; papel :data:`STOCKPILES_ROLE`)."""
STOCKPILE_CANDIDATES_TABLE = "stc"
"""La tabla de candidatos sin marca y su estado (``des_stc_<detección>``)."""
STOCKPILE_BASE_GRID = "stb"
"""La base de los acopios de un material, dispersa (``rasters/des_stb_<detección>_<material>[_<vNN>].tif``)."""
STOCKPILE_THICKNESS_GRID = "stt"
"""El espesor de los acopios de un material, disperso (``des_stt_<detección>_<material>``)."""
STOCKPILE_GROUND_GRID = "stg"
"""El terreno sin acopios, solo en las huellas (``des_stg_<detección>``; P-5)."""
STOCKPILE_SURFACE_GRID = "stp"
"""La superficie con que se detectó, solo en las huellas (``des_stp_<detección>``)."""
BODY_THICKNESS_GRID = "bdt"
"""El espesor de un cuerpo apoyado, disperso (``des_bdt_<cuerpo>``)."""
BODY_BASE_GRID = "bds"
"""La base de un cuerpo «bajo un techo», dispersa (``des_bds_<cuerpo>``)."""

SUPPORTED_FAMILIES: tuple[DatasetFamily, ...] = (
    DatasetFamily(STOCKPILES_TABLE, "table", Store.GPKG, GPKG_LAYER.id, STOCKPILES_ROLE, "",
                  "Tabla de acopios"),
    DatasetFamily(STOCKPILE_CANDIDATES_TABLE, "table", Store.GPKG, GPKG_LAYER.id, STOCKPILE_CANDIDATES_ROLE, "",
                  "Candidatos sin marca y su estado"),
    DatasetFamily(STOCKPILE_BASE_GRID, "raster", Store.RASTERS, GEOTIFF.id, STOCKPILE_BASE_ROLE, ".tif",
                  "Base de los acopios de un material"),
    DatasetFamily(STOCKPILE_THICKNESS_GRID, "raster", Store.RASTERS, GEOTIFF.id, STOCKPILE_THICKNESS_ROLE, ".tif",
                  "Espesor de los acopios de un material"),
    DatasetFamily(STOCKPILE_GROUND_GRID, "raster", Store.RASTERS, GEOTIFF.id, STOCKPILE_GROUND_ROLE, ".tif",
                  "Terreno sin acopios en sus huellas"),
    DatasetFamily(STOCKPILE_SURFACE_GRID, "raster", Store.RASTERS, GEOTIFF.id, STOCKPILE_SURFACE_ROLE, ".tif",
                  "Superficie con que se detectaron los acopios, en sus huellas"),
    DatasetFamily(BODY_THICKNESS_GRID, "raster", Store.RASTERS, GEOTIFF.id, BODY_THICKNESS_ROLE, ".tif",
                  "Espesor de un cuerpo apoyado"),
    DatasetFamily(BODY_BASE_GRID, "raster", Store.RASTERS, GEOTIFF.id, BODY_BASE_ROLE, ".tif",
                  "Base de un cuerpo bajo un techo"),
)
"""Las familias de datos de la detección de acopios y del cuerpo bajo un techo (plan 016 §5.2.3), aparte de las de las
tres specs anteriores. **Dispersas** (sin dato fuera de las huellas: 0,4 MiB frente a 15,1 MiB enteras, P-4) y cada una
con su papel, por el que las leen la 011, la 012 y R-18 (ADR-0031 §3); ninguna lleva el papel de una superficie de
diseño. Su nombre y su ubicación valen en los dos ámbitos de la detección, del proyecto o de la versión (D-15; véase
:func:`dataset_locator`)."""
FAMILIES_BY_CODE: Mapping[str, DatasetFamily] = MappingProxyType(
    {family.code: family
     for family in (*FAMILIES, *QUARRY_FAMILIES, *ENTITY_FAMILIES, *SUPPORTED_FAMILIES)})
"""Las familias de las cuatro specs por código (solo lectura)."""
if len(FAMILIES_BY_CODE) != (len(FAMILIES) + len(QUARRY_FAMILIES) + len(ENTITY_FAMILIES)
                              + len(SUPPORTED_FAMILIES)):
    raise RuntimeError("dos familias de datos del diseño con el mismo código")  # pragma: no cover


def _family(code: object) -> DatasetFamily:
    found = FAMILIES_BY_CODE.get(code) if isinstance(code, str) else None
    if found is None:
        raise ValueError(f"{code!r} no es una familia de datos del diseño: es una de "
                         f"{', '.join(FAMILIES_BY_CODE)}")
    return found


def dataset_name(family: str, name: str = "") -> str:
    """El nombre estable del dato de la familia ``family`` de la operación ``name``:
    ``des_<familia>_<nombre>`` (el nombre en ASCII en minúsculas, ``gis.provenance.dataset_slug``:
    el mismo nombre da el mismo dato). Una familia **sin nombre** (``DatasetFamily.named`` falso:
    ``des_decl_<vNN>``, ``des_enl_<vNN>``) es una por versión y se llama ``des_<familia>``: no lleva
    ``name`` (``ValueError`` si se lo dan). ``GisError`` ``gis.dataset_name_invalid`` si no queda
    ninguna letra ni cifra; ``ValueError`` si la familia no es de ``des``."""
    found = _family(family)
    if not found.named:
        if name not in ("", None):
            raise ValueError(f"los datos de la familia «{found.code}» son uno por versión: no "
                             f"llevan el nombre de una operación, no {name!r}")
        return found.prefix.rstrip("_")
    return found.prefix + dataset_slug(name)


def dataset_locator(family: str, name: str, version_code: str | None) -> str:
    """La ubicación del dato de la familia ``family`` de la operación ``name`` en la versión
    ``version_code`` («V03»): la tabla (``des_bmt_<nombre>_v03``) o la ruta en su almacén
    (``rasters/des_srf_<nombre>_v03.tif``; D-34 de la 009). Con una familia sin nombre
    (``des_decl_v03``), ``name`` es ``""``.

    ``version_code`` ``None`` (spec 016, T03; ADR-0031 §2; D-15): el dato **del proyecto**, sin código de versión
    (``des_stk_<nombre>``, ``rasters/des_stb_<nombre>.tif``): el de una detección de acopios sobre una superficie del
    proyecto, que lee R-18 sin consumir un dato de versión (RF-009-05). Es el mismo dato, el mismo nombre y las mismas
    familias; solo cambia dónde se escribe."""
    found = _family(family)
    base = dataset_name(family, name)
    if found.store is Store.GPKG:
        return base if version_code is None else version_locator(base, version_code)
    locator = f"{found.store}/{base}{found.extension}"
    return locator if version_code is None else version_locator(locator, version_code)


def dataset_spec(family: str, name: str, version_code: str | None, *,
                 content: ContentDigest | None = None,
                 crs_epsg: int | None = None) -> DatasetSpec:
    """La ``DatasetSpec`` del dato de la familia ``family`` de la operación ``name`` en la
    versión ``version_code`` (RF-008-17, RF-013-31; ``None``: el del proyecto, sin código de versión,
    :func:`dataset_locator`): su nombre, su tipo, su almacén, su
    ubicación, su lector y su papel; sin selector y no editable en QGIS. ``content``: su hash,
    calculado fuera de la transacción (R4); ``crs_epsg``, el de una rejilla o una capa. Con una
    familia sin nombre (:func:`dataset_name`), ``name`` es ``""``."""
    found = _family(family)
    return DatasetSpec(dataset_name(family, name), MODULE, found.kind, found.store,
                       dataset_locator(family, name, version_code), reader=found.reader,
                       role=found.role, content=content, crs_epsg=crs_epsg)


# --- Ajustes -----------------------------------------------------------------------------------

_BOUND_ALL, _BOUND_SECTORS, _BOUND_LAYER, _BOUND_BOTH = "all", "sectors", "layer", "both"
_ANCHOR_PROFILE, _ANCHOR_GRID = "profile", "grid"

ENVELOPE_SETTINGS: tuple[SettingDef, ...] = (
    SettingDef("direction", "Envelope direction", choices=(
        (Direction.DOWN.value, "Downward envelope"), (Direction.UP.value, "Upward envelope"))),
    SettingDef("metric", "Distance metric", choices=(
        (Metric.CHAMFER5.value, "5×5 chamfer distance"),
        (Metric.EXACT.value, "Exact Euclidean distance"))),
    SettingDef("reach_m", "Reach", unit="m"),
    SettingDef("slope_mode", "Slope mode", choices=(
        (SlopeMode.CONSTANT.value, "Constant slope"),
        (SlopeMode.SECTORS.value, "Slope of each sector"))),
    SettingDef("slope_deg", "Slope angle", unit="deg"),
    SettingDef("mesh_factor", "Mesh factor", unit="-"),
    SettingDef("seeds.kind", "Origin of the seeds", choices=(
        (SeedKind.SURFACE.value, "Cells of a surface"), (SeedKind.FIXED.value, "Fixed elevation"),
        (SeedKind.GRID.value, "Grid of elevations"))),
    SettingDef("seeds.zone.kind", "Zone of the seeds", choices=(
        (ZoneKind.DOMAIN.value, "Default domain"),
        (ZoneKind.CONSTRAINT.value, "Zone of a constraint"),
        (ZoneKind.SECTOR.value, "Design sector"), (ZoneKind.LAYER.value, "Polygon layer"))),
    SettingDef("seeds.elevation_m", "Elevation of the fixed seeds", unit="m"),
    SettingDef("domain.bound", "Bound of the work domain", choices=(
        (_BOUND_ALL, "Whole work domain"), (_BOUND_SECTORS, "Bounded to sectors"),
        (_BOUND_LAYER, "Bounded to a layer"), (_BOUND_BOTH, "Bounded to sectors and a layer"))),
    SettingDef("base_profile", "Base profile", choices=(("", "None"),)),
)
"""Los ajustes de ``des.envelope`` que enseña su procedencia (plan §5.2.3): la dirección, la
métrica, el alcance, el modo y el valor de la pendiente, el factor de malla, el origen de las
semillas, el acotado del dominio y el perfil base de las celdas sin sector (con la pendiente por
sectores; su código, tal cual). Los nombres (superficies, capas, sectores) no se declaran."""
DESIGN_SETTINGS: tuple[SettingDef, ...] = (
    SettingDef("sense", "Benching sense", choices=(
        (BenchSense.CUT.value, "Cut, face first"), (BenchSense.FILL.value, "Fill, berm first"))),
    SettingDef("base_profile", "Base profile", choices=(("", "None"),)),
    SettingDef("anchor.source", "Anchor of the benches", choices=(
        (_ANCHOR_PROFILE, "Anchor elevation of the profile"),
        (_ANCHOR_GRID, "Grid of anchor elevations"))),
)
"""Los ajustes de ``des.stepped_design`` que enseña su procedencia: el sentido, el perfil base
(su código, tal cual: un valor que no es «ninguno» se enseña como está) y de dónde sale el
ancla."""

CROWN_SEEDS = "crown"
"""El origen de las semillas de un lado de la cantera cuando son «coronación y zonas a sostener»
(RF-014-02; ``QuarrySide.seeds`` es ``None``): el valor que se guarda en ``<lado>.seeds.kind``."""


def _side_settings(side: Surface, label: str) -> tuple[SettingDef, ...]:
    """Los ajustes de un lado de la cantera (``final`` o ``exploitation``), cada uno con su
    nombre propio (``label``: «of the final surface»)."""
    return (
        SettingDef(f"{side.value}.seeds.kind", f"Seeds {label}", choices=(
            (CROWN_SEEDS, "Crown and zones to hold"),
            (SeedKind.SURFACE.value, "Cells of a surface"),
            (SeedKind.FIXED.value, "Fixed elevation"),
            (SeedKind.GRID.value, "Grid of elevations"))),
        SettingDef(f"{side.value}.base_profile", f"Base profile {label}", choices=(("", "None"),)),
        SettingDef(f"{side.value}.anchor", f"Anchor {label}", choices=(
            (AnchorMode.FIXED.value, "Anchor elevation of the profile"),
            (AnchorMode.GRID.value, "Grid of anchor elevations"),
            (AnchorMode.NEAREST_FLOOR.value, "Floor nearest to each wall"))),
        SettingDef(f"{side.value}.metric", f"Distance metric {label}", choices=(
            (Metric.CHAMFER5.value, "5×5 chamfer distance"),
            (Metric.EXACT.value, "Exact Euclidean distance"))),
    )


QUARRY_SETTINGS: tuple[SettingDef, ...] = (
    SettingDef("order", "Order of the design", choices=(
        (Order.FINAL_FIRST.value, "Final surface first"),
        (Order.EXPLOITATION_FIRST.value, "Exploitation surface first"))),
    *_side_settings(Surface.FINAL, "of the final surface"),
    *_side_settings(Surface.EXPLOITATION, "of the exploitation surface"),
    SettingDef("to_final", "Exploitation down to the final surface", choices=(
        (ToFinalMode.NONE.value, "No"), (ToFinalMode.WARNED.value, "All the warned zones"),
        (ToFinalMode.LAYER.value, "Zones of a layer"))),
)
"""Los ajustes de ``des.quarry`` que enseña su procedencia (plan 014 §5.3.3; RF-014-12, RF-014-13,
RF-014-18): el orden; por lado (``final.…`` y ``exploitation.…``), el origen de las semillas
(:data:`CROWN_SEEDS` o el de unas de la 013), el perfil base (su código, tal cual), el ancla
(también «al fondo de cada muro») y la métrica; y «explotación hasta la final». Los nombres
(superficies, capas, campos, sectores) no se declaran."""
FILL_ONLY_SETTINGS: tuple[SettingDef, ...] = tuple(
    setting for setting in DESIGN_SETTINGS if setting.key != "sense")
"""Los ajustes de ``des.fill_only`` (plan 014 §5.3.3): los del escalonado de la 013 salvo el
sentido, que es siempre relleno (el perfil base y de dónde sale el ancla); la capa de las láminas
y su campo son nombres."""
PLATFORM_SETTINGS: tuple[SettingDef, ...] = ()
"""Los ajustes de ``des.platform`` que enseña su procedencia: ninguno (plan 015 §5.2.2: la definición
de una entidad son sus **parámetros** ``des.platform.{e}.*``, que la procedencia enseña con sus
valores; los ajustes solo guardan nombres —el de la entidad, su código y los campos de su capa—, que
no se declaran). Lo mismo vale para la declaración y la capa de entidades."""


# --- Cifras ------------------------------------------------------------------------------------

CUT_M3 = "des.cut_m3"
FILL_M3 = "des.fill_m3"
"""Las cifras del desmonte y del terraplén del diseño: con ellas compara el aviso de magnitud
frente a la revisión congelada más reciente (D-25)."""

ENVELOPE_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.env_cells", "-", "Cells with envelope"),
    FigureDef("des.env_area_m2", "m2", "Area with envelope"),
    FigureDef("des.env_min_m", "m", "Lowest elevation of the envelope", allow_negative=True),
    FigureDef("des.env_max_m", "m", "Highest elevation of the envelope", allow_negative=True),
    FigureDef("des.env_cut_m3", "m3", "Cut of the envelope against the start surface"),
    FigureDef("des.env_fill_m3", "m3", "Fill of the envelope against the start surface"),
)
"""Las cifras de ``des.envelope`` (RF-013-17)."""
DESIGN_FIGURES: tuple[FigureDef, ...] = (
    FigureDef(CUT_M3, "m3", "Cut volume"),
    FigureDef(FILL_M3, "m3", "Fill volume"),
    FigureDef("des.moved_area_m2", "m2", "Area with movement"),
    FigureDef("des.slope_p90_deg", "deg", "90th percentile of the slope"),
    FigureDef("des.slope_p99_deg", "deg", "99th percentile of the slope"),
    FigureDef("des.slope_max_deg", "deg", "Maximum slope"),
    FigureDef("des.edge_step_max_m", "m", "Largest step at the edge of the prohibited cells"),
    FigureDef("des.berm_count", "-", "Berms by sector, profile and level"),
    FigureDef("des.nodata_area_m2", "m2", "Area without data"),
)
"""Las cifras de ``des.stepped_design`` (RF-013-30, RF-013-31)."""
FIGURES: tuple[FigureDef, ...] = ENVELOPE_FIGURES + DESIGN_FIGURES
"""Las cifras de la 013 (plan 013 §5.2.3), cada una con su unidad del catálogo."""

AREA_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.rcn_area_m2", "m2", "Area of the excavation boundary"),
)
"""La cifra de ``des.excavation_area`` (RF-014-01)."""
TWO_SURFACES_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.exp_cut_m3", "m3", "Excavation of the exploitation surface"),
    FigureDef("des.unsplit_m3", "m3", "Unsplit volume"),
    FigureDef("des.restoration_fill_m3", "m3", "Restoration fill"),
    FigureDef("des.to_final_m3", "m3", "Volume taken down to the final surface"),
    FigureDef("des.exp_cut_area_ha", "ha", "Area of the excavation of the exploitation"),
    FigureDef("des.unsplit_area_ha", "ha", "Unsplit area"),
    FigureDef("des.restoration_fill_area_ha", "ha", "Area of the restoration fill"),
    FigureDef("des.quarry_min_m", "m", "Lowest elevation of the quarry surface",
              allow_negative=True),
    FigureDef("des.quarry_max_m", "m", "Highest elevation of the quarry surface",
              allow_negative=True),
)
"""Las cifras de ``des.quarry`` (RF-014-16, RF-014-18): la excavación de la explotación, el
desdoblado, el relleno de restauración (lo clasificado, no diseñado) y lo que pasa del desdoblado a
la explotación, en m³; sus áreas en ha; y las cotas mínima y máxima de cada superficie (con la
superficie en su ámbito, :func:`quarry_figure_scope`), por sector y en total."""
TRANSITION_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.transition_m3", "m3", "Volume of the transition"),
    FigureDef("des.created_step_max_m", "m", "Largest created step at the edge"),
    FigureDef("des.created_step_share_pct", "%",
              "Share of edge pairs within the admitted created step"),
)
"""Las cifras de ``des.edge_transition`` (RF-014-19 a RF-014-21)."""
FILL_ONLY_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.fill_only_cut_m3", "m3", "Cut of the fill-only design"),
)
"""La cifra propia de ``des.fill_only`` (RF-014-22, RF-014-25): las demás son las del escalonado
de la 013 (:data:`DESIGN_FIGURES`), ya registradas."""
REFIT_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.refit_m3", "m3", "Volume of the refit"),
)
"""La cifra de ``des.refit`` por superficie (RF-014-27)."""
QUARRY_FIGURES: tuple[FigureDef, ...] = (
    *AREA_FIGURES, *TWO_SURFACES_FIGURES, *TRANSITION_FIGURES, *FILL_ONLY_FIGURES, *REFIT_FIGURES)
"""Las cifras que declara la 014 (plan 014 §5.2.3), aparte de las de la 013."""

SUPPORTED_M3 = "des.supported_m3"
DECLARED_COUNT = "des.declared_count"
"""Las claves de lo apoyado y de lo declarado (spec 015)."""

PLATFORM_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.plat_area_m2", "m2", "Area of the platform"),
    FigureDef("des.plat_axis_m", "m", "Length of the axis of the platform"),
    FigureDef("des.plat_footprint_m", "m", "Length of the footprint of the platform"),
    FigureDef("des.plat_start_level_m", "m", "Level of the platform at the start of its axis",
              allow_negative=True),
    FigureDef("des.plat_end_level_m", "m", "Level of the platform at the end of its axis",
              allow_negative=True),
    FigureDef("des.plat_cut_m3", "m3", "Cut of the platform footprint"),
    FigureDef("des.plat_fill_m3", "m3", "Fill of the platform footprint"),
    FigureDef("des.edge_cut_m3", "m3", "Cut of the platform edge"),
    FigureDef("des.edge_fill_m3", "m3", "Fill of the platform edge"),
    FigureDef("des.edge_wall_max_m", "m", "Largest cut or fill of the platform edge"),
    FigureDef("des.plat_below_m2", "m2",
              "Area of the footprint not left at the platform level (above or below it)"),
    FigureDef("des.plat_below_max_m", "m",
              "Largest gap between the footprint and the platform level (above or below it)"),
)
"""Las cifras de ``des.platform`` (RF-015-24, RF-015-22; plan 015 §5.2.3), con el ámbito de
:func:`entity_figure_scope`: el área de su huella, las longitudes de su eje y de su huella, las cotas
de la rasante en sus extremos (pueden ser negativas), el corte y el relleno de la huella y del borde
por separado, el mayor desmonte o relleno de una celda del borde (``des.edge_wall_max_m``: la «altura máxima
de su pared» del plan, [I]; T45, D-11) y, de las celdas de la huella que no quedan en la rasante, por
encima **o** por debajo (por las máscaras), su área y la diferencia máxima (``des.plat_below_*``: la clave dice
«below» por el modo «en corte», que no rellena; T45, D-10). Las dos cotas son ``plat_start_level_m`` y
``plat_end_level_m`` (el plan las llamaba con la palabra que el glosario §14 reserva a la ley)."""
SUPPORT_FIGURES: tuple[FigureDef, ...] = (
    FigureDef(SUPPORTED_M3, "m3", "Volume resting on an entity"),
)
"""La cifra de lo apoyado (RF-015-15; ADR-0030 §4): el volumen que una operación que rellena apoya
sobre la huella de **cada** entidad (``scope = {name, entity}``, con la entidad en la que se apoya). La
deja también toda operación de la 013 o la 014 que rellena sobre una entidad (T23)."""
DECLARE_FIGURES: tuple[FigureDef, ...] = (
    FigureDef(DECLARED_COUNT, "-", "Constraints declared by the entities"),
)
"""La cifra de ``des.declare_constraints`` (RF-015-10): cuántas restricciones declara la versión."""
ENTITY_FIGURES: tuple[FigureDef, ...] = (*PLATFORM_FIGURES, *SUPPORT_FIGURES, *DECLARE_FIGURES)
"""Las cifras que declara la 015 (plan 015 §5.2.3), aparte de las de la 013 y la 014."""

# Las cifras de los cuatro tipos de la 016 (spec 016, T03; plan 016 §5.2.3; RF-016-02, 09, 13, 17, 19, 20, 21).
STOCKPILE_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.stk_count", "-", "Stockpiles detected"),
    FigureDef("des.stk_candidates", "-", "Candidates without a mark"),
    FigureDef("des.stk_area_m2", "m2", "Footprint area of the stockpile"),
    FigureDef("des.stk_volume_m3", "m3", "Volume of the stockpile above its base"),
    FigureDef("des.stk_thickness_max_m", "m", "Largest thickness of the stockpile"),
    FigureDef("des.stk_plane_tilt_deg", "deg", "Tilt of the base plane of the stockpile"),
)
"""Las cifras de ``des.stockpile_detect`` (RF-016-02, RF-016-08; plan 016 §5.2.3): cuántos acopios y cuántos candidatos
da la detección (con el ámbito de :func:`entity_figure_scope`) y, **por acopio y material** (ámbito de
:func:`stockpile_figure_scope`: la clave del acopio y su material), su área, su volumen sobre su base, su espesor máximo y
la inclinación de su plano de base (un acopio con superficie de base propia, RF-016-03, no tiene plano ni inclinación)."""
REMOVAL_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.rmv_removed_m3", "m3", "Volume removed from the stockpile"),
    FigureDef("des.rmv_resting_m3", "m3", "Volume of the material that rested on the stockpile"),
    FigureDef("des.rmv_transition_m3", "m3", "Volume of the transition of the removal"),
    FigureDef("des.rmv_kept_m3", "m3", "Volume not removed where the masks do not allow it"),
    FigureDef("des.rmv_transition_m2", "m2", "Area of the transition of the removal"),
    FigureDef("des.rmv_wall_max_m", "m", "Largest wall left by the removal"),
)
"""Las cifras de ``des.stockpile_removal`` (RF-016-13; plan 016 §5.2.3), con el ámbito de las entidades: el volumen
retirado del acopio, el del material que se le apoyaba, el de la transición, el que no se retira donde las máscaras no
lo admiten, el área de la transición y la mayor pared. Las deja también la plataforma que sale de retirar un acopio
«como plataforma» (RF-016-16). La cifra de lo apoyado, ``des.supported_m3``, es de :data:`SUPPORT_FIGURES`."""
BUTTRESS_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.btr_volume_m3", "m3", "Volume of the buttress"),
    FigureDef("des.btr_area_m2", "m2", "Area of the buttress"),
    FigureDef("des.btr_height_max_m", "m", "Largest height of the buttress"),
    FigureDef("des.btr_cutoff_m2", "m2", "Area of the foot of the buttress that is cut off"),
    FigureDef("des.btr_cutoff_m3", "m3", "Volume of the foot of the buttress that is cut off"),
)
"""Las cifras de ``des.buttress`` (RF-016-17, RF-016-19; plan 016 §5.2.3): su volumen, su área y su altura máxima y el
área y el volumen que faltan del pie cortado por el borde del relleno admitido."""
BODY_FIGURES: tuple[FigureDef, ...] = (
    FigureDef("des.bdy_volume_m3", "m3", "Volume of the supported body"),
    FigureDef("des.bdy_thickness_max_m", "m", "Largest thickness of the supported body"),
    FigureDef("des.bdy_far_m2", "m2", "Area of the body far from the thickness data"),
    FigureDef("des.bdy_far_m3", "m3", "Volume of the body far from the thickness data"),
    FigureDef("des.bdy_ignored", "-", "Thickness data ignored outside the footprint"),
)
"""Las cifras de ``des.body`` (RF-016-20, RF-016-21; plan 016 §5.2.3): su volumen y su espesor máximo, el área y el
volumen de lo que queda a más de la distancia máxima de los datos y cuántos datos se ignoraron por caer fuera de la
huella."""
SUPPORTED_FIGURES: tuple[FigureDef, ...] = (*STOCKPILE_FIGURES, *REMOVAL_FIGURES, *BUTTRESS_FIGURES, *BODY_FIGURES)
"""Las cifras que declara la 016 (plan 016 §5.2.3), aparte de las de las tres specs anteriores (``des.supported_m3``
ya es de la 015)."""


# --- Tipos de operación ------------------------------------------------------------------------

EXCAVATION_AREA = "des.excavation_area"
QUARRY = "des.quarry"
EDGE_TRANSITION = "des.edge_transition"
FILL_ONLY = "des.fill_only"
REFIT = "des.refit"
"""Los cinco tipos de la 014 (plan 014 §5.2.3)."""
LIMIT_COMMAND = "geoblender.des_create_limit_from_perimeter"
QUARRY_COMMAND = "geoblender.des_design_quarry"
TRANSITIONS_COMMAND = "geoblender.des_create_transitions"
FILL_ONLY_COMMAND = "geoblender.des_design_fill_only"
REFIT_COMMAND = "geoblender.des_refit_to_limit"
"""Las órdenes del catálogo que los lanzan, una por tipo (plan 014 §5.3.3; entrada «014»)."""

PLATFORM = "des.platform"
DECLARE_CONSTRAINTS = "des.declare_constraints"
ENTITY_LAYER = "des.entity_layer"
"""Los tres tipos de la 015 (plan 015 §5.2.3). «Soltar el apoyo…» no es un tipo: es una
``des.platform`` repetida con ``supersedes`` (T25)."""
PLATFORM_COMMAND = "geoblender.des_create_platform"
"""La orden del catálogo que lanza los tres: «Plataforma…» (entrada «R-36» hasta que la T31 la entregue;
la declaración y la capa de entidades las encadena la orden que crea la entidad, plan 015 §5.3.2). Es
la definitiva del plan 015 §5.3.3 (spec 015, T15): sustituye a la clave marcador que traía el catálogo
(``geoblender.des_draw_platform``)."""

STOCKPILE_DETECT = "des.stockpile_detect"
STOCKPILE_DETECT_PROJECT = "des.stockpile_detect_project"
STOCKPILE_REMOVAL = "des.stockpile_removal"
BUTTRESS = "des.buttress"
BODY = "des.body"
"""Los tipos de la 016 (spec 016, T03 y T04; plan 016 §5.2.3): la detección de acopios **de una versión** y **del
proyecto** (el mismo algoritmo con otro ámbito: D-15, ADR-0031 §2), su retirada, el contrafuerte y el cuerpo apoyado.
«Como plataforma» no es un tipo: es una ``des.platform`` con la huella como geometría (P-3)."""
STOCKPILE_DETECT_TYPES: tuple[str, ...] = (STOCKPILE_DETECT, STOCKPILE_DETECT_PROJECT)
"""Los dos tipos de operación de la detección: de versión y de proyecto (T04)."""
STOCKPILE_COMMAND = "geoblender.des_detect_stockpiles"
REMOVAL_COMMAND = "geoblender.des_remove_stockpile"
BUTTRESS_COMMAND = "geoblender.des_add_buttress"
BODY_COMMAND = "geoblender.des_create_body"
"""Las órdenes que los lanzan (plan 016 §5.3.3; la decisión de la sesión principal sobre la T35, 18/11/2026: se conservan
los nombres que ya tiene el catálogo, ``des_add_buttress`` y ``des_edit_stockpile``, y la «Unidad por espesor sobre su
apoyo…» pasa a ser ``des_create_body``). Las de acopios, la retirada y el cuerpo **aún no están en el catálogo** (las
crea la T35): una orden que lanza una operación se declara en ``OperationDef.commands``, que solo comprueba su forma."""


@dataclass(frozen=True, slots=True)
class OperationType:
    """Un tipo de operación de ``des`` sin sus funciones (plan §5.2.3): ``op_type``, su nombre
    visible (``label_msgid``, con su español en ``core/i18n/messages.toml``), las familias de
    datos que produce y los ajustes de su orden que enseña su procedencia; con su nombre, sus
    cifras (``figures``), las órdenes que lo lanzan (``commands``; por defecto, :data:`COMMAND`), si
    se reproduce (``reproducible``) y si su recálculo reúne él mismo todo lo vigente que consume
    (``drops_discarded``: la declaración de restricciones, que lee las entidades vivas de la versión;
    spec 015, T20). Todos son de versión (RF-009-05; ``scope``) salvo la detección de acopios del proyecto (T04, D-15) y
    se repiten solos; los que no reúnen ellos mismos lo vigente
    pueden apoyarse en una entidad que se descarta, y entonces su recálculo **espera una decisión** (rehacerlos,
    descartarlos o darlos por buenos, ``entity_store.release_support``: ``OperationDef.offers_release``, T40)."""

    op_type: str
    label_msgid: str
    outputs: tuple[str, ...]
    settings: tuple[SettingDef, ...]
    figures: tuple[FigureDef, ...] = ()
    commands: tuple[str, ...] = (COMMAND,)
    reproducible: bool = True
    drops_discarded: bool = False
    scope: str = "version"
    """Su ámbito (``OperationDef.scope``: ``version`` o ``project``; spec 016, T04): todos son de versión salvo la
    detección de acopios del proyecto (:data:`STOCKPILE_DETECT_PROJECT`, D-15)."""

    def definition(self, recompute: RecomputeFunction | None = None,
                   reproduce: ReproduceFunction | None = None) -> OperationDef:
        """Su ``OperationDef`` (versión :data:`OP_VERSION`) con las funciones de ``bl``: la de
        recálculo y la de reproducción (con :data:`FIGURE_TOLERANCE`); ``ValueError`` de
        ``OperationDef`` si falta la de recálculo, y si se da la de reproducción a un tipo que no
        se reproduce."""
        if reproduce is not None and not self.reproducible:
            raise ValueError(f"«{self.op_type}» no se reproduce (depende de lo vigente): no lleva "
                             "función de reproducción")
        return OperationDef(
            self.op_type, OP_VERSION, MODULE, self.label_msgid, True, scope=self.scope,
            commands=self.commands, recompute=recompute, settings=self.settings,
            drops_discarded=self.drops_discarded, offers_release=not self.drops_discarded,
            reproduce=reproduce, figure_tolerance=FIGURE_TOLERANCE if reproduce is not None else None)


OPERATION_TYPES: tuple[OperationType, ...] = (
    OperationType(ENVELOPE, "Slope envelope", (ENVELOPE_GRID,), ENVELOPE_SETTINGS,
                  ENVELOPE_FIGURES),
    OperationType(STEPPED, "Benched design", (DESIGN_GRID, BERMS_GRID, BERM_TABLE, REPORT_TABLE),
                  DESIGN_SETTINGS, DESIGN_FIGURES),
)
"""Los tipos de operación de la 013, en el orden del plan 013 §5.2.3."""
QUARRY_OPERATION_TYPES: tuple[OperationType, ...] = (
    OperationType(EXCAVATION_AREA, "Limit from the perimeter", (EXCAVATION_AREA_GRID,), (),
                  AREA_FIGURES, (LIMIT_COMMAND,)),
    OperationType(QUARRY, "Quarry with two surfaces",
                  (EXPLOITATION_GRID, FINAL_GRID, EXPLOITATION_ENVELOPE_GRID, FINAL_ENVELOPE_GRID,
                   CLASSIFICATION_GRID, BERM_TABLE, QUARRY_REPORT_TABLE),
                  QUARRY_SETTINGS, TWO_SURFACES_FIGURES, (QUARRY_COMMAND,)),
    OperationType(EDGE_TRANSITION, "Transitions with the untouched terrain",
                  (TRANSITION_GRID, EDGE_REPORT_TABLE), (), TRANSITION_FIGURES,
                  (TRANSITIONS_COMMAND,)),
    OperationType(FILL_ONLY, "Fill only", (DESIGN_GRID, REPORT_TABLE), FILL_ONLY_SETTINGS,
                  FILL_ONLY_FIGURES, (FILL_ONLY_COMMAND,)),
    OperationType(REFIT, "Refit of the design to a new limit", (REFIT_GRID,), (), REFIT_FIGURES,
                  (REFIT_COMMAND,), reproducible=False),
)
"""Los tipos de operación de la 014, en el orden del plan 014 §5.2.3, aparte de los de la 013."""
ENTITY_OPERATION_TYPES: tuple[OperationType, ...] = (
    OperationType(PLATFORM, "Platform", (ENTITY_SURFACE_GRID, ENTITY_TABLE, ENTITY_REPORT_TABLE),
                  PLATFORM_SETTINGS, (*PLATFORM_FIGURES, *SUPPORT_FIGURES), (PLATFORM_COMMAND,)),
    OperationType(DECLARE_CONSTRAINTS, "Constraints of the entities", (DECLARED_TABLE,), (),
                  DECLARE_FIGURES, (PLATFORM_COMMAND,), drops_discarded=True),
    OperationType(ENTITY_LAYER, "Layer of the entities", (ENTITY_MAP_TABLE,), (), (),
                  (PLATFORM_COMMAND,), reproducible=False, drops_discarded=True),
)
"""Los tipos de operación de la 015, en el orden del plan 015 §5.2.3, aparte de los de la 013 y la
014: repetibles y reproducibles (:data:`ENTITY_REPRODUCIBLE`) salvo la capa de entidades (T30: es una vista
regenerable que incluye el estado de cada entidad, deducido del grafo; ``drops_discarded``: su recálculo
reúne él mismo las entidades vivas, como la declaración)."""
SUPPORTED_OPERATION_TYPES: tuple[OperationType, ...] = (
    OperationType(STOCKPILE_DETECT, "Stockpile detection",
                  (STOCKPILES_TABLE, STOCKPILE_CANDIDATES_TABLE, STOCKPILE_BASE_GRID, STOCKPILE_THICKNESS_GRID,
                   STOCKPILE_GROUND_GRID, STOCKPILE_SURFACE_GRID, ENTITY_REPORT_TABLE),
                  (), STOCKPILE_FIGURES, (STOCKPILE_COMMAND,)),
    OperationType(STOCKPILE_DETECT_PROJECT, "Stockpile detection of the project",
                  (STOCKPILES_TABLE, STOCKPILE_CANDIDATES_TABLE, STOCKPILE_BASE_GRID, STOCKPILE_THICKNESS_GRID,
                   STOCKPILE_GROUND_GRID, STOCKPILE_SURFACE_GRID, ENTITY_REPORT_TABLE),
                  (), STOCKPILE_FIGURES, (STOCKPILE_COMMAND,), scope="project"),
    OperationType(STOCKPILE_REMOVAL, "Stockpile removal",
                  (ENTITY_SURFACE_GRID, ENTITY_TABLE, ENTITY_REPORT_TABLE),
                  (), (*REMOVAL_FIGURES, *SUPPORT_FIGURES), (REMOVAL_COMMAND,)),
    OperationType(BUTTRESS, "Buttress", (ENTITY_SURFACE_GRID, ENTITY_TABLE, ENTITY_REPORT_TABLE),
                  (), (*BUTTRESS_FIGURES, *SUPPORT_FIGURES), (BUTTRESS_COMMAND,)),
    OperationType(BODY, "Supported body",
                  (BODY_THICKNESS_GRID, BODY_BASE_GRID, ENTITY_SURFACE_GRID, ENTITY_TABLE, ENTITY_REPORT_TABLE),
                  (), BODY_FIGURES, (BODY_COMMAND,)),
)
"""Los tipos de operación de la 016 (plan 016 §5.2.3), aparte de los de las tres specs anteriores: de la versión,
repetibles y reproducibles, **sin comportamiento todavía** (cada tarea que crea una operación le da su cálculo). Como en
la plataforma, la definición de cada entidad son sus **parámetros** (``des.<tipo>.{e}.*``): los ajustes no declaran
ninguno. Salidas: la detección, sus tablas y rejillas dispersas (el papel de cada una es el de su familia); la retirada
y el contrafuerte, su superficie entera (``des_psf_``), su tabla (``des_epr_``: la huella y, el contrafuerte, la zona de
coronación) y su informe; el cuerpo, su espesor disperso y, «sobre una base», su superficie entera o, «bajo un techo», su
base dispersa. La retirada y el contrafuerte dejan también ``des.supported_m3`` (lo que apoyan: ADR-0031 §4).

**La detección del proyecto** (D-15; ADR-0031 §2) es la misma operación con otro escritor, pero ``OperationDef.scope`` es
uno por tipo: el segundo tipo de la detección, :data:`STOCKPILE_DETECT_PROJECT`, **de proyecto**, tiene las mismas salidas, los
mismos ajustes y las mismas cifras que el de versión (spec 016, T04; decisión de la sesión principal, 18/11/2026). Los
parámetros no tienen el problema: una familia de versión admite el valor del proyecto."""
OPERATION_TYPES_BY_NAME: Mapping[str, OperationType] = MappingProxyType(
    {declared.op_type: declared
     for declared in (*OPERATION_TYPES, *QUARRY_OPERATION_TYPES, *ENTITY_OPERATION_TYPES,
                      *SUPPORTED_OPERATION_TYPES)})
"""Los tipos de las cuatro specs por nombre (solo lectura)."""
VERSION_TYPES: tuple[str, ...] = tuple(t.op_type for t in OPERATION_TYPES)
"""Los tipos de versión de la 013 (RF-013-17, RF-013-31)."""
REPRODUCIBLE: tuple[str, ...] = VERSION_TYPES
"""Los tipos de la 013 que se repiten solos y se reproducen (los dos): los que repite
``design.store.recompute_run``."""
QUARRY_VERSION_TYPES: tuple[str, ...] = tuple(t.op_type for t in QUARRY_OPERATION_TYPES)
"""Los tipos de versión de la 014, que se repiten solos (RF-014-29)."""
QUARRY_REPRODUCIBLE: tuple[str, ...] = tuple(t.op_type for t in QUARRY_OPERATION_TYPES
                                             if t.reproducible)
"""Los tipos de la 014 que se reproducen: todos salvo el ajuste."""
ENTITY_VERSION_TYPES: tuple[str, ...] = tuple(t.op_type for t in ENTITY_OPERATION_TYPES)
"""Los tipos de versión de la 015, que se repiten solos (RF-015-02)."""
ENTITY_REPRODUCIBLE: tuple[str, ...] = tuple(t.op_type for t in ENTITY_OPERATION_TYPES
                                             if t.reproducible)
"""Los tipos de la 015 que se reproducen: la plataforma y la declaración de restricciones (RF-015-02: bit a bit
desde una revisión congelada, con :data:`FIGURE_TOLERANCE` en las cifras). La capa de entidades no (T30)."""
SUPPORTED_TYPES: tuple[str, ...] = tuple(t.op_type for t in SUPPORTED_OPERATION_TYPES)
"""Todos los tipos de la 016, de versión y de proyecto, en su orden: los que se repiten solos (RF-016-10)."""
SUPPORTED_VERSION_TYPES: tuple[str, ...] = tuple(t.op_type for t in SUPPORTED_OPERATION_TYPES if t.scope == "version")
"""Los tipos de versión de la 016."""
SUPPORTED_PROJECT_TYPES: tuple[str, ...] = tuple(t.op_type for t in SUPPORTED_OPERATION_TYPES if t.scope == "project")
"""Los tipos de proyecto de la 016 (T04): la detección de acopios sobre una superficie del proyecto (D-15)."""
SUPPORTED_REPRODUCIBLE: tuple[str, ...] = tuple(t.op_type for t in SUPPORTED_OPERATION_TYPES if t.reproducible)
"""Los tipos de la 016 que se reproducen: todos (bit a bit desde una revisión congelada, con
:data:`FIGURE_TOLERANCE` en las cifras)."""


def operation_def(op_type: str, recompute: RecomputeFunction | None = None,
                  reproduce: ReproduceFunction | None = None) -> OperationDef:
    """El ``OperationDef`` de ``op_type`` (de la 013, la 014, la 015 o la 016) con las funciones de recálculo y
    de reproducción que le da ``bl``. ``ValueError`` si el tipo no es de ``des``, falta la
    función de recálculo o se da la de reproducción a uno que no se reproduce."""
    found = OPERATION_TYPES_BY_NAME.get(op_type) if isinstance(op_type, str) else None
    if found is None:
        raise ValueError(f"{op_type!r} no es un tipo de operación del diseño: es uno de "
                         f"{', '.join(OPERATION_TYPES_BY_NAME)}")
    return found.definition(recompute, reproduce)


def _check_functions(name: str, given: Mapping[str, Any], wanted: tuple[str, ...]) -> None:
    if set(given) != set(wanted):
        raise ValueError(f"las funciones de {name} son las de {', '.join(wanted)}, no las de "
                         f"{', '.join(sorted(map(str, given)))}")


def operation_defs(recompute: Mapping[str, RecomputeFunction],
                   reproduce: Mapping[str, ReproduceFunction]) -> tuple[OperationDef, ...]:
    """Los ``OperationDef`` de los dos tipos de la 013, en su orden, cada uno con su función de
    ``recompute`` y de ``reproduce`` (por tipo). ``ValueError`` si sobra o falta alguna."""
    _check_functions("recálculo", recompute, REPRODUCIBLE)
    _check_functions("reproducción", reproduce, REPRODUCIBLE)
    return tuple(declared.definition(recompute[declared.op_type], reproduce[declared.op_type])
                 for declared in OPERATION_TYPES)


def quarry_operation_defs(recompute: Mapping[str, RecomputeFunction],
                          reproduce: Mapping[str, ReproduceFunction]
                          ) -> tuple[OperationDef, ...]:
    """Los ``OperationDef`` de los cinco tipos de la 014, en su orden: cada uno con su función de
    ``recompute`` (todos se repiten solos) y, los de :data:`QUARRY_REPRODUCIBLE`, con la de
    ``reproduce``. ``ValueError`` si sobra o falta alguna."""
    _check_functions("recálculo", recompute, QUARRY_VERSION_TYPES)
    _check_functions("reproducción", reproduce, QUARRY_REPRODUCIBLE)
    return tuple(declared.definition(recompute[declared.op_type],
                                     reproduce.get(declared.op_type))
                 for declared in QUARRY_OPERATION_TYPES)


def entity_operation_defs(recompute: Mapping[str, RecomputeFunction],
                          reproduce: Mapping[str, ReproduceFunction]
                          ) -> tuple[OperationDef, ...]:
    """Los ``OperationDef`` de los tres tipos de la 015, en su orden: cada uno con su función de
    ``recompute`` (todos se repiten solos) y, los de :data:`ENTITY_REPRODUCIBLE` (la plataforma y la
    declaración; no la capa de entidades), con la de ``reproduce``. ``ValueError`` si sobra o falta
    alguna."""
    _check_functions("recálculo", recompute, ENTITY_VERSION_TYPES)
    _check_functions("reproducción", reproduce, ENTITY_REPRODUCIBLE)
    return tuple(declared.definition(recompute[declared.op_type], reproduce.get(declared.op_type))
                 for declared in ENTITY_OPERATION_TYPES)


def supported_operation_defs(recompute: Mapping[str, RecomputeFunction],
                             reproduce: Mapping[str, ReproduceFunction]) -> tuple[OperationDef, ...]:
    """Los ``OperationDef`` de los cinco tipos de la 016 (spec 016, T03 y T04), en su orden (los dos de la detección,
    el de versión y el de proyecto, juntos): cada uno con su función de ``recompute`` (todos se repiten solos) y de
    ``reproduce`` (:data:`SUPPORTED_REPRODUCIBLE`: todos). ``ValueError`` si sobra o falta alguna."""
    _check_functions("recálculo", recompute, SUPPORTED_TYPES)
    _check_functions("reproducción", reproduce, SUPPORTED_REPRODUCIBLE)
    return tuple(declared.definition(recompute[declared.op_type], reproduce[declared.op_type])
                 for declared in SUPPORTED_OPERATION_TYPES)


# --- Las cifras: armarlas -----------------------------------------------------------------------


def _finite(key: str, value: object) -> float:
    """``value`` como real finito; un valor que no lo es es un error del programa (RF-013-17)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"la cifra «{key}» es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"la cifra «{key}» no es un número finito: {value!r} (RF-013-17: no se "
                         "registra una cifra NaN ni infinita)")
    return number


def _count(key: str, value: object) -> float:
    """``value`` como un número entero no negativo (celdas, bermas) en float64."""
    number = _finite(key, value)
    if number < 0 or number != int(number):
        raise ValueError(f"la cifra «{key}» es un número entero no negativo, no {value!r}")
    return number


FIGURE_SCOPE_KEY = "name"
"""La clave del ámbito de las cifras de ``des``: el nombre de la operación."""


def figure_scope(name: str) -> dict[str, str]:
    """El ámbito de las cifras de la operación ``name`` (RF-013-17): su nombre en ASCII, el mismo
    que da el dato (``dataset_slug``; el nombre es único en la versión por él). La cifra vigente de
    una clave es la última de cada ámbito (RF-009-20): sin él, dos envolventes (o dos escalonados)
    de una versión se pisarían, y al congelar y reproducir solo se verían las de la última (hallazgo
    del hito H1, T20). ``GisError`` ``gis.dataset_name_invalid`` si no queda ninguna letra ni
    cifra."""
    return {FIGURE_SCOPE_KEY: dataset_slug(name)}


SURFACE_SCOPE_KEY = "surface"
SECTOR_SCOPE_KEY = "sector"
"""Las claves del ámbito de una cifra de la 014 además del nombre: la superficie (``final`` o
``exploitation``) y el sector (su código)."""


def quarry_figure_scope(name: str, *, surface: Surface | str | None = None,
                        sector: str | None = None) -> dict[str, str]:
    """El ámbito de una cifra de la 014 (plan 014 §2.1; ``docs/trampas.md`` §6): el de
    :func:`figure_scope` y, si los tiene, la superficie ``surface`` (``Surface``) y el código del
    sector ``sector`` (sin él, la del total). Sin ellos, las cifras de las dos superficies o de
    dos sectores se pisarían. ``ValueError`` si la superficie no es una de las dos o el sector no
    es un texto con algo."""
    scope = figure_scope(name)
    if surface is not None:
        try:
            scope[SURFACE_SCOPE_KEY] = Surface(surface).value
        except ValueError:
            raise ValueError(f"la superficie de una cifra es «final» o «exploitation», no "
                             f"{surface!r}") from None
    if sector is not None:
        if not isinstance(sector, str) or not sector.strip():
            raise ValueError(f"el sector de una cifra es su código, no {sector!r}")
        scope[SECTOR_SCOPE_KEY] = sector
    return scope


SURFACE_SCOPE_NAMES: Mapping[str, Mapping[Surface, str]] = MappingProxyType({
    "es": MappingProxyType({Surface.FINAL: "final", Surface.EXPLOITATION: "explotación"}),
    "en": MappingProxyType({Surface.FINAL: "final", Surface.EXPLOITATION: "exploitation"})})
"""Cómo se ve la superficie del ámbito de una cifra de la 014 en cada idioma (T61, el H3: la barra N
decía «cantera, exploitation» en español). Lo que se guarda es el valor de :class:`Surface`."""


def figure_text(figure: FigureRecord, *, language: str = "es") -> str:
    """La cifra registrada ``figure`` como la lee una persona en ``language`` (la de
    ``FigureRecord.text``), con la superficie de su ámbito (:data:`SURFACE_SCOPE_KEY`, la de una
    cifra de la 014: ``final`` o ``exploitation``) en ese idioma (:data:`SURFACE_SCOPE_NAMES`):
    «Cota mínima de la superficie de la cantera · cantera, explotación = 188,9 m» (T61). La clave
    y el valor guardados no cambian; una cifra de otra spec, o cuyo ámbito no lleva una de las dos
    superficies (la de un ajuste lleva el nombre del dato), sale como ``FigureRecord.text``.
    ``ValueError`` con otro idioma."""
    if language not in SURFACE_SCOPE_NAMES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: "
                         f"{', '.join(SURFACE_SCOPE_NAMES)}")
    value = figure.scope.get(SURFACE_SCOPE_KEY)
    if not figure.key.startswith(f"{MODULE}.") or value not in _SURFACE_VALUES:
        return figure.text(language=language)
    scope = {key: (SURFACE_SCOPE_NAMES[language][Surface(item)] if key == SURFACE_SCOPE_KEY
                   else item) for key, item in figure.scope.items()}
    return replace(figure, scope=MappingProxyType(scope)).text(language=language)


_SURFACE_VALUES = frozenset(item.value for item in Surface)


def refit_figure_scope(name: str, surface: str) -> dict[str, str]:
    """El ámbito de la cifra ``des.refit_m3`` de la superficie ``surface`` (el nombre de su dato)
    en el ajuste ``name`` (spec 014, T32; plan 014 §5.2.3: «por superficie»): el de
    :func:`figure_scope` y, en la clave de la superficie (:data:`SURFACE_SCOPE_KEY`), el nombre del
    dato de la superficie que se ajusta: sin él, las de dos superficies se pisarían. ``ValueError``
    si falta."""
    scope = figure_scope(name)
    scope[SURFACE_SCOPE_KEY] = _named(surface, "de la superficie que se ajusta")
    return scope


def envelope_figures(*, name: str, cells: int, area_m2: float, min_m: float | None,
                     max_m: float | None, cut_m3: float | None, fill_m3: float | None
                     ) -> tuple[FigureSpec, ...]:
    """Las cifras CALCULADO de la envolvente ``name`` (RF-013-17), con el ámbito de
    :func:`figure_scope`, en el orden de :data:`ENVELOPE_FIGURES`: las celdas con envolvente, su
    área (m²), sus cotas mínima y máxima (m) y el desmonte y el terraplén (m³) frente a la
    superficie de partida. Sin celdas con envolvente no hay cota mínima ni máxima (``None``): esa
    cifra no existe y no se da; y sin superficie de partida (unas semillas de cota fija o de una
    rejilla de cotas) tampoco hay desmonte ni terraplén (``None``). Un valor que no es finito es
    un error del programa (``ValueError``)."""
    scope = figure_scope(name)
    found = [FigureSpec("des.env_cells", _count("des.env_cells", cells), "-", scope=scope),
             FigureSpec("des.env_area_m2", _finite("des.env_area_m2", area_m2), "m2",
                        scope=scope)]
    for key, value in (("des.env_min_m", min_m), ("des.env_max_m", max_m)):
        if value is not None:
            found.append(FigureSpec(key, _finite(key, value), "m", scope=scope))
    for key, value in (("des.env_cut_m3", cut_m3), ("des.env_fill_m3", fill_m3)):
        if value is not None:
            found.append(FigureSpec(key, _finite(key, value), "m3", scope=scope))
    return tuple(found)


def design_figures(report: DesignReport, *, name: str, berm_count: int
                   ) -> tuple[FigureSpec, ...]:
    """Las cifras CALCULADO del escalonado ``name`` (RF-013-30, RF-013-31), con el ámbito de
    :func:`figure_scope`, en el orden de :data:`DESIGN_FIGURES`, del informe ``report``
    (``design.report.DesignReport``) y del número de bermas de su tabla (``berm_count``). Sin
    celdas con movimiento el informe no tiene inclinación (``None``): esas cifras no existen y no
    se dan. Un valor que no es finito es un error del programa (``ValueError``)."""
    scope = figure_scope(name)
    found = [FigureSpec(CUT_M3, _finite(CUT_M3, report.cut_m3), "m3", scope=scope),
             FigureSpec(FILL_M3, _finite(FILL_M3, report.fill_m3), "m3", scope=scope),
             FigureSpec("des.moved_area_m2", _finite("des.moved_area_m2", report.moved_area_m2),
                        "m2", scope=scope)]
    for key, value in (("des.slope_p90_deg", report.slope_p90_deg),
                       ("des.slope_p99_deg", report.slope_p99_deg),
                       ("des.slope_max_deg", report.slope_max_deg)):
        if value is not None:
            found.append(FigureSpec(key, _finite(key, value), "deg", scope=scope))
    found += [FigureSpec("des.edge_step_max_m",
                         _finite("des.edge_step_max_m", report.edge_step_max_m), "m",
                         scope=scope),
              FigureSpec("des.berm_count", _count("des.berm_count", berm_count), "-",
                         scope=scope),
              FigureSpec("des.nodata_area_m2",
                         _finite("des.nodata_area_m2", report.nodata_area_m2), "m2",
                         scope=scope)]
    return tuple(found)


ENTITY_SCOPE_KEY = "entity"
"""La clave del ámbito de una cifra de las entidades además del nombre: el código de la entidad
(``PLT-001``; inmutable por versión: no cambia al renombrarla)."""


_LIVE_PLATFORM = (
    "SELECT 1 FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
    "WHERE r.version_uid = ? AND o.op_type = ? AND o.status = 'done' AND o.superseded_by IS NULL LIMIT 1")


def has_platform_operation(conn: sqlite3.Connection, version_uid: str) -> bool:
    """Si la versión ``version_uid`` (su uid) tiene **alguna** operación ``des.platform`` hecha y sin sustituir, en
    cualquier revisión (spec 015, T38): sin ella ninguna entidad está viva y calculada. Una sola consulta, sin
    cargar nada de las entidades: es lo primero que mira el gancho de la declaración pendiente
    (``gis.masks.declaring``) cada vez que se pregunta por el estado de las máscaras, también al dibujar la
    interfaz. Solo lee."""
    return conn.execute(_LIVE_PLATFORM, (version_uid, PLATFORM)).fetchone() is not None


def entity_figure_scope(name: str, code: str) -> dict[str, str]:
    """El ámbito de una cifra de las entidades (spec 015, T04; plan 015 §5.2.3; ``docs/trampas.md``
    §6): el de :func:`figure_scope` (el nombre de la operación en ASCII, único en la versión) y, en
    :data:`ENTITY_SCOPE_KEY`, el código de la entidad ``code``: el de la propia entidad en las cifras
    de la plataforma y el de **la entidad en la que se apoya** en ``des.supported_m3``. Sin él, las
    cifras de dos entidades se pisarían (la vigente de una clave es la última de cada ámbito,
    RF-009-20). ``ValueError`` si ``code`` no es el código de una entidad (``PLT-001``);
    ``GisError`` ``gis.dataset_name_invalid`` si el nombre no tiene letras ni cifras."""
    scope = figure_scope(name)
    entity_segment(code)  # el código de una entidad (ValueError, TypeError)
    scope[ENTITY_SCOPE_KEY] = code
    return scope


def _non_negative(key: str, value: object) -> float:
    """``value`` como real finito y no negativo (un volumen, un área, una longitud)."""
    number = _finite(key, value)
    if number < 0:
        raise ValueError(f"la cifra «{key}» no admite un valor negativo: {value!r}")
    return number


def platform_figures(name: str, code: str, values: Mapping[str, float | None]
                     ) -> tuple[FigureSpec, ...]:
    """Las cifras CALCULADO de la plataforma ``name`` de código ``code`` (RF-015-24; plan 015
    §5.2.3), con el ámbito de :func:`entity_figure_scope`, en el orden de :data:`PLATFORM_FIGURES`
    y con su unidad: ``values`` da cada una por su clave (las doce, ninguna de más ni de menos). Una
    que no existe (``None``: sin celdas fuera de la rasante no hay diferencia máxima; sin
    relleno, no hay pared) no se registra; las que no admiten negativos (todas salvo las cotas)
    rechazan uno. Un valor que no es finito es un error del programa (``ValueError``)."""
    declared = {figure.key: figure for figure in PLATFORM_FIGURES}
    given = _mapping(values, "las cifras de una plataforma")
    extra = sorted(str(key) for key in given if key not in declared)
    if extra:
        raise ValueError(f"{', '.join(extra)} no son cifras de una plataforma: son "
                         f"{', '.join(declared)}")
    missing = [key for key in declared if key not in given]
    if missing:
        raise ValueError(f"faltan las cifras de la plataforma «{name}»: {', '.join(missing)} "
                         "(las que no existen se dan como None)")
    scope = entity_figure_scope(name, code)
    found = []
    for key, figure in declared.items():
        value = given[key]
        if value is None:
            continue
        number = _finite(key, value) if figure.allow_negative else _non_negative(key, value)
        found.append(FigureSpec(key, number, figure.unit, scope=scope))
    return tuple(found)


SUPPORT_REF_SEPARATOR = "#"
"""Lo que separa, en la referencia de un **acopio** (``STK-001#m07``), el código de su detección de la clave de su marca (spec 016,
T15; P-1, ADR-0031 §4): el código de una entidad no lleva ``#`` y la clave de una marca (su nombre) puede llevarlo, así que se
parte por el primero."""


def support_ref(code: str, stockpile: str | None = None) -> str:
    """La referencia de aquello en lo que se apoya una operación (spec 016, T15; plan 016 §5.2.3 «Dependencias», A13; P-1): el código
    de la entidad (``PLT-001``) o, de un **acopio**, el de su detección y la clave de su marca (``STK-001#m07``, el que ``des.supported_m3``
    lleva en su ámbito como ``entity`` y ``stockpile``). ``ValueError`` si ``code`` no es de una entidad o la clave está en blanco (no
    cita ningún acopio); sin clave (``None``), el código tal cual."""
    entity_segment(code)  # el código de una entidad (ValueError, TypeError)
    if stockpile is None:
        return code
    if not isinstance(stockpile, str) or not stockpile.strip():
        raise ValueError(f"la clave de un acopio es un texto con algo, no {stockpile!r}")
    return f"{code}{SUPPORT_REF_SEPARATOR}{stockpile}"


def split_support_ref(ref: str) -> tuple[str, str | None]:
    """El código de la entidad y la clave del acopio de una referencia de :func:`support_ref` (``"STK-001#m07"`` →
    ``("STK-001", "m07")``; ``"PLT-001"`` → ``("PLT-001", None)``), partida por el primer ``#``. ``ValueError`` si el código no es el
    de una entidad o hay ``#`` y la clave está en blanco."""
    code, separator, key = ref.partition(SUPPORT_REF_SEPARATOR)
    stockpile = key if separator else None
    support_ref(code, stockpile)  # los mismos rechazos
    return code, stockpile


def supported_figures(name: str, volumes: Mapping[str, float]) -> tuple[FigureSpec, ...]:
    """Las cifras ``des.supported_m3`` de la operación ``name`` (spec 015, T04; RF-015-15; ADR-0030
    §4): una por entidad en la que se apoya, por orden de código, con el volumen apoyado (m³; cero
    si lo declara el usuario y no rellena nada) y el ámbito de :func:`entity_figure_scope` con **esa**
    entidad (``volumes``: código → volumen). **Una por acopio** (spec 016, T15; RF-016-14, P-1): si la clave es la
    referencia de un acopio (:func:`support_ref`, ``STK-001#m07``), el ámbito es el de :func:`stockpile_figure_scope`: la entidad (la
    detección) **y la clave del acopio** (sin ella, las cifras de dos acopios de una detección se pisarían, RF-009-20). Sin
    entidades, ninguna. ``ValueError`` si un volumen no es un número finito y no negativo o un código no es el de una
    entidad."""
    scope_of: dict[str, dict[str, str]] = {}
    for ref in volumes:
        code, stockpile = split_support_ref(ref)
        scope_of[ref] = (entity_figure_scope(name, code) if stockpile is None
                         else stockpile_figure_scope(name, code, stockpile))
    return tuple(FigureSpec(SUPPORTED_M3, _non_negative(SUPPORTED_M3, volumes[ref]), "m3",
                            scope=scope_of[ref])
                 for ref in sorted(scope_of))


def declare_figures(count: int) -> tuple[FigureSpec, ...]:
    """La cifra ``des.declared_count`` de ``des.declare_constraints`` (RF-015-10): cuántas
    restricciones declara la versión (un entero no negativo; cero si ninguna entidad protege), sin
    ámbito: hay una declaración por versión."""
    return (FigureSpec(DECLARED_COUNT, _count(DECLARED_COUNT, count), "-"),)


# --- Los ajustes: guardarlos y leerlos ---------------------------------------------------------


def _bound(domain: WorkDomain) -> str:
    sectors, layer = bool(domain.sectors), domain.layer is not None
    if sectors and layer:
        return _BOUND_BOTH
    return _BOUND_SECTORS if sectors else _BOUND_LAYER if layer else _BOUND_ALL


def _codes(values: Iterable[str], what: str) -> list[str]:
    if isinstance(values, str | bytes) or not isinstance(values, Iterable):
        raise TypeError(f"{what} son una lista de códigos, no {values!r}")
    found = list(values)
    for item in found:
        if not isinstance(item, str):
            raise TypeError(f"{what} son textos, no {item!r}")
    return found


def envelope_settings(request: EnvelopeRequest, pending_sectors: Iterable[str] = (),
                      touched_sectors: Iterable[str] = ()) -> dict[str, Any]:
    """Los ajustes de ``des.envelope`` (``gb_operation.settings``; JSON sin rutas): lo que la
    vuelve a pedir igual con sus entradas —el nombre, la dirección, la métrica, el alcance (m), el
    modo y el valor de la pendiente (°), el factor de malla, el origen de las semillas con su
    zona, el acotado del dominio y los perfiles asignados (el base y el de cada sector, que la
    pendiente por sectores necesita para recalcular y reproducir)— y, para la marca de RF-013-06,
    los sectores sin búsqueda vigente al calcular (``pending_sectors``: sus códigos) y los que tocó
    el dominio de trabajo (``touched_sectors``: con ellos y los pendientes de ahora se dice
    «búsqueda de intocables pendiente», ``design.sectors.pending_marks``). Es un diccionario
    nuevo."""
    seeds, domain = request.seeds, request.domain
    zone = seeds.zone
    return {
        "name": request.name,
        "direction": Direction(request.direction).value,
        "metric": Metric(request.metric).value,
        "reach_m": request.reach_m,
        "slope_mode": SlopeMode(request.slope_mode).value,
        "slope_deg": request.slope_deg,
        "mesh_factor": request.mesh_factor,
        "seeds": {
            "kind": SeedKind(seeds.kind).value, "surface": seeds.surface,
            "zone": None if zone is None else {"kind": ZoneKind(zone.kind).value,
                                               "name": zone.name},
            "elevation_m": seeds.elevation_m, "grid": seeds.grid},
        "domain": {"bound": _bound(domain), "sectors": list(domain.sectors),
                   "layer": domain.layer},
        "base_profile": request.base_profile or "",
        "sector_profiles": dict(request.sector_profiles),
        "pending_sectors": _codes(pending_sectors, "los sectores pendientes"),
        "touched_sectors": _codes(touched_sectors, "los sectores que toca el dominio"),
    }


def design_settings(request: DesignRequest, surface: str, pending_sectors: Iterable[str] = (),
                    touched_sectors: Iterable[str] = (), previous: Mapping[str, Any] | None = None
                    ) -> dict[str, Any]:
    """Los ajustes de ``des.stepped_design`` (JSON sin rutas): el nombre, la envolvente que se
    escalona (el nombre de su operación), la superficie de partida ``surface`` (el nombre de su
    dato: la petición no la lleva), el sentido, el perfil base, el perfil de cada sector (por
    código de sector, en su orden), de dónde sale el ancla, los sectores sin búsqueda vigente al
    calcular y los que tocó el dominio (RF-013-06; véase :func:`envelope_settings`) y lo
    ``previous``: la operación del mismo tipo y nombre de la revisión congelada más reciente con
    la que se comparó el desmonte y el terraplén (``operation``, ``revision``, ``cut_m3`` y
    ``fill_m3``; D-25), que guarda lo que vio para repetirlo igual al reproducir. Es un
    diccionario nuevo."""
    anchor = request.anchor_grid
    return {
        "name": request.name,
        "envelope": request.envelope,
        "surface": surface,
        "sense": BenchSense(request.sense).value,
        "base_profile": request.base_profile,
        "sector_profiles": dict(request.sector_profiles),
        "anchor": {"source": _ANCHOR_PROFILE if anchor is None else _ANCHOR_GRID,
                   "grid": anchor},
        "pending_sectors": _codes(pending_sectors, "los sectores pendientes"),
        "touched_sectors": _codes(touched_sectors, "los sectores que toca el dominio"),
        "previous": None if previous is None else _previous(previous),
    }


def excavation_area_settings(name: str, surface: str) -> dict[str, Any]:
    """Los ajustes de ``des.excavation_area`` (spec 014, T06; RF-014-01; JSON sin rutas): el
    nombre de la operación y la superficie de partida ``surface`` (el nombre de su dato), lo que
    la vuelve a pedir igual con sus entradas. Es un diccionario nuevo; ``ValueError`` si falta
    alguno de los dos."""
    return {"name": _named(name, "del recinto"),
            "surface": _named(surface, "de la superficie de partida")}


def excavation_area_start(settings: Mapping[str, Any]) -> tuple[str, str]:
    """El nombre y la superficie de partida que guardan unos ajustes de ``des.excavation_area``
    (:func:`excavation_area_settings`). ``ValueError`` si no los llevan."""
    what = "los ajustes de un recinto"
    data = _mapping(settings, what)
    return _required_text(data, "name", what), _required_text(data, "surface", what)


def transition_settings(name: str, surface: str, start: str) -> dict[str, Any]:
    """Los ajustes de ``des.edge_transition`` (spec 014, T28; RF-014-19, RF-014-29; JSON sin
    rutas): el nombre de la operación, la superficie de diseño que se une con el terreno no
    afectado (``surface``, el nombre de su dato) y la superficie de partida ``start`` (el de la
    suya), lo que la vuelve a pedir igual con sus entradas. Es un diccionario nuevo; ``ValueError``
    si falta alguno."""
    return {"name": _named(name, "de la transición"),
            "surface": _named(surface, "de la superficie de diseño"),
            "start": _named(start, "de la superficie de partida")}


def transition_start(settings: Mapping[str, Any]) -> tuple[str, str, str]:
    """El nombre, la superficie de diseño y la superficie de partida que guardan unos ajustes de
    ``des.edge_transition`` (:func:`transition_settings`). ``ValueError`` si no los llevan."""
    what = "los ajustes de una transición"
    data = _mapping(settings, what)
    return (_required_text(data, "name", what), _required_text(data, "surface", what),
            _required_text(data, "start", what))


def _seeds_settings(source: SeedSource | None) -> dict[str, Any]:
    """Las semillas de un lado de la cantera: :data:`CROWN_SEEDS` sin ``source`` o las de la 013
    con su zona."""
    if source is None:
        return {"kind": CROWN_SEEDS}
    zone = source.zone
    return {"kind": SeedKind(source.kind).value, "surface": source.surface,
            "zone": None if zone is None else {"kind": ZoneKind(zone.kind).value,
                                               "name": zone.name},
            "elevation_m": source.elevation_m, "grid": source.grid}


def _side_settings_of(side: QuarrySide) -> dict[str, Any]:
    """Lo de un lado de la cantera (``final`` o ``exploitation``) en sus ajustes."""
    return {"base_profile": side.base_profile, "sector_profiles": dict(side.sector_profiles),
            "seeds": _seeds_settings(side.seeds), "anchor": AnchorMode(side.anchor).value,
            "anchor_grid": side.anchor_grid, "metric": Metric(side.metric).value}


def _layer_field(value: LayerField | None) -> dict[str, str] | None:
    return None if value is None else {"layer": value.layer, "field": value.field}


def quarry_settings(request: QuarryRequest, pending_sectors: Iterable[str] = (),
                    touched_sectors: Iterable[str] = (),
                    previous: Mapping[Surface | str, Mapping[str, Any]] | None = None
                    ) -> dict[str, Any]:
    """Los ajustes de ``des.quarry`` (spec 014, T19; RF-014-29, RF-014-31; JSON sin rutas): lo que
    la vuelve a pedir igual con sus entradas —el nombre, la superficie de partida, el orden, cada
    lado (``final`` y ``exploitation``: el perfil base y el de cada sector, las semillas —
    :data:`CROWN_SEEDS` o las de la 013 con su zona—, el ancla con su rejilla y la métrica), las
    capas con sus campos (fondos, zonas a conservar, corredores, zonas de restauración por relleno
    y láminas de agua) y «explotación hasta la final» con su capa—, con las claves de
    :data:`QUARRY_SETTINGS`; y, como en :func:`envelope_settings`, los sectores sin búsqueda
    vigente al calcular y los que tocó el recinto (RF-014-30); y, como en :func:`design_settings`,
    lo ``previous`` con que se comparó **cada lado** (T51; D-25 de la 013): por superficie
    (``final`` y ``exploitation``), su ``operation``, ``revision``, ``cut_m3`` y ``fill_m3``, los
    del mismo lado de la cantera del mismo nombre de la revisión congelada más reciente; ``None``
    si no se comparó (:func:`settings_previous` con la superficie lo lee). Es un diccionario
    nuevo; ``ValueError`` si ``previous`` no trae los dos lados con esa forma."""
    corridors = request.corridors
    return {
        "name": request.name,
        "start": request.start,
        "order": Order(request.order).value,
        Surface.FINAL.value: _side_settings_of(request.final),
        Surface.EXPLOITATION.value: _side_settings_of(request.exploitation),
        "floors": _layer_field(request.floors),
        "conserve": [{"kind": ZoneKind(zone.kind).value, "name": zone.name}
                     for zone in request.conserve],
        "corridors": None if corridors is None else {
            "layer": corridors.layer, "width_field": corridors.width_field,
            "level_field": corridors.level_field,
            "start_level_field": corridors.start_level_field,
            "gradient_field": corridors.gradient_field},
        "fill_zones": request.fill_zones,
        "water": _layer_field(request.water),
        "to_final": ToFinalMode(request.to_final).value,
        "to_final_layer": request.to_final_layer,
        "pending_sectors": _codes(pending_sectors, "los sectores pendientes"),
        "touched_sectors": _codes(touched_sectors, "los sectores que toca el recinto"),
        "previous": None if previous is None else _sides_previous(previous),
    }


def _sides_previous(value: Mapping[Surface | str, Mapping[str, Any]]) -> dict[str, Any]:
    """Lo anterior con que se comparó cada lado de una cantera (T51), comprobado: los dos lados,
    cada uno como :func:`_previous`, y nada más."""
    what = "lo anterior con que se comparó la cantera"
    data = {Surface(key).value: item for key, item in _mapping(value, what).items()}
    if sorted(data) != sorted(side.value for side in Surface):
        raise ValueError(f"{what} lleva los dos lados ({', '.join(s.value for s in Surface)}), "
                         f"no {sorted(data)}")
    return {side.value: _previous(data[side.value]) for side in Surface}


def fill_only_settings(request: FillOnlyRequest, pending_sectors: Iterable[str] = (),
                       touched_sectors: Iterable[str] = (),
                       previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Los ajustes de ``des.fill_only`` (spec 014, T30; RF-014-22 a RF-014-24, RF-014-29; JSON sin
    rutas): los de su escalonado de la 013 (:func:`design_settings`: el nombre, la envolvente, la
    superficie de partida en ``surface``, el perfil base y el de cada sector, el ancla, los
    sectores pendientes y los que toca el dominio, y lo ``previous`` con que se comparó, D-25)
    **sin el sentido**, que siempre es relleno (:data:`FILL_ONLY_SETTINGS`), y la capa de las
    láminas de agua con su campo (``water``; ``None`` sin láminas). Es un diccionario nuevo."""
    settings = design_settings(request.design, request.start, pending_sectors, touched_sectors,
                               previous)
    del settings["sense"]
    settings["water"] = _layer_field(request.water)
    return settings


def refit_part(surface: str) -> str:
    """Lo que distingue en el nombre de su salida la superficie ajustada ``surface`` (el nombre de
    su dato) de las demás de un ajuste (spec 014, T32; plan 014 §5.2.3,
    ``des_adj_<n>_<sup>_<vNN>``): su nombre sin el prefijo ``des_`` (``des_exp_corta`` →
    ``exp_corta``). ``ValueError`` si falta."""
    found = _named(surface, "de la superficie que se ajusta")
    return found[len(_PREFIX):] if found.startswith(_PREFIX) else found


def refit_output(name: str, surface: str) -> str:
    """El nombre del dato de la superficie ``surface`` ajustada por el ajuste ``name`` (spec 014,
    T32; plan 014 §5.2.3): ``des_adj_<nombre>_<superficie>`` (:func:`dataset_name` de
    ``f"{name} {refit_part(surface)}"``; con el código de la versión en su ubicación). ``GisError``
    ``gis.dataset_name_invalid`` si el nombre no tiene ninguna letra ni cifra."""
    return dataset_name(REFIT_GRID, f"{name} {refit_part(surface)}")


def refit_settings(request: RefitRequest,
                   faces: Mapping[str, Mapping[str, object]] | None = None) -> dict[str, Any]:
    """Los ajustes de ``des.refit`` (spec 014, T32; RF-014-27, RF-014-29; JSON sin rutas): el
    nombre de la operación, las superficies de diseño que se ajustan (los nombres de sus datos, en
    su orden) y la superficie de partida ``start`` (la que lee la comprobación contra un límite
    nuevo de sus salidas, T31), lo que lo vuelve a pedir igual con sus entradas. El ángulo que
    traiga una petición por guion no se guarda (es la cara del perfil de cada superficie, P-3).

    Con ``faces`` (T49, hallazgo F-10: superficie → clave ``des.bench.{p}.…`` → valor), también la
    cara y el factor de malla con que se ajusta cada superficie, los que anotó la operación que
    hizo su diseño (``faces``, en el orden de las superficies): lo que el ajuste usó, no lo que
    vale hoy el perfil; :func:`refit_request` no lo lee (un recálculo los vuelve a leer de esa
    operación). Es un diccionario nuevo; ``ValueError`` si falta algún nombre o la cara de alguna
    superficie."""
    settings: dict[str, Any] = {
        "name": _named(request.name, "del ajuste"),
        "surfaces": [_named(surface, "de la superficie que se ajusta")
                     for surface in request.surfaces],
        "start": _named(request.start, "de la superficie de partida")}
    if faces is not None:
        missing = [surface for surface in request.surfaces if surface not in faces]
        if missing:
            raise ValueError(f"falta la cara con que se ajusta {', '.join(missing)}")
        settings["faces"] = {surface: dict(faces[surface]) for surface in request.surfaces}
    return settings


def _mapping(value: object, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{what} es un diccionario, no {value!r}")
    return value


def _required_text(data: Mapping[str, Any], key: str, what: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} lleva «{key}» (un texto), no {value!r}")
    return value


def _optional_text(data: Mapping[str, Any], key: str, what: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{what} lleva «{key}» como un texto o nada, no {value!r}")
    return value


def _number(data: Mapping[str, Any], key: str, what: str, *, required: bool = False
            ) -> float | None:
    value = data.get(key)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Real) \
            or not math.isfinite(float(value)):
        raise ValueError(f"{what} lleva «{key}» como un número finito, no {value!r}")
    return float(value)


def _enum[E: StrEnum](kind: type[E], data: Mapping[str, Any], key: str, what: str) -> E:
    value = data.get(key)
    try:
        return kind(value)
    except ValueError:
        options = ", ".join(item.value for item in kind)
        raise ValueError(f"{what} lleva «{key}» como uno de {options}, no {value!r}") from None


def _list(data: Mapping[str, Any], key: str, what: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{what} lleva «{key}» como una lista de textos, no {value!r}")
    return tuple(value)


def envelope_request(settings: Mapping[str, Any]) -> EnvelopeRequest:
    """La envolvente que repiten los ajustes ``settings`` de una operación ``des.envelope`` (los
    de :func:`envelope_settings`): al recalcularla y al reproducirla. ``ValueError`` si no son
    los de una envolvente (nombrando el campo)."""
    what = "los ajustes de una envolvente"
    data = _mapping(settings, what)
    seeds = _mapping(data.get("seeds"), f"{what}, «seeds»,")
    zone = seeds.get("zone")
    if zone is not None:
        zone_data = _mapping(zone, f"{what}, «seeds.zone»,")
        zone = Zone(_enum(ZoneKind, zone_data, "kind", f"{what}, «seeds.zone»,"),
                    _optional_text(zone_data, "name", f"{what}, «seeds.zone»,"))
    domain = _mapping(data.get("domain"), f"{what}, «domain»,")
    mesh = _number(data, "mesh_factor", what, required=True)
    assert mesh is not None
    profiles = _profiles(data, what)
    return EnvelopeRequest(
        name=_required_text(data, "name", what),
        direction=_enum(Direction, data, "direction", what),
        seeds=SeedSource(
            _enum(SeedKind, seeds, "kind", f"{what}, «seeds»,"),
            surface=_optional_text(seeds, "surface", f"{what}, «seeds»,"), zone=zone,
            elevation_m=_number(seeds, "elevation_m", f"{what}, «seeds»,"),
            grid=_optional_text(seeds, "grid", f"{what}, «seeds»,")),
        slope_mode=_enum(SlopeMode, data, "slope_mode", what),
        slope_deg=_number(data, "slope_deg", what),
        metric=_enum(Metric, data, "metric", what),
        mesh_factor=mesh,
        reach_m=_number(data, "reach_m", what),
        domain=WorkDomain(sectors=_list(domain, "sectors", f"{what}, «domain»,"),
                          layer=_optional_text(domain, "layer", f"{what}, «domain»,")),
        base_profile=_optional_text(data, "base_profile", what) or None,
        sector_profiles=profiles)


def _profiles(data: Mapping[str, Any], what: str) -> dict[str, str]:
    """El perfil de cada sector de unos ajustes (ninguno si no los llevan)."""
    found = _mapping(data.get("sector_profiles", {}), f"{what}, «sector_profiles»,")
    for sector, profile in found.items():
        if not isinstance(sector, str) or not isinstance(profile, str):
            raise ValueError(f"{what} llevan, por sector, el código de su perfil, no "
                             f"{sector!r}: {profile!r}")
    return dict(found)


def design_request(settings: Mapping[str, Any]) -> DesignRequest:
    """El escalonado que repiten los ajustes ``settings`` de una operación ``des.stepped_design``
    (los de :func:`design_settings`; la superficie de partida, con :func:`design_start`).
    ``ValueError`` si no son los de un escalonado (nombrando el campo)."""
    what = "los ajustes de un escalonado"
    data = _mapping(settings, what)
    _mapping(data.get("sector_profiles"), f"{what}, «sector_profiles»,")
    profiles = _profiles(data, what)
    anchor = _mapping(data.get("anchor"), f"{what}, «anchor»,")
    source = anchor.get("source")
    if source not in (_ANCHOR_PROFILE, _ANCHOR_GRID):
        raise ValueError(f"{what} llevan el ancla «{_ANCHOR_PROFILE}» o «{_ANCHOR_GRID}», no "
                         f"{source!r}")
    grid = _optional_text(anchor, "grid", f"{what}, «anchor»,")
    if (source == _ANCHOR_GRID) != (grid is not None):
        raise ValueError(f"{what} llevan la rejilla de anclas si y solo si el ancla es "
                         f"«{_ANCHOR_GRID}»")
    return DesignRequest(
        name=_required_text(data, "name", what),
        envelope=_required_text(data, "envelope", what),
        sense=_enum(BenchSense, data, "sense", what),
        base_profile=_required_text(data, "base_profile", what),
        sector_profiles=dict(profiles), anchor_grid=grid)


def design_start(settings: Mapping[str, Any]) -> str:
    """El nombre del dato de la superficie de partida de unos ajustes de escalonado
    (:func:`design_settings`). ``ValueError`` si no lo llevan."""
    what = "los ajustes de un escalonado"
    return _required_text(_mapping(settings, what), "surface", what)


def _zone_of(value: object, what: str) -> Zone | None:
    if value is None:
        return None
    data = _mapping(value, what)
    return Zone(_enum(ZoneKind, data, "kind", what), _optional_text(data, "name", what))


def _seeds_of(value: object, what: str, label: str) -> SeedSource | None:
    here = f"{what}, «{label}»,"
    data = _mapping(value, here)
    if data.get("kind") == CROWN_SEEDS:
        return None
    return SeedSource(
        _enum(SeedKind, data, "kind", here), surface=_optional_text(data, "surface", here),
        zone=_zone_of(data.get("zone"), f"{what}, «{label}.zone»,"),
        elevation_m=_number(data, "elevation_m", here), grid=_optional_text(data, "grid", here))


def _side_of(data: Mapping[str, Any], side: Surface, what: str) -> QuarrySide:
    here = f"{what}, «{side.value}»,"
    found = _mapping(data.get(side.value), here)
    return QuarrySide(
        base_profile=_required_text(found, "base_profile", here),
        sector_profiles=_profiles(found, here),
        seeds=_seeds_of(found.get("seeds"), what, f"{side.value}.seeds"),
        anchor=_enum(AnchorMode, found, "anchor", here),
        anchor_grid=_optional_text(found, "anchor_grid", here),
        metric=_enum(Metric, found, "metric", here))


def _layer_field_of(value: object, what: str) -> LayerField | None:
    if value is None:
        return None
    data = _mapping(value, what)
    return LayerField(_required_text(data, "layer", what), _required_text(data, "field", what))


def quarry_request(settings: Mapping[str, Any]) -> QuarryRequest:
    """La cantera que repiten los ajustes ``settings`` de una operación ``des.quarry`` (los de
    :func:`quarry_settings`): al recalcularla y al reproducirla. ``ValueError`` si no son los de
    una cantera (nombrando el campo; también lo que rechaza la petición: un lado con la rejilla de
    anclas sin el ancla en rejilla, un corredor sin cota ni rasante…)."""
    what = "los ajustes de una cantera"
    data = _mapping(settings, what)
    corridors = data.get("corridors")
    corridor_fields = None
    if corridors is not None:
        here = f"{what}, «corridors»,"
        found = _mapping(corridors, here)
        corridor_fields = CorridorFields(
            _required_text(found, "layer", here), _required_text(found, "width_field", here),
            level_field=_optional_text(found, "level_field", here),
            start_level_field=_optional_text(found, "start_level_field", here),
            gradient_field=_optional_text(found, "gradient_field", here))
    conserve = data.get("conserve", [])
    if not isinstance(conserve, list):
        raise ValueError(f"{what} llevan «conserve» como una lista de zonas, no {conserve!r}")
    zones = tuple(_zone_of(item, f"{what}, «conserve»,") for item in conserve)
    return QuarryRequest(
        name=_required_text(data, "name", what),
        start=_required_text(data, "start", what),
        final=_side_of(data, Surface.FINAL, what),
        exploitation=_side_of(data, Surface.EXPLOITATION, what),
        order=_enum(Order, data, "order", what),
        floors=_layer_field_of(data.get("floors"), f"{what}, «floors»,"),
        conserve=tuple(zone for zone in zones if zone is not None),
        corridors=corridor_fields,
        fill_zones=_optional_text(data, "fill_zones", what),
        water=_layer_field_of(data.get("water"), f"{what}, «water»,"),
        to_final=_enum(ToFinalMode, data, "to_final", what),
        to_final_layer=_optional_text(data, "to_final_layer", what))


def fill_only_request(settings: Mapping[str, Any]) -> FillOnlyRequest:
    """El diseño «solo relleno» que repiten los ajustes ``settings`` de una operación
    ``des.fill_only`` (los de :func:`fill_only_settings`): al recalcularlo y al reproducirlo.
    ``ValueError`` si no son los de un diseño «solo relleno» (nombrando el campo: los de su
    escalonado, como :func:`design_request`, y la capa de láminas sin su campo)."""
    what = "los ajustes de un diseño «solo relleno»"
    data = _mapping(settings, what)
    design = design_request({**data, "sense": BenchSense.FILL.value})
    return FillOnlyRequest(design.name, design.envelope, design_start(data), design.base_profile,
                           design.sector_profiles, design.anchor_grid,
                           _layer_field_of(data.get("water"), f"{what}, «water»,"))


def refit_request(settings: Mapping[str, Any]) -> RefitRequest:
    """El ajuste que repiten los ajustes ``settings`` de una operación ``des.refit`` (los de
    :func:`refit_settings`): al recalcularlo. ``ValueError`` si no son los de un ajuste (nombrando
    el campo)."""
    what = "los ajustes de un ajuste a un límite nuevo"
    data = _mapping(settings, what)
    return RefitRequest(_required_text(data, "name", what), _list(data, "surfaces", what),
                        _required_text(data, "start", what))


def refit_source(settings: Mapping[str, Any], output: str) -> str | None:
    """La superficie de la que sale la superficie ajustada ``output`` (el nombre de su dato) de
    la operación ``des.refit`` de ajustes ``settings``: la de su lista cuya salida
    (:func:`refit_output`) se llama así; ``None`` si ninguna. ``ValueError`` si no son los ajustes
    de un ajuste."""
    request = refit_request(settings)
    for surface in request.surfaces:
        if refit_output(request.name, surface) == output:
            return surface
    return None


# --- Los ajustes de las entidades (spec 015, T04) ---------------------------------------------


def platform_settings(request: PlatformRequest, code: str) -> dict[str, Any]:
    """Los ajustes de ``des.platform`` (spec 015, T04; RF-015-02, RF-015-19; JSON sin rutas): el
    nombre de la plataforma, su ``code`` (``PLT-001``) y los campos de su capa de los que salieron
    sus valores iniciales y el enlace de su eje (``fields``: la cota inicial, la pendiente, el
    ancho, el campo del eje y la capa de ese eje; ``None`` los que no lleva). **Ninguna otra cosa**:
    la capa, la geometría, la partida, el modo, el borde y lo demás son **parámetros de la
    entidad** (``des.platform.{e}.*``, :func:`platform_values`): guardarlos aquí los duplicaría y
    cambiar uno no cambiaría el otro. Lo único que se añade después es la contrapendiente que la
    persona confirmó al crear (:data:`COUNTERSLOPE_CONFIRMED`; T15), que se decide tras calcular. Es un
    diccionario nuevo; ``ValueError`` si ``code`` no es el de una entidad."""
    if not isinstance(request, PlatformRequest):
        raise TypeError(f"los ajustes de una plataforma salen de una PlatformRequest, no "
                        f"{request!r}")
    entity_segment(code)
    fields = request.fields
    return {
        "name": request.name,
        "code": code,
        "fields": {
            "start_level_field": fields.start_level_field,
            "gradient_field": fields.gradient_field,
            "width_field": fields.width_field,
            "axis_field": fields.axis_field,
            "axis_layer": fields.axis_layer,
        },
    }


def platform_code(settings: Mapping[str, Any]) -> str:
    """El código de la entidad que guardan unos ajustes de ``des.platform``
    (:func:`platform_settings`). ``ValueError`` si no lo llevan o no es el de una entidad."""
    what = "los ajustes de una plataforma"
    code = _required_text(_mapping(settings, what), "code", what)
    entity_segment(code)
    return code


COUNTERSLOPE_CONFIRMED = "counterslope_confirmed"
"""La clave de los ajustes de ``des.platform`` donde queda la contrapendiente que la persona confirmó
expresamente al crearla (RF-015-23; spec 015, T15; decisión de la sesión principal, revisable):
:class:`CounterslopeConfirmation`. No es de :func:`platform_settings` (que no la conoce: se confirma
después de calcular): la añade quien crea (``entity_store.create_platform``) y la arrastra el recálculo."""


@dataclass(frozen=True, slots=True)
class CounterslopeConfirmation:
    """La contrapendiente de una plataforma que la persona confirmó al crearla (RF-015-23): su cuantía
    (``amount_m``, m: la del peor tramo del perfil) y su abscisa (``abscissa_m``, m), quién la confirmó
    (``decided_by``) y cuándo (``decided_on``, UTC). Un recálculo la reutiliza solo si la contrapendiente
    nueva no pasa de la confirmada más la tolerancia (:meth:`covers`); si pasa, vuelve a pedirla."""

    amount_m: float
    abscissa_m: float
    decided_by: str
    decided_on: str

    def covers(self, rise_m: float, tolerance_m: float) -> bool:
        """Si la contrapendiente ``rise_m`` (m) del recálculo entra en lo confirmado: no pasa de la cuantía
        confirmada más la tolerancia ``tolerance_m`` de la entidad (``counter_tol_m``)."""
        return rise_m <= self.amount_m + tolerance_m

    def settings(self) -> dict[str, Any]:
        """Lo que se anota en los ajustes de la operación (JSON)."""
        return {"amount_m": self.amount_m, "abscissa_m": self.abscissa_m,
                "decided_by": self.decided_by, "decided_on": self.decided_on}


def counterslope_confirmation(amount_m: float, abscissa_m: float, decided_by: str, decided_on: str
                              ) -> CounterslopeConfirmation:
    """La confirmación de una contrapendiente de ``amount_m`` m en la abscisa ``abscissa_m`` m, de
    ``decided_by`` en ``decided_on``. ``ValueError`` si la cuantía o la abscisa no son finitas, la
    cuantía no es positiva o falta quién o cuándo (no se anota una decisión sin decisor)."""
    for what, value in (("la cuantía", amount_m), ("la abscisa", abscissa_m)):
        if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
            raise ValueError(f"{what} de la contrapendiente confirmada es un número finito, no "
                             f"{value!r}")
    if amount_m <= 0:
        raise ValueError(f"la contrapendiente confirmada es positiva, no {amount_m}")
    for what, text in (("quién", decided_by), ("cuándo", decided_on)):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"falta {what} confirmó la contrapendiente")
    return CounterslopeConfirmation(float(amount_m), float(abscissa_m), decided_by, decided_on)


def counterslope_confirmed(settings: Mapping[str, Any]) -> CounterslopeConfirmation | None:
    """La contrapendiente confirmada que guardan los ajustes ``settings`` de una operación
    ``des.platform`` (:data:`COUNTERSLOPE_CONFIRMED`), o ``None`` si no la llevan (no tuvo que
    confirmarse o es de antes). ``ValueError`` si la llevan y no es una confirmación (nombrando el
    campo)."""
    data = _mapping(settings, "los ajustes de una plataforma")
    found = data.get(COUNTERSLOPE_CONFIRMED)
    if found is None:
        return None
    what = f"los ajustes de una plataforma, «{COUNTERSLOPE_CONFIRMED}»,"
    item = _mapping(found, what)
    amount = _number(item, "amount_m", what, required=True)
    abscissa = _number(item, "abscissa_m", what, required=True)
    assert amount is not None and abscissa is not None  # required
    return counterslope_confirmation(amount, abscissa, _required_text(item, "decided_by", what),
                                     _required_text(item, "decided_on", what))


SUPPORTS_RELEASED = "supports_released"
"""La clave de los ajustes de una operación de ``des`` donde queda **lo que se dio por bueno sin su apoyo** (RF-015-17,
A7, P-6; spec 015, T25): una lista de :class:`ReleasedSupport` (la entidad, el motivo, el decisor y la fecha),
**acumulada**: la operación que repite a otra se queda con la lista de la que sustituye y le suma lo nuevo. No es de
los ajustes que da cada tipo (``platform_settings``…): la anota quien suelta el apoyo
(``design.entity_store.release_support``) y la arrastran los recálculos (``design.store.OperationStart``)."""


@dataclass(frozen=True, slots=True)
class ReleasedSupport:
    """Un apoyo que la persona dio por bueno **sin** la entidad en la que se apoyaba, que se descartó (RF-015-17;
    plan 015 §5.4 A7, P-6): el código de la entidad (``entity``: ``PLT-001``), el motivo (``reason``), quién lo
    decidió (``by``) y cuándo (``when``, UTC). Es lo que se anota en los ajustes de la operación repetida
    (:data:`SUPPORTS_RELEASED`) y en el evento ``support_released``."""

    entity: str
    reason: str
    by: str
    when: str

    def __post_init__(self) -> None:
        entity_segment(self.entity)
        for what, text in (("el motivo", self.reason), ("quién lo decidió", self.by),
                           ("cuándo", self.when)):
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"falta {what} en el apoyo que se da por bueno ({self.entity})")

    def settings(self) -> dict[str, str]:
        """Lo que se anota en los ajustes de la operación (JSON)."""
        return {"entity": self.entity, "reason": self.reason, "by": self.by, "when": self.when}


def released_supports(settings: Mapping[str, Any]) -> tuple[ReleasedSupport, ...]:
    """Los apoyos que dan por buenos los ajustes ``settings`` de una operación (:data:`SUPPORTS_RELEASED`), por orden;
    ninguno si no los llevan. ``ValueError`` si los llevan y no son una lista de apoyos (nombrando el campo)."""
    data = _mapping(settings, "los ajustes de una operación del diseño")
    found = data.get(SUPPORTS_RELEASED)
    if found is None:
        return ()
    what = f"los ajustes de una operación del diseño, «{SUPPORTS_RELEASED}»,"
    if isinstance(found, str | bytes | Mapping) or not isinstance(found, Iterable):
        raise ValueError(f"{what} son una lista de apoyos dados por buenos, no {found!r}")
    items: list[ReleasedSupport] = []
    for item in found:
        entry = _mapping(item, what)
        items.append(ReleasedSupport(_required_text(entry, "entity", what), _required_text(entry, "reason", what),
                                     _required_text(entry, "by", what), _required_text(entry, "when", what)))
    return tuple(items)


def merge_released(*groups: Iterable[ReleasedSupport]) -> tuple[ReleasedSupport, ...]:
    """Los apoyos de ``groups`` en el orden en que llegan y **sin repetir la entidad** (el primero que la dio por
    buena manda: su motivo y su decisor no se pisan)."""
    found: dict[str, ReleasedSupport] = {}
    for group in groups:
        for item in group:
            found.setdefault(item.entity, item)
    return tuple(found.values())


def platform_values(code: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Los valores de la entidad de código ``code`` entre los parámetros resueltos ``parameters``
    (clave completa → valor, como los anota una operación: ``des.platform.plt_001.mode``): por su
    último segmento (``mode``), sin los de otra entidad ni los del proyecto. Es lo que recibe
    :func:`platform_request`. ``ValueError`` si ``code`` no es el de una entidad."""
    prefix = f"{PLATFORM_PREFIX}.{entity_segment(code)}."
    return {key[len(prefix):]: value for key, value in _mapping(
        parameters, "los parámetros de una entidad").items()
        if isinstance(key, str) and key.startswith(prefix)}


_VALUES = "los valores de una plataforma"


def _entity_values(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Los valores de una plataforma por su último segmento; ``ValueError`` si uno no es de una."""
    found: dict[str, Any] = {}
    for key, value in _mapping(parameters, _VALUES).items():
        try:
            found[PlatformParam(key).value] = value
        except ValueError:
            options = ", ".join(item.value for item in PlatformParam)
            raise ValueError(f"{_VALUES} son de {options}, no «{key}»") from None
    return found


def _param_text(values: Mapping[str, Any], param: PlatformParam, *, required: bool = False
                ) -> str | None:
    value = values.get(param.value)
    if value is None:
        if required:
            raise ValueError(f"falta «{param.value}» en {_VALUES}")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{_VALUES} llevan «{param.value}» como un texto, no {value!r}")
    return value


def platform_request(settings: Mapping[str, Any], parameters: Mapping[str, Any]
                     ) -> PlatformRequest:
    """La plataforma que repiten los ajustes ``settings`` de una operación ``des.platform`` (los de
    :func:`platform_settings`) con los valores de los parámetros de su entidad ``parameters``
    (por último segmento: :func:`platform_values`): al recalcularla y al reproducirla. La capa y la
    geometría salen de los parámetros (cambiar uno repite la operación con el nuevo), la capa de
    las líneas y los campos, de los ajustes; lo que no tiene valor (la apoyada, la pendiente máxima,
    lo que declara) queda como en la petición sin pedirlo. ``ValueError`` si no son los de una
    plataforma (nombrando el campo)."""
    what = "los ajustes de una plataforma"
    data = _mapping(settings, what)
    fields_what = f"{what}, «fields»,"
    fields = _mapping(data.get("fields"), fields_what)
    values = _entity_values(parameters)
    protect = values.get(PlatformParam.PROTECT.value)
    if protect is not None and not isinstance(protect, bool):
        raise ValueError(f"{_VALUES} llevan «protect» como sí o no, no {protect!r}")
    stockpile = _param_text(values, PlatformParam.STOCKPILE)
    # la plataforma que retira un acopio «como plataforma» (T21) no lee su capa ni su geometría (salen del acopio): sin ellos, el acopio
    layer = _param_text(values, PlatformParam.LAYER, required=stockpile is None) or stockpile
    feature = _param_text(values, PlatformParam.FEATURE, required=stockpile is None) or stockpile
    start = _param_text(values, PlatformParam.START, required=True)
    assert layer is not None and feature is not None and start is not None
    return PlatformRequest(
        name=_required_text(data, "name", what),
        fields=PlatformFields(
            layer=layer,
            start_level_field=_required_text(fields, "start_level_field", fields_what),
            gradient_field=_required_text(fields, "gradient_field", fields_what),
            width_field=_optional_text(fields, "width_field", fields_what),
            axis_field=_optional_text(fields, "axis_field", fields_what),
            axis_layer=_optional_text(fields, "axis_layer", fields_what)),
        feature=feature, start=start,
        support=_param_text(values, PlatformParam.SUPPORT),
        mode=_param_text(values, PlatformParam.MODE),
        edge_angle_deg=_number(values, PlatformParam.EDGE_ANGLE.value, _VALUES),
        reach_m=_number(values, PlatformParam.REACH.value, _VALUES),
        mesh_factor=_number(values, PlatformParam.MESH_FACTOR.value, _VALUES),
        counter_tol_m=_number(values, PlatformParam.COUNTER_TOL.value, _VALUES),
        metric=_param_text(values, PlatformParam.METRIC),
        max_slope_pct=_number(values, PlatformParam.MAX_SLOPE.value, _VALUES),
        protect=bool(protect),
        guard_m=_number(values, PlatformParam.GUARD.value, _VALUES),
        reason=_param_text(values, PlatformParam.REASON),
        stockpile=stockpile)


def _entity_pairs(entities: Iterable[tuple[str, str]], what: str) -> list[dict[str, str]]:
    """Las entidades ``(código, nombre)`` de ``what`` como las guardan los ajustes."""
    if isinstance(entities, str | bytes | Mapping) or not isinstance(entities, Iterable):
        raise TypeError(f"las entidades {what} son una lista de (código, nombre), no "
                        f"{entities!r}")
    found: list[dict[str, str]] = []
    for pair in entities:
        code, name = pair
        entity_segment(code)
        if not isinstance(name, str):
            raise TypeError(f"el nombre de la entidad «{code}» es un texto, no {name!r}")
        if not name.strip():
            raise ValueError(f"falta el nombre de la entidad «{code}»")
        if any(item["code"] == code for item in found):
            raise ValueError(f"la entidad «{code}» está dos veces {what}")
        found.append({"code": code, "name": name})
    return found


def declare_settings(entities: Iterable[tuple[str, str]], *, version_uid: str | None = None,
                     decisions: Mapping[str, tuple[str, date]] | None = None) -> dict[str, Any]:
    """Los ajustes de ``des.declare_constraints`` (spec 015, T04 y T17; RF-015-10; JSON sin rutas): las
    entidades que recoge, por orden, cada una con su código y el nombre de su dato ``des_epr_`` (lo que hace
    falta para nombrar sus datos al recalcular y reproducir: el nombre con que se calculó). Es un
    diccionario nuevo; ``ValueError`` si un código no es el de una entidad, un nombre está en blanco o una
    entidad sale dos veces.

    ``version_uid`` (T17): el uid de la versión que declara, de donde sale el ``uid`` de cada restricción
    declarada (``core.constraints.declared.declared_uid``); ``decisions`` (T17): de cada entidad que declara
    (por su código, y ha de ser una de ``entities``), quién la creó o cambió y la fecha de esa decisión: lo
    que la reproducción, sin proyecto, no puede leer de su historial de parámetros. Sin ellos, los ajustes
    son los de la T04 (:func:`settings_version` y :func:`settings_decisions` no dan nada)."""
    found: dict[str, Any] = {"entities": _entity_pairs(entities, "de la declaración")}
    if version_uid is not None:
        if not isinstance(version_uid, str) or not version_uid.strip():
            raise ValueError(f"el uid de la versión de la declaración es un texto, no {version_uid!r}")
        found["version"] = version_uid
    if decisions:
        listed = {item["code"]: item for item in found["entities"]}
        for code, (who, when) in decisions.items():
            if code not in listed:
                raise ValueError(f"la decisión es de «{code}», que no es una de las entidades de la "
                                 "declaración")
            if not isinstance(who, str) or not who.strip():
                raise ValueError(f"el decisor de «{code}» es un texto con algo escrito, no {who!r}")
            if not isinstance(when, date) or hasattr(when, "hour"):
                raise TypeError(f"la fecha de la decisión de «{code}» es una fecha, no {when!r}")
            listed[code]["decided_by"] = who
            listed[code]["decided_on"] = when.isoformat()
    return found


def entity_layer_settings(entities: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """Los ajustes de ``des.entity_layer`` (spec 015, T04; RF-015-27): las mismas que
    :func:`declare_settings`, las de la capa de entidades."""
    return {"entities": _entity_pairs(entities, "de la capa de entidades")}


def settings_entities(settings: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Las entidades ``(código, nombre)`` que guardan unos ajustes de ``des.declare_constraints`` o
    de ``des.entity_layer`` (:func:`declare_settings`, :func:`entity_layer_settings`), por orden.
    ``ValueError`` si no las llevan como esas listas."""
    what = "los ajustes de la declaración o de la capa de entidades"
    items = _mapping(settings, what).get("entities")
    if not isinstance(items, list):
        raise ValueError(f"{what} llevan «entities» como una lista, no {items!r}")
    found = []
    for item in items:
        data = _mapping(item, f"{what}, «entities»,")
        found.append((_required_text(data, "code", f"{what}, «entities»,"),
                      _required_text(data, "name", f"{what}, «entities»,")))
    return tuple(found)


def settings_version(settings: Mapping[str, Any]) -> str | None:
    """El uid de la versión que anotan los ajustes de ``des.declare_constraints``
    (:func:`declare_settings`, ``version_uid``); ``None`` si no lo llevan. ``ValueError`` si no es un
    texto."""
    what = "los ajustes de la declaración"
    value = _mapping(settings, what).get("version")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} llevan «version» como un texto, no {value!r}")
    return value


def settings_decisions(settings: Mapping[str, Any]) -> dict[str, tuple[str, date]]:
    """Quién creó o cambió cada entidad que declara y la fecha de su decisión, de los ajustes de
    ``des.declare_constraints`` (:func:`declare_settings`, ``decisions``): código de la entidad → ``(decisor,
    fecha)``; solo las entidades que la llevan. ``ValueError`` si una decisión no es un decisor y una fecha
    ISO."""
    what = "los ajustes de la declaración, «entities»,"
    items = _mapping(settings, "los ajustes de la declaración").get("entities", [])
    if not isinstance(items, list):
        raise ValueError(f"los ajustes de la declaración llevan «entities» como una lista, no {items!r}")
    found: dict[str, tuple[str, date]] = {}
    for item in items:
        data = _mapping(item, what)
        who, when = data.get("decided_by"), data.get("decided_on")
        if who is None and when is None:
            continue
        if not isinstance(who, str) or not who.strip() or not isinstance(when, str):
            raise ValueError(f"{what} llevan «decided_by» y «decided_on» (un texto y una fecha), no "
                             f"{who!r} y {when!r}")
        found[_required_text(data, "code", what)] = (who, date.fromisoformat(when))
    return found


def settings_pending(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Los códigos de los sectores sin búsqueda vigente al calcular que guardan unos ajustes
    (RF-013-06; ninguno si no los llevan). ``ValueError`` si no son una lista de textos."""
    return _list(_mapping(settings, "los ajustes de una operación del diseño"),
                 "pending_sectors", "los ajustes de una operación del diseño")


def settings_touched(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Los códigos de los sectores que tocó el dominio de trabajo al calcular, de unos ajustes
    (RF-013-06; ninguno si no los llevan): con ``design.sectors.pending_marks`` y los sectores de
    ahora dan la marca «búsqueda de intocables pendiente». ``ValueError`` si no son una lista de
    textos."""
    return _list(_mapping(settings, "los ajustes de una operación del diseño"),
                 "touched_sectors", "los ajustes de una operación del diseño")


def _previous(value: Mapping[str, Any]) -> dict[str, Any]:
    """Lo anterior con que se comparó un escalonado (D-25), comprobado y como diccionario nuevo."""
    what = "lo anterior con que se comparó el escalonado"
    data = _mapping(value, what)
    return {"operation": _required_text(data, "operation", what),
            "revision": _required_text(data, "revision", what),
            "cut_m3": _number(data, "cut_m3", what, required=True),
            "fill_m3": _number(data, "fill_m3", what, required=True)}


def settings_previous(settings: Mapping[str, Any], surface: Surface | str | None = None
                      ) -> dict[str, Any] | None:
    """Lo anterior con que se comparó el escalonado de unos ajustes (``operation``, ``revision``,
    ``cut_m3`` y ``fill_m3``; D-25), o ``None`` si no se comparó con nada. Con ``surface``, el de
    ese lado en los ajustes de una cantera (:func:`quarry_settings`, T51); sin la clave (una
    cantera de antes de la T51), ``None``. ``ValueError`` si no tiene esa forma."""
    value = _mapping(settings, "los ajustes de un escalonado").get("previous")
    if value is None:
        return None
    if surface is not None:
        return _sides_previous(value)[Surface(surface).value]
    return _previous(value)


# --- Lo que consume una operación ---------------------------------------------------------------


def _unique[T](items: Iterable[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(items))


def sector_inputs(available: Collection[str]) -> tuple[Use, ...]:
    """Los sectores y las búsquedas de intocables de la 012 como entradas (papeles
    :data:`SECTORS_ROLE` y :data:`SEARCHES_ROLE`), los que estén en ``available`` (los nombres
    de los datos registrados del proyecto, ``gis.masks.store.available_tables``)."""
    return tuple(Use(table, role) for table, role in ((SECTOR_TABLE, SECTORS_ROLE),
                                                       (SEARCH_TABLE, SEARCHES_ROLE))
                 if table in available)


def _named(value: str | None, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"falta el nombre del dato {what}")
    return value


def envelope_inputs(request: EnvelopeRequest, masks: Iterable[Use] = (),
                    available: Collection[str] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.envelope`` (RF-013-17; plan §5.2.3), en su orden: la superficie de
    partida de las semillas (``surface``) o su rejilla de cotas (``seeds_grid``; una cota fija
    no es ninguna entrada), la capa de la zona de las semillas y la que acota el dominio si las
    hay, las máscaras de la versión ``masks`` (``MaskSet.uses()``, con sus papeles) y los
    sectores y las búsquedas registrados (``available``). Si una cambia, la envolvente queda
    obsoleta. ``ValueError`` si faltan los nombres de lo que consume."""
    seeds, found = request.seeds, []
    kind = SeedKind(seeds.kind)
    if kind is SeedKind.SURFACE:
        found.append(Use(_named(seeds.surface, "de la superficie de las semillas"), SURFACE_ROLE))
    elif kind is SeedKind.GRID:
        found.append(Use(_named(seeds.grid, "de la rejilla de cotas de las semillas"),
                         SEEDS_GRID_ROLE))
    zone = seeds.zone
    if zone is not None and ZoneKind(zone.kind) is ZoneKind.LAYER:
        found.append(Use(_named(zone.name, "de la capa de la zona de las semillas"),
                         ZONE_LAYER_ROLE))
    if request.domain.layer is not None:
        found.append(Use(_named(request.domain.layer, "de la capa que acota el dominio"),
                         DOMAIN_LAYER_ROLE))
    found += list(masks)
    found += sector_inputs(available)
    return _unique(found)


def design_inputs(request: DesignRequest, surface: str, masks: Iterable[Use] = (),
                  available: Collection[str] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.stepped_design`` (RF-013-31; D-26, plan §5.2.3), en su orden: la
    envolvente que escalona (``envelope``: el dato ``des_env_<nombre>`` de su operación, de la
    misma versión), la superficie de partida ``surface`` (``surface``), la rejilla de anclas si
    el ancla es una rejilla (``anchors``), las máscaras ``masks``, los sectores y las
    búsquedas registrados. ``ValueError`` si faltan los nombres."""
    found = [Use(dataset_name(ENVELOPE_GRID, request.envelope), ENVELOPE_ROLE),
             Use(_named(surface, "de la superficie de partida"), SURFACE_ROLE)]
    if request.anchor_grid is not None:
        found.append(Use(_named(request.anchor_grid, "de la rejilla de anclas"), ANCHORS_ROLE))
    found += list(masks)
    found += sector_inputs(available)
    return _unique(found)


def excavation_area_inputs(surface: str, masks: Iterable[Use] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.excavation_area`` (spec 014, T06; RF-014-01; plan 014 §5.2.3), en su
    orden: la superficie de partida ``surface`` (``surface``: sus celdas sin dato quedan fuera del
    recinto) y las máscaras de la versión ``masks`` (``MaskSet.uses()``, con sus papeles). Si una
    cambia, el recinto queda obsoleto. No lee ningún parámetro. ``ValueError`` si falta el nombre
    de la superficie."""
    return _unique([Use(_named(surface, "de la superficie de partida"), SURFACE_ROLE),
                    *masks])


def transition_inputs(surface: str, start: str, masks: Iterable[Use] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.edge_transition`` (spec 014, T28; RF-014-19, RF-014-31; plan 014
    §5.2.3), en su orden: la superficie de diseño ``surface`` (papel :data:`DESIGN_SURFACE_ROLE`:
    la que se une con el terreno no afectado), la superficie de partida ``start``
    (:data:`SURFACE_ROLE`) y las máscaras de la versión ``masks`` (``MaskSet.uses()``: lo que
    admiten mover). Si una cambia, la transición queda obsoleta. ``ValueError`` si faltan los
    nombres."""
    return _unique([Use(_named(surface, "de la superficie de diseño"), DESIGN_SURFACE_ROLE),
                    Use(_named(start, "de la superficie de partida"), SURFACE_ROLE), *masks])


def side_role(surface: Surface | str, role: str) -> str:
    """El papel de lo que consume un lado de la cantera (``final`` o ``exploitation``) con el
    papel ``role`` de la 013: ``final_anchors``, ``exploitation_seeds_grid``… (los dos lados
    pueden leer cosas distintas con el mismo papel). ``ValueError`` si no es una de las dos."""
    return f"{Surface(surface).value}_{role}"


def quarry_inputs(request: QuarryRequest, masks: Iterable[Use] = (),
                  available: Collection[str] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.quarry`` (spec 014, T19; RF-014-29, RF-014-31; plan 014 §5.2.3), en su
    orden: la superficie de partida (``surface``); de cada lado, lo que leen sus semillas de la 013
    (su superficie, su rejilla de cotas o la capa de su zona, con :func:`side_role`) y su rejilla de
    anclas (``<lado>_anchors``); las capas de polígonos y de líneas que usa, cada una con su papel
    (:data:`FLOORS_LAYER_ROLE`, :data:`CONSERVE_LAYER_ROLE` —las zonas a conservar que son una
    capa—, :data:`CORRIDORS_LAYER_ROLE`, :data:`FILL_LAYER_ROLE` y :data:`TO_FINAL_LAYER_ROLE`);
    las máscaras de la versión ``masks`` y los sectores y las búsquedas registrados
    (``available``). Si una cambia, la cantera queda obsoleta. La capa de las láminas de agua no
    la usa (es de «Solo relleno»). ``ValueError`` si faltan los nombres de lo que consume."""
    found = [Use(_named(request.start, "de la superficie de partida"), SURFACE_ROLE)]
    for surface in Surface:
        side = request.side(surface)
        seeds = side.seeds
        if seeds is not None:
            kind = SeedKind(seeds.kind)
            if kind is SeedKind.SURFACE:
                found.append(Use(_named(seeds.surface, "de la superficie de las semillas"),
                                 side_role(surface, SURFACE_ROLE)))
            elif kind is SeedKind.GRID:
                found.append(Use(_named(seeds.grid, "de la rejilla de cotas de las semillas"),
                                 side_role(surface, SEEDS_GRID_ROLE)))
            zone = seeds.zone
            if zone is not None and ZoneKind(zone.kind) is ZoneKind.LAYER:
                found.append(Use(_named(zone.name, "de la capa de la zona de las semillas"),
                                 side_role(surface, ZONE_LAYER_ROLE)))
        if side.anchor_grid is not None:
            found.append(Use(_named(side.anchor_grid, "de la rejilla de anclas"),
                             side_role(surface, ANCHORS_ROLE)))
    if request.floors is not None:
        found.append(Use(_named(request.floors.layer, "de los fondos"), FLOORS_LAYER_ROLE))
    for zone in request.conserve:
        if ZoneKind(zone.kind) is ZoneKind.LAYER:
            found.append(Use(_named(zone.name, "de una zona a conservar"), CONSERVE_LAYER_ROLE))
    if request.corridors is not None:
        found.append(Use(_named(request.corridors.layer, "de los corredores"),
                         CORRIDORS_LAYER_ROLE))
    if request.fill_zones is not None:
        found.append(Use(_named(request.fill_zones, "de las zonas de restauración por relleno"),
                         FILL_LAYER_ROLE))
    if request.to_final_layer is not None:
        found.append(Use(_named(request.to_final_layer,
                                "de las zonas de «explotación hasta la final»"),
                         TO_FINAL_LAYER_ROLE))
    found += list(masks)
    found += sector_inputs(available)
    return _unique(found)


def fill_only_inputs(request: FillOnlyRequest, masks: Iterable[Use] = (),
                     available: Collection[str] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.fill_only`` (spec 014, T30; RF-014-29, RF-014-31; plan 014 §5.2.3: «como
    ``des.stepped_design`` en relleno, más láminas»), en su orden: lo de su escalonado
    (:func:`design_inputs`: la envolvente, la superficie de partida y la rejilla de anclas), la capa
    de las láminas de agua si la hay (:data:`WATER_LAYER_ROLE`), las máscaras ``masks`` y los
    sectores y las búsquedas registrados (``available``). Si una cambia, el diseño queda obsoleto.
    ``ValueError`` si faltan los nombres de lo que consume."""
    found = list(design_inputs(request.design, request.start))
    if request.water is not None:
        found.append(Use(_named(request.water.layer, "de las láminas de agua"), WATER_LAYER_ROLE))
    found += list(masks)
    found += sector_inputs(available)
    return _unique(found)


def refit_inputs(request: RefitRequest, masks: Iterable[Use] = (),
                 available: Collection[str] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.refit`` (spec 014, T32; RF-014-27, RF-014-29; plan 014 §5.2.3: «las
    superficies que ajusta; las máscaras nuevas»), en su orden: cada superficie de diseño que se
    ajusta (papel :data:`DESIGN_SURFACE_ROLE`), la superficie de partida (:data:`SURFACE_ROLE`),
    las máscaras de la versión ``masks`` (``MaskSet.uses()``: el límite nuevo) y la tabla de los
    sectores si está registrada (``available``: el perfil de cada celda sale de su sector). Las
    búsquedas de intocables no: el ajuste no las lee. Si una cambia, el ajuste queda obsoleto.
    ``ValueError`` si faltan los nombres."""
    found = [Use(_named(surface, "de la superficie que se ajusta"), DESIGN_SURFACE_ROLE)
             for surface in request.surfaces]
    found.append(Use(_named(request.start, "de la superficie de partida"), SURFACE_ROLE))
    found += list(masks)
    found += [use for use in sector_inputs(available) if use.role == SECTORS_ROLE]
    return _unique(found)


def platform_inputs(request: PlatformRequest, start: str, masks: Iterable[Use] = (),
                    supports: Iterable[str] = (), removed: Iterable[str] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.platform`` (spec 015, T04; RF-015-02, RF-015-04, RF-015-06, RF-015-15;
    plan 015 §5.2.3), en su orden: la capa de las plataformas (:data:`ENTITY_LAYER_ROLE`: la
    geometría y su hash; un cambio de geometría en QGIS deja obsoleta la operación) y, si un polígono
    enlaza su eje con otra capa, la de ese eje (:data:`ENTITY_AXIS_LAYER_ROLE`); la superficie de
    partida ``start`` (:data:`SURFACE_ROLE`; **ya resuelta**: el nombre de su dato, no el
    ``entity:<código>`` del parámetro); las máscaras de la versión ``masks`` (``MaskSet.uses()``) y,
    **añadidas al crear** (una operación hecha es inmutable), las superficies de las entidades en
    las que se apoya, ``supports`` (:data:`SUPPORTED_ON_ROLE`: las que detecta el cálculo y las que
    declara el usuario, y la superficie de apoyo de la petición, resuelta), sin repetir. Si una
    cambia, la plataforma queda obsoleta. No lee sectores ni búsquedas: las máscaras ya las llevan y
    ``refuse_pending`` rechaza el cálculo con uno pendiente. ``ValueError`` si faltan los nombres;
    ``TypeError`` si ``supports`` es un texto.

    **Retirar un acopio «como plataforma»** (spec 016, T21; RF-016-16, plan 016 §5.2.3 «``des.platform`` gana la entrada
    ``removed_stockpile``»): la geometría de la plataforma es la huella del acopio, **un dato producido de la versión**, no una capa
    del proyecto: en lugar de la capa (y de la del eje) la operación consume, con el papel :data:`REMOVED_STOCKPILE_ROLE`, lo que lee del
    acopio, ``removed`` (los nombres de su tabla ``des_stk_``, de su base ``des_stb_`` y de la superficie con que se detectó): si la
    detección cambia, la plataforma queda obsoleta. Sin ``request.stockpile``, ``removed`` no se da (``ValueError``) y nada cambia."""
    removed_names = _codes(removed, "los datos del acopio que se retira")
    if removed_names and request.stockpile is None:
        raise ValueError("solo una plataforma de un acopio consume los datos del acopio que retira (RF-016-16)")
    found: list[Use] = []
    if request.stockpile is None:
        found.append(Use(_named(request.layer, "de la capa de las plataformas"), ENTITY_LAYER_ROLE))
        if request.fields.axis_layer is not None:
            found.append(Use(_named(request.fields.axis_layer, "de la capa de los ejes"),
                             ENTITY_AXIS_LAYER_ROLE))
    found.append(Use(_named(start, "de la superficie de partida"), SURFACE_ROLE))
    found += [Use(_named(name, "del acopio que se retira"), REMOVED_STOCKPILE_ROLE) for name in removed_names]
    found += list(masks)
    found += [Use(_named(name, "de una superficie en la que se apoya"), SUPPORTED_ON_ROLE)
              for name in _codes(supports, "las superficies de apoyo")]
    return _unique(found)


def _entity_inputs(names: Iterable[str], what: str) -> tuple[Use, ...]:
    """Los datos ``des_epr_`` de las entidades de nombre ``names`` como entradas (papel
    :data:`ENTITY_ROLE`), sin repetir."""
    return _unique(Use(dataset_name(ENTITY_TABLE, name), ENTITY_ROLE)
                   for name in _codes(names, what))


def declare_inputs(names: Iterable[str]) -> tuple[Use, ...]:
    """Lo que consume ``des.declare_constraints`` (spec 015, T04; RF-015-10; plan 015 §5.2.3): los
    datos ``des_epr_`` de las entidades vivas que protegen (papel :data:`ENTITY_ROLE`), por el nombre
    de cada entidad. Ninguna entrada de una capa del proyecto. Si uno cambia, la declaración queda
    obsoleta. ``GisError`` ``gis.dataset_name_invalid`` si un nombre no tiene letras ni cifras;
    ``TypeError`` si ``names`` es un texto."""
    return _entity_inputs(names, "las entidades de la declaración")


def entity_layer_inputs(names: Iterable[str]) -> tuple[Use, ...]:
    """Lo que consume ``des.entity_layer`` (spec 015, T04 y T30; RF-015-27; plan 015 §5.2.3): de **todas** las
    entidades vivas, por el nombre de cada una, su dato ``des_epr_`` (papel :data:`ENTITY_ROLE`: la huella) y su
    informe ``des_prp_`` (papel :data:`ENTITY_REPORT_ROLE`: de donde salen sus cifras principales; T30: sin él,
    cambiar la cota o la pendiente de una entidad cambia el corte y el relleno y no la huella, y la capa se
    quedaría con las cifras de antes sin avisar). Como :func:`declare_inputs` en lo demás."""
    found: list[Use] = []
    for name in _codes(names, "las entidades de la capa"):
        found.append(Use(dataset_name(ENTITY_TABLE, name), ENTITY_ROLE))
        found.append(Use(dataset_name(ENTITY_REPORT_TABLE, name), ENTITY_REPORT_ROLE))
    return _unique(found)


# --- Los parámetros que lee una operación -------------------------------------------------------

ENVELOPE_PROFILE_PARAMS: tuple[BenchParam, ...] = (
    BenchParam.HEIGHT, BenchParam.FACE, BenchParam.BERM, BenchParam.MESH_FACTOR)
"""Lo que lee una envolvente por sectores de un perfil: su talud general (altura, cara, berma) y
su factor de malla. No su ancla: cambiarla no cambia la envolvente."""


def profile_params(codes: Iterable[str], parameters: Iterable[BenchParam] = tuple(BenchParam)
                   ) -> tuple[str, ...]:
    """Las claves ``des.bench.{p}.<valor>`` de los parámetros ``parameters`` (por defecto, los
    cinco) de cada perfil de ``codes``, en el orden de los perfiles y de los valores y sin
    repetir. ``ValueError`` si un código no es de un perfil."""
    wanted = tuple(parameters)
    return _unique(bench_key(code, param) for code in dict.fromkeys(codes) for param in wanted)


def envelope_params(request: EnvelopeRequest, *, profiles: Iterable[str] = (),
                    sector_slopes: Iterable[str] = ()) -> tuple[str, ...]:
    """Los parámetros que lee ``des.envelope`` (RF-013-17; ``begin_operation(params=…)``): con
    pendiente constante, solo el espesor mínimo de la 012 con que cuenta su desmonte y su
    terraplén; por sectores, además, el talud general de los perfiles ``profiles`` que usa
    (:data:`ENVELOPE_PROFILE_PARAMS`) y los taludes impuestos de los sectores ``sector_slopes``
    (``design.sectors.slope_params``)."""
    found: list[str] = []
    if SlopeMode(request.slope_mode) is SlopeMode.SECTORS:
        found += profile_params(profiles, ENVELOPE_PROFILE_PARAMS)
        found += _codes(sector_slopes, "las claves de los taludes de los sectores")
    return _unique([*found, VERIFY_MIN_THICKNESS])


def design_params(request: DesignRequest, *, sector_slopes: Iterable[str] = ()
                  ) -> tuple[str, ...]:
    """Los parámetros que lee ``des.stepped_design`` (RF-013-17, RF-013-27, RF-013-30): los cinco
    valores de cada perfil que usa (el base y los de los sectores), los taludes impuestos de los
    sectores ``sector_slopes``, la tolerancia de cara, el umbral de aviso de magnitud y el
    espesor mínimo."""
    codes = [request.base_profile, *(profile for _sector, profile in request.sector_profiles)]
    return _unique([*profile_params(codes),
                    *_codes(sector_slopes, "las claves de los taludes de los sectores"),
                    TOLERANCE_FACE, WARNING_RATIO, VERIFY_MIN_THICKNESS])


def quarry_profiles(request: QuarryRequest) -> tuple[str, ...]:
    """Los códigos de los perfiles que usa la cantera ``request``: de la final y de la explotación,
    el base y el de cada sector, sin repetir y en su orden."""
    return _unique(code for surface in Surface for code in (
        request.side(surface).base_profile,
        *(profile for _sector, profile in request.side(surface).sector_profiles)))


CREATED_STEP_PARAMS: tuple[str, ...] = (EDGE_MAX_STEP, EDGE_MIN_SHARE)
"""El salto y el porcentaje admitidos del salto creado (RF-014-20, RF-014-21; D-6): los lee también
el diseño que mide el salto creado de sus superficies en su resumen (T56, hallazgo F-18: la
cantera, «solo relleno» y el ajuste), no solo la transición (:data:`TRANSITION_PARAMS`)."""


def quarry_params(request: QuarryRequest, *, sector_slopes: Iterable[str] = ()
                  ) -> tuple[str, ...]:
    """Los parámetros que lee ``des.quarry`` (spec 014, T19; RF-014-29, RF-014-31): los cinco
    valores de cada perfil de los dos lados (:func:`quarry_profiles`), los taludes impuestos de los
    sectores ``sector_slopes``, el anillo de coronación (también el lado con semillas de la 013 lo
    necesita: el aviso de RF-014-03), el umbral y el área mínima del aviso de desdoblado, el talud
    de conservación solo si hay zonas a conservar (no tiene valor por defecto, D-9), el salto y el
    porcentaje admitidos del salto creado de sus dos superficies (:data:`CREATED_STEP_PARAMS`,
    T56), la tolerancia de cara, el umbral de aviso de magnitud y el espesor mínimo de la 012."""
    return _unique([*profile_params(quarry_profiles(request)),
                    *_codes(sector_slopes, "las claves de los taludes de los sectores"),
                    CROWN_RING, UNSPLIT_THRESHOLD, UNSPLIT_MIN_AREA,
                    *((CONSERVE_SLOPE,) if request.conserve else ()), *CREATED_STEP_PARAMS,
                    TOLERANCE_FACE, WARNING_RATIO, VERIFY_MIN_THICKNESS])


TRANSITION_PARAMS: tuple[str, ...] = (EDGE_TRANSITION_DEG, EDGE_MAX_STEP, EDGE_MIN_SHARE,
                                      VERIFY_MIN_THICKNESS)
"""Los parámetros que lee ``des.edge_transition`` (spec 014, T28; RF-014-19 a RF-014-21): el
ángulo de transición (sin valor por defecto, D-9), el salto y el porcentaje admitidos del salto
creado (D-6) y el espesor mínimo de la 012 con que se buscan las celdas que mueve el diseño."""

REFIT_PROFILE_PARAMS: tuple[BenchParam, ...] = (BenchParam.FACE, BenchParam.MESH_FACTOR)
"""Lo que usa el ajuste de un perfil (RF-014-27): la cara y el factor de malla; ni la altura, ni
la berma, ni el ancla. Los que **anotó** la operación que hizo el diseño de cada superficie (P-3;
T49), no los de hoy: no son parámetros que el ajuste lea del proyecto (:func:`refit_params`)."""


def refit_params() -> tuple[str, ...]:
    """Los parámetros que lee del proyecto ``des.refit`` (spec 014, T32; RF-014-27, RF-014-29): el
    espesor mínimo de la 012 con que se mira si el límite nuevo deja algo fuera (la comprobación
    de la T31) y el salto y el porcentaje admitidos del salto creado de cada superficie ajustada
    (:data:`CREATED_STEP_PARAMS`, T56). La cara y el factor de malla de cada superficie
    (:data:`REFIT_PROFILE_PARAMS`) son los que anotó la operación que hizo su diseño (P-3; T49,
    hallazgo F-10): van en sus ajustes (:func:`refit_settings`), no aquí, que anotaría los de
    hoy."""
    return (VERIFY_MIN_THICKNESS, *CREATED_STEP_PARAMS)


PLATFORM_COMMON_PARAMS: tuple[str, ...] = (TOLERANCE_FACE, WARNING_RATIO, VERIFY_MIN_THICKNESS,
                                           *CREATED_STEP_PARAMS)
"""Lo que lee de los parámetros del proyecto toda plataforma (spec 015, T04; plan 015 §5.2.2): la
tolerancia de cara de la 013 (la pared más empinada que la cara solo se admite en el límite del
alcance, RF-015-22) y el umbral de aviso de magnitud (RF-015-13), el espesor mínimo de la 012 con
que se cuentan las celdas que mueve y el salto y el porcentaje admitidos del salto creado de la 014
(:data:`CREATED_STEP_PARAMS`, RF-015-13)."""

_PLATFORM_READ: tuple[PlatformParam, ...] = (
    PlatformParam.LAYER, PlatformParam.FEATURE, PlatformParam.START, PlatformParam.START_LEVEL,
    PlatformParam.GRADIENT, PlatformParam.MODE, PlatformParam.EDGE_ANGLE, PlatformParam.REACH,
    PlatformParam.MESH_FACTOR, PlatformParam.COUNTER_TOL, PlatformParam.METRIC)
"""Los valores de la entidad que lee siempre ``des.platform``: los que cambian su resultado. No
lee su nombre (renombrarla no la deja obsoleta) ni lo que declara (``protect``, ``guard_m`` y
``reason``: lo lee la declaración)."""


def platform_params(code: str, request: PlatformRequest, *, supports: bool = False
                    ) -> tuple[str, ...]:
    """Los parámetros que lee ``des.platform`` de la entidad de código ``code``
    (``begin_operation(params=…)``; spec 015, T04; RF-015-02, RF-015-16; plan 015 §5.2.2): la capa,
    la geometría, la partida, la cota inicial y la pendiente de la rasante, el modo, el borde (su
    ángulo, su alcance, su factor de malla y su métrica) y la tolerancia de contrapendiente, y, solo
    los que tienen valor (un parámetro sin valor ni valor por defecto es un rechazo de la 008): el
    ancho, si la geometría es una línea con su campo de ancho; la superficie de apoyo y la pendiente
    máxima, si la ``request`` las lleva; y las dependencias declaradas (``supports``), si la entidad
    las tiene (``supports=True``: cambiarlas cambia lo que se apoya). Después, los del proyecto
    (:data:`PLATFORM_COMMON_PARAMS`). Por orden de :class:`~.params.PlatformParam`. Cambiar la
    partida, un parámetro o la geometría deja la plataforma (y, en cascada, lo que parte de ella)
    obsoleta con su causa. ``ValueError`` si ``code`` no es el de una entidad."""
    read = set(_PLATFORM_READ)
    if request.stockpile is not None:
        # retirar un acopio «como plataforma» (T21): la geometría y la rasante salen del acopio y de su plano (no de una capa ni de
        # unos valores copiados): lee el acopio, y no la capa, la geometría ni la cota inicial y la pendiente
        read -= {PlatformParam.LAYER, PlatformParam.FEATURE, PlatformParam.START_LEVEL, PlatformParam.GRADIENT}
        read.add(PlatformParam.STOCKPILE)
    if request.fields.width_field is not None:
        read.add(PlatformParam.WIDTH)
    if request.support is not None:
        read.add(PlatformParam.SUPPORT)
    if request.max_slope_pct is not None:
        read.add(PlatformParam.MAX_SLOPE)
    if supports:
        read.add(PlatformParam.SUPPORTS)
    return (*(entity_key(code, param) for param in PlatformParam if param in read),
            *PLATFORM_COMMON_PARAMS)


def declare_params(codes: Iterable[str], *, protecting: Iterable[str] = (),
                   reasoned: Iterable[str] = ()) -> tuple[str, ...]:
    """Los parámetros que lee ``des.declare_constraints`` de las entidades de código ``codes`` (spec
    015, T04; RF-015-10, RF-015-12; plan 015 §5.2.3), por entidad y en su orden: su nombre (el
    motivo generado, «declarada por la plataforma P1», lo lleva) y si protege (``protect``); de las
    que protegen (``protecting``), su modo (una «en corte y relleno» que protege se rechaza) y su
    resguardo (``guard_m``, obligatorio si protege: D-19); y, de las que editaron su motivo
    (``reasoned``), el ``reason``. ``ValueError`` si un código de ``protecting`` o de ``reasoned``
    no está en ``codes`` o no es el de una entidad."""
    entities = _codes(codes, "las entidades de la declaración")
    protects = set(_codes(protecting, "las entidades que protegen"))
    edited = set(_codes(reasoned, "las entidades con el motivo editado"))
    unknown = sorted((protects | edited) - set(entities))
    if unknown:
        raise ValueError(f"{', '.join(unknown)} no están entre las entidades de la declaración")
    found: list[str] = []
    for code in entities:
        found += [entity_key(code, PlatformParam.NAME), entity_key(code, PlatformParam.PROTECT)]
        if code in protects:
            found += [entity_key(code, PlatformParam.MODE), entity_key(code, PlatformParam.GUARD)]
        if code in edited:
            found.append(entity_key(code, PlatformParam.REASON))
    return _unique(found)


# --- Los cuatro tipos de entidad de la 016 (spec 016, T03; plan 016 §5.2.2 y §5.2.3; ADR-0025, ADR-0031) -----------
# Sin comportamiento todavía: los ajustes, lo que consume, los parámetros que lee y las cifras de cada tipo, como los
# de la plataforma (``platform_*``); las tareas siguientes crean cada operación con ellos.

STOCKPILE_SCOPE_KEY = "stockpile"
"""La clave del ámbito de una cifra de un acopio además de la del nombre y la entidad: **la clave del acopio** (la de
su marca: ``m07``). La detección es una sola operación con muchos acopios (P-1): sin ella, las cifras de dos acopios se
pisarían (la vigente de una clave es la última de cada ámbito, RF-009-20)."""
MATERIAL_SCOPE_KEY = "material"
"""La clave del ámbito de una cifra de un acopio con material (D-19): una base y un espesor por material."""


def stockpile_figure_scope(name: str, code: str, stockpile: str, material: str | None = None) -> dict[str, str]:
    """El ámbito de una cifra de **un acopio** de la detección ``name`` de código ``code`` (spec 016, T03; plan 016
    §2.1; ``docs/trampas.md`` §6): el de :func:`entity_figure_scope` (el nombre de la operación y el código de la
    detección), la clave del acopio (:data:`STOCKPILE_SCOPE_KEY`, ``m07``) y, si lo tiene, su material
    (:data:`MATERIAL_SCOPE_KEY`). ``ValueError`` si ``code`` no es un código de entidad, o la clave o el material están en
    blanco."""
    scope = entity_figure_scope(name, code)
    for key, value in ((STOCKPILE_SCOPE_KEY, stockpile), (MATERIAL_SCOPE_KEY, material)):
        if value is None and key == MATERIAL_SCOPE_KEY:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"el {key} del ámbito de una cifra de un acopio es un texto con algo, no {value!r}")
        scope[key] = value
    return scope


@dataclass(frozen=True, slots=True)
class StockpileFigures:
    """Las cifras de **un acopio** de una detección (RF-016-02; plan 016 §5.2.3): su clave (``stockpile``), su material
    (``material``, ``None`` si la marca no lo da), su área (m²), su volumen sobre su base (m³), su espesor máximo (m) y la
    inclinación de su plano de base (°; ``None`` si no tiene plano: su base es una superficie propia, RF-016-03)."""

    stockpile: str
    material: str | None
    area_m2: float
    volume_m3: float
    thickness_max_m: float
    plane_tilt_deg: float | None = None


def stockpile_figures(name: str, code: str, *, count: int, candidates: int | None,
                      stockpiles: Iterable[StockpileFigures]) -> tuple[FigureSpec, ...]:
    """Las cifras CALCULADO de la detección ``name`` de código ``code`` (spec 016, T03; RF-016-02, RF-016-08; plan 016
    §5.2.3), en el orden de :data:`STOCKPILE_FIGURES`: ``des.stk_count`` (los acopios) y ``des.stk_candidates`` (si se
    pidieron los candidatos: ``candidates`` no es ``None``), con el ámbito de :func:`entity_figure_scope`, y, de cada
    acopio de ``stockpiles`` y en su orden, su área, su volumen, su espesor máximo y la inclinación de su plano (si lo
    tiene), con el ámbito de :func:`stockpile_figure_scope`. Ninguna es negativa ni NaN ni infinita; los recuentos son
    enteros (``ValueError``; ``TypeError`` si no son números)."""
    scope = entity_figure_scope(name, code)
    found = [FigureSpec("des.stk_count", _count("des.stk_count", count), "-", scope=scope)]
    if candidates is not None:
        found.append(FigureSpec("des.stk_candidates", _count("des.stk_candidates", candidates), "-", scope=scope))
    for item in stockpiles:
        each = stockpile_figure_scope(name, code, item.stockpile, item.material)
        values = (("des.stk_area_m2", item.area_m2, "m2"), ("des.stk_volume_m3", item.volume_m3, "m3"),
                  ("des.stk_thickness_max_m", item.thickness_max_m, "m"),
                  ("des.stk_plane_tilt_deg", item.plane_tilt_deg, "deg"))
        found += [FigureSpec(key, _non_negative(key, value), unit, scope=each)
                  for key, value, unit in values if value is not None]
    return tuple(found)


def _entity_figures(declared: tuple[FigureDef, ...], what: str, name: str, code: str,
                    values: Mapping[str, float | None]) -> tuple[FigureSpec, ...]:
    """Las cifras de ``declared`` de la entidad ``name`` de código ``code`` con el ámbito de
    :func:`entity_figure_scope`, en el orden de ``declared`` y con su unidad: ``values`` da cada una por su clave (todas,
    ninguna de más ni de menos). Una que no existe (``None``) no se registra; un recuento (unidad ``-``) es un entero no
    negativo y las demás, un real finito no negativo (``ValueError``)."""
    keys = {figure.key: figure for figure in declared}
    given = _mapping(values, f"las cifras de {what}")
    extra = sorted(str(key) for key in given if key not in keys)
    if extra:
        raise ValueError(f"{', '.join(extra)} no son cifras de {what}: son {', '.join(keys)}")
    missing = [key for key in keys if key not in given]
    if missing:
        raise ValueError(f"faltan las cifras de {what} «{name}»: {', '.join(missing)} "
                         "(las que no existen se dan como None)")
    scope = entity_figure_scope(name, code)
    found = []
    for key, figure in keys.items():
        value = given[key]
        if value is None:
            continue
        number = _count(key, value) if figure.unit == "-" else _non_negative(key, value)
        found.append(FigureSpec(key, number, figure.unit, scope=scope))
    return tuple(found)


def removal_figures(name: str, code: str, values: Mapping[str, float | None]) -> tuple[FigureSpec, ...]:
    """Las cifras CALCULADO de la retirada ``name`` de código ``code`` (spec 016, T03; RF-016-13; plan 016 §5.2.3),
    con el ámbito de :func:`entity_figure_scope`, en el orden de :data:`REMOVAL_FIGURES`: ``values`` da cada una por su
    clave (las seis; ``None`` la que no existe: sin pared no hay ``des.rmv_wall_max_m``). Ninguna es negativa ni NaN
    (``ValueError``)."""
    return _entity_figures(REMOVAL_FIGURES, "una retirada", name, code, values)


def buttress_figures(name: str, code: str, values: Mapping[str, float | None]) -> tuple[FigureSpec, ...]:
    """Las cifras CALCULADO del contrafuerte ``name`` de código ``code`` (spec 016, T03; RF-016-17, RF-016-19; plan 016
    §5.2.3): como :func:`removal_figures`, con :data:`BUTTRESS_FIGURES` (las cinco)."""
    return _entity_figures(BUTTRESS_FIGURES, "un contrafuerte", name, code, values)


def body_figures(name: str, code: str, values: Mapping[str, float | None]) -> tuple[FigureSpec, ...]:
    """Las cifras CALCULADO del cuerpo apoyado ``name`` de código ``code`` (spec 016, T03; RF-016-20, RF-016-21; plan 016
    §5.2.3): como :func:`removal_figures`, con :data:`BODY_FIGURES` (las cinco; ``des.bdy_ignored`` es un recuento)."""
    return _entity_figures(BODY_FIGURES, "un cuerpo apoyado", name, code, values)


def _typed_code(code: str, kind: str, what: str) -> str:
    """``code`` si es el código de una entidad de tipo ``kind`` (``STK-001``); :class:`ValueError` si no es un código de
    entidad, no es de un tipo registrado o es de otro tipo: un error del programa."""
    found = entity_params_of(code)
    if found.kind != kind:
        raise ValueError(f"el código {code!r} no es el de {what} ({found.code_prefix}-… es de {found.kind})")
    return code


def supported_code(settings: Mapping[str, Any]) -> str:
    """El código de la entidad que guardan unos ajustes de un tipo de la 016 (:func:`stockpile_settings`,
    :func:`removal_settings`, :func:`buttress_settings` y :func:`body_settings`). ``ValueError`` si no lo llevan o no es
    el de una entidad."""
    what = "los ajustes de una entidad de la 016"
    code = _required_text(_mapping(settings, what), "code", what)
    entity_segment(code)
    return code


def supported_values(code: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Los valores de la entidad de código ``code`` (de cualquier tipo registrado) entre los parámetros resueltos
    ``parameters`` (clave completa → valor, como los anota una operación: ``des.stockpile.stk_001.margin_m``): por su
    último segmento (``margin_m``), sin los de otra entidad ni los del proyecto. Es lo que reciben
    :func:`stockpile_request`, :func:`removal_request`, :func:`buttress_request` y :func:`body_request`.
    ``ValueError`` si ``code`` no es el de una entidad de un tipo registrado."""
    prefix = f"{entity_params_of(code).key_prefix}.{entity_segment(code)}."
    return {key[len(prefix):]: value for key, value in _mapping(
        parameters, "los parámetros de una entidad").items()
        if isinstance(key, str) and key.startswith(prefix)}


def _values_of(members: type[StrEnum], parameters: Mapping[str, Any], what: str) -> dict[str, Any]:
    """Los valores ``parameters`` (por último segmento) de ``what``; ``ValueError`` si uno no es de su tipo."""
    found: dict[str, Any] = {}
    names = {item.value for item in members}
    for key, value in _mapping(parameters, what).items():
        if key not in names:
            raise ValueError(f"{what} son de {', '.join(sorted(names))}, no «{key}»")
        found[key] = value
    return found


def _value_text(values: Mapping[str, Any], name: str, what: str, *, required: bool = False) -> str | None:
    """El valor de texto ``name`` de ``values``; ``None`` si no lo hay y no es obligatorio; ``ValueError`` si falta
    siendo obligatorio o no es un texto con algo."""
    value = values.get(name)
    if value is None:
        if required:
            raise ValueError(f"falta «{name}» en {what}")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} llevan «{name}» como un texto, no {value!r}")
    return value


def _value_flag(values: Mapping[str, Any], name: str, what: str) -> bool | None:
    """El valor sí/no ``name`` de ``values`` (``None`` si no lo hay); ``ValueError`` si no es un sí/no."""
    value = values.get(name)
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{what} llevan «{name}» como sí o no, no {value!r}")
    return value


def _value_integer(values: Mapping[str, Any], name: str, what: str) -> int | None:
    """El valor entero ``name`` de ``values`` (``None`` si no lo hay); ``ValueError`` si no es un entero."""
    value = values.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise ValueError(f"{what} llevan «{name}» como un número entero, no {value!r}")
    return int(value)


_STOCKPILE_NUMBERS = (StockpileParam.MARGIN, StockpileParam.CROWN_INNER, StockpileParam.CROWN_OUTER,
                      StockpileParam.CROWN_SLOPE, StockpileParam.CROWN_FLAT_MIN, StockpileParam.MAX_RESIDUAL,
                      StockpileParam.TILT_MAX, StockpileParam.SUPPORT_QUANTILE, StockpileParam.OPEN_DIAMETER,
                      StockpileParam.MIN_HEIGHT, StockpileParam.MIN_AREA, StockpileParam.MAX_AREA,
                      StockpileParam.GUARD)


def stockpile_settings(request: StockpileRequest, code: str) -> dict[str, Any]:
    """Los ajustes de ``des.stockpile_detect`` (spec 016, T03; RF-016-02, RF-015-02; JSON sin rutas): el nombre de la
    detección, su ``code`` (``STK-001``) y los campos de su capa de marcas de los que salen la clave, el margen, el
    material y la superficie de base de cada marca (``fields``; ``None`` los que no lleva). **Ninguna otra cosa**: la
    capa, la superficie, los umbrales de D-3 y las decisiones son **parámetros de la entidad**
    (``des.stockpile.{e}.*``, :func:`supported_values`), como en la plataforma. Es un diccionario nuevo;
    ``ValueError`` si ``code`` no es el de una entidad."""
    if not isinstance(request, StockpileRequest):
        raise TypeError(f"los ajustes de una detección de acopios salen de una StockpileRequest, no {request!r}")
    _typed_code(code, "stockpile", "una detección de acopios")
    fields = request.fields
    return {"name": request.name, "code": code,
            "fields": {"name_field": fields.name_field, "margin_field": fields.margin_field,
                       "material_field": fields.material_field, "base_field": fields.base_field}}


def stockpile_request(settings: Mapping[str, Any], parameters: Mapping[str, Any]) -> StockpileRequest:
    """La detección que repiten los ajustes ``settings`` de una operación ``des.stockpile_detect`` (los de
    :func:`stockpile_settings`) con los valores de los parámetros de su entidad ``parameters`` (por último segmento:
    :func:`supported_values`): al recalcularla y al reproducirla. La capa, la superficie, los candidatos, los umbrales
    y las decisiones salen de los parámetros (cambiar uno repite la operación con el nuevo) y los campos de la capa, de
    los ajustes; lo que no tiene valor queda ``None`` sin pedirlo. ``ValueError`` si no son los de una detección
    (nombrando el campo)."""
    what = "los ajustes de una detección de acopios"
    values_what = "los valores de una detección de acopios"
    data = _mapping(settings, what)
    fields_what = f"{what}, «fields»,"
    fields = _mapping(data.get("fields"), fields_what)
    values = _values_of(StockpileParam, parameters, values_what)
    layer = _value_text(values, "layer", values_what, required=True)
    surface = _value_text(values, "surface", values_what, required=True)
    assert layer is not None and surface is not None
    numbers_found = {param.value: _number(values, param.value, values_what) for param in _STOCKPILE_NUMBERS}
    return StockpileRequest(
        name=_required_text(data, "name", what),
        fields=StockpileFields(
            layer=layer, name_field=_optional_text(fields, "name_field", fields_what),
            margin_field=_optional_text(fields, "margin_field", fields_what),
            material_field=_optional_text(fields, "material_field", fields_what),
            base_field=_optional_text(fields, "base_field", fields_what)),
        surface=surface, candidates=_value_flag(values, "candidates", values_what),
        fit_rounds=_value_integer(values, "fit_rounds", values_what),
        turns=_value_integer(values, "turns", values_what),
        decisions=_value_text(values, "decisions", values_what),
        protect=_value_flag(values, "protect", values_what),
        reason=_value_text(values, "reason", values_what), **numbers_found)


def stockpile_inputs(request: StockpileRequest, surface: str, masks: Iterable[Use] = (),
                     perimeter: Iterable[Use] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.stockpile_detect`` (spec 016, T03; RF-016-02, RF-016-08; plan 016 §5.2.3; ADR-0031 §3), en su
    orden: la capa de marcas (:data:`MARKS_LAYER_ROLE`: la geometría y su hash; un cambio de geometría en QGIS deja
    obsoleta la operación, uno de un campo no), la superficie en la que se detecta ``surface`` (:data:`SURFACE_ROLE`; el
    nombre de su dato), las máscaras de la versión ``masks`` (``MaskSet.uses()``; las de una detección **de versión**) y
    el perímetro de actuación ``perimeter`` (lo que consume la detección **del proyecto**, que no tiene máscaras de
    versión: RF-012-13), sin repetir. Si una cambia, la detección queda obsoleta. ``ValueError`` si faltan los nombres.
    (La superficie de base propia de una marca, RF-016-03, la añade la T13.)"""
    if not isinstance(request, StockpileRequest):
        raise TypeError(f"las entradas de una detección de acopios salen de una StockpileRequest, no {request!r}")
    return _unique([Use(_named(request.layer, "de la capa de las marcas"), MARKS_LAYER_ROLE),
                    Use(_named(surface, "de la superficie en la que se detecta"), SURFACE_ROLE),
                    *masks, *perimeter])


_STOCKPILE_READ = (StockpileParam.LAYER, StockpileParam.SURFACE, StockpileParam.CANDIDATES, StockpileParam.MARGIN,
                   StockpileParam.CROWN_INNER, StockpileParam.CROWN_OUTER, StockpileParam.CROWN_SLOPE,
                   StockpileParam.CROWN_FLAT_MIN, StockpileParam.MAX_RESIDUAL, StockpileParam.FIT_ROUNDS,
                   StockpileParam.TURNS, StockpileParam.TILT_MAX, StockpileParam.SUPPORT_QUANTILE,
                   StockpileParam.OPEN_DIAMETER, StockpileParam.MIN_HEIGHT, StockpileParam.MIN_AREA,
                   StockpileParam.MAX_AREA, StockpileParam.DECISIONS)
"""Los valores de la entidad que lee siempre ``des.stockpile_detect``: los que cambian su resultado, **también las decisiones
sobre los candidatos** (spec 016, T13; P-14: toda detección las lleva, vacías si nadie decide, así que decidir las cambia y la
deja obsoleta con su causa). No lee su nombre ni lo que declara (``protect``, ``guard_m`` y ``reason``: lo lee la
declaración)."""


def stockpile_params(code: str, request: StockpileRequest) -> tuple[str, ...]:
    """Los parámetros que lee ``des.stockpile_detect`` de la entidad de código ``code`` (``begin_operation(params=…)``;
    spec 016, T03; RF-016-02, RF-016-10; plan 016 §5.2.2): la capa, la superficie, los candidatos y los 14 umbrales
    (:data:`_STOCKPILE_READ`: con las decisiones sobre los candidatos, que toda detección lleva) y, **por su clave, sin
    copiarlo**, el umbral de la huella de la 011 (:data:`~.params.ANTHROPIC_PRESENCE`, D-17): cambiar un umbral, la
    capa (su geometría) o ese parámetro deja obsoleta la operación entera con su causa (CE-016-01). ``ValueError`` si
    ``code`` no es el de una detección."""
    _typed_code(code, "stockpile", "una detección de acopios")
    read = [entity_key(code, param) for param in _STOCKPILE_READ]
    return _unique([*read, ANTHROPIC_PRESENCE])


def removal_settings(request: RemovalRequest, code: str) -> dict[str, Any]:
    """Los ajustes de ``des.stockpile_removal`` (spec 016, T03; RF-016-11): el nombre de la retirada y su ``code``
    (``RMV-001``); el acopio, la partida, la transición y lo demás son **parámetros** de la entidad
    (``des.removal.{e}.*``). ``ValueError`` si ``code`` no es el de una retirada."""
    if not isinstance(request, RemovalRequest):
        raise TypeError(f"los ajustes de una retirada salen de una RemovalRequest, no {request!r}")
    _typed_code(code, "removal", "una retirada")
    return {"name": request.name, "code": code}


def removal_request(settings: Mapping[str, Any], parameters: Mapping[str, Any]) -> RemovalRequest:
    """La retirada que repiten los ajustes ``settings`` de ``des.stockpile_removal`` con los valores de los parámetros
    de su entidad ``parameters`` (por último segmento: :func:`supported_values`). ``ValueError`` si no son los de una
    retirada (nombrando el campo)."""
    what = "los ajustes de una retirada"
    values_what = "los valores de una retirada"
    data = _mapping(settings, what)
    values = _values_of(RemovalParam, parameters, values_what)
    stockpile = _value_text(values, "stockpile", values_what, required=True)
    start = _value_text(values, "start", values_what, required=True)
    assert stockpile is not None and start is not None
    return RemovalRequest(
        name=_required_text(data, "name", what), stockpile=stockpile, start=start,
        support=_value_text(values, "support", values_what),
        transition_deg=_number(values, "transition_deg", values_what),
        mesh_factor=_number(values, "mesh_factor", values_what), metric=_value_text(values, "metric", values_what),
        wall_reason=_value_text(values, "wall_reason", values_what),
        protect=_value_flag(values, "protect", values_what), guard_m=_number(values, "guard_m", values_what),
        reason=_value_text(values, "reason", values_what))


def removal_inputs(request: RemovalRequest, start: str, removed: Iterable[str], masks: Iterable[Use] = (),
                   supports: Iterable[str] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.stockpile_removal`` (spec 016, T03; RF-016-11, RF-016-14; plan 016 §5.2.3), en su orden: la
    superficie de partida ``start`` (:data:`SURFACE_ROLE`; **ya resuelta**: el nombre de su dato), el acopio que se
    retira, ``removed`` (:data:`REMOVED_STOCKPILE_ROLE`: los nombres de su tabla ``des_stk_`` y de su base ``des_stb_``),
    las máscaras de la versión ``masks`` y, **añadidas al crear** (una operación hecha es inmutable), lo que apoya
    ``supports`` (:data:`SUPPORTED_ON_ROLE`: las superficies sobre las que se apoyaba lo que la retirada atribuye,
    RF-016-14), sin repetir. ``ValueError`` si faltan los nombres; ``TypeError`` si ``removed`` o ``supports`` es un
    texto."""
    if not isinstance(request, RemovalRequest):
        raise TypeError(f"las entradas de una retirada salen de una RemovalRequest, no {request!r}")
    found = [Use(_named(start, "de la superficie de partida"), SURFACE_ROLE)]
    found += [Use(_named(name, "del acopio que se retira"), REMOVED_STOCKPILE_ROLE)
              for name in _codes(removed, "los datos del acopio que se retira")]
    found += list(masks)
    found += [Use(_named(name, "de una superficie en la que se apoya"), SUPPORTED_ON_ROLE)
              for name in _codes(supports, "las superficies de apoyo")]
    return _unique(found)


def _supported_read(code: str, kind: str, what: str, params: Iterable[str], *, optional: Iterable[
        tuple[bool, str]] = (), supports: bool = False) -> list[str]:
    """Las claves de ``params`` de la entidad ``code`` de tipo ``kind`` y, de ``optional`` (pares ``(se lee, valor)``),
    las que se leen; las dependencias declaradas si ``supports``."""
    _typed_code(code, kind, what)
    read = [entity_key(code, param) for param in params]
    read += [entity_key(code, param) for used, param in optional if used]
    if supports:
        read.append(entity_key(code, "supports"))
    return read


def removal_params(code: str, request: RemovalRequest, *, supports: bool = False) -> tuple[str, ...]:
    """Los parámetros que lee ``des.stockpile_removal`` de la entidad de código ``code`` (spec 016, T03; RF-016-11,
    RF-016-15; plan 016 §5.2.2): el acopio, la partida, el ángulo de transición, el factor de malla y la métrica; la
    superficie de apoyo, si la ``request`` la lleva; las dependencias declaradas, si ``supports``; y los del proyecto
    que lee toda entidad que mide un borde (:data:`PLATFORM_COMMON_PARAMS`: la tolerancia de cara, el umbral de
    magnitud, el espesor mínimo de la 012 y el salto creado de la 014). No lee su nombre ni su motivo de la pared ni lo
    que declara. ``ValueError`` si ``code`` no es el de una retirada."""
    read = _supported_read(
        code, "removal", "una retirada",
        (RemovalParam.STOCKPILE, RemovalParam.START, RemovalParam.TRANSITION, RemovalParam.MESH_FACTOR,
         RemovalParam.METRIC), optional=((request.support is not None, RemovalParam.SUPPORT),), supports=supports)
    return _unique([*read, *PLATFORM_COMMON_PARAMS])


def buttress_settings(request: ButtressRequest, code: str) -> dict[str, Any]:
    """Los ajustes de ``des.buttress`` (spec 016, T03; RF-016-17): el nombre del contrafuerte, su ``code`` (``BTR-001``)
    y el campo de la cota de coronación de su capa de zonas (``fields``; ``None`` si no lo lleva). La capa, la
    geometría, la partida, el perfil, la cota y lo demás son **parámetros** (``des.buttress.{e}.*``). ``ValueError`` si
    ``code`` no es el de un contrafuerte."""
    if not isinstance(request, ButtressRequest):
        raise TypeError(f"los ajustes de un contrafuerte salen de una ButtressRequest, no {request!r}")
    _typed_code(code, "buttress", "un contrafuerte")
    return {"name": request.name, "code": code, "fields": {"crown_field": request.fields.crown_field}}


def buttress_request(settings: Mapping[str, Any], parameters: Mapping[str, Any]) -> ButtressRequest:
    """El contrafuerte que repiten los ajustes ``settings`` de ``des.buttress`` con los valores de los parámetros de su
    entidad ``parameters`` (por último segmento: :func:`supported_values`). ``ValueError`` si no son los de un
    contrafuerte (nombrando el campo)."""
    what = "los ajustes de un contrafuerte"
    values_what = "los valores de un contrafuerte"
    data = _mapping(settings, what)
    fields_what = f"{what}, «fields»,"
    fields = _mapping(data.get("fields"), fields_what)
    values = _values_of(ButtressParam, parameters, values_what)
    texts = {name: _value_text(values, name, values_what, required=True) for name in ("layer", "feature", "start",
                                                                                      "profile")}
    assert all(texts.values())
    return ButtressRequest(
        name=_required_text(data, "name", what),
        fields=ButtressFields(layer=texts["layer"], crown_field=_optional_text(fields, "crown_field", fields_what)),
        feature=texts["feature"], start=texts["start"], profile=texts["profile"],
        support=_value_text(values, "support", values_what), crown_m=_number(values, "crown_m", values_what),
        reach_m=_number(values, "reach_m", values_what), metric=_value_text(values, "metric", values_what),
        protect=_value_flag(values, "protect", values_what), guard_m=_number(values, "guard_m", values_what),
        reason=_value_text(values, "reason", values_what))


def buttress_inputs(request: ButtressRequest, start: str, masks: Iterable[Use] = (),
                    supports: Iterable[str] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.buttress`` (spec 016, T03; RF-016-17; plan 016 §5.2.3), en su orden: la capa de las zonas de
    coronación (:data:`ENTITY_LAYER_ROLE`: la geometría y su hash), la superficie de partida ``start``
    (:data:`SURFACE_ROLE`; ya resuelta), las máscaras de la versión ``masks`` y, **añadidas al crear**, las superficies
    en las que se apoya, ``supports`` (:data:`SUPPORTED_ON_ROLE`: las que detecta el cálculo, las que declara el usuario y
    la de apoyo de la petición, resuelta), sin repetir. ``ValueError`` si faltan los nombres."""
    if not isinstance(request, ButtressRequest):
        raise TypeError(f"las entradas de un contrafuerte salen de una ButtressRequest, no {request!r}")
    found = [Use(_named(request.layer, "de la capa de las zonas de coronación"), ENTITY_LAYER_ROLE),
             Use(_named(start, "de la superficie de partida"), SURFACE_ROLE), *masks]
    found += [Use(_named(name, "de una superficie en la que se apoya"), SUPPORTED_ON_ROLE)
              for name in _codes(supports, "las superficies de apoyo")]
    return _unique(found)


def buttress_params(code: str, request: ButtressRequest, *, supports: bool = False) -> tuple[str, ...]:
    """Los parámetros que lee ``des.buttress`` de la entidad de código ``code`` (spec 016, T03; RF-016-17, RF-016-18;
    plan 016 §5.2.2): la capa, la geometría, la partida, el perfil, la cota de coronación y la métrica; el alcance y la
    superficie de apoyo, si la ``request`` los lleva; las dependencias declaradas, si ``supports``; **los cinco valores
    del perfil de la 013** (``des.bench.{p}.*``: su altura, su cara, su berma, su ancla y su factor de malla; ``ValueError``
    si el perfil no es un código válido); y los del proyecto (:data:`PLATFORM_COMMON_PARAMS`). ``ValueError`` si
    ``code`` no es el de un contrafuerte."""
    read = _supported_read(
        code, "buttress", "un contrafuerte",
        (ButtressParam.LAYER, ButtressParam.FEATURE, ButtressParam.START, ButtressParam.PROFILE,
         ButtressParam.CROWN, ButtressParam.METRIC),
        optional=((request.reach_m is not None, ButtressParam.REACH), (request.support is not None,
                                                                      ButtressParam.SUPPORT)),
        supports=supports)
    return _unique([*read, *profile_params([request.profile]), *PLATFORM_COMMON_PARAMS])


def body_settings(request: BodyRequest, code: str) -> dict[str, Any]:
    """Los ajustes de ``des.body`` (spec 016, T03; RF-016-20): el nombre del cuerpo y su ``code`` (``BDY-001``); la
    huella, los datos de espesor, la superficie, el sentido y la distancia máxima son **parámetros**
    (``des.body.{e}.*``). ``ValueError`` si ``code`` no es el de un cuerpo."""
    if not isinstance(request, BodyRequest):
        raise TypeError(f"los ajustes de un cuerpo apoyado salen de una BodyRequest, no {request!r}")
    _typed_code(code, "body", "un cuerpo apoyado")
    return {"name": request.name, "code": code}


def body_request(settings: Mapping[str, Any], parameters: Mapping[str, Any]) -> BodyRequest:
    """El cuerpo apoyado que repiten los ajustes ``settings`` de ``des.body`` con los valores de los parámetros de su
    entidad ``parameters`` (por último segmento: :func:`supported_values`). ``ValueError`` si no son los de un cuerpo
    (nombrando el campo)."""
    what = "los ajustes de un cuerpo apoyado"
    values_what = "los valores de un cuerpo apoyado"
    data = _mapping(settings, what)
    values = _values_of(BodyParam, parameters, values_what)
    texts = {name: _value_text(values, name, values_what, required=True)
             for name in ("layer", "feature", "data_layer", "data_field", "data_from", "surface", "sense")}
    assert all(texts.values())
    return BodyRequest(
        name=_required_text(data, "name", what), **texts,  # type: ignore[arg-type]
        start=_value_text(values, "start", values_what), max_distance_m=_number(values, "max_distance_m", values_what),
        zero_at_edge=_value_flag(values, "zero_at_edge", values_what),
        support=_value_text(values, "support", values_what), protect=_value_flag(values, "protect", values_what),
        guard_m=_number(values, "guard_m", values_what), reason=_value_text(values, "reason", values_what))


def body_inputs(request: BodyRequest, surface: str, masks: Iterable[Use] = (),
                supports: Iterable[str] = ()) -> tuple[Use, ...]:
    """Lo que consume ``des.body`` (spec 016, T03; RF-016-20; plan 016 §5.2.3), en su orden: la huella (la capa de
    entidades, :data:`ENTITY_LAYER_ROLE`), los datos de espesor (:data:`BODY_DATA_ROLE`: su geometría y su hash), la
    superficie conocida ``surface`` (:data:`SURFACE_ROLE`; ya resuelta), las máscaras de la versión ``masks`` y,
    **añadidas al crear**, lo que apoya, ``supports`` (:data:`SUPPORTED_ON_ROLE`), sin repetir. ``ValueError`` si
    faltan los nombres."""
    if not isinstance(request, BodyRequest):
        raise TypeError(f"las entradas de un cuerpo apoyado salen de una BodyRequest, no {request!r}")
    found = [Use(_named(request.layer, "de la capa de la huella"), ENTITY_LAYER_ROLE),
             Use(_named(request.data_layer, "de la capa de los datos de espesor"), BODY_DATA_ROLE),
             Use(_named(surface, "de la superficie conocida"), SURFACE_ROLE), *masks]
    found += [Use(_named(name, "de una superficie en la que se apoya"), SUPPORTED_ON_ROLE)
              for name in _codes(supports, "las superficies de apoyo")]
    return _unique(found)


def body_params(code: str, request: BodyRequest, *, supports: bool = False) -> tuple[str, ...]:
    """Los parámetros que lee ``des.body`` de la entidad de código ``code`` (spec 016, T03; RF-016-20 a RF-016-22; plan
    016 §5.2.2): la huella (capa y geometría), los datos de espesor (capa, campo y de dónde se leen), la superficie
    conocida, el sentido, la distancia máxima y el «cero en el borde»; la partida (solo «sobre una base») y la superficie
    de apoyo, si la ``request`` los lleva; las dependencias declaradas, si ``supports``; y, del proyecto, el espesor
    mínimo de la 012 por su clave. ``ValueError`` si ``code`` no es el de un cuerpo."""
    read = _supported_read(
        code, "body", "un cuerpo apoyado",
        (BodyParam.LAYER, BodyParam.FEATURE, BodyParam.DATA_LAYER, BodyParam.DATA_FIELD, BodyParam.DATA_FROM,
         BodyParam.SURFACE, BodyParam.SENSE),
        optional=((request.start is not None and BodySense(request.sense) is BodySense.ON_BASE, BodyParam.START),
                  (True, BodyParam.MAX_DISTANCE), (True, BodyParam.ZERO_AT_EDGE),
                  (request.support is not None, BodyParam.SUPPORT)),
        supports=supports)
    return _unique([*read, VERIFY_MIN_THICKNESS])
