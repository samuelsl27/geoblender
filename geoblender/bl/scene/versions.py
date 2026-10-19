# SPDX-License-Identifier: GPL-3.0-or-later
"""La versión activa de la sesión (spec 009, T18; HU-009-1; RF-009-10; plan 009 §5.3.4, A11, D-8,
D-25 y D-42), las colecciones de las versiones y el renombrado desde el Outliner (T22;
RF-009-30, RF-009-22; D-35, D-36).

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
  :func:`status_text` son los textos del control y de la barra de estado;
  :func:`not_editable_text`, el de «Versión no editable» (T20) con una SUPERADO o DESCARTADO.
- Cada cambio de lo que se ve pide redibujar la barra superior y la de estado de cada ventana
  (:func:`request_redraw`, T35: un solo sitio, también si la orden se lanzó fuera de la barra
  superior) y avisa a lo apuntado con :func:`add_listener`.
- Manejadores ``@persistent``: ``load_post`` (:func:`on_load_post`: elige otra vez con la vista
  cargada) y ``save_pre`` (:func:`on_save_pre`: las escenas del proyecto llevan la versión activa
  de la sesión, también una escena nueva o una que Ctrl+Z devolvió a antes del cambio).

Una versión no se borra nunca (RF-009-12): lo que una escena o el equipo recuerdan solo deja de
valer si es de otro proyecto. En un proyecto del esquema 2 abierto en solo lectura no hay
versiones: «Sin versión».

**Las colecciones de las versiones** (T22; RF-009-30; plan A11, D-35): un dato de una versión
se carga en la colección de su versión, bajo «Versiones» (:func:`ensure_version_collection`, que
usa ``bl.scene.views.ensure_collection``), con su nombre generado («V10 · Definitiva [VIGENTE]
r2»: la revisión abierta o, si ya no tiene, la última), el color de su estado
(:data:`COLOR_TAGS`) y ``Collection.geoblender``; la marca en vivo (``bl.scene.live``) lee las
versiones en la misma instantánea (:func:`read_for_view`) y pone al día nombres y colores al
cambiar de estado o de revisión (:func:`show_versions`), sin volver a cargar ni mover nada. Una
SUPERADO queda sin color y sin excluir.

**El renombrado desde el Outliner** (T22; RF-009-22, D-36): suscrito con ``bpy.msgbus`` al nombre
de ``Object`` y ``Collection`` en :func:`register` y otra vez en ``load_post`` (Blender borra
las suscripciones al cargar un ``.blend``), :func:`on_name_changed` compara el nombre de las
colecciones de las versiones y de los objetos y colecciones de los datos del proyecto con el que
les puso Geoblender (``bl.scene.views.NAME_PROPERTY``): lo renombrado vuelve a su nombre
generado y su texto pasa a título en el proyecto, que vuelve a generar el nombre con él
(:func:`rename_from_outliner`); en solo lectura o con la versión no editable, solo vuelve el
nombre generado y un aviso dice por qué.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import weakref
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy
from bpy.app.handlers import persistent

from ...core.errors import GeoblenderError
from ...core.i18n import language, tr, translate
from ...core.versions import read as versions_read
from ...core.versions.model import (
    EDITABLE,
    Revision,
    RevisionState,
    Version,
    VersionError,
    VersionStatus,
    render,
)
from ..props.core import OBJECT_PROPERTY
from ..props.versions import COLLECTION_PROPERTY, WINDOW_MANAGER_PROPERTY
from . import project_session, views

if TYPE_CHECKING:
    from ...core.project.session import Project

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
VERSIONS_KEY = "versions"
"""La clave (``bl.scene.views.KEY_PROPERTY``) de la colección «Versiones» (T22; RF-009-30)."""
VERSIONS_LABEL = "Versions"
"""El ``msgid`` del nombre de la colección «Versiones»."""
VERSION_KEY = "version:"
"""El comienzo de la clave de la colección de una versión (``version:<uid>``)."""
COLOR_TAGS: dict[VersionStatus, str] = {
    VersionStatus.BORRADOR: "COLOR_03",
    VersionStatus.VIGENTE: "COLOR_04",
    VersionStatus.SUPERADO: "NONE",
    VersionStatus.DESCARTADO: "COLOR_08",
}
"""El color de la colección de una versión por su estado (``paneles-contextuales.md`` §5.3):
VIGENTE verde, BORRADOR amarillo, DESCARTADO marrón; SUPERADO sin color y sin excluirla (D-35:
excluirla la descargaría y una vista dejaría de enseñar lo que estaba mirando)."""

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
    """Una revisión de la versión activa como se enseña: su uid, «V10.r2», su estado, si está
    alterada y, si lo está, lo que no coincide (``altered_detail``, en JSON: el motivo de que no
    se reproduzca, T23)."""

    uid: str
    label: str
    state: RevisionState
    altered: bool = False
    detail: str | None = None

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


def not_editable_text() -> str | None:
    """Si la versión activa es SUPERADO o DESCARTADO, por qué no se edita ni se calcula en ella
    («Versión no editable», spec 009, T20; RF-009-21): el texto de RF-009-04 en el idioma de
    Geoblender («V01 está en estado SUPERADO: cree una versión nueva a partir de ella»); si no
    (o sin versión activa), ``None``. Con lo ya leído: no lee el proyecto."""
    shown = active()
    if shown is None or shown.status in EDITABLE:
        return None
    return render("core.version_not_editable", language=language(), version=shown.code,
                  state=shown.status)


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
    return shown, tuple(ShownRevision(item.uid, item.label(code), item.state, item.altered,
                                      item.altered_detail)
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


# Las colecciones de las versiones (T22) -------------------------------------------------------


@dataclass(frozen=True)
class VersionsRead:
    """Lo que la vista lee de las versiones en la instantánea de la marca en vivo (T22;
    RF-009-30, RF-009-22): las versiones del proyecto, la revisión que se enseña con cada una
    (por su uid), el título de cada dato cargado que lo tiene y el código de la versión de cada
    dato cargado de una versión (por el uid del dato)."""

    versions: tuple[Version, ...] = ()
    revisions: Mapping[str, Revision] = field(default_factory=dict)
    titles: Mapping[str, str] = field(default_factory=dict)
    codes: Mapping[str, str] = field(default_factory=dict)


def read_for_view(conn: sqlite3.Connection, dataset_uids: Iterable[str]) -> VersionsRead:
    """Lo que necesita la vista de las versiones y de los datos ``dataset_uids`` (los cargados),
    leído con ``conn`` (en la instantánea de quien llama: ``bl.scene.live.read_view``). Sin
    versiones (un proyecto del esquema 2 en solo lectura), nada. No escribe."""
    if not versions_read.has_versions(conn):
        return VersionsRead()
    found = versions_read.versions(conn)
    code_of = {version.uid: version.code for version in found}
    marks = versions_read.dataset_titles(conn, dataset_uids)
    return VersionsRead(
        found, versions_read.latest_revisions(conn),
        {uid: title for uid, (_owner, title) in marks.items() if title},
        {uid: code_of[owner] for uid, (owner, _title) in marks.items() if owner in code_of})


def _dress(collection: bpy.types.Collection, shown: ShownVersion) -> bool:
    """Pone en la colección de una versión su nombre generado (anotado:
    ``bl.scene.views.named``), el color de su estado y ``Collection.geoblender`` (su uid y su
    estado); nunca la excluye ni la oculta (D-35). Devuelve si cambió algo."""
    changed = views.named(collection, shown.name())
    color = COLOR_TAGS[shown.status]
    if collection.color_tag != color:
        collection.color_tag = color
        changed = True
    props = getattr(collection, COLLECTION_PROPERTY)
    if props.version_id != shown.uid:
        props.version_id = shown.uid
        changed = True
    if props.status != str(shown.status):
        props.status = str(shown.status)
        changed = True
    return changed


def ensure_version_collection(version: Version, revision: Revision | None, *,
                              scene: bpy.types.Scene | None = None) -> bpy.types.Collection:
    """La colección de ``version`` en ``scene`` (por defecto, la de la ventana), bajo
    «Versiones» (RF-009-30; plan A11): la que ya está (enlazada donde falte) o una nueva, con su
    clave (``version:<uid>``), su nombre generado con su código, su título, su estado y
    ``revision`` (la revisión que se enseña con ella: la abierta o, si ya no tiene, la última),
    «V10 · Definitiva [VIGENTE] r2», y el color de su estado. Dentro va la colección de cada dato
    de la versión (``bl.scene.views.ensure_collection``). No escribe en el proyecto."""
    chosen = bpy.context.scene if scene is None else scene
    root = views.child_collection(chosen.collection, VERSIONS_KEY,
                                  translate(language(), VERSIONS_LABEL))
    shown = _shown(version, revision)
    found = views.child_collection(root, f"{VERSION_KEY}{version.uid}", shown.name())
    _dress(found, shown)
    return found


def version_collections() -> dict[str, bpy.types.Collection]:
    """La colección de cada versión de la vista, por el uid de su versión (por su clave)."""
    found: dict[str, bpy.types.Collection] = {}
    for item in bpy.data.collections:
        key = item.get(views.KEY_PROPERTY)
        if isinstance(key, str) and key.startswith(VERSION_KEY):
            found.setdefault(key[len(VERSION_KEY):], item)
    return found


def show_versions(found: Iterable[Version], latest: Mapping[str, Revision]) -> int:
    """Pone al día, sin volver a cargar ni mover nada, el nombre y el color de la colección de
    cada versión de ``found`` que está en la vista, con su estado y su revisión de hoy
    (``latest``, la que se enseña con cada una; RF-009-30): lo que hace la marca en vivo en la
    misma tanda que lee el proyecto (``bl.scene.live``). Una colección de una versión que no está
    en ``found`` (de otro proyecto) no se toca. Devuelve cuántas cambiaron."""
    collections = version_collections()
    changed = 0
    for version in found:
        collection = collections.get(version.uid)
        if collection is not None and _dress(collection, _shown(version, latest.get(version.uid))):
            changed += 1
    return changed


# El renombrado desde el Outliner (T22; RF-009-22, D-36) ----------------------------------------

_VERSION_SUFFIX = re.compile(r"\s*\[[^\[\]]*\](?:\s*r\d+)?\s*$")
"""El estado y la revisión que deja la persona al final del nombre de una versión."""
_DATASET_SUFFIX = re.compile(r"\s*\[[^\[\]]*\][^\[\]]*$")
"""El estado que deja la persona al final del nombre de un dato (y lo que lo sigue, « · Au»)."""
VERSION_ITEM = "version"
DATASET_ITEM = "dataset"


@dataclass(frozen=True)
class _Renamed:
    """Un objeto o una colección de la vista que la persona ha renombrado: lo que es
    (:data:`VERSION_ITEM` o :data:`DATASET_ITEM`), el uid de su versión o de su dato, el texto que
    escribió y el nombre que le había puesto Geoblender."""

    item: bpy.types.ID
    kind: str
    uid: str
    typed: str
    generated: str


class _Token:
    """Lo que lleva consigo la suscripción de ``msgbus``: vive mientras Blender la guarda."""


class _Bus:
    """La suscripción al nombre de ``Object`` y ``Collection`` (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.owner = object()  # dueño de las suscripciones de msgbus
        self.token: weakref.ref[_Token] | None = None
        self.busy = False


_BUS = _Bus()


def version_title(typed: str, code: str) -> str:
    """El título que escribió la persona al renombrar la colección de la versión ``code``: el
    texto sin el código (``V02 · ``) ni el estado y la revisión (`` [BORRADOR] r1``) si los
    dejó."""
    text = typed.strip()
    prefix = re.match(rf"{re.escape(code)}\s*·\s*", text)
    if prefix is not None:
        text = text[prefix.end():]
    return _VERSION_SUFFIX.sub("", text).strip()


def dataset_title(typed: str, label: str, code: str = "") -> str:
    """El título que escribió la persona al renombrar el objeto o la colección de un dato: el
    texto sin el estado (`` [VIGENTE]``, con lo que lo sigue) y, si lo dejó, sin el tipo del dato
    (``label``, «MDT») ni el código de su versión (``code``, `` · V10``)."""
    text = typed.strip()
    bare = _DATASET_SUFFIX.sub("", text)
    if bare != text:
        if code:
            bare = re.sub(rf"\s*·\s*{re.escape(code)}$", "", bare)
        if label and bare.startswith(f"{label} "):
            bare = bare[len(label) + 1:]
    return bare.strip()


def _check(item: bpy.types.ID, kind: str, uid: str, found: list[_Renamed]) -> None:
    generated = item.get(views.NAME_PROPERTY)
    if not isinstance(generated, str):
        views.remember(item)  # sin nombre anotado (una vista anterior): el de hoy
    elif generated != item.name:
        found.append(_Renamed(item, kind, uid, item.name, generated))


def _renamed(project_uid: str) -> list[_Renamed]:
    """Las colecciones de las versiones y los objetos y las colecciones de los datos del
    proyecto ``project_uid`` cuyo nombre ya no es el que les puso Geoblender (lo del usuario no
    tiene dato ni clave: no entra)."""
    found: list[_Renamed] = []
    for collection in bpy.data.collections:
        key = collection.get(views.KEY_PROPERTY)
        if not isinstance(key, str):
            continue
        if key.startswith(VERSION_KEY):
            _check(collection, VERSION_ITEM, key[len(VERSION_KEY):], found)
        elif key.startswith(views.DATASET_KEY) and any(
                getattr(obj, OBJECT_PROPERTY).project_uid == project_uid
                for obj in collection.objects):
            _check(collection, DATASET_ITEM, key[len(views.DATASET_KEY):], found)
    for obj in bpy.data.objects:
        props = getattr(obj, OBJECT_PROPERTY)
        if props.dataset_uid and props.project_uid == project_uid:
            _check(obj, DATASET_ITEM, props.dataset_uid, found)
    return found


def _not_kept(typed: str, reason: str) -> str:
    return tr("The name «{text}» was not kept: {reason}", text=typed, reason=reason)


def _write_title(project: Project, renamed: _Renamed, title: str) -> str | None:
    """Guarda ``title`` como título de lo renombrado (``core.versions.store.set_title``, evento
    ``title_changed``); si no se puede, por qué, en el idioma de Geoblender."""
    from ...core.versions import store  # al usarlo: no al habilitar

    target = ({"version_uid": renamed.uid} if renamed.kind == VERSION_ITEM
              else {"dataset_uid": renamed.uid})
    try:
        with project.write_transaction() as conn:
            store.set_title(conn, project, title=title, **target)
    except VersionError as exc:
        return render(exc.code, language=language(), **exc.values)
    except (GeoblenderError, sqlite3.Error, OSError) as exc:
        LOGGER.warning("No se pudo guardar el título de «%s»", renamed.typed, exc_info=True)
        return str(exc)
    return None


def _titles_of(project: Project, renamed: list[_Renamed]
               ) -> dict[tuple[str, str], tuple[str, str, str]]:
    """Lo que hace falta de lo renombrado, en una lectura: de cada versión, su código y su
    título; de cada dato, el tipo de su cargador en el idioma de Geoblender, su título (el de
    hoy, o su nombre) y el código de su versión ('' del proyecto). Lo que el proyecto no tiene
    no sale."""
    from ...core.datasets import registry  # al usarlo: no al habilitar

    wanted = {item.uid for item in renamed if item.kind == DATASET_ITEM}
    found: dict[tuple[str, str], tuple[str, str, str]] = {}
    with project.read() as conn:
        if not versions_read.has_versions(conn):
            return found
        code_of: dict[str, str] = {}
        for version in versions_read.versions(conn):
            code_of[version.uid] = version.code
            found[(VERSION_ITEM, version.uid)] = (version.code, version.title, "")
        titles = versions_read.dataset_titles(conn, wanted)
        for uid in wanted:
            record = registry.get(conn, uid)
            if record is None or uid not in titles:
                continue
            owner, title = titles[uid]
            loader = views.loader_for(record.name)
            label = "" if loader is None else translate(language(), loader.label)
            found[(DATASET_ITEM, uid)] = (label, title or record.name, code_of.get(owner, ""))
    return found


def rename_from_outliner(project: Project) -> tuple[list[str], list[str]]:
    """Lo que hace :func:`on_name_changed` con el proyecto de la sesión ``project`` (RF-009-22,
    D-36): cada colección de una versión y cada objeto o colección de un dato del proyecto que la
    persona ha renombrado vuelve a su nombre generado; su texto (sin el código, el tipo ni el
    estado si los dejó: :func:`version_title`, :func:`dataset_title`) pasa a ser su título en el
    proyecto (``set_title``, evento ``title_changed``), sin cambiar su código, su identidad, su
    nombre en el proyecto ni ninguna ruta, y el nombre se vuelve a generar con él (la marca en
    vivo, ``bl.scene.live.show_now``). En solo lectura o con la versión no editable, solo vuelve
    el nombre generado. Devuelve los uid cuyo título cambió y los avisos (por qué no se guardó
    un nombre), en el idioma de Geoblender. Lo de otro proyecto queda como lo dejó la persona."""
    renamed = _renamed(project.uid)
    if not renamed:
        return [], []
    known = _titles_of(project, renamed)
    refusal = None
    if not project.writable:
        from ..ops.core_provenance import read_only_text  # al usarlo: bl.ops importa bl.scene

        refusal = read_only_text(project)
    written: list[str] = []
    warnings: list[str] = []
    for item in renamed:
        found = known.get((item.kind, item.uid))
        if found is None:  # no es de este proyecto: el nombre de la persona
            views.remember(item.item)
            continue
        views.named(item.item, item.generated)  # el generado vuelve
        prefix, current, code = found
        title = (version_title(item.typed, prefix) if item.kind == VERSION_ITEM
                 else dataset_title(item.typed, prefix, code))
        if title == current:
            continue
        reason = refusal if refusal is not None else _write_title(project, item, title)
        if reason is not None:
            warnings.append(_not_kept(item.typed, reason))
        elif item.uid not in written:
            written.append(item.uid)
    if written:
        from . import live  # al usarlo: live importa este módulo

        refresh(project)
        live.show_now(project)
    return written, warnings


def on_name_changed(*_args: object) -> None:
    """Lo que avisa ``bpy.msgbus`` al cambiar el nombre de un objeto o una colección (D-36): con
    un proyecto en la sesión, :func:`rename_from_outliner`; sus avisos van al registro de Blender
    (``bl.ops.jobs.report_later``). Lo que ella misma renombra no vuelve a contar (su nombre
    queda anotado). Un fallo va al registro técnico: Blender sigue."""
    project = project_session.current()
    if project is None or _BUS.busy:
        return
    _BUS.busy = True
    try:
        _written, warnings = rename_from_outliner(project)
        if warnings:
            from ..ops import jobs as jobs_ops  # al usarlo: bl.ops importa bl.scene

            for text in warnings:
                jobs_ops.report_later("WARNING", text)
    except Exception:  # noqa: BLE001 - una suscripción que falla no tumba Blender
        LOGGER.exception("Falló el renombrado desde el Outliner")
    finally:
        _BUS.busy = False


def _subscribe() -> None:
    """Se suscribe al nombre de ``Object`` y ``Collection`` (las suscripciones de ahora)."""
    bpy.msgbus.clear_by_owner(_BUS.owner)
    token = _Token()
    for owner_type in (bpy.types.Object, bpy.types.Collection):
        bpy.msgbus.subscribe_rna(key=(owner_type, "name"), owner=_BUS.owner, args=(token,),
                                 notify=on_name_changed)
    _BUS.token = weakref.ref(token)


def is_subscribed() -> bool:
    """Si Blender guarda la suscripción al nombre (lo que lleva consigo sigue vivo: Blender la
    suelta al cargar un fichero o al quitarla)."""
    return _BUS.token is not None and _BUS.token() is not None


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


def request_redraw() -> None:
    """Pide redibujar lo que enseña la versión activa en cada ventana (T35; RF-009-10): la barra
    superior (el control 8) y la de estado. Es el único sitio que lo pide; lo llama cada cambio
    de lo que enseñan (:func:`_notify`: abrir y cerrar el proyecto, cargar la vista, cambiar la
    versión activa y cada lectura que cambia las versiones o las revisiones: crear una versión,
    cambiar su estado, congelar). Las dos barras son áreas globales de la ventana, fuera de
    ``screen.areas`` (``docs/trampas.md`` §5): ``Area.tag_redraw`` no llega a ellas. La de
    estado, con ``bl.ui.statusbar.redraw`` (``status_text_set``, salvo en las ventanas con un
    operador modal); la superior, asignando ``WindowManager.geoblender_version_panels.shown`` (lo
    que dice la barra de estado), que tiene función ``update``
    (``bl.props.versions.redraw_all_windows``): con ella Blender avisa a todas las regiones de
    todas las ventanas. Un fallo va al registro técnico: la versión activa no depende de quien la
    enseña."""
    try:
        from ..ui import statusbar  # al usarlo: bl.ui importa bl.scene

        statusbar.redraw()
        manager = getattr(bpy.context, "window_manager", None)
        panels = getattr(manager, WINDOW_MANAGER_PROPERTY, None)
        if panels is not None:
            panels.shown = status_text()
    except Exception:  # noqa: BLE001 - la versión activa no depende de quien la enseña
        LOGGER.exception("No se pudo pedir que se redibujen las barras de las ventanas")


def _notify() -> None:
    request_redraw()
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
    vista es de otro): Blender ha borrado las suscripciones de ``msgbus`` y se renueva la del
    nombre (T22; ``docs/trampas.md`` §3); con el proyecto aún abierto, elige otra vez su versión
    activa, la de la vista cargada si la trae (D-25)."""
    try:
        _subscribe()
    except Exception:  # noqa: BLE001 - un manejador que falla no tumba Blender
        LOGGER.exception("No se pudo renovar la suscripción al nombre de la vista")
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
    """Apunta la escucha del proyecto de la sesión y los manejadores y se suscribe al nombre de
    ``Object`` y ``Collection`` (sin leer nada)."""
    _STATE.forget()
    project_session.add_listener(on_project_changed)
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if function not in handlers:
            handlers.append(function)
    _subscribe()


def unregister() -> None:
    """Quita la suscripción, los manejadores y la escucha y olvida lo de la sesión y lo
    apuntado."""
    bpy.msgbus.clear_by_owner(_BUS.owner)
    _BUS.token = None
    _BUS.busy = False
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        while function in handlers:
            handlers.remove(function)
    project_session.remove_listener(on_project_changed)
    _STATE.forget()
    _STATE.listeners = []
