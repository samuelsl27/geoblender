# SPDX-License-Identifier: GPL-3.0-or-later
"""Las propiedades de los límites y las restricciones (spec 012, T21, T22; RF-012-05,
RF-012-19, RF-012-28; plan 012 §5.1 y §5.2.4).

``WindowManager.geoblender_constraints`` (:class:`GEOBLENDER_PG_core_constraints`) guarda lo
que dibujan las ventanas Límites, Restricciones, Buscar elementos intocables por sector,
Intenciones del cliente y Verificación, y la barra N «Restricción»: las restricciones ya leídas
(código, nombre, tipo, estado, parámetros resueltos en la versión activa, últimas cifras), la
activa y sus filtros, los sectores y su búsqueda, y las verificaciones de la versión. Es una
**vista** que se regenera desde el proyecto, nunca la fuente (nada se lee al dibujar, como la 008
y la 010); vive en ``WindowManager``, que Blender no guarda en el ``.blend``.

**Límites…** (T22): las capas de polígonos del proyecto con sus dos casillas
(:class:`GEOBLENDER_PG_core_layer_choice`: límite legal y perímetro de actuación), los campos
del formulario (el campo del nombre, el motivo, el decisor, la fecha y el resguardo hacia dentro,
todos en texto) y las líneas del informe de los límites
(:class:`GEOBLENDER_PG_core_report_line`: cada una con su texto ya traducido y, la de una parte
de la franja, el lugar al que lleva «Ir a»).

**Restricciones…** (T23): las restricciones ya leídas (:class:`GEOBLENDER_PG_core_constraint_item`:
su nombre, tipo, estado en la versión activa, lo que le falta, motivo, decisor, fecha y sus
parámetros con su valor en la versión y en el proyecto, :class:`GEOBLENDER_PG_core_param_line`), la
elegida, el filtro de las que tienen problemas, las capas de las que se pueden crear y el último
resultado de crear, compilar o exportar (``report_lines``).

**Buscar elementos intocables por sector…** (T24): los sectores de búsqueda con su estado
(:class:`GEOBLENDER_PG_core_sector_item`: vigente o pendiente), el elegido, la capa de
polígonos y el campo con que se declaran, las capas «entidades» que se pueden consultar con su
casilla (:class:`GEOBLENDER_PG_core_search_layer`), la distancia de búsqueda tal como se lee, lo
hallado por la búsqueda abierta con la decisión de cada entidad
(:class:`GEOBLENDER_PG_core_hit_item`), quién cierra la búsqueda y su último resultado
(``search_lines``).

**Intenciones del cliente…** (T25): las intenciones guardadas
(:class:`GEOBLENDER_PG_core_intention_item`: su papel, su geometría, su cota, su fecha, su
documento, su capa, su decisión y las restricciones que salieron de ellas), la elegida, las capas
«entidades», los documentos y las decisiones de la propiedad que se pueden elegir
(:class:`GEOBLENDER_PG_core_pick`), los campos del formulario para guardar las marcas de una capa
(``mark_*``, todos en texto salvo el papel) y su último resultado (``mark_lines``).

**Ver restricciones y límites** (T26): ``WindowManager.geoblender_constraints_overlay`` es el
control 30 como propiedad (se lee y se escribe: activa o quita la superposición de
``bl.draw.constraints``, que importa al activarla); y la vista guarda la superficie sobre la que se
dibuja (``overlay_surface``, el nombre de su dato; vacío: la rejilla más reciente del proyecto) y
las que se pueden elegir (``overlay_surfaces``).

**La restricción seleccionada** (T27; RF-012-19): ``selected`` (una
:class:`GEOBLENDER_PG_core_constraint_item` como las de la lista) y ``selected_lines`` (las líneas
de su última verificación) son lo que dibuja la barra N «Restricción»; la regenera
``bl.ui.constraint_panels`` al cambiar el objeto activo, la restricción elegida en la lista o la
versión activa, nunca al dibujar. Elegir otra fila de la lista (``item_index``) avisa a ese
módulo.

Ninguna propiedad es una coordenada ni una distancia en ``FloatProperty`` (ADR-0005; los
resguardos, los pesos, las distancias y los espesores de los diálogos, en ``StringProperty``:
``docs/trampas.md`` §1; las coordenadas absolutas de «Ir a», también en texto).
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from ...core.constraints.model import IntentionRole

WINDOW_MANAGER_PROPERTY = "geoblender_constraints"
"""El nombre de la propiedad de ``WindowManager`` (la usan las ventanas de las restricciones)."""
OVERLAY_PROPERTY = "geoblender_constraints_overlay"
"""El de la propiedad de ``WindowManager`` de «Ver restricciones y límites» (control 30)."""
_OVERLAY_MODULE = f"{__package__.rpartition('.')[0]}.draw.constraints"
_PANELS_MODULE = f"{__package__.rpartition('.')[0]}.ui.constraint_panels"
MARK_FIELD = "FIELD"
"""El valor de ``mark_role`` cuando el papel de cada marca lo da un campo de la capa."""
MARK_ROLE_ITEMS = [(MARK_FIELD, "From a field of the layer", ""),
                   *[(role.name, role.label_msgid, "") for role in IntentionRole]]
"""Los valores de ``mark_role``: el campo de la capa o uno de los seis papeles para todas."""
_STATIC: set[str] = set()  # ni animable ni nada más


def _get_overlay(_self: Any) -> bool:
    """Si la superposición de las restricciones está activa (sin importarla si no lo está)."""
    module = sys.modules.get(_OVERLAY_MODULE)
    return bool(module is not None and module.enabled())


def _set_overlay(_self: Any, value: bool) -> None:
    """Activa o quita la superposición de las restricciones (la importa al activarla)."""
    if value:
        importlib.import_module(_OVERLAY_MODULE).enable()
        return
    module = sys.modules.get(_OVERLAY_MODULE)
    if module is not None:
        module.disable()


def _surface_changed(_self: Any, _context: Any) -> None:
    """Se eligió otra superficie: con la superposición activa, la rehace."""
    module = sys.modules.get(_OVERLAY_MODULE)
    if module is not None:
        module.on_surface_changed()


def _chosen_changed(_self: Any, _context: Any) -> None:
    """Se eligió otra restricción en la lista de Restricciones…: la barra N la sigue (si no hay un
    objeto de restricción activo)."""
    module = sys.modules.get(_PANELS_MODULE)
    if module is not None:
        module.on_chosen_changed()


class GEOBLENDER_PG_core_layer_choice(bpy.types.PropertyGroup):
    """Una capa de polígonos del proyecto que ofrece Límites…: su dato (``name``) y si es un
    límite legal o el perímetro de actuación."""

    legal: BoolProperty(  # type: ignore[valid-type]
        default=False, options=_STATIC,
        description="Use this layer as (part of) the legal limit")
    perimeter: BoolProperty(  # type: ignore[valid-type]
        default=False, options=_STATIC,
        description="Use this layer as the action perimeter")


class GEOBLENDER_PG_core_report_line(bpy.types.PropertyGroup):
    """Una línea del informe de los límites, ya traducida: su texto, si va en alerta y, si lleva
    «Ir a», el lugar (``x`` e ``y`` absolutas y el radio en metros, en texto: ADR-0005)."""

    text: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    alert: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]
    x: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    y: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    radius: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_param_line(bpy.types.PropertyGroup):
    """Un parámetro de una restricción en la versión activa: su clave (``key``), su valor en la
    versión y en el proyecto ya como se lee (``text``: «V01: 8 m [ADO] · proyecto: —») y si está
    registrado (``registered``: sin registrar no se puede cambiar, se completa). El nombre del
    parámetro, en ``name``."""

    key: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    text: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    registered: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_constraint_item(bpy.types.PropertyGroup):
    """Una restricción de la lista de Restricciones… (RF-012-19), ya leída del proyecto: su nombre
    (``name``), su ``uid`` y su código, el tipo (``ctype``, el valor de ``ConstraintType``;
    vacío si no tiene), la geometría (``kind``) y la capa y el ``fid`` donde está, su estado en
    la versión activa (``state``: ``incomplete``, ``invalid``, ``active`` o ``inactive``) con lo
    que le falta (``problems``, un texto por línea), la prioridad, el motivo, el decisor, la fecha
    (DD/MM/AAAA) y la decisión enlazada, y sus parámetros. Todo en texto o entero: ninguna
    coordenada (ADR-0005)."""

    uid: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    code: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    ctype: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    kind: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    layer: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    fid: IntProperty(default=0, options=_STATIC)  # type: ignore[valid-type]
    state: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    problems: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    priority: IntProperty(default=0, options=_STATIC)  # type: ignore[valid-type]
    reason: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    decided_by: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    decided_on: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    decision: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    parameters: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_param_line)


class GEOBLENDER_PG_core_sector_item(bpy.types.PropertyGroup):
    """Un sector de búsqueda de intocables (RF-012-07, RF-012-09): su nombre (``name``), su
    código (vacío: el perímetro de actuación como único sector), si tiene una búsqueda vigente y
    lo que se dice de ella (``text``: «Búsqueda pendiente» o «Búsqueda vigente, cerrada por …»)."""

    code: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    current: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]
    text: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_search_layer(bpy.types.PropertyGroup):
    """Una capa «entidades» del proyecto que se puede consultar en una búsqueda (``name``: su
    dato), su geometría (``kind``: ``point``, ``line`` o ``polygon``) y si se consulta."""

    kind: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    use: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_hit_item(bpy.types.PropertyGroup):
    """Una entidad hallada por la búsqueda abierta (RF-012-08): cómo se nombra (``name``), su
    capa (el dato) y su número, su geometría, su distancia al sector (m, en texto), sus
    atributos (``details``, un campo por línea), su decisión (``state``: ``pending``,
    ``converted`` o ``discarded``), el motivo de esa decisión y, si se convirtió, el código de la
    restricción. Todo en texto o entero: ninguna coordenada (ADR-0005)."""

    layer: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    fid: IntProperty(default=0, options=_STATIC)  # type: ignore[valid-type]
    kind: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    distance: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    details: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    state: StringProperty(default="pending", options=_STATIC)  # type: ignore[valid-type]
    reason: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    constraint: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_pick(bpy.types.PropertyGroup):
    """Algo que se elige por su nombre en una lista (RF-012-26): una capa «entidades» del
    proyecto (``name``: su dato; ``kind``: ``point``, ``line`` o ``polygon``), un documento
    (``name``; ``uid``: el de su entrada) o una decisión de la propiedad (``name``: cómo se lee;
    ``uid``: el suyo)."""

    uid: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    kind: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_intention_item(bpy.types.PropertyGroup):
    """Una intención del cliente de la lista de Intenciones del cliente… (RF-012-26,
    RF-012-27), ya leída del proyecto: su nombre (``name``), su ``uid``, su papel (``role``, el
    valor de ``IntentionRole``) y su geometría (``kind``), su cota en metros (``elevation``,
    vacía si el papel no la pide), su fecha (DD/MM/AAAA), el nombre de su documento y de su capa,
    su decisión enlazada ya escrita y los códigos de las restricciones que salieron de ella
    (``converted``, separados por comas). Todo en texto: ninguna coordenada (ADR-0005)."""

    uid: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    role: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    kind: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    elevation: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    stated_on: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    document: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    source: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    decision: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    converted: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_constraints(bpy.types.PropertyGroup):
    """Lo que dibujan las ventanas de las restricciones (una vista; véase el módulo)."""

    constraints: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_constraint_item)
    item_index: IntProperty(  # type: ignore[valid-type]
        default=0, min=0, options=_STATIC, update=_chosen_changed)
    selected: PointerProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_constraint_item, options=_STATIC)
    selected_lines: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_report_line)
    only_problems: BoolProperty(  # type: ignore[valid-type]
        default=False, options=_STATIC,
        description="Show only the constraints that are incomplete or not valid")
    report_lines: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_report_line)
    source_layers: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_layer_choice)
    limit_layers: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_layer_choice)
    limit_name_field: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Field of the layers that gives the name of each limit; without it, the "
                    "name of the layer")
    limit_reason: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Why these limits are the ones in force (title, concession, decision)")
    limit_decided_by: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, description="Who decides that these are the limits")
    limit_decided_on: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, description="Date of the decision, as DD/MM/YYYY")
    limit_inward: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Distance in metres, inside the legal limit, where cutting is not allowed")
    limit_lines: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_report_line)
    # Buscar elementos intocables por sector… (T24)
    sectors: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_sector_item)
    sector_index: IntProperty(default=0, min=0, options=_STATIC)  # type: ignore[valid-type]
    sector_sources: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_layer_choice)
    sector_layer: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Layer of polygons of the project that gives the search sectors")
    sector_field: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Field of that layer that names each sector")
    search_layers: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_search_layer)
    search_distance: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    search_distance_set: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]
    hits: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_hit_item)
    hit_index: IntProperty(default=0, min=0, options=_STATIC)  # type: ignore[valid-type]
    search_title: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    search_decided_by: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, description="Who closes the search")
    search_lines: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_report_line)
    # Intenciones del cliente… (T25)
    intentions: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_intention_item)
    intention_index: IntProperty(default=0, min=0, options=_STATIC)  # type: ignore[valid-type]
    mark_layers: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_pick)
    mark_documents: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_pick)
    mark_decisions: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_pick)
    mark_layer: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Layer of features of the project whose entities are the marks of the "
                    "client")
    mark_role: EnumProperty(  # type: ignore[valid-type]
        items=MARK_ROLE_ITEMS, default=MARK_FIELD, options=_STATIC,
        description="The role of all the marks, or the field of the layer that gives the role "
                    "of each one")
    mark_role_field: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Field of the layer that says the role of each mark")
    mark_role_values: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Which role each value of the field means, as «value = role; value = role» "
                    "(empty: the value is the name of the role)")
    mark_name_field: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Field of the layer that gives the name of each mark (empty: the name of "
                    "the layer)")
    mark_elevation_field: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Field of the layer that gives the elevation of the marks «Mine to an "
                    "elevation»")
    mark_elevation: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Elevation in metres of all the marks «Mine to an elevation» (empty: the "
                    "field gives it)")
    mark_date_field: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Field of the layer that gives the date of each mark, as YYYY-MM-DD")
    mark_date: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="Date of all the marks, as DD/MM/YYYY (empty: the field gives it)")
    mark_document: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="The document of the client the marks come from, registered as an input "
                    "of type document")
    mark_decision: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC,
        description="The decision of the owner the marks rest on (optional)")
    mark_lines: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_report_line)
    overlay_surface: StringProperty(  # type: ignore[valid-type]
        default="", options=_STATIC, update=_surface_changed,
        description="Surface of the project the constraints are drawn on over the 3D view "
                    "(empty: the most recent grid of the project)")
    overlay_surfaces: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_pick)


classes: tuple[type, ...] = (GEOBLENDER_PG_core_layer_choice, GEOBLENDER_PG_core_report_line,
                             GEOBLENDER_PG_core_param_line, GEOBLENDER_PG_core_constraint_item,
                             GEOBLENDER_PG_core_sector_item, GEOBLENDER_PG_core_search_layer,
                             GEOBLENDER_PG_core_hit_item, GEOBLENDER_PG_core_pick,
                             GEOBLENDER_PG_core_intention_item, GEOBLENDER_PG_core_constraints)


def register() -> None:
    """Pone ``WindowManager.geoblender_constraints`` (las clases ya están registradas) y
    ``WindowManager.geoblender_constraints_overlay`` (T26)."""
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_core_constraints, options=_STATIC))
    setattr(bpy.types.WindowManager, OVERLAY_PROPERTY, BoolProperty(
        name="Show constraints and limits", get=_get_overlay, set=_set_overlay,
        options={"SKIP_SAVE"},
        description="Show the constraints and the limits over the 3D view while designing"))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_constraints`` y ``geoblender_constraints_overlay`` (antes
    de desregistrar las clases); sin ellas, nada."""
    for name in (OVERLAY_PROPERTY, WINDOW_MANAGER_PROPERTY):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
