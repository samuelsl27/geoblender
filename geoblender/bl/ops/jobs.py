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

:data:`MONITOR` es el monitor de la sesión, y el **lanzador de la sesión**
(:func:`session_runner`, un ``JobRunner``) se le da con :meth:`JobMonitor.attach`
(RF-004-13, RF-004-18; plan §5.1, §5.4.4 y §5.4.5):

- :func:`register` instala los textos de los trabajos en ``core.i18n``, registra los tipos
  de trabajo de la 004 (``jobs.catalog.register_builtin_workers``) y crea el lanzador, sin
  crear ninguna carpeta: el paquete de los workers es la carpeta del paquete raíz, el
  intérprete es el ``python.exe`` de Blender (``sys.executable``), el máximo de trabajos en
  proceso aparte sale de las preferencias (``jobs.max_parallel_jobs``, que al cambiar llega
  con ``reconfigure``) y la raíz de trabajos, de :func:`jobs_root`. También pone el
  manejador ``exit_pre`` (persistente) y se apunta a los cambios de proyecto de la 002
  (``bl.scene.project_session.add_listener``).
- Raíz de trabajos (:func:`jobs_root`, RF-004-18): con un proyecto abierto,
  ``Project.cache_dir()/jobs`` (la caché única de la 002: en la carpeta del proyecto si está
  en disco local y en escritura; en los datos de usuario si está en red o en solo lectura) y,
  sin proyecto, ``<datos de usuario>/cache/_sin_proyecto/jobs``, con ``<datos de usuario>`` =
  ``extension_path_user(bl.ADDON_PACKAGE)`` (:func:`user_dir`; nunca el paquete de un
  submódulo). El motor de cálculo va en ``<datos de usuario>/runtime``
  (:func:`runtime_dir`), que nadie crea sin el consentimiento del usuario (RF-004-19). Las
  calcula ``bl`` y se las da a ``jobs/`` como ``Path``.
- Al cambiar de proyecto (:func:`on_project_changed`), la raíz pasa a la del nuevo (o a la
  de sin proyecto) y la raíz del proyecto queda prohibida en las peticiones (RF-004-02); al
  abrir uno, ``records.mark_interrupted`` deja «Interrumpido» lo que su registro dejaba en
  cola o en curso sin estar en el lanzador (Blender se cerró con ello en marcha, RF-004-13)
  y ``JobRunner.purge`` borra los terminados hace más de ``retention_days`` días
  (RF-004-17); los MB liberados van al registro técnico y, si algo no se pudo borrar, queda
  un aviso del proyecto. Lo que ya estaba en marcha sigue en su carpeta.
- :func:`unregister` y el manejador ``exit_pre`` (:func:`on_exit_pre`) cierran el lanzador
  con ``JobRunner.shutdown(timeout_s=3)`` (los trabajos en curso quedan «Interrumpido» y
  sin proceso, RF-004-13) **antes** de retirar el temporizador del monitor;
  :func:`unregister` quita además el manejador, el aviso de cambio de proyecto y los tipos
  de trabajo.

Operadores reales, con el ``bl_idname`` del catálogo de la 003 (Herramientas ▸ Trabajos),
que así deja de generar sus provisionales; funcionan en los dos modos (sus botones están en
la barra de estado, que en modo Blender también se ve), sin la puerta de modo:

- ``geoblender.jobs_show_jobs`` (RF-004-08, RF-004-13): mide la carpeta de los trabajos, lee
  los trabajos guardados que no son del lanzador (:func:`read_stored_jobs`: de la raíz en
  uso y de la de sin proyecto, tras dejar «Interrumpido» los que constaban activos; así se
  ven también tras desactivar y reactivar Geoblender) y abre la lista de trabajos
  (``GEOBLENDER_PT_jobs_list``, ``bl/ui/jobs.py``) con ``wm.call_panel``. Sin ventana, su
  ``poll`` falla y lo dice.
- ``geoblender.jobs_cancel`` (RF-004-09): cancela el trabajo ``job_uid`` o, vacío (el botón
  de la barra de estado), el más antiguo en curso (si todos esperan, el más antiguo en la
  cola: el que enseña la barra). Uno en cola queda «Cancelado» sin arrancar; uno en curso
  recibe la petición de parar (``JobRunner.cancel``). Cancelar otra vez, uno que ya terminó
  o uno que no existe no hace nada más y avisa (spec §8). Sin trabajos activos, su ``poll``
  falla con «No hay trabajos en curso».

