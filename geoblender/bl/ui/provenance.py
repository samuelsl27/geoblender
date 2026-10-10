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

**Parámetros del proyecto** (:class:`GEOBLENDER_PT_core_parameters`, ventana emergente que
abre ``geoblender.core_show_parameters``; RF-008-06, RF-008-59; T50): filtros por módulo, tipo
y marca; la lista (:class:`GEOBLENDER_UL_core_parameters`) con la clave, el valor con su
unidad, la insignia de tipo ([HIP] en ámbar), las marcas «sin confirmar» y «revisar», el
origen, el decisor y la fecha; del seleccionado, su origen, su decisión, lo que hay que revisar,
el aviso de divergencia de su última cifra calculada con «Usar el valor calculado…» (Cambiar
relleno con la cifra), el historial completo (:class:`GEOBLENDER_UL_core_parameter_history`) y
Cambiar parámetro… y Confirmar parámetro; en solo lectura, desactivados y con el motivo.
:func:`fill_parameters` lee la lista de ``core.params`` (``ParameterStore.list`` con los
filtros de la vista) y :func:`fill_history`, el historial y el aviso del seleccionado; los
llaman la orden que abre el panel, Cambiar y Confirmar al escribir, y los filtros y la
selección al cambiar. Las filas viven en ``WindowManager.geoblender_provenance`` (D16), como
texto ya presentado: ningún valor pasa por una propiedad flotante.

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
from ...core.params import HistoryAction, ParameterFilter, ParameterStore, ParamKind, ParamMark
from ...core.params.store import shown_value
from ...core.provenance import contract
from ...core.timeutil import parse_utc
from .. import compat
from ..props.provenance import FILTER_ALL, WINDOW_MANAGER_PROPERTY
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

PARAMETERS_PANEL = "GEOBLENDER_PT_core_parameters"
PARAMETERS_LIST = "GEOBLENDER_UL_core_parameters"
HISTORY_LIST = "GEOBLENDER_UL_core_parameter_history"
SET_PARAMETER = "geoblender.core_set_parameter"
CONFIRM_PARAMETER = "geoblender.core_confirm_parameter"
PARAMETERS_PANEL_UNITS = 44
PARAMETER_ROWS = 8  # filas visibles de la lista (después, se desplaza)
HISTORY_ROWS = 5
# Ancho (unidades) de cada columna de la lista de parámetros y del historial.
PARAMETER_COLUMNS = (9.0, 5.5, 2.5, 5.0, 10.0, 7.0, 4.0)
HISTORY_COLUMNS = (1.5, 3.5, 4.5, 2.5, 3.5, 5.0, 3.5, 8.0, 6.0, 5.5)

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
        self.filling = False  # se están regenerando las filas de los parámetros


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
    """Olvida los recuentos y las filas de lo obsoleto; dice si había algo que mostrar."""
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
    """Lo que se apunta en ``project_session``: olvida lo del proyecto anterior (también la
    lista de parámetros) y, con uno nuevo, pone el temporizador (lee en su primer tic, no al
    abrir: RNF-002-02)."""
    had = _forget()
    _clear_parameters()
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
              emboss: bool = True, enabled: bool = True, **values: Any) -> None:
    """Un botón de una orden del catálogo con ``shown`` (desactivado si su clase real aún no
    ha llegado o sin ``enabled``) y las propiedades de ``values`` que tenga."""
    sub = layout.row(align=True)
    sub.enabled = enabled and is_available(idname)
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


# Parámetros del proyecto (T50) -----------------------------------------------------------------


def _write_unavailable() -> str | None:
    """Por qué no se pueden cambiar ni confirmar los parámetros ahora (sin proyecto, sin la
    procedencia o en solo lectura), o ``None``."""
    from ..ops import core_provenance  # al usarlo: bl/ops importa bl/ui (ARQ-08)

    return core_provenance.write_unavailable()


def _project() -> Project | None:
    """El proyecto de la sesión, si tiene la procedencia (también en solo lectura)."""
    session = _session()
    return session.project if session.unavailable() is None else None


