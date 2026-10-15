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
  ya en texto) y (T27) lo que no se evaluó, con los filtros por nivel y código de la lista.

Las dos de ``WindowManager`` son una vista que se regenera desde el proyecto y no se guarda en
el ``.blend`` (como la de la procedencia, D16 de la 008). Las propiedades de las filas no
tienen nombre ni descripción: las dibujan los paneles con sus textos. Ninguna se anima.

(T25; RF-005-05) **El asistente de la importación de tablas**: cada fichero (o cada hoja de un
XLSX) es una tabla (:class:`GEOBLENDER_PG_dh_table`) con su papel y sus columnas
(:class:`GEOBLENDER_PG_dh_column`), y cada columna, el campo de la tabla que da: una
enumeración **dinámica** (sus elementos dependen del papel) cuyos elementos salen de una caché
del módulo (:func:`field_items`, riesgo R9 del plan: Blender no guarda los textos de los
elementos que devuelve una función, y si Python libera la lista, la interfaz lee basura), con
un número fijo por campo en todos los papeles. Cambiar el papel de una tabla propone otra vez
sus campos (``interop.drillholes_tabular.suggest_mapping``); :func:`table_mapping` da la
correspondencia de una tabla y :func:`fill_tables`, las tablas de unos ficheros.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any

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

from ...core.i18n import language, tr, translate
from ...interop.drillholes_tabular import ELEMENT_PREFIX, TableRole, aliases, suggest_mapping

SCENE_PROPERTY = "geoblender_dh_display"
"""El nombre de la representación de los sondeos en ``Scene``."""
IMPORT_PROPERTY = "geoblender_dh_import"
"""El nombre de la importación pendiente en ``WindowManager``."""
VALIDATION_PROPERTY = "geoblender_dh_validation"
"""El nombre de la validación en ``WindowManager``."""
LOG_SET = "lithology"
"""El esquema de logueo por defecto: la litología (``drillholes.model.LITHOLOGY_LOG_SET``)."""
FILTER_ALL = "ALL"
NOT_EVALUATED = "NOT_EVALUATED"
"""El nivel de una fila de la lista que dice lo que no se evaluó (una nota del informe)."""
LEVEL_FILTER_ITEMS = [
    (FILTER_ALL, "Any", ""),
    ("ERROR", "Error", ""),
    ("WARNING", "Warning", ""),
    (NOT_EVALUATED, "Not evaluated", "What the validation could not check"),
]
"""Los niveles de la lista de incidencias (el de una incidencia, ``drillholes.validate.Level``
en mayúsculas; el de una nota, :data:`NOT_EVALUATED`)."""
_STATIC: set[str] = set()  # ni animable ni nada más

# --- El asistente de la importación de tablas (T25) --------------------------------------------

NOT_IMPORTED = "NONE"
ROLE_ITEMS = [
    ("COLLAR", "Collars", ""),
    ("SURVEY", "Surveys", ""),
    ("LITHOLOGY", "Lithology", ""),
    ("ASSAY_WIDE", "Assays in columns", "One column per element"),
    ("ASSAY_LONG", "Assays in rows", "Element, value and unit in each row"),
    ("LITHOLOGY_CATALOG", "Lithology catalog", ""),
    ("ELEMENT_CATALOG", "Element catalog", ""),
]
"""El papel de una tabla de sondeos en una importación (``msgid`` en inglés)."""
ROLES: Mapping[str, str] = MappingProxyType(
    {identifier: identifier.lower() for identifier, *_rest in ROLE_ITEMS})
