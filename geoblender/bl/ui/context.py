# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo del objeto activo y proveedores de la Leyenda y del Filtro de datos (spec 003;
RF-003-09; plan 003 §5.3, contrato 6; BS §8.12, Consulta ▸; AR §3.1, n.º 26 y 27; PC §1).

- **Tipo activo** (:func:`active_kind`): el ``kind`` de ``Object.geoblender`` del objeto
  activo (``DRILLHOLES``, ``BLOCK_MODEL``…; PC §1). La propiedad la registra la 006
  (RF-006-29): hasta entonces se lee con tolerancia y, sin ella, ningún objeto es de un tipo
  de Geoblender.
- **Proveedores** (contrato 6): cada spec que da contenido a la Leyenda o al Filtro de datos
  (005 para los sondeos, R-22 para el modelo de bloques…) registra el suyo para su tipo con
  :func:`register_legend_provider` y :func:`register_data_filter_provider`, y lo quita con
  los ``unregister_*`` al desregistrarse. Un proveedor de leyenda da los campos por los que
  se puede colorear (:class:`Field`, con su título ya en el idioma de Geoblender), el
  vigente y cómo aplicar uno; uno de filtro, los campos, la expresión vigente y cómo
  aplicarla (si la rechaza, lanza un ``GeoblenderError`` con el motivo).
- **Controles genéricos de la 003**: las ventanas emergentes ``GEOBLENDER_PT_ui_legend`` y
  ``GEOBLENDER_PT_ui_data_filter`` (acceso rápido de la vista y Mayús+Alt+L / Mayús+Alt+F)
  y los comandos ``geoblender.ui_edit_legend`` y ``geoblender.ui_edit_data_filter``
  (Herramientas ▸ Consulta ▸, en ``bl/ops/ui.py``). Sin proveedor para el tipo activo, los
  comandos no se pueden ejecutar y las ventanas muestran, desactivado,
  :func:`no_provider_message` («Seleccione sondeos (005) o un modelo de bloques (R-22)»,
  spec §8). Con él, la Leyenda lista sus campos (el vigente, hundido) y el Filtro muestra la
  expresión vigente, los campos y el botón que la edita.

:func:`clear` olvida los proveedores al desregistrar la interfaz.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import bpy

from ...core.i18n import tr
from .drawing import draw_command

KIND_PROPERTY = "geoblender"  # Object.geoblender (spec 006, RF-006-29)
LEGEND_PANEL = "GEOBLENDER_PT_ui_legend"
DATA_FILTER_PANEL = "GEOBLENDER_PT_ui_data_filter"
EDIT_LEGEND = "geoblender.ui_edit_legend"
EDIT_DATA_FILTER = "geoblender.ui_edit_data_filter"


@dataclass(frozen=True)
class Field:
    """Un campo del tipo activo: su identificador y su título (en el idioma de
    Geoblender)."""

    id: str
    label: str


class LegendProvider(Protocol):
    """La Leyenda de un tipo de objeto (contrato 6)."""

    def fields(self, context: Any) -> Sequence[Field]: ...

    def current(self, context: Any) -> str: ...

    def apply(self, context: Any, field: str) -> None: ...


class DataFilterProvider(Protocol):
    """El Filtro de datos de un tipo de objeto (contrato 6)."""

    def fields(self, context: Any) -> Sequence[Field]: ...

    def current(self, context: Any) -> str: ...

    def apply(self, context: Any, expression: str) -> None: ...


_LEGEND: dict[str, LegendProvider] = {}
_DATA_FILTER: dict[str, DataFilterProvider] = {}


def register_legend_provider(kind: str, provider: LegendProvider) -> None:
    """Pone el proveedor de la Leyenda del tipo ``kind``."""
    _LEGEND[kind] = provider


def unregister_legend_provider(kind: str) -> None:
    """Quita el proveedor de la Leyenda del tipo ``kind`` (sin él, nada)."""
    _LEGEND.pop(kind, None)


def register_data_filter_provider(kind: str, provider: DataFilterProvider) -> None:
    """Pone el proveedor del Filtro de datos del tipo ``kind``."""
    _DATA_FILTER[kind] = provider


def unregister_data_filter_provider(kind: str) -> None:
    """Quita el proveedor del Filtro de datos del tipo ``kind`` (sin él, nada)."""
    _DATA_FILTER.pop(kind, None)


def clear() -> None:
    """Olvida todos los proveedores (al desregistrar la interfaz)."""
    _LEGEND.clear()
    _DATA_FILTER.clear()


def active_object(context: Any) -> Any:
    """El objeto activo de ``context`` (o de su capa de vista)."""
    obj = getattr(context, "active_object", None)
    if obj is None:
        view_layer = getattr(context, "view_layer", None)
        obj = getattr(getattr(view_layer, "objects", None), "active", None)
    return obj


def active_kind(context: Any) -> str:
    """El tipo de Geoblender del objeto activo ("" si no tiene: sin objeto, sin la
    propiedad de la 006 o sin tipo)."""
    data = getattr(active_object(context), KIND_PROPERTY, None)
    return str(getattr(data, "kind", "") or "")


def legend_provider(context: Any) -> LegendProvider | None:
    """El proveedor de la Leyenda del tipo activo, o ``None``."""
    return _LEGEND.get(active_kind(context))


def data_filter_provider(context: Any) -> DataFilterProvider | None:
    """El proveedor del Filtro de datos del tipo activo, o ``None``."""
    return _DATA_FILTER.get(active_kind(context))


def no_provider_message() -> str:
    """El paso previo de la Leyenda y del Filtro sin proveedor (spec §8)."""
    return tr("Select drillholes (005) or a block model (R-22)")


def _draw_unavailable(layout: Any) -> None:
    row = layout.row()
    row.enabled = False
    row.label(text=no_provider_message(), icon="INFO", translate=False)


class GEOBLENDER_PT_ui_legend(bpy.types.Panel):
    """Colour the items of the active type by one of their fields"""

    bl_idname = LEGEND_PANEL
    bl_label = "Legend"
    bl_translation_context = "Geoblender"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"

    def draw(self, context: Any) -> None:
        provider = legend_provider(context)
        if provider is None:
            _draw_unavailable(self.layout)
            return
        current = provider.current(context)
        column = self.layout.column(align=True)
        for field in provider.fields(context):
            properties = column.operator(EDIT_LEGEND, text=field.label, translate=False,
                                         depress=field.id == current)
            properties.field = field.id


class GEOBLENDER_PT_ui_data_filter(bpy.types.Panel):
    """Expression on the items of the active type"""

    bl_idname = DATA_FILTER_PANEL
    bl_label = "Data filter"
    bl_translation_context = "Geoblender"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"

    def draw(self, context: Any) -> None:
        provider = data_filter_provider(context)
        if provider is None:
            _draw_unavailable(self.layout)
            return
        layout = self.layout
        expression = provider.current(context)
        layout.label(text=expression or tr("No filter"), icon="FILTER", translate=False)
        column = layout.column(align=True)
        column.active = False
        for field in provider.fields(context):
            column.label(text=field.label, translate=False)
        draw_command(layout, EDIT_DATA_FILTER, context=context)


classes: tuple[type, ...] = (GEOBLENDER_PT_ui_legend, GEOBLENDER_PT_ui_data_filter)
