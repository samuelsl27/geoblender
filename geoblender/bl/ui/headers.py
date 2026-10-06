# SPDX-License-Identifier: GPL-3.0-or-later
"""Menú del tipo activo en la fila 1 de la Vista 3D y en el clic derecho (spec 003;
RF-003-17; PC §1, §3 y §4; CW §4).

- **Fila 1** (:func:`draw_row1`, añadida con ``append`` a ``VIEW3D_MT_editor_menus``, tras
  los menús nativos; si el usuario pliega los menús de la cabecera, queda dentro del menú
  plegado): «Herramientas ▾», el menú «<Tipo> ▾» del contexto de esa vista
  (``context.context_kind``: el fijado con la chincheta, «Selección (n) ▾» con varios
  tipos o el del objeto activo), sus dos iconos de acción y la chincheta. Sin tipo, solo
  «Herramientas ▾». Si no cabe (PC §1: unos 795 px de lo nativo y 262 de lo de
  Geoblender, ``bl.compat.view3d_row1_widths``), desaparecen primero la chincheta y los dos
  iconos y después Herramientas pasa a icono.
- **Clic derecho** (:func:`draw_context_menu`, añadida a ``VIEW3D_MT_object_context_menu``,
  ``VIEW3D_MT_edit_curve_context_menu`` y ``OUTLINER_MT_object``): «Geoblender · <Tipo> ▸»
  con el mismo menú; en ``OUTLINER_MT_collection``, el de la versión si la colección activa
  es la de una versión (:func:`draw_collection_menu`).
- **Mayús+Alt+B** (``geoblender.ui_call_context_menu``, en ``bl/ops/ui.py``): el mismo
  menú bajo el cursor (:func:`context_menu_id`; sin tipo, «Herramientas»).

Todo es el mismo menú generado del catálogo (``contexts.toml``; ``bl/ui/menus.py``), así
que el contenido es igual en los tres sitios. En modo Blender no se dibuja nada.
:func:`install` lo añade una sola vez (también tras una recarga) y :func:`uninstall` lo
quita.
"""

from __future__ import annotations

from typing import Any

import bpy

from ...core.catalog import ContextSpec
from ...core.i18n import tr
from .. import compat
from . import context as ui_context
from . import gate
from .commands import catalog, text
from .drawing import draw_command

TOOLS_MENU = "GEOBLENDER_MT_ui_tools"
PIN = "geoblender.ui_toggle_context_pin"
ROW1_TARGET = "VIEW3D_MT_editor_menus"
OBJECT_MENUS = (
    "VIEW3D_MT_object_context_menu",
    "VIEW3D_MT_edit_curve_context_menu",
    "OUTLINER_MT_object",
)
COLLECTION_MENU = "OUTLINER_MT_collection"
OURS_ATTR = "_gb_headers"  # marca de las funciones añadidas


def context_spec(context: Any) -> tuple[ContextSpec | None, int]:
    """El menú contextual de la vista de ``context`` y cuántos elementos abarca."""
    kind, count = ui_context.context_kind(context)
    if not kind:
        return None, 0
    return catalog().contexts.get(kind), count


def menu_label(spec: ContextSpec, count: int) -> str:
    """«Sondeos», «Selección (3)»… en el idioma de Geoblender."""
    if spec.kind == ui_context.SELECTION_KIND:
        return tr("Selection ({n})", n=count)
    return text(catalog().commands[spec.id].label)


def context_menu_id(context: Any) -> str:
    """El menú que abre Mayús+Alt+B: el del contexto o, sin tipo, «Herramientas»."""
    spec, _count = context_spec(context)
    return spec.id if spec is not None else TOOLS_MENU


def row1_level(context: Any) -> int:
    """Cuánto de la fila 1 cabe (PC §1): 2, todo; 1, sin la chincheta ni los iconos;
    0, además Herramientas en icono."""
    width = float(getattr(getattr(context, "region", None), "width", 0) or 0)
    if width <= 0:
        return 2
    widths = compat.view3d_row1_widths()
    available = width / compat.ui_scale() - widths["native"]
    if available >= widths["full"]:
        return 2
    if available >= widths["full"] - widths["pin_and_icons"]:
        return 1
    return 0


