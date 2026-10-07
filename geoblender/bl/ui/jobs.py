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
:func:`measure_folder`) y una fila por trabajo con su nombre (y el icono de su estado), su
estado («Cancelando» si se pidió pararlo), su avance (el de la barra de estado, que nunca
retrocede), su duración en s y, en gris, el intérprete que lo ejecuta y su último mensaje
(el del §8 si no terminó bien, sin traza). Con tres botones: Cancelar
(``geoblender.jobs_cancel`` con su ``job_uid``; los activos del lanzador a los que no se
pidió parar), Registro (``wm.path_open`` sobre su ``job.log``, si existe) y Descartar
(``geoblender.jobs_clean`` con ``scope = ONE``; los terminados que ningún módulo incorporó,
mientras ese operador esté disponible).

Los trabajos de la lista (:func:`listed_jobs`, RF-004-08 y RF-004-13): primero los
**guardados** en las carpetas de trabajos que no son del lanzador (de otra sesión de
Blender o de antes de desactivar Geoblender: el lanzador nuevo no los conoce), por
identificador; después los del lanzador, por orden de llegada; ninguno dos veces. Los
guardados se leen al abrir la lista (``bl.ops.jobs.read_stored_jobs``, que deja antes
«Interrumpido» los que constaban activos) o, si se dibuja sin haberlos leído para ese
lanzador, en su primer dibujo; nunca al registrar. Se olvidan al desregistrar y al cambiar
de proyecto (:func:`forget_stored`), y los descartados salen al momento.

Los textos salen al dibujar, en el idioma de Geoblender: los estados con ``core.i18n.tr`` y
los mensajes del §8 con ``jobs.messages.render``.

El motor de cálculo (spec 004, T32; RF-004-19, RF-004-20; plan 004 §5.5): la lista lleva,
bajo su título, el estado del motor del lanzador (:func:`engine_state_text`: «Listo · numpy
2.5.3 · BLAS scipy-openblas · 2000 × 2000 en 0,043 s», «No instalado», desactualizado o
dañado). ``geoblender.jobs_setup_runtime`` (``bl/ops/jobs.py``) dibuja aquí su diálogo de
consentimiento (:func:`draw_consent`: origen, una fila por paquete con su versión y su
licencia, y las que incluye su rueda, MB de descarga y en disco, carpeta de destino y que no
cambia el Python de Blender), el estado del motor con sus botones (:func:`draw_engine`) y la
confirmación de quitarlo (:func:`draw_remove`). Los botones del diálogo de consentimiento,
«Instalar» y «Cancelar», son de Geoblender y van en su idioma (:func:`draw_consent_buttons`,
T40; ADR-0012): ``template_popup_confirm`` sustituye a los de ``invoke_props_dialog``, cuyo
«Cancel» es el de Blender, en el idioma de Blender.

El intérprete externo (spec 004, T33; RF-004-26): si el lanzador tiene uno, la lista dice,
bajo el estado del motor, que los trabajos del motor corren con él («Intérprete externo
(desarrollo): <ruta>»), y la fila de cada trabajo que corrió en él lo indica con sus
versiones de Python y numpy («Intérprete externo · Python 3.13… · numpy …»).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import bpy

from ...core.i18n import format_number, language, tr
from ...jobs import cleanup, messages
from ...jobs import runtime as jobs_runtime
from ...jobs.records import ErrorInfo, InterpreterInfo
from ...jobs.runner import JobRunner, JobSnapshot
from ...jobs.runtime import ComputeEnvironment, InstallPlan, WheelSource
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

