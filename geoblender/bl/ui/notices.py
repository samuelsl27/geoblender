# SPDX-License-Identifier: GPL-3.0-or-later
"""Los avisos de la barra de estado, con plazo (spec 019, T22; RF-019-18; D-10; plan 019 A5; UI-09, UI-11).

Cada orden de Geoblender escribe por ``report`` como siempre (Blender lo registra en el Info) y
``bl.reporting`` deja además el aviso en la cola de ``core.notices`` (:func:`post`). El campo de la barra de
estado (:data:`FIELD`, en los dos modos) muestra el último aviso vivo, también plegado. Lo que lo retira:

- el plazo: 15 s (:data:`core.notices.DEFAULT_TTL`; D-10) y 10 s el de Ctrl+Z y el de la disposición anterior
  (:data:`UNDO_TTL`); un temporizador de 1 s (:func:`tick`) barre la cola (:func:`sweep`) y se retira solo cuando
  no queda ningún aviso;
- cambiar la selección o el objeto activo (DIFF-019 b: Python no ve los eventos de entrada): se compara la
  selección de cuando se avisó con la de ahora en cada barrido y cuando ``msgbus`` avisa de que cambió el objeto
  activo (:func:`on_selection_event`);
- cancelar (una orden que devuelve ``CANCELLED`` sin haber informado de nada: si informó de un error, su aviso se
  queda), cambiar de proyecto o de versión y conmutar a la interfaz de Blender (:func:`clear`).

**El informe de Blender no se controla** (D-10; T01): la línea de la barra de estado caduca sola y el globo
emergente solo con un clic.

El tiempo se inyecta en las funciones que lo usan (``now``); sin él, se lee de :data:`_clock`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any

import bpy
from bpy.app.handlers import persistent

from ..reporting import Sink, set_sink
from ..scene import project_session
from ..scene import versions as scene_versions
from . import statusbar, switcher

if TYPE_CHECKING:  # ``core.notices`` se importa al usarlo (RNF-001-03: registrar no importa dominio)
    from ...core.notices import Notice, Queue

LOGGER = logging.getLogger("geoblender.bl.ui")

FIELD = "notice"
FIELD_ORDER = 65.0  # el sitio del aviso de Ctrl+Z de la 008: tras los de la procedencia, antes de los trabajos
FIELD_PRIORITY = 1
FIELD_MODES = frozenset({statusbar.GEOBLENDER, statusbar.BLENDER})
FOLDED_UNITS = 6  # el aviso plegado, en unidades: Blender corta el texto con «…»
TICK_S = 1.0
UNDO_TTL = 10.0
ICONS = {"info": "INFO", "warning": "ERROR", "error": "CANCEL"}
MSGID = "{text}"  # el texto ya llega en el idioma de la persona: se muestra tal cual

_QUEUE: Queue | None = None
_clock: Callable[[], float] = time.monotonic


class _State:
    def __init__(self) -> None:
        self.owner = object()  # dueño de la suscripción de msgbus
        self.subscribed = False
        self.generation = 0  # sube con cada aviso nuevo
        self.baseline: object = None  # la selección cuando se avisó por última vez


_STATE = _State()


def queue() -> Queue:
    """La cola de avisos de la sesión (``core.notices.Queue``, que se importa al primer uso)."""
    global _QUEUE
    if _QUEUE is None:
        from ...core.notices import Queue

        _QUEUE = Queue()
    return _QUEUE


def _now(now: float | None) -> float:
    return _clock() if now is None else now


# La selección ------------------------------------------------------------------------------------


def selection_signature() -> object:
    """Qué hay seleccionado y activo en la capa de vista de ahora (``None`` si Blender no tiene contexto)."""
    layer = getattr(bpy.context, "view_layer", None)
    if layer is None:
        return None
    active = layer.objects.active
    selected = tuple(sorted(obj.name for obj in layer.objects if obj.select_get(view_layer=layer)))
    return (active.name if active is not None else None, selected)


def check_selection() -> int:
    """Si cambió la selección o el objeto activo desde el último aviso, retira los avisos; devuelve cuántos."""
    if _QUEUE is None or not len(_QUEUE):
        return 0
    if selection_signature() == _STATE.baseline:
        return 0
    return clear("selection")


def on_selection_event(*_args: Any) -> None:
    """``msgbus`` avisó de que cambió el objeto activo (o lo llama el barrido)."""
    check_selection()


# La cola ---------------------------------------------------------------------------------------------


def post(level: str, text: str, *, ttl: float | None = None, now: float | None = None) -> Notice | None:
    """Deja ``text`` (ya en el idioma de la persona) en la cola con su ``level`` (``info``, ``warning`` o
    ``error``) y su plazo ``ttl``; uno repetido renueva el plazo (UI-09). Sin texto, nada."""
    if not text:
        return None
    check_selection()  # lo anterior que ya no corresponde a la selección de ahora se va antes de añadir
    from ...core.notices import DEFAULT_TTL

    notice = queue().add(level, MSGID, {"text": text}, _now(now), DEFAULT_TTL if ttl is None else ttl)
    _STATE.generation += 1
    _STATE.baseline = selection_signature()
    _ensure_timer()
    statusbar.redraw()
    return notice


def current(now: float | None = None) -> Notice | None:
    """El aviso vivo más reciente, o ``None``."""
    return _QUEUE.latest(_now(now)) if _QUEUE is not None else None


def latest_text(now: float | None = None) -> str:
    """El texto del aviso vivo más reciente en el idioma activo, o ""."""
    found = current(now)
    return found.text() if found is not None else ""


def sweep(now: float | None = None) -> int:
    """Retira los avisos cuyo plazo se cumplió en ``now`` y los de una selección que cambió; devuelve cuántos y,
    si retiró alguno, redibuja la barra de estado."""
    removed = _QUEUE.expire(_now(now)) if _QUEUE is not None else 0
    removed += check_selection()
    if removed:
        statusbar.redraw()
    return removed


def clear(reason: str) -> int:
    """Retira todos los avisos por ``reason`` (``core.notices.REASONS``), quita el temporizador y redibuja la
    barra de estado si había alguno; devuelve cuántos."""
    removed = queue().clear(reason)
    _retire_timer()
    if removed:
        statusbar.redraw()
    return removed


def tick() -> float | None:
    """El temporizador de 1 s: barre la cola mientras quede algún aviso."""
    sweep()
    if _QUEUE is not None and len(_QUEUE):
        return TICK_S
    return None


def _ensure_timer() -> None:
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=TICK_S, persistent=True)


def _retire_timer() -> None:
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)


# Lo que llega de las órdenes -----------------------------------------------------------------------------


def level_of(types: set[str]) -> str | None:
    """El nivel del aviso de un informe de Blender (``DEBUG``, ``OPERATOR`` y ``PROPERTY`` no se avisan)."""
    if any(kind.startswith("ERROR") for kind in types):
        return "error"
    if "WARNING" in types:
        return "warning"
    if "INFO" in types:
        return "info"
    return None


def on_report(types: set[str], message: str) -> None:
    """Un ``self.report`` de una orden de Geoblender (``bl.reporting``)."""
    level = level_of(types)
    if level is not None:
        post(level, message)


def generation() -> int:
    """Cuántos avisos se han dejado (``bl.reporting`` lo compara al terminar una orden)."""
    return _STATE.generation


def on_cancelled(mark: int) -> None:
    """Una orden devolvió ``CANCELLED``: si no avisó de nada desde que empezó (``mark``), limpia la barra."""
    if _STATE.generation == mark:
        clear("cancel")


def on_project_changed(_project: Any) -> None:
    """Se abrió, cambió o cerró el proyecto de la sesión."""
    clear("project")


def on_version_changed() -> None:
    """Cambió lo que se ve de las versiones (la activa, el estado…)."""
    clear("version")


def on_entered_blender() -> None:
    """Una ventana pasó a la interfaz de Blender."""
    clear("switch")


# El campo de la barra de estado ------------------------------------------------------------------------


def _draw(layout: Any, _context: Any, *, folded: bool = False) -> None:
    shown = current()
    if shown is None:
        return
    row = layout.row(align=True)
    if folded:
        row.ui_units_x = FOLDED_UNITS  # Blender corta el texto con «…»
    row.label(text=shown.text(), icon=ICONS[shown.level], translate=False)


def _width(_context: Any, *, folded: bool = False) -> float:
    shown = current()
    if shown is None:
        return 0.0
    if folded:
        return statusbar.units_px(FOLDED_UNITS)
    return statusbar.label_px(shown.text(), icon=True)


# Instalación -----------------------------------------------------------------------------------------


def _subscribe() -> None:
    bpy.msgbus.clear_by_owner(_STATE.owner)
    bpy.msgbus.subscribe_rna(key=(bpy.types.LayerObjects, "active"), owner=_STATE.owner, args=(),
                             notify=on_selection_event)
    _STATE.subscribed = True


@persistent
def on_load_post(*_args: Any) -> None:
    """Al abrir otro fichero: los avisos eran del anterior y Blender olvida las suscripciones."""
    clear("project")
    if _STATE.subscribed:
        _subscribe()


def install() -> None:
    """Registra el campo de la barra de estado (después de ``statusbar.install``), la suscripción al objeto activo,
    las escuchas del proyecto, de la versión y del conmutador, y el manejador de ``load_post``. Idempotente."""
    statusbar.register_field(FIELD, priority=FIELD_PRIORITY, draw=_draw, width_px=_width, modes=FIELD_MODES,
                             order=FIELD_ORDER, folded_draw=partial(_draw, folded=True),
                             folded_width_px=partial(_width, folded=True))
    _subscribe()
    project_session.add_listener(on_project_changed)
    scene_versions.add_listener(on_version_changed)
    switcher.add_blender_hook(on_entered_blender)
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)
    set_sink(Sink(on_report, generation, on_cancelled))


def uninstall() -> None:
    """Quita todo lo de :func:`install`, el temporizador y los avisos."""
    set_sink(None)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    switcher.remove_blender_hook(on_entered_blender)
    scene_versions.remove_listener(on_version_changed)
    project_session.remove_listener(on_project_changed)
    bpy.msgbus.clear_by_owner(_STATE.owner)
    _STATE.subscribed = False
    statusbar.unregister_field(FIELD)
    _retire_timer()
    if _QUEUE is not None:
        _QUEUE.clear("switch")
    _STATE.baseline = None
