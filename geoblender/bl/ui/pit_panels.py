# SPDX-License-Identifier: GPL-3.0-or-later
"""Las ventanas de la corta por bancos (spec 018, T32; HU-018-1, HU-018-3; RF-018-07, RF-018-15, RF-018-34, RF-015-28; plan 018 §5.3.3, §5.5 y H-5).

**Roseta de taludes…** y **Rampa…**: las ventanas ``GEOBLENDER_PT_des_pit_roses`` y ``GEOBLENDER_PT_des_pit_ramps`` (las abren ``geoblender.des_edit_pit_rose`` y
``geoblender.des_edit_pit_ramp``, de ``bl.ops.des_pit``) son la copia, para la corta, de la de los perfiles de pista de la 017 (``des_panels``): una lista con lo ya leído del
proyecto (``WindowManager.geoblender_design.pit_roses`` y ``.pit_ramps``: nada se lee ni se calcula al dibujar), el elegido con **cada valor con su tipo, su ámbito y su fuente**
(con «Cambiar…» si está registrado), **los derivados, que no se editan** (de una roseta, el avance ``n·h/tan α + B`` y el talud general ``atan(n·h/avance)`` de cada rango para la
altura de cada perfil de banco; de una rampa, la longitud de eje que pide cada banco ``h / g`` y la sección del perfil de pista: los del dominio, ``design.pit_rose`` y
``design.pit_ramp_def``), lo que le falta o no vale, y «Roseta nueva…» o «Rampa nueva…» y «Completar o renombrar…», que son ``geoblender.des_save_pit_rose`` y
``geoblender.des_save_pit_ramp``. Con la escritura no disponible (sin proyecto, solo lectura o la versión activa no editable) lo que escribe sale desactivado y el motivo, en ámbar.
``design.pit_rose``, ``design.pit_ramp_def`` y ``design.road_profiles`` son perezosos: se importan al leer los datos (habilitar no los carga: RNF-001-03).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from typing import Any

import bpy

from ...core.errors import GeoblenderError
from ...core.i18n import language, tr, translate
from ...core.params import ParameterStore, format_value
from ...core.params import definition as param_definition
from ...design import messages as design_messages
from ...design import profiles as design_profiles
from ...design.params import BenchParam, PitRampParam, RoadProfileParam, RoseParam, bench_key, pitramp_key, road_profile_key, rose_key
from ..scene import versions as scene_versions
from . import des_panels, labels, provenance
from .res_panels import NOT_SHOWN
from .view_panels import ROW_FIELD, ROW_HEADING, ROW_NONE, CardLine

LOGGER = logging.getLogger("geoblender.bl.ui")
TRANSLATION_CONTEXT = "Geoblender"
ROSES_PANEL = "GEOBLENDER_PT_des_pit_roses"
ROSES_LIST = "GEOBLENDER_UL_des_pit_roses"
SAVE_ROSE = "geoblender.des_save_pit_rose"
RAMPS_PANEL = "GEOBLENDER_PT_des_pit_ramps"
RAMPS_LIST = "GEOBLENDER_UL_des_pit_ramps"
SAVE_RAMP = "geoblender.des_save_pit_ramp"
DECIMALS = 2
"""Los decimales de lo derivado (el avance, el talud general y las longitudes)."""
_RAMP_ORDER = (PitRampParam.TYPE, PitRampParam.SENSE, PitRampParam.START, PitRampParam.GRADIENT, PitRampParam.ROAD_PROFILE, PitRampParam.TRANSITION,
               PitRampParam.TURN_RADIUS, PitRampParam.MIN_PLATFORM)


def _number(value: float) -> str:
    """Un número como se lee (coma o punto según el idioma), con a lo sumo :data:`DECIMALS` decimales."""
    return format_value(round(float(value), DECIMALS), language())


def _record(store: ParameterStore, conn: sqlite3.Connection, key: str, version: Any) -> tuple[Any, Any, Any]:
    """Del valor ``key``: el del proyecto, el propio de la versión activa y el que vale (el propio y, si no, el del proyecto); ``None`` el que falta."""
    project_record = store.get(key, conn=conn)
    own = None if version is None else store.get(key, version=version.uid, conn=conn)
    chosen = next((item for item in (own, project_record) if item is not None and item.value is not None), None)
    return project_record, own, chosen


def _put_parameter(target: Any, key: str, name: str, found: tuple[Any, Any, Any], version: Any) -> None:
    """Una línea de valor de la fila ``target``: su nombre, cómo se lee en la versión y en el proyecto, si está registrado y su fuente."""
    project_record, own, chosen = found
    line = target.parameters.add()
    line.key, line.registered, line.name = key, project_record is not None or own is not None, name
    line.text = des_panels.parameter_text(project_record, own, key, version)
    if chosen is not None:
        line.source = tr("Source: {source} · decided by {who}", source=chosen.source or NOT_SHOWN, who=chosen.decided_by)


def _label(key: str, fallback: str) -> str:
    found = param_definition(key)
    return translate(language(), found.label_msgid) if found is not None and found.label_msgid else fallback


def _bench_heights(store: ParameterStore, conn: sqlite3.Connection, version: Any) -> list[tuple[str, float]]:
    """La altura de cada perfil de banco del proyecto que la tiene (la de la versión activa y, si no, la del proyecto): nombre y metros."""
    found: list[tuple[str, float]] = []
    for row in design_profiles.read_profiles(conn):
        chosen = _record(store, conn, bench_key(row.code, BenchParam.HEIGHT), version)[2]
        if chosen is not None and isinstance(chosen.value, (int, float)):
            found.append((row.name, float(chosen.value)))
    return found


def _scope_and_badge(target: Any, chosen: list[tuple[Any, Any]], version: Any) -> None:
    """La insignia (la del tipo menos firme) y el ámbito de los valores que se ven."""
    kinds = [record.kind for record, _own in chosen]
    origins = {"version" if record is own else "project" for record, own in chosen}
    target.badge = provenance.badge(min(kinds, key=des_panels.FIRMNESS.index)) if kinds else ""
    target.scope = des_panels._scope_text(origins, version)


def _add_line(target: Any, text: str, alert: bool = False) -> None:
    line = target.lines.add()
    line.name, line.alert = text, alert


# --- Roseta de taludes… ---------------------------------------------------------------------------------------------------------------------


def put_rose(target: Any, row: Any, store: ParameterStore, conn: sqlite3.Connection, version: Any) -> None:
    """Una roseta del proyecto (``design.pit_rose.StoredEntry``) en la fila ``target`` de la vista: los valores de cada rango con su tipo, su ámbito y su fuente; cómo se lee, su
    insignia y su ámbito; lo que no vale (un hueco, un solape, un valor fuera de rango: lo dice el dominio, RF-018-07) y **sus derivados**, el avance y el talud general de cada
    rango para la altura de cada perfil de banco (``design.pit_rose.derived``; no son parámetros)."""
    from ...design import pit_rose  # al usarlo: habilitar no lo carga (RNF-001-03)

    target.name, target.code = row.name, row.code
    target.parameters.clear()
    target.lines.clear()
    target.problem = ""
    stored = [str(key) for (key,) in conn.execute("SELECT DISTINCT key FROM gb_parameter WHERE key LIKE ?", (f"des.rose.{row.code}.%",))]
    numbers = _numbers_of(stored, row.code)
    ranges: list[tuple[Any, ...]] = []
    chosen: list[tuple[Any, Any]] = []
    for number in numbers:
        values: list[Any] = []
        for param in RoseParam:
            key = rose_key(row.code, f"r{number}", param)
            found = _record(store, conn, key, version)
            _put_parameter(target, key, f"r{number} · {_label(key, param.value)}", found, version)
            values.append(None if found[2] is None else found[2].value)
            if found[2] is not None:
                chosen.append((found[2], found[1]))
        ranges.append(tuple(values))
    _scope_and_badge(target, chosen, version)
    shown = [f"{_number(low)}°–{_number(high)}°: α {_number(face)}°, B {_number(berm)} m" for low, high, face, berm in ranges if None not in (low, high, face, berm)]
    target.summary = " · ".join(shown)
    try:
        checked = pit_rose.check_rose(row.name, row.code, ranges)
    except design_messages.DesignError as exc:  # un hueco, un solape, le falta algo o no vale en la versión activa
        target.problem = des_panels.design_error_text(exc)
        return
    heights = _bench_heights(store, conn, version)
    if not heights:
        _add_line(target, tr("There is no bench profile with a height: the advance and the overall slope need one"))
    for name, height in heights:
        for item in pit_rose.derived(checked, height):
            _add_line(target, tr("{bench} (h {height}): {low}°–{high}°: advance {advance} · overall slope {slope}°", bench=name, height=f"{_number(height)} m",
                                 low=_number(item.range.from_deg), high=_number(item.range.to_deg), advance=f"{_number(item.advance_m)} m",
                                 slope=_number(item.overall_slope_deg)))


def _numbers_of(keys: Sequence[str], code: str) -> list[int]:
    """Los números de los rangos de la roseta ``code`` que tienen alguna clave en ``keys`` (``des.rose.{code}.r{i}.…``), de menor a mayor."""
    prefix = f"des.rose.{code}."
    found = set()
    for key in keys:
        part = key[len(prefix):].split(".")[0] if key.startswith(prefix) else ""
        if part.startswith("r") and part[1:].isdigit():
            found.add(int(part[1:]))
    return sorted(found)


def fill_pit_roses(project: Any) -> int:
    """Regenera la lista de Roseta de taludes… desde ``project`` (RF-018-07): las rosetas del proyecto (``design.pit_rose.read_roses``), cada una con sus valores y sus derivados;
    conserva la elegida (por su código). Devuelve cuántas hay. Si no se puede leer, el error sigue y la vista queda como estaba."""
    from ...design import pit_rose  # al usarlo: habilitar no lo carga (RNF-001-03)

    shown = des_panels.view()
    if shown is None:  # inalcanzable con la extensión registrada
        raise RuntimeError("la vista de las rosetas de taludes no está registrada")
    version = scene_versions.active()
    store = ParameterStore(project)
    old = shown.pit_roses
    chosen = old[shown.pit_rose_index].code if 0 <= shown.pit_rose_index < len(old) else ""
    with project.read() as conn:
        stored = pit_rose.read_roses(conn)
        shown.pit_roses.clear()
        for row in stored:
            put_rose(shown.pit_roses.add(), row, store, conn, version)
    shown.pit_rose_index = next((index for index, item in enumerate(shown.pit_roses) if item.code == chosen), 0)
    shown.pit_roses_project = project.uid
    return len(shown.pit_roses)


def choose_pit_rose(code: str) -> None:
    """Deja elegida en la lista la roseta de código ``code`` (si está)."""
    shown = des_panels.view()
    if shown is not None:
        shown.pit_rose_index = next((index for index, item in enumerate(shown.pit_roses) if item.code == code), shown.pit_rose_index)


def show_pit_rose_report(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja ``lines`` (texto, si va en alerta) como el último resultado de la ventana de las rosetas."""
    shown = des_panels.view()
    if shown is not None:
        _report(shown.pit_rose_report, lines)


