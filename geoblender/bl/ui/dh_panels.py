# SPDX-License-Identifier: GPL-3.0-or-later
"""Pestaña «Sondeos» de la Vista 3D (spec 005, T24; RF-005-10, RF-005-11, RF-005-16, RF-005-19,
RF-005-20, RF-005-23 a RF-005-25; plan 005 §5.1 y §5.5).

Con un proyecto abierto, en la región lateral N de la Vista 3D, pestaña «Sondeos»:

- ``GEOBLENDER_PT_dh_pending`` («Importación pendiente»), solo mientras una importación de
  sondeos espera la decisión de la persona (``WindowManager.geoblender_dh_import``): los
  códigos nuevos y si se dan de alta (RF-005-10), cada sondeo que el proyecto ya tiene y si se
  conservan sus registros (RF-005-11), la sustitución que pide motivo y el motivo, y (T25)
  «Aplicar» y «Descartar» (la orden de la importación con ``stage`` y ``pending``); (T26) de
  una base de RecMin de esquema desconocido, el aviso y «Leer igualmente» (RF-005-15);
- ``GEOBLENDER_PT_dh_validation`` («Validación»): la lista de incidencias de la última
  validación (``GEOBLENDER_UL_dh_issues``), que se filtra por nivel y por código (RF-005-16), y
  las órdenes de validar, exportar el informe (RF-005-19) y calcular las trazas (RF-005-20);
- ``GEOBLENDER_PT_dh_display`` («Representación»): el esquema de logueo y el radio de los
  tubos, el elemento y las clases de las barras de leyes, su ancho y su separación, las
  etiquetas y la leyenda (RF-005-23 a RF-005-25), de ``Scene.geoblender_dh_display``.

Las órdenes se dibujan con su etiqueta del catálogo de la 003; las que aún no están disponibles
salen desactivadas con su motivo (su ``poll``). Los textos pasan por ``core.i18n.tr``; la
pestaña y los títulos se traducen al registrar (:func:`localize`), como la pestaña «Proyecto».
"""

from __future__ import annotations

from typing import Any

import bpy

from ...core.i18n import language, tr, translate
from ..props.dh import FILTER_ALL, IMPORT_PROPERTY, SCENE_PROPERTY, VALIDATION_PROPERTY
from ..scene import project_session
from . import commands

TRANSLATION_CONTEXT = "Geoblender"
TAB = "Drillholes"  # msgid de la pestaña
PENDING_LABEL = "Pending import"
VALIDATION_LABEL = "Validation"
DISPLAY_LABEL = "Display"
LIST = "GEOBLENDER_UL_dh_issues"
LIST_ROWS = 6
IMPORT_DRILLHOLES = "geoblender.dh_import_drillholes"
"""La orden de «Aplicar» y «Descartar» de la importación pendiente (con ``stage`` y
``pending``: plan 005 §5.3.1) si no dice otra (``command``: la de una base de RecMin, T26)."""
_ICONS = {"ERROR": "ERROR", "WARNING": "INFO"}


def _project_open() -> bool:
    return project_session.current() is not None


def _command(layout: Any, idname: str, icon: str) -> None:
    """La orden ``idname`` con su etiqueta del catálogo, en el idioma de Geoblender."""
    found = commands.catalog().commands.get(idname)
    label = commands.text(found.label) if found is not None else idname
    layout.operator(idname, text=label, icon=icon, translate=False)


class _DrillholesTab:
    """Lo común de los paneles de la pestaña «Sondeos» (sin base de Blender: NOM-01)."""

    bl_category = TAB
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_translation_context = TRANSLATION_CONTEXT

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _project_open()


class GEOBLENDER_PT_dh_pending(_DrillholesTab, bpy.types.Panel):
    """Drillhole import waiting for a decision: new codes and drillholes already in the
    project"""

    bl_idname = "GEOBLENDER_PT_dh_pending"
    bl_label = PENDING_LABEL

    @classmethod
    def poll(cls, context: Any) -> bool:
        pending = getattr(context.window_manager, IMPORT_PROPERTY, None)
        return _project_open() and bool(getattr(pending, "operation_uid", ""))

    def draw(self, context: Any) -> None:
        layout = self.layout
        pending = getattr(context.window_manager, IMPORT_PROPERTY)
        if not pending.operation_uid:
            layout.label(text=tr("No drillhole import is waiting for a decision"),
                         icon="INFO", translate=False)
            return
        if pending.confirm:  # una base de RecMin de esquema desconocido (RF-005-15)
            column = layout.column(align=True)
            for line in pending.confirm.splitlines():
                column.label(text=line, icon="ERROR", translate=False)
        if pending.new_codes:
            layout.label(text=tr("New codes: {codes}", codes=pending.new_codes),
                         icon="ERROR", translate=False)
            layout.prop(pending, "register_codes", text=tr("Register the new codes"),
                        translate=False)
        if pending.holes:
            layout.label(text=tr("Drillholes already in the project"), translate=False)
            column = layout.column(align=True)
            for hole in pending.holes:
                text = tr("{hole}: keep the existing records", hole=hole.name)
                column.prop(hole, "keep", text=text, translate=False)
        if pending.question:
            column = layout.column(align=True)
            for line in pending.question.splitlines():
                column.label(text=line, icon="QUESTION", translate=False)
            layout.prop(pending, "reason", text=tr("Reason"), translate=False)
        row = layout.row(align=True)
        apply = tr("Read it anyway") if pending.confirm else tr("Apply")
        for stage, text, icon in (("APPLY", apply, "CHECKMARK"),
                                  ("DISCARD", tr("Discard"), "CANCEL")):
            button = row.operator(pending.command or IMPORT_DRILLHOLES, text=text, icon=icon,
                                  translate=False)
            button.stage = stage
            button.pending = pending.operation_uid


