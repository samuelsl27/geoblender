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

**Envolventes y escalonado…** (T24; HU-013-1, HU-013-3, HU-013-5, HU-013-6; RF-013-05, RF-013-16,
RF-013-17, RF-013-21, RF-013-31; D-14, D-27, D-30):
:class:`GEOBLENDER_OT_des_compute_envelope` es **una sola orden** con la envolvente y su escalonado
opcional, con el diálogo de la spec (semillas, dirección, métrica, pendiente, alcance, acotar a,
escalonar con su sentido, su superficie de partida, su perfil base, el de cada sector y su ancla, y
el nombre). **Calcular** (el aceptar del diálogo) corre ``design.steps.envelope_run`` en su modal por
pasos (``_StepsModal``: avance «Calculando la envolvente… 40 % · Esc: cancelar» y cancelación con
Esc) y deja el cálculo hecho y **sin registrar** (:func:`hold_calculation`), con su resumen y sus
avisos en la vista (``bl.ui.des_panels.show_summary``); al terminar pide confirmar
(:func:`_ask_confirmation`: la misma orden con ``confirm=True``, que abre el diálogo de **Crear**,
«Crear con N avisos» si los hay). **Crear** llama a ``Calculation.create()`` (una transacción) y
**Cancelar**, cerrar la ventana (``cancel``), un cálculo nuevo, cambiar de proyecto y desactivar
Geoblender descartan el cálculo y borran los temporales. Con «Escalonar», tras crear la envolvente
(``design.steps.design_run`` la lee de la versión) sigue el escalonado en el mismo modal, con su
propio resumen y su propia confirmación; si se rechaza, la envolvente ya está creada y lo dice. El
rechazo de un sector con la búsqueda pendiente es el de ``design`` (``des.sector_pending``,
nombrando el sector y la orden de la 012). Desde un guion (``bpy.ops`` sin ``in_steps``), de una
vez; el perfil de cada sector y los sectores a los que se acota se marcan en
``WindowManager.geoblender_design`` (``sectors[].profile_pick`` y ``.use``). Ninguna cuenta ni regla
es de aquí: el cálculo, los rangos y los avisos son los de ``design``.

**Vista previa de semillas, dominios y restricciones** (T25; HU-013-1; RF-013-01, RF-013-02,
RF-013-03, RF-013-33): :class:`GEOBLENDER_OT_des_toggle_preview` activa o quita la vista previa de la
Vista 3D (``bl.draw.design``) con lo que pide su diálogo —las semillas (de una superficie en una zona,
una cota fija en una zona o una rejilla de cotas) y el acotado del dominio—, sin crear objetos ni
escribir en el proyecto; con ella activa, el control la quita aunque el proyecto esté ya en solo
lectura. Las semillas y el acotado se piden con las mismas funciones que el diálogo de las envolventes
(:func:`seed_source`, :func:`work_domain`). Nada se cuenta ni se resume aquí: lo hace ``design.preview``.

**Exportar una rejilla del diseño** (T28; HU-013-6; RF-013-34; D-29 de la 011):
:class:`GEOBLENDER_OT_des_export_design_grid` (interna; el botón «Exportar rejilla a GeoTIFF…» está
en la barra N «Diseño», con el objeto de la rejilla activo) escribe la envolvente, la superficie de
diseño o la rejilla de cotas de berma registradas como GeoTIFF entregable con
``design.export.export_grid_steps``, por pasos con el avance y Esc (desde un guion, de una vez). No
es una operación: no escribe nada en el proyecto y vale en solo lectura (fuera de él) y desde una
versión que ya no es editable; sobre un fichero que ya existe pregunta antes de sustituirlo
(:func:`_confirm_later`). Qué rejilla es, de qué versión y qué nombre lleva su operación lo dice
``design.export.stored_grid``. **Recalcular lo obsoleto** ya estaba integrado (T21, véase arriba): la
T28 lo prueba de punta a punta sobre un proyecto real.

**Los cargadores de la vista** (T27): el de las rejillas ``des_env_``, ``des_srf_`` y ``des_brm_``
(objetos ``DESIGN``) es de ``bl/scene/des_views.py``, que registra ``bl.scene`` junto al tipo de
objeto que necesita.
"""

from __future__ import annotations

import functools
import logging
import math
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

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
from ...design import model as design_model
from ...design import provenance
from ...design.model import PERIMETER_SEGMENT
from ...gis import provenance as gis_provenance
from ...gis.messages import GisError
from ..props.des import PREVIEW_PROPERTY
from ..scene import project_session, undo_watch
from ..scene import versions as scene_versions
from ..ui import constraint_panels, des_panels
from ..ui import provenance as ui_provenance
from ..ui.commands import catalog, command_idname, with_note
from ..ui.commands import text as command_text
from . import incorporation, surface_proposal
from .core import _StepsModal
from .core_provenance import (
    KIND_ITEMS,
    PARAMETER_SCOPE_ITEMS,
    SESSION,
    SOURCE_KIND_ITEMS,
    ProvenanceAwareOperator,
    ensure_ready,
    error_text,
    read_only_dirs,
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


@dataclass(frozen=True)
class _Next:
    """Lo que sigue a la envolvente en la misma orden (D-30): su escalonado, ya pedido, que se
    calcula en cuanto la persona crea la envolvente (lee la envolvente de la versión)."""

    request: design_model.DesignRequest
    surface: str
    version: str


_NEXT: list[_Next] = []  # a lo más uno: el escalonado que espera a que se cree la envolvente


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
    proyecto, desactivar Geoblender): borra sus temporales y no deja nada, y con él el escalonado
    que esperaba a la envolvente. Sin él, nada."""
    held = _HELD[:]
    _HELD.clear()
    _NEXT.clear()
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


