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
- **Plegado** (spec 008, T69; M6: a 1920 px con escala efectiva 1,5, el trabajo de la 004 se
  salía por la derecha): un campo puede registrar además una **forma plegada**, más estrecha y
  con sus mismos botones (``folded_draw``, ``folded_width_px``). Si después de ocultar las
  prioridades 3 y 2 lo que queda aún no cabe, se pliegan los campos que la tienen, de derecha
  a izquierda y solo los que hace falta (:func:`fold`; :func:`arrange` dice qué se ve y
  plegado o no). Los de la 003 no se pliegan.

Lo que ocupa cada campo se calcula como lo dibuja Blender (spec 008, T69): el ancho ``blf``
de cada texto más lo que añade su elemento (:func:`label_px`, :func:`button_px`,
:func:`popover_px`, :func:`units_px`), con las medidas de ``bl.compat.statusbar_widths``, y un
separador entre campos (:data:`SEPARATOR_PX`), frente a la región menos
``bl.compat.STATUSBAR_RESERVED_PX``, todo a escala 1,0.

Los campos de la 003 (AR §6): el **proyecto** («Sin proyecto» si no hay ninguno abierto), su
**EPSG** y las coordenadas **absolutas** X, Y, Z del cursor 3D («Cursor: X 736 512,34  Y …»;
GeoOrigin entero más la posición local, en float64, con ``core.georef.local_to_world`` y
``core.i18n.format_xyz``), todos de prioridad 1; el **encaje** nativo (prioridad 3; un clic
abre el menú circular de encaje) y el **recorte** de la Vista 3D de destino si hay alguno
(prioridad 2; la banda de la 003 o la caja de Blender).

Se dibuja en cada redibujo de la ventana, así que nada se calcula dos veces (spec 003, T46;
RNF-003-03): los campos se ordenan al registrar o quitar uno, cada texto se mide con ``blf``
una vez, el cursor se pasa a absolutas solo si se ha movido (o cambian el origen o el
idioma) y los nombres del encaje se traducen una vez por idioma.

La barra de estado no se redibuja sola: una suscripción de ``bpy.msgbus`` al cursor 3D
(:func:`on_cursor_moved`), renovada en ``load_post``, la redibuja en las ventanas sin
operadores modales con ``workspace.status_text_set(None)`` (:func:`redraw`, que usa también
el seguimiento de los trabajos de la 004). :func:`uninstall` quita el
``append`` y la suscripción y olvida los campos.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import blf
import bpy
import numpy as np
from bpy.app.handlers import persistent

from ...core.georef import GeoOrigin, local_to_world
from ...core.i18n import format_xyz, language, tr
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
WIDTHS = compat.statusbar_widths()
"""Lo que ocupa cada elemento de la barra de estado además de su texto (esta versión)."""
SEPARATOR_PX = WIDTHS.separator  # separador de línea entre campos, con su espacio
UI_FONT_ID = 0
MAX_CACHED_TEXTS = 256  # textos medidos que se guardan (después, se empieza de nuevo)

DrawField = Callable[[Any, Any], None]
WidthField = Callable[[Any], float]


@dataclass(frozen=True)
class Field:
    """Un campo de la barra de estado (contrato 5) y, si se puede plegar, su forma plegada
    (spec 008, T69)."""

    key: str
    priority: int
    draw: DrawField
    width_px: WidthField
    modes: frozenset[str]
    order: float
    folded_draw: DrawField | None = None
    folded_width_px: WidthField | None = None


class _State:
    def __init__(self) -> None:
        self.fields: dict[str, Field] = {}
        self.ordered: tuple[Field, ...] | None = None  # los campos en su orden (caché)
        self.owner = object()  # dueño de la suscripción de msgbus
        self.subscribed = False
        # Cachés de lo que se pide en cada redibujo (spec 003, T46; RNF-003-03): el ancho
        # de cada texto medido con blf, el texto del cursor de la última posición y los
        # nombres del encaje por idioma.
        self.widths: dict[str, float] = {}
        self.cursor: tuple[object, str] | None = None
        self.snap_names: dict[str, dict[str, str]] = {}


_STATE = _State()


# Registro de campos ----------------------------------------------------------------------


def register_field(key: str, *, priority: int, draw: DrawField, width_px: WidthField,
                   modes: frozenset[str] = ONLY_GEOBLENDER, order: float = 100.0,
                   folded_draw: DrawField | None = None,
                   folded_width_px: WidthField | None = None) -> None:
    """Registra (o sustituye) el campo ``key``: prioridad 1, 2 o 3; ``draw(layout,
    context)``; ``width_px(context)``, lo que ocupa a escala 1,0 (0: nada que mostrar);
    ``modes``, ``GEOBLENDER`` y, si se ve también en modo Blender, ``BLENDER``; ``order``,
    su sitio en la barra (los de la 003, de 10 a 60); y, si se puede plegar (spec 008, T69),
    ``folded_draw`` y ``folded_width_px``, su forma plegada (los dos o ninguno)."""
    if priority not in (1, 2, 3):
        raise ValueError(f"prioridad «{priority}» del campo «{key}»: se espera 1, 2 o 3")
    unknown = set(modes) - {GEOBLENDER, BLENDER}
    if not modes or unknown:
        raise ValueError(f"modos del campo «{key}»: se espera GEOBLENDER o BLENDER")
    if (folded_draw is None) != (folded_width_px is None):
        raise ValueError(f"forma plegada del campo «{key}»: se esperan su dibujo y su ancho")
    _STATE.fields[key] = Field(key, priority, draw, width_px, frozenset(modes), order,
                               folded_draw, folded_width_px)
    _STATE.ordered = None