class GEOBLENDER_UL_dh_issues(bpy.types.UIList):
    """Validation issues: level, code, drillhole and message"""

    bl_idname = LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        row = layout.row(align=True)
        row.label(text=item.code, icon=_ICONS.get(item.level, "DOT"), translate=False)
        row.label(text=item.hole, translate=False)
        row.label(text=item.message, translate=False)

    def filter_items(self, context: Any, data: Any, propname: str) -> tuple[list[int], list[int]]:
        """Solo las incidencias del nivel y con el código que piden los filtros (RF-005-16)."""
        level = data.level_filter
        code = data.code_filter.strip().casefold()
        shown = self.bitflag_filter_item
        flags = [shown if ((level == FILTER_ALL or item.level == level)
                           and (not code or code in item.code.casefold())) else 0
                 for item in getattr(data, propname)]
        return flags, []


class GEOBLENDER_PT_dh_validation(_DrillholesTab, bpy.types.Panel):
    """Validation of the drillhole database: issues by level and code, report and traces"""

    bl_idname = "GEOBLENDER_PT_dh_validation"
    bl_label = VALIDATION_LABEL

    def draw(self, context: Any) -> None:
        layout = self.layout
        validation = getattr(context.window_manager, VALIDATION_PROPERTY)
        row = layout.row(align=True)
        row.prop(validation, "level_filter", text=tr("Level"), translate=False)
        row.prop(validation, "code_filter", text=tr("Code"), translate=False)
        if validation.issues:
            layout.template_list(LIST, "", validation, "issues", validation, "issue_index",
                                 rows=LIST_ROWS)
        else:
            layout.label(text=tr("No validation issues to show"), icon="INFO",
                         translate=False)
        column = layout.column(align=True)
        _command(column, "geoblender.dh_validate", "CHECKMARK")
        _command(column, "geoblender.dh_export_validation_report", "EXPORT")
        _command(column, "geoblender.dh_desurvey", "CURVE_PATH")


class GEOBLENDER_PT_dh_display(_DrillholesTab, bpy.types.Panel):
    """Display of the drillholes: logging scheme, tubes, grade bars, labels and legend"""

    bl_idname = "GEOBLENDER_PT_dh_display"
    bl_label = DISPLAY_LABEL

    def draw(self, context: Any) -> None:
        layout = self.layout
        display = getattr(context.scene, SCENE_PROPERTY)
        layout.use_property_split = True
        layout.prop(display, "log_set", text=tr("Logging scheme"), translate=False)
        layout.prop(display, "tube_radius", text=tr("Tube radius"), translate=False)
        layout.prop(display, "element", text=tr("Element"), translate=False)
        if display.grade_classes:
            column = layout.column(align=True)
            for grade_class in display.grade_classes:
                row = column.row(align=True)
                row.prop(grade_class, "lower", text=tr("From"), translate=False)
                row.prop(grade_class, "color", text="")
        layout.prop(display, "bar_width", text=tr("Bar width"), translate=False)
        layout.prop(display, "bar_offset", text=tr("Bar separation"), translate=False)
        layout.prop(display, "show_labels", text=tr("Labels"), translate=False)
        row = layout.row()
        row.active = display.show_labels
        row.prop(display, "labels_at_end", text=tr("Depth at the bottom"), translate=False)
        layout.prop(display, "show_legend", text=tr("Legend"), translate=False)


def localize() -> None:
    """La pestaña y los títulos en el idioma de la interfaz (antes de registrar)."""
    for cls, label in ((GEOBLENDER_PT_dh_pending, PENDING_LABEL),
                       (GEOBLENDER_PT_dh_validation, VALIDATION_LABEL),
                       (GEOBLENDER_PT_dh_display, DISPLAY_LABEL)):
        cls.bl_category = tr("Drillholes")
        cls.bl_label = translate(language(), label)


# En orden de registro (la lista, antes del panel que la dibuja).
classes: tuple[type, ...] = (GEOBLENDER_PT_dh_pending, GEOBLENDER_UL_dh_issues,
                             GEOBLENDER_PT_dh_validation, GEOBLENDER_PT_dh_display)