- ``geoblender.jobs_run_selftest`` (HU-004-1, RF-004-03): lanza con el monitor un
  autodiagnóstico (``mode``): ``SUM_10S``, una suma por trozos de unos 10 s (50 × 0,2 s:
  más de 5 s estimados, en proceso aparte, y un avance cada 0,2 s, RF-004-06),
  ``MATMUL_BLENDER``, el producto 500 × 500 con el numpy de Blender (unos 0,2 s: en hilo)
  y ``MATMUL_COMPUTE``, el de 2000 × 2000 con el motor de cálculo (en proceso aparte; sin
  motor queda «Fallido» con ``runtime_missing`` y el operador lo dice). Sin lanzador, su
  ``poll`` falla y lo dice.
- ``geoblender.jobs_clean`` (RF-004-17, RF-004-08): borra las carpetas de los trabajos
  terminados con ``JobRunner.purge``, que nunca toca un trabajo activo, e informa de los MB
  liberados: ``OLD``, los terminados hace más días que ``retention_days`` de las
  preferencias; ``FINISHED``, todos los terminados (los dos, desde el menú, tras un diálogo
  de confirmación); ``ONE``, solo el ``job_uid`` (el «Descartar» de la lista de trabajos,
  sin diálogo; si es un trabajo guardado de otra raíz, en la suya).

- ``geoblender.jobs_setup_runtime`` (Motor de cálculo…; RF-004-19 a RF-004-25, plan §5.4.7
  y §5.5): el motor de cálculo del lanzador de la sesión (:func:`compute_environment`, el
  del lock de esta versión en ``<datos de usuario>/runtime``; crearlo no toca el disco).
  ``action``: ``STATUS`` (por defecto, el del menú) instala, actualiza o repara según esté
  el motor (no instalado, de otra versión de Geoblender o dañado) y, con el motor listo,
  enseña su estado con Verificar, Reparar y Quitar; ``INSTALL``, ``UPDATE`` y ``REPAIR``
  calculan el plan sin usar la red (origen ``source``; ``AUTO``: el de las preferencias,
  con su almacén de ruedas) y, antes de hacer nada, lo enseñan en el diálogo de
  consentimiento (``bl/ui/jobs.py``) con «Instalar» y «Cancelar»; «Instalar» lanza la
  cadena ``jobs.runtime.RuntimeSetup`` (instalar → verificar → adoptar) con el plan
  enseñado (su huella, ``confirmation``) y el consentimiento del usuario, seguida en la
  barra de estado. PyPI con el acceso en línea de Blender desactivado no abre el diálogo y
  dice las dos salidas (RF-004-23). ``VERIFY`` verifica el motor instalado; ``REMOVE``, tras
  confirmarlo en un diálogo, lo borra si ningún trabajo lo usa. Sin confirmación (desde un
  guion) no instala ni borra nada.
- Un trabajo que necesita el motor y no lo tiene (``runtime_missing`` al lanzarlo con
  :meth:`JobMonitor.submit`) abre ese mismo diálogo (:func:`offer_runtime_setup`,
  RF-004-25); en ``blender -b`` no hay a quién enseñárselo.

Todos sin ``UNDO``: no cambian la escena. ``jobs_set_external_python`` sigue provisional
hasta la T33.
"""

from __future__ import annotations

import logging
import math
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import EnumProperty, StringProperty

from ...core import i18n
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, language, tr
from ...jobs import catalog, cleanup, messages, records
from ...jobs import runtime as jobs_runtime
from ...jobs.cleanup import CleanupReport
from ...jobs.messages import JobError
from ...jobs.paths import JobDir, resolve_jobs_root
from ...jobs.protocol import JobRequest, JsonValue, new_request
from ...jobs.runner import JobHandle, JobResult, JobRunner, JobSnapshot
from ...jobs.runtime import ComputeEnvironment, InstallPlan, RuntimeSetup, WheelSource
from .. import ADDON_PACKAGE
from ..props.jobs import MAX_PARALLEL_DEFAULT, RETENTION_DEFAULT
from ..scene import project_session
from ..ui import jobs as job_list
from ..ui import statusbar

if TYPE_CHECKING:
    from ...core.project.session import Project

TICK_S = 0.25
"""Cada cuánto sondea el temporizador (plan §5.4.4)."""
NOTICE_S = 10.0
"""Lo que dura en la barra de estado el aviso de un trabajo que acabó (RF-004-07)."""
TRANSLATION_CONTEXT = "Geoblender"
SHUTDOWN_TIMEOUT_S = 3.0
"""Lo que puede tardar en cerrarse el lanzador al desactivar o salir (RF-004-13)."""
RUNTIME_DIR = "runtime"
"""La carpeta del motor de cálculo en los datos de usuario (plan §5.2)."""
PACKAGE_DIR = Path(__file__).resolve().parents[2]
"""La carpeta del paquete raíz de la extensión, la que cargan los workers (tiene
``workers/_bootstrap.py``)."""

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
        temporizador si no lo estaba. Si no se lanzó porque necesita el motor de cálculo y
        falta, ofrece instalarlo (:func:`offer_runtime_setup`, RF-004-25). Sin lanzador,
        :class:`RuntimeError` y nada más."""
        runner = self._runner
        if runner is None:
            raise RuntimeError("no hay lanzador de trabajos: Geoblender aún no ha preparado "
                               "la carpeta de los trabajos")
        handle = runner.submit(job, on_finish=on_finish)
        self.start()
        offer_runtime_setup(runner, handle.result())
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
        if runner is not None:
            read_stored_jobs(runner)
        else:
            job_list.forget_stored()
        return _call_panel(job_list.PANEL)


