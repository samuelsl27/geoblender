# SPDX-License-Identifier: GPL-3.0-or-later
"""Topografía y SIG (código ``gis``, nivel 2): rejillas de paso exacto, ráster, TIN,
curvas, vectorial y máscaras de restricciones.

Dominio puro: solo importa paquetes de nivel menor (ARQ-07); las librerías
externas, a través de puertos implementados en ``adapters`` (ARQ-04).

Reexporta la API pública (plan 006 §5.1): los puertos (``gis.ports``), los parámetros
(``gis.params``), el error y los mensajes (``gis.messages``), los informes
(``gis.reports``), la rejilla de paso exacto y el volumen entre superficies (``gis.grid``),
las superficies en rejilla y los MDT leídos de un fichero (``gis.raster``), el remuestreo a
la rejilla del proyecto (``gis.resample``) y la declaración de CRS y datum con sus
transformaciones (``gis.crs``). Cada tarea de la 006 añade aquí lo suyo.
"""

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
    resample_classes_to_grid,
    resample_to_grid,
)
from .reports import (
    Conflict,
    ConflictKind,
    Rejection,
    ResampleReport,
    SurfaceReport,
    TinReport,
    TopoReport,
)

__all__ = [
    "ELLIPSOIDAL_ETRS89",
    "PARAMS",
    "Cancelled",
    "Conflict",
    "ConflictKind",
    "CoordinateTransform",
    "CrsService",
    "CrsServiceStatus",
    "CrsServiceUnavailable",
    "Declaration",
    "GisError",
    "Grid",
    "ParamDef",
    "Progress",
    "Raster",
    "RasterIO",
    "RasterSource",
    "Rejection",
    "ResampleMethod",
    "ResampleReport",
    "SurfaceReport",
    "TinReport",
    "TopoReport",
    "Transform",
    "TransformInfo",
    "TriangulationError",
    "Triangulator",
    "VolumeResult",
    "WriteProfile",
    "aligned_grid",
    "choose_method",
    "crs_service_status",
    "needs_transform",
    "param",
    "project_grid",
    "reference_label",
    "require_crs_service",
    "resample_classes_to_grid",
    "resample_to_grid",
    "transform_coordinates",
    "transform_summary",
    "transformation_for",
    "validate_step",
    "volume_between",
]
