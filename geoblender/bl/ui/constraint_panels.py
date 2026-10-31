# SPDX-License-Identifier: GPL-3.0-or-later
"""Las ventanas de los límites y las restricciones (spec 012; plan 012 §5.1, §5.3.4, §5.5, D-12,
D-14, D-31).

**Límites…** (T22; HU-012-1; RF-012-01, RF-012-02, RF-012-05, RF-012-15, RF-012-28): la ventana
``GEOBLENDER_PT_core_limits`` (la abre ``geoblender.core_edit_limits``, ``bl.ops.core_constraints``)
dibuja lo que hay en ``WindowManager.geoblender_constraints`` (``bl.props.core_constraints``):

- el **informe de los límites** declarados en la versión activa (:func:`limit_lines`): el límite
  legal, su resguardo hacia dentro, el perímetro de actuación (o, sin él, que el límite legal hace
  de perímetro, D-14), su intersección y la franja de solo relleno con m² y ha (D-12), cada parte
  de la franja con su área y su centro absoluto y «Ir a» (``geoblender.core_go_to_place``), lo que
  queda fuera de la rejilla de cada límite (RF-012-15) y lo que impide compilarlos (RF-012-04);
- el **formulario** para declararlos: las capas de polígonos del proyecto (:func:`polygon_layers`:
  «entidades» de polígonos y «dominios») con las casillas de límite legal y de perímetro de
  actuación, el campo del nombre (opcional), el motivo, el decisor, la fecha y el resguardo hacia
  dentro, y «Declarar los límites» (``geoblender.core_declare_limits``).

En solo lectura o con la versión activa no editable dice por qué y dibuja desactivado lo que
escribe (RF-012-28). **Nada se lee al dibujar**: :func:`fill_limits` regenera la vista desde el
proyecto (al abrir la ventana y tras declarar). Los textos pasan por ``core.i18n`` y se dibujan
con ``translate=False``; las coordenadas absolutas, en texto (ADR-0005).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import bpy

from ...core.catalog.search import path_text
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, language, tr
from ...core.params.model import format_value
from ...gis import provenance as gis_provenance
from ...gis import store as gis_store
from ...gis.masks import store as mask_store
from .. import compat
from ..props.core_constraints import WINDOW_MANAGER_PROPERTY
from ..scene import versions as scene_versions
from . import labels
from .commands import catalog, text

LOGGER = logging.getLogger("geoblender.bl.ui")
TRANSLATION_CONTEXT = "Geoblender"
LIMITS_PANEL = "GEOBLENDER_PT_core_limits"
DECLARE_LIMITS = "geoblender.core_declare_limits"
GO_TO_PLACE = "geoblender.core_go_to_place"
IMPORT_VECTOR = "geoblender.gis_import_vector"
LIMITS_PANEL_UNITS = 36
LIMITS_WIDTH_PX = LIMITS_PANEL_UNITS * compat.UI_UNIT_PX
"""El ancho de la ventana Límites (36 unidades, como la de los materiales)."""
PLACE_MIN_RADIUS_M = 25.0
PLACE_AREA_FACTOR = 1.5
"""El semilado del cuadrado que encuadra «Ir a» a una parte de la franja: ``PLACE_AREA_FACTOR``
veces la raíz de su área, y como poco ``PLACE_MIN_RADIUS_M`` m."""
DATE_FORMAT = "%d/%m/%Y"
"""Cómo se teclea la fecha de la decisión (DD/MM/AAAA, como en la 008)."""


def view() -> Any | None:
    """``WindowManager.geoblender_constraints`` (``None`` sin la extensión registrada)."""
    manager = getattr(bpy.context, "window_manager", None)
    return getattr(manager, WINDOW_MANAGER_PROPERTY, None)


def _write_unavailable() -> str | None:
    """Por qué no se puede escribir en el proyecto ahora (sin proyecto, solo lectura o la versión
    activa no editable), o ``None``."""
    from ..ops import core_provenance  # al usarlo: bl/ops importa bl/ui (ARQ-08)

    return core_provenance.write_unavailable() or scene_versions.not_editable_text()


def _label(idname: str) -> str:
    """La etiqueta del catálogo de comandos de la orden ``idname``, en el idioma de
    Geoblender."""
    return text(catalog().commands[idname].label)


# --- Lo que se lee del proyecto ------------------------------------------------------------------


def polygon_layers(project: Any) -> tuple[str, ...]:
    """Los datos del proyecto que pueden dar límites, por nombre: las capas «entidades» de
    polígonos (``gis_fea_``; no las de puntos ni las de líneas) y las de «dominios» (``gis_dom_``,
    siempre polígonos). Una cuya tabla falta no se ofrece."""
    records = gis_store.list_gis_datasets(project, families=(gis_provenance.FEATURES,
                                                             gis_provenance.DOMAINS))
    domains = gis_provenance.FAMILIES_BY_CODE[gis_provenance.DOMAINS].prefix
    found: list[str] = []
    for record in records:
        if record.name.startswith(domains):
            found.append(record.name)
            continue
        try:
            source = gis_store.feature_source(project, record)
        except (GeoblenderError, ValueError):
            LOGGER.warning("La capa «%s» no se ofrece a Límites…", record.name, exc_info=True)
            continue
        if source.kind == "polygon":
            found.append(source.name)
    return tuple(sorted(found))


@dataclass(frozen=True, slots=True)
class Line:
    """Una línea del informe de los límites (ya traducida): su texto, si va en alerta y, si lleva
    «Ir a», el lugar (``x`` e ``y`` absolutas y el radio, en metros, en texto)."""

    text: str
    alert: bool = False
    place: tuple[str, str, str] | None = None


def _m2_ha(area_m2: float) -> tuple[str, str]:
    """Un área como se lee en m² y en ha (D-12): («40 000», «4,00»)."""
    return format_number(area_m2, 0), format_number(area_m2 / 10_000.0, 2)


def place_of(x: float, y: float, area_m2: float) -> tuple[str, str, str]:
    """El lugar al que lleva «Ir a» desde una parte de la franja de centro absoluto ``(x, y)`` y
    ``area_m2``: las coordenadas y el radio como texto que se lee sin pérdida (``repr`` de un
    float64: ADR-0005)."""
    radius = max(PLACE_MIN_RADIUS_M, PLACE_AREA_FACTOR * float(area_m2) ** 0.5)
    return repr(float(x)), repr(float(y)), repr(float(radius))


def limit_lines(found: Any, where: str) -> list[Line]:
    """El informe de los límites declarados ``found`` (``gis.masks.store.DeclaredLimits``) en la
    versión ``where`` (su código, o «el proyecto»), en el idioma de Geoblender: primero lo que
    impide compilarlos (en alerta; sin informe, porque las áreas de una geometría no válida no
    valen), después el límite legal con su resguardo, el perímetro (o que el límite legal hace de
    perímetro), la intersección, la franja con cada parte y «Ir a», lo que queda fuera de la
    rejilla (en alerta) y los límites que ahí no están activos (RF-012-05, RF-012-15, D-12,
    D-14)."""
    shown = language()
    lines = [Line(problem.text(shown), alert=True) for problem in found.problems]
    report = found.report
    if report is None:
        if not found.problems:
            lines.append(Line(tr("No active legal limit: choose its layers below")))
    else:
        area, hectares = _m2_ha(report.legal_m2)
        lines.append(Line(tr("Legal limit {hectares} ha ({area} m²)", hectares=hectares,
                             area=area)))
        if found.inward_m is not None:
            lines.append(Line(tr("Inward setback of the legal limit: {value} m",
                                 value=format_value(found.inward_m, shown))))
        if report.perimeter_from_legal:
            lines.append(Line(tr("No action perimeter: the legal limit is taken as the "
                                 "perimeter")))
        else:
            area, hectares = _m2_ha(report.perimeter_m2)
            lines.append(Line(tr("Action perimeter {hectares} ha ({area} m²)",
                                 hectares=hectares, area=area)))
            area, hectares = _m2_ha(report.intersection_m2)
            lines.append(Line(tr("Intersection {hectares} ha ({area} m²)", hectares=hectares,
                                 area=area)))
            parts = report.strip_parts
            area, hectares = _m2_ha(report.strip_m2)
            if not parts:
                lines.append(Line(tr("No fill-only strip: the action perimeter is inside the "
                                     "legal limit")))
            elif len(parts) == 1:
                lines.append(Line(tr("Fill-only strip {hectares} ha ({area} m²) in {count} part",
                                     hectares=hectares, area=area, count=1)))
            else:
                lines.append(Line(tr("Fill-only strip {hectares} ha ({area} m²) in {count} parts",
                                     hectares=hectares, area=area, count=len(parts))))
            for part in parts:
                lines.append(Line(
                    tr("{area} m² at ({x}; {y})", area=format_number(part.area_m2, 0),
                       x=format_number(part.centroid[0], 1),
                       y=format_number(part.centroid[1], 1)),
                    place=place_of(part.centroid[0], part.centroid[1], part.area_m2)))
        for outside in report.outside:
            lines.append(Line(tr("{name}: {area} m² outside the project grid", name=outside.name,
                                 area=format_number(outside.area_m2, 0)), alert=True))
    for item in found.inactive:
        assert item.ctype is not None
        lines.append(Line(tr("«{name}» ({ctype}) is not active in {where}",
                             name=item.shown_name(shown), ctype=item.ctype.label(shown),
                             where=where)))
    return lines


def _put_lines(target: Any, lines: Sequence[Line]) -> None:
    target.clear()
    for line in lines:
        item = target.add()
        item.text, item.alert = line.text, line.alert
        if line.place is not None:
            item.x, item.y, item.radius = line.place


def fill_limits(project: Any) -> Any:
    """Regenera la vista de Límites… desde ``project``: las capas de polígonos (conserva las
    casillas de las que siguen), la fecha de hoy si no hay otra y el informe de los límites de la
    versión activa (``gis.masks.store.declared_limits``, que no escribe nada); devuelve esos
    límites. Si no se puede leer, el error sigue y la vista queda como estaba."""
    limits = view()
    if limits is None:  # inalcanzable con la extensión registrada
        raise RuntimeError("la vista de los límites no está registrada")
    shown = scene_versions.active()
    found = mask_store.declared_limits(project, version=None if shown is None else shown.uid)
    layers = polygon_layers(project)
    chosen = {item.name: (item.legal, item.perimeter) for item in limits.limit_layers}
    limits.limit_layers.clear()
    for name in layers:
        item = limits.limit_layers.add()
        item.name = name
        item.legal, item.perimeter = chosen.get(name, (False, False))
    if not limits.limit_decided_on.strip():
        limits.limit_decided_on = dt.date.today().strftime(DATE_FORMAT)
    _put_lines(limits.limit_lines, limit_lines(found, tr("the project") if shown is None
                                               else shown.code))
    return found


# --- Dibujo --------------------------------------------------------------------------------------


def _draw_line(layout: Any, line: Any, width: float) -> None:
    """Una línea del informe: su texto (en alerta, si lo está) y, si lleva un lugar, «Ir a»."""
    if line.x:
        row = layout.row(align=True)
        row.label(text=line.text, translate=False)
        button = row.operator(GO_TO_PLACE, text=_label(GO_TO_PLACE), translate=False)
        button.x, button.y, button.radius = line.x, line.y, line.radius
        return
    shown = labels.wrapped(line.text, width, icon=line.alert)
    column = layout.column(align=True)
    column.alert = bool(line.alert)
    for index, part in enumerate(shown):
        icon = ("ERROR" if index == 0 else "BLANK1") if line.alert else "NONE"
        column.label(text=part, icon=icon, translate=False)


def draw_limits(layout: Any, context: Any) -> None:
    """La ventana de Límites… (véase el módulo), de lo ya leído."""
    limits = view()
    if limits is None:
        return
    blocked = _write_unavailable()
    if blocked is not None:  # se ve y no se cambia (RF-012-28)
        note = layout.row()
        note.alert = True
        note.label(text=blocked, icon="LOCKED", translate=False)
    width = labels.dialog_width(LIMITS_WIDTH_PX)
    box = layout.box()
    box.label(text=tr("Limits in force"), translate=False)
    for line in limits.limit_lines:
        _draw_line(box, line, width)
    form = layout.column()
    form.enabled = blocked is None
    form.label(text=tr("Polygon layers of the project"), translate=False)
    if not len(limits.limit_layers):
        labels.draw_wrapped(form, tr(
            "The project has no polygon layers: import them first with {path}, as Features",
            path=path_text(catalog(), IMPORT_VECTOR, language())), width, icon="INFO")
    else:
        head = form.row()
        head.label(text=tr("Layer"), translate=False)
        head.label(text=tr("Legal limit"), translate=False)
        head.label(text=tr("Action perimeter"), translate=False)
        for item in limits.limit_layers:
            row = form.row()
            row.label(text=item.name, translate=False)
            row.prop(item, "legal", text="")
            row.prop(item, "perimeter", text="")
    form.prop(limits, "limit_name_field", text=tr("Name field (optional)"), translate=False)
    form.prop(limits, "limit_reason", text=tr("Reason"), translate=False)
    form.prop(limits, "limit_decided_by", text=tr("Decided by"), translate=False)
    form.prop(limits, "limit_decided_on", text=tr("Date (DD/MM/YYYY)"), translate=False)
    form.prop(limits, "limit_inward", text=tr("Inward setback of the legal limit (m)"),
              translate=False)
    form.operator(DECLARE_LIMITS, text=_label(DECLARE_LIMITS), icon="CHECKMARK",
                  translate=False)


class GEOBLENDER_PT_core_limits(bpy.types.Panel):
    """Legal limit and action perimeter of the project: their report and the form to declare
    them"""

    bl_idname = LIMITS_PANEL
    bl_label = "Limits"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = LIMITS_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_limits(self.layout, context)


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_PT_core_limits,)
