# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores reales del módulo ``ui`` (spec 003; plan 003 §5.3).

- ``geoblender.ui_toggle_mode`` (RF-003-01, RF-003-02; CW §2 y §3): conmuta la ventana
  entre Geoblender y Blender con ``bl.ui.switcher``; ``target`` = ``TOGGLE`` (por defecto,
  el atajo Ctrl+F10 y F3), ``GEOBLENDER`` o ``BLENDER`` (los dos botones del conmutador).
  Pedir el modo activo no hace nada. Si hubo que anexar el espacio de trabajo desde los
  recursos, lo dice. Funciona en los dos modos y desde cualquier editor (su atajo está en
  el mapa «Window»), así que no pasa por la puerta de modo. Sin ``UNDO``: conmutar no es
  un paso de deshacer (CW §3.3).

``bl_label`` y ``bl_description`` son los ``msgid`` del catálogo (contrato 1 del plan
003); ``bl.ui.registry`` los pone en el idioma de Geoblender al registrar la interfaz.
"""

from __future__ import annotations

from typing import Any

import bpy
from bpy.props import EnumProperty

from ...core.i18n import tr

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


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_OT_ui_toggle_mode,)