"""El papel de una tabla (``interop.drillholes_tabular.TableRole``, los de
``drillholes.provenance.TABLE_ROLES``) por el identificador de su elección."""
TABLE_ROLE_ITEMS = [(NOT_IMPORTED, "Not imported", ""), *ROLE_ITEMS]
"""El papel de una tabla en el asistente: uno de :data:`ROLE_ITEMS` o no se importa."""
FIELD_NONE = "NONE"
"""El campo de una columna que no se importa."""
FIELD_ELEMENT = "ELEMENT"
"""El campo de una columna de unos análisis en columnas que es un elemento (su código, el
nombre de la columna)."""
FIELD_MSGIDS: Mapping[str, str] = MappingProxyType({
    "name": "Hole", "hole": "Hole", "x": "X (east)", "y": "Y (north)", "z": "Z (elevation)",
    "depth": "Depth (m)", "azimuth": "Azimuth (°)", "inclination": "Inclination",
    "hole_type": "Type", "planned": "Planned", "grade_control": "Grade control",
    "category": "Category", "priority": "Priority", "sector": "Sector", "group": "Group",
    "campaign": "Campaign", "start_date": "Start date", "end_date": "End date",
    "survey_method": "Survey method", "external_id": "External identifier",
    "comments": "Comments", "method": "Method", "from_m": "From (m)", "to_m": "To (m)",
    "code": "Code", "description": "Description", "logged_by": "Logged by",
    "sample_id": "Sample", "lab": "Laboratory", "batch": "Batch", "element": "Element",
    "value": "Value", "unit": "Unit", "color": "Color (sRGB)", "pattern": "Pattern",
    "density": "Density", "sort_order": "Order", "decimals": "Decimals",
    "detection_limit": "Detection limit",
})
"""El nombre (``msgid``) de cada campo de una tabla de sondeos en el asistente."""
ROLE_FIELD_MSGIDS: Mapping[tuple[str, str], str] = MappingProxyType({
    (str(TableRole.ELEMENT_CATALOG), "name"): "Name",
})
"""Los campos que en un papel tienen otro nombre (el ``name`` de un elemento)."""
NONE_MSGID = "Not imported"
ELEMENT_MSGID = "Element (its column name)"
_FIELDS_IN_ORDER: tuple[str, ...] = tuple(dict.fromkeys(
    field for role in TableRole for field in aliases(role)))
_FIELD_NUMBERS: Mapping[str, int] = MappingProxyType({
    FIELD_NONE: 0, **{field: number for number, field in enumerate(_FIELDS_IN_ORDER, start=1)},
    FIELD_ELEMENT: len(_FIELDS_IN_ORDER) + 1})
"""El número fijo de cada elemento del campo de una columna (el mismo en todos los papeles:
el valor guardado es su número)."""
_FIELD_ITEMS: dict[tuple[str, str], list[tuple[str, str, str, int]]] = {}
"""La caché de los elementos del campo de una columna por papel e idioma (riesgo R9): las
listas viven mientras el módulo."""


def field_items(role: str, lang: str) -> list[tuple[str, str, str, int]]:
    """Los elementos del campo de una columna de una tabla del papel ``role`` (``""``: sin
    papel) en el idioma ``lang``: «No se importa», cada campo del papel en su orden y, en unos
    análisis en columnas, «Elemento (el nombre de su columna)»; la misma lista cada vez, de la
    caché del módulo (riesgo R9)."""
    key = (role, lang)
    found = _FIELD_ITEMS.get(key)
    if found is None:
        found = [(FIELD_NONE, translate(lang, NONE_MSGID), "", _FIELD_NUMBERS[FIELD_NONE])]
        if role:
            for field in aliases(role):
                msgid = ROLE_FIELD_MSGIDS.get((role, field), FIELD_MSGIDS[field])
                found.append((field, translate(lang, msgid), "", _FIELD_NUMBERS[field]))
            if role == str(TableRole.ASSAY_WIDE):
                found.append((FIELD_ELEMENT, translate(lang, ELEMENT_MSGID), "",
                              _FIELD_NUMBERS[FIELD_ELEMENT]))
        _FIELD_ITEMS[key] = found
    return found


def _column_field_items(self: Any, context: Any) -> list[tuple[str, str, str, int]]:
    return field_items(self.table_role, language())


def apply_mapping(table: Any, mapping: Mapping[str, str]) -> None:
    """Pone a las columnas de ``table`` (:class:`GEOBLENDER_PG_dh_table`) los campos de
    ``mapping`` (campo → columna, la de ``interop.drillholes_tabular``) para su papel; las
    columnas que no están en ella, «No se importa»."""
    role = ROLES.get(table.role, "")
    by_column: dict[str, str] = {}
    for field, column in (mapping.items() if role else ()):
        by_column.setdefault(column, FIELD_ELEMENT if field.startswith(ELEMENT_PREFIX)
                             else field)
    for column in table.columns:
        column.table_role = role
        column.field = by_column.get(column.name, FIELD_NONE)


