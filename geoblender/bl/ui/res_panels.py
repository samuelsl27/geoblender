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
D-35).

**La ventana de la cubicación** (T25; RF-011-23, RF-011-24; plan §5.5, D-27, D-29, D-37;
RNF-011-05): ``GEOBLENDER_PT_res_volumetrics`` es N ▸ Proyecto ▸ Cubicaciones (plegado al
empezar, tras Elemento activo e Inventario) y, con ``wm.call_panel``, la misma tabla en una
ventana (la que abren las órdenes al terminar, «Ratios…» y ``geoblender.res_show_volumetrics``).
Dibuja (:func:`draw_volumetrics`) las cubicaciones de la versión activa
(``GEOBLENDER_UL_res_cubications``: su nombre, su revisión como se lee, «V01.r1 en curso» o «V01
vigente: r1», :func:`status_text`, y «obsoleta», en alerta) y, de la elegida, su revisión, cada
operación (``res.volume`` y ``res.tonnage``, D-16) con sus marcas de hoy y el factor combinado;
los filtros de su tabla (todos los datos o las relaciones; el dominio, el banco y la unidad, con
«cualquiera» y «el total», el de por defecto); la tabla (``GEOBLENDER_UL_res_rows``: un valor por
fila con su ámbito, su unidad, [CAL] y, si tiene marcas, en alerta; como mucho
:data:`ROWS_SHOWN`, «… y n más: afine el filtro»); la fila elegida con sus marcas («depende de
una hipótesis», «depende de un valor sin confirmar», «obsoleta») y sus notas («sin densidad»…);
los parámetros que leyó con su valor, su tipo y su ámbito, y «Exportar CSV…»
(``geoblender.res_export_csv``). En solo lectura y con la versión SUPERADO se ve igual: solo lee.

**Cuándo se lee** (nunca al dibujar): la lista, con :func:`fill_volumetrics` (al abrir los
diálogos de los momentos, «Ratios…», la ventana) y la tabla de la elegida al elegirla
(:func:`show_cubication`, o pulsarla en la lista: :func:`cubication_chosen`), tal como la escribe
el CSV (:func:`read_table`: ``reserves.export``, en el idioma de Geoblender), presentada en
tuplas de textos; cambiar un filtro solo vuelve a filtrar lo leído (:func:`fill_rows`). Cuando
el proyecto cambia (la escucha de los indicadores), cambian la versión activa o el idioma, o una
orden acaba de cubicar (:func:`show_later`: la última llamada de su modal no lee la tabla,
RNF-011-04), lo leído es viejo y el dibujo pide un temporizador de un disparo
(:func:`volumetrics_tick`) que lo vuelve a leer.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import bpy

from ...core.catalog.search import path_text
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, language, tr, translate
from ...core.params import VERSION_SCOPE, ParameterStore
from ...core.params import definition as param_definition
from ...core.params.model import ParamKind, format_value
from ...core.params.store import shown_value
from ...core.provenance.messages import render as render_core
from ...core.versions.model import EDITABLE
from ...gis import provenance as gis_provenance
from ...gis import store as gis_store
from ...reserves import materials as res_materials
from ...reserves import messages as res_messages
from ...reserves import params as res_params
from ...reserves import surfaces as res_surfaces
from ...reserves import table as res_table
from .. import compat
from ..props.res import (
    BASE_ELEVATION,
    BASE_ITEMS,
    BASE_SURFACE,
    FILTER_TOTAL,
    KIND_ITEMS,
    QUANTITIES_ALL,
    QUANTITIES_RATIOS,
    QUANTITY_ITEMS,
    ROLE_ITEMS,
    ROLE_NONE,
    STATE_ITEMS,
    WINDOW_MANAGER_PROPERTY,
)
from ..scene import project_session
from ..scene import versions as scene_versions
from . import core_panel, labels, provenance
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
    if _VOLUMETRICS.key is not None and _VOLUMETRICS.key[0] == project.uid:
        _VOLUMETRICS.generation += 1  # la ventana de la cubicación lo leerá al dibujarse
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


# --- La ventana de la cubicación (T24, T25; RF-011-18, RF-011-19, RF-011-23, RF-011-24) ---------

