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
  (español por defecto, independiente del de Blender; al cambiarlo se aplica sin
  reiniciar, ``bl.ui.i18n``), títulos de la barra (automático,
  texto o iconos; BS §3), fila de acceso rápido de la vista, «Ocultar lo no disponible»
  (BS §7.3) y barra de estado minera (AR §6).

- ``WindowManager.geoblender_redraw`` (:data:`REDRAW_PROPERTY`, spec 009, T35 y T41): la
  petición de redibujar todas las ventanas, también la barra superior y la de estado, que son
  áreas globales fuera de ``screen.areas``. No guarda nada que se lea: la cambia
  ``bl.ui.bars.redraw`` y lo que importa es su función ``update`` (:func:`redraw_all_windows`).

- :func:`remembered_language` y :func:`remember_language` (spec 003, T37; RF-003-20; II
  §2.2): el idioma de Geoblender de la última sesión, en un fichero de la carpeta de datos
  de la extensión (``ui/language``). Las preferencias no se pueden leer hasta que se
  registra ``GeoblenderPreferences``, y los grupos de propiedades (el suyo incluido) se
  registran antes: con él, sus nombres y descripciones salen en ese idioma «al reiniciar».
  Lo escribe ``bl.ui.i18n`` cada vez que fija el idioma.

Nada es animable (``options=set()``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
)

from .. import ADDON_PACKAGE

LOGGER = logging.getLogger("geoblender.bl.props")

LANGUAGE_FILE = ("ui", "language")  # carpeta y fichero en los datos de la extensión

# Nombre de la marca del modo en WorkSpace (API pública: la leen la plantilla y los scripts).
WORKSPACE_PROPERTY = "geoblender_mode"
# Vistas guardadas de la escena (API pública: la leen los scripts).
VIEWS_PROPERTY = "geoblender_views"
# La petición de redibujar todas las ventanas (spec 009, T35 y T41; la cambia bl.ui.bars).
REDRAW_PROPERTY = "geoblender_redraw"
SAVED_VIEW_SLOTS = 4
PERSPECTIVE_ITEMS = [
    ("PERSP", "Perspective", "Perspective projection"),
    ("ORTHO", "Orthographic", "Orthographic projection"),
]
_STATIC: set[str] = set()

# Idioma de Geoblender: ES (por defecto) o EN; core.i18n usa "es" y "en".
LANGUAGES: dict[str, str] = {"ES": "es", "EN": "en"}
LANGUAGE_ITEMS = [
    ("ES", "Spanish", "Geoblender in Spanish"),
    ("EN", "English", "Geoblender in English"),
]
# Títulos de la barra superior (BS §3): automático (el primer nivel de A a E que cabe),
# siempre texto o siempre iconos.
TOPBAR_TITLES_ITEMS = [
    ("AUTO", "Automatic", "The first level that fits next to the right block of Blender"),
    ("TEXT", "Text", "Menu titles as text"),
    ("ICONS", "Icons", "Menu titles as icons"),
]


def _language_path(create: bool) -> Path:
    folder = bpy.utils.extension_path_user(ADDON_PACKAGE, path=LANGUAGE_FILE[0], create=create)
    return Path(folder) / LANGUAGE_FILE[1]


def remembered_language() -> str:
    """El idioma de Geoblender de la última sesión (``"es"`` o ``"en"``; español si no se
    sabe)."""
    try:
        value = _language_path(create=False).read_text(encoding="utf-8").strip()
    except (OSError, ValueError, UnicodeDecodeError):
        return "es"
    return value if value in LANGUAGES.values() else "es"


def remember_language(language: str) -> None:
    """Guarda ``language`` (``"es"`` o ``"en"``) para la sesión siguiente; si no se puede,
    no pasa nada (se usará el español)."""
    if language not in LANGUAGES.values():
        return
    try:
        path = _language_path(create=True)
        if not path.is_file() or path.read_text(encoding="utf-8").strip() != language:
            path.write_text(language, encoding="utf-8")
    except (OSError, ValueError):
        pass


def _language_changed(group: object, context: object) -> None:
    """Elegir el idioma de Geoblender lo aplica sin reiniciar, en el siguiente ciclo
    (``bl.ui.i18n``; RF-003-21)."""
    from ..ui import i18n  # diferido: bl/ui importa bl/props

    i18n.on_preference_changed(group, context)


def redraw_all_windows(_manager: Any, _context: Any) -> None:
    """La función ``update`` de ``WindowManager.geoblender_redraw`` (spec 009, T35 y T41;
    RF-009-10, RF-008-28). Solo deja una línea en el registro técnico: lo que importa es que
    exista. Asignar desde Python una propiedad de ``bpy.props`` **sin** ``update`` no avisa a
    nada (ni redibuja ni marca el grafo de dependencias); **con** ``update``, Blender la ejecuta
    y avisa después a todas las regiones de todas las ventanas (``NC_WINDOW``), también a la
    barra superior y a la de estado, que son áreas globales de la ventana, fuera de
    ``screen.areas``, a las que ``Area.tag_redraw`` no llega (``docs/trampas.md`` §5)."""
    LOGGER.debug("Se pide redibujar todas las ventanas")


class GEOBLENDER_PG_ui_preferences(bpy.types.PropertyGroup):
    """Preferencias de la interfaz de Geoblender (spec 003)."""

    language: EnumProperty(  # type: ignore[valid-type]
        name="Geoblender language",
        description="Language of the Geoblender interface, independent of Blender's",
        items=LANGUAGE_ITEMS,
        default="ES",
        options=_STATIC,
        update=_language_changed,
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
    """Pone ``WorkSpace.geoblender_mode``, ``Scene.geoblender_views`` (las clases ya están
    registradas) y ``WindowManager.geoblender_redraw``."""
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
    setattr(
        bpy.types.WindowManager,
        REDRAW_PROPERTY,
        BoolProperty(options=_STATIC, update=redraw_all_windows),
    )


def unregister() -> None:
    """Quita ``WindowManager.geoblender_redraw``, ``Scene.geoblender_views`` y
    ``WorkSpace.geoblender_mode``; sin ellas, nada."""
    if hasattr(bpy.types.WindowManager, REDRAW_PROPERTY):
        delattr(bpy.types.WindowManager, REDRAW_PROPERTY)
    if hasattr(bpy.types.Scene, VIEWS_PROPERTY):
        delattr(bpy.types.Scene, VIEWS_PROPERTY)
    if hasattr(bpy.types.WorkSpace, WORKSPACE_PROPERTY):
        delattr(bpy.types.WorkSpace, WORKSPACE_PROPERTY)
