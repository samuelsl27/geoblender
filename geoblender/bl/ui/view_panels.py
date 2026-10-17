# SPDX-License-Identifier: GPL-3.0-or-later
"""Los paneles de la vista regenerable en N ▸ Proyecto (spec 010; HU-010-3; plan 010 §5.3.3,
§5.5).

**Elemento activo** (:class:`GEOBLENDER_PT_core_active_item`; T14, RF-010-06; plan A6, D-16):
mientras el objeto activo es la vista de un dato del proyecto abierto, su ficha leída del
proyecto (``core.views.card.item_card``, en una instantánea y sin escribir nada): el nombre del
dato, su tipo, su estado (con «obsoleto»), si el objeto está al día en la vista (de
``Object.geoblender.view_state``, que pone la marca en vivo: «al día», «no al día: Refrescar
(F5)» o «sin respaldo en el proyecto»), su versión («—» hasta la spec 009), la operación que
escribió su contenido con su fecha y su versión de Geoblender, ↑ sus entradas con el hash que
consumió abreviado a :data:`HASH_CHARS` caracteres, ↓ sus derivados con «obsoleto» (en alerta) y
las cifras de su operación con su unidad y su insignia de tipo, sin marcas (las marcas leen el
grafo entero), o «Sin cifras registradas»; y Procedencia, la cadena entera en el panel de la 008
(``geoblender.core_show_lineage`` con su dato). Un objeto del usuario, o de otro proyecto, no
tiene ficha; uno cuyo dato ya no está en el proyecto, lo dice.

**Cuándo se lee** (D-16; nunca al dibujar: el panel solo pinta las filas ya leídas de
``WindowManager.geoblender_view_panels``, con ``bl.ui.labels`` para partir los textos al ancho
de la barra lateral): al cambiar el objeto activo (una suscripción de ``bpy.msgbus`` a
``LayerObjects.active``, :func:`on_active_changed`), tras cada lectura del proyecto cambiado de
los indicadores de la procedencia (``bl.ui.provenance.add_change_listener``,
:func:`on_project_read`: también al abrirlo, en su primer tic, y al cambiar el idioma) y tras
cargar un ``.blend`` (:func:`on_load_post`). Blender borra las suscripciones de ``msgbus`` al
cargar un fichero (``docs/trampas.md`` §3): ``load_post`` la renueva. Al cambiar el proyecto de
la sesión (``project_session``), la ficha se olvida: abrirlo no lee nada (RNF-002-02). Mientras
esta sesión escribe en el proyecto (``Project.writing``) o QGIS lo dejó en WAL, no se lee (como
los indicadores): lo hará su siguiente lectura. En solo lectura, igual: solo lee.
``core.views.card`` se importa al usarlo: registrar no carga ``core.provenance.importer`` (spec
008, T65).

:func:`register` suscribe y apunta el manejador ``@persistent`` y las escuchas; :func:`unregister`
lo quita todo. El panel (con la pestaña y el título traducidos por :func:`localize` antes de
registrar, y registrado otra vez al cambiar el idioma, ``bl.ui.i18n``) va tras el panel Proyecto
(``bl_order``).
"""

from __future__ import annotations

import logging
import sqlite3
import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy
from bpy.app.handlers import persistent

from ...core.errors import GeoblenderError
from ...core.gpkg.header import read_header
from ...core.i18n import language, tr, translate
from ...core.provenance import contract
from ...core.provenance.messages import render
from ...core.timeutil import parse_utc
from ..props.core import OBJECT_PROPERTY
from ..props.views import WINDOW_MANAGER_PROPERTY
from ..scene import project_session, views
from . import core_panel, labels, provenance

if TYPE_CHECKING:
    from ...core.project.session import Project
    from ...core.views.card import ItemCard, Link

LOGGER = logging.getLogger("geoblender.bl.ui")

TRANSLATION_CONTEXT = "Geoblender"
ACTIVE_ITEM_PANEL = "GEOBLENDER_PT_core_active_item"
ACTIVE_ITEM_LABEL = "Active item"  # msgid del título
ACTIVE_ITEM_ORDER = 1
"""El orden del panel en la pestaña: tras el panel Proyecto (el de por defecto, 0)."""
SHOW_LINEAGE = "geoblender.core_show_lineage"
HASH_CHARS = provenance.HASH_CHARS
NO_VALUE = "—"
DATE_PATTERN = "%d/%m/%Y %H:%M"