CUBICATIONS_LIST = "GEOBLENDER_UL_res_cubications"
ROWS_LIST = "GEOBLENDER_UL_res_rows"
VOLUMETRICS_LABEL = "Cubications"  # msgid del título
VOLUMETRICS_ORDER = 3  # tras Elemento activo (1) e Inventario (2) de la 010
VOLUMETRICS_UNITS = 36  # el ancho de la ventana (como la de los materiales)
VOLUMETRICS_WIDTH_PX = VOLUMETRICS_UNITS * compat.UI_UNIT_PX
CUBICATION_ROWS = 3
TABLE_ROWS = 8
ROWS_SHOWN = 500
"""Las filas de la tabla que se presentan como mucho (como el inventario de la 010, D-7: «… y
5 500 más: afine el filtro»): así abrir y filtrar una tabla de 6 000 filas no pasa de 0,5 s y
cada redibujo, de 5 ms (RNF-011-05)."""
ROW_NAME_FACTOR = 0.62
RETRY_S = 0.5
"""Cuándo se vuelve a intentar leer las cubicaciones si esta sesión está escribiendo."""
SHOW_VOLUMETRICS = "geoblender.res_show_volumetrics"
EXPORT_CSV = "geoblender.res_export_csv"
BETWEEN_COMMAND = "geoblender.res_compute_volume_between_surfaces"
FILTER_ANY = "ANY"
FILTER_ALL = "ALL"
FILTER_OUTSIDE = "OUTSIDE"
_OPEN, _FROZEN, _CLOSED = "open", "frozen", "closed"  # core.versions.model.RevisionState
_RATIOS = frozenset(res_table.RATIO_QUANTITIES)
_FACTOR = ("grid_scale_factor", "ground_effect_pct")  # el factor combinado (D-34)

type ShownRow = tuple[str, Any, str | None, str, str, str, str, str, str]
"""Una fila de la tabla ya presentada: su dominio, su rodaja (``(z0, z1)`` o ``None``) y su
unidad tal como se guardan (lo que filtra), su dato, su ámbito, el nombre de su dato, su valor
con su unidad, sus marcas y sus notas (textos: el GC no sigue estas tuplas, ``docs/trampas.md``
§2)."""


@dataclass(frozen=True)
class CubicationTable:
    """La tabla de una cubicación ya leída y presentada en el idioma de Geoblender (T25): de qué
    proyecto, versión e idioma es, su nombre, sus filas (:data:`ShownRow`), lo que se puede
    elegir en sus filtros (``reserves.table.Choices``), el nombre de cada unidad por su código,
    lo que dice de ella (su revisión, cada operación con sus marcas y el factor combinado:
    ``(texto, alerta)``) y los parámetros que leyó."""

    key: tuple[str, str, str]
    name: str
    rows: tuple[ShownRow, ...]
    choices: res_table.Choices
    units: dict[str, str]
    lines: tuple[tuple[str, bool], ...]
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class RowFilter:
    """Lo que piden los filtros de la tabla: un dominio, una rodaja y una unidad tal como se
    guardan (``"*"``, ``None``: el total; ``reserves.table.ANY``: cualquiera) y si solo las
    relaciones (D-35)."""

    domain: Any = res_table.ANY
    bench: Any = res_table.ANY
    unit: Any = res_table.ANY
    ratios: bool = False

    def admits(self, row: ShownRow) -> bool:
        """Si la fila ``row`` pasa el filtro."""
        if self.ratios and row[3] not in _RATIOS:
            return False
        return all(wanted is res_table.ANY or found == wanted for wanted, found in (
            (self.domain, row[0]), (self.bench, row[1]), (self.unit, row[2])))


@dataclass
class _Volumetrics:
    """Lo leído para la ventana de la cubicación: de qué proyecto, versión activa e idioma es la
    lista (``key``); cuántas veces ha cambiado el proyecto (``generation``, la sube la escucha
    de los indicadores) y en cuál se leyeron la lista (``listed``) y la tabla de la elegida
    (``table_for``: de qué proyecto, versión e idioma, cuál y en qué cambio del proyecto; también
    si no se pudo leer): si no es lo de hoy, el panel pide leerlo otra vez en un temporizador;
    si la siguiente lectura deja los filtros por
    defecto (``reset``), la tabla de la elegida, los elementos de cada filtro (listas vivas del
    módulo: Blender guarda punteros a sus cadenas) con lo que guarda cada uno, y si las
    escrituras en la vista no deben volver a leer ni filtrar (``quiet``)."""

    key: tuple[str, str, str] | None = None
    generation: int = 0
    listed: int = -1
    table_for: tuple[str, str, str, str, int] | None = None
    reset: bool = False
    table: CubicationTable | None = None
    items: dict[str, list[tuple[str, str, str, int]]] = field(default_factory=dict)
    values: dict[str, dict[str, Any]] = field(default_factory=dict)
    quiet: int = 0


_VOLUMETRICS = _Volumetrics()
_FILTERS = ("domain", "bench", "unit")


@contextmanager
def _quiet() -> Iterator[None]:
    """Mientras dura, cambiar la elegida o los filtros en la vista no lee ni filtra nada."""
    _VOLUMETRICS.quiet += 1
    try:
        yield
    finally:
        _VOLUMETRICS.quiet -= 1


def _key(project: Any, version_uid: str | None) -> tuple[str, str, str]:
    return (project.uid, version_uid or "", language())


