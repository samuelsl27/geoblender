# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades de los sondeos (spec 005, T24; RF-005-10, RF-005-11, RF-005-16, RF-005-19,
RF-005-23 a RF-005-25; plan 005 §5.1 y §5.5).

- ``Scene.geoblender_dh_display`` (:class:`GEOBLENDER_PG_dh_display`): la **representación** de
  los sondeos (pestaña «Sondeos» ▸ «Representación»): el esquema de logueo de los tubos, su
  radio, el elemento de las barras de leyes con las clases de su leyenda
  (:class:`GEOBLENDER_PG_dh_grade_class`, editable, en la unidad del elemento; RF-005-24), el
  ancho y la separación de las barras, las etiquetas (RF-005-25) y la leyenda. Es de la escena:
  se guarda con el ``.blend``. Ningún valor es una coordenada (ADR-0005): radio, ancho y
  separación son longitudes de dibujo; el límite de cada clase, el texto tal como se escribe
  (un ``FloatProperty`` lo redondearía a float32).
- ``WindowManager.geoblender_dh_import`` (:class:`GEOBLENDER_PG_dh_import`): la **importación
  pendiente** («Importación pendiente», RF-005-10 y RF-005-11): su operación, los códigos
  nuevos y si se dan de alta, los sondeos que ya están en el proyecto con lo que se hace con
  cada uno (:class:`GEOBLENDER_PG_dh_pending_hole`) y el motivo de una sustitución.
- ``WindowManager.geoblender_dh_validation`` (:class:`GEOBLENDER_PG_dh_validation`): la
  **validación** («Validación», RF-005-16): las incidencias (:class:`GEOBLENDER_PG_dh_issue`,
  ya en texto) con los filtros por nivel y código de la lista.

Las dos de ``WindowManager`` son una vista que se regenera desde el proyecto y no se guarda en
el ``.blend`` (como la de la procedencia, D16 de la 008). Las propiedades de las filas no
tienen nombre ni descripción: las dibujan los paneles con sus textos. Ninguna se anima.
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
    PointerProperty,
    StringProperty,
)

SCENE_PROPERTY = "geoblender_dh_display"
"""El nombre de la representación de los sondeos en ``Scene``."""
IMPORT_PROPERTY = "geoblender_dh_import"
"""El nombre de la importación pendiente en ``WindowManager``."""
VALIDATION_PROPERTY = "geoblender_dh_validation"
"""El nombre de la validación en ``WindowManager``."""
LOG_SET = "lithology"
"""El esquema de logueo por defecto: la litología (``drillholes.model.LITHOLOGY_LOG_SET``)."""
FILTER_ALL = "ALL"
LEVEL_FILTER_ITEMS = [
    (FILTER_ALL, "Any", ""),
    ("ERROR", "Error", ""),
    ("WARNING", "Warning", ""),
]
"""Los niveles de la lista de incidencias (el de una incidencia, ``drillholes.validate.Level``
en mayúsculas)."""
_STATIC: set[str] = set()  # ni animable ni nada más


class GEOBLENDER_PG_dh_grade_class(bpy.types.PropertyGroup):
    """Una clase de la leyenda de leyes: desde dónde empieza y su color (RF-005-24)."""

    lower: StringProperty(  # type: ignore[valid-type]
        name="From",
        description="Lower limit of the class, as written, in the unit of the element "
                    "(empty: from the lowest value)",
        default="", options=_STATIC,
    )
    color: FloatVectorProperty(  # type: ignore[valid-type]
        name="Color", description="Color of the class", subtype="COLOR_GAMMA", size=3,
        min=0.0, max=1.0, default=(0.5, 0.5, 0.5), options=_STATIC,
    )


class GEOBLENDER_PG_dh_display(bpy.types.PropertyGroup):
    """La representación de los sondeos en la vista (RF-005-23 a RF-005-25)."""

    log_set: StringProperty(  # type: ignore[valid-type]
        name="Logging scheme",
        description="Lithology logging scheme that colors the tubes (lithology, or an extra "
                    "table of RecMin)",
        default=LOG_SET, options=_STATIC,
    )
    tube_radius: FloatProperty(  # type: ignore[valid-type]
        name="Tube radius", description="Radius of the drillhole tubes, in metres",
        default=0.5, min=0.01, soft_max=10.0, options=_STATIC,
    )
    element: StringProperty(  # type: ignore[valid-type]
        name="Element",
        description="Element whose grade bars are drawn beside each interval (empty: none)",
        default="", options=_STATIC,
    )
    grade_classes: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_dh_grade_class, options=_STATIC, name="Grade classes",
        description="Classes of the grade legend, in the unit of the element",
    )
    bar_width: FloatProperty(  # type: ignore[valid-type]
        name="Bar width", description="Width of the grade bars, in metres",
        default=2.0, min=0.01, soft_max=50.0, options=_STATIC,
    )
    bar_offset: FloatProperty(  # type: ignore[valid-type]
        name="Bar separation",
        description="Separation of the grade bars from the drillhole trace, in metres",
        default=1.0, min=0.0, soft_max=50.0, options=_STATIC,
    )
    show_labels: BoolProperty(  # type: ignore[valid-type]
        name="Labels", description="Name and total depth of each drillhole at its collar",
        default=False, options=_STATIC,
    )
    labels_at_end: BoolProperty(  # type: ignore[valid-type]
        name="Depth at the bottom", description="Also the depth at the bottom of each drillhole",
        default=False, options=_STATIC,
    )
    show_legend: BoolProperty(  # type: ignore[valid-type]
        name="Legend", description="Legend of the lithology and of the grade classes",
        default=True, options=_STATIC,
    )


