# SPDX-License-Identifier: GPL-3.0-or-later
"""Los trabajos en segundo plano en la barra de estado (spec 004; RF-004-06, RF-004-07;
plan 004 §5.4.4 y §5.5; D-7).

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

Sin nada que mostrar, el campo no ocupa sitio (:func:`width_px` da 0) ni dibuja nada. Los
textos salen al dibujar, en el idioma de Geoblender: los estados con ``core.i18n.tr`` y
los mensajes del §8 con ``jobs.messages.render``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ...core.i18n import format_number, language, tr
from ...jobs import messages
from ...jobs.records import ErrorInfo
from ...jobs.runner import JobSnapshot
from .. import compat
from . import statusbar

if TYPE_CHECKING:
    from ..ops.jobs import StatusView

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
BUTTONS = 2
SEPARATOR = " · "
_STATE_TEXTS: dict[str, dict[str, str]] = {}  # idioma → estado → su nombre


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
    }


def state_text(state: str) -> str:
    """El nombre de un estado en el idioma de Geoblender («Terminado»); se traducen una
    vez por idioma (la barra de estado lo pide en cada redibujo)."""
    lang = language()
    texts = _STATE_TEXTS.get(lang)
    if texts is None:
        texts = _STATE_TEXTS[lang] = _state_texts()
    return texts.get(state, state)


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


def current_view() -> StatusView:
    """Lo que calculó el último ``tick`` del monitor de la sesión."""
    from ..ops import jobs as ops_jobs  # diferido: bl/ops importa bl/ui (ARQ-08)

    return ops_jobs.MONITOR.view()


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
    """Quita el campo «jobs»."""
    statusbar.unregister_field(FIELD_KEY)
