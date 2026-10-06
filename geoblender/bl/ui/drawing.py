# SPDX-License-Identifier: GPL-3.0-or-later
"""Dibujo de un comando del catálogo en cualquier sitio (spec 003; RF-003-06, RF-003-07,
RF-003-08; BS §6 y §7.3).

:func:`draw_command` dibuja un comando con su **única definición** del catálogo (etiqueta,
icono y propiedades fijas), igual en un menú, en el acceso rápido, en un menú circular o
contextual: un operador (de Geoblender o nativo), un menú (submenú ▸), un panel (ventana
emergente) o una propiedad nativa (``tool_settings.use_snap``). Si el comando no está
disponible (BS §7.3) se dibuja **desactivado** dentro de una fila propia o, con «Ocultar lo
no disponible», no se dibuja; si está disponible pero su comprobación dice que no es
aplicable ahora (``commands.not_applicable``: una ranura de vista vacía), también se dibuja
desactivado (RF-003-09). Un acceso cruzado ↗ lleva la marca delante de su etiqueta.

Cada comando lleva su icono propio (``bl/ui/icons.py``) o, si no se puede mostrar (sin
interfaz gráfica, o sin su PNG), su reserva nativa, comprobada en el enumerado de iconos de
la versión instalada (una desconocida no se dibuja; RF-003-22).
"""

from __future__ import annotations

import functools
from typing import Any

import bpy

from ...core.catalog import Command
from . import icons
from .commands import catalog, is_available, not_applicable, text

CROSS_MARK = "↗ "  # acceso cruzado (BS §6)


@functools.cache
def _native_icons() -> frozenset[str]:
    """Los nombres del enumerado de iconos de la versión de Blender en ejecución."""
    parameter = bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"]
    return frozenset(parameter.enum_items.keys())


def native_icon(name: str) -> str:
    """``name`` si es un icono de esta versión de Blender; si no, ``"NONE"``."""
    return name if name in _native_icons() else "NONE"


def icon_kwargs(cmd: Command | None) -> dict[str, Any]:
    """Los argumentos de icono de un comando: su icono propio (``{"icon_value": n}``) o,
    si no se puede mostrar, su reserva nativa (``{"icon": …}``; RF-003-22)."""
    if cmd is None:
        return {"icon": "NONE"}
    return icons.icon_kwargs(cmd.icon, native_icon(cmd.icon_fallback))


def is_menu_id(idname: str) -> bool:
    """Verdadero si ``idname`` es la clase de un menú (``*_MT_*``)."""
    return "_MT_" in idname


def property_owner(context: Any, path: str) -> tuple[Any, str]:
    """(dato, propiedad) de una propiedad nativa del catálogo (``tool_settings.use_snap``
    → ``(scene.tool_settings, "use_snap")``)."""
    owner, _, name = path.rpartition(".")
    if owner == "tool_settings":
        return context.scene.tool_settings, name
    if owner == "space_data":
        return context.space_data, name
    return context.scene, name


def _disabled(layout: Any, inline: bool) -> Any:
    sub = layout.row(align=True) if inline else layout.column()
    sub.enabled = False
    return sub


def draw_command(
    layout: Any,
    key: str,
    *,
    context: Any = None,
    cross: bool = False,
    label: str | None = None,
    icon_only: bool = False,
    hide_unavailable: bool = False,
    inline: bool = False,
    depress: bool | None = None,
) -> Any:
    """Dibuja el comando de ``key`` en ``layout`` y devuelve las propiedades del
    operador dibujado (o ``None``). ``inline``: en una fila de cabecera (la fila
    desactivada se alinea); ``label``: otro texto (el número de Refrescar…)."""
    cmd = catalog().commands.get(key)
    if cmd is None:
        return None
    available = is_available(key)
    if hide_unavailable and not available:
        return None
    shown = "" if icon_only else (text(cmd.label) if label is None else label)
    if cross and shown:
        shown = CROSS_MARK + shown
    applicable = available and not not_applicable(context, cmd)
    target = layout if applicable else _disabled(layout, inline)
    kwargs: dict[str, Any] = {"text": shown, "translate": False, **icon_kwargs(cmd)}
    idname = cmd.idname
    if cmd.kind == "panel":
        target.popover(idname, **kwargs)
        return None
    if cmd.kind == "menu" or (cmd.kind == "native" and is_menu_id(idname)):
        target.menu(idname, **kwargs)
        return None
    if cmd.kind == "property":
        data, name = property_owner(context if context is not None else bpy.context, idname)
        target.prop(data, name, **kwargs)
        return None
    if depress is not None:
        kwargs["depress"] = depress
    properties = target.operator(idname, **kwargs)
    for name, value in cmd.props:
        setattr(properties, name, value)
    return properties
