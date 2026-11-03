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

**Sectores de diseño…** (T23; HU-013-2; RF-013-07, RF-013-08, RF-013-10, RF-013-21): la ventana
``GEOBLENDER_PT_des_sectors`` (la abre ``geoblender.des_edit_design_sectors``) dibuja los sectores
de ``WindowManager.geoblender_design``, leídos con :func:`fill_sectors` de ``design.sectors``
(los de la 012, o el perímetro de actuación como único sector):

- la lista (``GEOBLENDER_UL_des_sectors``): el nombre, el área, el talud impuesto y el estado de su
  búsqueda de intocables, «Búsqueda pendiente» en ámbar;
- del elegido: su código (la clave de su talud, ADR-0029), su área, el estado de su búsqueda (con
  quién la cerró y cuándo, o pendiente en ámbar con la orden de la 012 para hacerla), el talud que
  impone («10,6° [ADO]») con su origen, su decisor y su ámbito («la propiedad · decidido por … ·
  V01»), el perfil asignado a la superficie en preparación (:func:`assign_profiles`, que llama la
  ventana de las envolventes) y «Fijar el talud del sector…» (``geoblender.des_set_sector_slope``);
- los taludes de los sectores que ya no existen (renombrados o quitados), en una lista aparte y
  sin borrarlos nunca (RF-013-10);
- «Declarar de nuevo desde una capa…»: la capa y el campo de la 012 y su orden
  ``geoblender.core_declare_sectors``, que conserva los valores de los sectores que mantienen su
  código; la ventana se pone al día sola (:func:`on_project_read`).

Ni el área, ni el estado, ni el talud, ni los huérfanos se calculan aquí: son los del dominio
(``design.sectors``).

**Envolventes y escalonado…** (T24; HU-013-1, HU-013-3, HU-013-5, HU-013-6; RF-013-17, RF-013-21,
RF-013-31): lo que ofrece su diálogo y lo que enseña su resumen, ya leído del proyecto.
:func:`refresh_choices` lee las superficies y rejillas de cotas (las del proyecto y las de la
versión activa), las zonas (el dominio por defecto, las restricciones, los sectores y las capas
de polígonos) y las capas con que se puede acotar el dominio, en listas vivas del módulo que
alimentan los ``EnumProperty`` dinámicos (:func:`surface_items`, :func:`anchor_items`,
:func:`zone_items`, :func:`layer_items`; ``docs/trampas.md`` §3). :func:`draw_sector_rows` dibuja
los sectores con su marca de acotado y su perfil. :func:`show_summary` deja el resumen del cálculo
abierto (``summary_title`` y ``summary``) con :func:`summary_lines`: el desmonte, el terraplén, la
inclinación, las bermas y los avisos (en ámbar), de las cifras y del informe del dominio (aquí solo se
escriben).

**Vista previa de semillas, dominios y restricciones** (T25; HU-013-1; RF-013-03):
:func:`show_preview` deja en ``WindowManager.geoblender_design.preview`` el resumen que dice
``design.preview`` (líneas ya traducidas, los avisos en alerta) cuando ``bl.draw.design`` acaba de
construir la vista previa de la Vista 3D, y lo vacía al quitarla; la barra N «Diseño» (T27) lo leerá de
ahí.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy

from ...core.catalog.search import path_text
from ...core.constraints import store as constraint_store
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, language, tr, translate
from ...core.params import ParameterStore, ParamKind, format_value
from ...core.params import definition as param_definition
from ...design import messages as design_messages
from ...design import profiles as design_profiles
from ...design import provenance as design_provenance
from ...design.model import PERIMETER_SEGMENT, BenchProfile
from ...design.params import BenchParam, bench_key
from ...reserves import surfaces as res_surfaces
from ..props.des import WINDOW_MANAGER_PROPERTY
from ..scene import project_session
from ..scene import versions as scene_versions
from . import constraint_panels, labels, provenance
from .commands import catalog
from .commands import text as command_text
from .res_panels import NOT_SHOWN, record_text

if TYPE_CHECKING:  # solo para los tipos: habilitar no importa el cálculo (RNF-001-03)
    from ...design.sectors import DesignSector, OrphanSlope
    from ...design.steps import Calculation

