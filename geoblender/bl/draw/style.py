# SPDX-License-Identifier: GPL-3.0-or-later
"""El grosor de línea y el tamaño de punto de un objeto, tal como los guarda su aspecto (spec 019, T07b; RF-019-07).

Las superposiciones de ``bl/draw`` dibujan sobre el alambre de Blender (1 px, global), así que no tienen un grosor
propio por objeto: lo toman del espejo ``Object.geoblender.look`` (``line_width`` y ``point_size``) **solo si alguien
lo guardó** (``is_property_set``). Sin valor guardado, :func:`stored` da ``None`` y quien dibuja usa lo de siempre
(el predefinido de cada cargador): lo que se ve no cambia. Este módulo no importa ``gpu`` ni dibuja: son las
funciones puras (y medibles) que deciden qué valor se pasa al *shader*.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import bpy

from ..props.core import OBJECT_PROPERTY

__all__ = ["LINE_KINDS", "NATIVE_WIDTH", "POINT_KINDS", "Stroke", "candidates", "index_factor", "invalidate", "note", "plan",
           "stored"]

LINE_KINDS = frozenset({"BREAKLINES", "CONTOURS", "BOUNDARY", "CLIENT_INTENTION", "CONSTRAINT"})
"""Los tipos de objeto de aristas sueltas a los que se les dibuja el grosor de línea guardado."""
POINT_KINDS = frozenset({"POINTS"})
"""Los tipos de objeto de vértices sueltos a los que se les dibuja el tamaño de punto guardado."""
NATIVE_WIDTH = 1.0
"""El grosor del alambre de Blender, en px: con un valor guardado de 1 o menos no se dibuja nada encima."""


_styled: dict[int, Any] = {}
_dirty = True


def note(obj: Any) -> None:
    """Anota que ``obj`` tiene un valor guardado (lo llama el ``update`` del espejo): así cada fotograma mira solo
    estos objetos y no recorre todos los de la escena."""
    _styled[obj.session_uid] = obj


def invalidate() -> None:
    """Pide rehacer la lista de objetos con valor guardado en el próximo dibujo (tras abrir un ``.blend`` o deshacer)."""
    global _dirty
    _dirty = True


def candidates() -> list[Any]:
    """Los objetos de Geoblender con un grosor o un tamaño guardado (el recorrido de todos los objetos solo se hace
    la primera vez y tras :func:`invalidate`; un objeto borrado se descarta)."""
    global _dirty
    if _dirty:
        _styled.clear()
        for obj in bpy.data.objects:
            if any(stored(obj, prop) is not None for prop in ("line_width", "point_size")):
                note(obj)
        _dirty = False
    alive: list[Any] = []
    for key, obj in list(_styled.items()):
        try:
            obj.name  # noqa: B018 - falla con ReferenceError si el objeto ya no existe
        except ReferenceError:
            del _styled[key]
        else:
            alive.append(obj)
    return alive


@dataclass(frozen=True)
class Stroke:
    """Lo que se dibuja de un objeto: su ``primitive`` (``LINES`` o ``POINTS``) con ``size_px`` px (ya por el tamaño de
    píxel de la interfaz) y si el color es el de su aspecto (``own_color``) o el del tema."""

    obj: Any
    primitive: str
    size_px: float
    own_color: bool


def stored(obj: Any, prop: str) -> float | None:
    """El valor guardado de ``prop`` (``line_width`` o ``point_size``) en el aspecto de ``obj``; ``None`` si el objeto
    no es de Geoblender, no tiene aspecto o nadie lo cambió (se usa entonces lo de siempre)."""
    group = getattr(obj, OBJECT_PROPERTY, None)
    look = getattr(group, "look", None)
    if look is None or not look.is_property_set(prop):
        return None
    return float(getattr(look, prop))


def index_factor(obj: Any) -> float:
    """Por cuánto se multiplica el trazo de las curvas maestras de ``obj``: el ``line_width`` guardado (predefinido 1,
    que deja los 3 px de siempre) o 1 si no hay ninguno."""
    value = stored(obj, "line_width")
    return 1.0 if value is None else value


def plan(objects: Iterable[Any], *, pixel_size: float) -> list[Stroke]:
    """Qué se dibuja de ``objects`` por su aspecto: las aristas de los tipos de :data:`LINE_KINDS` con un grosor guardado
    mayor que el del alambre, y los vértices de los de :data:`POINT_KINDS` con un tamaño guardado. Sin valor guardado
    (o de 1 px o menos en las líneas), nada."""
    strokes: list[Stroke] = []
    for obj in objects:
        kind = getattr(getattr(obj, OBJECT_PROPERTY, None), "kind", None)
        if kind in LINE_KINDS:
            width = stored(obj, "line_width")
            if width is not None and width > NATIVE_WIDTH:
                strokes.append(Stroke(obj, "LINES", width * float(pixel_size), obj.geoblender.look.is_property_set("color")))
        elif kind in POINT_KINDS:
            size = stored(obj, "point_size")
            if size is not None:
                strokes.append(Stroke(obj, "POINTS", size * float(pixel_size), obj.geoblender.look.is_property_set("color")))
    return strokes
