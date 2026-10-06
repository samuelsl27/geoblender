# SPDX-License-Identifier: GPL-3.0-or-later
"""La **única** clase de preferencias de Geoblender (PLT-02; plan 002 §5.1 y §5.2).

``bl_idname`` es ``bl.ADDON_PACKAGE``, el paquete raíz de la extensión (3 componentes):
con el ``__package__`` de un submódulo Blender la registra sin error pero
``preferences.addons[…].preferences`` queda en ``None`` (docs/trampas.md §4). Una segunda
``AddonPreferences`` sustituiría a esta: cada módulo añade aquí **su grupo**
(``core`` en la spec 002; la 003 añade los campos de ``ui`` y la 004 el grupo ``jobs``).
"""

from __future__ import annotations

import bpy
from bpy.props import PointerProperty

from .. import ADDON_PACKAGE
from .core import GEOBLENDER_PG_core_preferences


class GeoblenderPreferences(bpy.types.AddonPreferences):
    """Preferencias de Geoblender, un grupo por módulo."""

    bl_idname = ADDON_PACKAGE

    core: PointerProperty(type=GEOBLENDER_PG_core_preferences)  # type: ignore[valid-type]

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        column = layout.column()
        column.label(text="Project", translate=False)
        column.prop(self.core, "lock_stale_minutes")
        column.prop(self.core, "checkout_dir")


# En orden de registro: los grupos (bl/props/core.py) ya están registrados antes.
classes: tuple[type, ...] = (GeoblenderPreferences,)
