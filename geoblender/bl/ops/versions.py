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
- ``geoblender.core_new_revision`` (T21; RF-009-06, RF-009-07, RF-009-08, RF-009-21; plan A5 a
  A7, D-40): «Nueva revisión…» de la versión de la orden (:func:`target_version`), un diálogo
  «Congelar V10.r2 y abrir V10.r3» con el motivo (obligatorio) que lee antes el plan de la
  congelación (``core.versions.freeze.freeze_plan``, :func:`revision_dialog`, sin escribir): si
  hay algo que aceptar (resultados obsoletos, operaciones que esperan revisión a mano, entradas no
  localizables y, con la spec 012 —T28, RF-012-25—, los hallazgos de las verificaciones: lo que no
  cumple, con sus m³ por recinto, y las superficies de diseño sin verificación al día, cada uno con
  su nota, ``AcceptItem.finding``), lo dice con la lista y «Aceptar y congelar» (lo aceptado, en
  ``accept``); si algo
  lo impide (una entrada cambiada sin decidir, una operación de la versión en curso, la
  comprobación de apertura…), una ventana sin aceptar que lo dice. Aceptado desde la interfaz,
  ``core.versions.freeze.freeze_steps`` en un modal de pasos (``_StepsModal`` de
  ``bl.ops.core``: un evento del temporizador cada 0,05 s y 0,05 s de pasos en cada uno), con su
  avance en la barra de estado («Congelando V10.r2: copiando «des_final_v10.tif»… 40 % · Esc:
  cancelar», :func:`freeze_status_text`) y Esc, que no deja nada a medias; desde un guion o sin
  ventana, de una vez. Al terminar, «V10.r2 congelada (1,2 GB copiados; 3 contenidos ya
  congelados, referenciados); V10.r3 abierta» (:func:`frozen_text`) y los avisos (la cabecera que
  no se pudo escribir, los del proyecto) con ``bl.ops.jobs.report_later``. Sin versión, o con
  ella SUPERADO o DESCARTADO («Versión no editable», RF-009-04), los menús y la ventana del
  control 8 la dibujan desactivada (:func:`new_revision_check`) y su descripción y su ``poll``
  dicen por qué.
- ``geoblender.core_reproduce_version`` (T23; RF-009-11, RF-009-09; plan A9, D-4, D-32): «Reproducir
  la versión desde sus entradas congeladas», de la revisión ``revision_uid`` o, sin ella, de la
  última congelada de la versión de la orden (:func:`target_version`). Llama a
  ``core.versions.reproduce.reproduce_steps``, que comprueba antes todas sus huellas y el espacio
  y vuelve a ejecutar, en la caché y sin cambiar nada del proyecto, sus operaciones con lo
  congelado: desde la interfaz, en el modal de pasos (``_StepsModal``, 0,05 s por evento) con su
  avance en la barra de estado («Reproduciendo V10.r2: «des.pit» (2 de 5)… 40 % · Esc:
  cancelar», :class:`ReproduceStatus`) y Esc, que no deja nada; desde un guion, de una vez. Al
  terminar, el resumen («V10.r2 reproducida: coinciden …»; con lo que no coincide y su causa, un
  aviso) y, desde la interfaz, la ventana del informe (``GEOBLENDER_PT_core_reproduce_report``,
  ``bl.ui.version_panels.fill_report``). Sin versión, sin revisión congelada o con la última
  alterada, los menús y la ventana del control 8 la dibujan desactivada con el motivo
  (:func:`reproduce_check`) y su descripción y su ``poll`` lo dicen (:func:`reproduce_note`).
  No escribe en el proyecto: también en solo lectura (la caché va entonces a los datos de
  usuario).
- ``geoblender.core_show_decisions`` (T24; RF-009-13; plan A10, D-33): «Encargos y decisiones de la
  propiedad…», que lee las decisiones de la propiedad, los documentos que pueden citar y los
  encargos de las versiones (``bl.ui.version_panels.fill_decisions``) y abre su ventana
  (``GEOBLENDER_PT_core_decisions``); solo lee: también en solo lectura. Desde un guion, sin
  ventana, solo las filas.
- ``geoblender.core_add_decision`` (T24; RF-009-13; interna): «Registrar decisión…», el diálogo
  con quién decide, el día (DD/MM/AAAA; hoy, por defecto), qué se decide, el documento (una
  entrada registrada de tipo documento, :func:`document_items`) y una referencia en texto, y
  los parámetros (sus claves) y las versiones (sus códigos; la activa, por defecto) a los que
  afecta, separados por comas, que llama a ``core.versions.decisions.record_decision``. Después,
  la lista, Parámetros del proyecto (su decisor de la propiedad) y el control 8.

Las que escriben, con ``bl_options = {'REGISTER'}`` (sin paso de deshacer, como las de la 008:
Ctrl+Z no deshace la base) y ``poll`` con el motivo (sin proyecto o en solo lectura). Tras
escribir, la cabecera (:func:`_after_writing`), los indicadores de la procedencia y las versiones
de la sesión (el control 8, su ventana y la barra de estado). Los rechazos, con el texto de
``core.versions`` en el idioma de Geoblender, sin escribir nada.