def _stamp(name: str) -> tuple[str, str, str, str, int] | None:
    """Lo que dice de qué es la tabla de ``name`` leída ahora (``_Volumetrics.table_for``): el
    proyecto de la sesión, su versión activa, el idioma, ``name`` y el cambio del proyecto."""
    project = project_session.current()
    if project is None:
        return None
    return (*_key(project, scene_versions.active_version()), name, _VOLUMETRICS.generation)


def _editable(version_uid: str) -> bool:
    """Si la versión ``version_uid`` de las leídas es BORRADOR o VIGENTE (sin leerla, sí)."""
    found = next((item for item in scene_versions.versions() if item.uid == version_uid), None)
    return found is None or found.status in EDITABLE


def status_text(item: Any, *, editable: bool) -> str:
    """La revisión de una cubicación (``reserves.store.Cubication``) como se lee (RF-009-20):
    «V01.r2 en curso» (con «· vigente: r1» si la versión tiene una congelada), «V01 vigente:
    r1» (de una versión SUPERADO o DESCARTADO, «V01 congelada: r1») o «V01 cerrada (r2)»."""
    code, _dot, number = item.revision.partition(".")
    if item.revision_state == _OPEN:
        shown = tr("{revision} in progress", revision=item.revision)
        if not item.current:
            return shown
        current = tr("current: {revision}", revision=item.current)
        return f"{shown} · {current}"
    if item.revision_state == _FROZEN and editable:
        return tr("{version} current: {revision}", version=code, revision=number)
    if item.revision_state == _FROZEN:
        return tr("{version} frozen: {revision}", version=code, revision=number)
    if item.revision_state == _CLOSED:
        return tr("{version} closed ({revision})", version=code, revision=number)
    return item.revision or NOT_SHOWN


def stale_text() -> str:
    """«obsoleta», la marca de una cubicación obsoleta (RF-008-31), en el idioma de Geoblender."""
    return render_core("core.mark_stale", language=language())


def fill_volumetrics(project: Any, version_uid: str | None) -> tuple[Any, ...]:
    """Vuelve a leer de ``project`` las cubicaciones de la versión activa ``version_uid``
    (``reserves.store.cubications``; sin versión, ninguna) y las deja en la vista
    (``cubications``: su nombre, si reparte por unidades, si tiene toneladas, su revisión como
    se lee, :func:`status_text`, y si está obsoleta); la elegida sigue elegida si sigue en la
    lista y, si no, ninguna (y su tabla se olvida). No lee ninguna tabla. Devuelve las leídas.
    Si no se puede leer, el error sigue y la vista queda como estaba."""
    from ...reserves import store  # al usarlo: habilitar no lo carga

    found = () if not version_uid else store.cubications(project, version=version_uid)
    shown = view()
    if shown is None:
        return found
    editable = _editable(version_uid or "")
    with _quiet():
        shown.cubications.clear()
        for item in found:
            row = shown.cubications.add()
            row.name, row.units, row.tonnage = item.name, item.units, item.tonnage is not None
            row.revision, row.stale = item.revision, item.stale
            row.status = status_text(item, editable=editable)
        names = [item.name for item in found]
        if shown.cubication in names:
            shown.cubication_index = names.index(shown.cubication)
        else:
            shown.cubication, shown.cubication_index = "", -1
    if not shown.cubication:
        _clear_table(shown)
    _VOLUMETRICS.key, _VOLUMETRICS.listed = _key(project, version_uid), _VOLUMETRICS.generation
    return found


def _bench_text(bench: tuple[float | None, float | None]) -> str:
    """Una rodaja como se lee: «[100,5; 101,5) m», «por debajo de 100 m», «por encima de
    130 m» (las cotas, sin separador de miles)."""
    low, high = bench
    shown = language()
    if low is None:
        return tr("below {elevation} m", elevation=format_value(high, shown, grouped=False))
    if high is None:
        return tr("above {elevation} m", elevation=format_value(low, shown, grouped=False))
    return (f"[{format_value(low, shown, grouped=False)}; "
            f"{format_value(high, shown, grouped=False)}) m")


def _domain_text(domain: str) -> str:
    return tr("Outside the domains") if domain == res_table.OUTSIDE_DOMAINS else domain


def _note_text(codes: tuple[str, ...], shown: str) -> str:
    return " · ".join(res_messages.render(code, language=shown)
                      if code in res_messages.MESSAGES else code for code in codes)


def _value_text(row: Any, shown: str) -> str:
    """El valor de una fila con su unidad («20 m³», «1,5 m³/m³»; sin valor, «sin valor» y su
    nota)."""
    text = shown_value(row.value, row.unit_code, shown)
    if row.value is None and row.notes:
        text = f"{text} ({_note_text(row.notes, shown)})"
    return text


def _status_line(name: str, export: Any) -> tuple[str, bool]:
    """La primera línea de la tabla: el nombre de la cubicación con su revisión como se lee y,
    si está obsoleta, «obsoleta» (en alerta)."""
    shown = view()
    listed = None if shown is None else next(
        (item for item in shown.cubications if item.name == name), None)
    status = export.header.revision if listed is None else listed.status
    text = f"{name} · {status}" if status else name
    if listed is not None and listed.stale:
        return f"{text} · {stale_text()}", True
    return text, False