def read_stored_jobs(runner: JobRunner) -> tuple[JobSnapshot, ...]:
    """Lee para la lista de trabajos los guardados que no son de ``runner``: los de su raíz
    de trabajos y los de la de sin proyecto (los de diagnóstico), después de dejar
    «Interrumpido» los que constaban en cola o en curso sin estar en él
    (``JobRunner.stored_snapshots``; RF-004-08, RF-004-13), y los recuerda
    (``bl.ui.jobs.remember_stored``). Lo llaman ``jobs_show_jobs`` y el primer dibujo de la
    lista, nunca el registro. Si no se pueden leer, la lista sale sin ellos y el fallo va al
    registro técnico."""
    try:
        stored = tuple(runner.stored_snapshots(extra_roots=(jobs_root(None),)))
    except Exception:  # noqa: BLE001 - la lista se abre igual
        LOGGER.exception("No se pudieron leer los trabajos de la carpeta de trabajos")
        stored = ()
    job_list.remember_stored(runner, stored)
    return stored


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
    # 50 trozos de 0,2 s: unos 10 s, más de 5 s estimados → proceso aparte (RF-004-03), y
    # un avance por trozo, cinco por segundo (RF-004-06; M1 pide al menos dos; T37).
    "SUM_10S": MappingProxyType({"op": "chunked_sum", "n": 20_000, "chunks": 50,
                                 "sleep_s": 0.2}),
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


def max_parallel_jobs() -> int:
    """Trabajos a la vez en proceso aparte (``max_parallel_jobs`` de las preferencias; 2
    si aún no se pueden leer, como al habilitar la extensión por primera vez)."""
    value = getattr(_jobs_preferences(), "max_parallel_jobs", None)
    return MAX_PARALLEL_DEFAULT if value is None else int(value)


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
        job_list.forget_stored(report.removed)
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
    lista, RF-004-08): uno del lanzador o uno guardado de la lista, en su raíz; lo dice con
    ``operator.report``."""
    if not job_uid:
        operator.report({"ERROR"}, tr("No job to discard was given"))
        return {"CANCELLED"}
    snapshot = next((s for s in job_list.listed_jobs(runner) if s.job_uid == job_uid), None)
    name = snapshot.name if snapshot is not None else job_uid
    root = None
    if snapshot is not None and snapshot.stored and snapshot.folder is not None:
        root = snapshot.folder.parent
    report = runner.purge(older_than_days=None, all_finished=True, only=(job_uid,),
                          jobs_root=root)
    job_list.forget_stored(report.removed)
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
        operator.report({"WARNING"}, _failed_text(report))


def _failed_text(report: CleanupReport) -> str:
    return tr(
        "Job folders that could not be deleted completely (another program has a file "
        "open): {count}; they will be tried again in the next cleaning",
        count=len(report.failed))


def _refresh_folder_size(runner: JobRunner) -> None:
    """Vuelve a medir la carpeta de los trabajos si la lista la había medido."""
    if job_list.folder_size(runner.jobs_root) is not None:
        job_list.measure_folder(runner.jobs_root)


# El motor de cálculo (RF-004-19 a RF-004-25) ---------------------------------------------

SETUP_ACTION_ITEMS = [
    ("STATUS", "State",
     "Show the state of the compute engine; if it is missing, out of date or damaged, offer "
     "to install it"),
    ("INSTALL", "Install",
     "Install the compute engine after showing what is installed, from where, with which "
     "licences and how much it takes"),
    ("UPDATE", "Update",
     "Install the compute engine of this version of Geoblender, which replaces the one of an "
     "earlier version"),
    ("VERIFY", "Verify",
     "Check the installed compute engine: package versions, numpy, its BLAS and a "
     "2000 × 2000 product"),
    ("REPAIR", "Repair", "Install the compute engine again over a damaged or unverified one"),
    ("REMOVE", "Remove",
     "Delete the compute engine of this version of Geoblender, after confirming it"),
]
SETUP_SOURCE_ITEMS = [
    ("AUTO", "As in the preferences",
     "The source chosen in the preferences: by default, the wheel store if one is "
     "configured; otherwise PyPI"),
    ("WHEELHOUSE", "Wheel store", "Only the wheel store folder, without internet"),
    ("PYPI", "PyPI", "Download from PyPI (needs online access)"),
]
INSTALL_ACTIONS = frozenset({"INSTALL", "UPDATE", "REPAIR"})
"""Las acciones que instalan el motor (con el diálogo de consentimiento, RF-004-20)."""
ACTION_FOR_STATUS: Mapping[str, str] = MappingProxyType({
    jobs_runtime.STATUS_MISSING: "INSTALL",
    jobs_runtime.STATUS_OUTDATED: "UPDATE",
    jobs_runtime.STATUS_BROKEN: "REPAIR",
})
"""Lo que se ofrece según el estado del motor (con ``ready``, su estado)."""
SETUP_DIALOG_WIDTH = 600
"""Ancho del diálogo de consentimiento y del estado del motor (en píxeles a escala 1)."""


class _SetupState:
    """La cadena del motor de cálculo de esta sesión (``jobs.runtime.RuntimeSetup``), lo que
    falló en el último intento, el último plan enseñado en el diálogo y lo que mide la
    carpeta que se ofrece quitar."""

    def __init__(self) -> None:
        self.current: Any = None
        self.last_error: str | None = None
        self.shown: InstallPlan | None = None
        self.remove_mb: tuple[Path, float] | None = None

    def clear(self) -> None:
        self.__init__()


_SETUP = _SetupState()


def forget_setup() -> None:
    """Olvida la cadena del motor de la sesión, su último fallo y lo enseñado en el diálogo
    (al desregistrar; los trabajos de la cadena los cierra el lanzador)."""
    _SETUP.clear()


def setup_running() -> bool:
    """Si se está instalando o verificando el motor de cálculo en esta sesión."""
    current = _SETUP.current
    return current is not None and not current.done


def online_access() -> bool:
    """El «Permitir acceso en línea» de Blender (``bpy.app.online_access``): sin él no se
    descarga nada de PyPI (RF-004-23)."""
    return bool(bpy.app.online_access)


class _SetupRefused(Exception):
    """El motor no se puede instalar así: ``message`` dice por qué, en el idioma de
    Geoblender."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _job_error_text(exc: JobError) -> str:
    """El mensaje del §8 de ``exc`` en el idioma de Geoblender."""
    return messages.render(exc.code, language=language(), **exc.values)


