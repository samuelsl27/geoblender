# SPDX-License-Identifier: GPL-3.0-or-later
"""Órdenes de las versiones (spec 009; plan 009 §5.3.5 y §5.5; ADR-0011, ADR-0012).

- ``geoblender.core_set_active_version`` (T18; RF-009-10; plan A11, D-8, D-25, D-42): «Fijar la
  versión activa», cada versión de Proyecto ▸ Versiones ▸ Versión activa y de la ventana del
  control 8, con el uid de la versión (``version_uid``; vacío, «Sin versión»). Cambia la de la
  sesión con ``bl.scene.versions.set_active``: las escenas del proyecto y los datos de usuario,
  nunca el proyecto, así que se puede también en solo lectura, para consultar, y con una versión
  SUPERADO o DESCARTADO (D-42). Sin decir cuál (F3, un guion sin la propiedad) no cambia nada;
  una versión que el proyecto no tiene se rechaza con su texto. Sin ``UNDO``: no cambia nada
  que deshacer (la vista guarda la versión activa al guardarse). Con el proyecto abierto.
- ``geoblender.core_new_version`` (T19; RF-009-01; plan A1, D-10, D-24, D-26): «Nueva
  versión…», un diálogo con el rasgo, el título, el motivo, de cuál parte («Ninguna» o una
  versión, :func:`parent_items`) y el encargo (opcional), que llama a
  ``core.versions.store.create_version``: V11 en BORRADOR con su r1 abierta y, si parte de otra,
  sus parámetros de versión heredados («Heredado de V10.r2») y nada más. La nueva pasa a ser la
  versión activa (M1: «Crear V01 y V02: el control enseña V02.r1»).
- ``geoblender.core_set_version_state`` (T19; RF-009-02, RF-009-03, RF-009-04, RF-009-25; plan
  A2, D-3): «Cambiar estado…» de la versión de la orden (:func:`target_version`: la de la
  colección de una versión en el Outliner, desde su menú contextual «Versión ▾», o la activa),
  con un diálogo que ofrece solo los destinos que admite su estado (BORRADOR: VIGENTE o
  DESCARTADO; VIGENTE: DESCARTADO) y avisa de lo que pasará: cuál pasará a SUPERADO al declarar
  VIGENTE otra, «Congele antes una revisión de V11» si aún no tiene ninguna congelada, «El
  proyecto queda sin versión vigente» al descartar la VIGENTE; el motivo, obligatorio para
  descartar. De una SUPERADO o DESCARTADO no ofrece ninguno: una ventana dice por qué (el texto
  de RF-009-04), sin botón de aceptar. Llama a ``core.versions.store.set_status``: solo se
  escriben la base, su diario y la cabecera (RF-009-02). Sin versión, la ventana del control 8 y
  los menús la dibujan desactivada (``bl.ui.version_panels``, :func:`no_version_check`) y su
  descripción dice que se elija antes.

Las dos que escriben, con ``bl_options = {'REGISTER'}`` (sin paso de deshacer, como las de la
008: Ctrl+Z no deshace la base) y ``poll`` con el motivo (sin proyecto o en solo lectura). Tras
escribir, la cabecera (:func:`_after_writing`), los indicadores de la procedencia y las versiones
de la sesión (el control 8, su ventana y la barra de estado). Los rechazos, con el texto de
``core.versions`` en el idioma de Geoblender, sin escribir nada.

Las demás órdenes de la 009 (Nueva revisión…, Reproducir…, decisiones) llegan en sus tareas
(T21 a T24) y, hasta entonces, son provisionales de R-07.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import EnumProperty, StringProperty

from ...core import i18n
from ...core.errors import GeoblenderError
from ...core.i18n import language, tr, translate
from ...core.project.events import EventKind, read_events
from ...core.versions import read as versions_read
from ...core.versions import store as versions_store
from ...core.versions.model import REQUESTED, VersionError, VersionStatus, render
from ..props.versions import COLLECTION_PROPERTY
from ..scene import project_session
from ..scene import versions as scene_versions
from ..ui.commands import catalog, text, with_note
from .core import TRANSLATION_CONTEXT, _poll_project
from .core_provenance import error_text, write_unavailable

if TYPE_CHECKING:
    from ...core.project.session import Project

LOGGER = logging.getLogger("geoblender.bl.ops")

SET_ACTIVE = "geoblender.core_set_active_version"
NEW_VERSION = "geoblender.core_new_version"
SET_STATE = "geoblender.core_set_version_state"
DIALOG_WIDTH = 520
"""El ancho de los diálogos de Nueva versión… y Cambiar estado… (px, a escala 1,0)."""
NO_PARENT = "NONE"
"""«Ninguna» en «Parte de» de Nueva versión…: una versión que no parte de otra."""
TARGETS: tuple[VersionStatus, ...] = (VersionStatus.VIGENTE, VersionStatus.DESCARTADO)
"""Los estados que puede pedir una persona (``core.versions.model.REQUESTED``), en el orden en
que los ofrece Cambiar estado…: VIGENTE → SUPERADO lo hace declarar VIGENTE otra (D-3)."""
TARGET_ITEMS = [
    ("VIGENTE", "CURRENT", ""),
    ("DESCARTADO", "DISCARDED", ""),
]
"""Los destinos de Cambiar estado… (identificador = el estado como se guarda; nombre = su
``msgid``)."""
_FIELD = {"SKIP_SAVE"}  # las rellena el diálogo: nunca las de la vez anterior
_HIDDEN = {"HIDDEN", "SKIP_SAVE"}  # las pone quien la lanza


def _error(exc: BaseException) -> str:
    """El texto de un error para el usuario en el idioma de Geoblender: el de una versión con
    su ``render``; los demás, como los de la procedencia."""
    if isinstance(exc, VersionError):
        return render(exc.code, language=i18n.language(), **exc.values)
    return error_text(exc)


def _write_poll(cls: type) -> bool:
    """El ``poll`` de las órdenes que escriben en el proyecto: dice por qué no se puede (sin
    proyecto, sin la procedencia o en solo lectura)."""
    reason = write_unavailable()
    if reason is not None:
        cls.poll_message_set(reason)  # type: ignore[attr-defined]
        return False
    return True


def _state_name(status: VersionStatus | str) -> str:
    """«BORRADOR», «VIGENTE»… en el idioma de Geoblender («DRAFT», «CURRENT»… en inglés)."""
    return translate(language(), VersionStatus(status).msgid)


def _after_writing(project: Project) -> list[str]:
    """Tras confirmar un cambio de las versiones: la cabecera (la primera versión sube
    ``min_reader_schema``, D-24), los avisos del proyecto, los indicadores de la procedencia (lo
    de una versión que se cierra sale de la cascada) y las versiones de la sesión. Devuelve los
    avisos (la cabecera que no se pudo escribir: se regenera al cerrar)."""
    warnings: list[str] = []
    try:
        project.refresh_header()
    except GeoblenderError as exc:
        LOGGER.warning("No se pudo regenerar la cabecera del proyecto: %s", exc)
        warnings.append(exc.message)
    for message in project.take_notices():
        project_session.notify(message)
        warnings.append(message)
    from ..ui import provenance as ui  # al usarlo (ARQ-08)

    if ui.refresh(force=True):
        ui.redraw()
    scene_versions.refresh(project)
    return warnings


# La versión de la orden ---------------------------------------------------------------------


def collection_version(context: Any) -> str | None:
    """La versión (su uid o su código) de la colección activa del Outliner de ``context``, si es
    la de una versión (``Collection.geoblender.version_id``; el menú contextual «Versión ▾», PC
    §3.13); fuera del Outliner o en otra colección, ``None``."""
    space = getattr(context, "space_data", None)
    if getattr(space, "type", "") != "OUTLINER":
        return None
    collection = getattr(context, "collection", None)
    if collection is None:
        layer = getattr(getattr(context, "view_layer", None), "active_layer_collection", None)
        collection = getattr(layer, "collection", None)
    data = getattr(collection, COLLECTION_PROPERTY, None)
    return str(getattr(data, "version_id", "") or "") or None


def target_version(context: Any) -> str | None:
    """La versión de una orden de versión sin ``version_uid``: la de la colección del Outliner
    (:func:`collection_version`) o, si no, la activa de la sesión; ``None`` si ninguna."""
    return collection_version(context) or scene_versions.active_version()


def no_version_text() -> str:
    """Por qué no se puede cambiar el estado sin versión, en el idioma de Geoblender."""
    return tr("Choose the active version first: Project ▸ Versions ▸ Active version")


def no_version_check(context: Any, _cmd: Any) -> str:
    """«No aplicable ahora» de Cambiar estado… (``bl.ui.commands.register_check``; BS §7.3): sin
    versión de la orden, el motivo; si no, ""."""
    return "" if target_version(context) else no_version_text()


# Fijar la versión activa (T18) --------------------------------------------------------------


class GEOBLENDER_OT_core_set_active_version(bpy.types.Operator):
    """Make this version the active one"""

    bl_idname = SET_ACTIVE
    bl_label = "Set the active version"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    version_uid: StringProperty(  # type: ignore[valid-type]
        name="Version",
        description="Identity of the version to make active (empty: no version)",
        default="",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll_project(cls, context)

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            self.report({"ERROR"}, tr("No project is open"))
            return {"CANCELLED"}
        if not self.properties.is_property_set("version_uid"):
            self.report({"WARNING"}, tr("Choose the version in Project ▸ Versions ▸ Active "
                                        "version: nothing has changed"))
            return {"CANCELLED"}
        try:
            warnings = scene_versions.set_active(context, project, self.version_uid or None)
        except VersionError as exc:
            self.report({"ERROR"}, render(exc.code, language=i18n.language(), **exc.values))
            return {"CANCELLED"}
        except GeoblenderError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        except (sqlite3.Error, OSError) as exc:
            LOGGER.exception("No se pudieron leer las versiones del proyecto")
            self.report({"ERROR"}, tr("The versions of the project could not be read: {detail}",
                                      detail=str(exc)))
            return {"CANCELLED"}
        for message in warnings:
            self.report({"WARNING"}, message)
        shown = scene_versions.active()
        version = tr("No version") if shown is None else shown.name()
        self.report({"INFO"}, tr("Active version: {version}", version=version))
        return {"FINISHED"}

    def invoke(self, context: bpy.types.Context, event: Any) -> set[str]:
        return self.execute(context)


# Nueva versión… (T19) -----------------------------------------------------------------------

_PARENT_CHOICES: list[tuple[str, str, str]] = []
"""Lo último que dio :func:`parent_items`: Blender necesita que Python guarde los textos de un
enumerado dinámico mientras los usa."""


def parent_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Los elementos de «Parte de» (``parent_uid``): «Ninguna» y cada versión del proyecto de la
    sesión, de cualquier estado, con su estado y su revisión («V10 · Definitiva [VIGENTE] r2»;
    lo ya leído, ``bl.scene.versions``: nada se lee al dibujar)."""
    choices = [(NO_PARENT, tr("No parent"), "")]
    choices += [(shown.uid, shown.name(), "") for shown in scene_versions.versions()]
    _PARENT_CHOICES[:] = choices
    return _PARENT_CHOICES