class GEOBLENDER_PG_dh_pending_hole(bpy.types.PropertyGroup):
    """Un sondeo de la fuente que ya está en el proyecto (su nombre, ``name``) y si se
    conservan sus registros (RF-005-11)."""

    keep: BoolProperty(  # type: ignore[valid-type]
        name="Keep the existing records",
        description="Keep the records of this drillhole already in the project instead of "
                    "replacing them with those of the source",
        default=False, options=_STATIC,
    )


class GEOBLENDER_PG_dh_import(bpy.types.PropertyGroup):
    """La importación de sondeos que espera la decisión de la persona (RF-005-10,
    RF-005-11)."""

    operation_uid: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, name="Pending import",
        description="Uid of the import operation that waits for a decision",
    )
    new_codes: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, name="New codes",
        description="Codes of the source that are not in the catalogs of the project",
    )
    register_codes: BoolProperty(  # type: ignore[valid-type]
        name="Register the new codes",
        description="Add the new codes to the catalogs of the project (the lithologies, with "
                    "a color of their own); without it, the import is cancelled",
        default=True, options=_STATIC,
    )
    holes: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_dh_pending_hole, options=_STATIC,
        name="Drillholes already in the project",
        description="Drillholes of the source that the project already has",
    )
    reason: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, name="Reason",
        description="Why the input replaces the one imported with the same data and other "
                    "settings",
    )


class GEOBLENDER_PG_dh_issue(bpy.types.PropertyGroup):
    """Una incidencia de la validación, ya en texto (RF-005-16): código, nivel, sondeo,
    tabla, tramo o profundidad, campo, valor y mensaje."""

    code: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    level: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    hole: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    table: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    depth: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    field: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    value: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    message: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_dh_validation(bpy.types.PropertyGroup):
    """Las incidencias de la última validación de los sondeos y los filtros de su lista
    (RF-005-16)."""

    issues: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_dh_issue, options=_STATIC, name="Validation issues",
        description="Issues of the last validation of the drillhole database",
    )
    issue_index: IntProperty(  # type: ignore[valid-type]
        default=0, min=0, options=_STATIC, name="Selected issue",
        description="Selected row of the validation issues",
    )
    level_filter: EnumProperty(  # type: ignore[valid-type]
        items=LEVEL_FILTER_ITEMS, default=FILTER_ALL, options=_STATIC, name="Level",
        description="Show only the issues of this level",
    )
    code_filter: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, name="Code",
        description="Show only the issues whose code contains this text",
    )


# En orden de registro: las filas antes de quien las reúne.
classes: tuple[type, ...] = (
    GEOBLENDER_PG_dh_grade_class,
    GEOBLENDER_PG_dh_display,
    GEOBLENDER_PG_dh_pending_hole,
    GEOBLENDER_PG_dh_import,
    GEOBLENDER_PG_dh_issue,
    GEOBLENDER_PG_dh_validation,
)

_POINTERS: tuple[tuple[type, str, type], ...] = (
    (bpy.types.Scene, SCENE_PROPERTY, GEOBLENDER_PG_dh_display),
    (bpy.types.WindowManager, IMPORT_PROPERTY, GEOBLENDER_PG_dh_import),
    (bpy.types.WindowManager, VALIDATION_PROPERTY, GEOBLENDER_PG_dh_validation),
)


def register() -> None:
    """Pone ``Scene.geoblender_dh_display``, ``WindowManager.geoblender_dh_import`` y
    ``WindowManager.geoblender_dh_validation`` (las clases ya están registradas)."""
    for owner, name, group in _POINTERS:
        setattr(owner, name, PointerProperty(type=group, options=_STATIC))


def unregister() -> None:
    """Quita las tres (antes de desregistrar las clases); sin ellas, nada."""
    for owner, name, _group in reversed(_POINTERS):
        if hasattr(owner, name):
            delattr(owner, name)