def unregister_field(key: str) -> None:
    """Quita el campo ``key`` (si no está, nada)."""
    _STATE.fields.pop(key, None)
    _STATE.ordered = None


def fields() -> tuple[Field, ...]:
    """Los campos registrados, en su orden (se ordenan al registrar o quitar uno, no en
    cada dibujo)."""
    if _STATE.ordered is None:
        ordered = sorted(enumerate(_STATE.fields.values()),
                         key=lambda pair: (pair[1].order, pair[0]))
        _STATE.ordered = tuple(field for _index, field in ordered)
    return _STATE.ordered


# Elección de lo que se ve ----------------------------------------------------------------


def total_px(widths: Iterable[float]) -> float:
    """Lo que ocupan unos campos de anchos ``widths`` con un separador entre cada dos."""
    values = list(widths)
    return sum(values) + SEPARATOR_PX * max(0, len(values) - 1)


def fit(widths: Sequence[tuple[int, float]], available_px: float) -> list[int]:
    """Los índices de los campos ``(prioridad, ancho)`` que se ven en ``available_px``:
    se quitan los de prioridad 3 y después los de prioridad 2 (cada vez, todos los de esa
    prioridad, de derecha a izquierda, hasta que quepa); los de prioridad 1 se quedan."""
    shown = list(range(len(widths)))

    def total() -> float:
        return total_px(widths[i][1] for i in shown)

    for priority in (3, 2):
        for index in reversed([i for i in shown if widths[i][0] == priority]):
            if total() <= available_px:
                return shown
            shown.remove(index)
    return shown


def fold(widths: Sequence[tuple[float, float | None]], available_px: float) -> list[bool]:
    """Qué campos ``(ancho, ancho plegado o None)`` se pliegan para caber en
    ``available_px`` (spec 008, T69): de derecha a izquierda, los que tienen una forma plegada
    más estrecha, hasta que quepa; si plegados todos aún no cabe, quedan todos plegados."""
    folded = [False] * len(widths)
    total = total_px(width for width, _narrow in widths)
    for index in reversed(range(len(widths))):
        if total <= available_px:
            break
        width, narrow = widths[index]
        if narrow is not None and narrow < width:
            folded[index] = True
            total -= width - narrow
    return folded


def mode_of(context: Any) -> str:
    """``GEOBLENDER`` o ``BLENDER``, el modo de la ventana de ``context``."""
    geoblender = gate.is_geoblender_workspace(getattr(context, "workspace", None))
    return GEOBLENDER if geoblender else BLENDER


def _folded_px(field: Field, context: Any) -> float | None:
    if field.folded_width_px is None:
        return None
    width = float(field.folded_width_px(context))
    return width if width > 0 else None


def arrange(context: Any) -> list[tuple[Field, bool]]:
    """Los campos que se dibujan ahora en la barra de estado de ``context``, en su orden, y
    si cada uno va plegado: se ocultan las prioridades 3 y 2 que no caben (:func:`fit`) y,
    si aún no cabe, se pliegan los que se pueden plegar (:func:`fold`; spec 008, T69)."""
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
        return [(field, False) for field, _width in candidates]
    available = region_width / scale - compat.STATUSBAR_RESERVED_PX
    chosen = [candidates[index]
              for index in fit([(field.priority, width) for field, width in candidates],
                               available)]
    if total_px(width for _field, width in chosen) <= available:
        return [(field, False) for field, _width in chosen]
    folded = fold([(width, _folded_px(field, context)) for field, width in chosen], available)
    return [(field, flag) for (field, _width), flag in zip(chosen, folded, strict=True)]


def visible_fields(context: Any) -> list[Field]:
    """Los campos que se dibujan ahora en la barra de estado de ``context``."""
    return [field for field, _folded in arrange(context)]


def draw_statusbar(self: Any, context: Any) -> None:
    """Los campos visibles, separados por una línea (RF-003-28), plegados los que no caben
    (spec 008, T69)."""
    shown = arrange(context)
    if not shown:
        return
    row = self.layout.row(align=False)
    for index, (field, folded) in enumerate(shown):
        if index:
            row.separator(type="LINE")
        draw = field.folded_draw if folded and field.folded_draw is not None else field.draw
        draw(row, context)