LOGGER = logging.getLogger("geoblender.bl.ui")
TRANSLATION_CONTEXT = "Geoblender"
PROFILES_PANEL = "GEOBLENDER_PT_des_profiles"
PROFILES_LIST = "GEOBLENDER_UL_des_profiles"
SAVE_PROFILE = "geoblender.des_save_bench_profile"
SET_PARAMETER = "geoblender.core_set_parameter"
SECTORS_PANEL = "GEOBLENDER_PT_des_sectors"
SECTORS_LIST = "GEOBLENDER_UL_des_sectors"
SET_SECTOR_SLOPE = "geoblender.des_set_sector_slope"
DECLARE_SECTORS = constraint_panels.DECLARE_SECTORS
FIND_UNTOUCHABLES = "geoblender.core_find_untouchables"
EDIT_LIMITS = constraint_panels.EDIT_LIMITS
PROFILES_PANEL_UNITS = 40
PROFILES_WIDTH_PX = PROFILES_PANEL_UNITS * 20
PROFILE_ROWS = 5
SECTORS_PANEL_UNITS = 44
SECTORS_WIDTH_PX = SECTORS_PANEL_UNITS * 20
SECTOR_ROWS = 4
SECTOR_NAME_FACTOR = 0.3
SECTOR_AREA_FACTOR = 0.25
SECTOR_SLOPE_FACTOR = 0.35
"""Cómo reparte la fila de la lista de sectores su ancho: el nombre, el área, el talud impuesto
y, con lo que queda, el estado de su búsqueda."""
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


# --- Lo que se enseña de los sectores de diseño (T23) --------------------------------------------


def _label(idname: str) -> str:
    """La etiqueta del catálogo de comandos de la orden ``idname``, en el idioma de Geoblender."""
    return command_text(catalog().commands[idname].label)


def _scope_name(scope: str, version: Any) -> str:
    """De dónde sale un talud: «el proyecto» o el código de la versión activa."""
    return tr("the project") if scope == "project" or version is None else str(version.code)


def slope_text(record: Any) -> str:
    """El talud de un registro (``ParameterRecord``) como se lee: «10,6° [ADO]», y «sin confirmar»
    si lo está (los grados pegados al número, como los derivados de un perfil)."""
    shown = f"{format_value(float(record.value), language())}° {provenance.badge(record.kind)}"
    return f"{shown} {tr('unconfirmed')}" if record.unconfirmed else shown


def slope_texts(sector: DesignSector, version: Any) -> tuple[str, str, str]:
    """El talud general máximo que impone ``sector`` como se lee: ``(talud, origen, problema)``.
    El talud, con su tipo («10,6° [ADO]»); el origen, quién lo decidió y de qué ámbito sale
    («la propiedad · decidido por Samuel (IMGA) · V01»); el problema, un talud guardado fuera de
    (0; 90) ° (el dominio lo rechaza al usarlo: aquí se lista para corregirlo). Un sector sin fila
    o con la fila sin valor no impone ninguno: los tres, vacíos."""
    found = sector.slope
    if found is None or found.value is None:
        return "", "", ""
    problem = ""
    try:
        _ = sector.imposed_deg  # el dominio comprueba el rango y lanza si no vale
    except design_messages.DesignError as exc:
        problem = design_error_text(exc)
    record = found.record
    source = tr("{source} · decided by {who} · {scope}", source=record.source or NOT_SHOWN,
                who=record.decided_by, scope=_scope_name(found.scope, version))
    return slope_text(record), source, problem


