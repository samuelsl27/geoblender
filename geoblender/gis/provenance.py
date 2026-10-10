# SPDX-License-Identifier: GPL-3.0-or-later
"""Declaraciones de procedencia de la topografía (spec 006, T41; RF-006-26; RF-008-17,
RF-008-25, RF-008-26, RF-008-27; ADR-0025 §2; plan 006 §5.6.3, D8 y D22).

Lo que la 006 registra en la procedencia de la 008, declarado con tipos de ``core``. Importar
este módulo no registra nada: lo registra ``bl/ops/gis.py`` en su ``register()`` (y lo quita en
``unregister()``), con las funciones de recálculo y de reimportación, que son de ``bl`` porque
lanzan trabajos.

**Tipos de operación** (:data:`OPERATION_TYPES`, :class:`OperationType`; versión
:data:`OP_VERSION`): ``gis.import_dtm``, ``gis.import_points`` y ``gis.import_vector`` (no se
repiten solas: se reimportan, y quedan «revisar a mano», RF-008-27); ``gis.resample``,
``gis.tin_from_points``, ``gis.tin_from_contours``, ``gis.grid_to_tin``, ``gis.tin_to_grid`` y
``gis.contours`` (se repiten solas con su función de recálculo, RF-008-26); y
``gis.export_raster`` y ``gis.export_gpkg`` (no se repiten). Ninguna está acoplada a otra
(RF-008-25): la cadena de trabajos de un TIN (preparar, triangular, terminar) es una sola
operación. Cada tipo dice las órdenes que lo lanzan (los ``bl_idname`` del catálogo de la 003),
los papeles de lo que consume, las familias de datos que produce, las bibliotecas que influyen
en sus resultados (``pyproj``, la versión fijada en ``tools/wheels.toml``; ``triangulator``,
el triangulador usado, RF-006-26) y, una importación, sus lectores de contenido
(``gis.content``). :func:`operation_def` y :func:`operation_defs` construyen los
``OperationDef``; :func:`importer_def`, el ``ImporterDef`` de un lector de importación
(RF-008-11). Ninguna operación de la 006 registra cifras: no hay ``FigureDef`` (sus informes
son diagnósticos, spec §11).

**Datos** (:data:`FAMILIES`, :class:`DatasetFamily`): el nombre estable de un dato es
``gis_<familia>_<nombre>`` (:func:`dataset_name`), con el nombre de la orden en ASCII en
minúsculas con «_» (:func:`dataset_slug`); su :class:`~..core.datasets.DatasetSpec`
(:func:`dataset_spec`) dice su tipo, su almacén, su ubicación, su lector y su papel de salida.

- ``src`` (rejilla de origen de un MDT importado) y ``dtm`` (rejilla del proyecto): ``raster``
  en ``rasters/``, leídas con ``gis.geotiff@1``; ``tin``: ``mesh`` en ``meshes/``, con
  ``core.npz_mesh@1``; ``pts``, ``brk``, ``cnt`` y ``bnd`` (puntos, líneas de rotura, curvas
  de nivel y contornos): ``vector`` en ``project.gpkg``, una tabla por dato (D8), con
  ``core.gpkg_layer@1`` (el registro de la 008 lee las tablas del proyecto con ese lector).
- **Lo importado** (``src``, ``pts``, ``brk``, ``bnd`` y las curvas de una capa importada,
  RF-008-52) es inmutable, con su entrada y sin selector, y su ubicación lleva el uid corto de
  la entrada (:func:`input_tag`, D22: ``rasters/gis_src_<nombre>_<entrada8>.tif``,
  ``gis_pts_<nombre>_<entrada8>``), porque la 008 no reutiliza nunca una ubicación y lo
  importado de una entrada sustituida se conserva. **Lo calculado** (``dtm``, ``tin`` y las
  curvas de una superficie) no tiene entrada: ``rasters/gis_dtm_<nombre>.tif``,
  ``meshes/gis_tin_<nombre>.npz``, ``gis_cnt_<nombre>``.
- Ninguno es editable a mano en QGIS (RF-008-56). Cada familia tiene su papel de salida
  (``gb_operation_io.role``), distinto en cada una: por él se busca el sucesor de lo
  sustituido. El papel de una capa importada decide su familia (:data:`LAYER_ROLES`).

Las exportaciones (``gis.export_*``) escriben fuera de los datos del proyecto o en
``exports/``, sin seguimiento: su dato lo declara la exportación (plan §5.6.6; T31). Dentro de
``exports/`` el entregable es el dato ``gis_exp_<ruta>`` del almacén ``exports``
(:func:`export_spec`, con su ubicación de :func:`export_locator`): una rejilla
(``gis.geotiff@1``) o un documento (el GeoPackage, ``core.document@1``); fuera, ninguno (D21).
Una ruta del proyecto fuera de ``exports/`` no es un destino (:func:`inside_project`). Python
puro (ADR-0004).
"""

