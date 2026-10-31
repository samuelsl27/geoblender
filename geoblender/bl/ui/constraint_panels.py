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

**Restricciones…** (T23; HU-012-2, HU-012-4; RF-012-02, RF-012-04, RF-012-19, RF-012-28): la
ventana ``GEOBLENDER_PT_core_constraints`` (la abre ``geoblender.core_edit_constraints``) dibuja la
lista de las restricciones del proyecto (``GEOBLENDER_UL_core_constraints``: la insignia del tipo,
el nombre y el estado en la versión activa: incompleta, no válida, activa o inactiva en ella, con
el filtro de las que tienen problemas) y, de la elegida, su motivo, decisor, fecha, decisión
enlazada, lo que le falta y sus parámetros con su valor en la versión y en el proyecto («V01: 8 m
[ADO] · proyecto: —», :func:`parameter_text`), cada uno con «Cambiar…» (el diálogo de la 008 con el
ámbito de la 009, ``geoblender.core_set_parameter``) y «Completar…» o «Editar…»
(``geoblender.core_complete_constraint``). Arriba, «Desde una capa…»
(``geoblender.core_create_constraints``), «Compilar las máscaras» (``geoblender.gis_compile_constraints``)
y «Exportar las máscaras…» (``geoblender.gis_export_constraint_masks``); abajo, el último
resultado de cada una (lo creado y lo rechazado, el informe de compilar con lo ganado y lo
perdido y la búsqueda pendiente: :func:`compile_lines`). :func:`fill_constraints` regenera la
vista desde el proyecto, sin escribir (``gis.masks.store.listed_constraints``).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import bpy

from ...core.catalog.search import path_text
from ...core.constraints import checks as constraint_checks
from ...core.constraints.model import ConstraintType, is_code
from ...core.constraints.params import family, param_key
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, language, translate, tr
from ...core.params.model import format_value
from ...core.params.store import ParameterStore
from ...gis import provenance as gis_provenance
from ...gis import store as gis_store
from ...gis.masks import store as mask_store
from .. import compat
from ..props.core_constraints import WINDOW_MANAGER_PROPERTY
from ..scene import versions as scene_versions
from . import labels, res_panels
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
CONSTRAINTS_PANEL = "GEOBLENDER_PT_core_constraints"
CONSTRAINTS_LIST = "GEOBLENDER_UL_core_constraints"
CREATE_CONSTRAINTS = "geoblender.core_create_constraints"
COMPLETE_CONSTRAINT = "geoblender.core_complete_constraint"
COMPILE_CONSTRAINTS = "geoblender.gis_compile_constraints"
EXPORT_MASKS = "geoblender.gis_export_constraint_masks"
SET_PARAMETER = "geoblender.core_set_parameter"
CONSTRAINTS_PANEL_UNITS = 40
CONSTRAINTS_WIDTH_PX = CONSTRAINTS_PANEL_UNITS * compat.UI_UNIT_PX
"""El ancho de la ventana Restricciones (40 unidades)."""
CONSTRAINT_ROWS = 6
BADGE_FACTOR = 0.28
NAME_FACTOR = 0.6
"""Cómo reparte la fila de la lista su ancho: la insignia del tipo, el nombre y el estado."""
MAX_CONFLICT_LINES = 5
"""Cuántos conflictos (zonas sin movimiento posible) enseña el informe de compilar."""


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


# --- Restricciones… (T23; RF-012-02, RF-012-04, RF-012-19, RF-012-28) ----------------------------


def source_layers(project: Any) -> tuple[str, ...]:
    """Los datos del proyecto de los que se pueden crear restricciones, por nombre: las capas
    «entidades» (``gis_fea_``: puntos, líneas o polígonos) y las de «dominios» (``gis_dom_``,
    polígonos; D-27)."""
    records = gis_store.list_gis_datasets(project, families=(gis_provenance.FEATURES,
                                                             gis_provenance.DOMAINS))
    return tuple(sorted(record.name for record in records))


def type_label(ctype: str) -> str:
    """El nombre en el idioma de Geoblender del tipo de restricción ``ctype`` (el valor de
    ``ConstraintType``); vacío, «sin tipo»."""
    if not ctype:
        return translate(language(), constraint_checks.NO_TYPE_MSGID)
    return ConstraintType(ctype).label(language())


