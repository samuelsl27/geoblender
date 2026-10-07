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
temporizador y los quita. Los operadores ``geoblender.jobs_*`` llegan con T20 y T21.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import bpy

from ...core import i18n
from ...jobs import catalog, messages
from ...jobs.paths import JobDir
from ...jobs.protocol import JobRequest
from ...jobs.runner import JobHandle, JobResult, JobRunner, JobSnapshot
from ..ui import statusbar

TICK_S = 0.25
"""Cada cuánto sondea el temporizador (plan §5.4.4)."""
NOTICE_S = 10.0
"""Lo que dura en la barra de estado el aviso de un trabajo que acabó (RF-004-07)."""

LOGGER = logging.getLogger("geoblender.bl.ops")

classes: tuple[type, ...] = ()


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
        return min(100, max(0, math.floor(self.frac * 100 + 1e-9)))

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
        running = [snapshot for snapshot in active if snapshot.state == "running"]
        shown: dict[str, float] = {}
        for snapshot in running:
            previous = self._shown.get(snapshot.job_uid, 0.0)
            shown[snapshot.job_uid] = max(previous, _clamp(snapshot.frac))
        self._shown = shown
        if running:
            current: JobSnapshot | None = running[0]
            frac = shown[running[0].job_uid]
        else:
            current, frac = (active[0] if active else None), 0.0
        return StatusView(active=len(active), current=current, frac=frac, notice=notice)


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
