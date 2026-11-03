# SPDX-License-Identifier: GPL-3.0-or-later
"""Las ventanas del diseño de explotación (spec 013; plan 013 §5.3.3, §5.5, D-17, D-24; ADR-0027).

**Perfiles de banco…** (T22; HU-013-4; RF-013-18, RF-013-19, RF-013-20, RF-013-33): la ventana
``GEOBLENDER_PT_des_profiles`` (la abre ``geoblender.des_edit_bench_profiles``, ``bl.ops.des``)
dibuja los perfiles de ``WindowManager.geoblender_design`` (``bl.props.des``), ya leídos del
proyecto:

- la lista (``GEOBLENDER_UL_des_profiles``): el nombre con la insignia de tipo de sus valores
  (la del menos firme: [HIP] antes que [ADO]) y cómo se lee, «h 10 m · cara 60° · berma 6 m ·
  ancla 125 m», en ámbar si la rejilla no lo resuelve o le falta algo;
- del elegido: su ámbito (de dónde salen los valores que se ven: «el proyecto», «V01» o «V01 y el
  proyecto»), sus **derivados** («avance 11,77 m · talud general 40,3°»), «no resuelto por la
  rejilla» en ámbar (RF-013-20; ADR-0014), lo que le falta o no vale en la versión activa y cada
  uno de sus cinco valores con su tipo y su ámbito («V03: 8 m [ADO] · proyecto: —», RF-009-29) y
  «Cambiar…» (``geoblender.core_set_parameter`` de su clave: la 008 pide el tipo, el origen, el
  decisor y el motivo y la 009 pregunta «¿Para el proyecto o solo para V01?»);
- «Perfil nuevo…» y «Completar o renombrar…» (``geoblender.des_save_bench_profile``).

Los derivados y la marca de la rejilla **no se calculan aquí**: son los de
``design.model.BenchProfile`` (``avance_m``, ``general_deg``, ``unresolved_by``). **Nada se lee al
dibujar**: :func:`fill_profiles` regenera la vista desde el proyecto (al abrir la ventana y tras
guardar) y :func:`on_project_read` la vuelve a leer cuando la procedencia avisa de que el
proyecto cambió (``bl.ui.provenance.add_change_listener``: un valor cambiado con ``Cambiar…``).
En solo lectura o con la versión activa no editable dice por qué y dibuja desactivado lo que
escribe (RF-013-33). Los textos pasan por ``core.i18n`` y se dibujan con ``translate=False``.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from typing import Any

import bpy

from ...core.errors import GeoblenderError
from ...core.i18n import format_number, language, tr, translate
from ...core.params import ParameterStore, ParamKind, format_value
from ...core.params import definition as param_definition
from ...design import messages as design_messages
from ...design import profiles as design_profiles
from ...design.model import BenchProfile
from ...design.params import BenchParam, bench_key
from ..props.des import WINDOW_MANAGER_PROPERTY
from ..scene import versions as scene_versions
from . import labels, provenance
from .res_panels import NOT_SHOWN, record_text

LOGGER = logging.getLogger("geoblender.bl.ui")
TRANSLATION_CONTEXT = "Geoblender"
PROFILES_PANEL = "GEOBLENDER_PT_des_profiles"
PROFILES_LIST = "GEOBLENDER_UL_des_profiles"
SAVE_PROFILE = "geoblender.des_save_bench_profile"
SET_PARAMETER = "geoblender.core_set_parameter"
PROFILES_PANEL_UNITS = 40
PROFILES_WIDTH_PX = PROFILES_PANEL_UNITS * 20
PROFILE_ROWS = 5
DERIVED_DECIMALS = 2
"""Los decimales con que se lee el avance (m) y el talud general (°) de un perfil: «11,77 m» y
«40,34°» (RF-013-20 los escribe a dos decimales y a uno, «40,3°»)."""
NAME_FACTOR = 0.4
FIRMNESS = (ParamKind.HIPOTESIS, ParamKind.ADOPTADO, ParamKind.CALCULADO, ParamKind.MEDIDO)
"""Los tipos de menos a más firme: la insignia de un perfil es la de su valor menos firme."""
REQUIRED = (BenchParam.HEIGHT, BenchParam.FACE, BenchParam.BERM, BenchParam.ANCHOR)
"""Los cuatro valores que se declaran siempre (el factor de malla tiene uno por defecto)."""
LABELS = {
    BenchParam.HEIGHT: "Bench height",
    BenchParam.FACE: "Face angle of the bench",
    BenchParam.BERM: "Minimum berm width",
    BenchParam.ANCHOR: "Anchor elevation",
    BenchParam.MESH_FACTOR: "Mesh factor of the profile",
}
"""El ``msgid`` del nombre de cada valor (el de ``design.params.FAMILIES``)."""


def view() -> Any | None:
    """``WindowManager.geoblender_design`` (``None`` sin la extensión registrada)."""
    manager = getattr(bpy.context, "window_manager", None)
    return getattr(manager, WINDOW_MANAGER_PROPERTY, None)


def _write_unavailable() -> str | None:
    """Por qué no se puede escribir ahora (sin proyecto, solo lectura o la versión activa no
    editable), o ``None``."""
    from ..ops import des as des_ops  # al usarlo: bl/ops importa bl/ui (ARQ-08)

    return des_ops.design_unavailable()


# --- Lo que se enseña de un perfil ---------------------------------------------------------------


def number_text(value: float | None, param: BenchParam) -> str:
    """Un valor de un perfil como se lee: «10 m», «60°»; sin valor, «—»."""
    if value is None:
        return NOT_SHOWN
    shown = format_value(float(value), language())
    return f"{shown}°" if param is BenchParam.FACE else f"{shown} m"


def design_error_text(exc: design_messages.DesignError) -> str:
    """El texto de un error del diseño en el idioma de Geoblender (``DesignError.text`` es el
    español)."""
    return design_messages.render(exc.code, language=language(), **exc.values)


def parameter_text(project_record: Any, own: Any, key: str, version: Any) -> str:
    """Un valor de un perfil con su tipo y su ámbito: el del proyecto y, si hay una versión activa
    (``version``), el propio de ella («V01: 10 m [ADO] · proyecto: —», RF-009-29). Sin ningún
    valor registrado, el de por defecto de su definición («1 [ADO] sin confirmar») o «—»."""
    if project_record is None and own is None:
        found = param_definition(key)
        return NOT_SHOWN if found is None or found.default is None else record_text(None, key)
    project_text = NOT_SHOWN if project_record is None else record_text(project_record)
    if version is None:
        return project_text
    own_text = NOT_SHOWN if own is None else record_text(own)
    return tr("{version}: {value} · project: {project}", version=version.code, value=own_text,
              project=project_text)


def _grid(project: Any) -> Any | None:
    """La rejilla del proyecto (su ventana y su paso), con la que se mira lo que la rejilla no
    resuelve; ``None`` si no se puede leer."""
    from ...gis.grid import project_grid  # al usarlo: habilitar no lo carga

    record = getattr(project, "record", None)
    if record is None:
        return None
    try:
        return project_grid(record.window, float(record.grid_step_m))
    except (GeoblenderError, ValueError):
        LOGGER.warning("No se pudo leer la rejilla del proyecto", exc_info=True)
        return None


def _scope_text(origins: set[str], version: Any) -> str:
    """De dónde salen los valores que se ven: «el proyecto», «V01» o «V01 y el proyecto»."""
    if not origins:
        return NOT_SHOWN
    if origins == {"project"}:
        return tr("the project")
    if origins == {"version"}:
        return str(version.code)
    return tr("{version} and the project", version=version.code)


def put_profile(target: Any, row: Any, store: ParameterStore, conn: sqlite3.Connection,
                version: Any, grid: Any | None) -> None:
    """Un perfil del proyecto (``design.profiles.StoredProfile``) en la fila ``target`` de la
    vista: sus cinco valores con su tipo y su ámbito, de dónde salen, su insignia, cómo se lee y
    sus derivados, que son los del dominio (``BenchProfile``)."""
    shown = language()
    target.name, target.code = row.name, row.code
    target.parameters.clear()
    values: dict[BenchParam, Any] = {}
    kinds: list[ParamKind] = []
    origins: set[str] = set()
    for param in BenchParam:
        key = bench_key(row.code, param)
        project_record = store.get(key, conn=conn)
        own = None if version is None else store.get(key, version=version.uid, conn=conn)
        line = target.parameters.add()
        line.key, line.registered = key, project_record is not None or own is not None
        line.name = translate(shown, LABELS[param])
        line.text = parameter_text(project_record, own, key, version)
        chosen = next((record for record in (own, project_record)
                       if record is not None and record.value is not None), None)
        if chosen is not None:
            values[param] = chosen.value
            if param in REQUIRED:
                kinds.append(chosen.kind)
                origins.add("version" if chosen is own else "project")
        elif param is BenchParam.MESH_FACTOR:
            found = param_definition(key)
            values[param] = None if found is None else found.default
    target.summary = tr(
        "h {height} · face {face} · berm {berm} · anchor {anchor}",
        height=number_text(values.get(BenchParam.HEIGHT), BenchParam.HEIGHT),
        face=number_text(values.get(BenchParam.FACE), BenchParam.FACE),
        berm=number_text(values.get(BenchParam.BERM), BenchParam.BERM),
        anchor=number_text(values.get(BenchParam.ANCHOR), BenchParam.ANCHOR))
    target.badge = provenance.badge(min(kinds, key=FIRMNESS.index)) if kinds else ""
    target.scope = _scope_text(origins, version)
    target.derived = target.unresolved = target.problem = ""
    try:
        profile = BenchProfile(row.code, row.name,
                               **{param.value: values.get(param) for param in BenchParam})
    except design_messages.DesignError as exc:  # le falta algo o no vale en la versión activa
        target.problem = design_error_text(exc)
        return
    target.derived = tr("advance {advance} m · general slope {slope}°",
                        advance=format_number(profile.avance_m, DERIVED_DECIMALS),
                        slope=format_number(profile.general_deg, DERIVED_DECIMALS))
    if grid is not None:
        target.unresolved = profile.unresolved_by(grid, language=shown) or ""


def fill_profiles(project: Any) -> int:
    """Regenera la lista de Perfiles de banco… desde ``project`` (RF-013-18, RF-013-20): los
    perfiles del proyecto (``design.profiles.read_profiles``), cada uno con sus valores en la
    versión activa y en el proyecto y sus derivados; conserva el elegido (por su código).
    Devuelve cuántos hay. Si no se puede leer, el error sigue y la vista queda como estaba."""
    shown = view()
    if shown is None:  # inalcanzable con la extensión registrada
        raise RuntimeError("la vista de los perfiles de banco no está registrada")
    version = scene_versions.active()
    store = ParameterStore(project)
    grid = _grid(project)
    old = shown.profiles
    chosen = old[shown.profile_index].code if 0 <= shown.profile_index < len(old) else ""
    with project.read() as conn:
        stored = design_profiles.read_profiles(conn)
        shown.profiles.clear()
        for row in stored:
            put_profile(shown.profiles.add(), row, store, conn, version, grid)
    shown.profile_index = next((index for index, item in enumerate(shown.profiles)
                                if item.code == chosen), 0)
    shown.profiles_project = project.uid
    return len(shown.profiles)


def choose(code: str) -> None:
    """Deja elegido en la lista el perfil de código ``code`` (si está)."""
    shown = view()
    if shown is None:
        return
    for index, item in enumerate(shown.profiles):
        if item.code == code:
            shown.profile_index = index
            return


def show_report(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja ``lines`` (texto, si va en alerta) como el último resultado de la ventana."""
    shown = view()
    if shown is None:
        return
    shown.profile_report.clear()
    for text, alert in lines:
        line = shown.profile_report.add()
        line.name, line.alert = text, alert


