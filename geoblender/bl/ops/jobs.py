# SPDX-License-Identifier: GPL-3.0-or-later
"""Trabajos en segundo plano dentro de Blender (spec 004; plan 004 §5.1, §5.4.4 y §5.5).

:class:`JobMonitor` sigue los trabajos del lanzador (``jobs.runner.JobRunner``) desde el
hilo de Blender, sin hilos propios (ARQ-19): un temporizador **persistente**
(``bpy.app.timers``, sobrevive a abrir otro ``.blend``) llama a :func:`tick` cada
:data:`TICK_S` s desde que se lanza el primer trabajo (:meth:`JobMonitor.submit`) y se
retira solo cuando no queda nada que mostrar. Cada ``tick`` (objetivo ≤ 5 ms, RNF-004-03):

1. sondea el lanzador (``JobRunner.poll``, que no bloquea) y lee cómo está cada trabajo
   (``JobRunner.snapshots``);
2. calcula lo que muestra la barra de estado (:class:`StatusView`): mientras hay trabajos
   activos, cuántos son y el más antiguo en curso (o, si todos esperan, el más antiguo en
   la cola), con su avance, que **nunca retrocede** y se acota a 0–100 % (RF-004-06, spec
   §8), y su último mensaje; y el último trabajo que llegó a un estado final, durante
   :data:`NOTICE_S` s (RF-004-07);
3. redibuja la barra de estado de cada ventana sin operadores modales
   (``bl.ui.statusbar.redraw``, con ``status_text_set(None)``: la barra no está en
   ``screen.areas``; con un modal, su texto de estado es suyo y no se toca).

Lo dibuja el campo «jobs» de la barra de estado de la 003 (``bl/ui/jobs.py``), en modo
Geoblender y en modo Blender. En ``blender -b`` los temporizadores no se ejecutan: las
pruebas llaman a :func:`tick` a mano.

:data:`MONITOR` es el monitor de la sesión. El lanzador se le da con
:meth:`JobMonitor.attach` (lo crea la tarea T22 con la raíz de trabajos del proyecto).
:func:`register` instala los textos de los trabajos en ``core.i18n`` y registra los tipos de
trabajo de la 004 (``jobs.catalog.register_builtin_workers``); :func:`unregister` retira el
temporizador y los quita.

Operadores reales, con el ``bl_idname`` del catálogo de la 003 (Herramientas ▸ Trabajos),
que así deja de generar sus provisionales; funcionan en los dos modos (sus botones están en
la barra de estado, que en modo Blender también se ve), sin la puerta de modo:

- ``geoblender.jobs_show_jobs`` (RF-004-08): mide la carpeta de los trabajos y abre la lista
  de trabajos (``GEOBLENDER_PT_jobs_list``, ``bl/ui/jobs.py``) con ``wm.call_panel``. Sin
  ventana, su ``poll`` falla y lo dice.
- ``geoblender.jobs_cancel`` (RF-004-09): cancela el trabajo ``job_uid`` o, vacío (el botón
  de la barra de estado), el más antiguo en curso (si todos esperan, el más antiguo en la
  cola: el que enseña la barra). Uno en cola queda «Cancelado» sin arrancar; uno en curso
  recibe la petición de parar (``JobRunner.cancel``). Cancelar otra vez, uno que ya terminó
  o uno que no existe no hace nada más y avisa (spec §8). Sin trabajos activos, su ``poll``
  falla con «No hay trabajos en curso».

- ``geoblender.jobs_run_selftest`` (HU-004-1, RF-004-03): lanza con el monitor un
  autodiagnóstico (``mode``): ``SUM_10S``, una suma por trozos de unos 10 s (20 × 0,5 s:
  más de 5 s estimados, en proceso aparte), ``MATMUL_BLENDER``, el producto 500 × 500 con el
  numpy de Blender (unos 0,2 s: en hilo) y ``MATMUL_COMPUTE``, el de 2000 × 2000 con el
  motor de cálculo (en proceso aparte; sin motor queda «Fallido» con ``runtime_missing`` y
  el operador lo dice). Sin lanzador, su ``poll`` falla y lo dice.
- ``geoblender.jobs_clean`` (RF-004-17, RF-004-08): borra las carpetas de los trabajos
  terminados con ``JobRunner.purge``, que nunca toca un trabajo activo, e informa de los MB
  liberados: ``OLD``, los terminados hace más días que ``retention_days`` de las
  preferencias; ``FINISHED``, todos los terminados (los dos, desde el menú, tras un diálogo
  de confirmación); ``ONE``, solo el ``job_uid`` (el «Descartar» de la lista de trabajos,
  sin diálogo).

Todos sin ``UNDO``: no cambian la escena. Los de la fase 4 (``jobs_setup_runtime``,
``jobs_set_external_python``) siguen provisionales hasta entonces.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import bpy
from bpy.props import EnumProperty, StringProperty

from ...core import i18n
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, tr
from ...jobs import catalog, messages
from ...jobs.cleanup import CleanupReport
from ...jobs.paths import JobDir
from ...jobs.protocol import JobRequest, JsonValue, new_request
from ...jobs.runner import JobHandle, JobResult, JobRunner, JobSnapshot
from .. import ADDON_PACKAGE
from ..props.jobs import RETENTION_DEFAULT
from ..ui import jobs as job_list
from ..ui import statusbar

TICK_S = 0.25
"""Cada cuánto sondea el temporizador (plan §5.4.4)."""
NOTICE_S = 10.0
"""Lo que dura en la barra de estado el aviso de un trabajo que acabó (RF-004-07)."""
TRANSLATION_CONTEXT = "Geoblender"

LOGGER = logging.getLogger("geoblender.bl.ops")


@dataclass(frozen=True, slots=True)
class StatusView:
    """Lo que muestra la barra de estado de los trabajos (RF-004-06, RF-004-07).

    ``active``: trabajos en cola o en curso. ``current``: el más antiguo en curso (si todos
    esperan, el más antiguo en la cola; ``None`` sin activos). ``frac``: su avance mostrado
    (0–1, nunca menor que el anterior del mismo trabajo; 0 en la cola). ``notice``: el
    último trabajo que llegó a un estado final, mientras dura su aviso."""

    active: int = 0
    current: JobSnapshot | None = None
    frac: float = 0.0
    notice: JobSnapshot | None = None

    @property
    def percent(self) -> int:
        """El avance mostrado, en % entero hacia abajo (0–100)."""
        return job_list.percent_of(self.frac)

    @property
    def visible(self) -> bool:
        """Si hay algo que mostrar."""
        return self.active > 0 or self.notice is not None


EMPTY_VIEW = StatusView()


class JobMonitor:
    """El seguimiento de los trabajos en Blender (plan §5.4.4). ``clock``: el reloj
    monótono de los avisos (las pruebas lo adelantan)."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._runner: JobRunner | None = None
        self._view = EMPTY_VIEW
        self._notice_until = 0.0
        self._shown: dict[str, float] = {}
        self._failing = False

    @property
    def runner(self) -> JobRunner | None:
        """El lanzador que sigue (``None`` si aún no tiene)."""
        return self._runner

    def attach(self, runner: JobRunner | None) -> None:
        """Sigue los trabajos de ``runner`` (un ``JobRunner``; ``None``: ninguno)."""
        self._runner = runner

    def submit(self, job: JobDir | JobRequest, *,
               on_finish: Callable[[JobResult], object] | None = None) -> JobHandle:
        """Lanza ``job`` (``JobDir`` o ``JobRequest``) con el lanzador
        (``JobRunner.submit``, que no bloquea) y empieza a seguirlo: registra el
        temporizador si no lo estaba. Sin lanzador, :class:`RuntimeError` y nada más."""
        runner = self._runner
        if runner is None:
            raise RuntimeError("no hay lanzador de trabajos: Geoblender aún no ha preparado "
                               "la carpeta de los trabajos")
        handle = runner.submit(job, on_finish=on_finish)
        self.start()
        return handle

    def start(self) -> None:
        """Registra el temporizador (persistente, cada :data:`TICK_S` s) si no lo está."""
        if not bpy.app.timers.is_registered(tick):
            bpy.app.timers.register(tick, first_interval=TICK_S, persistent=True)

    def stop(self) -> None:
        """Retira el temporizador y olvida lo mostrado (al desregistrar)."""
        _retire()
        self._view = EMPTY_VIEW
        self._notice_until = 0.0
        self._shown.clear()

    @property
    def watching(self) -> bool:
        """Si el temporizador está registrado."""
        return bpy.app.timers.is_registered(tick)

    def view(self) -> StatusView:
        """Lo que muestra ahora la barra de estado (lo calcula :meth:`tick`)."""
        return self._view

    def shown_frac(self, snapshot: JobSnapshot) -> float:
        """El avance que se muestra de ``snapshot`` (0–1): en curso, el de la barra de
        estado, que nunca retrocede (RF-004-06); si no, el suyo, acotado. Lo usa la lista
        de trabajos."""
        frac = _clamp(snapshot.frac)
        if snapshot.state == "running":
            return max(frac, self._shown.get(snapshot.job_uid, 0.0))
        return frac

    def tick(self) -> float | None:
        """Un sondeo (plan §5.4.4): el lanzador, lo que se muestra y el redibujo de la
        barra de estado. Devuelve :data:`TICK_S` mientras haya algo que mostrar; si no,
        retira el temporizador y devuelve ``None``."""
        snapshots: list[JobSnapshot] = []
        finished: list[str] = []
        runner = self._runner
        if runner is not None:
            try:
                finished = [update.job_uid for update in runner.poll() if update.finished]
                snapshots = list(runner.snapshots())
            except Exception:  # noqa: BLE001 - el seguimiento no tumba la interfaz
                if not self._failing:
                    LOGGER.exception("Falló el seguimiento de los trabajos en segundo plano")
                self._failing = True
                return TICK_S
            self._failing = False
        view = self._compute(snapshots, finished)
        changed = view != self._view
        self._view = view
        if changed:
            statusbar.redraw()
        if view.visible:
            return TICK_S
        _retire()
        return None

    def _compute(self, snapshots: list[JobSnapshot], finished: list[str]) -> StatusView:
        now = self._clock()
        notice = self._view.notice
        by_uid = {snapshot.job_uid: snapshot for snapshot in snapshots}
        for job_uid in finished:
            ended = by_uid.get(job_uid)
            if ended is not None:
                notice, self._notice_until = ended, now + NOTICE_S
        if notice is not None and now >= self._notice_until:
            notice = None
        active = [snapshot for snapshot in snapshots if snapshot.active]
        shown: dict[str, float] = {}
        for snapshot in active:
            if snapshot.state == "running":
                previous = self._shown.get(snapshot.job_uid, 0.0)
                shown[snapshot.job_uid] = max(previous, _clamp(snapshot.frac))
        self._shown = shown
        current = oldest_active(active)
        frac = shown.get(current.job_uid, 0.0) if current is not None else 0.0
        return StatusView(active=len(active), current=current, frac=frac, notice=notice)


