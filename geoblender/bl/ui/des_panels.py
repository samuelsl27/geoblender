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
construir la vista previa de la Vista 3D, y lo vacía al quitarla; la barra N «Diseño» lo enseña
mientras lo hay.

**La barra N «Diseño»** (T27; HU-013-6; RF-013-32, RF-013-06, RF-010-06): el panel
``GEOBLENDER_PT_des_design`` (de la Vista 3D) enseña, del objeto ``DESIGN`` activo (una envolvente,
una superficie de diseño o una rejilla de cotas de berma cargada en la vista por
``bl.scene.des_views``), lo que dice de él el proyecto (:func:`item_lines`; todo lo da el proyecto, nada
se calcula aquí): su estado, **al día u obsoleto con su causa** (``core.provenance.stale``); en alerta,
la marca «búsqueda de intocables pendiente» con el sector, si un sector que tocó su dominio de trabajo
ya no tiene la búsqueda vigente (``design.sectors.pending_marks``, RF-013-06; una fila por sector
pendiente, y otra vez como primeras filas del apartado «Cifras», junto a ellas: es del estado de ahora
y no del cálculo, no se escribe en el proyecto y el informe y las cifras guardados no la llevan); los
ajustes de su operación y los **parámetros** que leyó, cada uno con su valor, su insignia de tipo, su
ámbito, su origen y su decisor, y lo que valen hoy si cambiaron (``core.provenance.lineage``); las
**semillas** y el dominio de trabajo (los ajustes de la envolvente: la de un escalonado, la suya); las **restricciones
aplicadas** (las activas en su versión) y sus **cifras** registradas con su insignia. Sin objeto de
diseño activo, enseña el resumen de la vista previa de las semillas mientras lo hay. Las mismas líneas,
sin las cifras (que ya son las de su ficha), las enseñan «Elemento activo» y «Cifras de la selección»
de la 010 (``view_panels.register_object_lines``). **Nada se lee al dibujar**: :func:`read_selected`
regenera las líneas al cambiar el objeto activo, tras cada lectura del proyecto cambiado y tras cargar un
``.blend`` (``view_panels.add_card_listener``). Con un dato leído, al final de la barra N está el botón
«Exportar rejilla a GeoTIFF…» (T28; RF-013-34: ``geoblender.des_export_design_grid`` con la rejilla del
objeto activo), siempre activo: exportar no escribe en el proyecto, así que vale en solo lectura.

**«Límite desde el perímetro…»** (spec 014, T20; HU-014-1; RF-014-01): el resumen de su cálculo
(:func:`show_summary`, :func:`summary_lines`: «Recinto excavable «Límite» en V01», sus celdas y su
área) y la ficha de su recinto en la barra N (:func:`item_lines`: su título «Recinto excavable ·
Límite», su superficie de partida y su cifra, sin semillas ni envolvente: el recinto es el corte
admitido de las máscaras).

**«Cantera con dos superficies…»** (spec 014, T21; HU-014-3; RF-014-12, RF-014-13): las listas de su
diálogo, leídas con las demás en :func:`refresh_choices` (las capas de polígonos que puede no usar,
:func:`optional_layer_items`; las de líneas de los corredores, :func:`line_layer_items` con
:func:`line_layers`; y la zona a conservar, :func:`conserve_items`), el perfil de cada sector por
superficie (:func:`draw_sector_rows` con ``pick``, que :func:`fill_sectors` conserva) y el resumen de
su cálculo (:func:`show_summary`: «Cantera «Corta» en V01», el orden con las celdas que cambió su
regla, las cotas de cada superficie, la excavación de la explotación, el desdoblado y el relleno, y
sus avisos).

**El resumen, la clasificación y la barra N de la cantera** (spec 014, T22; HU-014-3, HU-014-4;
RF-014-15 a RF-014-18; plan 014 §5.5): el resumen dice además la excavación de la explotación en ha,
la clasificación con el área de cada clase en ha y el espesor mínimo que la separa, y «explotación
hasta la final: no» si no se pidió (con el modo, lo que pasó a la explotación es una de sus notas;
el aviso de desdoblado sobre terreno sin explotar, con sus zonas, va en ámbar). La barra N enseña la
ficha de cada rejilla de la cantera cargada en la vista (``bl.scene.des_views``: las dos
superficies, sus envolventes y la clasificación): sus ajustes, los perfiles de cada superficie, la
superficie de partida, las capas que leyó con sus campos, los parámetros, las semillas de cada
superficie con el recinto como dominio, las restricciones, la leyenda de la clasificación (un color
por clase) y las cifras registradas, por sector y en total.

**«Solo relleno…»** (spec 014, T30; HU-014-6; RF-014-22 a RF-014-24): la lista de las envolventes
de la versión activa de su diálogo (:func:`envelope_items`, leída en :func:`refresh_choices`), el
resumen de su cálculo (:func:`show_summary`: «Diseño «solo relleno» «Balsa» en V01», el terraplén,
el corte frente al terreno registrado y el área con movimiento, las celdas en que la lámina de agua
es la partida, la inclinación y las bermas, y los avisos de su escalonado) y, en la ficha de su
superficie (una ``des_srf_``), la capa de láminas con su campo.

**La comprobación contra un límite nuevo** (spec 014, T31; HU-014-7; RF-014-26): al recompilar las
máscaras de una versión, :func:`limit_steps` añade al resumen de la compilación
(``constraint_panels.compile_check_steps``) el aviso de cada superficie de diseño de la 014 que
mueve algo fuera del límite vigente, con su volumen y su área (``design.store.limit_checks``), y la
ficha de la barra N de esa superficie lo dice también, en alerta, tras su estado. Desde la T35
(RNF-014-02), **por pasos y con una caché en memoria** (``design.store.LimitCheckMemo``, la de
:data:`_LIMITS`): los pasos de la compilación comprueban, tras guardarla, todas las superficies de
diseño de la versión que se pueden ajustar y las guardan con su clave barata; la ficha y el diálogo
del ajuste las leen de ella sin leer ninguna rejilla. Sin acierto, la ficha no se bloquea: no dice
nada y lanza la comprobación por pasos en un temporizador (:func:`limit_tick`), que llena la caché y
vuelve a leer la ficha; el diálogo comprueba antes de abrirse (:func:`refit_rows_steps`, en el modal
de su orden). La caché se invalida sola por la clave y se vacía al cerrar el proyecto y al
desactivar Geoblender (:func:`forget_limit_checks`).

**«Ajustar el diseño a un límite nuevo…»** (spec 014, T33; HU-014-7; RF-014-27, RF-014-32): las filas
de su diálogo (:func:`refit_rows`: cada superficie de diseño de la versión que se puede ajustar, con
lo que deja fuera del límite vigente; las que lo dejan, marcadas), el resumen de su cálculo
(:func:`show_summary`: «Ajuste «…» en V01» y, por superficie, su volumen de ajuste con la cara de su
perfil) y la ficha de cada superficie ajustada (la superficie de la que sale y su partida). El botón
«Exportar rejilla a GeoTIFF…» vale ya para todas las rejillas de la 014 (la clasificación y el
recinto, con su leyenda en los metadatos: ``design.export``)."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy

from ...core.catalog.search import path_text
from ...core.constraints import store as constraint_store
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, language, tr, translate
from ...core.params import ParameterStore, ParamKind, format_value, parameter_label
from ...core.params import definition as param_definition
from ...core.project.model import Progress
from ...design import messages as design_messages
from ...design import profiles as design_profiles
from ...design import provenance as design_provenance
from ...design.model import (PERIMETER_SEGMENT, BenchProfile, CellClass, Order, SeedKind, Surface,
                             ToFinalMode, ZoneKind)
from ...design.params import BenchParam, bench_key
from ...gis import provenance as gis_provenance
from ...gis import store as gis_store
from ...reserves import surfaces as res_surfaces
from ..props.des import WINDOW_MANAGER_PROPERTY
from ..scene import des_views, project_session
from ..scene import versions as scene_versions
from . import constraint_panels, labels, provenance, view_panels
from .commands import catalog
from .commands import text as command_text
from .context import active_object, object_kind
from .res_panels import NOT_SHOWN, record_text
from .view_panels import ROW_FIELD, ROW_FIGURE, ROW_HEADING, ROW_NONE, CardLine