def _draw_icon(layout: Any, context: Any, item: Any) -> None:
    if item.key is not None:
        draw_command(layout, item.key, context=context, icon_only=True, inline=True)
    elif item.placeholder is not None:
        row = layout.row(align=True)
        row.enabled = False
        row.label(text=text(item.placeholder[0]), translate=False)


def draw_row1(self: Any, context: Any) -> None:
    """La parte de Geoblender de la fila 1 de la Vista 3D (RF-003-17; PC §1)."""
    if not gate.is_geoblender_workspace(getattr(context, "workspace", None)):
        return
    layout = self.layout
    level = row1_level(context)
    tools = catalog().commands[TOOLS_MENU]
    if level == 0:
        draw_command(layout, TOOLS_MENU, context=context, icon_only=True, inline=True)
    else:
        layout.menu(TOOLS_MENU, text=text(tools.label), translate=False)
    spec, count = context_spec(context)
    if spec is None:
        return
    layout.menu(spec.id, text=menu_label(spec, count), translate=False)
    if level < 2:
        return
    row = layout.row(align=True)
    for item in spec.icons:
        _draw_icon(row, context, item)
    pinned = ui_context.pinned(context) is not None
    layout.operator(PIN, text="", icon="PINNED" if pinned else "UNPINNED", depress=pinned)


def draw_context_menu(self: Any, context: Any) -> None:
    """«Geoblender · <Tipo> ▸» al final del clic derecho de la Vista 3D y del Outliner."""
    if not gate.is_geoblender_workspace(getattr(context, "workspace", None)):
        return
    spec, count = context_spec(context)
    if spec is None:
        return
    layout = self.layout
    layout.separator()
    layout.menu(spec.id, text=tr("Geoblender · {kind}", kind=menu_label(spec, count)),
                translate=False)


def _active_collection(context: Any) -> Any:
    collection = getattr(context, "collection", None)
    if collection is None:
        view_layer = getattr(context, "view_layer", None)
        layer = getattr(view_layer, "active_layer_collection", None)
        collection = getattr(layer, "collection", None)
    return collection


def draw_collection_menu(self: Any, context: Any) -> None:
    """«Geoblender · Versión ▸» en el clic derecho de una colección del Outliner que es la
    de una versión (PC §3.13)."""
    if not gate.is_geoblender_workspace(getattr(context, "workspace", None)):
        return
    kind = ui_context.collection_kind(_active_collection(context))
    spec = catalog().contexts.get(kind) if kind else None
    if spec is None:
        return
    layout = self.layout
    layout.separator()
    layout.menu(spec.id, text=tr("Geoblender · {kind}", kind=menu_label(spec, 1)),
                translate=False)


for _function in (draw_row1, draw_context_menu, draw_collection_menu):
    setattr(_function, OURS_ATTR, True)


# Instalación ------------------------------------------------------------------------------


def _targets() -> tuple[tuple[str, Any], ...]:
    return (
        (ROW1_TARGET, draw_row1),
        *((name, draw_context_menu) for name in OBJECT_MENUS),
        (COLLECTION_MENU, draw_collection_menu),
    )


def _remove_ours() -> None:
    for name, _function in _targets():
        owner = getattr(bpy.types, name, None)
        if owner is None:
            continue
        for function in list(getattr(owner.draw, "_draw_funcs", None) or ()):
            if getattr(function, OURS_ATTR, False):
                owner.remove(function)


def install() -> None:
    """Añade la fila 1 y el clic derecho una sola vez (quita antes los de un módulo
    anterior a una recarga)."""
    _remove_ours()
    for name, function in _targets():
        owner = getattr(bpy.types, name, None)
        if owner is not None:
            owner.append(function)


def uninstall() -> None:
    """Quita lo añadido a la fila 1 y al clic derecho."""
    _remove_ours()
