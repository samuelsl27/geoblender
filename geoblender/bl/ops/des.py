# SPDX-License-Identifier: GPL-3.0-or-later
"""El diseño de explotación en Blender: envolventes y escalonado (código ``des``, spec 013; plan 013
§5.1, §5.2.4, §5.3.2, §5.3.3, D-14, D-19, D-30; ADR-0025 §2, ADR-0027).

**El registro** (T21; HU-013-1 a HU-013-6; RF-013-33): lo que la 013 declara en ``core``, en
constantes del módulo construidas una vez:

- sus **definiciones de parámetros** del proyecto (``design.params.DEFINITIONS``: la tolerancia
  de cara y el umbral de aviso de magnitud, 1,0 ° y 2,0 «sin confirmar») y sus **familias**
  (``design.params.FAMILIES``, ADR-0027: la altura, la cara, la berma, el ancla y el factor de
  malla de cada perfil de banco y el talud general máximo impuesto de cada sector, por su código
  inmutable y de versión, sin valor por defecto salvo el factor de malla: D-7);
- sus **tipos de operación** (:data:`OPERATION_DEFS`): ``des.envelope`` y ``des.stepped_design``,
  de la versión, repetibles y reproducibles (D-26), cada uno con su función de recálculo de
  :data:`RECOMPUTE` y la de reproducción de :data:`REPRODUCE`, y ``des.edit_bench_profiles``, del
  proyecto y sin repetición (``design.profiles.OPERATIONS``); y sus quince **cifras**
  (``design.provenance.FIGURES``);
- sus textos (``design.messages``) en ``core.i18n``.

:func:`register` pone lo que falta y apunta cómo quitarlo; :func:`unregister` quita solo eso, en
orden inverso: lo que otro registró antes con la misma clave, o puso después en su lugar, es suyo y
se queda (también una definición o una familia de ``des``). Los dos son simétricos e idempotentes:
registrar y desregistrar deja los registros de ``core`` como estaban (ADR-0025 §2). Nada pesado: lo
que registra son declaraciones ligeras (``design.params``, ``design.provenance``,
``design.profiles``, ``design.messages``) y el cálculo, el almacén y la reproducción
(``design.store``, ``design.reproduce``, ``design.steps`` y todo lo que arrastran: las máscaras, la
cadena de versiones…) se importan **al usarlos**, dentro de cada función: habilitar Geoblender
tarda ≤ 0,5 s (RNF-001-03).

**Recalcular lo obsoleto** (D-19, plan §5.3.2; RF-013-17, RF-008-26): las funciones de
:data:`RECOMPUTE` (:func:`recompute_envelope` y :func:`recompute_design`) empiezan con
``design.store.recompute_run`` la operación que sustituye a la obsoleta (en la revisión abierta de
**su** versión, con lo que lee hoy), **sin pedir confirmación** (la operación ya existe y se repite
con sus ajustes), dejan sus pasos en la cola de ``des`` (:data:`RUNS`, :func:`queue_steps`) y la
devuelven «en curso»: ``recompute_steps`` de la 008 espera («Esperando a «des.envelope»…») mientras
el temporizador de la cola (:func:`des_tick`, persistente) da un paso de la primera por llamada, de
``design.store.STEP_BUDGET_S`` como mucho, con su avance en la barra de estado («Recalculando
«Ampliación»… 40 %»). Unos pasos que fallan dejan su operación «fallida» con el motivo (si sus pasos
no lo hicieron ya) y sigue la siguiente. Desregistrar cierra lo que espera, como Esc: lo empezado
lo cancelan sus pasos sin dejar nada a medias (RF-013-33) y lo que no empezó queda «cancelado» (no
«en curso»). En ``blender -b`` no corren los temporizadores: las pruebas llaman a :func:`des_tick`
a mano.

**Reproducir** (RF-009-11): las funciones de :data:`REPRODUCE` son las de ``design.reproduce``,
importadas al usarlas (como ``core.versions.reproduce`` en ``bl.ops.versions``).

**El cálculo abierto** (D-14, RF-013-31; plan §5.3.2): «Calcular» deja un cálculo hecho y **sin
registrar** (``design.steps.Calculation``), con sus rejillas en temporales junto a su destino, hasta
que la persona lo crea o lo cancela. Es de la sesión: :func:`hold_calculation` lo guarda en memoria
(el anterior se descarta), :func:`calculation` lo da mientras siga abierto y
:func:`discard_calculation` lo descarta. Cambiar de proyecto (cerrarlo o abrir otro:
:func:`project_changed`) y desactivar Geoblender lo descartan: no quedan ``*.tif.tmp-*``. La
confirmación de la orden no recalcula: llama a ``create()`` de éste.

**La disponibilidad** (RF-013-33): :func:`design_unavailable` dice por qué no se puede lanzar ahora
una orden de Diseño que escribe, en el idioma de Geoblender: sin proyecto, sin la procedencia o en
solo lectura («Proyecto en solo lectura: …»), o con la versión activa SUPERADO o DESCARTADO («V02
está en estado SUPERADO: cree una versión nueva a partir de ella»); ``None`` si se puede, también
sin versión activa (la orden que calcula la pide al lanzarla, RF-009-05). :class:`DesignCommand` es
el ``poll`` común de las cuatro órdenes de «Diseño» de R-33 (Perfiles de banco…, Sectores de
diseño…, Vista previa de semillas, dominios y restricciones y Envolventes y escalonado…) y
:class:`DesignCommandAware`, el de las que son además de :class:`ProvenanceAwareOperator`, con su
descripción con el porqué si la versión activa no es editable (RF-009-21).

**Perfiles de banco…** (T22; RF-013-18, RF-013-19, RF-013-20):
:class:`GEOBLENDER_OT_des_edit_bench_profiles` abre la ventana de ``bl.ui.des_panels`` (lo
leído del proyecto) y la interna :class:`GEOBLENDER_OT_des_save_bench_profile` crea, completa y renombra perfiles con
``design.profiles.edit_bench_profiles`` (una operación de proyecto, en una transacción, con el
ámbito de la 009 «¿Para el proyecto o solo para V01?»); cambiar un valor que ya existe es
``core_set_parameter`` (la 008 y la 009). Ninguna cuenta ni regla de rango es de aquí: las del
dominio (``design.model.BenchProfile``, ``design.params``).

**Sectores de diseño…** (T23; RF-013-07, RF-013-08, RF-013-09, RF-013-10, RF-013-21):
:class:`GEOBLENDER_OT_des_edit_design_sectors` abre la ventana de ``bl.ui.des_panels`` con los
sectores de la 012 (o el perímetro como único sector), el estado de su búsqueda, el talud que
impone cada uno y el perfil asignado, y la interna :class:`GEOBLENDER_OT_des_set_sector_slope`
guarda ese talud como el parámetro de su código (``des.sector.{código}.max_general_slope_deg``,
ADR-0029) con su tipo, su origen, su decisor y su motivo, en el proyecto o solo en la versión
activa (la 009): lo crea la primera vez en el ámbito y lo cambia después (su historial). «Declarar
de nuevo desde una capa…» es la orden de la 012 (``core_declare_sectors``): conserva los valores de
los sectores que mantienen su código y los demás quedan en la lista de huérfanos, sin borrarlos.
Ninguna regla de rango ni cuenta es de aquí: las del dominio (``design.params``,
``design.sectors``).

**Las demás órdenes** (T24, T25 y T28) y **los cargadores de la vista** (T27) se añaden en sus
tareas: :data:`classes` irá creciendo con ellas. El cargador de las rejillas ``des_env_``,
``des_srf_`` y ``des_brm_`` (objetos ``DESIGN``) es de ``bl/scene/des_views.py`` (T27), que
registra ``bl.scene`` junto al tipo de objeto que necesita.
"""

