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
- **Cubicar entre dos superficies…** (Mayús+Alt+M; T21; RF-011-01 a 06, RF-011-20, RF-011-25,
  RF-011-26; plan §5.3.4, §5.5, A10, A11, D-25, D-30, D-31):
  :class:`GEOBLENDER_OT_res_compute_volume_between_surfaces` propone en su diálogo las dos
  superficies seleccionadas en la vista (de partida, la de mayor cota media,
  :func:`ordered_surfaces`; «Invertir», :func:`invert_surfaces`) entre las de las listas de
  ``bl.ui.res_panels`` (rejillas del proyecto y de la versión activa, congeladas en la revisión
  de la que parte y la cota constante), con su ámbito opcional y la rejilla de diferencias;
  comprueba lo pedido sin escribir nada (A1, la capa del ámbito en el CRS del proyecto, el
  nombre repetido, que pregunta si se sustituye: D-30) y lanza ``res.volume``
  (``reserves.store.volume_run``) en la revisión abierta de la versión activa: desde la
  interfaz, por pasos en su modal (``bl.ops.core._StepsModal``, con el avance en la barra de
  estado y Esc, que no deja nada a medias, RF-011-25); desde un guion, de una vez. Al terminar
  dice sus totales, carga la rejilla de diferencias en la vista (con el cargador de
  ``res_dif_``, ``bl.scene.res_views``) y abre la ventana de la cubicación (T25).
- **Diferencia entre superficies…** (T22; RF-011-05, RF-011-20, RF-011-23; plan §5.3.4, A15,
  D-25, D-29): :class:`GEOBLENDER_OT_res_compute_surface_difference`, el mismo diálogo y los
  mismos pasos que la anterior (lo común, en ``_SurfacesCommand``) sin ámbito y siempre con la
  rejilla: ``res.difference`` la escribe como dato de la versión activa con sus seis cifras y
  la carga en la vista, coloreada (una cubicación y una diferencia no comparten el nombre de su
  rejilla); ``geoblender.res_export_difference`` («Exportar a GeoTIFF…» del menú «Diferencia
  ▾»; no es una operación) la escribe como GeoTIFF entregable desde lo registrado, por pasos,
  también de una versión no editable y, fuera del proyecto, en solo lectura.
"""

from __future__ import annotations

import functools
import logging
import math
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import bpy
import numpy as np
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, StringProperty

from ...core import i18n
from ...core import params as core_params
from ...core.catalog.search import path_text
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, tr
from ...core.params.store import DEFAULT_SOURCE_PREFIX, shown_value
from ...core.project.model import Progress
from ...core.provenance import contract
from ...core.provenance.operations import CANCEL_REASON_PREFIX, failure_reason
from ...core.provenance.undo import UndoKind
from ...core.units import UnitError, convert, parse_quantity
from ...gis import provenance as gis_provenance
from ...gis import store as gis_store
from ...gis.crs import crs_service_status, reference_label
from ...gis.messages import GisError
from ...reserves import materials
from ...reserves import messages as res_messages
from ...reserves import params as res_params
from ...reserves import provenance
from ...reserves import scale as res_scale
from ...reserves.messages import ResError
from ...reserves.surfaces import SurfaceRef, check_pair, propose_order, surface_source
from ...reserves.tonnage import PERCENT_TOLERANCE
from ...reserves.volumes import FINAL, START, VolumeRequest
from ..props import res as res_props
from ..props.core import OBJECT_PROPERTY
from ..scene import project_session, res_views, undo_watch, views
from ..scene import versions as scene_versions
from ..ui import gate, res_panels
from ..ui import provenance as ui_provenance
from ..ui.commands import catalog, text
from . import jobs as jobs_ops
from .core import _StepsModal
from .core_provenance import (
    KIND_ITEMS,
    PARAMETER_SCOPE_ITEMS,
    SESSION,
    SET_PARAMETER_WIDTH,
    SOURCE_KIND_ITEMS,
    ProvenanceAwareOperator,
    error_text,
    read_only_dirs,
    scope_choice,
    typed_value,
    write_unavailable,
)
from .incorporation import StepQueue

if TYPE_CHECKING:
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
    salga de ella (``keep_open``), hasta pulsar fuera o Esc. Una que aún no está registrada (la
    de la cubicación llega con la T25), nada."""
    if getattr(bpy.types, name, None) is None:
        return {"CANCELLED"}
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


# --- Entre dos superficies… (T21; RF-011-01 a 06, RF-011-20, RF-011-25, RF-011-26) -------------

BETWEEN = "geoblender.res_compute_volume_between_surfaces"
PARAMETERS = "geoblender.core_show_parameters"
DIALOG_WIDTH = 440
_SURFACES_OBJ = "Superficies de la cubicación"
_SURFACE_KINDS = ("DTM", "TIN")  # Object.geoblender.kind de un objeto que muestra una superficie