def _filters(view: Any) -> ParameterFilter:
    """Los filtros de la lista (``core.params``; «Cualquiera» no filtra)."""
    module = None if view.filter_module == FILTER_ALL else view.filter_module
    kind = None if view.filter_kind == FILTER_ALL else ParamKind[view.filter_kind]
    mark = None if view.filter_mark == FILTER_ALL else ParamMark[view.filter_mark]
    return ParameterFilter(module=module, kind=kind, mark=mark)


def _selected(view: Any) -> Any | None:
    """La fila seleccionada de la lista de parámetros, o ``None``."""
    rows = view.parameters
    index = view.parameter_index
    return rows[index] if 0 <= index < len(rows) else None


def _local(moment: str, pattern: str = "%d/%m/%Y") -> str:
    """Una hora UTC guardada, en hora local como la lee una persona (``24/09/2026``)."""
    try:
        return parse_utc(moment).astimezone().strftime(pattern)
    except ValueError:
        return moment


def fill_parameters() -> int:
    """Regenera las filas de la lista de parámetros desde el proyecto de la sesión, con los
    filtros de la vista (RF-008-06; ``ParameterStore.list``), conserva el seleccionado si
    sigue en la lista y lee su historial (:func:`fill_history`). Sin proyecto con la
    procedencia, la lista queda vacía. Devuelve cuántas filas hay. Si no se puede leer el
    proyecto, el error sigue y las filas quedan como estaban."""
    view = _view()
    if view is None:
        return 0
    project = _project()
    found = [] if project is None else ParameterStore(project).list(_filters(view))
    chosen = _selected(view)
    key = None if chosen is None else chosen.key
    _STATE.filling = True
    try:
        rows = view.parameters
        rows.clear()
        for item in found:
            record = item.record
            row = rows.add()
            row.uid = record.uid
            row.key = record.key
            row.module = record.module
            row.value = item.shown
            row.kind = str(record.kind)
            row.unconfirmed = record.unconfirmed
            row.review = ParamMark.REVIEW in item.marks
            row.review_text = item.review_text
            row.source = record.source
            row.decided_by = record.decided_by
            row.decided_at = _local(record.decided_at)
        keys = [item.record.key for item in found]
        view.parameter_index = keys.index(key) if key in keys else 0
    finally:
        _STATE.filling = False
    fill_history()
    return len(found)


def fill_history() -> None:
    """Regenera el historial del parámetro seleccionado (RF-008-06; ``ParameterStore.history``)
    y su aviso de divergencia (RF-008-59: el de su última cifra calculada, con la cifra que se
    adoptaría). Si no se puede leer el proyecto, el error sigue."""
    view = _view()
    if view is None or _STATE.filling:
        return
    project = _project()
    chosen = _selected(view)
    entries: list[Any] = []
    warning = None
    if project is not None and chosen is not None:
        from ...core.provenance.figures import parameter_divergence  # al usarlo

        with project.read() as conn:
            entries = ParameterStore(project).history(chosen.key, conn=conn)
            warning = parameter_divergence(conn, chosen.uid)
    history = view.parameter_history
    history.clear()
    for entry in entries:
        row = history.add()
        row.rev = entry.rev
        row.action = str(entry.action)
        row.value = shown_value(entry.value, entry.unit)
        row.kind = str(entry.kind)
        row.unconfirmed = entry.unconfirmed
        row.decided_by = entry.decided_by
        row.decided_at = _local(entry.decided_at)
        row.reason = entry.reason or ""
        row.changed_by = entry.changed_by
        row.changed_at = _local(entry.changed_at, "%d/%m/%Y %H:%M")
    view.history_index = max(0, len(history) - 1)
    view.parameter_divergence = "" if warning is None else warning.render(language())
    view.parameter_figure_uid = "" if warning is None else warning.figure_uid


def _clear_parameters() -> None:
    """Vacía la lista de parámetros, el historial y el aviso (otro proyecto, ninguno)."""
    view = _view()
    if view is None or not (len(view.parameters) or len(view.parameter_history)
                            or view.parameter_divergence):
        return
    _STATE.filling = True
    try:
        view.parameters.clear()
        view.parameter_history.clear()
        view.parameter_index = 0
        view.parameter_divergence = ""
        view.parameter_figure_uid = ""
    finally:
        _STATE.filling = False