def put_sector(target: Any, sector: DesignSector, state: Any | None, version: Any,
               profile: str, names: Mapping[str, str]) -> None:
    """Un sector de diseño (``design.sectors.DesignSector``) en la fila ``target`` de la vista: su
    nombre y su código, su área, el estado de su búsqueda (el de la 012 si se conoce, con quién la
    cerró y cuándo), su talud impuesto con su origen y el perfil asignado ``profile`` (su código;
    ``names`` da el nombre de cada perfil del proyecto). Nada se calcula aquí: es el dominio."""
    target.name = constraint_panels.sector_name(sector.code, sector.name)
    target.code = sector.code
    target.area = f"{format_number(sector.area_m2, 0)} m²"
    target.pending = sector.pending
    if state is not None:
        target.search = constraint_panels.sector_text(state.search)
    else:  # sin el estado de la 012 a mano: lo que dice el dominio
        target.search = tr("Search pending") if sector.pending else tr("Search in force")
    target.slope, target.slope_source, target.problem = slope_texts(sector, version)
    target.profile = profile
    target.profile_name = names.get(profile, profile) if profile else ""


def orphan_text(orphan: OrphanSlope) -> str:
    """Un talud de un sector que ya no existe, como se lee: «Talud de «sector_2» en V01: 12° [ADO]
    · la propiedad · decidido por Samuel (IMGA)». Nunca se borra (RF-013-10)."""
    sector = (tr("the action perimeter") if orphan.segment == PERIMETER_SEGMENT
              else orphan.segment)
    record = orphan.record
    scope = tr("the project") if orphan.scope == "project" else orphan.version
    value = NOT_SHOWN if record.value is None else slope_text(record)
    return tr("Slope of «{sector}» in {scope}: {value} · {source} · decided by {who}",
              sector=sector, scope=scope, value=value,
              source=record.source or NOT_SHOWN, who=record.decided_by)


def fill_sectors(project: Any) -> int:
    """Regenera la lista de Sectores de diseño… desde ``project`` (RF-013-07, RF-013-08,
    RF-013-10): los sectores de la 012 (o el perímetro como único sector) con su área, el estado
    de su búsqueda y el talud que imponen en la versión activa (``design.sectors.design_sectors``),
    y aparte los de los sectores que ya no existen (``orphan_slopes``); conserva el elegido y el
    perfil asignado a cada sector (por su código). Devuelve cuántos sectores hay. Si no se puede
    leer, el error sigue y la vista queda como estaba."""
    from ...design import sectors as design_sectors  # al usarlo: habilitar no carga el cálculo
    from ...gis.masks import access as mask_access  # ídem

    shown = view()
    if shown is None:  # inalcanzable con la extensión registrada
        raise RuntimeError("la vista de los sectores de diseño no está registrada")
    version = scene_versions.active()
    uid = None if version is None else version.uid
    found = design_sectors.design_sectors(project, uid)
    states = {state.code: state for state in mask_access.sector_states(project, uid)}
    orphans = design_sectors.orphan_slopes(project, found)
    with project.read() as conn:
        names = design_profiles.profile_names(conn)
    old = shown.sectors
    chosen = old[shown.sector_index].code if 0 <= shown.sector_index < len(old) else None
    assigned = {item.code: item.profile for item in old if item.profile}
    marks = {item.code: (bool(item.use), item.profile_pick) for item in old}
    shown.sectors.clear()
    for sector in found:
        row = shown.sectors.add()
        put_sector(row, sector, states.get(sector.code), version,
                   assigned.get(sector.code, ""), names)
        use, pick = marks.get(sector.code, (False, ""))
        row.use, row.profile_pick = use, pick or row.profile_name
    shown.sector_index = next((index for index, item in enumerate(shown.sectors)
                               if item.code == chosen), 0)
    shown.orphans.clear()
    for orphan in orphans:
        line = shown.orphans.add()
        line.name, line.alert = orphan_text(orphan), True
    shown.sectors_project = project.uid
    return len(shown.sectors)


def fill_sector_sources(project: Any) -> None:
    """Las capas de polígonos del proyecto de las que se pueden declarar de nuevo los sectores, en
    la vista de la 012 (``sector_sources``: la declaración es suya, ``core_declare_sectors``)."""
    other = constraint_panels.view()
    if other is None:
        return
    other.sector_sources.clear()
    for name in constraint_panels.polygon_layers(project):
        other.sector_sources.add().name = name


def choose_sector(code: str) -> None:
    """Deja elegido en la lista el sector de código ``code`` (si está)."""
    shown = view()
    if shown is None:
        return
    for index, item in enumerate(shown.sectors):
        if item.code == code:
            shown.sector_index = index
            return