def state_text(state: str, where: str) -> str:
    """El estado de una restricción como se lee (RF-012-19): «Incompleta», «No válida»,
    «Activa» o «Inactiva en V01» (``where``, la versión activa o «el proyecto»)."""
    if state == "incomplete":
        return tr("Incomplete")
    if state == "invalid":
        return tr("Not valid")
    if state == "inactive":
        return tr("Inactive in {version}", version=where)
    return tr("Active")


def _where() -> str:
    shown = scene_versions.active()
    return tr("the project") if shown is None else shown.code


def parameter_text(store: ParameterStore, conn: Any, key: str, version: Any
                   ) -> tuple[str, bool]:
    """El parámetro ``key`` de una restricción como se lee en la versión activa ``version`` (la
    que se enseña; ``None``: el proyecto): su valor propio de la versión y el del proyecto, cada
    uno con su unidad y su insignia de tipo («V01: 8 m [ADO] · proyecto: —», RF-009-29) y si está
    registrado en alguno de los dos."""
    project_record = store.get(key, conn=conn)
    own = None if version is None else store.get(key, version=version.uid, conn=conn)
    project_text = (res_panels.NOT_SHOWN if project_record is None
                    else res_panels.record_text(project_record))
    registered = project_record is not None or own is not None
    if version is None:
        return project_text, registered
    own_text = res_panels.NOT_SHOWN if own is None else res_panels.record_text(own)
    return tr("{version}: {value} · project: {project}", version=version.code, value=own_text,
              project=project_text), registered


def _put_constraint(target: Any, entry: Any, store: ParameterStore, conn: Any,
                    version: Any) -> None:
    """Una restricción de la lista (``gis.masks.store.ListedConstraint``) en la fila ``target``
    de la vista, con lo que le falta y, de cada parámetro que pide su tipo, su valor en la
    versión y en el proyecto."""
    shown = language()
    row = entry.constraint
    target.name = row.shown_name(shown)
    target.uid, target.code = row.uid, row.code
    target.ctype = "" if row.ctype is None else row.ctype.value
    target.kind, target.layer, target.fid = row.kind.value, row.layer, int(row.fid)
    target.state = entry.state
    target.problems = "\n".join(problem.text(shown) for problem in entry.problems)
    target.priority = int(row.priority)
    target.reason, target.decided_by = row.reason or "", row.decided_by or ""
    target.decided_on = "" if row.decided_on is None else row.decided_on.strftime(DATE_FORMAT)
    target.decision = row.decision_uid or ""
    target.parameters.clear()
    if not is_code(row.code):
        return
    wanted = () if row.ctype is None else row.ctype.requires
    for param in wanted:
        key = param_key(row.code, param)
        line = target.parameters.add()
        line.key = key
        line.name = translate(shown, family(param).template.label_msgid)
        line.text, line.registered = parameter_text(store, conn, key, version)


def fill_constraints(project: Any) -> int:
    """Regenera la lista de Restricciones… desde ``project`` (RF-012-19): todas las restricciones
    con su estado en la versión activa (``gis.masks.store.listed_constraints``, que no escribe
    nada) y sus parámetros; conserva la elegida (por su ``uid``) y las capas de origen que se
    pueden ofrecer. Devuelve cuántas hay. Si no se puede leer, el error sigue y la vista queda
    como estaba."""
    shown = view()
    if shown is None:  # inalcanzable con la extensión registrada
        raise RuntimeError("la vista de las restricciones no está registrada")
    version = scene_versions.active()
    listed = mask_store.listed_constraints(project, version=None if version is None
                                           else version.uid)
    layers = source_layers(project)
    old = shown.constraints
    chosen = old[shown.item_index].uid if 0 <= shown.item_index < len(old) else ""
    store = ParameterStore(project)
    shown.constraints.clear()
    with project.read() as conn:
        for entry in listed:
            _put_constraint(shown.constraints.add(), entry, store, conn, version)
    shown.item_index = next((index for index, item in enumerate(shown.constraints)
                             if item.uid == chosen), 0)
    shown.source_layers.clear()
    for name in layers:
        shown.source_layers.add().name = name
    return len(shown.constraints)