DECLARE_SECTORS_AGAIN = des_panels.DECLARE_SECTORS_AGAIN
_REPORTED_ERROR = "Error: "  # cómo empieza cada línea del error de una orden lanzada con bpy.ops


def _declare_sectors(mode: str) -> set[str]:
    """La orden de la 012 que declara los sectores (``core_declare_sectors``) con la capa y el
    campo de su vista, lanzada como ``mode`` (``INVOKE_DEFAULT`` desde la interfaz: su ``invoke``
    y, si hace falta, el diálogo de la entrada cambiada; ``EXEC_DEFAULT`` desde un guion). Lo que
    rechaza llega como ``RuntimeError`` con su texto."""
    name = des_panels.DECLARE_SECTORS.split(".", 1)[1]
    return set(getattr(bpy.ops.geoblender, name)(mode))


def _error_lines(exc: RuntimeError) -> list[str]:
    """Los errores que dijo una orden lanzada con ``bpy.ops`` (``Error: …`` por línea), sin la
    palabra que Blender les antepone."""
    return [line.removeprefix(_REPORTED_ERROR) for line in str(exc).splitlines() if line.strip()]


class GEOBLENDER_OT_des_declare_sectors(DesignCommandAware, ProvenanceAwareOperator,
                                       bpy.types.Operator):
    """Declare the sectors again from the layer of polygons of the window and read the design
    sectors again"""

    bl_idname = DECLARE_SECTORS_AGAIN
    bl_label = "Declare the sectors again"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context: Any) -> set[str]:
        """«Declarar de nuevo desde una capa…» de la ventana de los sectores (RF-013-07,
        RF-013-10; T44): la declaración es la de la 012 (``core_declare_sectors``, que conserva los
        valores de los sectores que mantienen su código), lanzada como se lanzó esta (desde la
        interfaz, con su ``invoke``); solo si termina, vuelve a leer en la misma ventana los
        sectores, los huérfanos y las capas, y deja en ella y en la barra de estado lo que dice la
        012. Cancelada o rechazada, la ventana queda como estaba y se dice su error."""
        mode = "INVOKE_DEFAULT" if self.provenance_dialog else "EXEC_DEFAULT"
        try:
            done = _declare_sectors(mode)
        except RuntimeError as exc:  # la 012 lo rechazó: su texto (bpy.ops no lo pasa a la barra)
            for line in _error_lines(exc):
                self.report({"ERROR"}, line)
            return {"CANCELLED"}
        if "FINISHED" not in done:
            return {"CANCELLED"}
        other = constraint_panels.view()
        said = [] if other is None else [(line.text, bool(line.alert))
                                         for line in other.search_lines]
        project = SESSION.project
        try:
            des_panels.fill_sectors(project)
            des_panels.fill_sector_sources(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            LOGGER.warning("No se pudo volver a leer los sectores de diseño", exc_info=True)
            said.append((design_error_text(exc), True))
        des_panels.show_sector_report(said)
        for text, alert in said:
            self.report({"WARNING" if alert else "INFO"}, text)
        return {"FINISHED"}


# --- Envolventes y escalonado… (T24; HU-013-1, HU-013-3, HU-013-5, HU-013-6; RF-013-05,
#     RF-013-16, RF-013-17, RF-013-21, RF-013-31, RF-013-33; plan §5.3.3, §5.5, D-14, D-27, D-30) --

COMPUTE_ENVELOPE = "geoblender.des_compute_envelope"
ENVELOPE_STAGE = provenance.ENVELOPE
STEPPED_STAGE = provenance.STEPPED
SEEDS_FROM_ITEMS = [
    ("SURFACE", "A surface in a zone", ""),
    ("FIXED", "A fixed elevation in a zone", ""),
    ("GRID", "A grid of elevations", ""),
]
"""De dónde salen las semillas (``design.model.SeedKind``): la superficie en las celdas de una zona,
una cota fija en las celdas de una zona o una rejilla de cotas."""
DIRECTION_ITEMS = [("DOWN", "Downwards", ""), ("UP", "Upwards", "")]
METRIC_ITEMS = [("CHAMFER5", "Chamfer 5×5", ""), ("EXACT", "Exact Euclidean", "")]
SLOPE_ITEMS = [("CONSTANT", "Constant", ""), ("SECTORS", "By sectors", "")]
BOUND_ITEMS = [("ALL", "The whole domain", ""), ("SECTORS", "Some sectors", ""),
               ("LAYER", "A layer of polygons", "")]
SENSE_ITEMS = [("CUT", "Cut (face first)", ""), ("FILL", "Fill (berm first)", "")]


class ComputeFormError(ProfileFormError):
    """Lo que impide calcular con lo escrito en el diálogo de las envolventes (ya en el idioma de
    Geoblender)."""


@dataclass(frozen=True)
class _Plan:
    """Lo pedido en el diálogo, ya comprobado: la envolvente, su escalonado si se pidió, la
    superficie de la que parte y el perfil de cada sector (código del sector → código del perfil)
    cuando hacen falta."""

    envelope: design_model.EnvelopeRequest
    design: design_model.DesignRequest | None
    start: str
    assigned: dict[str, str]


def _zone_of(identifier: str) -> design_model.Zone | None:
    """La zona de una opción de la lista de zonas (``bl.ui.des_panels.zone_items``): ninguna (toda
    la superficie), el dominio por defecto, o una restricción, un sector o una capa por su código o
    su nombre."""
    if identifier in ("", des_panels.NO_ZONE):
        return None
    kinds = design_model.ZoneKind
    if identifier == des_panels.DOMAIN_ZONE:
        return design_model.Zone(kinds.DOMAIN)
    for prefix, kind in ((des_panels.CONSTRAINT_ZONE, kinds.CONSTRAINT),
                         (des_panels.SECTOR_ZONE, kinds.SECTOR), (des_panels.LAYER_ZONE, kinds.LAYER)):
        if identifier.startswith(prefix) and identifier[len(prefix):]:
            return design_model.Zone(kind, identifier[len(prefix):])
    raise ComputeFormError(tr("Choose the zone of the seeds"))


def seed_source(seeds_from: str, surface: str, zone: str, elevation: str
                ) -> design_model.SeedSource:
    """Las semillas pedidas en un diálogo (el de las envolventes y el de la vista previa): de dónde
    salen (``SURFACE``, ``FIXED`` o ``GRID``), la superficie o rejilla de cotas, la zona (una opción
    de ``bl.ui.des_panels.zone_items``) y la cota fija tecleada. Las que faltan o no valen las
    rechaza el dominio al calcular (``des.seed_missing``, ``des.seed_elevation``…);
    :class:`ComputeFormError` si falta algo del diálogo."""
    kind = design_model.SeedKind(seeds_from.lower())
    if kind is design_model.SeedKind.FIXED:
        value = typed_number(elevation, tr("Elevation (m)"))
        if value is None:
            raise ComputeFormError(tr("Write the fixed elevation of the seeds in metres"))
        return design_model.SeedSource(kind, zone=_zone_of(zone), elevation_m=value)
    if surface in ("", des_panels.NO_ZONE):
        raise ComputeFormError(tr("Choose the surface of the seeds: there are no grids in the "
                                  "project or in the active version"))
    if kind is design_model.SeedKind.GRID:
        return design_model.SeedSource(kind, grid=surface)
    return design_model.SeedSource(kind, surface=surface, zone=_zone_of(zone))


def work_domain(bound: str, bound_layer: str, shown: Any) -> design_model.WorkDomain:
    """El acotado del dominio de trabajo pedido en un diálogo (RF-013-02): todo, los sectores
    marcados en la vista (``shown.sectors[].use``) o una capa de polígonos; nunca se amplía.
    :class:`ComputeFormError` si falta algo del diálogo."""
    if bound == "SECTORS":
        codes = tuple(item.code for item in shown.sectors if item.use and item.code)
        if not codes:
            raise ComputeFormError(tr("Mark the sectors the work domain is bound to"))
        return design_model.WorkDomain(sectors=codes)
    if bound == "LAYER":
        if bound_layer in ("", des_panels.NO_LAYER):
            raise ComputeFormError(tr("Choose the layer of polygons the work domain is bound "
                                      "to"))
        return design_model.WorkDomain(layer=bound_layer)
    return design_model.WorkDomain()


def _draw_seeds(layout: Any, operator: Any) -> None:
    """Las semillas de un diálogo (el de las envolventes y el de la vista previa): su origen, la
    superficie o la rejilla de cotas, la zona y la cota fija, según el origen."""
    seeds = layout.box()
    seeds.label(text=tr("Seeds"), translate=False)
    seeds.prop(operator, "seeds_from", text=tr("Origin of the seeds"), translate=False)
    if operator.seeds_from != "FIXED":
        seeds.prop(operator, "surface", text=tr("Surface") if operator.seeds_from == "SURFACE"
                   else tr("Grid of elevations"), translate=False)
    if operator.seeds_from != "GRID":
        seeds.prop(operator, "zone", text=tr("Zone of the seeds"), translate=False)
    if operator.seeds_from == "FIXED":
        seeds.prop(operator, "elevation", text=tr("Elevation (m)"), translate=False)


def _draw_bound(layout: Any, operator: Any) -> None:
    """El acotado del dominio de un diálogo: a todo, a unos sectores o a una capa de polígonos (la
    casilla de cada sector la dibuja ``bl.ui.des_panels.draw_sector_rows``)."""
    layout.prop(operator, "bound", text=tr("Bound to"), translate=False)
    if operator.bound == "LAYER":
        layout.prop(operator, "bound_layer", text=tr("Layer of polygons"), translate=False)


def _invoke_later(idname: str, window: Any, **values: Any) -> None:
    """Lanza la orden ``idname`` con ``INVOKE_DEFAULT`` y ``values`` en la ventana ``window`` en
    cuanto acaba lo que corre (un diálogo no se abre desde dentro de un modal); sin ventana,
    nada."""
    if window is None:
        return
    group, name = idname.split(".")

    def call() -> None:
        try:
            with bpy.context.temp_override(window=window):
                getattr(getattr(bpy.ops, group), name)("INVOKE_DEFAULT", **values)
        except (RuntimeError, TypeError, AttributeError, ReferenceError):
            LOGGER.warning("No se pudo pedir confirmación en %s", idname, exc_info=True)

    bpy.app.timers.register(call, first_interval=0.0)


def _first_window() -> Any:
    manager = getattr(bpy.context, "window_manager", None)
    windows = list(getattr(manager, "windows", ()) or ())
    return windows[0] if windows else None


def _ask_confirmation(context: Any = None) -> None:
    """Pide confirmar el cálculo recién hecho (D-14): la misma orden con ``confirm=True`` en cuanto
    acaba el modal (un diálogo no se abre desde dentro de un modal); sin ventana, nada (lo dice el
    informe y el cálculo espera a que se cree con ``confirm=True``)."""
    _invoke_later(COMPUTE_ENVELOPE, getattr(context, "window", None) or _first_window(),
                  confirm=True)


def _confirm_later(values: Mapping[str, Any], idname: str) -> None:
    """Pide confirmar que se sustituye el fichero que ya existe (D-29 de la 011): la misma orden
    ``idname`` con ``confirm`` (su confirmación) y ``values``, en cuanto acaba ésta; sin ventana,
    nada (lo dice el aviso)."""
    _invoke_later(idname, _first_window(), confirm=True, **values)


def _drain(operator: Any, steps: Iterator[Progress]) -> Any:
    """Los pasos ``steps`` de una orden de una vez (desde un guion): el resultado del último o, si
    fallan, ``None`` (ya dicho con el ``_report`` de ``operator``; sus pasos no dejan nada a
    medias)."""
    found = None
    try:
        for step in steps:
            if step.result is not None:
                found = step.result
    except GeoblenderError as exc:
        operator._report({"ERROR"}, operator._error_text(exc))
        return None
    except (sqlite3.Error, OSError, ValueError) as exc:
        LOGGER.error("«%s» se ha parado", operator.bl_idname, exc_info=exc)
        operator._report({"ERROR"}, error_text(exc))
        return None
    if found is None:  # pragma: no cover - los pasos acaban siempre con su resultado
        operator._report({"ERROR"}, tr("The operation did not finish with its result"))
    return found


class GEOBLENDER_OT_des_compute_envelope(DesignCommandAware, ProvenanceAwareOperator,
                                         _StepsModal, bpy.types.Operator):
    """Envelope of an excavation or a fill and, if you want, its benching and design surface"""

    bl_idname = COMPUTE_ENVELOPE
    bl_label = "Envelopes and benching…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.ENVELOPE

    # Como Compilar las máscaras: cada evento del temporizador avanza pasos durante, como mucho,
    # este tiempo (cada paso, ≤ 0,05 s: ninguna llamada de más de 0,2 s, RNF-013-07).
    STEP_BUDGET_S = 0.05

    name: StringProperty(  # type: ignore[valid-type]
        name="Name",
        description="Name of the envelope, unique in the active version; its benching has the same "
                    "name", options=_FIELD)
    seeds_from: EnumProperty(  # type: ignore[valid-type]
        name="Origin of the seeds",
        description="Where the seeds come from: the cells of a surface inside a zone, a fixed "
                    "elevation in the cells of a zone or a grid of elevations of the project or of "
                    "the active version", items=SEEDS_FROM_ITEMS, default="SURFACE", options=_FIELD)
    surface: EnumProperty(  # type: ignore[valid-type]
        name="Surface",
        description="Surface or grid of elevations of the project or of the active version the "
                    "seeds are read from", items=des_panels.surface_items, options=_FIELD)
    zone: EnumProperty(  # type: ignore[valid-type]
        name="Zone of the seeds",
        description="Cells where the seeds are: the whole surface, the default domain, the zone "
                    "of a constraint, a design sector or a layer of polygons",
        items=des_panels.zone_items, options=_FIELD)
    elevation: StringProperty(  # type: ignore[valid-type]
        name="Elevation (m)", description="Fixed elevation of the seeds in metres", options=_FIELD)
    direction: EnumProperty(  # type: ignore[valid-type]
        name="Envelope direction",
        description="Downwards: the lowest surface that does not go under the seeds; upwards: the "
                    "highest surface that does not go over them",
        items=DIRECTION_ITEMS, default="DOWN", options=_FIELD)
    metric: EnumProperty(  # type: ignore[valid-type]
        name="Metric",
        description="How the distance to the seeds is measured: the 5×5 chamfer (fast, with the "
                    "scale of the grid) or the exact Euclidean distance (constant slope only)",
        items=METRIC_ITEMS, default="CHAMFER5", options=_FIELD)
    slope_mode: EnumProperty(  # type: ignore[valid-type]
        name="Slope",
        description="A constant slope or the general slope of each sector (the maximum it imposes "
                    "or, without one, that of its profile)",
        items=SLOPE_ITEMS, default="CONSTANT", options=_FIELD)
    slope: StringProperty(  # type: ignore[valid-type]
        name="Slope (°)",
        description="Slope of the envelope in degrees, from 0 (included) to 90 (excluded)",
        options=_FIELD)
    mesh: StringProperty(  # type: ignore[valid-type]
        name="Mesh factor",
        description="Factor between 0 (excluded) and 1 that reduces the slope of the envelope for "
                    "the grid (empty: 1)", options=_FIELD)
    reach: StringProperty(  # type: ignore[valid-type]
        name="Reach",
        description="Largest distance from the seeds, in metres, at which the envelope has data "
                    "(empty: no limit)", options=_FIELD)
    bound: EnumProperty(  # type: ignore[valid-type]
        name="Bound to",
        description="Where the work domain is bound: the whole domain of the masks, some sectors "
                    "or a layer of polygons (it is never enlarged)",
        items=BOUND_ITEMS, default="ALL", options=_FIELD)
    bound_layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of polygons",
        description="Layer of polygons of the project the work domain is bound to",
        items=des_panels.layer_items, options=_FIELD)
    stepped: BoolProperty(  # type: ignore[valid-type]
        name="Bench the envelope", default=False,
        description="After creating the envelope, bench it into benches and berms and compose the "
                    "design surface (with its own summary to confirm)", options=_FIELD)
    sense: EnumProperty(  # type: ignore[valid-type]
        name="Sense",
        description="Cut: the face first, the surface stays over the envelope; fill: the berm "
                    "first, the surface stays under it",
        items=SENSE_ITEMS, default="CUT", options=_FIELD)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the benching starts from: the ground the design is composed with",
        items=des_panels.surface_items, options=_FIELD)
    base_profile: StringProperty(  # type: ignore[valid-type]
        name="Base profile",
        description="Bench profile of the cells without a sector (and of the sectors without "
                    "their own)", options=_FIELD)
    anchor: EnumProperty(  # type: ignore[valid-type]
        name="Anchor",
        description="Elevation the benches are anchored to: that of each profile or a grid of "
                    "anchors of the project or of the active version",
        items=des_panels.anchor_items, options=_FIELD)
    # La confirmación de crear (D-14) y los pasos con el temporizador de la ventana, con el avance y
    # Esc: los pone invoke; desde un guion, sin ellos, de una vez.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué.
        Con ``confirm``, el diálogo de crear el cálculo abierto (D-14). Si no, las listas de
        superficies, zonas, capas, perfiles y sectores leídas de nuevo, la propuesta (el nombre, la
        superficie y la de partida: el terreno) y el diálogo del cálculo: Intro calcula."""
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
            des_panels.fill_profiles(project)
            des_panels.fill_sectors(project)
            des_panels.refresh_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        des_panels.clear_sector_marks()
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.bl_idname)].label),
            confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """El nombre y las superficies que propone el diálogo si quien lo lanza no los dio. De
        «Superficie» y de «Superficie de partida», el terreno (T45): el MDT o el TIN seleccionado
        en la vista; con una superficie de diseño seleccionada, la de partida de su ficha; sin
        selección, la primera de la lista que no es una rejilla de un diseño
        (``surface_proposal.ground_item``). La lista las sigue ofreciendo todas."""
        given = self.properties.is_property_set
        if not self.name.strip():
            self.name = tr("Envelope")
        if des_panels.has_surfaces():
            items = [identifier for identifier, _name, _about
                     in des_panels.surface_items(None, None)]
            ground = surface_proposal.ground_item(context, project, items,
                                                  des_panels.surface_choice)
            if not given("surface"):
                self.surface = ground
            if not given("start"):
                self.start = ground

    def _confirmation(self, context: Any) -> set[str]:
        """El diálogo de crear el cálculo abierto (D-14, RF-013-31): su resumen con los avisos y
        «Crear» (o «Crear con N avisos», que los nombra); «Cancelar» y cerrarlo lo descartan."""
        held = calculation()
        if held is None:
            self.report({"ERROR"}, tr("There is no open calculation: compute first"))
            return {"CANCELLED"}
        count = len(held.warnings())
        if not count:
            confirm_text = tr("Create")
        elif count == 1:
            confirm_text = tr("Create with 1 warning")
        else:
            confirm_text = tr("Create with {count} warnings", count=count)
        shown = des_panels.view()
        title = shown.summary_title if shown is not None and shown.summary_title else (
            command_text(catalog().commands[command_idname(self.bl_idname)].label))
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=title, confirm_text=confirm_text)

    def draw(self, context: Any) -> None:
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        shown = des_panels.view()
        layout.prop(self, "name", text=tr("Name"), translate=False)
        _draw_seeds(layout, self)
        layout.prop(self, "direction", text=tr("Envelope direction"), translate=False)
        layout.prop(self, "metric", text=tr("Metric"), translate=False)
        layout.prop(self, "slope_mode", text=tr("Slope"), translate=False)
        if self.slope_mode == "CONSTANT":
            layout.prop(self, "slope", text=tr("Slope (°)"), translate=False)
        layout.prop(self, "mesh", text=tr("Mesh factor"), translate=False)
        layout.prop(self, "reach", text=tr("Reach"), translate=False)
        _draw_bound(layout, self)
        layout.prop(self, "stepped", text=tr("Bench the envelope"), toggle=True, translate=False)
        if self.stepped:
            layout.prop(self, "sense", text=tr("Sense"), translate=False)
            layout.prop(self, "start", text=tr("Start surface"), translate=False)
            layout.prop(self, "anchor", text=tr("Anchor"), translate=False)
        profiles = self.stepped or self.slope_mode == "SECTORS"
        if profiles and shown is not None:
            layout.prop_search(self, "base_profile", shown, "profiles", text=tr("Base profile"),
                               translate=False)
        bound = self.bound == "SECTORS"
        if (bound or profiles) and shown is not None and len(shown.sectors):
            box = layout.box()
            box.label(text=tr("Sectors"), translate=False)
            des_panels.draw_sector_rows(box, bound=bound, profiles=profiles)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _seeds(self) -> design_model.SeedSource:
        """Las semillas pedidas; las que faltan o no valen las rechaza el dominio al calcular
        (``des.seed_missing``, ``des.seed_elevation``…)."""
        return seed_source(self.seeds_from, self.surface, self.zone, self.elevation)

    def _domain(self, shown: Any) -> design_model.WorkDomain:
        """El acotado del dominio de trabajo pedido (RF-013-02): todo, los sectores marcados o una
        capa; nunca se amplía."""
        return work_domain(self.bound, self.bound_layer, shown)

    @staticmethod
    def _profile_code(picked: str, where: str, codes: Mapping[str, str]) -> str | None:
        """El código del perfil de banco que se eligió por su nombre (``None`` si no se eligió
        ninguno); :class:`ComputeFormError` si ya no existe."""
        wanted = picked.strip()
        if not wanted:
            return None
        found = codes.get(wanted)
        if found is None:
            raise ComputeFormError(tr("The bench profile «{profile}» ({where}) is not in the "
                                      "project", profile=wanted, where=where))
        return found

    def _plan(self, project: Any) -> _Plan:
        """Lo pedido en el diálogo, comprobado sin escribir ni calcular nada: los perfiles y los
        sectores se leen de nuevo (un guion no abre el diálogo) y las peticiones del dominio se
        arman con ellos. Los rangos, las semillas y los perfiles sin valor los rechaza el dominio
        al calcular (RF-013-16, RF-013-19). :class:`ComputeFormError` si falta algo del diálogo."""
        des_panels.fill_profiles(project)
        des_panels.fill_sectors(project)
        shown = des_panels.view()
        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the envelope"))
        seeds = self._seeds()
        mode = design_model.SlopeMode(self.slope_mode.lower())
        constant = mode is design_model.SlopeMode.CONSTANT
        slope = typed_number(self.slope, tr("Slope (°)")) if constant else None
        if constant and slope is None:
            raise ComputeFormError(tr("Write the slope of the envelope in degrees"))
        mesh = typed_number(self.mesh, tr("Mesh factor"))
        reach = typed_number(self.reach, tr("Reach"))
        domain = self._domain(shown)
        codes = des_panels.profile_codes()
        base = self._profile_code(self.base_profile, tr("Base profile"), codes)
        assigned: dict[str, str] = {}
        for item in shown.sectors:
            found = self._profile_code(item.profile_pick, item.name, codes)
            if found is not None:
                assigned[item.code] = found
        by_sectors = not constant
        envelope = design_model.EnvelopeRequest(
            name, self.direction.lower(), seeds, slope_mode=mode, slope_deg=slope,
            metric=self.metric.lower(), mesh_factor=1.0 if mesh is None else mesh, reach_m=reach,
            domain=domain, base_profile=base if by_sectors else None,
            sector_profiles=assigned if by_sectors else {})
        if not self.stepped:
            return _Plan(envelope, None, "", assigned if by_sectors else {})
        if base is None:
            raise ComputeFormError(tr("Choose the base profile of the benching"))
        if self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the benching"))
        design = design_model.DesignRequest(
            name, name, self.sense.lower(), base, assigned,
            None if self.anchor in ("", des_panels.NO_ANCHOR) else self.anchor)
        return _Plan(envelope, design, self.start, assigned)

    # --- Calcular -----------------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido
        (sin escribir nada si no vale), pasa por la puerta de la 008 y calcula la envolvente por
        pasos con ``design.steps.envelope_run`` —compila las máscaras antes si no están al día—,
        sin registrar nada (D-14): desde la interfaz, en el modal con el avance y Esc; desde un guion,
        de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar."""
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
            plan = self._plan(project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.envelope_run(project, plan.envelope, version=version,
                                          budget_s=self.STEP_BUDGET_S)
        if plan.design is not None:
            _NEXT[:] = [_Next(plan.design, plan.start, version)]
        des_panels.assign_profiles(project, plan.assigned)  # RF-013-21: lo asignado, en la vista
        return self._run(context, project, plan.envelope.name, ENVELOPE_STAGE, steps)

    def _run(self, context: Any, project: Any, name: str, stage: str,
             steps: Iterator[Progress]) -> set[str]:
        """Corre los pasos de una fase (la envolvente o su escalonado): en el modal, con el avance y
        Esc, o de una vez desde un guion."""
        self._project, self._name, self._stage = project, name, stage
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, steps)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        calculated = _drain(self, steps)
        if calculated is None:
            _NEXT.clear()
            return {"CANCELLED"}
        self._finished(context, calculated)
        return {"FINISHED"}

    def _finished(self, context: Any, opened: Calculation) -> None:
        """Lo que hace al terminar un cálculo (RF-013-31): lo deja abierto y sin registrar, enseña su
        resumen con los avisos (en el informe y en la vista) y, desde la interfaz, pide confirmar."""
        hold_calculation(opened)
        des_panels.show_summary(opened)
        shown = des_panels.view()
        for line in () if shown is None else shown.summary:
            self._report({"WARNING" if line.alert else "INFO"}, line.name)
        if self.in_steps and getattr(context, "window", None) is not None:
            _ask_confirmation(context)

    # --- Crear --------------------------------------------------------------------------------

    def _create(self, context: Any) -> set[str]:
        """«Crear» (D-14, RF-013-17, RF-013-31): registra el cálculo abierto en una transacción
        (``Calculation.create``: la operación, su dato, sus tablas y sus cifras); si falla, no queda
        nada. Si se había pedido el escalonado, sigue con él (la envolvente ya está en la versión)."""
        project = SESSION.project
        opened = calculation()
        if opened is None:
            self.report({"ERROR"}, tr("There is no open calculation: compute first"))
            return {"CANCELLED"}
        try:
            opened.create()
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            discard_calculation()
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, opened.op_type)  # Ctrl+Z no lo deshace
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        des_panels.show_summary(None)
        self.report({"INFO"}, tr("Envelope «{name}» created in {version}", name=opened.name,
                                 version=opened.version)
                    if opened.op_type == ENVELOPE_STAGE
                    else tr("Benching «{name}» created in {version}", name=opened.name,
                            version=opened.version))
        following = _NEXT.pop() if _NEXT and opened.op_type == ENVELOPE_STAGE else None
        _NEXT.clear()
        if following is None:
            return {"FINISHED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        try:
            steps = design_steps.design_run(project, following.request, following.surface,
                                            version=following.version,
                                            budget_s=self.STEP_BUDGET_S)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return self._run(context, project, following.request.name, STEPPED_STAGE, steps)

    # --- En pasos (_StepsModal) ---------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado (plan §5.5): «Calculando la envolvente… 40 % · Esc:
        cancelar» o, en la segunda fase, «Calculando el escalonado… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if getattr(self, "_stage", ENVELOPE_STAGE) == STEPPED_STAGE:
            return tr("Computing the benching… {percent} % · Esc: cancel", percent=percent)
        return tr("Computing the envelope… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Calculation cancelled: nothing has been left half-done")

    def _error_text(self, exc: GeoblenderError) -> str:
        """El error de los pasos en el idioma de Geoblender; si falló el escalonado, dice que la
        envolvente ya está creada."""
        found = design_error_text(exc)
        if getattr(self, "_stage", ENVELOPE_STAGE) != STEPPED_STAGE:
            return found
        return f"{found} " + tr("The envelope «{name}» is already created: only its benching has "
                                "not been computed", name=getattr(self, "_name", ""))

    def _after_stop(self, context: Any) -> None:
        """Tras cancelar o fallar: el escalonado que esperaba no sigue."""
        _NEXT.clear()

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        if step.result is None:
            if project_session.current() is not getattr(self, "_project", None):
                return self._fail(context, tr(
                    "The project was closed while the design «{name}» was being computed: nothing "
                    "has been left half-done", name=getattr(self, "_name", "")))
            return None
        self._done(context)
        self._finished(context, step.result)
        return {"FINISHED"}

    def modal(self, context: Any, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except Exception as exc:  # noqa: BLE001 - los pasos cerrados no dejan nada a medias
            LOGGER.error("«%s» se ha parado", self.bl_idname, exc_info=exc)
            return self._fail(context, design_error_text(exc))

    def cancel(self, context: Any) -> None:
        """Lo que Blender llama al cancelar: un modal en curso cierra sus pasos (como Esc); la
        ventana de la confirmación cerrada sin crear («Cancelar», Esc, apartar el ratón) descarta el
        cálculo abierto y sus temporales (D-14). El diálogo del cálculo no descarta nada."""
        if getattr(self, "_steps", None) is not None:
            _StepsModal.cancel(self, context)
            _NEXT.clear()
        elif self.confirm:
            discard_calculation()


# --- Vista previa de semillas, dominios y restricciones (T25; HU-013-1; RF-013-01, RF-013-02,
#     RF-013-03, RF-013-33; plan §5.3.3, §5.5, D-29) ----------------------------------------------

TOGGLE_PREVIEW = "geoblender.des_toggle_preview"


def _preview() -> Any:
    """El módulo de la vista previa (``bl.draw.design``), importado al usarlo."""
    from ..draw import design as preview  # al usarlo: nada pesado al registrar

    return preview


def _preview_on(context: Any = None) -> bool:
    """Si la vista previa está activa (sin importar su módulo si no lo está)."""
    manager = getattr(context, "window_manager", None) or getattr(bpy.context, "window_manager",
                                                                  None)
    return bool(getattr(manager, PREVIEW_PROPERTY, False))


class GEOBLENDER_OT_des_toggle_preview(DesignCommandAware, ProvenanceAwareOperator,
                                       bpy.types.Operator):
    """Show the seeds, domains and constraints before computing"""

    bl_idname = TOGGLE_PREVIEW
    bl_label = "Preview of seeds, domains and constraints"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = ENVELOPE_STAGE

    seeds_from: EnumProperty(  # type: ignore[valid-type]
        name="Origin of the seeds",
        description="Where the seeds come from: the cells of a surface inside a zone, a fixed "
                    "elevation in the cells of a zone or a grid of elevations of the project or of "
                    "the active version", items=SEEDS_FROM_ITEMS, default="SURFACE", options=_FIELD)
    surface: EnumProperty(  # type: ignore[valid-type]
        name="Surface",
        description="Surface or grid of elevations of the project or of the active version the "
                    "seeds are read from", items=des_panels.surface_items, options=_FIELD)
    zone: EnumProperty(  # type: ignore[valid-type]
        name="Zone of the seeds",
        description="Cells where the seeds are: the whole surface, the default domain, the zone "
                    "of a constraint, a design sector or a layer of polygons",
        items=des_panels.zone_items, options=_FIELD)
    elevation: StringProperty(  # type: ignore[valid-type]
        name="Elevation (m)", description="Fixed elevation of the seeds in metres", options=_FIELD)
    bound: EnumProperty(  # type: ignore[valid-type]
        name="Bound to",
        description="Where the work domain is bound: the whole domain of the masks, some sectors "
                    "or a layer of polygons (it is never enlarged)",
        items=BOUND_ITEMS, default="ALL", options=_FIELD)
    bound_layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of polygons",
        description="Layer of polygons of the project the work domain is bound to",
        items=des_panels.layer_items, options=_FIELD)

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Con la vista previa activa, se puede quitar siempre; si no, lo de las órdenes de Diseño
        (RF-013-33): con un proyecto en escritura y la versión activa editable o ninguna."""
        return True if _preview_on(context) else _write_poll(cls)

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Con la vista previa activa, la quita. Si no, sin versión activa abre la ventana que pide
        una (RF-009-05) y con ella no editable dice por qué; con una, lee de nuevo las listas de
        superficies, zonas, capas y sectores, propone de «Superficie» el terreno, como «Envolventes y
        escalonado…» (T46, ``surface_proposal.ground_item``), si quien la lanza no la dio, y abre el
        diálogo de lo que se previsualiza: Intro la muestra."""
        self.provenance_dialog = True
        if _preview_on(context):
            return self.execute(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            des_panels.fill_sectors(project)
            des_panels.refresh_choices(project)
            if des_panels.has_surfaces() and not self.properties.is_property_set("surface"):
                items = [identifier for identifier, _name, _about
                         in des_panels.surface_items(None, None)]
                self.surface = surface_proposal.ground_item(context, project, items,
                                                            des_panels.surface_choice)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        des_panels.clear_sector_marks()
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.bl_idname)].label),
            confirm_text=tr("Show"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        _draw_seeds(layout, self)
        _draw_bound(layout, self)
        shown = des_panels.view()
        if self.bound == "SECTORS" and shown is not None and len(shown.sectors):
            box = layout.box()
            box.label(text=tr("Sectors"), translate=False)
            des_panels.draw_sector_rows(box, bound=True, profiles=False)

    def execute(self, context: Any) -> set[str]:
        """Con la vista previa activa, la quita. Si no, comprueba lo pedido (sin escribir ni calcular
        nada) y la activa: se construye por pasos con el temporizador, solo leyendo, y dibuja las
        semillas, el dominio de trabajo, los sectores y las restricciones con su resumen (RF-013-03)."""
        preview = _preview()
        if preview.enabled():
            preview.disable()
            self.report({"INFO"}, tr("Preview of seeds, domains and constraints hidden"))
            return {"FINISHED"}
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            des_panels.fill_sectors(SESSION.project)
            wanted = preview.Plan(
                seed_source(self.seeds_from, self.surface, self.zone, self.elevation),
                work_domain(self.bound, self.bound_layer, des_panels.view()))
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        try:
            preview.enable(wanted)
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr(
                "The preview of seeds, domains and constraints could not be shown: {detail}",
                detail=design_error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the preview of seeds, domains and constraints"))
        return {"FINISHED"}


# --- Exportar una rejilla del diseño a GeoTIFF (T28; HU-013-6; RF-013-34; plan §5.3.3, D-29) -------

EXPORT_DESIGN_GRID = "geoblender.des_export_design_grid"
EXPORT_TICKS = 1000
"""El total de los pasos de la exportación (``Progress.total``): su avance, en milésimas."""
GEOTIFF_SUFFIX = ".tif"


def _export_progress(steps: Iterator[float], name: str) -> Iterator[Progress]:
    """Los pasos de ``design.export.export_grid_steps`` (su avance, 0–1) como ``Progress`` (fase
    ``export``, en milésimas); el último lleva el fichero escrito. Cerrarlos cierra los de la
    exportación, que no dejan nada a medias."""
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


class GEOBLENDER_OT_des_export_design_grid(_StepsModal, bpy.types.Operator):
    """Write a registered grid of the design (envelope, design surface or berm elevations) as a
    deliverable GeoTIFF (it is not an operation: also from a superseded version and, outside the
    project, in read-only)"""

    bl_idname = EXPORT_DESIGN_GRID
    bl_label = "Export grid to GeoTIFF…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    STEP_BUDGET_S = 0.05

    source: StringProperty(  # type: ignore[valid-type]
        name="Design grid",
        description="Uid or name of the grid of the design (empty: the active one in the view)",
        options=_FIELD)
    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"})
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.tif;*.tiff", options={"HIDDEN"})
    check_existing: BoolProperty(  # type: ignore[valid-type]
        default=True, options={"HIDDEN", "SKIP_SAVE"})
    overwrite: BoolProperty(  # type: ignore[valid-type]
        name="Replace", description="Replace the file if it already exists", options=_FIELD)
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Con un proyecto abierto y con procedencia: exportar no es una operación (D-29), así que
        también en solo lectura (fuera del proyecto) y con la versión SUPERADO."""
        reason = SESSION.unavailable()
        if reason is not None:
            cls.poll_message_set(reason)
            return False
        return True

    def _stored(self, context: Any) -> Any:
        """La rejilla que se exporta (``design.export.StoredGrid``): la de :attr:`source` o la del
        objeto de diseño activo de la vista; ``ValueError`` sin ninguna, y ``DesignError`` si no es
        una rejilla viva del diseño."""
        from ...design import export  # al usarlo: habilitar no lo carga

        ref = self.source.strip() or des_panels.wanted(context)
        if not ref:
            raise ValueError(tr("Choose the design grid: select it in the view"))
        return export.stored_grid(SESSION.project, ref,
                                  version=scene_versions.active_version() or "")

    def invoke(self, context: Any, event: Any) -> set[str]:
        """El diálogo de fichero, con el destino que propone (``exports/<dato>_<V01>.tif`` del
        proyecto); con ``confirm``, la confirmación de sustituir el que ya existe."""
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
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        self.source = stored.record.uid
        if not self.filepath:
            stem = f"{stored.record.name}_{stored.version_code}"
            self.filepath = str(Path(SESSION.project.root, gis_provenance.EXPORTS_FOLDER,
                                     f"{stem}{GEOTIFF_SUFFIX}"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        """Escribe el entregable desde lo registrado (``design.export``): desde la interfaz, por
        pasos con el avance y Esc; desde un guion, de una vez. Sobre un fichero que ya existe, solo
        con ``overwrite`` (desde la interfaz, lo pregunta)."""
        from ...design import export  # al usarlo: habilitar no lo carga

        blocked = SESSION.unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        shown = self.filepath.strip()
        try:
            stored = self._stored(context)
            if not shown:
                raise ValueError(tr("Choose the file to export to"))
            target = Path(bpy.path.abspath(shown))
            steps = export.export_grid_steps(
                SESSION.project, stored.family, stored.name, target, version=stored.version_uid,
                read_only=read_only_dirs(), overwrite=bool(self.overwrite))
        except GisError as exc:
            interactive = self.in_steps and getattr(context, "window", None) is not None
            if exc.code == "gis.export_target_exists" and interactive:
                self.report({"WARNING"}, error_text(exc))
                _confirm_later({"source": stored.record.uid, "filepath": shown},
                               idname=EXPORT_DESIGN_GRID)
            else:
                self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
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
            self._report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return {"CANCELLED"}  # pragma: no cover - los pasos acaban siempre con el fichero

    def _exported(self) -> set[str]:
        self._report({"INFO"}, tr("Design grid exported to «{file}»",
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
        return design_error_text(exc)

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


classes: tuple[type, ...] = (GEOBLENDER_OT_des_edit_bench_profiles,
                             GEOBLENDER_OT_des_save_bench_profile,
                             GEOBLENDER_OT_des_edit_design_sectors,
                             GEOBLENDER_OT_des_set_sector_slope,
                             GEOBLENDER_OT_des_compute_envelope,
                             GEOBLENDER_OT_des_toggle_preview,
                             GEOBLENDER_OT_des_export_design_grid,
                             GEOBLENDER_OT_des_declare_sectors)
"""Las órdenes reales del diseño (la T22 pone «Perfiles de banco…» y su orden interna, la T23
«Sectores de diseño…» y la suya, la T24 «Envolventes y escalonado…», la T25 «Vista previa de
semillas, dominios y restricciones», la T28, la interna que exporta una rejilla a GeoTIFF, y la
T44, la que declara de nuevo los sectores desde su ventana)."""
