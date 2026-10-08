# SPDX-License-Identifier: GPL-3.0-or-later
"""Topografía y SIG (código ``gis``, nivel 2): rejillas de paso exacto, ráster, TIN,
curvas, vectorial y máscaras de restricciones.

Dominio puro: solo importa paquetes de nivel menor (ARQ-07); las librerías
externas, a través de puertos implementados en ``adapters`` (ARQ-04).

Reexporta la API pública (plan 006 §5.1): los puertos (``gis.ports``), los parámetros
(``gis.params``), el error y los mensajes (``gis.messages``), los informes
(``gis.reports``), la rejilla de paso exacto y el volumen entre superficies (``gis.grid``),
las superficies en rejilla y los MDT leídos de un fichero (``gis.raster``), el remuestreo y
la reproyección a la rejilla del proyecto (``gis.resample``), la declaración de CRS y
datum con sus transformaciones (``gis.crs``), el aviso de alturas elipsoidales
(``gis.vertical``), la validación de una superficie (``gis.validate``), los puntos, las
líneas de rotura y sus duplicados (``gis.points``), las capas de un GeoPackage leídas sobre
una copia (``gis.vector``), la preparación de las restricciones de un TIN
(``gis.breaklines``), el triangulador propio (``gis.cdt``), el TIN con su fichero, su paso
a rejilla y desde ella y su muestreo (``gis.tin``), el TIN desde curvas de nivel con la
corrección de triángulos planos (``gis.tin_contours``) y las curvas de nivel de una rejilla
o de un TIN (``gis.contours``). Cada tarea de la 006 añade aquí lo suyo.
"""

from .breaklines import PreparedInput, prepare_constraints
from .cdt import PureTriangulator
from .contours import ContourLine, contours_from_raster, contours_from_tin
from .crs import (
    ELLIPSOIDAL_ETRS89,
    CoordinateTransform,
    CrsServiceStatus,
    Declaration,
    crs_service_status,
    needs_transform,
    reference_label,
    require_crs_service,
    transform_coordinates,
    transform_summary,
    transformation_for,
)
from .grid import (
    Grid,
    VolumeResult,
    aligned_grid,
    project_grid,
    validate_step,
    volume_between,
)
from .messages import GisError
from .params import PARAMS, ParamDef, param
from .points import (
    Breakline,
    ColumnMapping,
    DuplicateGroup,
    DuplicatePolicy,
    DuplicateReport,
    PointSet,
    breaklines_from_features,
    find_duplicates,
    points_from_features,
    points_from_rows,
    resolve_duplicates,
)
from .ports import (
    Cancelled,
    CrsService,
    CrsServiceUnavailable,
    Progress,
    RasterIO,
    Transform,
    TransformInfo,
    TriangulationError,
    Triangulator,
    WriteProfile,
)
from .raster import Raster, RasterSource
from .resample import (
    ResampleMethod,
    choose_method,
    reproject_to_grid,
    resample_classes_to_grid,
    resample_to_grid,
)
from .reports import (
    Conflict,
    ConflictError,
    ConflictKind,
    Rejection,
    ResampleReport,
    SurfaceReport,
    TinReport,
    TopoReport,
)
from .tin import Tin, build_tin, load_tin, raster_to_tin, sample_tin, save_tin, tin_to_raster
from .tin_contours import tin_from_contours
from .validate import validate_raster, validate_tin
from .vector import FeatureSet, LayerInfo, copy_source, import_dir, list_layers, read_layer
from .vertical import VerticalCheck, check_vertical_offset, ellipsoidal_band

__all__ = [
    "ELLIPSOIDAL_ETRS89",
    "PARAMS",
    "Breakline",
    "Cancelled",
    "ColumnMapping",
    "Conflict",
    "ConflictError",
    "ConflictKind",
    "ContourLine",
    "CoordinateTransform",
    "CrsService",
    "CrsServiceStatus",
    "CrsServiceUnavailable",
    "Declaration",
    "DuplicateGroup",
    "DuplicatePolicy",
    "DuplicateReport",
    "FeatureSet",
    "GisError",
    "Grid",
    "LayerInfo",
    "ParamDef",
    "PointSet",
    "PreparedInput",
    "Progress",
    "PureTriangulator",
    "Raster",
    "RasterIO",
    "RasterSource",
    "Rejection",
    "ResampleMethod",
    "ResampleReport",
    "SurfaceReport",
    "Tin",
    "TinReport",
    "TopoReport",
    "Transform",
    "TransformInfo",
    "TriangulationError",
    "Triangulator",
    "VerticalCheck",
    "VolumeResult",
    "WriteProfile",
    "aligned_grid",
    "breaklines_from_features",
    "build_tin",
    "check_vertical_offset",
    "choose_method",
    "contours_from_raster",
    "contours_from_tin",
    "copy_source",
    "crs_service_status",
    "ellipsoidal_band",
    "find_duplicates",
    "import_dir",
    "list_layers",
    "load_tin",
    "needs_transform",
    "param",
    "points_from_features",
    "points_from_rows",
    "prepare_constraints",
    "project_grid",
    "raster_to_tin",
    "read_layer",
    "reference_label",
    "reproject_to_grid",
    "require_crs_service",
    "resample_classes_to_grid",
    "resample_to_grid",
    "resolve_duplicates",
    "sample_tin",
    "save_tin",
    "tin_from_contours",
    "tin_to_raster",
    "transform_coordinates",
    "transform_summary",
    "transformation_for",
    "validate_raster",
    "validate_step",
    "validate_tin",
    "volume_between",
]
