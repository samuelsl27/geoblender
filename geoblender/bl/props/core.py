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

Spec 008 (T45): ``registry_seq`` en la escena (RF-008-32; plan 008 §5.4.11), el número del
diario de Ctrl+Z que se copia en cada cambio registrado (``IntProperty``: viaja con la escena
que restaura deshacer); y ``read_only_folders`` en las preferencias (RF-008-15; S-3), las
carpetas de solo lectura del usuario separadas por «;», que :func:`read_only_dirs_of` suma a
las de la variable ``GEOBLENDER_READ_ONLY_DIRS``.

Ninguna se anima (``options=set()``): un fotograma clave sobre el GeoOrigin no tiene
sentido.
"""

from __future__ import annotations

import os

import bpy
from bpy.props import BoolProperty, IntProperty, PointerProperty, StringProperty

from ...core.paths import READ_ONLY_DIRS_ENV, READ_ONLY_DIRS_SEPARATOR, ReadOnlyDirs

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
    # Spec 008 (RF-008-32; plan 008 §5.4.11): el número del último cambio registrado en el
    # proyecto que ha visto esta escena; Ctrl+Z restaura la escena con el suyo.
    registry_seq: IntProperty(  # type: ignore[valid-type]
        name="Registry sequence",
        description=(
            "Number of the last change registered in the project that this scene has seen "
            "(Ctrl+Z restores it and warns that the project keeps the change)"
        ),
        default=0,
        min=0,
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
    # Spec 008 (RF-008-15; S-3 del plan 008; ADR-0025 §9): las carpetas de solo lectura de
    # este usuario, separadas por «;» como en la variable; se suman a las de la variable.
    read_only_folders: StringProperty(  # type: ignore[valid-type]
        name="Read-only folders",
        description=(
            "Folders where Geoblender never writes (client dossiers), separated by «;». "
            "The GEOBLENDER_READ_ONLY_DIRS variable adds those of the company"
        ),
        default="",
        options=_STATIC,
    )


def preference_folders(text: str) -> list[str]:
    """Las carpetas de solo lectura de la preferencia ``read_only_folders``: su texto partido
    por «;» (``core.paths.READ_ONLY_DIRS_SEPARATOR``), como lo pide
    ``core.paths.ReadOnlyDirs.from_sources`` (que salta las vacías)."""
    return str(text or "").split(READ_ONLY_DIRS_SEPARATOR)


def read_only_dirs_of(preferences: object | None) -> ReadOnlyDirs:
    """Las carpetas de solo lectura de ahora (RF-008-15; S-3): las de la variable
    ``GEOBLENDER_READ_ONLY_DIRS`` (se lee en cada llamada) más las de ``read_only_folders`` del
    grupo ``core`` de las preferencias ``preferences`` (``None``, aún sin preferencias:
    ninguna). No toca el disco ni la red: eso lo hace ``ReadOnlyDirs.contains``."""
    text = getattr(preferences, "read_only_folders", "")
    return ReadOnlyDirs.from_sources(
        os.environ.get(READ_ONLY_DIRS_ENV),
        preference_folders(text if isinstance(text, str) else ""),
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
