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

**«Expandir banco…»** (T32b; RF-018-22, RF-018-23): :class:`GEOBLENDER_OT_des_expand_bench` calcula **un paso** sobre una polilínea con ``design.steps.pit_expand_run`` y, al confirmar,
deja la capa ``des_pxb_`` editable en QGIS (el patrón de «Proponer el trazado…» de la 017: no es una entidad). **«Roseta de taludes…» y «Rampa…»** (T32; RF-018-07, RF-018-15; plan 018 H-5): :class:`GEOBLENDER_OT_des_edit_pit_rose` y :class:`GEOBLENDER_OT_des_edit_pit_ramp` abren sus ventanas
(``bl.ui.pit_panels``) y las internas :class:`GEOBLENDER_OT_des_save_pit_rose` y :class:`GEOBLENDER_OT_des_save_pit_ramp` crean, completan y renombran con
``design.pit_rose.edit_pit_roses`` y ``design.pit_ramp_def.edit_pit_ramps`` (``des.edit_pit_roses`` y ``des.edit_pit_ramps``: operaciones **de proyecto**, una transacción cada una;
la copia, para la corta, de «Perfil de pista…» de la 017). Las demás órdenes de la corta («Línea de cielo…» y «Superficie y sólido…») son de las tareas siguientes; la provisional
del catálogo (``des_compute_daylight``) la sustituye ella."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ...core.errors import GeoblenderError
from ...core import i18n
from ...core.i18n import tr
from ...core.params import ParameterStore, ParamKind
from ...core.provenance.undo import UndoKind
from ...design import params as design_params
from ...core.project.model import Progress
from ...core.timeutil import format_utc
from ...gis import provenance as gis_provenance
from ...gis.messages import GisError
from ...design import messages as design_messages
from ...design import provenance
from ..scene import versions as scene_versions
from ..scene import undo_watch
from ..ui import constraint_panels, des_panels, pit_panels
from ..ui import provenance as ui_provenance
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
    error_text,
    read_only_dirs,
    scope_choice,
    write_unavailable,
)
from .des import (
    DIALOG_WIDTH,
    TRANSLATION_CONTEXT,
    ComputeFormError,
    DesignCommand,
    DesignCommandAware,
    PROFILE_KIND_ITEMS,
    ProfileFormError,
    _ask_confirmation,
    _confirm_later,
    _entity_or_selected,
    _EntitySteps,
    _export_progress,
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
    design_unavailable,
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
_PIT_HIDDEN = frozenset({"confirm", "in_steps", "preview", "confirm_mean", "code", "show_more"})
_FOLDED_TEXT = ("sector_profiles", "sector_roses", "sector_n_berm", "arc_tol", "simplify", "close_radius", "az_window")
"""Los campos de texto que el diálogo de «Nueva corta…» pliega en «Más opciones» (con el de la esquina del desfase): si alguno tiene valor, se enseñan."""
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
    pits: list[tuple[str, str, str]] = field(default_factory=list)
    text_fields: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    number_fields: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)


_CHOICES = _Choices()


def _fixed_choices() -> None:
    """Las listas sin nada del proyecto: «—» (o «ninguno»)."""
    _CHOICES.layers = [(_NONE, NOT_SHOWN, tr("There are no layers of polygons in the project"))]
    _CHOICES.noramp = [(_NONE, tr("No zones without a ramp"), tr("The ramps may start anywhere"))]
    _CHOICES.fixed = [(_NONE, tr("No fixed benches"), tr("No bench is fixed to a line of the project"))]
    _CHOICES.profiles = [(_NONE, NOT_SHOWN, tr("There are no bench profiles in the project"))]
    _CHOICES.roses = [(_NONE, tr("No rose"), tr("The benches have the face of the bench profile"))]
    _CHOICES.ramps = []
    _CHOICES.pits = [(_NONE, NOT_SHOWN, tr("There are no calculated pits in the active version"))]
    _CHOICES.text_fields = {}
    _CHOICES.number_fields = {}


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
        for source in gis_store.feature_sources(project, polygons):
            _CHOICES.text_fields[source.name] = field_choices(source.columns, numeric=False)
            _CHOICES.number_fields[source.name] = field_choices(source.columns, numeric=True)
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


def field_choices(columns: Any, *, numeric: bool) -> list[tuple[str, str, str]]:
    """Las opciones de la lista de campos de una capa (spec 018, T40f): primero la propuesta («Automático» para el nombre, que la orden resuelve; «Elija un campo» para la cota) y después
    los campos de la capa **de texto** (``numeric`` falso) o **numéricos** (enteros o reales); cada uno con su nombre tal cual lo tiene la capa. Un campo binario no se ofrece."""
    if numeric:
        first = (_NONE, tr("Choose a field"), tr("The ascending pit needs the field with the elevation of each floor"))
    else:
        first = (_NONE, tr("Automatic"), tr("The field «nombre» or «name» or, without it, the number (fid)"))
    wanted = ("INTEGER", "DOUBLE") if numeric else ("TEXT",)
    kind = tr("Numeric field of the layer") if numeric else tr("Text field of the layer")
    return [first, *((column.field, column.field, kind) for column in columns if column.sql_type in wanted)]


def _field_items(self: Any, numeric: bool) -> list[tuple[str, str, str]]:
    """Los campos de la capa elegida en ``self`` (una lista viva del módulo); de una capa que no se leyó, solo la propuesta."""
    found = (_CHOICES.number_fields if numeric else _CHOICES.text_fields).get(str(getattr(self, "layer", "")))
    return found if found else field_choices((), numeric=numeric)


