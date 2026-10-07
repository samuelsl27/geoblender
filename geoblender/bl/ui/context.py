# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo del objeto activo, chincheta del contexto y proveedores de la Leyenda y del Filtro
de datos (spec 003; RF-003-09, RF-003-17; plan 003 §5.3, contrato 6; BS §8.12, Consulta ▸;
AR §3.1, n.º 26 y 27; PC §1 y §4).

- **Tipo activo** (:func:`active_kind`): el ``kind`` de ``Object.geoblender`` del objeto
  activo (``DRILLHOLES``, ``BLOCK_MODEL``…; PC §1). La propiedad la registra la 006
  (RF-006-29): hasta entonces se lee con tolerancia y, sin ella, ningún objeto es de un tipo
  de Geoblender. La versión es una colección (``Collection.geoblender.version_id``, R-07;
  :func:`collection_kind`).
- **Contexto de una vista** (:func:`context_kind`, RF-003-17; PC §1 y §4): el tipo cuyo
  menú «<Tipo> ▾» se ofrece en la fila 1, en el clic derecho y con Mayús+Alt+B: el fijado
  con la **chincheta** de esa Vista 3D (:func:`toggle_pin`; por área y por sesión, se
  olvida si su objeto desaparece) o, si no, «Selección (n)» (``SELECTION``) cuando los
  objetos seleccionados son de varios tipos, o el tipo del objeto activo; sin ninguno,
  "" (la fila 1 solo muestra «Herramientas ▾»).
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

:func:`clear` olvida los proveedores y las chinchetas al desregistrar la interfaz.
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
SELECTION_KIND = "SELECTION"  # «Selección (n) ▾» (PC §4)
VERSION_KIND = "VERSION"  # la colección de una versión (PC §3.13)


@dataclass(frozen=True)
class Pin:
    """Lo que fija la chincheta de una Vista 3D: el tipo, cuántos elementos y el objeto
    (por nombre; si desaparece, la chincheta se suelta)."""

    kind: str
    count: int
    object_name: str


_PINS: dict[int, Pin] = {}  # por área (su puntero), en esta sesión


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
    """Olvida todos los proveedores y las chinchetas (al desregistrar la interfaz)."""
    _LEGEND.clear()
    _DATA_FILTER.clear()
    _PINS.clear()


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
    return object_kind(active_object(context))


def object_kind(obj: Any) -> str:
    """El tipo de Geoblender de un objeto ("" si no tiene)."""
    data = getattr(obj, KIND_PROPERTY, None)
    return str(getattr(data, "kind", "") or "")


def collection_kind(collection: Any) -> str:
    """``VERSION`` si la colección es la de una versión (``Collection.geoblender.version_id``,
    R-07; con tolerancia, como el tipo de los objetos); si no, ""."""
    data = getattr(collection, KIND_PROPERTY, None)
    return VERSION_KIND if getattr(data, "version_id", "") else ""


def _area_key(context: Any) -> int | None:
    area = getattr(context, "area", None)
    pointer = getattr(area, "as_pointer", None)
    return int(pointer()) if callable(pointer) else None


def _selection(context: Any) -> tuple[str, int]:
    """(tipo, n) de lo seleccionado y activo, sin chincheta: ``SELECTION`` y cuántos si
    hay varios tipos; el tipo activo si no; ("", 0) sin tipo activo."""
    selected = getattr(context, "selected_objects", None) or ()
    kinds = [kind for kind in (object_kind(obj) for obj in selected) if kind]
    if len(set(kinds)) > 1:
        return SELECTION_KIND, len(kinds)
    kind = active_kind(context)
    return (kind, max(1, len(kinds))) if kind else ("", 0)


def pinned(context: Any) -> Pin | None:
    """La chincheta de la Vista 3D de ``context`` (``None`` si no está fijada o si su
    objeto ya no existe)."""
    key = _area_key(context)
    pin = _PINS.get(key) if key is not None else None
    if pin is None:
        return None
    if pin.object_name and pin.object_name not in bpy.data.objects:
        _PINS.pop(key, None)
        return None
    return pin


def toggle_pin(context: Any) -> bool:
    """Fija el contexto actual de la Vista 3D de ``context`` o lo suelta; devuelve si
    queda fijado. Sin tipo que fijar, no hace nada."""
    key = _area_key(context)
    if key is None:
        return False
    if key in _PINS:
        del _PINS[key]
        return False
    kind, count = _selection(context)
    if not kind:
        return False
    obj = active_object(context)
    _PINS[key] = Pin(kind, count, str(getattr(obj, "name", "") or ""))
    return True


def context_kind(context: Any) -> tuple[str, int]:
    """(tipo, n) del menú contextual de la Vista 3D de ``context`` (RF-003-17): el fijado
    con la chincheta o el de la selección; ("", 0) sin ninguno."""
    pin = pinned(context)
    if pin is not None:
        return pin.kind, pin.count
    return _selection(context)


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