# Cómo se dibuja cada fila de la ficha (GEOBLENDER_PG_core_card_row.kind).
ROW_NAME = "name"  # el nombre del dato, con el icono de su tipo
ROW_FIELD = "field"  # un dato de la ficha («Tipo: …»)
ROW_VIEW = "view"  # «al día»: se dibuja con el view_state del objeto activo
ROW_HEADING = "heading"  # el título de un apartado (↑ entradas, ↓ derivados, cifras)
ROW_ITEM = "item"  # una entrada o un derivado
ROW_FIGURE = "figure"  # una cifra con su insignia
ROW_NONE = "none"  # un apartado vacío («Ninguna entrada»)

# El icono del tipo de un dato (core.datasets.DATASET_KINDS); otro, el de un fichero.
KIND_ICONS: dict[str, str] = {
    "raster": "IMAGE_DATA",
    "mesh": "MESH_DATA",
    "vector": "CURVE_DATA",
    "table": "SPREADSHEET",
    "drillholes": "MESH_CYLINDER",
    "point_cloud": "POINTCLOUD_DATA",
    "block_model": "MESH_CUBE",
}
OTHER_ICON = "FILE"
INPUT_ICON = "IMPORT"  # una entrada registrada
DATASET_ICON = "OBJECT_DATA"  # un dato de las entradas o los derivados

# El estado de un dato (gb_dataset.status) como en su nombre generado («VIGENTE»).
STATUS_MSGIDS: dict[str, str] = {
    "current": "CURRENT",
    "missing": "MISSING",
    "blocked": "BLOCKED",
    "damaged": "DAMAGED",
    "superseded": "SUPERSEDED",
    "discarded": "DISCARDED",
}
STALE_MSGID = "STALE"


@dataclass(frozen=True)
class CardLine:
    """Una línea de la ficha antes de ponerla en ``WindowManager.geoblender_view_panels``
    (:class:`~..props.views.GEOBLENDER_PG_core_card_row`)."""

    kind: str
    text: str = ""
    icon: str = ""
    alert: bool = False
    uid: str = ""


class _Token:
    """Lo que lleva consigo la suscripción de ``msgbus``: vive mientras Blender la guarda."""