def pit_name_items(self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Los campos de texto de la capa de origen (el nombre de cada polígono)."""
    return _field_items(self, False)


def pit_level_items(self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Los campos numéricos de la capa de origen (la cota de cada fondo)."""
    return _field_items(self, True)


def _chosen_field(typed: str, picked: str) -> str | None:
    """El campo que pide el diálogo: el tecleado (desde un guion) y, sin él, el de la lista; ``None`` si no hay ninguno."""
    return typed.strip() or (None if picked in ("", _NONE) else picked)


def refresh_pit_list(project: Any) -> None:
    """Vuelve a leer de ``project`` la lista de las cortas **calculadas** de la versión activa (su código y su nombre) que ofrecen «Línea de cielo…» y «Superficie y sólido…» (spec 018, T40e, H3-6);
    sin versión activa o sin cortas, «—». Solo lee; si no se puede leer, el error sigue."""
    from ...design import pit_layer  # al usarlo: habilitar no carga el cálculo

    _CHOICES.pits = [(_NONE, NOT_SHOWN, tr("There are no calculated pits in the active version"))]
    version = scene_versions.active()
    if version is None:
        return
    with project.read() as conn:
        heads = pit_layer.pit_heads(project, conn, version)
    if heads:
        _CHOICES.pits = [(head.code, f"{head.name} ({head.code})", tr("Pit of the active version")) for head in heads]


def pit_pick_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las cortas calculadas de la versión activa (una lista viva del módulo); sin ninguna, «—»."""
    if not _CHOICES.pits:
        _fixed_choices()
    return _CHOICES.pits


def _chosen_pit(operator: Any) -> str:
    """La corta que pide el diálogo: la tecleada en ``pit`` (desde un guion: su código o su nombre) o, sin ella, la de la lista; ``""`` si no hay ninguna (la del objeto seleccionado, si lo hay)."""
    typed = str(getattr(operator, "pit", "")).strip()
    picked = str(getattr(operator, "pit_pick", _NONE))
    return typed or ("" if picked == _NONE else picked)


def _propose_pit(operator: Any, context: Any) -> None:
    """Prepara el diálogo de una orden de una corta: la lista de las cortas leída de nuevo y, si no se dio ninguna, la del objeto seleccionado en la vista como la elegida."""
    try:
        refresh_pit_list(SESSION.project)
        if not str(operator.pit).strip():
            selected = _entity_or_selected("", context)
            if selected in {item[0] for item in _CHOICES.pits}:
                operator.pit_pick = selected
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.debug("No se pudo leer la lista de cortas", exc_info=True)


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


_TYPED: dict[str, Any] = {}
"""Lo escrito en el diálogo de «Nueva corta…» cuando el cálculo falló o se canceló (T40i, UI-14): solo en memoria, **nada en el proyecto**; ``key`` es el proyecto y la versión de entonces."""


def _typing_key() -> tuple[Any, str]:
    return (getattr(SESSION.project, "uid", None), scene_versions.active_version() or "")


def remember_typed(operator: Any) -> None:
    """Recuerda, en memoria, lo escrito en el diálogo de ``operator`` (T40i): se pone de nuevo en el siguiente diálogo, una sola vez, si es el mismo proyecto y la misma versión."""
    _TYPED.clear()
    _TYPED.update(key=_typing_key(), values={name: getattr(operator, name) for name in _pit_fields()})


def forget_typed() -> None:
    """Olvida lo recordado (el cálculo salió bien)."""
    _TYPED.clear()


def _restore_typed(operator: Any) -> None:
    """Pone en ``operator`` lo recordado (:func:`remember_typed`) salvo lo que dio quien lo lanzó; se usa una sola vez y solo con el mismo proyecto y versión. Un valor que ya no es válido
    (una capa que ya no está) se salta."""
    found = dict(_TYPED)
    _TYPED.clear()
    if not found or found["key"] != _typing_key():
        return
    for name, value in found["values"].items():
        if operator.properties.is_property_set(name):
            continue
        try:
            setattr(operator, name, value)
        except (TypeError, ValueError):
            LOGGER.info("No se recupera lo escrito en «%s»: ya no es válido", name)


def pit_error_text(exc: BaseException) -> str:
    """El texto de un error de «Nueva corta…»: el de ``design_error_text`` y, si falta una tolerancia del desfase, dónde está y qué hacer (T40i, UI-09)."""
    text = design_error_text(exc)
    if isinstance(exc, design_messages.DesignError) and exc.code == "des.entity_param_missing":
        parsed = design_params.parse_entity_key(exc.values.get("field"))
        if parsed is not None and parsed[1] == "pit" and parsed[2] in {param for _prop, param in _tolerance_rows()}:
            text = f"{text} " + tr("It is under «More options» of the dialog; the guide gives starting values")
    return text


def _start_notice(start: str) -> str | None:
    """RF-018-03, T40h: el aviso del diálogo cuando la partida es una entidad (por defecto, la última de la cadena: otra corta) y no el terreno, con su nombre legible (el de la lista) y cómo
    elegir otra; ``None`` si la partida es una superficie."""
    if not start.startswith("entity:"):
        return None
    label = next((item[1] for item in des_panels.platform_start_items(None, None) if item[0] == start), start)
    return tr("It starts from {surface}, not from the ground: a floor that is not below that surface is rejected; to start from the ground, choose it in «Start surface»", surface=label)


def _layer_changed(self: Any, context: Any) -> None:
    """El ``update`` de la capa de origen: los campos elegidos eran de la capa anterior, vuelven a la propuesta; y la vista previa, como con cualquier campo."""
    for prop in ("name_pick", "level_pick"):
        try:
            if getattr(self, prop) != _NONE:
                setattr(self, prop, _NONE)
        except (TypeError, ValueError):
            LOGGER.debug("El campo %s no vuelve a la propuesta", prop, exc_info=True)
    _refresh_pit_preview(self, context)


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
        items=pit_layer_items, options=_FIELD, update=_layer_changed)
    name_pick: EnumProperty(  # type: ignore[valid-type]
        name="Name field", description="Field of the layer with the name of each polygon: a text field (automatic: the field «nombre» or «name» or, without it, the number (fid))",
        items=pit_name_items, options=_FIELD, update=_refresh_pit_preview)
    level_pick: EnumProperty(  # type: ignore[valid-type]
        name="Elevation field", description="Field of the layer with the elevation of the floor of each polygon, in metres: a numeric field (ascending: each floor at its elevation)",
        items=pit_level_items, options=_FIELD, update=_refresh_pit_preview)
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
    # «Más opciones»: despliega lo que casi nunca se toca (valores por sector y tolerancias); solo cambia lo que dibuja el diálogo (H3-3).
    show_more: BoolProperty(  # type: ignore[valid-type]
        name="More options", description="Show or hide the options that are rarely touched: the values by sector and the tolerances of the offset", default=False, options=_HIDDEN)
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
            _restore_typed(self)  # lo escrito antes de un cálculo que falló (T40i)
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
        origin.prop(self, "name_pick", text=tr("Name field"), translate=False)  # la lista de los campos de texto; ``name_field`` es para los guiones
        if self.mode == "UP":
            origin.prop(self, "level_pick", text=tr("Elevation field"), translate=False)  # la de los numéricos; ``level_field``, para los guiones
        benches = layout.box()
        benches.prop(self, "profile", text=tr("Bench profile"), translate=False)
        benches.prop(self, "rose", text=tr("Rose of slopes"), translate=False)
        benches.prop(self, "n_berm", text=tr("Benches per berm"), translate=False)
        more = self._more_shown()
        fold = layout.row()  # lo que casi nunca se toca va plegado: así «Calcular» y «Cancelar» caben en 1920 × 1001 (H3-3)
        fold.prop(self, "show_more", text=tr("More options"), icon="TRIA_DOWN" if more else "TRIA_RIGHT", emboss=False, translate=False)
        if more:
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
        if more:
            tolerances = layout.box()
            tolerances.prop(self, "corner", text=tr("Corner of the offset"), translate=False)
            for prop, param in _tolerance_rows():
                label = {"arc_tol": tr("Arc tolerance (m)"), "simplify": tr("Simplification tolerance (m)"), "close_radius": tr("Closing radius (m)"),
                         "az_window": tr("Azimuth window (m)")}[prop]
                tolerances.prop(self, prop, text=label, translate=False)
                tolerances.label(text=_pit_param_text(param), translate=False)  # el tipo de cada tolerancia (RF-018-10, D-14)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        notice = _start_notice(self.start)
        if notice is not None:
            des_panels.draw_wrapped(layout, notice, DIALOG_WIDTH)
        layout.prop(self, "support", text=tr("Support surface"), translate=False)
        _draw_entity_preview_button(layout, self, CREATE_PIT, _pit_fields())  # «Vista previa» (RF-018-32)

    def _more_shown(self) -> bool:
        """Si el diálogo enseña lo plegado (los valores por sector y las tolerancias del desfase): lo pidió quien lo abrió o ya hay algo escrito (no se esconde lo escrito)."""
        return bool(self.show_more or self.corner != "DEFAULT" or any(getattr(self, prop).strip() for prop in _FOLDED_TEXT))

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
            name, road_model.LayerFields(self.layer, _chosen_field(self.name_field, self.name_pick)), self.mode.lower(), self.start,
            level_field=_chosen_field(self.level_field, self.level_pick) if up else None, support=chosen(self.support),
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
        if not code:
            remember_typed(self)  # si falla o se cancela, el diálogo vuelve a abrirse con lo escrito (T40i)
        try:
            request = self._entity_request(project, version, code) if code else self._request()
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, pit_error_text(exc))
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
            forget_typed()  # el cálculo salió bien: nada que recordar
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
        found = pit_error_text(exc)
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


# --- Expandir banco… (T32b; HU-018-2; RF-018-22, RF-018-23, RF-018-34, RF-015-28; plan 018 §5.3.3) -----------------------------------------------------

EXPAND_BENCH = provenance.PIT_EXPAND_COMMAND
EXPAND_KIND_ITEMS = [(_NOT_CHOSEN, "Not chosen", "The line says what it is (a layer of polylines of a pit) or it is taken as a foot"),
                     ("foot", "Foot", "The line is the foot of a bench: the bench that follows is its crest"),
                     ("crest", "Crest", "The line is the crest of a bench: the bench that follows is its foot")]
"""Lo que **es** la línea de partida si su capa no lo dice (RF-018-22)."""
_EXPAND_FIELDS = ("name", "source", "name_field", "feature", "line_pick", "bench", "bench_pick", "kind", "part", "part_pick", "mode", "start", "profile", "rose", "n_berm", "sector_profiles", "sector_roses", "sector_n_berm", "corner",
                  "arc_tol", "simplify", "az_window")
_EXPAND_LAYERS: list[tuple[str, str, str]] = []
"""Las líneas de partida que ofrece el diálogo de «Expandir banco…» (una lista viva del módulo)."""


def expand_source_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas de líneas con Z de las que parte «Expandir banco…» (una lista viva del módulo): las polilíneas de las cortas calculadas de la versión activa, los bancos ya expandidos, las
    rutas propuestas y las líneas de rotura del proyecto; sin ninguna, «—»."""
    if not _EXPAND_LAYERS:
        _EXPAND_LAYERS.append((_NONE, NOT_SHOWN, tr("There are no layers of 3D lines in the project")))
    return _EXPAND_LAYERS


@dataclass
class _ExpandLines:
    """Las listas vivas de la línea, el banco y la parte de «Expandir banco…» (T40j), de la capa de partida elegida: lo que leyó :func:`refresh_expand_lines`."""

    lines: list[Any] = field(default_factory=list)
    line_items: list[tuple[str, str, str]] = field(default_factory=list)
    bench_items: list[tuple[str, str, str]] = field(default_factory=list)
    part_items: list[tuple[str, str, str]] = field(default_factory=list)


_LINES = _ExpandLines()


def _lines_without_layer() -> None:
    """Sin capa de partida leída: solo la propuesta «automático»."""
    _LINES.lines = []
    _LINES.line_items = [(_NONE, tr("By bench, kind and part"), tr("The line is the one of the bench, kind and part below"))]
    _LINES.bench_items = [(_NONE, tr("Automatic"), tr("Bench 1, or the one the layer says"))]
    _LINES.part_items = [(_NONE, tr("Automatic"), tr("The first part, 0"))]


def expand_line_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las líneas de la capa de partida de «Expandir banco…» (una lista viva del módulo), precedidas por «por banco, tipo y parte»."""
    if not _LINES.line_items:
        _lines_without_layer()
    return _LINES.line_items


def expand_bench_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Los bancos que tiene la capa de partida (una lista viva del módulo), o «automático»."""
    if not _LINES.bench_items:
        _lines_without_layer()
    return _LINES.bench_items


def expand_part_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las partes que tiene la capa de partida (una lista viva del módulo), o «automático»."""
    if not _LINES.part_items:
        _lines_without_layer()
    return _LINES.part_items


def _kind_word(kind: str | None) -> str:
    return {"foot": tr("Foot"), "crest": tr("Crest")}.get(kind or "", kind or NOT_SHOWN)


def refresh_expand_lines(project: Any, layer: str) -> None:
    """Vuelve a leer de ``project`` las líneas de la capa de partida ``layer`` (T40j): la lista de las líneas (con su banco, su tipo, su parte y su cota si la capa los tiene, o su nombre), la de
    los bancos y la de las partes. Si no se puede leer (sin capa, sin versión), solo queda «automático»; solo lee."""
    _lines_without_layer()
    version = scene_versions.active()
    if version is None or layer in ("", _NONE):
        return
    from ...design import pit_expand  # al usarlo: habilitar no carga el cálculo

    try:
        found = pit_expand.source_lines(project, version, layer)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.info("No se pudieron leer las líneas de «%s»", layer, exc_info=True)
        return
    _LINES.lines = list(found)
    for item in found:
        level = "" if item.level_m is None else f" · {_metres(item.level_m)} m"
        if item.bench is not None and item.kind is not None:
            label = tr("Bench {bench} · {kind} · part {part}{level} ({name})", bench=item.bench, kind=_kind_word(item.kind), part=item.part or 0, level=level, name=item.name)
        else:
            label = f"{item.name}{level}"
        _LINES.line_items.append((str(item.fid), label, tr("Line of the layer")))
    benches = sorted({item.bench for item in found if item.bench is not None})
    parts = sorted({item.part or 0 for item in found if item.bench is not None})
    if benches:
        _LINES.bench_items += [(str(number), tr("Bench {bench}", bench=number), tr("Bench of the layer")) for number in benches]
    if parts:
        _LINES.part_items += [(str(number), tr("Part {part}", part=number), tr("Part of the bench: 0 is the first, the others only if the bench has several")) for number in parts]


def _propose_lines(operator: Any) -> None:
    """Lo que propone el diálogo de la línea de partida (T40j): el primer banco de la capa, su tipo y la parte 0; sin banco ni tipo en la capa, nada."""
    first = next((item for item in _LINES.lines if item.bench is not None and item.kind is not None), None)
    if first is None:
        return
    offered = {identifier for identifier, _label, _about in _LINES.bench_items}
    if str(first.bench) in offered:
        operator.bench_pick = str(first.bench)
    if "0" in {identifier for identifier, _label, _about in _LINES.part_items}:
        operator.part_pick = "0"
    if first.kind in ("foot", "crest"):
        operator.kind = first.kind


def _source_changed(self: Any, _context: Any) -> None:
    """El ``update`` de la línea de partida: las listas de la capa anterior no valen; se leen las de la nueva y vuelve la propuesta (T40j)."""
    self.line_pick = self.bench_pick = self.part_pick = _NONE
    project = SESSION.project
    if project is not None:
        refresh_expand_lines(project, self.source)
        _propose_lines(self)


def _chosen_whole(typed: str, picked: str, label: str) -> int | None:
    """El número tecleado (manda: viene de un guion) o, sin él, el de la lista (``none``: ninguno)."""
    return _whole(typed, label) if typed.strip() else (None if picked in ("", _NONE) else int(picked))


def refresh_expand_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` las líneas de partida del diálogo de «Expandir banco…» (RF-018-22): las polilíneas ``des_pbl_`` de las cortas de la versión activa, los bancos expandidos
    ``des_pxb_``, las rutas propuestas ``des_rpl_`` y las líneas de rotura ``gis_brk_``. Si no se puede leer, el error sigue."""
    from ...gis import provenance as gis_provenance
    from ...gis import store as gis_store

    found: list[tuple[str, str, str]] = []
    version = scene_versions.active()
    if version is not None:
        for code, about in ((provenance.PIT_POLYLINES_TABLE, tr("Polylines of a pit of the active version")),
                            (provenance.PIT_EXPANDED_TABLE, tr("Expanded bench of the active version (3D lines)")),
                            (provenance.ROUTE_LAYER_TABLE, tr("Proposed route of the active version (3D lines)"))):
            prefix = provenance.FAMILIES_BY_CODE[code].prefix
            found.extend((name, name.removeprefix(prefix), about) for name in _version_layers(project, version.uid, prefix))
    found.extend((record.name, constraint_panels.layer_label(record.name), tr("Layer of 3D lines"))
                 for record in gis_store.list_gis_datasets(project, families=(gis_provenance.BREAKLINES,)))
    _EXPAND_LAYERS[:] = found or [(_NONE, NOT_SHOWN, tr("There are no layers of 3D lines in the project"))]


def _pit_defaults(project: Any, source: str) -> dict[str, str]:
    """Lo que de la corta de la que sale la línea ``source`` (``des_pbl_<corta>``, de una corta de la versión activa) rellena el diálogo (RF-018-22): su perfil de banco, su roseta, los
    bancos por berma, lo de cada sector, la esquina y las tolerancias del desfase, en el texto del diálogo. Una línea que no es de una corta, o una corta sin esos valores, nada."""
    from ...design import entities, pit_store

    version = scene_versions.active()
    if version is None or not source.startswith(provenance.FAMILIES_BY_CODE[provenance.PIT_POLYLINES_TABLE].prefix):
        return {}
    for entry in entities.registry(project, version.uid):
        record = entry.record
        if record.kind is not entities.EntityKind.PIT or provenance.dataset_name(provenance.PIT_POLYLINES_TABLE, record.name) != source:
            continue
        values = pit_store.pit_parameters(project, version, record.code)
        found: dict[str, str] = {}
        for prop, key in (("profile", "profile"), ("rose", "rose"), ("corner", "corner")):
            if values.get(key):
                found[prop] = str(values[key])
        for prop, key in (("n_berm", "n_berm"), ("arc_tol", "arc_tol_m"), ("simplify", "simplify_m"), ("az_window", "az_window_m")):
            if values.get(key) is not None:
                found[prop] = str(values[key])
        for prop, key in (("sector_profiles", "profile"), ("sector_roses", "rose"), ("sector_n_berm", "n_berm")):
            pairs = [f"{short.partition('.')[2]}={value}" for short, value in sorted(values.items()) if short.startswith(f"{key}.")]
            if pairs:
                found[prop] = ";".join(pairs)
        return found
    return {}


class GEOBLENDER_OT_des_expand_bench(_CreatesInSteps, _CalculateAndCreate, DesignCommandAware, ProvenanceAwareOperator, _StepsModal, bpy.types.Operator):
    """Expand one bench of a pit of the active version into the next one with its profile: its foot into its crest or the other way round, as a layer of 3D lines that you can edit in QGIS and use as a fixed bench; it changes no surface and is not an entity"""

    bl_idname = EXPAND_BENCH
    bl_label = "Expand bench…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PIT_EXPAND
    COMMAND = EXPAND_BENCH

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the expanded bench, unique in the active version: the layer of 3D lines is called after it", options=_FIELD)
    source: EnumProperty(  # type: ignore[valid-type]
        name="Source line", description="Layer of 3D lines the bench is taken from: the polylines of a pit of the active version, an expanded bench, a proposed route or a breakline of the project",
        items=expand_source_items, options=_FIELD, update=_source_changed)
    name_field: StringProperty(  # type: ignore[valid-type]
        name="Name field", description="Field of the layer with the name of each line (empty: the field «nombre» or «name» or, without it, the number (fid))", options=_FIELD)
    feature: StringProperty(  # type: ignore[valid-type]
        name="Line", description="Name or number (fid) of the line of the layer to expand (empty: the bench, kind and part below, if the layer has them)", options=_FIELD)
    line_pick: EnumProperty(  # type: ignore[valid-type]
        name="Line", description="Line of the layer to expand, from the list (by bench, kind and part: the bench, kind and part below)", items=expand_line_items, options=_FIELD)
    bench: StringProperty(  # type: ignore[valid-type]
        name="Bench", description="Whole number of the bench to expand, when the layer says it (the polylines of a pit) or when you say it (empty: bench 1)", options=_FIELD)
    bench_pick: EnumProperty(  # type: ignore[valid-type]
        name="Bench", description="Bench of the layer to expand, from the list (automatic: bench 1)", items=expand_bench_items, options=_FIELD)
    part_pick: EnumProperty(  # type: ignore[valid-type]
        name="Part", description="Part of the bench, from the list: 0 is the first; the others only if the bench has several parts", items=expand_part_items, options=_FIELD)
    kind: EnumProperty(  # type: ignore[valid-type]
        name="Kind of line", description="Whether the line is the foot or the crest of a bench, if its layer does not say it", items=EXPAND_KIND_ITEMS, default=_NOT_CHOSEN, options=_FIELD)
    part: StringProperty(  # type: ignore[valid-type]
        name="Part", description="Whole number of the part of the bench, when it has several (empty: the first, 0)", options=_FIELD)
    mode: EnumProperty(  # type: ignore[valid-type]
        name="Mode", description="Ascending: the benches rise outwards. Descending: they go down inwards", items=PIT_MODE_ITEMS, default="UP", options=_FIELD)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface", description="Surface the bench starts from: by default, the last of the chain of the active version and, without it, the ground",
        items=des_panels.platform_start_items, options=_FIELD)
    profile: EnumProperty(  # type: ignore[valid-type]
        name="Bench profile", description="Bench profile of the expansion: its height, face angle, berm and anchor; create or complete them with «Bench profiles…»", items=pit_profile_items,
        options=_FIELD)
    rose: EnumProperty(  # type: ignore[valid-type]
        name="Rose of slopes", description="Rose of design slopes: the face angle and the berm by the direction of the face of each stretch of the bench (none: the bench profile alone)",
        items=pit_rose_items, options=_FIELD)
    n_berm: StringProperty(  # type: ignore[valid-type]
        name="Benches per berm", description="Whole number of benches between two berms (empty: the default value, one bench)", options=_FIELD)
    sector_profiles: StringProperty(  # type: ignore[valid-type]
        name="Profiles by sector", description="Bench profile of each design sector, written sector=profile and separated by «;»", options=_FIELD)
    sector_roses: StringProperty(  # type: ignore[valid-type]
        name="Roses by sector", description="Rose of design slopes of each design sector, written sector=rose and separated by «;»", options=_FIELD)
    sector_n_berm: StringProperty(  # type: ignore[valid-type]
        name="Benches per berm by sector", description="Benches per berm of each design sector, written sector=number and separated by «;»", options=_FIELD)
    corner: EnumProperty(  # type: ignore[valid-type]
        name="Corner of the offset", description="How the corners of the offset are made: rounded with arcs or mitred", items=PIT_CORNER_ITEMS, default="DEFAULT", options=_FIELD)
    arc_tol: StringProperty(  # type: ignore[valid-type]
        name="Arc tolerance (m)", description="Most the arcs of the rounded corners may separate from the circle, in metres; a hypothesis without default value", options=_FIELD)
    simplify: StringProperty(  # type: ignore[valid-type]
        name="Simplification tolerance (m)", description="Most a simplified bench line may separate from the offset, in metres; a hypothesis without default value", options=_FIELD)
    az_window: StringProperty(  # type: ignore[valid-type]
        name="Azimuth window (m)", description="Length in metres along the bench over which the azimuth of the face is averaged to choose the range of the rose; a hypothesis without default value",
        options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez. Un banco expandido
    # no pide confirmación: no graba ninguna superficie.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    _saved = False
    """Si lo que llega al modal es lo guardado del banco (y no el cálculo)."""

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué. Con ``confirm``, el diálogo de crear el cálculo abierto. Si no, las listas leídas de nuevo,
        la propuesta (un nombre, la primera línea, y **del perfil, la roseta, los sectores y las tolerancias de la corta de la que sale**) y el diálogo del cálculo: Intro calcula."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            return self._confirmation(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            des_panels.refresh_choices(project)
            des_panels.refresh_platform_choices(project)
            refresh_pit_choices(project)
            refresh_expand_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=command_text(catalog().commands[command_idname(self.COMMAND)].label), confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio: un nombre que no repite el de ningún banco expandido de la versión («Banco expandido 1»…), la primera línea de partida, la
        partida (la última de la cadena y, sin ella, el terreno: como «Nueva corta…») y, **si la línea es de una corta de la versión, el perfil, la roseta, los bancos por berma, los sectores,
        la esquina y las tolerancias de esa corta** (RF-018-22). Lo que ya dio quien lo lanza no cambia. Ninguna cifra minera se inventa."""
        given = self.properties.is_property_set
        if not self.name.strip():
            version = scene_versions.active()
            prefix = provenance.FAMILIES_BY_CODE[provenance.PIT_EXPANDED_TABLE].prefix
            taken = set() if version is None else set(_version_layers(project, version.uid, prefix))
            number = 1
            while provenance.dataset_name(provenance.PIT_EXPANDED_TABLE, f"{tr('Expanded bench')} {number}") in taken:
                number += 1
            self.name = f"{tr('Expanded bench')} {number}"
        offered = [item[0] for item in expand_source_items(self, None) if item[0] != _NONE]
        if offered and not given("source"):
            self.source = offered[0]
        refresh_expand_lines(project, self.source)  # las listas de la línea, el banco y la parte de esa capa, con su propuesta (T40j)
        if not given("bench_pick") and not given("part_pick") and not given("kind"):
            _propose_lines(self)
        if not given("start"):
            offered_starts = {item[0] for item in des_panels.platform_start_items(None, None)}
            start = des_panels.platform_default_start()
            if start is None or start not in offered_starts:
                grids = [identifier for identifier in offered_starts if identifier != _NONE and not identifier.startswith("entity:")]
                start = surface_proposal.ground_item(context, project, sorted(grids), des_panels.surface_choice) if grids else None
            if start is not None:
                self.start = start
        for prop, text in _pit_defaults(project, self.source).items():
            if given(prop):
                continue
            if prop in ("profile", "rose"):
                if text not in {item[0] for item in (pit_profile_items if prop == "profile" else pit_rose_items)(self, None)}:
                    continue
                setattr(self, prop, text)
            elif prop == "corner":
                if text.upper() in {item[0] for item in PIT_CORNER_ITEMS}:
                    self.corner = text.upper()
            else:
                setattr(self, prop, text)

    def draw(self, context: Any) -> None:
        """Arriba el nombre; la línea de partida —su capa, el campo del nombre, la línea o el banco, su tipo y su parte—; el sentido y la partida; el perfil, la roseta y los bancos por berma y lo
        de cada sector; y las tolerancias del desfase, **cada una con su tipo**. En la confirmación de crear, el resumen."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        origin = layout.box()
        origin.prop(self, "source", text=tr("Source line"), translate=False)
        origin.prop(self, "name_field", text=tr("Name field"), translate=False)
        origin.prop(self, "line_pick", text=tr("Line"), translate=False)
        if self.line_pick == _NONE:  # con una línea elegida no hace falta decir su banco, su tipo ni su parte
            origin.prop(self, "bench_pick", text=tr("Bench"), translate=False)
            origin.prop(self, "kind", text=tr("Kind of line"), translate=False)
            origin.prop(self, "part_pick", text=tr("Part"), translate=False)
        layout.prop(self, "mode", text=tr("Mode"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        benches = layout.box()
        benches.prop(self, "profile", text=tr("Bench profile"), translate=False)
        benches.prop(self, "rose", text=tr("Rose of slopes"), translate=False)
        benches.prop(self, "n_berm", text=tr("Benches per berm"), translate=False)
        sectors = layout.box()
        sectors.prop(self, "sector_profiles", text=tr("Profiles by sector"), translate=False)
        sectors.prop(self, "sector_roses", text=tr("Roses by sector"), translate=False)
        sectors.prop(self, "sector_n_berm", text=tr("Benches per berm by sector"), translate=False)
        tolerances = layout.box()
        tolerances.prop(self, "corner", text=tr("Corner of the offset"), translate=False)
        for prop, param, label in (("arc_tol", "arc_tol_m", tr("Arc tolerance (m)")), ("simplify", "simplify_m", tr("Simplification tolerance (m)")),
                                   ("az_window", "az_window_m", tr("Azimuth window (m)"))):
            tolerances.prop(self, prop, text=label, translate=False)
            tolerances.label(text=_pit_param_text(param), translate=False)  # el tipo de cada tolerancia (RF-018-10, D-14)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self) -> Any:
        """Lo pedido en el diálogo como la ``design.pit_expand.ExpandRequest`` (RF-018-22), comprobado sin escribir ni calcular nada: la capa de líneas con el campo de los nombres, la línea por su
        nombre o su número o por su banco, su tipo y su parte, el sentido, la partida, el perfil, la roseta, los bancos por berma, los sectores y las tolerancias, tecleados con coma o con punto
        decimal. Lo que se deja vacío lo resuelve el dominio: el valor por defecto o el rechazo con su nombre (RF-015-08). :class:`ComputeFormError` si falta algo que el diálogo necesita."""
        from ...design import pit_expand, road_model  # al usarlo: habilitar no carga el cálculo

        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the expanded bench"))
        if self.source in ("", _NONE):
            raise ComputeFormError(tr("Choose the line to expand: there is no layer of 3D lines in the project"))

        def chosen(value: str) -> str | None:
            return None if value in ("", _NONE) else value

        return pit_expand.ExpandRequest(
            name, road_model.LayerFields(self.source, self.name_field.strip() or None), self.mode.lower(), self.start if self.start != _NONE else "",
            kind=None if self.kind == _NOT_CHOSEN else self.kind, feature=self.feature.strip() or (None if self.line_pick in ("", _NONE) else self.line_pick),
            bench=_chosen_whole(self.bench, self.bench_pick, tr("Bench")), part=_chosen_whole(self.part, self.part_pick, tr("Part")) or 0,
            profile=chosen(self.profile), rose=chosen(self.rose), n_berm=_whole(self.n_berm, tr("Benches per berm")),
            sector_profiles=_pairs(self.sector_profiles, tr("Profiles by sector"), _text), sector_roses=_pairs(self.sector_roses, tr("Roses by sector"), _text),
            sector_n_berm=_pairs(self.sector_n_berm, tr("Benches per berm by sector"), _whole), corner=None if self.corner == "DEFAULT" else self.corner.lower(),
            arc_tol_m=typed_number(self.arc_tol, tr("Arc tolerance (m)")), simplify_m=typed_number(self.simplify, tr("Simplification tolerance (m)")),
            az_window_m=typed_number(self.az_window, tr("Azimuth window (m)")))

    # --- Calcular y crear ---------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido (sin escribir nada si falta algo), pasa por la puerta de la 008 y calcula el banco por pasos
        con ``design.steps.pit_expand_run`` —compila las máscaras antes si no están al día—, sin registrar nada (RF-015-03): desde la interfaz, en el modal con el avance y Esc (RF-018-35);
        desde un guion, de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar. Los rechazos (la capa, la línea, el perfil, la roseta, las tolerancias, el nombre
        repetido, la partida, un sector con la búsqueda pendiente…) y todas las cuentas son de ``design``."""
        if self.confirm:
            return self._create(context)
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
        try:
            request = self._request()
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
        steps = design_steps.pit_expand_run(project, request, version=version, budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _finished(self, context: Any, opened: Any) -> set[str]:
        """Con lo guardado llegando (:meth:`_creation_steps`), acaba: el banco ya está creado. Si no, como las demás (:meth:`_CalculateAndCreate._finished`): deja el cálculo abierto con su
        resumen y pide confirmar."""
        if self._saved:
            self._saved = False
            return {"FINISHED"}
        return _CalculateAndCreate._finished(self, context, opened)

    def _create(self, context: Any) -> set[str]:
        """«Crear» (RF-018-22, RF-015-02): registra el banco expandido —**la capa de líneas con Z editable en QGIS** y la operación, en una transacción— sin más confirmación que el botón (no
        graba ninguna superficie). Desde la interfaz, **por pasos** con el avance y Esc (:class:`_CreatesInSteps`); desde un guion, de una vez, con el mismo resultado. **No es una entidad**: no
        encadena la capa de entidades ni declara nada."""
        opened = calculation()
        if opened is None or opened.op_type != self.provenance_op_type:
            self.report({"ERROR"}, tr("There is no open calculation: compute first"))
            return {"CANCELLED"}
        started = self._create_in_steps(context, opened)
        if started is not None:  # desde la interfaz, por pasos
            return started
        return _CalculateAndCreate._create(self, context)

    def _creation_steps(self, project: Any, opened: Calculation) -> Iterator[Progress]:
        """Los pasos de «Crear» ``opened`` en el modal: los de ``Calculation.create_steps`` (la capa, montada y escrita en su temporal por pasos; la transacción final, el último) y, en cuanto lo
        guardado llega, lo registrado; **nada más**: no es una entidad. Cerrar los pasos antes (Esc) o un fallo no dejan nada: ``create_steps`` descarta el cálculo y borra sus temporales."""
        creating = opened.create_steps(budget_s=self.STEP_BUDGET_S)
        saved = None
        try:
            for step in creating:
                if step.result is not None:
                    saved = step
                    break
                yield step
        finally:
            creating.close()
        assert saved is not None  # los pasos acaban siempre con lo guardado
        self._registered(opened)
        self._creating, self._saved = False, True
        yield saved

    def _created_text(self, opened: Calculation) -> str:
        return tr("Bench «{name}» expanded in {version}: the layer «{layer}» is editable in QGIS", name=opened.name, version=opened.version,
                  layer=provenance.dataset_name(provenance.PIT_EXPANDED_TABLE, opened.name))

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Expandiendo el banco… 40 % · Esc: cancelar» o «Guardando el banco expandido… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self._creating:
            return tr("Saving the expanded bench… {percent} % · Esc: cancel", percent=percent)
        return tr("Expanding the bench… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if self._creating:
            return tr("Creation cancelled: the bench has not been expanded and the calculation has been discarded; nothing has been left half-done")
        return _CalculateAndCreate._cancelled_text(self)


# --- «Línea de cielo…» y «Superficie y sólido…» (spec 018, T33; HU-018-4; RF-018-29, RF-018-30, RF-018-33, RF-018-34) -------------------------------------------------------------------

SKYLINE = provenance.PIT_LAYER_COMMAND
"""La orden de «Línea de cielo…» (la de la operación ``des.pit_layer``)."""
SURFACE = "geoblender.des_pit_surface"
"""La orden de «Superficie y sólido…»."""
SURFACE_ITEMS = [
    ("TIN", "TIN", "The TIN of the pit, with its polylines and its skyline as edges, as a view of the 3D window (it writes nothing in the project)"),
    ("SOLID", "Excavation solid", "The solid of the excavation: a closed mesh between the start surface and the surface of the pit, as a view of the 3D window (it writes nothing in the project)"),
    ("SURFACE", "Surface to GeoTIFF", "The surface of the pit, the official one of the project, as a deliverable GeoTIFF"),
    ("FINDINGS", "Findings to CSV", "The findings of the pit, with their place, as a CSV file for Excel")]
"""Lo que hace «Superficie y sólido…»: las dos vistas y los dos entregables."""
_SURFACE_FILES = ("SURFACE", "FINDINGS")
"""Lo que pide un fichero."""


def _pit_of(given: str, context: Any) -> str:
    """La corta a la que se refiere una orden de la línea de cielo o de la superficie: la tecleada (su código o su nombre) o la del objeto seleccionado en la vista. :class:`ValueError` si no hay ninguna."""
    ref = _entity_or_selected(given, context)
    if not ref:
        raise ValueError(tr("Choose the pit: give its code or its name, or select its object in the 3D view"))
    return ref


def _metres(value: float) -> str:
    """Un número en metros con dos decimales y la coma decimal del español (el punto, en inglés)."""
    text = f"{float(value):,.2f}"
    return text if i18n.language() == "en" else text.replace(",", " ").replace(".", ",")


def _skyline_lines(shown: Any) -> list[str]:
    """Lo que dice el informe de la línea de cielo de ``shown`` (``design.pit_view.SkylineReport``): su título, sus cifras con su insignia de tipo y el lugar de las distancias."""
    language = i18n.language()
    lines = [tr("Skyline of pit «{name}» ({code}) in {version}", name=shown.name, code=shown.code, version=shown.version_code)]
    if not shown.figures:
        lines.append(tr("The pit has no skyline: it does not come out at the ground"))
    lines += [f"{ui_provenance.badge(figure.kind)} {provenance.figure_text(figure, language=language)}" for figure in shown.figures]
    for label, found in ((tr("legal limit"), shown.legal), (tr("perimeter of the works"), shown.perimeter)):
        if found is not None:
            lines.append(tr("Closest to the {limit}: the skyline at x = {x} m, y = {y} m, z = {z} m",
                            limit=label, x=_metres(found.on_line[0]), y=_metres(found.on_line[1]), z=_metres(found.on_line[2])))
    return lines


class GEOBLENDER_OT_des_pit_skyline(_EntitySteps, DesignCommandAware, ProvenanceAwareOperator, _StepsModal, bpy.types.Operator):
    """Show the figures of the skyline of a pit (where it comes out at the ground: its parts, its length, the area it encloses, its lowest and highest level and its distance to the legal limit and to the perimeter of the works) and bring its layer up to date if it is behind"""

    bl_idname = SKYLINE
    bl_label = "Skyline…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PIT_LAYER

    pit: StringProperty(  # type: ignore[valid-type]
        name="Pit", description="Code or name of the pit of the active version (empty: the one chosen in the list or, without it, the one of the object selected in the 3D view)", options=_FIELD)
    pit_pick: EnumProperty(  # type: ignore[valid-type]
        name="Pit", description="Pit of the active version, from the calculated ones", items=pit_pick_items, options=_FIELD)
    update_layer: BoolProperty(  # type: ignore[valid-type]
        name="Bring the layer up to date", description="If the layer of the skyline for QGIS is behind the pits of the version, bring it up to date (it is the only thing this command writes)", default=True,
        options=_FIELD)
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """El diálogo de la corta y de poner al día la capa; Intro la muestra. La corta del objeto seleccionado, si lo hay, se propone."""
        self.in_steps = getattr(context, "window", None) is not None
        _propose_pit(self, context)
        return context.window_manager.invoke_props_dialog(self, width=DIALOG_WIDTH, translate=False, title=tr("Skyline…"), confirm_text=tr("Show"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "pit_pick", text=tr("Pit"), translate=False)
        layout.prop(self, "update_layer", text=tr("Bring the layer up to date"), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Enseña las cifras registradas de la línea de cielo de la corta (``design.pit_view.skyline_report``: solo lee) y, si la capa de la línea de cielo está atrasada y ``update_layer``, la pone
        al día (``des.pit_layer``: una operación de la versión, por pasos con el avance y Esc desde la interfaz). Lo demás no escribe nada (RF-018-29, RF-018-33)."""
        from ...design import pit_layer, pit_view  # al usarlo: habilitar no carga el cálculo

        blocked = design_unavailable()
        refusal = None if blocked is not None else self._version_refusal()
        if blocked is not None or refusal is not None:
            self.report({"ERROR"}, blocked or refusal or "")
            return {"CANCELLED"}
        project, version = SESSION.project, scene_versions.active_version() or ""
        try:
            shown = pit_view.skyline_report(project, version, _pit_of(_chosen_pit(self), context))
        except (GeoblenderError, sqlite3.Error, OSError, ValueError, TypeError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        self.report_log = []
        for text in _skyline_lines(shown):
            self._report({"INFO"}, text)
        if not shown.layer_pending:
            self._report({"INFO"}, tr("The skyline layer of {version} is already up to date", version=shown.version_code))
            return {"FINISHED"}
        if not self.update_layer:
            self._report({"WARNING"}, tr("The skyline layer of {version} is behind the pits: tick «Bring the layer up to date» to bring it up to date", version=shown.version_code))
            return {"FINISHED"}
        self._version = shown.version_code
        return self._run_steps(context, project, shown.name, pit_layer.pit_layer_steps(project, version, budget_s=self.STEP_BUDGET_S))

    def _finished(self, context: Any, result: Any) -> set[str]:
        undo_watch.record(UndoKind.OPERATION, provenance.PIT_LAYER)  # Ctrl+Z no lo deshace
        self._report({"INFO"}, tr("The skyline layer of {version} is brought up to date", version=getattr(self, "_version", "")))
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        return {"FINISHED"}

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Bringing the skyline layer up to date… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Cancelled: the layer has been left as it was; nothing has been left half-done")


class GEOBLENDER_OT_des_pit_surface(_EntitySteps, DesignCommand, _StepsModal, bpy.types.Operator):
    """Create, when you ask for it, the TIN or the solid of the excavation of a pit as a view (with the warning before creating more triangles than the limit of a view) or write its surface to a GeoTIFF or its findings to a CSV; it writes nothing in the project"""

    bl_idname = SURFACE
    bl_label = "Surface and solid…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    pit: StringProperty(  # type: ignore[valid-type]
        name="Pit", description="Code or name of the pit of the active version (empty: the one chosen in the list or, without it, the one of the object selected in the 3D view)", options=_FIELD)
    pit_pick: EnumProperty(  # type: ignore[valid-type]
        name="Pit", description="Pit of the active version, from the calculated ones", items=pit_pick_items, options=_FIELD)
    what: EnumProperty(  # type: ignore[valid-type]
        name="What", description="The TIN or the solid of the pit as a view, or its surface to GeoTIFF or its findings to CSV", items=SURFACE_ITEMS, default="TIN", options=_FIELD)
    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH",
        description="File to write the surface or the findings to (empty: the exports folder of the project, with the name of the data and the version)", options={"SKIP_SAVE"})
    overwrite: BoolProperty(  # type: ignore[valid-type]
        name="Replace", description="Replace the file if it already exists", options=_FIELD)
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    confirm_large: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """El diálogo (la corta, qué se hace y el fichero); con ``confirm``, la confirmación de crear la vista por encima del límite de triángulos o de sustituir el fichero que ya existe."""
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            if self.confirm_large:
                return context.window_manager.invoke_confirm(self, event, title=tr("Create the view anyway"), confirm_text=tr("Create"), translate=False,
                                                             message=tr("«{name}» has more triangles than the limit of a view: it may be slow. Create it anyway?", name=self.pit))
            self.overwrite = True
            return context.window_manager.invoke_confirm(self, event, title=tr("Replace the file"), confirm_text=tr("Replace"), translate=False,
                                                         message=tr("«{file}» already exists: replace it?", file=Path(self.filepath).name))
        _propose_pit(self, context)
        return context.window_manager.invoke_props_dialog(self, width=DIALOG_WIDTH, translate=False, title=tr("Surface and solid…"), confirm_text=tr("Accept"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "pit_pick", text=tr("Pit"), translate=False)
        layout.prop(self, "what", text=tr("What"), translate=False)
        if self.what in _SURFACE_FILES:
            layout.prop(self, "filepath", text=tr("File"), translate=False)
            layout.prop(self, "overwrite", text=tr("Replace"), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Hace lo pedido sobre la corta de la versión activa sin escribir nada en el proyecto: **el TIN o el sólido** (``bl.scene.views.load_steps`` con los cargadores de ``bl.scene.pit_views``, por pasos con
        el avance y Esc; por encima del límite de triángulos, el aviso **antes de crear nada** y, desde la interfaz, la pregunta de si se crea de todos modos), o **la superficie a GeoTIFF**
        (``design.export.export_grid_steps``) o **los hallazgos a CSV** (``design.export.export_pit_findings_csv``) en ``filepath`` (vacío: la carpeta de exportaciones del proyecto), sin sustituir un fichero que existe
        salvo con ``overwrite``."""
        from ...design import pit_view  # al usarlo: habilitar no carga el cálculo

        blocked = design_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project, version = SESSION.project, scene_versions.active_version() or ""
        try:
            if not version:
                raise ValueError(tr("There is no active version: make the version of the pit the active one first"))
            found = pit_view.pit_datasets(project, version, _pit_of(_chosen_pit(self), context))
            if self.what in ("TIN", "SOLID"):
                return self._view(context, project, found)
            return self._export(context, project, found)
        except GisError as exc:
            interactive = self.in_steps and getattr(context, "window", None) is not None
            if exc.code == "gis.export_target_exists" and interactive:
                self.report({"WARNING"}, error_text(exc))
                _confirm_later({"pit": _chosen_pit(self), "what": self.what, "filepath": self.filepath}, idname=SURFACE)
            else:
                self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError, TypeError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}

    # --- Las vistas ---------------------------------------------------------------------------

    def _view(self, context: Any, project: Any, found: Any) -> set[str]:
        from ..scene import pit_views, views

        self._found = found
        pit_views.take_large()  # un aviso de antes no es de esta carga
        uid = found.polylines_uid if self.what == "TIN" else found.benches_uid
        confirmed = bool(self.confirm_large)

        def steps() -> Iterator[Progress]:
            if confirmed:
                with pit_views.unlimited():  # al cerrar los pasos (Esc) también se quita
                    yield from views.load_steps(context, project, [uid])
            else:
                yield from views.load_steps(context, project, [uid])

        return self._run_steps(context, project, found.name, steps())

    def _loaded(self, outcome: Any) -> set[str]:
        """Lo que dice la orden de lo cargado: los avisos, el aviso de triángulos (que, desde la interfaz, pregunta si se crea de todos modos) y los errores."""
        from ..scene import pit_views

        for text in outcome.notes:
            self._report({"WARNING"}, text)
        large = pit_views.take_large()
        if outcome.loaded:
            for text in outcome.errors:
                self._report({"WARNING"}, text)
            self._report({"INFO"}, tr("Loaded into the view: {names}", names=", ".join(outcome.labels or outcome.loaded)))
            return {"FINISHED"}
        if large is not None and not self.confirm_large and self.in_steps and getattr(bpy.context, "window", None) is not None:
            self._report({"WARNING"}, design_error_text(large))
            _confirm_later({"pit": _chosen_pit(self) or self._found.code, "what": self.what, "confirm_large": True}, idname=SURFACE)
            return {"FINISHED"}  # no se ha creado nada: la pregunta sigue
        for text in outcome.errors:
            self._report({"ERROR"}, text)
        return {"CANCELLED"}

    # --- Los entregables ----------------------------------------------------------------------

    def _target(self, project: Any, found: Any, dataset: str, suffix: str) -> Path:
        shown = self.filepath.strip()
        if shown:
            return Path(bpy.path.abspath(shown))
        return Path(project.root, gis_provenance.EXPORTS_FOLDER, f"{dataset}_{found.version_code}{suffix}")

    def _export(self, context: Any, project: Any, found: Any) -> set[str]:
        from ...design import export  # al usarlo: habilitar no lo carga

        self._found = found
        if self.what == "FINDINGS":
            target = self._target(project, found, found.findings, ".csv")
            export.export_pit_findings_csv(project, found.code, target, version=found.version_uid, read_only=read_only_dirs(), overwrite=bool(self.overwrite))
            self.report_log = []
            return self._written(target)
        target = self._target(project, found, found.surface, ".tif")
        stored = export.stored_grid(project, found.surface, version=found.version_uid)
        work = export.export_grid_steps(project, stored.family, stored.name, target, version=stored.version_uid, read_only=read_only_dirs(), overwrite=bool(self.overwrite))
        return self._run_steps(context, project, found.name, _export_progress(work, target.name))

    def _written(self, target: Path) -> set[str]:
        if self.what == "FINDINGS":
            self._report({"INFO"}, tr("Findings of the pit exported to «{file}»", file=target.name))
        else:
            self._report({"INFO"}, tr("Surface of the pit exported to «{file}»", file=target.name))
        return {"FINISHED"}

    def _finished(self, context: Any, result: Any) -> set[str]:
        from ..scene import views

        if isinstance(result, views.LoadOutcome):
            return self._loaded(result)
        return self._written(Path(result))

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self.what in ("TIN", "SOLID"):
            return tr("Creating the view of «{name}»… {percent} % · Esc: cancel", name=self._name, percent=percent)
        return tr("Exporting «{file}»… {percent} % · Esc: cancel", file=step.message, percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Cancelled: nothing has been left half-done")


classes: tuple[type, ...] = (GEOBLENDER_OT_des_create_pit, GEOBLENDER_OT_des_expand_bench, GEOBLENDER_OT_des_pit_skyline, GEOBLENDER_OT_des_pit_surface, GEOBLENDER_OT_des_edit_pit_rose, GEOBLENDER_OT_des_save_pit_rose, GEOBLENDER_OT_des_edit_pit_ramp,
                             GEOBLENDER_OT_des_save_pit_ramp)
"""Las órdenes de la corta por bancos (T31: «Nueva corta…»; T32: «Roseta de taludes…» y «Rampa…» con sus internas; las demás las ponen las tareas siguientes)."""

__all__ = ["CREATE_PIT", "EDIT_PIT_RAMP", "EDIT_PIT_ROSE", "EXPAND_BENCH", "GEOBLENDER_OT_des_create_pit", "GEOBLENDER_OT_des_pit_skyline", "GEOBLENDER_OT_des_pit_surface", "SKYLINE", "SURFACE", "classes", "refresh_expand_choices", "refresh_pit_choices", "refresh_ramp_choices"]