from __future__ import annotations

import ntpath
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any

from ..core.content.builtin import DOCUMENT
from ..core.content.builtin import GPKG_LAYER as CORE_GPKG_LAYER
from ..core.content.builtin import NPZ_MESH
from ..core.content.encoder import ContentDigest
from ..core.datasets.model import DatasetSpec, Store
from ..core.provenance.contract import (
    ImporterDef,
    OperationDef,
    RecomputeFunction,
    ReimportFunction,
)
from .content import ASC, GEOTIFF, GPKG_LAYER, POINTS_TEXT, XYZ_GRID
from .messages import GisError

MODULE = "gis"
"""El código de la topografía (``core.catalog.schema.MODULE_CODES``)."""
OP_VERSION = "1.0"
"""La versión inicial del algoritmo de cada tipo (sube cuando un cambio puede mover un
resultado, RF-008-24)."""
MAX_SLUG_CHARS = 40
"""Largo máximo del nombre de la orden en el de un dato (las rutas cuentan con el límite de
Windows, ``docs/trampas.md``)."""

# --- Tipos de operación ------------------------------------------------------------------------

IMPORT_DTM = "gis.import_dtm"
IMPORT_POINTS = "gis.import_points"
IMPORT_VECTOR = "gis.import_vector"
RESAMPLE = "gis.resample"
TIN_FROM_POINTS = "gis.tin_from_points"
TIN_FROM_CONTOURS = "gis.tin_from_contours"
GRID_TO_TIN = "gis.grid_to_tin"
TIN_TO_GRID = "gis.tin_to_grid"
CONTOURS = "gis.contours"
EXPORT_RASTER = "gis.export_raster"
EXPORT_GPKG = "gis.export_gpkg"

PYPROJ = "pyproj"
"""La biblioteca de las transformaciones de CRS (su versión, la fijada en
``tools/wheels.toml``)."""
TRIANGULATOR = "triangulator"
"""El triangulador usado en un TIN (``blender-cdt@5.2.1`` o ``pure@<versión>``, RF-006-26)."""

# --- Familias de datos ---------------------------------------------------------------------

SOURCE_GRID = "src"
PROJECT_GRID = "dtm"
TIN = "tin"
POINTS = "pts"
BREAKLINES = "brk"
CONTOUR_LINES = "cnt"
BOUNDARY = "bnd"

_GIS_PREFIX = f"{MODULE}_"
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_HEX = re.compile(r"[0-9a-f]+")
_TAG_CHARS = 8
_OBJ = "Dato de topografía"
_FIELD = "nombre"


