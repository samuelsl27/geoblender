# SPDX-License-Identifier: GPL-3.0-or-later
"""La **única** clase de preferencias de Geoblender (PLT-02; plan 002 §5.1 y §5.2).

``bl_idname`` es ``bl.ADDON_PACKAGE``, el paquete raíz de la extensión (3 componentes):
con el ``__package__`` de un submódulo Blender la registra sin error pero
``preferences.addons[…].preferences`` queda en ``None`` (docs/trampas.md §4). Una segunda
``AddonPreferences`` sustituiría a esta: cada módulo añade aquí **su grupo**
(``core`` en la spec 002; la 003 añade el grupo ``ui`` y la 004 el grupo ``jobs``).
"""

from __future__ import annotations

import bpy
from bpy.props import PointerProperty

from ...core.i18n import tr
from .. import ADDON_PACKAGE
from .core import GEOBLENDER_PG_core_preferences
from .ui import GEOBLENDER_PG_ui_preferences


class GeoblenderPreferences(bpy.types.AddonPreferences):
    """Preferencias de Geoblender, un grupo por módulo."""

    bl_idname = ADDON_PACKAGE

    core: PointerProperty(type=GEOBLENDER_PG_core_preferences)  # type: ignore[valid-type]
    ui: PointerProperty(type=GEOBLENDER_PG_ui_preferences)  # type: ignore[valid-type]

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        column = layout.column()
        column.label(text=tr("Project"), translate=False)
        column.prop(
            self.core, "lock_stale_minutes", text=tr("Stale lock after (min)"),
            translate=False,
        )
        column.prop(
            self.core, "checkout_dir", text=tr("Local copies folder"), translate=False
        )
        self.draw_ui(layout.column())

    def draw_ui(self, column: bpy.types.UILayout) -> None:
        """El grupo ``ui`` (spec 003): idioma, títulos de la barra, fila de acceso rápido,
        «Ocultar lo no disponible» y barra de estado minera."""
        ui = self.ui
        column.separator()
        column.label(text=tr("Interface"), translate=False)
        row = column.row(align=True)
        row.label(text=tr("Geoblender language"), translate=False)
        row.prop_enum(ui, "language", "ES", text=tr("Spanish"), translate=False)
        row.prop_enum(ui, "language", "EN", text=tr("English"), translate=False)
        row = column.row(align=True)
        row.label(text=tr("Top bar titles"), translate=False)
        row.prop_enum(ui, "topbar_titles", "AUTO", text=tr("Automatic"), translate=False)
        row.prop_enum(ui, "topbar_titles", "TEXT", text=tr("Text"), translate=False)
        row.prop_enum(ui, "topbar_titles", "ICONS", text=tr("Icons"), translate=False)
        column.prop(ui, "show_view_quick_access", text=tr("Quick access row of the view"),
                    translate=False)
        column.prop(ui, "hide_unavailable", text=tr("Hide what is not available yet"),
                    translate=False)
        column.prop(ui, "show_mining_statusbar", text=tr("Mining status bar"),
                    translate=False)


# En orden de registro: los grupos (bl/props/core.py) ya están registrados antes.
classes: tuple[type, ...] = (GeoblenderPreferences,)
