# SPDX-License-Identifier: GPL-3.0-or-later
"""Pestaña «Proyecto» de la Vista 3D (spec 002; RF-002-13, RF-002-30, RF-002-31,
RF-002-32, RF-002-34; plan 002 §5.5).

``GEOBLENDER_PT_core_project`` (región lateral N, pestaña «Proyecto»): mientras hay un
proyecto abierto, su nombre, el modo de apertura (y, en solo lectura, su motivo, siempre a
la vista), el CRS horizontal y vertical, el GeoOrigin, la ventana de trabajo y el paso de
rejilla (:func:`project_rows`, coordenadas con espacio fino de miles), el diario de la base
(«clásico»), si la vista está desfasada y los avisos pendientes; y los botones del
proyecto (en el original, sacar una copia local; en la copia, publicarla). Sin proyecto,
cómo crear o abrir uno y, si el fichero cargado es vista de un proyecto que no está abierto,
«Abrir el proyecto de esta vista» (spec 010, T12; RF-010-04: ``bl.scene.view_link``).

Todos los textos pasan por ``core.i18n.tr``. La pestaña y el título se traducen al
registrar (:func:`localize`): ``bl_category`` y ``bl_label`` son textos fijos de la clase.
"""

from __future__ import annotations

import time
from typing import Any

import bpy

from ...core.errors import GeoblenderError
from ...core.gpkg.header import read_header
from ...core.i18n import tr
from ...core.project.model import OpenMode
from ..scene import project_session, view_link
from . import labels

TRANSLATION_CONTEXT = "Geoblender"
PANEL_LABEL = "Project"  # msgid de la pestaña y del título
JOURNAL_TTL_S = 5.0  # el diario se vuelve a mirar como mucho cada 5 s (en red cuesta)
NOTICES_SHOWN = 3
_READ_ONLY_PREFIX = "Solo lectura: "  # el que pone core.project a su motivo

_journal_cache: dict[str, tuple[float, str]] = {}


def _mode_name(mode: OpenMode) -> str:
    if mode is OpenMode.WRITE_NETWORK:
        return tr("writing on the network (cache on this computer)")
    if mode is OpenMode.CHECKOUT:
        return tr("writing in a local working copy")
    return tr("writing (local disk)")


def mode_text(project: Any) -> str:
    """El modo de apertura con su motivo en solo lectura (RF-002-13)."""
    status = project.status
    if status.writable:
        return tr("Mode: {mode}", mode=_mode_name(status.mode))
    return tr("Mode: read-only: {reason}", reason=status.message.removeprefix(_READ_ONLY_PREFIX))


def project_rows(project: Any) -> list[tuple[str, str]]:
    """(icono, texto) de los seis datos de RF-002-34: nombre, modo, CRS horizontal y
    vertical, GeoOrigin, ventana de trabajo y paso de rejilla."""
    # Diferido: bl/ops importa bl/ui (la puerta de modo, contrato 2 del plan 003), y bl/ui
    # no importa bl/ops al cargarse (ARQ-08).
    from ..ops.core import crs_lines, origin_lines

    horizontal, vertical = crs_lines(project)
    origin, window, step = origin_lines(project)
    return [
        ("FILE_FOLDER", tr("Name: {name}", name=project.name)),
        ("UNLOCKED" if project.writable else "LOCKED", mode_text(project)),
        ("WORLD", horizontal),
        ("EMPTY_SINGLE_ARROW", vertical),
        ("OBJECT_ORIGIN", origin),
        ("SELECT_SET", window),
        ("GRID", step),
    ]


def _rows(column: Any, text: str, icon: str, width_px: float, *, alert: bool = False) -> None:
    """``text`` como una etiqueta con ``icon`` si cabe en ``width_px`` (tal cual, con sus espacios) y, si no, en las líneas que caben (``labels.wrapped``; la primera con el icono, las demás con
    su hueco), todas en alerta si ``alert``: Blender corta con «…» una etiqueta que no cabe y el dato no se lee (spec 018, T40f)."""
    lines = labels.wrapped(text, width_px, icon=True)
    for index, line in enumerate(lines if len(lines) > 1 else [text]):
        row = column.row()
        row.alert = alert
        row.label(text=line, icon=icon if index == 0 else "BLANK1", translate=False)


def journal_text(project: Any) -> str:
    """El diario de la base (clásico o WAL), mirado como mucho cada 5 s."""
    key = str(project.root)
    now = time.monotonic()
    cached = _journal_cache.get(key)
    if cached is not None and now - cached[0] < JOURNAL_TTL_S:
        return cached[1]
    try:
        header = read_header(project.database_path)
    except (GeoblenderError, OSError):
        text = tr("Journal: unknown")
    else:
        text = (
            tr("Journal: WAL (it is converted back to classic when writing)")
            if header.needs_recovery
            else tr("Journal: classic")
        )
    _journal_cache[key] = (now, text)
    return text


def _view_is_stale() -> bool:
    return any(scene.geoblender.view_stale for scene in bpy.data.scenes)