@dataclass(frozen=True, slots=True)
class OperationType:
    """Un tipo de operación de la 006 sin su función de recálculo (plan §5.6.3):
    ``op_type``, su nombre visible (``label_msgid``, con su español en
    ``core/i18n/messages.toml``), si se repite solo, las órdenes que lo lanzan
    (``commands``), los papeles de lo que consume (``inputs``, los de ``Use``), las familias
    de datos que produce (``outputs``; una capa importada, una de ellas según su papel), las
    bibliotecas que influyen en sus resultados (``libraries``) y, una importación, los
    lectores de su entrada (``readers``, con versión)."""

    op_type: str
    label_msgid: str
    repeatable: bool
    commands: tuple[str, ...]
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    libraries: tuple[str, ...] = ()
    readers: tuple[str, ...] = ()

    def definition(self, recompute: RecomputeFunction | None = None) -> OperationDef:
        """Su ``OperationDef`` (versión :data:`OP_VERSION`, del proyecto, sin grupo) con la
        función de recálculo ``recompute``: la de ``bl`` si se repite solo y ``None`` si no
        (si no, ``ValueError`` de ``OperationDef``)."""
        return OperationDef(
            self.op_type,
            OP_VERSION,
            MODULE,
            self.label_msgid,
            self.repeatable,
            commands=self.commands,
            libraries=self.libraries,
            recompute=recompute,
        )


OPERATION_TYPES: tuple[OperationType, ...] = (
    OperationType(IMPORT_DTM, "Import of a raster DTM", False,
                  ("geoblender.gis_import_dtm",), outputs=(SOURCE_GRID,),
                  readers=(GEOTIFF.id, ASC.id, XYZ_GRID.id)),
    OperationType(IMPORT_POINTS, "Import of points and breaklines", False,
                  ("geoblender.gis_import_points",), outputs=(POINTS, BREAKLINES),
                  readers=(POINTS_TEXT.id,)),
    OperationType(IMPORT_VECTOR, "Import of a vector layer", False,
                  ("geoblender.gis_import_vector",),
                  outputs=(POINTS, BREAKLINES, CONTOUR_LINES, BOUNDARY),
                  readers=(GPKG_LAYER.id,)),
    OperationType(RESAMPLE, "Resampling to the project grid", True,
                  ("geoblender.gis_resample_to_grid",), inputs=("source",),
                  outputs=(PROJECT_GRID,), libraries=(PYPROJ,)),
    OperationType(TIN_FROM_POINTS, "TIN from points and breaklines", True,
                  ("geoblender.gis_create_tin_from_points",),
                  inputs=("points", "breaklines", "boundary"), outputs=(TIN,),
                  libraries=(TRIANGULATOR,)),
    OperationType(TIN_FROM_CONTOURS, "TIN from contour lines", True,
                  ("geoblender.gis_create_tin_from_contours",),
                  inputs=("contours", "spot_heights", "boundary"), outputs=(TIN,),
                  libraries=(TRIANGULATOR,)),
    OperationType(GRID_TO_TIN, "DTM to TIN conversion", True,
                  ("geoblender.gis_convert_dtm_tin",), inputs=("source",), outputs=(TIN,)),
    OperationType(TIN_TO_GRID, "TIN to DTM conversion", True,
                  ("geoblender.gis_convert_dtm_tin",), inputs=("source",),
                  outputs=(PROJECT_GRID,)),
    OperationType(CONTOURS, "Contour lines of a surface", True,
                  ("geoblender.gis_create_contours",), inputs=("source",),
                  outputs=(CONTOUR_LINES,)),
    OperationType(EXPORT_RASTER, "Export of a raster DTM", False,
                  ("geoblender.gis_export_raster",), inputs=("exported",)),
    OperationType(EXPORT_GPKG, "Export to GeoPackage", False,
                  ("geoblender.gis_export_gpkg",), inputs=("exported",)),
)
"""Los tipos de operación de la 006, en el orden del plan §5.6.3."""
OPERATION_TYPES_BY_NAME: Mapping[str, OperationType] = MappingProxyType(
    {declared.op_type: declared for declared in OPERATION_TYPES})
