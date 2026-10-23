# SPDX-License-Identifier: GPL-3.0-or-later
"""Las filas de los paneles de la procedencia (spec 008; RF-008-06, RF-008-16, RF-008-28,
RF-008-29; plan 008 §5.1, §5.5 y D16).

``WindowManager.geoblender_provenance`` (:class:`GEOBLENDER_PG_core_provenance`) guarda lo que
dibujan los paneles de Proyecto ▸ Control: los parámetros con el historial del seleccionado,
el registro de entradas, lo obsoleto y lo que espera revisión a mano, y las filas sangradas de
la procedencia, con los filtros de la lista de parámetros (módulo, tipo y marca). Es una
**vista** que se regenera desde el proyecto, nunca la fuente: la fuente es la base del
proyecto. Vive en ``WindowManager``, que Blender no guarda en el ``.blend`` (RF-002-29), y
cada valor llega ya presentado como texto («35 %», «1,15»): ninguna cifra pasa por una
propiedad flotante (float32; ARQ-13). Los estados (``status``, ``kind``…) son los valores de
los enumerados de ``core`` (``InputStatus``, ``ParamKind``…); «comprobando» y «no
localizable», que no se guardan (D7), los dice la sesión al dibujar el registro de entradas.

Las propiedades de las filas no tienen nombre ni descripción: no se dibujan con los suyos,
sino con los textos del catálogo de idioma que pone cada panel; salvo «Desplegado» de la
procedencia, el triángulo de cada nudo. Las de la vista, sí (T71): la ayuda emergente de una
lista enseña las de su fila activa (no ``input_index``), y la de la búsqueda, las suyas.
Ninguna se anima.

Spec 008, T50: cambiar un filtro de la lista de parámetros la vuelve a leer del proyecto con
esos filtros (``bl.ui.provenance.fill_parameters``: filtra ``core.params``), y cambiar el
seleccionado lee su historial y el aviso de divergencia de su última cifra calculada
(``fill_history``; ``parameter_divergence`` y ``parameter_figure_uid``).

Spec 008, T52: :class:`GEOBLENDER_PG_core_import_setting` es un ajuste de la importación que el
importador vuelve a pedir al actualizar una entrada (la colección ``settings`` de
``geoblender.core_resolve_input``), también un texto.

Spec 008, T54: ``unusable``, los datos bloqueados, que faltan o dañados con lo que se ofrece para
resolverlos (los regenera el temporizador de los indicadores con lo obsoleto), y
``unregistered``, las capas y tablas del proyecto sin registrar (las regenera el registro de
entradas).

Spec 008, T55: la procedencia (``lineage``, filas sangradas con su insignia, sus marcas y su
nota; ``lineage_more``, las que no caben) se lee de nuevo al cambiar la búsqueda
(``lineage_uid``, el uid o el texto que se busca: ``bl.ui.provenance.search_lineage``); si no es
una cifra, un dato ni una operación del proyecto, ``lineage_error`` dice por qué y
``lineage_matches`` lista las cifras vigentes y los datos que contienen el texto.
"""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from ...core.catalog.schema import MODULE_CODES

# Nombre de la propiedad de WindowManager (la usan los paneles de la fase 8).
WINDOW_MANAGER_PROPERTY = "geoblender_provenance"
FILTER_ALL = "ALL"  # el elemento «Cualquiera» de cada filtro: no filtra
_STATIC: set[str] = set()  # ni animable ni nada más

# Filtros de la lista de parámetros (RF-008-06; core.params.ParameterFilter): el módulo dueño,
# el tipo (identificador = nombre de ParamKind, sin tildes; etiqueta = su insignia) y la marca
# (nombre de ParamMark).
MODULE_FILTER_ITEMS = [
    (FILTER_ALL, "Any", ""),
    *((code, code, "") for code in MODULE_CODES),
]
KIND_FILTER_ITEMS = [
    (FILTER_ALL, "Any", ""),
    ("MEDIDO", "[MEA]", ""),
    ("CALCULADO", "[CAL]", ""),
    ("ADOPTADO", "[ADO]", ""),
    ("HIPOTESIS", "[HYP]", ""),
]
MARK_FILTER_ITEMS = [
    (FILTER_ALL, "Any", ""),
    ("UNCONFIRMED", "unconfirmed", ""),
    ("REVIEW", "review", ""),
]


def _text() -> StringProperty:  # type: ignore[valid-type]
    return StringProperty(default="", options=_STATIC)


def _flag() -> BoolProperty:  # type: ignore[valid-type]
    return BoolProperty(default=False, options=_STATIC)