def _created(conn: sqlite3.Connection, version_uid: str) -> dict[str, Any]:
    """Los datos del evento ``version_created`` de la versión ``version_uid`` (de cuál parte, de
    qué revisión heredó y cuántos parámetros), leídos en la misma transacción."""
    for event in reversed(read_events(conn, EventKind.VERSION_CREATED)):
        if event.entity_uid == version_uid:
            return dict(event.data or {})
    return {}


def created_text(code: str, data: dict[str, Any]) -> str:
    """Lo que dice Nueva versión… al crear la versión ``code`` (plan §5.5), en el idioma de
    Geoblender: «V11 creada en BORRADOR, con su revisión r1 abierta; hereda 3 parámetros de V10
    (V10.r2)» (con ``data``, los datos de su evento)."""
    shown = tr("{version} created in {state}, with its revision r1 open", version=code,
               state=_state_name(VersionStatus.BORRADOR))
    parent = data.get("parent")
    if not parent:
        return shown
    inherited = int(data.get("inherited") or 0)
    revision = data.get("inherited_from") or parent
    if inherited == 1:
        return shown + tr("; inherits 1 parameter from {parent} ({revision})", parent=parent,
                          revision=revision)
    if inherited:
        return shown + tr("; inherits {n} parameters from {parent} ({revision})", n=inherited,
                          parent=parent, revision=revision)
    return shown + tr("; starts from {parent}", parent=parent)


