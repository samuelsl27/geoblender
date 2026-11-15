# SPDX-License-Identifier: GPL-3.0-or-later
"""Declaraciones de procedencia de la compilación de las restricciones (spec 012; RF-012-11,
RF-012-16; plan 012 §5.2.3, D-24, D-37).

- :data:`COMPILE` (``gis.compile_constraints``): operación de **versión** que se repite sola y se
  reproduce con :data:`FIGURE_TOLERANCE` (10⁻⁹ relativo, D-37). Importar este módulo no registra
  nada: lo registra ``bl`` (con su recálculo); las pruebas, a mano.
- **Datos de la versión** (:data:`FAMILIES`, D-24), ``gis_<familia>`` con el código de la versión
  en su ubicación (``core.versions.model.version_locator``): la rejilla de clases
  (``rasters/gis_msk_<vNN>.tif``, ``gis.geotiff@1``), las zonas en tramos de fila
  (``gis_mskz_<vNN>``), el informe en formato largo (``gis_mskr_<vNN>``), las partes de la franja
  (``gis_mskp_<vNN>``, una capa de puntos) y **las restricciones compiladas**
  (``gis_mskg_<vNN>``, polígonos con su código y su tipo: lo que lee la compilación siguiente
  para lo ganado y lo perdido, A5; decisión de la T10). Las tablas, con ``core.gpkg_layer@1``;
  ninguna editable en QGIS.
- **Entradas** (:func:`compile_inputs`): las tres capas de restricciones, **la tabla de las
  restricciones declaradas por las entidades de la versión** si está viva (spec 015, T18;
  RF-012-16, RF-012-29: ``des_decl_<vNN>``, papel :data:`DECLARED_ROLE`; sin ella, las de siempre),
  los sectores y las búsquedas (las que están registradas); **parámetros** (:func:`compile_params`):
  de cada restricción **del proyecto** con código, su «activa» y, si lo está, lo que pide su tipo
  (resueltos versión → proyecto al empezar, RF-009-24). Las **declaradas** no tienen parámetros en
  el almacén (P-8 de la 015): su resguardo hacia fuera y su «activa» son columnas de su tabla, que
  es una entrada (si cambian, la compilación queda obsoleta), y :func:`declared_resolved` los da
  bajo las **mismas claves** (``core.constraint.dec__plt_001.buffer_out_m``) para que la compilación
  las trate como a las demás; **ajustes** (:func:`compile_settings`): la rejilla, lo de la
  compilación anterior (A5) y los sectores sin búsqueda vigente (RF-012-10, D-26).
- **Cifras** (:data:`FIGURES`): las áreas de los límites y de las máscaras, y la de cada zona y
  la que queda fuera de la rejilla (ámbito ``{"constraint": código}``).

Python puro (nivel 2).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ...core.constraints.declared import DATASET_NAME as DECLARED_NAME
from ...core.constraints.declared import DECLARED_ROLE, DeclaredConstraint
from ...core.constraints.model import Constraint, ConstraintParam, GeometryKind, is_code
from ...core.constraints.params import param_key
from ...core.constraints.store import CONSTRAINT_LAYERS, SEARCH_TABLE, SECTOR_TABLE
from ...core.content.builtin import GPKG_LAYER
from ...core.content.encoder import ContentDigest
from ...core.datasets.model import DatasetSpec, Store
from ...core.provenance.contract import (
    FigureDef,
    OperationDef,
    RecomputeFunction,
    ReproduceFunction,
    Tolerance,
)
from ...core.provenance.operations import Use
from ...core.versions.model import version_locator
from ..content import GEOTIFF
from ..grid import Grid

__all__ = [
    "CLASSES",
    "COMMAND",
    "COMPILE",
    "CONSTRAINT_ROLES",
    "DECLARED_NAME",
    "DECLARED_ROLE",
    "FAMILIES",
    "FAMILIES_BY_CODE",
    "FIGURES",
    "FIGURE_TOLERANCE",
    "MODULE",
    "OP_VERSION",
    "PARTS",
    "REPORT",
    "SEARCHES_ROLE",
    "SECTORS_ROLE",
    "SHAPES",
    "ZONES",
    "DatasetFamily",
    "compile_inputs",
    "compile_params",
    "compile_settings",
    "dataset_locator",
    "dataset_name",
    "dataset_spec",
    "declared_resolved",
    "grid_of",
    "operation_def",
]

MODULE = "gis"
OP_VERSION = "1.1"
"""La versión del algoritmo de la compilación (``M.m``; sube cuando un cambio puede mover una
cifra, RF-008-24). **1.1** (T44, hallazgo F-1 de la 012): con varios límites legales, la zona de
cada uno son las celdas enteras dentro de su polígono y la banda hacia dentro (``<código>:inner``),
la de cada uno y no la de la unión repetida; con un solo límite, nada cambia. Una compilación de
la 1.0 con varios límites legales queda obsoleta (causa «algoritmo») y se recalcula."""
COMPILE = "gis.compile_constraints"
COMMAND = "geoblender.gis_compile_constraints"
FIGURE_TOLERANCE = Tolerance(relative=1e-9)
"""La tolerancia de las cifras al reproducir (D-37)."""

CLASSES = "msk"
ZONES = "mskz"
REPORT = "mskr"
PARTS = "mskp"
SHAPES = "mskg"

CONSTRAINT_ROLES: Mapping[GeometryKind, str] = MappingProxyType({
    GeometryKind.POLYGON: "constraints_polygon", GeometryKind.LINE: "constraints_line",
    GeometryKind.POINT: "constraints_point"})
"""El papel de entrada de cada capa de restricciones."""
SECTORS_ROLE = "sectors"
SEARCHES_ROLE = "searches"


@dataclass(frozen=True, slots=True)
class DatasetFamily:
    """Una familia de datos de las máscaras: código, tipo, almacén, lector, papel de salida,
    extensión (``""`` en una tabla) y su nombre en ``gpkg_contents``."""

    code: str
    kind: str
    store: Store
    reader: str
    role: str
    extension: str
    label: str


FAMILIES: tuple[DatasetFamily, ...] = (
    DatasetFamily(CLASSES, "raster", Store.RASTERS, GEOTIFF.id, "classes", ".tif",
                  "Rejilla de clases de las restricciones"),
    DatasetFamily(ZONES, "table", Store.GPKG, GPKG_LAYER.id, "zones", "",
                  "Zonas de las restricciones"),
    DatasetFamily(REPORT, "table", Store.GPKG, GPKG_LAYER.id, "report", "",
                  "Informe de las restricciones"),
    DatasetFamily(PARTS, "vector", Store.GPKG, GPKG_LAYER.id, "parts", "",
                  "Partes de la franja de solo relleno"),
    DatasetFamily(SHAPES, "vector", Store.GPKG, GPKG_LAYER.id, "shapes", "",
                  "Restricciones compiladas (polígonos)"),
)
FAMILIES_BY_CODE: Mapping[str, DatasetFamily] = MappingProxyType(
    {family.code: family for family in FAMILIES})


def _family(code: object) -> DatasetFamily:
    found = FAMILIES_BY_CODE.get(code) if isinstance(code, str) else None
    if found is None:
        raise ValueError(f"{code!r} no es una familia de las máscaras: es una de "
                         f"{', '.join(FAMILIES_BY_CODE)}")
    return found


def dataset_name(family: str) -> str:
    """El nombre del dato de la familia ``family`` (uno por versión): ``gis_<familia>``."""
    return f"{MODULE}_{_family(family).code}"


def dataset_locator(family: str, version_code: str) -> str:
    """La ubicación del dato en la versión ``version_code``: ``gis_mskz_v01`` o
    ``rasters/gis_msk_v01.tif``."""
    found = _family(family)
    base = dataset_name(family)
    if found.store is Store.GPKG:
        return version_locator(base, version_code)
    return version_locator(f"{found.store}/{base}{found.extension}", version_code)


def dataset_spec(family: str, version_code: str, *, content: ContentDigest | None = None,
                 crs_epsg: int | None = None) -> DatasetSpec:
    """La ``DatasetSpec`` del dato de la familia ``family`` en la versión ``version_code``."""
    found = _family(family)
    return DatasetSpec(dataset_name(family), MODULE, found.kind, found.store,
                       dataset_locator(family, version_code), reader=found.reader,
                       role=found.role, content=content, crs_epsg=crs_epsg)


def operation_def(recompute: RecomputeFunction | None = None,
                  reproduce: ReproduceFunction | None = None) -> OperationDef:
    """El ``OperationDef`` de :data:`COMPILE` con las funciones de ``bl``."""
    return OperationDef(COMPILE, OP_VERSION, MODULE, "Compilation of the constraints", True,
                        scope="version", commands=(COMMAND,), recompute=recompute,
                        reproduce=reproduce,
                        figure_tolerance=FIGURE_TOLERANCE if reproduce is not None else None)


FIGURES: tuple[FigureDef, ...] = (
    FigureDef("gis.legal_area_m2", "m2", "Area of the legal limit"),
    FigureDef("gis.perimeter_area_m2", "m2", "Area of the action perimeter"),
    FigureDef("gis.limits_intersection_m2", "m2", "Area of the perimeter within the legal limit"),
    FigureDef("gis.fill_strip_area_m2", "m2", "Area of the fill-only strip"),
    FigureDef("gis.default_domain_m2", "m2", "Area of the default domain"),
    FigureDef("gis.cut_allowed_m2", "m2", "Area where cutting is allowed"),
    FigureDef("gis.fill_allowed_m2", "m2", "Area where filling is allowed"),
    FigureDef("gis.no_movement_m2", "m2", "Area without possible movement"),
    FigureDef("gis.zone_area_m2", "m2", "Area of the zone of the constraint"),
    FigureDef("gis.zone_outside_grid_m2", "m2", "Area of the zone outside the grid"),
)
"""Las cifras de la compilación (plan §5.2.3)."""


def compile_inputs(available: Collection[str]) -> tuple[Use, ...]:
    """Lo que consume la compilación: cada capa de restricciones, la tabla de las declaradas por las
    entidades de la versión (:data:`DECLARED_NAME`, papel :data:`DECLARED_ROLE`; RF-012-16,
    RF-012-29), los sectores y las búsquedas que estén en ``available`` (los nombres de los datos
    registrados del proyecto y, de la versión que se compila, el de sus declaradas vivas:
    ``gis.masks.store.available_tables``). Sin declaradas vivas, son exactamente las de la 012."""
    found = [Use(table, CONSTRAINT_ROLES[kind]) for kind, table in CONSTRAINT_LAYERS.items()
             if table in available]
    found += [Use(DECLARED_NAME, DECLARED_ROLE)] if DECLARED_NAME in available else []
    found += [Use(table, role) for table, role in ((SECTOR_TABLE, SECTORS_ROLE),
                                                   (SEARCH_TABLE, SEARCHES_ROLE))
              if table in available]
    return tuple(found)


def compile_params(constraints: Iterable[Constraint], resolved: Mapping[str, object]
                   ) -> tuple[str, ...]:
    """Las claves que lee la compilación (RF-012-16): de cada restricción **del proyecto** con
    código, su «activa» y, si está activa, lo que pide su tipo; solo las que tienen valor en
    ``resolved`` (una que falta la lista ``checks`` como incompleta). Las **declaradas** por una
    entidad quedan fuera: sus resguardos y su «activa» son columnas de su tabla, no parámetros del
    almacén (``begin_operation`` solo resuelve claves del almacén: de otro modo, crearía filas o
    fallaría; P-8 de la 015)."""
    keys: list[str] = []
    for item in constraints:
        if not is_code(item.code) or item.declared:
            continue
        active = param_key(item.code, ConstraintParam.ACTIVE)
        wanted = [active]
        value = resolved.get(active)
        value = getattr(value, "value", value)
        if value is True and item.ctype is not None:
            wanted += [param_key(item.code, param) for param in item.ctype.requires
                       if param is not ConstraintParam.ACTIVE]
        keys += [key for key in wanted if resolved.get(key) is not None and key not in keys]
    return tuple(keys)


def declared_resolved(rows: Iterable[DeclaredConstraint]) -> dict[str, object]:
    """Los valores de las **columnas** de las restricciones declaradas ``rows`` bajo las claves de los
    parámetros de una restricción (``core.constraint.<código>.buffer_out_m`` y ``.active``; T18, P-8
    de la 015): lo que la compilación suma al ``resolved`` del almacén para tratarlas como a las
    demás. Valores sueltos (``float`` y ``bool``), sin ``ResolvedParam``: ninguna es un parámetro, no
    hay fila ni historial; los da la entidad. El peso y el resguardo hacia dentro no se usan en
    ``no_fill`` (ni en ningún tipo que declare una entidad): no se inyectan."""
    found: dict[str, object] = {}
    for item in rows:
        found[param_key(item.code, ConstraintParam.BUFFER_OUT)] = float(item.buffer_out_m)
        found[param_key(item.code, ConstraintParam.ACTIVE)] = bool(item.active)
    return found


def compile_settings(grid: Grid, *, previous: Mapping[str, Any] | None,
                     pending_sectors: Sequence[str]) -> dict[str, Any]:
    """Los ajustes de la compilación: la rejilla, lo de la compilación anterior (A5) y los
    sectores sin búsqueda vigente (``""``: el perímetro como único sector)."""
    return {"grid": {"west": grid.west, "north": grid.north, "dx": grid.dx, "dy": grid.dy,
                     "ncols": grid.ncols, "nrows": grid.nrows},
            "previous": None if previous is None else dict(previous),
            "pending_sectors": list(pending_sectors)}


def grid_of(settings: Mapping[str, Any]) -> Grid:
    """La rejilla de los ajustes de una compilación."""
    found = settings.get("grid")
    if not isinstance(found, Mapping):
        raise ValueError("los ajustes de la compilación llevan su rejilla")
    return Grid(float(found["west"]), float(found["north"]), float(found["dx"]),
                float(found["dy"]), int(found["ncols"]), int(found["nrows"]))
