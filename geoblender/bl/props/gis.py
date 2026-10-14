# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades del módulo ``gis`` (spec 006, T29 y T31; RF-006-12, RF-006-25; plan 006 §5.1 y
§5.3.5).

:class:`GEOBLENDER_PG_gis_column` es una fila del asistente de «Puntos y líneas de rotura…»
(``geoblender.gis_import_points``): una columna del fichero de texto (su índice desde 0, su
nombre en la cabecera y lo que lleva en las primeras filas) y su papel (P, X, Y, Z, código,
línea o ninguno). Solo texto, enteros y enumerados: ninguna coordenada (ADR-0005). Desde un
guion, ``columns=[{"name": "X", "index": 1, "role": "X"}, …]`` (Blender pide ``name`` en
cada fila).

:class:`GEOBLENDER_PG_gis_export_item` es una fila de «Capas a GeoPackage…»
(``geoblender.gis_export_gpkg``, T31): un dato de la topografía (su nombre, ``name``) y si se
exporta (``selected``). Desde un guion, ``items=[{"name": "gis_pts_taludes", "selected":
True}, …]``.

No se anima (``options=set()``).
"""

from __future__ import annotations

from types import MappingProxyType

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty

NOT_IMPORTED = "NONE"
COLUMN_ROLE_ITEMS = [
    (NOT_IMPORTED, "Not imported", "The column is not imported"),
    ("POINT_ID", "Point (P)", "Identifier of the point"),
    ("X", "X (east)", ""),
    ("Y", "Y (north)", ""),
    ("Z", "Z (elevation)", ""),
    ("CODE", "Code", "Survey code of the point"),
    ("LINE", "Line", "Breakline the point belongs to"),
]
"""Los papeles de una columna en el asistente (``msgid`` en inglés)."""
COLUMN_ROLES = MappingProxyType({
    "POINT_ID": "point_id", "X": "x", "Y": "y", "Z": "z", "CODE": "code", "LINE": "line",
})
"""El papel del asistente → el de ``gis.points.ColumnMapping`` (y de ``settings["columns"]``)."""
_STATIC: set[str] = set()  # ni animable ni nada más


class GEOBLENDER_PG_gis_column(bpy.types.PropertyGroup):
    """Una columna del fichero de puntos y su papel (RF-006-12)."""

    index: IntProperty(  # type: ignore[valid-type]
        name="Column", description="Column of the file, from 0", default=0, min=0,
        options=_STATIC,
    )
    role: EnumProperty(  # type: ignore[valid-type]
        name="Role", items=COLUMN_ROLE_ITEMS, default=NOT_IMPORTED, options=_STATIC,
    )


class GEOBLENDER_PG_gis_export_item(bpy.types.PropertyGroup):
    """Un dato de la topografía en «Capas a GeoPackage…» y si se exporta (RF-006-25)."""

    selected: BoolProperty(  # type: ignore[valid-type]
        name="Export the layer", description="Write this layer to the GeoPackage",
        default=True, options=_STATIC,
    )


classes: tuple[type, ...] = (GEOBLENDER_PG_gis_column, GEOBLENDER_PG_gis_export_item)
"""Los grupos de propiedades de ``gis``."""
