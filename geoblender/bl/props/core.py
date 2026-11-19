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

Spec 006 (T27; RF-006-29; plan 006 §5.1 y §5.6.7): :class:`GEOBLENDER_PG_core_object`, en
``Object.geoblender``, marca cada objeto que muestra un dato del proyecto en la vista: su tipo
(``kind``; las specs siguientes añaden los suyos a :data:`OBJECT_KINDS`), el uid de su dato y de
su proyecto, el hash de contenido de su dato, su estado (vigente, falta, bloqueado, dañado), la
fecha (UTC) de la operación que escribió su contenido y si estaba obsoleto al cargarlo; todo en
texto, enteros o enumerados (ninguna coordenada). :class:`GEOBLENDER_PG_core_view_dataset` es
una fila del diálogo de «Cargar en la vista…» (el dato, su nombre visible y si se carga).

Spec 010 (T07; RF-010-01, RF-010-02, RF-010-08; plan 010 §5.2, D-9, D-10 y D-17): tres campos
más en ``Object.geoblender``: ``view_state``, si el objeto está al día, no al día (muestra un
contenido anterior o se cargó con otro GeoOrigin) o sin respaldo en el proyecto
(:data:`VIEW_STATES`); ``origin``, el GeoOrigin con que se cargó, «X0 Y0 Z0» en metros enteros
(texto, como el ``geoorigin`` del ancla; vacío en lo cargado antes de la 010); y ``figures``, las
cifras registradas de su dato al cargarlo o al refrescar (:class:`GEOBLENDER_PG_core_figure`), en
texto ya escrito con su unidad y su tipo: solo para mostrarlas, nunca para calcular (principio 2;
ninguna propiedad flotante, principio 6).

Spec 009 (T18; RF-009-10; plan 009 §5.2.7, D-8, D-25): ``active_version_uid`` en la escena, la
versión activa de la sesión que se guarda con la vista (la elige ``bl.scene.versions``).

