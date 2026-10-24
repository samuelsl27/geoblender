# SPDX-License-Identifier: GPL-3.0-or-later
"""Los paneles de la cubicación (spec 011; plan 011 §5.1, §5.3.3, §5.3.4, §5.5, D-9, D-11,
D-12, D-18).

**Materiales y densidades…** (T20; RF-011-11, RF-011-15, RF-011-21): la ventana
``GEOBLENDER_PT_res_materials`` (la abre ``geoblender.res_edit_materials``, ``bl.ops.res``)
dibuja la columna de materiales en edición de ``WindowManager.geoblender_res_panels``
(``bl.props.res``):

- el umbral de presencia de lo antrópico con su valor, su tipo y «Cambiar…» (``Cambiar
  parámetro…`` de la 008);
- las unidades de arriba abajo (``GEOBLENDER_UL_res_units``) con los botones de añadir, quitar,
  subir y bajar (``geoblender.res_edit_column``) y, de la elegida, su nombre, su clase, su
  papel, su estado, su base (una rejilla del proyecto o una cota constante; la última, sin base)
  y, una antrópica, su rejilla de espesores; una compuesta, sus componentes
  (``GEOBLENDER_UL_res_components``) y «Porcentajes…» (``geoblender.res_set_percentages``);
- de cada unidad que no es compuesta y de cada componente, ya guardados, la densidad in situ y
  el K con su tipo y su ámbito («V01: 1,25 [HIP] · proyecto: sin valor [HIP] sin confirmar»),
  con «Densidad…» y «K…» (``geoblender.core_set_parameter`` de su clave: la 008 pide el tipo, el
  origen, el decisor y el motivo y, del K, la 009 pregunta «¿Para el proyecto o solo para
  V01?») y «Aplicar a todas» (``geoblender.res_apply_swell``);
- «Guardar la columna» (``geoblender.res_save_materials``).

En solo lectura dice por qué y dibuja desactivado lo que escribe. **Nada se lee al dibujar**:
:func:`fill_materials` regenera la vista desde el proyecto (al abrir la ventana) y
:func:`refresh_parameters`, solo los valores de los parámetros, en su sitio (tras guardar o
cambiar un parámetro: :func:`on_project_read` escucha los indicadores de la procedencia,
``bl.ui.provenance.add_change_listener``). Los textos pasan por ``core.i18n`` y se dibujan con
``translate=False``.

**Las listas de los diálogos de la cubicación** (T21; plan §2.1, §5.3.4): las superficies que se
pueden cubicar (:func:`surface_items`: las de ``reserves.surfaces.surface_choices`` y «Cota
constante»), las capas que pueden ser su ámbito (:func:`scope_items`: «Sin ámbito», contornos
y dominios) y, para «Por unidad, fase y banco…» (T23), las capas de dominios
(:func:`domain_items`) y los campos de la elegida (:func:`field_items`, con su título), en
listas vivas del módulo (Blender guarda punteros a sus cadenas), del proyecto de
la sesión, su versión activa y el idioma de Geoblender: la orden las vuelve a leer al abrir su
diálogo (:func:`refresh_choices`) y la escucha de los indicadores, cuando cambia el proyecto.

**Las cubicaciones de la versión activa** (T24): :func:`fill_volumetrics` las deja en la vista
(lo que ofrece «Por momentos de extracción…» como momentos y directa) y :func:`show_cubication`
deja elegida una con el filtro de datos de su tabla (todos o, desde «Ratios…», las relaciones;
D-35), la que dibujará la ventana de la cubicación (T25).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import bpy

from ...core.errors import GeoblenderError
from ...core.i18n import language, tr, translate
from ...core.params import VERSION_SCOPE, ParameterStore
from ...core.params import definition as param_definition
from ...core.params.store import shown_value
from ...gis import provenance as gis_provenance
from ...gis import store as gis_store
from ...reserves import materials as res_materials
from ...reserves import params as res_params
from ...reserves import surfaces as res_surfaces
from ..props.res import (
    BASE_ELEVATION,
    BASE_ITEMS,
    BASE_SURFACE,
    KIND_ITEMS,
    QUANTITIES_ALL,
    ROLE_ITEMS,
    ROLE_NONE,
    STATE_ITEMS,
    WINDOW_MANAGER_PROPERTY,
)
from ..scene import project_session
from ..scene import versions as scene_versions
from . import provenance
from .commands import catalog, text

LOGGER = logging.getLogger("geoblender.bl.ui")
TRANSLATION_CONTEXT = "Geoblender"
MATERIALS_PANEL = "GEOBLENDER_PT_res_materials"
UNITS_LIST = "GEOBLENDER_UL_res_units"
COMPONENTS_LIST = "GEOBLENDER_UL_res_components"
MATERIALS_PANEL_UNITS = 36
UNIT_ROWS = 5
COMPONENT_ROWS = 3
NOT_SHOWN = "—"
"""Un valor que no hay (la versión activa sin valor propio)."""
SET_PARAMETER = "geoblender.core_set_parameter"
EDIT_COLUMN = "geoblender.res_edit_column"
SAVE_MATERIALS = "geoblender.res_save_materials"
APPLY_SWELL = "geoblender.res_apply_swell"
SET_PERCENTAGES = "geoblender.res_set_percentages"
COMPOUND = "COMPOUND"
ANTHROPIC = "ANTHROPIC"
_KIND = {identifier: name for identifier, name, _about in KIND_ITEMS}
_ROLE = {identifier: name for identifier, name, _about in ROLE_ITEMS}


def view() -> Any | None:
    """``WindowManager.geoblender_res_panels`` (``None`` sin la extensión registrada)."""
    manager = getattr(bpy.context, "window_manager", None)
    return getattr(manager, WINDOW_MANAGER_PROPERTY, None)


def _write_unavailable() -> str | None:
    """Por qué no se puede escribir en el proyecto ahora, o ``None``."""
    from ..ops import core_provenance  # al usarlo: bl/ops importa bl/ui (ARQ-08)

    return core_provenance.write_unavailable()


# --- Lo que se enseña de un parámetro ------------------------------------------------------------


def record_text(record: Any, key: str | None = None) -> str:
    """Un parámetro del proyecto como se enseña: su valor con su unidad, su insignia de tipo y,
    si lo tiene, «sin confirmar» («sin valor [HIP] sin confirmar», «1,9 t/m³ [MED]»). Sin
    registrar, lo que registraría su primera lectura (el valor y el tipo por defecto de la
    definición de ``key``, «sin confirmar»; RF-008-04); sin definición, «—»."""
    if record is None:
        found = None if key is None else param_definition(key)
        if found is None:
            return NOT_SHOWN
        value, unit, kind, unconfirmed = found.default, found.unit, found.kind, True
    else:
        value, unit, kind, unconfirmed = (record.value, record.unit, record.kind,
                                          record.unconfirmed)
    shown = f"{shown_value(value, unit, language())} {provenance.badge(kind)}"
    if unconfirmed:
        shown = f"{shown} {tr('unconfirmed')}"
    return shown


def parameter_text(store: ParameterStore, conn: sqlite3.Connection, key: str,
                   version: Any) -> str:
    """El parámetro ``key`` con su tipo (:func:`record_text`) y, si su módulo lo admite por
    versión y hay una versión activa (``version``, la que se enseña), también el valor propio
    de ella (RF-009-29): «V01: 1,25 [HIP] · proyecto: sin valor [HIP] sin confirmar»."""
    project_text = record_text(store.get(key, conn=conn), key)
    found = param_definition(key)
    if version is None or found is None or found.scope != VERSION_SCOPE:
        return project_text
    own = store.get(key, version=version.uid, conn=conn)
    return tr("{version}: {value} · project: {project}", version=version.code,
              value=NOT_SHOWN if own is None else record_text(own), project=project_text)


# --- La vista: llenarla desde el proyecto --------------------------------------------------------


def _elevation_text(elevation: float) -> str:
    """Una cota constante como se teclea (sin decimales si es entera; coma en español)."""
    text = str(int(elevation)) if float(elevation).is_integer() else repr(float(elevation))
    return text.replace(".", ",") if language() == "es" else text


def _set_unit(item: Any, unit: res_materials.Unit) -> None:
    """Una unidad guardada (``reserves.materials.Unit``) en la fila ``item`` de la vista."""
    item.name = unit.name
    item.code = unit.code
    item.saved = True
    item.kind = str(unit.kind).upper()
    item.role = ROLE_NONE if unit.role is None else str(unit.role).upper()
    item.state = str(unit.state).upper()
    item.base_kind, item.base_dataset, item.base_elevation = BASE_SURFACE, "", ""
    base = unit.base
    if base is not None and base.dataset is not None:
        item.base_dataset = base.dataset
    elif base is not None and base.elevation is not None:
        item.base_kind, item.base_elevation = BASE_ELEVATION, _elevation_text(base.elevation)
    item.thickness_dataset = "" if unit.thickness is None else (unit.thickness.dataset or "")
    item.components.clear()
    for component in unit.components:
        row = item.components.add()
        row.name, row.code, row.saved = component.name, component.code, True
        row.role = ROLE_NONE if component.role is None else str(component.role).upper()
    item.component_index = 0


def fill_materials(project: Any) -> int:
    """Regenera la columna en edición desde ``project`` (RF-011-11): la guardada
    (``res_materials``; sin ella, ninguna unidad), las rejillas del proyecto que se pueden
    elegir como base o espesor y los valores de sus parámetros (:func:`refresh_parameters`).
    Devuelve cuántas unidades hay. Si no se puede leer el proyecto, el error sigue y la vista
    queda como estaba."""
    shown = view()
    if shown is None:
        return 0
    with project.read() as conn:
        column = res_materials.read_column(conn)
    surfaces = [record.name for record in gis_store.list_gis_datasets(
        project, families=(gis_provenance.PROJECT_GRID,))]
    shown.units.clear()
    for unit in () if column is None else column.units:
        _set_unit(shown.units.add(), unit)
    shown.unit_index = 0
    shown.surfaces.clear()
    for name in surfaces:
        shown.surfaces.add().name = name
    shown.materials_project = project.uid
    refresh_parameters(project)
    return len(shown.units)


def mark_saved(project: Any, column: res_materials.MaterialColumn) -> None:
    """Tras guardar ``column`` (la de la vista, en su orden): cada fila con su código y su
    nombre guardados, en su sitio (sin regenerar la lista), y los valores de sus parámetros."""
    shown = view()
    if shown is None:
        return
    for item, unit in zip(shown.units, column.units, strict=False):
        item.code, item.name, item.saved = unit.code, unit.name, True
        for row, component in zip(item.components, unit.components, strict=False):
            row.code, row.name, row.saved = component.code, component.name, True
    shown.materials_project = project.uid
    refresh_parameters(project)


def refresh_parameters(project: Any) -> None:
    """Vuelve a leer, en su sitio, los valores de los parámetros que enseña la vista de
    ``project`` (el umbral de presencia y la densidad, el K y el porcentaje de cada unidad y
    componente guardados, RF-011-21); si la vista es de otro proyecto (o de ninguno), nada."""
    shown = view()
    if shown is None or not shown.materials_project or shown.materials_project != project.uid:
        return
    version = scene_versions.active()
    store = ParameterStore(project)
    with project.read() as conn:
        shown.presence = record_text(store.get(res_params.ANTHROPIC_PRESENCE, conn=conn),
                                     res_params.ANTHROPIC_PRESENCE)
        for item in shown.units:
            saved = item.saved and bool(item.code)
            simple = saved and item.kind != COMPOUND
            item.density = parameter_text(store, conn, res_params.density_key(item.code),
                                          version) if simple else ""
            item.swell = parameter_text(store, conn, res_params.swell_key(item.code),
                                        version) if simple else ""
            for row in item.components:
                inside = saved and item.kind == COMPOUND and row.saved and bool(row.code)
                keys = (res_params.density_key(item.code, row.code),
                        res_params.swell_key(item.code, row.code),
                        res_params.percent_key(item.code, row.code)) if inside else ()
                texts = [parameter_text(store, conn, key, version) for key in keys]
                row.density, row.swell, row.percent = texts if texts else ("", "", "")


def on_project_read(project: Any) -> None:
    """Lo que hace la escucha de los indicadores de la procedencia cada vez que el proyecto
    cambió (``bl.ui.provenance.add_change_listener``): los valores de los parámetros de la
    vista, al día (:func:`refresh_parameters`), y las listas de los diálogos de la cubicación,
    si ya se leyeron para él (:func:`refresh_choices`). Si no se puede leer, lo deja en el
    registro técnico."""
    try:
        refresh_parameters(project)
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudieron leer los parámetros de los materiales", exc_info=True)
    key = _CHOICES.key
    if key is not None and key[0] == project.uid:
        try:
            refresh_choices(project, key[1])
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.warning("No se pudieron leer las superficies de la cubicación", exc_info=True)


# --- Las listas de los diálogos de la cubicación (T21; plan §2.1, §5.3.4) -----------------------

ELEVATION = "ELEVATION"
"""El elemento «Cota constante» de las listas de superficies (su cota se teclea aparte)."""
FROZEN = "frozen:"
"""El comienzo del identificador de una superficie congelada en la revisión de la que parte la
versión activa (``frozen:<nombre del dato>``); el de una viva es el nombre de su dato."""
NO_SCOPE = "NONE"
"""El elemento «Sin ámbito» de la lista de capas del ámbito."""
NO_DOMAINS = "NONE"
"""El elemento «Sin dominios» de la lista de capas de dominios (T23)."""
NO_FIELD = "NONE"
"""El elemento de la lista de campos sin capa de dominios (o de una capa sin campos)."""
VOLUMETRICS_PANEL = "GEOBLENDER_PT_res_volumetrics"
"""La ventana de la cubicación (T25): la abre la orden al terminar."""


@dataclass
class _Choices:
    """Las listas vivas de los diálogos (plan §2.1: Blender guarda punteros a sus cadenas): de
    qué proyecto, versión activa e idioma son, las superficies (``EnumProperty``), las capas del
    ámbito, las de dominios y los campos de cada una (T23), y cada superficie por su
    identificador."""

    key: tuple[str, str, str] | None = None
    surfaces: list[tuple[str, str, str]] = field(default_factory=list)
    layers: list[tuple[str, str, str]] = field(default_factory=list)
    domains: list[tuple[str, str, str]] = field(default_factory=list)
    fields: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    by_id: dict[str, res_surfaces.SurfaceChoice] = field(default_factory=dict)


_CHOICES = _Choices()


def surface_id(choice: res_surfaces.SurfaceChoice) -> str:
    """El identificador de ``choice`` en las listas: el nombre de su dato o, de lo congelado,
    :data:`FROZEN` y su nombre."""
    return choice.name if choice.revision is None else FROZEN + choice.name


def _fixed_items() -> tuple[tuple[str, str, str], tuple[str, str, str]]:
    return ((ELEVATION, tr("Constant elevation"), tr("A constant elevation (m), typed below")),
            (NO_SCOPE, tr("No scope"), tr("The whole grid of the surfaces")))


def _no_domains() -> tuple[tuple[str, str, str], tuple[str, str, str]]:
    return ((NO_DOMAINS, tr("No domains"), tr("Do not split the cubication by domains")),
            (NO_FIELD, NOT_SHOWN, tr("Choose a domain layer first")))


def refresh_choices(project: Any, version_uid: str | None) -> None:
    """Vuelve a leer de ``project``, con la versión activa ``version_uid``, las superficies que
    ofrece la orden (``reserves.surfaces.surface_choices``: las rejillas del proyecto y de la
    versión activa y las congeladas en la revisión de la que parte), las capas que pueden ser
    su ámbito (contornos y dominios, D-32) y las de dominios con sus campos (T23,
    ``gis.store.domain_fields``), en el idioma de Geoblender. Si no se puede leer, el error
    sigue y las listas quedan como estaban."""
    found = res_surfaces.surface_choices(project, version_uid=version_uid or "")
    layers = gis_store.list_gis_datasets(project, families=(gis_provenance.BOUNDARY,
                                                            gis_provenance.DOMAINS))
    domains = [record for record in layers if record.name.startswith(
        gis_provenance.FAMILIES_BY_CODE[gis_provenance.DOMAINS].prefix)]
    fields = {record.name: [(column, title, tr("Field «{field}» of the layer", field=title))
                            for column, title in gis_store.domain_fields(project, record)]
              for record in domains}
    elevation, no_scope = _fixed_items()
    no_domains, no_field = _no_domains()
    surfaces: list[tuple[str, str, str]] = []
    for choice in found:
        if choice.revision is not None:
            surfaces.append((surface_id(choice), f"{choice.name} · {choice.revision}",
                             tr("Frozen in {revision}, the revision the active version starts "
                                "from", revision=choice.revision)))
        else:
            surfaces.append((choice.name, choice.name,
                             tr("A grid of the active version") if choice.version_uid
                             else tr("A grid of the project")))
    boundary = gis_provenance.FAMILIES_BY_CODE[gis_provenance.BOUNDARY].prefix
    _CHOICES.surfaces = [*surfaces, elevation]
    _CHOICES.layers = [no_scope, *((record.name, record.name,
                                    tr("Boundary layer") if record.name.startswith(boundary)
                                    else tr("Domain layer (their union)"))
                                   for record in layers)]
    _CHOICES.domains = [no_domains, *((record.name, record.name, tr("Domain layer"))
                                      for record in domains)]
    _CHOICES.fields = {name: items or [no_field] for name, items in fields.items()}
    _CHOICES.fields[NO_DOMAINS] = [no_field]
    _CHOICES.by_id = {surface_id(choice): choice for choice in found}
    _CHOICES.key = (project.uid, version_uid or "", language())


def _only_fixed() -> None:
    """Las listas sin nada del proyecto: la cota constante, sin ámbito y sin dominios."""
    elevation, no_scope = _fixed_items()
    no_domains, no_field = _no_domains()
    _CHOICES.surfaces, _CHOICES.layers, _CHOICES.by_id = [elevation], [no_scope], {}
    _CHOICES.domains, _CHOICES.fields = [no_domains], {NO_DOMAINS: [no_field]}


def _ensure_choices() -> None:
    """Las listas del proyecto de la sesión y su versión activa (las lee si son de otro, una
    vez: ``invoke`` las vuelve a leer siempre); sin proyecto, solo la cota constante."""
    project = project_session.current()
    if project is None:
        if not _CHOICES.surfaces:
            _only_fixed()
        return
    key = (project.uid, scene_versions.active_version() or "", language())
    if key == _CHOICES.key:
        return
    try:
        refresh_choices(project, key[1])
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.warning("No se pudieron leer las superficies de la cubicación", exc_info=True)
        _only_fixed()
        _CHOICES.key = key  # sin volver a intentarlo en cada dibujo: invoke lo relee


def surface_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las opciones de las listas de superficies de los diálogos (``EnumProperty``): las de
    :func:`refresh_choices` y «Cota constante», en una lista viva del módulo."""
    _ensure_choices()
    return _CHOICES.surfaces


