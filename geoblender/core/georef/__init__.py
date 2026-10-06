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

__all__ = [
    "DEFAULT_HORIZONTAL_EPSG",
    "DEFAULT_VERTICAL_EPSG",
    "CrsCatalog",
    "CrsRef",
    "VerticalRef",
    "load_catalog",
]
