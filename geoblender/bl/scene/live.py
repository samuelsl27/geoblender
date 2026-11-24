# SPDX-License-Identifier: GPL-3.0-or-later
"""La marca en vivo de la vista (spec 010, T08; RF-010-02; RNF-010-03; plan 010 §5.3.2, A3,
D-12; generaliza la de los sondeos, spec 005, T47).

Mientras hay un proyecto abierto, la vista dice lo que dice hoy el proyecto de cada dato
cargado, sin volver a cargar nada, sin recalcular y sin escribir en el proyecto: su estado y su
marca de obsoleto, «no al día» lo que muestra un contenido anterior (o se cargó con otro
GeoOrigin) y «sin respaldo en el proyecto» lo descartado o lo que el proyecto no tiene, en
``Object.geoblender`` y en el nombre generado de sus objetos y de su colección
(``bl.scene.views.show_view_state``); y Refrescar (control 7) se dibuja resaltado mientras haya
algo que no está al día (:func:`refresh_state`).

**Quién la pide** (:func:`request`, que solo la apunta y pone el temporizador): los indicadores
de la procedencia tras cada lectura del proyecto cambiado (``bl.ui.provenance``, que la apunta
con ``add_change_listener``: así la marca no alarga su tic); deshacer y rehacer, que devuelven
los objetos a otra carga (``undo_post``, ``redo_post``); abrir un ``.blend`` (``load_post``); y
cargar o descargar datos de la vista (``bl.scene.views``), que cambia lo que no está al día.
Cada petición cambia :func:`view_generation`, con la que el inventario de N ▸ Proyecto sabe que
lo suyo puede ser viejo (spec 010, T15).

**El temporizador** (:func:`mark_tick`, persistente, cada :data:`MARK_TICK_S` s mientras queda
algo): con una petición, agrupa los objetos de la escena por dato (``views.loaded_items``, los de
todos los proyectos: los de otro, sin respaldo en este), lee en una instantánea lo que dice de
ellos el proyecto de la sesión (``core.views.state.view_states``) y lo que lee cada cargador que
declara su marca en vivo (``views.live_reads``), y guarda cuántos no están al día
(``core.views.state.pending``: :func:`pending_count`); después aplica por tandas, hasta
:data:`MARK_BUDGET_S` s por llamada contando la lectura (D-12: 200 datos que cambian a la vez no
caben en una), y lo que queda, en el siguiente tic, con los objetos agrupados otra vez (no
guarda objetos de Blender entre tics: deshacer o abrir otro fichero los invalida). Una petición
nueva a mitad vuelve a leer. Si cambió algo, redibuja la barra superior (``bl.ui.bars``), los
esquemas y las vistas 3D. Mientras esta sesión escribe en el proyecto (``Project.writing``) o
el proyecto está en WAL (QGIS: leerlo haría una copia privada), espera :data:`MARK_RETRY_S` s;
si no se puede leer (otro programa lo bloquea), deja la petición: el siguiente cambio la vuelve
a pedir.

**Lo de cada cargador** (spec 010, T09; plan §5.6, D-13): lo que declara con
``views.extend_loader``. Su ``LiveHook`` (los sondeos: sus sondeos de traza obsoleta) se lee en
la misma instantánea, solo el de los cargadores de lo que muestra el contenido de hoy, y se
aplica con lo general.

**Al abrir** (spec 010, T10; RF-010-03; plan A4, D-2, D-13): abrir el proyecto no lee nada
(RNF-002-02: lo pide el primer tic de sus indicadores). La primera lectura tras abrir el
proyecto, o tras abrir un ``.blend`` con el proyecto abierto (``load_post``), dice cuántos datos
de la vista no están al día («3 datos de la vista no están al día: Refrescar (F5)»,
:func:`opening_text`; ninguno si todo lo está) en el registro de Blender
(``bl.ops.jobs.report_later``: Blender no pasa a Info lo que dice un temporizador) y en los
avisos del proyecto (``project_session.notify``), y rehace lo que el ``SessionParts`` de cada
cargador dice que les falta a sus objetos que muestran el contenido de hoy (la superposición de
los sondeos, por la cola de los sondeos, con su avance, sin volver a cargarlos; lo que no está
al día se queda marcado para Refrescar: spec 010, T20), una vez por apertura.

Al cambiar el proyecto de la sesión (``project_session.add_listener``), olvida lo leído y
retira el temporizador. Los manejadores son ``@persistent`` (sin ello se pierden al abrir otro
``.blend``) y :func:`unregister` los quita con el temporizador (``docs/trampas.md`` §3).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import TYPE_CHECKING, Any

import bpy
from bpy.app.handlers import persistent

from ...core.errors import GeoblenderError
from ...core.gpkg.header import read_header
from ...core.i18n import language, tr
from ...core.views import state
from . import project_session, views
from . import versions as scene_versions

if TYPE_CHECKING:
    from ...core.project.session import Project
    from ..ui.commands import CommandState

LOGGER = logging.getLogger("geoblender.bl.scene")

MARK_BUDGET_S = 0.015
"""Lo que puede tardar como mucho cada llamada de la marca, lectura incluida (D-12; RNF-010-03:
≤ 20 ms en el hilo de Blender); lo que queda sigue en el siguiente tic (al menos un dato por
llamada)."""
MARK_TICK_S = 0.05
"""El intervalo entre dos tandas de la marca."""
MARK_RETRY_S = 0.5
"""La espera mientras el proyecto no se puede leer sin coste (esta sesión escribe, o en WAL):
la de los indicadores de la procedencia."""
REFRESH = "geoblender.core_refresh"
"""La orden que se resalta mientras algo no está al día (Refrescar, control 7)."""
OPENING_REPORT = "WARNING"
"""Cómo va al registro de Blender el aviso de lo que no está al día al abrir (RF-010-03)."""
MAX_NOTES = 64  # estados de Refrescar guardados (por número e idioma); después, de nuevo


class _State:
    """Lo de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.requested = False  # hay una petición sin leer
        self.opened = False  # se abrió un .blend: la próxima lectura es la primera
        self.project: Project | None = None  # el proyecto de la última lectura
        self.states: dict[str, state.ItemView] = {}  # lo leído, por uid de dato
        self.live: dict[str, Any] = {}  # lo que leyeron los cargadores, por su comienzo
        self.titles: dict[str, str] = {}  # el título de los datos que lo tienen (spec 009)
        self.codes: dict[str, str] = {}  # la versión de los datos de una versión (spec 009)
        self.remaining: list[str] = []  # los datos que quedan por aplicar, en orden
        self.pending = 0  # cuántos no están al día (control 7)
        self.notes: dict[tuple[int, str], CommandState] = {}
        self.generation = 0  # cuántas peticiones (solo crece: no se olvida)