def parameters_changed() -> None:
    """Un filtro cambió (``bl.props.provenance``): :func:`fill_parameters`; si no se puede
    leer el proyecto, queda en el registro técnico."""
    if _STATE.filling:
        return
    try:
        fill_parameters()
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo leer la lista de parámetros del proyecto", exc_info=True)


def selection_changed() -> None:
    """Cambió el seleccionado (``bl.props.provenance``): :func:`fill_history`."""
    if _STATE.filling:
        return
    try:
        fill_history()
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo leer el historial del parámetro", exc_info=True)


def badge(kind: str) -> str:
    """La insignia de un tipo ([MED], [CAL], [ADO] o [HIP]) en el idioma de Geoblender."""
    if kind == ParamKind.MEDIDO:
        return tr("[MEA]")
    if kind == ParamKind.CALCULADO:
        return tr("[CAL]")
    if kind == ParamKind.ADOPTADO:
        return tr("[ADO]")
    return tr("[HYP]")


def _action_text(action: str) -> str:
    if action == HistoryAction.DEFAULT:
        return tr("Default value")
    if action == HistoryAction.CREATE:
        return tr("Created")
    if action == HistoryAction.CONFIRM:
        return tr("Confirmed")
    return tr("Changed")


def _cell(layout: Any, shown: str, units: float, *, alert: bool = False) -> None:
    """Una columna de una fila de lista: ``shown`` con ``units`` de ancho."""
    cell = layout.row(align=True)
    cell.ui_units_x = units
    cell.alert = alert
    cell.label(text=shown, translate=False)


def _marks_text(unconfirmed: bool, review: bool = False) -> str:
    marks = []
    if unconfirmed:
        marks.append(tr("unconfirmed"))
    if review:
        marks.append(tr("review"))
    return " · ".join(marks)


def draw_parameter_row(layout: Any, row: Any) -> None:
    """Una fila de la lista de parámetros (RF-008-06): clave, valor con su unidad, insignia de
    tipo ([HIP] en ámbar), marcas, origen, decisor y fecha."""
    line = layout.row(align=True)
    key, value, kind, marks, source, decided_by, decided_at = PARAMETER_COLUMNS
    _cell(line, row.key, key)
    _cell(line, row.value, value)
    _cell(line, badge(row.kind), kind, alert=row.kind == ParamKind.HIPOTESIS)
    _cell(line, _marks_text(row.unconfirmed, row.review), marks, alert=row.review)
    _cell(line, row.source, source)
    _cell(line, row.decided_by, decided_by)
    _cell(line, row.decided_at, decided_at)


def draw_history_row(layout: Any, row: Any) -> None:
    """Una fila del historial (RF-008-02, RF-008-06): revisión, qué fue, valor, insignia,
    «sin confirmar», decisor y fecha de la decisión, motivo, y quién y cuándo lo registró."""
    line = layout.row(align=True)
    rev, action, value, kind, marks, decided_by, decided_at, reason, by, at = HISTORY_COLUMNS
    _cell(line, str(row.rev), rev)
    _cell(line, _action_text(row.action), action)
    _cell(line, row.value, value)
    _cell(line, badge(row.kind), kind, alert=row.kind == ParamKind.HIPOTESIS)
    _cell(line, _marks_text(row.unconfirmed), marks)
    _cell(line, row.decided_by, decided_by)
    _cell(line, row.decided_at, decided_at)
    _cell(line, row.reason, reason)
    _cell(line, row.changed_by, by)
    _cell(line, row.changed_at, at)


