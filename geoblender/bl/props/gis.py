# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades del módulo ``gis`` (spec 006, T29; RF-006-12; plan 006 §5.1 y §5.3.5).

:class:`GEOBLENDER_PG_gis_column` es una fila del asistente de «Puntos y líneas de rotura…»
(``geoblender.gis_import_points``): una columna del fichero de texto (su índice desde 0, su
nombre en la cabecera y lo que lleva en las primeras filas) y su papel (P, X, Y, Z, código,
línea o ninguno). Solo texto, enteros y enumerados: ninguna coordenada (ADR-0005). Desde un
guion, ``columns=[{"name": "X", "index": 1, "role": "X"}, …]`` (Blender pide ``name`` en
cada fila).

No se anima (``options=set()``).
"""

from __future__ import annotations

from types import MappingProxyType

import bpy
from bpy.props import EnumProperty, IntProperty

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


classes: tuple[type, ...] = (GEOBLENDER_PG_gis_column,)
"""Los grupos de propiedades de ``gis``."""
