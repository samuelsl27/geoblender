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

**«Roseta de taludes…» y «Rampa…»** (T32; RF-018-07, RF-018-15; plan 018 H-5): :class:`GEOBLENDER_OT_des_edit_pit_rose` y :class:`GEOBLENDER_OT_des_edit_pit_ramp` abren sus ventanas
(``bl.ui.pit_panels``) y las internas :class:`GEOBLENDER_OT_des_save_pit_rose` y :class:`GEOBLENDER_OT_des_save_pit_ramp` crean, completan y renombran con
``design.pit_rose.edit_pit_roses`` y ``design.pit_ramp_def.edit_pit_ramps`` (``des.edit_pit_roses`` y ``des.edit_pit_ramps``: operaciones **de proyecto**, una transacción cada una;
la copia, para la corta, de «Perfil de pista…» de la 017). Las demás órdenes de la corta («Expandir banco…», «Línea de cielo…» y «Superficie y sólido…») son de las tareas
siguientes; las provisionales del catálogo (``des_expand_bench``, ``des_compute_daylight``) las sustituyen ellas."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.params import ParameterStore, ParamKind
from ...core.provenance.undo import UndoKind
from ...design import params as design_params
from ...core.project.model import Progress
from ...core.timeutil import format_utc
from ...design import messages as design_messages
from ...design import provenance
from ..scene import versions as scene_versions
from ..scene import undo_watch
from ..ui import constraint_panels, des_panels, pit_panels
from ..ui.commands import catalog, command_idname
from ..ui.commands import text as command_text
from ..ui.res_panels import NOT_SHOWN, record_text
from . import surface_proposal
from .core import _StepsModal
from .core_provenance import (
    PARAMETER_SCOPE_ITEMS,
    SESSION,
    SOURCE_KIND_ITEMS,
    ProvenanceAwareOperator,
    ensure_ready,
    scope_choice,
    write_unavailable,
)
from .des import (
    DIALOG_WIDTH,
    TRANSLATION_CONTEXT,
    ComputeFormError,
    DesignCommandAware,
    PROFILE_KIND_ITEMS,
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


# --- Roseta de taludes… y Rampa… (T32; HU-018-1, HU-018-3; RF-018-07, RF-018-15; plan 018 H-5) -----------------------------------------------------

EDIT_PIT_ROSE = provenance.PIT_ROSE_COMMAND
EDIT_PIT_RAMP = provenance.PIT_RAMP_COMMAND
SAVE_PIT_ROSE = pit_panels.SAVE_ROSE
SAVE_PIT_RAMP = pit_panels.SAVE_RAMP
_NOT_CHOSEN = "NONE"
RAMP_TYPE_ITEMS = [(_NOT_CHOSEN, "Not chosen", "Not chosen"), ("spiral", "Spiral", "The ramp winds along the wall of the pit"), ("zigzag", "Zigzag", "The ramp goes to and fro with return platforms")]
"""El tipo de la rampa (RF-018-15): sin valor por defecto, lo declara una persona."""
RAMP_SENSE_ITEMS = [(_NOT_CHOSEN, "Not chosen", "Not chosen"), ("cw", "Clockwise", "The ramp turns clockwise"), ("ccw", "Counter-clockwise", "The ramp turns counter-clockwise")]
"""El sentido de la rampa (RF-018-15)."""


def _call_panel(name: str) -> set[str]:
    """Abre la ventana emergente ``name`` (la de ``bl.ops.des``); una que no está registrada, nada. Aparte para que las pruebas la sustituyan."""
    from .des import _call_panel as call

    return call(name)


_RAMP_ROADS: list[tuple[str, str, str]] = []
"""La lista viva de los perfiles de pista del diálogo de «Rampa…» (los ``items`` de un ``EnumProperty`` han de seguir vivos)."""


def ramp_road_items(self: Any, context: Any) -> list[tuple[str, str, str]]:
    """Los perfiles de pista del proyecto, **precedidos por «sin elegir»**: el valor por defecto de una rampa no lo da ningún perfil (D-19) y renombrar no escribe ninguno."""
    base = des_panels.road_profile_items(self, context)
    _RAMP_ROADS[:] = [(_NOT_CHOSEN, tr("Not chosen"), tr("Not chosen")), *(item for item in base if item[0] != des_panels.NO_ZONE)]
    return _RAMP_ROADS


def ramp_field_label(attribute: str) -> str:
    """El nombre, en el idioma de la interfaz, del campo ``attribute`` del diálogo de «Rampa…» (cada uno, un ``msgid`` literal del catálogo)."""
    labels = {"ramp_type": tr("Ramp type"), "sense": tr("Sense"), "start": tr("Start point"), "gradient": tr("Design gradient g (%)"), "road_profile": tr("Road profile"),
              "transition": tr("Transition (m)"), "turn_radius": tr("Turning radius (m)"), "min_platform": tr("Minimum platform (m)")}
    return labels[attribute]


def refresh_ramp_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` los perfiles de pista que ofrece el diálogo de «Rampa…» (la lista viva de ``des_panels.road_profile_items``)."""
    from ...design import road_profiles  # al usarlo: habilitar no carga el cálculo

    with project.read() as conn:
        stored = road_profiles.read_profiles(conn)
    if stored:
        des_panels._CHOICES.road_profiles = [(item.code, item.name, tr("Road profile")) for item in stored]


class _CodedSave:
    """Lo común de las dos órdenes que guardan un dato del proyecto con código (la roseta y la rampa): la fila que se completa o se renombra, la declaración de los valores
    (tipo, fuente, decisor, motivo y ámbito) y el cierre. Las propiedades las declara cada orden."""

    provenance_dialog = False
    _KEY_EXAMPLE = ""
    _known: dict[str, dict[str, str]]

    def _rows(self, conn: Any) -> Any:
        raise NotImplementedError

    def _stored(self, project: Any) -> Any:
        """La fila de :attr:`code` en el proyecto; ``ProfileFormError`` si ya no está (sin código, ``None``: uno nuevo)."""
        if not self.code:
            return None
        with project.read() as conn:
            found = [row for row in self._rows(conn) if row.code == self.code]
        if not found:
            raise ProfileFormError(tr("«{code}» is no longer in the project: open the list again", code=self.code))
        return found[0]

    def _declaration(self, declaration_type: Any) -> Any:
        """La declaración de lo escrito: su tipo, su fuente, quién lo decide, por qué y para quién (el proyecto o solo la versión activa)."""
        decided_by = self.decided_by.strip()
        if not decided_by:
            raise ProfileFormError(tr("Write who decides the values"))
        source = self.source.strip()
        version = None
        if self.scope == "VERSION":  # solo la versión activa (RF-009-24, RF-009-29)
            active = scene_versions.active()
            if active is None:
                raise ProfileFormError(tr("Choose the active version first: Project ▸ Versions ▸ Active version"))
            version = active.code
        kind = ParamKind.ADOPTADO if self.kind == "ADOPTADO" else ParamKind.HIPOTESIS
        return declaration_type(source=source or decided_by, decided_by=decided_by, reason=self.reason.strip() or tr("Declared in the pit windows"),
                                source_kind=self.source_kind.lower() if source else "person", kind=kind.value, version=version)

    def _invoke(self, context: Any, title: str) -> set[str]:
        self.provenance_dialog = True
        project = SESSION.project
        try:
            row = self._stored(project)
            self._known = {} if row is None else self._known_values(project, row.code)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        if row is not None:
            self.name = row.name
        if not self.decided_by:
            self.decided_by = project.session.user_host
        if not self.properties.is_property_set("scope"):
            self.scope = "PROJECT"
        return context.window_manager.invoke_props_dialog(self, width=DIALOG_WIDTH, translate=False, title=title, confirm_text=tr("Save"))

    def _known_values(self, project: Any, code: str) -> dict[str, dict[str, str]]:
        return {}

    def _draw_scope(self, layout: Any) -> None:
        choice = scope_choice(self._KEY_EXAMPLE)
        if choice is None:  # «¿Para el proyecto o solo para V01?» (RF-009-29)
            return
        layout.label(text=tr("For the project or only for {version}?", version=choice.code), translate=False)
        row = layout.row(align=True)
        row.use_property_split = False
        row.prop_enum(self, "scope", "PROJECT", text=tr("The project"), translate=False)
        only = row.row(align=True)
        only.enabled = choice.refusal is None  # «Versión no editable» (RF-009-21)
        only.prop_enum(self, "scope", "VERSION", text=tr("Only {version}", version=choice.code), translate=False)
        if choice.refusal is not None:
            refused = layout.row()
            refused.alert = True
            refused.label(text=choice.refusal, icon="ERROR", translate=False)

    def _draw_declaration(self, layout: Any) -> None:
        layout.prop(self, "kind", text=tr("Type"), translate=False)
        layout.prop(self, "source", text=tr("Source"), translate=False)
        layout.prop(self, "source_kind", text=tr("Source type"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def _renamed(self, row: Any, has_values: bool) -> str | None:
        """El nombre nuevo de la fila que se completa (``None``: el suyo); ``ProfileFormError`` si no cambia nada."""
        typed_name = self.name.strip()
        renamed = self.name if typed_name and typed_name != row.name else None
        if renamed is None and not has_values:
            raise ProfileFormError(tr("Nothing to change in «{name}»", name=row.name))
        return renamed

    def _run(self, saver: Any, said: Any, after: Any) -> set[str]:
        """Escribe con ``saver`` (el dominio) y lo deja dicho: nada se escribe si lo escrito no vale (el dominio lo mira todo antes: 0 transacciones, RF-018-07, RF-018-15)."""
        project = SESSION.project
        try:
            edit, declaration = self._request(project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report, dialog=self.provenance_dialog, version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        try:
            edited = saver(project, [edit], declaration)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, self.provenance_op_type)
        rows = edited.roses if hasattr(edited, "roses") else edited.ramps
        code = edited.created[0] if edited.created else edit.code
        name = next(row.name for row in rows if row.code == code)
        text = said(bool(edited.created), name, code)
        after(project, code, text)
        self.report({"INFO"}, text)
        return {"FINISHED"}


class GEOBLENDER_OT_des_edit_pit_rose(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Slope roses of the pit, with their ranges, their source and the advance and overall slope derived from them"""

    bl_idname = EDIT_PIT_ROSE
    bl_label = "Slope rose…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.EDIT_PIT_ROSES

    def execute(self, context: Any) -> set[str]:
        """Lee las rosetas del proyecto y sus rangos en la versión activa en la vista y abre su ventana; desde un guion sin ventana, solo la vista (RF-018-07). Activa con el proyecto
        en escritura y la versión activa editable (o ninguna: la edición es de proyecto) y, si no, desactivada con su motivo (RF-015-28)."""
        try:
            pit_panels.fill_pit_roses(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(pit_panels.ROSES_PANEL)


class GEOBLENDER_OT_des_save_pit_rose(_CodedSave, DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Create a slope rose, complete the ranges it lacks or rename it"""

    bl_idname = SAVE_PIT_ROSE
    bl_label = "Save slope rose…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = provenance.EDIT_PIT_ROSES
    _KEY_EXAMPLE = design_params.rose_key("r", "r1", design_params.RoseParam.FACE_DEG)

    code: StringProperty(  # type: ignore[valid-type]
        name="Rose", description="Code of the slope rose to complete or rename (empty: a new rose)", options=_HIDDEN)
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the rose, such as ROSETA_NORTE: it can change, its code cannot", options=_FIELD)
    ranges: StringProperty(  # type: ignore[valid-type]
        name="Ranges",
        description="The ranges of the face azimuth, each as «from to angle berm» (degrees, degrees, degrees, metres) separated by «;»: they cover 0 to 360 without gaps or overlaps",
        options=_FIELD)
    kind: EnumProperty(  # type: ignore[valid-type]
        name="Type", description="Type of the values: adopted or hypothesis", items=PROFILE_KIND_ITEMS, default="ADOPTADO", options=_FIELD)
    source: StringProperty(  # type: ignore[valid-type]
        name="Source", description="Document, standard, person, operation or algorithm the values come from (empty: the decider)", options=_FIELD)
    source_kind: EnumProperty(  # type: ignore[valid-type]
        name="Source type", description="Whether the source is a document, a standard, a person, an operation or an algorithm", items=SOURCE_KIND_ITEMS, default="PERSON",
        options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decided the values (the owner, a laboratory, a person)", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the rose has these values (recorded in its history)", options=_FIELD)
    scope: EnumProperty(  # type: ignore[valid-type]
        name="Scope", description="Whether the change is for the project or only for the active version (a parameter that its module admits by version)",
        items=PARAMETER_SCOPE_ITEMS, default="PROJECT", options=_FIELD)

    def _rows(self, conn: Any) -> Any:
        from ...design import pit_rose  # al usarlo: habilitar no lo carga (RNF-001-03)

        return pit_rose.read_roses(conn)

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo: de una roseta que existe, con su nombre; de una nueva, vacío. Propone el decisor y el ámbito; no cambia nada hasta que se acepta."""
        return self._invoke(context, tr("Slope rose"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        self._draw_scope(layout)
        layout.prop(self, "ranges", text=tr("Ranges"), translate=False)
        layout.label(text=tr("Each range: from to angle berm, separated by «;»"), translate=False)
        self._draw_declaration(layout)

    def _ranges(self) -> list[tuple[float, float, float, float]]:
        """Lo tecleado en :attr:`ranges` como cuatro números por rango (desde, hasta, α, B); ``ProfileFormError`` nombrando el rango si no son cuatro números."""
        found: list[tuple[float, float, float, float]] = []
        for part in self.ranges.split(";"):
            tokens = part.split()
            if not tokens:
                continue
            if len(tokens) != 4:
                raise ProfileFormError(tr("«{value}» is not a range: write «from to angle berm»", value=part.strip()))
            numbers = [typed_number(token, tr("Ranges")) for token in tokens]
            found.append((numbers[0], numbers[1], numbers[2], numbers[3]))  # type: ignore[arg-type]
        return found

    def _request(self, project: Any) -> tuple[Any, Any]:
        """Lo escrito, como lo pide el dominio: la edición y la declaración de los rangos. Los huecos, los solapes, los nombres y los valores fuera de rango los rechaza el dominio
        (``DesignError``, RF-018-07): ninguna regla ni cuenta es de aquí."""
        from ...design import pit_rose  # al usarlo: habilitar no lo carga (RNF-001-03)

        row = self._stored(project)
        ranges = self._ranges()
        if row is None:
            edit = pit_rose.RoseEdit(name=self.name, ranges=ranges)
        else:
            edit = pit_rose.RoseEdit(name=self._renamed(row, bool(ranges)), code=row.code, ranges=ranges or None)
        return edit, (self._declaration(pit_rose.Declaration) if ranges else None)

    def execute(self, context: Any) -> set[str]:
        """Crea, completa o renombra la roseta con ``design.pit_rose.edit_pit_roses`` (una sola operación de proyecto y una transacción; RF-018-07). Todo se mira antes de escribir:
        sin nombre, con el nombre de otra, con un hueco o un solape de azimut, con un valor fuera de rango o con un texto que no son cuatro números se rechaza nombrando la roseta, el
        rango y el valor, y no deja nada (0 transacciones)."""
        from ...design import pit_rose  # al usarlo: habilitar no lo carga (RNF-001-03)

        def said(created: bool, name: str, code: str) -> str:
            if created:
                return tr("Slope rose «{name}» created with the code «{code}»", name=name, code=code)
            return tr("Slope rose «{name}» saved (code «{code}»)", name=name, code=code)

        def after(project: Any, code: str, text: str) -> None:
            try:
                pit_panels.fill_pit_roses(project)
            except (GeoblenderError, sqlite3.Error, OSError, ValueError):
                LOGGER.warning("No se pudo volver a leer la lista de rosetas", exc_info=True)
            pit_panels.choose_pit_rose(code)
            pit_panels.show_pit_rose_report([(text, False)])

        return self._run(pit_rose.edit_pit_roses, said, after)


class GEOBLENDER_OT_des_edit_pit_ramp(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Ramp definitions of the pit, with their values, their source and the length they need per bench"""

    bl_idname = EDIT_PIT_RAMP
    bl_label = "Ramp…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.EDIT_PIT_RAMPS

    def execute(self, context: Any) -> set[str]:
        """Lee las definiciones de rampa del proyecto y sus valores en la versión activa en la vista y abre su ventana; desde un guion sin ventana, solo la vista (RF-018-15)."""
        try:
            pit_panels.fill_pit_ramps(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(pit_panels.RAMPS_PANEL)


class GEOBLENDER_OT_des_save_pit_ramp(_CodedSave, DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Create a ramp definition, complete the values it lacks or rename it"""

    bl_idname = SAVE_PIT_RAMP
    bl_label = "Save ramp…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = provenance.EDIT_PIT_RAMPS
    _KEY_EXAMPLE = design_params.pitramp_key("q", design_params.PitRampParam.GRADIENT)

    code: StringProperty(  # type: ignore[valid-type]
        name="Ramp", description="Code of the ramp definition to complete or rename (empty: a new ramp)", options=_HIDDEN)
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the ramp, such as ESPIRAL_A: it can change, its code cannot", options=_FIELD)
    ramp_type: EnumProperty(  # type: ignore[valid-type]
        name="Ramp type", description="Spiral along the wall or zigzag with return platforms", items=RAMP_TYPE_ITEMS, default=_NOT_CHOSEN, options=_FIELD)
    sense: EnumProperty(  # type: ignore[valid-type]
        name="Sense", description="Whether the ramp turns clockwise or counter-clockwise", items=RAMP_SENSE_ITEMS, default=_NOT_CHOSEN, options=_FIELD)
    start: StringProperty(  # type: ignore[valid-type]
        name="Start point", description="Where the ramp starts: «fondo», «banco N» or «capa:nombre» (a point of a layer of points)", options=_FIELD)
    gradient: StringProperty(  # type: ignore[valid-type]
        name="Design gradient g (%)", description="Design gradient of the ramp in per cent, more than 0 and at most the maximum of its road profile", options=_FIELD)
    road_profile: EnumProperty(  # type: ignore[valid-type]
        name="Road profile", description="Road profile of the ramp: its section width and its rules", items=ramp_road_items, options=_FIELD)
    transition: StringProperty(  # type: ignore[valid-type]
        name="Transition (m)", description="Length of the linear transition of the face in metres, 0 or more", options=_FIELD)
    turn_radius: StringProperty(  # type: ignore[valid-type]
        name="Turning radius (m)", description="Turning radius of a zigzag ramp in metres, more than 0 (hypothesis: no default value)", options=_FIELD)
    min_platform: StringProperty(  # type: ignore[valid-type]
        name="Minimum platform (m)", description="Minimum length of the return platform of a zigzag ramp in metres, more than 0 (hypothesis: no default value)", options=_FIELD)
    kind: EnumProperty(  # type: ignore[valid-type]
        name="Type", description="Type of the values: adopted or hypothesis", items=PROFILE_KIND_ITEMS, default="ADOPTADO", options=_FIELD)
    source: StringProperty(  # type: ignore[valid-type]
        name="Source", description="Document, standard, person, operation or algorithm the values come from (empty: the decider)", options=_FIELD)
    source_kind: EnumProperty(  # type: ignore[valid-type]
        name="Source type", description="Whether the source is a document, a standard, a person, an operation or an algorithm", items=SOURCE_KIND_ITEMS, default="PERSON",
        options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decided the values (the owner, a laboratory, a person)", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the ramp has these values (recorded in its history)", options=_FIELD)
    scope: EnumProperty(  # type: ignore[valid-type]
        name="Scope", description="Whether the change is for the project or only for the active version (a parameter that its module admits by version)",
        items=PARAMETER_SCOPE_ITEMS, default="PROJECT", options=_FIELD)

    _FIELDS = (("ramp_type", design_params.PitRampParam.TYPE, "Ramp type"), ("sense", design_params.PitRampParam.SENSE, "Sense"),
               ("start", design_params.PitRampParam.START, "Start point"), ("gradient", design_params.PitRampParam.GRADIENT, "Design gradient g (%)"),
               ("road_profile", design_params.PitRampParam.ROAD_PROFILE, "Road profile"), ("transition", design_params.PitRampParam.TRANSITION, "Transition (m)"),
               ("turn_radius", design_params.PitRampParam.TURN_RADIUS, "Turning radius (m)"),
               ("min_platform", design_params.PitRampParam.MIN_PLATFORM, "Minimum platform (m)"))

    def _rows(self, conn: Any) -> Any:
        from ...design import pit_ramp_def  # al usarlo: habilitar no lo carga (RNF-001-03)

        return pit_ramp_def.read_ramps(conn)

    def _known_values(self, project: Any, code: str) -> dict[str, dict[str, str]]:
        """Lo que la rampa ``code`` ya tiene declarado, por propiedad y ámbito (``PROJECT`` o ``VERSION``): su texto. Con ello el diálogo de completar no pide lo que ya vale."""
        store = ParameterStore(project)
        version = scene_versions.active()
        found: dict[str, dict[str, str]] = {}
        with project.read() as conn:
            for attribute, param, _label in self._FIELDS:
                key = design_params.pitramp_key(code, param)
                records = {"PROJECT": store.get(key, conn=conn), "VERSION": None if version is None else store.get(key, version=version.uid, conn=conn)}
                found[attribute] = {scope: record_text(record) for scope, record in records.items() if record is not None and record.value is not None}
        return found

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo: de una rampa que existe, con su nombre y lo que ya vale en cada ámbito (solo se piden los valores que le faltan); de una nueva, vacío."""
        try:
            refresh_ramp_choices(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError):
            LOGGER.warning("No se pudo volver a leer la lista de perfiles de pista", exc_info=True)
        return self._invoke(context, tr("Ramp definition"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        self._draw_scope(layout)
        known = getattr(self, "_known", {})
        declared = False
        for attribute, _param, label in self._FIELDS:
            here = known.get(attribute, {}).get(self.scope)
            if here is not None:  # ya vale en ese ámbito: se cambia con «Cambiar…»
                layout.label(text=tr("{name}: {value}", name=ramp_field_label(attribute), value=here), translate=False)
                declared = True
            else:
                layout.prop(self, attribute, text=ramp_field_label(attribute), translate=False)
        if declared:
            layout.label(text=tr("Values already declared are changed with «Change…» in the list"), translate=False)
        self._draw_declaration(layout)

    def _values(self) -> dict[Any, Any]:
        """Lo escrito como lo pide el dominio (por valor de la rampa); lo vacío o «sin elegir» no se da: el dominio dice cuál falta (D-19: ningún valor por defecto)."""
        values: dict[Any, Any] = {}
        for attribute, item, label in self._FIELDS:
            typed = getattr(self, attribute)
            if attribute in ("ramp_type", "sense", "road_profile"):
                if typed not in (_NOT_CHOSEN, des_panels.NO_ZONE, ""):
                    values[item] = typed
            elif item is design_params.PitRampParam.START:
                if typed.strip():
                    values[item] = typed.strip()
            else:
                number = typed_number(typed, ramp_field_label(attribute))
                if number is not None:
                    values[item] = number
        return values

    def _request(self, project: Any) -> tuple[Any, Any]:
        """La edición y la declaración de lo escrito. Los rangos, el nombre y la pendiente máxima del perfil de pista los rechaza el dominio (``DesignError``, RF-018-15)."""
        from ...design import pit_ramp_def, pit_rose  # al usarlo: habilitar no lo carga (RNF-001-03)

        row = self._stored(project)
        values = self._values()
        if row is None:
            edit = pit_ramp_def.RampEdit(name=self.name, values=values)
        else:
            edit = pit_ramp_def.RampEdit(name=self._renamed(row, bool(values)), code=row.code, values=values or None)
        return edit, (self._declaration(pit_rose.Declaration) if values else None)

    def execute(self, context: Any) -> set[str]:
        """Crea, completa o renombra la definición con ``design.pit_ramp_def.edit_pit_ramps`` (una sola operación de proyecto y una transacción; RF-018-15). Todo se mira antes de
        escribir: sin nombre, con el nombre de otra, sin un valor, con uno fuera de rango o con una pendiente por encima de la máxima del perfil de pista se rechaza nombrando la rampa,
        el campo y el valor, y no deja nada (0 transacciones)."""
        from ...design import pit_ramp_def  # al usarlo: habilitar no lo carga (RNF-001-03)

        def said(created: bool, name: str, code: str) -> str:
            if created:
                return tr("Ramp «{name}» created with the code «{code}»", name=name, code=code)
            return tr("Ramp «{name}» saved (code «{code}»)", name=name, code=code)

        def after(project: Any, code: str, text: str) -> None:
            try:
                pit_panels.fill_pit_ramps(project)
            except (GeoblenderError, sqlite3.Error, OSError, ValueError):
                LOGGER.warning("No se pudo volver a leer la lista de rampas", exc_info=True)
            pit_panels.choose_pit_ramp(code)
            pit_panels.show_pit_ramp_report([(text, False)])

        return self._run(pit_ramp_def.edit_pit_ramps, said, after)


classes: tuple[type, ...] = (GEOBLENDER_OT_des_create_pit, GEOBLENDER_OT_des_edit_pit_rose, GEOBLENDER_OT_des_save_pit_rose, GEOBLENDER_OT_des_edit_pit_ramp,
                             GEOBLENDER_OT_des_save_pit_ramp)
"""Las órdenes de la corta por bancos (T31: «Nueva corta…»; T32: «Roseta de taludes…» y «Rampa…» con sus internas; las demás las ponen las tareas siguientes)."""

__all__ = ["CREATE_PIT", "EDIT_PIT_RAMP", "EDIT_PIT_ROSE", "GEOBLENDER_OT_des_create_pit", "classes", "refresh_pit_choices", "refresh_ramp_choices"]
