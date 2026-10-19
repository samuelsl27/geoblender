# SPDX-License-Identifier: GPL-3.0-or-later
"""Las filas de los paneles de la vista regenerable (spec 010; RF-010-06, RF-010-07, RF-010-08;
plan 010 §5.1 y §5.2).

``WindowManager.geoblender_view_panels`` (:class:`GEOBLENDER_PG_core_view_panels`) guarda lo
que dibujan N ▸ Proyecto ▸ Elemento activo e Inventario y la ventana de «Cifras de la
selección»: filas de texto ya presentado, como las de la procedencia (``bl/props/provenance.py``;
plan 008 D16). Es una **vista** que se regenera desde el proyecto, nunca la fuente; vive en
``WindowManager``, que Blender no guarda en el ``.blend`` de ``scenes/`` (spec 002 D-11). No se
llama ``geoblender_views``: ese nombre ya es ``Scene.geoblender_views``, las vistas guardadas de la
003 (``bl.props.ui.VIEWS_PROPERTY``).

Spec 010, T07: el grupo, aún sin filas (las ponen los paneles de la T14 a la T16).

Spec 010, T14 (RF-010-06; plan A6, D-16): la ficha de «Elemento activo» (``card``, filas
:class:`GEOBLENDER_PG_core_card_row`), del dato ``card_uid`` del proyecto ``card_project``
(``card_found`` falso si el proyecto ya no lo tiene), que ``bl.ui.view_panels`` lee al cambiar
el objeto activo o el proyecto. Las propiedades de las filas no tienen nombre ni descripción: no
se dibujan con los suyos (como las de la procedencia). Ninguna se anima.

Spec 010, T15 (RF-010-07; plan A7, D-15): el inventario (``inventory``, filas
:class:`GEOBLENDER_PG_core_inventory_row` con los valores del proyecto, que el panel presenta en
el idioma de Geoblender), la fila elegida (``inventory_index``), de qué proyecto son
(``inventory_project``), cuántas cumplen el filtro y cuántas no caben («… y n más»), y sus
filtros, enumerados fijos (los identificadores son los de ``core.views.inventory``; el tipo
«Entradas» es la categoría; el de versión, dinámico desde la 009): cambiar uno vuelve a filtrar
lo ya leído, sin leer el proyecto (``bl.ui.view_panels.inventory_filtered``); el texto, a cada
tecla.

Spec 010, T16 (RF-010-08; plan A8, D-17): las filas de la ventana de «Cifras de la selección»
(``selection``, como las de la ficha: el nombre de cada dato, cada cifra con su insignia y sus
marcas, o que no tiene), leídas del proyecto al pedir la orden, y de qué proyecto son
(``selection_project``).

Spec 009, T25 (RF-009-20, RF-009-30, RF-009-09; plan 009 A11): las filas del inventario son
también de versiones y de revisiones, con sus marcas («alterada» y «en curso»), y el filtro de
versión es un enumerado **dinámico** (``bl.ui.view_panels.version_filter_items``): «Todas»,
«Sin versión» y las versiones del inventario ya leído (su uid; nada se lee al abrirlo), cada
una con el número de su código para que lo elegido siga siendo la misma versión al leer otra
vez (una versión no se borra nunca, RF-009-12).
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

# Nombre de la propiedad de WindowManager (la usan los paneles de la vista, spec 010).
WINDOW_MANAGER_PROPERTY = "geoblender_view_panels"
_STATIC: set[str] = set()  # ni animable ni nada más

# Filtros del inventario (T15; core.views.inventory: KindFilter, StatusFilter, PresenceFilter y
# VERSION_NONE). El tipo «Entradas» es la categoría INPUT; los demás tipos, los de los datos.
INVENTORY_INPUT = "INPUT"
INVENTORY_KIND_ITEMS = [
    ("ALL", "Everything", ""),
    (INVENTORY_INPUT, "Inputs", ""),
    ("RASTER", "Grids", ""),
    ("MESH", "Meshes", ""),
    ("VECTOR", "Vector data", ""),
    ("TABLE", "Tables", ""),
    ("DRILLHOLES", "Drillholes", ""),
    ("OTHER", "Others", ""),
]
INVENTORY_STATUS_ITEMS = [
    ("LIVE", "Live items", ""),
    ("CURRENT", "Current items", ""),
    ("STALE", "Stale items", ""),
    ("INPUT_CHANGED", "Changed input", ""),
    ("UNUSABLE", "Unusable items", ""),
    ("HISTORY", "Project history", ""),
    ("ALL", "Any status", ""),
]
INVENTORY_VERSION_ALL = "ALL"
"""El filtro de versión que no filtra (el primero del enumerado dinámico, su número 0)."""
INVENTORY_PRESENCE_ITEMS = [
    ("ALL", "Everything", ""),
    ("IN", "In the scene", ""),
    ("OUT", "Not in the scene", ""),
]


def _inventory_filtered(_view: object, _context: object) -> None:
    """Cambió un filtro del inventario: se vuelve a filtrar lo leído (sin leer el proyecto)."""
    from ..ui import view_panels  # al usarlo: bl/ui importa bl/props

    view_panels.inventory_filtered()


def _version_items(view: object, context: object) -> list[tuple[str, str, str, int]]:
    """Los elementos del filtro de versión (spec 009, T25): los de
    ``bl.ui.view_panels.version_filter_items``, con lo ya leído del inventario."""
    from ..ui import view_panels  # al usarlo: bl/ui importa bl/props

    return view_panels.version_filter_items(view, context)


class GEOBLENDER_PG_core_card_row(bpy.types.PropertyGroup):
    """Una línea de la ficha de «Elemento activo» (spec 010, RF-010-06) o de la ventana de
    «Cifras de la selección» (RF-010-08), ya presentada: ``kind`` dice cómo se dibuja
    (``bl.ui.view_panels``: su nombre, un dato de la ficha, el título de un apartado, una
    entrada o un derivado, una cifra, sus marcas, «ninguno», un aviso o el lugar de «al día»,
    que se dibuja con el objeto activo), su texto en el idioma de Geoblender al leerla, su
    icono, si va en alerta y el uid de lo que nombra (una entrada, un dato o una cifra)."""

    kind: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    text: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    icon: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    alert: BoolProperty(options=_STATIC)  # type: ignore[valid-type]
    uid: StringProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_inventory_row(bpy.types.PropertyGroup):
    """Una fila del inventario (spec 010, RF-010-07; ``core.views.inventory.InventoryItem``):
    su nombre (``name``, el de todo grupo), su categoría («INPUT», «DATASET» y, con la spec
    009, «VERSION» o «REVISION»), su uid, su módulo, su tipo, su estado como lo guarda el
    proyecto («current»…; el de una versión, «VIGENTE»…; el de una revisión, «open»…), su
    versión (su código; vacía, «—»: lo del proyecto), si está en la escena, si está obsoleto,
    si depende de una entrada cambiada, si se puede cargar en la vista y, de una revisión,
    si está alterada (RF-009-09) y si está en curso, la abierta (RF-009-20)."""

    category: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    uid: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    module: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    kind: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    status: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    version: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    in_scene: BoolProperty(options=_STATIC)  # type: ignore[valid-type]
    stale: BoolProperty(options=_STATIC)  # type: ignore[valid-type]
    input_changed: BoolProperty(options=_STATIC)  # type: ignore[valid-type]
    loadable: BoolProperty(options=_STATIC)  # type: ignore[valid-type]
    altered: BoolProperty(options=_STATIC)  # type: ignore[valid-type]
    in_progress: BoolProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_view_panels(bpy.types.PropertyGroup):
    """Lo que dibujan los paneles de la vista regenerable (spec 010): una vista del proyecto,
    regenerada desde él."""

    # Elemento activo (T14; RF-010-06).
    card: CollectionProperty(type=GEOBLENDER_PG_core_card_row,  # type: ignore[valid-type]
                             options=_STATIC)
    card_uid: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    card_project: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    card_found: BoolProperty(options=_STATIC)  # type: ignore[valid-type]

    # Inventario (T15; RF-010-07).
    inventory: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_inventory_row, options=_STATIC, name="Inventory",
        description="What is registered in the project, loaded in the view or not",
    )
    inventory_index: IntProperty(  # type: ignore[valid-type]
        default=0, min=0, options=_STATIC, name="Chosen row",
        description="Row whose orders are shown below the list",
    )
    inventory_project: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    inventory_total: IntProperty(default=0, min=0, options=_STATIC)  # type: ignore[valid-type]
    inventory_more: IntProperty(default=0, min=0, options=_STATIC)  # type: ignore[valid-type]
    inventory_text: StringProperty(  # type: ignore[valid-type]
        default="", options={"TEXTEDIT_UPDATE"}, update=_inventory_filtered, name="Text",
        description="Words that the name has to contain, without telling capitals or accents "
                    "apart",
    )
    inventory_kind: EnumProperty(  # type: ignore[valid-type]
        items=INVENTORY_KIND_ITEMS, default="ALL", options=_STATIC,
        update=_inventory_filtered, name="Type",
        description="Only the inputs, or the data of this type",
    )
    inventory_status: EnumProperty(  # type: ignore[valid-type]
        items=INVENTORY_STATUS_ITEMS, default="LIVE", options=_STATIC,
        update=_inventory_filtered, name="Status", description="Only what has this status",
    )
    inventory_version: EnumProperty(  # type: ignore[valid-type]
        items=_version_items, default=0, options=_STATIC,
        update=_inventory_filtered, name="Version", description="Only what has this version",
    )
    inventory_presence: EnumProperty(  # type: ignore[valid-type]
        items=INVENTORY_PRESENCE_ITEMS, default="ALL", options=_STATIC,
        update=_inventory_filtered, name="In the scene",
        description="Only what is loaded in the scene, or only what is not",
    )

    # Cifras de la selección (T16; RF-010-08).
    selection: CollectionProperty(type=GEOBLENDER_PG_core_card_row,  # type: ignore[valid-type]
                                  options=_STATIC)
    selection_project: StringProperty(options=_STATIC)  # type: ignore[valid-type]


# En orden de registro (las filas, antes del grupo que las usa).
classes: tuple[type, ...] = (GEOBLENDER_PG_core_card_row, GEOBLENDER_PG_core_inventory_row,
                             GEOBLENDER_PG_core_view_panels)


def register() -> None:
    """Pone ``WindowManager.geoblender_view_panels`` (las clases ya están registradas)."""
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_core_view_panels, options=_STATIC))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_view_panels`` (antes de desregistrar las clases); sin
    ella, nada."""
    if hasattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY):
        delattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY)