_STATE = _State()


def request(project: Project | None) -> None:
    """Pide la marca en vivo del proyecto de la sesión (con ``None``, sin proyecto, nada): la
    apunta, cambia :func:`view_generation` y pone el temporizador (:func:`mark_tick`,
    persistente, al siguiente ciclo), sin leer nada. Es lo que se apunta en los indicadores de
    la procedencia (``bl.ui.provenance.add_change_listener``: se llama con el proyecto tras cada
    lectura)."""
    if project is None:
        return
    _STATE.requested = True
    _STATE.generation += 1
    if not bpy.app.timers.is_registered(mark_tick):
        bpy.app.timers.register(mark_tick, first_interval=0.0, persistent=True)


def view_generation() -> int:
    """Un número que cambia con cada petición de la marca (:func:`request`): tras cada lectura
    del proyecto cambiado, al cargar o descargar datos de la vista, al deshacer o rehacer y al
    abrir un ``.blend``. Así sabe el inventario (spec 010, T15; ``bl.ui.view_panels``), sin leer
    nada, que lo que enseña puede ser viejo (otro proyecto, otra escena)."""
    return _STATE.generation


def pending_count() -> int:
    """Cuántos datos de la vista no están al día según la última lectura (los que Refrescar
    vuelve a cargar: ``core.views.state.pending``); 0 sin proyecto."""
    return _STATE.pending


def pending_text(count: int) -> str:
    """«1 dato de la vista no está al día» o «3 datos de la vista no están al día», en el
    idioma de Geoblender."""
    if count == 1:
        return tr("1 data item in the view is not up to date")
    return tr("{n} data items in the view are not up to date", n=count)


def opening_text(count: int) -> str:
    """El aviso de la primera lectura tras abrir (RF-010-03): «1 dato de la vista no está al
    día: Refrescar (F5)» o «3 datos de la vista no están al día: Refrescar (F5)», en el idioma
    de Geoblender."""
    if count == 1:
        return tr("1 data item in the view is not up to date: Refresh (F5)")
    return tr("{n} data items in the view are not up to date: Refresh (F5)", n=count)


