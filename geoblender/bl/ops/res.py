# SPDX-License-Identifier: GPL-3.0-or-later
"""La cubicación en Blender (código ``res``, spec 011; plan 011 §5.1, §5.3.3, A12, D-19, D-36;
ADR-0025 §2, ADR-0027).

**El registro** (T19; RF-011-20, RF-011-26): lo que la cubicación declara a las specs 008 y 009,
constantes del módulo construidas una vez:

- sus **definiciones de parámetros** del proyecto (``reserves.params.DEFINITIONS``: el espesor
  mínimo, el umbral de presencia de lo antrópico y la tolerancia de los momentos) y sus
  **familias** (``reserves.params.FAMILIES``, ADR-0027: la densidad, el K y el porcentaje de cada
  unidad y componente de la columna de materiales) en ``core.params``;
- sus **tipos de operación** (:data:`OPERATION_DEFS`: ``res.volume``, ``res.tonnage``,
  ``res.difference`` y ``res.stages``, de la versión, cada uno con su función de recálculo de
  :data:`RECOMPUTE` y la de reproducción de :data:`REPRODUCE`, y ``res.edit_materials``, del
  proyecto) y sus **cifras** (``reserves.provenance.FIGURES``) en ``core.provenance.contract``;
- sus textos (``reserves.messages``) en ``core.i18n``.

:func:`register` pone lo que falta y apunta cómo quitarlo; :func:`unregister` quita solo eso, en
orden inverso: lo que otro registró antes con la misma clave, o puso después en su lugar, es
suyo y se queda (también una definición o una familia de ``res``). Los dos son simétricos e
idempotentes. Registrar importa ``reserves.provenance`` y lo que arrastra (``reserves.volumes``,
el núcleo; plan §2.1: no en el primer paso de una cubicación); lo que solo hace falta al usarlo
(``reserves.store``, ``reserves.reproduce`` y la reproducción de la 009), al usarlo.

**Recalcular lo obsoleto** (D-19, plan A12; RF-011-20, RF-008-26): las funciones de
:data:`RECOMPUTE` (:func:`recompute_volume`, :func:`recompute_tonnage`,
:func:`recompute_difference` y :func:`recompute_stages`) empiezan con
``reserves.store.recompute_run`` la operación que sustituye a la obsoleta (en la revisión abierta
de su versión, con lo vigente y sus parámetros resueltos de nuevo), dejan sus pasos en la cola de
``res`` (:data:`RUNS`, :func:`queue_steps`) y la devuelven «en curso»: ``recompute_steps`` de la
008 espera («Esperando a «res.volume»…») mientras el temporizador de la cola (:func:`res_tick`,
persistente) da un paso de la primera por llamada, de ``reserves.volumes.STEP_BUDGET_S`` como
mucho, con su avance en la barra de estado («Recalculando «Mensual octubre»… 40 %»). Unos pasos
que fallan dejan su operación «fallida» con el motivo (si sus pasos no lo hicieron ya) y sigue la
siguiente; los avisos del resultado van al registro de Blender (``bl.ops.jobs.report_later``: lo
que dice un temporizador no llega a Info). Desregistrar cierra lo que espera, como Esc: lo
empezado lo cancelan sus pasos sin dejar nada a medias (RF-011-25) y lo que no empezó queda
«cancelado» (no «en curso»). En ``blender -b`` no corren los temporizadores: las pruebas llaman a
:func:`res_tick` a mano.

**Reproducir** (A12; RF-009-11): las funciones de :data:`REPRODUCE` son las de
``reserves.reproduce`` (``res.volume`` y ``res.difference``, la misma), importadas al usarlas
(como ``core.versions.reproduce`` en ``bl.ops.versions``): habilitar no carga la reproducción.

**Las órdenes** (D-36): las de Cubicación de R-38 siguen siendo las provisionales del catálogo
hasta que llega la clase real de cada una (T20 a T25), que la pasa a la entrada «011» de
``core/catalog/data/entries.toml``. Ya están (:data:`classes`):

- **Materiales y densidades…** (T20; RF-011-11, RF-011-15, RF-011-21; plan §5.3.4, §5.5, D-9,
  D-12, D-18): :class:`GEOBLENDER_OT_res_edit_materials` lee la columna del proyecto en la vista
  (``bl.ui.res_panels.fill_materials``) y abre su ventana (``GEOBLENDER_PT_res_materials``);
  ``geoblender.res_edit_column`` añade, quita, sube y baja unidades y componentes de la columna
  en edición (sin escribir nada); ``geoblender.res_save_materials`` la guarda con
  ``res.edit_materials`` (``reserves.store.save_materials``) y registra sin valor, «sin
  confirmar», los parámetros de sus unidades que el proyecto aún no tiene
  (:func:`ensure_parameters`; ninguna densidad ni K por defecto, D-8). La densidad y el K de cada
  unidad se declaran con
  «Cambiar parámetro…» de la 008 (``geoblender.core_set_parameter``, con el ámbito de la 009);
  ``geoblender.res_apply_swell`` («Aplicar a todas») pone el K de una unidad en todas las demás
  en una transacción, y ``geoblender.res_set_percentages`` («Porcentajes…»), los de los
  componentes de una compuesta juntos, que tienen que sumar 100 % (RF-011-15). En solo lectura,
  ninguna está disponible y dicen por qué (RF-011-26).
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
from bpy.props import CollectionProperty, EnumProperty, StringProperty

from ...core import i18n
from ...core import params as core_params
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, tr
from ...core.params.store import DEFAULT_SOURCE_PREFIX, shown_value
from ...core.provenance import contract
from ...core.provenance.operations import CANCEL_REASON_PREFIX, failure_reason
from ...core.provenance.undo import UndoKind
from ...core.units import UnitError, convert, parse_quantity
from ...reserves import materials
from ...reserves import messages as res_messages
from ...reserves import params as res_params
from ...reserves import provenance
from ...reserves.messages import ResError
from ...reserves.surfaces import SurfaceRef
from ...reserves.tonnage import PERCENT_TOLERANCE
from ..props import res as res_props
from ..scene import undo_watch
from ..scene import versions as scene_versions
from ..ui import provenance as ui_provenance
from ..ui import res_panels
from ..ui.commands import catalog, text
from . import jobs as jobs_ops
from .core_provenance import (
    KIND_ITEMS,
    PARAMETER_SCOPE_ITEMS,
    SESSION,
    SET_PARAMETER_WIDTH,
    SOURCE_KIND_ITEMS,
    ProvenanceAwareOperator,
    error_text,
    scope_choice,
    typed_value,
    write_unavailable,
)
from .incorporation import StepQueue

if TYPE_CHECKING:
    from ...core.project.model import Progress
    from ...core.provenance.operations import OperationHandle
    from ...core.provenance.recompute import RecomputeRequest
    from ...core.versions.reproduce import ReproduceRequest

LOGGER = logging.getLogger("geoblender.bl.ops")
MODULE = provenance.MODULE
"""El módulo de las definiciones, las familias, los tipos y las cifras de la cubicación
(``res``)."""

RECOMPUTING = "Recomputing «{name}»… {percent} %"
"""Lo que dice la barra de estado de unos pasos de la cola (``msgid`` con ``name`` y
``percent``)."""
DROPPED_REASON = CANCEL_REASON_PREFIX + "se desactivó Geoblender antes de empezar"
"""El motivo de una operación cuyos pasos esperaban en la cola sin haber empezado al
desactivar Geoblender."""

_UNDO: list[Callable[[], None]] = []


# --- La cola de los pasos del recálculo (D-19) ---------------------------------------------------

RUNS = StepQueue()
"""Los pasos de las operaciones de ``res`` que recalcula «Recalcular lo obsoleto», por orden de
llegada (la cola es suya, aparte de las de la topografía y de los sondeos)."""
res_tick: Callable[[], float | None] = RUNS.timer
"""El temporizador de la cola de ``res``: un paso de la primera por llamada (el mismo objeto
siempre: Blender reconoce un temporizador por su función)."""


def pending_runs() -> list[str]:
    """Las operaciones cuyos pasos esperan en la cola, en orden."""
    return RUNS.pending()


def _shown_name(handle: Any) -> str:
    """El nombre de la cubicación de ``handle`` (sus ajustes) o, sin él, su tipo."""
    name = (getattr(handle, "settings", None) or {}).get("name")
    return name.strip() if isinstance(name, str) and name.strip() else str(handle.op_type)


def _end(stop: Callable[[str], None], reason: str) -> None:
    """Deja la operación terminada con ``stop`` (``fail`` o ``cancel``) y ``reason``; si ya
    terminó (sus pasos lo hicieron) o no se puede escribir, lo deja en el registro técnico."""
    try:
        stop(reason)
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.debug("La operación ya había terminado o no se pudo registrar cómo terminó",
                     exc_info=True)


def _report_warnings(result: object) -> None:
    """Los avisos del resultado de unos pasos (``StoredVolume``, ``StoredTonnage`` o
    ``StoredStages``), al registro de Blender en el idioma de Geoblender."""
    found = getattr(result, "result", None)
    if found is None:
        found = getattr(result, "outputs", None)
    for notice in getattr(found, "warnings", None) or ():
        jobs_ops.report_later("WARNING", notice.text(i18n.language()))


class _Steps:
    """Los pasos de una operación de ``res`` en la cola: cada uno da su avance (0–1). Si fallan,
    la operación queda «fallida» con el motivo y se acaban; al cerrarlos (desregistrar), los
    empezados se cierran (su operación la cancelan ellos) y, si no empezaron, la operación
    queda «cancelada» con :data:`DROPPED_REASON`."""

    def __init__(self, handle: OperationHandle, name: str, steps: Iterator[Progress]) -> None:
        self._handle = handle
        self._name = name
        self._steps = steps
        self._started = False
        self._finished = False

    def __iter__(self) -> _Steps:
        return self

    def __next__(self) -> float:
        if self._finished:
            raise StopIteration
        self._started = True
        try:
            step = next(self._steps)
        except StopIteration:
            self._finished = True
            raise
        except Exception as error:  # noqa: BLE001 - la operación queda fallida, sigue la cola
            self._finished = True
            LOGGER.exception("El recálculo de «%s» (%s) se ha parado", self._name,
                             self._handle.uid)
            _end(self._handle.fail, failure_reason(error))
            raise StopIteration from None
        if step.result is not None:
            _report_warnings(step.result)
        return step.done / step.total if step.total else 0.0

    def close(self) -> None:
        """Cierra los pasos (desregistrar): véase la clase."""
        if not self._started and not self._finished:
            _end(self._handle.cancel, DROPPED_REASON)
        self._finished = True
        close = getattr(self._steps, "close", None)
        if callable(close):
            close()


def queue_steps(handle: OperationHandle, steps: Iterator[Progress]) -> None:
    """Pone en la cola de ``res`` los pasos ``steps`` (``Progress``) de la operación ``handle``,
    «en curso», y registra su temporizador si no lo estaba."""
    name = _shown_name(handle)
    RUNS.add(handle.uid, name, _Steps(handle, name, steps), status=RECOMPUTING)


def _recompute(request: RecomputeRequest) -> OperationHandle:
    """La operación nueva de ``request`` (``reserves.store.recompute_run``), «en curso», con sus
    pasos en la cola de ``res``."""
    from ...reserves import store  # al usarlo: habilitar no lo carga

    handle, steps = store.recompute_run(request)
    queue_steps(handle, steps)
    return handle


def recompute_volume(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``res.volume`` (RF-008-26; D-19): véase el módulo."""
    return _recompute(request)