def _parameter_line(used: Any, shown: str) -> str:
    """Un parámetro que leyó la cubicación: «Espesor mínimo: 0 m [ADO] sin confirmar ·
    proyecto»."""
    value = f"{shown_value(used.value, used.unit, shown)} {provenance.badge(used.kind)}"
    if used.unconfirmed:
        value = f"{value} {tr('unconfirmed')}"
    return tr("{name}: {value} · {scope}", name=used.label, value=value, scope=used.scope)


def read_table(project: Any, version_uid: str, name: str) -> CubicationTable:
    """Lee de ``project`` la cubicación ``name`` de la versión ``version_uid`` tal como la
    escribe el CSV (``reserves.export.cubication_export``, en el idioma de Geoblender: sus
    marcas y sus parámetros) y la presenta (``reserves.export.shown_rows``: sin repetir los m³
    in situ en la tabla de toneladas). Los errores siguen (``res.cubication_unknown``…)."""
    from ...reserves import export as res_export  # al usarlo: habilitar no lo carga

    shown = language()
    found = res_export.cubication_export(project, name, version=version_uid, language=shown)
    items = res_export.shown_rows(found)
    units: dict[str, str] = {}
    parts: dict[tuple[str, str], str] = {}
    for item in items:
        row = item.row
        if row.unit is not None and row.component is None:
            units.setdefault(row.unit, item.name or row.unit)
        elif row.unit is not None and row.component is not None:
            parts.setdefault((row.unit, row.component), item.name or row.component)
    labels_of: dict[str, str] = {}
    rows: list[ShownRow] = []
    factor: dict[str, str] = {}
    for item in items:
        row = item.row
        bench = row.bench
        where: list[str] = []
        if row.domain != res_table.ALL_DOMAINS:
            where.append(_domain_text(row.domain))
        if bench is not None:
            where.append(_bench_text(bench))
        if row.unit is not None:
            where.append(units.get(row.unit, row.unit))
            if row.component is not None:
                where.append(parts.get((row.unit, row.component), row.component))
        label = labels_of.get(row.quantity)
        if label is None:
            quantity = res_table.QUANTITIES.get(row.quantity)
            label = labels_of[row.quantity] = (translate(shown, quantity.label) if quantity
                                               is not None and quantity.label else row.quantity)
        value = _value_text(row, shown)
        if (row.quantity in _FACTOR and not where):
            factor.setdefault(row.quantity, tr("{name}: {value}", name=label, value=value))
        rows.append((row.domain, bench, row.unit, row.quantity, " · ".join(where), label, value,
                     " · ".join(item.marks), _note_text(row.notes, shown)))
    lines = [_status_line(name, found)]
    for operation in found.header.operations:
        text = tr("{operation} ({revision})", operation=operation.label,
                  revision=operation.revision)
        if operation.marks:
            text = " · ".join((text, *operation.marks))
        lines.append((text, bool(operation.marks)))
    lines += [(factor[quantity], False) for quantity in _FACTOR if quantity in factor]
    return CubicationTable(
        _key(project, version_uid), name, tuple(rows),
        res_table.choices(item.row for item in items), units, tuple(lines),
        tuple(_parameter_line(used, shown) for used in found.header.parameters))


def _filter_items(table: CubicationTable) -> None:
    """Los elementos de los filtros de ``table`` (con lo que guarda cada uno), en las listas
    vivas del módulo: «cualquiera» (0), «el total» (:data:`bl.props.res.FILTER_TOTAL`) y cada
    dominio («Fuera de los dominios», el último), rodaja (de abajo arriba) y unidad (en el orden
    de la columna)."""
    choices = table.choices
    domains = [value for value in choices.domains
               if value not in (res_table.ALL_DOMAINS, res_table.OUTSIDE_DOMAINS)]
    found = {
        "domain": [(FILTER_ANY, tr("Any domain"), res_table.ANY),
                   (FILTER_ALL, tr("All the domains (total)"), res_table.ALL_DOMAINS),
                   *((f"D{index}", value, value) for index, value in enumerate(domains)),
                   *(((FILTER_OUTSIDE, tr("Outside the domains"), res_table.OUTSIDE_DOMAINS),)
                     if res_table.OUTSIDE_DOMAINS in choices.domains else ())],
        "bench": [(FILTER_ANY, tr("Any bench"), res_table.ANY),
                  (FILTER_ALL, tr("All the benches (total)"), None),
                  *((f"B{index}", _bench_text(bench), bench)
                    for index, bench in enumerate(choices.benches))],
        "unit": [(FILTER_ANY, tr("Any unit"), res_table.ANY),
                 (FILTER_ALL, tr("All the units (total)"), None),
                 *((f"U{index}", table.units.get(code, code), code)
                   for index, code in enumerate(choices.units))],
    }
    for name, listed in found.items():
        items = _VOLUMETRICS.items.setdefault(name, [])
        items[:] = [(identifier, text, "", number)
                    for number, (identifier, text, _value) in enumerate(listed)]
        _VOLUMETRICS.values[name] = {identifier: value for identifier, _t, value in listed}