"""Los tipos de operación por nombre (solo lectura)."""
IMPORTS: tuple[str, ...] = tuple(t.op_type for t in OPERATION_TYPES if t.readers)
"""Las importaciones (registran su entrada; se reimportan)."""
EXPORTS: tuple[str, ...] = (EXPORT_RASTER, EXPORT_GPKG)
"""Las exportaciones."""
REPEATABLE: tuple[str, ...] = tuple(t.op_type for t in OPERATION_TYPES if t.repeatable)
"""Los tipos que se repiten solos con su función de recálculo (RF-008-26)."""
_IMPORT_READERS = {GEOTIFF.id: GEOTIFF, ASC.id: ASC, XYZ_GRID.id: XYZ_GRID,
                   POINTS_TEXT.id: POINTS_TEXT, GPKG_LAYER.id: GPKG_LAYER}
IMPORT_READERS: tuple[str, ...] = tuple(
    _IMPORT_READERS[reader_id].reader_id for name in IMPORTS
    for reader_id in OPERATION_TYPES_BY_NAME[name].readers)
"""Los lectores de las importaciones, sin versión: un ``ImporterDef`` por cada uno (plan
§5.6.8)."""


def _operation_type(op_type: object) -> OperationType:
    found = OPERATION_TYPES_BY_NAME.get(op_type) if isinstance(op_type, str) else None
    if found is None:
        raise ValueError(f"{op_type!r} no es un tipo de operación de la topografía: es uno de "
                         f"{', '.join(OPERATION_TYPES_BY_NAME)}")
    return found


def operation_def(op_type: str, recompute: RecomputeFunction | None = None) -> OperationDef:
    """El ``OperationDef`` del tipo ``op_type`` con la función de recálculo ``recompute``
    que le da ``bl`` (la de un tipo que se repite solo; ``None`` en una importación o una
    exportación). ``ValueError`` si el tipo no es de la 006, si se repite solo y no recibe su
    función, o si no se repite y la recibe; ``TypeError`` si ``recompute`` no es una
    función."""
    return _operation_type(op_type).definition(recompute)


def operation_defs(
    recompute: Mapping[str, RecomputeFunction],
    *,
    op_types: Iterable[str] | None = None,
) -> tuple[OperationDef, ...]:
    """Los ``OperationDef`` de ``op_types`` (todos, por defecto, en el orden de
    :data:`OPERATION_TYPES`), cada uno con su función de ``recompute`` (por tipo: la de cada
    uno que se repite solo, y ninguna más). ``ValueError`` si un tipo no es de la 006 o se
    repite en ``op_types``, si falta la función de uno que se repite solo, o si ``recompute``
    trae una para un tipo que no se construye o que no se repite."""
    chosen = OPERATION_TYPES if op_types is None else tuple(_operation_type(name)
                                                            for name in op_types)
    names = [declared.op_type for declared in chosen]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValueError(f"tipos de operación repetidos: {', '.join(repeated)}")
    extra = sorted(set(recompute) - set(names))
    if extra:
        raise ValueError(f"funciones de recálculo de tipos que no se construyen: "
                         f"{', '.join(map(str, extra))}")
    return tuple(declared.definition(recompute.get(declared.op_type)) for declared in chosen)


def importer_def(reader_id: str, reimport: ReimportFunction) -> ImporterDef:
    """El ``ImporterDef`` del lector de importación ``reader_id`` (sin versión, de
    :data:`IMPORT_READERS`) con la función de reimportación ``reimport`` que le da ``bl``
    (RF-008-11). ``ValueError`` si el lector no es de una importación de la 006;
    ``TypeError`` si ``reimport`` no es una función."""
    if reader_id not in IMPORT_READERS:
        raise ValueError(f"{reader_id!r} no es el lector de una importación de la topografía "
                         f"(sin versión): es uno de {', '.join(IMPORT_READERS)}")
    return ImporterDef(reader_id, reimport)