def show_report(lines: Sequence[Line]) -> None:
    """Deja ``lines`` como el último resultado de Restricciones… (lo creado y lo rechazado, lo
    compilado, lo exportado)."""
    shown = view()
    if shown is not None:
        _put_lines(shown.report_lines, lines)


def compile_lines(stored: Any, revision: str, pending: Sequence[str]) -> list[Line]:
    """El informe de una compilación (``gis.masks.store.StoredMasks``) en la revisión
    ``revision`` (RF-012-05, RF-012-06, RF-012-10, RF-012-11, RF-012-14, RF-012-15): el dominio,
    el corte, el relleno y la franja en ha; los avisos (el límite legal que hace de perímetro,
    una zona fuera de la rejilla…); el área en la que no cabe ningún movimiento; de cada
    restricción que cambió desde la compilación anterior, el polígono y la zona ganados y
    perdidos en m² (A5); y, en alerta, los sectores sin búsqueda de intocables vigente
    (``pending``: sus nombres)."""
    result = stored.result
    grid, masks = result.grid, result.masks

    def hectares(runs: Any) -> str:
        return format_number(runs.area(grid) / 10_000.0, 2)

    lines = [Line(tr("Masks of {revision} up to date: domain {domain} ha, cut {cut} ha, fill "
                     "{fill} ha, strip {strip} ha", revision=revision,
                     domain=hectares(masks.default_domain), cut=hectares(masks.cut_allowed),
                     fill=hectares(masks.fill_allowed), strip=hectares(masks.fill_strip)))]
    shown = language()
    for notice in result.notices:
        lines.append(Line(notice.text(shown),
                          alert=notice.code == "core.constraint_zone_outside_grid"))
    if masks.no_movement_m2 > 0.0:
        lines.append(Line(tr("No movement is possible in {area} m²",
                             area=format_number(masks.no_movement_m2, 0)), alert=True))
        for conflict in masks.conflicts[:MAX_CONFLICT_LINES]:
            lines.append(Line(tr("{causes}: {area} m²", causes=", ".join(conflict.causes),
                                 area=format_number(conflict.area_m2, 0))))
    for change in result.changes:
        lines.append(Line(tr(
            "{name}: polygon +{gained} m² −{lost} m², zone +{zone_gained} m² −{zone_lost} m²",
            name=change.name or change.code,
            gained=format_number(change.polygon_gained_m2, 0),
            lost=format_number(change.polygon_lost_m2, 0),
            zone_gained=format_number(change.zone_gained_m2, 0),
            zone_lost=format_number(change.zone_lost_m2, 0))))
    if pending:
        lines.append(Line(tr("Search for untouchable elements pending in: {names}",
                             names="; ".join(pending)), alert=True))
    return lines


class GEOBLENDER_UL_core_constraints(bpy.types.UIList):
    """Constraints of the project with their type and their state in the active version"""

    bl_idname = CONSTRAINTS_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        split = layout.split(factor=BADGE_FACTOR, align=True)
        split.label(text=type_label(item.ctype), translate=False)
        names = split.split(factor=NAME_FACTOR, align=True)
        names.label(text=item.name, translate=False)
        bad = item.state in ("incomplete", "invalid")
        cell = names.row(align=True)
        cell.alert = bad
        cell.label(text=state_text(item.state, _where()), icon="ERROR" if bad else "NONE",
                   translate=False)

    def filter_items(self, context: Any, data: Any, propname: str
                     ) -> tuple[list[int], list[int]]:
        """Con «solo las incompletas o no válidas», solo esas."""
        items = getattr(data, propname)
        flags = [self.bitflag_filter_item] * len(items)
        if getattr(data, "only_problems", False):
            for index, item in enumerate(items):
                if item.state not in ("incomplete", "invalid"):
                    flags[index] = 0
        return flags, []