class GEOBLENDER_OT_core_new_version(bpy.types.Operator):
    """Feature, parent, assignment and reason of the new version"""

    bl_idname = NEW_VERSION
    bl_label = "New version…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    feature: StringProperty(  # type: ignore[valid-type]
        name="Feature", description="What sets the version apart from the others",
        options=_FIELD,
    )
    title: StringProperty(  # type: ignore[valid-type]
        name="Title", description="Title of the version, shown with its code", options=_FIELD,
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the version is created (recorded with it)",
        options=_FIELD,
    )
    parent_uid: EnumProperty(  # type: ignore[valid-type]
        name="Starts from",
        description="Version it starts from: it inherits its version parameters and what is "
                    "frozen in its last frozen revision, never its results or figures",
        items=parent_items,
        options=_FIELD,
    )
    request: StringProperty(  # type: ignore[valid-type]
        name="Assignment",
        description="The assignment of the owner that gives rise to the version (free text)",
        options=_FIELD,
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _write_poll(cls)

    def invoke(self, context: bpy.types.Context, event: Any) -> set[str]:
        """Abre el diálogo vacío («Parte de»: «Ninguna»); nada cambia hasta aceptarlo."""
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=text(catalog().commands[NEW_VERSION].label))

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "feature", text=tr("Feature"), translate=False)
        layout.prop(self, "title", text=tr("Title"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)
        layout.prop(self, "parent_uid", text=tr("Starts from"), translate=False)
        layout.prop(self, "request", text=tr("Assignment (optional)"), translate=False)

    def execute(self, context: bpy.types.Context) -> set[str]:
        blocked = write_unavailable()
        project = project_session.current()
        if blocked is not None or project is None:
            self.report({"ERROR"}, blocked or tr("No project is open"))
            return {"CANCELLED"}
        parent = None if self.parent_uid in ("", NO_PARENT) else self.parent_uid
        try:
            with project.write_transaction() as conn:
                version, _revision = versions_store.create_version(
                    conn, project, feature=self.feature, title=self.title, reason=self.reason,
                    parent=parent, request=self.request)
                data = _created(conn, version.uid)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, _error(exc))
            return {"CANCELLED"}
        warnings = _after_writing(project)
        try:  # la nueva, la activa (M1)
            warnings += scene_versions.set_active(context, project, version.uid)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            LOGGER.warning("No se pudo hacer activa la versión nueva", exc_info=True)
            warnings.append(_error(exc))
        self.report({"INFO"}, created_text(version.code, data))
        for message in warnings:
            self.report({"WARNING"}, message)
        return {"FINISHED"}


