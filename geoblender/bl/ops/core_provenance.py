# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia en Blender (spec 008; plan 008 §5.1, §5.3.2, §5.3.4, §5.4.6, §5.4.13 y §5.5;
ADR-0025).

- Textos (T44): al registrar, :func:`register` instala en ``core.i18n`` los mensajes de la
  procedencia y de los parámetros (``CATALOG_ES`` de ``core.provenance.messages`` y de
  ``core.params``: los rechazos y avisos de la spec §8, los nombres visibles de las operaciones
  de ``core``, el estado de una entrada, las marcas de una cifra…), para que la interfaz los
  muestre con ``core.i18n.tr`` en el idioma de Geoblender. Sus órdenes tienen ya su
  ``bl_idname`` en el catálogo de la 003 (entrada ``008``): mientras no llegue aquí su clase
  real, la interfaz registra la provisional, que dice «Disponible en 008 · …».
- Carpetas de solo lectura (T45; RF-008-15; S-3 del plan; ADR-0025 §9): :func:`read_only_dirs`
  las da como están ahora (la variable ``GEOBLENDER_READ_ONLY_DIRS`` más la preferencia
  ``core.read_only_folders``), para pasarlas a ``core`` (``check_write_target``, crear, abrir,
  copiar y publicar). Si la lista está vacía (o lleva entradas que no son rutas completas),
  :func:`warn_read_only_dirs` lo avisa **una vez por sesión** (en los avisos del panel del
  proyecto y en el registro técnico): lo llama un temporizador justo después de registrar
  (en el registro aún no se pueden leer las preferencias); el diagnóstico de la instalación
  lo dice siempre (``bl.ui.help``).
- Declaraciones de ``core`` (T46; ADR-0025 §2, plan §5.3.4): :func:`register` registra lo que
  ``core`` declara para la procedencia —sus operaciones (``CORE_OPERATIONS``), el importador de
  las capas de un GeoPackage (:data:`CORE_IMPORTERS`), sus lectores de contenido
  (``CONTENT_READERS``) y el parámetro del límite de los originales (``core_defs``)— y
  :func:`unregister` quita lo que registró. Nada de eso lee el disco; el importador se carga al
  usarlo (registrar no carga ``core.provenance.importer``).
- La sesión de la procedencia (T46; RF-008-58, RF-008-09; RNF-008-12; plan §5.4.6):
  :data:`SESSION` (:class:`ProvenanceSession`) escucha los cambios de proyecto de la sesión
  (``bl.scene.project_session.add_listener``). Al abrir un proyecto con la procedencia (esquema
  2 o posterior, también en solo lectura) **no comprueba nada** —el proyecto queda usable como
  en la 002 (RNF-002-02)—: deja todo pendiente para la puerta (``CheckState``) y un temporizador
  **persistente** (:func:`check_tick`, cada :data:`TICK_S` s) que un tic después empieza la
  comprobación de apertura (``core.provenance.checks.open_check_steps``) y la avanza un paso
  por tic, de :data:`STEP_BUDGET_S` s como mucho, con su progreso para la barra de estado
  («Comprobando el proyecto… 42 %»). Al terminar queda su informe
  (:attr:`ProvenanceSession.report`, el de la sesión en solo lectura) y sus avisos en los de la
  sesión; si la puerta pidió hashes que no entraron, se hacen después
  (``hash_requests_steps``), igual que los que pida más tarde
  (:meth:`ProvenanceSession.request_hashes`). Un proyecto sin la procedencia (esquema 1 sin
  migrar, o uno posterior del que solo se lee la cabecera) no arranca nada:
  :meth:`ProvenanceSession.unavailable` da el motivo que muestran los paneles. Cerrar o abrir
  otro proyecto, y desactivar Geoblender, paran la comprobación y cancelan lo pendiente.
- El trabajo de hash (T47; RF-008-09, RNF-008-11; plan §5.3.3): :func:`register` registra el
  tipo de trabajo ``core_content_hash`` (``jobs.content_hash.WORKER_INFO``) y da a la sesión
  :data:`HASH_JOBS`, con el que la comprobación manda el hash de las fuentes externas grandes
  al lanzador de la sesión (con el monitor de los trabajos, que lo sigue en la barra de
  estado), con las rutas de la fuente en la línea de órdenes; :func:`unregister` lo quita.

- Ayudas para los módulos (T48; plan §5.3.4 «Calcular», «Exportar» y «Mostrar», §5.4.7):
  :class:`ProvenanceAwareOperator`, la base de sus operadores, junto con ``bpy.types.Operator``:

  - :func:`ensure_ready`, la puerta antes de operar (``core.provenance.gate.can_run`` con lo
    pendiente de la sesión): con lo aún sin comprobar, espera (y pide los hashes,
    :meth:`ProvenanceSession.request_hashes`); con una entrada cambiada sin decidir aguas
    arriba, se niega y, lanzada desde la interfaz, abre su diálogo (:func:`open_input_dialog`,
    la orden :data:`RESOLVE_INPUT`: Actualizar, Mantener la copia, Cancelar; RF-008-10,
    RF-008-61); con lo que falta, está bloqueado o dañado, se niega con su motivo;
  - ``begin`` (``begin_operation`` tras la puerta: «en curso», RF-008-51) y :func:`launch_job`,
    que lanza con el monitor de los trabajos el trabajo de la 004 de esa operación (con su
    ``operation_uid``); al terminar, el módulo la incorpora con :func:`ingest_job_result`
    (``jobs.ingest.job_outcome`` → ``ingest_job`` → ``JobRunner.mark_ingested``; RF-008-20).
    Un trabajo que no termina bien deja la operación cancelada o fallida con el motivo de la
    004. Hasta incorporarla, la lista de trabajos (:func:`job_note`) y la procedencia la dicen
    «pendiente de incorporar» (RF-008-23); si la 004 borra la carpeta de su trabajo antes
    (descartarlo, limpiar o la purga), :func:`on_jobs_removed` la deja «no incorporada» con
    el motivo (:data:`NOT_INGESTED_REASONS`). Lo pendiente de incorporar es de esta sesión de
    Blender (el equipo que lanzó el trabajo): las operaciones que quedan «en curso» al
    cerrarla se registran «interrumpidas» al abrir el proyecto en escritura otra sesión;
  - :func:`check_write_target`: antes de escribir un entregable, la guarda de ``core`` con el
    proyecto de la sesión y :func:`read_only_dirs` (RF-008-15).