def on_project_read(project: Any) -> None:
    """Lo que hace la escucha de los indicadores de la procedencia cada vez que el proyecto
    cambió (``bl.ui.provenance.add_change_listener``): los valores de la vista, al día si es de
    ``project``. Si no se puede leer, lo deja en el registro técnico."""
    shown = view()
    if shown is None or not shown.profiles_project or shown.profiles_project != project.uid:
        return
    try:
        fill_profiles(project)
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudieron leer los perfiles de banco", exc_info=True)


# --- Dibujo --------------------------------------------------------------------------------------


def _draw_text(layout: Any, shown_text: str, width: float, *, alert: bool = False) -> None:
    """``shown_text`` partido al ancho de la zona (``width``), en alerta si ``alert``: una etiqueta
    de Blender no parte el texto, lo corta con «…»."""
    column = layout.column(align=True)
    column.alert = alert
    for index, part in enumerate(labels.wrapped(shown_text, width, icon=alert)):
        icon = ("ERROR" if index == 0 else "BLANK1") if alert else "NONE"
        column.label(text=part, icon=icon, translate=False)


def _draw_blocked(layout: Any, blocked: str | None, width: float) -> None:
    """Por qué la ventana se ve y no se cambia (RF-013-33), en alerta y con el candado."""
    if blocked is None:
        return
    note = layout.column(align=True)
    note.alert = True
    for index, part in enumerate(labels.wrapped(blocked, width, icon=True)):
        note.label(text=part, icon="LOCKED" if index == 0 else "BLANK1", translate=False)


