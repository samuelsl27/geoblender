# SPDX-License-Identifier: GPL-3.0-or-later
"""Las propiedades de la cubicación (spec 011, T19 y T20; RF-011-06, RF-011-11, RF-011-15,
RF-011-23; plan 011 §5.1, §5.2.4, §5.5, D-12, D-18).

``WindowManager.geoblender_res_panels`` (:class:`GEOBLENDER_PG_res_panels`) guarda lo que
dibujan N ▸ Proyecto ▸ Cubicaciones, la ventana de una cubicación y la de Materiales y
densidades…: las cubicaciones de la versión activa ya leídas (nombre, revisión, «vigente» o «en
curso», obsoleta), la elegida, sus filas ya presentadas con sus filtros (dominio, rodaja, unidad)
y la columna de materiales en edición. Es una **vista** que se regenera desde el proyecto, nunca
la fuente (nada se lee al dibujar, como la 008 y la 010); vive en ``WindowManager``, que Blender
no guarda en el ``.blend``.

**La columna en edición** (T20; RF-011-11, D-12): :attr:`GEOBLENDER_PG_res_panels.units`, las
unidades de arriba abajo (:class:`GEOBLENDER_PG_res_unit`: su código, D-18, vacío hasta que se
guarda por primera vez; su nombre, clase, papel, estado, base y rejilla de espesores; una
compuesta, sus componentes, :class:`GEOBLENDER_PG_res_component`), las rejillas del proyecto que
se pueden elegir como base o espesor (:attr:`~GEOBLENDER_PG_res_panels.surfaces`, por nombre de
dato) y, ya presentados, la densidad, el K y el porcentaje de cada una con su tipo y su ámbito
(«V01: 1,25 [HIP] · proyecto: sin valor [HIP] sin confirmar») y el umbral de presencia de lo
antrópico. Lo que se edita no se escribe hasta «Guardar la columna» (``bl.ops.res``).
:class:`GEOBLENDER_PG_res_percent` es una fila del diálogo «Porcentajes…».

**Las cubicaciones de la versión activa** (T24; RF-011-18, RF-011-19, RF-011-23):
:attr:`~GEOBLENDER_PG_res_panels.cubications` (:class:`GEOBLENDER_PG_res_cubication`: su nombre,
si reparte por unidades y si tiene toneladas), la elegida
(:attr:`~GEOBLENDER_PG_res_panels.cubication`, su nombre) y el filtro de datos de su tabla
(:attr:`~GEOBLENDER_PG_res_panels.quantities`: todos o las relaciones, D-35). La T25 añade lo
demás de cada una (revisión, «vigente» o «en curso», obsoleta) y sus filas.
:class:`GEOBLENDER_PG_res_moment` es un momento de «Por momentos de extracción…» (su nombre) y
:class:`GEOBLENDER_PG_res_moment_choice`, una fila de su diálogo (una cubicación y si es momento).

Ninguna propiedad es una coordenada ni una cota en ``FloatProperty`` (ADR-0005; la cota
constante de una base, en ``StringProperty``: ``docs/trampas.md`` §1). Las propiedades de las
filas no tienen nombre ni descripción: las dibuja la ventana con sus textos.
"""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

WINDOW_MANAGER_PROPERTY = "geoblender_res_panels"
"""El nombre de la propiedad de ``WindowManager`` (la usan los paneles de la cubicación)."""
_STATIC: set[str] = set()  # ni animable ni nada más

KIND_ITEMS = [
    ("NATURAL", "Natural", ""),
    ("ANTHROPIC", "Anthropic", ""),
    ("COMPOUND", "Compound", ""),
]
"""La clase de una unidad (``reserves.materials.Kind``, en mayúsculas)."""
ROLE_NONE = "NONE"
"""El papel aún sin elegir (una unidad nueva: la columna no se guarda sin él)."""
ROLE_ITEMS = [
    (ROLE_NONE, "Not chosen", ""),
    ("USEFUL", "Useful", ""),
    ("WASTE", "Waste", ""),
]
"""El papel de una unidad o de un componente (``reserves.materials.Role``, en mayúsculas)."""
STATE_ITEMS = [
    ("IN_SITU", "In situ", ""),
    ("LOOSE", "Loose", ""),
]
"""El estado de una unidad (``reserves.materials.State``, en mayúsculas)."""
BASE_SURFACE = "SURFACE"
BASE_ELEVATION = "ELEVATION"
BASE_ITEMS = [
    (BASE_SURFACE, "Surface", ""),
    (BASE_ELEVATION, "Constant elevation", ""),
]
"""De qué es la base de una unidad (D-24): una rejilla del proyecto o una cota constante."""
QUANTITIES_ALL = "ALL"
QUANTITIES_RATIOS = "RATIOS"
QUANTITY_ITEMS = [
    (QUANTITIES_ALL, "All the data", ""),
    (QUANTITIES_RATIOS, "Waste to useful ratios", ""),
]
"""El filtro de datos de la tabla de la cubicación elegida (T24, D-35): todos o solo las
relaciones (``reserves.table.RATIO_QUANTITIES``), el que pone «Ratios…»."""


