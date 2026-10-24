# SPDX-License-Identifier: GPL-3.0-or-later
"""Las propiedades de la cubicación (spec 011, T19; RF-011-06, RF-011-11, RF-011-23; plan 011
§5.1 y §5.2.4).

``WindowManager.geoblender_res_panels`` (:class:`GEOBLENDER_PG_res_panels`) guardará lo que
dibujan N ▸ Proyecto ▸ Cubicaciones, la ventana de una cubicación y la de Materiales y
densidades…: las cubicaciones de la versión activa ya leídas (nombre, revisión, «vigente» o «en
curso», obsoleta), la elegida, sus filas ya presentadas con sus filtros (dominio, rodaja, unidad)
y la columna de materiales en edición. Es una **vista** que se regenera desde el proyecto, nunca
la fuente (nada se lee al dibujar, como la 008 y la 010); vive en ``WindowManager``, que Blender
no guarda en el ``.blend``.

T19: el grupo, aún sin filas (las ponen la T20, la columna en edición, y la T25, el panel).
Ninguna propiedad será una coordenada ni una cota en ``FloatProperty`` (ADR-0005; las cotas, los
anclajes y los espesores de los diálogos, en ``StringProperty``: ``docs/trampas.md`` §1).
"""

from __future__ import annotations

import bpy
from bpy.props import PointerProperty

WINDOW_MANAGER_PROPERTY = "geoblender_res_panels"
"""El nombre de la propiedad de ``WindowManager`` (la usan los paneles de la cubicación)."""
_STATIC: set[str] = set()  # ni animable ni nada más


class GEOBLENDER_PG_res_panels(bpy.types.PropertyGroup):
    """Lo que dibujan los paneles de la cubicación (una vista; véase el módulo)."""


classes: tuple[type, ...] = (GEOBLENDER_PG_res_panels,)


def register() -> None:
    """Pone ``WindowManager.geoblender_res_panels`` (las clases ya están registradas)."""
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_res_panels, options=_STATIC))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_res_panels`` (antes de desregistrar las clases); sin
    ella, nada."""
    if hasattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY):
        delattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY)