def _no_filter_items(name: str) -> list[tuple[str, str, str, int]]:
    items = _VOLUMETRICS.items.setdefault(name, [])
    if not items:
        items.append((FILTER_ALL, NOT_SHOWN, "", FILTER_TOTAL))
    return items


def domain_filter_items(_view: Any, _context: Any) -> list[tuple[str, str, str, int]]:
    """Los elementos del filtro de dominio de la tabla elegida (una lista viva del módulo; no
    lee nada)."""
    return _no_filter_items("domain")


def bench_filter_items(_view: Any, _context: Any) -> list[tuple[str, str, str, int]]:
    """Los elementos del filtro de banco (rodaja) de la tabla elegida."""
    return _no_filter_items("bench")


def unit_filter_items(_view: Any, _context: Any) -> list[tuple[str, str, str, int]]:
    """Los elementos del filtro de unidad de la tabla elegida."""
    return _no_filter_items("unit")


def current_filter(shown: Any) -> RowFilter:
    """Lo que piden los filtros de la vista ``shown`` (lo elegido que ya no está: el total)."""
    wanted = {}
    for name in _FILTERS:
        values = _VOLUMETRICS.values.get(name, {})
        identifier = str(getattr(shown, f"{name}_filter", "") or "")
        wanted[name] = values.get(identifier, values.get(FILTER_ALL, (
            res_table.ALL_DOMAINS if name == "domain" else None)))
    return RowFilter(wanted["domain"], wanted["bench"], wanted["unit"],
                     shown.quantities == QUANTITIES_RATIOS)


def _choose_filters(shown: Any, wanted: RowFilter) -> None:
    """Elige en los filtros de la vista lo que pide ``wanted`` (lo que no está: el total)."""
    with _quiet():
        for name, value in zip(_FILTERS, (wanted.domain, wanted.bench, wanted.unit),
                               strict=True):
            identifier = next((key for key, found in _VOLUMETRICS.values[name].items()
                               if found == value and (found is res_table.ANY) == (
                                   value is res_table.ANY)), FILTER_ALL)
            setattr(shown, f"{name}_filter", identifier)


def fill_rows(table: CubicationTable | None, filters: RowFilter) -> int:
    """Presenta en la vista las filas de ``table`` que pasan ``filters`` (como mucho
    :data:`ROWS_SHOWN`, con cuántas más hay), sin leer el proyecto (RNF-011-05). Devuelve
    cuántas pasan."""
    shown = view()
    if shown is None:
        return 0
    rows = shown.rows
    rows.clear()
    if table is None:
        shown.rows_more, shown.rows_of = 0, ""
        return 0
    found = [row for row in table.rows if filters.admits(row)]
    badge = provenance.badge(ParamKind.CALCULADO)
    for values in found[:ROWS_SHOWN]:
        item = rows.add()
        (_d, _b, _u, item.quantity, item.scope, item.name, item.value, item.marks,
         item.notes) = values
        item.badge = badge
    shown.rows_more = max(0, len(found) - ROWS_SHOWN)
    shown.row_index = 0
    shown.rows_of = table.name
    return len(found)


def _put_lines(target: Any, lines: Any) -> None:
    target.clear()
    for text, alert in lines:
        line = target.add()
        line.name, line.alert = text, alert


def _clear_table(shown: Any) -> None:
    _VOLUMETRICS.table, _VOLUMETRICS.table_for = None, None
    shown.lines.clear()
    shown.parameters.clear()
    fill_rows(None, RowFilter())


def _show(project: Any, version_uid: str, name: str, *, quantities: str,
          keep: bool) -> None:
    """Lee la tabla de ``name`` (:func:`read_table`) y la presenta: lo que dice de ella, sus
    parámetros, sus filtros (los de antes, con ``keep``, si siguen; si no, el total o, con las
    relaciones, cualquier unidad) y sus filas. Los errores siguen."""
    shown = view()
    if shown is None:  # inalcanzable con la extensión registrada
        return
    before = current_filter(shown) if keep and _VOLUMETRICS.values else None
    stamp = (*_key(project, version_uid), name, _VOLUMETRICS.generation)
    table = read_table(project, version_uid, name)
    _VOLUMETRICS.table, _VOLUMETRICS.table_for, _VOLUMETRICS.reset = table, stamp, False
    _filter_items(table)
    ratios = quantities == QUANTITIES_RATIOS
    with _quiet():
        shown.quantities = quantities
    _choose_filters(shown, before if before is not None else RowFilter(
        res_table.ALL_DOMAINS, None, res_table.ANY if ratios else None, ratios))
    _put_lines(shown.lines, table.lines)
    _put_lines(shown.parameters, ((text, False) for text in table.parameters))
    fill_rows(table, current_filter(shown))


