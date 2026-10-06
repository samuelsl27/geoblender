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
  bloque derecho (``draw_right``) no se toca.
- **Nivel de la barra** (RF-003-10; BS §2.3 y §3; :func:`current_level`): el fijado en las
  preferencias («Texto» = B, «Iconos» = D) o, en automático, el primero de A a E que cabe
  junto al bloque derecho de Blender (``core.catalog.width.choose_topbar_level``) con los
  títulos medidos con ``blf`` en el idioma de Geoblender (:func:`titles_px`, en caché por
  idioma), la escala de la interfaz y las constantes de la versión de Blender
  (``bl.compat``). Cada menú de texto lleva su ancho explícito (``ui_units_x``): en 5.2.1
  un menú de cabecera con icono y texto recorta el título.
- **Modo Blender**: el conmutador con B hundido, «Geoblender ▾» (los 13 menús) y todo lo
  que dibuja el original, con lo que otros complementos le añaden.

**Respaldo de compatibilidad** (RF-003-05; ADR-0012, técnica A; CW §5): si la versión de
Blender no tiene ``draw_left`` con la forma esperada (``bl.compat.topbar_patchable``), no
se sustituye nada: se añade (``append``) a ``TOPBAR_MT_editor_menus`` el conmutador y
«Geoblender ▾» tras la Ayuda de Blender, en los dos modos, y se avisa una vez por sesión
«Interfaz de Geoblender en modo de compatibilidad» (en los avisos del proyecto y en el
registro). :func:`mode` dice cuál está activo.

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

import blf
import bpy

from ...core.catalog import Catalog
from ...core.catalog.width import (
    GEOBLENDER_MENU,
    HELP_MENU,
    TOOLS_MENU,
    Level,
    choose_topbar_level,
    menu_button_px,
)
from ...core.i18n import language, tr, translate
from .. import compat
from ..scene import project_session
from . import gate, quick_access
from .commands import catalog, preference, text
from .drawing import draw_command, icon_kwargs, native_icon

LOGGER = logging.getLogger("geoblender.bl.ui.topbar")
ORIGINAL_ATTR = "_gb_original"  # el draw_left original, en el propio envoltorio
COMPAT_ATTR = "_gb_compat"  # marca de la función añadida en el respaldo de compatibilidad
TOGGLE = "geoblender.ui_toggle_mode"
LAYOUTS_PANEL = "GEOBLENDER_PT_ui_layouts"
BLENDER_MENUS = "TOPBAR_MT_editor_menus"
LOGO_TEXT = "GB"  # reserva del logotipo sin icono propio (II §1.4)
# Niveles fijados por la preferencia «Títulos de la barra» (BS §3); AUTO, el automático.
FORCED_LEVELS: dict[str, Level] = {"TEXT": Level.B, "ICONS": Level.D}
UI_FONT_ID = 0  # la fuente de la interfaz en blf

DrawLeft = Callable[[Any, Any], None]


class _State:
    def __init__(self) -> None:
        self.wrapper: DrawLeft | None = None  # el envoltorio instalado
        self.compat: DrawLeft | None = None  # la función añadida en compatibilidad
        self.failed = False  # ya se registró un error de dibujo
        self.warned = False  # ya se avisó del modo de compatibilidad en esta sesión
        self.titles: dict[str, dict[str, float]] = {}  # anchos blf por idioma (caché)
        self.level_key: tuple[object, ...] | None = None  # última elección (caché)
        self.level: Level = Level.B
        self.override: Level | None = None  # nivel fijado por la medida (T19)


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
    return _STATE.wrapper is not None and getattr(header(), "draw_left", None) is _STATE.wrapper


def is_compat_function(function: Any) -> bool:
    """Verdadero si ``function`` es la que añade el respaldo de compatibilidad (de este
    módulo o de uno anterior a una recarga)."""
    return bool(getattr(function, COMPAT_ATTR, False))


def mode() -> str:
    """``"patched"`` (``draw_left`` sustituido), ``"compat"`` (respaldo) o ``""`` (sin
    instalar)."""
    if _STATE.wrapper is not None:
        return "patched"
    return "compat" if _STATE.compat is not None else ""


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


def titles_px(lang: str) -> dict[str, float]:
    """Ancho ``blf`` a escala 1,0 (fuente de la interfaz, 11 pt) del título de cada menú
    de la barra y de «Geoblender ▾» en el idioma ``lang`` (``"es"`` o ``"en"``), por clase
    del menú (BS §2.3). En caché por idioma."""
    cached = _STATE.titles.get(lang)
    if cached is not None:
        return cached
    cat = catalog()
    blf.size(UI_FONT_ID, compat.UI_FONT_POINTS)
    found = {
        menu_id: float(blf.dimensions(UI_FONT_ID, translate(lang, cat.commands[menu_id].label))[0])
        for menu_id in (*cat.top_menus, GEOBLENDER_MENU)
    }
    _STATE.titles[lang] = found
    return found


def set_override(value: Level | None) -> None:
    """Fija un nivel por encima de las preferencias (``None`` lo quita); solo para medir
    la barra en la GUI (``tools/inblender/measure_topbar.py``, T19)."""
    _STATE.override = value
    _STATE.level_key = None