"""

from __future__ import annotations

import datetime as dt
import logging
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ...core import i18n
from ...core.errors import GeoblenderError
from ...core.i18n import language, tr, translate
from ...core.project.events import EventKind, read_events
from ...core.project.model import Progress
from ...core.versions import read as versions_read
from ...core.versions import store as versions_store
from ...core.versions.model import (
    EDITABLE,
    REQUESTED,
    ItemState,
    RevisionState,
    VersionError,
    VersionStatus,
    render,
    revision_label,
)
from ..props.versions import COLLECTION_PROPERTY
from ..scene import project_session
from ..scene import versions as scene_versions
from ..ui import labels
from ..ui.commands import catalog, text, with_note
from . import jobs as jobs_ops
from .core import TRANSLATION_CONTEXT, _poll_project, _StepsModal
from .core_provenance import SESSION, error_text, write_unavailable

if TYPE_CHECKING:
    from ...core.project.session import Project
    from ...core.provenance.gate import CheckState
    from ...core.versions.freeze import AcceptItem, Blocker, FreezeOutcome
    from ...core.versions.reproduce import ReproduceReport

LOGGER = logging.getLogger("geoblender.bl.ops")

SET_ACTIVE = "geoblender.core_set_active_version"
NEW_VERSION = "geoblender.core_new_version"
SET_STATE = "geoblender.core_set_version_state"
NEW_REVISION = "geoblender.core_new_revision"
REPRODUCE = "geoblender.core_reproduce_version"
REPORT_PANEL = "GEOBLENDER_PT_core_reproduce_report"
"""La ventana del informe de Reproducir… (``bl.ui.version_panels``, T23)."""
SHOW_DECISIONS = "geoblender.core_show_decisions"
ADD_DECISION = "geoblender.core_add_decision"
DECISIONS_PANEL = "GEOBLENDER_PT_core_decisions"
"""La ventana de los encargos y las decisiones de la propiedad (``bl.ui.version_panels``, T24)."""
NO_DOCUMENT = "NONE"
"""«Ninguno» en «Documento» de Registrar decisión…: una decisión con solo una referencia."""
DIALOG_WIDTH = 520
"""El ancho de los diálogos de Nueva versión…, Cambiar estado… y Nueva revisión… (px, a escala
1,0)."""
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


def _after_writing(project: Project, *, header: bool = True) -> list[str]:
    """Tras confirmar un cambio de las versiones: la cabecera (la primera versión sube
    ``min_reader_schema``, D-24; ``header=False`` si ya la escribió quien llama, como
    ``freeze_steps``), los avisos del proyecto, los indicadores de la procedencia (lo de una
    versión que se cierra sale de la cascada) y las versiones de la sesión. Devuelve los avisos
    (la cabecera que no se pudo escribir: se regenera al cerrar)."""
    warnings: list[str] = []
    try:
        if header:
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


# Nueva revisión… (T21) ----------------------------------------------------------------------

_ACCEPT_SEPARATOR = ","
_KIND_SEPARATOR = ":"
_QUOTED = re.compile(r"«(.+?)»")
"""El nombre entre comillas angulares del avance de la copia («Copiando «x.tif»…»)."""


def _shown_version(version: str) -> scene_versions.ShownVersion | None:
    """La versión ``version`` (uid o código) entre las ya leídas de la sesión, o ``None``."""
    return next((item for item in scene_versions.versions() if version in (item.uid, item.code)),
                None)


def not_editable_note(context: Any, version: str | None = None) -> str | None:
    """«Versión no editable» (RF-009-04, RF-009-21) de la versión ``version`` (si no, la de la
    orden, :func:`target_version`) si es SUPERADO o DESCARTADO, en el idioma de Geoblender; si
    no (o sin versión), ``None``. Con lo ya leído: no lee el proyecto."""
    shown = _shown_version(version or target_version(context) or "")
    if shown is None or shown.status in EDITABLE:
        return None
    return render("core.version_not_editable", language=language(), version=shown.code,
                  state=shown.status)


def new_revision_check(context: Any, _cmd: Any) -> str:
    """«No aplicable ahora» de Nueva revisión… (``bl.ui.commands.register_check``; BS §7.3): sin
    versión de la orden, que se elija; con ella SUPERADO o DESCARTADO, el texto de RF-009-04; si
    no, ""."""
    if not target_version(context):
        return no_version_text()
    return not_editable_note(context) or ""


def accept_token(items: Iterable[AcceptItem]) -> str:
    """Lo que se acepta (``accept`` de Nueva revisión…): «clase:uid» de cada elemento, separados
    por comas (``dataset:…,operation:…,input:…``)."""
    return _ACCEPT_SEPARATOR.join(f"{item.item_kind}{_KIND_SEPARATOR}{item.item_uid}"
                                  for item in items)


def _acceptance(token: str) -> Any:
    """La ``core.versions.freeze.Acceptance`` de ``token`` (:func:`accept_token`); ``None`` si
    no acepta nada."""
    pairs = frozenset(tuple(part.strip().split(_KIND_SEPARATOR, 1))
                      for part in token.split(_ACCEPT_SEPARATOR)
                      if _KIND_SEPARATOR in part)
    if not pairs:
        return None
    from ...core.versions.freeze import Acceptance  # al usarlo (plan §2.1)

    return Acceptance(pairs)  # type: ignore[arg-type]


def _pending(project: Project) -> CheckState | None:
    """Lo que la comprobación de apertura aún no ha comprobado (la congelación espera a que
    termine, D-40), si es la del proyecto ``project``; si no, ``None``."""
    return SESSION.pending if SESSION.project is project else None


_STATE_TEXTS = {
    ItemState.STALE: "stale result",
    ItemState.REVIEW: "waiting for manual review",
    ItemState.UNLOCATABLE: "cannot be located",
}
"""El estado de un elemento que hay que aceptar, en la lista del diálogo (``msgid``)."""


def _joined(parts: list[str]) -> str:
    """«a, b y c» en el idioma de Geoblender."""
    if len(parts) < 2:
        return "".join(parts)
    return tr("{items} and {last}", items=", ".join(parts[:-1]), last=parts[-1])


@dataclass(frozen=True)
class RevisionDialog:
    """Lo que enseña Nueva revisión… de una versión (del plan de la congelación, sin escribir):
    su uid y su código, la revisión que se congela («V10.r2») y la que se abrirá («V10.r3»), lo
    que hay que aceptar y lo que lo impide."""

    uid: str
    code: str
    label: str
    following: str
    accept: tuple[AcceptItem, ...]
    blockers: tuple[Blocker, ...]

    @property
    def title(self) -> str:
        """«Congelar V10.r2 y abrir V10.r3»."""
        return tr("Freeze {revision} and open {following}", revision=self.label,
                  following=self.following)

    @property
    def confirm_text(self) -> str:
        """El botón de aceptar: «Aceptar y congelar» si hay algo que aceptar; si no,
        «Congelar»."""
        return tr("Accept and freeze") if self.accept else tr("Freeze")

    @property
    def accepted(self) -> str:
        """Todo lo que hay que aceptar, como lo lleva ``accept`` (:func:`accept_token`)."""
        return accept_token(self.accept)

    def accept_text(self) -> str:
        """«Hay 3 resultados obsoletos, 1 operación que espera revisión a mano y 1 entrada no
        localizable: si congela, quedarán anotados» (plan §5.5); "" sin nada que aceptar. Un
        elemento al día con la nota de un módulo (spec 012, RF-012-25: lo que no cumple una
        verificación, una superficie sin verificar) se cuenta como «hallazgo de las
        verificaciones»; el obsoleto con nota, por su estado."""
        if not self.accept:
            return ""
        states = [item.state for item in self.accept]
        parts = []
        stale = states.count(ItemState.STALE)
        if stale:
            parts.append(tr("1 stale result") if stale == 1
                         else tr("{n} stale results", n=stale))
        review = states.count(ItemState.REVIEW)
        if review:
            parts.append(tr("1 operation waiting for manual review") if review == 1
                         else tr("{n} operations waiting for manual review", n=review))
        missing = states.count(ItemState.UNLOCATABLE)
        if missing:
            parts.append(tr("1 input that cannot be located") if missing == 1
                         else tr("{n} inputs that cannot be located", n=missing))
        findings = sum(1 for item in self.accept
                       if item.finding is not None and item.state not in _STATE_TEXTS)
        if findings:
            parts.append(tr("1 finding of the compliance checks") if findings == 1
                         else tr("{n} findings of the compliance checks", n=findings))
        if len(self.accept) == 1:
            return tr("There is {items}: if you freeze, it will be recorded as it is",
                      items=_joined(parts))
        return tr("There are {items}: if you freeze, they will be recorded as they are",
                  items=_joined(parts))

    def accept_lines(self) -> list[str]:
        """Cada elemento que hay que aceptar, con su nombre y su estado: «des_final_v10»:
        resultado obsoleto; con la nota de un módulo (spec 012, RF-012-25), a continuación o, si
        está al día, sola: «Diseño»: «r_torre»: 600 m³ de movimiento."""
        lines = []
        for item in self.accept:
            state = _STATE_TEXTS.get(item.state)
            shown = None if state is None else translate(language(), state)
            if item.finding is None:
                lines.append(tr("«{name}»: {state}", name=item.name,
                                state=translate(language(), str(item.state))
                                if shown is None else shown))
            elif shown is None:
                lines.append(tr("«{name}»: {finding}", name=item.name, finding=item.finding))
            else:
                lines.append(tr("«{name}»: {state} · {finding}", name=item.name, state=shown,
                                finding=item.finding))
        return lines

    def blocker_texts(self) -> list[str]:
        """Lo que lo impide, en el idioma de Geoblender («Hay entradas aguas arriba de V10.r2
        cambiadas sin decidir («Limites_v1»): …»)."""
        return [render(blocker.code, language=language(), version=self.code,
                       revision=self.label,
                       names=", ".join(f"«{name}»" for name in blocker.names))
                for blocker in self.blockers]


def revision_dialog(project: Project, version: str) -> RevisionDialog:
    """Lee de ``project`` lo que enseña Nueva revisión… de la versión ``version`` (uid o código):
    el plan de congelar su revisión abierta (``core.versions.freeze.freeze_plan``), sin escribir
    nada. ``VersionError`` si no existe (``core.version_unknown``) o no es editable
    (``core.version_not_editable``)."""
    from ...core.versions.freeze import freeze_plan  # al usarlo (plan §2.1)

    plan = freeze_plan(project, version, pending=_pending(project))
    code = plan.version.code
    return RevisionDialog(uid=plan.version.uid, code=code, label=plan.label,
                          following=revision_label(code, plan.revision.number + 1),
                          accept=plan.accept, blockers=plan.blockers)


def size_text(size: int) -> str:
    """Un tamaño como lo lee una persona, en el idioma de Geoblender (unidades decimales; coma
    decimal en español: «1,2 GB»)."""
    for unit, factor in (("GB", 10**9), ("MB", 10**6), ("kB", 10**3)):
        if size >= factor:
            shown = f"{size / factor:.1f} {unit}"
            return shown.replace(".", ",") if language() == "es" else shown
    return f"{size} B"


def frozen_text(outcome: FreezeOutcome) -> str:
    """Lo que dice Nueva revisión… al terminar (plan §5.5), en el idioma de Geoblender: «V10.r2
    congelada (1,2 GB copiados; 3 contenidos ya congelados, referenciados); V10.r3 abierta»."""
    code = outcome.label.partition(".")[0]
    following = outcome.opened.label(code) if outcome.opened is not None else ""
    size = size_text(outcome.copied_bytes)
    referenced = len(outcome.referenced)
    if referenced == 1:
        return tr("{revision} frozen ({size} copied; 1 content already frozen, referenced); "
                  "{following} open", revision=outcome.label, size=size, following=following)
    if referenced:
        return tr("{revision} frozen ({size} copied; {n} contents already frozen, referenced); "
                  "{following} open", revision=outcome.label, size=size, n=referenced,
                  following=following)
    return tr("{revision} frozen ({size} copied); {following} open", revision=outcome.label,
              size=size, following=following)


def freeze_status_text(label: str, step: Progress) -> str:
    """El avance de Nueva revisión… en la barra de estado (plan §5.5), en el idioma de
    Geoblender, del paso ``step`` de congelar la revisión ``label``: «Congelando V10.r2:
    copiando «des_final_v10.tif»… 40 % · Esc: cancelar» (las fases de
    ``core.versions.copy.PHASES`` y la confirmación)."""
    from ...core.versions.copy import PHASES  # al usarlo (plan §2.1)

    percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
    found = _QUOTED.search(step.message or "")
    name = found.group(1) if found else ""
    space, copying, checking, tables, manifest = PHASES
    if step.phase in (copying, tables) and name:
        return tr("Freezing {revision}: copying «{name}»… {percent} % · Esc: cancel",
                  revision=label, name=name, percent=percent)
    if step.phase == checking and name:
        return tr("Freezing {revision}: checking «{name}»… {percent} % · Esc: cancel",
                  revision=label, name=name, percent=percent)
    if step.phase == space:
        return tr("Freezing {revision}: checking the free space… {percent} % · Esc: cancel",
                  revision=label, percent=percent)
    if step.phase == manifest:
        return tr("Freezing {revision}: writing the manifest… {percent} % · Esc: cancel",
                  revision=label, percent=percent)
    return tr("Freezing {revision}: confirming… {percent} % · Esc: cancel", revision=label,
              percent=percent)


def _open_label(project: Project, version: str) -> str:
    """«V10.r2», la revisión abierta de la versión ``version`` (uid o código); ``version`` si
    no tiene (la congelación lo rechaza con su texto)."""
    with project.read() as conn:
        found = versions_read.version(conn, version)
        revision = None if found is None else versions_read.open_revision(conn, found.uid)
    return version if found is None or revision is None else revision.label(found.code)


class GEOBLENDER_OT_core_new_revision(_StepsModal, bpy.types.Operator):
    """New revision of the active version (the reason is required)"""

    bl_idname = NEW_REVISION
    bl_label = "New revision…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    # Como Refrescar y Cargar en la vista (plan §5.3.5): cada evento del temporizador avanza
    # pasos durante, como mucho, este tiempo (ninguna llamada de más de 0,2 s).
    STEP_BUDGET_S = 0.05

    version_uid: StringProperty(  # type: ignore[valid-type]
        name="Version",
        description="Identity or code of the version whose open revision is frozen (empty: "
                    "the one of the command, the active one)",
        options=_HIDDEN,
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why the next revision is opened (required; recorded with it)",
        options=_FIELD,
    )
    # Lo aceptado en el diálogo (:func:`accept_token`): lo pone ``invoke`` con lo que lista.
    accept: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]
    # En pasos desde el temporizador de la ventana, con el avance y Esc: lo pone ``invoke``;
    # desde un guion, sin él, de una vez.
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        if not _write_poll(cls):
            return False
        note = not_editable_note(context)
        if note is not None:
            cls.poll_message_set(note)
            return False
        return True

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        """Su descripción emergente y, sin versión de la orden o con ella no editable, por qué
        no se puede (BS §7.3)."""
        about = getattr(cls, "bl_description", "")
        version = getattr(properties, "version_uid", "") or target_version(context)
        if not version:
            return with_note(about, no_version_text())
        return with_note(about, not_editable_note(context, version) or "")

    def _version(self, context: Any) -> str | None:
        return self.version_uid or target_version(context)

    def invoke(self, context: bpy.types.Context, event: Any) -> set[str]:
        """Lee el plan de la congelación y abre el diálogo con el motivo y lo que hay que
        aceptar o, si algo lo impide, una ventana con el porqué; nada cambia hasta aceptarlo."""
        project = project_session.current()
        uid = self._version(context)
        if project is None or not uid:
            self.report({"ERROR"}, tr("No project is open") if project is None
                        else no_version_text())
            return {"CANCELLED"}
        try:
            dialog = revision_dialog(project, uid)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self.version_uid = dialog.uid
        self.accept = dialog.accepted
        self.in_steps = getattr(context, "window", None) is not None
        self._dialog = dialog
        if dialog.blockers:
            return context.window_manager.invoke_popup(self, width=DIALOG_WIDTH)
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=dialog.title,
            confirm_text=dialog.confirm_text)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        dialog = getattr(self, "_dialog", None)
        if dialog is None:  # sin invoke (no debería pasar): lo lee ahora
            project = project_session.current()
            try:
                dialog = None if project is None else revision_dialog(project, self.version_uid)
            except (GeoblenderError, sqlite3.Error, OSError) as exc:
                layout.label(text=error_text(exc), icon="ERROR", translate=False)
                return
            if dialog is None:
                layout.label(text=tr("No project is open"), translate=False)
                return
        width = labels.dialog_width(DIALOG_WIDTH)
        if dialog.blockers:
            labels.draw_wrapped(layout, dialog.title, width)
            for shown in dialog.blocker_texts():
                column = layout.column()
                column.alert = True
                labels.draw_wrapped(column, shown, width, icon="ERROR")
            return
        layout.prop(self, "reason", text=tr("Reason"), translate=False)
        header = dialog.accept_text()
        if not header:
            return
        column = layout.column()
        column.alert = True
        labels.draw_wrapped(column, header, width, icon="ERROR")
        for shown in dialog.accept_lines():
            labels.draw_wrapped(layout, shown, width, icon="DOT")

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
        from ...core.versions.freeze import freeze_steps  # al usarlo (plan §2.1)

        try:
            label = _open_label(project, uid)
            steps = freeze_steps(project, uid, reason=self.reason,
                                 accepted=_acceptance(self.accept), pending=_pending(project))
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self._project = project
        self._label = label
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, steps)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        outcome = None
        try:
            for step in steps:
                if step.result is not None:
                    outcome = step.result
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self._report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if outcome is None:  # pragma: no cover - freeze_steps acaba siempre con su final
            self._report({"ERROR"}, tr("The operation did not finish with its result"))
            return {"CANCELLED"}
        return self._finish(outcome)

    def _finish(self, outcome: FreezeOutcome) -> set[str]:
        """Lo que dice la orden al terminar: congelada y abierta (o cancelada) y los avisos (la
        cabecera que no se pudo escribir, los del proyecto) con ``report_later``; tras
        congelar, los indicadores y las versiones de la sesión (el control 8)."""
        if outcome.cancelled:
            self._report({"INFO"}, self._cancelled_text())
            self.outcome = "CANCELLED"
            return {"CANCELLED"}
        warnings = [*outcome.warnings, *_after_writing(self._project, header=False)]
        self._report({"INFO"}, frozen_text(outcome))
        for message in warnings:
            jobs_ops.report_later("WARNING", message)
        self.outcome = "FINISHED"
        return {"FINISHED"}

    # En pasos ------------------------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        return freeze_status_text(getattr(self, "_label", ""), step)

    def _cancelled_text(self) -> str:
        return tr("Freezing cancelled: nothing has been left half-done")

    def _error_text(self, exc: GeoblenderError) -> str:
        return error_text(exc)

    def _result(self, context: bpy.types.Context, step: Progress) -> set[str] | None:
        if step.result is None:
            if project_session.current() is not getattr(self, "_project", None):
                return self._fail(context, tr("The project was closed while {revision} was "
                                              "being frozen: nothing has been left half-done",
                                              revision=getattr(self, "_label", "")))
            return None
        self._done(context)
        return self._finish(step.result)

    def modal(self, context: bpy.types.Context, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except (sqlite3.Error, OSError) as exc:
            LOGGER.error("«Nueva revisión…» se ha parado", exc_info=exc)
            return self._fail(context, error_text(exc))
        except Exception as exc:  # noqa: BLE001 - los pasos cerrados no dejan nada a medias
            LOGGER.error("«Nueva revisión…» se ha parado", exc_info=exc)
            return self._fail(context, tr("Freezing {revision} stopped: {error}",
                                          revision=getattr(self, "_label", ""),
                                          error=str(exc)))


# Reproducir… (T23) ---------------------------------------------------------------------------

_OPERATION = re.compile(r"«(?P<op>[^»]+)» \((?P<index>\d+) \w+ (?P<count>\d+)\)")
"""La operación del paso que empieza a reproducirla («Reproduciendo V10.r2: «des.pit» (2 de
5)…», ``core.version_reproduce_progress``)."""


def _call_panel(name: str) -> set[str]:
    """Abre la ventana emergente ``name`` con ``wm.call_panel``; sigue abierta aunque el ratón
    salga de ella (``keep_open``), hasta pulsar fuera o Esc (como las de la 008 y la 010)."""
    return bpy.ops.wm.call_panel(name=name, keep_open=True)


def altered_text(label: str, detail: str | None) -> str:
    """Por qué no se reproduce la revisión ``label`` alterada, con lo que no coincide (su
    ``altered_detail``), en el idioma de Geoblender: «La revisión V10.r2 está alterada
    (rasters/des_final_v10.tif: otro tamaño): no se reproduce»."""
    from ...core.versions.reproduce import detail_text  # al usarlo (plan §2.1)

    shown = language()
    return render("core.version_reproduce_altered", language=shown, revision=label,
                  what=detail_text(detail, shown))


def reproduce_note(context: Any, version: str | None = None) -> str | None:
    """Por qué no se puede reproducir ahora la última revisión congelada de la versión
    ``version`` (si no, la de la orden, :func:`target_version`), en el idioma de Geoblender: sin
    versión, que se elija; sin ninguna congelada, «Congele antes una revisión de V11»; con la
    última alterada, :func:`altered_text`. ``None`` si se puede o si no se sabe sin leer el
    proyecto (una versión que no es la activa: lo dice la orden al pedirla). Con lo ya leído
    (``bl.scene.versions``)."""
    uid = version or target_version(context)
    if not uid:
        return no_version_text()
    shown = _shown_version(uid)
    if shown is None or shown.uid != scene_versions.active_version():
        return None
    frozen = [item for item in scene_versions.revisions() if item.state == RevisionState.FROZEN]
    if not frozen:
        return render("core.version_freeze_first", language=language(), version=shown.code)
    last = frozen[-1]
    return altered_text(last.label, last.detail) if last.altered else None


def reproduce_check(context: Any, _cmd: Any) -> str:
    """«No aplicable ahora» de Reproducir… (``bl.ui.commands.register_check``; BS §7.3): el
    motivo de :func:`reproduce_note`, o ""."""
    return reproduce_note(context) or ""


def reproduce_target(project: Project, revision: str, version: str | None) -> tuple[str, str]:
    """La revisión que se reproduce y su etiqueta («V10.r2»): ``revision`` (uid o etiqueta) si
    se da o, si no, la última congelada de ``version`` (uid o código). Solo lee. ``VersionError``
    sin versiones en el proyecto (``core.version_reproduce_unknown``), con una versión que no
    existe (``core.version_unknown``) o sin ninguna congelada (``core.version_freeze_first``);
    una revisión dada que no está, la rechaza la reproducción con su texto."""
    asked = revision or version or ""
    with project.read() as conn:
        if not versions_read.has_versions(conn):
            raise VersionError("core.version_reproduce_unknown", field="revisión", value=asked,
                               revision=asked)
        if revision:
            found = versions_read.revision(conn, revision)
            owner = None if found is None else versions_read.version(conn, found.version_uid)
            if found is None or owner is None:
                return revision, revision
            return found.uid, found.label(owner.code)
        chosen = versions_read.version(conn, asked)
        if chosen is None:
            raise VersionError("core.version_unknown", field="versión", value=asked,
                               version=asked)
        last = versions_read.last_frozen(conn, chosen.uid)
    if last is None:
        raise VersionError("core.version_freeze_first", field="versión", value=chosen.code,
                           version=chosen.code)
    return last.uid, last.label(chosen.code)


class ReproduceStatus:
    """El avance de Reproducir… en la barra de estado (plan §5.5), en el idioma de Geoblender,
    de la revisión ``label``: «Reproduciendo V10.r2: comprobando las huellas… 10 % · Esc:
    cancelar» y, desde que empieza cada operación (sus entradas, su reproducción y la
    comparación), «Reproduciendo V10.r2: «des.pit» (2 de 5)… 40 % · Esc: cancelar». Recuerda la
    operación en curso de un paso al siguiente."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.operation: tuple[str, int, int] | None = None

    def text(self, step: Progress) -> str:
        """El texto del paso ``step`` de ``core.versions.reproduce.reproduce_steps``."""
        from ...core.versions.reproduce import CHECK_PHASE, PHASES  # al usarlo (plan §2.1)

        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        found = _OPERATION.search(step.message or "") if step.phase == PHASES[2] else None
        if found is not None:
            self.operation = (found["op"], int(found["index"]), int(found["count"]))
        if step.phase == CHECK_PHASE:
            return tr("Reproducing {revision}: checking the fingerprints… {percent} % · Esc: "
                      "cancel", revision=self.label, percent=percent)
        if step.phase == PHASES[-1]:
            return tr("Reproducing {revision}: writing the report… {percent} % · Esc: cancel",
                      revision=self.label, percent=percent)
        if self.operation is None:  # pragma: no cover - cada operación empieza con su paso
            return tr("Reproducing {revision}… {percent} % · Esc: cancel", revision=self.label,
                      percent=percent)
        name, index, count = self.operation
        return tr("Reproducing {revision}: «{op_type}» ({index} of {count})… {percent} % · Esc: "
                  "cancel", revision=self.label, op_type=name, index=index, count=count,
                  percent=percent)


