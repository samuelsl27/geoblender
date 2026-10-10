# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia en la interfaz (spec 008; plan 008 §5.5; ADR-0012).

**Barra de estado** (campos de la 003 con ``bl.ui.statusbar.register_field``, prioridad 1,
en los dos modos, Geoblender y Blender; spec §11), cada uno solo si tiene algo que mostrar:

- «⚠ n entradas» (RF-008-16; con una, «⚠ 1 entrada»: T71): las entradas cambiadas sin
  decidir; abre el registro de entradas (``geoblender.core_show_inputs``);
- «! n obsoletos» (RF-008-28; «! 1 obsoleto»): los datos obsoletos, más las operaciones
  obsoletas que solo dejan cifras, más las que esperan revisión a mano; abre lo obsoleto
  (:class:`GEOBLENDER_PT_core_stale`);
- «Comprobando el proyecto… 42 %» (RF-008-58), el progreso de la comprobación de apertura de
  la sesión de la procedencia (``bl.ops.core_provenance.SESSION``), con su botón de cancelar
  (``geoblender.core_cancel_checks``);
- el aviso de Ctrl+Z (RF-008-32; plan §5.4.11): :func:`show_undo_notice` lo deja
  :data:`UNDO_NOTICE_S` s.

Si no caben (spec 008, T69; M6: a 1920 px con escala efectiva 1,5), la barra de estado los
**pliega** de derecha a izquierda (``bl.ui.statusbar.fold``), con los mismos botones: «⚠ n»,
«! n», solo «42 %» con su botón de cancelar y el aviso de Ctrl+Z cortado a
:data:`UNDO_FOLDED_UNITS` unidades. Lo que ocupa cada campo, plegado o no, se calcula como lo
dibuja Blender (``statusbar.button_px``, ``popover_px``, ``label_px``).

Los iconos ``gb_state_input_changed`` y ``gb_state_stale`` dibujan los mismos signos ⚠ y ! con
que empiezan los textos de la spec (AR §6): en la barra van solo los textos, sin repetir el
signo; el de lo obsoleto, en el panel.

**Al día sin leer en cada dibujo** (RNF-008-06: ≤ 1 s tras el cambio y ≤ 1 ms el dibujo): los
recuentos (``core.provenance.stale``) se leen en un temporizador persistente
(:func:`indicator_tick`, cada :data:`INDICATOR_TICK_S` s mientras hay un proyecto abierto),
y solo si cambió el contador de cambios de la cabecera de ``project.gpkg`` (lo sube cada
transacción confirmada, sea de quien sea) o el idioma; si no, el tic lee 100 bytes. Un
proyecto que QGIS dejó en WAL no se lee hasta que vuelva al diario clásico (lo que escribe
Geoblender lo devuelve antes). Los campos dibujan lo último leído, con sus textos medidos una
vez. Al abrir un proyecto no se lee nada (RNF-002-02 no cambia): el primer tic, después.

**Control 7** (RF-008-28): el número de lo obsoleto tras el icono de Refrescar
(``quick_access.set_count_provider``), que abre :class:`GEOBLENDER_PT_core_stale`; sin nada
obsoleto, solo el icono. Refrescar sigue provisional hasta la 009.

**Lo obsoleto** (:class:`GEOBLENDER_PT_core_stale`, RF-008-28): «Refrescar · obsoletos (n)» y,
por cada resultado obsoleto (como mucho :data:`MAX_STALE_ROWS`; los demás, «… y n más»): un
dato o una operación que solo deja cifras, con su nombre, su módulo, la causa («Obsoleto:
cambió Producción») y Recalcular (``geoblender.core_recompute_stale`` de ese elemento) o, si
espera revisión a mano, «revisar» y
Dar por buena… (``geoblender.core_accept_review``); después (T54; RF-008-56, RF-008-57), los
datos que no se pueden usar (bloqueados por una edición externa, que faltan o dañados), cada uno
con su aviso y lo que se ofrece para resolverlo (Aceptar la edición, Recalcular, Reimportar:
``geoblender.core_resolve_dataset``); al final, Recalcular lo obsoleto. Dibuja las filas de
``WindowManager.geoblender_provenance.stale`` y ``unusable`` (D16), que el temporizador
regenera con los recuentos. Las órdenes cuya clase real aún no ha llegado se dibujan
desactivadas.

**Parámetros del proyecto** (:class:`GEOBLENDER_PT_core_parameters`, ventana emergente que
abre ``geoblender.core_show_parameters``; RF-008-06, RF-008-59; T50): filtros por módulo, tipo
y marca; la lista (:class:`GEOBLENDER_UL_core_parameters`) con la clave, el valor con su
unidad, la insignia de tipo ([HIP] con su icono ámbar: :func:`badge_icon`), las marcas «sin
confirmar» y «revisar», el origen, el decisor y la fecha; del seleccionado, su origen, su
decisión, lo que hay que revisar,
el aviso de divergencia de su última cifra calculada con «Usar el valor calculado…» (Cambiar
relleno con la cifra), el historial completo (:class:`GEOBLENDER_UL_core_parameter_history`) y
Cambiar parámetro… y Confirmar parámetro; en solo lectura, desactivados y con el motivo.
:func:`fill_parameters` lee la lista de ``core.params`` (``ParameterStore.list`` con los
filtros de la vista) y :func:`fill_history`, el historial y el aviso del seleccionado; los
llaman la orden que abre el panel, Cambiar y Confirmar al escribir, y los filtros y la
selección al cambiar. Las filas viven en ``WindowManager.geoblender_provenance`` (D16), como
texto ya presentado: ningún valor pasa por una propiedad flotante. Los valores, en el idioma de
Geoblender y con el separador de miles de las cifras, como una cifra («500 000 t/año»; T71).

**Registro de entradas** (:class:`GEOBLENDER_PT_core_inputs`, ventana emergente que abre
``geoblender.core_show_inputs``; RF-008-16, RF-008-13; T51): la cabecera de las columnas y la
lista (:class:`GEOBLENDER_UL_core_inputs`) con el nombre, el estado, el tipo, la fecha de
entrega, quién la entrega, los CRS horizontal y vertical declarados, el hash de contenido
abreviado (12 caracteres) y si guarda su original; de la seleccionada, Actualizar (si está
cambiada, también con su copia mantenida, y se encuentra su fuente) y Mantener la copia (si
está cambiada), Descartar… y Editar…, que abren sus diálogos (T52); y Comprobar cambios en las
entradas
(``geoblender.core_check_inputs``); debajo (T54; RF-008-62), las capas y tablas del proyecto
sin registrar, creadas desde QGIS, con Registrar como entrada… e Ignorar…
(``geoblender.core_resolve_unregistered``); en solo lectura, desactivadas y con el motivo.
:func:`fill_inputs` lee las filas (``core.inputs.list_inputs``) con el estado registrado; el
que no se guarda (plan D7) lo dice la sesión al dibujar (:func:`input_status`):
«comprobando» mientras una comprobación tiene pendiente la entrada y «no localizable» si la
última no encontró su fuente. Con el registro abierto, el temporizador de los indicadores
vuelve a leer sus filas cuando cambia el proyecto.

**Grafo de operaciones y procedencia** (:class:`GEOBLENDER_PT_core_lineage`, ventana emergente
que abre ``geoblender.core_show_lineage``; RF-008-29, RF-008-31; T55): la búsqueda (el uid de una
cifra, de un dato o de una operación, o el nombre de un dato; si no es nada de eso, el motivo y
las cifras vigentes y los datos que contienen el texto, cada uno con su procedencia) y la cadena
(:class:`GEOBLENDER_UL_core_lineage`): lo pedido y, sangrados debajo, cada eslabón con la versión
de su algoritmo y de Geoblender, quién y cuándo; sus parámetros con el valor y la unidad que
leyó, su insignia de tipo y «sin confirmar», y lo de hoy si cambió; sus entradas con su estado;
los datos que consumió y el eslabón que escribió esa versión. La cifra lleva su unidad, su
insignia y las marcas de RF-008-31 según el estado de hoy, y un eslabón obsoleto, su causa en
alerta. Cada nudo se pliega (``expanded``). :func:`search_lineage` lee la cadena al abrir el
panel y al cambiar la búsqueda (no en cada cambio del proyecto: con un grafo grande tarda hasta
0,5 s); las filas viven en ``WindowManager.geoblender_provenance``, como texto ya presentado.

**Insignias de tipo** (RF-008-02, RF-008-06, RF-008-29; T70): en las tres listas (parámetros,
su historial y la procedencia), [MED], [CAL], [ADO] y [HIP] (:func:`badge`) en una columna de
:data:`BADGE_UNITS` unidades. Blender solo colorea un texto en rojo (``alert``), que la interfaz
deja para los errores y los cambios: [HIP] se distingue con el icono ámbar propio
:data:`HYPOTHESIS_ICON` de la 003 junto a la insignia, sin alerta (:func:`badge_icon`; sin él,
su reserva nativa ámbar), y los demás tipos llevan un hueco del mismo ancho, para que el texto
quede alineado.

