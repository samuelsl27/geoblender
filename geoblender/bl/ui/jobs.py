# SPDX-License-Identifier: GPL-3.0-or-later
"""Los trabajos en segundo plano en la barra de estado y en su lista (spec 004; RF-004-06,
RF-004-07, RF-004-08; plan 004 §5.4.4 y §5.5; D-7).

El campo «jobs» de la barra de estado de la 003 (``bl.ui.statusbar.register_field``,
prioridad 1, declarado para los dos modos: es lo único de Geoblender que se ve en modo
Blender, y solo mientras haya algo que mostrar). Sin ``append`` propio (contrato 5 del plan
003). Dibuja lo que calculó el último ``tick`` del monitor (``bl.ops.jobs.MONITOR``):

- mientras hay trabajos activos (RF-004-06): su número con el icono ``SORTTIME``; la barra
  de avance del más antiguo en curso («<nombre> · 42 %», 10 unidades de ancho; si todos
  esperan, «<nombre> · En cola»), su último mensaje y dos botones de icono: la lista de
  trabajos (``geoblender.jobs_show_jobs``) y cancelar el activo (``geoblender.jobs_cancel``);
- durante 10 s tras acabar uno (RF-004-07): su nombre, su estado y su duración en s
  («Cálculo · Terminado · 2,0 s») y, si no terminó bien, el mensaje del §8 en una línea
  (nunca una traza de Python), con el icono ``CHECKMARK``, ``ERROR`` o ``CANCEL``.

Sin nada que mostrar, el campo no ocupa sitio (:func:`width_px` da 0) ni dibuja nada.

La lista de trabajos (:class:`GEOBLENDER_PT_jobs_list`, RF-004-08) es una ventana emergente
(región de cabecera, como las de la 003: solo la abre ``geoblender.jobs_show_jobs`` con
``wm.call_panel``): su título, lo que ocupa la carpeta de los trabajos (medido al abrirla,
:func:`measure_folder`) y, por orden de llegada, una fila por trabajo del lanzador con su
nombre (y el icono de su estado), su estado («Cancelando» si se pidió pararlo), su avance
(el de la barra de estado, que nunca retrocede), su duración en s y, en gris, el intérprete
que lo ejecuta y su último mensaje (el del §8 si no terminó bien, sin traza). Con tres
botones: Cancelar (``geoblender.jobs_cancel`` con su ``job_uid``; los activos a los que no
se pidió parar), Registro (``wm.path_open`` sobre su ``job.log``, si existe) y Descartar
(``geoblender.jobs_clean`` con ``scope = ONE``; los terminados que ningún módulo incorporó,
mientras ese operador esté disponible).

Los textos salen al dibujar, en el idioma de Geoblender: los estados con ``core.i18n.tr`` y
los mensajes del §8 con ``jobs.messages.render``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bpy

from ...core.i18n import format_number, language, tr
from ...jobs import cleanup, messages
from ...jobs.records import ErrorInfo, InterpreterInfo
from ...jobs.runner import JobSnapshot
from ...jobs.worker_api import UNKNOWN_BLAS
from .. import compat
from . import commands, statusbar

if TYPE_CHECKING:
    from ..ops.jobs import JobMonitor, StatusView

FIELD_KEY = "jobs"
FIELD_PRIORITY = 1
FIELD_ORDER = 70.0  # tras los de la 003 (10–60)
FIELD_MODES = frozenset({statusbar.GEOBLENDER, statusbar.BLENDER})
BAR_UNITS = 10
"""Ancho de la barra de avance, en unidades de interfaz (plan §5.4.4)."""
ACTIVE_ICON = "SORTTIME"
NOTICE_ICONS: Mapping[str, str] = {
    "succeeded": "CHECKMARK",
    "failed": "ERROR",
    "timed_out": "ERROR",
    "cancelled": "CANCEL",
    "interrupted": "CANCEL",
}
SHOW_JOBS = "geoblender.jobs_show_jobs"
SHOW_JOBS_ICON = "COLLAPSEMENU"
CANCEL_JOB = "geoblender.jobs_cancel"
CANCEL_JOB_ICON = "X"
CLEAN_JOB = "geoblender.jobs_clean"
CLEAN_JOB_ICON = "TRASH"
OPEN_LOG = "wm.path_open"
OPEN_LOG_ICON = "TEXT"
FOLDER_ICON = "FILE_FOLDER"
BUTTONS = 2
SEPARATOR = " · "
NO_VALUE = "—"
"""La duración de un trabajo que no llegó a arrancar."""
CANCELLING = "cancelling"
"""Lo que se muestra como estado de uno en curso al que se pidió parar («Cancelando»)."""

PANEL = "GEOBLENDER_PT_jobs_list"
PANEL_UNITS = 34
STATE_UNITS = 5
LIST_BAR_UNITS = 6
DURATION_UNITS = 4
"""Anchos de la lista de trabajos y de sus columnas, en unidades de interfaz."""

_TEXTS: dict[tuple[str, str], dict[str, str]] = {}  # (tabla, idioma) → clave → texto
_FOLDER_MB: dict[Path, float] = {}  # la carpeta de los trabajos medida al abrir la lista


def _cached(table: str, build: Callable[[], dict[str, str]]) -> dict[str, str]:
    """Los textos de ``table`` en el idioma de Geoblender; se traducen una vez por idioma
    (la barra de estado y la lista los piden en cada redibujo)."""
    key = (table, language())
    texts = _TEXTS.get(key)
    if texts is None:
        texts = _TEXTS[key] = build()
    return texts


def _state_texts() -> dict[str, str]:
    """Estado de un trabajo → su nombre (los ``msgid``, en ``messages.toml``)."""
    return {
        "queued": tr("Queued"),
        "running": tr("Running"),
        "succeeded": tr("Succeeded"),
        "failed": tr("Failed"),
        "cancelled": tr("Cancelled"),
        "timed_out": tr("Timed out"),
        "interrupted": tr("Interrupted"),
        CANCELLING: tr("Cancelling"),
    }


def _interpreter_texts() -> dict[str, str]:
    """Tipo de intérprete → su nombre."""
    return {
        "blender": "Blender",
        "compute": tr("Compute engine"),
        "external": tr("External interpreter"),
    }


def state_text(state: str) -> str:
    """El nombre de un estado en el idioma de Geoblender («Terminado»)."""
    return _cached("states", _state_texts).get(state, state)


def error_text(error: ErrorInfo) -> str:
    """El mensaje de un error, en una línea y en el idioma de Geoblender: los del §8 con
    ``jobs.messages.render``; los propios de un cálculo, su texto (en inglés, su ``msgid``
    con sus valores). Nunca una traza de Python (RF-004-07)."""
    shown = language()
    if error.code in messages.MESSAGES:
        return messages.render(error.code, language=shown, **error.values)
    if shown != "es":
        try:
            return messages.one_line(error.msgid.format_map(dict(error.values)))
        except (KeyError, IndexError, ValueError, AttributeError):
            pass
    return messages.one_line(error.text)


def bar_text(current: JobSnapshot, percent: int) -> str:
    """El texto de la barra de avance: «<nombre> · 42 %» o «<nombre> · En cola»."""
    if current.state == "running":
        return current.name + SEPARATOR + tr("{percent}%", percent=percent)
    return current.name + SEPARATOR + state_text(current.state)


def notice_text(snapshot: JobSnapshot) -> str:
    """El aviso de un trabajo que acabó: nombre, estado, duración en s y, si no terminó
    bien, el mensaje del §8 (RF-004-07)."""
    seconds = format_number(snapshot.duration_s or 0.0, 1)
    parts = [snapshot.name, state_text(snapshot.state), f"{seconds} s"]
    if snapshot.state != "succeeded" and snapshot.error is not None:
        parts.append(error_text(snapshot.error))
    return SEPARATOR.join(parts)


def _monitor() -> JobMonitor:
    """El monitor de los trabajos de la sesión."""
    from ..ops import jobs as ops_jobs  # diferido: bl/ops importa bl/ui (ARQ-08)

    return ops_jobs.MONITOR


def current_view() -> StatusView:
    """Lo que calculó el último ``tick`` del monitor de la sesión."""
    return _monitor().view()


def _running_message(view: StatusView) -> str:
    current = view.current
    if current is None or current.state != "running":
        return ""
    return messages.one_line(current.message)


def draw(layout: Any, _context: Any) -> None:
    """Dibuja el campo «jobs» (nada si no hay nada que mostrar)."""
    view = current_view()
    if not view.visible:
        return
    row = layout.row(align=True)
    current = view.current
    if view.active and current is not None:
        row.label(text=str(view.active), icon=ACTIVE_ICON, translate=False)
        bar = row.row(align=True)
        bar.ui_units_x = BAR_UNITS
        bar.progress(factor=view.percent / 100, type="BAR",
                     text=bar_text(current, view.percent), translate=False)
        message = _running_message(view)
        if message:
            row.label(text=message, translate=False)
        row.operator(SHOW_JOBS, text="", icon=SHOW_JOBS_ICON, emboss=False)
        row.operator(CANCEL_JOB, text="", icon=CANCEL_JOB_ICON, emboss=False)
    notice = view.notice
    if notice is not None:
        if view.active:
            row.separator()
        row.label(text=notice_text(notice), icon=NOTICE_ICONS.get(notice.state, "INFO"),
                  translate=False)


def width_px(_context: Any) -> float:
    """Lo que ocupa el campo a escala 1,0 (0 si no hay nada que mostrar)."""
    view = current_view()
    if not view.visible:
        return 0.0
    unit = float(compat.UI_UNIT_PX)
    width = 0.0
    current = view.current
    if view.active and current is not None:
        width += unit + statusbar.text_px(str(view.active))
        width += BAR_UNITS * unit + BUTTONS * unit
        message = _running_message(view)
        if message:
            width += statusbar.text_px(message)
    if view.notice is not None:
        width += unit + statusbar.text_px(notice_text(view.notice))
    return width


def install() -> None:
    """Registra el campo «jobs» en la barra de estado (después de ``statusbar.install``)."""
    statusbar.register_field(FIELD_KEY, priority=FIELD_PRIORITY, draw=draw,
                             width_px=width_px, modes=FIELD_MODES, order=FIELD_ORDER)


def uninstall() -> None:
    """Quita el campo «jobs» y olvida la medida de la carpeta de los trabajos."""
    statusbar.unregister_field(FIELD_KEY)
    _FOLDER_MB.clear()


# Lista de trabajos (RF-004-08) -----------------------------------------------------------


def percent_of(frac: float) -> int:
    """Un avance (0–1) en % entero hacia abajo, acotado a 0–100 (lo que no es un número,
    0)."""
    if not isinstance(frac, int | float) or math.isnan(frac):
        return 0
    return math.floor(min(1.0, max(0.0, float(frac))) * 100 + 1e-9)


def job_state_text(snapshot: JobSnapshot) -> str:
    """El estado de un trabajo en la lista: el suyo o, en curso con la cancelación pedida,
    «Cancelando»."""
    if snapshot.state == "running" and snapshot.cancel_requested:
        return state_text(CANCELLING)
    return state_text(snapshot.state)


def job_icon(snapshot: JobSnapshot) -> str:
    """El icono de un trabajo: el de los activos o el del aviso de su estado final."""
    return ACTIVE_ICON if snapshot.active else NOTICE_ICONS.get(snapshot.state, "INFO")


def duration_text(seconds: float | None) -> str:
    """Una duración en s con un decimal («2,0 s»); «—» si el trabajo no arrancó."""
    if seconds is None:
        return NO_VALUE
    return f"{format_number(seconds, 1)} s"


def interpreter_text(info: InterpreterInfo | None) -> str:
    """El intérprete que ejecuta un trabajo: su tipo y las versiones de Python, numpy y su
    BLAS, si se conocen («Blender · Python 3.13.9 · numpy 2.3.4»); "" en la cola."""
    if info is None:
        return ""
    parts = [_cached("interpreters", _interpreter_texts).get(info.kind, info.kind)]
    if info.python:
        parts.append("Python " + info.python)
    if info.numpy:
        parts.append("numpy " + info.numpy)
    if info.blas and info.blas != UNKNOWN_BLAS:
        parts.append("BLAS " + info.blas)
    return SEPARATOR.join(parts)


def message_text(snapshot: JobSnapshot) -> str:
    """El último mensaje de un trabajo, en una línea: si no terminó bien, el del §8 en el
    idioma de Geoblender (nunca una traza)."""
    if snapshot.state != "succeeded" and snapshot.error is not None:
        return error_text(snapshot.error)
    return messages.one_line(snapshot.message)


def details_text(snapshot: JobSnapshot) -> str:
    """La línea gris de un trabajo: su intérprete y su último mensaje."""
    parts = (interpreter_text(snapshot.interpreter), message_text(snapshot))
    return SEPARATOR.join(part for part in parts if part)


def measure_folder(root: Path | None) -> float | None:
    """Mide los MB que ocupa la carpeta de los trabajos ``root`` y lo recuerda para la
    lista (se mide al abrirla, no en cada redibujo); con ``None``, olvida la medida."""
    _FOLDER_MB.clear()
    if root is None:
        return None
    try:
        size = cleanup.folder_size_mb(root)
    except OSError:
        return None
    _FOLDER_MB[Path(root)] = size
    return size


def folder_size(root: Path | None) -> float | None:
    """Lo que medía la carpeta ``root`` al abrir la lista (``None`` si no se midió)."""
    return None if root is None else _FOLDER_MB.get(Path(root))


def _draw_buttons(row: Any, snapshot: JobSnapshot, *, discard: bool) -> None:
    """Cancelar, Registro y Descartar, desactivados cuando no proceden."""
    cancel = row.row(align=True)
    cancel.enabled = snapshot.active and not snapshot.cancel_requested
    cancel.operator(CANCEL_JOB, text="", icon=CANCEL_JOB_ICON).job_uid = snapshot.job_uid
    log = row.row(align=True)
    log_file = snapshot.log_file
    log.enabled = log_file is not None and log_file.is_file()
    log.operator(OPEN_LOG, text="", icon=OPEN_LOG_ICON).filepath = (
        str(log_file) if log_file is not None else "")
    drop = row.row(align=True)
    drop.enabled = discard and not snapshot.active and not snapshot.ingested
    properties = drop.operator(CLEAN_JOB, text="", icon=CLEAN_JOB_ICON)
    if discard:  # el provisional de la 003 no tiene estas propiedades
        properties.scope = "ONE"
        properties.job_uid = snapshot.job_uid


def _draw_job(layout: Any, snapshot: JobSnapshot, *, frac: float, discard: bool) -> None:
    """La fila de un trabajo y, debajo, su línea gris."""
    column = layout.column(align=True)
    row = column.row(align=True)
    row.label(text=snapshot.name, icon=job_icon(snapshot), translate=False)
    state = row.row(align=True)
    state.ui_units_x = STATE_UNITS
    state.label(text=job_state_text(snapshot), translate=False)
    percent = percent_of(frac)
    bar = row.row(align=True)
    bar.ui_units_x = LIST_BAR_UNITS
    bar.progress(factor=percent / 100, type="BAR", text=tr("{percent}%", percent=percent),
                 translate=False)
    duration = row.row(align=True)
    duration.ui_units_x = DURATION_UNITS
    duration.alignment = "RIGHT"
    duration.label(text=duration_text(snapshot.duration_s), translate=False)
    _draw_buttons(row, snapshot, discard=discard)
    details = details_text(snapshot)
    if details:
        line = column.row(align=True)
        line.active = False
        line.label(text=details, translate=False)


def draw_list(layout: Any) -> None:
    """Dibuja la lista de trabajos del lanzador de la sesión (RF-004-08)."""
    monitor = _monitor()
    runner = monitor.runner
    layout.label(text=tr("Background jobs"), icon=ACTIVE_ICON, translate=False)
    size = folder_size(runner.jobs_root) if runner is not None else None
    if size is not None:
        layout.label(text=tr("Jobs folder: {size} MB", size=format_number(size, 1)),
                     icon=FOLDER_ICON, translate=False)
    snapshots = runner.snapshots() if runner is not None else []
    if not snapshots:
        layout.label(text=tr("There are no background jobs"), translate=False)
        return
    discard = commands.is_available(CLEAN_JOB)
    for snapshot in snapshots:
        layout.separator()
        _draw_job(layout, snapshot, frac=monitor.shown_frac(snapshot), discard=discard)


class GEOBLENDER_PT_jobs_list(bpy.types.Panel):
    """Running and finished jobs with their progress"""

    bl_idname = PANEL
    bl_label = "Background jobs"
    bl_translation_context = commands.TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_list(self.layout)


classes: tuple[type, ...] = (GEOBLENDER_PT_jobs_list,)