class GEOBLENDER_UL_des_profiles(bpy.types.UIList):
    """Bench profiles of the project with their values and their type"""

    bl_idname = PROFILES_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        split = layout.split(factor=NAME_FACTOR, align=True)
        title = f"{item.name} {item.badge}" if item.badge else item.name
        split.label(text=title, translate=False)
        cell = split.row(align=True)
        bad = bool(item.unresolved or item.problem)
        cell.alert = bad
        cell.label(text=item.summary, icon="ERROR" if bad else "NONE", translate=False)


def _draw_chosen(layout: Any, item: Any, width: float, writable: bool) -> None:
    """El perfil elegido: su nombre, su ámbito y su insignia, sus derivados, lo que la rejilla no
    resuelve o lo que le falta (en alerta), cada uno de sus cinco valores (con «Cambiar…» si está
    registrado) y «Completar o renombrar…» (RF-013-18, RF-013-20). Los textos largos, partidos al
    ancho de la zona y el botón de un valor, debajo de él."""
    box = layout.box()
    title = f"{item.name} {item.badge}" if item.badge else item.name
    box.label(text=title, translate=False)
    _draw_text(box, tr("Scope: {scope}", scope=item.scope), width)
    _draw_text(box, item.summary, width)
    if item.derived:
        _draw_text(box, item.derived, width)
    if item.unresolved:
        _draw_text(box, item.unresolved, width, alert=True)
    if item.problem:
        _draw_text(box, item.problem, width, alert=True)
    box.label(text=tr("Parameters"), translate=False)
    for line in item.parameters:
        block = box.column(align=True)
        block.enabled = writable
        _draw_text(block, f"{line.name}:", width)
        _draw_text(block, line.text, width)
        if line.registered:
            button = block.operator(SET_PARAMETER, text=tr("Change…"), translate=False)
            button.key = line.key
    edit = box.row()
    edit.enabled = writable
    button = edit.operator(SAVE_PROFILE, text=tr("Complete or rename…"), icon="GREASEPENCIL",
                           translate=False)
    button.code = item.code