def assign_profiles(project: Any, assigned: Mapping[str, str]) -> None:
    """Pone a cada sector el perfil de banco de la superficie en preparación (RF-013-21):
    ``assigned`` da el código del perfil de cada código de sector (el perímetro, ``""``); un sector
    que no está, sin perfil. La ventana de las envolventes lo llama al elegir los perfiles; las
    lecturas de los sectores lo conservan."""
    shown = view()
    if shown is None:
        return
    with project.read() as conn:
        names = design_profiles.profile_names(conn)
    for item in shown.sectors:
        code = assigned.get(item.code, "")
        item.profile = code
        item.profile_name = names.get(code, code) if code else ""
        item.profile_pick = item.profile_name


def show_sector_report(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja ``lines`` (texto, si va en alerta) como el último resultado de la ventana de los
    sectores."""
    shown = view()
    if shown is None:
        return
    shown.sector_report.clear()
    for message, alert in lines:
        line = shown.sector_report.add()
        line.name, line.alert = message, alert


# --- Envolventes y escalonado… (T24; HU-013-1, HU-013-3, HU-013-5; RF-013-21, RF-013-31) --------

NO_ZONE = "none"
DOMAIN_ZONE = "domain"
CONSTRAINT_ZONE = "constraint:"
SECTOR_ZONE = "sector:"
LAYER_ZONE = "layer:"
NO_ANCHOR = "none"
NO_LAYER = "none"
"""Los identificadores de las opciones de las listas del diálogo: sin zona (toda la superficie),
el dominio por defecto de las máscaras, y el prefijo de una restricción, un sector o una capa (con
su código o su nombre detrás); sin rejilla de anclas (la del perfil); sin capa."""


@dataclass
class _Choices:
    """Las listas del diálogo ya leídas del proyecto (vivas: ``EnumProperty`` conserva sus textos,
    ``docs/trampas.md`` §3) y la clave de lo que se leyó."""

    surfaces: list[tuple[str, str, str]] = field(default_factory=list)
    anchors: list[tuple[str, str, str]] = field(default_factory=list)
    zones: list[tuple[str, str, str]] = field(default_factory=list)
    layers: list[tuple[str, str, str]] = field(default_factory=list)
    key: tuple[str, str, str] | None = None


_CHOICES = _Choices()


def _fixed_choices() -> None:
    """Las listas sin nada del proyecto: sin superficies, sin rejilla de anclas, sin capa y las
    zonas que no dependen de él."""
    _CHOICES.surfaces = [(NO_ZONE, NOT_SHOWN, tr("There are no grids in the project"))]
    _CHOICES.anchors = [(NO_ANCHOR, tr("The anchor of the profile"),
                         tr("Anchor the benches to the elevation of the profile"))]
    _CHOICES.zones = [(NO_ZONE, tr("The whole surface"),
                       tr("Seeds in every cell of the surface with an elevation")),
                      (DOMAIN_ZONE, tr("The default domain"),
                       tr("The cells of the default work domain of the masks"))]
    _CHOICES.layers = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of polygons in the project"))]


def refresh_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` las listas del diálogo, con la versión activa: las superficies
    y rejillas de cotas del proyecto y de la versión activa (las que puede leer el cálculo: no las
    congeladas ni las de otra versión), las zonas (el dominio por defecto, las restricciones, los
    sectores declarados y las capas de polígonos) y las capas con que se acota el dominio. Si no se
    puede leer, el error sigue y las listas quedan como estaban."""
    version = scene_versions.active_version() or ""
    found = [choice for choice in res_surfaces.surface_choices(project, version_uid=version)
             if choice.revision is None]
    with project.read() as conn:
        constraints = constraint_store.read_constraints(conn)
    layers = constraint_panels.polygon_layers(project)
    shown = view()
    sectors = [] if shown is None else [(item.code, item.name) for item in shown.sectors
                                        if item.code]
    _fixed_choices()
    if found:
        of_version, of_project = tr("A grid of the active version"), tr("A grid of the project")
        _CHOICES.surfaces = [(choice.name, choice.name,
                              of_version if choice.version_uid else of_project)
                             for choice in found]
    _CHOICES.anchors = [*_CHOICES.anchors, *_CHOICES.surfaces] if found else _CHOICES.anchors
    _CHOICES.zones = [
        *_CHOICES.zones,
        *((CONSTRAINT_ZONE + item.code, item.name, tr("Zone of a constraint"))
          for item in constraints if item.code),
        *((SECTOR_ZONE + code, name, tr("Design sector")) for code, name in sectors),
        *((LAYER_ZONE + name, constraint_panels.layer_label(name), tr("Layer of polygons"))
          for name in layers)]
    if layers:
        _CHOICES.layers = [(name, constraint_panels.layer_label(name), tr("Layer of polygons"))
                           for name in layers]
    _CHOICES.key = (project.uid, version, language())


def _ensure_choices() -> None:
    """Las listas del proyecto de la sesión y su versión activa (las lee si son de otro, una vez:
    ``invoke`` las vuelve a leer siempre); sin proyecto, las que no dependen de él."""
    project = project_session.current()
    if project is None:
        if not _CHOICES.zones:
            _fixed_choices()
        return
    key = (project.uid, scene_versions.active_version() or "", language())
    if key == _CHOICES.key:
        return
    try:
        refresh_choices(project)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.warning("No se pudieron leer las listas de envolventes y escalonado", exc_info=True)
        _fixed_choices()
        _CHOICES.key = key  # sin volver a intentarlo en cada dibujo: invoke las relee


def surface_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las superficies y rejillas de cotas que ofrece el diálogo (``EnumProperty``): una lista viva
    del módulo."""
    _ensure_choices()
    return _CHOICES.surfaces


def anchor_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las opciones del ancla del escalonado: el ancla de cada perfil o una rejilla de anclas del
    proyecto o de la versión activa (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.anchors


def zone_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las zonas de las semillas: toda la superficie, el dominio por defecto, una restricción, un
    sector o una capa de polígonos (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.zones


def layer_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas de polígonos con que se acota el dominio de trabajo (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.layers


def forget_choices() -> None:
    """Olvida las listas leídas (al desregistrar)."""
    _CHOICES.key = None
    _CHOICES.surfaces, _CHOICES.anchors, _CHOICES.zones, _CHOICES.layers = [], [], [], []


def has_surfaces() -> bool:
    """Si el proyecto ofrece alguna superficie o rejilla de cotas (la primera opción no es la de
    «ninguna»)."""
    _ensure_choices()
    return bool(_CHOICES.surfaces) and _CHOICES.surfaces[0][0] != NO_ZONE


def profile_codes() -> dict[str, str]:
    """El código de cada perfil de banco de la vista por su nombre (lo que se elige en el diálogo)."""
    shown = view()
    return {} if shown is None else {item.name: item.code for item in shown.profiles}


def clear_sector_marks() -> None:
    """Quita la marca de acotar de los sectores (el diálogo parte sin acotar); los perfiles
    elegidos se conservan."""
    shown = view()
    if shown is not None:
        for item in shown.sectors:
            item.use = False


def draw_sector_rows(layout: Any, *, bound: bool, profiles: bool) -> None:
    """Los sectores del diálogo, uno por fila: con ``bound``, su casilla de acotar el dominio de
    trabajo a él; con ``profiles``, el perfil que se le asigna (buscado entre los perfiles del
    proyecto; vacío, el perfil base). Su estado de búsqueda va en ámbar si está pendiente."""
    shown = view()
    if shown is None:
        return
    for item in shown.sectors:
        row = layout.row(align=True)
        if bound:
            row.prop(item, "use", text=item.name, translate=False)
        else:
            row.label(text=item.name, translate=False)
        if item.pending:
            alert = row.row(align=True)
            alert.alert = True
            alert.label(text=tr("Search pending"), icon="ERROR", translate=False)
        if profiles:
            row.prop_search(item, "profile_pick", shown, "profiles", text="", translate=False)


def _figure(calculation: Calculation, key: str) -> float | None:
    """El valor de la cifra ``key`` de un cálculo (``None`` si no se dio)."""
    return next((figure.value for figure in calculation.figures if figure.key == key), None)


def _number(value: float | None, decimals: int = 0) -> str:
    return NOT_SHOWN if value is None else format_number(value, decimals)


def summary_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de un cálculo hecho y sin registrar (RF-013-31), línea a línea y en el idioma de
    Geoblender, con los avisos al final y en alerta: de una envolvente, sus celdas, su área, sus
    cotas y el desmonte y el terraplén frente a la superficie de partida (las cifras que se
    registrarían); de un escalonado, el desmonte y el terraplén, la inclinación p99 y máxima con su
    lugar, y las bermas con sus cotas reales (el informe y las bermas del dominio). Aquí solo se
    escriben."""
    lines: list[tuple[str, bool]] = []
    if calculation.op_type == design_provenance.ENVELOPE:
        cells = _figure(calculation, "des.env_cells")
        lines.append((tr("Envelope «{name}»: {cells} cells ({area} m²)", name=calculation.name,
                         cells=_number(cells), area=_number(_figure(calculation,
                                                                    "des.env_area_m2"))), False))
        low, high = _figure(calculation, "des.env_min_m"), _figure(calculation, "des.env_max_m")
        if low is not None and high is not None:
            lines.append((tr("Elevations {low} to {high} m", low=_number(low, 1),
                             high=_number(high, 1)), False))
        cut, fill = _figure(calculation, "des.env_cut_m3"), _figure(calculation, "des.env_fill_m3")
        if cut is not None and fill is not None:
            lines.append((tr("Against the start surface: cut {cut} m³ · fill {fill} m³",
                             cut=_number(cut), fill=_number(fill)), False))
    else:
        outcome = calculation.outcome
        report, berms = outcome.report, outcome.berms  # type: ignore[union-attr]
        lines.append((tr("Benching «{name}»: cut {cut} m³ · fill {fill} m³ · moved area {area} m²",
                         name=calculation.name, cut=_number(report.cut_m3),
                         fill=_number(report.fill_m3), area=_number(report.moved_area_m2)),
                      False))
        if report.slope_max_deg is not None and report.slope_p99_deg is not None:
            where = report.slope_max_at
            lines.append((tr("Cell slope: p99 {p99}° · maximum {max}° at ({x}, {y})",
                             p99=_number(report.slope_p99_deg, 1),
                             max=_number(report.slope_max_deg, 1),
                             x=_number(None if where is None else where.x, 1),
                             y=_number(None if where is None else where.y, 1)), False))
        if berms.lowest_m is not None and berms.highest_m is not None:
            lines.append((tr("{count} berms, real elevations {low} to {high} m",
                             count=_number(berms.count), low=_number(berms.lowest_m, 1),
                             high=_number(berms.highest_m, 1)), False))
        else:
            lines.append((tr("No berms: nothing moves"), False))
    lines.extend((notice.text(language()), notice.severity == "warning")
                 for notice in calculation.notices)
    return lines


def show_preview(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja ``lines`` (texto ya traducido, si va en alerta) como el resumen de la vista previa de
    semillas, dominios y restricciones (T25; RF-013-03; ``bl.draw.design``: lo que dice
    ``design.preview``, aquí solo se guarda para que lo dibuje la barra N); sin líneas, lo vacía."""
    shown = view()
    if shown is None:
        return
    shown.preview.clear()
    for text, alert in lines:
        line = shown.preview.add()
        line.name, line.alert = text, alert


def show_summary(calculation: Calculation | None) -> None:
    """Deja el resumen del cálculo abierto ``calculation`` (:func:`summary_lines`) en la vista, con
    su título («Envolvente «Hoyo» en V01»); sin cálculo, lo vacía."""
    shown = view()
    if shown is None:
        return
    shown.summary.clear()
    if calculation is None:
        shown.summary_title = ""
        return
    shown.summary_title = (tr("Envelope «{name}» in {version}", name=calculation.name,
                              version=calculation.version)
                           if calculation.op_type == design_provenance.ENVELOPE
                           else tr("Benching «{name}» in {version}", name=calculation.name,
                                   version=calculation.version))
    for text, alert in summary_lines(calculation):
        line = shown.summary.add()
        line.name, line.alert = text, alert


def draw_summary(layout: Any, width_px: int) -> None:
    """El resumen del cálculo abierto de la vista (:func:`show_summary`) en un diálogo de
    ``width_px``: su título y cada línea partida al ancho, los avisos en ámbar."""
    shown = view()
    if shown is None:
        return
    width = labels.dialog_width(width_px)
    if shown.summary_title:
        _draw_text(layout, shown.summary_title, width)
    for line in shown.summary:
        _draw_text(layout, line.name, width, alert=bool(line.alert))


def on_project_read(project: Any) -> None:
    """Lo que hace la escucha de los indicadores de la procedencia cada vez que el proyecto
    cambió (``bl.ui.provenance.add_change_listener``): los valores de las ventanas de los perfiles
    y de los sectores, al día si son de ``project`` (un valor cambiado con ``Cambiar…``, sectores
    declarados de nuevo con la 012). Si no se puede leer, lo deja en el registro técnico."""
    shown = view()
    if shown is None:
        return
    if shown.profiles_project and shown.profiles_project == project.uid:
        try:
            fill_profiles(project)
        except (GeoblenderError, sqlite3.Error, OSError):
            LOGGER.warning("No se pudieron leer los perfiles de banco", exc_info=True)
    if shown.sectors_project and shown.sectors_project == project.uid:
        try:
            fill_sectors(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.warning("No se pudieron leer los sectores de diseño", exc_info=True)


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


# --- Sectores de diseño… (T23; HU-013-2; RF-013-07, RF-013-08, RF-013-10, RF-013-21) ----------


class GEOBLENDER_UL_des_sectors(bpy.types.UIList):
    """Design sectors with their area, the slope they impose and the state of their search"""

    bl_idname = SECTORS_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        split = layout.split(factor=SECTOR_NAME_FACTOR, align=True)
        split.label(text=item.name, translate=False)
        rest = split.split(factor=SECTOR_AREA_FACTOR, align=True)
        rest.label(text=item.area, translate=False)
        more = rest.split(factor=SECTOR_SLOPE_FACTOR, align=True)
        slope = more.row(align=True)
        slope.alert = bool(item.problem)
        slope.label(text=item.slope or NOT_SHOWN, translate=False)
        state = more.row(align=True)
        state.alert = bool(item.pending)
        state.label(text=tr("Search pending") if item.pending else tr("Search in force"),
                    icon="ERROR" if item.pending else "CHECKMARK", translate=False)


def _draw_sector(layout: Any, item: Any, width: float, writable: bool) -> None:
    """El sector elegido: su nombre y su código, su área, el estado de su búsqueda (en ámbar si
    está pendiente, con la orden de la 012 para hacerla), el talud que impone con su origen, su
    decisor y su ámbito, el perfil asignado y «Fijar el talud del sector…» (RF-013-07)."""
    box = layout.box()
    box.label(text=item.name, translate=False)
    if item.code:
        _draw_text(box, tr("Code: {code}", code=item.code), width)
    _draw_text(box, tr("Area: {area}", area=item.area), width)
    _draw_text(box, item.search, width, alert=bool(item.pending))
    if item.pending:
        _draw_text(box, tr("The search of untouchable elements is mandatory before designing: "
                           "{path}", path=path_text(catalog(), FIND_UNTOUCHABLES, language())),
                   width)
        search = box.row()
        search.enabled = writable
        search.operator(FIND_UNTOUCHABLES, text=_label(FIND_UNTOUCHABLES), icon="VIEWZOOM",
                        translate=False)
    if item.slope:
        _draw_text(box, tr("Maximum general slope imposed: {slope}", slope=item.slope), width)
        _draw_text(box, item.slope_source, width)
    else:
        _draw_text(box, tr("No maximum general slope imposed"), width)
    if item.problem:
        _draw_text(box, item.problem, width, alert=True)
    _draw_text(box, tr("Profile assigned: {profile}", profile=item.profile_name or NOT_SHOWN),
               width)
    edit = box.row()
    edit.enabled = writable
    button = edit.operator(SET_SECTOR_SLOPE, text=_label(SET_SECTOR_SLOPE), icon="GREASEPENCIL",
                           translate=False)
    button.code = item.code


def _draw_orphans(layout: Any, shown: Any, width: float) -> None:
    """Los taludes de los sectores que ya no existen, en una lista aparte y en ámbar (RF-013-10):
    no se borran nunca; la persona declara el valor en el sector que los sustituye."""
    if not len(shown.orphans):
        return
    box = layout.box()
    box.label(text=tr("Parameters without a sector: {count}", count=len(shown.orphans)),
              translate=False)
    _draw_text(box, tr("These values belong to sectors that no longer exist (renamed or "
                       "removed). They are never deleted: set the value again in the sector "
                       "that replaces them"), width)
    for line in shown.orphans:
        _draw_text(box, line.name, width, alert=bool(line.alert))


def _draw_declare(layout: Any, writable: bool) -> None:
    """«Declarar de nuevo desde una capa…» (RF-013-07, RF-013-10): la capa de polígonos y el
    campo del nombre de la 012 y su orden de declarar los sectores (``core_declare_sectors``,
    que conserva los valores de los sectores que mantienen su código)."""
    other = constraint_panels.view()
    box = layout.box()
    box.label(text=tr("Declare the sectors from a layer of polygons"), translate=False)
    form = box.column()
    form.enabled = writable
    if other is not None:
        form.prop_search(other, "sector_layer", other, "sector_sources",
                         text=tr("Layer of the sectors"), translate=False)
        form.prop(other, "sector_field", text=tr("Field of the name"), translate=False)
    form.operator(DECLARE_SECTORS, text=tr("Declare again from a layer…"), icon="CHECKMARK",
                  translate=False)


def draw_sectors(layout: Any, context: Any) -> None:
    """La ventana de Sectores de diseño… (véase el módulo), de lo ya leído."""
    shown = view()
    if shown is None:
        return
    blocked = _write_unavailable()
    writable = blocked is None
    width = labels.dialog_width(SECTORS_WIDTH_PX)
    _draw_blocked(layout, blocked, width)
    if not len(shown.sectors):
        labels.draw_wrapped(layout, tr(
            "There is no action perimeter or legal limit and no sectors are declared: declare "
            "the legal limit first with {path}",
            path=path_text(catalog(), EDIT_LIMITS, language())), width, icon="INFO")
    else:
        layout.label(text=tr("Design sectors: {count}", count=len(shown.sectors)),
                     translate=False)
        layout.template_list(SECTORS_LIST, "", shown, "sectors", shown, "sector_index",
                             rows=SECTOR_ROWS)
        index = min(max(shown.sector_index, 0), len(shown.sectors) - 1)
        _draw_sector(layout, shown.sectors[index], width, writable)
    _draw_orphans(layout, shown, width)
    _draw_declare(layout, writable)
    if len(shown.sector_report):
        box = layout.box()
        box.label(text=tr("Last result"), translate=False)
        for line in shown.sector_report:
            _draw_text(box, line.name, width, alert=bool(line.alert))


class GEOBLENDER_PT_des_sectors(bpy.types.Panel):
    """Design sectors: their area, the state of their search, the maximum general slope they
    impose with its source and decider, and the profile assigned to each"""

    bl_idname = SECTORS_PANEL
    bl_label = "Design sectors"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = SECTORS_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_sectors(self.layout, context)


# En orden de registro (las listas, antes de la ventana que las dibuja).
classes: tuple[type, ...] = (GEOBLENDER_UL_des_profiles, GEOBLENDER_PT_des_profiles,
                             GEOBLENDER_UL_des_sectors, GEOBLENDER_PT_des_sectors)


def install() -> None:
    """Pone la escucha de los indicadores (:func:`on_project_read`); idempotente."""
    provenance.add_change_listener(on_project_read)


def uninstall() -> None:
    """Quita lo que puso :func:`install` y olvida las listas del diálogo de las envolventes;
    idempotente."""
    provenance.remove_change_listener(on_project_read)
    forget_choices()