def _setup_target() -> tuple[JobRunner, ComputeEnvironment] | None:
    """El lanzador de la sesión y su motor de cálculo, si los hay."""
    runner = _open_runner()
    env = getattr(runner, "runtime", None) if runner is not None else None
    if runner is None or not isinstance(env, ComputeEnvironment):
        return None
    return runner, env


def _wheel_source(choice: str) -> WheelSource:
    """El origen de las ruedas: ``choice`` (``AUTO``: el de las preferencias,
    ``runtime_source``) con la carpeta del almacén de las preferencias
    (``wheelhouse_dir``). :class:`_SetupRefused` si se pide el almacén sin carpeta o con una
    que no es una ruta completa."""
    prefs = _jobs_preferences()
    if choice == "AUTO":
        choice = getattr(prefs, "runtime_source", None) or "AUTO"
    folder = str(getattr(prefs, "wheelhouse_dir", "") or "").strip()
    if folder:
        folder = bpy.path.abspath(folder)
    try:
        return jobs_runtime.choose_source(choice, wheelhouse_dir=Path(folder) if folder else None)
    except ValueError:
        if not folder:
            raise _SetupRefused(tr("No wheel store folder is set in the preferences")) from None
        raise _SetupRefused(tr("The wheel store folder «{folder}» is not a full path",
                               folder=folder)) from None


def _plan(env: ComputeEnvironment, choice: str) -> InstallPlan:
    """El plan de instalar el motor desde el origen ``choice``, sin usar la red ni escribir
    nada (``ComputeEnvironment.plan_install``). :class:`_SetupRefused` con el motivo si no se
    puede: PyPI sin acceso en línea (las dos salidas, RF-004-23), una rueda que no está en el
    almacén (RF-004-24) o un almacén sin configurar."""
    source = _wheel_source(choice)
    try:
        return env.plan_install(source, online_access=online_access())
    except JobError as exc:
        raise _SetupRefused(_job_error_text(exc)) from None


def _setup_title(action: str) -> str:
    """El título del diálogo de consentimiento de ``action``."""
    titles = {
        "INSTALL": tr("Install the compute engine"),
        "UPDATE": tr("Update the compute engine"),
        "REPAIR": tr("Repair the compute engine"),
    }
    return titles[action]


