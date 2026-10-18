# SPDX-License-Identifier: GPL-3.0-or-later
"""Acceso rápido del proyecto y de la vista (spec 003; RF-003-03, RF-003-11; AR §2 y §3;
BS §1 y §3).

- **Del proyecto** (:func:`draw_project`, en la barra superior tras Ayuda; AR §2):
  Guardar, Deshacer, Rehacer, Datos ▾, Refrescar y Versión activa. La versión lleva su
  título en los niveles A y B de la barra y solo su icono en C, D y E (BS §3). El
  conmutador y Disposición ▾, que también son del acceso rápido, los dibuja la barra al
  principio.
- **De la vista** (:func:`draw_view_row`, añadida con ``prepend`` a la fila 2 de cada
  Vista 3D, ``VIEW3D_HT_tool_header``, delante de los ajustes de la herramienta; AR §1 y
  §3): en modo Geoblender y con la preferencia «Fila de acceso rápido de la vista», los 24
  controles de AR §3.1 en su orden, con un separador de línea entre grupos. Si no caben,
  se pliegan con el modelo de ``core.catalog.width.fold_view_quick_access`` (AR §3.3): la
  anchura de la región, menos los ajustes nativos de la herramienta del modo activo
  (``bl.compat.native_tool_settings_px``) y el margen, a la escala de la interfaz; lo
  plegado va al botón «»» (``GEOBLENDER_PT_ui_quick_access_more``, que muestra los de esa
  vista). En los modos de edición (``EDIT_*``) solo quedan los controles con
  ``edit_modes`` (Vista, Sección, Nueva polilínea, Encaje, Plano de trabajo y Objeto
  actual). Vista, Sección, Nueva polilínea y Encaje no se pliegan nunca. En modo Blender
  no se dibuja nada.

Cada control se dibuja con la definición única de su comando (``drawing.draw_command``):
desactivado si no está disponible. Banda y Objeto actual llevan su título hasta el paso 1
del plegado (el estado que mostrarán con R-16 y R-09); los controles con número o
insignia (Refrescar, Comprobar) van en icono hasta que su entrada dé el número. Encaje es
el conmutador nativo (``tool_settings.use_snap``) y su menú ▾.

El número de un control con número (``icon_text``; spec 008, T49): quien lo sabe pone con
:func:`set_count_provider` una función que, con el contexto, da el número o ``None`` (sin
número). El número se dibuja tras el icono del control y abre su segundo comando
(``extra``): el control 7, «Refrescar · obsoletos (n)», con lo obsoleto del proyecto
(RF-008-28), cuyo número abre ``GEOBLENDER_PT_core_stale``. Sin número, el control es solo
su icono, como antes.

El texto y el icono de un control que los cambia (spec 009, T18): quien los sabe pone con
:func:`set_label_provider` una función que, con el contexto, da el texto y los argumentos del
icono, o ``None`` (su título y su icono del catálogo): el control 8, «● V10.r2» con el icono del
estado de la versión activa o «Sin versión» (``bl.ui.version_panels``; RF-009-10). En los niveles
C a E de la barra, solo su icono.

:func:`install` añade la fila a la cabecera una sola vez (también tras una recarga) y
:func:`uninstall` la quita.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import bpy

from ...core.catalog import Catalog, QuickAccessItem
from ...core.catalog.width import (
    FoldResult,
    Level,
    fold_view_quick_access,
    quick_access_available_px,
)
from ...core.i18n import tr
from .. import compat
from . import gate
from .commands import catalog, is_available, preference, preferences, text
from .drawing import draw_command

LOGGER = logging.getLogger("geoblender.bl.ui")

CountProvider = Callable[[Any], "int | None"]
"""El número de un control con número: (contexto) → n, o ``None`` si no tiene número."""
LabelProvider = Callable[[Any], "tuple[str, dict[str, Any]] | None"]
"""El texto y el icono de un control que los cambia (la versión activa, spec 009): (contexto) →
(texto, argumentos del icono), o ``None`` para dibujarlo con los de su comando."""

HEADER = "VIEW3D_HT_tool_header"
MORE_PANEL = "GEOBLENDER_PT_ui_quick_access_more"
TOGGLE = "geoblender.ui_toggle_mode"
LAYOUTS_PANEL = "GEOBLENDER_PT_ui_layouts"
VERSION_PANEL = "GEOBLENDER_PT_core_version"
TITLED_LEVELS = frozenset({Level.A, Level.B})  # la versión con su título (BS §3)
QUICK_ATTR = "_gb_quick_access"  # marca de la función añadida a la cabecera
EXTRA_ICON = "DOWNARROW_HLT"  # el ▾ de un control doble (Encaje)


class _State:
    def __init__(self) -> None:
        self.installed = False
        self.folds: dict[tuple[float, float, str, bool], FoldResult] = {}
        self.folded: dict[int, tuple[str, ...]] = {}  # plegados por área (su puntero)
        # Por ámbito: el catálogo, sus controles en orden y por clave (T46).
        self.items: dict[str, tuple[Catalog, tuple[QuickAccessItem, ...],
                                    dict[str, QuickAccessItem]]] = {}
        self.counts: dict[str, CountProvider] = {}  # clave del control → su número (008)
        self.labels: dict[str, LabelProvider] = {}  # clave del control → su texto (009)


_STATE = _State()


# Número de un control (spec 008, T49) -------------------------------------------------------


def set_count_provider(key: str, provider: CountProvider | None) -> None:
    """Pone quien da el número del control ``key`` (``provider(context)`` → n o ``None``) o,
    con ``None``, lo quita (el control vuelve a ser solo su icono)."""
    if provider is None:
        _STATE.counts.pop(key, None)
    else:
        _STATE.counts[key] = provider


def count_provider(key: str) -> CountProvider | None:
    """Quien da el número del control ``key``, o ``None``."""
    return _STATE.counts.get(key)


def count_of(key: str, context: Any) -> int | None:
    """El número del control ``key`` ahora, o ``None`` si no tiene (o si quien lo da falla:
    la barra se dibuja igual y el error queda en el registro técnico)."""
    provider = _STATE.counts.get(key)
    if provider is None:
        return None
    try:
        found = provider(context)
    except Exception:  # noqa: BLE001 - un número que falla no rompe la barra superior
        LOGGER.exception("Falló el número del control «%s»", key)
        return None
    return None if found is None else int(found)


# Texto de un control (spec 009, T18) -------------------------------------------------------


def set_label_provider(key: str, provider: LabelProvider | None) -> None:
    """Pone quien da el texto y el icono del control ``key`` (``provider(context)`` → (texto,
    argumentos del icono) o ``None``) o, con ``None``, lo quita (el control vuelve a dibujarse
    con su título y su icono del catálogo)."""
    if provider is None:
        _STATE.labels.pop(key, None)
    else:
        _STATE.labels[key] = provider


def label_provider(key: str) -> LabelProvider | None:
    """Quien da el texto y el icono del control ``key``, o ``None``."""
    return _STATE.labels.get(key)


def label_of(key: str, context: Any) -> tuple[str, dict[str, Any]] | None:
    """El texto y el icono del control ``key`` ahora, o ``None`` (sin quien los dé, o si falla:
    la barra se dibuja igual y el error queda en el registro técnico)."""
    provider = _STATE.labels.get(key)
    if provider is None:
        return None
    try:
        return provider(context)
    except Exception:  # noqa: BLE001 - un texto que falla no rompe la barra superior
        LOGGER.exception("Falló el texto del control «%s»", key)
        return None


def _draw_count(layout: Any, context: Any, item: QuickAccessItem) -> None:
    """El número de un control tras su icono, que abre su segundo comando (``extra``): sin
    icono (el del control ya está) y desactivado si ese comando no está disponible."""
    if not item.extra:
        return
    count = count_of(item.key, context)
    cmd = catalog().commands.get(item.extra)
    if count is None or cmd is None:
        return
    sub = layout.row(align=True)
    sub.enabled = is_available(item.extra)
    shown = str(count)
    if cmd.kind == "panel":
        sub.popover(cmd.idname, text=shown, translate=False)
    elif cmd.kind == "menu":
        sub.menu(cmd.idname, text=shown, translate=False)
    else:
        sub.operator(cmd.idname, text=shown, translate=False)


def _scope(scope: str) -> tuple[tuple[QuickAccessItem, ...], dict[str, QuickAccessItem]]:
    cat = catalog()
    cached = _STATE.items.get(scope)
    if cached is None or cached[0] is not cat:
        ordered = cat.quick_access(scope)
        cached = (cat, ordered, {item.key: item for item in ordered})
        _STATE.items[scope] = cached
    return cached[1], cached[2]


def items(scope: str) -> tuple[QuickAccessItem, ...]:
    """Los controles de acceso rápido de ``scope`` (``project`` o ``view``) en su orden,
    ordenados una vez por catálogo: se piden en cada redibujo (spec 003, T46;
    RNF-003-03)."""
    return _scope(scope)[0]


# Barra superior ---------------------------------------------------------------------------


def draw_project(layout: Any, context: Any, level: Level) -> None:
    """El acceso rápido del proyecto en la barra superior (AR §2), en el nivel ``level``."""
    row = layout.row(align=True)
    for item in items("project"):
        if item.key in (TOGGLE, LAYOUTS_PANEL):
            continue  # el conmutador y Disposición ▾ van al principio de la barra
        titled = item.key == VERSION_PANEL and level in TITLED_LEVELS
        shown = label_of(item.key, context)
        if shown is None:
            draw_command(row, item.key, context=context, icon_only=not titled, inline=True)
        else:
            draw_command(row, item.key, context=context, label=shown[0], icon=shown[1],
                         icon_only=not titled, inline=True)
        if item.display == "icon_text":
            _draw_count(row, context, item)


# Fila 2 de la Vista 3D ---------------------------------------------------------------------


def is_edit_mode(mode: str) -> bool:
    """Verdadero en un modo de edición (``EDIT_MESH``, ``EDIT_CURVE``…; AR §3.3)."""
    return mode.startswith("EDIT")


def fold(width_px: float, mode: str, scale: float | None = None) -> FoldResult:
    """Cómo queda la fila 2 en una región de ``width_px`` px reales en el modo de Blender
    ``mode`` (en caché por anchura, escala y modo)."""
    scale = compat.ui_scale() if scale is None else scale
    edit = is_edit_mode(mode)
    key = (width_px, scale, mode, edit)
    found = _STATE.folds.get(key)
    if found is not None:
        return found
    k = compat.quick_access_width_constants()
    available = quick_access_available_px(region_width_px=width_px, scale=scale,
                                          native_px=compat.native_tool_settings_px(mode), k=k)
    found = fold_view_quick_access(available_px=available, scale=scale, edit_mode=edit,
                                   items=items("view"), k=k)
    if len(_STATE.folds) > 256:
        _STATE.folds.clear()
    _STATE.folds[key] = found
    return found


def _area_key(area: Any) -> int:
    pointer = getattr(area, "as_pointer", None)
    return int(pointer()) if callable(pointer) else id(area)


def _draw_item(layout: Any, context: Any, item: QuickAccessItem, *, compact: bool,
               labelled: bool = False) -> None:
    """Un control de la fila 2 (o, con ``labelled``, de la ventana «»», con su título)."""
    if item.key.startswith("tool_settings."):
        row = layout.row(align=True)
        row.prop(context.scene.tool_settings, item.key.partition(".")[2], text="",
                 icon_only=True)
        if item.extra:
            draw_command(row, item.extra, context=context, icon_only=True, inline=True)
        if labelled:
            row.label(text=text(catalog().commands[item.key].label), translate=False)
        return
    titled = labelled or (item.display.endswith("_text") and item.display.startswith("popover")
                          and not compact)
    draw_command(layout, item.key, context=context, icon_only=not titled, inline=not labelled)


def draw_view_row(self: Any, context: Any) -> None:
    """La fila de acceso rápido de la vista, delante de los ajustes de la herramienta
    (RF-003-11; AR §3)."""
    if not gate.is_geoblender_workspace(getattr(context, "workspace", None)):
        return
    if not preference("show_view_quick_access", True):
        return
    region = getattr(context, "region", None)
    width = float(getattr(region, "width", 0) or 0)
    result = fold(width, str(getattr(context, "mode", "OBJECT")))
    _STATE.folded[_area_key(getattr(context, "area", None))] = result.folded
    by_key = _scope("view")[1]
    outer = self.layout.row(align=False)
    group: str | None = None
    row = outer
    for key in result.visible:
        item = by_key[key]
        if item.group != group:  # cada grupo, con sus botones juntos, tras una línea
            if group is not None:
                outer.separator(type="LINE")
            row = outer.row(align=True)
            group = item.group
        _draw_item(row, context, item, compact=key in result.compact)
    if result.more:
        outer.separator(type="LINE")
        outer.popover(MORE_PANEL, text=tr("»"), translate=False)


class GEOBLENDER_PT_ui_quick_access_more(bpy.types.Panel):
    """The quick access controls that do not fit in the row"""

    bl_idname = MORE_PANEL
    bl_label = "More controls"
    bl_translation_context = "Geoblender"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"

    def draw(self, context: Any) -> None:
        folded = _STATE.folded.get(_area_key(getattr(context, "area", None)))
        view_items = items("view")
        if folded is None:  # sin dibujo previo de esa vista: todos los que se pliegan
            folded = tuple(item.key for item in view_items if item.fold_step is not None)
        cat = catalog()
        layout = self.layout.column(align=True)
        group = ""
        for item in view_items:
            if item.key not in folded:
                continue
            if item.group != group:
                if group:
                    layout.separator(type="LINE")
                group = item.group
                title = cat.quick_access_groups.get(group, ("", ""))[0]
                row = layout.row()
                row.active = False
                row.label(text=text(title), translate=False)
            _draw_item(layout, context, item, compact=False, labelled=True)


def toggle_row(context: Any) -> bool:
    """«Mostrar la fila de acceso rápido de la vista» (AR §3.3): si ya se ve (preferencia
    encendida y la fila 2 visible en todas las Vistas 3D de la pantalla), apaga la
    preferencia; si no, la enciende y muestra la fila 2 de esas vistas. Devuelve si queda
    visible."""
    group = preferences()
    if group is None:
        return False
    spaces = [area.spaces.active for area in getattr(context.screen, "areas", ())
              if area.type == "VIEW_3D"]
    shown = bool(group.show_view_quick_access) and all(
        space.show_region_tool_header for space in spaces)
    if shown:
        group.show_view_quick_access = False
        return False
    group.show_view_quick_access = True
    for space in spaces:
        space.show_region_tool_header = True
    return True


# Instalación ------------------------------------------------------------------------------


def _remove_ours() -> None:
    header = getattr(bpy.types, HEADER)
    for function in list(getattr(header.draw, "_draw_funcs", None) or ()):
        if getattr(function, QUICK_ATTR, False):
            header.remove(function)


setattr(draw_view_row, QUICK_ATTR, True)


def install() -> None:
    """Añade la fila de la vista a ``VIEW3D_HT_tool_header`` una sola vez (quita antes la
    de un módulo anterior a una recarga)."""
    _remove_ours()
    getattr(bpy.types, HEADER).prepend(draw_view_row)
    _STATE.installed = True
    _STATE.folds.clear()
    _STATE.items.clear()


def uninstall() -> None:
    """Quita la fila de la vista y olvida el estado por área y los números de los
    controles."""
    _remove_ours()
    _STATE.installed = False
    _STATE.folds.clear()
    _STATE.folded.clear()
    _STATE.items.clear()
    _STATE.counts.clear()
    _STATE.labels.clear()


classes: tuple[type, ...] = (GEOBLENDER_PT_ui_quick_access_more,)
