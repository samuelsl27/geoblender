# SPDX-License-Identifier: GPL-3.0-or-later
"""La corta por bancos en Blender: «Nueva corta…» (spec 018, T31; HU-018-1, HU-018-3; RF-018-34, RF-018-35, RF-018-19, RF-018-32, RF-015-28; plan 018 §5.3.3 y §5.5; comprobación manual M1).

:class:`GEOBLENDER_OT_des_create_pit` (``geoblender.des_create_pit``) calcula con ``design.steps.pit_run`` la operación ``des.pit`` de la versión activa y, al confirmar, la crea. Su
diálogo pide el nombre y el modo; la capa de origen con sus campos; los perfiles (el base y los de cada sector), la roseta y los bancos por berma; las rampas, las zonas sin rampa y los
bancos fijados; los criterios de parada; la partida y el apoyo; y las tolerancias del desfase, cada una con su tipo. Todo lo demás es del patrón de la 017 (``bl.ops.des``): «Calcular» deja
el cálculo abierto con su resumen y **nada escrito** (RF-015-03); «Crear» registra en una transacción (por pasos desde la interfaz) y encadena la capa de entidades y las de la corta; Esc,
Cancelar y cerrar el proyecto no dejan nada (RF-015-29, RF-018-35). Con la pendiente media de una rampa por encima de pm **no se crea sin la confirmación expresa y su motivo** (RF-018-19: el
botón se llama «Confirmar y crear»). «Vista previa» (RF-018-32) enseña lo pedido antes de calcular y lo calculado después, sin escribir.

Los valores decimales, en ``StringProperty`` (regla 4: nada de float32). Los perfiles, las rosetas y las rampas se eligen de las listas del proyecto (:func:`refresh_pit_choices`); las
asignaciones por sector se escriben ``sector=valor`` separadas por «;». Lo que se deja vacío lo resuelve el dominio: el valor por defecto de su parámetro o, si no lo tiene, el rechazo de
RF-015-08 con su nombre. Un diálogo a medias no activa la vista previa ni escribe nada.

Las demás órdenes de la corta («Expandir banco…», «Rampa…», «Roseta de taludes…», «Línea de cielo…» y «Superficie y sólido…») son de las tareas T32 y T33; las provisionales del catálogo
(``des_expand_bench``, ``des_add_ramp``, ``des_compute_daylight``) las sustituyen ellas."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.project.model import Progress
from ...core.timeutil import format_utc
from ...design import messages as design_messages
from ...design import provenance
from ..scene import versions as scene_versions
from ..ui import constraint_panels, des_panels
from ..ui.commands import catalog, command_idname
from ..ui.commands import text as command_text
from ..ui.res_panels import NOT_SHOWN
from . import surface_proposal
from .core import _StepsModal
from .core_provenance import SESSION, ProvenanceAwareOperator, ensure_ready, write_unavailable
from .des import (
    DIALOG_WIDTH,
    TRANSLATION_CONTEXT,
    ComputeFormError,
    DesignCommandAware,
    ProfileFormError,
    _ask_confirmation,
    _CalculateAndCreate,
    _ChainsEntityLayer,
    _ClearsEntityPreview,
    _CreatesInSteps,
    _draw_entity_preview_button,
    _entity_preview,
    _entity_preview_loaded,
    _entity_preview_off,
    _FIELD,
    _HIDDEN,
    discard_calculation,
    calculation,
    design_error_text,
    typed_number,
)

if TYPE_CHECKING:  # solo para los tipos: habilitar no importa el cálculo (RNF-001-03)
    from ...design.steps import Calculation

LOGGER = logging.getLogger("geoblender.bl.ops")
CREATE_PIT = provenance.PIT_COMMAND
"""La orden de «Nueva corta…»."""
PIT_MODE_ITEMS = [
    ("UP", "Ascending", "From one or more floors, each at its elevation: the benches rise outwards until they come out at the ground"),
    ("DOWN", "Descending", "From one or more limits, whose crest follows the ground or is at an elevation: the benches go down inwards until a stop criterion")]
"""Los modos de una corta (RF-018-02)."""
PIT_CORNER_ITEMS = [
    ("DEFAULT", "By default", "The corner of the default value of the parameter (rounded: adopted, unconfirmed)"),
    ("ROUND", "Rounded", "The corners are rounded with arcs"),
    ("MITER", "Mitred", "The corners are kept sharp, mitred")]
"""La esquina del desfase (RF-018-10, D-14)."""
_PIT_HIDDEN = frozenset({"confirm", "in_steps", "preview", "confirm_mean", "code"})
"""Las propiedades ocultas del diálogo: las pone quien lo lanza (el botón de su ventana)."""
_NONE = des_panels.NO_ZONE
"""El identificador de «ninguno» de las listas opcionales (el mismo que usa «Plataforma…»)."""


# --- Las listas del diálogo -------------------------------------------------------------------------


@dataclass
class _Choices:
    """Las listas vivas del diálogo (los ``items`` de un ``EnumProperty`` han de seguir vivos): lo que leyó :func:`refresh_pit_choices`; sin proyecto, «—»."""

    layers: list[tuple[str, str, str]] = field(default_factory=list)
    noramp: list[tuple[str, str, str]] = field(default_factory=list)
    fixed: list[tuple[str, str, str]] = field(default_factory=list)
    profiles: list[tuple[str, str, str]] = field(default_factory=list)
    roses: list[tuple[str, str, str]] = field(default_factory=list)
    ramps: list[tuple[str, str, str]] = field(default_factory=list)


_CHOICES = _Choices()


def _fixed_choices() -> None:
    """Las listas sin nada del proyecto: «—» (o «ninguno»)."""
    _CHOICES.layers = [(_NONE, NOT_SHOWN, tr("There are no layers of polygons in the project"))]
    _CHOICES.noramp = [(_NONE, tr("No zones without a ramp"), tr("The ramps may start anywhere"))]
    _CHOICES.fixed = [(_NONE, tr("No fixed benches"), tr("No bench is fixed to a line of the project"))]
    _CHOICES.profiles = [(_NONE, NOT_SHOWN, tr("There are no bench profiles in the project"))]
    _CHOICES.roses = [(_NONE, tr("No rose"), tr("The benches have the face of the bench profile"))]
    _CHOICES.ramps = []


def _version_layers(project: Any, version_uid: str, prefix: str) -> list[str]:
    """Los nombres de los datos vigentes de la versión ``version_uid`` que empiezan por ``prefix`` (las rutas propuestas y los bancos expandidos). Solo lee."""
    from ...core.datasets.model import DatasetStatus  # al usarlo: habilitar no lo carga

    with project.read() as conn:
        rows = conn.execute("SELECT name FROM gb_dataset WHERE version_uid = ? AND status = ? ORDER BY name", (version_uid, DatasetStatus.CURRENT.value)).fetchall()
    return [str(name) for (name,) in rows if str(name).startswith(prefix)]


def refresh_pit_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` las listas del diálogo de «Nueva corta…» (plan 018 §5.3.3): las capas de **polígonos** (los fondos o los límites y las zonas sin rampa), las de **líneas
    con Z** que valen como bancos fijados (las líneas de rotura del proyecto, las rutas propuestas y los bancos expandidos de la versión activa), los **perfiles de banco**, las **rosetas** y
    las **rampas**. Se llama tras ``des_panels.refresh_choices`` y ``refresh_platform_choices`` (las superficies). Si no se puede leer, el error sigue."""
    from ...design import pit_ramp_def, pit_rose  # al usarlo: habilitar no carga el cálculo
    from ...design import profiles as design_profiles
    from ...gis import provenance as gis_provenance
    from ...gis import store as gis_store

    _fixed_choices()
    found = constraint_panels.search_layers(project)
    polygons = [name for name, kind in found if kind == "polygon"]
    if polygons:
        _CHOICES.layers = [(name, constraint_panels.layer_label(name), tr("Layer of polygons")) for name in polygons]
        _CHOICES.noramp = [*_CHOICES.noramp, *_CHOICES.layers]
    fixed = [(record.name, constraint_panels.layer_label(record.name), tr("Layer of 3D lines"))
             for record in gis_store.list_gis_datasets(project, families=(gis_provenance.BREAKLINES,))]
    version = scene_versions.active()
    if version is not None:
        for code, label in ((provenance.ROUTE_LAYER_TABLE, tr("Proposed route of the active version (3D lines)")),
                            (provenance.PIT_EXPANDED_TABLE, tr("Expanded bench of the active version (3D lines)"))):
            prefix = provenance.FAMILIES_BY_CODE[code].prefix
            fixed.extend((name, name.removeprefix(prefix), label) for name in _version_layers(project, version.uid, prefix))
    _CHOICES.fixed = [*_CHOICES.fixed, *fixed]
    with project.read() as conn:
        profiles = design_profiles.read_profiles(conn)
        roses = pit_rose.read_roses(conn)
        ramps = pit_ramp_def.read_ramps(conn)
    if profiles:
        _CHOICES.profiles = [(_NONE, tr("No base profile"), tr("Every sector has its own profile")), *((item.code, item.name, tr("Bench profile")) for item in profiles)]
    _CHOICES.roses = [*_CHOICES.roses, *((item.code, item.name, tr("Rose of design slopes")) for item in roses)]
    _CHOICES.ramps = [(item.code, item.name, tr("Ramp definition")) for item in ramps]