def _install_refusal(action: str, env: ComputeEnvironment) -> tuple[set[str], str] | None:
    """Por qué no se instala ahora (el tipo de aviso y su texto), o ``None``: ya se está
    instalando o verificando, o el motor ya está listo (instalar o actualizar; reparar
    siempre se puede)."""
    if setup_running():
        return {"WARNING"}, tr("The compute engine is already being installed or verified")
    if action != "REPAIR" and env.status() == jobs_runtime.STATUS_READY:
        return {"INFO"}, tr("The compute engine is already installed and verified")
    return None


def _setup_done(setup: RuntimeSetup) -> None:
    """La cadena del motor terminó: si falló, su motivo queda para el estado del motor; en
    el registro técnico, lo que midió la verificación o el fallo."""
    if setup.state == jobs_runtime.SETUP_SUCCEEDED:
        if _SETUP.current is setup:
            _SETUP.last_error = None
        check = setup.check
        LOGGER.info("Motor de cálculo (%s): terminado; %s", setup.kind,
                    jobs_runtime.check_text(check) if check else "sin verificación")
        return
    if _SETUP.current is setup:
        _SETUP.last_error = setup.error_text or setup.error_code or setup.state
    LOGGER.warning("Motor de cálculo (%s): %s: %s", setup.kind, setup.state,
                   setup.error_text or setup.error_code)


def _start_setup(operator: Any, setup: RuntimeSetup, message: str) -> set[str]:
    """Sigue la cadena ``setup`` en la barra de estado (el temporizador del monitor:
    ``RuntimeSetup`` lanza con el lanzador directamente) y lo dice."""
    _SETUP.current = setup
    _SETUP.last_error = None
    MONITOR.start()
    operator.report({"INFO"}, message)
    return {"FINISHED"}


def _install(operator: Any, runner: JobRunner, env: ComputeEnvironment,
             action: str) -> set[str]:
    """Instala el motor (``RuntimeSetup.install``: instalar → verificar → adoptar) con el
    plan que el usuario confirmó en el diálogo (``confirmation``, su huella), con su
    consentimiento (RF-004-19). Sin confirmación, o si el plan cambió desde que se enseñó,
    no instala nada."""
    refusal = _install_refusal(action, env)
    if refusal is not None:
        operator.report(*refusal)
        return {"CANCELLED"}
    try:
        plan = _plan(env, operator.source)
    except _SetupRefused as exc:
        operator.report({"ERROR"}, exc.message)
        return {"CANCELLED"}
    if not operator.confirmation:
        operator.report({"ERROR"},
                        tr("Installing the compute engine needs your confirmation in its "
                           "dialog"))
        return {"CANCELLED"}
    if operator.confirmation != plan.digest:
        operator.report({"ERROR"}, tr("What is going to be installed changed after it was "
                                      "shown: ask for it again"))
        return {"CANCELLED"}
    consent = jobs_runtime.Consent.given(plan)
    try:
        setup = jobs_runtime.RuntimeSetup.install(runner, env, plan, consent,
                                                  on_done=_setup_done)
    except JobError as exc:
        operator.report({"ERROR"}, _job_error_text(exc))
        return {"CANCELLED"}
    except (RuntimeError, ValueError) as exc:  # el lanzador se cerró; otro motor
        operator.report({"ERROR"}, str(exc))
        return {"CANCELLED"}
    return _start_setup(operator, setup, tr("Installing the compute engine: follow its "
                                            "progress in the status bar"))


def _verify(operator: Any, runner: JobRunner, env: ComputeEnvironment) -> set[str]:
    """Verifica el motor instalado (``RuntimeSetup.verify``, RF-004-22)."""
    if setup_running():
        operator.report({"WARNING"},
                        tr("The compute engine is already being installed or verified"))
        return {"CANCELLED"}
    try:
        setup = jobs_runtime.RuntimeSetup.verify(runner, env, on_done=_setup_done)
    except JobError as exc:
        operator.report({"ERROR"}, _job_error_text(exc))
        return {"CANCELLED"}
    except (RuntimeError, ValueError) as exc:
        operator.report({"ERROR"}, str(exc))
        return {"CANCELLED"}
    return _start_setup(operator, setup, tr("Verifying the compute engine: follow its "
                                            "progress in the status bar"))


def _engine_size_mb(env: ComputeEnvironment) -> float:
    """Los MB de la carpeta del motor (medidos una vez por diálogo de quitarlo)."""
    measured = _SETUP.remove_mb
    if measured is not None and measured[0] == env.path:
        return measured[1]
    size = cleanup.folder_size_mb(env.path)
    _SETUP.remove_mb = (env.path, size)
    return size