def refresh_state(_context: Any, idname: str) -> CommandState | None:
    """El estado de Refrescar (:data:`REFRESH`) para el proveedor de estado de las órdenes
    (``bl.ui.provenance.command_state``; RF-010-02): resaltado, con cuántos datos no están al
    día en su descripción, mientras haya alguno; si no, u otra orden, ``None``. Solo busca lo
    ya leído (se pide en cada dibujo)."""
    count = _STATE.pending
    if idname != REFRESH or count <= 0:
        return None
    key = (count, language())
    found = _STATE.notes.get(key)
    if found is None:
        from ..ui.commands import CommandState  # al usarlo: bl.ui importa bl.scene

        if len(_STATE.notes) >= MAX_NOTES:
            _STATE.notes.clear()
        found = CommandState(highlight=True, note=pending_text(count))
        _STATE.notes[key] = found
    return found


# El temporizador ------------------------------------------------------------------------------


def mark_tick() -> float | None:
    """La función del temporizador de la marca (véase el módulo): lee si hay una petición,
    aplica una tanda y devuelve :data:`MARK_TICK_S` mientras queda algo (o
    :data:`MARK_RETRY_S` si el proyecto no se puede leer ahora); si no, se retira y devuelve
    ``None``. Un fallo va al registro técnico: Blender sigue."""
    try:
        interval = _mark()
    except Exception:  # noqa: BLE001 - un temporizador que falla no tumba Blender
        LOGGER.exception("Falló la marca en vivo de la vista")
        _STATE.requested = False
        _STATE.remaining = []
        interval = None
    if interval is None:
        _retire()
    return interval


def _mark() -> float | None:
    started = time.perf_counter()
    project = project_session.current()
    if project is None:
        if _forget():
            _redraw()
        return None
    counted = dressed = False
    if _STATE.requested or _STATE.project is not project:
        if getattr(project, "writing", False) or _in_wal(project):
            _STATE.requested = True
            return MARK_RETRY_S
        _STATE.requested = False
        try:
            groups, states, live, shown = read_view(project)
        except (GeoblenderError, sqlite3.Error, OSError):
            LOGGER.info("No se pudo leer el proyecto para la marca en vivo de la vista; se "
                        "pide otra vez con el próximo cambio", exc_info=True)
            _STATE.remaining = []
            return None
        # La primera lectura tras abrir el proyecto o un .blend con él abierto (RF-010-03).
        first = _STATE.project is not project or _STATE.opened
        _STATE.opened = False
        _STATE.project = project
        _STATE.states = states
        _STATE.live = live
        _STATE.titles = dict(shown.titles)
        _STATE.codes = dict(shown.codes)
        _STATE.remaining = list(states)
        count = state.pending(states)
        counted = count != _STATE.pending
        _STATE.pending = count
        # Las colecciones de las versiones, en la misma tanda (spec 009, RF-009-30).
        dressed = scene_versions.show_versions(shown.versions, shown.revisions) > 0
        if first:
            _announce(count)
            _rebuild(project, groups, states)
    else:
        groups = views.loaded_items()
    budget = max(0.0, MARK_BUDGET_S - (time.perf_counter() - started))
    wanted = {uid: groups[uid] for uid in _STATE.remaining if uid in groups}
    changed, rest = views.show_view_state(wanted, _STATE.states, budget_s=budget,
                                          live=_STATE.live, titles=_STATE.titles,
                                          versions=_STATE.codes)
    _STATE.remaining = rest
    if changed or counted or dressed:
        _redraw()
    return MARK_TICK_S if rest or _STATE.requested else None


def _in_wal(project: Project) -> bool:
    """Si el proyecto está en WAL (lo deja así QGIS; leerlo haría una copia privada). Si no se
    puede leer su cabecera, lo dirá la lectura."""
    try:
        return read_header(project.database_path).needs_recovery
    except GeoblenderError:
        return False


