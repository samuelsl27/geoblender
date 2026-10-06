# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores reales del módulo ``ui`` (spec 003; plan 003 §5.3).

- ``geoblender.ui_toggle_mode`` (RF-003-01, RF-003-02; CW §2 y §3): conmuta la ventana
  entre Geoblender y Blender con ``bl.ui.switcher``; ``target`` = ``TOGGLE`` (por defecto,
  el atajo Ctrl+F10 y F3), ``GEOBLENDER`` o ``BLENDER`` (los dos botones del conmutador).
  Pedir el modo activo no hace nada. Si hubo que anexar el espacio de trabajo desde los
  recursos, lo dice. Funciona en los dos modos y desde cualquier editor (su atajo está en
  el mapa «Window»), así que no pasa por la puerta de modo. Sin ``UNDO``: conmutar no es
  un paso de deshacer (CW §3.3).
- ``geoblender.ui_call_pie`` y ``geoblender.ui_call_panel`` (internos; RF-003-18,
  RF-003-19; AT §1, regla 2): abren un menú circular (``name``) o un panel flotante
  (``name``, ``keep_open``) de Geoblender con ``wm.call_menu_pie`` y ``wm.call_panel``,
  que no saben del modo: sus atajos están en la Vista 3D, así que pasan por la puerta de
  modo (``bl.ui.gate``) y en modo Blender la tecla queda para Blender.

``bl_label`` y ``bl_description`` son los ``msgid`` del catálogo (contrato 1 del plan
003); ``bl.ui.registry`` los pone en el idioma de Geoblender al registrar la interfaz.
"""

from __future__ import annotations

from typing import Any

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ...core.i18n import tr
from ..ui import gate

TRANSLATION_CONTEXT = "Geoblender"
TARGET_ITEMS = [
    ("TOGGLE", "Toggle", "Switch to the other interface"),
    ("GEOBLENDER", "Geoblender", "Switch to the Geoblender interface"),
    ("BLENDER", "Blender", "Switch to the Blender interface"),
]


class GEOBLENDER_OT_ui_toggle_mode(bpy.types.Operator):
    """Switch this window between the Geoblender interface and the Blender one"""

    bl_idname = "geoblender.ui_toggle_mode"
    bl_label = "Switch Geoblender ⇄ Blender"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    target: EnumProperty(  # type: ignore[valid-type]
        name="Target",
        items=TARGET_ITEMS,
        default="TOGGLE",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return getattr(context, "window", None) is not None

    def execute(self, context: Any) -> set[str]:
        from ..ui import switcher  # diferido: bl/ui importa bl/ops

        result = switcher.toggle(context.window, self.target)
        if result.workspace is None:
            return {"CANCELLED"}
        if result.appended:
            self.report({"INFO"}, tr("The Geoblender workspace has been added to this file"))
        return {"FINISHED"}


class GEOBLENDER_OT_ui_call_pie(bpy.types.Operator):
    """Open a Geoblender pie menu (only in Geoblender mode)"""

    bl_idname = "geoblender.ui_call_pie"
    bl_label = "Pie menu"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"INTERNAL"}

    name: StringProperty(name="Menu", default="", options={"SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return gate.poll(cls, context)

    def execute(self, context: Any) -> set[str]:
        return bpy.ops.wm.call_menu_pie(name=self.name)

    def invoke(self, context: Any, event: Any) -> set[str]:
        return self.execute(context)


class GEOBLENDER_OT_ui_call_panel(bpy.types.Operator):
    """Open a Geoblender panel at the cursor (only in Geoblender mode)"""

    bl_idname = "geoblender.ui_call_panel"
    bl_label = "Floating panel"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"INTERNAL"}

    name: StringProperty(name="Panel", default="", options={"SKIP_SAVE"})  # type: ignore[valid-type]
    keep_open: BoolProperty(name="Keep open", default=False, options={"SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return gate.poll(cls, context)

    def execute(self, context: Any) -> set[str]:
        return bpy.ops.wm.call_panel(name=self.name, keep_open=self.keep_open)

    def invoke(self, context: Any, event: Any) -> set[str]:
        return self.execute(context)


# En orden de registro.
classes: tuple[type, ...] = (
    GEOBLENDER_OT_ui_toggle_mode,
    GEOBLENDER_OT_ui_call_pie,
    GEOBLENDER_OT_ui_call_panel,
)