def input_kind(reader_id: str) -> str:
    """El tipo de la entrada que lee el lector de importación ``reader_id`` (con versión):
    ``raster`` las rejillas, ``table`` el texto de puntos y ``vector`` una capa. ``ValueError``
    si no es el de una importación de la 006."""
    found = _IMPORT_READERS.get(reader_id) if isinstance(reader_id, str) else None
    if found is None:
        raise ValueError(f"{reader_id!r} no es el lector de una importación de la topografía "
                         f"(con versión): es uno de {', '.join(_IMPORT_READERS)}")
    return found.kinds[0]


# --- Datos ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DatasetFamily:
    """Una familia de datos de la 006: su código (``src``), su tipo y su almacén, su lector
    (con versión), su papel de salida en la operación que la escribe, si es lo importado de
    una entrada, lo calculado o las dos cosas, y la extensión de su fichero (``""`` en una
    tabla del GeoPackage)."""

    code: str
    kind: str
    store: Store
    reader: str
    role: str
    imported: bool
    computed: bool
    extension: str

    @property
    def prefix(self) -> str:
        """El comienzo del nombre de sus datos: ``gis_<código>_``."""
        return f"{_GIS_PREFIX}{self.code}_"


FAMILIES: tuple[DatasetFamily, ...] = (
    DatasetFamily(SOURCE_GRID, "raster", Store.RASTERS, GEOTIFF.id, "source_grid", True, False,
                  ".tif"),
    DatasetFamily(PROJECT_GRID, "raster", Store.RASTERS, GEOTIFF.id, "project_grid", False,
                  True, ".tif"),
    DatasetFamily(TIN, "mesh", Store.MESHES, NPZ_MESH.id, "tin", False, True, ".npz"),
    DatasetFamily(POINTS, "vector", Store.GPKG, CORE_GPKG_LAYER.id, "points", True, False, ""),
    DatasetFamily(BREAKLINES, "vector", Store.GPKG, CORE_GPKG_LAYER.id, "breaklines", True,
                  False, ""),
    DatasetFamily(CONTOUR_LINES, "vector", Store.GPKG, CORE_GPKG_LAYER.id, "contours", True,
                  True, ""),
    DatasetFamily(BOUNDARY, "vector", Store.GPKG, CORE_GPKG_LAYER.id, "boundary", True, False,
                  ""),
)
"""Las familias de datos de la 006 (plan §5.2.4 y §5.6.3)."""
FAMILIES_BY_CODE: Mapping[str, DatasetFamily] = MappingProxyType(
    {family.code: family for family in FAMILIES})
"""Las familias por código (solo lectura)."""
LAYER_ROLES: Mapping[str, str] = MappingProxyType({
    "points": POINTS,
    "breaklines": BREAKLINES,
    "contours": CONTOUR_LINES,
    "boundary": BOUNDARY,
})
"""El papel de una capa importada (ajuste ``role``) → la familia de su dato."""


def _family(code: object) -> DatasetFamily:
    found = FAMILIES_BY_CODE.get(code) if isinstance(code, str) else None
    if found is None:
        raise ValueError(f"{code!r} no es una familia de datos de la topografía: es una de "
                         f"{', '.join(FAMILIES_BY_CODE)}")
    return found


def layer_family(role: str) -> str:
    """La familia del dato de una capa importada con el papel ``role`` (:data:`LAYER_ROLES`);
    ``ValueError`` si el papel no es uno de ellos."""
    found = LAYER_ROLES.get(role) if isinstance(role, str) else None
    if found is None:
        raise ValueError(f"{role!r} no es el papel de una capa importada: es uno de "
                         f"{', '.join(LAYER_ROLES)}")
    return found


