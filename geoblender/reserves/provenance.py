# SPDX-License-Identifier: GPL-3.0-or-later
"""Declaraciones de procedencia de la cubicación (spec 011, T14; RF-011-05, RF-011-20,
RF-011-21, RF-011-22; ADR-0013, ADR-0025 §2; plan 011 §5.2.1, §5.2.3, D-16, D-25, D-30, D-38,
D-39).

Lo que ``res`` registra en la procedencia de la 008 y de la 009, declarado con tipos de
``core``. Importar este módulo no registra nada: lo registra ``bl/ops/res.py`` (T19) con sus
funciones de recálculo y de reproducción, que son de ``bl``; las pruebas, a mano
(``tests/support/res_fixtures.py``).

**Tipos de operación** (:data:`OPERATION_TYPES`, versión :data:`OP_VERSION`; plan §5.2.3):

- ``res.volume`` (:data:`VOLUME`), ``res.tonnage`` (:data:`TONNAGE`), ``res.difference``
  (:data:`DIFFERENCE`) y ``res.stages`` (:data:`STAGES`): de **versión** (RF-011-20; sus
  resultados son de la versión activa), se repiten solos y se reproducen con
  ``figure_tolerance`` :data:`FIGURE_TOLERANCE` (D-38). Una cubicación con unidades son **dos**
  operaciones encadenadas (D-16): ``res.volume`` (la geometría) y ``res.tonnage``, que consume
  su tabla y la columna, para que un K o una densidad no marquen ni rehagan los m³ in situ;
- ``res.edit_materials`` (:data:`EDIT_MATERIALS`): la columna de materiales, del **proyecto**
  (D-12), una edición a mano (no se repite sola).

Cada tipo dice las órdenes que lo lanzan (los ``bl_idname`` del catálogo de la 003) y los
ajustes de su orden que enseña su procedencia (:class:`~..core.provenance.contract.SettingDef`).

**Cifras** (:data:`FIGURES`, plan §5.2.3): las claves de ``reserves.table.QUANTITIES`` y las de
los momentos, con su unidad del catálogo (``m3``, ``m2``, ``t``, ``-``, ``%``, ``m3/m3``,
``t/t``); admiten negativos el neto, el efecto del factor combinado y las diferencias de los
momentos. :data:`DIFFERENCE_FIGURES`, las seis de los totales de ``res.difference``.

**Datos** (:data:`FAMILIES`; plan §5.2.1): ``res_<familia>_<nombre>`` (:func:`dataset_name`,
con el nombre de la cubicación en ASCII, ``gis.provenance.dataset_slug``), datos de la versión
con el código de la versión en su ubicación (``core.versions.model.version_locator``, D-34 de la
009: ``res_vol_mensual_v03``, ``rasters/res_dif_mensual_v03.tif``): las tablas de la cubicación
(``vol``), de sus toneladas (``ton``) y de sus momentos (``stg``), tipo ``table`` leídas con
``core.gpkg_layer@1`` (el lector de las tablas del GeoPackage: lee tablas y capas, no
``report``), y la rejilla de diferencias (``dif``), ``raster`` con ``gis.geotiff@1``. La columna
de materiales es el dato del proyecto :data:`MATERIALS` (:func:`materials_spec`). Ninguno es
editable en QGIS (RF-008-56).

**Lo que anota una operación al empezar** (``core.provenance.operations.begin_operation``):
:func:`volume_inputs` (las superficies con su papel ``start`` y ``final``, o lo congelado de la
revisión de la que parte la versión; el ámbito ``scope``; los dominios ``domains``; la columna
``materials`` y, por unidad, ``base_<u>`` y ``thickness_<u>``, D-39), :func:`volume_params` (el
espesor mínimo y, con unidades, el umbral de presencia: del proyecto, RF-011-21) y
:func:`volume_settings` (lo que la vuelve a pedir igual); :func:`tonnage_inputs` y
:func:`tonnage_params` (la densidad, el K y los porcentajes de cada elemento de la columna,
resueltos versión → proyecto, RF-011-21). :func:`volume_request` es lo contrario de
:func:`volume_settings`: la cubicación que repiten sus ajustes al recalcularla
(``reserves.store.recompute_run``) y al reproducirla (``reserves.reproduce``; A12). Las
funciones de reproducir de los tipos que se repiten son las de ``reserves.reproduce.REPRODUCE``
(la de ``res.stages``, con su cálculo). Python puro (nivel 9).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

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
from ..core.provenance.operations import Use
from ..core.versions.model import version_locator
from ..gis.content import GEOTIFF
from ..gis.provenance import dataset_slug
from .materials import TABLE as MATERIALS_TABLE
from .materials import Kind, MaterialColumn
from .params import ANTHROPIC_PRESENCE, MIN_THICKNESS, density_key, percent_key, swell_key
from .slices import Slices
from .surfaces import SurfaceRef
from .volumes import FINAL, START, VolumeRequest, base_role, thickness_role

__all__ = [
    "DIFFERENCE",
    "DIFFERENCE_FIGURES",
    "DIFFERENCE_GRID",
    "DOMAINS_ROLE",
    "EDIT_MATERIALS",
    "FAMILIES",
    "FAMILIES_BY_CODE",
    "FIGURES",
    "FIGURE_TOLERANCE",
    "MATERIALS",
    "MATERIALS_ROLE",
    "MODULE",
    "OPERATION_TYPES",
    "OPERATION_TYPES_BY_NAME",
    "OP_VERSION",
    "REPRODUCIBLE",
    "SCOPE_ROLE",
    "STAGES",
    "STAGE_TABLE",
    "TONNAGE",
    "TONNES",
    "VERSION_TYPES",
    "VOLUME",
    "VOLUMES",
    "VOLUMES_ROLE",
    "DatasetFamily",
    "OperationType",
    "dataset_locator",
    "dataset_name",
    "dataset_spec",
    "materials_spec",
    "operation_def",
    "operation_defs",
    "tonnage_inputs",
    "tonnage_params",
    "tonnage_settings",
    "volume_inputs",
    "volume_params",
    "volume_request",
    "volume_settings",
]

MODULE = "res"
"""El código de la cubicación y las reservas (``core.catalog.schema.MODULE_CODES``)."""
OP_VERSION = "1.0"
"""La versión inicial del algoritmo de cada tipo (sube cuando un cambio puede mover una cifra,
RF-008-24)."""
FIGURE_TOLERANCE = Tolerance(relative=1e-9)
"""La tolerancia de las cifras al reproducir (D-38, D-14 c): con el mismo Geoblender y numpy
salen bit a bit; con otro numpy, el último bit puede cambiar."""

# --- Tipos de operación ------------------------------------------------------------------------

VOLUME = "res.volume"
TONNAGE = "res.tonnage"
DIFFERENCE = "res.difference"
STAGES = "res.stages"
EDIT_MATERIALS = "res.edit_materials"

_BETWEEN = "geoblender.res_compute_volume_between_surfaces"
_BREAKDOWN = "geoblender.res_compute_volume_breakdown"
_DIFFERENCE_COMMAND = "geoblender.res_compute_surface_difference"
_STAGES_COMMAND = "geoblender.res_compute_extraction_stages"
_MATERIALS_COMMAND = "geoblender.res_edit_materials"

# --- Familias de datos y papeles ----------------------------------------------------------------

VOLUMES = "vol"
"""La tabla de una cubicación (``res_vol_<nombre>``)."""
TONNES = "ton"
"""La tabla de sus toneladas (``res_ton_<nombre>``)."""
STAGE_TABLE = "stg"
"""La tabla de una cubicación por momentos (``res_stg_<nombre>``)."""
DIFFERENCE_GRID = "dif"
"""La rejilla de diferencias (``rasters/res_dif_<nombre>.tif``)."""
MATERIALS = MATERIALS_TABLE
"""El dato de la columna de materiales del proyecto: ``res_materials`` (su tabla)."""
MATERIALS_ROLE = "materials"
"""El papel de la columna, como entrada y como salida."""
VOLUMES_ROLE = "volumes"
"""El papel de la tabla de una cubicación (la salida de ``res.volume``, la entrada de
``res.tonnage``)."""
SCOPE_ROLE = "scope"
"""El papel de la capa del ámbito."""
DOMAINS_ROLE = "domains"
"""El papel de la capa de dominios."""

_PREFIX = f"{MODULE}_"
_YES_NO = ((True, "Yes"), (False, "No"))


@dataclass(frozen=True, slots=True)
class DatasetFamily:
    """Una familia de datos de ``res`` (plan §5.2.1): su código (``vol``), su tipo y su
    almacén, su lector (con versión), su papel de salida, la extensión de su fichero (``""`` en
    una tabla) y el comienzo de su identificador en ``gpkg_contents`` (una tabla)."""

    code: str
    kind: str
    store: Store
    reader: str
    role: str
    extension: str
    label: str

    @property
    def prefix(self) -> str:
        """El comienzo del nombre de sus datos: ``res_<código>_``."""
        return f"{_PREFIX}{self.code}_"


FAMILIES: tuple[DatasetFamily, ...] = (
    DatasetFamily(VOLUMES, "table", Store.GPKG, GPKG_LAYER.id, VOLUMES_ROLE, "", "Cubicación"),
    DatasetFamily(TONNES, "table", Store.GPKG, GPKG_LAYER.id, "tonnage", "",
                  "Toneladas de la cubicación"),
    DatasetFamily(STAGE_TABLE, "table", Store.GPKG, GPKG_LAYER.id, "stages", "",
                  "Cubicación por momentos"),
    DatasetFamily(DIFFERENCE_GRID, "raster", Store.RASTERS, GEOTIFF.id, "difference", ".tif",
                  "Rejilla de diferencias"),
)
"""Las familias de datos de la versión de ``res`` (plan §5.2.1)."""
FAMILIES_BY_CODE: Mapping[str, DatasetFamily] = MappingProxyType(
    {family.code: family for family in FAMILIES})
"""Las familias por código (solo lectura)."""


def _family(code: object) -> DatasetFamily:
    found = FAMILIES_BY_CODE.get(code) if isinstance(code, str) else None
    if found is None:
        raise ValueError(f"{code!r} no es una familia de datos de la cubicación: es una de "
                         f"{', '.join(FAMILIES_BY_CODE)}")
    return found


def dataset_name(family: str, name: str) -> str:
    """El nombre estable del dato de la familia ``family`` de la cubicación ``name``:
    ``res_<familia>_<nombre>`` (el nombre en ASCII en minúsculas, ``gis.provenance.dataset_slug``:
    el mismo nombre da el mismo dato, D-30). ``GisError`` ``gis.dataset_name_invalid`` si no
    queda ninguna letra ni cifra; ``ValueError`` si la familia no es de ``res``."""
    return _family(family).prefix + dataset_slug(name)


def dataset_locator(family: str, name: str, version_code: str) -> str:
    """La ubicación del dato de la familia ``family`` de la cubicación ``name`` en la versión
    ``version_code`` («V03»): la tabla (``res_vol_<nombre>_v03``) o la ruta en su almacén
    (``rasters/res_dif_<nombre>_v03.tif``; D-34 de la 009)."""
    found = _family(family)
    base = dataset_name(family, name)
    if found.store is Store.GPKG:
        return version_locator(base, version_code)
    return version_locator(f"{found.store}/{base}{found.extension}", version_code)


def dataset_spec(family: str, name: str, version_code: str, *,
                 content: ContentDigest | None = None,
                 crs_epsg: int | None = None) -> DatasetSpec:
    """La ``DatasetSpec`` del dato de la familia ``family`` de la cubicación ``name`` en la
    versión ``version_code`` (RF-008-17, RF-011-22): su nombre, su tipo, su almacén, su
    ubicación, su lector y su papel; sin selector y no editable en QGIS. ``content``: su hash,
    calculado fuera de la transacción (R4); ``crs_epsg``, el de una rejilla."""
    found = _family(family)
    return DatasetSpec(dataset_name(family, name), MODULE, found.kind, found.store,
                       dataset_locator(family, name, version_code), reader=found.reader,
                       role=found.role, content=content, crs_epsg=crs_epsg)


def materials_spec(content: ContentDigest | None = None) -> DatasetSpec:
    """La ``DatasetSpec`` de la columna de materiales del proyecto (:data:`MATERIALS`; D-12):
    la tabla ``res_materials`` leída con ``core.gpkg_layer@1``, no editable en QGIS."""
    return DatasetSpec(MATERIALS, MODULE, "table", Store.GPKG, MATERIALS_TABLE,
                       reader=GPKG_LAYER.id, role=MATERIALS_ROLE, content=content)


# --- Tipos de operación ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperationType:
    """Un tipo de operación de ``res`` sin sus funciones (plan §5.2.3): ``op_type``, su nombre
    visible (``label_msgid``, con su español en ``core/i18n/messages.toml``), su ámbito
    (``version`` o ``project``), si se repite solo (y entonces se reproduce), las órdenes que lo
    lanzan, las familias de datos que produce y los ajustes de su orden que enseña su
    procedencia."""

    op_type: str
    label_msgid: str
    scope: str
    repeatable: bool
    commands: tuple[str, ...]
    outputs: tuple[str, ...] = ()
    settings: tuple[SettingDef, ...] = ()

    def definition(self, recompute: RecomputeFunction | None = None,
                   reproduce: ReproduceFunction | None = None) -> OperationDef:
        """Su ``OperationDef`` (versión :data:`OP_VERSION`) con las funciones de ``bl``: la de
        recálculo y la de reproducción de uno que se repite solo (con
        :data:`FIGURE_TOLERANCE`); ninguna en uno que no (``ValueError`` de
        ``OperationDef`` si no casan)."""
        return OperationDef(
            self.op_type, OP_VERSION, MODULE, self.label_msgid, self.repeatable,
            scope=self.scope, commands=self.commands, recompute=recompute,
            settings=self.settings, reproduce=reproduce,
            figure_tolerance=FIGURE_TOLERANCE if reproduce is not None else None,
        )


def _surface_settings(role: str, label: str) -> SettingDef:
    return SettingDef(f"{role}.elevation_m", label, unit="m")


_VOLUME_SETTINGS = (
    _surface_settings(START, "Constant start elevation"),
    _surface_settings(FINAL, "Constant final elevation"),
    SettingDef("bench_height_m", "Bench height", unit="m"),
    SettingDef("bench_anchor_m", "Bench anchor elevation", unit="m"),
    SettingDef("difference_grid", "Difference grid", choices=_YES_NO),
    SettingDef("point_scale", "Projection scale factor", unit="-"),
)

OPERATION_TYPES: tuple[OperationType, ...] = (
    OperationType(VOLUME, "Volumetrics between surfaces", "version", True,
                  (_BETWEEN, _BREAKDOWN), (VOLUMES, DIFFERENCE_GRID), _VOLUME_SETTINGS),
    OperationType(TONNAGE, "Tonnage of a cubication", "version", True, (_BREAKDOWN,),
                  (TONNES,)),
    OperationType(DIFFERENCE, "Difference between surfaces", "version", True,
                  (_DIFFERENCE_COMMAND,), (DIFFERENCE_GRID,), _VOLUME_SETTINGS[:2]),
    OperationType(STAGES, "Volumetrics by extraction stages", "version", True,
                  (_STAGES_COMMAND,), (STAGE_TABLE,)),
    OperationType(EDIT_MATERIALS, "Edit of the materials column", "project", False,
                  (_MATERIALS_COMMAND,)),
)
"""Los tipos de operación de ``res``, en el orden del plan §5.2.3."""
OPERATION_TYPES_BY_NAME: Mapping[str, OperationType] = MappingProxyType(
    {declared.op_type: declared for declared in OPERATION_TYPES})
"""Los tipos por nombre (solo lectura)."""
VERSION_TYPES: tuple[str, ...] = tuple(t.op_type for t in OPERATION_TYPES
                                       if t.scope == "version")
"""Los tipos de versión (RF-011-20)."""
REPRODUCIBLE: tuple[str, ...] = tuple(t.op_type for t in OPERATION_TYPES if t.repeatable)
"""Los tipos que se repiten solos y se reproducen (los de versión)."""


def _operation_type(op_type: object) -> OperationType:
    found = OPERATION_TYPES_BY_NAME.get(op_type) if isinstance(op_type, str) else None
    if found is None:
        raise ValueError(f"{op_type!r} no es un tipo de operación de la cubicación: es uno de "
                         f"{', '.join(OPERATION_TYPES_BY_NAME)}")
    return found


def operation_def(op_type: str, recompute: RecomputeFunction | None = None,
                  reproduce: ReproduceFunction | None = None) -> OperationDef:
    """El ``OperationDef`` de ``op_type`` con las funciones de recálculo y de reproducción que
    le da ``bl`` (las de uno que se repite solo; ``None`` en ``res.edit_materials``).
    ``ValueError`` si el tipo no es de ``res`` o las funciones no casan con él."""
    return _operation_type(op_type).definition(recompute, reproduce)


def operation_defs(recompute: Mapping[str, RecomputeFunction],
                   reproduce: Mapping[str, ReproduceFunction]) -> tuple[OperationDef, ...]:
    """Los ``OperationDef`` de todos los tipos de :data:`OPERATION_TYPES`, en su orden, cada
    uno con su función de ``recompute`` y de ``reproduce`` (por tipo: las de cada uno que se
    repite solo y ninguna más). ``ValueError`` si sobra o falta alguna."""
    for name, given in (("recálculo", recompute), ("reproducción", reproduce)):
        if set(given) != set(REPRODUCIBLE):
            raise ValueError(f"las funciones de {name} son las de {', '.join(REPRODUCIBLE)}, "
                             f"no las de {', '.join(sorted(map(str, given)))}")
    return tuple(declared.definition(recompute.get(declared.op_type),
                                     reproduce.get(declared.op_type))
                 for declared in OPERATION_TYPES)


# --- Cifras ------------------------------------------------------------------------------------

DIFFERENCE_FIGURES: tuple[str, ...] = (
    "res.cut_m3", "res.fill_m3", "res.net_m3", "res.area_m2", "res.nodata_area_m2",
    "res.still_area_m2",
)
"""Las seis cifras de los totales de una cubicación: las de ``res.difference`` (RF-011-23)."""

FIGURES: tuple[FigureDef, ...] = (
    FigureDef("res.cut_m3", "m3", "Cut volume"),
    FigureDef("res.fill_m3", "m3", "Fill volume"),
    FigureDef("res.net_m3", "m3", "Net volume", allow_negative=True),
    FigureDef("res.area_m2", "m2", "Area with data in both surfaces"),
    FigureDef("res.nodata_area_m2", "m2", "Area without data"),
    FigureDef("res.still_area_m2", "m2", "Area without movement"),
    FigureDef("res.unit_volume_m3", "m3", "Volume of the unit"),
    FigureDef("res.grid_scale_factor", "-", "Combined scale factor"),
    FigureDef("res.ground_effect_pct", "%", "Effect of the combined scale factor",
              allow_negative=True),
    FigureDef("res.unit_swell_m3", "m3", "Swollen volume of the unit"),
    FigureDef("res.unit_t", "t", "Tonnage of the unit"),
    FigureDef("res.total_t", "t", "Total tonnage"),
    FigureDef("res.useful_m3", "m3", "Useful volume in situ"),
    FigureDef("res.waste_m3", "m3", "Waste volume in situ"),
    FigureDef("res.useful_t", "t", "Useful tonnage"),
    FigureDef("res.waste_t", "t", "Waste tonnage"),
    FigureDef("res.waste_ratio_m3", "m3/m3", "Waste to useful ratio by volume"),
    FigureDef("res.waste_ratio_t", "t/t", "Waste to useful ratio by mass"),
    FigureDef("res.intrinsic_ratio_m3", "m3/m3", "Intrinsic ratio by volume"),
    FigureDef("res.intrinsic_ratio_t", "t/t", "Intrinsic ratio by mass"),
    FigureDef("res.stages_sum_m3", "m3", "Sum of the extraction stages"),
    FigureDef("res.stages_diff_m3", "m3",
              "Difference between the stages and the direct cubication", allow_negative=True),
    FigureDef("res.stages_diff_pct", "%",
              "Relative difference between the stages and the direct cubication",
              allow_negative=True),
)
"""Las cifras de ``res`` (plan §5.2.3; RF-011-22), cada una con su unidad del catálogo."""


# --- Lo que anota una operación al empezar ---------------------------------------------------


def _surface_use(ref: SurfaceRef, role: str, frozen: str | None) -> Use | None:
    """Lo que consume la superficie ``ref`` con el papel ``role``: un dato, lo congelado en la
    revisión ``frozen`` (la de la que parte la versión) o nada (una cota constante)."""
    if ref.dataset is not None:
        return Use(ref.dataset, role)
    if ref.frozen is not None:
        if frozen is None:
            raise ValueError(f"«{ref.shown}» está congelada: falta la revisión de la que parte "
                             "la versión (frozen)")
        return Use(ref.frozen, role, frozen=frozen)
    return None


def volume_inputs(request: VolumeRequest, *, scope: str | None = None,
                  frozen: str | None = None) -> tuple[Use, ...]:
    """Lo que consume la cubicación ``request`` (``Use``, RF-011-20; D-39), en su orden: la
    superficie de partida (``start``) y la final (``final``) —un dato, o lo congelado en la
    revisión ``frozen``; una cota constante no es una entrada—, la capa del ámbito ``scope`` (su
    nombre: obligatorio si la cubicación tiene ámbito), la de dominios y, con la columna, la
    columna (:data:`MATERIALS`) y la base y el espesor de cada unidad que los tiene como datos.
    ``ValueError`` si falta el nombre del ámbito o la revisión de lo congelado."""
    found = [use for use in (_surface_use(request.start, START, frozen),
                             _surface_use(request.final, FINAL, frozen)) if use is not None]
    if request.scope is not None:
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError(f"la cubicación «{request.name}» tiene ámbito: falta el nombre del "
                             "dato de su capa (scope)")
        found.append(Use(scope, SCOPE_ROLE))
    elif scope is not None:
        raise ValueError(f"la cubicación «{request.name}» no tiene ámbito: sobra «{scope}»")
    if request.domains is not None:
        found.append(Use(request.domains.layer, DOMAINS_ROLE))
    if request.column is not None:
        found.append(Use(MATERIALS, MATERIALS_ROLE))
        for unit in request.column.units:
            for ref, role in ((unit.base, base_role(unit.code)),
                              (unit.thickness, thickness_role(unit.code))):
                if ref is not None and ref.dataset is not None:
                    found.append(Use(ref.dataset, role))
    return tuple(found)


def volume_params(request: VolumeRequest) -> tuple[str, ...]:
    """Los parámetros que lee la cubicación ``request`` (RF-011-21: del proyecto): el espesor
    mínimo y, si reparte por unidades, el umbral de presencia de lo antrópico."""
    if request.column is None:
        return (MIN_THICKNESS,)
    return (MIN_THICKNESS, ANTHROPIC_PRESENCE)


def _surface_setting(ref: SurfaceRef) -> dict[str, Any]:
    if ref.dataset is not None:
        return {"dataset": ref.dataset}
    if ref.frozen is not None:
        return {"frozen": ref.frozen}
    return {"elevation_m": ref.elevation}


def volume_settings(request: VolumeRequest, *, scope: str | None = None) -> dict[str, Any]:
    """Los ajustes de la cubicación ``request`` (``gb_operation.settings``; JSON sin rutas): lo
    que la vuelve a pedir igual con sus entradas (el nombre, las superficies —el dato, lo
    congelado o la cota constante, m—, el ámbito, el campo de dominios, las rodajas —altura y
    anclaje o la lista de cotas, m—, si reparte por unidades, si escribe la rejilla y el factor
    de escala de la proyección que recibió, D-34)."""
    slices = request.slices
    return {
        "name": request.name,
        START: _surface_setting(request.start),
        FINAL: _surface_setting(request.final),
        "scope": scope,
        "domains_field": None if request.domains is None else request.domains.field,
        "bench_height_m": None if slices is None else slices.height_m,
        "bench_anchor_m": None if slices is None else slices.anchor_m,
        "bench_levels_m": None if slices is None or slices.levels is None
        else list(slices.levels),
        "units": request.column is not None,
        "difference_grid": request.difference_grid,
        "point_scale": request.point_scale,
    }


def _surface_ref(value: object, role: str) -> SurfaceRef:
    """La superficie ``role`` de los ajustes de una cubicación (:func:`_surface_setting`)."""
    if not isinstance(value, Mapping) or len(value) != 1:
        raise ValueError(f"los ajustes de la superficie «{role}» son el dato, lo congelado o la "
                         f"cota constante (uno), no {value!r}")
    ((kind, given),) = value.items()
    if kind == "dataset":
        return SurfaceRef(dataset=given)
    if kind == "frozen":
        return SurfaceRef(frozen=given)
    if kind == "elevation_m":
        return SurfaceRef(elevation=given)
    raise ValueError(f"los ajustes de la superficie «{role}» no dicen «{kind}»")


def _slices(settings: Mapping[str, Any]) -> Slices | None:
    """Las rodajas de los ajustes de una cubicación (o ninguna)."""
    height, anchor = settings.get("bench_height_m"), settings.get("bench_anchor_m")
    levels = settings.get("bench_levels_m")
    if height is None and anchor is None and levels is None:
        return None
    return Slices(height, anchor, None if levels is None else tuple(levels))


def volume_request(settings: Mapping[str, Any], *,
                   column: MaterialColumn | None = None) -> VolumeRequest:
    """La cubicación que repiten los ajustes ``settings`` de una operación ``res.volume`` o
    ``res.difference`` (los de :func:`volume_settings`), con la columna ``column`` que consume
    si reparte por unidades: lo que la vuelve a pedir igual al recalcularla y al reproducirla
    (A12). El espesor mínimo y el umbral de presencia no son ajustes: los de la operación
    (``reserves.store.volume_run``) o los congelados (``reserves.reproduce``).

    ``ValueError`` si los ajustes no son los de una cubicación, si la columna sobra o falta, o
    si tiene ámbito o dominios: sus capas (D-32) aún no se leen para repetirla."""
    if not isinstance(settings, Mapping):
        raise TypeError(f"los ajustes de una cubicación son un diccionario, no {settings!r}")
    name = settings.get("name")
    if not isinstance(name, str):
        raise ValueError(f"los ajustes de una cubicación llevan su nombre, no {name!r}")
    if settings.get("scope") is not None or settings.get("domains_field") is not None:
        raise ValueError(f"la cubicación «{name}» tiene ámbito o dominios: sus capas aún no se "
                         "leen para repetirla")
    units = settings.get("units", False)
    if not isinstance(units, bool) or units != (column is not None):
        raise ValueError(f"la cubicación «{name}» {'' if units else 'no '}reparte por unidades: "
                         f"{'falta' if units else 'sobra'} la columna de materiales")
    grid = settings.get("difference_grid", False)
    return VolumeRequest(name, _surface_ref(settings.get(START), START),
                         _surface_ref(settings.get(FINAL), FINAL), slices=_slices(settings),
                         column=column, difference_grid=grid,
                         point_scale=settings.get("point_scale"))


def tonnage_inputs(name: str) -> tuple[Use, ...]:
    """Lo que consume ``res.tonnage`` de la cubicación ``name`` (D-16): su tabla de volúmenes
    (``res_vol_<nombre>``, de la versión; papel ``volumes``) y la columna de materiales."""
    return (Use(dataset_name(VOLUMES, name), VOLUMES_ROLE), Use(MATERIALS, MATERIALS_ROLE))


def tonnage_settings(name: str) -> dict[str, Any]:
    """Los ajustes de ``res.tonnage`` de la cubicación ``name``: su nombre."""
    return {"name": name}


def tonnage_params(column: MaterialColumn) -> tuple[str, ...]:
    """Los parámetros que lee ``res.tonnage`` con la columna ``column`` (RF-011-21, D-11): de
    arriba abajo, la densidad y el K de cada unidad que no es compuesta y, de cada componente de
    una compuesta, la densidad, el K y su porcentaje."""
    found: list[str] = []
    for unit in column.units:
        if unit.kind is not Kind.COMPOUND:
            found += [density_key(unit.code), swell_key(unit.code)]
            continue
        for component in unit.components:
            found += [density_key(unit.code, component.code),
                      swell_key(unit.code, component.code),
                      percent_key(unit.code, component.code)]
    return tuple(found)