# Cambiar estado… (T19) ----------------------------------------------------------------------


@dataclass(frozen=True)
class StateDialog:
    """Lo que enseña Cambiar estado… de una versión: su uid, su código, su nombre con su estado y
    su revisión («V10 · Definitiva [VIGENTE] r2»), su estado, los destinos que admite (en el
    orden de :data:`TARGETS`), si tiene alguna revisión congelada y el código de la VIGENTE que
    pasaría a SUPERADO al declararla VIGENTE (``None`` si no hay otra)."""

    uid: str
    code: str
    name: str
    status: VersionStatus
    targets: tuple[VersionStatus, ...]
    frozen: bool
    current: str | None

    def notes(self, target: str) -> list[tuple[str, bool]]:
        """Lo que pasará con el destino ``target``, en el idioma de Geoblender (plan §5.5), y si
        es un impedimento (en alerta): sin revisión congelada, «Congele antes una revisión de
        V11»; la VIGENTE que pasará a SUPERADO; al descartar la VIGENTE, que el proyecto queda
        sin versión vigente."""
        if target not in {item.value for item in self.targets}:
            return []
        shown: list[tuple[str, bool]] = []
        if target == VersionStatus.VIGENTE:
            if not self.frozen:
                shown.append((render("core.version_freeze_first", language=language(),
                                     version=self.code), True))
            if self.current is not None:
                shown.append((tr("{version} will become {state}", version=self.current,
                                 state=_state_name(VersionStatus.SUPERADO)), False))
        elif target == VersionStatus.DESCARTADO and self.status is VersionStatus.VIGENTE:
            shown.append((tr("The project is left without a current version"), False))
        return shown