from __future__ import annotations

import functools
import logging
import math
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import EnumProperty, StringProperty

from ...core import i18n
from ...core import params as core_params
from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.params import ParamKind
from ...core.project.model import Progress
from ...core.provenance import contract
from ...core.provenance.undo import UndoKind
from ...design import messages as design_messages
from ...design import params as design_params
from ...design import profiles as design_profiles
from ...design import provenance
from ...design.model import PERIMETER_SEGMENT
from ..scene import project_session, undo_watch
from ..scene import versions as scene_versions
from ..ui import constraint_panels, des_panels
from ..ui import provenance as ui_provenance
from ..ui.commands import with_note
from . import incorporation
from .core_provenance import (
    KIND_ITEMS,
    PARAMETER_SCOPE_ITEMS,
    SESSION,
    SOURCE_KIND_ITEMS,
    ProvenanceAwareOperator,
    ensure_ready,
    error_text,
    scope_choice,
    typed_value,
    write_unavailable,
)
from .incorporation import StepQueue

if TYPE_CHECKING:  # solo para los tipos: habilitar no importa el cálculo (RNF-001-03)
    from ...core.project.session import Project
    from ...core.provenance.operations import OperationHandle
    from ...core.provenance.recompute import RecomputeRequest
    from ...core.versions.reproduce import ReproduceRequest
    from ...design.sectors import DesignSector
    from ...design.steps import Calculation

LOGGER = logging.getLogger("geoblender.bl.ops")
MODULE = provenance.MODULE
"""El módulo de las definiciones, las familias, los tipos y las cifras del diseño (``des``)."""

RECOMPUTING = incorporation.RECOMPUTING
"""Lo que dice la barra de estado de unos pasos de la cola (``msgid`` con ``name`` y
``percent``)."""
DROPPED_REASON = incorporation.DROPPED_REASON
"""El motivo de una operación cuyos pasos esperaban en la cola sin haber empezado al
desactivar Geoblender."""

_UNDO: list[Callable[[], None]] = []


# --- La cola de los pasos del recálculo (D-19) ---------------------------------------------------

RUNS = StepQueue()
"""Los pasos de las operaciones de ``des`` que recalcula «Recalcular lo obsoleto», por orden de
llegada (la cola es suya, aparte de las de la topografía, los sondeos, la cubicación y las
máscaras)."""
des_tick: Callable[[], float | None] = RUNS.timer
"""El temporizador de la cola de ``des``: un paso de la primera por llamada (el mismo objeto
siempre: Blender reconoce un temporizador por su función)."""


def pending_runs() -> list[str]:
    """Las operaciones cuyos pasos esperan en la cola, en orden."""
    return RUNS.pending()


def _shown_name(handle: Any) -> str:
    """El nombre de la envolvente o del escalonado de ``handle`` (sus ajustes) o, sin él, su
    tipo."""
    name = (getattr(handle, "settings", None) or {}).get("name")
    return name.strip() if isinstance(name, str) and name.strip() else str(handle.op_type)


def queue_steps(handle: OperationHandle, steps: Iterator[Progress]) -> None:
    """Pone en la cola de ``des`` los pasos ``steps`` (``Progress``) de la operación ``handle``,
    «en curso», y registra su temporizador si no lo estaba."""
    name = _shown_name(handle)
    RUNS.add(handle.uid, name, incorporation.RecomputeSteps(handle, name, steps),
             status=RECOMPUTING)