def _short(identifier: str, typed: str) -> str:
    """Una superficie de la lista en el nombre por defecto de una cubicación: el nombre de su
    dato sin su familia («octubre» de ``gis_dtm_octubre``) o la cota tecleada («100,5 m»)."""
    if identifier == res_panels.ELEVATION:
        return f"{typed.strip()} m" if typed.strip() else tr("Constant elevation")
    name = identifier.removeprefix(res_panels.FROZEN)
    for family in gis_provenance.FAMILIES:
        if name.startswith(family.prefix):
            return name.removeprefix(family.prefix)
    return name


def default_name(operator: Any) -> str:
    """El nombre que propone la orden: «<final> − <partida>» (plan §5.5)."""
    return (f"{_short(operator.final, operator.final_elevation)} − "
            f"{_short(operator.start, operator.start_elevation)}")


def invert_surfaces(operator: Any, _context: Any) -> None:
    """«Invertir» (RF-011-06): cambia la superficie de partida por la final (y sus cotas
    tecleadas) y, si el nombre era el propuesto, propone el nuevo; el botón vuelve a su sitio."""
    if not operator.invert:
        return
    proposed = default_name(operator)
    operator.start, operator.final = operator.final, operator.start
    operator.start_elevation, operator.final_elevation = (operator.final_elevation,
                                                          operator.start_elevation)
    if not operator.name.strip() or operator.name == proposed:
        operator.name = default_name(operator)
    operator.invert = False


def _typed_elevation(typed: str, *, field: str, label: str) -> float:
    """La cota constante tecleada (m, float64); ``res.bench_value_not_number`` si no es un
    número de metros."""
    try:
        number, unit = parse_quantity(typed)  # vacía: UnitError
        return float(convert(number, unit or _METRE, _METRE))
    except UnitError:
        raise ResError("res.bench_value_not_number", obj="Cubicación", field=field,
                       value=typed, label=label) from None


def _elevation_shown(value: float) -> str:
    text = str(int(value)) if float(value).is_integer() else repr(float(value))
    return text.replace(".", ",") if i18n.language() == "es" else text


def _surface_ref(identifier: str, typed: str, *, field: str, label: str
                 ) -> tuple[SurfaceRef, Any]:
    """La superficie elegida en la lista (``identifier``; la cota constante, ``typed``) y su
    fila de la lista (``None`` en la cota). ``gis.dataset_unknown`` si ya no está."""
    if identifier == res_panels.ELEVATION:
        value = _typed_elevation(typed, field=field, label=label)
        return SurfaceRef(elevation=value, label=tr("Constant elevation {value} m",
                                                    value=_elevation_shown(value))), None
    choice = res_panels.surface_choice(identifier)
    if choice is None:
        raise GisError("gis.dataset_unknown", obj=_SURFACES_OBJ, field=field, value=identifier)
    return replace(choice.ref, label=choice.name), choice


def _point_scale(project: Any, grid: Any, scope: Any) -> float | None:
    """El factor de escala de la proyección en el centro del ámbito o de la rejilla (A14, D-34:
    se informa, no se aplica); sin el servicio de CRS, ``None`` («no disponible»)."""
    from . import gis as gis_ops

    try:
        status = crs_service_status(gis_ops.crs_resolver)
        if status.service is None or grid is None:
            return None
        x, y = res_scale.center(grid, scope)
        crs, _vertical = gis_store.project_references(project)
        value = float(np.asarray(status.service.scale_factor(
            crs, np.array([[x, y]], dtype=np.float64)), dtype=np.float64).reshape(-1)[0])
    except Exception:  # noqa: BLE001 - sin factor combinado, la cubicación sigue (A14)
        LOGGER.warning("No se pudo calcular el factor de escala de la proyección", exc_info=True)
        return None
    return value if math.isfinite(value) and value > 0.0 else None


def _scope(project: Any, identifier: str) -> tuple[str | None, Any]:
    """La capa del ámbito elegida (su nombre y sus polígonos; ``None`` sin ámbito), en el CRS del
    proyecto (``res.scope_references_mismatch`` si no lo está)."""
    if not identifier or identifier == res_panels.NO_SCOPE:
        return None, None
    from ...reserves import store  # al usarlo: habilitar no lo carga

    polygons = store.load_scope(project, identifier)
    found = gis_store.dataset_references(project, identifier)
    expected = gis_store.project_references(project)
    if found[0] != expected[0]:
        raise ResError("res.scope_references_mismatch", obj=f"Capa «{identifier}»",
                       field="CRS", value=reference_label(*found), layer=identifier,
                       expected=reference_label(*expected))
    return identifier, polygons


@dataclass(eq=False)
class _Plan:
    """Una cubicación lista para empezar: lo pedido, sus superficies leídas (cabeceras), la capa
    del ámbito, la revisión de lo congelado, la cubicación a la que sustituiría (D-30) y el
    código de la versión activa."""

    request: VolumeRequest
    sources: dict[str, Any]
    scope: str | None
    frozen: str | None
    previous: str | None
    version: str