def _report(target: Any, lines: Sequence[tuple[str, bool]]) -> None:
    target.clear()
    for text, alert in lines:
        line = target.add()
        line.name, line.alert = text, alert


# --- Rampa… ---------------------------------------------------------------------------------------------------------------------------------



def _type_text(value: object) -> str:
    """El tipo de la rampa como se lee («espiral», «zig-zag»); un valor que no es de la lista, «—»."""
    return {"spiral": tr("spiral"), "zigzag": tr("zigzag")}.get(str(value), NOT_SHOWN)


def _sense_text(value: object) -> str:
    """El sentido de la rampa como se lee («horario», «antihorario»); un valor que no es de la lista, «—»."""
    return {"cw": tr("clockwise"), "ccw": tr("counter-clockwise")}.get(str(value), NOT_SHOWN)


def put_ramp(target: Any, row: Any, store: ParameterStore, conn: sqlite3.Connection, version: Any) -> None:
    """Una definición de rampa del proyecto (``design.pit_ramp_def.StoredEntry``) en la fila ``target`` de la vista: sus ocho valores con su tipo, su ámbito y su fuente; cómo se
    lee, su insignia y su ámbito; lo que le falta o no vale (``design.pit_ramp_def.check_ramp``, con la pendiente máxima del perfil de pista: RF-018-15) y **sus derivados**, la
    longitud de eje que pide cada banco ``h / g`` para la altura de cada perfil de banco y la sección del perfil de pista (``design.pit_ramp_def.derived``; no son parámetros)."""
    from ...design import pit_ramp_def, road_profiles  # al usarlo: habilitar no lo carga (RNF-001-03)

    target.name, target.code = row.name, row.code
    target.parameters.clear()
    target.lines.clear()
    target.problem = ""
    values: dict[str, Any] = {}
    chosen: list[tuple[Any, Any]] = []
    for param in _RAMP_ORDER:
        key = pitramp_key(row.code, param)
        found = _record(store, conn, key, version)
        _put_parameter(target, key, _label(key, param.value), found, version)
        if found[2] is not None:
            values[param.value] = found[2].value
            chosen.append((found[2], found[1]))
    _scope_and_badge(target, chosen, version)
    road_names = road_profiles.profile_names(conn)
    road_code = str(values.get("road_profile", ""))
    road_name = road_names.get(road_code, road_code or NOT_SHOWN)
    gradient = values.get("gradient_pct")
    target.summary = tr("{type} · {sense} · start {start} · g {gradient} · {road}",
                        type=_type_text(values.get("type")), sense=_sense_text(values.get("sense")),
                        start=values.get("start", NOT_SHOWN), gradient=NOT_SHOWN if gradient is None else f"{_number(gradient)} %", road=road_name)
    if road_code not in road_names:
        target.problem = tr("The road profile «{road}» of the ramp is not in the project", road=road_code or NOT_SHOWN) if values else ""
        return
    road_values = {param.value: _record(store, conn, road_profile_key(road_code, param), version)[2] for param in RoadProfileParam}
    try:
        profile = road_profiles.RoadProfile.from_values(road_code, road_name, {name: None if rec is None else rec.value for name, rec in road_values.items()})
        road = road_profiles.derived(profile)
        ramp = pit_ramp_def.check_ramp(row.name, row.code, values, max_gradient_pct=profile.max_gradient_pct, road_profile_name=road_name)
    except design_messages.DesignError as exc:  # le falta algo, no vale o pasa de la pendiente máxima del perfil de pista
        target.problem = des_panels.design_error_text(exc)
        return
    heights = _bench_heights(store, conn, version)
    if not heights:
        _add_line(target, tr("There is no bench profile with a height: the length needed per bench needs one"))
    for name, height in heights:
        found_derived = pit_ramp_def.derived(ramp, height, road)
        _add_line(target, tr("{bench} (h {height}): length needed per bench {length}", bench=name, height=f"{_number(height)} m",
                             length=f"{_number(found_derived.length_per_bench_m)} m"))
    _add_line(target, tr("Section of the road profile: {section}", section=f"{_number(road.section_m)} m"))


