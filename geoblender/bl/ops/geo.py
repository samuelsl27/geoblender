# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores del módulo ``geo`` (sección y recorte de la vista).

- ``geoblender.geo_set_clip_mode`` (spec 003, D-1; RF-003-15, RF-003-07; BS §8.12; AR §3.1,
  n.º 15; Alt+0 para «Sin recorte»): el modo de recorte de la Vista 3D de destino
  (``bl.ui.views``). La 003 entrega «Sin recorte» (``NONE``: quita los planos de recorte
  de esa región) y «Banda de la vista» (``BAND``: oculta lo que queda a más de
  ±``half_width`` del plano que pasa por el cursor 3D perpendicular a la mirada; de 0,1 a
  1000 m, 5 por defecto, y se ajusta con F9). Los demás modos (``FRONT``, ``BACK``,
  ``BAND_FADED``) son de R-16: invocados, informan «Disponible en R-16 · …» y no cambian
  nada, como un comando provisional. Su ``bl_label`` es el del menú donde viven sus
  variantes («Recorte», regla de ``bl.ui.provisional.base_command``); la descripción
  emergente, la del modo pedido. Pasa por la puerta de modo (tiene atajo en la Vista 3D) y
  lleva ``UNDO`` para que F9 lo repita con otro semiancho.
"""

from __future__ import annotations

from typing import Any

import bpy
from bpy.props import EnumProperty, FloatProperty

from ...core.i18n import tr
from ..ui import gate

TRANSLATION_CONTEXT = "Geoblender"
# Modos de recorte (BS §8.12): los nombres son las etiquetas del catálogo.
MODE_ITEMS = [
    ("NONE", "No clipping", ""),
    ("FRONT", "Front", ""),
    ("BACK", "Back", ""),
    ("BAND", "View band", ""),
    ("BAND_FADED", "Faded band", ""),
]
DELIVERED_MODES = frozenset({"NONE", "BAND"})  # D-1: los demás, con R-16
HALF_WIDTH_MIN_M = 0.1
HALF_WIDTH_MAX_M = 1000.0
HALF_WIDTH_DEFAULT_M = 5.0


class GEOBLENDER_OT_geo_set_clip_mode(bpy.types.Operator):
    """Clipping of the view: none, front, back, band or faded band"""

    bl_idname = "geoblender.geo_set_clip_mode"
    bl_label = "Clipping"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(  # type: ignore[valid-type]
        name="Mode", items=MODE_ITEMS, default="NONE", options={"SKIP_SAVE"},
    )
    half_width: FloatProperty(  # type: ignore[valid-type]
        name="Half width",
        description="Half width of the band, on each side of the plane through the 3D cursor",
        min=HALF_WIDTH_MIN_M,
        max=HALF_WIDTH_MAX_M,
        default=HALF_WIDTH_DEFAULT_M,
        subtype="DISTANCE",
        unit="LENGTH",
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        from ..ui import views  # diferido, como en bl/ops/ui.py

        if not gate.poll(cls, context):
            return False
        if views.target_view3d(context) is None:
            cls.poll_message_set(tr("There is no 3D view in this window"))
            return False
        return True

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        from ..ui import commands, provisional

        cat = commands.catalog()
        cmd = provisional.variant_for(cat, cls.bl_idname, properties)
        about = commands.text(cmd.description) if cmd is not None else ""
        if getattr(properties, "mode", "") in DELIVERED_MODES:
            return about
        note = provisional.message(cat, cls.bl_idname, properties)
        return f"{about}\n{note}" if about and note else (about or note)

    def execute(self, context: Any) -> set[str]:
        from ..ui import commands, provisional, views

        if self.mode not in DELIVERED_MODES:
            self.report({"INFO"}, provisional.message(
                commands.catalog(), commands.command_idname(self.bl_idname), self.properties))
            return {"CANCELLED"}
        target = views.target_view3d(context)
        if target is None:
            return {"CANCELLED"}
        if self.mode == "NONE":
            views.clear_clip(target)
        else:
            views.set_band(target, context.scene.cursor.location, self.half_width)
        return {"FINISHED"}


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_OT_geo_set_clip_mode,)