def dataset_slug(name: str) -> str:
    """El nombre de la orden ``name`` en el de sus datos: en minúsculas, sin tildes («ñ» →
    «n») y con un «_» por cada tramo que no es una letra o una cifra ASCII, sin «_» a los
    lados y con :data:`MAX_SLUG_CHARS` caracteres como mucho (un nombre ya en esa forma no
    cambia). :class:`~.messages.GisError` ``gis.dataset_name_invalid`` si no queda ninguna
    letra ni cifra; ``TypeError`` si no es un texto."""
    if not isinstance(name, str):
        raise TypeError(f"el nombre de un dato es un texto, no {name!r}")
    plain = "".join(char for char in unicodedata.normalize("NFKD", name)
                    if not unicodedata.combining(char)).lower()
    slug = _NON_SLUG.sub("_", plain).strip("_")[:MAX_SLUG_CHARS].rstrip("_")
    if not slug:
        raise GisError("gis.dataset_name_invalid", obj=_OBJ, field=_FIELD, value=name)
    return slug


def dataset_name(family: str, name: str) -> str:
    """El nombre estable del dato de la familia ``family`` que crea la orden llamada
    ``name``: ``gis_<familia>_<nombre>`` (:func:`dataset_slug`), el mismo para lo importado y
    para lo calculado. ``ValueError`` si la familia no es de la 006."""
    return _family(family).prefix + dataset_slug(name)


def input_tag(input_uid: str) -> str:
    """El uid corto de una entrada (D22): las :data:`_TAG_CHARS` primeras cifras
    hexadecimales de su uid (un UUID en texto), en minúsculas. ``ValueError`` si no es un
    uid así."""
    if not isinstance(input_uid, str):
        raise TypeError(f"el uid de una entrada es un texto, no {input_uid!r}")
    head = input_uid.lower().partition("-")[0]
    if len(head) != _TAG_CHARS or _HEX.fullmatch(head) is None or "-" not in input_uid:
        raise ValueError(f"{input_uid!r} no es el uid de una entrada (un UUID en texto, como "
                         "«3f2b9c1d-8e7a-4b6c-9d0e-1a2b3c4d5e6f»)")
    return head


def _origin(family: DatasetFamily, input_uid: str | None) -> None:
    imported = input_uid is not None
    if imported and not family.imported:
        raise ValueError(f"«{family.prefix}…» es lo calculado por una operación: no es lo "
                         "importado de una entrada (sin input_uid)")
    if not imported and not family.computed:
        raise ValueError(f"«{family.prefix}…» es lo importado de una entrada: falta su "
                         "input_uid (RF-008-52)")


def dataset_locator(family: str, name: str, *, input_uid: str | None = None) -> str:
    """La ubicación del dato de la familia ``family`` de la orden ``name``: la tabla del
    GeoPackage o la ruta relativa en su almacén (``rasters/…``, ``meshes/…``). Lo importado de
    la entrada ``input_uid`` lleva su uid corto (D22: ``gis_pts_<nombre>_<entrada8>``); lo
    calculado (sin ``input_uid``), no. ``ValueError`` si la familia no es de la 006 o no admite
    ese origen."""
    found = _family(family)
    _origin(found, input_uid)
    base = dataset_name(family, name)
    if input_uid is not None:
        base = f"{base}_{input_tag(input_uid)}"
    if found.store is Store.GPKG:
        return base
    return f"{found.store}/{base}{found.extension}"


def dataset_spec(
    family: str,
    name: str,
    *,
    input_uid: str | None = None,
    content: ContentDigest | None = None,
    crs_epsg: int | None = None,
    detail: Any = None,
) -> DatasetSpec:
    """La ``DatasetSpec`` del dato de la familia ``family`` de la orden ``name``
    (RF-008-17): su nombre (:func:`dataset_name`), su tipo, su almacén, su ubicación
    (:func:`dataset_locator`), su lector y su papel de salida; sin selector (una tabla por
    dato, D8) y no editable a mano en QGIS. Con ``input_uid`` es lo importado de esa entrada,
    inmutable (RF-008-52). ``content`` (el hash que dio el trabajo con el lector del dato),
    ``crs_epsg`` y ``detail`` pasan tal cual; lo que no admite ``DatasetSpec`` es su
    ``ValueError`` o ``TypeError``."""
    found = _family(family)
    return DatasetSpec(
        dataset_name(family, name),
        MODULE,
        found.kind,
        found.store,
        dataset_locator(family, name, input_uid=input_uid),
        reader=found.reader,
        role=found.role,
        content=content,
        crs_epsg=crs_epsg,
        input_uid=input_uid,
        immutable=input_uid is not None,
        detail=detail,
    )