def _index() -> IntProperty:  # type: ignore[valid-type]
    return IntProperty(default=0, min=0, options=_STATIC)


def _parameters_filtered(_view: object, _context: object) -> None:
    """Un filtro de la lista de parámetros cambió: se vuelve a leer con los filtros nuevos."""
    from ..ui import provenance  # al usarlo: bl/ui importa bl/props (ARQ-08)

    provenance.parameters_changed()


def _parameter_selected(_view: object, _context: object) -> None:
    """Cambió el parámetro seleccionado: su historial y su aviso de divergencia."""
    from ..ui import provenance

    provenance.selection_changed()


def _lineage_searched(_view: object, _context: object) -> None:
    """Cambió la búsqueda de la procedencia: se lee la de lo buscado (T55)."""
    from ..ui import provenance

    provenance.lineage_searched()


class GEOBLENDER_PG_core_parameter_row(bpy.types.PropertyGroup):
    """Una fila de la lista de parámetros (RF-008-06; ``core.params.ParameterRow``)."""

    uid: _text()  # type: ignore[valid-type]
    key: _text()  # type: ignore[valid-type]
    module: _text()  # type: ignore[valid-type]
    value: _text()  # type: ignore[valid-type]  # con su unidad, como lo lee una persona
    kind: _text()  # type: ignore[valid-type]  # ParamKind
    unconfirmed: _flag()  # type: ignore[valid-type]
    review: _flag()  # type: ignore[valid-type]
    review_text: _text()  # type: ignore[valid-type]
    source: _text()  # type: ignore[valid-type]
    decided_by: _text()  # type: ignore[valid-type]
    decided_at: _text()  # type: ignore[valid-type]
    # Spec 009 (T20; RF-009-29): el código de la versión activa si tiene valor propio y el
    # valor de cada ámbito («V02: 12 m [HIP] · proyecto: 11 m [HIP]»); "" si no.
    own_version: _text()  # type: ignore[valid-type]
    scopes: _text()  # type: ignore[valid-type]
    # Spec 009 (T24; RF-009-13): su decisor de la propiedad, cada decisión enlazada a su clave
    # en una línea («Propiedad: D. Juan · 03/10/2026 · «…»»), de la más antigua a la última.
    owner: _text()  # type: ignore[valid-type]


class GEOBLENDER_PG_core_parameter_history_row(bpy.types.PropertyGroup):
    """Una fila del historial del parámetro seleccionado (RF-008-06; ``HistoryEntry``)."""

    rev: _index()  # type: ignore[valid-type]
    action: _text()  # type: ignore[valid-type]  # HistoryAction
    value: _text()  # type: ignore[valid-type]
    kind: _text()  # type: ignore[valid-type]
    unconfirmed: _flag()  # type: ignore[valid-type]
    decided_by: _text()  # type: ignore[valid-type]
    decided_at: _text()  # type: ignore[valid-type]
    reason: _text()  # type: ignore[valid-type]
    changed_by: _text()  # type: ignore[valid-type]
    changed_at: _text()  # type: ignore[valid-type]


class GEOBLENDER_PG_core_input_row(bpy.types.PropertyGroup):
    """Una fila del registro de entradas (RF-008-16; ``core.inputs.InputRecord``)."""

    uid: _text()  # type: ignore[valid-type]
    name: _text()  # type: ignore[valid-type]
    status: _text()  # type: ignore[valid-type]  # InputStatus (el registrado)
    kind: _text()  # type: ignore[valid-type]
    module: _text()  # type: ignore[valid-type]
    received_at: _text()  # type: ignore[valid-type]
    received_from: _text()  # type: ignore[valid-type]
    crs_h: _text()  # type: ignore[valid-type]
    crs_v: _text()  # type: ignore[valid-type]
    content_hash: _text()  # type: ignore[valid-type]  # abreviado (12 caracteres)
    original: _text()  # type: ignore[valid-type]  # OriginalState


class GEOBLENDER_PG_core_stale_row(bpy.types.PropertyGroup):
    """Una fila de lo obsoleto o de lo que espera revisión a mano (RF-008-28;
    ``core.provenance.stale.StaleItem``)."""

    item_kind: _text()  # type: ignore[valid-type]  # «dataset» u «operation»
    uid: _text()  # type: ignore[valid-type]
    name: _text()  # type: ignore[valid-type]
    module: _text()  # type: ignore[valid-type]
    operation_uid: _text()  # type: ignore[valid-type]
    op_type: _text()  # type: ignore[valid-type]
    review: _flag()  # type: ignore[valid-type]
    text: _text()  # type: ignore[valid-type]  # «Obsoleto: cambió Producción»
    since: _text()  # type: ignore[valid-type]