def _recompute(request: RecomputeRequest) -> OperationHandle:
    """La operación nueva de ``request`` (``design.store.recompute_run``), «en curso», con sus
    pasos en la cola de ``des``."""
    from ...design import store  # al usarlo: habilitar no carga el cálculo

    handle, steps = store.recompute_run(request)
    queue_steps(handle, steps)
    return handle


def recompute_envelope(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.envelope`` (RF-008-26; RF-013-17; D-19): véase el módulo."""
    return _recompute(request)


def recompute_design(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.stepped_design`` (RF-008-26; RF-013-17; D-19): véase el módulo."""
    return _recompute(request)


def reproduce_envelope(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.envelope``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_envelope(request)


def reproduce_design(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.stepped_design``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_design(request)


# --- Declaraciones de la procedencia (ADR-0025 §2; plan §5.2.3) ----------------------------------

RECOMPUTE: Mapping[str, Callable[[RecomputeRequest], OperationHandle]] = MappingProxyType({
    provenance.ENVELOPE: recompute_envelope,
    provenance.STEPPED: recompute_design,
})
"""La función de recálculo de cada tipo de ``des`` que se repite solo (RF-008-26)."""
REPRODUCE: Mapping[str, Callable[[ReproduceRequest], Iterator[Progress]]] = MappingProxyType({
    provenance.ENVELOPE: reproduce_envelope,
    provenance.STEPPED: reproduce_design,
})
"""La función de reproducción de cada tipo de ``des`` que se repite solo (RF-009-11)."""
OPERATION_DEFS: tuple[contract.OperationDef, ...] = (
    *provenance.operation_defs(RECOMPUTE, REPRODUCE), *design_profiles.OPERATIONS)
"""Los ``OperationDef`` de los tres tipos de ``des`` (spec 013): la envolvente y el escalonado, de
la versión y repetibles, y la edición de los perfiles de banco, del proyecto."""
DEFINITIONS: tuple[core_params.ParamDef, ...] = design_params.DEFINITIONS
"""Las definiciones de parámetros del proyecto de ``des``."""
FAMILIES: tuple[core_params.ParamFamily, ...] = design_params.FAMILIES
"""Las familias de parámetros de ``des`` (ADR-0027)."""
FIGURES: tuple[contract.FigureDef, ...] = provenance.FIGURES
"""Las cifras de ``des``: las de la envolvente y las del escalonado."""


# --- Registro ------------------------------------------------------------------------------------


def register() -> None:
    """Instala los textos del diseño en ``core.i18n`` y registra sus definiciones de parámetros
    (:data:`DEFINITIONS`), sus familias, sus tipos de operación (:data:`OPERATION_DEFS`) y sus
    cifras (:data:`FIGURES`) que aún no están, y se apunta a los cambios de proyecto de la sesión
    (:func:`project_changed`); idempotente."""
    i18n.install(design_messages.CATALOG_ES)
    missing = tuple(defn for defn in DEFINITIONS if defn.key not in core_params.DEFINITIONS)
    if missing:
        core_params.register_definitions(missing)
        _UNDO.append(functools.partial(_unregister_definitions, missing))
    families = tuple(family for family in FAMILIES
                     if family.pattern not in core_params.FAMILIES)
    if families:
        core_params.register_families(families)
        _UNDO.append(functools.partial(_unregister_families, families))
    for definition in OPERATION_DEFS:
        if definition.op_type not in contract.OPERATIONS:
            contract.register_operation(definition)
            _UNDO.append(_unregister_if(contract.OPERATIONS, definition.op_type, definition,
                                        contract.unregister_operation))
    for figure in FIGURES:
        if figure.key not in contract.FIGURES:
            contract.register_figure(figure)
            _UNDO.append(_unregister_if(contract.FIGURES, figure.key, figure,
                                        contract.unregister_figure))
    if project_changed not in project_session.listeners():
        project_session.add_listener(project_changed)
        _UNDO.append(functools.partial(project_session.remove_listener, project_changed))


def unregister() -> None:
    """Cierra los pasos que esperan en la cola (como Esc; véase el módulo), descarta el cálculo
    abierto y quita lo que puso :func:`register`, en orden inverso (lo que otro cambió después es
    suyo); las traducciones instaladas se quedan; idempotente."""
    RUNS.drop()
    discard_calculation()
    while _UNDO:
        _UNDO.pop()()


def _unregister_if(view: Mapping[str, Any], key: str, item: object,
                   remove: Callable[[str], object]) -> Callable[[], None]:
    def undo() -> None:
        if view.get(key) is item:  # si otro lo cambió, es suyo
            remove(key)

    return undo


def _unregister_definitions(ours: tuple[core_params.ParamDef, ...]) -> None:
    """Quita las definiciones que puso :func:`register` (``ours``) y deja las demás de ``des``:
    las que otro registró antes con su clave o puso después en su lugar son suyas.
    ``core.params`` solo las quita por módulo: se quitan todas y se vuelven a poner las de otro,
    los mismos objetos."""
    mine = {id(defn) for defn in ours}
    others = [defn for defn in core_params.DEFINITIONS.values()
              if defn.module == MODULE and id(defn) not in mine]
    core_params.unregister_definitions(MODULE)
    if others:
        core_params.register_definitions(others)


def _unregister_families(ours: tuple[core_params.ParamFamily, ...]) -> None:
    """Como :func:`_unregister_definitions`, con las familias (ADR-0027)."""
    mine = {id(family) for family in ours}
    others = [family for family in core_params.FAMILIES.values()
              if family.module == MODULE and id(family) not in mine]
    core_params.unregister_families(MODULE)
    if others:
        core_params.register_families(others)


# --- El cálculo abierto (D-14, RF-013-31) --------------------------------------------------------

_HELD: list[Calculation] = []  # a lo más uno: el cálculo hecho y sin registrar de la sesión


def hold_calculation(opened: Calculation) -> None:
    """Deja ``opened`` (un ``design.steps.Calculation`` hecho y sin registrar) como el cálculo
    abierto de la sesión: el anterior, si lo había y sigue abierto, se descarta (sus temporales
    se borran)."""
    previous = _HELD[:]
    _HELD[:] = [opened]
    for other in previous:
        if other is not opened:
            _discard(other)


def calculation() -> Calculation | None:
    """El cálculo abierto de la sesión, o ``None`` si no hay: uno que ya se creó o se descartó
    (``Calculation.open`` falso) se olvida."""
    if _HELD and not _HELD[0].open:
        _HELD.clear()
    return _HELD[0] if _HELD else None


def discard_calculation() -> None:
    """Descarta el cálculo abierto de la sesión («Cancelar», cerrar la ventana, cambiar de
    proyecto, desactivar Geoblender): borra sus temporales y no deja nada. Sin él, nada."""
    held = _HELD[:]
    _HELD.clear()
    for other in held:
        _discard(other)


def _discard(held: Calculation) -> None:
    try:
        held.discard()
    except Exception:  # noqa: BLE001 - lo que queda son temporales; no impide seguir
        LOGGER.exception("No se pudieron borrar los temporales de un cálculo del diseño")


def project_changed(_project: Project | None) -> None:
    """Lo que se hace cuando la sesión pasa a tener otro proyecto o ninguno
    (``project_session.add_listener``): el cálculo abierto era del anterior y se descarta."""
    discard_calculation()


# --- Disponibilidad (RF-013-33) ----------------------------------------------------------------


def design_unavailable() -> str | None:
    """Por qué no están disponibles ahora las órdenes de Diseño que escriben (RF-013-33), en el
    idioma de Geoblender: sin proyecto, sin la procedencia o en solo lectura («Proyecto en solo
    lectura: …»), o con la versión activa SUPERADO o DESCARTADO («V02 está en estado SUPERADO:
    cree una versión nueva a partir de ella»); ``None`` si se puede, también sin versión activa
    (la orden que calcula la pide al lanzarla, RF-009-05). Con lo ya leído de las versiones
    (``bl.scene.versions``): no lee el proyecto."""
    return write_unavailable() or scene_versions.not_editable_text()


def _write_poll(cls: type) -> bool:
    """El ``poll`` de lo que escribe: dice por qué no se puede."""
    reason = design_unavailable()
    if reason is not None:
        cls.poll_message_set(reason)  # type: ignore[attr-defined]
        return False
    return True


class DesignCommand:
    """El ``poll`` común de las órdenes de Diseño de R-33: activas con un proyecto en escritura y la
    versión activa editable (o ninguna), y desactivadas con su motivo en las demás
    (:func:`design_unavailable`; RF-013-33). Se pone **antes** de la base de la orden::

        class GEOBLENDER_OT_des_x(DesignCommand, bpy.types.Operator): ...
    """

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _write_poll(cls)


class DesignCommandAware(DesignCommand):
    """Lo de :class:`DesignCommand` y, en una orden de ``ProvenanceAwareOperator``, su descripción
    con el porqué si la versión activa no es editable (RF-013-33, RF-009-21), una sola vez aunque
    la base ya lo dijera."""

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        about: str = super().description(context, properties)  # type: ignore[misc]
        note = scene_versions.not_editable_text()
        return about if note is None or note in about else with_note(about, note)


# --- Ventanas ------------------------------------------------------------------------------------

TRANSLATION_CONTEXT = "Geoblender"
DIALOG_WIDTH = 520
_HIDDEN = {"HIDDEN", "SKIP_SAVE"}  # las pone quien la lanza (el botón de la ventana)
_FIELD = {"SKIP_SAVE"}  # las rellena el diálogo: nunca las de la vez anterior
PROFILE_KIND_ITEMS = [item for item in KIND_ITEMS if item[0] in ("ADOPTADO", "HIPOTESIS")]
"""Los tipos con que una persona declara los valores de un perfil (RF-013-18, D-7): ADOPTADO o
HIPÓTESIS (``design.profiles.DECLARED_KINDS``)."""
_EXAMPLE = "p"  # un código cualquiera para preguntar el ámbito de las claves de los perfiles


def _call_panel(name: str) -> set[str]:
    """Abre la ventana emergente ``name`` con ``wm.call_panel``; sigue abierta aunque el ratón
    salga de ella (``keep_open``), hasta pulsar fuera o Esc. Una que no está registrada, nada."""
    if getattr(bpy.types, name, None) is None:
        return {"CANCELLED"}
    return bpy.ops.wm.call_panel(name=name, keep_open=True)


def design_error_text(exc: BaseException) -> str:
    """El texto de un error para la persona en el idioma de Geoblender: el de ``design`` en su
    idioma (``DesignError.text`` es el español) y el de los demás, el de ``core``."""
    if isinstance(exc, design_messages.DesignError):
        return des_panels.design_error_text(exc)
    return error_text(exc)


# --- Perfiles de banco… (T22; HU-013-4; RF-013-18, RF-013-19, RF-013-20, RF-013-33) ---------------

EDIT_BENCH_PROFILES = design_profiles.EDIT_COMMAND
SAVE_BENCH_PROFILE = des_panels.SAVE_PROFILE


class ProfileFormError(ValueError):
    """Lo que impide guardar un perfil con lo escrito en el diálogo (ya en el idioma de
    Geoblender)."""


def typed_number(typed: str, field: str) -> float | None:
    """Un número tecleado (con coma o con punto decimal; sin separador de miles): ``None`` si está
    vacío. :class:`ProfileFormError` si no es un número finito, nombrando el campo y lo tecleado
    (los rangos los mira el dominio, RF-013-19)."""
    text = typed.strip().replace(" ", "").replace(" ", "").replace(" ", "")
    if not text:
        return None
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise ProfileFormError(tr("«{value}» is not a number (field «{field}»)",
                                  value=typed.strip(), field=field))
    return number


class GEOBLENDER_OT_des_edit_bench_profiles(DesignCommandAware, ProvenanceAwareOperator,
                                            bpy.types.Operator):
    """Bench profiles such as EXPL_10_60_6 or REST_5_35_6"""

    bl_idname = EDIT_BENCH_PROFILES
    bl_label = "Bench profiles…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = design_profiles.EDIT_BENCH_PROFILES

    def execute(self, context: Any) -> set[str]:
        """Lee los perfiles del proyecto y sus valores en la versión activa en la vista y abre su
        ventana; desde un guion sin ventana, solo la vista (RF-013-18, RF-013-20)."""
        try:
            des_panels.fill_profiles(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(des_panels.PROFILES_PANEL)


class GEOBLENDER_OT_des_save_bench_profile(DesignCommandAware, ProvenanceAwareOperator,
                                           bpy.types.Operator):
    """Create a bench profile, complete the values it lacks or rename it"""

    bl_idname = SAVE_BENCH_PROFILE
    bl_label = "Save profile…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = design_profiles.EDIT_BENCH_PROFILES

    code: StringProperty(  # type: ignore[valid-type]
        name="Profile", description="Code of the profile to complete or rename (empty: a new "
        "profile)", options=_HIDDEN)
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the profile, such as EXPL_10_60_6: it can change, its "
        "code cannot", options=_FIELD)
    height: StringProperty(  # type: ignore[valid-type]
        name="Bench height (m)", description="Height of the bench in metres, more than 0",
        options=_FIELD)
    face: StringProperty(  # type: ignore[valid-type]
        name="Face angle (°)", description="Maximum inclination of the bench face in degrees, "
        "between 0 and 90 (both excluded)", options=_FIELD)
    berm: StringProperty(  # type: ignore[valid-type]
        name="Minimum berm width (m)", description="Minimum berm in metres, 0 or more",
        options=_FIELD)
    anchor: StringProperty(  # type: ignore[valid-type]
        name="Anchor elevation (m)", description="Elevation the benches are anchored to, in "
        "metres", options=_FIELD)
    mesh: StringProperty(  # type: ignore[valid-type]
        name="Mesh factor", description="Factor between 0 (excluded) and 1 that reduces the "
        "slope of the envelope for the grid (empty: 1)", options=_FIELD)
    kind: EnumProperty(  # type: ignore[valid-type]
        name="Type", description="Type of the values: adopted or hypothesis",
        items=PROFILE_KIND_ITEMS, default="HIPOTESIS", options=_FIELD)
    source: StringProperty(  # type: ignore[valid-type]
        name="Source", description="Document, standard, person, operation or algorithm the "
        "values come from (empty: the decider)", options=_FIELD)
    source_kind: EnumProperty(  # type: ignore[valid-type]
        name="Source type", items=SOURCE_KIND_ITEMS, default="PERSON", options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decided the values (the owner, a laboratory, a "
        "person)", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the profile has these values (recorded in its history)",
        options=_FIELD)
    scope: EnumProperty(  # type: ignore[valid-type]
        name="Scope",
        description="Whether the change is for the project or only for the active version (a "
                    "parameter that its module admits by version)",
        items=PARAMETER_SCOPE_ITEMS, default="PROJECT", options=_FIELD)

    def _stored(self, project: Any) -> design_profiles.StoredProfile | None:
        """La fila del perfil de :attr:`code` en el proyecto; ``ProfileFormError`` si ya no
        está (sin código, ``None``: un perfil nuevo)."""
        if not self.code:
            return None
        with project.read() as conn:
            found = [row for row in design_profiles.read_profiles(conn) if row.code == self.code]
        if not found:
            raise ProfileFormError(tr("The bench profile is no longer in the project: open the "
                                      "list again"))
        return found[0]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo: de un perfil que existe, con su nombre y lo que ya vale en cada ámbito
        (solo se piden los valores que le faltan); de uno nuevo, vacío. Propone el decisor
        (la persona de la sesión) y, de los parámetros de versión con una versión activa, el
        ámbito (RF-009-29); no cambia nada hasta que se acepta."""
        self.provenance_dialog = True
        project = SESSION.project
        try:
            row = self._stored(project)
            self._known = {} if row is None else _known_values(project, row.code)
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
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Bench profile"),
            confirm_text=tr("Save"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        choice = scope_choice(design_params.bench_key(_EXAMPLE, design_params.BenchParam.HEIGHT))
        if choice is not None:  # «¿Para el proyecto o solo para V01?» (RF-009-29)
            layout.label(text=tr("For the project or only for {version}?", version=choice.code),
                         translate=False)
            row = layout.row(align=True)
            row.use_property_split = False
            row.prop_enum(self, "scope", "PROJECT", text=tr("The project"), translate=False)
            only = row.row(align=True)
            only.enabled = choice.refusal is None  # «Versión no editable» (RF-009-21)
            only.prop_enum(self, "scope", "VERSION",
                           text=tr("Only {version}", version=choice.code), translate=False)
            if choice.refusal is not None:
                refused = layout.row()
                refused.alert = True
                refused.label(text=choice.refusal, icon="ERROR", translate=False)
        known = getattr(self, "_known", {})
        declared = False
        for param, attribute, label in (
                (design_params.BenchParam.HEIGHT, "height", tr("Bench height (m)")),
                (design_params.BenchParam.FACE, "face", tr("Face angle (°)")),
                (design_params.BenchParam.BERM, "berm", tr("Minimum berm width (m)")),
                (design_params.BenchParam.ANCHOR, "anchor", tr("Anchor elevation (m)")),
                (design_params.BenchParam.MESH_FACTOR, "mesh", tr("Mesh factor"))):
            here = known.get(param, {}).get(self.scope)
            if here is not None:  # ya vale en ese ámbito: se cambia con «Cambiar…»
                layout.label(text=tr("{name}: {value}", name=label, value=here), translate=False)
                declared = True
            else:
                layout.prop(self, attribute, text=label, translate=False)
        if declared:
            layout.label(text=tr("Values already declared are changed with «Change…» in the "
                                 "list"), translate=False)
        layout.prop(self, "kind", text=tr("Type"), translate=False)
        layout.prop(self, "source", text=tr("Source"), translate=False)
        layout.prop(self, "source_kind", text=tr("Source type"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def _request(self, project: Any) -> tuple[design_profiles.ProfileEdit,
                                              design_profiles.ProfileDeclaration | None]:
        """Lo escrito, como lo pide el dominio: la edición (un perfil nuevo con sus valores, o el
        existente con su nombre nuevo y los valores que se completan) y la declaración de los
        valores (tipo, origen, decisor, motivo y ámbito). :class:`ProfileFormError` si lo escrito
        no se puede leer o no cambia nada; los rangos, los nombres y los valores que faltan los
        rechaza el dominio (``DesignError``, RF-013-19)."""
        row = self._stored(project)
        param = design_params.BenchParam
        values: dict[Any, float] = {}
        for item, typed, label in (
                (param.HEIGHT, self.height, tr("Bench height (m)")),
                (param.FACE, self.face, tr("Face angle (°)")),
                (param.BERM, self.berm, tr("Minimum berm width (m)")),
                (param.ANCHOR, self.anchor, tr("Anchor elevation (m)")),
                (param.MESH_FACTOR, self.mesh, tr("Mesh factor"))):
            number = typed_number(typed, label)
            if number is not None:  # un perfil nuevo sin un valor: el dominio dice cuál falta
                values[item] = number
        if row is None:
            edit = design_profiles.ProfileEdit(name=self.name, values=values)
        else:
            typed = self.name.strip()  # vacío: se queda con el suyo
            renamed = self.name if typed and typed != row.name else None
            if renamed is None and not values:
                raise ProfileFormError(tr("Nothing to change in «{name}»", name=row.name))
            edit = design_profiles.ProfileEdit(name=renamed, code=row.code, values=values)
        if not values:
            return edit, None
        decided_by = self.decided_by.strip()
        if not decided_by:
            raise ProfileFormError(tr("Write who decides the values of the profile"))
        source = self.source.strip()
        version = None
        if self.scope == "VERSION":  # solo la versión activa (RF-009-24, RF-009-29)
            active = scene_versions.active()
            if active is None:
                raise ProfileFormError(tr("Choose the active version first: Project ▸ "
                                          "Versions ▸ Active version"))
            version = active.code
        kind = ParamKind.ADOPTADO if self.kind == "ADOPTADO" else ParamKind.HIPOTESIS
        return edit, design_profiles.ProfileDeclaration(
            source=source or decided_by, decided_by=decided_by,
            reason=self.reason.strip() or tr("Declared in the bench profiles window"),
            source_kind=self.source_kind.lower() if source else "person", kind=kind.value,
            version=version)

    def execute(self, context: Any) -> set[str]:
        """Crea, completa o renombra el perfil con ``design.profiles.edit_bench_profiles`` (una
        sola operación de proyecto y una sola transacción; RF-013-18). Todo se mira antes de
        escribir: un perfil sin nombre, con el nombre de otro, sin un valor o con uno fuera de
        rango se rechaza nombrando el perfil, el campo y el valor, y no deja nada (RF-013-19)."""
        project = SESSION.project
        try:
            edit, declaration = self._request(project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog,
                             version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        try:
            edited = design_profiles.edit_bench_profiles(project, [edit], declaration)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, design_profiles.EDIT_BENCH_PROFILES)
        code = edited.created[0] if edited.created else edit.code
        shown = next(row.name for row in edited.profiles if row.code == code)
        text = (tr("Bench profile «{name}» created with the code «{code}»", name=shown, code=code)
                if edited.created else
                tr("Bench profile «{name}» saved (code «{code}»)", name=shown, code=code))
        try:
            des_panels.fill_profiles(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.warning("No se pudo volver a leer la lista de perfiles de banco", exc_info=True)
        des_panels.choose(code)
        des_panels.show_report([(text, False)])
        self.report({"INFO"}, text)
        return {"FINISHED"}


def _known_values(project: Any, code: str) -> dict[Any, dict[str, str]]:
    """Lo que el perfil ``code`` ya tiene declarado, por valor y ámbito (``PROJECT`` o
    ``VERSION``, el de la versión activa): su texto («10 m [ADO]»). Con ello el diálogo de
    completar no pide lo que ya vale (se cambia con «Cambiar…»)."""
    store = core_params.ParameterStore(project)
    version = scene_versions.active()
    found: dict[Any, dict[str, str]] = {}
    with project.read() as conn:
        for param in design_params.BenchParam:
            key = design_params.bench_key(code, param)
            records = {"PROJECT": store.get(key, conn=conn),
                       "VERSION": None if version is None
                       else store.get(key, version=version.uid, conn=conn)}
            found[param] = {scope: des_panels.record_text(record)
                            for scope, record in records.items()
                            if record is not None and record.value is not None}
    return found


# --- Sectores de diseño… (T23; HU-013-2; RF-013-07 a RF-013-10, RF-013-21, RF-013-33) -----------

EDIT_DESIGN_SECTORS = "geoblender.des_edit_design_sectors"
SET_SECTOR_SLOPE = des_panels.SET_SECTOR_SLOPE


class SectorFormError(ProfileFormError):
    """Lo que impide guardar el talud de un sector con lo escrito en el diálogo (ya en el idioma de
    Geoblender)."""


def _parameters_written(project: Any) -> None:
    """Tras escribir un parámetro: la lista de Parámetros del proyecto, los indicadores (lo que
    dependía de él puede quedar obsoleto) y las ventanas de los perfiles y de los sectores (la
    escucha de los indicadores las pone al día)."""
    try:
        ui_provenance.fill_parameters()
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo volver a leer la lista de parámetros", exc_info=True)
    if ui_provenance.refresh(force=True):
        ui_provenance.redraw()
    des_panels.on_project_read(project)


class GEOBLENDER_OT_des_edit_design_sectors(DesignCommandAware, ProvenanceAwareOperator,
                                            bpy.types.Operator):
    """Sectors with their own bench profile"""

    bl_idname = EDIT_DESIGN_SECTORS
    bl_label = "Design sectors…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[str]:
        """Lee los sectores del proyecto —los de la 012 o el perímetro de actuación— con el estado
        de su búsqueda, el talud que impone cada uno en la versión activa y los huérfanos, y las
        capas de las que se pueden declarar de nuevo, y abre su ventana; desde un guion sin
        ventana, solo la vista (RF-013-07)."""
        project = SESSION.project
        try:
            des_panels.fill_sectors(project)
            des_panels.fill_sector_sources(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        des_panels.show_sector_report(())
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(des_panels.SECTORS_PANEL)


class GEOBLENDER_OT_des_set_sector_slope(DesignCommandAware, ProvenanceAwareOperator,
                                         bpy.types.Operator):
    """Set the maximum general slope that a sector imposes on the design"""

    bl_idname = SET_SECTOR_SLOPE
    bl_label = "Set the sector slope…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    code: StringProperty(  # type: ignore[valid-type]
        name="Sector", description="Code of the sector whose slope is set (empty: the action "
        "perimeter, when it is the only sector)", options=_HIDDEN)
    slope: StringProperty(  # type: ignore[valid-type]
        name="Maximum general slope (°)", description="Maximum general slope that the sector "
        "imposes on the design in degrees, between 0 and 90 (both excluded)", options=_FIELD)
    kind: EnumProperty(  # type: ignore[valid-type]
        name="Type", description="Type of the value: adopted or hypothesis",
        items=PROFILE_KIND_ITEMS, default="ADOPTADO", options=_FIELD)
    source: StringProperty(  # type: ignore[valid-type]
        name="Source", description="Document, standard, person, operation or algorithm the "
        "value comes from (empty: the decider)", options=_FIELD)
    source_kind: EnumProperty(  # type: ignore[valid-type]
        name="Source type", items=SOURCE_KIND_ITEMS, default="PERSON", options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decided the value (the owner, a laboratory, a "
        "person)", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the slope has this value (recorded in its history)",
        options=_FIELD)
    scope: EnumProperty(  # type: ignore[valid-type]
        name="Scope",
        description="Whether the change is for the project or only for the active version (a "
                    "parameter that its module admits by version)",
        items=PARAMETER_SCOPE_ITEMS, default="PROJECT", options=_FIELD)

    def _sector(self, project: Any) -> DesignSector:
        """El sector de :attr:`code` tal como está ahora en el proyecto (en la versión activa);
        :class:`SectorFormError` si ya no está."""
        from ...design import sectors as design_sectors  # al usarlo: habilitar no carga el cálculo

        version = scene_versions.active()
        found = design_sectors.design_sectors(project, None if version is None else version.uid)
        for item in found:
            if item.code == self.code:
                return item
        raise SectorFormError(tr("The sector is no longer in the project: open the list again"))

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo: del sector que se elige, con lo que ya impone en el ámbito (su valor,
        su tipo, su origen y su decisor); propone el decisor (la persona de la sesión) y, con una
        versión activa, el ámbito (RF-009-29: la versión si ya tiene valor propio, y si no, el
        proyecto); no cambia nada hasta que se acepta."""
        self.provenance_dialog = True
        project = SESSION.project
        try:
            sector = self._sector(project)
            choice = scope_choice(sector.key)
            store = core_params.ParameterStore(project)
            with project.read() as conn:
                shared = store.get(sector.key, conn=conn)
                own = None if choice is None else store.get(
                    sector.key, version=choice.version_uid, conn=conn)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        if choice is None or choice.refusal is not None:
            self.scope = "PROJECT"
        elif not self.properties.is_property_set("scope"):
            self.scope = "PROJECT" if own is None else "VERSION"
        record = own if self.scope == "VERSION" and own is not None else shared
        decided = ""
        if record is not None and record.value is not None:
            self.slope = typed_value(record.value, i18n.language())
            if record.kind.name in ("ADOPTADO", "HIPOTESIS"):
                self.kind = record.kind.name
            self.source = record.source
            self.source_kind = record.source_kind.name
            decided = "" if record.decided_by == core_params.DEFAULT_DECIDER else record.decided_by
        else:
            self.slope = ""
        self.decided_by = decided or project.session.user_host
        self._title = tr("Maximum general slope of {sector}",
                         sector=constraint_panels.sector_name(sector.code, sector.name))
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Sector slope"),
            confirm_text=tr("Save"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.label(text=getattr(self, "_title", self.code), translate=False)
        try:
            choice = scope_choice(design_params.sector_slope_key(self.code or PERIMETER_SEGMENT))
        except ValueError:  # un código que no es de sector: nada que preguntar
            choice = None
        if choice is not None:  # «¿Para el proyecto o solo para V01?» (RF-009-29)
            layout.label(text=tr("For the project or only for {version}?", version=choice.code),
                         translate=False)
            row = layout.row(align=True)
            row.use_property_split = False
            row.prop_enum(self, "scope", "PROJECT", text=tr("The project"), translate=False)
            only = row.row(align=True)
            only.enabled = choice.refusal is None  # «Versión no editable» (RF-009-21)
            only.prop_enum(self, "scope", "VERSION",
                           text=tr("Only {version}", version=choice.code), translate=False)
            if choice.refusal is not None:
                refused = layout.row()
                refused.alert = True
                refused.label(text=choice.refusal, icon="ERROR", translate=False)
        layout.prop(self, "slope", text=tr("Maximum general slope (°)"), translate=False)
        layout.prop(self, "kind", text=tr("Type"), translate=False)
        layout.prop(self, "source", text=tr("Source"), translate=False)
        layout.prop(self, "source_kind", text=tr("Source type"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def _request(self, project: Any) -> tuple[DesignSector, float]:
        """Lo escrito, ya comprobado: el sector y el talud en grados. :class:`SectorFormError` si
        el sector ya no está, falta el talud o quién lo decide, o no es un número; el rango (0 a
        90°, ambos excluidos) lo rechaza el dominio (``DesignError``, nombrando el sector, el
        campo y el valor)."""
        sector = self._sector(project)
        degrees = typed_number(self.slope, tr("Maximum general slope (°)"))
        if degrees is None:
            raise SectorFormError(tr("Write the maximum general slope of the sector"))
        design_params.check_sector_slope(sector.code or PERIMETER_SEGMENT, degrees)
        if not self.decided_by.strip():
            raise SectorFormError(tr("Write who decides the slope of the sector"))
        return sector, degrees

    def execute(self, context: Any) -> set[str]:
        """Guarda el talud del sector como su parámetro (``des.sector.{código}.
        max_general_slope_deg``) en el proyecto o solo en la versión activa: lo da de alta la
        primera vez en el ámbito y lo cambia después, con su tipo, su origen, su decisor y su
        motivo (RF-013-08); el de otro sector o de otra versión no cambia. Todo se mira antes de
        escribir: nada queda si se rechaza. Apunta Ctrl+Z (no deshace la BD) y pone al día las
        ventanas (RF-013-07)."""
        project = SESSION.project
        try:
            sector, degrees = self._request(project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        version = None
        if self.scope == "VERSION":  # solo la versión activa (RF-009-24, RF-009-29)
            active = scene_versions.active()
            if active is None:
                self.report({"ERROR"}, tr("Choose the active version first: Project ▸ "
                                          "Versions ▸ Active version"))
                return {"CANCELLED"}
            version = active
        decided_by, source = self.decided_by.strip(), self.source.strip()
        given: dict[str, Any] = {
            "kind": ParamKind.ADOPTADO if self.kind == "ADOPTADO" else ParamKind.HIPOTESIS,
            "source": source or decided_by,
            "source_kind": self.source_kind.lower() if source else "person",
            "decided_by": decided_by,
            "reason": self.reason.strip() or tr("Declared in the design sectors window"),
            "version": None if version is None else version.uid}
        store = core_params.ParameterStore(project)
        try:
            with project.write_transaction() as conn:
                if store.get(sector.key, version=given["version"], conn=conn) is None:
                    saved = store.create(conn, sector.key, degrees, **given)
                else:
                    saved = store.change(conn, sector.key, value=degrees, **given)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.PARAMETER, saved.key)  # Ctrl+Z no lo deshace
        _parameters_written(project)
        des_panels.choose_sector(sector.code)
        message = tr("Slope imposed by {sector} in {scope}: {value}",
                     sector=constraint_panels.sector_name(sector.code, sector.name),
                     scope=version.code if version is not None else tr("the project"),
                     value=des_panels.slope_text(saved))
        des_panels.show_sector_report([(message, False)])
        self.report({"INFO"}, message)
        return {"FINISHED"}


classes: tuple[type, ...] = (GEOBLENDER_OT_des_edit_bench_profiles,
                             GEOBLENDER_OT_des_save_bench_profile,
                             GEOBLENDER_OT_des_edit_design_sectors,
                             GEOBLENDER_OT_des_set_sector_slope)
"""Las órdenes reales del diseño (la T22 pone «Perfiles de banco…» y su orden interna, la T23
«Sectores de diseño…» y la suya; T24, T25 y T28 las irán añadiendo)."""
