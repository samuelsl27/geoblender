# SPDX-License-Identifier: GPL-3.0-or-later
"""Las propiedades de los límites y las restricciones (spec 012, T21; RF-012-19, RF-012-28; plan
012 §5.1 y §5.2.4).

``WindowManager.geoblender_constraints`` (:class:`GEOBLENDER_PG_core_constraints`) guardará lo
que dibujan las ventanas Límites, Restricciones, Buscar elementos intocables por sector,
Intenciones del cliente y Verificación, y la barra N «Restricción»: las restricciones ya leídas
(código, nombre, tipo, estado, parámetros resueltos en la versión activa, últimas cifras), la
activa y sus filtros, los sectores y su búsqueda, y las verificaciones de la versión. Es una
**vista** que se regenera desde el proyecto, nunca la fuente (nada se lee al dibujar, como la 008
y la 010); vive en ``WindowManager``, que Blender no guarda en el ``.blend``.

T21: el grupo, aún sin filas (las ponen la T22 a la T28, con la ventana de cada orden). Ninguna
propiedad será una coordenada ni una distancia en ``FloatProperty`` (ADR-0005; los resguardos,
los pesos, las distancias y los espesores de los diálogos, en ``StringProperty``:
``docs/trampas.md`` §1).
"""

from __future__ import annotations

import bpy
from bpy.props import PointerProperty

WINDOW_MANAGER_PROPERTY = "geoblender_constraints"
"""El nombre de la propiedad de ``WindowManager`` (la usan las ventanas de las restricciones)."""
_STATIC: set[str] = set()  # ni animable ni nada más


class GEOBLENDER_PG_core_constraints(bpy.types.PropertyGroup):
    """Lo que dibujan las ventanas de las restricciones (una vista; véase el módulo)."""


classes: tuple[type, ...] = (GEOBLENDER_PG_core_constraints,)


def register() -> None:
    """Pone ``WindowManager.geoblender_constraints`` (las clases ya están registradas)."""
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_core_constraints, options=_STATIC))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_constraints`` (antes de desregistrar las clases); sin
    ella, nada."""
    if hasattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY):
        delattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY)