def _draw_selected(layout: Any, view: Any, row: Any, blocked: str | None) -> None:
    """Lo del parámetro seleccionado: su decisión, lo que hay que revisar, su aviso de
    divergencia, su historial y Cambiar y Confirmar (desactivados con ``blocked``)."""
    details = layout.column(align=True)
    details.label(text=row.key, translate=False)
    details.label(text=tr("Source: {source}", source=row.source), translate=False)
    details.label(text=tr("Decided by {who} on {date}", who=row.decided_by,
                          date=row.decided_at), translate=False)
    if row.review and row.review_text:
        note = details.row()
        note.alert = True
        note.label(text=row.review_text, icon="ERROR", translate=False)
    writable = blocked is None
    if view.parameter_divergence:
        warning = layout.row()
        warning.alert = True
        warning.label(text=view.parameter_divergence, icon="ERROR", translate=False)
        _operator(layout, SET_PARAMETER, tr("Use the calculated value…"), enabled=writable,
                  key=row.key, from_figure_uid=view.parameter_figure_uid)
    layout.label(text=tr("History"), translate=False)
    layout.template_list(HISTORY_LIST, "", view, "parameter_history", view, "history_index",
                         rows=HISTORY_ROWS)
    buttons = layout.row(align=True)
    commands = catalog().commands
    _operator(buttons, SET_PARAMETER, text(commands[SET_PARAMETER].label), enabled=writable,
              key=row.key)
    _operator(buttons, CONFIRM_PARAMETER, text(commands[CONFIRM_PARAMETER].label),
              enabled=writable and (row.unconfirmed or row.review), key=row.key)
    if blocked is not None:
        layout.label(text=blocked, icon="LOCKED", translate=False)


def draw_parameters(layout: Any, context: Any) -> None:
    """El contenido de :class:`GEOBLENDER_PT_core_parameters` (RF-008-06, RF-008-59)."""
    layout.label(text=tr("Project parameters"), translate=False)
    reason = _session().unavailable()
    if reason is not None:
        layout.label(text=reason, icon="INFO", translate=False)
        return
    view = getattr(getattr(context, "window_manager", None), WINDOW_MANAGER_PROPERTY, None)
    if view is None:
        return
    filters = layout.row(align=True)
    filters.prop(view, "filter_module", text=tr("Module"), translate=False)
    filters.prop(view, "filter_kind", text=tr("Type"), translate=False)
    filters.prop(view, "filter_mark", text=tr("Mark"), translate=False)
    layout.template_list(PARAMETERS_LIST, "", view, "parameters", view, "parameter_index",
                         rows=PARAMETER_ROWS)
    row = _selected(view)
    if row is None:
        layout.label(text=tr("No parameters"), translate=False)
        return
    _draw_selected(layout, view, row, _write_unavailable())


class GEOBLENDER_UL_core_parameters(bpy.types.UIList):
    """The project parameters"""

    bl_idname = PARAMETERS_LIST

    def draw_item(self, _context: Any, layout: Any, _data: Any, item: Any, _icon: int,
                  _active_data: Any, _active_property: str, _index: int = 0,
                  _flt_flag: int = 0) -> None:
        draw_parameter_row(layout, item)


class GEOBLENDER_UL_core_parameter_history(bpy.types.UIList):
    """The history of the selected parameter"""

    bl_idname = HISTORY_LIST

    def draw_item(self, _context: Any, layout: Any, _data: Any, item: Any, _icon: int,
                  _active_data: Any, _active_property: str, _index: int = 0,
                  _flt_flag: int = 0) -> None:
        draw_history_row(layout, item)


class GEOBLENDER_PT_core_parameters(bpy.types.Panel):
    """Parameters with their type, provenance and history"""

    bl_idname = PARAMETERS_PANEL
    bl_label = "Project parameters"
    bl_translation_context = "Geoblender"
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = PARAMETERS_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_parameters(self.layout, context)


classes: tuple[type, ...] = (
    GEOBLENDER_PT_core_stale,
    GEOBLENDER_UL_core_parameters,
    GEOBLENDER_UL_core_parameter_history,
    GEOBLENDER_PT_core_parameters,
)


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
    los recuentos, las filas (también las de los parámetros) y el aviso."""
    for key in FIELD_KEYS:
        statusbar.unregister_field(key)
    if quick_access.count_provider(REFRESH) is stale_count:
        quick_access.set_count_provider(REFRESH, None)
    project_session.remove_listener(on_project_changed)
    _retire(indicator_tick)
    _retire(expire_undo_notice)
    _forget()
    _clear_parameters()
    _STATE.texts.clear()
    _STATE.properties.clear()
    _STATE.undo_text = ""
    _STATE.undo_until = 0.0