**Estados de las órdenes** (RF-008-61; BS §7.3; T56): :func:`command_state` es el proveedor de
``bl.ui.commands.set_state_provider``. Una orden de un módulo (su ``bl_idname`` en los
``commands`` del ``OperationDef`` de una operación hecha) de la que depende una entrada
cambiada sin decidir (``core.inputs.dependents``) lleva la insignia ⚠ y, en su descripción, el
aviso de RF-008-10; si alguno de sus resultados (un dato o, de una operación que solo deja
cifras, ella misma) está obsoleto o espera revisión a mano, su descripción lleva su
«Obsoleto: cambió …»; con algo obsoleto en el proyecto, «Recalcular lo
obsoleto» se dibuja resaltado en el menú y en los contextuales. Se calcula con los recuentos
(:func:`refresh`, solo cuando cambia el proyecto) y el dibujo solo lo busca.

:func:`install` registra los campos, el número del control 7, el proveedor de estado de las
órdenes y la escucha del proyecto de la sesión; :func:`uninstall` lo quita todo, con los
temporizadores.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any

import bpy

from ...core.errors import GeoblenderError
from ...core.gpkg.header import read_header
from ...core.i18n import language, tr
from ...core.inputs import (
    ACTIVE_STATUSES,
    InputFinding,
    InputStatus,
    OriginalState,
    Verdict,
    crs_text,
    dependents,
    list_inputs,
)
from ...core.params import HistoryAction, ParameterFilter, ParameterStore, ParamKind, ParamMark
from ...core.params.store import shown_value
from ...core.provenance import contract
from ...core.provenance.messages import render
from ...core.timeutil import parse_utc
from ..props.provenance import FILTER_ALL, WINDOW_MANAGER_PROPERTY
from ..scene import project_session
from . import icons, quick_access, statusbar
from .commands import (
    CommandState,
    catalog,
    is_available,
    registered_class,
    set_state_provider,
    state_provider,
    text,
)
from .drawing import draw_command, native_icon

if TYPE_CHECKING:
    from ...core.inputs import InputRecord
    from ...core.project.session import Project
    from ...core.provenance.stale import Counts, StaleItem, StaleReport
    from ..ops.core_provenance import ProvenanceSession

LOGGER = logging.getLogger("geoblender.bl.ui")

FIELD_INPUTS = "provenance_inputs"
FIELD_STALE = "provenance_stale"
FIELD_CHECKING = "provenance_checking"
FIELD_UNDO = "provenance_undo"
FIELD_PRIORITY = 1
FIELD_MODES = frozenset({statusbar.GEOBLENDER, statusbar.BLENDER})
"""Los campos se ven en los dos modos (plan §5.5; spec §11)."""

INDICATOR_TICK_S = 0.5
"""Cada cuánto mira el temporizador si el proyecto cambió (RNF-008-06: ≤ 1 s con la lectura)."""

UNDO_NOTICE_S = 10.0
"""Lo que se ve el aviso de Ctrl+Z en la barra de estado (plan §5.5)."""

UNDO_FOLDED_UNITS = 6
"""El ancho del aviso de Ctrl+Z plegado, en unidades: Blender corta el texto con «…» (T69)."""

FOLDED_INPUTS = "provenance_inputs_folded"  # los textos plegados, en la caché de textos (T69)
FOLDED_STALE = "provenance_stale_folded"

MAX_STALE_ROWS = 50
"""Las filas de lo obsoleto que se regeneran y dibujan (las demás, «… y n más»)."""

REFRESH = "geoblender.core_refresh"
STALE_PANEL = "GEOBLENDER_PT_core_stale"
SHOW_INPUTS = "geoblender.core_show_inputs"
CANCEL_CHECKS = "geoblender.core_cancel_checks"
RECOMPUTE = "geoblender.core_recompute_stale"
ACCEPT_REVIEW = "geoblender.core_accept_review"
RESOLVE_DATASET = "geoblender.core_resolve_dataset"
RESOLVE_UNREGISTERED = "geoblender.core_resolve_unregistered"
STALE_ICON = "gb_state_stale"
STALE_FALLBACK = "COLLECTION_COLOR_01"
CANCEL_ICON = "X"
UNDO_ICON = "LOOP_BACK"
STALE_PANEL_UNITS = 20
MAX_TEXTS = 256  # textos con número guardados (después, se empieza de nuevo)

PARAMETERS_PANEL = "GEOBLENDER_PT_core_parameters"
PARAMETERS_LIST = "GEOBLENDER_UL_core_parameters"
HISTORY_LIST = "GEOBLENDER_UL_core_parameter_history"
SET_PARAMETER = "geoblender.core_set_parameter"
CONFIRM_PARAMETER = "geoblender.core_confirm_parameter"
PARAMETERS_PANEL_UNITS = 44
PARAMETER_ROWS = 8  # filas visibles de la lista (después, se desplaza)
HISTORY_ROWS = 5
HYPOTHESIS_ICON = "gb_type_assumption"  # [HIP]: «HIP» sobre ámbar (spec 003, II §1.4; T70)
HYPOTHESIS_FALLBACK = "COLLECTION_COLOR_03"  # su reserva nativa ámbar (la de BORRADOR)
BADGE_UNITS = 3.5
"""Ancho de la insignia de tipo con su icono (T70): el de [HYP], el más ancho con icono, es
65 px a escala 1,0 (blf 30 + 35)."""
# Ancho (unidades) de cada columna de la lista de parámetros y del historial.
PARAMETER_COLUMNS = (9.0, 5.5, BADGE_UNITS, 5.0, 9.0, 7.0, 4.0)
HISTORY_COLUMNS = (1.5, 3.5, 4.5, BADGE_UNITS, 3.5, 5.0, 3.5, 7.0, 6.0, 5.5)

INPUTS_PANEL = "GEOBLENDER_PT_core_inputs"
INPUTS_LIST = "GEOBLENDER_UL_core_inputs"
CHECK_INPUTS = "geoblender.core_check_inputs"
RESOLVE_INPUT = "geoblender.core_resolve_input"
DISCARD_INPUT = "geoblender.core_discard_input"
EDIT_INPUT = "geoblender.core_edit_input"
INPUTS_PANEL_UNITS = 56
INPUT_ROWS = 8  # filas visibles del registro de entradas (después, se desplaza)
HASH_CHARS = 12  # el hash de contenido abreviado (plan §5.5)
# Ancho (unidades) de cada columna del registro de entradas: nombre, estado, tipo, entrega,
# quién la entrega, CRS horizontal, CRS vertical, hash de contenido y original.
INPUT_COLUMNS = (8.0, 10.0, 4.0, 4.5, 6.0, 5.5, 5.0, 5.5, 4.0)
_ACTIVE_INPUTS = frozenset(str(status) for status in ACTIVE_STATUSES)
NOT_SHOWN = "—"  # una celda sin valor (sin entrega, sin original)

LINEAGE_PANEL = "GEOBLENDER_PT_core_lineage"
LINEAGE_LIST = "GEOBLENDER_UL_core_lineage"
SHOW_LINEAGE = "geoblender.core_show_lineage"
LINEAGE_PANEL_UNITS = 56
LINEAGE_ROWS = 12  # filas visibles de la procedencia (después, se desplaza)
LINEAGE_INDENT = 1.5  # sangría de cada nivel (factor de ``separator``)
MAX_LINEAGE_ROWS = 1000
"""Las filas de la procedencia que se guardan en la vista (las demás, «… y n más»)."""

_clock: Callable[[], float] = time.monotonic