def _failed(shown: Any, name: str, error: Exception) -> None:
    """La tabla de ``name`` no se pudo leer: lo dice en su lugar (y la traza, al registro); no
    se vuelve a intentar hasta que el proyecto cambie o se elija otra vez."""
    LOGGER.warning("No se pudo leer la cubicación «%s»", name, exc_info=error)
    _clear_table(shown)
    _put_lines(shown.lines, ((str(error), True),))
    shown.rows_of = name
    _VOLUMETRICS.table_for, _VOLUMETRICS.reset = _stamp(name), False


def _select(shown: Any, name: str) -> None:
    """Deja elegida ``name`` en la vista (y en la lista, si está), sin leer nada."""
    names = [item.name for item in shown.cubications]
    with _quiet():
        shown.cubication = name
        shown.cubication_index = names.index(name) if name in names else -1


def show_cubication(name: str, *, quantities: str = QUANTITIES_ALL) -> None:
    """Deja elegida en la vista la cubicación ``name`` (vacío: ninguna) de la versión activa con
    el filtro de datos ``quantities`` (``bl.props.res.QUANTITY_ITEMS``: todos o las relaciones,
    D-35) y lee su tabla (:func:`read_table`), con los filtros en el total (con las relaciones,
    cualquier unidad). Si no se puede leer, el error sigue."""
    shown = view()
    if shown is None:  # inalcanzable con la extensión registrada
        return
    _select(shown, name)
    project, version_uid = project_session.current(), scene_versions.active_version()
    if not name or project is None or version_uid is None:
        _clear_table(shown)
        _VOLUMETRICS.reset = False
        return
    _show(project, version_uid, name, quantities=quantities, keep=False)


def show_later(name: str) -> None:
    """Deja elegida ``name`` (la que acaba de cubicar una orden) sin leer nada: la ventana la
    lee al dibujarse, en un temporizador (:func:`volumetrics_tick`), con los filtros en el
    total; así la última llamada del modal no lee la tabla (RNF-011-04)."""
    shown = view()
    if shown is None:  # inalcanzable con la extensión registrada
        return
    _select(shown, name)
    with _quiet():
        shown.quantities = QUANTITIES_ALL
    _VOLUMETRICS.reset = True


def cubication_chosen() -> None:
    """Se eligió otra cubicación en la lista del panel (``cubication_index``): se lee su tabla
    (una lectura al pulsarla, no al dibujar) y se presentan sus totales (todos los datos, los
    filtros en el total); si no se puede, lo dice en su lugar."""
    shown = view()
    if _VOLUMETRICS.quiet or shown is None:
        return
    index = shown.cubication_index
    name = shown.cubications[index].name if 0 <= index < len(shown.cubications) else ""
    with _quiet():
        shown.cubication = name
    project, version_uid = project_session.current(), scene_versions.active_version()
    if not name or project is None or version_uid is None:
        _clear_table(shown)
        return
    try:
        _show(project, version_uid, name, quantities=QUANTITIES_ALL, keep=False)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
        _failed(shown, name, exc)


def rows_filtered() -> None:
    """Cambió un filtro de la tabla: vuelve a filtrar lo leído, sin leer el proyecto."""
    shown = view()
    if _VOLUMETRICS.quiet or shown is None:
        return
    fill_rows(_VOLUMETRICS.table, current_filter(shown))


def volumetrics_is_old(project: Any, version_uid: str | None) -> bool:
    """Si lo que enseña la ventana puede ser viejo: la lista, leída de otro proyecto, de otra
    versión activa o en otro idioma, o antes de que el proyecto cambiara; la tabla de la
    elegida, de otra o de antes (o una orden la acaba de cubicar, :func:`show_later`). No lee
    nada: lo usa el dibujo."""
    state = _VOLUMETRICS
    if state.reset or state.key != _key(project, version_uid) or state.listed != state.generation:
        return True
    shown = view()
    chosen = "" if shown is None else str(shown.cubication)
    return bool(chosen) and state.table_for != (*_key(project, version_uid), chosen,
                                                state.generation)


def refresh_volumetrics(project: Any, version_uid: str | None) -> None:
    """Vuelve a leer la lista (:func:`fill_volumetrics`) y la tabla de la elegida, con sus
    filtros (por defecto, tras :func:`show_later`). Los errores de la lista siguen; los de la
    tabla, en su lugar."""
    shown = view()
    reset = _VOLUMETRICS.reset
    fill_volumetrics(project, version_uid)
    if shown is None or not shown.cubication or not version_uid:
        _VOLUMETRICS.reset = False
        return
    try:
        _show(project, version_uid, shown.cubication, quantities=str(shown.quantities),
              keep=not reset)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
        _failed(shown, shown.cubication, exc)