class _Guarded:
    """Los pasos de una cubicación de la orden: si se cierran antes del primero (Esc enseguida,
    desactivar Geoblender), la operación queda «cancelada» (sus pasos no han empezado: nada más
    la cerraría); si no, los cierran ellos (RF-011-25)."""

    def __init__(self, handle: OperationHandle, steps: Iterator[Progress]) -> None:
        self._handle = handle
        self._steps = steps
        self._started = False

    def __iter__(self) -> _Guarded:
        return self

    def __next__(self) -> Progress:
        self._started = True
        return next(self._steps)

    def close(self) -> None:
        if not self._started:
            from ...reserves import store

            self._started = True
            _end(self._handle.cancel, store.CANCELLED_REASON)
        close = getattr(self._steps, "close", None)
        if callable(close):
            close()


def ordered_surfaces(project: Any, first: str, second: str) -> tuple[str, str]:
    """``(partida, final)`` de dos superficies de la lista de la orden (RF-011-06, D-31:
    ``reserves.surfaces.propose_order``, de partida la de mayor cota media en sus celdas
    comunes); si no se pueden leer, en el orden dado (la cubicación dirá por qué)."""
    version_uid = scene_versions.active_version() or ""
    choices = [res_panels.surface_choice(item) for item in (first, second)]
    if any(choice is None for choice in choices):
        return first, second
    try:
        sources = [surface_source(project, choice.ref, version_uid=version_uid)
                   for choice in choices]
        start, _final = propose_order(*sources)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.info("No se pudo proponer el orden de las superficies", exc_info=True)
        return first, second
    return (first, second) if start is sources[0] else (second, first)


def thickness_text(project: Any) -> str:
    """El espesor mínimo con su valor y su tipo, y dónde se cambia (plan §5.5)."""
    record = core_params.ParameterStore(project).get(res_params.MIN_THICKNESS)
    return tr("Minimum thickness: {value} (it is changed in {path})",
              value=res_panels.record_text(record, res_params.MIN_THICKNESS),
              path=path_text(catalog(), PARAMETERS, i18n.language()))


def _grid_free(project: Any, name: str, version_uid: str, op_type: str) -> None:
    """La rejilla de diferencias de la cubicación ``name`` no es de una operación de otro tipo
    (una cubicación y una diferencia con el mismo nombre la compartirían): si lo es,
    ``ValueError`` con el texto para la persona, sin escribir nada."""
    from ...reserves import store  # al usarlo: habilitar no lo carga

    found = store.grid_writer(project, name, version=version_uid)
    if found is None or found == op_type:
        return
    other = provenance.OPERATION_TYPES_BY_NAME.get(found)
    version = scene_versions.active()
    raise ValueError(tr(
        "There is already a difference grid «{name}» in {version}, of «{other}»: give this one "
        "another name", name=name, version="" if version is None else version.code,
        other=found if other is None else i18n.translate(i18n.language(), other.label_msgid)))


def _difference_record(stored: Any) -> Any:
    """La rejilla de diferencias que guardó una cubicación (``res_dif_``), o ``None``."""
    prefix = provenance.FAMILIES_BY_CODE[provenance.DIFFERENCE_GRID].prefix
    return next((record for record in getattr(stored, "records", ())
                 if record.name.startswith(prefix)), None)


def _confirm_later(values: Mapping[str, Any], idname: str = BETWEEN) -> None:
    """Pide confirmar que se sustituye la cubicación del mismo nombre (D-30) o el fichero que ya
    existe (D-29): la misma orden ``idname`` con ``confirm`` (su confirmación) en cuanto acaba
    esta; sin ventana, nada (lo dice el aviso)."""
    manager = getattr(bpy.context, "window_manager", None)
    windows = list(getattr(manager, "windows", ()) or ())
    if not windows:
        return
    group, name = idname.split(".")

    def call() -> None:
        try:
            with bpy.context.temp_override(window=windows[0]):
                getattr(getattr(bpy.ops, group), name)("INVOKE_DEFAULT", confirm=True, **values)
        except (RuntimeError, TypeError, AttributeError, ReferenceError):
            LOGGER.warning("No se pudo pedir confirmación en %s", idname, exc_info=True)

    bpy.app.timers.register(call, first_interval=0.0)


