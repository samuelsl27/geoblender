# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia en la interfaz (spec 008; plan 008 §5.5; ADR-0012).

**Barra de estado** (campos de la 003 con ``bl.ui.statusbar.register_field``, prioridad 1,
en los dos modos, Geoblender y Blender; spec §11), cada uno solo si tiene algo que mostrar:

- «⚠ n entradas» (RF-008-16): las entradas cambiadas sin decidir; abre el registro de
  entradas (``geoblender.core_show_inputs``);
- «! n obsoletos» (RF-008-28): los datos obsoletos más las operaciones que esperan revisión a
  mano; abre lo obsoleto (:class:`GEOBLENDER_PT_core_stale`);
- «Comprobando el proyecto… 42 %» (RF-008-58), el progreso de la comprobación de apertura de
  la sesión de la procedencia (``bl.ops.core_provenance.SESSION``), con su botón de cancelar
  (``geoblender.core_cancel_checks``);
- el aviso de Ctrl+Z (RF-008-32; plan §5.4.11): :func:`show_undo_notice` lo deja
  :data:`UNDO_NOTICE_S` s.

Los iconos ``gb_state_input_changed`` y ``gb_state_stale`` dibujan los mismos signos ⚠ y ! con
que empiezan los textos de la spec (AR §6): en la barra van solo los textos, sin repetir el
signo; el de lo obsoleto, en el panel.

**Al día sin leer en cada dibujo** (RNF-008-06: ≤ 1 s tras el cambio y ≤ 1 ms el dibujo): los
recuentos (``core.provenance.stale``) se leen en un temporizador persistente
(:func:`indicator_tick`, cada :data:`INDICATOR_TICK_S` s mientras hay un proyecto abierto),
y solo si cambió el contador de cambios de la cabecera de ``project.gpkg`` (lo sube cada
transacción confirmada, sea de quien sea) o el idioma; si no, el tic lee 100 bytes. Un
proyecto que QGIS dejó en WAL no se lee hasta que vuelva al diario clásico (lo que escribe
Geoblender lo devuelve antes). Los campos dibujan lo último leído, con sus textos medidos una
vez. Al abrir un proyecto no se lee nada (RNF-002-02 no cambia): el primer tic, después.

**Control 7** (RF-008-28): el número de lo obsoleto tras el icono de Refrescar
(``quick_access.set_count_provider``), que abre :class:`GEOBLENDER_PT_core_stale`; sin nada
obsoleto, solo el icono. Refrescar sigue provisional hasta la 009.

**Lo obsoleto** (:class:`GEOBLENDER_PT_core_stale`, RF-008-28): «Refrescar · obsoletos (n)» y,
por cada resultado obsoleto (como mucho :data:`MAX_STALE_ROWS`; los demás, «… y n más»), su
nombre, su módulo, la causa («Obsoleto: cambió Producción») y Recalcular
(``geoblender.core_recompute_stale`` de ese elemento) o, si espera revisión a mano, «revisar» y
Dar por buena… (``geoblender.core_accept_review``); al final, Recalcular lo obsoleto. Dibuja las
filas de ``WindowManager.geoblender_provenance.stale`` (D16), que el temporizador regenera con
los recuentos. Las órdenes cuya clase real aún no ha llegado se dibujan desactivadas.

:func:`install` registra los campos, el número del control 7 y la escucha del proyecto de la
sesión; :func:`uninstall` lo quita todo, con los temporizadores.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import bpy

from ...core.errors import GeoblenderError
from ...core.gpkg.header import read_header
from ...core.i18n import language, tr
from ...core.provenance import contract
from .. import compat
from ..props.provenance import WINDOW_MANAGER_PROPERTY
from ..scene import project_session
from . import icons, quick_access, statusbar
from .commands import catalog, is_available, registered_class, text
from .drawing import draw_command, native_icon

if TYPE_CHECKING:
    from ...core.project.session import Project
    from ...core.provenance.stale import Counts, StaleItem
    from ..ops.core_provenance import ProvenanceSession

LOGGER = logging.getLogger("geoblender.bl.ui")

