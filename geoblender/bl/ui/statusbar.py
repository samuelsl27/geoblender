# SPDX-License-Identifier: GPL-3.0-or-later
"""Barra de estado minera (spec 003; RF-003-28; plan 003 §5.3, contrato 5, y §5.4, 14,
DT11 y DT14; AR §6).

Un **único** ``STATUSBAR_HT_header.append`` (:func:`draw_statusbar`), a la derecha de lo que
dibuja Blender (las ayudas de teclado de la herramienta siguen a la izquierda). Lo que se
ve son **campos registrados** con :func:`register_field`: cada spec registra los suyos y
ninguna añade su propio ``append`` (contrato 5). Un campo tiene su prioridad (1, 2 o 3),
cómo se dibuja, cuánto ocupa (px a escala 1,0; 0 si no tiene nada que mostrar), en qué
modos se ve (``GEOBLENDER`` y, si lo declara, ``BLENDER``: los trabajos de la 004) y su
orden en la barra (``order``; los de la 003, los primeros, como en AR §6).

- **Modo Geoblender**, con la preferencia «Barra de estado minera»: todos los campos. Si no
  caben (:func:`fit`, con el ancho medido con ``blf``), se ocultan primero los de prioridad
  3 y después los de prioridad 2; los de prioridad 1, nunca.
- **Modo Blender**, o la preferencia apagada: solo los campos declarados para los dos modos,
  y solo mientras tengan algo que mostrar.

Los campos de la 003 (AR §6): el **proyecto** («Sin proyecto» si no hay ninguno abierto), su
**EPSG** y las coordenadas **absolutas** X, Y, Z del cursor 3D («Cursor: X 736 512,34  Y …»;
GeoOrigin entero más la posición local, en float64, con ``core.georef.local_to_world`` y
``core.i18n.format_xyz``), todos de prioridad 1; el **encaje** nativo (prioridad 3; un clic
abre el menú circular de encaje) y el **recorte** de la Vista 3D de destino si hay alguno
(prioridad 2; la banda de la 003 o la caja de Blender).

La barra de estado no se redibuja sola: una suscripción de ``bpy.msgbus`` al cursor 3D
(:func:`on_cursor_moved`), renovada en ``load_post``, la redibuja en las ventanas sin
operadores modales con ``workspace.status_text_set(None)``. :func:`uninstall` quita el
``append`` y la suscripción y olvida los campos.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import blf
import bpy
import numpy as np
from bpy.app.handlers import persistent

from ...core.georef import GeoOrigin, local_to_world
from ...core.i18n import format_xyz, tr
from .. import compat
from ..scene import georef as scene_georef
from . import gate, views
from .commands import preference

HEADER = "STATUSBAR_HT_header"
GEOBLENDER = "GEOBLENDER"
BLENDER = "BLENDER"
ONLY_GEOBLENDER = frozenset({GEOBLENDER})
SNAP_PIE = "GEOBLENDER_MT_ui_pie_snap"
CALL_PIE = "geoblender.ui_call_pie"
OURS_ATTR = "_gb_statusbar"
LABEL_PAD_PX = 10.0  # relleno de una etiqueta de la barra de estado, a escala 1,0
SEPARATOR_PX = 12.0  # separador de línea entre campos
UI_FONT_ID = 0

DrawField = Callable[[Any, Any], None]
WidthField = Callable[[Any], float]


@dataclass(frozen=True)
class Field:
    """Un campo de la barra de estado (contrato 5)."""

    key: str
    priority: int
    draw: DrawField
    width_px: WidthField
    modes: frozenset[str]
    order: float


class _State:
    def __init__(self) -> None:
        self.fields: dict[str, Field] = {}
        self.owner = object()  # dueño de la suscripción de msgbus
        self.subscribed = False


_STATE = _State()


# Registro de campos ----------------------------------------------------------------------


def register_field(key: str, *, priority: int, draw: DrawField, width_px: WidthField,
                   modes: frozenset[str] = ONLY_GEOBLENDER, order: float = 100.0) -> None:
    """Registra (o sustituye) el campo ``key``: prioridad 1, 2 o 3; ``draw(layout,
    context)``; ``width_px(context)``, lo que ocupa a escala 1,0 (0: nada que mostrar);
    ``modes``, ``GEOBLENDER`` y, si se ve también en modo Blender, ``BLENDER``; ``order``,
    su sitio en la barra (los de la 003, de 10 a 60)."""
    if priority not in (1, 2, 3):
        raise ValueError(f"prioridad «{priority}» del campo «{key}»: se espera 1, 2 o 3")
    unknown = set(modes) - {GEOBLENDER, BLENDER}
    if not modes or unknown:
        raise ValueError(f"modos del campo «{key}»: se espera GEOBLENDER o BLENDER")
    _STATE.fields[key] = Field(key, priority, draw, width_px, frozenset(modes), order)


def unregister_field(key: str) -> None:
    """Quita el campo ``key`` (si no está, nada)."""
    _STATE.fields.pop(key, None)


def fields() -> tuple[Field, ...]:
    """Los campos registrados, en su orden."""
    ordered = sorted(enumerate(_STATE.fields.values()), key=lambda pair: (pair[1].order, pair[0]))
    return tuple(field for _index, field in ordered)


# Elección de lo que se ve ----------------------------------------------------------------


def fit(widths: Sequence[tuple[int, float]], available_px: float) -> list[int]:
    """Los índices de los campos ``(prioridad, ancho)`` que se ven en ``available_px``:
    se quitan los de prioridad 3 y después los de prioridad 2 (cada vez, todos los de esa
    prioridad, de derecha a izquierda, hasta que quepa); los de prioridad 1 se quedan."""
    shown = list(range(len(widths)))

    def total() -> float:
        return sum(widths[i][1] for i in shown) + SEPARATOR_PX * max(0, len(shown) - 1)

    for priority in (3, 2):
        for index in reversed([i for i in shown if widths[i][0] == priority]):
            if total() <= available_px:
                return shown
            shown.remove(index)
    return shown


def mode_of(context: Any) -> str:
    """``GEOBLENDER`` o ``BLENDER``, el modo de la ventana de ``context``."""
    geoblender = gate.is_geoblender_workspace(getattr(context, "workspace", None))
    return GEOBLENDER if geoblender else BLENDER


def visible_fields(context: Any) -> list[Field]:
    """Los campos que se dibujan ahora en la barra de estado de ``context``."""
    mode = mode_of(context)
    if mode == GEOBLENDER and not preference("show_mining_statusbar", True):
        mode = BLENDER  # solo los de los dos modos
    candidates: list[tuple[Field, float]] = []
    for field in fields():
        if mode not in field.modes:
            continue
        width = float(field.width_px(context))
        if width > 0:
            candidates.append((field, width))
    if not candidates:
        return []
    scale = compat.ui_scale()
    region_width = float(getattr(getattr(context, "region", None), "width", 0) or 0)
    if region_width <= 0:
        return [field for field, _width in candidates]
    available = region_width / scale - compat.STATUSBAR_RESERVED_PX
    chosen = fit([(field.priority, width) for field, width in candidates], available)
    return [candidates[index][0] for index in chosen]


def draw_statusbar(self: Any, context: Any) -> None:
    """Los campos visibles, separados por una línea (RF-003-28)."""
    shown = visible_fields(context)
    if not shown:
        return
    row = self.layout.row(align=False)
    for index, field in enumerate(shown):
        if index:
            row.separator(type="LINE")
        field.draw(row, context)


setattr(draw_statusbar, OURS_ATTR, True)


# Campos de la 003 (AR §6) ----------------------------------------------------------------


def text_px(*texts: str) -> float:
    """Lo que ocupan unas etiquetas con ``blf`` a escala 1,0 (fuente de la interfaz)."""
    blf.size(UI_FONT_ID, compat.UI_FONT_POINTS)
    return sum(float(blf.dimensions(UI_FONT_ID, text)[0]) + LABEL_PAD_PX for text in texts)


def project_text() -> str:
    """El nombre del proyecto abierto o «Sin proyecto»."""
    georef = scene_georef.project_georeference()
    return georef.name if georef is not None else tr("No project")


def epsg_text() -> str:
    """«EPSG:25830» del proyecto abierto ("" sin proyecto)."""
    georef = scene_georef.project_georeference()
    return f"EPSG:{georef.crs_epsg}" if georef is not None else ""


def cursor_text(context: Any) -> str:
    """Las coordenadas absolutas del cursor 3D en el formato del idioma ("" sin
    proyecto): GeoOrigin entero + posición local, en float64."""
    georef = scene_georef.project_georeference()
    scene = getattr(context, "scene", None) or bpy.context.scene
    if georef is None or scene is None:
        return ""
    local = np.array(tuple(scene.cursor.location), dtype=np.float64)
    x, y, z = (float(value) for value in local_to_world(local, GeoOrigin(*georef.origin)))
    return format_xyz(x, y, z)


def snap_names() -> dict[str, str]:
    """Elemento de encaje de Blender → su nombre en el idioma de Geoblender."""
    return {
        "INCREMENT": tr("increment"),
        "GRID": tr("grid"),
        "VERTEX": tr("vertex"),
        "EDGE": tr("edge"),
        "FACE": tr("face"),
        "FACE_PROJECT": tr("face"),
        "FACE_NEAREST": tr("nearest face"),
        "VOLUME": tr("volume"),
        "EDGE_MIDPOINT": tr("edge midpoint"),
        "EDGE_PERPENDICULAR": tr("perpendicular"),
    }


def snap_text(context: Any) -> str:
    """«Encaje: vértice», «Encaje: desactivado»… del encaje nativo de la escena."""
    scene = getattr(context, "scene", None) or bpy.context.scene
    settings = scene.tool_settings
    if not settings.use_snap:
        return tr("Snap: {mode}", mode=tr("off"))
    known = snap_names()
    names: list[str] = []
    for element in sorted(settings.snap_elements):
        name = known.get(element, element.lower())
        if name not in names:
            names.append(name)
    return tr("Snap: {mode}", mode=" + ".join(names))


def clip_text(context: Any) -> str:
    """«Recorte: banda» o «Recorte: caja» de la Vista 3D de destino ("" sin recorte)."""
    target = views.target_view3d(context)
    if target is None or target.rv3d is None:
        return ""
    mode = views.clip_mode(target.rv3d)
    if mode == "BAND":
        return tr("Clipping: {mode}", mode=tr("band"))
    if mode == "BOX":
        return tr("Clipping: {mode}", mode=tr("box"))
    return ""


def _draw_project(layout: Any, _context: Any) -> None:
    layout.label(text=project_text(), translate=False)


def _draw_epsg(layout: Any, _context: Any) -> None:
    layout.label(text=epsg_text(), translate=False)


def _draw_cursor(layout: Any, context: Any) -> None:
    row = layout.row(align=True)
    row.label(text=tr("Cursor:"), translate=False)
    row.label(text=cursor_text(context), translate=False)


def _draw_snap(layout: Any, context: Any) -> None:
    properties = layout.operator(CALL_PIE, text=snap_text(context), translate=False,
                                 emboss=False)
    properties.name = SNAP_PIE


def _draw_clip(layout: Any, context: Any) -> None:
    layout.label(text=clip_text(context), translate=False)


def _cursor_px(context: Any) -> float:
    value = cursor_text(context)
    return text_px(tr("Cursor:"), value) if value else 0.0


def _optional_px(text: str) -> float:
    return text_px(text) if text else 0.0


OWN_FIELDS: tuple[tuple[str, int, float, DrawField, WidthField], ...] = (
    ("project", 1, 10.0, _draw_project, lambda _context: text_px(project_text())),
    ("epsg", 1, 20.0, _draw_epsg, lambda _context: _optional_px(epsg_text())),
    ("cursor", 1, 30.0, _draw_cursor, _cursor_px),
    ("snap", 3, 40.0, _draw_snap, lambda context: text_px(snap_text(context))),
    ("clip", 2, 60.0, _draw_clip, lambda context: _optional_px(clip_text(context))),
)


# Redibujo con el cursor ------------------------------------------------------------------


def on_cursor_moved(*_args: Any) -> None:
    """El cursor 3D se ha movido: redibuja la barra de estado de las ventanas en modo
    Geoblender que no tienen un operador modal (su texto de estado es suyo)."""
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        workspace = window.workspace
        if workspace is None or not gate.is_geoblender_workspace(workspace):
            continue
        if len(getattr(window, "modal_operators", ())):
            continue
        with bpy.context.temp_override(window=window):
            workspace.status_text_set(None)


def _subscribe() -> None:
    bpy.msgbus.clear_by_owner(_STATE.owner)
    bpy.msgbus.subscribe_rna(key=(bpy.types.View3DCursor, "location"), owner=_STATE.owner,
                             args=(), notify=on_cursor_moved)
    _STATE.subscribed = True


def is_subscribed() -> bool:
    """Si la barra de estado sigue al cursor 3D."""
    return _STATE.subscribed


@persistent
def on_load_post(*_args: Any) -> None:
    """Al abrir otro fichero, Blender olvida las suscripciones: se renueva."""
    if _STATE.subscribed:
        _subscribe()


# Instalación -----------------------------------------------------------------------------


def _remove_ours() -> None:
    header = getattr(bpy.types, HEADER)
    for function in list(getattr(header.draw, "_draw_funcs", None) or ()):
        if getattr(function, OURS_ATTR, False):
            header.remove(function)


def install() -> None:
    """Registra los campos de la 003, añade la barra (una sola vez, también tras una
    recarga) y se suscribe al cursor 3D."""
    for key, priority, order, draw, width in OWN_FIELDS:
        register_field(key, priority=priority, draw=draw, width_px=width, order=order)
    _remove_ours()
    getattr(bpy.types, HEADER).append(draw_statusbar)
    _subscribe()
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)


def uninstall() -> None:
    """Quita la barra, la suscripción y el manejador, y olvida los campos."""
    _remove_ours()
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    bpy.msgbus.clear_by_owner(_STATE.owner)
    _STATE.subscribed = False
    _STATE.fields.clear()
