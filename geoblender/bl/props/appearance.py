# SPDX-License-Identifier: GPL-3.0-or-later
"""El espejo del aspecto de un elemento en su objeto (spec 019, T07; RF-019-07, RF-019-08; plan 019 §5.2 y A1).

:class:`GEOBLENDER_PG_core_appearance`, en ``Object.geoblender.look``: color, transparencia, visibilidad,
rótulo, grosor, tamaño y etiquetas del elemento que muestra el objeto, como **colores y enteros** (ninguna
coordenada: el color y la transparencia no lo son, regla 4 de ``AGENTS.md``). Cambiar una propiedad
**aplica en el acto** a la vista del objeto (``bl.scene.appearance.apply``; RNF-019-03) y no toca nada más:
ni la geometría, ni la procedencia, ni el proyecto (la escritura diferida a ``gb_appearance`` es de T08).
**Manda la tabla** del proyecto: el espejo es lo que hay sin ella (RF-019-08).

Qué propiedades se ofrecen de cada tipo lo dice el catálogo (``core.appearance.catalog.allowed``) filtrado por
lo que el aplicador sabe hacer (``bl.scene.appearance.offered``): un tipo sin la propiedad no la ofrece (UI-13).
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty

# Los límites de ``core.appearance.model`` (``LABEL_MAX`` y ``RANGES``), copiados: registrar no importa el dominio del
# aspecto (RNF-001-03, perezoso); una prueba los compara.
LABEL_MAX = 120
LINE_WIDTH_RANGE = (0.5, 20.0)
POINT_SIZE_RANGE = (1.0, 50.0)

_STATIC: set[str] = set()


def _changed(self: bpy.types.PropertyGroup, _context: bpy.types.Context) -> None:
    """``update`` de cada propiedad: aplica el aspecto al objeto en el acto (el módulo de la escena se
    importa aquí, al usarlo)."""
    from ..draw import style
    from ..scene import appearance

    if isinstance(self.id_data, bpy.types.Object):
        style.note(self.id_data)  # lo que dibuja ``bl.draw.look`` mira solo los objetos con algo guardado
    appearance.on_changed(self)


class GEOBLENDER_PG_core_appearance(bpy.types.PropertyGroup):
    """El aspecto de un elemento tal como lo ve la vista (``Object.geoblender.look``)."""

    label: StringProperty(  # type: ignore[valid-type]
        name="Label", description="Name shown for the element in the views", default="",
        maxlen=LABEL_MAX, options=_STATIC, update=_changed,
    )
    color: FloatVectorProperty(  # type: ignore[valid-type]
        name="Color", description="Color of the element in the views", subtype="COLOR", size=3,
        min=0.0, max=1.0, default=(0.6, 0.6, 0.6), options=_STATIC, update=_changed,
    )
    transparency: IntProperty(  # type: ignore[valid-type]
        name="Transparency", description="Transparency of the element in the views, in percent",
        subtype="PERCENTAGE", min=0, max=100, default=0, options=_STATIC, update=_changed,
    )
    visible: BoolProperty(  # type: ignore[valid-type]
        name="Visible", description="Show the element in the views", default=True,
        options=_STATIC, update=_changed,
    )
    line_width: FloatProperty(  # type: ignore[valid-type]
        name="Line width", description="Width of the lines of the element, in pixels",
        min=LINE_WIDTH_RANGE[0], max=LINE_WIDTH_RANGE[1], default=1.0,
        options=_STATIC, update=_changed,
    )
    point_size: FloatProperty(  # type: ignore[valid-type]
        name="Point size", description="Size of the points of the element, in pixels",
        min=POINT_SIZE_RANGE[0], max=POINT_SIZE_RANGE[1], default=3.0,
        options=_STATIC, update=_changed,
    )
    labels: BoolProperty(  # type: ignore[valid-type]
        name="Labels", description="Show the names of the parts of the element", default=False,
        options=_STATIC, update=_changed,
    )
    wire: BoolProperty(  # type: ignore[valid-type]
        name="Wireframe", description="Show the edges of the element over its faces", default=False,
        options=_STATIC, update=_changed,
    )


classes: tuple[type, ...] = (GEOBLENDER_PG_core_appearance,)