def state_dialog(project: Project, version: str) -> StateDialog:
    """Lee de ``project`` lo que enseña Cambiar estado… de la versión ``version`` (uid o
    código), sin escribir nada. ``VersionError`` (``core.version_unknown``) si no existe."""
    with project.read() as conn:
        found = versions_read.version(conn, version)
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version,
                               version=version)
        frozen = versions_read.last_frozen(conn, found.uid) is not None
        current = versions_read.current_version(conn)
        latest = versions_read.latest_revisions(conn).get(found.uid)
    allowed = REQUESTED.get(found.status, frozenset())
    number = "" if latest is None else latest.label(found.code).partition(".")[2]
    return StateDialog(
        uid=found.uid, code=found.code,
        name=scene_versions.version_name(found.code, found.title, found.status, number),
        status=found.status, targets=tuple(item for item in TARGETS if item in allowed),
        frozen=frozen,
        current=None if current is None or current.uid == found.uid else current.code,
    )


def changed_text(change: versions_store.StatusChange) -> str:
    """Lo que dice Cambiar estado… tras el cambio, en el idioma de Geoblender: «V11 pasa de
    BORRADOR a VIGENTE; V10 pasa a SUPERADO; V10.r3 cerrada al superarse»."""
    version = change.version
    parts = [tr("{version} goes from {old} to {new}", version=version.code,
                old=_state_name(change.previous), new=_state_name(version.status))]
    codes = {version.uid: version.code}
    if change.superseded is not None:
        codes[change.superseded.uid] = change.superseded.code
        parts.append(tr("{version} becomes {state}", version=change.superseded.code,
                        state=_state_name(change.superseded.status)))
    for revision in change.closed:
        label = revision.label(codes.get(revision.version_uid, version.code))
        parts.append(tr("{revision} closed on superseding", revision=label))
    return "; ".join(parts)