SETUP_RUNTIME = "geoblender.jobs_setup_runtime"
CONSENT_CONTEXT = "EXEC_DEFAULT"  # «Instalar» ejecuta: no vuelve a abrir el diálogo (T40)
ENGINE_ICON = "PREFERENCES"
EXTERNAL_ICON = "CONSOLE"
"""El icono de la línea del intérprete externo en la lista de trabajos (RF-004-26)."""
SOURCE_ICONS: Mapping[str, str] = {
    jobs_runtime.SOURCE_WHEELHOUSE: "DISK_DRIVE",
    jobs_runtime.SOURCE_PYPI: "WORLD",
}
SETUP_ICONS: Mapping[str, str] = {
    "INSTALL": "IMPORT",
    "UPDATE": "IMPORT",
    "VERIFY": "CHECKMARK",
    "REPAIR": "TOOL_SETTINGS",
    "REMOVE": "TRASH",
}
NOTE_ICON = "INFO"
PACKAGE_UNITS = 6
VERSION_UNITS = 4
"""Anchos de las columnas Paquete y Versión del diálogo de consentimiento."""
ENGINE_ACTIONS: Mapping[str, tuple[str, ...]] = {
    # Lo que ofrece el estado del motor según cómo está (plan 004 §5.3.2).
    jobs_runtime.STATUS_READY: ("VERIFY", "REPAIR", "REMOVE"),
    jobs_runtime.STATUS_MISSING: ("INSTALL",),
    jobs_runtime.STATUS_OUTDATED: ("UPDATE",),
    jobs_runtime.STATUS_BROKEN: ("REPAIR", "REMOVE"),
}

_TEXTS: dict[tuple[str, str], dict[str, str]] = {}  # (tabla, idioma) → clave → texto
_FOLDER_MB: dict[Path, float] = {}  # la carpeta de los trabajos medida al abrir la lista


class _StoredJobs:
    """Los trabajos guardados que leyó la lista al abrirse (``JobRunner.stored_snapshots``)
    y el lanzador para el que se leyeron (``None``: sin leer)."""

    def __init__(self) -> None:
        self.runner: JobRunner | None = None
        self.snapshots: tuple[JobSnapshot, ...] = ()

    def clear(self) -> None:
        self.runner = None
        self.snapshots = ()


_STORED = _StoredJobs()


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


def _ops() -> ModuleType:
    """``bl.ops.jobs``, importado al usarlo: bl/ops importa bl/ui (ARQ-08)."""
    from ..ops import jobs as ops_jobs

    return ops_jobs


def _monitor() -> JobMonitor:
    """El monitor de los trabajos de la sesión."""
    return _ops().MONITOR


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
    _STORED.clear()


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


def remember_stored(runner: JobRunner, snapshots: Iterable[JobSnapshot]) -> None:
    """Recuerda para la lista los trabajos guardados leídos para ``runner``."""
    _STORED.runner = runner
    _STORED.snapshots = tuple(snapshots)


def stored_jobs(runner: JobRunner | None) -> tuple[JobSnapshot, ...] | None:
    """Los trabajos guardados que se leyeron para ``runner`` (``None`` si aún no se leyeron
    para él)."""
    if runner is None or _STORED.runner is not runner:
        return None
    return _STORED.snapshots


def forget_stored(job_uids: Iterable[str] | None = None) -> None:
    """Olvida los trabajos guardados ``job_uids`` (los que se acaban de borrar) o, sin
    ellos, todos, que se vuelven a leer en el siguiente dibujo de la lista (al cambiar de
    proyecto)."""
    if job_uids is None:
        _STORED.clear()
        return
    gone = set(job_uids)
    _STORED.snapshots = tuple(s for s in _STORED.snapshots if s.job_uid not in gone)


def listed_jobs(runner: JobRunner | None) -> list[JobSnapshot]:
    """Los trabajos de la lista (RF-004-08): primero los guardados leídos para ``runner``
    (por identificador) y después los de ``runner`` (por orden de llegada), sin repetir
    ninguno; sin lanzador, ninguno."""
    if runner is None:
        return []
    session = list(runner.snapshots())
    own = {snapshot.job_uid for snapshot in session}
    stored = [s for s in stored_jobs(runner) or () if s.job_uid not in own]
    return [*stored, *session]


