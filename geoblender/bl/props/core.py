# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades del módulo ``core`` (spec 002; RF-002-10, RF-002-28; plan 002 §5.2).

- :class:`GEOBLENDER_PG_core_project`, en ``Scene.geoblender``: la georreferencia del
  proyecto abierto que se guarda con cada escena del ``.blend`` (identidad, nombre, ruta
  del proyecto **relativa** al ``.blend``, EPSG horizontal y vertical y GeoOrigin) y la
  marca de vista desfasada. El GeoOrigin va en ``IntProperty`` (metros enteros, 32 bits:
  4 435 300 < 2³¹), nunca en una propiedad flotante (float32; ADR-0005, ARQ-13), y sin
  límites que recorten un valor en silencio: lo valida ``core.georef``. La ventana de
  trabajo **no** va a la escena (sus esquinas son flotantes): se lee del proyecto
  abierto. Nada de esto es la fuente de verdad: lo es la base del proyecto, y
  ``bl.scene.georef`` lo sincroniza desde ella.
- :class:`GEOBLENDER_PG_core_preferences`: el grupo ``core`` de la única
  ``GeoblenderPreferences`` (``bl/props/preferences.py``): umbral del cerrojo caducado
  (de 10 a 1 440 min, 30 por defecto) y carpeta de las copias locales (vacía = la
  carpeta ``checkouts/`` de los datos de usuario, spec 002 D-4).

Ninguna se anima (``options=set()``): un fotograma clave sobre el GeoOrigin no tiene
sentido.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, IntProperty, PointerProperty, StringProperty

# Valores por defecto y límites del umbral del cerrojo (spec 002 §11; core.project.lock).
LOCK_STALE_DEFAULT = 30
LOCK_STALE_MIN = 10
LOCK_STALE_MAX = 1440
# 0 en vcrs_epsg: referencia vertical local (con su descripción en el proyecto).
LOCAL_VERTICAL = 0
# Nombre de la propiedad de la escena: Scene.geoblender (API pública de scripts).
SCENE_PROPERTY = "geoblender"
_STATIC: set[str] = set()  # ni animable ni nada más


class GEOBLENDER_PG_core_project(bpy.types.PropertyGroup):
    """Georreferencia del proyecto abierto, guardada con la escena (RF-002-28)."""

    project_uid: StringProperty(  # type: ignore[valid-type]
        name="Project UID",
        description="Identity of the Geoblender project of this scene",
        default="",
        options=_STATIC,
    )
    project_name: StringProperty(  # type: ignore[valid-type]
        name="Project name",
        default="",
        options=_STATIC,
    )
    project_path: StringProperty(  # type: ignore[valid-type]
        name="Project path",
        description="Project folder, relative to this .blend file (//…)",
        default="",
        options=_STATIC,
    )
    crs_epsg: IntProperty(  # type: ignore[valid-type]
        name="Horizontal CRS (EPSG)",
        default=0,
        options=_STATIC,
    )
    vcrs_epsg: IntProperty(  # type: ignore[valid-type]
        name="Vertical CRS (EPSG; 0 = local reference)",
        default=LOCAL_VERTICAL,
        options=_STATIC,
    )
    origin_x: IntProperty(  # type: ignore[valid-type]
        name="X0 (m)",
        description="GeoOrigin easting, whole metres",
        default=0,
        options=_STATIC,
    )
    origin_y: IntProperty(  # type: ignore[valid-type]
        name="Y0 (m)",
        description="GeoOrigin northing, whole metres",
        default=0,
        options=_STATIC,
    )
    origin_z: IntProperty(  # type: ignore[valid-type]
        name="Z0 (m)",
        description="GeoOrigin elevation, whole metres",
        default=0,
        options=_STATIC,
    )
    view_stale: BoolProperty(  # type: ignore[valid-type]
        name="View out of date",
        description="The view does not match the georeference of the project",
        default=False,
        options=_STATIC,
    )


class GEOBLENDER_PG_core_preferences(bpy.types.PropertyGroup):
    """Preferencias del módulo ``core`` (RF-002-10; spec 002 D-4)."""

    lock_stale_minutes: IntProperty(  # type: ignore[valid-type]
        name="Stale lock after (min)",
        description=(
            "Minutes without activity after which another session's lock can be forced"
        ),
        default=LOCK_STALE_DEFAULT,
        min=LOCK_STALE_MIN,
        max=LOCK_STALE_MAX,
        options=_STATIC,
    )
    checkout_dir: StringProperty(  # type: ignore[valid-type]
        name="Local copies folder",
        description="Folder for local working copies (empty: the extension's user data)",
        default="",
        subtype="DIR_PATH",
        options=_STATIC,
    )


# En orden de registro (los grupos, antes de quien los usa).
classes: tuple[type, ...] = (GEOBLENDER_PG_core_project, GEOBLENDER_PG_core_preferences)


def register() -> None:
    """Pone ``Scene.geoblender`` (las clases ya están registradas)."""
    bpy.types.Scene.geoblender = PointerProperty(  # type: ignore[attr-defined]
        type=GEOBLENDER_PG_core_project, options=_STATIC
    )


def unregister() -> None:
    """Quita ``Scene.geoblender`` (antes de desregistrar las clases); sin ella, nada."""
    if hasattr(bpy.types.Scene, "geoblender"):
        del bpy.types.Scene.geoblender  # type: ignore[attr-defined]
