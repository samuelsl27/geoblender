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

Lo demás llega con las tareas siguientes de la fase 7: el trabajo de hash (T47) y las ayudas
para los módulos (T48); los operadores de §5.3.2, con los paneles (fase 8).

``core.i18n`` no tiene cómo quitar traducciones: :func:`unregister` las deja (como los
trabajos de la 004), y volver a registrar las instala otra vez sin cambiar nada.

En ``blender -b`` los temporizadores no se ejecutan: las pruebas llaman a :func:`check_tick`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from typing import TYPE_CHECKING, Any

import bpy

from ...core import i18n, params
from ...core.content import readers as content_readers
from ...core.content.builtin import CONTENT_READERS, GPKG_LAYER
from ...core.i18n import tr
from ...core.inputs.guard import read_only_warnings
from ...core.params import core_defs
from ...core.paths import ReadOnlyDirs
from ...core.project.migrations import m0002
from ...core.provenance import contract, messages
from .. import ADDON_PACKAGE
from ..props.core import read_only_dirs_of
from ..scene import project_session
from ..ui import statusbar

if TYPE_CHECKING:
    from ...core.project.model import Progress
    from ...core.project.session import Project
    from ...core.provenance.checks import OpenCheckOutcome
    from ...core.provenance.contract import ReimportRequest
    from ...core.provenance.gate import CheckState

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
        """Los trabajos de hash de las fuentes externas grandes (``checks.HashJobs``; los pone
        T47); ``None``: todo en el hilo, por trozos."""
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


# Registro ---------------------------------------------------------------------------------


def register() -> None:
    """Instala los textos de la procedencia y de los parámetros en ``core.i18n``, registra las
    declaraciones de ``core``, apunta la sesión a los cambios de proyecto y pone el
    temporizador del aviso de las carpetas de solo lectura (persistente, para que no lo quite
    abrir otro ``.blend`` antes de que se dispare); idempotente."""
    i18n.install(messages.CATALOG_ES)
    i18n.install(params.CATALOG_ES)
    try:
        _register_declarations()
    except BaseException:
        _unregister_declarations()
        raise
    project_session.add_listener(on_project_changed)
    SESSION.on_project_changed(project_session.current())
    forget_read_only_warning()
    if not bpy.app.timers.is_registered(warn_read_only_dirs):
        bpy.app.timers.register(warn_read_only_dirs, first_interval=0.0, persistent=True)


def unregister() -> None:
    """Deja de escuchar los cambios de proyecto, para la comprobación en marcha (quita su
    temporizador y cancela lo pendiente) y olvida el proyecto, quita el temporizador del aviso
    (si aún no se disparó) y olvida que se avisó (la sesión siguiente avisa otra vez) y quita
    las declaraciones de ``core`` que registró; las traducciones instaladas se quedan;
    idempotente."""
    project_session.remove_listener(on_project_changed)
    SESSION.reset()
    if bpy.app.timers.is_registered(warn_read_only_dirs):
        bpy.app.timers.unregister(warn_read_only_dirs)
    forget_read_only_warning()
    _unregister_declarations()
