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

**Las órdenes** (D-36): aún ninguna (:data:`classes` vacío). Las seis de Cubicación de R-38 siguen
siendo las provisionales del catálogo hasta que llega la clase real de cada una (T20 a T25), que
la pasa a la entrada «011» de ``core/catalog/data/entries.toml``.
"""

from __future__ import annotations

import functools
import logging
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from ...core import i18n
from ...core import params as core_params
from ...core.errors import GeoblenderError
from ...core.provenance import contract
from ...core.provenance.operations import CANCEL_REASON_PREFIX, failure_reason
from ...reserves import messages as res_messages
from ...reserves import params as res_params
from ...reserves import provenance
from . import jobs as jobs_ops
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


classes: tuple[type, ...] = ()
"""Las órdenes reales de la cubicación: aún ninguna (llegan de la T20 a la T25)."""