class _State:
    """Lo de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.project: Project | None = None  # el proyecto de los recuentos
        self.counts: Counts | None = None
        self.signature: tuple[int, str] | None = None  # contador de cambios e idioma leídos
        self.texts: dict[tuple[str, int, str], str] = {}
        self.undo_text = ""
        self.undo_until = 0.0
        self.properties: dict[type, frozenset[str]] = {}  # propiedades de cada operador
        self.filling = False  # se están regenerando las filas de los parámetros
        self.searching = False  # se está poniendo la búsqueda de la procedencia
        self.command_states: dict[str, CommandState] = {}  # bl_idname → estado (T56)


_STATE = _State()


def _session() -> ProvenanceSession:
    """La sesión de la procedencia (``bl.ops.core_provenance``), importada al usarla: bl/ops
    importa bl/ui (ARQ-08)."""
    from ..ops import core_provenance

    return core_provenance.SESSION


# Los recuentos --------------------------------------------------------------------------------


def counts() -> Counts | None:
    """Los últimos recuentos leídos del proyecto de la sesión, o ``None`` (sin proyecto con la
    procedencia o aún sin leer)."""
    return _STATE.counts


def refresh(*, force: bool = False) -> bool:
    """Vuelve a leer los recuentos y las filas de lo obsoleto si el proyecto de la sesión
    cambió desde la última lectura (otro proyecto, otro contador de cambios en la cabecera de
    ``project.gpkg`` u otro idioma) o con ``force``. Devuelve si cambió lo que muestran la barra
    de estado y el control 7. Si no se puede leer ahora (otro programa escribe, WAL), lo deja
    como estaba y lo intenta en la próxima."""
    session = _session()
    project = session.project if session.unavailable() is None else None
    changed = False
    if project is not _STATE.project:
        changed = _forget()
        _STATE.project = project
    if project is None:
        return changed
    try:
        header = read_header(project.database_path)
    except GeoblenderError:
        return changed
    if header.needs_recovery:
        return changed  # en WAL (QGIS): sin leer una copia privada en cada tic
    shown = language()
    signature = (header.change_counter, shown)
    if signature == _STATE.signature and not force:
        return changed
    from ...core.provenance import stale  # al usarlo: registrar no lo carga

    try:
        report = stale.stale_items(project, language=shown)
        blocked = _unusable(project)
        states = _command_states(project, report, shown)
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.debug("No se pudo leer lo obsoleto del proyecto; se intenta después",
                     exc_info=True)
        return changed
    _STATE.signature = signature
    _STATE.command_states = states
    _fill_rows(report.items)
    _fill_unusable(blocked, shown)
    _refill_inputs()
    if report.counts != _STATE.counts:
        _STATE.counts = report.counts
        changed = True
    return changed


def _forget() -> bool:
    """Olvida los recuentos y las filas de lo obsoleto; dice si había algo que mostrar."""
    found = _STATE.counts
    had = found is not None and (found.obsolete > 0 or found.inputs_changed > 0)
    _STATE.project = None
    _STATE.counts = None
    _STATE.signature = None
    _STATE.command_states = {}
    _fill_rows(())
    _fill_unusable((), "")
    return had


def _view() -> Any:
    manager = getattr(bpy.context, "window_manager", None)
    return getattr(manager, WINDOW_MANAGER_PROPERTY, None)


def _fill_rows(items: Sequence[StaleItem]) -> None:
    """Regenera las filas de lo obsoleto (las primeras :data:`MAX_STALE_ROWS`)."""
    view = _view()
    if view is None:
        return
    rows = view.stale
    if not items and not len(rows):
        return
    rows.clear()
    for item in items[:MAX_STALE_ROWS]:
        row = rows.add()
        row.item_kind = item.item_kind
        row.uid = item.uid
        row.name = item.name
        row.module = item.module
        row.operation_uid = item.operation_uid
        row.op_type = item.op_type
        row.review = item.review
        row.text = item.text
        row.since = item.since
    view.stale_index = 0


def _unusable(project: Project) -> tuple[Any, ...]:
    """Los datos que no se pueden usar hasta resolverlos (``core.datasets.external.unusable``;
    T54), leídos del proyecto."""
    from ...core.datasets.external import unusable  # al usarlo: registrar no lo carga

    with project.read() as conn:
        return unusable(conn)


def _fill_unusable(items: Sequence[Any], shown: str) -> None:
    """Regenera las filas de lo que no se puede usar (RF-008-56, RF-008-57): cada dato con su
    estado, lo que se ofrece para resolverlo y su aviso en el idioma ``shown``."""
    view = _view()
    if view is None:
        return
    rows = view.unusable
    if not items and not len(rows):
        return
    rows.clear()
    for item in items:
        record = item.record
        row = rows.add()
        row.uid = record.uid
        row.name = record.name
        row.module = record.module
        row.status = str(record.status)
        row.offers = ",".join(str(offer) for offer in item.offers)
        row.text = item.text(shown)


# Los estados de las órdenes (T56) -------------------------------------------------------------

INPUT_BADGE = "⚠"
"""La insignia de una orden que depende de una entrada cambiada sin decidir (BS §7.3)."""


def command_state(_context: Any, idname: str) -> CommandState | None:
    """El proveedor de estado de las órdenes (``commands.set_state_provider``; RF-008-61): el
    de ``idname`` según lo último que leyó :func:`refresh`, o ``None``. Solo lo busca."""
    return _STATE.command_states.get(idname)


def _changed_warning(conn: sqlite3.Connection, record: InputRecord,
                     shown: str) -> tuple[str, tuple[str, ...]]:
    """El aviso de RF-008-10 de la entrada cambiada ``record`` en el idioma ``shown`` (su
    registro y lo que depende de ella ahora, sin mirar su fuente) y los tipos de las
    operaciones hechas que dependen de ella."""
    found = dependents(conn, record)
    finding = InputFinding(
        input_uid=record.uid, name=record.name, verdict=Verdict.CHANGED, before=record.status,
        status=record.status, registered_at=record.registered_at,
        registered_sha256=record.content_sha256, previous_seen=record.seen_sha256,
        reader=record.reader, content_sha256=record.seen_sha256, dependents=found)
    return finding.render(shown) or "", tuple(item.name for item in found.operations)


def _command_states(project: Project, report: StaleReport,
                    shown: str) -> dict[str, CommandState]:
    """El estado de cada orden que lo tiene (RF-008-61), en el idioma ``shown``: las órdenes de
    las operaciones que dependen de una entrada cambiada sin decidir, con la insignia y su aviso;
    las de las operaciones de la lista de lo obsoleto (las que escribieron un dato obsoleto, las
    obsoletas que solo dejan cifras y las que esperan revisión a mano), con su «Obsoleto: …»;
    y, con algo obsoleto, «Recalcular lo obsoleto» resaltado. Las entradas solo se leen si hay
    alguna cambiada."""
    notes: dict[str, list[str]] = {}
    badges: set[str] = set()

    def add(op_type: str, note: str, *, badge: bool = False) -> None:
        definition = contract.OPERATIONS.get(op_type)
        for idname in () if definition is None else definition.commands:
            found = notes.setdefault(idname, [])
            if note and note not in found:
                found.append(note)
            if badge:
                badges.add(idname)

    if report.counts.inputs_changed > 0:
        with project.read() as conn:
            for record in list_inputs(conn):
                if record.status is InputStatus.CHANGED:
                    warning, op_types = _changed_warning(conn, record, shown)
                    for op_type in dict.fromkeys(op_types):
                        add(op_type, warning, badge=True)
    for item in report.items:
        if item.op_type:
            add(item.op_type, item.text)
    states = {idname: CommandState(badge=INPUT_BADGE if idname in badges else "",
                                   note="\n".join(found))
              for idname, found in notes.items()}
    if report.counts.obsolete > 0:
        states[RECOMPUTE] = CommandState(highlight=True,
                                         note=states.get(RECOMPUTE, CommandState()).note)
    return states


def indicator_tick() -> float | None:
    """La función del temporizador de los indicadores: :func:`refresh` y, si cambió lo que se
    ve, redibuja la barra de estado y la barra superior. Sigue cada :data:`INDICATOR_TICK_S` s
    mientras haya un proyecto con la procedencia; si no, se retira."""
    try:
        changed = refresh()
    except Exception:  # noqa: BLE001 - un temporizador que falla no tumba Blender
        LOGGER.exception("Falló la lectura de los indicadores de la procedencia")
        changed = False
    if changed:
        redraw()
    if _STATE.project is None:
        _retire(indicator_tick)
        return None
    return INDICATOR_TICK_S


def on_project_changed(project: Project | None) -> None:
    """Lo que se apunta en ``project_session``: olvida lo del proyecto anterior (también la
    lista de parámetros) y, con uno nuevo, pone el temporizador (lee en su primer tic, no al
    abrir: RNF-002-02)."""
    had = _forget()
    _clear_parameters()
    _clear_inputs()
    _forget_lineage()
    _retire(indicator_tick)
    if project is not None:
        bpy.app.timers.register(indicator_tick, first_interval=INDICATOR_TICK_S,
                                persistent=True)
    if had:
        redraw()


def _retire(function: Callable[[], float | None]) -> None:
    if bpy.app.timers.is_registered(function):
        bpy.app.timers.unregister(function)


def redraw() -> None:
    """Redibuja la barra de estado y la barra superior (el control 7) de todas las
    ventanas."""
    statusbar.redraw()
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in getattr(window.screen, "areas", ()):
            if area.type == "TOPBAR":
                area.tag_redraw()


def stale_count(_context: Any = None) -> int | None:
    """El número del control 7: lo obsoleto del proyecto, o ``None`` si no hay nada
    (``quick_access.set_count_provider``)."""
    found = _STATE.counts
    if found is None or found.obsolete <= 0:
        return None
    return found.obsolete


# El aviso de Ctrl+Z ---------------------------------------------------------------------------


def show_undo_notice(message: str) -> None:
    """Deja ``message`` en la barra de estado durante :data:`UNDO_NOTICE_S` s (RF-008-32: «Ctrl+Z
    no deshace la operación «gis.resample»: sigue en el proyecto»); uno nuevo sustituye al
    anterior."""
    _STATE.undo_text = message
    _STATE.undo_until = _clock() + UNDO_NOTICE_S
    _retire(expire_undo_notice)
    bpy.app.timers.register(expire_undo_notice, first_interval=UNDO_NOTICE_S, persistent=True)
    statusbar.redraw()


def undo_notice() -> str:
    """El aviso de Ctrl+Z que se ve ahora, o ""."""
    if _STATE.undo_text and _clock() < _STATE.undo_until:
        return _STATE.undo_text
    return ""


def expire_undo_notice() -> float | None:
    """La función del temporizador del aviso: al pasar su tiempo, lo quita, redibuja la barra
    de estado y se retira."""
    left = _STATE.undo_until - _clock()
    if _STATE.undo_text and left > 0:
        return left
    _STATE.undo_text = ""
    _retire(expire_undo_notice)
    statusbar.redraw()
    return None


# Campos de la barra de estado -----------------------------------------------------------------


def _counted(field: str, n: int) -> str:
    """El texto con número del campo ``field`` en el idioma de Geoblender, compuesto una vez
    por número e idioma (la barra lo pide en cada redibujo); con 1, en singular (T71: «⚠ 1
    entrada», «! 1 obsoleto»). Los plegados («⚠ n», «! n») no tienen número gramatical."""
    key = (field, n, language())
    found = _STATE.texts.get(key)
    if found is None:
        if len(_STATE.texts) >= MAX_TEXTS:
            _STATE.texts.clear()
        if field == FIELD_INPUTS:
            found = tr("⚠ 1 input") if n == 1 else tr("⚠ {n} inputs", n=n)
        elif field == FIELD_STALE:
            found = tr("! 1 stale") if n == 1 else tr("! {n} stale", n=n)
        elif field == FOLDED_INPUTS:
            found = tr("⚠ {n}", n=n)
        else:
            found = tr("! {n}", n=n)
        _STATE.texts[key] = found
    return found


def inputs_text(*, folded: bool = False) -> str:
    """«⚠ n entradas» (RF-008-16; «⚠ 1 entrada», T71) o, plegado (T69), «⚠ n»; "" si ninguna
    entrada cambió sin decidir."""
    found = _STATE.counts
    if found is None or found.inputs_changed <= 0:
        return ""
    return _counted(FOLDED_INPUTS if folded else FIELD_INPUTS, found.inputs_changed)


def stale_text(*, folded: bool = False) -> str:
    """«! n obsoletos» (RF-008-28; «! 1 obsoleto», T71) o, plegado (T69), «! n»; "" si no hay
    nada obsoleto."""
    found = _STATE.counts
    if found is None or found.obsolete <= 0:
        return ""
    return _counted(FOLDED_STALE if folded else FIELD_STALE, found.obsolete)


def checking_text(*, folded: bool = False) -> str:
    """«Comprobando el proyecto… 42 %» (RF-008-58) mientras hay una comprobación o, plegado
    (T69), solo «42 %»; si no, ""."""
    session = _session()
    shown = session.status_text() or ""
    if not shown or not folded:
        return shown
    return tr("{percent}%", percent=session.percent)


def _operator_properties(idname: str) -> frozenset[str]:
    """Las propiedades del operador registrado de ``idname`` (las de un provisional, ninguna)."""
    cls = registered_class(idname)
    if cls is None:
        return frozenset()
    found = _STATE.properties.get(cls)
    if found is None:
        group, _, name = idname.partition(".")
        try:
            rna = getattr(getattr(bpy.ops, group), name).get_rna_type()
            found = frozenset(rna.properties.keys())
        except (AttributeError, KeyError, RuntimeError):
            found = frozenset()
        _STATE.properties[cls] = found
    return found


def _operator(layout: Any, idname: str, shown: str, *, icon: str = "NONE",
              emboss: bool = True, enabled: bool = True, **values: Any) -> None:
    """Un botón de una orden del catálogo con ``shown`` (desactivado si su clase real aún no
    ha llegado o sin ``enabled``) y las propiedades de ``values`` que tenga."""
    sub = layout.row(align=True)
    sub.enabled = enabled and is_available(idname)
    properties = sub.operator(idname, text=shown, icon=icon, translate=False, emboss=emboss)
    if values:
        names = _operator_properties(idname)
        for name, value in values.items():
            if name in names:
                setattr(properties, name, value)


def _draw_inputs(layout: Any, _context: Any, *, folded: bool = False) -> None:
    shown = inputs_text(folded=folded)
    if shown:
        _operator(layout, SHOW_INPUTS, shown, emboss=False)


def _draw_stale(layout: Any, _context: Any, *, folded: bool = False) -> None:
    shown = stale_text(folded=folded)
    if shown:
        sub = layout.row(align=True)
        sub.enabled = is_available(STALE_PANEL)
        sub.popover(STALE_PANEL, text=shown, translate=False)


def _draw_checking(layout: Any, _context: Any, *, folded: bool = False) -> None:
    shown = checking_text(folded=folded)
    if shown:
        row = layout.row(align=True)
        row.label(text=shown, translate=False)
        _operator(row, CANCEL_CHECKS, "", icon=CANCEL_ICON, emboss=False)


def _draw_undo(layout: Any, _context: Any, *, folded: bool = False) -> None:
    shown = undo_notice()
    if shown:
        row = layout.row(align=True)
        if folded:
            row.ui_units_x = UNDO_FOLDED_UNITS  # Blender corta el texto con «…»
        row.label(text=shown, icon=UNDO_ICON, translate=False)


def _inputs_px(_context: Any, *, folded: bool = False) -> float:
    shown = inputs_text(folded=folded)
    return statusbar.button_px(shown) if shown else 0.0


def _stale_px(_context: Any, *, folded: bool = False) -> float:
    shown = stale_text(folded=folded)
    return statusbar.popover_px(shown) if shown else 0.0


def _checking_px(_context: Any, *, folded: bool = False) -> float:
    shown = checking_text(folded=folded)
    return statusbar.label_px(shown) + statusbar.button_px() if shown else 0.0


def _undo_px(_context: Any, *, folded: bool = False) -> float:
    shown = undo_notice()
    if not shown:
        return 0.0
    if folded:
        return statusbar.units_px(UNDO_FOLDED_UNITS)
    return statusbar.label_px(shown, icon=True)


_Draw = Callable[..., None]
_Width = Callable[..., float]
FIELDS: tuple[tuple[str, float, _Draw, _Width], ...] = (
    (FIELD_INPUTS, 62.0, _draw_inputs, _inputs_px),
    (FIELD_STALE, 63.0, _draw_stale, _stale_px),
    (FIELD_CHECKING, 64.0, _draw_checking, _checking_px),
    (FIELD_UNDO, 65.0, _draw_undo, _undo_px),
)
"""Los campos: clave, sitio en la barra (tras los de la 003 y antes de los trabajos de la
004, como en AR §6), dibujo y ancho a escala 1,0 (0 sin nada que mostrar); los dos admiten
``folded=True``, su forma plegada (T69)."""
FIELD_KEYS: tuple[str, ...] = tuple(key for key, *_rest in FIELDS)


# Lo obsoleto ----------------------------------------------------------------------------------


def _stale_icon() -> dict[str, Any]:
    return icons.icon_kwargs(STALE_ICON, native_icon(STALE_FALLBACK))


def _row_name(row: Any) -> str:
    """El nombre de una fila: el del dato o, de una operación, su nombre visible."""
    if row.item_kind == "operation":
        defn = contract.OPERATIONS.get(row.op_type)
        if defn is not None and defn.label_msgid:
            return text(defn.label_msgid)
    return row.name


def _draw_stale_row(layout: Any, row: Any) -> None:
    line = layout.row(align=True)
    line.label(text=_row_name(row), translate=False, **_stale_icon())
    line.label(text=row.module, translate=False)
    if row.review:
        line.label(text=tr("review"), translate=False)
        _operator(line, ACCEPT_REVIEW, text(catalog().commands[ACCEPT_REVIEW].label),
                  operation_uid=row.operation_uid)
    else:
        _operator(line, RECOMPUTE, tr("Recompute"), scope="ITEM", subject_uid=row.uid)
    cause = layout.row()
    cause.active = False
    cause.label(text=row.text, translate=False)


def _draw_unusable_row(layout: Any, row: Any, writable: bool) -> None:
    """Un dato que no se puede usar (T54; RF-008-56, RF-008-57): su nombre (en alerta), su
    módulo y lo que se ofrece para resolverlo (Aceptar la edición, Recalcular, Reimportar: la
    orden ``geoblender.core_resolve_dataset`` con esa decisión, que abre su diálogo), y debajo
    su aviso."""
    from ...core.datasets.external import offer_label  # al usarlo: registrar no lo carga

    line = layout.row(align=True)
    name = line.row(align=True)
    name.alert = True
    name.label(text=row.name, translate=False)
    line.label(text=row.module, translate=False)
    shown = language()
    for offer in filter(None, row.offers.split(",")):
        _operator(line, RESOLVE_DATASET, offer_label(offer, shown), enabled=writable,
                  dataset_uid=row.uid, decision=offer.upper())
    note = layout.row()
    note.active = False
    note.label(text=row.text, translate=False)


def draw_stale(layout: Any, context: Any) -> None:
    """El contenido de :class:`GEOBLENDER_PT_core_stale` (RF-008-28; y, T54, lo que no se
    puede usar, RF-008-56 y RF-008-57)."""
    reason = _session().unavailable()
    if reason is not None:
        layout.label(text=reason, icon="INFO", translate=False)
        return
    found = _STATE.counts
    total = found.obsolete if found is not None else 0
    layout.label(text=tr("Refresh · stale ({n})", n=total), translate=False, **_stale_icon())
    view = getattr(getattr(context, "window_manager", None), WINDOW_MANAGER_PROPERTY, None)
    rows = view.stale if view is not None and total > 0 else ()
    if not len(rows):
        layout.label(text=tr("Nothing is stale"), translate=False)
    else:
        column = layout.column()
        for row in rows:
            _draw_stale_row(column, row)
        hidden = total - len(rows)
        if hidden > 0:
            column.label(text=tr("… and {count} more", count=hidden), translate=False)
    blocked = view.unusable if view is not None else ()
    if len(blocked):
        layout.separator(type="LINE")
        layout.label(text=tr("Datasets that cannot be used"), translate=False)
        column = layout.column()
        writable = _write_unavailable() is None
        for row in blocked:
            _draw_unusable_row(column, row, writable)
    layout.separator(type="LINE")
    draw_command(layout, RECOMPUTE, context=context)


class GEOBLENDER_PT_core_stale(bpy.types.Panel):
    """What is stale and why"""

    bl_idname = STALE_PANEL
    bl_label = "Stale results"
    bl_translation_context = "Geoblender"
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = STALE_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_stale(self.layout, context)


# Parámetros del proyecto (T50) -----------------------------------------------------------------


def _write_unavailable() -> str | None:
    """Por qué no se pueden cambiar ni confirmar los parámetros ahora (sin proyecto, sin la
    procedencia o en solo lectura), o ``None``."""
    from ..ops import core_provenance  # al usarlo: bl/ops importa bl/ui (ARQ-08)

    return core_provenance.write_unavailable()


def _project() -> Project | None:
    """El proyecto de la sesión, si tiene la procedencia (también en solo lectura)."""
    session = _session()
    return session.project if session.unavailable() is None else None


def _filters(view: Any) -> ParameterFilter:
    """Los filtros de la lista (``core.params``; «Cualquiera» no filtra)."""
    module = None if view.filter_module == FILTER_ALL else view.filter_module
    kind = None if view.filter_kind == FILTER_ALL else ParamKind[view.filter_kind]
    mark = None if view.filter_mark == FILTER_ALL else ParamMark[view.filter_mark]
    return ParameterFilter(module=module, kind=kind, mark=mark)


def _selected(view: Any) -> Any | None:
    """La fila seleccionada de la lista de parámetros, o ``None``."""
    rows = view.parameters
    index = view.parameter_index
    return rows[index] if 0 <= index < len(rows) else None


def _local(moment: str, pattern: str = "%d/%m/%Y") -> str:
    """Una hora UTC guardada, en hora local como la lee una persona (``24/09/2026``)."""
    try:
        return parse_utc(moment).astimezone().strftime(pattern)
    except ValueError:
        return moment


def fill_parameters() -> int:
    """Regenera las filas de la lista de parámetros desde el proyecto de la sesión, con los
    filtros de la vista (RF-008-06; ``ParameterStore.list``), conserva el seleccionado si
    sigue en la lista y lee su historial (:func:`fill_history`). Sin proyecto con la
    procedencia, la lista queda vacía. Devuelve cuántas filas hay. Si no se puede leer el
    proyecto, el error sigue y las filas quedan como estaban."""
    view = _view()
    if view is None:
        return 0
    project = _project()
    found = [] if project is None else ParameterStore(project).list(_filters(view))
    chosen = _selected(view)
    key = None if chosen is None else chosen.key
    shown = language()
    _STATE.filling = True
    try:
        rows = view.parameters
        rows.clear()
        for item in found:
            record = item.record
            row = rows.add()
            row.uid = record.uid
            row.key = record.key
            row.module = record.module
            row.value = shown_value(record.value, record.unit, shown)  # como una cifra (T71)
            row.kind = str(record.kind)
            row.unconfirmed = record.unconfirmed
            row.review = ParamMark.REVIEW in item.marks
            row.review_text = item.review_text
            row.source = record.source
            row.decided_by = record.decided_by
            row.decided_at = _local(record.decided_at)
        keys = [item.record.key for item in found]
        view.parameter_index = keys.index(key) if key in keys else 0
    finally:
        _STATE.filling = False
    fill_history()
    return len(found)


def fill_history() -> None:
    """Regenera el historial del parámetro seleccionado (RF-008-06; ``ParameterStore.history``)
    y su aviso de divergencia (RF-008-59: el de su última cifra calculada, con la cifra que se
    adoptaría). Si no se puede leer el proyecto, el error sigue."""
    view = _view()
    if view is None or _STATE.filling:
        return
    project = _project()
    chosen = _selected(view)
    entries: list[Any] = []
    warning = None
    if project is not None and chosen is not None:
        from ...core.provenance.figures import parameter_divergence  # al usarlo

        with project.read() as conn:
            entries = ParameterStore(project).history(chosen.key, conn=conn)
            warning = parameter_divergence(conn, chosen.uid)
    history = view.parameter_history
    history.clear()
    shown = language()
    for entry in entries:
        row = history.add()
        row.rev = entry.rev
        row.action = str(entry.action)
        row.value = shown_value(entry.value, entry.unit, shown)
        row.kind = str(entry.kind)
        row.unconfirmed = entry.unconfirmed
        row.decided_by = entry.decided_by
        row.decided_at = _local(entry.decided_at)
        row.reason = entry.reason or ""
        row.changed_by = entry.changed_by
        row.changed_at = _local(entry.changed_at, "%d/%m/%Y %H:%M")
    view.history_index = max(0, len(history) - 1)
    view.parameter_divergence = "" if warning is None else warning.render(shown)
    view.parameter_figure_uid = "" if warning is None else warning.figure_uid


def _clear_parameters() -> None:
    """Vacía la lista de parámetros, el historial y el aviso (otro proyecto, ninguno)."""
    view = _view()
    if view is None or not (len(view.parameters) or len(view.parameter_history)
                            or view.parameter_divergence):
        return
    _STATE.filling = True
    try:
        view.parameters.clear()
        view.parameter_history.clear()
        view.parameter_index = 0
        view.parameter_divergence = ""
        view.parameter_figure_uid = ""
    finally:
        _STATE.filling = False


def parameters_changed() -> None:
    """Un filtro cambió (``bl.props.provenance``): :func:`fill_parameters`; si no se puede
    leer el proyecto, queda en el registro técnico."""
    if _STATE.filling:
        return
    try:
        fill_parameters()
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo leer la lista de parámetros del proyecto", exc_info=True)


def selection_changed() -> None:
    """Cambió el seleccionado (``bl.props.provenance``): :func:`fill_history`."""
    if _STATE.filling:
        return
    try:
        fill_history()
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo leer el historial del parámetro", exc_info=True)


def badge(kind: str) -> str:
    """La insignia de un tipo ([MED], [CAL], [ADO] o [HIP]) en el idioma de Geoblender."""
    if kind == ParamKind.MEDIDO:
        return tr("[MEA]")
    if kind == ParamKind.CALCULADO:
        return tr("[CAL]")
    if kind == ParamKind.ADOPTADO:
        return tr("[ADO]")
    return tr("[HYP]")


def badge_icon(kind: str) -> dict[str, Any]:
    """El icono de la insignia de un tipo (T70; RF-008-02, RF-008-06, RF-008-29): de [HIP], el
    ámbar propio :data:`HYPOTHESIS_ICON` (``{"icon_value": n}``) o, si no se puede mostrar,
    su reserva nativa ámbar; de los demás, un hueco del mismo ancho (``BLANK1``)."""
    if kind == ParamKind.HIPOTESIS:
        return icons.icon_kwargs(HYPOTHESIS_ICON, native_icon(HYPOTHESIS_FALLBACK))
    return {"icon": "BLANK1"}


def _badge_cell(layout: Any, kind: str, units: float = BADGE_UNITS) -> None:
    """La columna de la insignia de tipo ``kind`` con su icono y sin alerta (T70): el rojo de
    ``alert`` es para los errores y los cambios."""
    cell = layout.row(align=True)
    cell.ui_units_x = units
    cell.label(text=badge(kind), translate=False, **badge_icon(kind))


def _action_text(action: str) -> str:
    if action == HistoryAction.DEFAULT:
        return tr("Default value")
    if action == HistoryAction.CREATE:
        return tr("Created")
    if action == HistoryAction.CONFIRM:
        return tr("Confirmed")
    return tr("Changed")


def _cell(layout: Any, shown: str, units: float, *, alert: bool = False) -> None:
    """Una columna de una fila de lista: ``shown`` con ``units`` de ancho."""
    cell = layout.row(align=True)
    cell.ui_units_x = units
    cell.alert = alert
    cell.label(text=shown, translate=False)


def _marks_text(unconfirmed: bool, review: bool = False) -> str:
    marks = []
    if unconfirmed:
        marks.append(tr("unconfirmed"))
    if review:
        marks.append(tr("review"))
    return " · ".join(marks)


def draw_parameter_row(layout: Any, row: Any) -> None:
    """Una fila de la lista de parámetros (RF-008-06): clave, valor con su unidad, insignia de
    tipo ([HIP] con su icono ámbar), marcas, origen, decisor y fecha."""
    line = layout.row(align=True)
    key, value, kind, marks, source, decided_by, decided_at = PARAMETER_COLUMNS
    _cell(line, row.key, key)
    _cell(line, row.value, value)
    _badge_cell(line, row.kind, kind)
    _cell(line, _marks_text(row.unconfirmed, row.review), marks, alert=row.review)
    _cell(line, row.source, source)
    _cell(line, row.decided_by, decided_by)
    _cell(line, row.decided_at, decided_at)


def draw_history_row(layout: Any, row: Any) -> None:
    """Una fila del historial (RF-008-02, RF-008-06): revisión, qué fue, valor, insignia ([HIP]
    con su icono ámbar), «sin confirmar», decisor y fecha de la decisión, motivo, y quién y
    cuándo lo registró."""
    line = layout.row(align=True)
    rev, action, value, kind, marks, decided_by, decided_at, reason, by, at = HISTORY_COLUMNS
    _cell(line, str(row.rev), rev)
    _cell(line, _action_text(row.action), action)
    _cell(line, row.value, value)
    _badge_cell(line, row.kind, kind)
    _cell(line, _marks_text(row.unconfirmed), marks)
    _cell(line, row.decided_by, decided_by)
    _cell(line, row.decided_at, decided_at)
    _cell(line, row.reason, reason)
    _cell(line, row.changed_by, by)
    _cell(line, row.changed_at, at)


def _draw_selected(layout: Any, view: Any, row: Any, blocked: str | None) -> None:
    """Lo del parámetro seleccionado: su decisión, lo que hay que revisar, su aviso de
    divergencia, su historial y Cambiar y Confirmar (desactivados con ``blocked``)."""
    details = layout.column(align=True)
    details.label(text=row.key, translate=False)
    details.label(text=tr("Source: {source}", source=row.source), translate=False)
    details.label(text=tr("Decided by {who} on {date}", who=row.decided_by,
                          date=row.decided_at), translate=False)
    if row.review and row.review_text:
        note = details.row()
        note.alert = True
        note.label(text=row.review_text, icon="ERROR", translate=False)
    writable = blocked is None
    if view.parameter_divergence:
        warning = layout.row()
        warning.alert = True
        warning.label(text=view.parameter_divergence, icon="ERROR", translate=False)
        _operator(layout, SET_PARAMETER, tr("Use the calculated value…"), enabled=writable,
                  key=row.key, from_figure_uid=view.parameter_figure_uid)
    layout.label(text=tr("History"), translate=False)
    layout.template_list(HISTORY_LIST, "", view, "parameter_history", view, "history_index",
                         rows=HISTORY_ROWS)
    buttons = layout.row(align=True)
    commands = catalog().commands
    _operator(buttons, SET_PARAMETER, text(commands[SET_PARAMETER].label), enabled=writable,
              key=row.key)
    _operator(buttons, CONFIRM_PARAMETER, text(commands[CONFIRM_PARAMETER].label),
              enabled=writable and (row.unconfirmed or row.review), key=row.key)
    if blocked is not None:
        layout.label(text=blocked, icon="LOCKED", translate=False)


def draw_parameters(layout: Any, context: Any) -> None:
    """El contenido de :class:`GEOBLENDER_PT_core_parameters` (RF-008-06, RF-008-59)."""
    layout.label(text=tr("Project parameters"), translate=False)
    reason = _session().unavailable()
    if reason is not None:
        layout.label(text=reason, icon="INFO", translate=False)
        return
    view = getattr(getattr(context, "window_manager", None), WINDOW_MANAGER_PROPERTY, None)
    if view is None:
        return
    filters = layout.row(align=True)
    filters.prop(view, "filter_module", text=tr("Module"), translate=False)
    filters.prop(view, "filter_kind", text=tr("Type"), translate=False)
    filters.prop(view, "filter_mark", text=tr("Mark"), translate=False)
    layout.template_list(PARAMETERS_LIST, "", view, "parameters", view, "parameter_index",
                         rows=PARAMETER_ROWS)
    row = _selected(view)
    if row is None:
        layout.label(text=tr("No parameters"), translate=False)
        return
    _draw_selected(layout, view, row, _write_unavailable())


class GEOBLENDER_UL_core_parameters(bpy.types.UIList):
    """The project parameters"""

    bl_idname = PARAMETERS_LIST

    def draw_item(self, _context: Any, layout: Any, _data: Any, item: Any, _icon: int,
                  _active_data: Any, _active_property: str, _index: int = 0,
                  _flt_flag: int = 0) -> None:
        draw_parameter_row(layout, item)


class GEOBLENDER_UL_core_parameter_history(bpy.types.UIList):
    """The history of the selected parameter"""

    bl_idname = HISTORY_LIST

    def draw_item(self, _context: Any, layout: Any, _data: Any, item: Any, _icon: int,
                  _active_data: Any, _active_property: str, _index: int = 0,
                  _flt_flag: int = 0) -> None:
        draw_history_row(layout, item)


class GEOBLENDER_PT_core_parameters(bpy.types.Panel):
    """Parameters with their type, provenance and history"""

    bl_idname = PARAMETERS_PANEL
    bl_label = "Project parameters"
    bl_translation_context = "Geoblender"
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = PARAMETERS_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_parameters(self.layout, context)


# Registro de entradas (T51) ---------------------------------------------------------------------


def _delivery_date(day: str | None) -> str:
    """La fecha de entrega guardada («2026-09-24») como la lee una persona («24/09/2026»);
    "" sin fecha."""
    if not day:
        return ""
    year, month, rest = day.split("-", 2)
    return f"{rest}/{month}/{year}"


def fill_inputs() -> int:
    """Regenera las filas del registro de entradas desde el proyecto de la sesión (RF-008-16;
    ``core.inputs.list_inputs``): todas las entradas, también las sustituidas y las
    descartadas, con su estado registrado, su tipo, su entrega, sus CRS declarados (como se
    leen en el idioma de Geoblender), su hash de contenido abreviado y su original; conserva
    la seleccionada si sigue. Sin proyecto con la procedencia, la lista queda vacía. Devuelve
    cuántas filas hay. Si no se puede leer el proyecto, el error sigue y las filas quedan como
    estaban."""
    view = _view()
    if view is None:
        return 0
    project = _project()
    found: list[Any] = []
    tables: tuple[Any, ...] = ()
    if project is not None:
        from ...core.datasets.orphans import unregistered_tables  # al usarlo

        with project.read() as conn:
            found = list_inputs(conn)
            tables = unregistered_tables(conn)
    _fill_unregistered(view, tables)
    rows = view.inputs
    index = view.input_index
    chosen = rows[index].uid if 0 <= index < len(rows) else None
    shown = language()
    rows.clear()
    for record in found:
        row = rows.add()
        row.uid = record.uid
        row.name = record.name
        row.status = str(record.status)
        row.kind = record.kind
        row.module = record.module
        row.received_at = _delivery_date(record.received_at)
        row.received_from = record.received_from or ""
        row.crs_h = crs_text(record.crs_h, shown)
        row.crs_v = crs_text(record.crs_v, shown)
        row.content_hash = record.content_sha256[:HASH_CHARS]
        row.original = str(record.original)
    uids = [record.uid for record in found]
    view.input_index = uids.index(chosen) if chosen in uids else 0
    return len(found)


def _fill_unregistered(view: Any, tables: Sequence[Any]) -> None:
    """Regenera las capas y tablas del proyecto sin registrar (RF-008-62; T54)."""
    rows = view.unregistered
    rows.clear()
    for item in tables:
        row = rows.add()
        row.kind = str(item.kind)
        row.name = item.name
        row.registrable = item.registrable


def _refill_inputs() -> None:
    """Con el registro de entradas abierto (con filas), las vuelve a leer: el proyecto cambió
    (una comprobación, una decisión) o el idioma. Si no se puede leer, queda en el registro
    técnico y se intenta en la próxima."""
    view = _view()
    if view is None or not len(view.inputs):
        return
    try:
        fill_inputs()
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.debug("No se pudo leer el registro de entradas; se intenta después",
                     exc_info=True)


def _clear_inputs() -> None:
    """Vacía el registro de entradas (otro proyecto, ninguno)."""
    view = _view()
    if view is not None and len(view.inputs):
        view.inputs.clear()
        view.input_index = 0
    if view is not None and len(view.unregistered):
        view.unregistered.clear()


def input_status(row: Any) -> str:
    """El estado que se ve de una fila del registro: de una entrada activa, lo que la sesión
    sabe ahora y no se guarda («checking» mientras una comprobación la tiene pendiente,
    «unreachable» si no se encontró su fuente; plan D7); si no, el registrado."""
    if row.status in _ACTIVE_INPUTS:
        state = _session().input_state(row.uid)
        if state is not None:
            return state
    return str(row.status)


def status_text(status: str) -> str:
    """Un estado de una entrada como se lee: «vigente», «comprobando», «cambiada», «cambiada ·
    se mantiene la copia», «no localizable», «sustituida» o «descartada · registro, no usar»
    (RF-008-16, RF-008-55), en el idioma de Geoblender."""
    return render(f"core.input_status_{status}", language=language())


def kind_text(kind: str) -> str:
    """El tipo de una entrada (``core.inputs.INPUT_KINDS``) como se lee."""
    match kind:
        case "raster":
            return tr("raster")
        case "vector":
            return tr("vector")
        case "table":
            return tr("table")
        case "drillholes":
            return tr("drillholes")
        case "mesh":
            return tr("mesh")
        case "point_cloud":
            return tr("point cloud")
        case "document":
            return tr("document")
        case "other":
            return tr("other")
    return kind


def original_text(original: str) -> str:
    """Si la entrada guarda su original (RF-008-53): «guardado», «no guardado» (pasa del
    límite) o «—» (no se guarda: un ráster, una nube, una capa)."""
    if original == OriginalState.STORED:
        return tr("stored")
    if original == OriginalState.TOO_LARGE:
        return tr("not stored")
    return NOT_SHOWN


def draw_input_row(layout: Any, row: Any) -> None:
    """Una fila del registro de entradas (RF-008-16): nombre, estado («cambiada» en alerta),
    tipo, fecha de entrega, quién la entrega, CRS horizontal y vertical declarados, hash de
    contenido abreviado y original."""
    line = layout.row(align=True)
    name, status, kind, received_at, received_from, crs_h, crs_v, digest, original = \
        INPUT_COLUMNS
    shown = input_status(row)
    _cell(line, row.name, name)
    _cell(line, status_text(shown), status, alert=shown == InputStatus.CHANGED)
    _cell(line, kind_text(row.kind), kind)
    _cell(line, row.received_at or NOT_SHOWN, received_at)
    _cell(line, row.received_from or NOT_SHOWN, received_from)
    _cell(line, row.crs_h, crs_h)
    _cell(line, row.crs_v, crs_v)
    _cell(line, row.content_hash, digest)
    _cell(line, original_text(row.original), original)


def _selected_input(view: Any) -> Any | None:
    rows = view.inputs
    index = view.input_index
    return rows[index] if 0 <= index < len(rows) else None


def _draw_input_buttons(layout: Any, row: Any, writable: bool) -> None:
    """Las órdenes de la entrada seleccionada (plan §5.5; T52): Actualizar de una cambiada,
    también si se mantiene su copia (no si no se encuentra su fuente, RF-008-13), Mantener la
    copia de una cambiada, Descartar… de una activa y Editar… de cualquiera; cada una abre su
    diálogo con el uid de la entrada."""
    from ..ops.core_provenance import UNREACHABLE  # al usarlo: bl/ops importa bl/ui

    buttons = layout.row(align=True)
    changed = row.status == InputStatus.CHANGED
    updatable = changed or row.status == InputStatus.KEPT
    found = input_status(row) != UNREACHABLE
    shown = language()
    commands = catalog().commands
    _operator(buttons, RESOLVE_INPUT, render("core.choice_update", language=shown),
              enabled=writable and updatable and found, input_uid=row.uid, decision="UPDATE")
    _operator(buttons, RESOLVE_INPUT, render("core.choice_keep", language=shown),
              enabled=writable and changed, input_uid=row.uid, decision="KEEP")
    _operator(buttons, DISCARD_INPUT, text(commands[DISCARD_INPUT].label),
              enabled=writable and row.status in _ACTIVE_INPUTS, input_uid=row.uid)
    _operator(buttons, EDIT_INPUT, text(commands[EDIT_INPUT].label), enabled=writable,
              input_uid=row.uid)


def draw_inputs(layout: Any, context: Any) -> None:
    """El contenido de :class:`GEOBLENDER_PT_core_inputs` (RF-008-16, RF-008-13, RF-008-09):
    la cabecera de las columnas, la lista, las órdenes de la seleccionada y Comprobar cambios en
    las entradas; en solo lectura, desactivadas y con el motivo."""
    layout.label(text=tr("Input register"), translate=False)
    reason = _session().unavailable()
    if reason is not None:
        layout.label(text=reason, icon="INFO", translate=False)
        return
    view = getattr(getattr(context, "window_manager", None), WINDOW_MANAGER_PROPERTY, None)
    if view is None:
        return
    header = layout.row(align=True)
    titles = (tr("Name"), tr("Status"), tr("Type"), tr("Delivered on"), tr("Delivered by"),
              tr("Horizontal CRS"), tr("Vertical CRS"), tr("Content hash"), tr("Original"))
    for title, units in zip(titles, INPUT_COLUMNS, strict=True):
        _cell(header, title, units)
    layout.template_list(INPUTS_LIST, "", view, "inputs", view, "input_index",
                         rows=INPUT_ROWS)
    blocked = _write_unavailable()
    row = _selected_input(view)
    if row is None:
        layout.label(text=tr("No inputs"), translate=False)
    else:
        _draw_input_buttons(layout, row, blocked is None)
    layout.separator(type="LINE")
    _operator(layout, CHECK_INPUTS, text(catalog().commands[CHECK_INPUTS].label),
              enabled=blocked is None)
    _draw_unregistered(layout, view, blocked is None)
    if blocked is not None:
        layout.label(text=blocked, icon="LOCKED", translate=False)


def _draw_unregistered(layout: Any, view: Any, writable: bool) -> None:
    """Las capas y tablas del proyecto sin registrar, creadas desde QGIS (T54; RF-008-62): cada
    una con Registrar como entrada… (si es una capa o una tabla de ``gpkg_contents``) e
    Ignorar…, que abren el diálogo de ``geoblender.core_resolve_unregistered``."""
    rows = view.unregistered
    if not len(rows):
        return
    layout.separator(type="LINE")
    layout.label(text=tr("Layers and tables of the project not registered"), translate=False)
    for row in rows:
        line = layout.row(align=True)
        line.label(text=row.name, translate=False)
        kind = row.kind.upper()
        _operator(line, RESOLVE_UNREGISTERED, tr("Register as input…"),
                  enabled=writable and row.registrable, kind=kind, name=row.name,
                  decision="REGISTER")
        _operator(line, RESOLVE_UNREGISTERED, tr("Ignore…"), enabled=writable, kind=kind,
                  name=row.name, decision="IGNORE")


class GEOBLENDER_UL_core_inputs(bpy.types.UIList):
    """The registered inputs"""

    bl_idname = INPUTS_LIST

    def draw_item(self, _context: Any, layout: Any, _data: Any, item: Any, _icon: int,
                  _active_data: Any, _active_property: str, _index: int = 0,
                  _flt_flag: int = 0) -> None:
        draw_input_row(layout, item)


class GEOBLENDER_PT_core_inputs(bpy.types.Panel):
    """Registered inputs with their content hash"""

    bl_idname = INPUTS_PANEL
    bl_label = "Input register"
    bl_translation_context = "Geoblender"
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = INPUTS_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_inputs(self.layout, context)


# Grafo de operaciones y procedencia (T55) -----------------------------------------------------


def lineage_error() -> str:
    """Por qué la última búsqueda de la procedencia no dio una cadena (lo buscado no es una
    cifra, un dato ni una operación del proyecto), o ""."""
    view = _view()
    return "" if view is None else view.lineage_error


def _clear_lineage(view: Any) -> None:
    """Vacía la procedencia, lo encontrado y el motivo (no la búsqueda)."""
    if len(view.lineage):
        view.lineage.clear()
    if len(view.lineage_matches):
        view.lineage_matches.clear()
    view.lineage_index = 0
    view.lineage_more = 0
    view.lineage_error = ""


def _forget_lineage() -> None:
    """Vacía la procedencia y su búsqueda (otro proyecto, ninguno)."""
    view = _view()
    if view is None:
        return
    _clear_lineage(view)
    if view.lineage_uid:
        _STATE.searching = True
        try:
            view.lineage_uid = ""
        finally:
            _STATE.searching = False


def search_lineage(wanted: str | None = None) -> int:
    """La procedencia de ``wanted`` (por defecto, la búsqueda del panel; si se da, pasa a ser
    la búsqueda) en las filas del panel (RF-008-29, RF-008-31): el uid de una cifra, de un dato
    o de una operación, o el nombre de un dato vivo (``core.provenance.lineage.lineage``). Si
    no es nada de eso, quedan el motivo (:func:`lineage_error`) y lo que lo contiene: las cifras
    vigentes y los datos (``search_items``). Sin proyecto con la procedencia o sin nada que
    buscar, todo vacío. Devuelve cuántas filas hay. Si no se puede leer el proyecto, el error
    sigue (y el panel queda vacío)."""
    view = _view()
    if view is None:
        return 0
    if wanted is not None and view.lineage_uid != wanted:
        _STATE.searching = True
        try:
            view.lineage_uid = wanted
        finally:
            _STATE.searching = False
    _clear_lineage(view)
    project = _project()
    shown_text = view.lineage_uid.strip()
    if project is None or not shown_text:
        return 0
    from ...core.provenance.lineage import lineage, search_items  # al usarlo
    from ...core.provenance.messages import ProvenanceError

    shown = language()
    try:
        tree = lineage(project, shown_text, language=shown)
    except ProvenanceError as exc:
        if exc.code != "core.lineage_unknown":
            raise
        view.lineage_error = render(exc.code, language=shown, **exc.values)
        for match in search_items(project, shown_text, language=shown):
            row = view.lineage_matches.add()
            row.kind = str(match.kind)
            row.uid = match.uid
            row.text = match.text
        return 0
    found = tree.rows()
    for item in found[:MAX_LINEAGE_ROWS]:
        text_shown, param_kind, marks, note = _lineage_cells(tree, item, shown)
        row = view.lineage.add()
        row.depth = item.depth
        row.kind = str(item.kind)
        row.uid = item.uid
        row.role = item.role or ""
        row.repeated = item.repeated
        row.text = text_shown
        row.param_kind = param_kind
        row.marks = ",".join(str(mark) for mark in marks)
        row.note = note
    view.lineage_more = max(0, len(found) - MAX_LINEAGE_ROWS)
    return min(len(found), MAX_LINEAGE_ROWS)


def lineage_searched() -> None:
    """Cambió la búsqueda del panel (``bl.props.provenance``): :func:`search_lineage`; si no
    se puede leer el proyecto, queda en el registro técnico."""
    if _STATE.searching:
        return
    try:
        search_lineage()
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo leer la procedencia del proyecto", exc_info=True)


def _role(role: str | None) -> str:
    return f" ({role})" if role else ""


def _operation_text(node: Any, shown: str) -> str:
    """Un eslabón: su nombre, su tipo con la versión de su algoritmo, la versión de Geoblender,
    quién y cuándo la lanzó y, si lo suyo no es un resultado guardado, cómo se presenta."""
    defn = contract.OPERATIONS.get(node.op_type)
    name = text(defn.label_msgid) if defn is not None and defn.label_msgid else node.op_type
    parts = [name, f"{node.op_type} {node.op_version}",
             f"Geoblender {node.geoblender_version}", node.user_host,
             _local(node.started_at, "%d/%m/%Y %H:%M")]
    if not node.result.saved:
        parts.append(node.result.text(language=shown))
    return " · ".join(parts)


def _parameter_text(node: Any, shown: str) -> str:
    """Un parámetro que leyó un eslabón: su nombre, su clave y el valor que leyó con su
    unidad."""
    from ...core.params import DEFINITIONS  # al usarlo: las definiciones de los módulos

    definition = DEFINITIONS.get(node.key)
    label = text(definition.label_msgid) if definition is not None and \
        definition.label_msgid else ""
    name = f"{label} · {node.key}" if label else node.key
    return f"{name} = {node.value_text(language=shown)}"


def _parameter_note(node: Any, shown: str) -> str:
    """Lo de hoy de un parámetro, si no es lo que leyó el eslabón (otro valor, otro tipo u
    otra marca: RF-008-31 cuenta lo de hoy), y si la operación de la que sale un CALCULADO
    está obsoleta."""
    notes = []
    if node.changed or node.current_kind != node.kind or \
            node.current_unconfirmed != node.unconfirmed:
        today = f"{node.current_value_text(language=shown)} {badge(node.current_kind)}"
        if node.current_unconfirmed:
            today += f" {tr('unconfirmed')}"
        notes.append(tr("today: {value}", value=today))
    if node.source_stale:
        notes.append(tr("its source operation is stale"))
    return " · ".join(notes)


def _lineage_cells(tree: Any, item: Any, shown: str) -> tuple[str, str, tuple[str, ...], str]:
    """De una fila de la procedencia (``core.provenance.lineage.LineageRow``): su texto, el
    tipo de su insignia (de una cifra o un parámetro), sus marcas y su nota."""
    node = item.node
    match str(item.kind):
        case "figure":
            note = "" if tree.result.saved else tree.result.text(language=shown)
            return node.text(language=shown), str(node.kind), tree.marks.marks, note
        case "operation":
            notes = [node.stale_text] if node.stale_text else []
            if node.review:
                notes.append(tr("review"))
            return (_operation_text(node, shown), "", ("stale",) if node.stale else (),
                    " · ".join(notes))
        case "parameter":
            return (_parameter_text(node, shown), str(node.kind),
                    ("unconfirmed",) if node.unconfirmed else (), _parameter_note(node, shown))
        case "input":
            return node.text(language=shown) + _role(item.role), "", (), ""
    shown_text = node.name + _role(item.role)
    if not node.current:
        shown_text += f" · {tr('earlier version')}"
    return shown_text, "", tree.marks.marks if item.depth == 0 else (), ""


def lineage_visible(rows: Sequence[Any]) -> list[bool]:
    """Qué filas de la procedencia se ven: las de debajo de un nudo plegado (``expanded``
    falso), no."""
    found: list[bool] = []
    folded: int | None = None
    for row in rows:
        if folded is not None and row.depth > folded:
            found.append(False)
            continue
        found.append(True)
        folded = None if row.expanded else row.depth
    return found


def _mark_text(kind: str, mark: str) -> str:
    """Una marca de una fila: de un parámetro, «sin confirmar»; de una cifra o un dato, la de
    RF-008-31 («depende de una hipótesis», «depende de un valor sin confirmar», «obsoleta»)."""
    if kind == "parameter":
        return tr("unconfirmed")
    return render(f"core.mark_{mark}", language=language())


def draw_lineage_row(layout: Any, row: Any, *, children: bool) -> None:
    """Una fila de la procedencia (RF-008-29, RF-008-31): sangrada por su profundidad, con el
    botón de plegar si tiene ramas, la insignia de tipo de una cifra o un parámetro ([HIP] con
    su icono ámbar), su texto, «ya mostrada arriba» si se repite, sus marcas en alerta y su
    nota (en alerta, la causa de un eslabón obsoleto)."""
    line = layout.row(align=True)
    if row.depth:
        line.separator(factor=LINEAGE_INDENT * row.depth)
    if children:
        icon = "DISCLOSURE_TRI_DOWN" if row.expanded else "DISCLOSURE_TRI_RIGHT"
        line.prop(row, "expanded", text="", icon=icon, emboss=False)
    else:
        line.label(text="", icon="BLANK1")
    if row.param_kind:
        _badge_cell(line, row.param_kind)
    line.label(text=row.text, translate=False)
    if row.repeated:
        again = line.row(align=True)
        again.active = False
        again.label(text=tr("shown above"), translate=False)
    marks = [mark for mark in row.marks.split(",") if mark]
    if row.kind != "operation":  # de un eslabón, su nota dice por qué
        for mark in marks:
            flagged = line.row(align=True)
            flagged.alert = True
            flagged.label(text=_mark_text(row.kind, mark), translate=False)
    if row.note:
        note = line.row(align=True)
        note.alert = "stale" in marks
        note.label(text=row.note, translate=False)


def draw_lineage(layout: Any, context: Any) -> None:
    """El contenido de :class:`GEOBLENDER_PT_core_lineage` (RF-008-29, RF-008-31): la
    búsqueda, el motivo si lo buscado no está, lo que lo contiene (cada uno abre su
    procedencia) y la cadena."""
    layout.label(text=tr("Operation graph and provenance"), translate=False)
    reason = _session().unavailable()
    if reason is not None:
        layout.label(text=reason, icon="INFO", translate=False)
        return
    view = getattr(getattr(context, "window_manager", None), WINDOW_MANAGER_PROPERTY, None)
    if view is None:
        return
    layout.prop(view, "lineage_uid", text=tr("Figure or dataset"), icon="VIEWZOOM",
                translate=False)
    matches = view.lineage_matches
    if len(matches):
        layout.label(text=tr("Figures and datasets found"), translate=False)
        column = layout.column(align=True)
        for match in matches:
            _operator(column, SHOW_LINEAGE, match.text, item_uid=match.uid)
    elif view.lineage_error:
        note = layout.row()
        note.alert = True
        note.label(text=view.lineage_error, icon="ERROR", translate=False)
    if len(view.lineage):
        layout.template_list(LINEAGE_LIST, "", view, "lineage", view, "lineage_index",
                             rows=LINEAGE_ROWS)
        if view.lineage_more:
            layout.label(text=tr("… and {count} more", count=view.lineage_more),
                         translate=False)
    elif not len(matches) and not view.lineage_error:
        layout.label(text=tr("Search for a figure or a dataset by its name, its key or its uid"),
                     translate=False)


class GEOBLENDER_UL_core_lineage(bpy.types.UIList):
    """The chain of operations of a figure or a dataset"""

    bl_idname = LINEAGE_LIST

    def draw_item(self, _context: Any, layout: Any, data: Any, item: Any, _icon: int,
                  _active_data: Any, _active_property: str, index: int = 0,
                  _flt_flag: int = 0) -> None:
        rows = data.lineage
        children = index + 1 < len(rows) and rows[index + 1].depth > item.depth
        draw_lineage_row(layout, item, children=children)

    def filter_items(self, _context: Any, data: Any, propname: str) -> tuple[list[int],
                                                                            list[int]]:
        flag = self.bitflag_filter_item
        return [flag if shown else 0 for shown in lineage_visible(getattr(data, propname))], []


class GEOBLENDER_PT_core_lineage(bpy.types.Panel):
    """What each result comes from and what depends on it"""

    bl_idname = LINEAGE_PANEL
    bl_label = "Operation graph and provenance"
    bl_translation_context = "Geoblender"
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = LINEAGE_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_lineage(self.layout, context)


classes: tuple[type, ...] = (
    GEOBLENDER_PT_core_stale,
    GEOBLENDER_UL_core_parameters,
    GEOBLENDER_UL_core_parameter_history,
    GEOBLENDER_PT_core_parameters,
    GEOBLENDER_UL_core_inputs,
    GEOBLENDER_PT_core_inputs,
    GEOBLENDER_UL_core_lineage,
    GEOBLENDER_PT_core_lineage,
)


# Instalación ----------------------------------------------------------------------------------


def install() -> None:
    """Registra los campos de la barra de estado (después de ``statusbar.install``), el número
    del control 7, el proveedor de estado de las órdenes y la escucha del proyecto de la
    sesión; con un proyecto ya abierto, pone el temporizador. Idempotente («Reparar la
    interfaz» la vuelve a llamar)."""
    for key, order, draw, width in FIELDS:
        statusbar.register_field(key, priority=FIELD_PRIORITY, draw=draw, width_px=width,
                                 modes=FIELD_MODES, order=order,
                                 folded_draw=partial(draw, folded=True),
                                 folded_width_px=partial(width, folded=True))
    quick_access.set_count_provider(REFRESH, stale_count)
    set_state_provider(command_state)
    project_session.add_listener(on_project_changed)
    if project_session.current() is not None and not bpy.app.timers.is_registered(
            indicator_tick):
        bpy.app.timers.register(indicator_tick, first_interval=INDICATOR_TICK_S,
                                persistent=True)


def uninstall() -> None:
    """Quita los campos, el número del control 7, el proveedor de estado de las órdenes, la
    escucha y los temporizadores, y olvida los recuentos, las filas (también las de los
    parámetros) y el aviso."""
    for key in FIELD_KEYS:
        statusbar.unregister_field(key)
    if quick_access.count_provider(REFRESH) is stale_count:
        quick_access.set_count_provider(REFRESH, None)
    if state_provider() is command_state:
        set_state_provider(None)
    project_session.remove_listener(on_project_changed)
    _retire(indicator_tick)
    _retire(expire_undo_notice)
    _forget()
    _clear_parameters()
    _clear_inputs()
    _forget_lineage()
    _STATE.texts.clear()
    _STATE.properties.clear()
    _STATE.undo_text = ""
    _STATE.undo_until = 0.0