def volumetrics_tick() -> float | None:
    """El temporizador de un disparo que pide la ventana al dibujarse con lo leído viejo: lee
    otra vez (:func:`refresh_volumetrics`) y la redibuja. Mientras esta sesión escribe en el
    proyecto, espera; si no se puede leer, lo deja en el registro técnico (y no lo vuelve a
    intentar hasta que algo cambie)."""
    project = project_session.current()
    if project is None:
        _VOLUMETRICS.key, _VOLUMETRICS.table = None, None
        return None
    if getattr(project, "writing", False):
        return RETRY_S
    version_uid = scene_versions.active_version()
    try:
        refresh_volumetrics(project, version_uid)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.warning("No se pudieron leer las cubicaciones de la versión activa", exc_info=True)
        state, shown = _VOLUMETRICS, view()
        state.key, state.listed, state.reset = _key(project, version_uid), state.generation, False
        state.table_for = _stamp("" if shown is None else str(shown.cubication))
    _redraw()
    return None


def _request_volumetrics() -> None:
    if not bpy.app.timers.is_registered(volumetrics_tick):
        bpy.app.timers.register(volumetrics_tick, first_interval=0.0)


def _redraw() -> None:
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()) or ():
        for area in window.screen.areas:
            area.tag_redraw()


def forget_volumetrics() -> None:
    """Olvida lo leído para la ventana (al desregistrar) y su temporizador."""
    if bpy.app.timers.is_registered(volumetrics_tick):
        bpy.app.timers.unregister(volumetrics_tick)
    state = _VOLUMETRICS
    state.key, state.table, state.table_for, state.reset = None, None, None, False
    state.listed = -1
    state.items.clear()
    state.values.clear()


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


# --- La ventana de la cubicación: dibujo (T25) --------------------------------------------------


def _lines(layout: Any, shown: str, width: float, *, icon: str = "NONE",
           alert: bool = False) -> None:
    """``shown`` (ya traducido) en las líneas que caben en ``width`` (en alerta, si
    ``alert``)."""
    column = layout.column(align=True)
    column.alert = alert
    labels.draw_wrapped(column, shown, width, icon=icon)


def _draw_chosen_row(layout: Any, row: Any, width: float) -> None:
    """La fila elegida de la tabla: su ámbito, su dato con su tipo y su valor, sus marcas (en
    alerta) y sus notas."""
    box = layout.box()
    if row.scope:
        _lines(box, row.scope, width)
    _lines(box, tr("{name}: {value}", name=f"{row.badge} {row.name}", value=row.value), width)
    if row.marks:
        _lines(box, row.marks, width, alert=True)
    if row.notes:
        _lines(box, row.notes, width, icon="INFO")


def draw_volumetrics(layout: Any, context: Any, *, popover: bool = False) -> None:
    """N ▸ Proyecto ▸ Cubicaciones y su ventana (``popover``), de lo ya leído (RF-011-23): las
    cubicaciones de la versión activa (su revisión y «obsoleta»), lo que dice de la elegida (su
    revisión, cada operación con sus marcas, el factor combinado), los filtros de su tabla
    (los datos —todos o las relaciones—, el dominio, el banco y la unidad), la tabla, la fila
    elegida, los parámetros que leyó y «Exportar CSV…» (en el panel, también la ventana). No
    lee el proyecto: si lo leído es viejo, pide leerlo (:func:`volumetrics_tick`)."""
    width = (labels.dialog_width(VOLUMETRICS_WIDTH_PX) if popover
             else labels.sidebar_width(context))
    if popover:
        layout.label(text=tr("Cubications"), translate=False)
    shown = view()
    project = project_session.current()
    if shown is None or project is None:
        _lines(layout, tr("No project is open"), width, icon="INFO")
        return
    version_uid = scene_versions.active_version()
    if version_uid is None:
        _lines(layout, tr("Choose the active version first: Project ▸ Versions ▸ Active "
                          "version"), width, icon="INFO")
        return
    if volumetrics_is_old(project, version_uid):
        _request_volumetrics()
    key = _VOLUMETRICS.key
    if key is None or key[:2] != (project.uid, version_uid):
        _lines(layout, tr("Reading the cubications…"), width, icon="TIME")
        return
    if not len(shown.cubications):
        version = scene_versions.active()
        _lines(layout, tr("There are no cubications in {version}: compute one first ({path})",
                          version="" if version is None else version.code,
                          path=path_text(catalog(), BETWEEN_COMMAND, language())),
               width, icon="INFO")
        return
    layout.template_list(CUBICATIONS_LIST, "", shown, "cubications", shown, "cubication_index",
                         rows=CUBICATION_ROWS)
    if not shown.cubication:
        _lines(layout, tr("Choose a cubication in the list"), width, icon="INFO")
        return
    if shown.rows_of != shown.cubication:
        _lines(layout, tr("Reading «{name}»…", name=shown.cubication), width, icon="TIME")
        return
    box = layout.box()
    for line in shown.lines:
        _lines(box, line.name, width, alert=line.alert)
    filters = layout.column(align=True)
    _choice(filters, shown, "quantities", QUANTITY_ITEMS, tr("Data"))
    filters.prop(shown, "domain_filter", text=tr("Domain"), translate=False)
    filters.prop(shown, "bench_filter", text=tr("Bench"), translate=False)
    filters.prop(shown, "unit_filter", text=tr("Unit"), translate=False)
    if not len(shown.rows):
        _lines(layout, tr("No row matches the filters"), width, icon="INFO")
    else:
        layout.template_list(ROWS_LIST, "", shown, "rows", shown, "row_index", rows=TABLE_ROWS)
        if shown.rows_more:
            _lines(layout, tr("… and {count} more: refine the filter",
                              count=format_number(shown.rows_more, 0)), width)
        index = min(max(shown.row_index, 0), len(shown.rows) - 1)
        _draw_chosen_row(layout, shown.rows[index], width)
    if len(shown.parameters):
        layout.label(text=tr("Parameters used"), translate=False)
        column = layout.column(align=True)
        for line in shown.parameters:
            _lines(column, line.name, width)
    row = layout.row(align=True)
    button = row.operator(EXPORT_CSV, text=_label(EXPORT_CSV), icon="EXPORT", translate=False)
    button.cubication = shown.cubication
    if not popover:
        button = row.operator(SHOW_VOLUMETRICS, text="", icon="WINDOW_NEW")
        button.cubication = shown.cubication