def _draw_buttons(row: Any, snapshot: JobSnapshot, *, discard: bool) -> None:
    """Cancelar, Registro y Descartar, desactivados cuando no proceden."""
    cancel = row.row(align=True)
    cancel.enabled = (snapshot.active and not snapshot.cancel_requested
                      and not snapshot.stored)
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
    """Dibuja la lista de trabajos (RF-004-08): los guardados y los del lanzador de la
    sesión. Si los guardados aún no se leyeron para ese lanzador, los lee (primer
    dibujo)."""
    monitor = _monitor()
    runner = monitor.runner
    if runner is not None and stored_jobs(runner) is None:
        _ops().read_stored_jobs(runner)
    layout.label(text=tr("Background jobs"), icon=ACTIVE_ICON, translate=False)
    size = folder_size(runner.jobs_root) if runner is not None else None
    if size is not None:
        layout.label(text=tr("Jobs folder: {size} MB", size=format_number(size, 1)),
                     icon=FOLDER_ICON, translate=False)
    engine = getattr(runner, "runtime", None) if runner is not None else None
    if isinstance(engine, ComputeEnvironment):
        layout.label(text=tr("Compute engine: {state}", state=engine_state_text(engine)),
                     icon=ENGINE_ICON, translate=False)
    external = getattr(runner, "external_python", None) if runner is not None else None
    if external is not None:
        layout.label(text=tr("External interpreter (development): {path}", path=str(external)),
                     icon=EXTERNAL_ICON, translate=False)
    snapshots = listed_jobs(runner)
    if not snapshots:
        layout.label(text=tr("There are no background jobs"), translate=False)
        return
    discard = commands.is_available(CLEAN_JOB)
    for snapshot in snapshots:
        layout.separator()
        _draw_job(layout, snapshot, frac=monitor.shown_frac(snapshot), discard=discard)


# Motor de cálculo (RF-004-19, RF-004-20) -------------------------------------------------


def _engine_state_texts() -> dict[str, str]:
    """Estado del motor → su texto (sin los datos de la verificación)."""
    return {
        jobs_runtime.STATUS_READY: tr("Ready"),
        jobs_runtime.STATUS_MISSING: tr("Not installed"),
        jobs_runtime.STATUS_OUTDATED: tr(
            "Out of date: it belongs to another version of Geoblender"),
        jobs_runtime.STATUS_BROKEN: tr("Damaged or not verified: it has to be repaired"),
    }


def _action_texts() -> dict[str, str]:
    """Acción de ``geoblender.jobs_setup_runtime`` → el texto de su botón."""
    return {
        "INSTALL": tr("Install"),
        "UPDATE": tr("Update"),
        "VERIFY": tr("Verify"),
        "REPAIR": tr("Repair"),
        "REMOVE": tr("Remove"),
    }


def _verified_text(check: object) -> str | None:
    """«Listo · numpy … · BLAS … · 2000 × 2000 en … s» de la verificación ``check`` (la de
    ``runtime.json``), o ``None`` si le falta algo."""
    if not isinstance(check, Mapping):
        return None
    numpy, blas = check.get("numpy"), check.get("blas")
    n, seconds = check.get("matmul_n"), check.get("matmul_s")
    if not (isinstance(numpy, str) and isinstance(blas, str) and type(n) is int
            and isinstance(seconds, int | float) and not isinstance(seconds, bool)):
        return None
    return tr("Ready · numpy {numpy} · BLAS {blas} · {n} × {n} in {seconds} s", numpy=numpy,
              blas=blas, n=n, seconds=format_number(seconds, 3))


def engine_state_text(env: ComputeEnvironment) -> str:
    """El estado del motor de cálculo ``env`` en una línea: listo, con lo que midió su última
    verificación («Listo · numpy 2.5.3 · BLAS scipy-openblas · 2000 × 2000 en 0,043 s»), no
    instalado, desactualizado (es de otra versión de Geoblender) o dañado. Solo lee."""
    status = env.status()
    if status == jobs_runtime.STATUS_READY:
        info = jobs_runtime.read_runtime_info(env.path) or {}
        verified = _verified_text(info.get(jobs_runtime.VERIFICATION_KEY))
        if verified is not None:
            return verified
    return _cached("engine", _engine_state_texts).get(status, status)


def source_text(source: WheelSource) -> str:
    """El origen de las ruedas: «Origen: almacén de ruedas <carpeta>» o «Origen: PyPI
    (internet)»."""
    if source.kind == jobs_runtime.SOURCE_WHEELHOUSE:
        return tr("Source: wheel store {folder}", folder=str(source.folder))
    return tr("Source: PyPI (internet)")


def _cell(row: Any, text: str, units: float) -> None:
    """Una celda de ``units`` unidades de ancho con ``text``."""
    cell = row.row(align=True)
    cell.ui_units_x = units
    cell.label(text=text, translate=False)