class GEOBLENDER_PG_res_surface(bpy.types.PropertyGroup):
    """Una rejilla del proyecto que se puede elegir como base o espesor (``name``: su nombre
    de dato, ``gis_dtm_…``)."""


class GEOBLENDER_PG_res_component(bpy.types.PropertyGroup):
    """Un componente de una unidad compuesta en edición (``name``: su nombre visible)."""

    code: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    saved: BoolProperty(options=_STATIC)  # type: ignore[valid-type]
    role: EnumProperty(items=ROLE_ITEMS, default=ROLE_NONE,  # type: ignore[valid-type]
                       options=_STATIC)
    density: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    swell: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    percent: StringProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_res_unit(bpy.types.PropertyGroup):
    """Una unidad de la columna en edición (``name``: su nombre visible; véase el módulo)."""

    code: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    saved: BoolProperty(options=_STATIC)  # type: ignore[valid-type]
    kind: EnumProperty(items=KIND_ITEMS, default="NATURAL",  # type: ignore[valid-type]
                       options=_STATIC)
    role: EnumProperty(items=ROLE_ITEMS, default=ROLE_NONE,  # type: ignore[valid-type]
                       options=_STATIC)
    state: EnumProperty(items=STATE_ITEMS, default="IN_SITU",  # type: ignore[valid-type]
                        options=_STATIC)
    base_kind: EnumProperty(items=BASE_ITEMS, default=BASE_SURFACE,  # type: ignore[valid-type]
                            options=_STATIC)
    base_dataset: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    base_elevation: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    thickness_dataset: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    components: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_res_component, options=_STATIC,
    )
    component_index: IntProperty(options=_STATIC)  # type: ignore[valid-type]
    density: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    swell: StringProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_res_percent(bpy.types.PropertyGroup):
    """El porcentaje de un componente en el diálogo «Porcentajes…» (``name``: el del
    componente; ``value``, lo tecleado)."""

    code: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    value: StringProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_res_moment(bpy.types.PropertyGroup):
    """Un momento de «Por momentos de extracción…» (T24; ``name``: el nombre de su cubicación;
    desde un guion, ``moments=[{"name": …}, …]``: Blender pide todas las propiedades de cada
    elemento, así que no tiene más)."""


class GEOBLENDER_PG_res_moment_choice(bpy.types.PropertyGroup):
    """Una cubicación de la versión activa en el diálogo «Por momentos de extracción…» (T24;
    ``name``: su nombre; ``chosen``: si es uno de los momentos)."""

    chosen: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_res_cubication(bpy.types.PropertyGroup):
    """Una cubicación de la versión activa ya leída (T24; ``name``: su nombre; si reparte por
    unidades y si tiene su tabla de toneladas)."""

    units: BoolProperty(options=_STATIC)  # type: ignore[valid-type]
    tonnage: BoolProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_res_panels(bpy.types.PropertyGroup):
    """Lo que dibujan los paneles de la cubicación (una vista; véase el módulo)."""

    units: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_res_unit, options=_STATIC,
    )
    unit_index: IntProperty(options=_STATIC)  # type: ignore[valid-type]
    surfaces: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_res_surface, options=_STATIC,
    )
    presence: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    materials_project: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    cubications: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_res_cubication, options=_STATIC,
    )
    cubication: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    quantities: EnumProperty(items=QUANTITY_ITEMS,  # type: ignore[valid-type]
                             default=QUANTITIES_ALL, options=_STATIC)


# En orden de registro: cada grupo, después de los que contiene.
classes: tuple[type, ...] = (GEOBLENDER_PG_res_surface, GEOBLENDER_PG_res_component,
                             GEOBLENDER_PG_res_unit, GEOBLENDER_PG_res_percent,
                             GEOBLENDER_PG_res_moment, GEOBLENDER_PG_res_moment_choice,
                             GEOBLENDER_PG_res_cubication, GEOBLENDER_PG_res_panels)


def register() -> None:
    """Pone ``WindowManager.geoblender_res_panels`` (las clases ya están registradas)."""
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_res_panels, options=_STATIC))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_res_panels`` (antes de desregistrar las clases); sin
    ella, nada."""
    if hasattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY):
        delattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY)