def oldest_active(snapshots: Iterable[JobSnapshot]) -> JobSnapshot | None:
    """El más antiguo en curso de ``snapshots`` (por orden de llegada) o, si todos esperan,
    el más antiguo en la cola; ``None`` sin activos. Es el que enseña la barra de estado y
    el que cancela su botón."""
    queued: JobSnapshot | None = None
    for snapshot in snapshots:
        if snapshot.state == "running":
            return snapshot
        if queued is None and snapshot.active:
            queued = snapshot
    return queued


def _clamp(frac: float) -> float:
    """Un avance dentro de 0–1 (lo que no es un número, 0)."""
    if not isinstance(frac, int | float) or math.isnan(frac):
        return 0.0
    return min(1.0, max(0.0, float(frac)))


MONITOR = JobMonitor()
"""El monitor de la sesión (lo dibuja ``bl/ui/jobs.py``)."""


def tick() -> float | None:
    """La función del temporizador: :meth:`JobMonitor.tick` de :data:`MONITOR`."""
    return MONITOR.tick()


def _retire() -> None:
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)


# Operadores ---------------------------------------------------------------------------


def _call_panel(name: str) -> set[str]:
    """Abre la ventana emergente ``name`` con ``wm.call_panel``; sigue abierta aunque el
    ratón salga de ella (``keep_open``), hasta pulsar fuera o Esc."""
    return bpy.ops.wm.call_panel(name=name, keep_open=True)


