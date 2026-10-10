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

Las filas no tienen nombre ni descripción: no se dibujan con los suyos, sino con los textos
del catálogo de idioma que pone cada panel. Ninguna se anima.

Spec 008, T50: cambiar un filtro de la lista de parámetros la vuelve a leer del proyecto con
esos filtros (``bl.ui.provenance.fill_parameters``: filtra ``core.params``), y cambiar el
seleccionado lee su historial y el aviso de divergencia de su última cifra calculada
(``fill_history``; ``parameter_divergence`` y ``parameter_figure_uid``).
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
    expanded: BoolProperty(default=True, options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_provenance(bpy.types.PropertyGroup):
    """La vista de los paneles de la procedencia, en ``WindowManager.geoblender_provenance``
    (D16): filas, fila activa de cada lista y filtros de la de parámetros."""

    parameters: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_parameter_row, options=_STATIC
    )
    parameter_index: IntProperty(  # type: ignore[valid-type]
        default=0, min=0, options=_STATIC, update=_parameter_selected
    )
    parameter_history: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_parameter_history_row, options=_STATIC
    )
    history_index: _index()  # type: ignore[valid-type]
    # El aviso de divergencia del seleccionado (RF-008-59) y la cifra que se adoptaría.
    parameter_divergence: _text()  # type: ignore[valid-type]
    parameter_figure_uid: _text()  # type: ignore[valid-type]
    filter_module: EnumProperty(  # type: ignore[valid-type]
        items=MODULE_FILTER_ITEMS, default=FILTER_ALL, options=_STATIC,
        update=_parameters_filtered,
    )
    filter_kind: EnumProperty(  # type: ignore[valid-type]
        items=KIND_FILTER_ITEMS, default=FILTER_ALL, options=_STATIC,
        update=_parameters_filtered,
    )
    filter_mark: EnumProperty(  # type: ignore[valid-type]
        items=MARK_FILTER_ITEMS, default=FILTER_ALL, options=_STATIC,
        update=_parameters_filtered,
    )
    inputs: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_input_row, options=_STATIC
    )
    input_index: _index()  # type: ignore[valid-type]
    stale: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_stale_row, options=_STATIC
    )
    stale_index: _index()  # type: ignore[valid-type]
    lineage: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_lineage_row, options=_STATIC
    )
    lineage_index: _index()  # type: ignore[valid-type]
    lineage_uid: _text()  # type: ignore[valid-type]  # la cifra, el dato o la operación pedidos


# En orden de registro: las filas antes de la vista que las reúne.
classes: tuple[type, ...] = (
    GEOBLENDER_PG_core_parameter_row,
    GEOBLENDER_PG_core_parameter_history_row,
    GEOBLENDER_PG_core_input_row,
    GEOBLENDER_PG_core_stale_row,
    GEOBLENDER_PG_core_lineage_row,
    GEOBLENDER_PG_core_provenance,
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