class GEOBLENDER_OT_core_reproduce_version(_StepsModal, bpy.types.Operator):
    """Recompute the version from its frozen inputs and compare the figures"""

    bl_idname = REPRODUCE
    bl_label = "Reproduce the version from its frozen inputs"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    # Como Nueva revisión… (plan §5.3.5): cada evento del temporizador avanza pasos durante,
    # como mucho, este tiempo (ninguna llamada de más de 0,2 s).
    STEP_BUDGET_S = 0.05

    revision_uid: StringProperty(  # type: ignore[valid-type]
        name="Revision",
        description="Identity or label of the frozen revision that is reproduced (empty: the "
                    "last frozen one of the version of the command, the active one)",
        options=_HIDDEN,
    )
    # En pasos desde el temporizador de la ventana, con el avance y Esc: lo pone ``invoke``;
    # desde un guion, sin él, de una vez.
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Con el proyecto abierto (también en solo lectura: no escribe en él); con la versión
        de la orden sin ninguna revisión congelada o con la última alterada, no, con el
        motivo. Sin versión, sí: un guion puede decir qué revisión (la orden lo rechaza si
        no)."""
        if not _poll_project(cls, context):
            return False
        if not target_version(context):
            return True
        note = reproduce_note(context)
        if note is not None:
            cls.poll_message_set(note)
            return False
        return True

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        """Su descripción emergente y, sin versión, sin revisión congelada o con la última
        alterada, por qué no se puede (BS §7.3)."""
        about = getattr(cls, "bl_description", "")
        if getattr(properties, "revision_uid", ""):
            return about
        return with_note(about, reproduce_note(context) or "")

    def invoke(self, context: bpy.types.Context, event: Any) -> set[str]:
        """Desde la interfaz: en pasos, con el avance y Esc (sin diálogo: no pide nada)."""
        self.in_steps = getattr(context, "window", None) is not None
        return self.execute(context)

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            self.report({"ERROR"}, tr("No project is open"))
            return {"CANCELLED"}
        version = None if self.revision_uid else target_version(context)
        if not self.revision_uid and not version:
            self.report({"ERROR"}, no_version_text())
            return {"CANCELLED"}
        from ...core.versions.reproduce import reproduce_steps  # al usarlo (plan §2.1)

        try:
            revision, label = reproduce_target(project, self.revision_uid, version)
            steps = reproduce_steps(project, revision)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self._project = project
        self._label = label
        self._status = ReproduceStatus(label)
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, steps)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        report = None
        try:
            for step in steps:
                if step.result is not None:
                    report = step.result
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self._report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if report is None:  # pragma: no cover - reproduce_steps acaba siempre con su informe
            self._report({"ERROR"}, tr("The operation did not finish with its result"))
            return {"CANCELLED"}
        finished = self._finish(report)
        if not report.cancelled and not report.matches:
            # Desde un guion, lo que informa la orden no llega a Info (docs/trampas.md §3).
            jobs_ops.report_later("WARNING", report.text(language()))
        return finished

    def _finish(self, report: ReproduceReport) -> set[str]:
        """Lo que dice la orden al terminar: el resumen del informe (con lo que no coincide y su
        causa, como aviso) y sus líneas en la ventana del informe (``fill_report``)."""
        if report.cancelled:
            self._report({"INFO"}, self._cancelled_text())
            self.outcome = "CANCELLED"
            return {"CANCELLED"}
        from ..ui import version_panels  # al usarlo (ARQ-08)

        version_panels.fill_report(self._project, report)
        self._report({"INFO"} if report.matches else {"WARNING"}, report.text(language()))
        self.outcome = "FINISHED"
        return {"FINISHED"}

    # En pasos ------------------------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        status = getattr(self, "_status", None)
        if status is None:  # pragma: no cover - lo pone execute antes de empezar
            status = self._status = ReproduceStatus(getattr(self, "_label", ""))
        return status.text(step)

    def _cancelled_text(self) -> str:
        return render("core.version_reproduce_cancelled", language=language())

    def _error_text(self, exc: GeoblenderError) -> str:
        return error_text(exc)

    def _result(self, context: bpy.types.Context, step: Progress) -> set[str] | None:
        if step.result is None:
            if project_session.current() is not getattr(self, "_project", None):
                return self._fail(context, tr("The project was closed while {revision} was "
                                              "being reproduced: nothing has been left "
                                              "half-done", revision=getattr(self, "_label", "")))
            return None
        self._done(context)
        finished = self._finish(step.result)
        if finished == {"FINISHED"}:
            try:  # la ventana del informe, desde el evento de la ventana
                _call_panel(REPORT_PANEL)
            except RuntimeError:
                LOGGER.warning("No se pudo abrir la ventana del informe", exc_info=True)
        return finished

    def modal(self, context: bpy.types.Context, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except (sqlite3.Error, OSError) as exc:
            LOGGER.error("«Reproducir…» se ha parado", exc_info=exc)
            return self._fail(context, error_text(exc))
        except Exception as exc:  # noqa: BLE001 - los pasos cerrados no dejan nada a medias
            LOGGER.error("«Reproducir…» se ha parado", exc_info=exc)
            return self._fail(context, tr("Reproducing {revision} stopped: {error}",
                                          revision=getattr(self, "_label", ""),
                                          error=str(exc)))


# Encargos y decisiones de la propiedad (T24) -------------------------------------------------

_LIST = re.compile(r"[,;]")
"""Lo que separa las claves de parámetro y los códigos de versión de Registrar decisión…"""


class _DayText(ValueError):
    """Un día de la decisión que no es DD/MM/AAAA (ni AAAA-MM-DD, desde un guion)."""


def decision_day(typed: str) -> dt.date | str | None:
    """El día de la decisión tecleado: DD/MM/AAAA (o, desde un guion, AAAA-MM-DD, que comprueba
    ``record_decision``); vacío, ``None`` (``record_decision`` lo pide). :class:`_DayText` si no
    es ninguno de los dos."""
    shown = typed.strip()
    if not shown:
        return None
    try:
        return dt.datetime.strptime(shown, "%d/%m/%Y").date()
    except ValueError:
        pass
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", shown):
        return shown
    raise _DayText(shown)


def listed(typed: str) -> list[str]:
    """Las claves o los códigos de un campo de Registrar decisión…, separados por comas (o por
    punto y coma), sin espacios a los lados y sin los vacíos."""
    return [part.strip() for part in _LIST.split(typed) if part.strip()]


_DOCUMENT_CHOICES: list[tuple[str, str, str]] = []
"""Lo último que dio :func:`document_items` (Blender necesita que Python guarde los textos de un
enumerado dinámico mientras los usa)."""


def document_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Los elementos de «Documento» (``source_input_uid``): «Ninguno» y cada entrada de tipo
    documento que puede citar una decisión, con su nombre (lo ya leído,
    ``bl.ui.version_panels.document_rows``: nada se lee al dibujar)."""
    from ..ui import version_panels  # al usarlo (ARQ-08)

    choices = [(NO_DOCUMENT, tr("None"), "")]
    choices += [(uid, name, "") for uid, name in
                version_panels.document_rows(project_session.current())]
    _DOCUMENT_CHOICES[:] = choices
    return _DOCUMENT_CHOICES


