# SPDX-License-Identifier: GPL-3.0-or-later
"""La versión activa de la sesión (spec 009, T18; HU-009-1; RF-009-10; plan 009 §5.3.4, A11, D-8,
D-25 y D-42).

La versión activa es **de la sesión** (D-8), nunca del proyecto: la usan las operaciones de
versión (las abre en su revisión) y la muestran el control 8 («● V10.r2» con el icono de su estado),
su ventana, el menú Proyecto ▸ Versiones ▸ Versión activa y la barra de estado («V10.r2 VIGENTE»).
Se guarda en dos sitios fuera del proyecto: en **la vista**, ``Scene.geoblender.active_version_uid``
de todas las escenas del proyecto (``bl.props.core``), y en **este equipo**,
``projects/<uid>/session.json`` de los datos de usuario (``core.userdata``). Cambiarla no escribe
nada en el proyecto: se puede también en solo lectura, para consultar, y con una versión SUPERADO
o DESCARTADO, que se consulta y no se edita (D-42; lo de editar dirá «Versión no editable», T20).

- :func:`choose_on_open` (D-25): al abrir el proyecto (la escucha de ``project_session``,
  :func:`on_project_changed`) y al cargar una vista (:func:`on_load_post`), la de la vista (la de
  una escena de este proyecto, si la versión existe; primero la de la ventana), si no, la de este
  equipo, si no, la VIGENTE y, si no hay, ninguna («Sin versión»). Elegirla al abrir no cambia lo
  que recuerda el equipo: eso lo hace quien la cambia.
- :func:`set_active`: la cambia (``geoblender.core_set_active_version``): la sesión, las escenas
  del proyecto y los datos de usuario.
- :func:`refresh`: vuelve a leer las versiones (``bl.ui.version_panels`` la llama tras cada
  lectura de los indicadores de la procedencia, cuando el proyecto ha cambiado).
- Lo leído queda en la sesión (:func:`versions`, :func:`revisions`, :func:`active`) y en las filas
  de ``WindowManager.geoblender_version_panels`` (``bl.props.versions``), que dibujan la ventana
  del control 8 y el menú: **nada se lee del proyecto al dibujar**. :func:`control_text` y
  :func:`status_text` son los textos del control y de la barra de estado.
- Cada cambio de lo que se ve avisa a lo apuntado con :func:`add_listener` (la interfaz, que
  redibuja la barra superior y la de estado).
- Manejadores ``@persistent``: ``load_post`` (:func:`on_load_post`: elige otra vez con la vista
  cargada) y ``save_pre`` (:func:`on_save_pre`: las escenas del proyecto llevan la versión activa
  de la sesión, también una escena nueva o una que Ctrl+Z devolvió a antes del cambio).

Una versión no se borra nunca (RF-009-12): lo que una escena o el equipo recuerdan solo deja de
valer si es de otro proyecto. En un proyecto del esquema 2 abierto en solo lectura no hay
versiones: «Sin versión».
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy
from bpy.app.handlers import persistent

from ...core.errors import GeoblenderError
from ...core.i18n import language, tr, translate
from ...core.versions import read as versions_read
from ...core.versions.model import RevisionState, Version, VersionError, VersionStatus
from ..props.versions import WINDOW_MANAGER_PROPERTY
from . import project_session

if TYPE_CHECKING:
    from ...core.project.session import Project
    from ...core.versions.model import Revision

LOGGER = logging.getLogger("geoblender.bl.scene")
SCENE_PROPERTY = "active_version_uid"
"""La propiedad de ``Scene.geoblender`` con la versión activa de la vista (su uid)."""
STATE_ICONS: dict[VersionStatus, str] = {
    VersionStatus.BORRADOR: "gb_state_draft",
    VersionStatus.VIGENTE: "gb_state_current",
    VersionStatus.SUPERADO: "gb_state_superseded",
    VersionStatus.DESCARTADO: "gb_state_discarded",
}
"""El icono propio de cada estado (el punto del control 8: VIGENTE verde, BORRADOR ámbar,
SUPERADO gris, DESCARTADO marrón; AR §2)."""

type Listener = Callable[[], object]
"""Lo que se avisa cuando cambia lo que se ve de las versiones (la activa o lo leído)."""


def version_name(code: str, title: str, status: str, number: str) -> str:
    """El nombre de una versión con su estado y su revisión, en el idioma de Geoblender: «V10 ·
    Definitiva [VIGENTE] r2» (plan A11; ``number``, «r2»: la abierta o la última)."""
    state = translate(language(), VersionStatus(status).msgid)
    head = f"{code} · {title}" if title else code
    return " ".join(part for part in (head, f"[{state}]", number) if part)


def revision_text(label: str, state: str, altered: bool) -> str:
    """Una revisión en la ventana de la versión activa, en el idioma de Geoblender: «en curso
    (V10.r3)», «congelada: V10.r2» o «cerrada (V09.r3)», con «(alterada)» si lo está."""
    shown = tr("{revision} (altered)", revision=label) if altered else label
    if state == RevisionState.OPEN:
        return tr("in progress ({revision})", revision=shown)
    if state == RevisionState.FROZEN:
        return tr("frozen: {revision}", revision=shown)
    return tr("closed ({revision})", revision=shown)


@dataclass(frozen=True)
class ShownVersion:
    """Una versión como se enseña: su uid, su código, su título, su estado, la revisión que se
    enseña con ella («V10.r2»: la abierta o, si ya no tiene, la última; «V10» sin revisiones), el
    estado de esa revisión y si está alterada."""

    uid: str
    code: str
    title: str
    status: VersionStatus
    revision: str
    revision_state: RevisionState | None = None
    altered: bool = False

    @property
    def number(self) -> str:
        """«r2» de la revisión que se enseña ("" sin revisiones)."""
        return self.revision.partition(".")[2]

    def name(self) -> str:
        """«V10 · Definitiva [VIGENTE] r2» (:func:`version_name`)."""
        return version_name(self.code, self.title, self.status, self.number)

    def status_text(self) -> str:
        """«V10.r2 VIGENTE», el de la barra de estado, en el idioma de Geoblender."""
        return f"{self.revision} {translate(language(), self.status.msgid)}"


@dataclass(frozen=True)
class ShownRevision:
    """Una revisión de la versión activa como se enseña: su uid, «V10.r2», su estado y si está
    alterada."""

    uid: str
    label: str
    state: RevisionState
    altered: bool = False

    def text(self) -> str:
        """«en curso (V10.r3)»… (:func:`revision_text`)."""
        return revision_text(self.label, self.state, self.altered)


@dataclass
class _State:
    """La versión activa de la sesión y lo leído de las versiones (no se guarda)."""

    project_uid: str = ""
    active_uid: str | None = None
    versions: tuple[ShownVersion, ...] = ()
    revisions: tuple[ShownRevision, ...] = ()
    listeners: list[Listener] = field(default_factory=list)

    def forget(self) -> None:
        self.project_uid = ""
        self.active_uid = None
        self.versions = ()
        self.revisions = ()


_STATE = _State()


# Lo que se ve --------------------------------------------------------------------------------


def _session_project() -> Project | None:
    """El proyecto de la sesión, si lo leído es suyo."""
    project = project_session.current()
    if project is None or project.uid != _STATE.project_uid:
        return None
    return project


def active_version(context: Any = None) -> str | None:
    """La versión activa de la sesión (su uid), o ``None`` sin versión o sin proyecto."""
    return _STATE.active_uid if _session_project() is not None else None


def active() -> ShownVersion | None:
    """La versión activa como se enseña, o ``None``."""
    uid = active_version()
    return None if uid is None else next(
        (item for item in _STATE.versions if item.uid == uid), None)


def versions() -> tuple[ShownVersion, ...]:
    """Las versiones del proyecto de la sesión, por número de código (lo último leído)."""
    return _STATE.versions if _session_project() is not None else ()


def revisions() -> tuple[ShownRevision, ...]:
    """Las revisiones de la versión activa, por número (lo último leído)."""
    return _STATE.revisions if active_version() is not None else ()


def control_text() -> str | None:
    """El texto del control 8: la revisión de la versión activa («V10.r2») o «Sin versión»;
    ``None`` sin proyecto (el control lleva entonces su título)."""
    if _session_project() is None:
        return None
    shown = active()
    return tr("No version") if shown is None else shown.revision


def status_text() -> str:
    """La versión de la barra de estado: «V10.r2 VIGENTE» o «Sin versión»; "" sin proyecto."""
    if _session_project() is None:
        return ""
    shown = active()
    return tr("No version") if shown is None else shown.status_text()


# Leer el proyecto -----------------------------------------------------------------------------


def _shown(version: Version, revision: Revision | None) -> ShownVersion:
    if revision is None:
        return ShownVersion(version.uid, version.code, version.title, version.status,
                            version.code)
    return ShownVersion(version.uid, version.code, version.title, version.status,
                        revision.label(version.code), revision.state, revision.altered)


def read_versions(project: Project, active_uid: str | None = None
                  ) -> tuple[tuple[ShownVersion, ...], tuple[ShownRevision, ...]]:
    """Las versiones de ``project`` como se enseñan y las revisiones de ``active_uid`` (si es
    una de ellas), en una lectura que no escribe nada; sin versiones (un esquema 2), nada."""
    with project.read() as conn:
        if not versions_read.has_versions(conn):
            return (), ()
        found = versions_read.versions(conn)
        latest = versions_read.latest_revisions(conn)
        codes = {version.uid: version.code for version in found}
        own = (versions_read.revisions(conn, active_uid)
               if active_uid is not None and active_uid in codes else ())
    shown = tuple(_shown(version, latest.get(version.uid)) for version in found)
    code = codes.get(active_uid or "", "")
    return shown, tuple(ShownRevision(item.uid, item.label(code), item.state, item.altered)
                        for item in own)


def _scenes_of(project_uid: str) -> list[bpy.types.Scene]:
    """Las escenas del proyecto ``project_uid``, la de la ventana la primera."""
    current = getattr(bpy.context, "scene", None)
    found = [scene for scene in bpy.data.scenes
             if scene.geoblender.project_uid == project_uid]
    if current is not None and current in found:
        found.remove(current)
        found.insert(0, current)
    return found


def choose_on_open(project: Project) -> str | None:
    """La versión activa al abrir ``project`` o al cargar una vista suya (D-25): la de la vista
    (la de una escena de este proyecto, primero la de la ventana, si existe en él), la de este
    equipo (datos de usuario), la VIGENTE o ``None``. Solo lee."""
    with project.read() as conn:
        if not versions_read.has_versions(conn):
            return None
        known = {version.uid for version in versions_read.versions(conn)}
        current = versions_read.current_version(conn)
    for scene in _scenes_of(project.uid):
        value = getattr(scene.geoblender, SCENE_PROPERTY)
        if value in known:
            return value
    try:
        remembered = project_session.userdata().active_version(project.uid)
    except (GeoblenderError, OSError):
        remembered = None
    if remembered in known:
        return remembered
    return None if current is None else current.uid


def _write_scenes(project_uid: str, version_uid: str | None) -> None:
    """``version_uid`` ("" sin versión) en todas las escenas del proyecto (solo lo que cambia)."""
    value = version_uid or ""
    for scene in _scenes_of(project_uid):
        if getattr(scene.geoblender, SCENE_PROPERTY) != value:
            setattr(scene.geoblender, SCENE_PROPERTY, value)


def _fill_rows() -> None:
    """Las filas de ``WindowManager.geoblender_version_panels`` con lo leído."""
    manager = getattr(bpy.context, "window_manager", None)
    view = getattr(manager, WINDOW_MANAGER_PROPERTY, None)
    if view is None:
        return
    view.project = _STATE.project_uid
    view.versions.clear()
    for item in _STATE.versions:
        row = view.versions.add()
        row.uid, row.code, row.title = item.uid, item.code, item.title
        row.status, row.revision = str(item.status), item.revision
        row.revision_state = "" if item.revision_state is None else str(item.revision_state)
        row.altered = item.altered
    view.revisions.clear()
    for revision in _STATE.revisions:
        row = view.revisions.add()
        row.uid, row.label, row.state = revision.uid, revision.label, str(revision.state)
        row.altered = revision.altered
    shown = active()
    view.revisions_of = "" if shown is None else shown.code


def _apply(project: Project, version_uid: str | None,
           shown: tuple[ShownVersion, ...], own: tuple[ShownRevision, ...]) -> None:
    """Deja ``version_uid`` como la activa de la sesión, con lo leído, en las escenas del
    proyecto y en las filas, y avisa."""
    _STATE.project_uid = project.uid
    _STATE.active_uid = version_uid
    _STATE.versions = shown
    _STATE.revisions = own
    _write_scenes(project.uid, version_uid)
    _fill_rows()
    _notify()


def set_active(context: Any, project: Project, version_uid: str | None, *,
               remember: bool = True) -> tuple[str, ...]:
    """Hace activa en la sesión la versión ``version_uid`` de ``project`` (``None`` o "": ninguna,
    «Sin versión»), de cualquier estado (D-42): la escribe en todas las escenas del proyecto y,
    con ``remember``, en los datos de usuario (la de este equipo, D-25); nunca en el proyecto, que
    puede estar en solo lectura (RF-009-10). Avisa a lo apuntado. Devuelve los avisos (los datos
    de usuario que no se pudieron escribir). ``VersionError`` (``core.version_unknown``) si el
    proyecto no tiene esa versión: entonces no cambia nada."""
    uid = version_uid or None
    shown, own = read_versions(project, uid)
    if uid is not None and uid not in {item.uid for item in shown}:
        raise VersionError("core.version_unknown", field="versión activa", value=uid,
                           version=uid)
    _apply(project, uid, shown, own)
    if not remember:
        return ()
    try:
        project_session.userdata().set_active_version(project.uid, uid)
    except (GeoblenderError, OSError) as exc:
        LOGGER.warning("No se pudo recordar la versión activa en este equipo: %s", exc)
        return (tr("The active version could not be remembered on this computer: {detail}",
                   detail=str(exc)),)
    return ()


def refresh(project: Project | None = None) -> bool:
    """Vuelve a leer las versiones del proyecto de la sesión (``project``, si es ese) y las
    revisiones de la activa; si cambió lo que se ve, pone al día las filas y avisa. Dice si
    cambió. Un error al leer va al registro técnico y deja lo anterior."""
    current = _session_project()
    if current is None or (project is not None and project is not current):
        return False
    try:
        shown, own = read_versions(current, _STATE.active_uid)
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudieron leer las versiones del proyecto", exc_info=True)
        return False
    if (shown, own) == (_STATE.versions, _STATE.revisions):
        return False
    _STATE.versions, _STATE.revisions = shown, own
    _fill_rows()
    _notify()
    return True


# Avisos ----------------------------------------------------------------------------------------


def add_listener(listener: Listener) -> None:
    """Apunta ``listener`` (sin argumentos) para avisarle de cada cambio de lo que se ve de las
    versiones; si ya lo estaba, no hace nada."""
    if listener not in _STATE.listeners:
        _STATE.listeners.append(listener)


def remove_listener(listener: Listener) -> None:
    """Deja de avisar a ``listener``; si no estaba, no hace nada."""
    if listener in _STATE.listeners:
        _STATE.listeners.remove(listener)


def listeners() -> tuple[Listener, ...]:
    """Lo apuntado con :func:`add_listener`, por orden."""
    return tuple(_STATE.listeners)


def _notify() -> None:
    for listener in list(_STATE.listeners):
        try:
            listener()
        except Exception:  # noqa: BLE001 - la versión activa no depende de quien la enseña
            LOGGER.exception("Falló lo que se pone al día al cambiar la versión activa")


# Abrir el proyecto y la vista --------------------------------------------------------------------


def _choose(project: Project) -> None:
    """Elige la versión activa de ``project`` (:func:`choose_on_open`) y la deja en la sesión y
    en sus escenas, sin cambiar lo que recuerda el equipo; si no se puede leer, ninguna."""
    try:
        chosen = choose_on_open(project)
        shown, own = read_versions(project, chosen)
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo elegir la versión activa del proyecto", exc_info=True)
        chosen, shown, own = None, (), ()
    _apply(project, chosen, shown, own)


def on_project_changed(project: Project | None) -> None:
    """Lo que se apunta en ``project_session``: con un proyecto, elige su versión activa (D-25);
    sin él, la olvida (las escenas conservan la suya: es de la vista)."""
    if project is None:
        had = bool(_STATE.project_uid)
        _STATE.forget()
        _fill_rows()
        if had:
            _notify()
        return
    _choose(project)


@persistent
def on_load_post(*_args: object) -> None:
    """Tras cargar un ``.blend`` (después de ``bl.scene.georef``, que cierra el proyecto si la
    vista es de otro): con el proyecto aún abierto, elige otra vez su versión activa, la de la
    vista cargada si la trae (D-25)."""
    project = project_session.current()
    if project is None:
        on_project_changed(None)
        return
    _choose(project)


@persistent
def on_save_pre(*_args: object) -> None:
    """Antes de guardar (después de ``bl.scene.georef``, que pone el proyecto en las escenas
    nuevas): todas las escenas del proyecto llevan la versión activa de la sesión, para que la
    vista guardada la elija al cargarla (D-25)."""
    project = _session_project()
    if project is not None:
        _write_scenes(project.uid, _STATE.active_uid)


HANDLERS: tuple[tuple[str, Callable[..., None]], ...] = (
    ("load_post", on_load_post),
    ("save_pre", on_save_pre),
)


def register() -> None:
    """Apunta la escucha del proyecto de la sesión y los manejadores (sin leer nada)."""
    _STATE.forget()
    project_session.add_listener(on_project_changed)
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if function not in handlers:
            handlers.append(function)


def unregister() -> None:
    """Quita los manejadores y la escucha y olvida lo de la sesión y lo apuntado."""
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        while function in handlers:
            handlers.remove(function)
    project_session.remove_listener(on_project_changed)
    _STATE.forget()
    _STATE.listeners = []