class _SurfacesCommand:
    """Lo común de «Cubicar entre dos superficies…» y «Diferencia entre superficies…» (sin base:
    NOM-01; sus propiedades, las de las dos órdenes, que la ponen delante de
    ``ProvenanceAwareOperator`` y ``_StepsModal``): el diálogo con las dos superficies (o una
    cota constante) e «Invertir», la comprobación de lo pedido sin escribir nada, la operación
    de :attr:`provenance_op_type` por pasos en el modal (con el avance y Esc) o de una vez desde
    un guion, y, al terminar, la rejilla de diferencias en la vista. Cada orden pone en su clase
    su ``execute`` y su ``modal`` (los de aquí): así ``ProvenanceAwareOperator`` los envuelve
    para el diario de Ctrl+Z."""

    OPENS_WINDOW = True
    """Si al terminar abre la ventana de la cubicación (T25)."""

    # Como Nueva revisión… (009): cada evento del temporizador avanza pasos durante, como mucho,
    # este tiempo (cada paso, ≤ 0,05 s: ninguna llamada de más de 0,2 s, RNF-011-04).
    STEP_BUDGET_S = 0.05

    name: StringProperty(  # type: ignore[valid-type]
        name="Name",
        description="Name of the cubication, unique in the active version (empty: «<final> − "
                    "<start>»)",
        options=_FIELD,
    )
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface before the works (the higher one): a grid of the project or of "
                    "the active version, one frozen in the revision it starts from, or a "
                    "constant elevation",
        items=res_panels.surface_items, options=_FIELD,
    )
    final: EnumProperty(  # type: ignore[valid-type]
        name="Final surface",
        description="Surface after the works: a grid of the project or of the active version, "
                    "one frozen in the revision it starts from, or a constant elevation",
        items=res_panels.surface_items, options=_FIELD,
    )
    start_elevation: StringProperty(  # type: ignore[valid-type]
        name="Start elevation", description="Constant elevation of the start surface, m",
        options=_FIELD,
    )
    final_elevation: StringProperty(  # type: ignore[valid-type]
        name="Final elevation", description="Constant elevation of the final surface, m",
        options=_FIELD,
    )
    invert: BoolProperty(  # type: ignore[valid-type]
        name="Invert", description="Swap the start and the final surfaces", default=False,
        options=_FIELD, update=invert_surfaces,
    )
    replace: BoolProperty(  # type: ignore[valid-type]
        name="Replace",
        description="Replace the cubication of the same name of the active version",
        default=False, options=_HIDDEN,
    )
    # La confirmación de sustituir (D-30) y los pasos con el temporizador de la ventana, con el
    # avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        """La puerta de modo de la Vista 3D (su atajo, Mayús+Alt+M) y la de la procedencia: sin
        proyecto, en solo lectura o con la versión activa no editable, dice por qué
        (RF-011-26)."""
        return gate.poll(cls, context) and super().poll(context)

    def provenance_inputs(self, context: Any) -> tuple[Any, ...]:
        return tuple(getattr(self, "_inputs", ()))

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el
        porqué. Si no, las listas de superficies y capas leídas de nuevo, la propuesta de las
        dos superficies seleccionadas en la vista (RF-011-06, D-31: de partida, la de mayor
        cota media), el nombre propuesto y el espesor mínimo, y el diálogo: Intro cubica."""
        self.provenance_dialog = True
        if self.confirm:
            return self._confirm(context, event)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            res_panels.refresh_choices(project, scene_versions.active_version())
            self._propose(context, project)
            self._thickness = thickness_text(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self.in_steps = getattr(context, "window", None) is not None
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=text(catalog().commands[self.bl_idname].label),  # type: ignore[attr-defined]
            confirm_text=tr("Compute"))

    def _propose(self, context: Any, project: Any) -> None:
        """Las superficies del diálogo: las dos seleccionadas en la vista, en el orden de D-31
        (o la única, de partida); sin selección, las dos primeras de la lista (o la cota
        constante de final). Lo que pasó quien la lanza no cambia."""
        items = [identifier for identifier, _name, _about in res_panels.surface_items(None,
                                                                                      None)]
        chosen = []
        by_uid = {res_panels.surface_choice(identifier).uid: identifier
                  for identifier in items if res_panels.surface_choice(identifier) is not None}
        for obj in getattr(context, "selected_objects", None) or ():
            marks = getattr(obj, OBJECT_PROPERTY, None)
            found = None if marks is None or marks.kind not in _SURFACE_KINDS \
                else by_uid.get(str(marks.dataset_uid))
            if found is not None and found not in chosen:
                chosen.append(found)
        given = self.properties.is_property_set
        if not (given("start") or given("final")):
            surfaces = [item for item in items if item != res_panels.ELEVATION]
            if len(chosen) >= 2:
                self.start, self.final = ordered_surfaces(project, chosen[0], chosen[1])
            elif chosen:
                self.start = chosen[0]
                self.final = next((item for item in items if item != chosen[0]),
                                  res_panels.ELEVATION)
            elif surfaces:
                self.start = surfaces[0]
                self.final = surfaces[1] if len(surfaces) > 1 else res_panels.ELEVATION
        if not self.name.strip():
            self.name = default_name(self)

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        if self.start == res_panels.ELEVATION:
            layout.prop(self, "start_elevation", text=tr("Start elevation (m)"), translate=False)
        layout.prop(self, "invert", text=tr("Invert"), toggle=True, icon="ARROW_LEFTRIGHT",
                    translate=False)
        layout.prop(self, "final", text=tr("Final surface"), translate=False)
        if self.final == res_panels.ELEVATION:
            layout.prop(self, "final_elevation", text=tr("Final elevation (m)"), translate=False)
        self._draw_options(layout)
        thickness = getattr(self, "_thickness", "")
        if thickness:
            layout.label(text=thickness, translate=False)

    def _draw_options(self, layout: Any) -> None:
        """Lo que dibuja el diálogo de cada orden tras las superficies (por defecto, nada)."""

    def _scope_layer(self) -> str:
        """La capa del ámbito elegida (por defecto, ninguna)."""
        return res_panels.NO_SCOPE

    def _wants_grid(self) -> bool:
        """Si escribe la rejilla de diferencias (por defecto, sí)."""
        return True

    def _confirm(self, context: Any, event: Any) -> set[str]:
        """La confirmación de sustituir la cubicación del mismo nombre (D-30): si se acepta,
        la orden sigue con ``replace``."""
        self.replace = True
        self.in_steps = getattr(context, "window", None) is not None
        version = scene_versions.active()
        return context.window_manager.invoke_confirm(
            self, event, title=tr("Replace the cubication"),
            message=tr("There is already a cubication «{name}» in {version}: replace it?",
                       name=self.name, version="" if version is None else version.code),
            confirm_text=tr("Replace"), translate=False)

    # --- Cubicar ------------------------------------------------------------------------------

    def _plan(self, project: Any, version_uid: str) -> _Plan:
        """Lo que se cubica, comprobado antes de escribir nada: las dos superficies (A1:
        ``res.surfaces_mismatch``, sin leer celdas), el ámbito, el nombre y la cubicación a la
        que sustituiría (D-30)."""
        from ...reserves import store  # al usarlo: habilitar no lo carga

        start, start_choice = _surface_ref(self.start, self.start_elevation,
                                           field="start", label=tr("Start elevation"))
        final, final_choice = _surface_ref(self.final, self.final_elevation,
                                           field="final", label=tr("Final elevation"))
        name = self.name.strip() or default_name(self)
        gis_provenance.dataset_slug(name)  # un nombre sin letras ni cifras no vale
        scope_name, scope = _scope(project, self._scope_layer())
        sources = {START: surface_source(project, start, version_uid=version_uid),
                   FINAL: surface_source(project, final, version_uid=version_uid)}
        check_pair(sources[START], sources[FINAL])
        grid = sources[START].grid if sources[START].grid is not None else sources[FINAL].grid
        request = VolumeRequest(name, start, final, scope=scope,
                                difference_grid=self._wants_grid(),
                                point_scale=_point_scale(project, grid, scope))
        frozen = next((choice.revision_uid for choice in (start_choice, final_choice)
                       if choice is not None and choice.revision_uid is not None), None)
        if request.difference_grid:
            _grid_free(project, name, version_uid, self.provenance_op_type)
        previous = store.previous_operation(project, self.provenance_op_type, name,
                                            version=version_uid)
        version = scene_versions.active()
        return _Plan(request, sources, scope_name, frozen, previous,
                     "" if version is None else version.code)

    def _values(self, name: str) -> dict[str, Any]:
        """Lo pedido, para volver a lanzarla (la confirmación de D-30)."""
        return {"name": name, "start": self.start, "final": self.final,
                "start_elevation": self.start_elevation,
                "final_elevation": self.final_elevation}

    def _ask_replace(self, plan: _Plan) -> set[str]:
        """La cubicación ya está en la versión activa (D-30): desde la interfaz, pregunta si se
        sustituye; desde un guion, se rechaza (con ``replace``, se sustituye)."""
        name = plan.request.name
        if self.provenance_dialog:
            self._report({"WARNING"}, tr("There is already a cubication «{name}» in {version}",
                                         name=name, version=plan.version))
            _confirm_later(self._values(name), idname=self.bl_idname)  # type: ignore[attr-defined]
        else:
            self._report({"ERROR"}, tr(
                "There is already a cubication «{name}» in {version}: to replace it, repeat the "
                "order with «Replace» (replace=True)", name=name, version=plan.version))
        return {"CANCELLED"}

    def execute(self, context: Any) -> set[str]:
        """Comprueba (sin escribir nada si no vale), empieza ``res.volume`` en la revisión
        abierta de la versión activa y cubica: desde la interfaz, por pasos con el avance y Esc;
        desde un guion, de una vez. Al terminar, la rejilla de diferencias en la vista y la
        ventana de la cubicación."""
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        version_uid = scene_versions.active_version() or ""
        try:
            plan = self._plan(project, version_uid)
            if plan.previous is not None and not self.replace:
                return self._ask_replace(plan)
            request = plan.request
            self._inputs = provenance.volume_inputs(request, scope=plan.scope,
                                                    frozen=plan.frozen)
            settings = provenance.volume_settings(request, scope=plan.scope)
            params = provenance.volume_params(request)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        handle = self.begin(context, settings=settings, params=params,
                            supersedes=plan.previous)
        if handle is None:
            return {"CANCELLED"}
        from ...reserves import store  # al usarlo: habilitar no lo carga

        try:
            steps = _Guarded(handle, store.volume_run(project, handle, request,
                                                      sources=plan.sources,
                                                      budget_s=self.STEP_BUDGET_S))
        except (TypeError, ValueError) as exc:  # inalcanzable: lo pedido es de res.volume
            _end(handle.fail, failure_reason(exc))
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self._project, self._name, self._loading = project, request.name, False
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, steps)
            return {"RUNNING_MODAL"}
        return self._run_all(context, steps)

    def _run_all(self, context: Any, steps: Iterator[Progress]) -> set[str]:
        """Los pasos de una vez (desde un guion)."""
        self.report_log: list[str] = []
        stored = None
        try:
            for step in steps:
                if step.result is not None:
                    stored = step.result
        except GeoblenderError as exc:
            self._report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        except (sqlite3.Error, OSError, ValueError) as exc:
            LOGGER.error("«%s» se ha parado", self._name, exc_info=exc)
            self._report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if stored is None:  # pragma: no cover - volume_run acaba siempre con su resultado
            self._report({"ERROR"}, tr("The operation did not finish with its result"))
            return {"CANCELLED"}
        self._report_result(stored)
        record = _difference_record(stored)
        if record is not None and views.loader_for(record.name) is not None:
            self._loaded(views.load_datasets(context, self._project, [record.uid]))
        return {"FINISHED"}

    def _report_result(self, stored: Any) -> None:
        """Lo que dice la orden al terminar (plan §5.5): «Mensual octubre (V03.r1, en curso):
        desmonte …, terraplén …, neto …» y los avisos de la cubicación."""
        result = stored.result
        version = scene_versions.active()
        self._report({"INFO"}, tr(
            "{name} ({revision}, in progress): cut {cut} m³, fill {fill} m³, net {net} m³",
            name=result.name, revision="" if version is None else version.revision,
            cut=format_number(result.cut_m3, 1), fill=format_number(result.fill_m3, 1),
            net=format_number(result.net_m3, 1)))
        for notice in result.warnings:
            self._report({"WARNING"}, notice.text(i18n.language()))

    def _loaded(self, outcome: Any) -> None:
        """Lo que dice la carga de la rejilla de diferencias en la vista (avisos y errores)."""
        for message in (*outcome.notes, *outcome.errors):
            self._report({"WARNING"}, message)

    def _show_window(self, context: Any) -> None:
        """La ventana de la cubicación, desde la interfaz (``_call_panel``; T25)."""
        if (not self.OPENS_WINDOW or not self.in_steps
                or getattr(context, "window", None) is None):
            return
        try:
            _call_panel(res_panels.VOLUMETRICS_PANEL)
        except RuntimeError:
            LOGGER.warning("No se pudo abrir la ventana de la cubicación", exc_info=True)

    # --- En pasos (_StepsModal) ---------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado (plan §5.5): «Cubicando «Mensual octubre»:
        leyendo… 40 % · Esc: cancelar»; después, la carga de la rejilla en la vista."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        name = getattr(self, "_name", "")
        if getattr(self, "_loading", False):
            return tr("Loading «{name}» into the view… {percent} %", name=name, percent=percent)
        if step.phase == "bands":
            return tr("Computing «{name}»: reading… {percent} % · Esc: cancel", name=name,
                      percent=percent)
        if step.phase == "grid":
            return tr("Computing «{name}»: writing the difference grid… {percent} % · Esc: "
                      "cancel", name=name, percent=percent)
        if step.phase in ("result", "save"):
            return tr("Computing «{name}»: saving… {percent} % · Esc: cancel", name=name,
                      percent=percent)
        return tr("Computing «{name}»: checking… {percent} % · Esc: cancel", name=name,
                  percent=percent)

    def _cancelled_text(self) -> str:
        if getattr(self, "_loading", False):
            return tr("«{name}» has been computed; its difference grid has not been loaded into "
                      "the view", name=getattr(self, "_name", ""))
        return tr("Volumetrics cancelled: nothing has been left half-done")

    def _error_text(self, exc: GeoblenderError) -> str:
        return error_text(exc)

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        if step.result is None:
            if project_session.current() is not getattr(self, "_project", None):
                return self._fail(context, tr(
                    "The project was closed while «{name}» was being computed: nothing has been "
                    "left half-done", name=getattr(self, "_name", "")))
            return None
        if self._loading:
            self._loaded(step.result)
            return self._finish(context)
        self._report_result(step.result)
        record = _difference_record(step.result)
        if record is None or views.loader_for(record.name) is None:
            return self._finish(context)
        finished, self._steps = self._steps, views.load_steps(context, self._project,
                                                              [record.uid])
        self._loading = True
        if finished is not None:
            finished.close()
        return None

    def _finish(self, context: Any) -> set[str]:
        self._done(context)
        self._show_window(context)
        return {"FINISHED"}

    def modal(self, context: Any, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except Exception as exc:  # noqa: BLE001 - los pasos cerrados no dejan nada a medias
            LOGGER.error("«%s» se ha parado", getattr(self, "_name", ""), exc_info=exc)
            return self._fail(context, error_text(exc))


class GEOBLENDER_OT_res_compute_volume_between_surfaces(_SurfacesCommand, ProvenanceAwareOperator,
                                                         _StepsModal, bpy.types.Operator):
    """Volume and tonnage between a base surface and a top surface, with their type and
    provenance"""

    bl_idname = BETWEEN
    bl_label = "Volume between two surfaces…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.VOLUME
    execute = _SurfacesCommand.execute
    modal = _SurfacesCommand.modal

    scope_layer: EnumProperty(  # type: ignore[valid-type]
        name="Scope",
        description="Polygons outside which nothing is measured: a boundary layer or the union "
                    "of a domain layer (none: the whole grid)",
        items=res_panels.scope_items, options=_FIELD,
    )
    difference_grid: BoolProperty(  # type: ignore[valid-type]
        name="Difference grid",
        description="Write the grid of differences (final − start, m) as data of the version "
                    "and load it into the view",
        default=True, options=_FIELD,
    )

    def _draw_options(self, layout: Any) -> None:
        layout.prop(self, "scope_layer", text=tr("Scope (optional)"), translate=False)
        layout.prop(self, "difference_grid", text=tr("Difference grid"), translate=False)

    def _scope_layer(self) -> str:
        return str(self.scope_layer)

    def _wants_grid(self) -> bool:
        return bool(self.difference_grid)

    def _values(self, name: str) -> dict[str, Any]:
        # Sin super(): las pruebas llaman a los métodos con un self simulado.
        return {**_SurfacesCommand._values(self, name), "scope_layer": self.scope_layer,
                "difference_grid": bool(self.difference_grid)}


# --- Diferencia entre superficies… y su rejilla (T22; RF-011-05, RF-011-20, RF-011-23) ---------

DIFFERENCE_COMMAND = "geoblender.res_compute_surface_difference"
EXPORT_DIFFERENCE = "geoblender.res_export_difference"
EXPORT_TICKS = 1000
"""El total de los pasos de la exportación (``Progress.total``): su avance, en milésimas."""
GEOTIFF_SUFFIX = ".tif"


class GEOBLENDER_OT_res_compute_surface_difference(_SurfacesCommand, ProvenanceAwareOperator,
                                                   _StepsModal, bpy.types.Operator):
    """Cut and fill between two surfaces"""

    bl_idname = DIFFERENCE_COMMAND
    bl_label = "Difference between surfaces…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.DIFFERENCE
    OPENS_WINDOW = False  # sin tabla: sus cifras, en «Elemento activo» de su rejilla (RF-011-23)
    execute = _SurfacesCommand.execute
    modal = _SurfacesCommand.modal


def _active_difference(context: Any) -> str:
    """El uid del dato que muestra el objeto activo de la vista si es una rejilla de
    diferencias; si no, vacío."""
    obj = getattr(context, "active_object", None)
    marks = getattr(obj, OBJECT_PROPERTY, None) if obj is not None else None
    if marks is None or marks.kind != res_views.KIND:
        return ""
    return str(marks.dataset_uid)


def _export_progress(steps: Iterator[float], name: str) -> Iterator[Progress]:
    """Los pasos de ``reserves.export.export_difference_steps`` (su avance, 0–1) como
    ``Progress`` (fase ``export``, en milésimas); el último lleva el fichero escrito. Cerrarlos
    cierra los de la exportación, que no dejan nada a medias."""
    try:
        while True:
            try:
                done = next(steps)
            except StopIteration as stop:
                yield Progress("export", EXPORT_TICKS, EXPORT_TICKS, name, result=stop.value)
                return
            yield Progress("export", int(EXPORT_TICKS * min(max(float(done), 0.0), 1.0)),
                           EXPORT_TICKS, name)
    finally:
        close = getattr(steps, "close", None)
        if callable(close):
            close()


class GEOBLENDER_OT_res_export_difference(_StepsModal, bpy.types.Operator):
    """Write the registered difference grid as a deliverable GeoTIFF (it is not an operation:
    also from a superseded version and, outside the project, in read-only)"""

    bl_idname = EXPORT_DIFFERENCE
    bl_label = "Export to GeoTIFF…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    STEP_BUDGET_S = 0.05

    source: StringProperty(  # type: ignore[valid-type]
        name="Difference grid",
        description="Uid or name of the difference grid (empty: the active one in the view)",
        options=_FIELD,
    )
    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"},
    )
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.tif;*.tiff", options={"HIDDEN"},
    )
    check_existing: BoolProperty(  # type: ignore[valid-type]
        default=True, options={"HIDDEN", "SKIP_SAVE"},
    )
    overwrite: BoolProperty(  # type: ignore[valid-type]
        name="Replace", description="Replace the file if it already exists", options=_FIELD,
    )
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Con un proyecto abierto (D-29: no es una operación; en solo lectura, fuera de él)."""
        reason = SESSION.unavailable()
        if reason is not None:
            cls.poll_message_set(reason)
            return False
        return True

    def _stored(self, context: Any) -> Any:
        """La rejilla de diferencias que se exporta (``reserves.store.StoredDifference``): la de
        :attr:`source` o la activa en la vista; ``ValueError`` sin ninguna."""
        from ...reserves import store  # al usarlo: habilitar no lo carga

        source = self.source.strip() or _active_difference(context)
        if not source:
            raise ValueError(tr("Choose the difference grid: select it in the view"))
        return store.stored_difference(SESSION.project, source)

    def invoke(self, context: Any, event: Any) -> set[str]:
        """El diálogo de fichero, con el destino que propone (``exports/<cubicación>_<V01.r1>``
        del proyecto); con ``confirm``, la confirmación de sustituir el que ya existe."""
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            self.overwrite = True
            return context.window_manager.invoke_confirm(
                self, event, title=tr("Replace the file"),
                message=tr("«{file}» already exists: replace it?",
                           file=Path(self.filepath).name),
                confirm_text=tr("Replace"), translate=False)
        try:
            stored = self._stored(context)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self.source = stored.record.uid
        if not self.filepath:
            stem = gis_provenance.dataset_slug(stored.name)
            if stored.revision:
                stem = f"{stem}_{stored.revision}"
            self.filepath = str(Path(SESSION.project.root, gis_provenance.EXPORTS_FOLDER,
                                     f"{stem}{GEOTIFF_SUFFIX}"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        """Escribe el entregable desde lo registrado (``reserves.export``): desde la interfaz,
        por pasos con el avance y Esc; desde un guion, de una vez. Sobre un fichero que ya
        existe, solo con ``overwrite`` (desde la interfaz, lo pregunta)."""
        from ...reserves import export  # al usarlo: habilitar no lo carga

        blocked = SESSION.unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            stored = self._stored(context)
            shown = self.filepath.strip()
            if not shown:
                raise ValueError(tr("Choose the file to export to"))
            target = Path(bpy.path.abspath(shown))
            steps = export.export_difference_steps(
                project, stored.name, target, version=stored.version_uid,
                read_only=read_only_dirs(), overwrite=bool(self.overwrite))
        except GisError as exc:
            interactive = self.in_steps and getattr(context, "window", None) is not None
            if exc.code == "gis.export_target_exists" and interactive:
                self.report({"WARNING"}, error_text(exc))
                _confirm_later({"source": self.source, "filepath": shown},
                               idname=EXPORT_DIFFERENCE)
            else:
                self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self._file = target.name
        progress = _export_progress(steps, target.name)
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, progress)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        try:
            for step in progress:
                if step.result is not None:
                    return self._exported()
        except (GeoblenderError, OSError) as exc:
            self._report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        return {"CANCELLED"}  # pragma: no cover - los pasos acaban siempre con el fichero

    def _exported(self) -> set[str]:
        self._report({"INFO"}, tr("Difference grid exported to «{file}»",
                                  file=getattr(self, "_file", "")))
        return {"FINISHED"}

    # --- En pasos (_StepsModal) ---------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Exporting «{file}»… {percent} % · Esc: cancel",
                  file=getattr(self, "_file", ""), percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Export cancelled: nothing has been written")

    def _error_text(self, exc: GeoblenderError) -> str:
        return error_text(exc)

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        if step.result is None:
            return None
        self._done(context)
        return self._exported()

    def modal(self, context: Any, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except OSError as exc:  # los pasos cerrados no dejan nada a medias
            LOGGER.error("La exportación de «%s» se ha parado", getattr(self, "_file", ""),
                         exc_info=exc)
            return self._fail(context, error_text(exc))


classes: tuple[type, ...] = (
    GEOBLENDER_OT_res_edit_materials,
    GEOBLENDER_OT_res_edit_column,
    GEOBLENDER_OT_res_save_materials,
    GEOBLENDER_OT_res_apply_swell,
    GEOBLENDER_OT_res_set_percentages,
    GEOBLENDER_OT_res_compute_volume_between_surfaces,
    GEOBLENDER_OT_res_compute_surface_difference,
    GEOBLENDER_OT_res_export_difference,
)
"""Las órdenes reales de la cubicación (las demás llegan de la T23 a la T25)."""
