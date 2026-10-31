# SPDX-License-Identifier: GPL-3.0-or-later
"""Las propiedades de los límites y las restricciones (spec 012, T21, T22; RF-012-05,
RF-012-19, RF-012-28; plan 012 §5.1 y §5.2.4).

``WindowManager.geoblender_constraints`` (:class:`GEOBLENDER_PG_core_constraints`) guarda lo
que dibujan las ventanas Límites, Restricciones, Buscar elementos intocables por sector,
Intenciones del cliente y Verificación, y la barra N «Restricción»: las restricciones ya leídas
(código, nombre, tipo, estado, parámetros resueltos en la versión activa, últimas cifras), la
activa y sus filtros, los sectores y su búsqueda, y las verificaciones de la versión. Es una
**vista** que se regenera desde el proyecto, nunca la fuente (nada se lee al dibujar, como la 008
y la 010); vive en ``WindowManager``, que Blender no guarda en el ``.blend``.

**Límites…** (T22): las capas de polígonos del proyecto con sus dos casillas
(:class:`GEOBLENDER_PG_core_layer_choice`: límite legal y perímetro de actuación), los campos
del formulario (el campo del nombre, el motivo, el decisor, la fecha y el resguardo hacia dentro,
todos en texto) y las líneas del informe de los límites
(:class:`GEOBLENDER_PG_core_report_line`: cada una con su texto ya traducido y, la de una parte
de la franja, el lugar al que lleva «Ir a»).

Ninguna propiedad es una coordenada ni una distancia en ``FloatProperty`` (ADR-0005; los
resguardos, los pesos, las distancias y los espesores de los diálogos, en ``StringProperty``:
``docs/trampas.md`` §1; las coordenadas absolutas de «Ir a», también en texto).
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty, StringProperty

WINDOW_MANAGER_PROPERTY = "geoblender_constraints"
"""El nombre de la propiedad de ``WindowManager`` (la usan las ventanas de las restricciones)."""
_STATIC: set[str] = set()  # ni animable ni nada más


class GEOBLENDER_PG_core_layer_choice(bpy.types.PropertyGroup):
    """Una capa de polígonos del proyecto que ofrece Límites…: su dato (``name``) y si es un
    límite legal o el perímetro de actuación."""

    legal: BoolProperty(  # type: ignore[valid-type]
        default=False, options=_STATIC,
        description="Use this layer as (part of) the legal limit")
    perimeter: BoolProperty(  # type: ignore[valid-type]
        default=False, options=_STATIC,
        description="Use this layer as the action perimeter")


class GEOBLENDER_PG_core_report_line(bpy.types.PropertyGroup):
    """Una línea del informe de los límites, ya traducida: su texto, si va en alerta y, si lleva
    «Ir a», el lugar (``x`` e ``y`` absolutas y el radio en metros, en texto: ADR-0005)."""

    text: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    alert: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]
    x: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    y: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    radius: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_constraints(bpy.types.PropertyGroup):
    """Lo que dibujan las ventanas de las restricciones (una vista; véase el módulo)."""

    limit_layers: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_layer_choice)
    limit_name_field: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Field of the layers that gives the name of each limit; without it, the "
                    "name of the layer")
    limit_reason: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Why these limits are the ones in force (title, concession, decision)")
    limit_decided_by: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, description="Who decides that these are the limits")
    limit_decided_on: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, description="Date of the decision, as DD/MM/YYYY")
    limit_inward: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Distance in metres, inside the legal limit, where cutting is not allowed")
    limit_lines: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_report_line)


classes: tuple[type, ...] = (GEOBLENDER_PG_core_layer_choice, GEOBLENDER_PG_core_report_line,
                             GEOBLENDER_PG_core_constraints)


def register() -> None:
    """Pone ``WindowManager.geoblender_constraints`` (las clases ya están registradas)."""
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_core_constraints, options=_STATIC))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_constraints`` (antes de desregistrar las clases); sin
    ella, nada."""
    if hasattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY):
        delattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY)