class GEOBLENDER_PG_core_unusable_row(bpy.types.PropertyGroup):
    """Un dato que no se puede usar hasta resolverlo: bloqueado por una edición externa, que
    falta o dañado (RF-008-56, RF-008-57; ``core.datasets.external.Unusable``), con lo que se
    ofrece para resolverlo y su aviso."""

    uid: _text()  # type: ignore[valid-type]
    name: _text()  # type: ignore[valid-type]
    module: _text()  # type: ignore[valid-type]
    status: _text()  # type: ignore[valid-type]  # DatasetStatus
    offers: _text()  # type: ignore[valid-type]  # valores de Offer separados por «,»
    text: _text()  # type: ignore[valid-type]  # su aviso


class GEOBLENDER_PG_core_unregistered_row(bpy.types.PropertyGroup):
    """Una capa o tabla del proyecto sin registrar, creada desde QGIS (RF-008-62;
    ``core.datasets.Foreign``), y si se puede registrar como entrada."""

    kind: _text()  # type: ignore[valid-type]  # ForeignKind
    name: _text()  # type: ignore[valid-type]
    registrable: _flag()  # type: ignore[valid-type]


class GEOBLENDER_PG_core_lineage_row(bpy.types.PropertyGroup):
    """Una fila sangrada de la procedencia (RF-008-29; ``core.provenance.lineage.LineageRow``),
    con sus marcas (RF-008-31) y si su nudo está desplegado."""

    depth: _index()  # type: ignore[valid-type]
    kind: _text()  # type: ignore[valid-type]  # LineageKind
    uid: _text()  # type: ignore[valid-type]
    text: _text()  # type: ignore[valid-type]
    role: _text()  # type: ignore[valid-type]
    repeated: _flag()  # type: ignore[valid-type]
    marks: _text()  # type: ignore[valid-type]  # valores de Mark separados por «,»
    expanded: BoolProperty(  # type: ignore[valid-type]
        default=True, options=_STATIC, name="Expanded",
        description="Show or hide what this link depends on",
    )
    # T55: el tipo (ParamKind) de una cifra o de un parámetro, para su insignia, y la nota de
    # la fila (la causa de un eslabón obsoleto, lo de hoy de un parámetro que cambió…).
    param_kind: _text()  # type: ignore[valid-type]
    note: _text()  # type: ignore[valid-type]


class GEOBLENDER_PG_core_lineage_match(bpy.types.PropertyGroup):
    """Lo que encuentra la búsqueda de la procedencia (T55; ``core.provenance.lineage.
    LineageMatch``): una cifra vigente o un dato, con su texto."""

    kind: _text()  # type: ignore[valid-type]  # LineageKind
    uid: _text()  # type: ignore[valid-type]
    text: _text()  # type: ignore[valid-type]