FIELD_INPUTS = "provenance_inputs"
FIELD_STALE = "provenance_stale"
FIELD_CHECKING = "provenance_checking"
FIELD_UNDO = "provenance_undo"
FIELD_PRIORITY = 1
FIELD_MODES = frozenset({statusbar.GEOBLENDER, statusbar.BLENDER})
"""Los campos se ven en los dos modos (plan §5.5; spec §11)."""

INDICATOR_TICK_S = 0.5
"""Cada cuánto mira el temporizador si el proyecto cambió (RNF-008-06: ≤ 1 s con la lectura)."""

UNDO_NOTICE_S = 10.0
"""Lo que se ve el aviso de Ctrl+Z en la barra de estado (plan §5.5)."""

MAX_STALE_ROWS = 50
"""Las filas de lo obsoleto que se regeneran y dibujan (las demás, «… y n más»)."""

REFRESH = "geoblender.core_refresh"
STALE_PANEL = "GEOBLENDER_PT_core_stale"
SHOW_INPUTS = "geoblender.core_show_inputs"
CANCEL_CHECKS = "geoblender.core_cancel_checks"
RECOMPUTE = "geoblender.core_recompute_stale"
ACCEPT_REVIEW = "geoblender.core_accept_review"
STALE_ICON = "gb_state_stale"
STALE_FALLBACK = "COLLECTION_COLOR_01"
CANCEL_ICON = "X"
UNDO_ICON = "LOOP_BACK"
STALE_PANEL_UNITS = 20
MAX_TEXTS = 256  # textos con número guardados (después, se empieza de nuevo)

_clock: Callable[[], float] = time.monotonic