class GEOBLENDER_UL_res_cubications(bpy.types.UIList):
    """Cubications of the active version, with their revision"""

    bl_idname = CUBICATIONS_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        row = layout.row(align=True)
        row.label(text=item.name, translate=False)
        row.label(text=item.status, translate=False)
        if item.stale:
            mark = row.row(align=True)
            mark.alert = True
            mark.label(text=stale_text(), icon="ERROR", translate=False)


class GEOBLENDER_UL_res_rows(bpy.types.UIList):
    """Rows of the table of the chosen cubication: one value each, with its unit, its type and
    its marks"""

    bl_idname = ROWS_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        name = f"{item.scope} · {item.name}" if item.scope else item.name
        value = f"{item.value} {item.badge}"
        split = layout.split(factor=ROW_NAME_FACTOR, align=True)
        split.label(text=name, translate=False)
        cell = split.row(align=True)
        cell.alignment = "RIGHT"
        cell.alert = bool(item.marks)
        cell.label(text=value, icon="ERROR" if item.marks else "NONE", translate=False)


class GEOBLENDER_PT_res_volumetrics(bpy.types.Panel):
    """Cubications of the active version: each one with its revision and its table, filtered by
    domain, bench and unit, with its marks"""

    bl_idname = VOLUMETRICS_PANEL
    bl_label = VOLUMETRICS_LABEL
    bl_category = core_panel.PANEL_LABEL
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_order = VOLUMETRICS_ORDER
    bl_options = {"DEFAULT_CLOSED"}
    bl_ui_units_x = VOLUMETRICS_UNITS  # su ancho como ventana (wm.call_panel)

    @classmethod
    def poll(cls, _context: Any) -> bool:
        return project_session.current() is not None

    def draw(self, context: Any) -> None:
        draw_volumetrics(self.layout, context, popover=bool(getattr(self, "is_popover", False)))


def localize() -> None:
    """La pestaña y el título de N ▸ Proyecto ▸ Cubicaciones en el idioma de la interfaz (antes
    de registrar)."""
    GEOBLENDER_PT_res_volumetrics.bl_category = tr("Project")
    GEOBLENDER_PT_res_volumetrics.bl_label = tr("Cubications")


def install() -> None:
    """Pone la escucha de los indicadores (:func:`on_project_read`; una sola vez). Otra
    versión activa no necesita escucha: la ventana de la cubicación la ve en su dibujo
    (:func:`volumetrics_is_old`), y un cambio de estado de una versión cambia el proyecto."""
    provenance.add_change_listener(on_project_read)


def uninstall() -> None:
    """Quita lo que puso :func:`install` y olvida las listas de los diálogos y lo leído para la
    ventana de la cubicación (con su temporizador)."""
    provenance.remove_change_listener(on_project_read)
    forget_choices()
    forget_volumetrics()

# En orden de registro (las listas, antes de la ventana que las dibuja).
classes: tuple[type, ...] = (GEOBLENDER_UL_res_units, GEOBLENDER_UL_res_components,
                             GEOBLENDER_PT_res_materials, GEOBLENDER_UL_res_cubications,
                             GEOBLENDER_UL_res_rows, GEOBLENDER_PT_res_volumetrics)