class GEOBLENDER_OT_jobs_show_jobs(bpy.types.Operator):
    """Running and finished jobs with their progress"""

    bl_idname = "geoblender.jobs_show_jobs"
    bl_label = "Background jobs"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if getattr(context, "window", None) is None:
            cls.poll_message_set(tr("The job list needs a Blender window"))
            return False
        return True

    def invoke(self, context: Any, event: Any) -> set[str]:
        return self.execute(context)

    def execute(self, context: Any) -> set[str]:
        runner = MONITOR.runner
        job_list.measure_folder(runner.jobs_root if runner is not None else None)
        return _call_panel(job_list.PANEL)


class GEOBLENDER_OT_jobs_cancel(bpy.types.Operator):
    """Cancel the job that is running"""

    bl_idname = "geoblender.jobs_cancel"
    bl_label = "Cancel the active job"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    job_uid: StringProperty(  # type: ignore[valid-type]
        name="Job",
        description="Identifier of the job to cancel (empty: the oldest running one)",
        default="",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        runner = MONITOR.runner
        if runner is None or runner.active_count() == 0:
            cls.poll_message_set(tr("No jobs are running"))
            return False
        return True

    def execute(self, context: Any) -> set[str]:
        runner = MONITOR.runner
        snapshots = runner.snapshots() if runner is not None else []
        if self.job_uid:
            target = next((s for s in snapshots if s.job_uid == self.job_uid), None)
            if target is None:
                self.report({"WARNING"}, tr("There is no job «{job}»", job=self.job_uid))
                return {"CANCELLED"}
        else:
            target = oldest_active(snapshots)
            if target is None:
                self.report({"WARNING"}, tr("No jobs are running"))
                return {"CANCELLED"}
        if runner is None or not runner.cancel(target.job_uid):
            self.report({"WARNING"}, tr(
                "The job «{job}» has already finished or is already being cancelled",
                job=target.name))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Cancelling the job «{job}»", job=target.name))
        return {"FINISHED"}


def _open_runner() -> JobRunner | None:
    """El lanzador de la sesión, si lo hay y admite trabajos (no se cerró)."""
    runner = MONITOR.runner
    if runner is None or getattr(runner, "closed", False):
        return None
    return runner


SELFTEST_WORKER = "selftest"
SELFTEST_OWNER = "jobs"
SELFTEST_PARAMS: Mapping[str, Mapping[str, JsonValue]] = MappingProxyType({
    # 20 trozos de 0,5 s: unos 10 s, más de 5 s estimados → proceso aparte (RF-004-03).
    "SUM_10S": MappingProxyType({"op": "chunked_sum", "n": 20_000, "chunks": 20,
                                 "sleep_s": 0.5}),
    # n > 1000 exige el motor de cálculo (jobs.selftest.environment).
    "MATMUL_COMPUTE": MappingProxyType({"op": "matmul", "n": 2000}),
    # Unos 0,2 s con el numpy de Blender (≤ 5 s estimados) → en hilo.
    "MATMUL_BLENDER": MappingProxyType({"op": "matmul", "n": 500}),
})
"""Los parámetros del autodiagnóstico (``jobs/selftest.py``) de cada ``mode``."""
SELFTEST_MODE_ITEMS = [
    ("SUM_10S", "Sum of 10 s",
     "Sum in chunks of about 10 s in a separate process, to follow its progress and "
     "cancel it"),
    ("MATMUL_COMPUTE", "Matrix product with the compute engine",
     "Product of two 2000 × 2000 float64 matrices with the numpy and the BLAS of the "
     "compute engine"),
    ("MATMUL_BLENDER", "Matrix product with Blender's numpy",
     "Product of two 500 × 500 float64 matrices with the numpy of Blender, in a thread"),
]


def _selftest_name(mode: str) -> str:
    """El nombre visible del autodiagnóstico de ``mode``, en el idioma de Geoblender."""
    names = {
        "SUM_10S": tr("Self-test: sum of 10 s"),
        "MATMUL_COMPUTE": tr("Self-test: 2000 × 2000 product with the compute engine"),
        "MATMUL_BLENDER": tr("Self-test: 500 × 500 product with Blender's numpy"),
    }
    return names[mode]


class GEOBLENDER_OT_jobs_run_selftest(bpy.types.Operator):
    """Run a test job and check the compute engine"""

    bl_idname = "geoblender.jobs_run_selftest"
    bl_label = "Self-test"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    mode: EnumProperty(  # type: ignore[valid-type]
        name="Mode", items=SELFTEST_MODE_ITEMS, default="SUM_10S", options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        if _open_runner() is None:
            cls.poll_message_set(tr("Geoblender has not prepared the jobs folder yet"))
            return False
        return True

    def execute(self, context: Any) -> set[str]:
        name = _selftest_name(self.mode)
        if _open_runner() is None:
            self.report({"ERROR"}, tr("Geoblender has not prepared the jobs folder yet"))
            return {"CANCELLED"}
        try:
            request = new_request(SELFTEST_WORKER, label=name, owner=SELFTEST_OWNER,
                                  params=SELFTEST_PARAMS[self.mode])
            handle = MONITOR.submit(request)
        except GeoblenderError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        result = handle.result()
        if result is not None and result.state != "succeeded":
            # No llegó a arrancar (sin motor de cálculo: «Fallido», runtime_missing).
            self.report({"ERROR"}, _error_of(handle.job_uid, result))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Launched the job «{job}»", job=name))
        return {"FINISHED"}


def _error_of(job_uid: str, result: JobResult) -> str:
    """El mensaje del §8 de un trabajo que acabó mal, en el idioma de Geoblender."""
    runner = MONITOR.runner
    snapshots = runner.snapshots() if runner is not None else []
    snapshot = next((s for s in snapshots if s.job_uid == job_uid), None)
    if snapshot is not None and snapshot.error is not None:
        return job_list.error_text(snapshot.error)
    return messages.one_line(result.error_text or "")


CLEAN_SCOPE_ITEMS = [
    ("OLD", "Older than the retention",
     "Finished jobs that ended more days ago than set in the preferences"),
    ("FINISHED", "All finished", "Every finished job, however recent"),
    ("ONE", "One job", "Only the finished job with that identifier (Discard)"),
]


def _jobs_preferences() -> Any:
    """El grupo ``jobs`` de las preferencias de la extensión, o ``None`` si aún no
    están."""
    addon = bpy.context.preferences.addons.get(ADDON_PACKAGE)
    return getattr(getattr(addon, "preferences", None), "jobs", None)


def retention_days() -> int:
    """Días que se conservan los trabajos terminados (``retention_days`` de las
    preferencias; 7 si no se pueden leer)."""
    value = getattr(_jobs_preferences(), "retention_days", None)
    return RETENTION_DEFAULT if value is None else int(value)


class GEOBLENDER_OT_jobs_clean(bpy.types.Operator):
    """Delete the folders of the finished jobs"""

    bl_idname = "geoblender.jobs_clean"
    bl_label = "Clean finished jobs…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    scope: EnumProperty(  # type: ignore[valid-type]
        name="Jobs to delete", items=CLEAN_SCOPE_ITEMS, default="OLD", options={"SKIP_SAVE"},
    )
    job_uid: StringProperty(  # type: ignore[valid-type]
        name="Job",
        description="Identifier of the job to discard (with One job)",
        default="",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        if MONITOR.runner is None:
            cls.poll_message_set(tr("Geoblender has not prepared the jobs folder yet"))
            return False
        return True

    def invoke(self, context: Any, event: Any) -> set[str]:
        if self.scope == "ONE":  # «Descartar» en la lista de trabajos: sin diálogo
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(
            self, width=360, title=tr("Clean finished jobs"), confirm_text=tr("Delete"),
            translate=False,
        )

    def draw(self, context: Any) -> None:
        column = self.layout.column(align=True)
        column.prop_enum(self, "scope", "OLD", translate=False,
                         text=tr("Finished more than {days} days ago", days=retention_days()))
        column.prop_enum(self, "scope", "FINISHED", text=tr("All finished"),
                         translate=False)
        note = self.layout.row()
        note.active = False
        note.label(text=tr("Queued and running jobs are never deleted"), translate=False)

    def execute(self, context: Any) -> set[str]:
        runner = MONITOR.runner
        if runner is None:
            self.report({"ERROR"}, tr("Geoblender has not prepared the jobs folder yet"))
            return {"CANCELLED"}
        if self.scope == "ONE":
            return _discard(self, runner, self.job_uid)
        if self.scope == "FINISHED":
            report = runner.purge(older_than_days=None, all_finished=True)
        else:
            report = runner.purge(older_than_days=retention_days())
        _refresh_folder_size(runner)
        if report.removed:
            self.report({"INFO"}, tr("Job folders deleted: {count} ({size} MB freed)",
                                     count=len(report.removed),
                                     size=format_number(report.freed_mb, 1)))
        elif not report.failed:
            self.report({"INFO"}, tr("There were no finished jobs to delete"))
        _report_failed(self, report)
        return {"FINISHED"}


def _discard(operator: Any, runner: JobRunner, job_uid: str) -> set[str]:
    """Borra la carpeta de un solo trabajo terminado, ``job_uid`` (el «Descartar» de la
    lista, RF-004-08), y lo dice con ``operator.report``."""
    if not job_uid:
        operator.report({"ERROR"}, tr("No job to discard was given"))
        return {"CANCELLED"}
    snapshot = next((s for s in runner.snapshots() if s.job_uid == job_uid), None)
    name = snapshot.name if snapshot is not None else job_uid
    report = runner.purge(older_than_days=None, all_finished=True, only=(job_uid,))
    _refresh_folder_size(runner)
    if report.removed:
        operator.report({"INFO"}, tr("Discarded the job «{job}» ({size} MB freed)", job=name,
                                     size=format_number(report.freed_mb, 1)))
        return {"FINISHED"}
    if report.failed:
        _report_failed(operator, report)
    elif snapshot is not None:  # en cola, en curso o con su hilo aún en marcha
        operator.report({"WARNING"}, tr(
            "The job «{job}» is still running: it cannot be discarded", job=name))
    else:
        operator.report({"WARNING"}, tr("There is no job «{job}»", job=job_uid))
    return {"CANCELLED"}


def _report_failed(operator: Any, report: CleanupReport) -> None:
    """El aviso de las carpetas que otro programa no dejó borrar del todo."""
    if report.failed:
        operator.report({"WARNING"}, tr(
            "Job folders that could not be deleted completely (another program has a file "
            "open): {count}; they will be tried again in the next cleaning",
            count=len(report.failed)))


def _refresh_folder_size(runner: JobRunner) -> None:
    """Vuelve a medir la carpeta de los trabajos si la lista la había medido."""
    if job_list.folder_size(runner.jobs_root) is not None:
        job_list.measure_folder(runner.jobs_root)


classes: tuple[type, ...] = (GEOBLENDER_OT_jobs_show_jobs, GEOBLENDER_OT_jobs_cancel,
                             GEOBLENDER_OT_jobs_run_selftest, GEOBLENDER_OT_jobs_clean)


def register() -> None:
    """Textos de los trabajos en ``core.i18n`` y tipos de trabajo de la 004; idempotente."""
    i18n.install(messages.CATALOG_ES)
    i18n.install(catalog.CATALOG_ES)
    catalog.unregister_builtin_workers()
    catalog.register_builtin_workers()


def unregister() -> None:
    """Retira el temporizador del monitor y quita los tipos de trabajo de la 004;
    idempotente."""
    MONITOR.stop()
    catalog.unregister_builtin_workers()
