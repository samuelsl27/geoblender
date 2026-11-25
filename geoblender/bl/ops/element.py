# SPDX-License-Identifier: GPL-3.0-or-later
"""``geoblender.ui_show_element`` (spec 019, T09; RF-019-06; UI-29): lleva a la ficha del elemento activo, en el editor de
Propiedades (pestaña Objeto). No escribe nada: solo cambia la pestaña que ve la persona."""

from __future__ import annotations

from typing import Any

import bpy

from ...core.i18n import tr

TRANSLATION_CONTEXT = "Geoblender"
OBJECT_TAB = "OBJECT"


def properties_spaces(context: Any) -> list[Any]:
    """Los espacios de Propiedades de las ventanas (los de todas las áreas)."""
    found = []
    for window in getattr(getattr(context, "window_manager", None), "windows", ()) or ():
        for area in getattr(getattr(window, "screen", None), "areas", ()) or ():
            if area.type == "PROPERTIES":
                found.append(area)
    return found


class GEOBLENDER_OT_ui_show_element(bpy.types.Operator):
    """Show the sheet of the active element in the Properties editor (Object tab). Nothing is written"""

    bl_idname = "geoblender.ui_show_element"
    bl_label = "Show the element sheet"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if getattr(context, "object", None) is not None:
            return True
        cls.poll_message_set(tr("Select an element of the project"))
        return False

    def execute(self, context: Any) -> set[str]:
        areas = properties_spaces(context)
        if not areas:
            self.report({"WARNING"}, tr("There is no Properties editor in this window"))
            return {"CANCELLED"}
        for area in areas:
            area.spaces.active.context = OBJECT_TAB
            area.tag_redraw()
        return {"FINISHED"}


classes: tuple[type, ...] = (GEOBLENDER_OT_ui_show_element,)
