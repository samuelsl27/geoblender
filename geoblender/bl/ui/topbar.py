# SPDX-License-Identifier: GPL-3.0-or-later
"""Barra superior (spec 003; RF-003-01, RF-003-03, RF-003-04, RF-003-24; ADR-0012; BS §1,
§3 y §4; CW §2, §4 y §5).

**La única sustitución destructiva** de Geoblender: :func:`install` cambia
``TOPBAR_HT_upper_bar.draw_left`` por un envoltorio que guarda el original en su atributo
``_gb_original``, y :func:`restore` vuelve a poner exactamente ese objeto.

- **Modo Geoblender** (el espacio de trabajo de la ventana está marcado): de izquierda a
  derecha, como BS §1, el conmutador [GB|B] con GB hundido, Disposición ▾, los menús de
  Blender plegados (≡), los 11 menús del flujo, Herramientas, Ayuda y el acceso rápido
  del proyecto (AR §2); con el área maximizada, también «Volver», como el original. El
  bloque derecho (``draw_right``) no se toca. Nivel de la barra (BS §3): B (títulos) o, con
  la preferencia «Iconos», D; el nivel automático lo calcula la T18.
- **Modo Blender**: el conmutador con B hundido, «Geoblender ▾» (los 13 menús) y todo lo
  que dibuja el original, con lo que otros complementos le añaden.

**Idempotencia** (RF-003-24; CW §5): si ``draw_left`` ya es un envoltorio de Geoblender
(tiene ``_gb_original``, también uno de un módulo anterior a un ``script.reload``), se
toma el original de ahí y no se envuelve dos veces; si ``draw_left`` es de otro
complemento, se guarda ese como original. Si al restaurar otro complemento ha sustituido
después ``draw_left``, se deja el suyo y el envoltorio, ya inactivo, solo delega en el
original. Un error al dibujar se registra una vez y la barra pasa a la original.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import bpy

from ...core.catalog import Catalog
from ...core.catalog.width import GEOBLENDER_MENU, HELP_MENU, TOOLS_MENU, Level
from ...core.i18n import tr
from . import gate
from .commands import catalog, preference, text
from .drawing import draw_command, icon_kwargs, native_icon

LOGGER = logging.getLogger("geoblender.bl.ui.topbar")
ORIGINAL_ATTR = "_gb_original"  # el draw_left original, en el propio envoltorio
TOGGLE = "geoblender.ui_toggle_mode"
LAYOUTS_PANEL = "GEOBLENDER_PT_ui_layouts"
BLENDER_MENUS = "TOPBAR_MT_editor_menus"
LOGO_TEXT = "GB"  # reserva del logotipo sin icono propio (II §1.4)

DrawLeft = Callable[[Any, Any], None]


class _State:
    def __init__(self) -> None:
        self.wrapper: DrawLeft | None = None  # el envoltorio instalado
        self.failed = False  # ya se registró un error de dibujo


_STATE = _State()


def header() -> type:
    """La clase de la barra superior de Blender."""
    return bpy.types.TOPBAR_HT_upper_bar


def original_of(function: Any) -> Any:
    """El ``draw_left`` original detrás de un envoltorio de Geoblender (o la propia
    función si no lo es)."""
    return getattr(function, ORIGINAL_ATTR, None) or function


def is_wrapper(function: Any) -> bool:
    """Verdadero si ``function`` es un envoltorio de Geoblender (de este módulo o de uno
    anterior a una recarga)."""
    return getattr(function, ORIGINAL_ATTR, None) is not None


def is_installed() -> bool:
    """Verdadero si la barra superior dibuja ahora el envoltorio de este módulo."""
    return _STATE.wrapper is not None and header().draw_left is _STATE.wrapper


# Dibujo -------------------------------------------------------------------------------


def draw_switcher(layout: Any, *, geoblender: bool) -> None:
    """El conmutador [GB|B] (CW §2): dos botones de icono contiguos, el del modo activo
    hundido."""
    row = layout.row(align=True)
    cat = catalog()
    cmd = cat.commands.get(TOGGLE)
    if cmd is not None and cmd.icon_fallback != "NONE":
        logo: dict[str, Any] = {"text": "", **icon_kwargs(cmd)}
    else:
        logo = {"text": LOGO_TEXT}
    properties = row.operator(TOGGLE, depress=geoblender, translate=False, **logo)
    properties.target = "GEOBLENDER"
    properties = row.operator(TOGGLE, text="", icon="BLENDER", depress=not geoblender)
    properties.target = "BLENDER"


def level() -> Level:
    """El nivel de la barra: D con la preferencia «Iconos»; si no, B (BS §3)."""
    return Level.D if preference("topbar_titles", "AUTO") == "ICONS" else Level.B


def _top_menu(layout: Any, cat: Catalog, menu_id: str, *, icon: bool) -> None:
    cmd = cat.commands[menu_id]
    if icon:
        layout.menu(menu_id, text="", **icon_kwargs(cmd))
    else:
        layout.menu(menu_id, text=text(cmd.label), translate=False)


def draw_geoblender(layout: Any, context: Any, current: Level | None = None) -> None:
    """La barra del modo Geoblender en el nivel ``current`` (BS §1 y §3)."""
    cat = catalog()
    current = level() if current is None else current
    draw_switcher(layout, geoblender=True)
    if current is Level.E:
        layout.menu(BLENDER_MENUS, text="", icon="COLLAPSEMENU")
        layout.separator(type="LINE")
        _top_menu(layout, cat, GEOBLENDER_MENU, icon=False)
        return
    draw_command(layout, LAYOUTS_PANEL, context=context, icon_only=True, inline=True)
    layout.separator(type="LINE")
    layout.menu(BLENDER_MENUS, text="", icon="COLLAPSEMENU")
    layout.separator(type="LINE")
    flow = [menu_id for menu_id in cat.top_menus if menu_id not in (TOOLS_MENU, HELP_MENU)]
    row = layout.row(align=False)
    for menu_id in flow:
        _top_menu(row, cat, menu_id, icon=current is Level.D)
    layout.separator(type="LINE")
    compact = current in (Level.C, Level.D)
    _top_menu(layout, cat, TOOLS_MENU, icon=compact)
    _top_menu(layout, cat, HELP_MENU, icon=compact)
    layout.separator(type="LINE")
    row = layout.row(align=True)
    for item in cat.quick_access("project"):
        if item.key in (TOGGLE, LAYOUTS_PANEL):
            continue  # el conmutador y Disposición ▾ van al principio
        draw_command(row, item.key, context=context, icon_only=True, inline=True)
    screen = getattr(context, "screen", None)
    if screen is not None and getattr(screen, "show_fullscreen", False):
        layout.operator("screen.back_to_previous", icon=native_icon("SCREEN_BACK"),
                        text=tr("Back to Previous"), translate=False)


def draw_blender(layout: Any, owner: Any, context: Any, original: DrawLeft) -> None:
    """La barra del modo Blender (BS §4): el conmutador, «Geoblender ▾» y el original."""
    draw_switcher(layout, geoblender=False)
    _top_menu(layout, catalog(), GEOBLENDER_MENU, icon=False)
    original(owner, context)


def _make_wrapper(original: DrawLeft) -> DrawLeft:
    def gb_draw_left(self: Any, context: Any) -> None:
        if _STATE.wrapper is not gb_draw_left:
            original(self, context)  # inactivo (desregistrado o sustituido): delega
            return
        try:
            if gate.is_geoblender_workspace(getattr(context, "workspace", None)):
                draw_geoblender(self.layout, context)
            else:
                draw_blender(self.layout, self, context, original)
        except Exception:  # la barra no se puede quedar vacía
            if not _STATE.failed:
                _STATE.failed = True
                LOGGER.exception("Error al dibujar la barra superior de Geoblender")
            original(self, context)

    setattr(gb_draw_left, ORIGINAL_ATTR, original)
    return gb_draw_left


# Instalación --------------------------------------------------------------------------


def install() -> str:
    """Sustituye ``draw_left`` por el envoltorio (una sola vez, también tras una recarga
    o si otro complemento la sustituyó); devuelve ``"patched"``."""
    cls = header()
    current = cls.draw_left
    if _STATE.wrapper is not None and current is _STATE.wrapper:
        return "patched"
    wrapper = _make_wrapper(original_of(current))
    cls.draw_left = wrapper
    _STATE.wrapper = wrapper
    _STATE.failed = False
    return "patched"


def restore() -> None:
    """Vuelve a poner el ``draw_left`` original guardado en el envoltorio; si otro
    complemento lo sustituyó después, deja el suyo (el envoltorio queda inactivo)."""
    wrapper = _STATE.wrapper
    if wrapper is None:
        return
    cls = header()
    if cls.draw_left is wrapper:
        cls.draw_left = getattr(wrapper, ORIGINAL_ATTR)
    _STATE.wrapper = None