class _State:
    """Lo de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.project: Project | None = None  # el proyecto de los recuentos
        self.counts: Counts | None = None
        self.signature: tuple[int, str] | None = None  # contador de cambios e idioma leídos
        self.texts: dict[tuple[str, int, str], str] = {}
        self.undo_text = ""
        self.undo_until = 0.0
        self.properties: dict[type, frozenset[str]] = {}  # propiedades de cada operador


_STATE = _State()


def _session() -> ProvenanceSession:
    """La sesión de la procedencia (``bl.ops.core_provenance``), importada al usarla: bl/ops
    importa bl/ui (ARQ-08)."""
    from ..ops import core_provenance

    return core_provenance.SESSION


# Los recuentos --------------------------------------------------------------------------------


def counts() -> Counts | None:
    """Los últimos recuentos leídos del proyecto de la sesión, o ``None`` (sin proyecto con la
    procedencia o aún sin leer)."""
    return _STATE.counts


def refresh(*, force: bool = False) -> bool:
    """Vuelve a leer los recuentos y las filas de lo obsoleto si el proyecto de la sesión
    cambió desde la última lectura (otro proyecto, otro contador de cambios en la cabecera de
    ``project.gpkg`` u otro idioma) o con ``force``. Devuelve si cambió lo que muestran la barra
    de estado y el control 7. Si no se puede leer ahora (otro programa escribe, WAL), lo deja
    como estaba y lo intenta en la próxima."""
    session = _session()
    project = session.project if session.unavailable() is None else None
    changed = False
    if project is not _STATE.project:
        changed = _forget()
        _STATE.project = project
    if project is None:
        return changed
    try:
        header = read_header(project.database_path)
    except GeoblenderError:
        return changed
    if header.needs_recovery:
        return changed  # en WAL (QGIS): sin leer una copia privada en cada tic
    shown = language()
    signature = (header.change_counter, shown)
    if signature == _STATE.signature and not force:
        return changed
    from ...core.provenance import stale  # al usarlo: registrar no lo carga

    try:
        report = stale.stale_items(project, language=shown)
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.debug("No se pudo leer lo obsoleto del proyecto; se intenta después",
                     exc_info=True)
        return changed
    _STATE.signature = signature
    _fill_rows(report.items)
    if report.counts != _STATE.counts:
        _STATE.counts = report.counts
        changed = True
    return changed


def _forget() -> bool:
    """Olvida los recuentos y las filas; dice si había algo que mostrar."""
    found = _STATE.counts
    had = found is not None and (found.obsolete > 0 or found.inputs_changed > 0)
    _STATE.project = None
    _STATE.counts = None
    _STATE.signature = None
    _fill_rows(())
    return had


def _view() -> Any:
    manager = getattr(bpy.context, "window_manager", None)
    return getattr(manager, WINDOW_MANAGER_PROPERTY, None)


def _fill_rows(items: Sequence[StaleItem]) -> None:
    """Regenera las filas de lo obsoleto (las primeras :data:`MAX_STALE_ROWS`)."""
    view = _view()
    if view is None:
        return
    rows = view.stale
    if not items and not len(rows):
        return
    rows.clear()
    for item in items[:MAX_STALE_ROWS]:
        row = rows.add()
        row.item_kind = item.item_kind
        row.uid = item.uid
        row.name = item.name
        row.module = item.module
        row.operation_uid = item.operation_uid
        row.op_type = item.op_type
        row.review = item.review
        row.text = item.text
        row.since = item.since
    view.stale_index = 0


def indicator_tick() -> float | None:
    """La función del temporizador de los indicadores: :func:`refresh` y, si cambió lo que se
    ve, redibuja la barra de estado y la barra superior. Sigue cada :data:`INDICATOR_TICK_S` s
    mientras haya un proyecto con la procedencia; si no, se retira."""
    try:
        changed = refresh()
    except Exception:  # noqa: BLE001 - un temporizador que falla no tumba Blender
        LOGGER.exception("Falló la lectura de los indicadores de la procedencia")
        changed = False
    if changed:
        redraw()
    if _STATE.project is None:
        _retire(indicator_tick)
        return None
    return INDICATOR_TICK_S


def on_project_changed(project: Project | None) -> None:
    """Lo que se apunta en ``project_session``: olvida lo del proyecto anterior y, con uno
    nuevo, pone el temporizador (lee en su primer tic, no al abrir: RNF-002-02)."""
    had = _forget()
    _retire(indicator_tick)
    if project is not None:
        bpy.app.timers.register(indicator_tick, first_interval=INDICATOR_TICK_S,
                                persistent=True)
    if had:
        redraw()


def _retire(function: Callable[[], float | None]) -> None:
    if bpy.app.timers.is_registered(function):
        bpy.app.timers.unregister(function)


def redraw() -> None:
    """Redibuja la barra de estado y la barra superior (el control 7) de todas las
    ventanas."""
    statusbar.redraw()
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in getattr(window.screen, "areas", ()):
            if area.type == "TOPBAR":
                area.tag_redraw()


def stale_count(_context: Any = None) -> int | None:
    """El número del control 7: lo obsoleto del proyecto, o ``None`` si no hay nada
    (``quick_access.set_count_provider``)."""
    found = _STATE.counts
    if found is None or found.obsolete <= 0:
        return None
    return found.obsolete


# El aviso de Ctrl+Z ---------------------------------------------------------------------------


def show_undo_notice(message: str) -> None:
    """Deja ``message`` en la barra de estado durante :data:`UNDO_NOTICE_S` s (RF-008-32: «Ctrl+Z
    no deshace la operación «gis.resample»: sigue en el proyecto»); uno nuevo sustituye al
    anterior."""
    _STATE.undo_text = message
    _STATE.undo_until = _clock() + UNDO_NOTICE_S
    _retire(expire_undo_notice)
    bpy.app.timers.register(expire_undo_notice, first_interval=UNDO_NOTICE_S, persistent=True)
    statusbar.redraw()


def undo_notice() -> str:
    """El aviso de Ctrl+Z que se ve ahora, o ""."""
    if _STATE.undo_text and _clock() < _STATE.undo_until:
        return _STATE.undo_text
    return ""


def expire_undo_notice() -> float | None:
    """La función del temporizador del aviso: al pasar su tiempo, lo quita, redibuja la barra
    de estado y se retira."""
    left = _STATE.undo_until - _clock()
    if _STATE.undo_text and left > 0:
        return left
    _STATE.undo_text = ""
    _retire(expire_undo_notice)
    statusbar.redraw()
    return None


# Campos de la barra de estado -----------------------------------------------------------------


def _counted(field: str, n: int) -> str:
    """El texto con número del campo ``field`` en el idioma de Geoblender, compuesto una vez
    por número e idioma (la barra lo pide en cada redibujo)."""
    key = (field, n, language())
    found = _STATE.texts.get(key)
    if found is None:
        if len(_STATE.texts) >= MAX_TEXTS:
            _STATE.texts.clear()
        if field == FIELD_INPUTS:
            found = tr("⚠ {n} inputs", n=n)
        else:
            found = tr("! {n} stale", n=n)
        _STATE.texts[key] = found
    return found


def inputs_text() -> str:
    """«⚠ n entradas» (RF-008-16), o "" si ninguna entrada cambió sin decidir."""
    found = _STATE.counts
    if found is None or found.inputs_changed <= 0:
        return ""
    return _counted(FIELD_INPUTS, found.inputs_changed)


def stale_text() -> str:
    """«! n obsoletos» (RF-008-28), o "" si no hay nada obsoleto."""
    found = _STATE.counts
    if found is None or found.obsolete <= 0:
        return ""
    return _counted(FIELD_STALE, found.obsolete)


def checking_text() -> str:
    """«Comprobando el proyecto… 42 %» (RF-008-58) mientras hay una comprobación, o ""."""
    return _session().status_text() or ""


def _operator_properties(idname: str) -> frozenset[str]:
    """Las propiedades del operador registrado de ``idname`` (las de un provisional, ninguna)."""
    cls = registered_class(idname)
    if cls is None:
        return frozenset()
    found = _STATE.properties.get(cls)
    if found is None:
        group, _, name = idname.partition(".")
        try:
            rna = getattr(getattr(bpy.ops, group), name).get_rna_type()
            found = frozenset(rna.properties.keys())
        except (AttributeError, KeyError, RuntimeError):
            found = frozenset()
        _STATE.properties[cls] = found
    return found


def _operator(layout: Any, idname: str, shown: str, *, icon: str = "NONE",
              emboss: bool = True, **values: Any) -> None:
    """Un botón de una orden del catálogo con ``shown`` (desactivado si su clase real aún no
    ha llegado) y las propiedades de ``values`` que tenga."""
    sub = layout.row(align=True)
    sub.enabled = is_available(idname)
    properties = sub.operator(idname, text=shown, icon=icon, translate=False, emboss=emboss)
    if values:
        names = _operator_properties(idname)
        for name, value in values.items():
            if name in names:
                setattr(properties, name, value)


def _draw_inputs(layout: Any, _context: Any) -> None:
    shown = inputs_text()
    if shown:
        _operator(layout, SHOW_INPUTS, shown, emboss=False)


def _draw_stale(layout: Any, _context: Any) -> None:
    shown = stale_text()
    if shown:
        sub = layout.row(align=True)
        sub.enabled = is_available(STALE_PANEL)
        sub.popover(STALE_PANEL, text=shown, translate=False)


def _draw_checking(layout: Any, _context: Any) -> None:
    shown = checking_text()
    if shown:
        row = layout.row(align=True)
        row.label(text=shown, translate=False)
        _operator(row, CANCEL_CHECKS, "", icon=CANCEL_ICON, emboss=False)


def _draw_undo(layout: Any, _context: Any) -> None:
    shown = undo_notice()
    if shown:
        layout.label(text=shown, icon=UNDO_ICON, translate=False)


def _px(shown: str, extra_units: int = 0) -> float:
    if not shown:
        return 0.0
    return statusbar.text_px(shown) + extra_units * float(compat.UI_UNIT_PX)


FIELDS: tuple[tuple[str, float, Callable[[Any, Any], None], Callable[[Any], float]], ...] = (
    (FIELD_INPUTS, 62.0, _draw_inputs, lambda _context: _px(inputs_text())),
    (FIELD_STALE, 63.0, _draw_stale, lambda _context: _px(stale_text(), 1)),
    (FIELD_CHECKING, 64.0, _draw_checking, lambda _context: _px(checking_text(), 1)),
    (FIELD_UNDO, 65.0, _draw_undo, lambda _context: _px(undo_notice(), 1)),
)
"""Los campos: clave, sitio en la barra (tras los de la 003 y antes de los trabajos de la
004, como en AR §6), dibujo y ancho a escala 1,0 (0 sin nada que mostrar)."""
FIELD_KEYS: tuple[str, ...] = tuple(key for key, *_rest in FIELDS)


# Lo obsoleto ----------------------------------------------------------------------------------


def _stale_icon() -> dict[str, Any]:
    return icons.icon_kwargs(STALE_ICON, native_icon(STALE_FALLBACK))


def _row_name(row: Any) -> str:
    """El nombre de una fila: el del dato o, de una operación, su nombre visible."""
    if row.item_kind == "operation":
        defn = contract.OPERATIONS.get(row.op_type)
        if defn is not None and defn.label_msgid:
            return text(defn.label_msgid)
    return row.name


def _draw_stale_row(layout: Any, row: Any) -> None:
    line = layout.row(align=True)
    line.label(text=_row_name(row), translate=False, **_stale_icon())
    line.label(text=row.module, translate=False)
    if row.review:
        line.label(text=tr("review"), translate=False)
        _operator(line, ACCEPT_REVIEW, text(catalog().commands[ACCEPT_REVIEW].label),
                  operation_uid=row.operation_uid)
    else:
        _operator(line, RECOMPUTE, tr("Recompute"), scope="ITEM", subject_uid=row.uid)
    cause = layout.row()
    cause.active = False
    cause.label(text=row.text, translate=False)


def draw_stale(layout: Any, context: Any) -> None:
    """El contenido de :class:`GEOBLENDER_PT_core_stale` (RF-008-28)."""
    reason = _session().unavailable()
    if reason is not None:
        layout.label(text=reason, icon="INFO", translate=False)
        return
    found = _STATE.counts
    total = found.obsolete if found is not None else 0
    layout.label(text=tr("Refresh · stale ({n})", n=total), translate=False, **_stale_icon())
    view = getattr(getattr(context, "window_manager", None), WINDOW_MANAGER_PROPERTY, None)
    rows = view.stale if view is not None and total > 0 else ()
    if not len(rows):
        layout.label(text=tr("Nothing is stale"), translate=False)
    else:
        column = layout.column()
        for row in rows:
            _draw_stale_row(column, row)
        hidden = total - len(rows)
        if hidden > 0:
            column.label(text=tr("… and {count} more", count=hidden), translate=False)
    layout.separator(type="LINE")
    draw_command(layout, RECOMPUTE, context=context)


class GEOBLENDER_PT_core_stale(bpy.types.Panel):
    """What is stale and why"""

    bl_idname = STALE_PANEL
    bl_label = "Stale results"
    bl_translation_context = "Geoblender"
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = STALE_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_stale(self.layout, context)


classes: tuple[type, ...] = (GEOBLENDER_PT_core_stale,)


# Instalación ----------------------------------------------------------------------------------


def install() -> None:
    """Registra los campos de la barra de estado (después de ``statusbar.install``), el número
    del control 7 y la escucha del proyecto de la sesión; con un proyecto ya abierto, pone el
    temporizador. Idempotente («Reparar la interfaz» la vuelve a llamar)."""
    for key, order, draw, width in FIELDS:
        statusbar.register_field(key, priority=FIELD_PRIORITY, draw=draw, width_px=width,
                                 modes=FIELD_MODES, order=order)
    quick_access.set_count_provider(REFRESH, stale_count)
    project_session.add_listener(on_project_changed)
    if project_session.current() is not None and not bpy.app.timers.is_registered(
            indicator_tick):
        bpy.app.timers.register(indicator_tick, first_interval=INDICATOR_TICK_S,
                                persistent=True)


def uninstall() -> None:
    """Quita los campos, el número del control 7, la escucha y los temporizadores, y olvida
    los recuentos, las filas y el aviso."""
    for key in FIELD_KEYS:
        statusbar.unregister_field(key)
    if quick_access.count_provider(REFRESH) is stale_count:
        quick_access.set_count_provider(REFRESH, None)
    project_session.remove_listener(on_project_changed)
    _retire(indicator_tick)
    _retire(expire_undo_notice)
    _forget()
    _STATE.texts.clear()
    _STATE.properties.clear()
    _STATE.undo_text = ""
    _STATE.undo_until = 0.0
