# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades de la interfaz (spec 003; RF-003-01, RF-003-02, RF-003-08, RF-003-10,
RF-003-11, RF-003-21, RF-003-28; plan 003 §5.2; ADR-0012).

- ``WorkSpace.geoblender_mode`` (:data:`WORKSPACE_PROPERTY`): la marca del modo
  Geoblender. Una ventana está en modo Geoblender cuando su espacio de trabajo activo la
  tiene (CW §1); se guarda en el ``.blend``. Al desactivar la extensión se quita la
  definición y el valor queda en el fichero (vuelve al habilitarla, CW §4).
- ``Scene.geoblender_views`` (:data:`VIEWS_PROPERTY`, spec 003 T22; RF-003-14): las
  vistas guardadas de la escena (ranuras 1–4, :class:`GEOBLENDER_PG_ui_saved_view`):
  orientación, centro **local** (``view_location_local``: a ±8 km del GeoOrigin, float32
  da ≤ 0,5 mm; nunca absoluto, ADR-0005), distancia y proyección. Se guardan con el
  ``.blend``, como las de Datamine (plan 003 DT6).
- :class:`GEOBLENDER_PG_ui_preferences`: el grupo ``ui`` de la única
  ``GeoblenderPreferences`` (``bl/props/preferences.py``): idioma de Geoblender
  (español por defecto, independiente del de Blender), títulos de la barra (automático,
  texto o iconos; BS §3), fila de acceso rápido de la vista, «Ocultar lo no disponible»
  (BS §7.3) y barra de estado minera (AR §6).

Nada es animable (``options=set()``).
"""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
)

# Nombre de la marca del modo en WorkSpace (API pública: la leen la plantilla y los scripts).
WORKSPACE_PROPERTY = "geoblender_mode"
# Vistas guardadas de la escena (API pública: la leen los scripts).
VIEWS_PROPERTY = "geoblender_views"
SAVED_VIEW_SLOTS = 4
PERSPECTIVE_ITEMS = [
    ("PERSP", "Perspective", "Perspective projection"),
    ("ORTHO", "Orthographic", "Orthographic projection"),
]
_STATIC: set[str] = set()

# Idioma de Geoblender: ES (por defecto) o EN; core.i18n usa "es" y "en".
LANGUAGES: dict[str, str] = {"ES": "es", "EN": "en"}
LANGUAGE_ITEMS = [
    ("ES", "Español", "Geoblender in Spanish"),
    ("EN", "English", "Geoblender in English"),
]
# Títulos de la barra superior (BS §3): automático (el primer nivel de A a E que cabe),
# siempre texto o siempre iconos.
TOPBAR_TITLES_ITEMS = [
    ("AUTO", "Automatic", "The first level that fits next to the right block of Blender"),
    ("TEXT", "Text", "Menu titles as text"),
    ("ICONS", "Icons", "Menu titles as icons"),
]


class GEOBLENDER_PG_ui_preferences(bpy.types.PropertyGroup):
    """Preferencias de la interfaz de Geoblender (spec 003)."""

    language: EnumProperty(  # type: ignore[valid-type]
        name="Geoblender language",
        description="Language of the Geoblender interface, independent of Blender's",
        items=LANGUAGE_ITEMS,
        default="ES",
        options=_STATIC,
    )
    topbar_titles: EnumProperty(  # type: ignore[valid-type]
        name="Top bar titles",
        description="How the Geoblender menus are shown in the top bar",
        items=TOPBAR_TITLES_ITEMS,
        default="AUTO",
        options=_STATIC,
    )
    show_view_quick_access: BoolProperty(  # type: ignore[valid-type]
        name="Quick access row of the view",
        description="Show the quick access row in each 3D view in Geoblender mode",
        default=True,
        options=_STATIC,
    )
    hide_unavailable: BoolProperty(  # type: ignore[valid-type]
        name="Hide what is not available yet",
        description="Hide inside the menus the commands that are not available yet",
        default=False,
        options=_STATIC,
    )
    show_mining_statusbar: BoolProperty(  # type: ignore[valid-type]
        name="Mining status bar",
        description="Show the project, its EPSG and the 3D cursor in the status bar",
        default=True,
        options=_STATIC,
    )


class GEOBLENDER_PG_ui_saved_view(bpy.types.PropertyGroup):
    """Una vista guardada (spec 003; RF-003-14): la ranura y lo que se restaura."""

    slot: IntProperty(  # type: ignore[valid-type]
        name="Slot", min=1, max=SAVED_VIEW_SLOTS, default=1, options=_STATIC,
    )
    view_location_local: FloatVectorProperty(  # type: ignore[valid-type]
        name="Centre (local)",
        description="Centre of the view in local coordinates (relative to the GeoOrigin)",
        size=3,
        options=_STATIC,
    )
    view_rotation: FloatVectorProperty(  # type: ignore[valid-type]
        name="Orientation", size=4, default=(1.0, 0.0, 0.0, 0.0), options=_STATIC,
    )
    view_distance: FloatProperty(  # type: ignore[valid-type]
        name="Distance", min=0.0, default=10.0, options=_STATIC,
    )
    view_perspective: EnumProperty(  # type: ignore[valid-type]
        name="Projection", items=PERSPECTIVE_ITEMS, default="PERSP", options=_STATIC,
    )


# En orden de registro (los grupos, antes de quien los usa).
classes: tuple[type, ...] = (GEOBLENDER_PG_ui_preferences, GEOBLENDER_PG_ui_saved_view)


def register() -> None:
    """Pone ``WorkSpace.geoblender_mode`` y ``Scene.geoblender_views`` (las clases ya
    están registradas)."""
    setattr(
        bpy.types.WorkSpace,
        WORKSPACE_PROPERTY,
        BoolProperty(
            name="Geoblender mode",
            description="This workspace is a Geoblender layout",
            default=False,
            options=_STATIC,
        ),
    )
    setattr(
        bpy.types.Scene,
        VIEWS_PROPERTY,
        CollectionProperty(type=GEOBLENDER_PG_ui_saved_view, options=_STATIC),
    )


def unregister() -> None:
    """Quita ``Scene.geoblender_views`` y ``WorkSpace.geoblender_mode``; sin ellas,
    nada."""
    if hasattr(bpy.types.Scene, VIEWS_PROPERTY):
        delattr(bpy.types.Scene, VIEWS_PROPERTY)
    if hasattr(bpy.types.WorkSpace, WORKSPACE_PROPERTY):
        delattr(bpy.types.WorkSpace, WORKSPACE_PROPERTY)
