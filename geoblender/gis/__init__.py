# SPDX-License-Identifier: GPL-3.0-or-later
"""Topografía y SIG (código ``gis``, nivel 2): rejillas de paso exacto, ráster, TIN,
curvas, vectorial y máscaras de restricciones.

Dominio puro: solo importa paquetes de nivel menor (ARQ-07); las librerías
externas, a través de puertos implementados en ``adapters`` (ARQ-04).

Reexporta la API pública (plan 006 §5.1): los puertos (``gis.ports``), los parámetros
(``gis.params``), el error y los mensajes (``gis.messages``), los informes
(``gis.reports``) y la rejilla de paso exacto (``gis.grid``). Cada tarea de la 006 añade
aquí lo suyo.
"""

from .grid import Grid, aligned_grid, project_grid, validate_step
from .messages import GisError
from .params import PARAMS, ParamDef, param
from .ports import (
    Cancelled,
    CrsService,
    Progress,
    RasterIO,
    Transform,
    TransformInfo,
    TriangulationError,
    Triangulator,
    WriteProfile,
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
    "PARAMS",
    "Cancelled",
    "Conflict",
    "ConflictKind",
    "CrsService",
    "GisError",
    "Grid",
    "ParamDef",
    "Progress",
    "RasterIO",
    "Rejection",
    "ResampleReport",
    "SurfaceReport",
    "TinReport",
    "TopoReport",
    "Transform",
    "TransformInfo",
    "TriangulationError",
    "Triangulator",
    "WriteProfile",
    "aligned_grid",
    "param",
    "project_grid",
    "validate_step",
]
