# SPDX-License-Identifier: GPL-3.0-or-later
"""Aplicar el aspecto de un elemento a su objeto (spec 019, T07; HU-019-1; RF-019-07, RF-019-08; plan 019 §5.2 y A1).

- :func:`apply` recorre las propiedades del aspecto y aplica cada una con su aplicador (:data:`APPLIERS`, un
  diccionario ``tipo → propiedad → función``); **un tipo sin aplicador para una propiedad no la ofrece**
  (:func:`offered`), así «según el tipo» sale del catálogo y no de un ``if``.
- Solo toca **la vista**: ``Object.color`` (con la transparencia en su alfa: es lo que se ve en la vista sólida
  con el color por objeto, T01), un material de visualización con ``diffuse_color`` y ``blend_method`` si hay
  transparencia, ``hide_set``, ``show_name`` y ``show_wire``. **Nunca** la geometría, la procedencia ni el
  proyecto (RF-019-08).
- :func:`read` lee el espejo ``Object.geoblender.look``; :func:`mirror` lo escribe sin disparar el aplicador;
  :func:`reapply` aplica a varios objetos (sin cablear aún: T08 lo llama tras cargar y refrescar).

No hay aplicador de grosor de línea ni de tamaño de punto: lo que dibuja ``bl/draw`` no toma el estilo de cada
objeto (son superposiciones de toda la región), así que esas dos propiedades no se ofrecen todavía
(:func:`offered`); cuando una superposición las lea, se añade aquí su aplicador y el panel las ofrece solo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

import bpy

from ...core.appearance.catalog import allowed
from ...core.appearance.model import Appearance, validate

__all__ = ["APPLIERS", "MATERIAL_PREFIX", "apply", "mirror", "offered", "on_changed", "read", "reapply"]

MATERIAL_PREFIX = "Geoblender look · "
"""El comienzo del nombre del material de visualización de un objeto (después, el nombre del objeto)."""

_Applier = Callable[[Any, str], None]
_mirroring = False  # mientras se escribe el espejo, su ``update`` no aplica


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    return (int(value[1:3], 16) / 255.0, int(value[3:5], 16) / 255.0, int(value[5:7], 16) / 255.0)


def _rgb_to_hex(rgb: Iterable[float]) -> str:
    return "#" + "".join(f"{min(255, max(0, int(c * 255 + 0.5))):02X}" for c in rgb)


def _visual_material(obj: Any) -> Any | None:
    """El material de visualización del objeto (el que lleva su nombre), creado y puesto si hace falta; ``None`` si el
    objeto no es una malla."""
    if obj.type != "MESH" or obj.data is None:
        return None
    name = MATERIAL_PREFIX + obj.name
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    if all(slot.material is not material for slot in obj.material_slots):
        obj.data.materials.append(material)
    return material


def _set_color(obj: Any, value: str) -> None:
    red, green, blue = _hex_to_rgb(value)
    obj.color = (red, green, blue, obj.color[3])
    material = bpy.data.materials.get(MATERIAL_PREFIX + obj.name)
    if material is not None:
        material.diffuse_color = (red, green, blue, material.diffuse_color[3])


def _set_transparency(obj: Any, value: str) -> None:
    alpha = 1.0 - int(value) / 100.0
    obj.color = (obj.color[0], obj.color[1], obj.color[2], alpha)
    material = bpy.data.materials.get(MATERIAL_PREFIX + obj.name)
    if material is None and alpha < 1.0:
        material = _visual_material(obj)
    if material is not None:
        material.diffuse_color = (obj.color[0], obj.color[1], obj.color[2], alpha)
        material.blend_method = "BLEND" if alpha < 1.0 else "HASHED"  # en 5.2, OPAQUE se guarda como HASHED (el predefinido)
        material.show_transparent_back = False


def _set_visible(obj: Any, value: str) -> None:
    try:
        obj.hide_set(value != "1")
    except RuntimeError:  # el objeto no está en la capa de vista actual: no hay qué ocultar
        pass


def _set_labels(obj: Any, value: str) -> None:
    obj.show_name = value == "1"


def _set_wire(obj: Any, value: str) -> None:
    obj.show_wire = value == "1"


def _label_is_mirror_only(_obj: Any, _value: str) -> None:
    """El rótulo no cambia nada del objeto aquí: lo que ve el Outliner lo pone ``scene.views.view_name`` (T10; P-2)."""


_COMMON: dict[str, _Applier] = {"label": _label_is_mirror_only, "visible": _set_visible}
_SURFACE: dict[str, _Applier] = {**_COMMON, "color": _set_color, "transparency": _set_transparency, "wire": _set_wire}
_LINES: dict[str, _Applier] = {**_COMMON, "color": _set_color}
APPLIERS: dict[str, dict[str, _Applier]] = {
    "PROJECT_ANCHOR": dict(_COMMON),
    "DTM": dict(_SURFACE), "TIN": dict(_SURFACE), "DESIGN": dict(_SURFACE), "DESIGN_ENTITY": dict(_SURFACE),
    "DRILLHOLES": {**_COMMON, "color": _set_color, "transparency": _set_transparency, "labels": _set_labels},
    "VOLUME_DIFFERENCE": {**_COMMON, "transparency": _set_transparency, "wire": _set_wire},
    "COMPLIANCE_GRID": {**_COMMON, "transparency": _set_transparency, "wire": _set_wire},
    "POINTS": {**_LINES, "labels": _set_labels},
    "BREAKLINES": dict(_LINES), "CONTOURS": dict(_LINES), "BOUNDARY": dict(_LINES),
    "CLIENT_INTENTION": dict(_LINES), "CONSTRAINT": dict(_LINES),
}
"""Por tipo (``Object.geoblender.kind``), lo que se sabe aplicar de cada propiedad."""


def offered(kind: str) -> tuple[str, ...]:
    """Las propiedades que se ofrecen del tipo ``kind``: las del catálogo que además tienen aplicador (A1; UI-13)."""
    have = APPLIERS.get(kind, {})
    return tuple(prop for prop in allowed(kind) if prop in have)


def apply(obj: Any, look: Appearance | Mapping[str, object]) -> None:
    """Aplica ``look`` (un :class:`Appearance` o ``{propiedad: valor}``) a la vista de ``obj``. Ignora lo que el tipo
    no ofrece. Solo toca la vista: ni la geometría ni la procedencia ni el proyecto."""
    kind = obj.geoblender.kind
    appliers = APPLIERS.get(kind, {})
    values = dict(look) if isinstance(look, Mapping) else look.as_dict()
    for prop in allowed(kind):
        fn = appliers.get(prop)
        if fn is not None and prop in values:
            fn(obj, validate(kind, prop, values[prop], name=obj.name))


def read(obj: Any) -> Appearance:
    """El espejo ``Object.geoblender.look`` de ``obj`` como :class:`Appearance` canónico, solo con lo que se ofrece."""
    look = obj.geoblender.look
    kind = obj.geoblender.kind
    raw: dict[str, object] = {
        "label": look.label, "color": _rgb_to_hex(look.color), "transparency": look.transparency,
        "visible": look.visible, "line_width": look.line_width, "point_size": look.point_size,
        "labels": look.labels, "wire": look.wire,
    }
    return Appearance(kind, tuple((prop, validate(kind, prop, raw[prop], name=obj.name))
                                  for prop in offered(kind) if prop != "label" or look.label.strip()))


def mirror(obj: Any, look: Appearance) -> None:
    """Escribe ``look`` en el espejo de ``obj`` **sin** aplicarlo (para ponerlo al día con la tabla)."""
    global _mirroring
    target = obj.geoblender.look
    _mirroring = True
    try:
        for prop, value in look:
            if prop == "color":
                target.color = _hex_to_rgb(value)
            elif prop == "label":
                target.label = value
            elif prop == "transparency":
                target.transparency = int(value)
            elif prop in ("visible", "labels", "wire"):
                setattr(target, prop, value == "1")
            elif prop in ("line_width", "point_size"):
                setattr(target, prop, float(value))
    finally:
        _mirroring = False


def on_changed(look_group: Any) -> None:
    """Lo que hace el ``update`` del espejo: aplicar al objeto lo que se ofrece de su tipo (no con el espejo en escritura)."""
    obj = look_group.id_data
    if _mirroring or not isinstance(obj, bpy.types.Object) or obj.geoblender.kind == "NONE":
        return
    apply(obj, read(obj))


def reapply(objects: Iterable[Any]) -> int:
    """Aplica el espejo de cada objeto de Geoblender de ``objects``; devuelve cuántos. (T08 lo cablea tras cargar y refrescar.)"""
    count = 0
    for obj in objects:
        if obj.geoblender.kind != "NONE":
            apply(obj, read(obj))
            count += 1
    return count