def read_view(project: Project) -> tuple[dict[str, tuple[bpy.types.Object, ...]],
                                         dict[str, state.ItemView], dict[str, Any],
                                         scene_versions.VersionsRead]:
    """Los objetos de la escena por dato (``views.loaded_items``, los de todos los proyectos)
    y, en una instantánea del proyecto, lo que dice de cada dato (``view_states``), lo que
    leen los cargadores con marca en vivo de lo que la muestra hoy (``live_reads``: solo los
    de esos cargadores) y lo de las versiones (spec 009, T22; RF-009-30, RF-009-22): las
    versiones con la revisión que se enseña con cada una y el título de los datos cargados
    (``bl.scene.versions.read_for_view``). Sin datos cargados, no abre el proyecto. No escribe.
    Lo usan la marca, Refrescar (``bl.scene.refresh``, spec 010, T11) y el renombrado
    (:func:`show_now`)."""
    groups = views.loaded_items()
    if not groups:
        return groups, {}, {}, scene_versions.VersionsRead()
    items = [views.loaded_item(uid, objects) for uid, objects in groups.items()]
    view_stale = any(scene.geoblender.view_stale for scene in bpy.data.scenes)
    with project.read() as conn:
        conn.execute("BEGIN")  # todo en la misma instantánea
        try:
            states = state.view_states(project, items, project_uid=project.uid,
                                       origin=project.origin, view_stale=view_stale, conn=conn)
            live = views.live_reads(conn, _hooked(states))
            shown = scene_versions.read_for_view(conn, groups, project)
        finally:
            conn.execute("ROLLBACK")
    return groups, states, live, shown


def show_now(project: Project) -> bool:
    """Pone al día ahora, de una vez y sin presupuesto, lo que hace la marca: lee el proyecto
    (:func:`read_view`) y aplica lo que dice de cada dato cargado (con su título) y de cada
    versión a sus objetos y sus colecciones, sin volver a cargar nada ni escribir en el
    proyecto. Lo usa el renombrado desde el Outliner (``bl.scene.versions``; spec 009,
    RF-009-22): el nombre se vuelve a generar con el título nuevo sin esperar al tic. Devuelve
    si cambió algo (y entonces redibuja)."""
    groups, states, live, shown = read_view(project)
    changed = views.show_view_state(groups, states, live=live, titles=shown.titles,
                                    versions=shown.codes)[0]
    changed = scene_versions.show_versions(shown.versions, shown.revisions) > 0 or changed
    if changed:
        _redraw()
    return changed


_SHOWS_TODAY = frozenset({state.ItemState.CURRENT, state.ItemState.RESTATE})
"""Lo que muestra el contenido de hoy: lo único en que se aplica el ``LiveHook`` de un cargador
y se rehace lo que no guarda el ``.blend`` (``SessionParts``); lo demás lo pone al día volver a
cargarlo (Refrescar)."""


def _loader_of(view: state.ItemView) -> views.Loader | None:
    """El cargador del dato de ``view`` (``None`` sin registro en el proyecto o sin cargador)."""
    return None if view.record is None else views.loader_for(view.record.name)


def _hooked(states: dict[str, state.ItemView]) -> set[str]:
    """Los cargadores con marca en vivo (``LiveHook``) de lo que muestra el contenido de hoy
    (``CURRENT``, ``RESTATE``: lo único en que se aplica), por su comienzo."""
    found: set[str] = set()
    for view in states.values():
        if view.state in _SHOWS_TODAY:
            loader = _loader_of(view)
            if loader is not None and loader.live is not None:
                found.add(loader.prefix)
    return found


def _announce(count: int) -> None:
    """La primera lectura tras abrir (RF-010-03; plan A4): si ``count`` datos de la vista no
    están al día (alguno), lo dice (:func:`opening_text`) en el registro de Blender y en los
    avisos del proyecto; si todo lo está, nada."""
    if count <= 0:
        return
    from ..ops import jobs as jobs_ops  # al usarlo: bl.ops importa bl.scene

    text = opening_text(count)
    project_session.notify(text)
    jobs_ops.report_later(OPENING_REPORT, text)