def _remove(operator: Any, runner: JobRunner, env: ComputeEnvironment) -> set[str]:
    """Quita el motor de este lock (``ComputeEnvironment.remove``) solo con la
    confirmación del diálogo (``confirmation``, su carpeta; RF-004-19) y si ningún trabajo
    lo usa."""
    if setup_running():
        operator.report({"WARNING"},
                        tr("The compute engine is already being installed or verified"))
        return {"CANCELLED"}
    if operator.confirmation != str(env.path):
        operator.report({"ERROR"},
                        tr("Removing the compute engine needs your confirmation in its "
                           "dialog"))
        return {"CANCELLED"}
    if not env.path.is_dir():
        operator.report({"INFO"}, tr("The compute engine is not installed"))
        return {"CANCELLED"}
    size = cleanup.folder_size_mb(env.path)
    if not env.remove(in_use=runner.locks_in_use()):
        operator.report({"WARNING"}, tr("The compute engine is in use: close the "
                                        "calculations that use it and try again"))
        return {"CANCELLED"}
    _SETUP.last_error = None
    _SETUP.remove_mb = None
    operator.report({"INFO"}, tr("Removed the compute engine ({size} MB freed)",
                                 size=format_number(size, 1)))
    return {"FINISHED"}


class GEOBLENDER_OT_jobs_setup_runtime(bpy.types.Operator):
    """Install, update, verify, repair or remove the compute engine, and its state"""

    bl_idname = "geoblender.jobs_setup_runtime"
    bl_label = "Compute engine…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    action: EnumProperty(  # type: ignore[valid-type]
        name="Action", description="What to do with the compute engine",
        items=SETUP_ACTION_ITEMS, default="STATUS", options={"SKIP_SAVE"},
    )
    source: EnumProperty(  # type: ignore[valid-type]
        name="Source", description="Where the wheels of the compute engine come from",
        items=SETUP_SOURCE_ITEMS, default="AUTO", options={"SKIP_SAVE"},
    )
    confirmation: StringProperty(  # type: ignore[valid-type]
        name="Confirmation",
        description="What the user confirmed in the dialog (the dialog fills it in)",
        default="", options={"SKIP_SAVE", "HIDDEN"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        runner = _open_runner()
        if runner is None:
            cls.poll_message_set(tr("Geoblender has not prepared the jobs folder yet"))
            return False
        if not isinstance(getattr(runner, "runtime", None), ComputeEnvironment):
            cls.poll_message_set(tr("The compute engine lock of this version of Geoblender "
                                    "could not be read"))
            return False
        return True

    def invoke(self, context: Any, event: Any) -> set[str]:
        target = _setup_target()
        if target is None:
            self.report({"ERROR"}, tr("Geoblender has not prepared the jobs folder yet"))
            return {"CANCELLED"}
        _runner, env = target
        action = self.action
        if action == "STATUS" and not setup_running():
            action = ACTION_FOR_STATUS.get(env.status(), "STATUS")
        self.action = action
        manager = context.window_manager
        if action == "STATUS":
            return manager.invoke_popup(self, width=SETUP_DIALOG_WIDTH)
        if action == "VERIFY":
            return self.execute(context)
        if action == "REMOVE":
            if not env.path.is_dir():
                self.report({"INFO"}, tr("The compute engine is not installed"))
                return {"CANCELLED"}
            _SETUP.remove_mb = None
            _engine_size_mb(env)
            self.confirmation = str(env.path)
            return manager.invoke_props_dialog(
                self, width=SETUP_DIALOG_WIDTH, title=tr("Remove the compute engine"),
                confirm_text=tr("Remove"), translate=False)
        refusal = _install_refusal(action, env)
        if refusal is not None:
            self.report(*refusal)
            return {"CANCELLED"}
        try:
            plan = _plan(env, self.source)
        except _SetupRefused as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        _SETUP.shown = plan
        self.confirmation = plan.digest
        return manager.invoke_props_dialog(
            self, width=SETUP_DIALOG_WIDTH, title=_setup_title(action),
            confirm_text=tr("Install"), translate=False)

    def draw(self, context: Any) -> None:
        target = _setup_target()
        if target is None:
            return
        _runner, env = target
        if self.action == "REMOVE":
            job_list.draw_remove(self.layout, env, _engine_size_mb(env))
            return
        if self.action not in INSTALL_ACTIONS:
            job_list.draw_engine(self.layout, env, running=setup_running(),
                                 last_error=_SETUP.last_error)
            return
        plan = _SETUP.shown
        if plan is None or plan.digest != self.confirmation:
            try:
                plan = _plan(env, self.source)
            except _SetupRefused as exc:
                alert = self.layout.row()
                alert.alert = True
                alert.label(text=exc.message, icon="ERROR", translate=False)
                return
        job_list.draw_consent(self.layout, plan)

    def execute(self, context: Any) -> set[str]:
        target = _setup_target()
        if target is None:
            self.report({"ERROR"}, tr("Geoblender has not prepared the jobs folder yet"))
            return {"CANCELLED"}
        runner, env = target
        action = self.action
        if action == "STATUS":
            action = ACTION_FOR_STATUS.get(env.status(), "STATUS")
        if action == "STATUS":
            self.report({"INFO"}, tr("Compute engine: {state}",
                                     state=job_list.engine_state_text(env)))
            return {"FINISHED"}
        if action == "VERIFY":
            return _verify(self, runner, env)
        if action == "REMOVE":
            return _remove(self, runner, env)
        return _install(self, runner, env, action)


def offer_runtime_setup(runner: Any, result: JobResult | None) -> str | None:
    """Si ``result`` es el de un trabajo que no se lanzó porque necesita el motor de cálculo
    y falta (``runtime_missing``: no está, es de otra versión de Geoblender o está dañado),
    abre el diálogo de instalarlo, actualizarlo o repararlo (RF-004-25) y devuelve esa
    acción; si no, ``None``. No ofrece nada mientras se instala o verifica. Un fallo aquí
    nunca impide lanzar trabajos: va al registro técnico."""
    try:
        if (result is None or result.state != "failed"
                or result.error_code != "runtime_missing"):
            return None
        env = getattr(runner, "runtime", None)
        if not isinstance(env, ComputeEnvironment) or setup_running():
            return None
        action = ACTION_FOR_STATUS.get(env.status())
        if action is None:
            return None
        _invoke_setup(action)
        return action
    except Exception:  # noqa: BLE001 - ofrecer el motor no tumba el lanzamiento
        LOGGER.exception("No se pudo ofrecer la instalación del motor de cálculo")
        return None


def _invoke_setup(action: str) -> bool:
    """Abre el diálogo de ``geoblender.jobs_setup_runtime`` con ``action`` y dice si se
    abrió. En ``blender -b`` no hay a quién enseñárselo: no hace nada. Si el operador no
    puede (p. ej. PyPI sin acceso en línea), él mismo da el motivo."""
    if bpy.app.background:
        return False
    try:
        result = bpy.ops.geoblender.jobs_setup_runtime("INVOKE_DEFAULT", action=action)
    except RuntimeError as exc:  # el operador informó de un error o el contexto no vale
        LOGGER.info("No se abrió el diálogo del motor de cálculo: %s", messages.one_line(
            str(exc)))
        return False
    return "RUNNING_MODAL" in result


# El lanzador de la sesión ---------------------------------------------------------------


class _Session:
    """El lanzador de esta sesión de Blender (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.runner: JobRunner | None = None


_SESSION = _Session()


def session_runner() -> JobRunner | None:
    """El lanzador de la sesión que creó :func:`register` (``None`` antes de registrar y
    después de desregistrar)."""
    return _SESSION.runner


def user_dir() -> Path:
    """Los datos de usuario de la extensión, ``extension_path_user(bl.ADDON_PACKAGE)``
    (los mismos que los de la 002; no los crea)."""
    return project_session.userdata().root


def runtime_dir() -> Path:
    """La carpeta del motor de cálculo, ``<datos de usuario>/runtime`` (no la crea:
    RF-004-19)."""
    return Path(bpy.utils.extension_path_user(ADDON_PACKAGE, path=RUNTIME_DIR))


def jobs_root(project: Project | None) -> Path:
    """La raíz de trabajos (RF-004-18) con ``project`` abierto (``Project.cache_dir()``
    más ``jobs``) o sin proyecto (``None``: ``<datos de usuario>/cache/_sin_proyecto/jobs``).
    No la crea."""
    cache = None if project is None else project.cache_dir()
    return resolve_jobs_root(project_cache_dir=cache, user_dir=user_dir())


def _forbidden_roots(project: Project | None) -> tuple[Path, ...]:
    """Las rutas que no pueden llevar las peticiones: la raíz del proyecto (RF-004-02)."""
    return () if project is None else (Path(project.root),)


def compute_environment() -> ComputeEnvironment | None:
    """El motor de cálculo del lock de esta versión de Geoblender
    (``jobs/runtime_lock.toml``) en ``<datos de usuario>/runtime`` (:func:`runtime_dir`). No
    crea, descarga ni comprueba nada (RF-004-19). Si el lock no se puede leer, ``None`` (el
    fallo va al registro técnico): los trabajos del motor quedan «Fallido» sin él."""
    try:
        lock = jobs_runtime.read_lock()
    except (ValueError, OSError):
        LOGGER.exception("No se pudo leer el lock del motor de cálculo (%s)",
                         jobs_runtime.LOCK_PATH)
        return None
    return ComputeEnvironment(user_dir(), lock)


def _open_session() -> None:
    """Crea el lanzador de la sesión, con el motor de cálculo de :func:`compute_environment`,
    y se lo da al monitor; si ya hay uno abierto, no hace nada. No crea ninguna carpeta."""
    if _SESSION.runner is not None and not _SESSION.runner.closed:
        return
    project = project_session.current()
    runner = JobRunner(jobs_root=jobs_root(project), package_dir=PACKAGE_DIR,
                       blender_python=Path(sys.executable),
                       runtime=compute_environment(),
                       max_subprocess=max_parallel_jobs(),
                       forbidden_roots=_forbidden_roots(project))
    _SESSION.runner = runner
    MONITOR.attach(runner)


def _close_session() -> None:
    """Cierra el lanzador de la sesión (``shutdown``: los trabajos en curso quedan
    «Interrumpido» y sin proceso en ≤ :data:`SHUTDOWN_TIMEOUT_S` s) y después retira el
    temporizador del monitor. Cerrar otra vez no hace nada más."""
    runner = _SESSION.runner
    try:
        if runner is not None:
            runner.shutdown(timeout_s=SHUTDOWN_TIMEOUT_S)
    finally:
        MONITOR.stop()


def on_max_parallel_changed(value: int) -> None:
    """``max_parallel_jobs`` cambió en las preferencias: llega al lanzador de la sesión
    (RF-004-04; si sube, arranca de la cola lo que quepa)."""
    runner = _SESSION.runner
    if runner is not None and not runner.closed:
        runner.reconfigure(max_subprocess=int(value))


def on_project_changed(project: Project | None) -> None:
    """La sesión pasó a tener ``project`` (o ninguno): la raíz de trabajos y la ruta
    prohibida pasan a las suyas (RF-004-18, RF-004-02) y, al abrir un proyecto, se marcan
    «Interrumpido» los trabajos de su raíz que constaban activos sin estar en el lanzador
    (RF-004-13) y se borran los terminados hace más de ``retention_days`` días
    (RF-004-17)."""
    runner = _SESSION.runner
    if runner is None or runner.closed:
        return
    root = jobs_root(project)
    runner.reconfigure(jobs_root=root, forbidden_roots=_forbidden_roots(project))
    job_list.forget_stored()  # la lista vuelve a leer los guardados de la raíz nueva
    if project is None:
        return
    active = {snapshot.job_uid for snapshot in runner.snapshots() if snapshot.active}
    interrupted = records.mark_interrupted(root, active_uids=active)
    days = retention_days()
    report = runner.purge(older_than_days=days)
    if interrupted:
        LOGGER.info("Proyecto «%s»: %d trabajos que Blender dejó en marcha quedan "
                    "«Interrumpido»", project.name, len(interrupted))
    if report.removed:
        LOGGER.info("Proyecto «%s»: borradas %d carpetas de trabajos terminados hace más "
                    "de %d días (%s MB liberados)", project.name, len(report.removed), days,
                    format_number(report.freed_mb, 1))
    if report.failed:
        project_session.notify(_failed_text(report))


@bpy.app.handlers.persistent
def on_exit_pre(*_args: object) -> None:
    """Manejador ``exit_pre`` (persistente: sigue tras abrir otro ``.blend``): al salir de
    Blender, cierra el lanzador de la sesión (RF-004-13)."""
    _close_session()


classes: tuple[type, ...] = (GEOBLENDER_OT_jobs_show_jobs, GEOBLENDER_OT_jobs_cancel,
                             GEOBLENDER_OT_jobs_run_selftest, GEOBLENDER_OT_jobs_clean,
                             GEOBLENDER_OT_jobs_setup_runtime)


def register() -> None:
    """Textos de los trabajos (y los de la instalación del motor) en ``core.i18n``, tipos
    de trabajo de la 004, el lanzador de la sesión (dado al monitor), el manejador
    ``exit_pre`` y el aviso de cambio de proyecto; idempotente."""
    i18n.install(messages.CATALOG_ES)
    i18n.install(catalog.CATALOG_ES)
    i18n.install(jobs_runtime.CATALOG_ES)
    catalog.unregister_builtin_workers()
    catalog.register_builtin_workers()
    _open_session()
    if on_exit_pre not in bpy.app.handlers.exit_pre:
        bpy.app.handlers.exit_pre.append(on_exit_pre)
    project_session.add_listener(on_project_changed)


def unregister() -> None:
    """Quita el aviso de cambio de proyecto y el manejador ``exit_pre``, cierra el
    lanzador de la sesión (``shutdown(timeout_s=3)``) antes de retirar el temporizador del
    monitor, lo suelta, olvida la cadena del motor de cálculo y quita los tipos de trabajo
    de la 004; idempotente."""
    project_session.remove_listener(on_project_changed)
    if on_exit_pre in bpy.app.handlers.exit_pre:
        bpy.app.handlers.exit_pre.remove(on_exit_pre)
    try:
        _close_session()
    finally:
        _SESSION.runner = None
        MONITOR.attach(None)
        forget_setup()
        catalog.unregister_builtin_workers()
