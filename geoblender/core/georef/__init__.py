# SPDX-License-Identifier: GPL-3.0-or-later
"""Georreferencia del proyecto (spec 002; ADR-0005): catálogo de CRS horizontales y
verticales, GeoOrigin y ventana de trabajo, y la única conversión absoluta ↔ local.

Python puro (biblioteca estándar y numpy). Las transformaciones entre CRS no están aquí:
necesitan pyproj y llegan con la spec 006 (``gis``).
"""

from .crs import (
    DEFAULT_HORIZONTAL_EPSG,
    DEFAULT_VERTICAL_EPSG,
    CrsCatalog,
    CrsRef,
    VerticalRef,
    load_catalog,
)
from .origin import (
    DEFAULT_GRID_STEP_M,
    GeoOrigin,
    Window,
    align_window,
    alignment_unit,
    check_grid_step,
    choose_origin,
)
from .transform import (
    PRECISION_LIMIT_M,
    PrecisionReport,
    local_to_world,
    precision_report,
    world_to_local,
)

__all__ = [
    "DEFAULT_GRID_STEP_M",
    "DEFAULT_HORIZONTAL_EPSG",
    "DEFAULT_VERTICAL_EPSG",
    "CrsCatalog",
    "CrsRef",
    "GeoOrigin",
    "PRECISION_LIMIT_M",
    "PrecisionReport",
    "VerticalRef",
    "Window",
    "align_window",
    "alignment_unit",
    "check_grid_step",
    "choose_origin",
    "load_catalog",
    "local_to_world",
    "precision_report",
    "world_to_local",
]