def _fill_decisions(project: Project) -> list[str]:
    """Vuelve a leer las filas de la ventana de las decisiones y de los documentos; devuelve el
    aviso si no se pudo (las de antes siguen)."""
    from ..ui import version_panels  # al usarlo (ARQ-08)

    try:
        version_panels.fill_decisions(project)
    except (GeoblenderError, sqlite3.Error, OSError) as exc:
        LOGGER.warning("No se pudieron leer las decisiones de la propiedad", exc_info=True)
        return [error_text(exc)]
    return []


def recorded_text(decision: Any) -> str:
    """Lo que dice Registrar decisión… al registrarla, en el idioma de Geoblender: «Decisión de la
    propiedad registrada: «K = 1,20» (D. Juan, 03/10/2026)»."""
    return tr("Owner decision recorded: «{what}» ({who}, {date})", what=decision.what,
              who=decision.decided_by, date=decision.day)


class GEOBLENDER_OT_core_show_decisions(bpy.types.Operator):
    """Assignments and decisions of the owner that the design follows"""

    bl_idname = SHOW_DECISIONS
    bl_label = "Assignments and decisions of the owner…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll_project(cls, context)

    def invoke(self, context: bpy.types.Context, event: Any) -> set[str]:
        return self.execute(context)

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Lee las decisiones, los documentos y los encargos y abre la ventana; solo lee:
        también en solo lectura. Desde un guion sin ventana, solo las filas."""
        project = project_session.current()
        if project is None:
            self.report({"ERROR"}, tr("No project is open"))
            return {"CANCELLED"}
        problems = _fill_decisions(project)
        if problems:
            self.report({"ERROR"}, problems[0])
            return {"CANCELLED"}
        if getattr(context, "window", None) is None:
            return {"FINISHED"}  # desde un guion sin ventana: las filas, sin la ventana
        return set(_call_panel(DECISIONS_PANEL))


class GEOBLENDER_OT_core_add_decision(bpy.types.Operator):
    """Record a decision of the owner and the parameters and versions it affects"""

    bl_idname = ADD_DECISION
    bl_label = "Register decision…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Who decides",
        description="Who decides for the owner (a person or a body of the owner)",
        options=_FIELD,
    )
    decided_at: StringProperty(  # type: ignore[valid-type]
        name="Decision date", description="Day of the decision, DD/MM/YYYY",
        options=_FIELD,
    )
    what: StringProperty(  # type: ignore[valid-type]
        name="What is decided", description="What the owner decides (recorded as it is typed)",
        options=_FIELD,
    )
    source_input_uid: EnumProperty(  # type: ignore[valid-type]
        name="Document",
        description="The document of the decision, registered as an input of type document "
                    "(the minutes, the letter, the capture)",
        items=document_items,
        options=_FIELD,
    )
    source_text: StringProperty(  # type: ignore[valid-type]
        name="Reference",
        description="Reference of the decision when there is no registered document (such as "
                    "«email of 03/10/2026»)",
        options=_FIELD,
    )
    parameters: StringProperty(  # type: ignore[valid-type]
        name="Parameters",
        description="Keys of the parameters it affects, separated by commas (in all their "
                    "scopes)",
        options=_FIELD,
    )
    versions: StringProperty(  # type: ignore[valid-type]
        name="Versions",
        description="Codes of the versions it affects, separated by commas",
        options=_FIELD,
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _write_poll(cls)

    def invoke(self, context: bpy.types.Context, event: Any) -> set[str]:
        """Abre el diálogo con el día de hoy y la versión activa (si quien la lanza no dijo
        otra cosa), con los documentos del proyecto leídos ahora; nada cambia hasta aceptarlo."""
        project = project_session.current()
        if project is None:
            self.report({"ERROR"}, tr("No project is open"))
            return {"CANCELLED"}
        _fill_decisions(project)
        given = self.properties.is_property_set
        if not given("decided_at"):
            self.decided_at = project.clock.now().astimezone().strftime("%d/%m/%Y")
        if not given("versions"):
            shown = scene_versions.active()
            self.versions = "" if shown is None else shown.code
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=text(catalog().commands[ADD_DECISION].label))

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "decided_by", text=tr("Who decides"), translate=False)
        layout.prop(self, "decided_at", text=tr("Decision date"), translate=False)
        layout.prop(self, "what", text=tr("What is decided"), translate=False)
        layout.prop(self, "source_input_uid", text=tr("Document"), translate=False)
        layout.prop(self, "source_text", text=tr("Reference"), translate=False)
        layout.prop(self, "parameters", text=tr("Parameters"), translate=False)
        layout.prop(self, "versions", text=tr("Versions"), translate=False)

    def execute(self, context: bpy.types.Context) -> set[str]:
        blocked = write_unavailable()
        project = project_session.current()
        if blocked is not None or project is None:
            self.report({"ERROR"}, blocked or tr("No project is open"))
            return {"CANCELLED"}
        from ...core.versions.decisions import record_decision  # al usarlo (plan §2.1)

        document = self.source_input_uid
        try:
            day = decision_day(self.decided_at)
            with project.write_transaction() as conn:
                decision = record_decision(
                    conn, project, decided_by=self.decided_by, decided_at=day,
                    what=self.what,
                    source_input_uid=None if document in ("", NO_DOCUMENT) else document,
                    source_text=self.source_text, parameters=listed(self.parameters),
                    versions=listed(self.versions))
        except _DayText as exc:
            self.report({"ERROR"}, tr("Decision date «{value}»: write it as DD/MM/YYYY",
                                      value=str(exc)))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        warnings = [*_after_writing(project, header=False), *_fill_decisions(project)]
        from ..ui import provenance as ui  # al usarlo (ARQ-08)

        try:  # su decisor de la propiedad, en Parámetros del proyecto
            ui.fill_parameters()
        except (GeoblenderError, sqlite3.Error, OSError):
            LOGGER.warning("No se pudo volver a leer la lista de parámetros", exc_info=True)
        self.report({"INFO"}, recorded_text(decision))
        for message in warnings:
            self.report({"WARNING"}, message)
        return {"FINISHED"}


# En orden de registro.
classes: tuple[type, ...] = (
    GEOBLENDER_OT_core_set_active_version,
    GEOBLENDER_OT_core_new_version,
    GEOBLENDER_OT_core_set_version_state,
    GEOBLENDER_OT_core_new_revision,
    GEOBLENDER_OT_core_reproduce_version,
    GEOBLENDER_OT_core_show_decisions,
    GEOBLENDER_OT_core_add_decision,
)