def draw_profiles(layout: Any, context: Any) -> None:
    """La ventana de Perfiles de banco… (véase el módulo), de lo ya leído."""
    shown = view()
    if shown is None:
        return
    blocked = _write_unavailable()
    writable = blocked is None
    width = labels.dialog_width(PROFILES_WIDTH_PX)
    _draw_blocked(layout, blocked, width)
    create = layout.row()
    create.enabled = writable
    button = create.operator(SAVE_PROFILE, text=tr("New profile…"), icon="ADD", translate=False)
    button.code = ""
    if not len(shown.profiles):
        labels.draw_wrapped(layout, tr(
            "There are no bench profiles yet: create one with its height, face angle, berm and "
            "anchor elevation"), width, icon="INFO")
    else:
        layout.label(text=tr("Bench profiles: {count}", count=len(shown.profiles)),
                     translate=False)
        layout.template_list(PROFILES_LIST, "", shown, "profiles", shown, "profile_index",
                             rows=PROFILE_ROWS)
        index = min(max(shown.profile_index, 0), len(shown.profiles) - 1)
        _draw_chosen(layout, shown.profiles[index], width, writable)
    if len(shown.profile_report):
        box = layout.box()
        box.label(text=tr("Last result"), translate=False)
        for line in shown.profile_report:
            _draw_text(box, line.name, width, alert=bool(line.alert))


class GEOBLENDER_PT_des_profiles(bpy.types.Panel):
    """Bench profiles of the project: their values, their type and their scope, and the orders to
    create, complete, rename and change them"""

    bl_idname = PROFILES_PANEL
    bl_label = "Bench profiles"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = PROFILES_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_profiles(self.layout, context)


# En orden de registro (las listas, antes de la ventana que las dibuja).
classes: tuple[type, ...] = (GEOBLENDER_UL_des_profiles, GEOBLENDER_PT_des_profiles)


def install() -> None:
    """Pone la escucha de los indicadores (:func:`on_project_read`); idempotente."""
    provenance.add_change_listener(on_project_read)


def uninstall() -> None:
    """Quita lo que puso :func:`install`; idempotente."""
    provenance.remove_change_listener(on_project_read)