def recompute_tonnage(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``res.tonnage`` (RF-008-26; D-16, D-19): véase el módulo."""
    return _recompute(request)


def recompute_difference(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``res.difference`` (RF-008-26; D-19): véase el módulo."""
    return _recompute(request)


def recompute_stages(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``res.stages`` (RF-008-26; D-19): véase el módulo."""
    return _recompute(request)


def reproduce_volume(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``res.volume`` y de ``res.difference``: la de ``reserves.reproduce``."""
    from ...reserves import reproduce  # al usarlo: habilitar no carga la reproducción

    return reproduce.reproduce_volume(request)


def reproduce_tonnage(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``res.tonnage``: la de ``reserves.reproduce``."""
    from ...reserves import reproduce  # al usarlo: habilitar no carga la reproducción

    return reproduce.reproduce_tonnage(request)


def reproduce_stages(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``res.stages``: la de ``reserves.reproduce``."""
    from ...reserves import reproduce  # al usarlo: habilitar no carga la reproducción

    return reproduce.reproduce_stages(request)


# --- Declaraciones de la procedencia (ADR-0025 §2; plan §5.2.3) ---------------------------------

RECOMPUTE: Mapping[str, Callable[[RecomputeRequest], OperationHandle]] = MappingProxyType({
    provenance.VOLUME: recompute_volume,
    provenance.TONNAGE: recompute_tonnage,
    provenance.DIFFERENCE: recompute_difference,
    provenance.STAGES: recompute_stages,
})
"""La función de recálculo de cada tipo de ``res`` que se repite solo (RF-008-26)."""
REPRODUCE: Mapping[str, Callable[[ReproduceRequest], Iterator[Progress]]] = MappingProxyType({
    provenance.VOLUME: reproduce_volume,
    provenance.TONNAGE: reproduce_tonnage,
    provenance.DIFFERENCE: reproduce_volume,
    provenance.STAGES: reproduce_stages,
})
"""La función de reproducción de cada tipo de ``res`` que se repite solo (RF-009-11)."""
OPERATION_DEFS: tuple[contract.OperationDef, ...] = provenance.operation_defs(RECOMPUTE,
                                                                              REPRODUCE)
"""Los ``OperationDef`` de los cinco tipos de ``res``, en el orden de
``reserves.provenance.OPERATION_TYPES``."""


# --- Registro --------------------------------------------------------------------------------


def register() -> None:
    """Instala los textos de la cubicación en ``core.i18n`` y registra sus definiciones de
    parámetros, sus familias, sus tipos de operación (:data:`OPERATION_DEFS`) y sus cifras que
    aún no están; idempotente."""
    i18n.install(res_messages.CATALOG_ES)
    missing = tuple(defn for defn in res_params.DEFINITIONS
                    if defn.key not in core_params.DEFINITIONS)
    if missing:
        core_params.register_definitions(missing)
        _UNDO.append(functools.partial(_unregister_definitions, missing))
    families = tuple(family for family in res_params.FAMILIES
                     if family.pattern not in core_params.FAMILIES)
    if families:
        core_params.register_families(families)
        _UNDO.append(functools.partial(_unregister_families, families))
    for definition in OPERATION_DEFS:
        if definition.op_type not in contract.OPERATIONS:
            contract.register_operation(definition)
            _UNDO.append(_unregister_if(contract.OPERATIONS, definition.op_type, definition,
                                        contract.unregister_operation))
    for figure in provenance.FIGURES:
        if figure.key not in contract.FIGURES:
            contract.register_figure(figure)
            _UNDO.append(_unregister_if(contract.FIGURES, figure.key, figure,
                                        contract.unregister_figure))


def unregister() -> None:
    """Cierra los pasos que esperan en la cola (como Esc; véase el módulo) y quita lo que puso
    :func:`register`, en orden inverso (lo que otro cambió después es suyo); las traducciones
    instaladas se quedan; idempotente."""
    RUNS.drop()
    while _UNDO:
        _UNDO.pop()()


def _unregister_if(view: Mapping[str, Any], key: str, item: object,
                   remove: Callable[[str], object]) -> Callable[[], None]:
    def undo() -> None:
        if view.get(key) is item:  # si otro lo cambió, es suyo
            remove(key)

    return undo


def _unregister_definitions(ours: tuple[core_params.ParamDef, ...]) -> None:
    """Quita las definiciones que puso :func:`register` (``ours``) y deja las demás de ``res``:
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


# --- Materiales y densidades… (T20; RF-011-11, RF-011-15, RF-011-21) ---------------------------

TRANSLATION_CONTEXT = "Geoblender"
EDIT_MATERIALS = "geoblender.res_edit_materials"
SAVE_MATERIALS = "geoblender.res_save_materials"
EDIT_COLUMN = "geoblender.res_edit_column"
APPLY_SWELL = "geoblender.res_apply_swell"
SET_PERCENTAGES = "geoblender.res_set_percentages"
_HIDDEN = {"HIDDEN", "SKIP_SAVE"}  # las pone quien la lanza (la fila de la ventana)
_FIELD = {"SKIP_SAVE"}  # las rellena el diálogo: nunca las de la vez anterior
_METRE = "m"

COLUMN_ACTION_ITEMS = [
    ("ADD_UNIT", "Add a unit", "Add a unit at the bottom of the column"),
    ("REMOVE_UNIT", "Remove the unit", "Remove the chosen unit from the column"),
    ("MOVE_UP", "Move the unit up", "Move the chosen unit one place up"),
    ("MOVE_DOWN", "Move the unit down", "Move the chosen unit one place down"),
    ("ADD_COMPONENT", "Add a component", "Add a component to the chosen compound unit"),
    ("REMOVE_COMPONENT", "Remove the component", "Remove the chosen component of its unit"),
]
"""Lo que cambia ``geoblender.res_edit_column`` en la columna en edición."""


def _call_panel(name: str) -> set[str]:
    """Abre la ventana emergente ``name`` con ``wm.call_panel``; sigue abierta aunque el ratón
    salga de ella (``keep_open``), hasta pulsar fuera o Esc."""
    return bpy.ops.wm.call_panel(name=name, keep_open=True)


def _write_poll(cls: type) -> bool:
    """El ``poll`` de lo que escribe en el proyecto: dice por qué no se puede."""
    reason = write_unavailable()
    if reason is not None:
        cls.poll_message_set(reason)  # type: ignore[attr-defined]
        return False
    return True


def _view() -> Any:
    found = res_panels.view()
    if found is None:  # inalcanzable con la extensión registrada
        raise RuntimeError("la vista de la cubicación no está registrada")
    return found


def _saved_column(project: Any) -> materials.MaterialColumn | None:
    """La columna guardada en el proyecto (``res_materials``), o ``None``."""
    with project.read() as conn:
        return materials.read_column(conn)


def column_parameters(column: materials.MaterialColumn | None) -> tuple[str, ...]:
    """Los parámetros que lee una cubicación con ``column`` (RF-011-21): el umbral de presencia
    de lo antrópico y la densidad, el K y el porcentaje de cada unidad y componente."""
    found = (res_params.ANTHROPIC_PRESENCE,)
    return found if column is None else found + provenance.tonnage_params(column)


def ensure_parameters(project: Any, column: materials.MaterialColumn | None) -> tuple[str, ...]:
    """Registra en ``project`` los parámetros de :func:`column_parameters` que aún no tiene con
    su valor por defecto «sin confirmar» (RF-008-04; la densidad, el K y los porcentajes, **sin
    valor**: D-8), en una transacción, para que se puedan declarar con «Cambiar parámetro…»;
    devuelve las claves que registró (ninguna si ya estaban). No los anota ninguna operación:
    los lee cada cubicación (como la regla bajo el límite de detección de la 005)."""
    store = core_params.ParameterStore(project)
    keys = column_parameters(column)
    with project.read() as conn:
        missing = tuple(key for key in keys if store.get(key, conn=conn) is None)
    if missing:
        with project.write_transaction() as conn:
            for key in missing:
                store.ensure_default(conn, key,
                                     geoblender_version=project.session.geoblender_version)
    return missing


def _elevation(item: Any) -> SurfaceRef | None:
    """La cota constante tecleada de la base de ``item`` (m, float64; ``None`` sin nada).
    ``ResError`` (``res.bench_value_not_number``) si no es un número de metros."""
    typed = item.base_elevation.strip()
    if not typed:
        return None
    try:
        number, unit = parse_quantity(typed)
        return SurfaceRef(elevation=float(convert(number, unit or _METRE, _METRE)))
    except UnitError:
        name = item.name.strip()
        raise ResError("res.bench_value_not_number", obj=f"Unidad «{name}»",
                       field="base_elevation", value=typed,
                       label=tr("Base elevation of «{unit}»", unit=name)) from None


def _base(item: Any) -> SurfaceRef | None:
    """La base de la unidad en edición ``item``: una rejilla del proyecto (por su nombre de
    dato) o una cota constante (D-24); sin nada, ``None``."""
    if item.base_kind == res_props.BASE_ELEVATION:
        return _elevation(item)
    dataset = item.base_dataset.strip()
    return SurfaceRef(dataset=dataset) if dataset else None


def _role(identifier: str) -> materials.Role | None:
    return None if identifier == res_props.ROLE_NONE else materials.Role(identifier.lower())


def edited_column(view: Any) -> materials.MaterialColumn:
    """La columna en edición de la vista ``view`` (``WindowManager.geoblender_res_panels``)
    como ``reserves.materials.MaterialColumn``, sin validarla: cada unidad o componente nuevo
    recibe su código de su nombre (``reserves.materials.unit_code``, D-18; los de las que ya
    estaban guardadas no cambian), la última unidad va sin base y solo una antrópica lleva su
    rejilla de espesores. ``ResError`` si una cota constante no es un número de metros."""
    taken = {item.code for item in view.units if item.code}
    last = len(view.units) - 1
    units = []
    for position, item in enumerate(view.units):
        code = item.code or materials.unit_code(item.name, taken)
        taken.add(code)
        kind = materials.Kind(item.kind.lower())
        components = []
        if kind is materials.Kind.COMPOUND:
            inside = {row.code for row in item.components if row.code}
            for row in item.components:
                component_code = row.code or materials.unit_code(row.name, inside)
                inside.add(component_code)
                components.append(materials.Component(component_code, row.name.strip(),
                                                      _role(row.role)))
        thickness = item.thickness_dataset.strip()
        units.append(materials.Unit(
            code, item.name.strip(), kind,
            None if kind is materials.Kind.COMPOUND else _role(item.role),
            materials.State(item.state.lower()),
            None if position == last else _base(item),
            SurfaceRef(dataset=thickness)
            if kind is materials.Kind.ANTHROPIC and thickness else None,
            tuple(components),
        ))
    return materials.MaterialColumn(tuple(units))


def _parameters_written(project: Any) -> None:
    """Tras escribir parámetros: la lista de Parámetros del proyecto, los indicadores (lo que
    dependía de ellos puede quedar obsoleto) y los valores de la ventana de los materiales."""
    try:
        ui_provenance.fill_parameters()
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo volver a leer la lista de parámetros", exc_info=True)
    if ui_provenance.refresh(force=True):
        ui_provenance.redraw()
    res_panels.on_project_read(project)


def _shown_scope(version: Any) -> str:
    return tr("the project") if version is None else version.code


class GEOBLENDER_OT_res_edit_materials(ProvenanceAwareOperator, bpy.types.Operator):
    """In-situ and loose density, swell factor K and role of each material"""

    bl_idname = "geoblender.res_edit_materials"
    bl_label = "Materials and densities…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.EDIT_MATERIALS

    def execute(self, context: Any) -> set[str]:
        """Lee la columna del proyecto en la vista (con sus parámetros registrados: los que
        falten, sin valor y «sin confirmar») y abre su ventana; desde un guion sin ventana,
        solo la vista."""
        project = SESSION.project
        try:
            ensure_parameters(project, _saved_column(project))
            res_panels.fill_materials(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(res_panels.MATERIALS_PANEL)


class GEOBLENDER_OT_res_edit_column(bpy.types.Operator):
    """Add, remove or move a unit or a component of the materials column being edited (nothing
    is written until it is saved)"""

    bl_idname = "geoblender.res_edit_column"
    bl_label = "Edit the materials column"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    action: EnumProperty(  # type: ignore[valid-type]
        name="Action", items=COLUMN_ACTION_ITEMS, default="ADD_UNIT", options=_HIDDEN,
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _write_poll(cls)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        found = {identifier: about for identifier, _name, about in COLUMN_ACTION_ITEMS}
        return i18n.translate(i18n.language(), found.get(properties.action, ""))

    def execute(self, context: Any) -> set[str]:
        view = _view()
        count = len(view.units)
        index = min(max(view.unit_index, 0), count - 1) if count else -1
        action = self.action
        if action == "ADD_UNIT":
            view.units.add().name = tr("New unit")
            view.unit_index = len(view.units) - 1
            return {"FINISHED"}
        if index < 0:
            self.report({"WARNING"}, tr("The column has no unit yet: add one first"))
            return {"CANCELLED"}
        if action == "REMOVE_UNIT":
            view.units.remove(index)
            view.unit_index = max(0, min(index, len(view.units) - 1))
        elif action in ("MOVE_UP", "MOVE_DOWN"):
            target = index - 1 if action == "MOVE_UP" else index + 1
            if 0 <= target < count:
                view.units.move(index, target)
                view.unit_index = target
        else:
            return self._component(view.units[index], action)
        return {"FINISHED"}

    def _component(self, unit: Any, action: str) -> set[str]:
        if unit.kind != res_panels.COMPOUND:
            self.report({"WARNING"}, tr("Only a compound unit has components: choose "
                                        "«Compound» first"))
            return {"CANCELLED"}
        if action == "ADD_COMPONENT":
            unit.components.add().name = tr("New component")
            unit.component_index = len(unit.components) - 1
            return {"FINISHED"}
        if not len(unit.components):
            return {"CANCELLED"}
        index = min(max(unit.component_index, 0), len(unit.components) - 1)
        unit.components.remove(index)
        unit.component_index = max(0, min(index, len(unit.components) - 1))
        return {"FINISHED"}


class GEOBLENDER_OT_res_save_materials(ProvenanceAwareOperator, bpy.types.Operator):
    """Save the materials column being edited as the column of the project, with its record"""

    bl_idname = "geoblender.res_save_materials"
    bl_label = "Save the column"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = provenance.EDIT_MATERIALS

    def execute(self, context: Any) -> set[str]:
        """Guarda la columna en edición con ``res.edit_materials`` (si no vale, la lista de lo
        que falla, sin escribir nada) y registra, sin valor, los parámetros nuevos."""
        project = SESSION.project
        try:
            column = edited_column(_view())
            column.validate()
        except GeoblenderError as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        handle = self.begin(context)
        if handle is None:
            return {"CANCELLED"}
        from ...reserves import store  # al usarlo: habilitar no lo carga

        try:
            store.save_materials(project, handle, column)
            ensure_parameters(project, column)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        res_panels.mark_saved(project, column)
        self.report({"INFO"}, tr("Materials column saved: {count} units",
                                 count=len(column.units)))
        return {"FINISHED"}


def _scope_records(store: core_params.ParameterStore, conn: sqlite3.Connection, key: str,
                   version: Any) -> tuple[Any, Any]:
    """El valor de ``key`` del proyecto y el propio de ``version`` (``None`` sin versión)."""
    own = None if version is None else store.get(key, version=version.uid, conn=conn)
    return store.get(key, conn=conn), own


def _proposed_scope(operator: Any, choice: Any, has_own: bool) -> None:
    """El ámbito que propone el diálogo (RF-009-29): la versión activa si ya tiene valor propio
    y, si no, el proyecto; con la activa no editable, el proyecto."""
    if choice is None or choice.refusal is not None:
        operator.scope = "PROJECT"
    elif not operator.properties.is_property_set("scope"):
        operator.scope = "VERSION" if has_own else "PROJECT"


def _draw_scope(layout: Any, operator: Any, key: str) -> None:
    """«¿Para el proyecto o solo para V01?» de un parámetro de versión, como Cambiar
    parámetro… de la 008 (``bl.ops.core_provenance``)."""
    choice = scope_choice(key)
    if choice is None:
        return
    layout.label(text=tr("For the project or only for {version}?", version=choice.code),
                 translate=False)
    row = layout.row(align=True)
    row.use_property_split = False
    row.prop_enum(operator, "scope", "PROJECT", text=tr("The project"), translate=False)
    only = row.row(align=True)
    only.enabled = choice.refusal is None
    only.prop_enum(operator, "scope", "VERSION",
                   text=tr("Only {version}", version=choice.code), translate=False)
    if choice.refusal is not None:
        refused = layout.row()
        refused.alert = True
        refused.label(text=choice.refusal, icon="ERROR", translate=False)


def _chosen_version(operator: Any) -> tuple[Any, str | None]:
    """La versión del cambio (la activa si el ámbito es la versión; si no, ``None``) o el
    texto de por qué no se puede."""
    if operator.scope != "VERSION":
        return None, None
    version = scene_versions.active()
    if version is None:
        return None, tr("Choose the active version first: Project ▸ Versions ▸ Active version")
    return version, None


class GEOBLENDER_OT_res_apply_swell(bpy.types.Operator):
    """Give the swell factor K of this unit to every unit and component of the column, in one
    transaction"""

    bl_idname = "geoblender.res_apply_swell"
    bl_label = "Apply to all"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    unit: StringProperty(name="Unit", options=_HIDDEN)  # type: ignore[valid-type]
    component: StringProperty(name="Component", options=_HIDDEN)  # type: ignore[valid-type]
    scope: EnumProperty(  # type: ignore[valid-type]
        name="Scope",
        description="Whether the change is for the project or only for the active version (a "
                    "parameter that its module admits by version)",
        items=PARAMETER_SCOPE_ITEMS, default="PROJECT", options=_FIELD,
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the parameter changes (recorded in its history)",
        options=_FIELD,
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _write_poll(cls)

    def _key(self) -> str:
        return res_params.swell_key(self.unit, self.component or None)

    def _source(self, project: Any, version: Any) -> Any:
        """El K de esta unidad en el ámbito del cambio (en la versión, el suyo o, sin él, el
        del proyecto) o ``None`` si no tiene valor."""
        store = core_params.ParameterStore(project)
        with project.read() as conn:
            record, own = _scope_records(store, conn, self._key(), version)
        found = own or record
        return found if found is not None and found.value is not None else None

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Propone el ámbito (el de la versión activa si la unidad tiene allí su K) y abre el
        diálogo con el K que se aplicará; sin K, lo dice y no abre nada."""
        project = SESSION.project
        key = self._key()
        choice = scope_choice(key)
        try:
            store = core_params.ParameterStore(project)
            with project.read() as conn:
                _record, own = _scope_records(
                    store, conn, key, None if choice is None else scene_versions.active())
            _proposed_scope(self, choice, own is not None and own.value is not None)
            version, refusal = _chosen_version(self)
            source = None if refusal else self._source(project, version)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if source is None:
            self.report({"ERROR"}, tr("Declare the swell factor K of this unit first (K…)"))
            return {"CANCELLED"}
        self._shown = shown_value(source.value, source.unit, i18n.language())
        return context.window_manager.invoke_props_dialog(
            self, width=SET_PARAMETER_WIDTH, translate=False,
            title=text(catalog().commands[APPLY_SWELL].label))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.label(text=tr("Swell factor K to apply to every unit: {value}",
                             value=getattr(self, "_shown", "")), translate=False)
        _draw_scope(layout, self, self._key())
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = SESSION.project
        version, refusal = _chosen_version(self)
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        key = self._key()
        store = core_params.ParameterStore(project)
        try:
            source = self._source(project, version)
            if source is None:
                self.report({"ERROR"}, tr("Declare the swell factor K of this unit first (K…)"))
                return {"CANCELLED"}
            targets = [found for found in column_parameters(_saved_column(project))
                       if found.endswith(".swell") and found != key]
            changed = []
            with project.write_transaction() as conn:  # todas o ninguna (D-9)
                for target in targets:
                    if store.get(target, conn=conn) is None:
                        store.ensure_default(
                            conn, target, geoblender_version=project.session.geoblender_version)
                    try:
                        store.change(conn, target, value=source.value, kind=source.kind,
                                     source=source.source, source_kind=source.source_kind,
                                     decided_by=source.decided_by,
                                     decided_at=source.decided_at, reason=self.reason,
                                     version=None if version is None else version.uid)
                    except core_params.ParamError as exc:
                        if exc.code != "core.param_unchanged":
                            raise
                        continue
                    changed.append(target)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        for target in changed:
            undo_watch.record(UndoKind.PARAMETER, target)  # Ctrl+Z no lo deshace
        _parameters_written(project)
        shown = shown_value(source.value, source.unit, i18n.language())
        self.report({"INFO"}, tr("Swell factor K = {value} {kind} in {count} units ({scope})",
                                 value=shown, kind=ui_provenance.badge(source.kind),
                                 count=len(changed), scope=_shown_scope(version)))
        return {"FINISHED"}


class GEOBLENDER_OT_res_set_percentages(bpy.types.Operator):
    """Percentages of the components of a compound unit, declared together: they must add up
    to 100 %"""

    bl_idname = "geoblender.res_set_percentages"
    bl_label = "Percentages…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    unit: StringProperty(name="Unit", options=_HIDDEN)  # type: ignore[valid-type]
    values: CollectionProperty(  # type: ignore[valid-type]
        type=res_props.GEOBLENDER_PG_res_percent, options=_FIELD,
    )
    kind: EnumProperty(  # type: ignore[valid-type]
        name="Type",
        description="Type of the value: measured, calculated (only by adopting a figure), "
                    "adopted or hypothesis",
        items=KIND_ITEMS, default="HIPOTESIS", options=_FIELD,
    )
    source: StringProperty(  # type: ignore[valid-type]
        name="Source",
        description="Document, standard, person, operation or algorithm the value comes from",
        options=_FIELD,
    )
    source_kind: EnumProperty(  # type: ignore[valid-type]
        name="Source type", items=SOURCE_KIND_ITEMS, default="DOCUMENT", options=_FIELD,
    )
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by",
        description="Who decided the value (the owner, a laboratory, a person)",
        options=_FIELD,
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the parameter changes (recorded in its history)",
        options=_FIELD,
    )
    scope: EnumProperty(  # type: ignore[valid-type]
        name="Scope",
        description="Whether the change is for the project or only for the active version (a "
                    "parameter that its module admits by version)",
        items=PARAMETER_SCOPE_ITEMS, default="PROJECT", options=_FIELD,
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _write_poll(cls)

    def _compound(self, project: Any) -> materials.Unit | None:
        """La unidad compuesta guardada de código :attr:`unit`; si no lo es, lo dice."""
        column = _saved_column(project)
        found = None
        if column is not None and self.unit in column.codes:
            found = column.unit(self.unit)
        if found is None or found.kind is not materials.Kind.COMPOUND or not found.components:
            self.report({"ERROR"}, tr("«{unit}» is not a compound unit of the saved column",
                                      unit=self.unit))
            return None
        return found

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Rellena el diálogo con el porcentaje de cada componente en el ámbito que propone
        (el de la versión activa si ya tiene valores propios) y su tipo, origen y decisor."""
        project = SESSION.project
        language = i18n.language()
        try:
            unit = self._compound(project)
            if unit is None:
                return {"CANCELLED"}
            keys = [res_params.percent_key(unit.code, item.code) for item in unit.components]
            choice = scope_choice(keys[0])
            version = None if choice is None else scene_versions.active()
            store = core_params.ParameterStore(project)
            with project.read() as conn:
                found = [_scope_records(store, conn, key, version) for key in keys]
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        _proposed_scope(self, choice, any(own is not None for _record, own in found))
        chosen = [own if self.scope == "VERSION" and own is not None else record
                  for record, own in found]
        self.values.clear()
        for component, record in zip(unit.components, chosen, strict=True):
            row = self.values.add()
            row.code, row.name = component.code, component.name.strip() or component.code
            row.value = "" if record is None else typed_value(record.value, language)
        first = next((record for record in chosen if record is not None), None)
        if first is not None:
            self.kind = first.kind.name
            default = first.source.startswith(DEFAULT_SOURCE_PREFIX)
            self.source = "" if default else first.source
            self.source_kind = first.source_kind.name
            self.decided_by = project.session.user_host \
                if first.decided_by == core_params.DEFAULT_DECIDER else first.decided_by
        self._shown = unit.shown
        return context.window_manager.invoke_props_dialog(
            self, width=SET_PARAMETER_WIDTH, translate=False,
            title=tr("Percentages of «{unit}»", unit=unit.shown))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.label(text=tr("Percentages of «{unit}»", unit=getattr(self, "_shown", self.unit)),
                     translate=False)
        if len(self.values):
            _draw_scope(layout, self, res_params.percent_key(self.unit, self.values[0].code))
        for row in self.values:
            layout.prop(row, "value", text=row.name, translate=False)
        layout.prop(self, "kind", text=tr("Type"), translate=False)
        layout.prop(self, "source", text=tr("Source"), translate=False)
        layout.prop(self, "source_kind", text=tr("Source type"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def _typed(self, unit: materials.Unit) -> tuple[list[tuple[str, float | None]], float]:
        """Lo tecleado de cada componente de ``unit`` (en %; ``None`` lo que falta) y la suma
        de lo tecleado. ``ParamError`` si un valor no vale (su rango, su unidad)."""
        typed = {row.code: row.value for row in self.values}
        decimal = "," if i18n.language() == "es" else "."
        found: list[tuple[str, float | None]] = []
        for component in unit.components:
            key = res_params.percent_key(unit.code, component.code)
            value = typed.get(component.code, "").strip()
            definition = core_params.definition(key)
            found.append((key, None if not value or definition is None
                          else core_params.parse_value(definition, value, None,
                                                       decimal=decimal)))
        return found, math.fsum(value for _key, value in found if value is not None)

    def execute(self, context: Any) -> set[str]:
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = SESSION.project
        version, refusal = _chosen_version(self)
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        store = core_params.ParameterStore(project)
        try:
            unit = self._compound(project)
            if unit is None:
                return {"CANCELLED"}
            found, total = self._typed(unit)
            if any(value is None for _key, value in found) or \
                    not abs(total - 100.0) < PERCENT_TOLERANCE:  # RF-011-15
                self.report({"ERROR"}, tr(
                    "The percentages of the components of «{unit}» add up to {value} %, not "
                    "100 % (to two decimals): none has changed", unit=unit.shown,
                    value=format_number(total, 2)))
                return {"CANCELLED"}
            changed = []
            with project.write_transaction() as conn:  # todos o ninguno
                for key, value in found:
                    if store.get(key, conn=conn) is None:
                        store.ensure_default(
                            conn, key, geoblender_version=project.session.geoblender_version)
                    try:
                        store.change(conn, key, value=value,
                                     kind=core_params.ParamKind[self.kind], source=self.source,
                                     source_kind=core_params.SourceKind[self.source_kind],
                                     decided_by=self.decided_by, reason=self.reason,
                                     version=None if version is None else version.uid)
                    except core_params.ParamError as exc:
                        if exc.code != "core.param_unchanged":
                            raise
                        continue
                    changed.append(key)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        for key in changed:
            undo_watch.record(UndoKind.PARAMETER, key)  # Ctrl+Z no lo deshace
        _parameters_written(project)
        language = i18n.language()
        values = "; ".join(shown_value(value, "%", language) for _key, value in found)
        self.report({"INFO"}, tr("Percentages of «{unit}»: {values} {kind} ({scope})",
                                 unit=unit.shown, values=values,
                                 kind=ui_provenance.badge(core_params.ParamKind[self.kind]),
                                 scope=_shown_scope(version)))
        return {"FINISHED"}


classes: tuple[type, ...] = (
    GEOBLENDER_OT_res_edit_materials,
    GEOBLENDER_OT_res_edit_column,
    GEOBLENDER_OT_res_save_materials,
    GEOBLENDER_OT_res_apply_swell,
    GEOBLENDER_OT_res_set_percentages,
)
"""Las órdenes reales de la cubicación (las demás llegan de la T21 a la T25)."""
