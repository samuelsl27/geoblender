# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores del aspecto de los elementos (spec 019, T08; HU-019-1; RF-019-08, RF-019-09; plan 019 §5.3 y A2).

- ``geoblender.ui_appearance_reset`` (RF-019-09): devuelve el predefinido a una propiedad (``scope`` ``PROPERTY``, con
  ``prop``), a todo el elemento activo (``ELEMENT``) o a todos los seleccionados (``SELECTION``; con ``prop``, solo esa
  propiedad). Borra las filas de ``gb_appearance``, pone el espejo y la vista en el predefinido y lo dice: «Restablecido:
  <propiedad> de «<nombre>»». Cambia el espejo del objeto (por eso lleva ``UNDO``); la tabla manda tras un deshacer
  (``bl.scene.undo_watch``, R-5).
- ``geoblender.ui_appearance_flush`` (interno): escribe ya lo pendiente (A2); lo normal es el temporizador de 0,5 s. No
  empuja un paso de deshacer: no hay nada que deshacer en vaciar.

Solo escriben la tabla de aspecto del proyecto, y lo dicen en su descripción (UI-18): ni el dato, ni sus versiones ni su
procedencia cambian.
"""

from __future__ import annotations

from typing import Any

import bpy
from bpy.props import EnumProperty, StringProperty

from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ..scene import appearance

TRANSLATION_CONTEXT = "Geoblender"
SCOPE_ITEMS = [
    ("PROPERTY", "Property", ""),
    ("ELEMENT", "Element", ""),
    ("SELECTION", "Selection", ""),
]


def _is_element(obj: Any) -> bool:
    return obj is not None and obj.geoblender.kind != "NONE"


class GEOBLENDER_OT_ui_appearance_reset(bpy.types.Operator):
    """Restore the default appearance of the element (or of a property). Only the appearance table of the project is written: the data, its versions and its provenance do not change"""

    bl_idname = "geoblender.ui_appearance_reset"
    bl_label = "Reset appearance"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    scope: EnumProperty(  # type: ignore[valid-type]
        name="Scope", items=SCOPE_ITEMS, default="ELEMENT", options={"SKIP_SAVE"})
    prop: StringProperty(name="Property", default="", options={"SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        if _is_element(getattr(context, "object", None)) or any(_is_element(o) for o in context.selected_objects):
            return True
        cls.poll_message_set(tr("Select an element of the project"))
        return False

    def _targets(self, context: Any) -> list[Any]:
        if self.scope == "SELECTION":
            return [obj for obj in context.selected_objects if _is_element(obj)]
        return [context.object] if _is_element(context.object) else []

    def execute(self, context: Any) -> set[str]:
        targets = self._targets(context)
        if self.scope == "PROPERTY" and not self.prop:
            self.report({"ERROR"}, tr("Reset: nothing to reset"))
            return {"CANCELLED"}
        props = [self.prop] if self.prop else None
        if not targets:
            self.report({"WARNING"}, tr("Select an element of the project"))
            return {"CANCELLED"}
        try:
            done = appearance.reset(targets, props)
        except GeoblenderError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, appearance.reset_message(props, done))
        return {"FINISHED"}


class GEOBLENDER_OT_ui_appearance_flush(bpy.types.Operator):
    """Write now the appearance changes still waiting (they are written 0.5 s after the last change). Only the appearance table of the project is written"""

    bl_idname = "geoblender.ui_appearance_flush"
    bl_label = "Save the pending appearance"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"INTERNAL"}

    def execute(self, context: Any) -> set[str]:
        appearance.flush()
        return {"FINISHED"}


classes: tuple[type, ...] = (GEOBLENDER_OT_ui_appearance_reset, GEOBLENDER_OT_ui_appearance_flush)