class GEOBLENDER_OT_core_set_version_state(bpy.types.Operator):
    """Draft, current, superseded or discarded; the state is an attribute and no path changes"""

    bl_idname = SET_STATE
    bl_label = "Change state…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    version_uid: StringProperty(  # type: ignore[valid-type]
        name="Version",
        description="Identity or code of the version whose state changes (empty: the one of "
                    "the command, the active one)",
        options=_HIDDEN,
    )
    target: EnumProperty(  # type: ignore[valid-type]
        name="New state",
        description="The state the version goes to: CURRENT (the previous current one becomes "
                    "SUPERSEDED) or DISCARDED (with a reason)",
        items=TARGET_ITEMS,
        default="VIGENTE",
        options=_FIELD,
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why the state changes (required to discard the version)",
        options=_FIELD,
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _write_poll(cls)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        """Su descripción emergente y, sin versión de la orden, por qué no se puede (BS §7.3)."""
        about = getattr(cls, "bl_description", "")
        if getattr(properties, "version_uid", "") or target_version(context):
            return about
        return with_note(about, no_version_text())

    def _version(self, context: Any) -> str | None:
        return self.version_uid or target_version(context)

    def invoke(self, context: bpy.types.Context, event: Any) -> set[str]:
        """Lee la versión de la orden y abre el diálogo con los destinos que admite o, si no
        admite ninguno (SUPERADO o DESCARTADO), una ventana con el porqué; nada cambia hasta
        aceptar el diálogo."""
        project = project_session.current()
        uid = self._version(context)
        if project is None or not uid:
            self.report({"ERROR"}, tr("No project is open") if project is None
                        else no_version_text())
            return {"CANCELLED"}
        try:
            dialog = state_dialog(project, uid)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, _error(exc))
            return {"CANCELLED"}
        self.version_uid = dialog.uid
        self._dialog = dialog
        if not dialog.targets:
            return context.window_manager.invoke_popup(self, width=DIALOG_WIDTH)
        if self.target not in {item.value for item in dialog.targets}:
            self.target = dialog.targets[0].value
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=text(catalog().commands[SET_STATE].label))

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        dialog = getattr(self, "_dialog", None)
        if dialog is None:  # sin invoke (no debería pasar): lo lee ahora
            project = project_session.current()
            try:
                dialog = None if project is None else state_dialog(project, self.version_uid)
            except (GeoblenderError, sqlite3.Error, OSError) as exc:
                layout.label(text=_error(exc), icon="ERROR", translate=False)
                return
            if dialog is None:
                layout.label(text=tr("No project is open"), translate=False)
                return
        layout.label(text=dialog.name, translate=False)
        if not dialog.targets:
            row = layout.row()
            row.alert = True
            row.label(text=render("core.version_not_editable", language=language(),
                                  version=dialog.code, state=dialog.status),
                      icon="ERROR", translate=False)
            return
        layout.label(text=tr("New state"), translate=False)
        row = layout.row(align=True)
        for target in dialog.targets:
            row.prop_enum(self, "target", target.value, text=_state_name(target),
                          translate=False)
        for note, blocking in dialog.notes(self.target):
            line = layout.row()
            line.alert = blocking
            line.label(text=note, icon="ERROR" if blocking else "INFO", translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def execute(self, context: bpy.types.Context) -> set[str]:
        blocked = write_unavailable()
        project = project_session.current()
        if blocked is not None or project is None:
            self.report({"ERROR"}, blocked or tr("No project is open"))
            return {"CANCELLED"}
        uid = self._version(context)
        if not uid:
            self.report({"ERROR"}, no_version_text())
            return {"CANCELLED"}
        try:
            with project.write_transaction() as conn:
                change = versions_store.set_status(conn, project, uid, self.target,
                                                   reason=self.reason)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, _error(exc))
            return {"CANCELLED"}
        warnings = _after_writing(project)
        self.report({"INFO"}, changed_text(change))
        if (change.previous is VersionStatus.VIGENTE
                and change.version.status is VersionStatus.DESCARTADO):
            warnings.insert(0, tr("The project is left without a current version"))
        for message in warnings:
            self.report({"WARNING"}, message)
        return {"FINISHED"}


# En orden de registro.
classes: tuple[type, ...] = (
    GEOBLENDER_OT_core_set_active_version,
    GEOBLENDER_OT_core_new_version,
    GEOBLENDER_OT_core_set_version_state,
)
