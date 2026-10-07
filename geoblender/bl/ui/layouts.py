# SPDX-License-Identifier: GPL-3.0-or-later
"""Disposiciones de Geoblender (spec 003; RF-003-16; CW §6.2 y §6.4; BS §1, n.º 2, y §8.12,
Disposición ▸).

Una disposición es un espacio de trabajo marcado como Geoblender (``geoblender_mode``):
todas comparten la barra superior, el acceso rápido y los atajos, y solo cambia el reparto
de áreas. Las de ``layouts.toml`` están en ``resources/geoblender_ui.blend`` y se añaden al
fichero **bajo demanda**; las de una entrada aún no entregada (R-62, R-57) se ven
desactivadas con su «Disponible en …» (lo dice ``commands.is_available`` de cada variante
``geoblender.ui_add_layout?layout=…``).

- :func:`activate_layout` (``geoblender.ui_add_layout``): activa la disposición en la
  ventana y, si el fichero no la tiene, la anexa antes desde los recursos (sin dejar la
  biblioteca en el fichero). La asignación es diferida, como al conmutar
  (``switcher.activate``).
- :func:`remove` («Quitar esta disposición», ``geoblender.ui_remove_layout``): borra solo
  ese espacio de trabajo, nunca datos; la principal no se quita. Si una ventana la usa,
  pasa antes a la principal (diferido) y el espacio se borra cuando el cambio se ha
  aplicado (temporizador :func:`check_pending`).
- :func:`restore` («Restaurar la disposición», ``geoblender.ui_restore_layout``): anexa
  otra vez la de los recursos, con su reparto original, y la deja con el mismo nombre en
  lugar de la desordenada (en una ventana que la usa, también tras el cambio diferido).
- :class:`GEOBLENDER_PT_ui_layouts`, la ventana **Disposición ▾** de la barra superior
  (CW §6.4): las disposiciones del fichero (un clic activa una; la activa, hundida), las
  que faltan, Quitar, Restaurar, «Mostrar la fila de acceso rápido de la vista» y
  «Mostrar la barra de estado minera».

Lo que la ventana de la orden no permite («No aplicable ahora», RF-003-09: quitar la
principal o un espacio de Blender, restaurar uno que no está en los recursos) lo dicen
:func:`remove_check` y :func:`restore_check`, que se registran como comprobaciones de
``commands`` (los menús los dibujan desactivados). :func:`unregister` retira el
temporizador, el manejador ``load_post`` y lo pendiente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import bpy
from bpy.app.handlers import persistent

from ...core.catalog import LayoutSpec
from ...core.catalog.schema import make_key
from ...core.i18n import tr
from . import gate, switcher
from .commands import catalog, preferences, register_check, unregister_check
from .drawing import draw_command

PANEL = "GEOBLENDER_PT_ui_layouts"
ADD = "geoblender.ui_add_layout"
REMOVE = "geoblender.ui_remove_layout"
RESTORE = "geoblender.ui_restore_layout"
TOGGLE_ROW = "geoblender.ui_toggle_quick_access_row"
CHECK_INTERVAL_S = 0.05
CHECK_ATTEMPTS = 40  # unos 2 s: si la ventana no cambia, el espacio se queda


@dataclass
class _Pending:
    """Un espacio que se borra (o se sustituye por ``replacement``) cuando ninguna ventana
    lo usa."""

    workspace: Any
    name: str
    replacement: Any = None


class _State:
    def __init__(self) -> None:
        self.pending: list[_Pending] = []
        self.attempts = 0


_STATE = _State()


# Lo que dice el catálogo -----------------------------------------------------------------


def specs() -> tuple[LayoutSpec, ...]:
    """Las disposiciones del catálogo, en su orden (``layouts.toml``)."""
    return catalog().layouts


def spec(layout_id: str) -> LayoutSpec | None:
    """La disposición del catálogo con ese ``id`` (``MAIN``, ``DATA``…)."""
    return next((item for item in specs() if item.id == layout_id), None)


def spec_for_workspace(name: str) -> LayoutSpec | None:
    """La disposición del catálogo cuyo espacio de trabajo se llama ``name``."""
    return next((item for item in specs() if item.workspace == name), None)


def add_key(layout_id: str) -> str:
    """La clave del catálogo de «activar o añadir» esa disposición."""
    return make_key(ADD, {"layout": layout_id})


def main_name() -> str:
    """El nombre del espacio de la disposición principal."""
    return switcher.main_workspace()


# Estado del fichero ----------------------------------------------------------------------


def present() -> list[Any]:
    """Los espacios de trabajo de Geoblender del fichero: los del catálogo en su orden y,
    después, los demás marcados (copias con otro nombre), por nombre."""
    marked = [ws for ws in bpy.data.workspaces if gate.is_geoblender_workspace(ws)]
    order = {item.workspace: index for index, item in enumerate(specs())}
    return sorted(marked, key=lambda ws: (order.get(ws.name, len(order)), ws.name))


def windows_using(workspace: Any) -> list[Any]:
    """Las ventanas cuyo espacio de trabajo activo es ``workspace``."""
    return [window for window in bpy.context.window_manager.windows
            if window.workspace is not None and window.workspace == workspace]


def context_workspace(context: Any) -> Any:
    """El espacio de trabajo de la ventana de ``context`` («esta disposición»)."""
    context = bpy.context if context is None else context
    workspace = getattr(context, "workspace", None)
    if workspace is None:
        window = getattr(context, "window", None)
        workspace = getattr(window, "workspace", None)
    return workspace


def target_workspace(context: Any, name: str = "") -> Any:
    """El espacio con ese nombre o, sin nombre, el de la ventana de ``context``."""
    if name:
        return bpy.data.workspaces.get(name)
    return context_workspace(context)


# Activar o añadir ------------------------------------------------------------------------


def activate_layout(window: Any, layout_id: str) -> tuple[str, bool]:
    """Activa en ``window`` la disposición ``layout_id``, anexándola antes desde los
    recursos si el fichero no la tiene; devuelve su nombre y si hubo que anexarla."""
    item = spec(layout_id)
    if item is None:
        raise ValueError(f"disposición desconocida «{layout_id}»")
    workspace = bpy.data.workspaces.get(item.workspace)
    appended = workspace is None
    if workspace is None:
        workspace = switcher.append_workspace(window, item.workspace)
    switcher.activate(window, workspace)
    return workspace.name, appended


# Quitar y restaurar ----------------------------------------------------------------------


def remove_problem(workspace: Any) -> str:
    """"" si ``workspace`` se puede quitar; si no, por qué (sin espacio, uno de Blender o
    la principal)."""
    if workspace is None or not gate.is_geoblender_workspace(workspace):
        return tr("This window is not in a Geoblender layout")
    if getattr(workspace, "name", "") == main_name():
        return tr("The main layout cannot be removed")
    return ""


def restore_problem(workspace: Any) -> str:
    """"" si ``workspace`` se puede restaurar desde los recursos; si no, por qué."""
    if workspace is None or not gate.is_geoblender_workspace(workspace):
        return tr("This window is not in a Geoblender layout")
    name = str(getattr(workspace, "name", ""))
    if spec_for_workspace(name) is None:
        return tr("«{name}» is not a layout of the Geoblender resources", name=name)
    return ""


def remove_check(context: Any, _cmd: Any = None) -> str:
    """«No aplicable ahora» de «Quitar esta disposición» (RF-003-09)."""
    return remove_problem(context_workspace(context))


def restore_check(context: Any, _cmd: Any = None) -> str:
    """«No aplicable ahora» de «Restaurar la disposición» (RF-003-09)."""
    return restore_problem(context_workspace(context))


def _main_workspace(window: Any) -> Any:
    main = bpy.data.workspaces.get(main_name())
    return main if main is not None else switcher.append_workspace(window, main_name())


def remove(workspace: Any) -> bool:
    """Quita ``workspace`` (nunca datos; :func:`remove_problem` dice si se puede).
    Devuelve verdadero si ya está borrado y falso si queda pendiente de que las ventanas
    que lo usan pasen a la principal."""
    users = windows_using(workspace)
    if not users:
        bpy.data.batch_remove([workspace])
        return True
    for window in users:
        switcher.activate(window, _main_workspace(window))
    _STATE.pending.append(_Pending(workspace, workspace.name))
    _schedule()
    return False


def restore(workspace: Any) -> bool:
    """Vuelve a anexar la disposición de ``workspace`` desde los recursos y la deja con
    su nombre en lugar de la desordenada. Devuelve verdadero si ya está hecho y falso si
    queda pendiente del cambio diferido de las ventanas que la usan."""
    name = workspace.name
    fresh = switcher.load_workspace(name)
    users = windows_using(workspace)
    if not users:
        _replace(workspace, fresh, name)
        return True
    for window in users:
        switcher.activate(window, fresh)
    _STATE.pending.append(_Pending(workspace, name, fresh))
    _schedule()
    return False


def _replace(old: Any, new: Any, name: str) -> None:
    bpy.data.batch_remove([old])
    if new is not None:
        new.name = name


def pending_names() -> tuple[str, ...]:
    """Los espacios que esperan a que ninguna ventana los use para borrarse."""
    return tuple(item.name for item in _STATE.pending)


def _alive(workspace: Any) -> bool:
    try:
        return workspace is not None and workspace.name is not None
    except ReferenceError:
        return False


def check_pending() -> float | None:
    """Temporizador: borra (o sustituye) los espacios pendientes que ya no usa ninguna
    ventana; vuelve a mirar mientras quede alguno, unos 2 s como mucho."""
    waiting: list[_Pending] = []
    for item in _STATE.pending:
        if not _alive(item.workspace):
            continue  # ya no está (lo quitó otra orden o se abrió otro fichero)
        if windows_using(item.workspace):
            waiting.append(item)
            continue
        _replace(item.workspace, item.replacement if _alive(item.replacement) else None,
                 item.name)
    _STATE.pending = waiting
    _STATE.attempts += 1
    if waiting and _STATE.attempts < CHECK_ATTEMPTS:
        return CHECK_INTERVAL_S
    _STATE.pending = []
    _STATE.attempts = 0
    return None


def _schedule() -> None:
    _STATE.attempts = 0
    if not bpy.app.timers.is_registered(check_pending):
        bpy.app.timers.register(check_pending, first_interval=0.0)


@persistent
def on_load_post(*_args: Any) -> None:
    """Al abrir otro fichero, lo pendiente ya no es de ese fichero."""
    _STATE.pending = []


# Ventana Disposición ▾ -------------------------------------------------------------------


def _draw_present(layout: Any, context: Any, current: Any) -> None:
    column = layout.column(align=True)
    for workspace in present():
        item = spec_for_workspace(workspace.name)
        depress = current is not None and workspace == current
        if item is not None:
            draw_command(column, add_key(item.id), context=context, depress=depress)
        else:
            properties = column.operator("wm.context_set_id", text=workspace.name,
                                         icon="WORKSPACE", translate=False, depress=depress)
            properties.data_path = "window.workspace"
            properties.value = workspace.name


def _draw_missing(layout: Any, context: Any) -> None:
    missing = [item for item in specs() if item.workspace not in bpy.data.workspaces]
    if not missing:
        return
    layout.separator(type="LINE")
    row = layout.row()
    row.active = False
    row.label(text=tr("Add layout"), translate=False)
    column = layout.column(align=True)
    for item in missing:
        draw_command(column, add_key(item.id), context=context)


class GEOBLENDER_PT_ui_layouts(bpy.types.Panel):
    """Choose, add, remove or restore a Geoblender layout"""

    bl_idname = PANEL
    bl_label = "Layouts"
    bl_translation_context = "Geoblender"
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = 13

    def draw(self, context: Any) -> None:
        layout = self.layout
        current = context_workspace(context)
        _draw_present(layout, context, current)
        _draw_missing(layout, context)
        layout.separator(type="LINE")
        column = layout.column(align=True)
        draw_command(column, REMOVE, context=context)
        draw_command(column, RESTORE, context=context)
        layout.separator(type="LINE")
        column = layout.column(align=True)
        draw_command(column, TOGGLE_ROW, context=context)
        group = preferences()
        if group is not None:
            column.prop(group, "show_mining_statusbar", text=tr("Show the mining status bar"),
                        translate=False)


# Registro --------------------------------------------------------------------------------

classes: tuple[type, ...] = (GEOBLENDER_PT_ui_layouts,)


def register() -> None:
    """Las comprobaciones de Quitar y Restaurar y el manejador ``load_post``."""
    register_check(REMOVE, remove_check)
    register_check(RESTORE, restore_check)
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)


def unregister() -> None:
    """Retira el temporizador, el manejador y las comprobaciones, y olvida lo pendiente."""
    if bpy.app.timers.is_registered(check_pending):
        bpy.app.timers.unregister(check_pending)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    unregister_check(REMOVE)
    unregister_check(RESTORE)
    _STATE.pending = []
    _STATE.attempts = 0