class GEOBLENDER_PG_core_import_setting(bpy.types.PropertyGroup):
    """Un ajuste de la importación que el importador vuelve a pedir al actualizar una entrada
    (RF-008-11; ``core.provenance.contract.SettingsNeeded``): su clave es ``name`` (el de todo
    grupo) y ``value``, el valor que se le da (texto). Lo usa ``geoblender.core_resolve_input``
    (desde un guion, ``settings=[{"name": "layer", "value": "limites"}]``); no vive en
    ``WindowManager``."""

    value: StringProperty(name="Value", default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_provenance(bpy.types.PropertyGroup):
    """La vista de los paneles de la procedencia, en ``WindowManager.geoblender_provenance``
    (D16): filas, fila activa de cada lista y filtros de la de parámetros. Cada propiedad con
    su nombre y su descripción del catálogo (T71): los enseña la ayuda emergente de una lista
    (su fila activa) y de la búsqueda de la procedencia."""

    parameters: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_parameter_row, options=_STATIC, name="Project parameters",
        description="Parameters of the open project that the list shows, with its filters",
    )
    parameter_index: IntProperty(  # type: ignore[valid-type]
        default=0, min=0, options=_STATIC, update=_parameter_selected,
        name="Selected parameter",
        description="Parameter whose history, warning and orders are shown below the list",
    )
    parameter_history: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_parameter_history_row, options=_STATIC,
        name="Parameter history",
        description="Every entry of the history of the selected parameter",
    )
    history_index: IntProperty(  # type: ignore[valid-type]
        default=0, min=0, options=_STATIC, name="Selected history entry",
        description="Selected row of the history of the parameter",
    )
    # El aviso de divergencia del seleccionado (RF-008-59) y la cifra que se adoptaría.
    parameter_divergence: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, name="Difference with the calculated value",
        description="Warning of the last figure that calculates the selected parameter with "
                    "another value",
    )
    parameter_figure_uid: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, name="Calculated figure",
        description="Identifier of the figure that «Use the calculated value…» adopts",
    )
    filter_module: EnumProperty(  # type: ignore[valid-type]
        items=MODULE_FILTER_ITEMS, default=FILTER_ALL, options=_STATIC,
        update=_parameters_filtered, name="Module",
        description="Only the parameters of this module",
    )
    filter_kind: EnumProperty(  # type: ignore[valid-type]
        items=KIND_FILTER_ITEMS, default=FILTER_ALL, options=_STATIC,
        update=_parameters_filtered, name="Type",
        description="Only the parameters of this type",
    )
    filter_mark: EnumProperty(  # type: ignore[valid-type]
        items=MARK_FILTER_ITEMS, default=FILTER_ALL, options=_STATIC,
        update=_parameters_filtered, name="Mark",
        description="Only the parameters with this mark",
    )
    inputs: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_input_row, options=_STATIC, name="Input register",
        description="Inputs of the open project, with their state",
    )
    input_index: IntProperty(  # type: ignore[valid-type]
        default=0, min=0, options=_STATIC, name="Selected input",
        description="Input whose orders are shown below the list",
    )
    stale: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_stale_row, options=_STATIC, name="Stale results",
        description="Stale results and those waiting for manual review, with their cause",
    )
    stale_index: IntProperty(  # type: ignore[valid-type]
        default=0, min=0, options=_STATIC, name="Selected stale result",
        description="Selected row of the stale results",
    )
    # Spec 008, T54: lo que no se puede usar (panel de lo obsoleto) y las capas sin registrar
    # (registro de entradas).
    unusable: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_unusable_row, options=_STATIC,
        name="Datasets that cannot be used",
        description="Blocked, missing or damaged datasets, with what is offered to resolve "
                    "them",
    )
    unregistered: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_unregistered_row, options=_STATIC,
        name="Layers and tables of the project not registered",
        description="Layers and tables created in the project outside Geoblender, such as "
                    "from QGIS",
    )
    lineage: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_lineage_row, options=_STATIC, name="Provenance chain",
        description="The figure or dataset searched for and, indented below, each link down "
                    "to its inputs",
    )
    lineage_index: IntProperty(  # type: ignore[valid-type]
        default=0, min=0, options=_STATIC, name="Selected link",
        description="Selected row of the provenance chain",
    )
    # La cifra, el dato o la operación pedidos (su uid o el nombre de un dato), o lo que se
    # busca (T55).
    lineage_uid: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, update=_lineage_searched, name="Figure or dataset",
        description="Identifier of a figure, a dataset or an operation, or part of the name "
                    "of a figure or a dataset",
    )
    lineage_more: IntProperty(  # type: ignore[valid-type]
        default=0, min=0, options=_STATIC, name="Rows not shown",
        description="Rows of the provenance chain that do not fit in the list",
    )
    lineage_error: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, name="Search problem",
        description="Why what was searched for is not a figure, a dataset or an operation of "
                    "the project",
    )
    lineage_matches: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_lineage_match, options=_STATIC, name="Matches",
        description="Current figures and datasets whose name contains the text searched for",
    )


# En orden de registro: las filas antes de la vista que las reúne.
classes: tuple[type, ...] = (
    GEOBLENDER_PG_core_parameter_row,
    GEOBLENDER_PG_core_parameter_history_row,
    GEOBLENDER_PG_core_input_row,
    GEOBLENDER_PG_core_stale_row,
    GEOBLENDER_PG_core_unusable_row,
    GEOBLENDER_PG_core_unregistered_row,
    GEOBLENDER_PG_core_lineage_row,
    GEOBLENDER_PG_core_lineage_match,
    GEOBLENDER_PG_core_provenance,
    GEOBLENDER_PG_core_import_setting,  # el de los ajustes de geoblender.core_resolve_input
)


def register() -> None:
    """Pone ``WindowManager.geoblender_provenance`` (las clases ya están registradas)."""
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_core_provenance, options=_STATIC))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_provenance`` (antes de desregistrar las clases); sin
    ella, nada."""
    if hasattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY):
        delattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY)