if TYPE_CHECKING:  # solo para los tipos: habilitar no importa el cálculo (RNF-001-03)
    from ...design.model import EnvelopeRequest, QuarryRequest, SeedSource, WorkDomain, Zone
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
DECLARE_SECTORS_AGAIN = "geoblender.des_declare_sectors"  # la 012 y volver a leer (T44)
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
    español), con las notas que lo acompañan (las partes de RF-014-08, T47)."""
    return exc.text_in(language())


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
    marks = {item.code: (bool(item.use), item.profile_pick, item.final_pick,
                         item.exploitation_pick) for item in old}
    shown.sectors.clear()
    for sector in found:
        row = shown.sectors.add()
        put_sector(row, sector, states.get(sector.code), version,
                   assigned.get(sector.code, ""), names)
        use, pick, final, exploitation = marks.get(sector.code, (False, "", "", ""))
        row.use, row.profile_pick = use, pick or row.profile_name
        row.final_pick, row.exploitation_pick = final, exploitation  # la cantera (014, T21)
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
    ``docs/trampas.md`` §3), las superficies por su identificador (su nombre; T45) y la clave de lo
    que se leyó."""

    surfaces: list[tuple[str, str, str]] = field(default_factory=list)
    anchors: list[tuple[str, str, str]] = field(default_factory=list)
    zones: list[tuple[str, str, str]] = field(default_factory=list)
    layers: list[tuple[str, str, str]] = field(default_factory=list)
    optional_layers: list[tuple[str, str, str]] = field(default_factory=list)
    lines: list[tuple[str, str, str]] = field(default_factory=list)
    conserve: list[tuple[str, str, str]] = field(default_factory=list)
    designs: list[tuple[str, str, str]] = field(default_factory=list)
    envelopes: list[tuple[str, str, str]] = field(default_factory=list)
    by_id: dict[str, res_surfaces.SurfaceChoice] = field(default_factory=dict)
    key: tuple[str, str, str] | None = None


_CHOICES = _Choices()


def _fixed_choices() -> None:
    """Las listas sin nada del proyecto: sin superficies, sin rejilla de anclas, sin capa y las
    zonas que no dependen de él; las capas que la cantera puede no usar, solo «ninguna»."""
    _CHOICES.surfaces = [(NO_ZONE, NOT_SHOWN, tr("There are no grids in the project"))]
    _CHOICES.by_id = {}
    _CHOICES.anchors = [(NO_ANCHOR, tr("The anchor of the profile"),
                         tr("Anchor the benches to the elevation of the profile"))]
    _CHOICES.zones = [(NO_ZONE, tr("The whole surface"),
                       tr("Seeds in every cell of the surface with an elevation")),
                      (DOMAIN_ZONE, tr("The default domain"),
                       tr("The cells of the default work domain of the masks"))]
    _CHOICES.layers = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of polygons in the project"))]
    _CHOICES.optional_layers = [(NO_LAYER, tr("No layer"), tr("Without this layer"))]
    _CHOICES.lines = [(NO_LAYER, tr("No layer"), tr("Without this layer"))]
    _CHOICES.conserve = [(NO_ZONE, tr("No zone"), tr("No zone to conserve"))]
    _CHOICES.designs = [(NO_ZONE, NOT_SHOWN,
                         tr("There are no design surfaces in the active version"))]
    _CHOICES.envelopes = [(NO_ZONE, NOT_SHOWN, tr("There are no envelopes in the active version"))]


DESIGN_SURFACE_PREFIXES: tuple[str, ...] = tuple(
    family.prefix for family in (*design_provenance.FAMILIES, *design_provenance.QUARRY_FAMILIES)
    if family.role == design_provenance.DESIGN_SURFACE_ROLE)
"""El comienzo del nombre de las superficies de diseño (las familias con el papel
``design_surface``: la de un escalonado de la 013, las dos de una cantera, la transición y la
ajustada de la 014)."""


def line_layers(project: Any) -> tuple[str, ...]:
    """Las capas «entidades» de líneas del proyecto (``gis_fea_``), por nombre: los ejes de los
    corredores de la cantera (spec 014, T21; plan 014 §5.2.1). Una cuya tabla falta no se
    ofrece."""
    records = gis_store.list_gis_datasets(project, families=(gis_provenance.FEATURES,))
    found: list[str] = []
    for record in records:
        try:
            source = gis_store.feature_source(project, record)
        except (GeoblenderError, ValueError):
            LOGGER.warning("La capa «%s» no se ofrece a la cantera", record.name, exc_info=True)
            continue
        if source.kind == "line":
            found.append(source.name)
    return tuple(sorted(found))