def fill_pit_ramps(project: Any) -> int:
    """Regenera la lista de Rampa… desde ``project`` (RF-018-15): las definiciones de rampa del proyecto (``design.pit_ramp_def.read_ramps``), cada una con sus valores y sus
    derivados; conserva la elegida (por su código). Devuelve cuántas hay."""
    from ...design import pit_ramp_def  # al usarlo: habilitar no lo carga (RNF-001-03)

    shown = des_panels.view()
    if shown is None:
        raise RuntimeError("la vista de las rampas no está registrada")
    version = scene_versions.active()
    store = ParameterStore(project)
    old = shown.pit_ramps
    chosen = old[shown.pit_ramp_index].code if 0 <= shown.pit_ramp_index < len(old) else ""
    with project.read() as conn:
        stored = pit_ramp_def.read_ramps(conn)
        shown.pit_ramps.clear()
        for row in stored:
            put_ramp(shown.pit_ramps.add(), row, store, conn, version)
    shown.pit_ramp_index = next((index for index, item in enumerate(shown.pit_ramps) if item.code == chosen), 0)
    shown.pit_ramps_project = project.uid
    return len(shown.pit_ramps)


def choose_pit_ramp(code: str) -> None:
    """Deja elegida en la lista la rampa de código ``code`` (si está)."""
    shown = des_panels.view()
    if shown is not None:
        shown.pit_ramp_index = next((index for index, item in enumerate(shown.pit_ramps) if item.code == code), shown.pit_ramp_index)