def _rebuild(project: Project, groups: dict[str, tuple[bpy.types.Object, ...]],
             states: dict[str, state.ItemView]) -> None:
    """La primera lectura tras abrir el proyecto o un ``.blend`` con él abierto (RF-010-03;
    plan A4, D-13): por cada cargador que declara lo que no se guarda en el ``.blend``
    (``SessionParts``), con sus objetos de datos que muestran el contenido de hoy (``CURRENT``,
    ``RESTATE``), si les falta (``missing``), lo rehace (``rebuild``: en segundo plano, con su
    avance y sin volver a cargarlos; la superposición de los sondeos). Lo que no está al día se
    queda marcado, sin volver a cargarlo ni rehacer nada: es lo de Refrescar (spec 010, T20).
    Uno que falla va al registro técnico: la marca sigue."""
    wanted: dict[str, tuple[views.SessionParts, list[bpy.types.Object]]] = {}
    for uid, view in states.items():
        loader = _loader_of(view)
        if loader is None or loader.session_parts is None or view.state not in _SHOWS_TODAY:
            continue
        wanted.setdefault(loader.prefix, (loader.session_parts, []))[1].extend(groups.get(uid, ()))
    for prefix, (parts, objects) in wanted.items():
        try:
            if objects and parts.missing(project, objects):
                parts.rebuild(project)
        except Exception:  # noqa: BLE001 - lo de la sesión no tumba la marca
            LOGGER.exception("No se pudo rehacer lo de la sesión de la vista «%s…»", prefix)


def _forget() -> bool:
    """Olvida lo leído y la petición; dice si había algo que no estaba al día (el control 7
    cambia)."""
    had = _STATE.pending > 0
    _STATE.requested = False
    _STATE.opened = False
    _STATE.project = None
    _STATE.states = {}
    _STATE.live = {}
    _STATE.titles = {}
    _STATE.codes = {}
    _STATE.remaining = []
    _STATE.pending = 0
    return had


def _retire() -> None:
    if bpy.app.timers.is_registered(mark_tick):
        bpy.app.timers.unregister(mark_tick)


def _redraw() -> None:
    """Redibuja la barra superior (el control 7: Refrescar resaltado), con
    ``bl.ui.bars.redraw`` (spec 009, T41: es un área global de la ventana, fuera de
    ``screen.areas``, y ``Area.tag_redraw`` no llega a ella), y los esquemas y las vistas 3D."""
    from ..ui import bars  # al usarlo: bl.ui importa bl.scene

    bars.redraw()
    manager = getattr(bpy.context, "window_manager", None)
    for window in list(getattr(manager, "windows", ()) or ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) or ():
            if area.type in ("OUTLINER", "VIEW_3D"):
                area.tag_redraw()


# La sesión y los manejadores ------------------------------------------------------------------


def on_project_changed(_project: Project | None) -> None:
    """Lo que se apunta en ``project_session``: olvida lo leído del proyecto anterior y retira
    el temporizador (con uno nuevo, lo pide el primer tic de sus indicadores: al abrir no se
    lee nada, RNF-002-02)."""
    _retire()
    if _forget():
        _redraw()


def _request_safely() -> None:
    try:
        request(project_session.current())
    except Exception:  # noqa: BLE001 - un manejador que falla no tumba Blender
        LOGGER.exception("No se pudo pedir la marca en vivo de la vista")


@persistent
def on_undo_post(*_args: Any) -> None:
    """Tras deshacer (Ctrl+Z): los objetos pueden mostrar otra carga; pide la marca."""
    _request_safely()


@persistent
def on_redo_post(*_args: Any) -> None:
    """Tras rehacer (Ctrl+Mayús+Z): pide la marca."""
    _request_safely()


@persistent
def on_load_post(*_args: Any) -> None:
    """Tras abrir un ``.blend``: si sigue abierto su proyecto (``bl.scene.georef`` cierra el
    de otro), pide la marca de lo que trae, que será la primera tras abrirlo (el aviso de lo
    que no está al día y lo que no guarda el ``.blend``: RF-010-03)."""
    _STATE.opened = True
    _request_safely()


# (lista de bpy.app.handlers, función), en el orden en que se registran.
HANDLERS: tuple[tuple[str, Any], ...] = (
    ("load_post", on_load_post),
    ("undo_post", on_undo_post),
    ("redo_post", on_redo_post),
)


def register() -> None:
    """Añade los manejadores (sin repetirlos) y la escucha del proyecto de la sesión;
    idempotente."""
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if function not in handlers:
            handlers.append(function)
    project_session.add_listener(on_project_changed)


def unregister() -> None:
    """Quita la escucha, los manejadores (todas sus apariciones) y el temporizador, y olvida lo
    leído; idempotente."""
    project_session.remove_listener(on_project_changed)
    for name, function in reversed(HANDLERS):
        handlers = getattr(bpy.app.handlers, name)
        while function in handlers:
            handlers.remove(function)
    _retire()
    _forget()
    _STATE.notes.clear()