Lo demás llega con las tareas siguientes: los operadores de §5.3.2, con los paneles, y el
estado de comando de las órdenes de los módulos (fase 8).

``core.i18n`` no tiene cómo quitar traducciones: :func:`unregister` las deja (como los
trabajos de la 004), y volver a registrar las instala otra vez sin cambiar nada.

En ``blender -b`` los temporizadores no se ejecutan: las pruebas llaman a :func:`check_tick`.
"""

from __future__ import annotations

import functools
import logging
import os
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import bpy

from ...core import i18n, params
from ...core.content import readers as content_readers
from ...core.content.builtin import CONTENT_READERS, GPKG_LAYER
from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.inputs.guard import check_write_target as guard_write_target
from ...core.inputs.guard import read_only_warnings
from ...core.params import core_defs
from ...core.paths import ReadOnlyDirs
from ...core.project.migrations import m0002
from ...core.provenance import contract, messages
from ...jobs import catalog as job_catalog
from ...jobs import content_hash
from ...jobs.protocol import new_request
from .. import ADDON_PACKAGE
from ..props.core import read_only_dirs_of
from ..scene import project_session
from ..ui import jobs as job_list
from ..ui import statusbar
from . import jobs as jobs_ops

if TYPE_CHECKING:
    from pathlib import Path

    from ...core.datasets.model import DatasetSpec
    from ...core.project.model import Progress
    from ...core.project.session import Project
    from ...core.provenance.checks import OpenCheckOutcome
    from ...core.provenance.contract import ReimportRequest
    from ...core.provenance.figures import FigureSpec
    from ...core.provenance.gate import BlockReason, CheckState, Ready
    from ...core.provenance.operations import IngestOutcome, IngestWriter, OperationHandle
    from ...jobs.protocol import JobRequest
    from ...jobs.runner import JobHandle, JobResult, JobRunner, JobSnapshot

LOGGER = logging.getLogger("geoblender.bl.ops")

TICK_S = 0.05
"""Cada cuánto avanza el temporizador de la comprobación (plan §5.4.6), en segundos."""

STEP_BUDGET_S = 0.020
"""Lo que dura como mucho cada paso de la comprobación (RNF-008-12: la interfaz responde en
≤ 0,1 s mientras corre)."""

PROVENANCE_SCHEMA = m0002.MIGRATION.to_version
"""El primer esquema del proyecto con la procedencia: el de la migración 1 → 2."""

_OPEN = "open"  # la comprobación de apertura (los ocho pasos)
_REQUESTS = "requests"  # los hashes que pidió la puerta (pasos 7 y 8)

classes: tuple[type, ...] = ()


class _State:
    """Estado de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.read_only_checked = False  # ya se miró (y, si tocaba, se avisó) en esta sesión
        self.undo: list[Callable[[], object]] = []  # cómo quitar lo que se registró
        self.jobs: dict[str, _PendingJob] = {}  # job_uid → operación pendiente de incorporar


_STATE = _State()


# Carpetas de solo lectura -----------------------------------------------------------------


def _core_preferences() -> Any:
    """El grupo ``core`` de las preferencias de la extensión, o ``None`` si aún no están (una
    habilitación sin ``default_set``, o durante el registro)."""
    addon = bpy.context.preferences.addons.get(ADDON_PACKAGE)
    return getattr(getattr(addon, "preferences", None), "core", None)


def read_only_dirs() -> ReadOnlyDirs:
    """Las carpetas de solo lectura de ahora (RF-008-15): las de la variable
    ``GEOBLENDER_READ_ONLY_DIRS`` más las de la preferencia ``core.read_only_folders``, leídas en
    cada llamada (una preferencia cambiada vale en la orden siguiente)."""
    return read_only_dirs_of(_core_preferences())


def warn_read_only_dirs() -> None:
    """Una vez por sesión (S-3): si no hay ninguna carpeta de solo lectura, o alguna entrada no
    es una ruta completa, deja cada aviso en los de la sesión (``project_session.notify``: el
    panel del proyecto y el registro técnico). Las siguientes llamadas no hacen nada. Es el
    temporizador de :func:`register` (sin repetición: devuelve ``None``)."""
    if _STATE.read_only_checked:
        return None
    _STATE.read_only_checked = True
    for text in read_only_warnings(read_only_dirs(), i18n.language()):
        project_session.notify(text)
    return None


def forget_read_only_warning() -> None:
    """Olvida que ya se miró en esta sesión (al desregistrar; y en las pruebas)."""
    _STATE.read_only_checked = False


# La sesión de la procedencia --------------------------------------------------------------


