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

from ...core.i18n import language, tr
from ...core.inputs.guard import read_only_warnings
from ...core.paths import READ_ONLY_DIRS_ENV
from .. import ADDON_PACKAGE
from .core import GEOBLENDER_PG_core_preferences, read_only_dirs_of
from .jobs import SET_EXTERNAL_PYTHON, GEOBLENDER_PG_jobs_preferences
from .ui import GEOBLENDER_PG_ui_preferences


class GeoblenderPreferences(bpy.types.AddonPreferences):
    """Preferencias de Geoblender, un grupo por módulo."""

    bl_idname = ADDON_PACKAGE

    core: PointerProperty(type=GEOBLENDER_PG_core_preferences)  # type: ignore[valid-type]
    ui: PointerProperty(type=GEOBLENDER_PG_ui_preferences)  # type: ignore[valid-type]
    jobs: PointerProperty(type=GEOBLENDER_PG_jobs_preferences)  # type: ignore[valid-type]

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        self.draw_core(layout.column())
        self.draw_ui(layout.column())
        self.draw_jobs(layout.column())

    def draw_core(self, column: bpy.types.UILayout) -> None:
        """El grupo ``core`` (spec 002 y spec 008): umbral del cerrojo, carpeta de las copias
        locales y carpetas de solo lectura del usuario (separadas por «;») con, debajo, las de
        la variable ``GEOBLENDER_READ_ONLY_DIRS``, que se ven sin poder editarlas, y los avisos
        (ninguna carpeta, o una que no es una ruta completa; RF-008-15, plan 008 §5.5)."""
        core = self.core
        column.label(text=tr("Project"), translate=False)
        column.prop(core, "lock_stale_minutes", text=tr("Stale lock after (min)"),
                    translate=False)
        column.prop(core, "checkout_dir", text=tr("Local copies folder"), translate=False)
        column.prop(core, "read_only_folders", text=tr("Read-only folders"), translate=False)
        dirs = read_only_dirs_of(core)
        listed = column.column(align=True)
        listed.active = False  # de la variable de la empresa: aquí solo se ven
        if dirs.env_folders:
            listed.label(text=tr("From the variable {variable}:", variable=READ_ONLY_DIRS_ENV),
                         translate=False)
            for folder in dirs.env_folders:
                listed.label(text=str(folder), icon="LOCKED", translate=False)
        else:
            listed.label(text=tr("The variable {variable} declares no folder",
                                 variable=READ_ONLY_DIRS_ENV), translate=False)
        warnings = read_only_warnings(dirs, language())
        if warnings:
            alert = column.column(align=True)
            alert.alert = True
            for text in warnings:
                alert.label(text=text, icon="ERROR", translate=False)

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

    def draw_jobs(self, column: bpy.types.UILayout) -> None:
        """El grupo ``jobs`` (spec 004; plan 004 §5.2.7): trabajos a la vez en proceso
        aparte, días que se conservan los terminados, origen del motor de cálculo,
        almacén de ruedas e intérprete externo. La ruta del intérprete externo se ve sin
        poder editarla: solo la guarda, después de comprobarla,
        ``geoblender.jobs_set_external_python`` (RF-004-26), con sus botones de elegirla y
        de quitarla al lado."""
        jobs = self.jobs
        column.separator()
        column.label(text=tr("Background jobs"), translate=False)
        column.prop(jobs, "max_parallel_jobs", text=tr("Jobs at once (separate process)"),
                    translate=False)
        column.prop(jobs, "retention_days", text=tr("Keep finished jobs (days)"),
                    translate=False)
        column.prop(jobs, "runtime_source", text=tr("Compute engine source"),
                    translate=False)
        column.prop(jobs, "wheelhouse_dir", text=tr("Wheel store folder"), translate=False)
        column.prop(jobs, "use_external_python", text=tr("Use an external interpreter"),
                    translate=False)
        row = column.row(align=True)
        path = row.row(align=True)
        path.enabled = False
        path.prop(jobs, "external_python", text=tr("External interpreter"), translate=False)
        row.operator(SET_EXTERNAL_PYTHON, text="", icon="FILEBROWSER")
        row.operator(SET_EXTERNAL_PYTHON, text="", icon="X").clear = True


# En orden de registro: los grupos (bl/props/core.py, ui.py y jobs.py) ya están
# registrados antes.
classes: tuple[type, ...] = (GeoblenderPreferences,)