def _draw_chosen(layout: Any, item: Any, width: float, writable: bool) -> None:
    """La restricción elegida de la lista: tipo y nombre, estado y lo que le falta, motivo,
    decisor, fecha, decisión enlazada, sus parámetros (cada uno con «Cambiar…», la 008, de
    ámbito la 009) y «Completar…» o «Editar…» (RF-012-19, RF-012-03)."""
    box = layout.box()
    title = f"{type_label(item.ctype)} · {item.name}"
    box.label(text=title, translate=False)
    bad = item.state in ("incomplete", "invalid")
    state = box.row()
    state.alert = bad
    state.label(text=state_text(item.state, _where()), icon="ERROR" if bad else "NONE",
                translate=False)
    for problem in item.problems.splitlines():
        _draw_line(box, Line(problem, alert=True), width)
    details = box.column(align=True)
    for msgid_text in (
            tr("Reason: {value}", value=item.reason or res_panels.NOT_SHOWN),
            tr("Decided by: {value}", value=item.decided_by or res_panels.NOT_SHOWN),
            tr("Date of the decision: {value}", value=item.decided_on or res_panels.NOT_SHOWN),
            tr("Priority: {value}", value=item.priority)):
        details.label(text=msgid_text, translate=False)
    if item.decision:
        details.label(text=tr("Linked decision: {value}", value=item.decision), translate=False)
    if len(item.parameters):
        box.label(text=tr("Parameters"), translate=False)
    for line in item.parameters:
        row = box.row(align=True)
        row.enabled = writable
        shown = f"{line.name}: {line.text}"
        row.label(text=shown, translate=False)
        if line.registered:
            button = row.operator(SET_PARAMETER, text=tr("Change…"), translate=False)
            button.key = line.key
    edit = box.row()
    edit.enabled = writable
    button = edit.operator(
        COMPLETE_CONSTRAINT, text=_label(COMPLETE_CONSTRAINT) if item.state == "incomplete"
        else tr("Edit…"), icon="GREASEPENCIL", translate=False)
    button.uid = item.uid


def draw_constraints(layout: Any, context: Any) -> None:
    """La ventana de Restricciones… (véase el módulo), de lo ya leído."""
    shown = view()
    if shown is None:
        return
    blocked = _write_unavailable()
    writable = blocked is None
    if blocked is not None:  # se ve y no se cambia (RF-012-28)
        note = layout.row()
        note.alert = True
        note.label(text=blocked, icon="LOCKED", translate=False)
    width = labels.dialog_width(CONSTRAINTS_WIDTH_PX)
    buttons = layout.row(align=True)
    writes = buttons.row(align=True)
    writes.enabled = writable
    writes.operator(CREATE_CONSTRAINTS, text=_label(CREATE_CONSTRAINTS), icon="ADD",
                    translate=False)
    writes.operator(COMPILE_CONSTRAINTS, text=_label(COMPILE_CONSTRAINTS), icon="PLAY",
                    translate=False)
    buttons.operator(EXPORT_MASKS, text=_label(EXPORT_MASKS), icon="EXPORT", translate=False)
    if not len(shown.constraints):
        labels.draw_wrapped(layout, tr("There are no constraints yet: create them from a layer "
                                       "of the project"), width, icon="INFO")
    else:
        layout.label(text=tr("Constraints in {where}: {count}", where=_where(),
                             count=len(shown.constraints)), translate=False)
        layout.prop(shown, "only_problems", text=tr("Only incomplete or not valid"),
                    translate=False)
        layout.template_list(CONSTRAINTS_LIST, "", shown, "constraints", shown, "item_index",
                             rows=CONSTRAINT_ROWS)
        index = min(max(shown.item_index, 0), len(shown.constraints) - 1)
        _draw_chosen(layout, shown.constraints[index], width, writable)
    if len(shown.report_lines):
        box = layout.box()
        box.label(text=tr("Last result"), translate=False)
        for line in shown.report_lines:
            _draw_line(box, line, width)


class GEOBLENDER_PT_core_constraints(bpy.types.Panel):
    """Constraints of the project: their type, state and parameters in the active version, and
    the order to create, complete, compile and export them"""

    bl_idname = CONSTRAINTS_PANEL
    bl_label = "Constraints"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = CONSTRAINTS_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_constraints(self.layout, context)


# En orden de registro (la lista, antes de la ventana que la dibuja).
classes: tuple[type, ...] = (GEOBLENDER_PT_core_limits, GEOBLENDER_UL_core_constraints,
                             GEOBLENDER_PT_core_constraints)