class ProvenanceSession:
    """La procedencia del proyecto de la sesión en Blender (plan §5.1 y §5.4.6): el monitor de
    la comprobación de apertura y de los hashes que pide la puerta, con lo que aún no se ha
    comprobado (:attr:`pending`, el ``CheckState`` del proyecto que usa la puerta), su progreso
    y su informe. Lo avanza :func:`check_tick` desde un temporizador, en el hilo de Blender (sin
    hilos propios, ARQ-19)."""

    def __init__(self) -> None:
        self.hash_jobs: Any = None
        """Los trabajos de hash de las fuentes externas grandes (``checks.HashJobs``: los de
        :data:`HASH_JOBS` mientras Geoblender está registrado); ``None``: todo en el hilo, por
        trozos."""
        self._project: Project | None = None
        self._pending: CheckState | None = None
        self._next: str | None = None  # lo que empieza en el próximo tic
        self._kind: str | None = None  # lo que está en marcha
        self._steps: Iterator[Progress] | None = None
        self._asked: frozenset[tuple[str, str]] = frozenset()  # lo pedido al empezar
        self._progress: Progress | None = None
        self._report: OpenCheckOutcome | None = None

    # Lo que se ve -------------------------------------------------------------------------

    @property
    def project(self) -> Project | None:
        """El proyecto que sigue (el de la sesión), o ``None``."""
        return self._project

    @property
    def pending(self) -> CheckState:
        """Lo que la comprobación de apertura aún no ha comprobado y los hashes pedidos
        (``core.provenance.gate.CheckState``), para la puerta. Si hay una comprobación prevista
        que aún no ha empezado, todo está pendiente."""
        if self._pending is None:
            from ...core.provenance.gate import CheckState  # al usarlo: abrir no lo carga

            self._pending = CheckState()
            if self._next == _OPEN:
                self._pending.start()
        return self._pending

    @property
    def running(self) -> bool:
        """Si hay una comprobación en marcha o prevista para el próximo tic."""
        return self._next is not None or self._steps is not None

    @property
    def progress(self) -> Progress | None:
        """El último paso dado (``core.project.model.Progress``), o ``None`` si aún no ha
        empezado ninguno."""
        return self._progress

    @property
    def percent(self) -> int:
        """El progreso del último paso, en % entero (0 sin pasos)."""
        step = self._progress
        if step is None or step.total <= 0:
            return 0
        return min(100, max(0, step.done * 100 // step.total))

    @property
    def report(self) -> OpenCheckOutcome | None:
        """El informe de la última comprobación de apertura terminada del proyecto
        (``core.provenance.checks.OpenCheckOutcome``; en solo lectura, lo detectado sin
        registrar), o ``None``."""
        return self._report

    def unavailable(self) -> str | None:
        """Por qué el proyecto de la sesión no tiene procedencia (lo que dicen los paneles y
        las órdenes de la 008), en el idioma de Geoblender, o ``None`` si la tiene: sin
        proyecto, «Abra un proyecto»; uno del esquema 1 sin migrar, que hay que migrarlo; uno
        del que solo se lee la cabecera, su motivo de solo lectura."""
        project = self._project
        if project is None or project.closed:
            return tr("Open a project")
        if project.header_only:
            return tr("Read-only project: {reason}", reason=project.status.message)
        if project.schema_version < PROVENANCE_SCHEMA:
            return tr("Schema {schema} project: migrate the project to use provenance",
                      schema=project.schema_version)
        return None

    def status_text(self) -> str | None:
        """«Comprobando el proyecto… 42 %» mientras hay una comprobación en marcha o prevista;
        si no, ``None``."""
        if not self.running:
            return None
        return tr("Checking the project… {percent} %", percent=self.percent)

    # Lo que la cambia ---------------------------------------------------------------------

    def on_project_changed(self, project: Project | None) -> None:
        """La sesión pasó a tener ``project`` (o ninguno): para lo que hubiera del anterior,
        lo olvida y, si el nuevo tiene la procedencia, deja todo pendiente y la comprobación
        de apertura para el próximo tic, sin hacer nada más (RNF-002-02 no cambia)."""
        if project is self._project:
            return
        self.reset()
        self._project = project
        if project is not None and self.unavailable() is None:
            self._next = _OPEN
            _schedule()

    def request_hashes(self) -> bool:
        """Los hashes que pidió la puerta (``pending.requests``) se harán: con una comprobación
        en marcha, al terminarla; si no, empiezan en el próximo tic. Dice si hay algo que
        hacer."""
        if self.running:
            return True
        if self.unavailable() is not None or not self.pending.requests:
            return False
        self._next, self._progress = _REQUESTS, None
        _schedule()
        return True

    def cancel(self) -> None:
        """Para la comprobación en marcha o prevista (lo que tenía en trabajos se cancela y no
        se registra nada) y la puerta deja de esperarla; lo pedido sigue pedido."""
        steps, self._steps = self._steps, None
        busy = self._next is not None or steps is not None
        self._next = None
        self._kind = None
        if steps is not None:
            _close(steps)
        if self._pending is not None:
            self._pending.finish()
        _retire()
        if busy:
            statusbar.redraw()

    def reset(self) -> None:
        """:meth:`cancel` y olvida el proyecto, lo pendiente, el progreso y el informe."""
        self.cancel()
        self._project = None
        self._pending = None
        self._asked = frozenset()
        self._progress = None
        self._report = None

    # El temporizador ----------------------------------------------------------------------

    def tick(self) -> float | None:
        """Un paso (≤ :data:`STEP_BUDGET_S` s): empieza lo previsto o avanza lo que está en
        marcha. Devuelve :data:`TICK_S` mientras queda algo; si no, retira el temporizador y
        devuelve ``None``. Si la comprobación falla, se para y lo avisa."""
        shown = self.percent
        try:
            if self._steps is None:
                if self._next is None:
                    _retire()
                    return None
                self._kind, self._next = self._next, None
                self._steps = self._start(self._kind)
            step = next(self._steps)
        except StopIteration:
            self._steps = None
            self._kind = None
        except Exception as exc:  # noqa: BLE001 - un temporizador que falla no tumba Blender
            self._fail(exc)
            return None
        else:
            self._progress = step
            if _outcome_of(step) is not None:
                self._finish(step.result)
        if self.percent != shown or not self.running:
            statusbar.redraw()
        if self.running:
            return TICK_S
        _retire()
        return None

    def _start(self, kind: str) -> Iterator[Progress]:
        from ...core.provenance import checks  # al usarlo: abrir no lo carga

        project = self._project
        pending = self.pending
        if kind == _OPEN:
            self._asked = frozenset()
            return checks.open_check_steps(project, write=project.writable, pending=pending,
                                           jobs=self.hash_jobs, budget_s=STEP_BUDGET_S)
        self._asked = _keys(pending.requests)
        return checks.hash_requests_steps(project, pending, jobs=self.hash_jobs,
                                          budget_s=STEP_BUDGET_S)

    def _finish(self, outcome: OpenCheckOutcome) -> None:
        steps, self._steps = self._steps, None
        if steps is not None:
            _close(steps)
        if self._kind == _OPEN:
            self._report = outcome
        self._kind = None
        for text in outcome.texts(i18n.language()):
            project_session.notify(text)
        if _keys(self.pending.requests) - self._asked:
            self._next = _REQUESTS  # lo que la puerta pidió mientras tanto
            self._progress = None

    def _fail(self, exc: BaseException) -> None:
        steps, self._steps = self._steps, None
        self._next = None
        self._kind = None
        if steps is not None:
            _close(steps)
        if self._pending is not None:
            self._pending.finish()
        _retire()
        LOGGER.error("La comprobación del proyecto se ha parado", exc_info=exc)
        project_session.notify(tr("The project check stopped: {error}",
                                  error=str(exc) or type(exc).__name__))
        statusbar.redraw()


def _outcome_of(step: Progress) -> object | None:
    """El resultado del último paso (el ``OpenCheckOutcome``), o ``None`` en los demás."""
    from ...core.provenance.checks import OpenCheckOutcome

    return step.result if isinstance(step.result, OpenCheckOutcome) else None


def _keys(items: Iterable[Any]) -> frozenset[tuple[str, str]]:
    return frozenset((str(item.item_kind), item.uid) for item in items)


def _close(steps: Iterator[Progress]) -> None:
    """Cierra un generador de pasos (cancela sus trabajos; la puerta deja de esperarlo)."""
    try:
        steps.close()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - parar no tumba Blender: va al registro técnico
        LOGGER.exception("Falló al parar la comprobación del proyecto")


SESSION = ProvenanceSession()
"""La sesión de la procedencia de este Blender."""


def check_tick() -> float | None:
    """La función del temporizador: :meth:`ProvenanceSession.tick` de :data:`SESSION`."""
    return SESSION.tick()


def on_project_changed(project: Project | None) -> None:
    """Lo que se apunta en ``project_session``: :meth:`ProvenanceSession.on_project_changed`."""
    SESSION.on_project_changed(project)


def _schedule() -> None:
    """Pone el temporizador (persistente: sigue si se abre otro ``.blend``) si no está."""
    if not bpy.app.timers.is_registered(check_tick):
        bpy.app.timers.register(check_tick, first_interval=TICK_S, persistent=True)


def _retire() -> None:
    if bpy.app.timers.is_registered(check_tick):
        bpy.app.timers.unregister(check_tick)


# Declaraciones de ``core`` -----------------------------------------------------------------


def _reimport_layer(request: ReimportRequest) -> Any:
    """El importador de ``core.gpkg_layer`` (``core.provenance.importer.reimport_layer``),
    cargado al usarlo."""
    from ...core.provenance.importer import reimport_layer

    return reimport_layer(request)


CORE_IMPORTERS: tuple[contract.ImporterDef, ...] = (
    contract.ImporterDef(GPKG_LAYER.reader_id, _reimport_layer),
)
"""El importador de ``core`` que se registra: el de ``core.provenance.importer.CORE_IMPORTERS``
(el mismo lector y la misma función), sin cargar el importador al registrar."""


# El trabajo de hash -----------------------------------------------------------------------


def _session_runner() -> JobRunner | None:
    """El lanzador de trabajos de la sesión (``bl.ops.jobs``), si lo hay y admite trabajos."""
    runner = jobs_ops.MONITOR.runner
    if runner is None or runner.closed:
        return None
    return runner


def _monitor_submit(runner: JobRunner, request: JobRequest,
                    paths: Mapping[str, Path]) -> JobHandle:
    """Lanza un trabajo de hash con el monitor de los trabajos (que lo sigue en la barra de
    estado); ``runner`` es su lanzador."""
    return jobs_ops.MONITOR.submit(request, paths=paths)


HASH_JOBS = content_hash.ContentHashJobs(_session_runner, submit=_monitor_submit)
"""Los trabajos de hash de la sesión (T47; RF-008-09, RNF-008-11, plan §5.3.3): el trabajo
``core_content_hash`` con el lanzador de la sesión, con la ruta de la fuente en la línea de
órdenes. Es el ``hash_jobs`` de :data:`SESSION` mientras Geoblender está registrado."""


def _register_declarations() -> None:
    """Registra lo que ``core`` declara y aún no está registrado, y apunta cómo quitarlo."""
    undo = _STATE.undo
    missing = [defn for defn in core_defs.DEFINITIONS if defn.key not in params.DEFINITIONS]
    if missing:
        params.register_definitions(missing)
        undo.append(lambda: params.unregister_definitions("core"))
    for defn in contract.CORE_OPERATIONS:
        if defn.op_type not in contract.OPERATIONS:
            contract.register_operation(defn)
            undo.append(_unregister_if(contract.OPERATIONS, defn.op_type, defn,
                                       contract.unregister_operation))
    for importer in CORE_IMPORTERS:
        if importer.reader_id not in contract.IMPORTERS:
            contract.register_importer(importer)
            undo.append(_unregister_if(contract.IMPORTERS, importer.reader_id, importer,
                                       contract.unregister_importer))
    for reader in CONTENT_READERS:
        if reader.id not in content_readers.READERS:
            content_readers.register_reader(reader)
            undo.append(_unregister_if(content_readers.READERS, reader.id, reader,
                                       content_readers.unregister_reader))
    info = content_hash.WORKER_INFO
    if info.name not in job_catalog.WORKERS:
        job_catalog.register_worker(info)
        undo.append(_unregister_if(job_catalog.WORKERS, info.name, info,
                                   job_catalog.unregister_worker))


def _unregister_if(view: Any, key: str, item: object,
                   remove: Callable[[str], int]) -> Callable[[], None]:
    def undo() -> None:
        if view.get(key) is item:  # si otro lo cambió, es suyo
            remove(key)

    return undo


def _unregister_declarations() -> None:
    """Quita lo que registró :func:`_register_declarations`, en orden inverso."""
    while _STATE.undo:
        _STATE.undo.pop()()


# Ayudas para los módulos (T48) ------------------------------------------------------------

RESOLVE_INPUT = "geoblender.core_resolve_input"
"""La orden del diálogo de una entrada cambiada (RF-008-10; plan §5.3.2): Actualizar, Mantener
la copia y Cancelar, con el ``input_uid`` de la entrada."""

NOT_INGESTED_REASONS: Mapping[str, str] = MappingProxyType({
    jobs_ops.REMOVED_DISCARDED: "se descartó su trabajo «{job}» en la lista de trabajos sin "
                                "incorporarlo",
    jobs_ops.REMOVED_CLEANED: "se borró la carpeta de su trabajo «{job}» al limpiar los "
                              "trabajos terminados sin incorporarlo",
    jobs_ops.REMOVED_PURGED: "se borró la carpeta de su trabajo «{job}» por antigüedad sin "
                             "incorporarlo",
})
"""El motivo que queda en el proyecto (en español, como los demás motivos guardados) de una
operación cuyo trabajo se borró sin incorporarlo, según por qué se borró (RF-008-23)."""

RELEASE_WAIT_S = 0.1
"""Lo que espera como mucho :func:`ingest_job_result` a que acabe el hilo de un trabajo en hilo
que ya terminó, para darlo por incorporado (``JobRunner.mark_ingested`` no lo hace mientras
su hilo sigue vivo)."""

_SUCCEEDED = "succeeded"  # el final de un trabajo que terminó bien (jobs.records)

type Report = Callable[[set[str], str], object]
"""Cómo se dicen las cosas: ``Operator.report`` (tipo y texto)."""


@dataclass(frozen=True, slots=True)
class _PendingJob:
    """Un trabajo lanzado con :func:`launch_job` cuya operación aún no se ha incorporado."""

    handle: OperationHandle
    label: str
    on_finish: Callable[[JobResult], object] | None


def _notify(_kind: set[str], text: str) -> None:
    """Sin operador, lo que se dice va a los avisos de la sesión."""
    project_session.notify(text)


def error_text(exc: BaseException) -> str:
    """El texto de un error para el usuario en el idioma de Geoblender: el de la procedencia
    en su idioma; el de otro error de Geoblender, su mensaje (en español)."""
    if isinstance(exc, messages.ProvenanceError):
        return messages.render(exc.code, language=i18n.language(), **exc.values)
    if isinstance(exc, GeoblenderError):
        return exc.message
    return str(exc) or type(exc).__name__


def write_unavailable() -> str | None:
    """Por qué no se puede lanzar ahora una operación registrada (lo que dice el ``poll`` de
    :class:`ProvenanceAwareOperator`), en el idioma de Geoblender, o ``None`` si se puede: sin
    proyecto, sin la procedencia o en solo lectura, con su motivo."""
    reason = SESSION.unavailable()
    if reason is not None:
        return reason
    project = SESSION.project
    if project is not None and not project.writable:
        return tr("Read-only project: {reason}", reason=project.status.message)
    return None


def ensure_ready(op_type: str, inputs: Sequence[Any] = (), *, report: Report | None = None,
                 dialog: bool = False) -> Ready | None:
    """La puerta antes de empezar una operación de tipo ``op_type`` que consume ``inputs``
    (``core.provenance.operations.Use``) en el proyecto de la sesión, con lo que su
    comprobación de apertura aún no ha comprobado (RF-008-10, RF-008-21, RF-008-56 a 58; plan
    §5.3.4 «Calcular» y §5.4.5). Devuelve el ``Ready`` de la puerta (sus avisos ya dichos, y
    lo que consume que está obsoleto) si se puede ejecutar; si no, dice por qué con
    ``report`` (``Operator.report``; sin él, en los avisos de la sesión) y devuelve ``None``:

    - sin proyecto, sin la procedencia o en solo lectura: su motivo;
    - con algo aún sin comprobar o un hash largo pedido: «Comprobando el proyecto…: espere a
      que termine» (aviso), y lo pedido se hace (:meth:`ProvenanceSession.request_hashes`);
    - con una entrada cambiada sin decidir aguas arriba (RF-008-10) y ``dialog`` (la orden se
      lanzó desde la interfaz), abre su diálogo (:func:`open_input_dialog`) y lo dice como
      aviso; sin ``dialog`` (un guion), como error, igual que lo que falta, está bloqueado o
      dañado."""
    say = _notify if report is None else report
    unavailable = write_unavailable()
    if unavailable is not None:
        say({"ERROR"}, unavailable)
        return None
    from ...core.provenance import gate  # al usarlo: registrar no lo carga

    language = i18n.language()
    try:
        result = gate.can_run(SESSION.project, op_type, inputs, pending=SESSION.pending)
    except GeoblenderError as exc:
        say({"ERROR"}, error_text(exc))
        return None
    if isinstance(result, gate.Pending):
        SESSION.request_hashes()
        say({"WARNING"}, result.text(language))
        return None
    if isinstance(result, gate.Blocked):
        changed = [reason for reason in result.reasons
                   if reason.kind is gate.BlockKind.INPUT_CHANGED]
        opened = bool(dialog and changed)
        if opened:
            open_input_dialog(changed[0])
        say({"WARNING"} if opened else {"ERROR"}, result.text(language))
        return None
    for notice in result.notices:
        say({"WARNING"}, notice.text(language))
    return result


def open_input_dialog(reason: BlockReason) -> set[str]:
    """Abre el diálogo de la entrada cambiada de ``reason`` (RF-008-10, RF-008-61; plan
    §5.3.2): la orden :data:`RESOLVE_INPUT` con su ``input_uid`` (Actualizar, Mantener la copia
    y Cancelar). Mientras su clase real no llegue (T52), la provisional dice «Disponible en
    008». Si no se puede abrir, lo deja en el registro técnico y devuelve ``{"CANCELLED"}``."""
    group, name = RESOLVE_INPUT.split(".")
    try:
        operator = getattr(getattr(bpy.ops, group), name)
        values: dict[str, Any] = {}
        if "input_uid" in operator.get_rna_type().properties.keys():
            values["input_uid"] = reason.uid or ""
        return set(operator("INVOKE_DEFAULT", **values))
    except (RuntimeError, KeyError, AttributeError, TypeError):
        LOGGER.warning("No se pudo abrir el diálogo de la entrada cambiada «%s»", reason.name,
                       exc_info=True)
        return {"CANCELLED"}


def check_write_target(path: str | os.PathLike[str]) -> None:
    """Rechaza (``ProvenanceError``, sin escribir nada) que un módulo escriba en ``path`` un
    entregable o cualquier fichero fuera de lo que gestiona el proyecto, si es o está dentro de
    una carpeta de solo lectura (:func:`read_only_dirs`, las de ahora), de la carpeta de la
    fuente de una entrada del proyecto de la sesión que está fuera de él o es el fichero de una
    fuente que está dentro (RF-008-15; ``core.inputs.guard.check_write_target``)."""
    project = SESSION.project
    if project is not None and (project.closed or project.header_only):
        project = None  # no se puede leer: cuentan solo las carpetas de solo lectura
    guard_write_target(path, project=project, read_only=read_only_dirs())


def pending_ingests() -> dict[str, str]:
    """Los trabajos lanzados en esta sesión con :func:`launch_job` cuya operación aún no se ha
    incorporado: su ``job_uid`` y el uid de su operación."""
    return {job_uid: entry.handle.uid for job_uid, entry in _STATE.jobs.items()}


def job_note(snapshot: JobSnapshot) -> str | None:
    """La nota de un trabajo en la lista de trabajos (``bl.ui.jobs.set_note_provider``;
    RF-008-23): «pendiente de incorporar» si su operación aún no se ha incorporado; si no,
    ``None``."""
    if snapshot.job_uid not in _STATE.jobs:
        return None
    return messages.render("core.result_pending", language=i18n.language())


def launch_job(handle: OperationHandle, worker: str, *, label: str,
               params: Mapping[str, Any] | None = None, paths: Mapping[str, Path] | None = None,
               on_finish: Callable[[JobResult], object] | None = None,
               **request: Any) -> JobHandle:
    """Lanza el trabajo de la 004 de la operación ``handle`` («en curso» desde
    ``begin_operation``; RF-008-51, RF-008-20; plan §5.3.4 «Calcular») con el monitor de los
    trabajos, que lo sigue en la barra de estado: tipo ``worker``, nombre visible ``label``,
    ``params``, las rutas absolutas ``paths`` (en la línea de órdenes, nunca en la petición) y
    lo demás de ``jobs.protocol.new_request`` (``request``), con el ``operation_uid`` de la
    operación, el proyecto y su módulo como dueño. Al terminar, en el hilo de Blender, llama a
    ``on_finish`` con su ``JobResult``: ahí (o después) el módulo la incorpora con
    :func:`ingest_job_result`; si el trabajo no terminó bien y no la incorporó, la operación
    queda cancelada o fallida con el motivo de la 004. Hasta incorporarla, «pendiente de
    incorporar» (:func:`job_note`). Si no se puede lanzar, la operación queda fallida con el
    motivo y el error sigue: :class:`RuntimeError` sin lanzador de trabajos, ``JobError`` con
    una petición que no vale y :class:`ValueError` con una ruta que no vale."""
    from ...core.provenance.operations import failure_reason

    try:
        runner = jobs_ops.MONITOR.runner
        if runner is None or runner.closed:
            raise RuntimeError("no hay lanzador de trabajos: Geoblender aún no ha preparado la "
                               "carpeta de los trabajos")
        job_request = new_request(worker, label=label, owner=handle.definition.module,
                                  params=params, project_uid=handle.project_uid,
                                  operation_uid=handle.uid, **request)
        finished = functools.partial(_job_finished, job_request.job_uid)
        job = jobs_ops.MONITOR.submit(job_request, on_finish=finished, paths=paths)
    except Exception as exc:
        try:
            handle.fail(failure_reason(exc))
        except Exception:  # noqa: BLE001 - el error que sigue es el de lanzarlo
            LOGGER.warning("La operación «%s» (%s) sigue «en curso»: no se pudo dejar fallida",
                           handle.op_type, handle.uid, exc_info=True)
        raise
    _STATE.jobs[job.job_uid] = _PendingJob(handle, label, on_finish)
    return job


def _job_finished(job_uid: str, result: JobResult) -> None:
    """El aviso de fin de un trabajo de :func:`launch_job` (en el sondeo del monitor, en el
    hilo de Blender): el ``on_finish`` del módulo y, si el trabajo no terminó bien y la
    operación sigue sin incorporar, :func:`ingest_job_result`, que la deja cancelada o fallida
    con el motivo de la 004."""
    entry = _STATE.jobs.get(job_uid)
    if entry is None:
        return
    try:
        if entry.on_finish is not None:
            entry.on_finish(result)
    finally:
        if job_uid in _STATE.jobs and result.state != _SUCCEEDED:
            ingest_job_result(entry.handle, result)


def ingest_job_result(
    handle: OperationHandle,
    result: JobResult,
    outputs: Sequence[DatasetSpec] | IngestWriter = (),
    *,
    figures: Sequence[FigureSpec] = (),
    software: Mapping[str, str] | None = None,
    message: str | None = None,
) -> IngestOutcome:
    """Incorpora a su operación ``handle`` el trabajo de la 004 que terminó con ``result``
    (RF-008-20, RF-008-23; plan §5.4.7): su final y la procedencia técnica de su
    ``state.json`` (``jobs.ingest.job_outcome``) → ``core.provenance.operations.ingest_job``
    con ``outputs`` (las salidas ya guardadas o la función que escribe los resultados del
    módulo en la transacción y las devuelve), ``figures``, ``software`` y ``message`` → el
    lanzador lo da por incorporado (``mark_ingested``: se borran sus entradas y sus
    resultados). Devuelve el ``IngestOutcome`` (hecha, y obsoleta si algo de lo que consumió
    cambió mientras se calculaba; o cancelada o fallida con el motivo de la 004). Si la
    incorporación falla, el error sigue: la operación queda fallida y el trabajo, con sus
    resultados, sin incorporar; en solo lectura o con el proyecto cerrado, sigue «pendiente de
    incorporar»."""
    from ...core.provenance.operations import ingest_job
    from ...jobs.ingest import job_outcome

    outcome = job_outcome(result, result.job_dir)
    try:
        ingested = ingest_job(handle.project, handle, outcome, outputs, figures=figures,
                              software=software, message=message)
    except BaseException:
        if not _still_pending(handle):
            _STATE.jobs.pop(result.job_uid, None)
        raise
    _STATE.jobs.pop(result.job_uid, None)
    _release(result.job_uid)
    return ingested


def _still_pending(handle: OperationHandle) -> bool:
    """Si la operación sigue «pendiente de incorporar» en el proyecto (si no se puede leer,
    se da por pendiente)."""
    from ...core.provenance.lineage import ResultState, result_state

    try:
        return result_state(handle.project, handle.uid).state is ResultState.PENDING
    except Exception:  # noqa: BLE001 - sin poder leerlo, sigue pendiente
        return True


def _release(job_uid: str) -> None:
    """El lanzador da el trabajo por incorporado (``JobRunner.mark_ingested``), esperando
    como mucho :data:`RELEASE_WAIT_S` a que acabe su hilo; si no puede, lo deja en el registro
    técnico (el trabajo queda en la lista, con sus resultados)."""
    runner = jobs_ops.MONITOR.runner
    if runner is None or runner.closed:
        return
    deadline = time.monotonic() + RELEASE_WAIT_S
    while True:
        try:
            runner.mark_ingested(job_uid)
            return
        except ValueError:
            if time.monotonic() >= deadline:
                LOGGER.warning("El trabajo %s no se pudo dar por incorporado", job_uid,
                               exc_info=True)
                return
            time.sleep(0.002)
        except OSError:
            LOGGER.warning("El trabajo %s no se pudo dar por incorporado", job_uid,
                           exc_info=True)
            return


def on_jobs_removed(job_uids: tuple[str, ...], why: str) -> None:
    """Lo que se apunta en ``bl.ops.jobs`` (RF-008-23; plan §5.4.7): de cada trabajo de esta
    sesión cuya carpeta se borró sin incorporar su operación (``why``: descartarlo en la
    lista, limpiar o la purga por antigüedad), la operación pasa a «no incorporada» con el
    motivo (:data:`NOT_INGESTED_REASONS`). Si no se puede (solo lectura, proyecto cerrado),
    sigue «en curso» y queda en el registro técnico."""
    from ...core.provenance.operations import mark_not_ingested

    template = NOT_INGESTED_REASONS.get(why, NOT_INGESTED_REASONS[jobs_ops.REMOVED_CLEANED])
    for job_uid in job_uids:
        entry = _STATE.jobs.pop(job_uid, None)
        if entry is None:
            continue
        handle = entry.handle
        try:
            mark_not_ingested(handle.project, handle.uid, template.format(job=entry.label))
        except Exception:  # noqa: BLE001 - la limpieza de los trabajos sigue
            LOGGER.warning("La operación «%s» (%s) sigue «en curso»: no se pudo dejar «no "
                           "incorporada»", handle.op_type, handle.uid, exc_info=True)


class ProvenanceAwareOperator:
    """La base de los operadores de los módulos que lanzan una operación registrada (plan
    §5.3.4 «Calcular», «Exportar» y «Mostrar»; RF-008-10, RF-008-15, RF-008-20, RF-008-23,
    RF-008-51, RF-008-61), junto con ``bpy.types.Operator``::

        class GEOBLENDER_OT_gis_resample(ProvenanceAwareOperator, bpy.types.Operator): ...

    Declara :attr:`provenance_op_type`, el tipo de su ``OperationDef`` (cuyo ``commands``
    lleva su ``bl_idname``), y, si consume algo, :meth:`provenance_inputs`. Da:

    - ``poll``: sin proyecto, sin la procedencia o en solo lectura, no está disponible y dice
      por qué (:func:`write_unavailable`);
    - ``invoke`` (desde la interfaz) → ``execute``: la puerta abrirá el diálogo de una entrada
      cambiada; un ``invoke`` propio llama a ``super().invoke`` o pone antes
      ``self.provenance_dialog = True``;
    - :meth:`begin` (la puerta y ``begin_operation``), :meth:`launch_job` (su trabajo de la
      004, que el módulo incorpora con :func:`ingest_job_result`) y :meth:`check_write_target`
      (antes de escribir un entregable); cada una dice lo que impide seguir con
      ``Operator.report`` y devuelve ``None`` o falso.

    Los operadores no calculan (ARQ): validan, llaman al dominio y presentan el resultado."""

    # Sin anotaciones: Blender toma las de la clase por propiedades del operador.
    provenance_op_type = ""
    """El tipo de la operación que lanza (``gis.resample``)."""

    provenance_dialog = False
    """Si se lanzó desde la interfaz (``invoke``): la puerta abre el diálogo de una entrada
    cambiada; desde un guion, solo lo dice."""

    @classmethod
    def poll(cls, context: Any) -> bool:
        reason = write_unavailable()
        if reason is not None:
            cls.poll_message_set(reason)  # type: ignore[attr-defined]
            return False
        return True

    def provenance_inputs(self, context: Any) -> Sequence[Any]:
        """Lo que consume la operación (``Use``): por defecto, nada."""
        return ()

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        return self.execute(context)  # type: ignore[attr-defined]

    def begin(self, context: Any, *, settings: Mapping[str, Any] | None = None,
              params: Sequence[str] = (), executor: str = "blender",
              group_uid: str | None = None,
              supersedes: str | None = None) -> OperationHandle | None:
        """La puerta (:func:`ensure_ready`, con el diálogo si se lanzó desde la interfaz) y, si
        se puede, la operación «en curso» (``begin_operation`` con ``settings``, lo de
        :meth:`provenance_inputs`, los parámetros ``params`` y ``executor``: ``blender``, o
        ``job_thread``/``job_process`` para un trabajo, que al incorporarla dice dónde corrió
        de verdad). ``None`` si no se puede (ya dicho)."""
        inputs = tuple(self.provenance_inputs(context))
        ready = ensure_ready(self.provenance_op_type, inputs,
                             report=self.report,  # type: ignore[attr-defined]
                             dialog=self.provenance_dialog)
        if ready is None:
            return None
        from ...core.provenance.operations import begin_operation

        try:
            return begin_operation(SESSION.project, self.provenance_op_type,
                                   settings=dict(settings or {}), inputs=list(inputs),
                                   params=list(params), executor=executor,
                                   group_uid=group_uid, supersedes=supersedes)
        except GeoblenderError as exc:
            self.report({"ERROR"}, error_text(exc))  # type: ignore[attr-defined]
            return None

    def launch_job(self, handle: OperationHandle, worker: str, *, label: str,
                   params: Mapping[str, Any] | None = None,
                   paths: Mapping[str, Path] | None = None,
                   on_finish: Callable[[JobResult], object] | None = None,
                   **request: Any) -> JobHandle | None:
        """:func:`launch_job`; si no se puede lanzar (la operación queda fallida), lo dice y
        devuelve ``None``."""
        try:
            return launch_job(handle, worker, label=label, params=params, paths=paths,
                              on_finish=on_finish, **request)
        except RuntimeError:
            self.report({"ERROR"},  # type: ignore[attr-defined]
                        tr("Geoblender has not prepared the jobs folder yet"))
        except (GeoblenderError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))  # type: ignore[attr-defined]
        return None

    def check_write_target(self, path: str | os.PathLike[str]) -> bool:
        """:func:`check_write_target`: si no se puede escribir en ``path``, lo dice (nombrando
        la carpeta o la entrada) y devuelve falso."""
        try:
            check_write_target(path)
        except GeoblenderError as exc:
            self.report({"ERROR"}, error_text(exc))  # type: ignore[attr-defined]
            return False
        return True


# Registro ---------------------------------------------------------------------------------


def register() -> None:
    """Instala los textos de la procedencia, de los parámetros y del trabajo de hash en
    ``core.i18n``, registra las declaraciones de ``core`` (con el tipo de trabajo
    ``core_content_hash``), da a la sesión sus trabajos de hash (:data:`HASH_JOBS`), la apunta
    a los cambios de proyecto, escucha las carpetas de trabajos borradas
    (:func:`on_jobs_removed`), pone la nota de la lista de trabajos (:func:`job_note`) y el
    temporizador del aviso de las carpetas de solo lectura (persistente, para que no lo quite
    abrir otro ``.blend`` antes de que se dispare); idempotente."""
    i18n.install(messages.CATALOG_ES)
    i18n.install(params.CATALOG_ES)
    i18n.install(content_hash.CATALOG_ES)
    try:
        _register_declarations()
    except BaseException:
        _unregister_declarations()
        raise
    SESSION.hash_jobs = HASH_JOBS
    project_session.add_listener(on_project_changed)
    SESSION.on_project_changed(project_session.current())
    jobs_ops.add_removal_listener(on_jobs_removed)
    job_list.set_note_provider(job_note)
    forget_read_only_warning()
    if not bpy.app.timers.is_registered(warn_read_only_dirs):
        bpy.app.timers.register(warn_read_only_dirs, first_interval=0.0, persistent=True)


def unregister() -> None:
    """Deja de escuchar los cambios de proyecto y las carpetas de trabajos borradas, quita la
    nota de la lista de trabajos y olvida lo pendiente de incorporar (sus operaciones siguen
    «en curso»: el lanzador ya interrumpió sus trabajos), para la comprobación en marcha (quita
    su temporizador y cancela lo pendiente) y olvida el proyecto, quita el temporizador del aviso
    (si aún no se disparó) y olvida que se avisó (la sesión siguiente avisa otra vez), quita
    los trabajos de hash de la sesión y las declaraciones de ``core`` que registró; las
    traducciones instaladas se quedan; idempotente."""
    project_session.remove_listener(on_project_changed)
    jobs_ops.remove_removal_listener(on_jobs_removed)
    if job_list.note_provider() is job_note:
        job_list.set_note_provider(None)
    _STATE.jobs.clear()
    SESSION.reset()
    SESSION.hash_jobs = None
    if bpy.app.timers.is_registered(warn_read_only_dirs):
        bpy.app.timers.unregister(warn_read_only_dirs)
    forget_read_only_warning()
    _unregister_declarations()
