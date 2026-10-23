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

**Inventario** (:class:`GEOBLENDER_PT_core_project_inventory` con la lista
:class:`GEOBLENDER_UL_core_project_inventory`; T15, RF-010-07; plan A7, D-15), en el modo
Geoblender y cerrado al empezar: lo registrado en el proyecto, cargado o no en la vista
(entradas y datos en todos sus estados, ``core.views.inventory``), con su tipo, su estado, su
versión («—» hasta la spec 009), si está en la escena y sus marcas (obsoleto, entrada cambiada),
filtrable por tipo, estado, versión, presencia en la escena y texto, con como mucho 500 filas
(«… y 19 600 más: afine el filtro», D-7), y, de la fila elegida, sus datos y las órdenes Cargar
en la vista (``geoblender.core_load_into_view`` con su dato), Descargar
(``geoblender.core_unload_from_view``) y Procedencia (la de la 008), desactivadas con el motivo
si no se puede (una entrada no se carga ni tiene procedencia; lo sustituido, lo descartado, lo
que falta o lo que ningún módulo carga, no se carga; lo que no está en la escena, no se
descarga).

**Cuándo se lee** (A7): la lectura entera (``read_inventory``, 22–30 ms con 20 000 datos) se
guarda con el contador de cambios de la cabecera de ``project.gpkg``, y cada filtro filtra lo
leído (``page``), sin leer el proyecto. Lo que enseña se hace viejo con cada petición de la
marca en vivo (``bl.scene.live.view_generation``: el proyecto cambió, se cargó o descargó algo,
se deshizo…), pero no se lee nada hasta que el panel se dibuja: entonces pide un temporizador
de un disparo (:func:`inventory_tick`) que vuelve a leer si cambió el contador (si no, solo
vuelve a filtrar con lo que está ahora en la escena, ``views.loaded_items``). Así no se lee si
el panel no está a la vista. Mientras esta sesión escribe o el proyecto está en WAL, espera. En
solo lectura, igual. Cargar o descargar algo de la vista, desde el inventario, un menú o un
guion (``bl.scene.views.add_view_listener``, :func:`on_view_changed`; T21), pone al día ya la
columna «En la escena» y lo de la fila elegida, volviendo a filtrar lo leído, sin leer el
proyecto: la presencia en la escena es de la escena. La lectura se guarda como tuplas de textos
y booleanos (el GC no las sigue, ``docs/trampas.md`` §2); las filas, con los valores del
proyecto, que el dibujo presenta. ``core.views.inventory`` se importa al usarlo, como
``core.views.card``.

**Cifras de la selección** (la ventana emergente :class:`GEOBLENDER_PT_core_selection_figures`;
T16, RF-010-08; plan A8, D-17), que abre la orden ``geoblender.core_show_selection_figures``
(control 29, ``bl.ops.views``) tras leer con :func:`fill_selection_figures`: de los datos de
este proyecto que muestran los objetos seleccionados (sin repetir, por nombre), las cifras
registradas, leídas del proyecto con sus marcas (``core.views.card.dataset_figures``), cada una
con su insignia de tipo, su nombre y su valor con su unidad, y sus marcas de hoy en alerta
(«depende de una hipótesis», «obsoleta»…), o «Sin cifras registradas» (con el porqué si ninguno
tiene: hasta que la cubicación, R-38, registre las primeras). **No mide nada**: ni áreas ni
volúmenes de la geometría; y las cifras que anota cada objeto (``Object.geoblender.figures``,
solo para mostrarlas) no son su fuente.

**Con las versiones** (spec 009, T25; RF-009-20, RF-009-30, RF-009-09; plan 009 A11 y D-9):

- el **inventario** tiene una fila por versión («V01 · Definitiva», con el icono de su estado,
  ``bl.ui.version_panels.state_icon``, y su estado, «VIGENTE»…) y por revisión («V01.r2», con su
  estado: «en curso», la abierta, «congelada» o «cerrada», y la marca «alterada» en alerta), y
  cada dato con el código de su versión; el filtro de versión es un enumerado dinámico
  (:func:`version_filter_items`) con «Todas», «Sin versión» y las versiones de lo ya leído (nada
  se lee para él); al cambiar el proyecto de la sesión, vuelve a «Todas». Una versión o una
  revisión no se carga en la vista ni tiene procedencia: la tienen sus datos;
- la **ficha** de un dato de versión dice su versión con sus revisiones («V01 · Definitiva — en
  curso (r2) · vigente: r1», ``core.views.card.RevisionMark``; con «(alterada)» en alerta), las
  cifras de su operación como las «en curso» de la revisión abierta («Cifras en curso (r2)»,
  RF-009-20) y, aparte, las vigentes de su versión, las de su última revisión congelada (D-9:
  «Cifras vigentes de V01.r1»; de una versión SUPERADO o DESCARTADO, «Cifras congeladas de
  V01.r1»; sin ninguna congelada, «Aún no hay ninguna revisión congelada de V02»). Un dato del
  proyecto, como en la 010;
- **el estado que tenía al congelarse** lo de una revisión congelada (T37; RF-009-19, D-23; plan
  A4 (1); ``core.versions.model.ItemState.text``), en alerta si no estaba al día: bajo cada
  cifra vigente o congelada de la ficha («obsoleta al congelarse, aceptada», «a revisar a mano
  al congelarse», «no reproducible»), y en el estado de un dato que es de esa revisión y no lo
  «en curso» de una abierta (de una versión SUPERADO o DESCARTADO, con el contenido congelado):
  «Estado: VIGENTE · OBSOLETO AL CONGELARSE, ACEPTADO», en la ficha y en lo de su fila elegida
  del inventario, y en su fila, la marca :data:`FROZEN_STATE_ICON`. Lo «en curso» lleva el
  estado de hoy.