class _State:
    """Lo de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.owner = object()  # dueño de la suscripción de msgbus
        self.token: weakref.ref[_Token] | None = None


_STATE = _State()


# Las filas ------------------------------------------------------------------------------------


def _local(moment: str | None) -> str:
    """Una hora UTC guardada, en hora local como la lee una persona; sin ella, nada."""
    if not moment:
        return ""
    try:
        return parse_utc(moment).astimezone().strftime(DATE_PATTERN)
    except ValueError:
        return moment


def status_text(status: str) -> str:
    """El estado de un dato como en su nombre generado («VIGENTE», «FALTA»…), en el idioma de
    Geoblender."""
    msgid = STATUS_MSGIDS.get(str(status))
    return translate(language(), msgid) if msgid else str(status)


def _link_status(link: Link) -> str:
    """El estado de hoy de una entrada («vigente», «cambiada»…) o de un dato («vigente»,
    «falta»…), y «obsoleto» si lo está."""
    from ...core.views import card  # al usarlo: registrar no lo carga

    if not link.status:
        word = ""
    elif link.kind == card.INPUT:
        try:
            word = render(f"core.input_status_{link.status}", language=language())
        except ValueError:
            word = link.status
    else:
        word = status_text(link.status).lower()
    if link.stale:
        word = " · ".join(part for part in (word, translate(language(), STALE_MSGID).lower())
                          if part)
    return word


def link_text(link: Link, *, with_hash: bool) -> str:
    """Una entrada o un derivado de la ficha: su nombre (con su papel, salvo el de lo importado),
    su estado de hoy y, con ``with_hash``, el hash que consumió la operación, abreviado
    («MDT norte · vigente · 3f2a1b4c5d6e»)."""
    from ...core.views import card  # al usarlo: registrar no lo carga

    name = link.name if not link.role or link.role == card.IMPORTED_ROLE else (
        f"{link.name} ({link.role})")
    parts = [name, _link_status(link)]
    if with_hash and link.content_sha256:
        parts.append(link.content_sha256[:HASH_CHARS])
    return " · ".join(part for part in parts if part)


def operation_text(found: ItemCard) -> str:
    """La operación que escribió el contenido del dato: su nombre, su tipo con la versión de su
    algoritmo, cuándo terminó y la versión de Geoblender; sin ella, «—»."""
    operation = found.operation
    if operation is None:
        return NO_VALUE
    definition = contract.OPERATIONS.get(operation.op_type)
    label = translate(language(), definition.label_msgid) if definition is not None and \
        definition.label_msgid else ""
    parts = (label, f"{operation.op_type} {operation.op_version}",
             _local(operation.finished_at), f"Geoblender {operation.geoblender_version}")
    return " · ".join(part for part in parts if part)


def card_lines(found: ItemCard) -> list[CardLine]:
    """Las líneas de la ficha de ``found`` (``core.views.card.ItemCard``), en el idioma de
    Geoblender (véase el módulo)."""
    from ...core.views import card  # al usarlo: registrar no lo carga

    record = found.record
    loader = views.loader_for(record.name)
    kind = [translate(language(), loader.label)] if loader is not None else []
    kind += [provenance.kind_text(record.kind), record.module]
    status = status_text(record.status)
    if found.stale:
        status = f"{status} · {translate(language(), STALE_MSGID)}"
    lines = [
        CardLine(ROW_NAME, record.name, KIND_ICONS.get(record.kind, OTHER_ICON), uid=record.uid),
        CardLine(ROW_FIELD, tr("Type: {kind}", kind=" · ".join(part for part in kind if part))),
        CardLine(ROW_FIELD, tr("Status: {status}", status=status),
                 alert=found.stale or not record.live),
        CardLine(ROW_VIEW),
        CardLine(ROW_FIELD, tr("Version: {version}", version=found.version or NO_VALUE)),
        CardLine(ROW_FIELD, tr("Operation: {operation}", operation=operation_text(found))),
        CardLine(ROW_HEADING, tr("↑ Inputs")),
    ]
    lines += [CardLine(ROW_ITEM, link_text(link, with_hash=True),
                       INPUT_ICON if link.kind == card.INPUT else DATASET_ICON,
                       alert=link.stale, uid=link.uid) for link in found.upstream] or [
        CardLine(ROW_NONE, tr("No inputs"))]
    lines.append(CardLine(ROW_HEADING, tr("↓ Derived data")))
    lines += [CardLine(ROW_ITEM, link_text(link, with_hash=False), DATASET_ICON,
                       alert=link.stale, uid=link.uid) for link in found.downstream] or [
        CardLine(ROW_NONE, tr("No derived data"))]
    lines.append(CardLine(ROW_HEADING, tr("Figures")))
    lines += [CardLine(ROW_FIGURE,
                       f"{provenance.badge(figure.kind)} {figure.text(language=language())}",
                       uid=figure.uid) for figure in found.figures] or [
        CardLine(ROW_NONE, tr("No figures recorded"))]
    return lines


# La lectura -----------------------------------------------------------------------------------


def _view(context: Any) -> Any:
    return getattr(getattr(context, "window_manager", None), WINDOW_MANAGER_PROPERTY, None)


def _active_object(context: Any) -> Any:
    """El objeto activo de la capa de ``context`` (sin ella, la de la primera ventana)."""
    layer = getattr(context, "view_layer", None)
    if layer is None:
        windows = getattr(getattr(context, "window_manager", None), "windows", None) or ()
        layer = windows[0].view_layer if len(windows) else None
    return getattr(getattr(layer, "objects", None), "active", None)


def shown_by(obj: Any) -> tuple[str, str]:
    """El uid del dato que muestra ``obj`` y el de su proyecto (vacíos: no muestra ninguno)."""
    props = getattr(obj, OBJECT_PROPERTY, None)
    if props is None:
        return "", ""
    return str(props.dataset_uid), str(props.project_uid)


def _in_wal(project: Project) -> bool:
    """Si QGIS dejó el proyecto en WAL (leerlo haría una copia privada); si no se puede leer
    su cabecera, lo dirá la lectura."""
    try:
        return read_header(project.database_path).needs_recovery
    except GeoblenderError:
        return False


def _clear(view: Any) -> bool:
    """Olvida la ficha; dice si había una."""
    had = bool(view.card_uid) or len(view.card) > 0
    if had:
        view.card.clear()
        view.card_uid = ""
        view.card_project = ""
        view.card_found = False
    return had


def _fill(view: Any, project_uid: str, uid: str, found: ItemCard | None) -> None:
    """Pone la ficha leída del dato ``uid`` (``None``: el proyecto ya no lo tiene)."""
    view.card.clear()
    view.card_uid = uid
    view.card_project = project_uid
    view.card_found = found is not None
    for line in card_lines(found) if found is not None else ():
        row = view.card.add()
        row.kind = line.kind
        row.text = line.text
        row.icon = line.icon
        row.alert = line.alert
        row.uid = line.uid


def read_card(context: Any = None) -> bool:
    """Lee del proyecto de la sesión la ficha del objeto activo de ``context`` (por defecto,
    ``bpy.context``) y la pone en ``WindowManager.geoblender_view_panels``; sin proyecto, o si
    el objeto no muestra un dato suyo, la olvida. No escribe en el proyecto; mientras esta sesión
    escribe en él o está en WAL, no lo lee (lo hará la siguiente lectura de los indicadores).
    Devuelve si hay ficha. Si no se puede leer, la olvida y lo anota en el registro técnico."""
    context = bpy.context if context is None else context
    view = _view(context)
    if view is None:
        return False
    project = project_session.current()
    uid, owner = shown_by(_active_object(context))
    if project is None or not uid or owner != project.uid:
        changed = _clear(view)
    elif getattr(project, "writing", False) or _in_wal(project):
        return False
    else:
        # Al usarlo: registrar no carga core.provenance.importer (spec 008, T65).
        from ...core.views import card

        try:
            found = card.item_card(project, uid)
        except (GeoblenderError, sqlite3.Error, OSError):
            LOGGER.info("No se pudo leer del proyecto la ficha del objeto activo",
                        exc_info=True)
            changed = _clear(view)
        else:
            _fill(view, project.uid, uid, found)
            changed = True
    if changed:
        _redraw()
    return bool(view.card_uid) and bool(view.card_found)


def _read_safely() -> None:
    try:
        read_card()
    except Exception:  # noqa: BLE001 - lo que llama Blender no lo tumba
        LOGGER.exception("Falló la lectura de la ficha del objeto activo")


def _redraw() -> None:
    """Redibuja las vistas 3D (su barra lateral)."""
    manager = getattr(bpy.context, "window_manager", None)
    for window in list(getattr(manager, "windows", ()) or ()):
        for area in getattr(getattr(window, "screen", None), "areas", ()) or ():
            if area.type == "VIEW_3D":
                area.tag_redraw()


# Las escuchas ---------------------------------------------------------------------------------


def on_active_changed(*_args: Any) -> None:
    """Lo que avisa ``bpy.msgbus`` al cambiar el objeto activo: lee su ficha."""
    _read_safely()


def on_project_read(_project: Project) -> None:
    """Lo que se apunta en los indicadores de la procedencia (se llama tras cada lectura del
    proyecto cambiado, ``bl.ui.provenance.add_change_listener``): vuelve a leer la ficha."""
    _read_safely()


def on_project_changed(_project: Project | None) -> None:
    """Lo que se apunta en ``project_session``: olvida la ficha del proyecto anterior (con uno
    nuevo, la lee el primer tic de sus indicadores: al abrir no se lee nada, RNF-002-02)."""
    view = _view(bpy.context)
    if view is not None and _clear(view):
        _redraw()


def _subscribe() -> None:
    """Se suscribe al objeto activo de las capas (una sola suscripción, la de ahora)."""
    bpy.msgbus.clear_by_owner(_STATE.owner)
    token = _Token()
    bpy.msgbus.subscribe_rna(key=(bpy.types.LayerObjects, "active"), owner=_STATE.owner,
                             args=(token,), notify=on_active_changed)
    _STATE.token = weakref.ref(token)


def is_subscribed() -> bool:
    """Si Blender guarda la suscripción de la ficha al objeto activo (lo que lleva consigo
    sigue vivo: Blender la suelta al cargar un fichero o al quitarla)."""
    return _STATE.token is not None and _STATE.token() is not None


@persistent
def on_load_post(*_args: Any) -> None:
    """Tras cargar un ``.blend``: Blender ha borrado las suscripciones de ``msgbus``; se renueva
    la de la ficha y se lee la del objeto activo del fichero."""
    try:
        _subscribe()
    except Exception:  # noqa: BLE001 - un manejador que falla no tumba Blender
        LOGGER.exception("No se pudo renovar la suscripción de la ficha al objeto activo")
    _read_safely()


# El panel -------------------------------------------------------------------------------------


def _draw_lines(layout: Any, text: str, width: float, *, icon: str = "NONE",
                alert: bool = False) -> None:
    """``text`` en las líneas que caben en ``width`` (``bl.ui.labels.wrapped``), en una columna
    (en alerta, si ``alert``), la primera con ``icon`` y las demás con su hueco."""
    with_icon = icon not in ("", "NONE")
    column = layout.column(align=True)
    column.alert = alert
    for index, line in enumerate(labels.wrapped(text, width, icon=with_icon)):
        shown = (icon if index == 0 else "BLANK1") if with_icon else "NONE"
        column.label(text=line, icon=shown, translate=False)


def view_text(obj: Any) -> tuple[str, bool]:
    """Si ``obj`` está al día en la vista (``Object.geoblender.view_state``): el texto y si va
    en alerta."""
    state = str(getattr(getattr(obj, OBJECT_PROPERTY, None), "view_state", "CURRENT"))
    if state == views.VIEW_OUTDATED:
        return tr("In the view: not up to date: Refresh (F5)"), True
    if state == views.VIEW_UNBACKED:
        return tr("In the view: unbacked in the project"), True
    return tr("In the view: up to date"), False


def draw_card(layout: Any, context: Any) -> None:
    """El contenido de :class:`GEOBLENDER_PT_core_active_item`: la ficha ya leída del objeto
    activo, o por qué no hay. No lee el proyecto."""
    width = labels.sidebar_width(context)
    view = _view(context)
    project = project_session.current()
    obj = _active_object(context)
    uid, owner = shown_by(obj)
    if view is None or project is None or not uid or owner != project.uid:
        _draw_lines(layout, tr("The active object does not show data of this project"), width,
                    icon="INFO")
        return
    if view.card_uid != uid or view.card_project != owner:
        _draw_lines(layout, tr("Reading the project data of the active object…"), width,
                    icon="TIME")
        return
    if not view.card_found:
        _draw_lines(layout, tr("The project no longer has the data of this object"), width,
                    icon="ERROR", alert=True)
        return
    for row in view.card:
        if row.kind == ROW_VIEW:
            text, alert = view_text(obj)
            _draw_lines(layout, text, width, alert=alert)
            continue
        if row.kind == ROW_HEADING:
            layout.separator()
        sub = layout.column(align=True)
        sub.active = row.kind != ROW_NONE
        _draw_lines(sub, row.text, width, icon=row.icon or "NONE", alert=row.alert)
    layout.separator()
    button = layout.operator(SHOW_LINEAGE, text=tr("Provenance"), icon="NODETREE",
                             translate=False)
    button.item_uid = uid


class GEOBLENDER_PT_core_active_item(bpy.types.Panel):
    """The project data shown by the active object: what it is, where it comes from and what
    depends on it"""

    bl_idname = ACTIVE_ITEM_PANEL
    bl_label = ACTIVE_ITEM_LABEL
    bl_category = core_panel.PANEL_LABEL
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_order = ACTIVE_ITEM_ORDER

    @classmethod
    def poll(cls, _context: Any) -> bool:
        return project_session.current() is not None

    def draw(self, context: Any) -> None:
        draw_card(self.layout, context)


def localize() -> None:
    """La pestaña y el título en el idioma de la interfaz (antes de registrar)."""
    GEOBLENDER_PT_core_active_item.bl_category = tr("Project")
    GEOBLENDER_PT_core_active_item.bl_label = tr("Active item")


# En orden de registro (tras los de core_panel: la pestaña «Proyecto»).
classes: tuple[type, ...] = (GEOBLENDER_PT_core_active_item,)


def register() -> None:
    """Se suscribe al objeto activo y apunta el manejador de ``load_post`` y las escuchas del
    proyecto de la sesión y de los indicadores; idempotente."""
    _subscribe()
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)
    project_session.add_listener(on_project_changed)
    provenance.add_change_listener(on_project_read)


def unregister() -> None:
    """Quita las escuchas, el manejador (todas sus apariciones) y la suscripción, y olvida la
    ficha; idempotente."""
    provenance.remove_change_listener(on_project_read)
    project_session.remove_listener(on_project_changed)
    while on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    bpy.msgbus.clear_by_owner(_STATE.owner)
    _STATE.token = None
    view = _view(bpy.context)
    if view is not None:
        _clear(view)