def scope_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las opciones de la lista de capas del ámbito: «Sin ámbito» y las capas de contornos y de
    dominios del proyecto (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.layers


def domain_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las opciones de la lista de capas de dominios de «Por unidad, fase y banco…» (T23):
    «Sin dominios» y las capas de dominios del proyecto (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.domains


def field_items(owner: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las opciones de la lista de campos (T23; RF-011-07): los de la capa de dominios elegida
    en ``owner`` (su ``domains_layer``), con su título; sin capa, «—» (listas vivas del
    módulo)."""
    _ensure_choices()
    layer = str(getattr(owner, "domains_layer", NO_DOMAINS) or NO_DOMAINS)
    found = _CHOICES.fields.get(layer)
    return found if found is not None else _CHOICES.fields.setdefault(
        NO_DOMAINS, [_no_domains()[1]])


def surface_choice(identifier: str) -> res_surfaces.SurfaceChoice | None:
    """La superficie de identificador ``identifier`` de las listas leídas, o ``None``."""
    return _CHOICES.by_id.get(identifier)


def forget_choices() -> None:
    """Olvida las listas leídas (al desregistrar)."""
    _CHOICES.key, _CHOICES.by_id = None, {}


# --- Las cubicaciones de la versión activa (T24; RF-011-18, RF-011-19, RF-011-23) --------------


def fill_volumetrics(project: Any, version_uid: str | None) -> tuple[Any, ...]:
    """Vuelve a leer de ``project`` las cubicaciones de la versión activa ``version_uid``
    (``reserves.store.cubications``; sin versión, ninguna) y las deja en la vista
    (``cubications``: su nombre, si reparte por unidades y si tiene toneladas); si la elegida ya
    no está, ninguna. Devuelve las leídas. Si no se puede leer, el error sigue y la vista queda
    como estaba. La T25 le añade lo demás de cada una."""
    from ...reserves import store  # al usarlo: habilitar no lo carga

    found = () if not version_uid else store.cubications(project, version=version_uid)
    shown = view()
    if shown is None:
        return found
    shown.cubications.clear()
    for item in found:
        row = shown.cubications.add()
        row.name, row.units, row.tonnage = item.name, item.units, item.tonnage is not None
    if shown.cubication not in {item.name for item in found}:
        shown.cubication = ""
    return found


def show_cubication(name: str, *, quantities: str = QUANTITIES_ALL) -> None:
    """Deja elegida en la vista la cubicación ``name`` con el filtro de datos ``quantities``
    (``bl.props.res.QUANTITY_ITEMS``: todos o las relaciones, D-35): la que dibuja la ventana
    de la cubicación (T25)."""
    shown = view()
    if shown is None:  # inalcanzable con la extensión registrada
        return
    shown.cubication, shown.quantities = name, quantities


# --- Dibujo --------------------------------------------------------------------------------------


def _label(idname: str) -> str:
    """La etiqueta del catálogo de comandos de la orden ``idname``, en el idioma de
    Geoblender."""
    return text(catalog().commands[idname].label)


def _choice(layout: Any, owner: Any, prop: str, items: Any, label: str) -> None:
    """Una fila con la etiqueta ``label`` y un botón por cada elemento de ``items`` (sus
    textos en el idioma de Geoblender)."""
    row = layout.row(align=True)
    # Sin separar etiqueta y valor: con ella, Blender lleva el texto de ``prop_enum`` a una
    # etiqueta a la izquierda y deja el botón vacío (009, T36).
    row.use_property_split = False
    row.label(text=label, translate=False)
    shown = language()
    for identifier, name, _about in items:
        row.prop_enum(owner, prop, identifier, text=translate(shown, name), translate=False)


def _draw_parameters(layout: Any, owner: Any, unit: str, component: str) -> None:
    """La densidad y el K de una unidad o de un componente guardado, con sus órdenes."""
    row = layout.row(align=True)
    row.label(text=tr("In-situ density: {value}", value=owner.density), translate=False)
    button = row.operator(SET_PARAMETER, text=tr("Density…"), translate=False)
    button.key = res_params.density_key(unit, component or None)
    row = layout.row(align=True)
    row.label(text=tr("K: {value}", value=owner.swell), translate=False)
    button = row.operator(SET_PARAMETER, text=tr("K…"), translate=False)
    button.key = res_params.swell_key(unit, component or None)
    apply = row.operator(APPLY_SWELL, text=_label(APPLY_SWELL), translate=False)
    apply.unit = unit
    apply.component = component


def _draw_components(layout: Any, unit: Any) -> None:
    """Los componentes de una compuesta, el elegido y «Porcentajes…»."""
    layout.label(text=tr("Components"), translate=False)
    row = layout.row()
    row.template_list(COMPONENTS_LIST, "", unit, "components", unit, "component_index",
                      rows=COMPONENT_ROWS)
    side = row.column(align=True)
    side.operator(EDIT_COLUMN, text="", icon="ADD").action = "ADD_COMPONENT"
    side.operator(EDIT_COLUMN, text="", icon="REMOVE").action = "REMOVE_COMPONENT"
    if not len(unit.components):
        return
    index = min(max(unit.component_index, 0), len(unit.components) - 1)
    component = unit.components[index]
    layout.prop(component, "name", text=tr("Name"), translate=False)
    _choice(layout, component, "role", ROLE_ITEMS[1:], tr("Role"))
    if not (unit.saved and component.saved):
        layout.label(text=tr("Save the column to declare its parameters"), icon="INFO",
                     translate=False)
        return
    layout.label(text=tr("Share: {value}", value=component.percent), translate=False)
    _draw_parameters(layout, component, unit.code, component.code)
    layout.operator(SET_PERCENTAGES, text=_label(SET_PERCENTAGES),
                    translate=False).unit = unit.code


def _draw_unit(layout: Any, materials: Any, unit: Any, last: bool) -> None:
    """La unidad elegida: su nombre, su clase, su papel, su estado, su base, su espesor y sus
    parámetros (o sus componentes)."""
    box = layout.box()
    box.prop(unit, "name", text=tr("Name"), translate=False)
    _choice(box, unit, "kind", KIND_ITEMS, tr("Kind"))
    if unit.kind != COMPOUND:
        _choice(box, unit, "role", ROLE_ITEMS[1:], tr("Role"))
    _choice(box, unit, "state", STATE_ITEMS, tr("State"))
    if last:
        box.label(text=tr("No base: it is the last unit"), translate=False)
    else:
        _choice(box, unit, "base_kind", BASE_ITEMS, tr("Base"))
        if unit.base_kind == BASE_ELEVATION:
            box.prop(unit, "base_elevation", text=tr("Base elevation (m)"), translate=False)
        else:
            box.prop_search(unit, "base_dataset", materials, "surfaces", text=tr("Surface"),
                            translate=False)
    if unit.kind == ANTHROPIC:
        box.prop_search(unit, "thickness_dataset", materials, "surfaces",
                        text=tr("Thickness grid"), translate=False)
    if unit.kind == COMPOUND:
        _draw_components(box, unit)
    elif unit.saved and unit.code:
        _draw_parameters(box, unit, unit.code, "")
    else:
        box.label(text=tr("Save the column to declare its parameters"), icon="INFO",
                  translate=False)


def draw_materials(layout: Any, context: Any) -> None:
    """La ventana de Materiales y densidades… (véase el módulo), de lo ya leído."""
    materials = view()
    if materials is None:
        return
    blocked = _write_unavailable()
    if blocked is not None:  # en solo lectura, se ve y no se cambia (RF-011-26)
        note = layout.row()
        note.alert = True
        note.label(text=blocked, icon="LOCKED", translate=False)
    edit = layout.column()
    edit.enabled = blocked is None
    row = edit.row(align=True)
    row.label(text=tr("Anthropic presence: {value}", value=materials.presence),
              translate=False)
    row.operator(SET_PARAMETER, text=tr("Change…"),
                 translate=False).key = res_params.ANTHROPIC_PRESENCE
    edit.label(text=tr("Units, from top to bottom"), translate=False)
    row = edit.row()
    row.template_list(UNITS_LIST, "", materials, "units", materials, "unit_index",
                      rows=UNIT_ROWS)
    side = row.column(align=True)
    for action, icon in (("ADD_UNIT", "ADD"), ("REMOVE_UNIT", "REMOVE"),
                         ("MOVE_UP", "TRIA_UP"), ("MOVE_DOWN", "TRIA_DOWN")):
        side.operator(EDIT_COLUMN, text="", icon=icon).action = action
    count = len(materials.units)
    if count:
        index = min(max(materials.unit_index, 0), count - 1)
        _draw_unit(edit, materials, materials.units[index], index == count - 1)
    else:
        edit.label(text=tr("No unit yet: add the units from top to bottom"), icon="INFO",
                   translate=False)
    edit.operator(SAVE_MATERIALS, text=_label(SAVE_MATERIALS), icon="FILE_TICK",
                  translate=False)


class GEOBLENDER_UL_res_units(bpy.types.UIList):
    """Units of the materials column, from top to bottom"""

    bl_idname = UNITS_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        row = layout.row(align=True)
        row.label(text=item.name or NOT_SHOWN, translate=False)
        shown = language()
        kind = translate(shown, _KIND.get(item.kind, ""))
        if item.kind != COMPOUND and item.role != ROLE_NONE:
            kind = f"{kind} · {translate(shown, _ROLE.get(item.role, ''))}"
        row.label(text=kind, translate=False)


class GEOBLENDER_UL_res_components(bpy.types.UIList):
    """Components of a compound unit"""

    bl_idname = COMPONENTS_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        row = layout.row(align=True)
        row.label(text=item.name or NOT_SHOWN, translate=False)
        role = "" if item.role == ROLE_NONE else translate(language(), _ROLE[item.role])
        row.label(text=role, translate=False)


class GEOBLENDER_PT_res_materials(bpy.types.Panel):
    """Materials column of the project: its units from top to bottom, with their density, swell
    factor and percentages"""

    bl_idname = MATERIALS_PANEL
    bl_label = "Materials and densities"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = MATERIALS_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_materials(self.layout, context)


def install() -> None:
    """Pone la escucha de los indicadores (:func:`on_project_read`; una sola vez)."""
    provenance.add_change_listener(on_project_read)


def uninstall() -> None:
    """Quita lo que puso :func:`install` y olvida las listas de los diálogos."""
    provenance.remove_change_listener(on_project_read)
    forget_choices()

# En orden de registro (las listas, antes de la ventana que las dibuja).
classes: tuple[type, ...] = (GEOBLENDER_UL_res_units, GEOBLENDER_UL_res_components,
                             GEOBLENDER_PT_res_materials)