class GEOBLENDER_PT_core_project(bpy.types.Panel):
    """Geoblender project: name, mode, CRS, GeoOrigin, work window and grid step"""

    bl_idname = "GEOBLENDER_PT_core_project"
    bl_label = PANEL_LABEL
    bl_category = PANEL_LABEL
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_translation_context = TRANSLATION_CONTEXT

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        project = project_session.current()
        if project is None:
            _rows(layout.column(align=True), tr("No project is open"), "INFO", labels.sidebar_width(context))
            self.draw_view_offer(context, layout)
            column = layout.column(align=True)
            column.operator("geoblender.core_new_project", text=tr("New project…"),
                            icon="FILE_NEW", translate=False)
            column.operator("geoblender.core_open_project", text=tr("Open project…"),
                            icon="FILE_FOLDER", translate=False)
            column.menu("GEOBLENDER_MT_core_recent", text=tr("Open recent"),
                        icon="RECOVER_LAST", translate=False)
            self.draw_notices(layout, context)
            return
        box = layout.box()
        column = box.column(align=True)
        width = labels.sidebar_width(context)
        for icon, text in project_rows(project):  # cada dato en las líneas que caben: la barra lateral estrecha no los corta con «…» (T40f)
            locked = icon == "LOCKED"
            _rows(column, text, icon, width, alert=locked)
            if locked:  # el rojo dice qué es: el proyecto no admite cambios
                _rows(column, tr("Read-only: nothing can be saved in the project; the reason is above"), "BLANK1", width, alert=True)
        _rows(column, journal_text(project), "FILE_BLEND", width)
        if _view_is_stale():
            row = layout.row()
            row.alert = True
            row.label(text=tr("The view is out of date: reload its data"), icon="ERROR",
                      translate=False)
        self.draw_notices(layout, context)
        column = layout.column(align=True)
        column.operator("geoblender.core_save_project", text=tr("Save"), icon="FILE_TICK",
                        translate=False)
        column.operator("geoblender.core_set_work_window", text=tr("Work window…"),
                        icon="SELECT_SET", translate=False)
        column.operator("geoblender.core_set_crs", text=tr("Reference system…"),
                        icon="WORLD", translate=False)
        column.operator("geoblender.core_show_geoorigin", text=tr("GeoOrigin…"),
                        icon="OBJECT_ORIGIN", translate=False)
        column.operator("geoblender.core_show_lock", text=tr("Project lock…"),
                        icon="LOCKED", translate=False)
        if project.is_checkout:
            column.operator("geoblender.core_publish_project",
                            text=tr("Publish to the network…"), icon="NETWORK_DRIVE",
                            translate=False)
        else:
            column.operator("geoblender.core_checkout_project",
                            text=tr("Work on a local copy…"), icon="DISK_DRIVE",
                            translate=False)
        column = layout.column(align=True)
        column.operator("geoblender.core_open_project", text=tr("Open project…"),
                        icon="FILE_FOLDER", translate=False)
        column.menu("GEOBLENDER_MT_core_recent", text=tr("Open recent"),
                    icon="RECOVER_LAST", translate=False)
        column.operator("geoblender.core_new_project", text=tr("New project…"),
                        icon="FILE_NEW", translate=False)
        column.operator("geoblender.core_close_project", text=tr("Close project"),
                        icon="PANEL_CLOSE", translate=False)

    def draw_view_offer(self, context: Any, layout: Any) -> None:
        """Sin proyecto, mientras el fichero cargado sea vista de un proyecto que no está
        abierto (``view_link.current_offer``): de qué proyecto es y «Abrir el proyecto de esta
        vista», con su diálogo (spec 010, T12; RF-010-04; plan R3: por si el diálogo se cerró
        sin respuesta o se pulsó «Ahora no»)."""
        offer = view_link.current_offer()
        if offer is None:
            return
        box = layout.box()
        labels.draw_wrapped(box, view_link.panel_text(offer), labels.sidebar_width(context),
                            icon="FILE_BLEND")
        # Sin icono: así cabe en la barra lateral de por defecto (con él, no).
        button = box.operator(view_link.OPEN_VIEW_PROJECT,
                              text=tr("Open the project of this view"), translate=False)
        for name, value in offer.properties().items():
            setattr(button, name, value)

    def draw_notices(self, layout: Any, context: Any = None) -> None:
        """Los últimos avisos pendientes (de los manejadores y del temporizador) y el
        botón para descartarlos."""
        pending = project_session.notices()
        if not pending:
            return
        box = layout.box()
        column = box.column(align=True)
        column.alert = True
        width = labels.sidebar_width(context)
        for message in pending[-NOTICES_SHOWN:]:  # partido en las líneas que caben: no se corta con «…» (spec 019, T42)
            _rows(column, message, "ERROR", width, alert=True)
        box.operator("geoblender.core_clear_notices", text=tr("Dismiss"), icon="X",
                     translate=False)


def localize() -> None:
    """La pestaña y el título en el idioma de la interfaz (antes de registrar)."""
    GEOBLENDER_PT_core_project.bl_category = tr("Project")
    GEOBLENDER_PT_core_project.bl_label = tr("Project")


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_PT_core_project,)