:func:`register` suscribe y apunta el manejador ``@persistent`` y las escuchas (también la de lo
cargado y descargado de la vista); :func:`unregister` lo quita todo (también el temporizador del
inventario). Los paneles (con la pestaña y el título traducidos por :func:`localize` antes de
registrar, y registrados otra vez al cambiar el idioma, ``bl.ui.i18n``) van tras el panel
Proyecto (``bl_order``): Elemento activo y, después, Inventario; la ventana de las cifras no
tiene pestaña.
"""

from __future__ import annotations

import logging
import sqlite3
import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy
from bpy.app.handlers import persistent

from ...core.datasets.model import DatasetStatus
from ...core.errors import GeoblenderError
from ...core.gpkg.header import read_header
from ...core.i18n import format_number, language, tr, translate
from ...core.provenance import contract
from ...core.provenance.messages import render
from ...core.timeutil import parse_utc
from ...core.versions.model import (
    EDITABLE,
    ItemState,
    RevisionState,
    VersionStatus,
    revision_label,
)
from .. import compat
from ..props.core import OBJECT_PROPERTY
from ..props.views import INVENTORY_INPUT, INVENTORY_VERSION_ALL, WINDOW_MANAGER_PROPERTY
from ..scene import live, project_session, views
from . import core_panel, gate, labels, provenance, version_panels

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ...core.project.session import Project
    from ...core.provenance.figures import FigureRecord
    from ...core.views.card import DatasetFigures, ItemCard, Link, RevisionMark
    from ...core.views.inventory import InventoryFilter, InventorySnapshot

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
ROW_MARKS = "marks"  # las marcas de una cifra (Cifras de la selección, en alerta)
ROW_NOTE = "note"  # un aviso de la ventana de Cifras de la selección

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

# El inventario (T15).
INVENTORY_PANEL = "GEOBLENDER_PT_core_project_inventory"
INVENTORY_LIST = "GEOBLENDER_UL_core_project_inventory"
INVENTORY_LABEL = "Inventory"  # msgid del título
INVENTORY_ORDER = 2
"""El orden del panel en la pestaña: tras Elemento activo."""
INVENTORY_ROWS = 6
"""Las filas que se ven de la lista (se puede agrandar)."""
INVENTORY_NAME_FACTOR = 0.6
"""Lo que ocupa el nombre en una fila de la lista (Blender lo acorta si no cabe; entero, en lo
de la fila elegida)."""
INVENTORY_RETRY_S = 0.5
"""La espera del temporizador mientras el proyecto no se puede leer sin coste (esta sesión
escribe, o en WAL): la de la marca en vivo."""
LOAD_INTO_VIEW = "geoblender.core_load_into_view"
UNLOAD_FROM_VIEW = "geoblender.core_unload_from_view"
INPUT_CATEGORY = INVENTORY_INPUT  # core.views.inventory.Category.INPUT
DATASET_CATEGORY = "DATASET"  # core.views.inventory.Category.DATASET
INPUT_CHANGED_MSGID = "INPUT CHANGED"
IN_SCENE_ICON = "HIDE_OFF"
STALE_ICON = "ERROR"
INPUT_CHANGED_ICON = "FILE_REFRESH"
LOAD_ICON = "ADD"
UNLOAD_ICON = "REMOVE"
_HISTORY = frozenset({str(DatasetStatus.SUPERSEDED), str(DatasetStatus.DISCARDED)})
_MISSING = str(DatasetStatus.MISSING)

# Las versiones en el inventario (spec 009, T25).
VERSION_CATEGORY = "VERSION"  # core.views.inventory.Category.VERSION
REVISION_CATEGORY = "REVISION"  # core.views.inventory.Category.REVISION
_NUMBERED = frozenset({VERSION_CATEGORY, REVISION_CATEGORY})
VERSION_NONE = "NONE"  # core.views.inventory.VERSION_NONE: lo que no tiene versión («—»)
REVISION_ICONS: dict[str, str] = {
    str(RevisionState.OPEN): "TIME",
    str(RevisionState.FROZEN): "FREEZE",
    str(RevisionState.CLOSED): "LOCKED",
}
"""El icono de una revisión por su estado: la abierta (en curso), la congelada y la cerrada."""
ALTERED_ICON = version_panels.ALTERED_ICON
ALTERED_MSGID = "ALTERED"
FROZEN_STATE_ICON = "FREEZE"
"""La marca de la fila de un dato que no estaba al día al congelarse (T37, RF-009-19)."""
FIRST_VERSION_ITEM = 1
"""El número del filtro de versión de V01 es su número más este (0 es «Todas», 1 «Sin
versión»): lo elegido sigue siendo la misma versión aunque se lean otras."""
_UNNUMBERED_ITEMS = 1_000_000
"""El número del filtro de una versión cuyo código no lleva número (no debería pasar)."""
_VERSION_CHOICES: list[tuple[str, str, str, int]] = []
"""Los elementos del filtro de versión (Blender necesita que Python guarde sus textos)."""

# Cifras de la selección (T16).
SELECTION_FIGURES_PANEL = "GEOBLENDER_PT_core_selection_figures"
SELECTION_FIGURES_LABEL = "Selection figures"  # msgid del título
SELECTION_FIGURES_UNITS = 28
"""El ancho de la ventana, en unidades de interfaz (560 px a escala 1,0)."""
SELECTION_FIGURES_WIDTH_PX = SELECTION_FIGURES_UNITS * compat.UI_UNIT_PX


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


class _Inventory:
    """La última lectura del inventario (no se guarda en el ``.blend``): la instantánea (tuplas
    de textos y booleanos), de qué proyecto y con qué :func:`~..scene.live.view_generation` se
    filtró por última vez."""

    def __init__(self) -> None:
        self.snapshot: InventorySnapshot | None = None
        self.project: Project | None = None
        self.generation = -1

    def forget(self) -> None:
        self.snapshot = None
        self.project = None
        self.generation = -1


_INVENTORY = _Inventory()


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


def frozen_state_text(state: str | None, *, figure: bool = False) -> str:
    """El estado que tenía al congelarse lo de una revisión congelada (T37, RF-009-19;
    ``core.versions.model.ItemState``), en el idioma de Geoblender: el de un dato, «OBSOLETO AL
    CONGELARSE, ACEPTADO»…; con ``figure``, el de una cifra, «obsoleta al congelarse,
    aceptada»…; al día o sin él, «»; uno que no se conoce, tal como está."""
    if not state:
        return ""
    try:
        return ItemState(str(state)).text(language(), figure=figure)
    except ValueError:
        return str(state)


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


def _figure_line(figure: FigureRecord, *, alert: bool = False) -> CardLine:
    """Una cifra de la ficha: su insignia de tipo, su nombre y su valor con su unidad."""
    return CardLine(ROW_FIGURE, f"{provenance.badge(figure.kind)} "
                                f"{figure.text(language=language())}",
                    alert=alert, uid=figure.uid)


def figures_heading(mark: RevisionMark | None) -> str:
    """El título de las cifras de la operación del dato: de un dato de versión vivo, las «en
    curso» de su revisión abierta («Cifras en curso (r2)», RF-009-20); si no, «Cifras»."""
    if mark is None or mark.in_progress is None:
        return tr("Figures")
    return tr("Figures in progress ({revision})", revision=f"r{mark.in_progress}")


def frozen_figure_lines(mark: RevisionMark, figures: Sequence[FigureRecord],
                        states: Mapping[str, str] | None = None) -> list[CardLine]:
    """Las cifras vigentes de la versión de un dato (D-9; spec 009, T25): las de su última
    revisión congelada, «Cifras vigentes de V01.r1» (de una versión SUPERADO o DESCARTADO,
    «Cifras congeladas de V01.r1»), en alerta si está alterada, cada una con el estado que
    tenía al congelarse debajo si no estaba al día (``states``, por uid; «obsoleta al
    congelarse, aceptada», en alerta; T37, RF-009-19); sin ninguna congelada, «Aún no hay
    ninguna revisión congelada de V02»."""
    if mark.current is None:
        return [CardLine(ROW_HEADING, tr("Current figures of {revision}", revision=mark.code)),
                CardLine(ROW_NONE, tr("No revision of {version} has been frozen yet",
                                      version=mark.code))]
    label = revision_label(mark.code, mark.current)
    heading = (tr("Current figures of {revision}", revision=label) if mark.status in EDITABLE
               else tr("Frozen figures of {revision}", revision=label))
    altered = mark.current_altered
    lines = [CardLine(ROW_HEADING, heading, alert=altered)]
    for figure in figures:
        lines.append(_figure_line(figure, alert=altered))
        state = frozen_state_text((states or {}).get(figure.uid), figure=True)
        if state:
            lines.append(CardLine(ROW_MARKS, state, alert=True, uid=figure.uid))
    if not figures:
        lines.append(CardLine(ROW_NONE, tr("No figures recorded")))
    return lines


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
    # De una revisión congelada, no lo «en curso»: el estado que tenía al congelarse (T37).
    frozen = frozen_state_text(found.frozen_state)
    if frozen:
        status = f"{status} · {frozen}"
    mark = found.revision  # de un dato de versión: su versión y sus revisiones (spec 009)
    version = (found.version or NO_VALUE) if mark is None else mark.heading(language())
    lines = [
        CardLine(ROW_NAME, record.name, KIND_ICONS.get(record.kind, OTHER_ICON), uid=record.uid),
        CardLine(ROW_FIELD, tr("Type: {kind}", kind=" · ".join(part for part in kind if part))),
        CardLine(ROW_FIELD, tr("Status: {status}", status=status),
                 alert=found.stale or bool(frozen) or not record.live),
        CardLine(ROW_VIEW),
        CardLine(ROW_FIELD, tr("Version: {version}", version=version),
                 alert=mark is not None and mark.current_altered),
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
    lines.append(CardLine(ROW_HEADING, figures_heading(mark)))
    lines += [_figure_line(figure) for figure in found.figures] or [
        CardLine(ROW_NONE, tr("No figures recorded"))]
    if mark is not None:
        lines += frozen_figure_lines(mark, found.frozen_figures, found.frozen_figure_states)
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


def _put_lines(rows: Any, lines: Sequence[CardLine]) -> None:
    """Las líneas ``lines`` en las filas ``rows`` (``GEOBLENDER_PG_core_card_row``), en lugar de
    las que hubiera."""
    rows.clear()
    for line in lines:
        row = rows.add()
        row.kind = line.kind
        row.text = line.text
        row.icon = line.icon
        row.alert = line.alert
        row.uid = line.uid


def _fill(view: Any, project_uid: str, uid: str, found: ItemCard | None) -> None:
    """Pone la ficha leída del dato ``uid`` (``None``: el proyecto ya no lo tiene)."""
    view.card_uid = uid
    view.card_project = project_uid
    view.card_found = found is not None
    _put_lines(view.card, card_lines(found) if found is not None else ())


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
    """Lo que se apunta en ``project_session``: olvida la ficha y el inventario del proyecto
    anterior y su filtro de versión vuelve a «Todas» (con uno nuevo, la ficha la lee el primer
    tic de sus indicadores y el inventario, el primer dibujo de su panel: al abrir no se lee
    nada, RNF-002-02)."""
    view = _view(bpy.context)
    forgot = _forget_inventory(view)
    _all_versions(view)
    if (view is not None and _clear(view)) or forgot:
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
                alert: bool = False, icon_value: int = 0) -> None:
    """``text`` en las líneas que caben en ``width`` (``bl.ui.labels.wrapped``), en una columna
    (en alerta, si ``alert``), la primera con ``icon`` (o con el icono propio ``icon_value``) y
    las demás con su hueco."""
    with_icon = bool(icon_value) or icon not in ("", "NONE")
    column = layout.column(align=True)
    column.alert = alert
    for index, line in enumerate(labels.wrapped(text, width, icon=with_icon)):
        if index == 0 and icon_value:
            column.label(text=line, icon_value=icon_value, translate=False)
            continue
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


# El inventario (T15) --------------------------------------------------------------------------


def _forget_inventory(view: Any) -> bool:
    """Olvida la lectura del inventario, retira su temporizador y vacía sus filas (con
    ``view``); dice si había filas."""
    _INVENTORY.forget()
    if bpy.app.timers.is_registered(inventory_tick):
        bpy.app.timers.unregister(inventory_tick)
    if view is None:
        return False
    had = bool(view.inventory_project) or len(view.inventory) > 0
    if had:
        view.inventory.clear()
        view.inventory_index = 0
        view.inventory_project = ""
        view.inventory_total = 0
        view.inventory_more = 0
    return had


def _version_number(code: str | None, position: int) -> int:
    """El número del elemento de la versión ``code`` en el filtro de versión: el de su código
    (V01 → 1) más :data:`FIRST_VERSION_ITEM`."""
    digits = (code or "")[1:]
    if digits.isdigit():
        return int(digits) + FIRST_VERSION_ITEM
    return _UNNUMBERED_ITEMS + position


def version_filter_items(_view: Any, _context: Any) -> list[tuple[str, str, str, int]]:
    """Los elementos del filtro de versión del inventario (``inventory_version``, un enumerado
    dinámico; spec 009, T25): «Todas», «Sin versión» y cada versión del inventario ya leído del
    proyecto de la sesión, por su número («V01 · Definitiva», con su uid). No lee el proyecto:
    sin inventario leído, solo los dos primeros. Cada versión lleva el número de su código
    (:func:`_version_number`), y lo elegido sigue siendo la misma al leer otra vez."""
    choices = [(INVENTORY_VERSION_ALL, tr("All versions"), "", 0),
               (VERSION_NONE, tr("Without version"), "", 1)]
    snapshot = _INVENTORY.snapshot
    project = project_session.current()
    if snapshot is not None and project is not None and _INVENTORY.project is project:
        choices += [(item.uid, item.name, "", _version_number(item.version, position))
                    for position, item in enumerate(snapshot.versions)]
    _VERSION_CHOICES[:] = choices
    return _VERSION_CHOICES


def _all_versions(view: Any) -> None:
    """El filtro de versión, otra vez «Todas» (lo elegido era de otro proyecto), sin leerlo:
    olvidado el inventario, una versión elegida ya no está entre sus elementos y leerlo
    avisaría en la consola."""
    if view is not None:
        view.property_unset("inventory_version")


def inventory_filter(view: Any) -> InventoryFilter:
    """Lo que piden los filtros del panel (``core.views.inventory.InventoryFilter``): el tipo
    «Entradas» es la categoría de las entradas; los demás tipos, los de los datos; la versión,
    su uid («Todas» si lo elegido ya no está entre lo leído)."""
    from ...core.views import inventory  # al usarlo, como card

    kind = str(view.inventory_kind)
    if kind == INPUT_CATEGORY:
        category, kind = INPUT_CATEGORY, inventory.ALL
    else:
        category = inventory.ALL if kind == inventory.ALL else DATASET_CATEGORY
    return inventory.InventoryFilter(category=category, kind=kind,
                                     status=str(view.inventory_status),
                                     version=str(view.inventory_version) or inventory.ALL,
                                     presence=str(view.inventory_presence),
                                     text=str(view.inventory_text))


def _fill_inventory(view: Any, project_uid: str, snapshot: InventorySnapshot) -> None:
    """Filtra ``snapshot`` con los filtros del panel y lo que está ahora en la escena, y pone la
    página en las filas (la elegida sigue elegida si sigue en ella). No lee el proyecto."""
    from ...core.views import inventory  # al usarlo, como card

    in_scene = frozenset(views.loaded_items(project_uid))
    found = inventory.page(snapshot, inventory_filter(view), in_scene)
    rows = view.inventory
    index = view.inventory_index
    chosen = rows[index].uid if 0 <= index < len(rows) else ""
    rows.clear()
    selected = 0
    for position, item in enumerate(found.items):
        row = rows.add()
        row.name = item.name
        row.category = str(item.category)
        row.uid = item.uid
        row.module = item.module
        row.kind = item.kind
        row.status = item.status
        row.version = item.version or ""
        row.in_scene = item.category == DATASET_CATEGORY and item.uid in in_scene
        row.stale = item.stale
        row.input_changed = item.input_changed
        row.loadable = item.loadable
        row.altered = item.altered
        row.in_progress = item.in_progress
        row.frozen_state = item.frozen_state or ""
        if item.uid == chosen:
            selected = position
    view.inventory_index = selected
    view.inventory_project = project_uid
    view.inventory_total = found.total
    view.inventory_more = found.more


def inventory_is_old(project: Project) -> bool:
    """Si lo que enseña el inventario puede ser viejo: no leído aún, de otro proyecto o filtrado
    antes de la última petición de la marca en vivo (el proyecto cambió, se cargó o descargó
    algo…). No lee nada: lo usa el dibujo del panel."""
    return (_INVENTORY.snapshot is None or _INVENTORY.project is not project
            or _INVENTORY.generation != live.view_generation())


def _loadable(name: str) -> bool:
    """Si algún módulo carga el dato ``name`` en la vista (tiene cargador)."""
    return views.loader_for(name) is not None


def refresh_inventory(context: Any = None) -> float | None:
    """La lectura del inventario del proyecto de la sesión (lo que hace :func:`inventory_tick`):
    si cambió el contador de cambios de la cabecera desde la última lectura (u otro proyecto),
    lo lee entero (``core.views.inventory.read_inventory``, en una instantánea y sin escribir
    nada); después, lo filtra con los filtros del panel y lo que está ahora en la escena y llena
    las filas. Mientras esta sesión escribe o el proyecto está en WAL, no lee: devuelve la
    espera (:data:`INVENTORY_RETRY_S`); si no, ``None``. Sin proyecto, olvida el inventario. Si
    no se puede leer, el error sigue (las filas, como estaban)."""
    context = bpy.context if context is None else context
    view = _view(context)
    project = project_session.current()
    if view is None or project is None:
        _forget_inventory(view)
        return None
    try:
        header = read_header(project.database_path)
    except GeoblenderError:
        header = None  # lo dirá la lectura
    if getattr(project, "writing", False) or (header is not None and header.needs_recovery):
        return INVENTORY_RETRY_S
    generation = live.view_generation()
    snapshot = _INVENTORY.snapshot
    if snapshot is None or _INVENTORY.project is not project or header is None or \
            header.change_counter != snapshot.change_counter:
        from ...core.views import inventory  # al usarlo, como card

        snapshot = inventory.read_inventory(project, loadable=_loadable)
    _INVENTORY.snapshot = snapshot
    _INVENTORY.project = project
    _INVENTORY.generation = generation
    _fill_inventory(view, project.uid, snapshot)
    _redraw()
    return None


def inventory_tick() -> float | None:
    """El temporizador de un disparo que pide el dibujo del panel cuando el inventario es viejo
    (:func:`refresh_inventory`); lo que falla queda en el registro técnico y lo vuelve a
    intentar el siguiente dibujo."""
    try:
        return refresh_inventory()
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.info("No se pudo leer el inventario del proyecto", exc_info=True)
    except Exception:  # noqa: BLE001 - lo que llama Blender no lo tumba
        LOGGER.exception("Falló la lectura del inventario del proyecto")
    return None


def _request_inventory() -> None:
    """Pide la lectura del inventario al siguiente ciclo (una vez)."""
    if not bpy.app.timers.is_registered(inventory_tick):
        bpy.app.timers.register(inventory_tick, first_interval=0.0)


def inventory_filtered() -> None:
    """Cambió un filtro del panel (``bl.props.views``): vuelve a filtrar lo leído con lo que
    está ahora en la escena, sin leer el proyecto (lo viejo lo lee el siguiente dibujo)."""
    try:
        view = _view(bpy.context)
        project = project_session.current()
        snapshot = _INVENTORY.snapshot
        if view is None or project is None or snapshot is None or \
                _INVENTORY.project is not project:
            return
        _fill_inventory(view, project.uid, snapshot)
        _redraw()
    except Exception:  # noqa: BLE001 - lo que llama Blender no lo tumba
        LOGGER.exception("Falló el filtro del inventario del proyecto")


def on_view_changed() -> None:
    """Lo que se apunta en ``bl.scene.views.add_view_listener`` (T21): se cargó o descargó algo
    de la vista (desde el inventario, un menú o un guion). La columna «En la escena» y lo de la
    fila elegida se ponen al día ya, volviendo a filtrar lo leído con lo que está ahora en la
    escena, sin leer el proyecto (la presencia en la escena es de la escena; con el filtro «En
    la escena», la fila entra o sale), y se redibuja la barra lateral. Si lo leído estaba al día
    antes de esta carga (la petición de la marca que la acompaña es la única desde el último
    filtro), sigue al día: el dibujo no vuelve a pedir su lectura. Sin inventario leído de este
    proyecto, nada."""
    try:
        view = _view(bpy.context)
        project = project_session.current()
        snapshot = _INVENTORY.snapshot
        if view is None or project is None or snapshot is None or \
                _INVENTORY.project is not project:
            return
        fresh = _INVENTORY.generation == live.view_generation() - 1
        _fill_inventory(view, project.uid, snapshot)
        if fresh:
            _INVENTORY.generation = live.view_generation()
        _redraw()
    except Exception:  # noqa: BLE001 - lo cargado o descargado ya está en la escena
        LOGGER.exception("Falló la puesta al día del inventario tras cargar o descargar")


def row_icon(row: Any) -> dict[str, Any]:
    """Los argumentos del icono de una fila: el de una entrada, el del tipo de un dato, el del
    estado de una versión (el propio, ``{"icon_value": n}``, o su reserva nativa; spec 009) o
    el del estado de una revisión."""
    if row.category == VERSION_CATEGORY:
        return version_panels.state_icon(row.status)
    if row.category == REVISION_CATEGORY:
        return {"icon": REVISION_ICONS.get(row.status, OTHER_ICON)}
    if row.category == INPUT_CATEGORY:
        return {"icon": INPUT_ICON}
    return {"icon": KIND_ICONS.get(row.kind, OTHER_ICON)}


def revision_state_text(state: str) -> str:
    """El estado de una revisión como se lee: «en curso» (la abierta, RF-009-20), «congelada» o
    «cerrada»."""
    if state == RevisionState.OPEN:
        return tr("in progress")
    if state == RevisionState.FROZEN:
        return tr("frozen")
    if state == RevisionState.CLOSED:
        return tr("closed")
    return state


def _row_status(row: Any) -> str:
    """El estado de una fila como se lee: el de una entrada («vigente», «cambiada»…), el de un
    dato como en su nombre generado («VIGENTE»), el de una versión («VIGENTE», «BORRADOR»…) o
    el de una revisión («en curso», «congelada», «cerrada»)."""
    if row.category == INPUT_CATEGORY:
        try:
            return render(f"core.input_status_{row.status}", language=language())
        except ValueError:
            return row.status
    if row.category == VERSION_CATEGORY:
        return translate(language(), VersionStatus(row.status).msgid)
    if row.category == REVISION_CATEGORY:
        return revision_state_text(row.status)
    return status_text(row.status)


def inventory_status_text(row: Any) -> str:
    """El estado de una fila con sus marcas: «VIGENTE · OBSOLETO · ENTRADA CAMBIADA»; de una
    revisión, «congelada · ALTERADA»; de un dato de una revisión congelada, el estado que
    tenía al congelarse, «VIGENTE · OBSOLETO AL CONGELARSE, ACEPTADO» (T37)."""
    parts = [_row_status(row)]
    if row.stale:
        parts.append(translate(language(), STALE_MSGID))
    if row.input_changed:
        parts.append(translate(language(), INPUT_CHANGED_MSGID))
    if row.altered:
        parts.append(translate(language(), ALTERED_MSGID))
    parts.append(frozen_state_text(getattr(row, "frozen_state", "")))
    return " · ".join(part for part in parts if part)


def inventory_kind_text(row: Any) -> str:
    """El tipo de una fila: «Entrada · ráster · gis» o, de un dato, su nombre de cargador, su
    tipo y su módulo («MDT de origen · ráster · gis»); «Versión» o «Revisión»."""
    if row.category == VERSION_CATEGORY:
        return tr("Version")
    if row.category == REVISION_CATEGORY:
        return tr("Revision")
    if row.category == INPUT_CATEGORY:
        first = tr("Input")
    else:
        loader = views.loader_for(row.name)
        first = translate(language(), loader.label) if loader is not None else ""
    parts = (first, provenance.kind_text(row.kind), row.module)
    return " · ".join(part for part in parts if part)


def load_refusal(row: Any) -> str:
    """Por qué no se puede cargar en la vista el elemento de una fila ("" si se puede)."""
    if row.category == INPUT_CATEGORY:
        return tr("An input is not loaded into the view: the data imported from it are")
    if row.category in _NUMBERED:
        return tr("A version or a revision is not loaded into the view: its data are")
    if row.loadable:
        return ""
    if row.status in _HISTORY:
        return tr("A superseded or discarded dataset is not loaded into the view")
    if row.status == _MISSING:
        return tr("Its file or its table is missing: it cannot be loaded into the view")
    return tr("No module loads this dataset into the view")


def unload_refusal(row: Any) -> str:
    """Por qué no se puede descargar de la vista ("" si se puede)."""
    return "" if row.in_scene else tr("Not loaded in the scene: there is nothing to unload")


def lineage_refusal(row: Any) -> str:
    """Por qué no tiene procedencia ("" si la tiene: un dato)."""
    if row.category == INPUT_CATEGORY:
        return tr("An input has no provenance: the data imported from it have it")
    if row.category in _NUMBERED:
        return tr("A version or a revision has no provenance: its data have it")
    return ""


def draw_inventory_row(layout: Any, row: Any) -> None:
    """Una fila de la lista (``draw_item`` de :class:`GEOBLENDER_UL_core_project_inventory`): el
    icono de su tipo (de una versión o una revisión, el de su estado) y su nombre; a la derecha,
    su estado, su versión («—»), si está en la escena (un ojo) y sus marcas, en alerta
    (obsoleto; entrada cambiada; revisión alterada; un dato que no estaba al día al
    congelarse, :data:`FROZEN_STATE_ICON`)."""
    line = layout.split(factor=INVENTORY_NAME_FACTOR, align=True)
    line.label(text=row.name, translate=False, **row_icon(row))
    right = line.row(align=True)
    right.alignment = "RIGHT"
    right.label(text=_row_status(row), translate=False)
    right.label(text=row.version or NO_VALUE, translate=False)
    right.label(text="", icon=IN_SCENE_ICON if row.in_scene else "BLANK1")
    marks = right.row(align=True)
    marks.alert = True
    if row.stale:
        marks.label(text="", icon=STALE_ICON)
    if row.input_changed:
        marks.label(text="", icon=INPUT_CHANGED_ICON)
    if row.altered:
        marks.label(text="", icon=ALTERED_ICON)
    if getattr(row, "frozen_state", ""):
        marks.label(text="", icon=FROZEN_STATE_ICON)


def _chosen(view: Any) -> Any:
    """La fila elegida de la lista, o ``None``."""
    rows = view.inventory
    index = view.inventory_index
    return rows[index] if 0 <= index < len(rows) else None


def _order(layout: Any, idname: str, text: str, icon: str, refusal: str, width: float,
           **values: Any) -> None:
    """Un botón de una orden de la fila elegida, con ``values`` en sus propiedades;
    desactivado y con el motivo debajo si ``refusal``."""
    row = layout.row(align=True)
    row.enabled = not refusal
    properties = row.operator(idname, text=text, icon=icon, translate=False)
    for name, value in values.items():
        setattr(properties, name, value)
    if refusal:
        _draw_lines(layout, refusal, width, icon="INFO")


def draw_chosen(layout: Any, row: Any, width: float) -> None:
    """Lo de la fila elegida: su nombre, su tipo, su estado con sus marcas (en alerta), su
    versión, si está en la escena, y Cargar en la vista, Descargar y Procedencia."""
    column = layout.column(align=True)
    _draw_lines(column, row.name, width, **row_icon(row))
    _draw_lines(column, tr("Type: {kind}", kind=inventory_kind_text(row)), width)
    _draw_lines(column, tr("Status: {status}", status=inventory_status_text(row)), width,
                alert=row.stale or row.input_changed or row.altered
                or bool(getattr(row, "frozen_state", "")))
    _draw_lines(column, tr("Version: {version}", version=row.version or NO_VALUE), width)
    _draw_lines(column, tr("Loaded in the scene") if row.in_scene else
                tr("Not loaded in the scene"), width)
    orders = layout.column(align=True)
    _order(orders, LOAD_INTO_VIEW, tr("Load into the view"), LOAD_ICON, load_refusal(row),
           width, datasets=row.uid)
    _order(orders, UNLOAD_FROM_VIEW, tr("Unload"), UNLOAD_ICON, unload_refusal(row), width,
           datasets=row.uid)
    _order(orders, SHOW_LINEAGE, tr("Provenance"), "NODETREE", lineage_refusal(row), width,
           item_uid=row.uid)


def draw_inventory(layout: Any, context: Any) -> None:
    """El contenido de :class:`GEOBLENDER_PT_core_project_inventory`: los filtros, la lista
    (o por qué no hay filas), «… y n más: afine el filtro» y lo de la fila elegida. No lee el
    proyecto: si lo que enseña es viejo, pide su lectura (:func:`inventory_tick`)."""
    view = _view(context)
    project = project_session.current()
    if view is None or project is None:
        return
    if inventory_is_old(project):
        _request_inventory()
    width = labels.sidebar_width(context)
    filters = layout.column(align=True)
    filters.prop(view, "inventory_text", text="", icon="VIEWZOOM", translate=False)
    filters.prop(view, "inventory_kind", text=tr("Type"), translate=False)
    filters.prop(view, "inventory_status", text=tr("Status"), translate=False)
    filters.prop(view, "inventory_version", text=tr("Version"), translate=False)
    filters.prop(view, "inventory_presence", text=tr("In the scene"), translate=False)
    if view.inventory_project != project.uid:
        _draw_lines(layout, tr("Reading the project inventory…"), width, icon="TIME")
        return
    if not len(view.inventory):
        _draw_lines(layout, tr("Nothing in the project matches the filter"), width,
                    icon="INFO")
        return
    layout.template_list(INVENTORY_LIST, "", view, "inventory", view, "inventory_index",
                         rows=INVENTORY_ROWS)
    if view.inventory_more:
        _draw_lines(layout, tr("… and {count} more: refine the filter",
                               count=format_number(view.inventory_more, 0)), width)
    row = _chosen(view)
    if row is not None:
        layout.separator()
        draw_chosen(layout, row, width)


class GEOBLENDER_UL_core_project_inventory(bpy.types.UIList):
    """What is registered in the project, loaded in the view or not"""

    bl_idname = INVENTORY_LIST

    def draw_item(self, _context: Any, layout: Any, _data: Any, item: Any, _icon: int,
                  _active_data: Any, _active_property: str, _index: int = 0,
                  _flt_flag: int = 0) -> None:
        draw_inventory_row(layout, item)


class GEOBLENDER_PT_core_project_inventory(bpy.types.Panel):
    """What is registered in the project, loaded in the view or not, with its marks and the
    orders of the chosen row"""

    bl_idname = INVENTORY_PANEL
    bl_label = INVENTORY_LABEL
    bl_category = core_panel.PANEL_LABEL
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_order = INVENTORY_ORDER
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return project_session.current() is not None and gate.in_geoblender_scope(context)

    def draw(self, context: Any) -> None:
        draw_inventory(self.layout, context)


# Cifras de la selección (T16) -----------------------------------------------------------------


def selected_objects(context: Any) -> list[Any]:
    """Los objetos seleccionados de ``context`` (``selected_objects``) o, si no los da, los de
    su capa que lo están."""
    found = getattr(context, "selected_objects", None)
    if found is not None:
        return list(found)
    layer = getattr(context, "view_layer", None)
    if layer is None:
        return []
    return [obj for obj in layer.objects if obj.select_get(view_layer=layer)]


def selection_lines(found: Sequence[DatasetFigures]) -> list[CardLine]:
    """Las líneas de la ventana de «Cifras de la selección» (RF-010-08) con las cifras de cada
    dato (``core.views.card.DatasetFigures``, con sus marcas), en el idioma de Geoblender: de
    cada uno, su nombre y cada cifra registrada con su insignia de tipo, su nombre y su valor con
    su unidad y, debajo, sus marcas de hoy (RF-008-31: «depende de una hipótesis», «obsoleta»…,
    en alerta), o «Sin cifras registradas»; si ninguno tiene, sus nombres y por qué; sin
    ninguno, que la selección no muestra datos del proyecto. Nada se mide."""
    shown = language()
    recorded = any(item.figures for item in found)
    lines: list[CardLine] = []
    for item in found:
        record = item.record
        lines.append(CardLine(ROW_NAME, record.name, KIND_ICONS.get(record.kind, OTHER_ICON),
                              uid=record.uid))
        for figure in item.figures:
            lines.append(CardLine(
                ROW_FIGURE, f"{provenance.badge(figure.kind)} {figure.text(language=shown)}",
                uid=figure.uid))
            marks = item.marks.get(figure.uid)
            texts = () if marks is None else marks.texts(language=shown)
            if texts:
                lines.append(CardLine(ROW_MARKS, " · ".join(texts), alert=True, uid=figure.uid))
        if recorded and not item.figures:
            lines.append(CardLine(ROW_NONE, tr("No figures recorded")))
    if not found:
        lines.append(CardLine(ROW_NOTE, tr("No selected object shows data of this project"),
                              "INFO"))
    elif not recorded:
        lines.append(CardLine(ROW_NOTE, tr("No figures recorded: no operation of these data "
                                           "recorded figures (the cubature records them, for "
                                           "example)"), "INFO"))
    return lines


def fill_selection_figures(context: Any = None) -> int:
    """Lee del proyecto de la sesión, en una instantánea, las cifras registradas con sus marcas
    de los datos de este proyecto que muestran los objetos seleccionados de ``context`` (por
    defecto, ``bpy.context``), sin repetir (``core.views.card.dataset_figures``: las de la
    operación que escribió el contenido de cada uno; sus marcas leen el grafo, por eso solo al
    pedirlo), y pone sus líneas, por nombre, en ``WindowManager.geoblender_view_panels``
    (:func:`selection_lines`). No mide nada ni escribe en el proyecto; las cifras de los
    objetos (``Object.geoblender.figures``) no cuentan: el proyecto es la fuente. Devuelve de
    cuántos datos; sin proyecto, 0. Si no se puede leer el proyecto, el error sigue y las filas
    quedan como estaban."""
    context = bpy.context if context is None else context
    view = _view(context)
    project = project_session.current()
    if view is None or project is None:
        return 0
    uids: dict[str, None] = {}
    for obj in selected_objects(context):
        uid, owner = shown_by(obj)
        if uid and owner == project.uid:
            uids[uid] = None
    # Al usarlo: registrar no carga core.provenance.importer (spec 008, T65).
    from ...core.views import card

    found = sorted(card.dataset_figures(project, list(uids), marks=True) if uids else (),
                   key=lambda item: (item.record.name.casefold(), item.record.name))
    view.selection_project = project.uid
    _put_lines(view.selection, selection_lines(found))
    return len(found)


def draw_selection_figures(layout: Any, context: Any) -> None:
    """El contenido de :class:`GEOBLENDER_PT_core_selection_figures`: las líneas ya leídas al
    pedir la orden, partidas al ancho de la ventana. No lee el proyecto."""
    layout.label(text=tr("Selection figures"), translate=False)
    width = labels.dialog_width(SELECTION_FIGURES_WIDTH_PX)
    view = _view(context)
    project = project_session.current()
    if project is None:
        _draw_lines(layout, tr("No project is open"), width, icon="INFO")
        return
    if view is None or view.selection_project != project.uid:
        return
    for index, row in enumerate(view.selection):
        if row.kind == ROW_NAME and index:
            layout.separator()
        sub = layout.column(align=True)
        sub.active = row.kind != ROW_NONE
        icon = row.icon or ("NONE" if row.kind == ROW_NOTE else "BLANK1")
        _draw_lines(sub, row.text, width, icon=icon, alert=row.alert)


class GEOBLENDER_PT_core_selection_figures(bpy.types.Panel):
    """Registered figures of the selected data, with their unit, their type and their marks"""

    bl_idname = SELECTION_FIGURES_PANEL
    bl_label = SELECTION_FIGURES_LABEL
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = SELECTION_FIGURES_UNITS

    def draw(self, context: Any) -> None:
        draw_selection_figures(self.layout, context)


def localize() -> None:
    """La pestaña y los títulos en el idioma de la interfaz (antes de registrar)."""
    GEOBLENDER_PT_core_active_item.bl_category = tr("Project")
    GEOBLENDER_PT_core_active_item.bl_label = tr("Active item")
    GEOBLENDER_PT_core_project_inventory.bl_category = tr("Project")
    GEOBLENDER_PT_core_project_inventory.bl_label = tr("Inventory")


# En orden de registro (tras los de core_panel: la pestaña «Proyecto»; la lista, antes del panel
# que la dibuja; la ventana de las cifras, sin pestaña).
classes: tuple[type, ...] = (GEOBLENDER_PT_core_active_item,
                             GEOBLENDER_UL_core_project_inventory,
                             GEOBLENDER_PT_core_project_inventory,
                             GEOBLENDER_PT_core_selection_figures)


def register() -> None:
    """Se suscribe al objeto activo y apunta el manejador de ``load_post`` y las escuchas del
    proyecto de la sesión, de los indicadores y de lo cargado y descargado de la vista;
    idempotente."""
    _subscribe()
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)
    project_session.add_listener(on_project_changed)
    provenance.add_change_listener(on_project_read)
    views.add_view_listener(on_view_changed)


def unregister() -> None:
    """Quita las escuchas, el manejador (todas sus apariciones), la suscripción y el
    temporizador del inventario, y olvida la ficha y el inventario; idempotente."""
    views.remove_view_listener(on_view_changed)
    provenance.remove_change_listener(on_project_read)
    project_session.remove_listener(on_project_changed)
    while on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    bpy.msgbus.clear_by_owner(_STATE.owner)
    _STATE.token = None
    view = _view(bpy.context)
    _forget_inventory(view)
    if view is not None:
        _clear(view)