def show_pit_ramp_report(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja ``lines`` como el último resultado de la ventana de las rampas."""
    shown = des_panels.view()
    if shown is not None:
        _report(shown.pit_ramp_report, lines)


def on_project_read(project: Any) -> None:
    """Lo que hace la escucha de los indicadores de la procedencia cada vez que el proyecto cambió: las listas de las rosetas y de las rampas, al día si son de ``project`` (un
    valor cambiado con «Cambiar…»). Si no se puede leer, lo deja en el registro técnico."""
    shown = des_panels.view()
    if shown is None:
        return
    for project_uid, fill, what in ((shown.pit_roses_project, fill_pit_roses, "las rosetas de taludes"), (shown.pit_ramps_project, fill_pit_ramps, "las rampas")):
        if project_uid and project_uid == project.uid:
            try:
                fill(project)
            except (GeoblenderError, sqlite3.Error, OSError, ValueError):
                LOGGER.warning("No se pudieron leer %s", what, exc_info=True)


# --- Dibujo ---------------------------------------------------------------------------------------------------------------------------------


def _draw_item(layout: Any, item: Any) -> None:
    """Una fila de la lista de rosetas o de rampas: su nombre con su insignia y cómo se lee (en ámbar si no vale)."""
    split = layout.split(factor=des_panels.NAME_FACTOR, align=True)
    title = f"{item.name} {item.badge}" if item.badge else item.name
    split.label(text=title, translate=False)
    cell = split.row(align=True)
    cell.alert = bool(item.problem)
    cell.label(text=item.summary, icon="ERROR" if item.problem else "NONE", translate=False)


class GEOBLENDER_UL_des_pit_roses(bpy.types.UIList):
    """Slope roses of the project with their ranges and their type"""

    bl_idname = ROSES_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int, active_data: Any, active_propname: str, index: int = 0, flt_flag: int = 0) -> None:
        _draw_item(layout, item)


class GEOBLENDER_UL_des_pit_ramps(bpy.types.UIList):
    """Ramp definitions of the project with their values and their type"""

    bl_idname = RAMPS_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int, active_data: Any, active_propname: str, index: int = 0, flt_flag: int = 0) -> None:
        _draw_item(layout, item)


def _draw_chosen(layout: Any, item: Any, width: float, writable: bool, save: str) -> None:
    """La elegida: su nombre, su ámbito y su insignia, cómo se lee, lo que le falta o no vale (en alerta), **sus derivados** (texto, sin botón, porque no son parámetros), cada uno
    de sus valores con su tipo, su ámbito y su fuente (con «Cambiar…» si está registrado) y «Completar o renombrar…»."""
    box = layout.box()
    title = f"{item.name} {item.badge}" if item.badge else item.name
    box.label(text=title, translate=False)
    des_panels._draw_text(box, tr("Scope: {scope}", scope=item.scope), width)
    des_panels._draw_text(box, item.summary, width)
    if item.problem:
        des_panels._draw_text(box, item.problem, width, alert=True)
    shown = des_panels.view()
    more = shown is not None and shown.pit_details
    if shown is not None:  # lo largo (los derivados y los valores con su fuente) va plegado: la ventana cabe (UI-01, UI-02; T40k)
        fold = box.row()
        fold.prop(shown, "pit_details", text=tr("Details"), icon="TRIA_DOWN" if more else "TRIA_RIGHT", emboss=False, translate=False)
    if not more:
        edit = box.row()
        edit.enabled = writable
        button = edit.operator(save, text=tr("Complete or rename…"), icon="GREASEPENCIL", translate=False)
        button.code = item.code
        return
    if not item.problem and len(item.lines):
        box.label(text=tr("Derived values (not parameters)"), translate=False)
        for line in item.lines:
            des_panels._draw_text(box, line.name, width, alert=bool(line.alert))
    box.label(text=tr("Parameters"), translate=False)
    for line in item.parameters:
        block = box.column(align=True)
        block.enabled = writable
        des_panels._draw_text(block, f"{line.name}:", width)
        des_panels._draw_text(block, line.text, width)
        if line.source:
            des_panels._draw_text(block, line.source, width)
        if line.registered:
            button = block.operator(des_panels.SET_PARAMETER, text=tr("Change…"), translate=False)
            button.key = line.key
    edit = box.row()
    edit.enabled = writable
    button = edit.operator(save, text=tr("Complete or rename…"), icon="GREASEPENCIL", translate=False)
    button.code = item.code


def _draw(layout: Any, *, items: Any, index: int, report: Any, listing: str, collection: str, index_name: str, save: str, new_text: str, empty_text: str, count_text: str) -> None:
    shown = des_panels.view()
    if shown is None:
        return
    blocked = des_panels._write_unavailable()
    writable = blocked is None
    width = labels.dialog_width(des_panels.PROFILES_WIDTH_PX)
    des_panels._draw_blocked(layout, blocked, width)
    labels.draw_wrapped(layout, tr("To close this window press Esc or click outside it"), width, icon="INFO")  # no tiene botón de cerrar: es una ventana emergente de Blender (T40k)
    create = layout.row()
    create.enabled = writable
    button = create.operator(save, text=new_text, icon="ADD", translate=False)
    button.code = ""
    if not len(items):
        labels.draw_wrapped(layout, empty_text, width, icon="INFO")
    else:
        layout.label(text=count_text, translate=False)
        layout.template_list(listing, "", shown, collection, shown, index_name, rows=des_panels.PROFILE_ROWS)
        _draw_chosen(layout, items[min(max(index, 0), len(items) - 1)], width, writable, save)
    if len(report):
        box = layout.box()
        box.label(text=tr("Last result"), translate=False)
        for line in report:
            des_panels._draw_text(box, line.name, width, alert=bool(line.alert))


def draw_roses(layout: Any, context: Any) -> None:
    """La ventana de Roseta de taludes… (véase el módulo), de lo ya leído."""
    shown = des_panels.view()
    if shown is None:
        return
    _draw(layout, items=shown.pit_roses, index=shown.pit_rose_index, report=shown.pit_rose_report, listing=ROSES_LIST, collection="pit_roses", index_name="pit_rose_index",
          save=SAVE_ROSE, new_text=tr("New rose…"),
          empty_text=tr("There are no slope roses yet: create one with its azimuth ranges, each with its face angle and its berm"),
          count_text=tr("Slope roses: {count}", count=len(shown.pit_roses)))


def draw_ramps(layout: Any, context: Any) -> None:
    """La ventana de Rampa… (véase el módulo), de lo ya leído."""
    shown = des_panels.view()
    if shown is None:
        return
    _draw(layout, items=shown.pit_ramps, index=shown.pit_ramp_index, report=shown.pit_ramp_report, listing=RAMPS_LIST, collection="pit_ramps", index_name="pit_ramp_index",
          save=SAVE_RAMP, new_text=tr("New ramp…"),
          empty_text=tr("There are no ramp definitions yet: create one with its type, sense, start, gradient, road profile and transition"),
          count_text=tr("Ramp definitions: {count}", count=len(shown.pit_ramps)))


class GEOBLENDER_PT_des_pit_roses(bpy.types.Panel):
    """Slope roses of the pit: their ranges with their source and type and their derived advance and overall slope, and the orders to create, complete and rename them"""

    bl_idname = ROSES_PANEL
    bl_label = "Slope roses"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = des_panels.PROFILES_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_roses(self.layout, context)


class GEOBLENDER_PT_des_pit_ramps(bpy.types.Panel):
    """Ramp definitions of the pit: their values with their source and type and the length they need per bench, and the orders to create, complete and rename them"""

    bl_idname = RAMPS_PANEL
    bl_label = "Ramp definitions"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = des_panels.PROFILES_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_ramps(self.layout, context)


# --- La barra N «Entidad» y «Elemento activo» de una corta (spec 018, T34; RF-018-26, RF-015-25; M5) ------------------------------------------------


_MODE_TEXT = {"up": "Ascending", "down": "Descending"}
_STOP_TEXT = {"surface": "it comes out to the surface", "top_level": "it reaches the top elevation", "floor_width": "the floor reaches the minimum width",
              "bottom_level": "it reaches the bottom elevation", "max_benches": "it reaches the maximum number of benches"}
"""El texto (``msgid``) de cada modo de la corta y de cada criterio que la paró (``design.pit_model.PitMode`` y ``StopCriterion``)."""


def _num(value: float | None, decimals: int = 0) -> str:
    return des_panels._number(value, decimals)


def _place_line(text: str, place: tuple[float, float], area_m2: float, *, alert: bool) -> CardLine:
    """Una fila con su «Ir a» (``ROW_PLACE``: ``x;y;radio`` de ``place_of``, el de las listas de la accesibilidad)."""
    return CardLine(des_panels.ROW_PLACE, text, alert=alert, uid=";".join(des_panels.constraint_panels.place_of(place[0], place[1], area_m2)))


def _finding_line(found: Any) -> CardLine:
    """Un hallazgo (``design.pit_model.Finding``) en la barra N: su texto (el de la leyenda de la vista previa, con su banco), siempre en alerta, con su «Ir a»; el área sin excavar da el radio."""
    from ..draw import pit as pit_draw  # el texto de un hallazgo es uno: el de su leyenda en la vista

    unit = str(getattr(found.kind, "value", found.kind))
    area = float(found.value) if unit == "unexcavated" and found.value is not None else 0.0
    return _place_line(pit_draw._finding_text(found), found.place, area, alert=True)


def pit_card_lines(project: Any, conn: sqlite3.Connection, version: Any, entry: Any, stored: Any) -> list[CardLine]:
    """Lo que dice la barra N de una **corta** (spec 018, T34; RF-018-26, RF-018-29, RF-018-31, RF-015-25; M5), **leído de lo guardado** de su operación vigente (``design.pit_card``; nada se calcula):
    su **modo y sus bancos**, por qué paró, las cotas de fondo y de coronación, la longitud de pies y de crestas, las áreas de bermas, de fondo y con movimiento, el volumen de corte y **el de cada banco**
    (los primeros ``LIST_LIMIT``), la **línea de cielo** con sus distancias al límite legal y al perímetro, las **rampas** (longitud, pendiente media y máxima, con su «Ir a» al inicio), los avisos del
    cálculo y **la lista de hallazgos, cada uno en alerta y con su «Ir a»**. El estado de la corta con su causa es el de cualquier entidad (:func:`des_panels._entity_state_line`)."""
    from ...design import pit_card

    shown = language()
    mode = stored.get("mode") if hasattr(stored, "get") else None
    mode_text = NOT_SHOWN if mode is None or mode.value is None else translate(shown, _MODE_TEXT.get(str(mode.value), str(mode.value)))
    lines = [CardLine(ROW_HEADING, tr("Pit"))]
    facts = pit_card.read_pit_facts(conn, str(entry.operation_uid))
    if facts is None:
        return [*lines, CardLine(ROW_NONE, tr("The project has no report of this pit"))]
    got = facts.figures.get
    lines.append(CardLine(ROW_FIELD, tr("Mode «{mode}» · benches: {benches}", mode=mode_text, benches=_num(got("benches")))))
    if facts.stop in _STOP_TEXT:
        lines.append(CardLine(ROW_FIELD, tr("Stopped by: {criterion}", criterion=translate(shown, _STOP_TEXT[str(facts.stop)]))))
    lines += [CardLine(ROW_FIELD, tr("Bottom elevation {bottom} m · top elevation {top} m", bottom=_num(got("z_bottom_m"), 2), top=_num(got("z_top_m"), 2))),
              CardLine(ROW_FIELD, tr("Length of the toes {foot} m · of the crests {crest} m", foot=_num(got("len_foot_m"), 1), crest=_num(got("len_crest_m"), 1))),
              CardLine(ROW_FIELD, tr("Area: berms {berm} m² · floor {floor} m² · moved {moved} m²", berm=_num(got("area_berm_m2")), floor=_num(got("area_floor_m2")),
                                     moved=_num(got("area_m2")))),
              CardLine(ROW_FIELD, tr("Cut volume: {cut} m³", cut=_num(got("cut_m3"))))]
    limit = des_panels.LIST_LIMIT
    if facts.benches:
        lines.append(CardLine(ROW_HEADING, tr("Volume by bench")))
        lines += [CardLine(ROW_FIELD, tr("Bench {bench}: elevation from {foot} to {crest} m · cut {cut} m³", bench=row.bench, foot=_num(row.z_foot_m, 2), crest=_num(row.z_crest_m, 2),
                                         cut=_num(row.cut_m3))) for row in facts.benches[:limit]]
        if len(facts.benches) > limit:
            lines.append(CardLine(ROW_NONE, tr("… and {more} more benches (all of them are in the table of the pit)", more=len(facts.benches) - limit)))
    if got("sky_parts"):
        lines.append(CardLine(ROW_FIELD, tr("Skyline: parts {parts} · length {length} m · encloses {area} m² · elevation from {low} to {high} m", parts=_num(got("sky_parts")),
                                            length=_num(got("sky_len_m")), area=_num(got("sky_area_m2")), low=_num(got("sky_z_min_m"), 2), high=_num(got("sky_z_max_m"), 2))))
        if got("sky_dist_legal_m") is not None:
            lines.append(CardLine(ROW_FIELD, tr("Distance from the skyline to the legal limit: {distance} m", distance=_num(got("sky_dist_legal_m"), 1))))
        if got("sky_dist_perimeter_m") is not None:
            lines.append(CardLine(ROW_FIELD, tr("Distance from the skyline to the perimeter of the works: {distance} m", distance=_num(got("sky_dist_perimeter_m"), 1))))
    else:
        lines.append(CardLine(ROW_FIELD, tr("The pit has no skyline")))
    lines.append(CardLine(ROW_HEADING, f"{tr('Ramps')} ({len(facts.ramps)})"))
    lines += [_place_line(tr("Ramp «{code}» · bench {bench}: length {length} m · mean gradient {mean} % · maximum {max} %", code=ramp.code, bench=ramp.bench, length=_num(ramp.length_m, 1),
                             mean=_num(ramp.gradient_mean_pct, 2), max=_num(ramp.gradient_max_pct, 2)), (ramp.x, ramp.y), 0.0, alert=False) for ramp in facts.ramps] or [
        CardLine(ROW_NONE, tr("Nothing to list"))]
    lines += [CardLine(ROW_FIELD, notice.text(shown), alert=notice.severity == "warning") for notice in facts.notices]
    lines.append(CardLine(ROW_HEADING, f"{tr('Findings')} ({len(facts.findings)})"))
    if not facts.findings:
        return [*lines, CardLine(ROW_NONE, tr("No findings: everything that was measured is within its limits"))]
    lines += [_finding_line(found) for found in facts.findings[:limit]]
    if len(facts.findings) > limit:
        lines.append(CardLine(ROW_NONE, tr("… and {more} more findings (the whole list is in the findings of the pit)", more=len(facts.findings) - limit)))
    return lines


# En orden de registro (las listas, antes de la ventana que las dibuja).
classes: tuple[type, ...] = (GEOBLENDER_UL_des_pit_roses, GEOBLENDER_PT_des_pit_roses, GEOBLENDER_UL_des_pit_ramps, GEOBLENDER_PT_des_pit_ramps)


def install() -> None:
    """Pone la escucha de los indicadores (:func:`on_project_read`); idempotente."""
    provenance.add_change_listener(on_project_read)


def uninstall() -> None:
    """Quita lo que puso :func:`install`; idempotente."""
    provenance.remove_change_listener(on_project_read)
