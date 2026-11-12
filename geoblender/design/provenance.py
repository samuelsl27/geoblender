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
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
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
from ..core.provenance.figures import FigureSpec
from ..core.provenance.operations import Use
from ..core.versions.model import version_locator
from ..gis.content import GEOTIFF
from ..gis.masks.provenance import SEARCHES_ROLE, SECTORS_ROLE
from ..gis.provenance import dataset_slug
from .model import (
    AnchorMode,
    BenchSense,
    DesignRequest,
    Direction,
    EnvelopeRequest,
    Metric,
    Order,
    SeedKind,
    SeedSource,
    SlopeMode,
    Surface,
    ToFinalMode,
    WorkDomain,
    Zone,
    ZoneKind,
)
from .params import (
    TOLERANCE_FACE,
    VERIFY_MIN_THICKNESS,
    WARNING_RATIO,
    BenchParam,
    bench_key,
)

if TYPE_CHECKING:  # solo para los tipos: importar el informe arrastraría los cálculos
    from .report import DesignReport

__all__ = [
    "ANCHORS_ROLE",
    "AREA_FIGURES",
    "BERMS_GRID",
    "BERM_TABLE",
    "CLASSIFICATION_GRID",
    "CLASSIFICATION_ROLE",
    "COMMAND",
    "CROWN_SEEDS",
    "CUT_M3",
    "DESIGN_FIGURES",
    "DESIGN_GRID",
    "DESIGN_SETTINGS",
    "DESIGN_SURFACE_ROLE",
    "DOMAIN_LAYER_ROLE",
    "EDGE_REPORT_ROLE",
    "EDGE_REPORT_TABLE",
    "EDGE_TRANSITION",
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
    "FILL_M3",
    "FILL_ONLY",
    "FILL_ONLY_COMMAND",
    "FILL_ONLY_FIGURES",
    "FILL_ONLY_SETTINGS",
    "FINAL_ENVELOPE_GRID",
    "FINAL_ENVELOPE_ROLE",
    "FINAL_GRID",
    "LIMIT_COMMAND",
    "MODULE",
    "OPERATION_TYPES",
    "OPERATION_TYPES_BY_NAME",
    "OP_VERSION",
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
    "REPORT_TABLE",
    "REPRODUCIBLE",
    "SEARCHES_ROLE",
    "SECTORS_ROLE",
    "SECTOR_SCOPE_KEY",
    "SEEDS_GRID_ROLE",
    "STEPPED",
    "SURFACE_ROLE",
    "SURFACE_SCOPE_KEY",
    "TRANSITIONS_COMMAND",
    "TRANSITION_FIGURES",
    "TRANSITION_GRID",
    "TWO_SURFACES_FIGURES",
    "VERSION_TYPES",
    "ZONE_LAYER_ROLE",
    "DatasetFamily",
    "OperationType",
    "dataset_locator",
    "dataset_name",
    "dataset_spec",
    "design_figures",
    "design_inputs",
    "design_params",
    "design_request",
    "design_settings",
    "design_start",
    "envelope_figures",
    "envelope_inputs",
    "envelope_params",
    "envelope_request",
    "envelope_settings",
    "figure_scope",
    "operation_def",
    "operation_defs",
    "profile_params",
    "quarry_figure_scope",
    "quarry_operation_defs",
    "sector_inputs",
    "settings_pending",
    "settings_previous",
    "settings_touched",
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


@dataclass(frozen=True, slots=True)
class DatasetFamily:
    """Una familia de datos de ``des`` (plan §5.2.3): su código (``env``), su tipo y su almacén,
    su lector (con versión), su papel de salida, la extensión de su fichero (``""`` en una tabla)
    y su nombre visible."""

    code: str
    kind: str
    store: Store
    reader: str
    role: str
    extension: str
    label: str

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
"""El recinto de excavación: 1 dentro, sin dato fuera (``rasters/des_rcn_<nombre>_<vNN>.tif``)."""
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
"""El papel del recinto de excavación."""
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

QUARRY_FAMILIES: tuple[DatasetFamily, ...] = (
    DatasetFamily(EXCAVATION_AREA_GRID, "raster", Store.RASTERS, GEOTIFF.id, EXCAVATION_AREA_ROLE,
                  ".tif", "Recinto de excavación"),
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
FAMILIES_BY_CODE: Mapping[str, DatasetFamily] = MappingProxyType(
    {family.code: family for family in (*FAMILIES, *QUARRY_FAMILIES)})
"""Las familias de las dos specs por código (solo lectura)."""
if len(FAMILIES_BY_CODE) != len(FAMILIES) + len(QUARRY_FAMILIES):  # pragma: no cover
    raise RuntimeError("dos familias de datos del diseño con el mismo código")


def _family(code: object) -> DatasetFamily:
    found = FAMILIES_BY_CODE.get(code) if isinstance(code, str) else None
    if found is None:
        raise ValueError(f"{code!r} no es una familia de datos del diseño: es una de "
                         f"{', '.join(FAMILIES_BY_CODE)}")
    return found


def dataset_name(family: str, name: str) -> str:
    """El nombre estable del dato de la familia ``family`` de la operación ``name``:
    ``des_<familia>_<nombre>`` (el nombre en ASCII en minúsculas, ``gis.provenance.dataset_slug``:
    el mismo nombre da el mismo dato). ``GisError`` ``gis.dataset_name_invalid`` si no queda
    ninguna letra ni cifra; ``ValueError`` si la familia no es de ``des``."""
    return _family(family).prefix + dataset_slug(name)


def dataset_locator(family: str, name: str, version_code: str) -> str:
    """La ubicación del dato de la familia ``family`` de la operación ``name`` en la versión
    ``version_code`` («V03»): la tabla (``des_bmt_<nombre>_v03``) o la ruta en su almacén
    (``rasters/des_srf_<nombre>_v03.tif``; D-34 de la 009)."""
    found = _family(family)
    base = dataset_name(family, name)
    if found.store is Store.GPKG:
        return version_locator(base, version_code)
    return version_locator(f"{found.store}/{base}{found.extension}", version_code)


def dataset_spec(family: str, name: str, version_code: str, *,
                 content: ContentDigest | None = None,
                 crs_epsg: int | None = None) -> DatasetSpec:
    """La ``DatasetSpec`` del dato de la familia ``family`` de la operación ``name`` en la
    versión ``version_code`` (RF-008-17, RF-013-31): su nombre, su tipo, su almacén, su
    ubicación, su lector y su papel; sin selector y no editable en QGIS. ``content``: su hash,
    calculado fuera de la transacción (R4); ``crs_epsg``, el de una rejilla."""
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


@dataclass(frozen=True, slots=True)
class OperationType:
    """Un tipo de operación de ``des`` sin sus funciones (plan §5.2.3): ``op_type``, su nombre
    visible (``label_msgid``, con su español en ``core/i18n/messages.toml``), las familias de
    datos que produce y los ajustes de su orden que enseña su procedencia; con su nombre, sus
    cifras (``figures``), las órdenes que lo lanzan (``commands``; por defecto, :data:`COMMAND`) y
    si se reproduce (``reproducible``). Todos son de versión (RF-009-05) y se repiten solos."""

    op_type: str
    label_msgid: str
    outputs: tuple[str, ...]
    settings: tuple[SettingDef, ...]
    figures: tuple[FigureDef, ...] = ()
    commands: tuple[str, ...] = (COMMAND,)
    reproducible: bool = True

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
            self.op_type, OP_VERSION, MODULE, self.label_msgid, True, scope="version",
            commands=self.commands, recompute=recompute, settings=self.settings,
            reproduce=reproduce,
            figure_tolerance=FIGURE_TOLERANCE if reproduce is not None else None)


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
OPERATION_TYPES_BY_NAME: Mapping[str, OperationType] = MappingProxyType(
    {declared.op_type: declared for declared in (*OPERATION_TYPES, *QUARRY_OPERATION_TYPES)})
"""Los tipos de las dos specs por nombre (solo lectura)."""
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


def operation_def(op_type: str, recompute: RecomputeFunction | None = None,
                  reproduce: ReproduceFunction | None = None) -> OperationDef:
    """El ``OperationDef`` de ``op_type`` (de la 013 o de la 014) con las funciones de recálculo y
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


def settings_previous(settings: Mapping[str, Any]) -> dict[str, Any] | None:
    """Lo anterior con que se comparó el escalonado de unos ajustes (``operation``, ``revision``,
    ``cut_m3`` y ``fill_m3``; D-25), o ``None`` si no se comparó con nada. ``ValueError`` si no
    tiene esa forma."""
    value = _mapping(settings, "los ajustes de un escalonado").get("previous")
    return None if value is None else _previous(value)


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