setattr(draw_statusbar, OURS_ATTR, True)


# Campos de la 003 (AR §6) ----------------------------------------------------------------


def _text_width(text: str) -> float:
    """El ancho ``blf`` de ``text`` a escala 1,0, medido una vez por texto (T46)."""
    width = _STATE.widths.get(text)
    if width is None:
        if len(_STATE.widths) >= MAX_CACHED_TEXTS:
            _STATE.widths.clear()
        blf.size(UI_FONT_ID, compat.UI_FONT_POINTS)
        width = float(blf.dimensions(UI_FONT_ID, text)[0])
        _STATE.widths[text] = width
    return width


def text_px(*texts: str) -> float:
    """Lo que ocupan unas etiquetas sin icono con ``blf`` a escala 1,0 (fuente de la
    interfaz); cada texto se mide una vez (la barra de estado lo pide en cada redibujo)."""
    return sum(label_px(text) for text in texts)


def label_px(text: str, *, icon: bool = False) -> float:
    """Lo que ocupa una etiqueta (``layout.label``) con ``text`` y, si ``icon``, su icono, a
    escala 1,0; sin texto ni icono, nada (spec 008, T69)."""
    if not text:
        return WIDTHS.icon_button if icon else 0.0
    return _text_width(text) + (WIDTHS.icon_label if icon else WIDTHS.label)


def button_px(text: str = "") -> float:
    """Lo que ocupa el botón de una orden (``layout.operator``) sin icono con ``text`` o, sin
    texto, solo con su icono, a escala 1,0 (spec 008, T69)."""
    return _text_width(text) + WIDTHS.button if text else WIDTHS.icon_button


def popover_px(text: str) -> float:
    """Lo que ocupa un desplegable (``layout.popover``) con ``text``, a escala 1,0 (spec 008,
    T69)."""
    return _text_width(text) + WIDTHS.popover


def units_px(units: float) -> float:
    """Lo que ocupa una fila de ``units`` unidades de interfaz (``ui_units_x``), a escala
    1,0."""
    return float(units) * compat.UI_UNIT_PX


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
    proyecto): GeoOrigin entero + posición local, en float64. Se calcula de nuevo solo si
    cambian la posición, el origen o el idioma (T46)."""
    georef = scene_georef.project_georeference()
    scene = getattr(context, "scene", None) or bpy.context.scene
    if georef is None or scene is None:
        return ""
    location = tuple(scene.cursor.location)
    key = (location, tuple(georef.origin), language())
    cached = _STATE.cursor
    if cached is not None and cached[0] == key:
        return cached[1]
    local = np.array(location, dtype=np.float64)
    x, y, z = (float(value) for value in local_to_world(local, GeoOrigin(*georef.origin)))
    found = format_xyz(x, y, z)
    _STATE.cursor = (key, found)
    return found


def snap_names() -> dict[str, str]:
    """Elemento de encaje de Blender → su nombre en el idioma de Geoblender (una vez por
    idioma; no se modifica)."""
    lang = language()
    found = _STATE.snap_names.get(lang)
    if found is None:
        found = _STATE.snap_names[lang] = _snap_names()
    return found


def _snap_names() -> dict[str, str]:
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
    ("snap", 3, 40.0, _draw_snap, lambda context: button_px(snap_text(context))),
    ("clip", 2, 60.0, _draw_clip, lambda context: _optional_px(clip_text(context))),
)


# Redibujo con el cursor ------------------------------------------------------------------


def redraw(windows: Iterable[Any] | None = None, *, geoblender_only: bool = False) -> int:
    """Redibuja la barra de estado de ``windows`` (por defecto, todas las ventanas) con
    ``workspace.status_text_set(None)`` (la barra no está en ``screen.areas``: plan 004
    §2.1), salvo las que tienen un operador modal (su texto de estado es suyo) y, con
    ``geoblender_only``, las que no están en modo Geoblender. Devuelve cuántas redibujó.
    Lo usan el cursor 3D y el seguimiento de los trabajos (spec 004, ``bl/ops/jobs.py``)."""
    if windows is None:
        manager = getattr(bpy.context, "window_manager", None)
        windows = getattr(manager, "windows", ())
    count = 0
    for window in windows:
        if len(getattr(window, "modal_operators", ())):
            continue
        workspace = window.workspace
        if workspace is None:
            continue
        if geoblender_only and not gate.is_geoblender_workspace(workspace):
            continue
        with bpy.context.temp_override(window=window):
            workspace.status_text_set(None)
        count += 1
    return count


def on_cursor_moved(*_args: Any) -> None:
    """El cursor 3D se ha movido: redibuja la barra de estado de las ventanas en modo
    Geoblender que no tienen un operador modal (su texto de estado es suyo)."""
    redraw(geoblender_only=True)


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
    _STATE.ordered = None
    _STATE.widths.clear()
    _STATE.cursor = None
    _STATE.snap_names.clear()