def refresh_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` las listas del diálogo, con la versión activa: las superficies
    y rejillas de cotas del proyecto y de la versión activa (las que puede leer el cálculo: no las
    congeladas ni las de otra versión), las zonas (el dominio por defecto, las restricciones, los
    sectores declarados y las capas de polígonos) y las capas con que se acota el dominio. Si no se
    puede leer, el error sigue y las listas quedan como estaban."""
    version = scene_versions.active_version() or ""
    found = [choice for choice in res_surfaces.surface_choices(project, version_uid=version)
             if choice.revision is None]
    envelope_prefix = design_provenance.FAMILIES_BY_CODE[design_provenance.ENVELOPE_GRID].prefix
    with project.read() as conn:
        constraints = constraint_store.read_constraints(conn)
        envelopes = _envelope_names(conn, [choice for choice in found if choice.version_uid
                                           and choice.name.startswith(envelope_prefix)])
    layers = constraint_panels.polygon_layers(project)
    lines = line_layers(project)
    shown = view()
    sectors = [] if shown is None else [(item.code, item.name) for item in shown.sectors
                                        if item.code]
    _fixed_choices()
    if found:
        of_version, of_project = tr("A grid of the active version"), tr("A grid of the project")
        _CHOICES.surfaces = [(choice.name, choice.name,
                              of_version if choice.version_uid else of_project)
                             for choice in found]
        _CHOICES.by_id = {choice.name: choice for choice in found}
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
    # La cantera (spec 014, T21): sus capas de polígonos y de líneas, que puede no usar, y sus
    # zonas a conservar (una restricción o una capa de polígonos, RF-014-07).
    _CHOICES.optional_layers = [*_CHOICES.optional_layers, *(
        (name, constraint_panels.layer_label(name), tr("Layer of polygons")) for name in layers)]
    _CHOICES.lines = [*_CHOICES.lines, *(
        (name, constraint_panels.layer_label(name), tr("Layer of lines")) for name in lines)]
    _CHOICES.conserve = [*_CHOICES.conserve, *(
        item for item in _CHOICES.zones
        if item[0].startswith((CONSTRAINT_ZONE, LAYER_ZONE)))]
    # Las transiciones (spec 014, T28): las superficies de diseño de la versión activa.
    designs = [(choice.name, choice.name, tr("A design surface of the active version"))
               for choice in found
               if choice.version_uid and choice.name.startswith(DESIGN_SURFACE_PREFIXES)]
    if designs:
        _CHOICES.designs = designs
    # «Solo relleno…» (spec 014, T30): las envolventes de la versión activa, por el nombre de su
    # operación (el que escalona, como el escalonado de la 013).
    if envelopes:
        _CHOICES.envelopes = [(name, name, tr("An envelope of the active version"))
                              for name in envelopes]
    _CHOICES.key = (project.uid, version, language())


def _envelope_names(conn: sqlite3.Connection, choices: Sequence[res_surfaces.SurfaceChoice]
                    ) -> list[str]:
    """El nombre de la operación de cada envolvente de ``choices`` (los datos ``des_env_`` de la
    versión activa), de los ajustes de la operación que la escribió, sin repetir y en su orden;
    una cuyos ajustes no lo llevan no se ofrece. Solo lee."""
    found: list[str] = []
    for choice in choices:
        row = conn.execute("SELECT o.settings FROM gb_dataset AS d JOIN gb_operation AS o "
                           "ON o.uid = d.operation_uid WHERE d.uid = ?", (choice.uid,)).fetchone()
        try:
            settings = json.loads(str(row[0])) if row is not None and row[0] else None
        except ValueError:
            settings = None
        name = settings.get("name") if isinstance(settings, dict) else None
        if isinstance(name, str) and name.strip() and name not in found:
            found.append(name)
    return found


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


def optional_layer_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Una capa de polígonos de la cantera que puede no usarse (los fondos, las zonas de relleno,
    las láminas de agua; spec 014, T21): «ninguna capa» y las capas de polígonos del proyecto (una
    lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.optional_layers


def line_layer_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """La capa de líneas de los corredores de la cantera (spec 014, T21): «ninguna capa» y las
    capas de líneas del proyecto (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.lines


def conserve_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """La zona a conservar de la cantera (spec 014, T21; RF-014-07): ninguna, una restricción o
    una capa de polígonos (con los identificadores de :func:`zone_items`; una lista viva del
    módulo)."""
    _ensure_choices()
    return _CHOICES.conserve


def design_surface_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las superficies de diseño de la versión activa que ofrece «Transiciones con el terreno no
    afectado» (spec 014, T28; plan 014 §5.2.3: :data:`DESIGN_SURFACE_PREFIXES`), con el nombre de
    su dato como identificador (el de :func:`surface_items`); sin ninguna, «—» (una lista viva del
    módulo)."""
    _ensure_choices()
    return _CHOICES.designs


def envelope_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las envolventes de la versión activa que ofrece «Solo relleno…» (spec 014, T30; plan 014
    §5.3.3: el escalonado en relleno de una envolvente, como la 013), con el nombre de su
    operación como identificador; sin ninguna, «—» (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.envelopes


def forget_choices() -> None:
    """Olvida las listas leídas (al desregistrar)."""
    _CHOICES.key = None
    _CHOICES.surfaces, _CHOICES.anchors, _CHOICES.zones, _CHOICES.layers = [], [], [], []
    _CHOICES.optional_layers, _CHOICES.lines, _CHOICES.conserve = [], [], []
    _CHOICES.designs, _CHOICES.envelopes = [], []
    _CHOICES.by_id = {}


def surface_choice(identifier: str) -> res_surfaces.SurfaceChoice | None:
    """La superficie de identificador ``identifier`` (el nombre de su dato) de la lista leída, o
    ``None``: lo que necesita la propuesta del diálogo con lo seleccionado en la vista (T45)."""
    _ensure_choices()
    return _CHOICES.by_id.get(identifier)


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


def draw_sector_rows(layout: Any, *, bound: bool, profiles: bool,
                     pick: str = "profile_pick") -> None:
    """Los sectores del diálogo, uno por fila: con ``bound``, su casilla de acotar el dominio de
    trabajo a él; con ``profiles``, el perfil que se le asigna (buscado entre los perfiles del
    proyecto; vacío, el perfil base) en su propiedad ``pick`` (la de las envolventes o, en la
    cantera, la de cada superficie: ``final_pick``, ``exploitation_pick``). Su estado de búsqueda
    va en ámbar si está pendiente."""
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
            row.prop_search(item, pick, shown, "profiles", text="", translate=False)


def _figure(calculation: Calculation, key: str) -> float | None:
    """El valor de la cifra ``key`` de un cálculo (``None`` si no se dio)."""
    return next((figure.value for figure in calculation.figures if figure.key == key), None)


def _number(value: float | None, decimals: int = 0) -> str:
    return NOT_SHOWN if value is None else format_number(value, decimals)


def _quarry_lines(outcome: Any) -> list[tuple[str, bool]]:
    """El resumen de las dos superficies de una cantera calculada (``design.quarry.QuarryOutcome``;
    spec 014, T21 y T22; RF-014-12, RF-014-13, RF-014-15 a RF-014-18): el orden del diseño con las
    celdas que cambió su regla, las cotas de cada superficie en el recinto, la excavación de la
    explotación en m³ y ha, el desdoblado y el relleno de restauración en m³, **la clasificación**
    con el área de cada clase en ha y el espesor mínimo que separa «sin diferencia» (los totales de
    su clasificación, ``classes.total``) y, si no se pidió, «explotación hasta la final: no» (con el
    modo, lo que pasó a la explotación es una nota del cálculo). Los avisos los añade
    :func:`summary_lines`."""
    total = outcome.classes.total
    order = (tr("Final surface first") if Order(outcome.order) is Order.FINAL_FIRST
             else tr("Exploitation surface first"))
    lines = [(tr("Order of the design: {order} · the order rule changed {cells} cells",
                 order=order, cells=_number(outcome.adjusted)), False)]
    final, exploitation = total.levels(Surface.FINAL), total.levels(Surface.EXPLOITATION)
    if final is not None:
        lines.append((tr("Final surface: elevations {low} to {high} m",
                         low=_number(final[0], 1), high=_number(final[1], 1)), False))
    if exploitation is not None:
        lines.append((tr("Exploitation surface: elevations {low} to {high} m · excavation "
                         "{cut} m³ in {area} ha", low=_number(exploitation[0], 1),
                         high=_number(exploitation[1], 1), cut=_number(total.exp_cut_m3),
                         area=_number(total.exp_cut_area_ha, 2)), False))
    lines.append((tr("Unsplit {unsplit} m³ · restoration fill {fill} m³",
                     unsplit=_number(total.unsplit_m3), fill=_number(total.fill_m3)), False))
    lines.append((tr("Classification (minimum thickness {thickness} m): unsplit {unsplit} ha · "
                     "restoration fill {fill} ha · no difference {none} ha",
                     thickness=format_value(float(outcome.classes.min_thickness_m), language()),
                     unsplit=_number(total.area_ha(CellClass.UNSPLIT), 2),
                     fill=_number(total.area_ha(CellClass.FILL), 2),
                     none=_number(total.area_ha(CellClass.NONE), 2)), False))
    if outcome.to_final is None:
        lines.append((tr("Exploitation down to the final surface: no"), False))
    return lines


def _transition_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de una transición calculada (``design.edges.EdgeTransition``; spec 014, T28;
    RF-014-19 a RF-014-21): la superficie de diseño, el ángulo y el volumen, las celdas y el área
    de la transición; y el salto creado del borde de la superficie nueva (las parejas, el
    porcentaje dentro del salto admitido y el mayor salto creado). El aviso de RF-014-21 lo añade
    :func:`summary_lines`."""
    outcome = calculation.outcome
    transition, report = outcome.transition, outcome.report  # type: ignore[union-attr]
    shown = language()
    surface = str(calculation.settings.get("surface") or "")
    return [
        (tr("Transition of «{surface}» at {angle}°: {volume} m³ in {cells} cells ({area} m²)",
            surface=surface, angle=format_value(float(transition.angle_deg), shown),
            volume=_number(transition.volume_m3), cells=_number(transition.cells),
            area=_number(transition.area_m2)), False),
        (tr("Created step at the edge: {pairs} pairs, {within} % within {threshold} m, the "
            "largest {maximum} m", pairs=_number(report.pairs),
            within=_number(report.within_pct, 2),
            threshold=format_value(float(report.threshold_m), shown),
            maximum=_number(max(0.0, report.maximum_m), 2)), False)]


def _refit_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de un ajuste a un límite nuevo calculado (``design.refit.RefitOutcome``; spec 014,
    T33; RF-014-27): por superficie, en el orden de la petición, su volumen de ajuste con la cara de
    su propio perfil, las celdas que cambian y, de ellas, las que vuelven al terreno fuera del
    límite. El aviso de las que no hacía falta ajustar lo añade :func:`summary_lines`."""
    return [(tr("«{surface}» refitted with the face of its profile: {volume} m³ in {cells} cells "
                "· {outside} cells back to the terrain outside the limit", surface=item.surface,
                volume=_number(item.volume_m3), cells=_number(item.cells),
                outside=_number(item.outside_cells)), False)
            for item in calculation.outcome.refits]  # type: ignore[union-attr]


def _refit_rows_of(project: Any, version_uid: str, origins: Sequence[Any],
                   checks: Sequence[Any], current: bool | None = None
                   ) -> tuple[list[tuple[str, str, bool]], str]:
    """Las filas de :func:`refit_rows` de las superficies ``origins`` (``SurfaceOrigin``) con sus
    comprobaciones ``checks`` (``RefitCheck``) y la nota si no hay ninguna y las máscaras no están
    al día (``current``: ya se sabe si lo están; ``None``, se lee)."""
    from ...core.versions import read as versions_read  # al usarlo: habilitar no lo carga
    from ...gis.masks import access as masks_access

    found = {check.surface: check for check in checks}
    rows: list[tuple[str, str, bool]] = []
    for origin in origins:
        surface = origin.record.name
        check = found.get(surface)
        if check is None:
            rows.append((surface, f"«{surface}»", False))
        elif check.outside:
            rows.append((surface, tr("«{surface}» · {volume} m³ in {area} m² outside the current "
                                     "limit", surface=surface, volume=_number(check.volume_m3),
                                     area=_number(check.area_m2)), True))
        else:
            rows.append((surface, tr("«{surface}» · nothing outside the current limit",
                                     surface=surface), False))
    note = ""
    if origins and not found:
        if current is None:
            state, _pending = masks_access.mask_state(project, version_uid)
            current = state is masks_access.MaskState.CURRENT
        if not current:
            with project.read() as conn:
                version = versions_read.version(conn, version_uid)
            note = tr("The masks of {version} are not up to date: compile them to see which "
                      "surfaces the current limit leaves outside",
                      version=version.code if version is not None else version_uid)
    return rows, note


def _refit_origins(project: Any, version_uid: str) -> tuple[Any, ...]:
    """Las superficies de diseño de la versión que se pueden ajustar (``design.store``)."""
    from ...design import store as design_store  # al usarlo: habilitar no carga el cálculo

    with project.read() as conn:
        return design_store.limit_surfaces(conn, version_uid, types=design_store.REFIT_SOURCES)


def cached_refit_rows(project: Any, version_uid: str
                      ) -> tuple[list[tuple[str, str, bool]], str] | None:
    """Las filas de «Ajustar el diseño a un límite nuevo…» (como :func:`refit_rows`) **de la
    caché** de la comprobación (spec 014, T35; RNF-014-02), sin leer ninguna rejilla; ``None`` si
    hay que comprobar antes (alguna superficie sin acierto y las máscaras al día). Sin máscaras al
    día no hay nada que comprobar: las filas sin marcar y la nota. Solo lee."""
    from ...design import store as design_store  # al usarlo: habilitar no carga el cálculo
    from ...gis.masks import access as masks_access

    origins = _refit_origins(project, version_uid)
    if not origins:
        return [], ""
    checks = _LIMITS.memo().lookup(project, version_uid, types=design_store.REFIT_SOURCES)
    if checks is not None:
        return _refit_rows_of(project, version_uid, origins, checks)
    state, _pending = masks_access.mask_state(project, version_uid)
    if state is masks_access.MaskState.CURRENT:
        return None
    return _refit_rows_of(project, version_uid, origins, (), current=False)


def refit_rows_steps(project: Any, version_uid: str) -> Iterator[Progress]:
    """La comprobación de las superficies de diseño de la versión que se pueden ajustar, por pasos
    (``design.store.LimitCheckMemo.fill_steps``, que llena la caché; spec 014, T35; RNF-014-02):
    los ``Progress`` de :data:`LIMIT_PHASE`, el último con las filas y la nota de
    :func:`refit_rows`. Cerrarlos a mitad no deja nada."""
    from ...design import store as design_store  # al usarlo: habilitar no carga el cálculo

    message = tr("Checking the design surfaces against the current limit…")
    found = yield from _progress(_LIMITS.memo().fill_steps(
        project, version_uid, types=design_store.REFIT_SOURCES), message)
    yield Progress(LIMIT_PHASE, 1, 1, message, result=_refit_rows_of(
        project, version_uid, _refit_origins(project, version_uid),
        [check for _op_type, check in found]))


def refit_rows(project: Any, version_uid: str) -> tuple[list[tuple[str, str, bool]], str]:
    """Las filas de «Ajustar el diseño a un límite nuevo…» (spec 014, T33; plan 014 §5.3.3): cada
    superficie de diseño de la versión ``version_uid`` que se puede ajustar
    (``design.store.REFIT_SOURCES``, por el nombre de su dato) con lo que dice de ella la ventana y
    si queda fuera del límite vigente (``design.store.limit_checks``: la marcada); y una nota si las
    máscaras no están al día (sin ellas no se sabe qué queda fuera). De la caché
    (:func:`cached_refit_rows`) o, sin acierto, de una vez (:func:`refit_rows_steps`: desde un
    guion; la orden, desde la interfaz, comprueba por pasos antes de abrir su ventana). Solo lee;
    los errores del proyecto siguen."""
    found = cached_refit_rows(project, version_uid)
    if found is not None:
        return found
    for step in refit_rows_steps(project, version_uid):
        if step.result is not None:
            return step.result  # type: ignore[return-value]
    raise AssertionError("la comprobación acaba siempre con sus filas")  # pragma: no cover


def summary_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de un cálculo hecho y sin registrar (RF-013-31), línea a línea y en el idioma de
    Geoblender, con los avisos al final y en alerta: de una envolvente, sus celdas, su área, sus
    cotas y el desmonte y el terraplén frente a la superficie de partida (las cifras que se
    registrarían); de un escalonado, el desmonte y el terraplén, la inclinación p99 y máxima con su
    lugar, y las bermas con sus cotas reales (el informe y las bermas del dominio); de un recinto
    excavable (spec 014, T20; RF-014-01), sus celdas y su área; de una cantera con dos superficies
    (spec 014, T21; RF-014-12), lo de :func:`_quarry_lines`; de una transición (T28), lo de
    :func:`_transition_lines`; de un diseño «solo relleno» (T30), lo de :func:`_fill_only_lines`;
    de un ajuste a un límite nuevo (T33), lo de :func:`_refit_lines`. Aquí solo se escriben."""
    lines: list[tuple[str, bool]] = []
    if calculation.op_type == design_provenance.QUARRY:
        lines.extend(_quarry_lines(calculation.outcome))
    elif calculation.op_type == design_provenance.REFIT:
        lines.extend(_refit_lines(calculation))
    elif calculation.op_type == design_provenance.EDGE_TRANSITION:
        lines.extend(_transition_lines(calculation))
    elif calculation.op_type == design_provenance.EXCAVATION_AREA:
        cells = calculation.outcome.cells  # type: ignore[union-attr]
        lines.append((tr("Excavation boundary «{name}»: {cells} cells ({area} m²)",
                         name=calculation.name, cells=_number(cells),
                         area=_number(_figure(calculation, "des.rcn_area_m2"))), False))
    elif calculation.op_type == design_provenance.ENVELOPE:
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
    elif calculation.op_type == design_provenance.FILL_ONLY:
        lines.extend(_fill_only_lines(calculation))
    else:
        outcome = calculation.outcome
        report, berms = outcome.report, outcome.berms  # type: ignore[union-attr]
        lines.append((tr("Benching «{name}»: cut {cut} m³ · fill {fill} m³ · moved area {area} m²",
                         name=calculation.name, cut=_number(report.cut_m3),
                         fill=_number(report.fill_m3), area=_number(report.moved_area_m2)),
                      False))
        lines.extend(_bench_lines(report, berms))
    lines.extend((notice.text(language()), notice.severity == "warning")
                 for notice in calculation.notices)
    return lines


def _bench_lines(report: Any, berms: Any, *, without_berms: bool = True
                 ) -> list[tuple[str, bool]]:
    """La inclinación p99 y máxima con su lugar y las bermas con sus cotas reales de un
    escalonado (su informe y sus bermas medidas), como las dice el resumen; sin bermas, «Sin
    bermas: no se mueve nada» si ``without_berms``."""
    lines: list[tuple[str, bool]] = []
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
    elif without_berms:
        lines.append((tr("No berms: nothing moves"), False))
    return lines


def _fill_only_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de un diseño «solo relleno» calculado (``design.fronts.FillOnlyOutcome``; spec
    014, T30; RF-014-22 a RF-014-24): el terraplén y el área con movimiento frente al terreno de
    partida con las láminas (el informe de su escalonado), el corte frente al terreno registrado
    (con dos decimales: tiene que ser menor de 1 m³), las celdas en que la lámina de agua es la
    partida, si las hay, y la inclinación y las bermas (un relleno de un solo banco no tiene
    bermas, y no por eso deja de mover: «Sin bermas: no se mueve nada», solo si no mueve nada).
    Los avisos los añade :func:`summary_lines`."""
    outcome = calculation.outcome
    report, berms = outcome.design.report, outcome.design.berms  # type: ignore[union-attr]
    lines = [(tr("Fill-only design «{name}»: fill {fill} m³ · cut {cut} m³ · moved area {area} m²",
                 name=calculation.name, fill=_number(report.fill_m3),
                 cut=_number(outcome.cut_m3, 2),  # type: ignore[union-attr]
                 area=_number(report.moved_area_m2)), False)]
    if outcome.water_cells:  # type: ignore[union-attr]
        lines.append((tr("Water sheets as the start surface in {cells} cells",
                         cells=_number(outcome.water_cells)), False))  # type: ignore[union-attr]
    return [*lines, *_bench_lines(report, berms, without_berms=not report.moved_area_m2)]


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
    _redraw()  # la barra N «Diseño» enseña este resumen mientras lo hay


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
    if calculation.op_type == design_provenance.ENVELOPE:
        title = tr("Envelope «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.EXCAVATION_AREA:
        title = tr("Excavation boundary «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.QUARRY:
        title = tr("Quarry «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.EDGE_TRANSITION:
        title = tr("Transition «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.FILL_ONLY:
        title = tr("Fill-only design «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.REFIT:
        title = tr("Refit «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    else:
        title = tr("Benching «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    shown.summary_title = title
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
    campo del nombre de la 012 y la orden de la 013 que lanza la suya de declarar los sectores
    (``core_declare_sectors``, que conserva los valores de los sectores que mantienen su código) y
    vuelve a leer esta ventana sin cerrarla (T44)."""
    other = constraint_panels.view()
    box = layout.box()
    box.label(text=tr("Declare the sectors from a layer of polygons"), translate=False)
    form = box.column()
    form.enabled = writable
    if other is not None:
        form.prop_search(other, "sector_layer", other, "sector_sources",
                         text=tr("Layer of the sectors"), translate=False)
        form.prop(other, "sector_field", text=tr("Field of the name"), translate=False)
    form.operator(DECLARE_SECTORS_AGAIN, text=tr("Declare again from a layer…"), icon="CHECKMARK",
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


# --- La barra N «Diseño»: el dato del objeto activo (T27; RF-013-32, RF-013-06) -------------------

SELECTED_PANEL = "GEOBLENDER_PT_des_design"
SELECTED_TAB = "Design"  # msgid de la pestaña y del título de la barra N
EXPORT_GRID = "geoblender.des_export_design_grid"  # su botón: «Exportar rejilla a GeoTIFF…» (T28)
MAX_CONSTRAINT_LINES = 10
"""Cuántas restricciones aplicadas enseña la barra N; de las demás, cuántas más hay."""
_LIMIT_CHECKED = frozenset({design_provenance.QUARRY, design_provenance.EDGE_TRANSITION,
                            design_provenance.FILL_ONLY, design_provenance.REFIT})
"""Los tipos de operación cuyas superficies se comprueban contra el límite vigente en la barra N
(los de ``design.store.LIMIT_CHECKED_TYPES``, sin importar el cálculo al habilitar)."""


@dataclass(frozen=True)
class ItemLines:
    """Lo que dice el proyecto del dato de un objeto de diseño (:func:`item_lines`): su título
    («Superficie de diseño · Hoyo»), las líneas de su ficha (estado, marcas, ajustes, parámetros,
    semillas y dominio, restricciones) y, aparte, sus cifras registradas, que empiezan por la marca de
    la búsqueda pendiente si la hay (sin ``uid``: no es una cifra)."""

    title: str
    lines: tuple[CardLine, ...]
    figures: tuple[CardLine, ...]


def wanted(context: Any = None) -> str:
    """El ``uid`` del dato que enseña la barra N: el del objeto ``DESIGN`` activo si es de un dato
    del proyecto abierto; si no, ``""``. No lee el proyecto."""
    context = bpy.context if context is None else context
    project = project_session.current()
    if project is None:
        return ""
    obj = active_object(context)
    if object_kind(obj) != des_views.KIND:
        return ""
    props = obj.geoblender
    return str(props.dataset_uid) if str(props.project_uid) == project.uid else ""


def has_preview() -> bool:
    """Si la vista previa de las semillas ha dejado su resumen (:func:`show_preview`)."""
    shown = view()
    return shown is not None and len(shown.preview) > 0


def _family_label(name: str) -> str:
    """El nombre, en el idioma de Geoblender, del tipo de rejilla del dato ``name`` (la envolvente,
    la superficie de diseño, las cotas de berma o el recinto excavable de la 014); vacío si no es
    de ellas."""
    for family, msgid in des_views.LOADERS:
        if name.startswith(des_views.prefix(family)):
            return translate(language(), msgid)
    return ""


def _stored_settings(conn: sqlite3.Connection, version_uid: str, family: str,
                     name: object) -> Mapping[str, Any] | None:
    """Los ajustes de la operación que escribió el dato de la familia ``family`` y la operación
    ``name`` en la versión ``version_uid``; ``None`` si la versión ya no lo tiene."""
    from ...core.datasets import registry as dataset_registry  # al usarlo: habilitar no lo carga

    if not isinstance(name, str) or not name:
        return None
    dataset = design_provenance.dataset_name(family, name)
    record = dataset_registry.get(conn, dataset, version_uid=version_uid)
    if record is None or record.name != dataset:
        return None
    row = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?",
                       (record.operation_uid,)).fetchone()
    found = json.loads(str(row[0])) if row is not None and row[0] else None
    return found if isinstance(found, dict) else None


def parameter_line(used: Any, version_code: str) -> CardLine:
    """Un parámetro que leyó la operación (``core.provenance.lineage.ParameterLink``): su nombre, su
    valor con su unidad y su insignia de tipo («Altura de banco · expl_10_60_6: 10 m [ADO]»), su
    ámbito («el proyecto» o la versión), su origen y quién lo decidió; si hoy vale otra cosa, lo de
    hoy, y en alerta. Aquí solo se escribe."""
    shown = language()
    value = f"{used.value_text(language=shown)} {provenance.badge(used.kind)}"
    if used.unconfirmed:
        value = f"{value} {tr('unconfirmed')}"
    scope = tr("the project") if used.scope == "project" else (version_code or str(used.scope))
    origin = [str(used.source or ""),
              tr("decided by {person}", person=used.decided_by) if used.decided_by else ""]
    parts = [f"{parameter_label(used.key, shown) or used.key}: {value}", scope,
             *(part for part in origin if part)]
    if used.changed:
        today = f"{used.current_value_text(language=shown)} {provenance.badge(used.current_kind)}"
        parts.append(tr("today: {value}", value=today))
    return CardLine(ROW_FIELD, " · ".join(parts), alert=bool(used.changed or used.source_stale))


def _zone_text(zone: Zone, constraints: Mapping[str, str], sectors: Mapping[str, str]) -> str:
    """La zona de las semillas como se lee: el dominio por defecto, «zona de «Hoyo»» (su
    restricción), «sector «Sector 1»» o «capa «x»»."""
    if zone.kind is ZoneKind.DOMAIN:
        return tr("default domain")
    name = str(zone.name or "")
    if zone.kind is ZoneKind.CONSTRAINT:
        return tr("zone of «{name}»", name=constraints.get(name) or name)
    if zone.kind is ZoneKind.SECTOR:
        return tr("sector «{name}»", name=sectors.get(name) or name)
    return tr("layer «{name}»", name=name)


def _domain_text(domain: WorkDomain, sectors: Mapping[str, str]) -> str:
    """El acotado del dominio de trabajo como se lee: todo el de las máscaras, unos sectores, una
    capa o los dos."""
    names = ", ".join(f"«{sectors.get(code) or code}»" for code in domain.sectors)
    if domain.sectors and domain.layer:
        return tr("Work domain: bound to the sectors {sectors} and to the layer «{layer}»",
                  sectors=names, layer=domain.layer)
    if domain.sectors:
        return tr("Work domain: bound to the sectors {sectors}", sectors=names)
    if domain.layer:
        return tr("Work domain: bound to the layer «{layer}»", layer=domain.layer)
    return tr("Work domain: the whole domain of the masks")


def seed_lines(request: EnvelopeRequest, constraints: Mapping[str, str],
               sectors: Mapping[str, str]) -> list[CardLine]:
    """Las semillas y el dominio de trabajo de una envolvente (RF-013-01, RF-013-02; los ajustes que
    guardó, ``design.provenance.envelope_request``): de dónde salen las semillas y su zona, y el
    acotado del dominio. ``constraints`` y ``sectors`` dan el nombre de cada código."""
    seeds = request.seeds
    origin = _seed_origin(seeds)
    text = (tr("Seeds: {origin} · {zone}", origin=origin,
               zone=_zone_text(seeds.zone, constraints, sectors))
            if seeds.zone is not None else tr("Seeds: {origin}", origin=origin))
    return [CardLine(ROW_FIELD, text), CardLine(ROW_FIELD, _domain_text(request.domain, sectors))]


def _seed_origin(seeds: SeedSource) -> str:
    """De dónde salen unas semillas de la 013 como se lee: «celdas de «Ladera»», «cota fija 90 m» o
    «rejilla de cotas «x»»."""
    if seeds.kind is SeedKind.SURFACE:
        return tr("cells of «{surface}»", surface=seeds.surface)
    if seeds.kind is SeedKind.FIXED:
        return tr("fixed elevation {elevation} m",
                  elevation=format_value(float(seeds.elevation_m or 0.0), language()))
    return tr("grid of elevations «{grid}»", grid=seeds.grid)


# --- La ficha de una cantera con dos superficies (spec 014, T22; RF-014-15, RF-014-16) ------------


def _quarry_profile_lines(settings: Mapping[str, Any], profile_names: Mapping[str, str],
                          sectors: Mapping[str, str]) -> list[CardLine]:
    """Los perfiles de banco de cada superficie de una cantera (sus ajustes ``final`` y
    ``exploitation``), por su nombre: «Perfiles de la superficie final: base REST_5_35_6»."""
    def assigned(side: Surface) -> str:
        found = settings.get(side.value)
        return profiles_text(found, profile_names, sectors) if isinstance(found, Mapping) else ""

    lines: list[CardLine] = []
    final, exploitation = assigned(Surface.FINAL), assigned(Surface.EXPLOITATION)
    if final:
        lines.append(CardLine(ROW_FIELD, tr("Profiles of the final surface: {profiles}",
                                            profiles=final)))
    if exploitation:
        lines.append(CardLine(ROW_FIELD, tr("Profiles of the exploitation surface: {profiles}",
                                            profiles=exploitation)))
    return lines


def _quarry_layer_lines(request: QuarryRequest, constraints: Mapping[str, str],
                        sectors: Mapping[str, str]) -> list[CardLine]:
    """Las capas que leyó una cantera, cada una con sus campos (plan 014 §5.2.1): los fondos, las
    zonas a conservar, los corredores, las zonas de restauración por relleno, las láminas de agua y
    las zonas de «explotación hasta la final»; con su encabezado, o ninguna línea si no usó
    ninguna."""
    label = constraint_panels.layer_label
    lines: list[CardLine] = []
    if request.floors is not None:
        lines.append(CardLine(ROW_FIELD, tr("{what}: layer «{layer}» · field «{field}»",
                                            what=tr("Floors"), layer=label(request.floors.layer),
                                            field=request.floors.field)))
    lines += [CardLine(ROW_FIELD, tr("{name}: {value}", name=tr("Zone to conserve"),
                                     value=_zone_text(zone, constraints, sectors)))
              for zone in request.conserve]
    corridors = request.corridors
    if corridors is not None and corridors.graded:
        lines.append(CardLine(ROW_FIELD, tr(
            "Corridors: layer «{layer}» · width «{width}» · start elevation «{start}» · "
            "grade «{grade}»", layer=label(corridors.layer), width=corridors.width_field,
            start=corridors.start_level_field, grade=corridors.grade_field)))
    elif corridors is not None:
        lines.append(CardLine(ROW_FIELD, tr(
            "Corridors: layer «{layer}» · width «{width}» · elevation «{level}»",
            layer=label(corridors.layer), width=corridors.width_field,
            level=corridors.level_field)))
    if request.fill_zones:
        lines.append(CardLine(ROW_FIELD, tr("{what}: layer «{layer}»",
                                            what=tr("Restoration fill zones"),
                                            layer=label(request.fill_zones))))
    if request.water is not None:
        lines.append(CardLine(ROW_FIELD, tr("{what}: layer «{layer}» · field «{field}»",
                                            what=tr("Water sheets"),
                                            layer=label(request.water.layer),
                                            field=request.water.field)))
    if ToFinalMode(request.to_final) is ToFinalMode.LAYER and request.to_final_layer:
        lines.append(CardLine(ROW_FIELD, tr("{what}: layer «{layer}»",
                                            what=tr("Exploitation down to the final surface"),
                                            layer=label(request.to_final_layer))))
    return [CardLine(ROW_HEADING, tr("Layers")), *lines] if lines else []


def _water_lines(settings: Mapping[str, Any]) -> list[CardLine]:
    """La capa de láminas de agua de un diseño «solo relleno» con su campo de cota (sus ajustes
    ``water``; spec 014, T30; RF-014-24): «Láminas de agua: capa «laminas» · campo «cota»»; ninguna
    línea sin láminas."""
    water = settings.get("water")
    if not isinstance(water, Mapping) or not water.get("layer"):
        return []
    return [CardLine(ROW_FIELD, tr("{what}: layer «{layer}» · field «{field}»",
                                   what=tr("Water sheets"),
                                   layer=constraint_panels.layer_label(str(water["layer"])),
                                   field=str(water.get("field") or "")))]


def _quarry_seed_lines(request: QuarryRequest | None, constraints: Mapping[str, str],
                       sectors: Mapping[str, str]) -> list[CardLine]:
    """Las semillas de cada superficie de una cantera («Coronación y zonas a sostener» o las de la
    013 con su zona) y su dominio de trabajo, el recinto excavable de las máscaras (RF-014-01,
    RF-014-02); si sus ajustes no se pueden leer, lo dice."""
    if request is None:
        return [CardLine(ROW_NONE, tr("The seeds and the domain are not recorded"))]
    lines: list[CardLine] = []
    for side, name in ((request.final, tr("Seeds of the final surface")),
                       (request.exploitation, tr("Seeds of the exploitation surface"))):
        seeds = side.seeds
        if seeds is None:
            value = tr("Crown and zones to hold")
        elif seeds.zone is None:
            value = _seed_origin(seeds)
        else:
            value = f"{_seed_origin(seeds)} · {_zone_text(seeds.zone, constraints, sectors)}"
        lines.append(CardLine(ROW_FIELD, tr("{name}: {value}", name=name, value=value)))
    lines.append(CardLine(ROW_FIELD, tr("Work domain: the excavation boundary of the masks")))
    return lines


def _legend_lines() -> list[CardLine]:
    """La leyenda de la clasificación de una cantera (``des_views.CLASS_LEGEND``): su encabezado y
    una línea por clase, con su código y su color en la vista (RF-014-15)."""
    shown = language()
    return [CardLine(ROW_HEADING, tr("Legend")),
            *(CardLine(ROW_FIELD, translate(shown, msgid))
              for _code, _color, msgid in des_views.CLASS_LEGEND)]


def _quarry_request(settings: Mapping[str, Any], name: str) -> QuarryRequest | None:
    """La cantera que guardan los ajustes ``settings`` (``design.provenance.quarry_request``), o
    ``None`` si no se pueden leer (lo deja en el registro técnico con el nombre del dato
    ``name``)."""
    try:
        return design_provenance.quarry_request(settings)
    except ValueError:
        LOGGER.info("Los ajustes de la cantera de «%s» no se pueden leer", name, exc_info=True)
        return None


def profiles_text(settings: Mapping[str, Any], profile_names: Mapping[str, str],
                  sectors: Mapping[str, str]) -> str:
    """Los perfiles de banco asignados que guardó la operación (RF-013-21): el base y el de cada
    sector, por su nombre («base EXPL_10_60_6 · Sector 2: REST_5_35_6»); vacío si no asignó ninguno.
    ``profile_names`` da el nombre de cada código de perfil y ``sectors``, el de cada sector."""
    parts: list[str] = []
    base = settings.get("base_profile")
    if isinstance(base, str) and base:
        parts.append(tr("base {profile}", profile=profile_names.get(base) or base))
    assigned = settings.get("sector_profiles")
    for code, profile in (assigned.items() if isinstance(assigned, Mapping) else ()):
        parts.append(f"{sectors.get(code) or code}: {profile_names.get(profile) or profile}")
    return " · ".join(parts)


LIMIT_PHASE = "limit_check"
"""La fase de los pasos de la comprobación de las superficies contra el límite vigente."""
LIMIT_TICK_S = 0.05
"""Cada cuánto vuelve el temporizador de la comprobación de fondo (:func:`limit_tick`)."""
LIMIT_BUDGET_S = 0.05
"""Lo que avanza la comprobación de fondo en cada llamada, como mucho (más su última unidad, de
≈ 0,1 s como mucho: RNF-014-02)."""


@dataclass
class _LimitChecks:
    """La caché en memoria de la comprobación contra el límite vigente
    (``design.store.LimitCheckMemo``, creada al usarla: habilitar no carga el cálculo) y la
    comprobación de fondo en marcha (sus unidades, el proyecto y la versión)."""

    held: Any = None
    work: Iterator[None] | None = None
    target: tuple[str, str] | None = None
    project: Any = None

    def memo(self) -> Any:
        """La caché (``design.store.LimitCheckMemo``)."""
        if self.held is None:
            from ...design import store as design_store  # al usarlo

            self.held = design_store.LimitCheckMemo()
        return self.held

    def stop(self) -> None:
        """Deja la comprobación de fondo (sus unidades se cierran sin guardar nada)."""
        work, self.work, self.target, self.project = self.work, None, None, None
        if work is not None:
            work.close()  # type: ignore[attr-defined]


_LIMITS = _LimitChecks()


def _progress[T](work: Generator[None, None, T], message: str) -> Generator[Progress, None, T]:
    """Las unidades de ``work`` como ``Progress`` de :data:`LIMIT_PHASE` con ``message``; devuelve
    lo que devuelve ``work``. Cerrarlo cierra ``work``."""
    try:
        while True:
            try:
                next(work)
            except StopIteration as stop:
                return stop.value  # type: ignore[no-any-return]
            yield Progress(LIMIT_PHASE, 0, 0, message)
    finally:
        work.close()


def limit_steps(project: Any, version_uid: str) -> Iterator[Progress]:
    """Lo que añade la 014 al resumen de una compilación de las máscaras de la versión
    ``version_uid`` (spec 014, T31; RF-014-26; ``constraint_panels.add_compile_check``), **por
    pasos** (T35; RNF-014-02): la comprobación de las superficies de diseño de la versión que se
    pueden ajustar (``design.store.REFIT_SOURCES``) contra el límite vigente, que llena la caché
    (:data:`_LIMITS`), un ``Progress`` por unidad; el último lleva, en alerta, el aviso de cada
    superficie de la 014 (``design.store.LIMIT_CHECKED_TYPES``) que mueve algo fuera de él, con su
    volumen y su área; ninguna línea si no queda nada fuera. Solo lee."""
    from ...design import store as design_store  # al usarlo: habilitar no carga el cálculo

    message = tr("Checking the design surfaces against the current limit…")
    found = yield from _progress(_LIMITS.memo().fill_steps(
        project, version_uid, types=design_store.REFIT_SOURCES), message)
    shown = language()
    yield Progress(LIMIT_PHASE, 1, 1, message, result=[
        constraint_panels.Line(check.notice.text(shown), alert=True) for op_type, check in found
        if op_type in design_store.LIMIT_CHECKED_TYPES and check.notice is not None])


def _check_later(project: Any, version_uid: str) -> None:
    """Lanza la comprobación de las superficies de la versión ``version_uid`` en el temporizador
    :func:`limit_tick` (por pasos; llena la caché y vuelve a leer la ficha), si no está ya en marcha
    para ella; una de otra versión o de otro proyecto se deja."""
    from ...design import store as design_store  # al usarlo: habilitar no carga el cálculo

    target = (str(project.uid), version_uid)
    if _LIMITS.work is not None and _LIMITS.target == target:
        return
    _LIMITS.stop()
    _LIMITS.work = _LIMITS.memo().fill_steps(project, version_uid,
                                             types=design_store.REFIT_SOURCES)
    _LIMITS.target, _LIMITS.project = target, project
    if not bpy.app.timers.is_registered(limit_tick):
        bpy.app.timers.register(limit_tick, first_interval=LIMIT_TICK_S, persistent=True)


def _reread_cards() -> None:
    """Vuelve a leer la ficha del objeto activo («Elemento activo») y la de la barra N «Diseño»."""
    try:
        view_panels.read_card()
    except Exception:  # noqa: BLE001 - lo que llama Blender no lo tumba
        LOGGER.exception("Falló la lectura de la ficha del objeto activo")
    read_selected_safely()


def limit_tick() -> float | None:
    """El temporizador de la comprobación de fondo (spec 014, T35; RNF-014-02): avanza sus unidades
    durante :data:`LIMIT_BUDGET_S` como mucho y vuelve en :data:`LIMIT_TICK_S`; al terminar, con la
    caché ya llena, vuelve a leer la ficha. Sin comprobación, o con otro proyecto en la sesión, se
    quita. Un fallo va al registro técnico (la ficha sigue sin la línea)."""
    work = _LIMITS.work
    if work is None:
        return None
    if project_session.current() is not _LIMITS.project:
        _LIMITS.stop()
        return None
    started = time.perf_counter()
    try:
        while True:
            next(work)
            if time.perf_counter() - started >= LIMIT_BUDGET_S:
                return LIMIT_TICK_S
    except StopIteration:
        _LIMITS.work = _LIMITS.target = _LIMITS.project = None
    except Exception:  # noqa: BLE001 - lo que llama Blender no lo tumba
        LOGGER.exception("Falló la comprobación de las superficies contra el límite vigente")
        _LIMITS.stop()
        return None
    _reread_cards()
    return None


def forget_limit_checks() -> None:
    """Vacía la caché de la comprobación y deja la de fondo (al cerrar el proyecto o abrir otro, y
    al desactivar Geoblender)."""
    _LIMITS.stop()
    if _LIMITS.held is not None:
        _LIMITS.held.clear()


def _outside_lines(project: Any, version_uid: str, uid: str) -> list[CardLine]:
    """La ficha de una superficie de diseño de la 014 (el dato ``uid`` de la versión
    ``version_uid``) que mueve algo fuera del límite vigente de su versión: su aviso, en alerta
    (spec 014, T31; RF-014-26); ninguna línea si no deja nada fuera, si no es una superficie de la
    014 o si las máscaras no están al día. **De la caché** (T35; RNF-014-02): sin acierto, ninguna
    línea y la comprobación por pasos en el temporizador (:func:`limit_tick`), que vuelve a leer la
    ficha al terminar. Si no se puede comprobar, lo deja en el registro técnico."""
    try:
        checks = _LIMITS.memo().lookup(project, version_uid, names=(uid,))
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.info("No se pudo comprobar «%s» contra el límite vigente", uid, exc_info=True)
        return []
    if checks is None:  # sin acierto: la ficha no se bloquea
        _check_later(project, version_uid)
        return []
    shown = language()
    return [CardLine(ROW_FIELD, check.notice.text(shown), alert=True) for check in checks
            if check.notice is not None]


def _constraint_lines(listed: Sequence[Any], version_code: str) -> list[CardLine]:
    """Las restricciones activas en la versión (``gis.masks.store.ListedConstraint``), cada una con su
    tipo y su nombre; las que pasan de :data:`MAX_CONSTRAINT_LINES`, contadas."""
    shown = language()
    active = [item.constraint for item in listed if item.state == "active"]
    if not active:
        return [CardLine(ROW_NONE, tr("No constraint is active in {version}",
                                      version=version_code or tr("the project")))]
    lines: list[CardLine] = []
    for item in active[:MAX_CONSTRAINT_LINES]:
        kind = constraint_panels.type_label("" if item.ctype is None else item.ctype.value)
        lines.append(CardLine(ROW_FIELD, f"{kind} · {item.shown_name(shown)}"))
    if len(active) > MAX_CONSTRAINT_LINES:
        lines.append(CardLine(ROW_NONE, tr("… and {count} more",
                                           count=len(active) - MAX_CONSTRAINT_LINES)))
    return lines


def _seed_card(settings: Mapping[str, Any], envelope_settings: Mapping[str, Any] | None,
               constraints: Mapping[str, str], sectors: Mapping[str, str],
               name: str) -> list[CardLine]:
    """Las semillas y el dominio de la ficha de una envolvente o de un escalonado (los de su
    envolvente, ``envelope_settings``; ``None`` si la versión ya no la tiene); si sus ajustes no
    se pueden leer, lo dice (y lo deja en el registro técnico con el nombre del dato ``name``)."""
    try:
        if envelope_settings is None:
            return [CardLine(ROW_NONE, tr("The envelope «{name}» is no longer in this version",
                                          name=str(settings.get("envelope") or "")))]
        return seed_lines(design_provenance.envelope_request(envelope_settings), constraints,
                          sectors)
    except ValueError:
        LOGGER.info("Los ajustes de la envolvente de «%s» no se pueden leer", name, exc_info=True)
        return [CardLine(ROW_NONE, tr("The seeds and the domain are not recorded"))]


def item_lines(project: Any, uid: str) -> ItemLines | None:
    """Lo que dice el proyecto del dato ``uid`` de un diseño (véase el módulo), en una instantánea y
    sin escribir nada; ``None`` si el proyecto ya no lo tiene. Su estado es el de
    ``core.provenance.stale`` (con su causa); los ajustes, los parámetros y la operación, los de
    ``core.provenance.lineage``; la marca de la búsqueda pendiente, la de ``design.sectors`` (en las
    líneas y otra vez como primeras filas de las cifras, ámbar y una por sector pendiente); las
    semillas y el dominio, los de los ajustes de la envolvente (la de un escalonado, la que
    escaló; un recinto excavable de la 014, T20, no tiene: su ficha dice su superficie de
    partida; una rejilla de una cantera, T22, las de cada superficie, con sus perfiles, su
    superficie de partida y las capas que leyó, y la clasificación, además, su leyenda; una
    transición, T28, su superficie de diseño y su superficie de partida, sin semillas; una
    superficie ajustada a un límite nuevo, T33, la superficie de la que sale y su partida, sin
    semillas); las restricciones, las activas en su versión (``gis.masks.store``) y las cifras, las de su
    operación. Los errores del proyecto (``GeoblenderError``, ``sqlite3.Error``) siguen."""
    from ...core.provenance import lineage as prov_lineage  # al usarlo: habilitar no lo carga
    from ...core.provenance import stale as prov_stale
    from ...core.versions import read as versions_read
    from ...core.views import card
    from ...design.sectors import design_sectors, pending_marks
    from ...gis.masks import store as masks_store
    from ...gis.polygons import drain

    shown = language()
    with project.read() as conn:
        found = card.item_card(project, uid, conn=conn)
        if found is None:
            return None
        tree = prov_lineage.lineage(project, uid, conn=conn, language=shown)
        link = tree.operations[tree.root]
        cause = (prov_stale.item_text(conn, prov_stale.DATASET, uid, language=shown)
                 if found.stale else None)
        owner = versions_read.dataset_versions(conn, [uid]).get(uid, "")
        constraints = {code: name for code, (name, _kind) in
                       constraint_store.constraint_names(conn).items()}
        profile_names = design_profiles.profile_names(conn)
        settings = link.settings
        area = link.op_type == design_provenance.EXCAVATION_AREA  # un recinto: sin semillas
        quarry = link.op_type == design_provenance.QUARRY  # una cantera: las de sus dos lados
        # Una transición (T28): sin semillas ni envolvente; su superficie de diseño y su partida.
        transition = link.op_type == design_provenance.EDGE_TRANSITION
        # Un ajuste a un límite nuevo (T33): tampoco; la superficie que ajusta y su partida.
        refit = link.op_type == design_provenance.REFIT
        envelope_settings: Mapping[str, Any] | None = settings
        if (link.op_type != design_provenance.ENVELOPE and not area and not quarry
                and not transition and not refit):
            envelope_settings =_stored_settings(conn, owner, design_provenance.ENVELOPE_GRID,
                                                 settings.get("envelope"))  # la que escaló
    version_code = found.revision.code if found.revision is not None else ""
    sectors = design_sectors(project, owner or None)
    names = {sector.code: sector.name for sector in sectors}
    listed = drain(masks_store.shown_constraints_steps(project, version=owner or None))

    lines: list[CardLine] = [
        CardLine(ROW_FIELD, cause or tr("Up to date"), alert=bool(found.stale))]
    if owner and link.op_type in _LIMIT_CHECKED:  # una superficie de la 014 fuera del límite (T31)
        lines += _outside_lines(project, owner, uid)
    try:
        touched = design_provenance.settings_touched(settings)
    except ValueError:
        touched = ()
        LOGGER.info("Los sectores que tocó «%s» no se pueden leer", found.record.name)
    marks = [CardLine(ROW_FIELD, mark.text(shown), alert=True)
             for mark in pending_marks(touched, sectors)]
    lines += marks
    if link.settings_text:
        lines.append(CardLine(ROW_FIELD, link.settings_text))
    request = _quarry_request(settings, found.record.name) if quarry else None
    if quarry:  # los perfiles de cada superficie (RF-014-12)
        lines += _quarry_profile_lines(settings, profile_names, names)
    elif assigned := profiles_text(settings, profile_names, names):
        lines.append(CardLine(ROW_FIELD, tr("Profiles: {profiles}", profiles=assigned)))
    if (link.op_type != design_provenance.ENVELOPE and not area and not quarry and not transition
            and not refit):
        lines.append(CardLine(ROW_FIELD, tr("Envelope: «{name}»",
                                            name=str(settings.get("envelope") or ""))))
    if transition:
        lines.append(CardLine(ROW_FIELD, tr("Design surface: «{surface}»",
                                            surface=str(settings.get("surface") or ""))))
    if refit:  # la superficie de diseño de la que sale este dato ajustado (T33)
        lines.append(CardLine(ROW_FIELD, tr("Refitted surface: «{surface}»", surface=str(
            design_provenance.refit_source(settings, found.record.name) or ""))))
    if link.op_type != design_provenance.ENVELOPE:
        start = settings.get("start" if quarry or transition or refit else "surface")
        lines.append(CardLine(ROW_FIELD, tr("Start surface: «{surface}»",
                                            surface=str(start or ""))))
    if request is not None:
        lines += _quarry_layer_lines(request, constraints, names)
    if link.op_type == design_provenance.FILL_ONLY:  # «solo relleno» (T30): su capa de láminas
        lines += _water_lines(settings)
    lines.append(CardLine(ROW_HEADING, tr("Parameters")))
    lines += [parameter_line(used, version_code) for used in link.params] or [
        CardLine(ROW_NONE, tr("No parameters recorded"))]
    # El recinto, la transición y el ajuste no tienen semillas ni acotado.
    if not area and not transition and not refit:
        lines.append(CardLine(ROW_HEADING, tr("Seeds and domains")))
        lines += (_quarry_seed_lines(request, constraints, names) if quarry else
                  _seed_card(settings, envelope_settings, constraints, names, found.record.name))
    lines.append(CardLine(ROW_HEADING, tr("Applied constraints")))
    lines += _constraint_lines(listed, version_code)
    if found.record.name.startswith(des_views.prefix(design_provenance.CLASSIFICATION_GRID)):
        lines += _legend_lines()  # la clasificación de una cantera: un color por clase
    # La marca también junto a las cifras (RF-013-06): una fila por sector pendiente, antes de ellas;
    # es del estado de ahora y no una cifra (sin ``uid``): las registradas no la llevan.
    figures = [CardLine(ROW_HEADING, tr("Figures")), *marks]
    figures += [CardLine(ROW_FIGURE, f"{provenance.badge(figure.kind)} "
                                     f"{figure.text(language=shown)}", uid=figure.uid)
                for figure in found.figures] or [CardLine(ROW_NONE, tr("No figures recorded"))]
    name = str(settings.get("name") or found.record.name)
    return ItemLines(f"{_family_label(found.record.name)} · {name}", tuple(lines), tuple(figures))


def object_lines(project: Any, obj: Any) -> list[CardLine]:
    """Las líneas más que enseñan «Elemento activo» y «Cifras de la selección» de un objeto
    ``DESIGN`` (``view_panels.register_object_lines``): las de :func:`item_lines`, sin las cifras
    (las de su ficha). Ninguna si el proyecto ya no tiene su dato."""
    uid = str(getattr(getattr(obj, "geoblender", None), "dataset_uid", "") or "")
    try:
        found = item_lines(project, uid) if uid else None
    except ValueError:  # el proyecto se abrió solo con su cabecera: sin rejilla, sin sectores
        LOGGER.info("No se pudieron leer las líneas del diseño de «%s»", getattr(obj, "name", ""),
                    exc_info=True)
        return []
    return [] if found is None else list(found.lines)


def _redraw() -> None:
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _clear_item(shown: Any) -> bool:
    """Olvida el dato de la barra N; dice si había uno."""
    had = bool(shown.item_uid) or len(shown.item) > 0
    if had:
        shown.item_uid = shown.item_project = shown.item_title = ""
        shown.item_found = False
        shown.item.clear()
    return had


def _put_item(shown: Any, uid: str, project_uid: str, found: ItemLines | None) -> None:
    """Deja en la vista lo leído del dato ``uid`` (``None``: el proyecto ya no lo tiene)."""
    shown.item_uid, shown.item_project = uid, project_uid
    shown.item_found = found is not None
    shown.item_title = "" if found is None else found.title
    shown.item.clear()
    for line in () if found is None else (*found.lines, *found.figures):
        row = shown.item.add()
        row.kind, row.name, row.alert, row.uid = line.kind, line.text, line.alert, line.uid


def read_selected(context: Any = None) -> bool:
    """Lee del proyecto de la sesión el dato del objeto de diseño activo (:func:`wanted`) y lo deja en
    ``WindowManager.geoblender_design`` (``item_title`` e ``item``); sin ninguno, o si el proyecto ya
    no lo tiene, lo olvida. No escribe en el proyecto; mientras esta sesión escribe en él o está en
    WAL, no lo lee (lo hará la siguiente lectura de los indicadores). Devuelve si hay un dato. Si no se
    puede leer, lo olvida y lo anota en el registro técnico."""
    shown = view()
    if shown is None:
        return False
    uid = wanted(context)
    project = project_session.current()
    if not uid or project is None:
        changed, found = _clear_item(shown), False
    elif not view_panels.readable(project):
        return bool(shown.item_uid)
    else:
        try:
            read = item_lines(project, uid)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.info("No se pudo leer del proyecto el dato del diseño seleccionado",
                        exc_info=True)
            changed, found = _clear_item(shown), False
        else:
            _put_item(shown, uid, project.uid, read)
            changed, found = True, read is not None
    if changed:
        _redraw()
    return found


def read_selected_safely() -> None:
    """:func:`read_selected` para lo que llama Blender: un fallo va al registro técnico."""
    try:
        read_selected()
    except Exception:  # noqa: BLE001 - lo que llama Blender no lo tumba
        LOGGER.exception("Falló la lectura del dato del diseño seleccionado")


def on_card_read() -> None:
    """Lo que se apunta en ``view_panels.add_card_listener``: se volvió a leer la ficha del objeto
    activo (cambió el objeto, el proyecto o el fichero), así que también este dato."""
    read_selected_safely()


def on_project_changed(_project: Any) -> None:
    """Lo que se apunta en ``project_session``: con otro proyecto (o ninguno), olvida el dato y la
    caché de la comprobación contra el límite vigente (:func:`forget_limit_checks`); con uno nuevo,
    la barra N no lee nada hasta que se selecciona algo."""
    forget_limit_checks()
    shown = view()
    if shown is not None and _clear_item(shown):
        _redraw()


def draw_selected(layout: Any, context: Any) -> None:
    """La barra N «Diseño» (véase el módulo), de lo ya leído: el dato del objeto activo y, mientras
    lo hay, el resumen de la vista previa de las semillas."""
    shown = view()
    if shown is None:
        return
    width = labels.sidebar_width(context)
    uid = wanted(context)
    if uid and shown.item_uid != uid:
        _draw_text(layout, tr("Reading the project data of the active object…"), width)
    elif uid and not shown.item_found:
        _draw_text(layout, tr("The project no longer has the data of this object"), width,
                   alert=True)
    elif uid:
        _draw_text(layout, shown.item_title, width)
        for row in shown.item:
            if row.kind == ROW_HEADING:
                layout.separator()
            sub = layout.column(align=True)
            sub.active = row.kind != ROW_NONE
            _draw_text(sub, row.name, width, alert=bool(row.alert))
        layout.separator()
        export = layout.row()  # exportar no escribe en el proyecto: vale también en solo lectura
        export.operator(EXPORT_GRID, text=_label(EXPORT_GRID), icon="EXPORT", translate=False)
    if len(shown.preview):
        if uid:
            layout.separator()
        _draw_text(layout, tr("Preview of the seeds"), width)
        for row in shown.preview:
            _draw_text(layout, row.name, width, alert=bool(row.alert))


class GEOBLENDER_PT_des_design(bpy.types.Panel):
    """The design shown by the active object: state, parameters, seeds, domain, constraints and
    figures, or the summary of the preview of the seeds"""

    bl_idname = SELECTED_PANEL
    bl_label = SELECTED_TAB
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = SELECTED_TAB

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(wanted(context)) or has_preview()

    def draw(self, context: Any) -> None:
        draw_selected(self.layout, context)


def localize() -> None:
    """La pestaña y el título de la barra N «Diseño» en el idioma de la interfaz (antes de
    registrar, y otra vez al cambiar el idioma)."""
    GEOBLENDER_PT_des_design.bl_category = tr("Design")
    GEOBLENDER_PT_des_design.bl_label = tr("Design")


# En orden de registro (las listas, antes de la ventana que las dibuja).
classes: tuple[type, ...] = (GEOBLENDER_UL_des_profiles, GEOBLENDER_PT_des_profiles,
                             GEOBLENDER_UL_des_sectors, GEOBLENDER_PT_des_sectors,
                             GEOBLENDER_PT_des_design)


def install() -> None:
    """Pone la escucha de los indicadores (:func:`on_project_read`) y las de la barra N «Diseño»: la
    ficha del objeto activo, el proyecto de la sesión y las líneas más de «Elemento activo» y
    «Cifras de la selección» de los objetos ``DESIGN``; y la comprobación de las superficies de la
    014 en el resumen de cada compilación de las máscaras, por pasos (:func:`limit_steps`);
    idempotente."""
    provenance.add_change_listener(on_project_read)
    view_panels.add_card_listener(on_card_read)
    view_panels.register_object_lines(des_views.KIND, object_lines)
    project_session.add_listener(on_project_changed)
    constraint_panels.add_compile_check(limit_steps)


def uninstall() -> None:
    """Quita lo que puso :func:`install`, olvida el dato de la barra N, las listas del diálogo de
    las envolventes y la caché de la comprobación contra el límite vigente, y quita su
    temporizador; idempotente."""
    constraint_panels.remove_compile_check(limit_steps)
    forget_limit_checks()
    if bpy.app.timers.is_registered(limit_tick):
        bpy.app.timers.unregister(limit_tick)
    project_session.remove_listener(on_project_changed)
    view_panels.unregister_object_lines(des_views.KIND, object_lines)
    view_panels.remove_card_listener(on_card_read)
    provenance.remove_change_listener(on_project_read)
    shown = view()
    if shown is not None:
        _clear_item(shown)
    forget_choices()