def suggest_fields(table: Any) -> None:
    """Los campos propuestos para las columnas de ``table`` por sus nombres y su papel
    (``interop.drillholes_tabular.suggest_mapping``; sin papel, ninguno)."""
    role = ROLES.get(table.role)
    columns = [column.name for column in table.columns]
    apply_mapping(table, suggest_mapping(role, columns) if role else {})


def _role_changed(self: Any, context: Any) -> None:
    suggest_fields(self)


def table_mapping(table: Any) -> dict[str, str]:
    """La correspondencia de columnas de ``table`` (campo → columna; un elemento de unos
    análisis en columnas, ``"element:<código>"``); sin papel, vacía. ``ValueError`` si dos
    columnas dan el mismo campo."""
    if table.role not in ROLES:
        return {}
    found: dict[str, str] = {}
    for column in table.columns:
        field = column.field
        if field == FIELD_NONE:
            continue
        key = ELEMENT_PREFIX + column.name.strip() if field == FIELD_ELEMENT else field
        if key in found:
            raise ValueError(tr("Two columns of «{table}» give «{field}»: choose one",
                                table=table.name, field=key))
        found[key] = column.name
    return found


def fill_tables(tables: Any, choices: Iterable[Any]) -> None:
    """Las tablas del asistente (``tables``, una colección de :class:`GEOBLENDER_PG_dh_table`)
    de unas elecciones (``bl.ops.dh.TableChoice``: su fichero, su hoja, su nombre, su papel,
    sus columnas y su correspondencia)."""
    tables.clear()
    for choice in choices:
        table = tables.add()
        table.name = choice.label
        table.path = str(choice.path)
        table.sheet = choice.sheet or ""
        table.entry = choice.name
        for index, header in enumerate(choice.columns):
            column = table.columns.add()
            column.name = header
            column.index = index
        table.role = choice.role.upper() if choice.role else NOT_IMPORTED
        apply_mapping(table, choice.mapping)


class GEOBLENDER_PG_dh_column(bpy.types.PropertyGroup):
    """Una columna de una tabla del asistente (su cabecera, ``name``) y el campo que da."""

    index: IntProperty(default=0, min=0, options=_STATIC)  # type: ignore[valid-type]
    table_role: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    field: EnumProperty(items=_column_field_items, options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_dh_table(bpy.types.PropertyGroup):
    """Un fichero (o una hoja de un XLSX) del asistente, ``name`` lo que se enseña: su ruta,
    su hoja, el nombre de su entrada, su papel y sus columnas."""

    path: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    sheet: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    entry: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    role: EnumProperty(  # type: ignore[valid-type]
        items=TABLE_ROLE_ITEMS, default=NOT_IMPORTED, options=_STATIC, update=_role_changed,
    )
    columns: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_dh_column, options=_STATIC,
    )


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
    RF-005-11): su orden, la orden que la aplica o la descarta (``command``: la de las tablas
    o la de una base de RecMin, T26), lo que hay que confirmar antes de leer (``confirm``:
    una base de RecMin de esquema desconocido, RF-005-15), los códigos nuevos, los sondeos que
    ya están, y (``question``) las sustituciones que piden el motivo (RF-008-11)."""

    operation_uid: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, name="Pending import",
        description="Uid of the import operation that waits for a decision",
    )
    command: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    confirm: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
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
    question: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_dh_issue(bpy.types.PropertyGroup):
    """Una incidencia de la validación, ya en texto (RF-005-16): código, nivel, sondeo,
    tabla, tramo o profundidad, campo, valor y mensaje; o (T27) una nota de lo que no se
    evaluó, con el nivel :data:`NOT_EVALUATED`."""

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
    GEOBLENDER_PG_dh_column,
    GEOBLENDER_PG_dh_table,
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