def forced_level() -> Level | None:
    """El nivel fijado (por la medida o por la preferencia «Títulos de la barra»), o
    ``None`` en automático."""
    if _STATE.override is not None:
        return _STATE.override
    return FORCED_LEVELS.get(str(preference("topbar_titles", "AUTO")))


def current_level(context: Any) -> Level:
    """El nivel de la barra para la región de ``context`` (RF-003-10): el fijado o el
    primero de A a E que cabe en su anchura con la escala y el idioma activos; sin
    anchura conocida, B."""
    forced = forced_level()
    if forced is not None:
        return forced
    width = float(getattr(getattr(context, "region", None), "width", 0) or 0)
    if width <= 0:
        return Level.B
    lang, scale = language(), compat.ui_scale()
    key = (lang, width, scale)
    if key != _STATE.level_key:
        _STATE.level = choose_topbar_level(region_width_px=width, scale=scale,
                                           titles_px=titles_px(lang),
                                           k=compat.topbar_width_constants())
        _STATE.level_key = key
    return _STATE.level


def _top_menu(layout: Any, cat: Catalog, menu_id: str, *, icon: bool,
              title: bool = True) -> None:
    """Un menú de la barra: solo su icono, su título o (nivel A) los dos; con título, con
    su ancho explícito (``ui_units_x``) para que no se recorte (BS §3)."""
    cmd = cat.commands[menu_id]
    if not title:
        layout.menu(menu_id, text="", **icon_kwargs(cmd))
        return
    row = layout.row(align=True)
    row.ui_units_x = menu_button_px(titles_px(language())[menu_id], icon=icon,
                                    k=compat.topbar_width_constants()) / compat.UI_UNIT_PX
    kwargs = icon_kwargs(cmd) if icon else {}
    row.menu(menu_id, text=text(cmd.label), translate=False, **kwargs)


def draw_geoblender(layout: Any, context: Any, current: Level | None = None) -> None:
    """La barra del modo Geoblender en el nivel ``current`` (por defecto, el de
    :func:`current_level`; BS §1 y §3)."""
    cat = catalog()
    current = current_level(context) if current is None else current
    draw_switcher(layout, geoblender=True)
    draw_command(layout, LAYOUTS_PANEL, context=context, icon_only=True, inline=True)
    layout.separator(type="LINE")
    layout.menu(BLENDER_MENUS, text="", icon="COLLAPSEMENU")
    layout.separator(type="LINE")
    if current is Level.E:
        _top_menu(layout, cat, GEOBLENDER_MENU, icon=False)
    else:
        flow = [menu_id for menu_id in cat.top_menus if menu_id not in (TOOLS_MENU, HELP_MENU)]
        row = layout.row(align=False)
        for menu_id in flow:
            _top_menu(row, cat, menu_id, icon=current is Level.A, title=current is not Level.D)
        layout.separator(type="LINE")
        compact = current in (Level.C, Level.D)
        _top_menu(layout, cat, TOOLS_MENU, icon=current is Level.A, title=not compact)
        _top_menu(layout, cat, HELP_MENU, icon=False, title=not compact)
    layout.separator(type="LINE")
    quick_access.draw_project(layout, context, current)
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


def gb_compat_menus(self: Any, context: Any) -> None:
    """Lo que añade el respaldo de compatibilidad tras la Ayuda de Blender: el conmutador
    y «Geoblender ▾» (RF-003-05)."""
    layout = self.layout
    draw_switcher(
        layout, geoblender=gate.is_geoblender_workspace(getattr(context, "workspace", None))
    )
    _top_menu(layout, catalog(), GEOBLENDER_MENU, icon=False)


setattr(gb_compat_menus, COMPAT_ATTR, True)


# Instalación --------------------------------------------------------------------------


def _remove_compat_functions() -> None:
    menus = getattr(bpy.types, compat.TOPBAR_MENUS)
    for function in list(getattr(menus.draw, "_draw_funcs", None) or ()):
        if is_compat_function(function):
            menus.remove(function)


def _install_compat() -> str:
    _remove_compat_functions()  # también la de un módulo anterior a una recarga
    getattr(bpy.types, compat.TOPBAR_MENUS).append(gb_compat_menus)
    _STATE.compat = gb_compat_menus
    if not _STATE.warned:
        _STATE.warned = True
        project_session.notify(tr("Geoblender interface in compatibility mode"))
    return "compat"


def install() -> str:
    """Sustituye ``draw_left`` por el envoltorio (una sola vez, también tras una recarga
    o si otro complemento la sustituyó) y devuelve ``"patched"``; si la barra no tiene la
    forma esperada, instala el respaldo de compatibilidad y devuelve ``"compat"``."""
    if _STATE.compat is not None or not compat.topbar_patchable(header()):
        return _install_compat()
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
    """Vuelve a poner el ``draw_left`` original guardado en el envoltorio (si otro
    complemento lo sustituyó después, deja el suyo y el envoltorio queda inactivo) o
    quita lo añadido por el respaldo de compatibilidad."""
    if _STATE.compat is not None:
        _remove_compat_functions()
        _STATE.compat = None
    wrapper = _STATE.wrapper
    if wrapper is None:
        return
    cls = header()
    if getattr(cls, "draw_left", None) is wrapper:
        cls.draw_left = getattr(wrapper, ORIGINAL_ATTR)
    _STATE.wrapper = None