def pit_layer_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas de polígonos de origen de la corta (una lista viva del módulo); sin ninguna, «—»."""
    if not _CHOICES.layers:
        _fixed_choices()
    return _CHOICES.layers


def pit_noramp_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """«Ninguna» y las capas de polígonos (las zonas sin rampa)."""
    if not _CHOICES.noramp:
        _fixed_choices()
    return _CHOICES.noramp


def pit_fixed_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """«Ninguna» y las capas de líneas con Z que valen como bancos fijados."""
    if not _CHOICES.fixed:
        _fixed_choices()
    return _CHOICES.fixed


def pit_profile_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Los perfiles de banco del proyecto (su código y su nombre); «ninguno» si todo sector lleva el suyo."""
    if not _CHOICES.profiles:
        _fixed_choices()
    return _CHOICES.profiles


def pit_rose_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """«Ninguna» y las rosetas de taludes de diseño del proyecto."""
    if not _CHOICES.roses:
        _fixed_choices()
    return _CHOICES.roses


def pit_ramp_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las definiciones de rampa del proyecto (sin ninguna, la lista está vacía: no se elige)."""
    return _CHOICES.ramps


# --- La petición ------------------------------------------------------------------------------------


def _whole(typed: str, label: str) -> int | None:
    """Un número entero tecleado (``None`` si está vacío): :class:`ProfileFormError` si no lo es, nombrando el campo y lo tecleado."""
    number = typed_number(typed, label)
    if number is None:
        return None
    if number != int(number):
        raise ProfileFormError(tr("«{value}» is not a whole number (field «{field}»)", value=typed.strip(), field=label))
    return int(number)


def _pairs(text: str, label: str, cast: Any) -> tuple[tuple[str, Any], ...]:
    """Las asignaciones por sector ``sector=valor`` separadas por «;» de ``text`` (``cast``: cómo se lee el valor): :class:`ProfileFormError` si una no tiene esa forma."""
    found: list[tuple[str, Any]] = []
    for part in text.replace("\n", ";").split(";"):
        if not part.strip():
            continue
        sector, equals, value = part.partition("=")
        if not equals or not sector.strip() or not value.strip():
            raise ProfileFormError(tr("«{value}» is not of the form sector=value (field «{field}»)", value=part.strip(), field=label))
        found.append((sector.strip(), cast(value.strip(), label)))
    return tuple(found)


def _text(value: str, _label: str) -> str:
    return value


def _tolerance_rows() -> tuple[tuple[str, str], ...]:
    """Las cuatro tolerancias del desfase con su tipo (RF-018-10, D-14, D-15, P-5): la propiedad del diálogo y su parámetro (``des.pit.{e}.*``). Las cuatro son HIPÓTESIS sin valor por
    defecto (el diálogo dice el tipo de cada una)."""
    return (("arc_tol", "arc_tol_m"), ("simplify", "simplify_m"), ("close_radius", "close_radius_m"), ("az_window", "az_window_m"))


def _pit_param_text(param: str) -> str:
    """El tipo (y, si lo tiene, el valor por defecto) del parámetro ``param`` de una corta, como lo dicen los diálogos de la 017 (``des._entity_param_text``)."""
    from .des import _entity_param_text

    return _entity_param_text("pit", param)


def _pit_fields() -> tuple[str, ...]:
    """Los campos del diálogo que pasan a su vista previa: sus propiedades no ocultas (la del motivo de la pendiente media es de la confirmación)."""
    return tuple(name for name in GEOBLENDER_OT_des_create_pit.__annotations__ if name not in _PIT_HIDDEN and name != "mean_reason")


def _refresh_pit_preview(self: Any, _context: Any) -> None:
    """El ``update`` de cada campo de «Nueva corta…» (RF-018-32, RF-015-26): con la vista previa **de esa corta** activa (la de una corta de la versión no), la redibuja con lo que dice
    ahora el diálogo. Un diálogo a medias (un campo sin escribir, un número que no lo es) no la cambia: sigue la última completa. Solo lee."""
    loaded = _entity_preview_loaded()
    if loaded is None or not loaded.enabled() or loaded.plan() is None or loaded.plan().pit is None or loaded.plan().pit.request is None:
        return
    from ...design.preview import PitAsk  # al usarlo: habilitar no carga el cálculo

    try:
        request = GEOBLENDER_OT_des_create_pit._request(self)
    except (ProfileFormError, GeoblenderError, sqlite3.Error, OSError, ValueError):
        return
    if loaded.plan().pit.request == request:
        return  # lo mismo que ya se dibuja (lo repite cada dibujo del diálogo al copiar sus campos al botón): no se reconstruye
    loaded.replace(loaded.EntityPlan(pit=PitAsk(request=request)))


def _show_calculated_preview(opened: Any) -> None:
    """Con la vista previa **de esta corta** activa, la cambia por la de lo que dejó «Calcular» (``opened``: el cálculo abierto): las polilíneas por banco, la línea de cielo, el eje
    de las rampas y los hallazgos (T29). Solo lee."""
    loaded = _entity_preview_loaded()
    if loaded is None or not loaded.enabled() or loaded.plan() is None or loaded.plan().pit is None or loaded.plan().pit.request is None:
        return
    from ...design.preview import PitAsk  # al usarlo: habilitar no carga el cálculo

    loaded.replace(loaded.EntityPlan(pit=PitAsk(request=opened.entity.job.request, prepared=opened.entity, outcome=opened.outcome)))


class GEOBLENDER_OT_des_create_pit(_ClearsEntityPreview, _CreatesInSteps, _ChainsEntityLayer, _CalculateAndCreate, DesignCommandAware, ProvenanceAwareOperator, _StepsModal,
                                   bpy.types.Operator):
    """Pit by benches of the active version: from the floors (ascending) or from the limits (descending), with its bench profiles, rose, ramps and stop criteria; its benches, its skyline and its design surface"""

    bl_idname = CREATE_PIT
    bl_label = "New pit…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PIT
    COMMAND = CREATE_PIT

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the pit, unique in the active version", options=_FIELD)
    mode: EnumProperty(  # type: ignore[valid-type]
        name="Mode", description="Ascending: from the floors of the layer, each at its elevation. Descending: from the limits of the layer, whose crest follows the ground or is at an elevation",
        items=PIT_MODE_ITEMS, default="UP", options=_FIELD, update=_refresh_pit_preview)
    layer: EnumProperty(  # type: ignore[valid-type]
        name="Source layer", description="Layer of polygons of the project the pit is taken from: its floors (ascending) or its limits (descending)",
        items=pit_layer_items, options=_FIELD, update=_refresh_pit_preview)
    name_field: StringProperty(  # type: ignore[valid-type]
        name="Name field", description="Field of the layer with the name of each polygon (empty: the field «nombre» or «name» or, without it, the number (fid))", options=_FIELD,
        update=_refresh_pit_preview)
    level_field: StringProperty(  # type: ignore[valid-type]
        name="Elevation field", description="Field of the layer with the elevation of the floor of each polygon, in metres (ascending: each floor at its elevation)", options=_FIELD,
        update=_refresh_pit_preview)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface", description="Surface the pit starts from: by default, the last of the chain of the active version and, without it, the ground",
        items=des_panels.platform_start_items, options=_FIELD, update=_refresh_pit_preview)
    support: EnumProperty(  # type: ignore[valid-type]
        name="Support surface", description="Surface the pit rests on, if it rests on one (none: it rests on no other surface)", items=des_panels.platform_support_items, options=_FIELD,
        update=_refresh_pit_preview)
    profile: EnumProperty(  # type: ignore[valid-type]
        name="Bench profile", description="Base bench profile of the pit: its height, face angle, berm and anchor; create or complete them with «Bench profiles…»",
        items=pit_profile_items, options=_FIELD, update=_refresh_pit_preview)
    rose: EnumProperty(  # type: ignore[valid-type]
        name="Rose of slopes", description="Rose of design slopes: the face angle and the berm by the direction of the face of each stretch of the bench (none: the bench profile alone)",
        items=pit_rose_items, options=_FIELD, update=_refresh_pit_preview)
    n_berm: StringProperty(  # type: ignore[valid-type]
        name="Benches per berm", description="Whole number of benches between two berms (empty: the default value, one bench)", options=_FIELD, update=_refresh_pit_preview)
    sector_profiles: StringProperty(  # type: ignore[valid-type]
        name="Profiles by sector", description="Bench profile of each design sector, written sector=profile and separated by «;» (the sector by its code; the profiles must have the same height and anchor)",
        options=_FIELD, update=_refresh_pit_preview)
    sector_roses: StringProperty(  # type: ignore[valid-type]
        name="Roses by sector", description="Rose of design slopes of each design sector, written sector=rose and separated by «;»", options=_FIELD, update=_refresh_pit_preview)
    sector_n_berm: StringProperty(  # type: ignore[valid-type]
        name="Benches per berm by sector", description="Benches per berm of each design sector, written sector=number and separated by «;» (they must agree with the one of the pit)",
        options=_FIELD, update=_refresh_pit_preview)
    ramps: EnumProperty(  # type: ignore[valid-type]
        name="Ramps", description="Ramp definitions the pit has: each one joins the floor with the surface; define them with «Ramp…»", items=pit_ramp_items,
        options={"ENUM_FLAG", "SKIP_SAVE"}, update=_refresh_pit_preview)
    noramp: EnumProperty(  # type: ignore[valid-type]
        name="Zones without a ramp", description="Layer of polygons with the zones where no ramp may pass (none: no zone)", items=pit_noramp_items, options=_FIELD,
        update=_refresh_pit_preview)
    fixed: EnumProperty(  # type: ignore[valid-type]
        name="Fixed benches", description="Layer of 3D lines (breaklines, proposed routes or expanded benches) whose closed lines are benches kept as they are (none: no fixed bench)",
        items=pit_fixed_items, options=_FIELD, update=_refresh_pit_preview)
    fixed_field: StringProperty(  # type: ignore[valid-type]
        name="Bench field", description="Field of the layer of fixed benches with the number of the bench of each line (empty: the bench is the one at the elevation of the line)",
        options=_FIELD, update=_refresh_pit_preview)
    top_level: StringProperty(  # type: ignore[valid-type]
        name="Crest elevation (m)", description="Elevation of the crest of the pit in metres: the benches do not rise above it (empty: they follow the ground); a stop criterion without default value",
        options=_FIELD, update=_refresh_pit_preview)
    bottom_level: StringProperty(  # type: ignore[valid-type]
        name="Floor elevation (m)", description="Elevation in metres of the floor where the descending pit stops (empty: another criterion); a stop criterion without default value", options=_FIELD,
        update=_refresh_pit_preview)
    max_benches: StringProperty(  # type: ignore[valid-type]
        name="Maximum number of benches", description="Whole number of benches where the descending pit stops (empty: another criterion); a stop criterion without default value", options=_FIELD,
        update=_refresh_pit_preview)
    min_floor_width: StringProperty(  # type: ignore[valid-type]
        name="Minimum width of the floor (m)", description="Width in metres of the floor under which the descending pit stops (empty: another criterion); a stop criterion without default value",
        options=_FIELD, update=_refresh_pit_preview)
    corner: EnumProperty(  # type: ignore[valid-type]
        name="Corner of the offset", description="How the corners of the offset of each bench are made: rounded with arcs or mitred", items=PIT_CORNER_ITEMS, default="DEFAULT", options=_FIELD,
        update=_refresh_pit_preview)
    arc_tol: StringProperty(  # type: ignore[valid-type]
        name="Arc tolerance (m)", description="Most the arcs of the rounded corners may separate from the circle, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_pit_preview)
    simplify: StringProperty(  # type: ignore[valid-type]
        name="Simplification tolerance (m)", description="Most a simplified bench line may separate from the offset, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_pit_preview)
    close_radius: StringProperty(  # type: ignore[valid-type]
        name="Closing radius (m)", description="Radius in metres that closes the narrow inlets of a bench line (empty or 0: no closing); a hypothesis without default value", options=_FIELD,
        update=_refresh_pit_preview)
    az_window: StringProperty(  # type: ignore[valid-type]
        name="Azimuth window (m)", description="Length in metres along the bench over which the azimuth of the face is averaged to choose the range of the rose; a hypothesis without default value",
        options=_FIELD, update=_refresh_pit_preview)
    mean_reason: StringProperty(  # type: ignore[valid-type]
        name="Reason for the mean gradient",
        description="Why you accept a mean gradient of a ramp above the maximum of its profile: it stays recorded with who and when; it is needed only if the mean gradient passes it",
        options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez. «Vista previa»: la
    # pone el botón del diálogo. La confirmación expresa de la pendiente media de las rampas (RF-018-19): la pone el botón de su ventana, que la dice; desde un guion, quien la lanza
    # (con su motivo ``mean_reason``).
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    preview: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    confirm_mean: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    # Calcular una corta traída o heredada «sin calcular» (RF-015-18): el código de la corta que ya está en la versión; con él no hay diálogo: se calcula con los parámetros que ya tiene
    # (``design.pit_store.entity_pit_request``), con su código, sin escribir ninguno.
    code: StringProperty(default="", options=_HIDDEN)  # type: ignore[valid-type]

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué. Con ``confirm``, el diálogo de crear el cálculo abierto. Con ``code`` (una corta sin
        calcular) y la versión editable, sin diálogo: calcula (:meth:`execute`). Si no, las listas leídas de nuevo, la propuesta (un nombre, la primera capa, el primer perfil y la partida) y el
        diálogo del cálculo: Intro calcula."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            return self._confirmation(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        if self.code.strip():  # una corta sin calcular: todo lo que hace falta ya lo tiene la versión
            return self.execute(context)
        project = SESSION.project
        try:
            des_panels.refresh_choices(project)
            des_panels.refresh_platform_choices(project)
            refresh_pit_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=command_text(catalog().commands[command_idname(self.COMMAND)].label), confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 018 §5.3.3): un nombre que no repite el de ninguna entidad de la versión («Corta 1»…), la primera capa de polígonos, el
        primer perfil de banco y **la partida: la última de la cadena** y, sin ella, el terreno (``surface_proposal.ground_item``, con lo seleccionado en la vista; RF-018-03). Ninguna cifra
        minera se propone: las cotas, los criterios de parada y las tolerancias quedan vacíos."""
        given = self.properties.is_property_set
        if not self.name.strip():
            taken, number = set(des_panels.platform_names()), 1
            while f"{tr('Pit')} {number}" in taken:
                number += 1
            self.name = f"{tr('Pit')} {number}"
        for prop, items, none in (("layer", pit_layer_items, _NONE), ("profile", pit_profile_items, _NONE)):
            offered = [item[0] for item in items(self, None) if item[0] != none]
            if offered and not given(prop):
                setattr(self, prop, offered[0])
        if not given("start"):
            offered_starts = {item[0] for item in des_panels.platform_start_items(None, None)}
            start = des_panels.platform_default_start()
            if start is None or start not in offered_starts:
                grids = [identifier for identifier in offered_starts if identifier != _NONE and not identifier.startswith("entity:")]
                start = surface_proposal.ground_item(context, project, sorted(grids), des_panels.surface_choice) if grids else None
            if start is not None:
                self.start = start

    def draw(self, context: Any) -> None:
        """Arriba el nombre y el modo; la capa de origen con sus campos; los perfiles, la roseta y los bancos por berma y las asignaciones por sector; las rampas, las zonas sin rampa y los
        bancos fijados; los criterios de parada; las tolerancias del desfase, **cada una con su tipo**; la partida y el apoyo; y «Vista previa». En la confirmación de crear, el resumen y, si
        la pendiente media de una rampa pide un motivo, su campo."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            if self.confirm_mean:
                layout.prop(self, "mean_reason", text=tr("Reason for the mean gradient"), translate=False)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "mode", text=tr("Mode"), translate=False)
        origin = layout.box()
        origin.prop(self, "layer", text=tr("Source layer"), translate=False)
        origin.prop(self, "name_field", text=tr("Name field"), translate=False)
        if self.mode == "UP":
            origin.prop(self, "level_field", text=tr("Elevation field"), translate=False)
        benches = layout.box()
        benches.prop(self, "profile", text=tr("Bench profile"), translate=False)
        benches.prop(self, "rose", text=tr("Rose of slopes"), translate=False)
        benches.prop(self, "n_berm", text=tr("Benches per berm"), translate=False)
        sectors = layout.box()
        sectors.prop(self, "sector_profiles", text=tr("Profiles by sector"), translate=False)
        sectors.prop(self, "sector_roses", text=tr("Roses by sector"), translate=False)
        sectors.prop(self, "sector_n_berm", text=tr("Benches per berm by sector"), translate=False)
        parts = layout.box()
        parts.prop(self, "ramps", text=tr("Ramps"), translate=False)
        parts.prop(self, "noramp", text=tr("Zones without a ramp"), translate=False)
        parts.prop(self, "fixed", text=tr("Fixed benches"), translate=False)
        parts.prop(self, "fixed_field", text=tr("Bench field"), translate=False)
        stops = layout.box()
        stops.prop(self, "top_level", text=tr("Crest elevation (m)"), translate=False)
        stops.prop(self, "bottom_level", text=tr("Floor elevation (m)"), translate=False)
        stops.prop(self, "max_benches", text=tr("Maximum number of benches"), translate=False)
        stops.prop(self, "min_floor_width", text=tr("Minimum width of the floor (m)"), translate=False)
        tolerances = layout.box()
        tolerances.prop(self, "corner", text=tr("Corner of the offset"), translate=False)
        for prop, param in _tolerance_rows():
            label = {"arc_tol": tr("Arc tolerance (m)"), "simplify": tr("Simplification tolerance (m)"), "close_radius": tr("Closing radius (m)"),
                     "az_window": tr("Azimuth window (m)")}[prop]
            tolerances.prop(self, prop, text=label, translate=False)
            tolerances.label(text=_pit_param_text(param), translate=False)  # el tipo de cada tolerancia (RF-018-10, D-14)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        layout.prop(self, "support", text=tr("Support surface"), translate=False)
        _draw_entity_preview_button(layout, self, CREATE_PIT, _pit_fields())  # «Vista previa» (RF-018-32)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self) -> Any:
        """Lo pedido en el diálogo como la ``design.pit_model.PitRequest`` (RF-018-01, RF-018-02, RF-018-06 a 09), comprobado sin escribir ni calcular nada: la capa con sus campos, el modo,
        la partida y el apoyo, los perfiles (el base y los de cada sector), la roseta, los bancos por berma, las rampas, las capas de zonas sin rampa y de bancos fijados, los criterios de parada
        y las tolerancias del desfase, tecleados con coma o con punto decimal. Lo que se deja vacío lo resuelve el dominio: el valor por defecto o el rechazo de RF-015-08 con su nombre.
        :class:`ComputeFormError` si falta algo que el diálogo necesita para armar la petición; :class:`ProfileFormError` si un número o una asignación no tiene sentido."""
        from ...design import pit_model, road_model  # al usarlo: habilitar no carga el cálculo

        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the pit"))
        if self.layer in ("", _NONE):
            raise ComputeFormError(tr("Choose the source layer of the pit: there is none of polygons in the project"))
        if self.start in ("", _NONE):
            raise ComputeFormError(tr("Choose the start surface of the pit"))
        up = self.mode == "UP"

        def chosen(value: str) -> str | None:
            return None if value in ("", _NONE) else value

        fixed, noramp = chosen(self.fixed), chosen(self.noramp)
        return pit_model.PitRequest(
            name, road_model.LayerFields(self.layer, self.name_field.strip() or None), self.mode.lower(), self.start,
            level_field=(self.level_field.strip() or None) if up else None, support=chosen(self.support),
            fixed=None if fixed is None else road_model.LayerFields(fixed, None), fixed_field=self.fixed_field.strip() or None,
            noramp=None if noramp is None else road_model.LayerFields(noramp, None), profile=chosen(self.profile), rose=chosen(self.rose),
            n_berm=_whole(self.n_berm, tr("Benches per berm")),
            sector_profiles=_pairs(self.sector_profiles, tr("Profiles by sector"), _text), sector_roses=_pairs(self.sector_roses, tr("Roses by sector"), _text),
            sector_n_berm=_pairs(self.sector_n_berm, tr("Benches per berm by sector"), _whole), ramps=tuple(sorted(self.ramps)),
            top_level_m=typed_number(self.top_level, tr("Crest elevation (m)")), bottom_level_m=typed_number(self.bottom_level, tr("Floor elevation (m)")),
            max_benches=_whole(self.max_benches, tr("Maximum number of benches")), min_floor_width_m=typed_number(self.min_floor_width, tr("Minimum width of the floor (m)")),
            corner=None if self.corner == "DEFAULT" else self.corner.lower(), arc_tol_m=typed_number(self.arc_tol, tr("Arc tolerance (m)")),
            simplify_m=typed_number(self.simplify, tr("Simplification tolerance (m)")), close_radius_m=typed_number(self.close_radius, tr("Closing radius (m)")),
            az_window_m=typed_number(self.az_window, tr("Azimuth window (m)")))

    # --- Calcular y crear ---------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Con ``preview``, activa la vista previa de lo pedido (:meth:`_show_preview`). Si no, comprueba lo pedido (sin escribir
        nada si falta algo), pasa por la puerta de la 008 y calcula la corta por pasos con ``design.steps.pit_run`` —compila las máscaras antes si no están al día—, sin registrar nada
        (RF-015-03): desde la interfaz, en el modal con el avance y Esc (RF-018-35); desde un guion, de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar. Los rechazos
        (la capa, los campos, el perfil, la roseta, las rampas, las tolerancias, el nombre repetido, la partida, un sector con la búsqueda pendiente…) y todas las cuentas son de ``design``.
        Con ``code``, la corta **sin calcular** de la versión con ese código: se calcula con los parámetros que ya tiene y con su código, sin escribir ninguno."""
        if self.confirm:
            return self._create(context)
        if self.preview:
            return self._show_preview()
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        version = scene_versions.active_version() or ""
        code = self.code.strip()
        try:
            request = self._entity_request(project, version, code) if code else self._request()
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report, dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.pit_run(project, request, version=version, code=code or None, budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    @staticmethod
    def _entity_request(project: Any, version: str, code: str) -> Any:
        """La petición de la corta **sin calcular** ``code`` de la versión ``version`` (``design.pit_store.entity_pit_request``: de los parámetros que ya tiene la versión, como la repite el
        recálculo). Solo lee."""
        from ...design import pit_store  # al usarlo: habilitar no carga el cálculo

        return pit_store.entity_pit_request(project, version, code)

    def _show_preview(self) -> set[str]:
        """«Vista previa» (RF-018-32, RF-015-26): comprueba lo pedido como al calcular (:meth:`_request`, sin escribir ni calcular nada) y activa con ello la vista previa de la corta
        (``bl.draw.entity``: antes de calcular, los polígonos, los sectores con las flechas de la cara, el punto de inicio, las zonas sin rampa y los bancos fijados); la que hubiera activa se
        cambia por la nueva (pulsarlo otra vez, o cambiar un campo del diálogo: :func:`_refresh_pit_preview`). Se quita al cancelar la orden, al Esc a mitad del cálculo, al crearla, con su
        control y al conmutar a la interfaz de Blender."""
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            request = self._request()
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        from ...design.preview import PitAsk  # al usarlo: habilitar no carga el cálculo

        preview = _entity_preview()
        try:
            preview.enable(preview.EntityPlan(pit=PitAsk(request=request)))
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr("The preview of the entity could not be shown: {detail}", detail=design_error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the preview of the pit «{name}»", name=request.name))
        return {"FINISHED"}

    def _finished(self, context: Any, opened: Any) -> set[str]:
        """Como las demás (:meth:`_ChainsEntityLayer._finished`) y, **tras calcular**, con la vista previa activa, **le da lo calculado** (``PitAsk(request, prepared, outcome)``: sin repetir
        la preparación)."""
        calculated = not self._chain
        done = _ChainsEntityLayer._finished(self, context, opened)
        if calculated:
            _show_calculated_preview(opened)
        return done

    def _confirmation(self, context: Any) -> set[str]:
        """El diálogo de crear el cálculo abierto. Con la **pendiente media de una rampa por encima de pm** (RF-018-19), que pide confirmación expresa, su botón lo dice («Confirmar y
        crear»): pulsarlo es la confirmación y el diálogo pide además su **motivo**, que queda registrado con quién y cuándo; «Cancelar» y cerrarlo no crean nada."""
        held = calculation()
        self.confirm_mean = held is not None and held.needs_mean_confirmation
        return _CalculateAndCreate._confirmation(self, context)

    def _confirm_text(self, held: Calculation) -> str:
        if held.needs_mean_confirmation:
            return tr("Confirm and create")
        return _CalculateAndCreate._confirm_text(self, held)

    def _create(self, context: Any) -> set[str]:
        """«Crear» (RF-018-01, RF-015-02): como las demás, y con la **pendiente media de una rampa por encima de pm no se crea sin la confirmación expresa** (``confirm_mean``: el botón
        de la ventana, o quien la lanza desde un guion) **ni sin su motivo** (``mean_reason``: RF-018-19; queda en los ajustes de la operación con quién y cuándo): lo dice y el cálculo
        sigue abierto (se confirma, o se calcula otra vez). **Ya creada**, quita la vista previa (la corta ya existe: ya no se prepara) y encadena lo que sigue (:meth:`_update_declared`:
        la capa de entidades y las de la corta, como operaciones aparte)."""
        from ...design import pit_store  # al usarlo: habilitar no carga el cálculo

        opened = calculation()
        if opened is not None and isinstance(opened.entity, pit_store.PreparedPit):
            problem = self._mean_problem(opened)
            if problem is not None:
                self.report({"ERROR"}, problem)
                if self.in_steps and getattr(context, "window", None) is not None:
                    _ask_confirmation(context, idname=self.COMMAND)  # el cálculo sigue abierto: se vuelve a pedir, con su motivo
                return {"CANCELLED"}
            started = self._create_in_steps(context, opened)
            if started is not None:  # desde la interfaz, por pasos: lo que sigue va en el mismo modal
                return started
        created = _CalculateAndCreate._create(self, context)
        if opened is None or "FINISHED" not in created:
            return created
        _entity_preview_off()  # la corta ya existe: ya no se prepara (RF-018-32)
        return self._update_declared(context, opened)

    def _mean_problem(self, opened: Calculation) -> str | None:
        """Lo que impide crear por la pendiente media de las rampas (``None`` si nada): sin la confirmación expresa, el rechazo del dominio (``des.pit_ramp_mean_over``); confirmada sin
        motivo, que falta. Con ella y su motivo, la deja dicha en el cálculo (``Calculation.confirm_pit``: la rampa, su media, el motivo, quién y cuándo)."""
        pending = opened.mean_pending
        if not pending:
            return None
        if not self.confirm_mean:
            try:
                opened.ensure_pit_creatable()
            except design_messages.DesignError as exc:
                return design_error_text(exc)
            return tr("The mean gradient of a ramp passes the maximum of its profile: confirm it expressly to create the pit")
        reason = self.mean_reason.strip()
        if not reason:
            return tr("Write the reason for accepting a mean gradient above the maximum of the profile: it stays recorded with who and when")
        project = SESSION.project
        who, when = project.session.user_host, format_utc(project.clock.now())
        opened.confirm_pit(provenance.ramp_confirmation(code, mean, reason, who, when) for code, mean, _limit in pending)
        return None

    def _after_registered(self) -> None:
        """En cuanto lo guardado llega (:class:`_CreatesInSteps`), quita la vista previa: la corta ya existe, ya no se prepara (RF-018-32)."""
        _entity_preview_off()

    def _created_text(self, opened: Calculation) -> str:
        return tr("Pit «{name}» created in {version}", name=opened.name, version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando la corta… 40 % · Esc: cancelar», «Guardando la corta… 40 % · Esc: cancelar» o, tras crearla, «Poniendo al día las restricciones
        declaradas… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self._chain:
            return tr("Updating the declared constraints and the masks… {percent} % · Esc: cancel", percent=percent)
        if self._creating:
            return tr("Saving the pit… {percent} % · Esc: cancel", percent=percent)
        return tr("Computing the pit… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if self._chain:
            return tr("Cancelled: the pit is created; the declared constraints and the masks are brought up to date before the next operation that uses them, "
                      "and the entity layer and the layers of the pit with the next entity order or «Recompute the stale results»")
        if self._creating:
            return tr("Creation cancelled: the pit has not been created and the calculation has been discarded; nothing has been left half-done")
        return _CalculateAndCreate._cancelled_text(self)

    def _error_text(self, exc: GeoblenderError) -> str:
        found = _CalculateAndCreate._error_text(self, exc)
        if self._chain:
            return f"{found} " + tr("The pit is created: only the declared constraints and the masks have not been brought up to date")
        return found


classes: tuple[type, ...] = (GEOBLENDER_OT_des_create_pit,)
"""Las órdenes de la corta por bancos (T31: «Nueva corta…»; T32 y T33 ponen las demás)."""

__all__ = ["CREATE_PIT", "GEOBLENDER_OT_des_create_pit", "classes", "refresh_pit_choices"]