# --- Entregables (T31; plan §5.6.6, D21) ----------------------------------------------------------

EXPORTS_FOLDER = str(Store.EXPORTS)
"""La carpeta de los entregables dentro del proyecto (``exports/``)."""
EXPORT_PREFIX = f"{_GIS_PREFIX}exp_"
"""El comienzo del nombre del dato de un entregable de ``exports/``: ``gis_exp_<ruta>``."""
EXPORT_ROLE = "export"
"""Su papel de salida en la operación que lo escribe."""
_EXPORT_KINDS: Mapping[str, str] = MappingProxyType({GEOTIFF.id: "raster",
                                                     DOCUMENT.id: "document"})


def _comparable(path: str | os.PathLike[str]) -> str:
    """Una ruta absoluta como la compara Windows: sin «.» ni «..», con «\\» y sin mayúsculas."""
    return ntpath.normcase(ntpath.normpath(os.path.abspath(os.fspath(path))))


def inside_project(root: str | os.PathLike[str], target: str | os.PathLike[str]) -> bool:
    """Si ``target`` es la raíz del proyecto ``root`` o está dentro (sin distinguir
    mayúsculas, como Windows)."""
    base, found = _comparable(root), _comparable(target)
    return found == base or found.startswith(base.rstrip("\\") + "\\")


def export_locator(root: str | os.PathLike[str], target: str | os.PathLike[str]) -> str | None:
    """La ubicación (``exports/<ruta con «/»>``) del entregable ``target`` si está dentro de
    ``exports/`` del proyecto ``root``; si no, ``None`` (fuera del proyecto: ningún dato, D21;
    en otra carpeta del proyecto, no es un destino: :func:`inside_project`)."""
    folder = Path(root) / EXPORTS_FOLDER
    if not inside_project(folder, target) or _comparable(folder) == _comparable(target):
        return None
    relative = os.path.relpath(os.path.abspath(os.fspath(target)),
                               os.path.abspath(os.fspath(folder)))
    return "/".join((EXPORTS_FOLDER, *PureWindowsPath(relative).parts))


def export_spec(locator: str, content: ContentDigest, *, crs_epsg: int | None = None,
                ) -> DatasetSpec:
    """La ``DatasetSpec`` del entregable de ``exports/`` en ``locator`` (:func:`export_locator`)
    con el ``content`` que dio su trabajo (plan §5.6.6): ``gis_exp_<ruta>`` (la ruta dentro de
    ``exports/`` con :func:`dataset_slug`: un entregable con la misma ruta es el mismo dato con
    otro contenido), almacén ``exports`` (sin seguimiento), su lector (``gis.geotiff@1``: una
    rejilla; ``core.document@1``: el GeoPackage, un documento) y el papel ``export``.
    ``ValueError`` si ``content`` no es de uno de esos lectores."""
    if not isinstance(content, ContentDigest):
        raise TypeError(f"el hash de un entregable es un ContentDigest, no {content!r}")
    kind = _EXPORT_KINDS.get(content.reader)
    if kind is None:
        raise ValueError(f"un entregable se lee con {', '.join(_EXPORT_KINDS)}, no con "
                         f"«{content.reader}»")
    relative = locator.removeprefix(f"{EXPORTS_FOLDER}/")
    return DatasetSpec(EXPORT_PREFIX + dataset_slug(relative), MODULE, kind, Store.EXPORTS,
                       locator, reader=content.reader, role=EXPORT_ROLE, content=content,
                       crs_epsg=crs_epsg)