Ninguna se anima (``options=set()``): un fotograma clave sobre el GeoOrigin no tiene
sentido.
"""

from __future__ import annotations

import os

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

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
    # Spec 009 (T18; RF-009-10; plan 009 §5.2.7, D-8, D-25): la versión activa de la sesión, que
    # se guarda con la vista (su uid; "" sin versión). La elige bl.scene.versions al abrir el
    # proyecto y al cargar la vista; nunca se guarda en el proyecto.
    active_version_uid: StringProperty(  # type: ignore[valid-type]
        name="Active version",
        description="Identity of the version that this view works on (empty: no version)",
        default="",
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


# Spec 006 (T27; RF-006-29; plan 006 §5.1 y §5.6.7) ------------------------------------------

# Nombre de la propiedad de los objetos: Object.geoblender (API pública de scripts).
OBJECT_PROPERTY = "geoblender"
# El tipo de lo que muestra un objeto (plan 006 §5.1): NONE en un objeto que no es de Geoblender.
OBJECT_KINDS: list[tuple[str, str, str]] = [
    ("NONE", "Not from Geoblender", "An object that does not show project data"),
    ("PROJECT_ANCHOR", "Project anchor", "The absolute corners of the work window, as text"),
    ("DTM", "DTM", "A grid of the project (digital terrain model)"),
    ("TIN", "TIN", "A triangulated surface of the project"),
    ("POINTS", "Points", "Survey points of the project"),
    ("BREAKLINES", "Breaklines", "Breaklines of the project"),
    ("CONTOURS", "Contour lines", "Contour lines of the project"),
    ("BOUNDARY", "Boundary", "Boundaries and holes of the project"),
    ("DRILLHOLES", "Drillholes", "Drillholes of the project"),
    # Spec 011 (T22; RF-011-05; plan 011 §5.2.4, A15): la rejilla de diferencias de una cubicación.
    ("VOLUME_DIFFERENCE", "Difference grid",
     "The grid of differences between two surfaces of a cubication, drawn on the final one"),
    # Spec 012 (T25; RF-012-26; plan 012 §5.2.4): una marca del cliente guardada como intención.
    ("CLIENT_INTENTION", "Client intention",
     "A mark of the client saved as an intention: it never limits the design on its own"),
    # Spec 012 (T27; RF-012-19; plan 012 §5.2.4): una restricción o un límite del proyecto.
    ("CONSTRAINT", "Constraint",
     "A constraint or a limit of the project, shown by its edges"),
    # Spec 012 (T28; RF-012-23; plan 012 §5.2.4, D-42): la rejilla de incumplimientos de una
    # verificación por recinto.
    ("COMPLIANCE_GRID", "Non-compliance grid",
     "The cells of a final surface that do not comply with the constraints, with their thickness "
     "(final minus start), drawn on the final surface"),
    # Spec 013 (T27; RF-013-32; plan 013 §5.1, D-32): la envolvente, la superficie de diseño o la
    # rejilla de cotas de berma de un diseño.
    ("DESIGN", "Design",
     "The envelope, the design surface or the berm elevations of a design, drawn as a surface"),
    # Spec 015 (T28; RF-015-25; plan 015 §5.1): una entidad de diseño de una versión (la plataforma), con su
    # huella y su eje. Spec 016 (T33; RF-016-14; plan 016 §5.5): también la retirada de un acopio, el contrafuerte
    # y el cuerpo apoyado, y la detección de acopios (la de una versión o la del proyecto), con la huella de cada acopio.
    ("DESIGN_ENTITY", "Design entity",
     "A design entity (a platform, the removal of a stockpile, a buttress or a supported body) or a stockpile "
     "detection, drawn by its footprint"),
]
# El estado del dato al cargarlo (gb_dataset.status de un dato vivo, en mayúsculas).
OBJECT_STATUSES: list[tuple[str, str, str]] = [
    ("NONE", "No status", "An object that does not show project data"),
    ("CURRENT", "Current", "The data in force in the project"),
    ("MISSING", "Missing", "Its file or table is missing from the project"),
    ("BLOCKED", "Blocked", "Edited outside Geoblender: accept it, recompute it or import it again"),
    ("DAMAGED", "Damaged", "What was imported changed: import it again"),
]
# Spec 010 (T07; RF-010-02; plan 010 §5.2, D-10): si el objeto muestra lo que dice hoy el proyecto.
VIEW_STATES: list[tuple[str, str, str]] = [
    ("CURRENT", "Up to date",
     "It shows the content, the status and the GeoOrigin that its data has now in the project"),
    ("OUTDATED", "Not up to date",
     "It shows an earlier content of its data, or it was loaded with another GeoOrigin: "
     "Refresh (F5)"),
    ("UNBACKED", "Unbacked in the project",
     "Its data is no longer in the project or was discarded: it is not deleted"),
]


class GEOBLENDER_PG_core_figure(bpy.types.PropertyGroup):
    """Una cifra registrada del dato de un objeto (spec 010, RF-010-08; D-17), en texto ya
    escrito: su uid y su clave, su nombre con su ámbito y su valor con su unidad en el idioma de
    la interfaz al cargarlo («1 563 631 m³»), el código de su unidad y su tipo («CALCULADO»).
    Solo para mostrarla: la regenera la vista desde el proyecto y ningún cálculo la lee."""

    uid: StringProperty(  # type: ignore[valid-type]
        name="Figure", default="", options=_STATIC,
    )
    key: StringProperty(  # type: ignore[valid-type]
        name="Key", default="", options=_STATIC,
    )
    label: StringProperty(  # type: ignore[valid-type]
        name="Name", default="", options=_STATIC,
    )
    value_text: StringProperty(  # type: ignore[valid-type]
        name="Value", default="", options=_STATIC,
    )
    unit: StringProperty(  # type: ignore[valid-type]
        name="Unit", default="", options=_STATIC,
    )
    kind: StringProperty(  # type: ignore[valid-type]
        name="Type", default="", options=_STATIC,
    )


class GEOBLENDER_PG_core_object(bpy.types.PropertyGroup):
    """Lo que muestra un objeto de la vista: el dato del proyecto y su estado al cargarlo
    (RF-006-29)."""

    kind: EnumProperty(  # type: ignore[valid-type]
        name="Type",
        description="Type of the project data this object shows",
        items=OBJECT_KINDS,
        default="NONE",
        options=_STATIC,
    )
    dataset_uid: StringProperty(  # type: ignore[valid-type]
        name="Dataset",
        description="Identity of the project data this object shows",
        default="",
        options=_STATIC,
    )
    project_uid: StringProperty(  # type: ignore[valid-type]
        name="Project UID",
        description="Identity of the Geoblender project of this object",
        default="",
        options=_STATIC,
    )
    content_sha256: StringProperty(  # type: ignore[valid-type]
        name="Content hash",
        description="Content hash of the data when it was loaded (gbch/1)",
        default="",
        options=_STATIC,
    )
    stale: BoolProperty(  # type: ignore[valid-type]
        name="Stale",
        description="The data was stale when it was loaded",
        default=False,
        options=_STATIC,
    )
    status: EnumProperty(  # type: ignore[valid-type]
        name="Status",
        description="Status of the data in the project when it was loaded",
        items=OBJECT_STATUSES,
        default="NONE",
        options=_STATIC,
    )
    date: StringProperty(  # type: ignore[valid-type]
        name="Date",
        description="When the operation that wrote its content finished (UTC)",
        default="",
        options=_STATIC,
    )
    # Spec 010 (T07; plan 010 §5.2).
    view_state: EnumProperty(  # type: ignore[valid-type]
        name="In the view",
        description="Whether the object shows what its data has now in the project",
        items=VIEW_STATES,
        default="CURRENT",
        options=_STATIC,
    )
    origin: StringProperty(  # type: ignore[valid-type]
        name="GeoOrigin",
        description="GeoOrigin with which it was loaded, «X0 Y0 Z0» in whole metres",
        default="",
        options=_STATIC,
    )
    figures: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_figure,
        name="Figures",
        description=(
            "Figures recorded for its data when it was loaded or refreshed, as text: only to "
            "show them"
        ),
        options=_STATIC,
    )


class GEOBLENDER_PG_core_view_dataset(bpy.types.PropertyGroup):
    """Una fila del diálogo de «Cargar en la vista…»: un dato del proyecto."""

    uid: StringProperty(  # type: ignore[valid-type]
        name="Dataset", default="", options=_STATIC,
    )
    label: StringProperty(  # type: ignore[valid-type]
        name="Name", default="", options=_STATIC,
    )
    selected: BoolProperty(  # type: ignore[valid-type]
        name="Load", description="Load this data into the view", default=False,
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
# Los de la vista (spec 006, T27); la cifra, antes del objeto que la usa (spec 010, T07).
classes += (GEOBLENDER_PG_core_figure, GEOBLENDER_PG_core_object,
            GEOBLENDER_PG_core_view_dataset)


def register() -> None:
    """Pone ``Scene.geoblender`` y ``Object.geoblender`` (las clases ya están registradas)."""
    bpy.types.Scene.geoblender = PointerProperty(  # type: ignore[attr-defined]
        type=GEOBLENDER_PG_core_project, options=_STATIC
    )
    setattr(bpy.types.Object, OBJECT_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_core_object, options=_STATIC))


def unregister() -> None:
    """Quita ``Object.geoblender`` y ``Scene.geoblender`` (antes de desregistrar las clases);
    sin ellas, nada."""
    if hasattr(bpy.types.Object, OBJECT_PROPERTY):
        delattr(bpy.types.Object, OBJECT_PROPERTY)
    if hasattr(bpy.types.Scene, "geoblender"):
        del bpy.types.Scene.geoblender  # type: ignore[attr-defined]