def draw_consent(layout: Any, plan: InstallPlan) -> None:
    """El diálogo de consentimiento (RF-004-20; plan 004 §5.5), antes de hacer nada: el
    origen, una fila por paquete con su versión y su licencia (y, en gris, las que incluye
    su rueda), los MB de descarga y en disco del lock, la carpeta de destino y que no cambia
    el Python de Blender. Sus botones «Instalar» y «Cancelar» los dibuja
    :func:`draw_consent_buttons`."""
    layout.label(text=source_text(plan.source),
                 icon=SOURCE_ICONS.get(plan.source.kind, "INFO"), translate=False)
    table = layout.column(align=True)
    header = table.row(align=True)
    header.active = False
    _cell(header, tr("Package"), PACKAGE_UNITS)
    _cell(header, tr("Version"), VERSION_UNITS)
    header.label(text=tr("Licence"), translate=False)
    for package in plan.packages:
        row = table.row(align=True)
        _cell(row, package.name, PACKAGE_UNITS)
        _cell(row, package.version, VERSION_UNITS)
        row.label(text=package.license, translate=False)
        if package.bundled_licenses:
            bundled = table.row(align=True)
            bundled.active = False
            bundled.label(text=tr("Also includes: {licenses}",
                                  licenses=", ".join(package.bundled_licenses)),
                          translate=False)
    layout.label(text=tr("Download: {download} MB · On disk: {disk} MB",
                         download=format_number(plan.download_mb, 1),
                         disk=format_number(plan.disk_mb, 1)), translate=False)
    layout.label(text=tr("Folder: {folder}", folder=str(plan.destination)), icon=FOLDER_ICON,
                 translate=False)
    note = layout.row()
    note.active = False
    note.label(text=tr("Used only in the heavy calculations, in a separate process; it does "
                       "not change Blender's Python"), icon=NOTE_ICON, translate=False)


def draw_consent_buttons(layout: Any, *, action: str, source: str,
                         confirmation: str) -> None:
    """Los botones del diálogo de consentimiento, al final, en el idioma de Geoblender
    (RF-004-20, ADR-0012; T40): «Instalar» y «Cancelar» (``template_popup_confirm``, que en
    un ``invoke_props_dialog`` sustituye a sus botones; el de cancelar de Blender va en el
    idioma de Blender). «Instalar» ejecuta ``geoblender.jobs_setup_runtime`` con ``action``,
    ``source`` y ``confirmation`` (la huella del plan enseñado) sin volver a abrir el
    diálogo; «Cancelar» lo cierra sin ejecutar nada (RF-004-19)."""
    layout.operator_context = CONSENT_CONTEXT
    properties = layout.template_popup_confirm(SETUP_RUNTIME, text=tr("Install"),
                                               translate=False, cancel_text=tr("Cancel"))
    properties.action = action
    properties.source = source
    properties.confirmation = confirmation


def draw_engine(layout: Any, env: ComputeEnvironment, *, running: bool,
                last_error: str | None) -> None:
    """El estado del motor de cálculo (``action = STATUS``): título, estado, carpeta, lo
    que pasó en el último intento si falló y, si no se está instalando ni verificando, los
    botones de lo que se puede hacer con él (con el motor listo: Verificar, Reparar y
    Quitar)."""
    layout.label(text=tr("Compute engine"), icon=ENGINE_ICON, translate=False)
    layout.label(text=tr("State: {state}", state=engine_state_text(env)), translate=False)
    layout.label(text=tr("Folder: {folder}", folder=str(env.path)), icon=FOLDER_ICON,
                 translate=False)
    if last_error:
        alert = layout.row()
        alert.alert = True
        alert.label(text=tr("Last attempt: {error}", error=messages.one_line(last_error)),
                    icon="ERROR", translate=False)
    if running:
        note = layout.row()
        note.active = False
        note.label(text=tr("Being installed or verified: follow its progress in the status "
                           "bar"), icon=NOTE_ICON, translate=False)
        return
    row = layout.row(align=True)
    texts = _cached("setup_actions", _action_texts)
    for action in ENGINE_ACTIONS.get(env.status(), ()):
        properties = row.operator(SETUP_RUNTIME, text=texts[action],
                                  icon=SETUP_ICONS[action])
        properties.action = action


def draw_remove(layout: Any, env: ComputeEnvironment, size_mb: float) -> None:
    """La confirmación de quitar el motor de cálculo: la carpeta que se borra y sus MB."""
    layout.label(text=tr("The folder {folder} is deleted ({size} MB); it can be installed "
                         "again later", folder=str(env.path), size=format_number(size_mb, 1)),
                 icon=SETUP_ICONS["REMOVE"], translate=False)


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
