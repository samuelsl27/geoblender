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

**Las órdenes** (T22 a T25 y T28) y **los cargadores de la vista** (T27) se añaden en sus tareas:
:data:`classes` irá creciendo con ellas. El cargador de las rejillas ``des_env_``, ``des_srf_`` y
``des_brm_`` (objetos ``DESIGN``) es de ``bl/scene/des_views.py`` (T27), que registra ``bl.scene``
junto al tipo de objeto que necesita.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from ...core import i18n
from ...core import params as core_params
from ...core.project.model import Progress
from ...core.provenance import contract
from ...design import messages as design_messages
from ...design import params as design_params
from ...design import profiles as design_profiles
from ...design import provenance
from ..scene import project_session
from ..scene import versions as scene_versions
from ..ui.commands import with_note
from . import incorporation
from .core_provenance import write_unavailable
from .incorporation import StepQueue

if TYPE_CHECKING:  # solo para los tipos: habilitar no importa el cálculo (RNF-001-03)
    from ...core.project.session import Project
    from ...core.provenance.operations import OperationHandle
    from ...core.provenance.recompute import RecomputeRequest
    from ...core.versions.reproduce import ReproduceRequest
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

classes: tuple[type, ...] = ()
"""Las órdenes reales del diseño (T22 a T25 y T28 las irán añadiendo)."""


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
