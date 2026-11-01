# SPDX-License-Identifier: GPL-3.0-or-later
"""Los límites legales y las restricciones en Blender (código ``core``, spec 012; plan 012 §5.1,
§5.3.3, D-19, D-29, D-31, D-38; ADR-0025 §2, ADR-0027).

**El registro** (T21; HU-012-4; RF-012-16, RF-012-28): lo que la 012 declara en ``core``, en
constantes del módulo construidas una vez:

- sus **familias de parámetros** (``core.constraints.params.FAMILIES``, ADR-0027): el resguardo
  hacia fuera y hacia dentro, el peso y si está activa cada restricción, por su código inmutable
  y de versión (D-4), sin valor por defecto (D-5); y su **definición** del proyecto, la distancia
  de búsqueda de intocables (``core.constraints.params.DEFINITIONS``, 25 m «sin confirmar»);
- sus **tipos de operación** de proyecto (:data:`OPERATION_DEFS`: ``core.edit_constraints``,
  ``core.edit_intentions``, ``core.declare_sectors`` y ``core.find_untouchables``; ninguno se
  repite solo: una restricción, una intención o una búsqueda son decisiones de una persona, D-26);
- **la comprobación de congelar** de ``res`` (D-29, RF-012-25): las verificaciones obsoletas, con
  recintos que no cumplen o con la marca de búsqueda pendiente, y las superficies de diseño sin
  verificación al día, que el diálogo de congelar de la 009 pide aceptar
  (``reserves.compliance_store.freeze_findings``,
  ``core.versions.freeze.register_freeze_check``);
- sus textos (``core.constraints.messages``) en ``core.i18n``.

Lo que declaran en ``core`` las otras dos mitades de la 012 lo registran sus módulos:
``gis.compile_constraints`` y sus cifras, ``bl/ops/gis.py`` (con su recálculo por la cola de las
máscaras); ``res.verify_constraints``, el espesor mínimo y sus cifras, ``bl/ops/res.py`` (con el
suyo por la cola de ``res``). Las tres tablas de restricciones y las demás de ``core`` no se
registran en ningún sitio: las crea la operación que las escribe por primera vez y las anota como
datos del proyecto (``formato-proyecto.md`` §3.11).

:func:`register` pone lo que falta y apunta cómo quitarlo; :func:`unregister` quita solo eso, en
orden inverso: lo que otro registró antes con la misma clave, o puso después en su lugar, es suyo y
se queda (también una definición, una familia o una comprobación de ``core`` o de ``res``). Los
dos son simétricos e idempotentes: registrar y desregistrar deja los registros de ``core`` como
estaban (ADR-0025 §2). Nada pesado: lo que registra ya está importado con el resto de ``bl``, y las
máscaras, su búsqueda, el almacén de la verificación y la cadena de versiones que arrastran
(``gis.masks.*``, ``gis.search``, ``reserves.compliance_store``, ``core.versions.freeze``…) se
importan al usarlos, dentro de cada orden: habilitar Geoblender tarda ≤ 0,5 s (RNF-001-03; spec
012, T38). La comprobación de congelar que se registra es :func:`freeze_findings`, que importa la
de ``res`` en su primera llamada, y se registra en ``core.versions.freezing`` (el módulo ligero).

Las órdenes (T22 a T28: Límites…, Restricciones…, Buscar elementos intocables por sector…,
Intenciones del cliente…, Ver restricciones y límites, Verificar un diseño por recinto…) las pasa
a la entrada «012» del catálogo cada una con su clase real; :data:`classes` irá creciendo con
ellas. Los cargadores de la vista de T27 y T28 se registrarán aquí también.

**Límites…** (T22; HU-012-1; RF-012-01, RF-012-02, RF-012-05, RF-012-15, RF-012-28; plan §5.3.4,
§5.5, D-14): :class:`GEOBLENDER_OT_core_edit_limits` lee del proyecto las capas de polígonos y los
límites declarados en la versión activa (``bl.ui.constraint_panels.fill_limits``) y abre su
ventana (``GEOBLENDER_PT_core_limits``); :class:`GEOBLENDER_OT_core_declare_limits` (interna;
«Declarar los límites» de la ventana) comprueba el formulario (:func:`limits_request`: las capas
elegidas, el motivo, el decisor, la fecha y el resguardo hacia dentro), mira todas las capas
antes de crear ninguna (``gis.masks.sources.check_constraints``) y crea las restricciones de cada
una (``gis.masks.sources.create_constraints``: una ``core.edit_constraints`` por capa, con el
límite legal o el perímetro de actuación y, como parámetros del proyecto, el resguardo hacia
dentro del límite legal y «activa»); después vuelve a leer la ventana y dice el informe. Las dos
quedan desactivadas, con su motivo, sin proyecto, en solo lectura o con la versión activa no
editable (:func:`constraints_unavailable`). ``geoblender.core_go_to_place`` («Ir a», interna; solo
lee) encuadra la Vista 3D en un lugar de coordenadas absolutas dadas en texto (ADR-0005).

**Restricciones…** (T23; HU-012-2; RF-012-01 a RF-012-04, RF-012-19, RF-012-28):
:class:`GEOBLENDER_OT_core_edit_constraints` lee las restricciones y su estado en la versión activa
y abre su ventana (``bl.ui.constraint_panels``); :class:`GEOBLENDER_OT_core_create_constraints`
(interna, «Desde una capa…») crea las de una capa «entidades» o «dominios» del proyecto con un tipo
para todas o el campo que lo da, sus campos del nombre, el motivo, el decisor y la fecha, y los
parámetros que se declaran (:func:`create_request`), con ``core.edit_constraints`` y sin tocar la
capa de origen, y deja el informe de las creadas y de las rechazadas;
:class:`GEOBLENDER_OT_core_complete_constraint` (interna, «Completar…») da su código y sus
parámetros a la dibujada en QGIS, guarda lo que cambia de una con código y da de alta los
parámetros que su tipo pide y le faltan. Los parámetros que ya existen se cambian con «Cambiar
parámetro…» de la 008 (``geoblender.core_set_parameter``) y su ámbito de la 009. «Compilar las
máscaras» y «Exportar las máscaras…» (``bl.ops.gis``) las lanza la misma ventana.

**Buscar elementos intocables por sector…** (T24; HU-012-3; RF-012-07 a RF-012-10, RF-012-28; plan
§5.3.4, §5.5, A6, A12, D-26): :class:`GEOBLENDER_OT_core_find_untouchables` lee los sectores con el
estado de su búsqueda (vigente o pendiente), las capas que se pueden consultar y la distancia de
búsqueda, enseña la búsqueda abierta y abre su ventana (``bl.ui.constraint_panels``). Desde ella,
:class:`GEOBLENDER_OT_core_declare_sectors` declara los sectores de una capa de polígonos y su campo
(``core.declare_sectors``) o los quita (el perímetro es el único sector);
:class:`GEOBLENDER_OT_core_search_untouchables` busca por pasos (modal con avance y Esc, ninguna
llamada de más de 0,2 s: ``gis.masks.sectors.search_steps``) en el sector y las capas elegidos y
deja la búsqueda **abierta** (:class:`OpenSearch`, en memoria: lo hallado con la decisión de
cada entidad); :class:`GEOBLENDER_OT_core_convert_hit` convierte una entidad hallada en un
intocable con su resguardo y su motivo (``core.edit_constraints`` solo de esa entidad:
``gis.masks.sources.create_from_entity``) y :class:`GEOBLENDER_OT_core_discard_hit` la descarta con
un motivo; :class:`GEOBLENDER_OT_core_close_search` registra la búsqueda
(``core.find_untouchables``: ``gis.masks.sectors.close_search``) y deja vigente el sector. Una
búsqueda abierta con algo convertido no se deja por buscar en otro sector (se perdería su
constancia); si se vuelve a buscar en el mismo, conserva las decisiones de lo que se vuelve a
hallar. Todas quedan desactivadas, con su motivo, sin proyecto, en solo lectura o con la versión
activa no editable (:func:`constraints_unavailable`).

**Intenciones del cliente…** (T25; HU-012-6; RF-012-26, RF-012-27, RF-012-28; plan §5.3.4, §5.5,
D-8):
:class:`GEOBLENDER_OT_core_edit_client_marks` lee las intenciones guardadas, las capas «entidades»,
los documentos y las decisiones de la propiedad y abre su ventana (``bl.ui.constraint_panels``).
Desde ella, :class:`GEOBLENDER_OT_core_save_client_marks` (interna, «Guardar las marcas»)
comprueba el formulario (:func:`marks_request`: la capa, el papel de un campo con su
correspondencia o uno para todas, el nombre, la cota y la fecha de un campo o una para todas, el
documento y la decisión) y guarda las marcas de la capa como intenciones (``core.edit_intentions``:
``gis.masks.sources.create_intentions``, con la capa y el documento como entradas); las entidades
que no sirven quedan rechazadas con su motivo y nada cambia en las máscaras (error 30).
:class:`GEOBLENDER_OT_core_convert_intention` (interna, «Convertir en restricción…») crea la
restricción de una intención con el tipo, el motivo, el decisor, la fecha y los parámetros que se
declaran (``core.edit_constraints`` con ``core_intention`` como entrada:
``core.constraints.provenance.convert_intention``): la intención no cambia ni se borra y las
máscaras pasan a obsoletas. Las intenciones se ven en la vista con ``core_intention``
(``bl.scene.constraint_views``, que registra ``bl.scene``). Las tres quedan desactivadas, con su
motivo, sin proyecto, en solo lectura o con la versión activa no editable
(:func:`constraints_unavailable`).

**Ver restricciones y límites** (T26; HU-012-1 a HU-012-4; RF-012-18; RNF-012-05; plan §5.3.4,
D-30): :class:`GEOBLENDER_OT_core_toggle_constraints_overlay` (el control 30) activa o quita la
superposición de la Vista 3D (``bl.draw.constraints``, que se importa al activarla: nada pesado al
registrar). Solo lee y no escribe en el proyecto: sirve en solo lectura y con la versión activa no
editable; hace falta un proyecto abierto.
"""

from __future__ import annotations

import datetime as dt
import functools
import logging
import math
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from ...core import i18n
from ...core import params as core_params
from ...core.catalog.search import path_text
from ...core.constraints import messages as constraint_messages
from ...core.constraints import params as constraint_params
from ...core.constraints import provenance as constraint_provenance
from ...core.constraints import store as constraint_store
from ...core.constraints.model import (
    Constraint,
    ConstraintParam,
    ConstraintType,
    GeometryKind,
    HitDecision,
    IntentionRole,
    is_code,
)
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, tr
from ...core.project.model import Progress
from ...core.provenance import contract
from ...core.provenance.operations import ItemKind, Use
from ...core.provenance.undo import UndoKind
from ...core.units import convert, parse_quantity
from ...core.versions import freezing as freeze_registry
from ...gis import store as gis_store
from ...reserves import provenance as res_provenance
from ..props.core_constraints import MARK_FIELD
from ..scene import project_session, undo_watch
from ..scene import versions as scene_versions
from ..ui import constraint_panels
from ..ui import views as ui_views
from ..ui.commands import catalog as command_catalog
from ..ui.commands import command_idname, text, with_note
from ..ui.res_panels import NOT_SHOWN
from .core import _StepsModal
from .core_provenance import (
    SESSION,
    ProvenanceAwareOperator,
    ensure_ready,
    error_text,
    write_unavailable,
)

if TYPE_CHECKING:  # solo para los tipos: habilitar no importa las máscaras (RNF-001-03, T38)
    from ...core.versions.freeze import FreezeCheck, FreezeFinding
    from ...gis.masks import sectors as mask_sectors

LOGGER = logging.getLogger("geoblender.bl.ops")
TRANSLATION_CONTEXT = "Geoblender"
EDIT_LIMITS = "geoblender.core_edit_limits"
DECLARE_LIMITS = constraint_panels.DECLARE_LIMITS
GO_TO_PLACE = constraint_panels.GO_TO_PLACE
_HIDDEN = {"HIDDEN", "SKIP_SAVE"}  # las pone quien la lanza (el botón de la ventana)
_METRE = "m"
MODULE = constraint_provenance.MODULE
"""El módulo de las definiciones, las familias y los tipos de operación de las restricciones
(``core``)."""
FREEZE_MODULE = res_provenance.MODULE
"""El módulo que declara la comprobación de congelar de la 012 (``res``)."""
OPERATION_DEFS: tuple[contract.OperationDef, ...] = constraint_provenance.OPERATIONS
"""Los ``OperationDef`` de los cuatro tipos de ``core`` de las restricciones (de proyecto, sin
repetición)."""

_UNDO: list[Callable[[], None]] = []


def freeze_findings(conn: sqlite3.Connection, version_uid: str) -> Sequence[FreezeFinding]:
    """La comprobación de congelar de ``res`` (``reserves.compliance_store.freeze_findings``,
    RF-012-25, D-29), la que registra :func:`register`: el almacén de la verificación y todo lo que
    arrastra se importa en la primera llamada, al congelar, y no al habilitar Geoblender
    (RNF-001-03, spec 012 T38)."""
    from ...reserves import compliance_store  # al usarla: habilitar no carga la verificación

    return compliance_store.freeze_findings(conn, version_uid)


# --- Registro --------------------------------------------------------------------------------


def register() -> None:
    """Instala los textos de las restricciones en ``core.i18n`` y registra sus familias de
    parámetros, la definición de la distancia de búsqueda, sus cuatro tipos de operación
    (:data:`OPERATION_DEFS`) y la comprobación de congelar de ``res`` que aún no están;
    idempotente."""
    i18n.install(constraint_messages.CATALOG_ES)
    missing = tuple(defn for defn in constraint_params.DEFINITIONS
                    if defn.key not in core_params.DEFINITIONS)
    if missing:
        core_params.register_definitions(missing)
        _UNDO.append(functools.partial(_unregister_definitions, missing))
    families = tuple(family for family in constraint_params.FAMILIES
                     if family.pattern not in core_params.FAMILIES)
    if families:
        core_params.register_families(families)
        _UNDO.append(functools.partial(_unregister_families, families))
    for definition in OPERATION_DEFS:
        if definition.op_type not in contract.OPERATIONS:
            contract.register_operation(definition)
            _UNDO.append(_unregister_if(contract.OPERATIONS, definition.op_type, definition,
                                        contract.unregister_operation))
    check = freeze_findings
    if (FREEZE_MODULE, check) not in freeze_registry.freeze_checks():
        freeze_registry.register_freeze_check(FREEZE_MODULE, check)
        _UNDO.append(functools.partial(_unregister_freeze_check, FREEZE_MODULE, check))


def unregister() -> None:
    """Quita lo que puso :func:`register`, en orden inverso (lo que otro cambió después es
    suyo); las traducciones instaladas se quedan; idempotente."""
    while _UNDO:
        _UNDO.pop()()
    drop_search()  # la búsqueda abierta vive en memoria: no sobrevive a Geoblender


def _unregister_if(view: Mapping[str, Any], key: str, item: object,
                   remove: Callable[[str], object]) -> Callable[[], None]:
    def undo() -> None:
        if view.get(key) is item:  # si otro lo cambió, es suyo
            remove(key)

    return undo


def _unregister_definitions(ours: tuple[core_params.ParamDef, ...]) -> None:
    """Quita las definiciones que puso :func:`register` (``ours``) y deja las demás de ``core``
    (la del límite de las copias de los originales, la de lo que otro registró antes con su clave
    o puso después en su lugar). ``core.params`` solo las quita por módulo: se quitan todas y se
    vuelven a poner las de otro, los mismos objetos."""
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


def _unregister_freeze_check(module: str, check: FreezeCheck) -> None:
    """Quita la comprobación ``check`` de ``module`` y deja las demás de ese módulo (en su
    orden): ``core.versions.freezing`` solo las quita por módulo."""
    others = [other for found, other in freeze_registry.freeze_checks()
              if found == module and other is not check]
    freeze_registry.unregister_freeze_checks(module)
    for other in others:
        freeze_registry.register_freeze_check(module, other)


# --- Disponibilidad ------------------------------------------------------------------------------


def constraints_unavailable() -> str | None:
    """Por qué no están disponibles ahora las órdenes de los límites y las restricciones que
    escriben (RF-012-28), en el idioma de Geoblender: sin proyecto, sin la procedencia o en solo
    lectura («Proyecto en solo lectura: …»), o con la versión activa SUPERADO o DESCARTADO («V02
    está en estado SUPERADO: cree una versión nueva a partir de ella»); ``None`` si se puede,
    también sin versión activa (la orden que compila la pide al lanzarla, RF-012-16)."""
    return write_unavailable() or scene_versions.not_editable_text()


def _write_poll(cls: type) -> bool:
    """El ``poll`` de lo que escribe: dice por qué no se puede."""
    reason = constraints_unavailable()
    if reason is not None:
        cls.poll_message_set(reason)  # type: ignore[attr-defined]
        return False
    return True


def _call_panel(name: str) -> set[str]:
    """Abre la ventana emergente ``name`` con ``wm.call_panel``; sigue abierta aunque el ratón
    salga de ella (``keep_open``), hasta pulsar fuera o Esc. Una que no está registrada,
    nada."""
    if getattr(bpy.types, name, None) is None:
        return {"CANCELLED"}
    return bpy.ops.wm.call_panel(name=name, keep_open=True)


# --- Límites… (T22) ------------------------------------------------------------------------------


class ConstraintFormError(ValueError):
    """Lo que impide crear, completar o declarar con lo escrito en una ventana (ya en el idioma
    de Geoblender)."""


class LimitsFormError(ConstraintFormError):
    """Lo que impide declarar los límites con lo escrito en la ventana (ya en el idioma de
    Geoblender)."""


@dataclass(frozen=True, slots=True)
class LimitsRequest:
    """Lo que pide la ventana de Límites… ya comprobado: las capas del límite legal, la del
    perímetro de actuación (si la hay), el campo del nombre (si lo hay), el motivo, el decisor,
    la fecha de la decisión y el resguardo hacia dentro del límite legal (m, float64; ``None``
    si no se declara ningún límite legal)."""

    legal: tuple[str, ...]
    perimeter: str | None
    name_field: str | None
    reason: str
    decided_by: str
    decided_on: dt.date
    inward_m: float | None


def _typed_date(typed: str) -> dt.date:
    """La fecha de la decisión tecleada: DD/MM/AAAA (como la 008) o AAAA-MM-DD."""
    shown = typed.strip()
    if not shown:
        raise LimitsFormError(tr("Write the date of the decision as DD/MM/YYYY"))
    for form in (constraint_panels.DATE_FORMAT, "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(shown, form).date()
        except ValueError:
            continue
    raise LimitsFormError(tr("«{value}» is not a date: write it as DD/MM/YYYY", value=shown))


def _typed_inward(typed: str) -> float:
    """El resguardo hacia dentro tecleado, en metros (float64, 0 o más; «10», «2,5 m»)."""
    shown = typed.strip()
    if not shown:
        raise LimitsFormError(tr("Write the inward setback of the legal limit in metres "
                                 "(0 or more)"))
    try:
        number, unit = parse_quantity(shown)
        value = float(convert(number, unit or _METRE, _METRE))
        checked = constraint_params.family(ConstraintParam.BUFFER_IN).template.check(value)
    except (GeoblenderError, ValueError):
        raise LimitsFormError(tr("Write the inward setback of the legal limit in metres "
                                 "(0 or more): «{value}» does not fit", value=shown)) from None
    if not isinstance(checked, float) or not math.isfinite(checked):  # inalcanzable
        raise LimitsFormError(tr("Write the inward setback of the legal limit in metres "
                                 "(0 or more)"))
    return checked


def limits_request(limits: Any) -> LimitsRequest:
    """Lo que pide la ventana de Límites… (``limits``: ``WindowManager.geoblender_constraints``)
    comprobado, sin leer ni escribir nada. :class:`LimitsFormError` si no se eligió ninguna capa,
    una es a la vez el límite legal y el perímetro, hay más de un perímetro, falta el motivo o el
    decisor, la fecha no lo es o el resguardo hacia dentro no es un número de metros de 0 o más
    (solo se pide con alguna capa de límite legal)."""
    legal = tuple(item.name for item in limits.limit_layers if item.legal)
    perimeters = tuple(item.name for item in limits.limit_layers if item.perimeter)
    if not legal and not perimeters:
        raise LimitsFormError(tr("Choose the layers of the legal limit or of the action "
                                 "perimeter"))
    for name in legal:
        if name in perimeters:
            raise LimitsFormError(tr("«{layer}» cannot be the legal limit and the action "
                                     "perimeter at once", layer=name))
    if len(perimeters) > 1:
        raise LimitsFormError(tr("Choose a single action perimeter: {count} layers are chosen",
                                 count=len(perimeters)))
    reason = limits.limit_reason.strip()
    if not reason:
        raise LimitsFormError(tr("Write the reason of the limits"))
    decided_by = limits.limit_decided_by.strip()
    if not decided_by:
        raise LimitsFormError(tr("Write who decides the limits"))
    decided_on = _typed_date(limits.limit_decided_on)
    inward = _typed_inward(limits.limit_inward) if legal else None
    return LimitsRequest(legal, perimeters[0] if perimeters else None,
                         limits.limit_name_field.strip() or None, reason, decided_by,
                         decided_on, inward)


def _layer_label(dataset: str) -> str:
    """El nombre de una capa para nombrar sus límites cuando no hay campo del nombre: el de su
    dato sin el prefijo de su familia (``gis_fea_concesion`` → ``concesion``)."""
    return constraint_panels.layer_label(dataset)


class GEOBLENDER_OT_core_edit_limits(ProvenanceAwareOperator, bpy.types.Operator):
    """Concession, perimeter of the works and fill-only strip"""

    bl_idname = EDIT_LIMITS
    bl_label = "Limits…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = constraint_provenance.EDIT_CONSTRAINTS

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Sin proyecto, en solo lectura o con la versión activa no editable, no está
        disponible y dice por qué (RF-012-28)."""
        return _write_poll(cls)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        """La de :class:`ProvenanceAwareOperator` y, con la versión activa no editable, el porqué
        (RF-012-28, RF-009-21)."""
        about = super().description(context, properties)
        note = scene_versions.not_editable_text()
        return about if note is None else with_note(about, note)

    def execute(self, context: Any) -> set[str]:
        """Lee las capas de polígonos y los límites de la versión activa en la vista y abre la
        ventana; desde un guion sin ventana, solo la vista."""
        try:
            constraint_panels.fill_limits(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(constraint_panels.LIMITS_PANEL)


class GEOBLENDER_OT_core_declare_limits(ProvenanceAwareOperator, bpy.types.Operator):
    """Declare the legal limit and the action perimeter from polygon layers of the project, with
    their reason, decider, date and inward setback"""

    bl_idname = DECLARE_LIMITS
    bl_label = "Declare the limits"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = constraint_provenance.EDIT_CONSTRAINTS

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _write_poll(cls)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        about = super().description(context, properties)
        note = scene_versions.not_editable_text()
        return about if note is None else with_note(about, note)

    def execute(self, context: Any) -> set[str]:
        """Declara los límites de la ventana (véase el módulo): comprueba el formulario y todas
        las capas antes de crear nada, pasa la puerta de la 008 con las capas como entradas, crea
        las restricciones de cada capa (una ``core.edit_constraints`` por capa, que apunta en el
        diario de Ctrl+Z) y dice cuántas y el informe de los límites (RF-012-05)."""
        limits = constraint_panels.view()
        project = SESSION.project
        try:
            request = limits_request(limits)
        except LimitsFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        jobs = [(name, ConstraintType.LEGAL_LIMIT) for name in request.legal]
        if request.perimeter is not None:
            jobs.append((request.perimeter, ConstraintType.ACTION_PERIMETER))
        values: dict[ConstraintParam, Any] = {ConstraintParam.ACTIVE: True}
        if request.inward_m is not None:
            values[ConstraintParam.BUFFER_IN] = request.inward_m
        declaration = constraint_provenance.ParamDeclaration(
            values=values, source=request.decided_by, decided_by=request.decided_by,
            reason=request.reason, source_kind="person")

        def mapping(ctype: ConstraintType) -> constraint_provenance.LayerMapping:
            return constraint_provenance.LayerMapping(
                ctype=ctype, name_field=request.name_field, reason=request.reason,
                decided_by=request.decided_by, decided_on=request.decided_on)

        ready = ensure_ready(self.provenance_op_type,
                             [Use(name, constraint_provenance.SOURCE_ROLE) for name, _ in jobs],
                             report=self.report, dialog=self.provenance_dialog,
                             version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        from ...gis.masks import sources  # al usarlas: habilitar no carga las máscaras (T38)
        from ...gis.masks import store as mask_store

        try:
            declared = mask_store.declared_limits(project,
                                                  version=scene_versions.active_version())
            taken = {(item.source_input, item.ctype) for item in
                     (*declared.legal, *declared.perimeter, *declared.inactive)
                     if item.source_input}
            for name, ctype in jobs:  # todas las capas, antes de crear ninguna
                rows, _rejected = sources.check_constraints(project, name, mapping(ctype))
                if (rows[0].source_input, ctype) in taken:  # no se declara dos veces
                    self.report({"ERROR"}, tr("«{layer}» is already declared as {ctype}: choose "
                                              "another layer", layer=name,
                                              ctype=ctype.label(i18n.language())))
                    return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        created = 0
        rejected: list[Any] = []
        failure: Exception | None = None
        try:
            for name, ctype in jobs:
                edited = sources.create_constraints(
                    project, name, mapping(ctype), params=declaration,
                    default_name=_layer_label(name))
                undo_watch.record(UndoKind.OPERATION, constraint_provenance.EDIT_CONSTRAINTS)
                created += len(edited.constraints)
                rejected.extend(edited.rejected)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            failure = exc
        try:  # lo hecho, aunque algo fallara a mitad: la ventana lo enseña
            found = constraint_panels.fill_limits(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            failure = failure or exc
            found = None
        if failure is not None:
            self.report({"ERROR"}, error_text(failure))
            return {"CANCELLED"} if not created else {"FINISHED"}
        self.report({"INFO"}, tr("Limits declared: {count} constraints created from {layers} "
                                 "layers", count=created, layers=len(jobs)))
        for item in rejected:
            self.report({"WARNING"}, item.text(i18n.language()))
        if found is not None:
            for line in limits.limit_lines:
                self.report({"WARNING" if line.alert else "INFO"}, line.text)
        return {"FINISHED"}


class GEOBLENDER_OT_core_go_to_place(bpy.types.Operator):
    """Frame the 3D View on a place of the report (absolute coordinates)"""

    bl_idname = GO_TO_PLACE
    bl_label = "Go to"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    # Las coordenadas absolutas viajan como texto (nunca ``FloatProperty``: float32, ADR-0005).
    x: StringProperty(default="", options=_HIDDEN)  # type: ignore[valid-type]
    y: StringProperty(default="", options=_HIDDEN)  # type: ignore[valid-type]
    radius: StringProperty(default="", options=_HIDDEN)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Solo lee: hace falta un proyecto abierto y una Vista 3D en la ventana."""
        if project_session.current() is None:
            cls.poll_message_set(tr("Open a project"))  # type: ignore[attr-defined]
            return False
        if ui_views.target_view3d(context) is None:
            cls.poll_message_set(  # type: ignore[attr-defined]
                tr("There is no 3D view in this window"))
            return False
        return True

    def execute(self, context: Any) -> set[str]:
        """Encuadra la Vista 3D de destino en el cuadrado de semilado ``radius`` metros alrededor
        de ``(x, y)`` absolutas (``bl.ui.views.go_to``)."""
        try:
            x, y, radius = (float(typed.replace(",", ".")) for typed in
                            (self.x, self.y, self.radius))
        except ValueError:
            typed = next((value for value in (self.x, self.y, self.radius)
                          if not _is_number(value)), "")
            self.report({"ERROR"}, tr("«{value}» is not a number: «Go to» needs coordinates "
                                      "and a radius in metres", value=typed))
            return {"CANCELLED"}
        if not all(math.isfinite(value) for value in (x, y, radius)) or radius <= 0.0:
            self.report({"ERROR"}, tr("«{value}» is not a number: «Go to» needs coordinates "
                                      "and a radius in metres", value=self.radius))
            return {"CANCELLED"}
        target = ui_views.target_view3d(context)
        if target is None or not ui_views.go_to(target, context, x, y, radius):
            self.report({"ERROR"}, tr("There is no 3D view in this window"))
            return {"CANCELLED"}
        return {"FINISHED"}


def _is_number(typed: str) -> bool:
    try:
        float(typed.replace(",", "."))
    except ValueError:
        return False
    return True


# --- Restricciones… (T23; RF-012-01 a RF-012-04, RF-012-19, RF-012-28) ----------------------------

EDIT_CONSTRAINTS = "geoblender.core_edit_constraints"
CREATE_CONSTRAINTS = constraint_panels.CREATE_CONSTRAINTS
COMPLETE_CONSTRAINT = constraint_panels.COMPLETE_CONSTRAINT
FIELD = "FIELD"
"""El valor de «tipo» de «Desde una capa…» cuando el tipo lo da un campo de la capa."""
NO_TYPE = "NONE"
"""El valor de «tipo» de «Completar…» mientras no se elige ninguno."""
CREATE_TYPE_ITEMS = [(FIELD, "From a field of the layer", ""),
                     *[(ctype.name, ctype.label_msgid, "") for ctype in ConstraintType]]
COMPLETE_TYPE_ITEMS = [(NO_TYPE, "Choose the type", ""),
                       *[(ctype.name, ctype.label_msgid, "") for ctype in ConstraintType]]
DIALOG_WIDTH = 520
_FIELD = {"SKIP_SAVE"}  # las rellena el diálogo: nunca las de la vez anterior


def _typed_metres(typed: str, param: ConstraintParam, message: str) -> float | None:
    """Un resguardo tecleado en metros (float64, 0 o más; «8», «2,5 m»); vacío, ``None`` (no se
    declara). ``message``: el texto del error, con «{value}»."""
    shown = typed.strip()
    if not shown:
        return None
    try:
        number, unit = parse_quantity(shown)
        value = float(convert(number, unit or _METRE, _METRE))
        checked = constraint_params.family(param).template.check(value)
    except (GeoblenderError, ValueError):
        raise ConstraintFormError(message.format(value=shown)) from None
    if not isinstance(checked, float) or not math.isfinite(checked):  # inalcanzable
        raise ConstraintFormError(message.format(value=shown))
    return checked


def _typed_weight(typed: str) -> float | None:
    """El peso tecleado de una «preferible no afectar» (1 o más); vacío, ``None``."""
    shown = typed.strip()
    if not shown:
        return None
    message = tr("Write the weight as a number of 1 or more: «{value}» does not fit",
                 value=shown)
    try:
        number, unit = parse_quantity(shown)
        checked = constraint_params.family(ConstraintParam.WEIGHT).template.check(float(number))
    except (GeoblenderError, ValueError):
        raise ConstraintFormError(message) from None
    if unit or not isinstance(checked, float) or not math.isfinite(checked):
        raise ConstraintFormError(message)
    return checked


def _typed_declared(buffer_out: str, buffer_in: str, weight: str,
                    active: bool) -> dict[ConstraintParam, Any]:
    """Los parámetros que se declaran de unas restricciones con lo tecleado en un diálogo (T23,
    T25): «activa» y, de los resguardos y el peso, los que se escribieron (los vacíos se declaran
    después). :class:`ConstraintFormError` si alguno no vale."""
    values: dict[ConstraintParam, Any] = {ConstraintParam.ACTIVE: bool(active)}
    for param, found in (
            (ConstraintParam.BUFFER_OUT, _typed_metres(
                buffer_out, ConstraintParam.BUFFER_OUT,
                tr("Write the outward setback in metres (0 or more): «{value}» does not fit",
                   value="{value}"))),
            (ConstraintParam.BUFFER_IN, _typed_metres(
                buffer_in, ConstraintParam.BUFFER_IN,
                tr("Write the inward setback of the legal limit in metres (0 or more): "
                   "«{value}» does not fit", value="{value}"))),
            (ConstraintParam.WEIGHT, _typed_weight(weight))):
        if found is not None:
            values[param] = found
    return values


def _typed_decision(project: Any, typed: str) -> str | None:
    """La decisión de la propiedad elegida en un diálogo (T41; RF-012-02): el ``uid`` de la que
    se llama ``typed`` entre las del proyecto (:func:`constraint_panels.decision_choices`);
    vacío, ``None`` (ninguna). :class:`ConstraintFormError` si no es una de las registradas."""
    shown = typed.strip()
    if not shown:
        return None
    found = next((uid for uid, name in constraint_panels.decision_choices(project)
                  if name == shown), None)
    if found is None:
        raise ConstraintFormError(tr("«{value}» is not a decision registered in the project",
                                     value=shown))
    return found


def _typed_values(typed: str) -> dict[str, ConstraintType] | None:
    """La correspondencia de los valores del campo del tipo tecleada («valor = tipo; valor =
    tipo»; cada tipo por su código, su nombre en español o en inglés); vacía, ``None`` (la de
    por defecto: los tipos por su nombre)."""
    shown = typed.strip()
    if not shown:
        return None
    known = constraint_provenance.default_type_values()
    found: dict[str, ConstraintType] = {}
    for pair in (part for part in shown.split(";") if part.strip()):
        value, _, kind = pair.partition("=")
        ctype = known.get(kind.strip().casefold())
        if not value.strip() or ctype is None:
            raise ConstraintFormError(tr(
                "«{value}» is not «value = type»: write the type by its name, as in "
                "«Hydrant = Untouchable; Pond = No cut»", value=pair.strip()))
        found[value.strip()] = ctype
    return found


@dataclass(frozen=True, slots=True)
class CreateRequest:
    """Lo que pide «Desde una capa…» ya comprobado: la capa, cómo se leen sus entidades, los
    parámetros que se declaran de las restricciones que se creen y la decisión de la propiedad
    que las respalda, si se eligió una (RF-012-01, RF-012-02)."""

    layer: str
    mapping: constraint_provenance.LayerMapping
    declaration: constraint_provenance.ParamDeclaration
    decision: str | None = None


def _fixed_or_field(field: str, fixed: str, message: str) -> tuple[str | None, str | None]:
    """El campo de la capa que da un dato o su valor fijo (uno de los dos; ``message`` si falta
    los dos)."""
    chosen, typed = field.strip(), fixed.strip()
    if not chosen and not typed:
        raise ConstraintFormError(message)
    return (chosen or None), (None if chosen else typed)


def create_request(form: Any, project: Any) -> CreateRequest:
    """Lo que pide «Desde una capa…» (``form``: las propiedades de la orden) comprobado, sin
    leer ni escribir nada de la capa. :class:`ConstraintFormError` si no se eligió una capa del
    proyecto de la que se puedan crear restricciones, falta el campo del tipo, el motivo, el
    decisor o la fecha (un campo de la capa o un valor para todas), la fecha no lo es, un
    resguardo o el peso no valen, la correspondencia de los valores del tipo no se lee o la
    decisión de la propiedad que se elige no es una de las del proyecto (T41)."""
    layer = form.layer.strip()
    if not layer:
        raise ConstraintFormError(tr("Choose the layer the constraints are created from"))
    if layer not in constraint_panels.source_layers(project):
        raise ConstraintFormError(tr(
            "«{layer}» is not a layer of the project that gives constraints: import it as "
            "Features or Domains", layer=layer))
    kinds: dict[str, Any]
    if form.ctype == FIELD:
        if not form.type_field.strip():
            raise ConstraintFormError(tr(
                "Write the field of the type: the one of the layer that says which type each "
                "constraint is"))
        kinds = {"type_field": form.type_field.strip(),
                 "type_values": _typed_values(form.type_values)}
    else:
        kinds = {"ctype": ConstraintType[form.ctype]}
    reason_field, reason = _fixed_or_field(
        form.reason_field, form.reason,
        tr("Write the reason of the constraints, or the field of the layer that gives it"))
    decider_field, decided_by = _fixed_or_field(
        form.decider_field, form.decided_by,
        tr("Write who decides the constraints, or the field of the layer that gives it"))
    date_field, typed_date = _fixed_or_field(
        form.date_field, form.decided_on,
        tr("Write the date of the decision as DD/MM/YYYY, or the field of the layer that "
           "gives it"))
    decided_on = None if typed_date is None else _typed_date(typed_date)
    mapping = constraint_provenance.LayerMapping(
        name_field=form.name_field.strip() or None, reason_field=reason_field, reason=reason,
        decider_field=decider_field, decided_by=decided_by, date_field=date_field,
        decided_on=decided_on, priority=int(form.priority), **kinds)
    values = _typed_declared(form.buffer_out, form.buffer_in, form.weight, form.active)
    declaration = constraint_provenance.ParamDeclaration(
        values=values, source=layer, source_kind="document",
        decided_by=decided_by or project.session.user_host,
        reason=reason or tr("Created from the layer «{layer}»", layer=layer))
    return CreateRequest(layer, mapping, declaration, _typed_decision(project, form.decision))


class GEOBLENDER_OT_core_edit_constraints(ProvenanceAwareOperator, bpy.types.Operator):
    """Untouchable, no cut, no fill, buffer and the other constraints of the design"""

    bl_idname = EDIT_CONSTRAINTS
    bl_label = "Constraints…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = constraint_provenance.EDIT_CONSTRAINTS

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Sin proyecto, en solo lectura o con la versión activa no editable, no está
        disponible y dice por qué (RF-012-28)."""
        return _write_poll(cls)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        """La de :class:`ProvenanceAwareOperator` y, con la versión activa no editable, el porqué
        (RF-012-28, RF-009-21)."""
        about = super().description(context, properties)
        note = scene_versions.not_editable_text()
        return about if note is None else with_note(about, note)

    def execute(self, context: Any) -> set[str]:
        """Lee las restricciones del proyecto y sus estados en la versión activa en la vista y
        abre su ventana, con elegida la del objeto activo si es el de una restricción (PC §3.7:
        «Editar la restricción…»); desde un guion sin ventana, solo la vista."""
        try:
            constraint_panels.fill_constraints(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        constraint_panels.choose_active(context)
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(constraint_panels.CONSTRAINTS_PANEL)


def _show_result(project: Any, lines: list[constraint_panels.Line], report: Any) -> None:
    """Deja ``lines`` como el último resultado de la ventana y lo dice con ``report`` (los de
    alerta, como aviso); vuelve a leer la lista. Un fallo al leer queda en el registro."""
    constraint_panels.show_report(lines)
    try:
        constraint_panels.fill_constraints(project)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.warning("No se pudo volver a leer la lista de restricciones", exc_info=True)
    for line in lines:
        report({"WARNING" if line.alert else "INFO"}, line.text)


class GEOBLENDER_OT_core_create_constraints(ProvenanceAwareOperator, bpy.types.Operator):
    """Create constraints from a layer of the project: a type for all of its entities or the
    field that gives it, with their name, reason, decider, date and setbacks"""

    bl_idname = CREATE_CONSTRAINTS
    bl_label = "From a layer…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = constraint_provenance.EDIT_CONSTRAINTS

    layer: StringProperty(  # type: ignore[valid-type]
        name="Layer", description="Layer of the project, as Features or Domains, the "
        "constraints are created from", options=_FIELD)
    ctype: EnumProperty(  # type: ignore[valid-type]
        name="Type", description="The type for all the entities of the layer, or the field "
        "that gives it", items=CREATE_TYPE_ITEMS, default=FIELD, options=_FIELD)
    type_field: StringProperty(  # type: ignore[valid-type]
        name="Type field", description="Field of the layer that says the type of each entity",
        options=_FIELD)
    type_values: StringProperty(  # type: ignore[valid-type]
        name="Values of the type", description="Which type each value of the field means, as "
        "«value = type; value = type» (empty: the value is the name of the type)",
        options=_FIELD)
    name_field: StringProperty(  # type: ignore[valid-type]
        name="Name field", description="Field of the layer that gives the name of each "
        "constraint", options=_FIELD)
    reason_field: StringProperty(  # type: ignore[valid-type]
        name="Reason field", description="Field of the layer that gives the reason of each "
        "constraint (empty: the reason written below)", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why these constraints limit the design", options=_FIELD)
    decider_field: StringProperty(  # type: ignore[valid-type]
        name="Decider field", description="Field of the layer that says who decided each "
        "constraint (empty: the decider written below)", options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decided that these constraints limit the design",
        options=_FIELD)
    date_field: StringProperty(  # type: ignore[valid-type]
        name="Date field", description="Field of the layer that gives the date of each "
        "decision, as YYYY-MM-DD (empty: the date written below)", options=_FIELD)
    decided_on: StringProperty(  # type: ignore[valid-type]
        name="Date", description="Date of the decision, as DD/MM/YYYY", options=_FIELD)
    priority: IntProperty(  # type: ignore[valid-type]
        name="Priority", description="Order of the constraints that cover the same cells: it "
        "only orders their causes, never lifts a prohibition", default=0, options=_FIELD)
    buffer_out: StringProperty(  # type: ignore[valid-type]
        name="Outward setback (m)", description="Distance in metres, outside the geometry, "
        "that the constraint also protects (empty: it is declared later)", options=_FIELD)
    buffer_in: StringProperty(  # type: ignore[valid-type]
        name="Inward setback (m)", description="Distance in metres, inside a legal limit, "
        "where cutting is not allowed (empty: it is declared later)", options=_FIELD)
    weight: StringProperty(  # type: ignore[valid-type]
        name="Weight", description="Weight of an area to avoid, 1 or more (empty: it is "
        "declared later)", options=_FIELD)
    active: BoolProperty(  # type: ignore[valid-type]
        name="Active", description="Whether the new constraints are in force", default=True,
        options=_FIELD)
    decision: StringProperty(  # type: ignore[valid-type]
        name="Decision of the owner", description="The decision of the owner that backs these "
        "constraints, one of those recorded in the project (empty: none)", options=_FIELD)

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _write_poll(cls)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        about = super().description(context, properties)
        note = scene_versions.not_editable_text()
        return about if note is None else with_note(about, note)

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Lee las capas de las que se pueden crear restricciones y las decisiones de la
        propiedad que se pueden elegir y abre el diálogo con la fecha de hoy; sin capas, dice
        cómo importarlas."""
        self.provenance_dialog = True
        project = SESSION.project
        try:
            constraint_panels.fill_constraints(project)
            constraint_panels.fill_decisions(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        view = constraint_panels.view()
        if view is None or not len(view.source_layers):
            self.report({"ERROR"}, tr(
                "The project has no layers to create constraints from: import them first with "
                "{path}, as Features", path=path_text(command_catalog(), constraint_panels
                                                      .IMPORT_VECTOR, i18n.language())))
            return {"CANCELLED"}
        if not self.layer:
            self.layer = view.source_layers[0].name
        if not self.decided_on:
            self.decided_on = dt.date.today().strftime(constraint_panels.DATE_FORMAT)
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=text(command_catalog().commands[CREATE_CONSTRAINTS].label),
            confirm_text=tr("Create"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        view = constraint_panels.view()
        if view is not None:
            layout.prop_search(self, "layer", view, "source_layers", text=tr("Layer"),
                               translate=False)
        layout.label(text=tr("Type"), translate=False)
        grid = layout.grid_flow(columns=2, align=True)
        for identifier, msgid, _about in CREATE_TYPE_ITEMS:
            grid.prop_enum(self, "ctype", identifier,
                           text=tr("From a field of the layer") if identifier == FIELD
                           else i18n.translate(i18n.language(), msgid), translate=False)
        if self.ctype == FIELD:
            layout.prop(self, "type_field", text=tr("Type field"), translate=False)
            layout.prop(self, "type_values", text=tr("Values of the type"), translate=False)
        layout.prop(self, "name_field", text=tr("Name field"), translate=False)
        layout.prop(self, "reason_field", text=tr("Reason field"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)
        layout.prop(self, "decider_field", text=tr("Decider field"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)
        layout.prop(self, "date_field", text=tr("Date field"), translate=False)
        layout.prop(self, "decided_on", text=tr("Date (DD/MM/YYYY)"), translate=False)
        layout.prop(self, "priority", text=tr("Priority"), translate=False)
        layout.prop(self, "buffer_out", text=tr("Outward setback (m)"), translate=False)
        layout.prop(self, "buffer_in", text=tr("Inward setback (m)"), translate=False)
        layout.prop(self, "weight", text=tr("Weight"), translate=False)
        layout.prop(self, "active", text=tr("Active"), translate=False)
        constraint_panels.draw_decision(layout, self, DIALOG_WIDTH)

    def execute(self, context: Any) -> set[str]:
        """Comprueba lo escrito y la puerta de la 008 (la capa es la entrada), crea las
        restricciones de la capa con ``core.edit_constraints`` (sin tocar la capa de origen),
        con los parámetros que pide su tipo y se declaran y la decisión de la propiedad que se
        elige (la misma para todas), y deja en la ventana el informe de las creadas y de las
        entidades rechazadas con su motivo (RF-012-01, RF-012-02)."""
        project = SESSION.project
        try:
            request = create_request(self, project)
        except ConstraintFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type,
                             [Use(request.layer, constraint_provenance.SOURCE_ROLE)],
                             report=self.report, dialog=self.provenance_dialog,
                             version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        from ...gis.masks import sources  # al usarlas: habilitar no carga las máscaras (T38)

        try:
            edited = sources.create_constraints(
                project, request.layer, request.mapping, params=request.declaration,
                default_name=_layer_label(request.layer), decision_uid=request.decision)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, constraint_provenance.EDIT_CONSTRAINTS)
        shown = i18n.language()
        lines = [constraint_panels.Line(tr(
            "Constraints created from «{layer}»: {created}; entities rejected: {rejected}",
            layer=request.layer, created=len(edited.constraints),
            rejected=len(edited.rejected)))]
        lines += [constraint_panels.Line(item.text(shown), alert=True)
                  for item in edited.rejected]
        _show_result(project, lines, self.report)
        return {"FINISHED"}


def _differs(row: Constraint, other: Constraint) -> bool:
    """Si ``other`` cambia algo de ``row`` que se guarda en su fila (no la geometría)."""
    return any(getattr(row, name) != getattr(other, name) for name in (
        "ctype", "name", "reason", "decided_by", "decided_on", "priority", "decision_uid"))


class GEOBLENDER_OT_core_complete_constraint(ProvenanceAwareOperator, bpy.types.Operator):
    """Complete or edit a constraint: its type, name, reason, decider, date and the setbacks it
    lacks (a constraint drawn in QGIS receives its code)"""

    bl_idname = COMPLETE_CONSTRAINT
    bl_label = "Complete…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = constraint_provenance.EDIT_CONSTRAINTS

    uid: StringProperty(  # type: ignore[valid-type]
        name="Constraint", options={"HIDDEN", "SKIP_SAVE"})
    ctype: EnumProperty(  # type: ignore[valid-type]
        name="Type", description="Type of the constraint", items=COMPLETE_TYPE_ITEMS,
        default=NO_TYPE, options=_FIELD)
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the constraint (a constraint without a code "
        "receives it from its name)", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the constraint limits the design", options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decided that the constraint limits the design",
        options=_FIELD)
    decided_on: StringProperty(  # type: ignore[valid-type]
        name="Date", description="Date of the decision, as DD/MM/YYYY", options=_FIELD)
    priority: IntProperty(  # type: ignore[valid-type]
        name="Priority", description="Order of the constraints that cover the same cells: it "
        "only orders their causes, never lifts a prohibition", default=0, options=_FIELD)
    buffer_out: StringProperty(  # type: ignore[valid-type]
        name="Outward setback (m)", description="Distance in metres, outside the geometry, "
        "that the constraint also protects (only if it does not have one yet)", options=_FIELD)
    buffer_in: StringProperty(  # type: ignore[valid-type]
        name="Inward setback (m)", description="Distance in metres, inside a legal limit, "
        "where cutting is not allowed (only if it does not have one yet)", options=_FIELD)
    weight: StringProperty(  # type: ignore[valid-type]
        name="Weight", description="Weight of an area to avoid, 1 or more (only if it does "
        "not have one yet)", options=_FIELD)
    active: BoolProperty(  # type: ignore[valid-type]
        name="Active", description="Whether the constraint is in force (only if it does not "
        "have it yet)", default=True, options=_FIELD)
    decision: StringProperty(  # type: ignore[valid-type]
        name="Decision of the owner", description="The decision of the owner that backs the "
        "constraint, one of those recorded in the project (empty: it stays as it is)",
        options=_FIELD)

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _write_poll(cls)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        about = super().description(context, properties)
        note = scene_versions.not_editable_text()
        return about if note is None else with_note(about, note)

    def _row(self, project: Any) -> Constraint:
        """La restricción de :attr:`uid` en el proyecto; ``ConstraintFormError`` si ya no
        está."""
        with project.read() as conn:
            found = [item for item in constraint_store.read_constraints(conn)
                     if item.uid == self.uid]
        if not found:
            raise ConstraintFormError(tr("The constraint is no longer in the project: open the "
                                         "list again"))
        return found[0]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo con lo que tiene la restricción (y, de sus parámetros, lo que ya vale
        en el proyecto: solo se dan de alta los que faltan) y las decisiones de la propiedad
        que se pueden elegir, con la suya si la tiene (T41)."""
        self.provenance_dialog = True
        project = SESSION.project
        try:
            row = self._row(project)
            constraint_panels.fill_decisions(project)
        except (ConstraintFormError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, str(exc) if isinstance(exc, ConstraintFormError)
                        else error_text(exc))
            return {"CANCELLED"}
        shown = i18n.language()
        view = constraint_panels.view()
        names = {} if view is None else {item.uid: item.name for item in view.mark_decisions}
        self.decision = names.get(row.decision_uid or "", "")
        self.ctype = NO_TYPE if row.ctype is None else row.ctype.name
        self.name = row.shown_name(shown) if row.name else ""
        self.reason = row.reason or ""
        self.decided_by = row.decided_by or project.session.user_host
        self.decided_on = (row.decided_on or dt.date.today()).strftime(
            constraint_panels.DATE_FORMAT)
        self.priority = int(row.priority)
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=text(command_catalog().commands[COMPLETE_CONSTRAINT].label),
            confirm_text=tr("Save"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.label(text=tr("Type"), translate=False)
        grid = layout.grid_flow(columns=2, align=True)
        for identifier, msgid, _about in COMPLETE_TYPE_ITEMS[1:]:
            grid.prop_enum(self, "ctype", identifier,
                           text=i18n.translate(i18n.language(), msgid), translate=False)
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)
        layout.prop(self, "decided_on", text=tr("Date (DD/MM/YYYY)"), translate=False)
        layout.prop(self, "priority", text=tr("Priority"), translate=False)
        layout.prop(self, "buffer_out", text=tr("Outward setback (m)"), translate=False)
        layout.prop(self, "buffer_in", text=tr("Inward setback (m)"), translate=False)
        layout.prop(self, "weight", text=tr("Weight"), translate=False)
        layout.prop(self, "active", text=tr("Active"), translate=False)
        constraint_panels.draw_decision(layout, self, DIALOG_WIDTH)

    def _updated(self, row: Constraint) -> Constraint:
        """``row`` con lo que se completa: lo escrito manda y lo vacío se queda como estaba (también
        la decisión de la propiedad, T41); :class:`ConstraintFormError` si no tiene tipo, un tipo
        que cabe en su geometría, nombre, motivo, decisor o fecha, o si la decisión no es una
        de las del proyecto."""
        if self.ctype == NO_TYPE and row.ctype is None:
            raise ConstraintFormError(tr("Choose the type of the constraint"))
        ctype = row.ctype if self.ctype == NO_TYPE else ConstraintType[self.ctype]
        assert ctype is not None
        if not ctype.accepts(row.kind):
            raise ConstraintFormError(tr(
                "A «{ctype}» cannot be {kind}: choose another type",
                ctype=ctype.label(i18n.language()),
                kind=i18n.translate(i18n.language(), GeometryKind(row.kind).article_msgid)))
        name = self.name.strip() or row.name
        reason = self.reason.strip() or row.reason or ""
        decided_by = self.decided_by.strip() or row.decided_by or ""
        if not name:
            raise ConstraintFormError(tr("Write the name of the constraint"))
        if not reason:
            raise ConstraintFormError(tr("Write the reason of the constraint"))
        if not decided_by:
            raise ConstraintFormError(tr("Write who decides the constraint"))
        typed_on = self.decided_on.strip()
        decided_on = _typed_date(typed_on) if typed_on else row.decided_on
        if decided_on is None:
            raise ConstraintFormError(tr("Write the date of the decision as DD/MM/YYYY"))
        decision_uid = _typed_decision(SESSION.project, self.decision) or row.decision_uid
        return replace(row, ctype=ctype, name=name, reason=reason, decided_by=decided_by,
                       decided_on=decided_on, priority=int(self.priority),
                       decision_uid=decision_uid)

    def _declaration(self, row: Constraint
                     ) -> constraint_provenance.ParamDeclaration:
        """Los parámetros que se declaran: los tecleados (y «activa»)."""
        values = _typed_declared(self.buffer_out, self.buffer_in, self.weight, self.active)
        decider = row.decided_by or SESSION.project.session.user_host
        return constraint_provenance.ParamDeclaration(
            values=values, source=decider, source_kind="person", decided_by=decider,
            reason=row.reason or tr("Completed in the list of constraints"))

    def execute(self, context: Any) -> set[str]:
        """Completa la restricción (RF-012-03, RF-012-04): una sin código (dibujada en QGIS)
        recibe el de su nombre y los parámetros que pide su tipo y se declaran; una con código
        guarda lo que cambió (tipo, nombre, motivo, decisor, fecha, prioridad) y da de alta los
        parámetros que su tipo pide y le faltan, sin tocar los que ya tiene (esos se cambian con
        su ámbito, ``core.set_parameter``). Todo es una ``core.edit_constraints``; si algo no
        vale, nada se escribe."""
        project = SESSION.project
        try:
            row = self._row(project)
            updated = self._updated(row)
            declaration = self._declaration(updated)
        except ConstraintFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog,
                             version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        store = core_params.ParameterStore(project)
        changed = _differs(row, updated)
        try:
            if changed or not row.code:
                edited = constraint_provenance.edit_constraints(
                    project, [updated], params=declaration if not row.code else None,
                    settings={"completed_by": declaration.decided_by},
                    srs_id=int(project.record.crs_epsg))
                updated = edited.constraints[0]
                undo_watch.record(UndoKind.OPERATION, constraint_provenance.EDIT_CONSTRAINTS)
            created = [] if not row.code else self._missing(project, store, updated,
                                                           declaration)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        for key in created:
            undo_watch.record(UndoKind.PARAMETER, key)  # Ctrl+Z no lo deshace
        if not (changed or not row.code or created):
            self.report({"INFO"}, tr("Nothing to change in «{name}»", name=updated.name))
            return {"CANCELLED"}
        lines = [constraint_panels.Line(tr("Constraint «{name}» saved with the code «{code}»",
                                           name=updated.name, code=updated.code))]
        _show_result(project, lines, self.report)
        return {"FINISHED"}

    def _missing(self, project: Any, store: core_params.ParameterStore, row: Constraint,
                 declaration: constraint_provenance.ParamDeclaration) -> list[str]:
        """Da de alta en el proyecto, en una transacción, los parámetros que pide el tipo de
        ``row`` (que tiene código), están declarados y todavía no existen; devuelve sus
        claves."""
        assert row.ctype is not None and is_code(row.code)
        created: list[str] = []
        with project.write_transaction() as conn:
            for param in row.ctype.requires:
                key = constraint_params.param_key(row.code, param)
                if param not in declaration.values or store.get(key, conn=conn) is not None:
                    continue
                store.create(conn, key, declaration.values[param],
                             kind=declaration.kind_of(param), source=declaration.source,
                             source_kind=declaration.source_kind,
                             decided_by=declaration.decided_by, reason=declaration.reason)
                created.append(key)
        return created


# --- Buscar elementos intocables por sector… (T24; HU-012-3; RF-012-07 a RF-012-10, RF-012-28) --

FIND_COMMAND = constraint_provenance.FIND_COMMAND
DECLARE_SECTORS = constraint_panels.DECLARE_SECTORS
SEARCH_UNTOUCHABLES = constraint_panels.SEARCH_UNTOUCHABLES
CONVERT_HIT = constraint_panels.CONVERT_HIT
DISCARD_HIT = constraint_panels.DISCARD_HIT
CLOSE_SEARCH = constraint_panels.CLOSE_SEARCH
_HIT_STATES = {HitDecision.CONVERTED: constraint_panels.CONVERTED,
               HitDecision.DISCARDED: constraint_panels.DISCARDED}


class SearchFormError(ConstraintFormError):
    """Lo que impide buscar, convertir, descartar o cerrar con lo escrito en la ventana de la
    búsqueda (ya en el idioma de Geoblender)."""


@dataclass(slots=True)
class OpenSearch:
    """La búsqueda abierta de esta sesión: hallada y sin cerrar (RF-012-08, RF-012-09). Lo
    hallado (``searched``: el sector con su huella, las capas con su hash, la distancia y las
    entidades), la versión en que se buscó (el perímetro como sector se lee en ella), la
    geometría y los títulos de los campos de cada capa consultada, el nombre con que se enseña
    cada entidad y la decisión que se lleva de cada una. Vive en memoria: se cierra con
    «Cerrar la búsqueda» (que la registra) y se pierde al cerrar el proyecto o desactivar
    Geoblender; lo convertido ya creó su restricción y queda aunque se pierda."""

    project: Any
    searched: mask_sectors.Searched
    version_uid: str | None
    kinds: dict[str, str]
    titles: dict[str, dict[str, str]]
    names: dict[tuple[str, int], str]
    decisions: dict[tuple[str, int], mask_sectors.Decision] = field(default_factory=dict)

    def converted(self) -> int:
        """Cuántas entidades convertidas lleva."""
        return sum(1 for item in self.decisions.values()
                   if item.decision is HitDecision.CONVERTED)

    def sector(self) -> str:
        """El sector buscado como se nombra (el perímetro de actuación, en el idioma de
        Geoblender)."""
        return constraint_panels.sector_name(self.searched.sector_code,
                                             self.searched.sector_name)


_OPEN: OpenSearch | None = None


def open_search() -> OpenSearch | None:
    """La búsqueda abierta de esta sesión, o ``None`` si no hay ninguna o es de otro proyecto
    (el proyecto se cerró o se cambió: se pierde)."""
    global _OPEN
    if _OPEN is not None and _OPEN.project is not SESSION.project:
        _OPEN = None
    return _OPEN


def drop_search() -> None:
    """Olvida la búsqueda abierta (la registrada o la que ya no vale)."""
    global _OPEN
    _OPEN = None


def _hit_name(found: Any) -> str:
    """Cómo se enseña una entidad hallada: el primer atributo de texto con algo escrito o, sin
    él, su capa y su número."""
    for value in found.attributes.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{constraint_panels.layer_label(str(found.layer))} {found.fid}"


def _hit_details(found: Any, titles: Mapping[str, str]) -> str:
    """Los atributos de una entidad hallada, uno por línea («nombre: Torre 14»)."""
    lines = []
    for column, value in found.attributes.items():
        shown = NOT_SHOWN if value is None or value == "" else str(value)
        lines.append(f"{titles.get(column, column)}: {shown}")
    return "\n".join(lines)


def _hit_lines(opened: OpenSearch) -> list[constraint_panels.HitLine]:
    lines = []
    for found in opened.searched.found:
        key = (str(found.layer), int(found.fid))
        decision = opened.decisions.get(key)
        lines.append(constraint_panels.HitLine(
            name=opened.names[key], layer=key[0], fid=key[1],
            kind=opened.kinds.get(key[0], "point"),
            distance=format_number(float(found.distance_m), 1),
            details=_hit_details(found, opened.titles.get(key[0], {})),
            state=constraint_panels.PENDING if decision is None else _HIT_STATES[
                decision.decision],
            reason="" if decision is None else decision.reason,
            constraint=(decision.constraint_code or "") if decision is not None else ""))
    return lines


def _title(opened: OpenSearch) -> str:
    """El título de lo hallado: el sector, cuántas entidades a ≤ qué distancia y cuántas
    siguen sin decidir."""
    undecided = len(opened.searched.found) - len(opened.decisions)
    return tr("Found in {sector}: {found} within {distance} m, {pending} without a decision",
              sector=opened.sector(), found=len(opened.searched.found),
              distance=constraint_panels.metres(opened.searched.distance_m), pending=undecided)


def _put_hits(opened: OpenSearch | None) -> None:
    """Deja en la ventana lo hallado por ``opened`` con las decisiones de ahora (o nada)."""
    if opened is None:
        constraint_panels.show_hits("", ())
        return
    constraint_panels.show_hits(_title(opened), _hit_lines(opened))


def _put_decision(opened: OpenSearch, key: tuple[str, int]) -> None:
    """Deja en la ventana la decisión nueva de la entidad ``key`` (su capa y su número) sin volver
    a llenar toda la lista (con miles de entidades hallados, cada decisión sería una llamada de
    más de 0,1 s; RNF-012-06)."""
    decision = opened.decisions[key]
    if not constraint_panels.update_hit(key[0], key[1], _HIT_STATES[decision.decision],
                                        decision.reason, decision.constraint_code or "",
                                        _title(opened)):
        _put_hits(opened)


def _find_hit(opened: OpenSearch, layer: str, fid: int) -> Any:
    """La entidad hallada de la capa ``layer`` y el número ``fid``; ``SearchFormError`` si no
    está entre las halladas."""
    for found in opened.searched.found:
        if str(found.layer) == layer and int(found.fid) == int(fid):
            return found
    raise SearchFormError(tr("The entity is not among the ones found: search again"))


def _undecided(opened: OpenSearch | None, layer: str, fid: int) -> tuple[OpenSearch, Any]:
    """La búsqueda abierta y la entidad ``layer``/``fid`` de ella, para decidir de nuevo
    o por primera vez: ``SearchFormError`` si no hay búsqueda abierta, la entidad no está entre
    las halladas o ya se convirtió (su restricción existe y no se deshace)."""
    if opened is None:
        raise SearchFormError(tr("There is no open search: search first"))
    found = _find_hit(opened, layer, fid)
    decision = opened.decisions.get((str(found.layer), int(found.fid)))
    if decision is not None and decision.decision is HitDecision.CONVERTED:
        raise SearchFormError(tr("The entity was already converted into «{code}»: it is not "
                                 "decided again", code=decision.constraint_code or ""))
    return opened, found


def _set_open(opened: OpenSearch | None) -> None:
    """Deja ``opened`` como la búsqueda abierta de la sesión."""
    global _OPEN
    _OPEN = opened


class _Writes:
    """El ``poll`` de lo que escribe: sin proyecto, en solo lectura o con la versión activa no
    editable, no está disponible y dice por qué (RF-012-28)."""

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _write_poll(cls)


class _WritesAware(_Writes):
    """Lo de :class:`_Writes` y, en una orden de :class:`ProvenanceAwareOperator`, su descripción
    con el porqué si la versión activa no es editable (RF-012-28, RF-009-21)."""

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        about = super().description(context, properties)  # type: ignore[misc]
        note = scene_versions.not_editable_text()
        return about if note is None else with_note(about, note)


class GEOBLENDER_OT_core_find_untouchables(_WritesAware, ProvenanceAwareOperator,
                                           bpy.types.Operator):
    """Mandatory search of the untouchable elements before designing"""

    bl_idname = FIND_COMMAND
    bl_label = "Find untouchable elements by sector…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = constraint_provenance.FIND_UNTOUCHABLES

    def execute(self, context: Any) -> set[str]:
        """Lee los sectores con el estado de su búsqueda, las capas que se pueden consultar y la
        distancia de búsqueda, enseña la búsqueda abierta (si la hay) y abre su ventana; desde
        un guion sin ventana, solo la vista."""
        try:
            constraint_panels.fill_search(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        _put_hits(open_search())
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(constraint_panels.SEARCH_PANEL)


def _declared_lines(declared: Any, perimeter: bool) -> list[constraint_panels.Line]:
    """El informe de declarar los sectores (RF-012-07, D-3)."""
    if perimeter:
        return [constraint_panels.Line(tr("No sectors are declared: the action perimeter is the "
                                          "only sector"))]
    if declared.uncovered_m2 is None:
        return [constraint_panels.Line(tr("Sectors declared: {count}",
                                          count=len(declared.sectors)))]
    return [constraint_panels.Line(tr(
        "Sectors declared: {count}; area of the perimeter without a sector: {area} m²",
        count=len(declared.sectors), area=format_number(declared.uncovered_m2, 0)))]


class GEOBLENDER_OT_core_declare_sectors(_WritesAware, ProvenanceAwareOperator,
                                         bpy.types.Operator):
    """Declare the search sectors from a layer of polygons of the project and the field that
    names them, or use the action perimeter as the only sector"""

    bl_idname = DECLARE_SECTORS
    bl_label = "Declare the sectors"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = constraint_provenance.DECLARE_SECTORS

    perimeter: BoolProperty(  # type: ignore[valid-type]
        name="Action perimeter", description="Declare no sectors: the action perimeter is the "
        "only sector", default=False, options=_HIDDEN)

    def execute(self, context: Any) -> set[str]:
        """Declara los sectores de la capa de polígonos y el campo de la ventana (o ninguno:
        «Usar el perímetro»), con ``core.declare_sectors`` (la capa es su entrada); dice cuántos y
        el área del perímetro que no cubre ningún sector (RF-012-07); una capa que no sirve se
        rechaza sin escribir nada. Una búsqueda abierta de un sector que ya no es el mismo se
        olvida."""
        view = constraint_panels.view()
        project = SESSION.project
        layer = field_name = None
        if not self.perimeter:
            layer, field_name = view.sector_layer.strip(), view.sector_field.strip()
            if not layer:
                self.report({"ERROR"}, tr("Choose the layer of polygons that gives the sectors"))
                return {"CANCELLED"}
            if not field_name:
                self.report({"ERROR"}, tr("Write the field of that layer that names each "
                                          "sector"))
                return {"CANCELLED"}
        version = scene_versions.active_version()
        inputs = [] if layer is None else [Use(layer, constraint_provenance.SOURCE_ROLE)]
        ready = ensure_ready(self.provenance_op_type, inputs, report=self.report,
                             dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...gis.masks import sectors as mask_sectors  # al usarlo: habilitar no lo carga (T38)

        try:
            declared = mask_sectors.declare_sectors(project, layer, field_name, version=version)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, constraint_provenance.DECLARE_SECTORS)
        lines = _declared_lines(declared, self.perimeter)
        try:
            constraint_panels.fill_search(project)
            self._forget_outdated(project, version, lines)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.warning("No se pudo volver a leer los sectores", exc_info=True)
        constraint_panels.show_search_report(lines)
        for line in lines:
            self.report({"WARNING" if line.alert else "INFO"}, line.text)
        return {"FINISHED"}

    @staticmethod
    def _forget_outdated(project: Any, version: str | None,
                         lines: list[constraint_panels.Line]) -> None:
        """Olvida la búsqueda abierta si su sector ya no existe o es otro (otra huella): ya no se
        podría cerrar. Lo convertido queda (su restricción ya existe); lo dice."""
        opened = open_search()
        if opened is None:
            return
        from ...gis.masks import access as mask_access  # al usarlo: habilitar no lo carga (T38)

        states = mask_access.sector_states(project, version)
        same = any(state.code == opened.searched.sector_code
                   and state.sha256 == opened.searched.sector_sha256 for state in states)
        if same:
            return
        drop_search()
        _put_hits(None)
        lines.append(constraint_panels.Line(tr(
            "The open search of «{sector}» was dropped: its sector changed. What was converted "
            "stays in the project", sector=opened.sector()), alert=True))


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Lo que pide la ventana para buscar, ya comprobado: el sector (código y nombre) y las capas
    (nombres de datos ``gis_fea_``, de 1 a 10)."""

    code: str
    name: str
    layers: tuple[str, ...]


def search_request(view: Any) -> SearchRequest:
    """El sector elegido y las capas marcadas de la ventana de la búsqueda, sin leer ni escribir
    nada. :class:`SearchFormError` si no hay sector elegido o las capas no son de 1 a 10."""
    if not 0 <= view.sector_index < len(view.sectors):
        raise SearchFormError(tr("Choose the sector to search"))
    sector = view.sectors[view.sector_index]
    layers = tuple(item.name for item in view.search_layers if item.use)
    if not 1 <= len(layers) <= constraint_provenance.MAX_LAYERS:
        raise SearchFormError(tr("Choose the layers to consult: from 1 to {max}",
                                 max=constraint_provenance.MAX_LAYERS))
    return SearchRequest(sector.code, sector.name, layers)


def _drain_search(operator: Any, steps: Any) -> Any:
    """Los pasos de la búsqueda de una vez (desde un guion): el resultado del último o, si
    fallan, ``None`` (ya dicho; no dejan nada a medias)."""
    found = None
    try:
        for step in steps:
            if step.result is not None:
                found = step.result
    except GeoblenderError as exc:
        operator._report({"ERROR"}, error_text(exc))
        return None
    except (sqlite3.Error, OSError, ValueError) as exc:
        LOGGER.error("«%s» se ha parado", command_idname(operator.bl_idname), exc_info=exc)
        operator._report({"ERROR"}, error_text(exc))
        return None
    if found is None:  # pragma: no cover - los pasos acaban siempre con su resultado
        operator._report({"ERROR"}, tr("The operation did not finish with its result"))
    return found


class GEOBLENDER_OT_core_search_untouchables(_Writes, _StepsModal, bpy.types.Operator):
    """Search the untouchable elements within the search distance of the chosen sector, in the
    chosen layers, in steps"""

    bl_idname = SEARCH_UNTOUCHABLES
    bl_label = "Search"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    STEP_BUDGET_S = 0.05  # cada evento del temporizador (RNF-012-06: ninguna llamada de > 0,2 s)

    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Desde la interfaz, por pasos con el avance y Esc."""
        self.in_steps = getattr(context, "window", None) is not None
        return self.execute(context)

    def execute(self, context: Any) -> set[str]:
        """Busca en el sector y las capas de la ventana las entidades a ≤ la distancia de
        búsqueda (RF-012-08): por pasos desde la interfaz, de una vez desde un guion. Solo lee.
        No busca en otro sector mientras la búsqueda abierta lleve algo convertido: se perdería
        su constancia."""
        from ...gis.masks import sectors as mask_sectors  # al usarlo: habilitar no lo carga (T38)

        project = SESSION.project
        try:
            request = search_request(constraint_panels.view())
            opened = open_search()
            if opened is not None and opened.searched.sector_code != request.code \
                    and opened.converted():
                raise SearchFormError(tr(
                    "Close the search of «{sector}» first: it has converted entities",
                    sector=opened.sector()))
            version = scene_versions.active_version()
            sources_found = gis_store.feature_sources(project, request.layers)
            steps = mask_sectors.search_steps(project, request.code, request.layers,
                                              version=version, budget_s=self.STEP_BUDGET_S)
        except SearchFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self._project = project
        self._request = request
        self._version = version
        self._sources = {item.name: item for item in sources_found}
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, steps)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        searched = _drain_search(self, steps)
        if searched is None:
            return {"CANCELLED"}
        return self._finished(searched)

    def _shown_sector(self) -> str:
        request = self._request
        return constraint_panels.sector_name(request.code, request.name)

    def _finished(self, searched: mask_sectors.Searched) -> set[str]:
        """Deja la búsqueda abierta, con las decisiones de la anterior del mismo sector que
        siguen hallándose, y enseña lo hallado en la ventana y en el informe de Blender."""
        previous = open_search()
        titles = {name: {column.column: column.field for column in source.columns}
                  for name, source in self._sources.items()}
        kinds = {name: source.kind for name, source in self._sources.items()}
        names = {(str(found.layer), int(found.fid)): _hit_name(found)
                 for found in searched.found}
        opened = OpenSearch(self._project, searched, self._version, kinds, titles, names)
        lost = 0
        if previous is not None and previous.searched.sector_code == searched.sector_code:
            for key, decision in previous.decisions.items():
                if key in names:
                    opened.decisions[key] = decision
                elif decision.decision is HitDecision.CONVERTED:
                    lost += 1
        _set_open(opened)
        _put_hits(opened)
        lines = [constraint_panels.Line(tr(
            "Search in «{sector}» (layers: {layers}; up to {distance} m): entities found: "
            "{found}", sector=self._shown_sector(),
            layers=", ".join(constraint_panels.layer_label(name) for name in searched.layers),
            distance=constraint_panels.metres(searched.distance_m),
            found=len(searched.found)))]
        if lost:
            lines.append(constraint_panels.Line(tr(
                "{count} entities converted before are no longer found: their constraints stay "
                "in the project", count=lost), alert=True))
        constraint_panels.show_search_report(lines)
        for line in lines:  # lo hallado, en la lista de la ventana (pueden ser miles)
            self._report({"WARNING" if line.alert else "INFO"}, line.text)
        return {"FINISHED"}

    # --- En pasos (_StepsModal) ---------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Searching in «{sector}»… {percent} % · Esc: cancel",
                  sector=self._shown_sector(), percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Search cancelled: nothing has been left half-done")

    def _error_text(self, exc: GeoblenderError) -> str:
        return error_text(exc)

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        if step.result is None:
            if project_session.current() is not getattr(self, "_project", None):
                return self._fail(context, tr(
                    "The project was closed while the search was running: nothing has been "
                    "left half-done"))
            return None
        self._done(context)
        finished = self._finished(step.result)
        if not bpy.app.background:  # la ventana con lo hallado (en blender -b, call_panel cierra)
            try:
                _call_panel(constraint_panels.SEARCH_PANEL)
            except RuntimeError:
                LOGGER.warning("No se pudo reabrir la ventana de la búsqueda", exc_info=True)
        return finished

    def modal(self, context: Any, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except (sqlite3.Error, OSError, ValueError) as exc:  # los pasos cerrados no dejan nada
            LOGGER.error("«%s» se ha parado", command_idname(self.bl_idname), exc_info=exc)
            return self._fail(context, error_text(exc))


def _metres_text(value: float) -> str:
    """Un resguardo en metros como se dice («8», «2,5»)."""
    return constraint_panels.metres(value)


class GEOBLENDER_OT_core_convert_hit(_WritesAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Create an untouchable constraint from the entity found, with its setback and its reason"""

    bl_idname = CONVERT_HIT
    bl_label = "Convert into untouchable…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = constraint_provenance.EDIT_CONSTRAINTS

    layer: StringProperty(  # type: ignore[valid-type]
        name="Layer", description="Layer of the project the entity found belongs to",
        options=_HIDDEN)
    fid: IntProperty(  # type: ignore[valid-type]
        name="Entity", description="Number of the entity found in its layer", options=_HIDDEN)
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the untouchable (empty: the name of the entity)",
        options=_FIELD)
    buffer_out: StringProperty(  # type: ignore[valid-type]
        name="Outward setback (m)", description="Distance in metres, outside the entity, that "
        "the untouchable also protects (more than 0 for a point or a line)", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the entity is an untouchable", options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decides that the entity is an untouchable",
        options=_FIELD)

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo con el nombre de la entidad y quien cierra la búsqueda como decisor."""
        self.provenance_dialog = True
        try:
            opened, found = _undecided(open_search(), self.layer, self.fid)
        except SearchFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        view = constraint_panels.view()
        self.name = opened.names[(str(found.layer), int(found.fid))]
        self.decided_by = (view.search_decided_by if view is not None else "").strip() \
            or SESSION.project.session.user_host
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=text(command_catalog().commands[CONVERT_HIT].label),
            confirm_text=tr("Convert"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        opened = open_search()
        if opened is not None:
            try:
                found = _find_hit(opened, self.layer, self.fid)
            except SearchFormError:
                found = None
            if found is not None:
                layout.label(text=tr("{name} · {layer} · {distance} m",
                                     name=opened.names[(str(found.layer), int(found.fid))],
                                     layer=constraint_panels.layer_label(str(found.layer)),
                                     distance=format_number(float(found.distance_m), 1)),
                             translate=False)
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "buffer_out", text=tr("Outward setback (m)"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)

    def _buffer(self, kind: str) -> float:
        """El resguardo hacia fuera escrito (m): obligatorio, y más de 0 en un punto o una
        línea (RF-012-04: sin él no ocupan nada)."""
        typed = _typed_metres(self.buffer_out, ConstraintParam.BUFFER_OUT, tr(
            "Write the outward setback in metres (0 or more): «{value}» does not fit",
            value="{value}"))
        if typed is None:
            raise SearchFormError(tr("Write the outward setback of the untouchable in metres"))
        if typed <= 0.0 and kind != GeometryKind.POLYGON.value:
            raise SearchFormError(tr("Write the outward setback in metres: an untouchable that "
                                     "is a point or a line needs more than 0"))
        return typed

    def execute(self, context: Any) -> set[str]:
        """Crea el intocable de la entidad (``core.edit_constraints`` con la capa como entrada,
        solo de esa entidad): su geometría tal cual, su origen, su motivo, su decisor, hoy como
        fecha y su resguardo como parámetro del proyecto; lo anota como convertido (RF-012-08).
        Si algo no vale, nada se escribe."""
        project = SESSION.project
        try:
            opened, found = _undecided(open_search(), self.layer, self.fid)
            kind = opened.kinds.get(str(found.layer), "point")
            reason, decider = self.reason.strip(), self.decided_by.strip()
            if not reason:
                raise SearchFormError(tr("Write the reason why the entity is an untouchable"))
            if not decider:
                raise SearchFormError(tr("Write who decides that the entity is an untouchable"))
            buffer_m = self._buffer(kind)
        except ConstraintFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        name = self.name.strip() or opened.names[(str(found.layer), int(found.fid))]
        layer = str(found.layer)
        ready = ensure_ready(self.provenance_op_type,
                             [Use(layer, constraint_provenance.SOURCE_ROLE)],
                             report=self.report, dialog=self.provenance_dialog,
                             version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        mapping = constraint_provenance.LayerMapping(
            ctype=ConstraintType.UNTOUCHABLE, reason=reason, decided_by=decider,
            decided_on=dt.date.today())
        declaration = constraint_provenance.ParamDeclaration(
            values={ConstraintParam.BUFFER_OUT: buffer_m, ConstraintParam.ACTIVE: True},
            source=layer, source_kind="document", decided_by=decider, reason=reason)
        from ...gis.masks import sectors as mask_sectors  # al usarlas: habilitar no las carga (T38)
        from ...gis.masks import sources

        try:
            edited = sources.create_from_entity(project, layer, int(found.fid), mapping,
                                                params=declaration, default_name=name)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, constraint_provenance.EDIT_CONSTRAINTS)
        made = edited.constraints[0]
        opened.decisions[(layer, int(found.fid))] = mask_sectors.Decision(
            layer, int(found.fid), HitDecision.CONVERTED, reason, made.code)
        _put_decision(opened, (layer, int(found.fid)))
        lines = [constraint_panels.Line(tr(
            "Entity converted: «{name}» is now an untouchable with {buffer} m of setback",
            name=made.name, buffer=_metres_text(buffer_m)))]
        constraint_panels.show_search_report(lines)
        self.report({"INFO"}, lines[0].text)
        return {"FINISHED"}


class GEOBLENDER_OT_core_discard_hit(_Writes, bpy.types.Operator):
    """Discard the entity found with a reason: it stays in the record of the search"""

    bl_idname = DISCARD_HIT
    bl_label = "Discard…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    layer: StringProperty(  # type: ignore[valid-type]
        name="Layer", description="Layer of the project the entity found belongs to",
        options=_HIDDEN)
    fid: IntProperty(  # type: ignore[valid-type]
        name="Entity", description="Number of the entity found in its layer", options=_HIDDEN)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the entity does not limit the design", options=_FIELD)

    def invoke(self, context: Any, event: Any) -> set[str]:
        try:
            _undecided(open_search(), self.layer, self.fid)
        except SearchFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=text(command_catalog().commands[DISCARD_HIT].label),
            confirm_text=tr("Discard"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Descarta la entidad con su motivo (RF-012-08): queda anotada en la constancia de la
        búsqueda al cerrarla. Sin motivo, se rechaza."""
        try:
            opened, found = _undecided(open_search(), self.layer, self.fid)
            reason = self.reason.strip()
            if not reason:
                raise SearchFormError(tr("Write the reason why the entity is discarded"))
        except SearchFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        from ...gis.masks import sectors as mask_sectors  # al usarlo: habilitar no lo carga (T38)

        key = (str(found.layer), int(found.fid))
        opened.decisions[key] = mask_sectors.Decision(key[0], key[1], HitDecision.DISCARDED,
                                                      reason)
        _put_decision(opened, key)
        line = constraint_panels.Line(tr("Entity discarded: «{name}»", name=opened.names[key]))
        constraint_panels.show_search_report([line])
        self.report({"INFO"}, line.text)
        return {"FINISHED"}


class GEOBLENDER_OT_core_close_search(_WritesAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Record the search of the sector as in force, with what was found, converted and
    discarded, who closed it and when"""

    bl_idname = CLOSE_SEARCH
    bl_label = "Close the search"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = constraint_provenance.FIND_UNTOUCHABLES

    def execute(self, context: Any) -> set[str]:
        """Cierra la búsqueda abierta (RF-012-09): la registra (``core.find_untouchables``) con
        el sector y su huella, las capas con su hash, lo hallado con su decisión y su motivo,
        quién la cierra y cuándo. Se rechaza, sin registrar nada, si algo queda sin decidir o el
        sector o una capa cambió después de buscar. El sector queda con la búsqueda vigente."""
        project = SESSION.project
        opened = open_search()
        if opened is None:
            self.report({"ERROR"}, tr("There is no open search: search first"))
            return {"CANCELLED"}
        view = constraint_panels.view()
        closer = view.search_decided_by.strip()
        if not closer:
            self.report({"ERROR"}, tr("Write who closes the search"))
            return {"CANCELLED"}
        searched = opened.searched
        inputs = [Use(searched.sector_dataset, constraint_provenance.SECTOR_ROLE),
                  *(Use(name, constraint_provenance.layer_role(index))
                    for index, name in enumerate(searched.layers, start=1))]
        ready = ensure_ready(self.provenance_op_type, inputs, report=self.report,
                             dialog=self.provenance_dialog,
                             version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        from ...gis.masks import sectors as mask_sectors  # al usarlo: habilitar no lo carga (T38)

        try:
            mask_sectors.close_search(project, searched, list(opened.decisions.values()),
                                      closed_by=closer, version=opened.version_uid)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, constraint_provenance.FIND_UNTOUCHABLES)
        drop_search()
        _put_hits(None)
        converted = sum(1 for item in opened.decisions.values()
                        if item.decision is HitDecision.CONVERTED)
        lines = [constraint_panels.Line(tr(
            "Search of «{sector}» closed (found: {found}, converted: {converted}, discarded: "
            "{discarded})", sector=opened.sector(), found=len(searched.found),
            converted=converted, discarded=len(searched.found) - converted))]
        try:
            constraint_panels.fill_search(project)
            pending = [item.name for item in view.sectors if not item.current]
            if pending:
                lines.append(constraint_panels.Line(tr(
                    "Search for untouchable elements pending in: {names}",
                    names="; ".join(pending)), alert=True))
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.warning("No se pudo volver a leer los sectores", exc_info=True)
        constraint_panels.show_search_report(lines)
        for line in lines:
            self.report({"WARNING" if line.alert else "INFO"}, line.text)
        return {"FINISHED"}


# --- Intenciones del cliente… (T25; HU-012-6; RF-012-26, RF-012-27, RF-012-28) -------------------

EDIT_MARKS = constraint_provenance.INTENTIONS_COMMAND
SAVE_MARKS = constraint_panels.SAVE_MARKS
CONVERT_INTENTION = constraint_panels.CONVERT_INTENTION


class MarksFormError(ConstraintFormError):
    """Lo que impide guardar las marcas del cliente con lo escrito en la ventana (ya en el
    idioma de Geoblender)."""


@dataclass(frozen=True, slots=True)
class MarksRequest:
    """Lo que pide el formulario de las marcas ya comprobado: la capa «entidades», la entrada del
    documento de origen, la decisión enlazada (si la hay), cómo se leen las marcas de la capa y el
    nombre que toman las que no tienen campo del nombre (RF-012-26)."""

    layer: str
    document: str
    decision: str | None
    mapping: constraint_provenance.IntentionMapping
    default_name: str


def _typed_roles(typed: str) -> dict[str, IntentionRole] | None:
    """La correspondencia de los valores del campo del papel tecleada («valor = papel; valor =
    papel»; cada papel por su código, su nombre en español o en inglés); vacía, ``None`` (la de
    por defecto: los papeles por su nombre)."""
    shown = typed.strip()
    if not shown:
        return None
    known = constraint_provenance.default_role_values()
    found: dict[str, IntentionRole] = {}
    for pair in (part for part in shown.split(";") if part.strip()):
        value, _, kind = pair.partition("=")
        role = known.get(kind.strip().casefold())
        if not value.strip() or role is None:
            raise MarksFormError(tr(
                "«{value}» is not «value = role»: write the role by its name, as in «Pond = "
                "Protect; Dump = Fill»", value=pair.strip()))
        found[value.strip()] = role
    return found


def _typed_elevation(typed: str) -> float | None:
    """La cota tecleada en metros (float64, finita; «612,5», «612.5 m»); vacía, ``None``."""
    shown = typed.strip()
    if not shown:
        return None
    message = tr("Write the elevation in metres: «{value}» is not a number", value=shown)
    try:
        number, unit = parse_quantity(shown)
        value = float(convert(number, unit or _METRE, _METRE))
    except (GeoblenderError, ValueError):
        raise MarksFormError(message) from None
    if not math.isfinite(value):
        raise MarksFormError(message)
    return value


def marks_request(form: Any) -> MarksRequest:
    """Lo que pide el formulario de las marcas (``form``: ``WindowManager.geoblender_constraints``)
    comprobado, sin leer ni escribir nada. :class:`MarksFormError` si no se eligió una capa del
    proyecto, falta el campo del papel, la correspondencia no se lee, la cota se da de un campo y
    de un valor a la vez o no es un número, falta la fecha o no lo es, falta el documento o no es
    uno de los registrados, o la decisión no es una de las registradas (RF-012-26)."""
    layer = form.mark_layer.strip()
    if not layer:
        raise MarksFormError(tr("Choose the layer the marks of the client come from"))
    if layer not in {item.name for item in form.mark_layers}:
        raise MarksFormError(tr(
            "«{layer}» is not a layer of features of the project: import it first as Features",
            layer=layer))
    role: IntentionRole | None = None
    role_field: str | None = None
    values: dict[str, IntentionRole] | None = None
    if form.mark_role == MARK_FIELD:
        role_field = form.mark_role_field.strip()
        if not role_field:
            raise MarksFormError(tr(
                "Write the role field: the field of the layer that says the role of each mark, "
                "or choose a role for all of them"))
        values = _typed_roles(form.mark_role_values)
    else:
        role = IntentionRole[form.mark_role]
    elevation_field = form.mark_elevation_field.strip() or None
    elevation = _typed_elevation(form.mark_elevation)
    if elevation_field is not None and elevation is not None:
        raise MarksFormError(tr("Write the elevation as a field of the layer or as a value for "
                                "all the marks, not both"))
    date_field = form.mark_date_field.strip() or None
    stated_on = None
    if date_field is None:
        typed = form.mark_date.strip()
        if not typed:
            raise MarksFormError(tr("Write the date of the marks as DD/MM/YYYY, or the field of "
                                    "the layer that gives it"))
        stated_on = _typed_date(typed)
    document = form.mark_document.strip()
    if not document:
        raise MarksFormError(tr("Choose the document the marks come from"))
    document_uid = next((item.uid for item in form.mark_documents if item.name == document),
                        None)
    if document_uid is None:
        raise MarksFormError(tr(
            "«{value}» is not a document registered as an input of the project", value=document))
    decision = form.mark_decision.strip()
    decision_uid = None
    if decision:
        decision_uid = next((item.uid for item in form.mark_decisions if item.name == decision),
                            None)
        if decision_uid is None:
            raise MarksFormError(tr("«{value}» is not a decision registered in the project",
                                    value=decision))
    mapping = constraint_provenance.IntentionMapping(
        role=role, role_field=role_field, role_values=values,
        name_field=form.mark_name_field.strip() or None, elevation_field=elevation_field,
        elevation_m=elevation, date_field=date_field, stated_on=stated_on)
    return MarksRequest(layer, document_uid, decision_uid, mapping,
                        constraint_panels.layer_label(layer))


class GEOBLENDER_OT_core_edit_client_marks(_WritesAware, ProvenanceAwareOperator,
                                           bpy.types.Operator):
    """Layers of the client with their role; they never become limits on their own"""

    bl_idname = EDIT_MARKS
    bl_label = "Client intentions…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = constraint_provenance.EDIT_INTENTIONS

    def execute(self, context: Any) -> set[str]:
        """Lee las intenciones guardadas, las capas «entidades», los documentos y las decisiones
        del proyecto y abre su ventana; desde un guion sin ventana, solo la vista."""
        try:
            constraint_panels.fill_intentions(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(constraint_panels.MARKS_PANEL)


class GEOBLENDER_OT_core_save_client_marks(_WritesAware, ProvenanceAwareOperator,
                                           bpy.types.Operator):
    """Save the entities of a layer of the project as client intentions, with their role, date,
    document and decision: they never enter a mask"""

    bl_idname = SAVE_MARKS
    bl_label = "Save the marks"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = constraint_provenance.EDIT_INTENTIONS

    def execute(self, context: Any) -> set[str]:
        """Guarda las marcas de la capa de la ventana como intenciones (``core.edit_intentions``,
        con la capa y el documento como entradas): su papel, su cota, su fecha, su documento y su
        decisión, y deja el informe de las guardadas y de las rechazadas con su motivo
        (RF-012-26). Lo que no vale se rechaza sin escribir nada; ninguna máscara cambia."""
        project = SESSION.project
        try:
            request = marks_request(constraint_panels.view())
        except ConstraintFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        ready = ensure_ready(
            self.provenance_op_type,
            [Use(request.layer, constraint_provenance.SOURCE_ROLE),
             Use(request.document, constraint_provenance.DOCUMENT_ROLE, kind=ItemKind.INPUT)],
            report=self.report, dialog=self.provenance_dialog,
            version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        from ...gis.masks import sources  # al usarlo: habilitar no lo carga (T38)

        try:
            edited = sources.create_intentions(
                project, request.layer, request.mapping, document=request.document,
                decision_uid=request.decision, default_name=request.default_name)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, constraint_provenance.EDIT_INTENTIONS)
        shown = i18n.language()
        lines = [constraint_panels.Line(tr(
            "Client intentions saved from «{layer}»: {saved}; entities rejected: {rejected}",
            layer=request.default_name, saved=len(edited.intentions),
            rejected=len(edited.rejected)))]
        lines += [constraint_panels.Line(item.text(shown), alert=True)
                  for item in edited.rejected]
        _show_marks_result(project, lines, self.report)
        return {"FINISHED"}


def _show_marks_result(project: Any, lines: list[constraint_panels.Line], report: Any) -> None:
    """Deja ``lines`` como el último resultado de la ventana de las intenciones y lo dice con
    ``report`` (los de alerta, como aviso); vuelve a leer la lista. Un fallo al leer queda en el
    registro."""
    try:
        constraint_panels.fill_intentions(project)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.warning("No se pudo volver a leer la lista de intenciones", exc_info=True)
    constraint_panels.show_marks_report(lines)
    for line in lines:
        report({"WARNING" if line.alert else "INFO"}, line.text)


class GEOBLENDER_OT_core_convert_intention(_WritesAware, ProvenanceAwareOperator,
                                           bpy.types.Operator):
    """Create a constraint from a client intention, with the type, reason and decider that are
    declared: the intention does not change"""

    bl_idname = CONVERT_INTENTION
    bl_label = "Convert into constraint…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = constraint_provenance.EDIT_CONSTRAINTS

    uid: StringProperty(  # type: ignore[valid-type]
        name="Intention", description="The client intention that becomes a constraint",
        options=_HIDDEN)
    ctype: EnumProperty(  # type: ignore[valid-type]
        name="Type", description="Type of the constraint", items=COMPLETE_TYPE_ITEMS,
        default=NO_TYPE, options=_FIELD)
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the constraint (empty: the name of the intention)",
        options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the constraint limits the design", options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decided that the constraint limits the design",
        options=_FIELD)
    decided_on: StringProperty(  # type: ignore[valid-type]
        name="Date", description="Date of the decision, as DD/MM/YYYY", options=_FIELD)
    priority: IntProperty(  # type: ignore[valid-type]
        name="Priority", description="Order of the constraints that cover the same cells: it "
        "only orders their causes, never lifts a prohibition", default=0, options=_FIELD)
    buffer_out: StringProperty(  # type: ignore[valid-type]
        name="Outward setback (m)", description="Distance in metres, outside the geometry, "
        "that the constraint also protects (empty: it is declared later)", options=_FIELD)
    buffer_in: StringProperty(  # type: ignore[valid-type]
        name="Inward setback (m)", description="Distance in metres, inside a legal limit, "
        "where cutting is not allowed (empty: it is declared later)", options=_FIELD)
    weight: StringProperty(  # type: ignore[valid-type]
        name="Weight", description="Weight of an area to avoid, 1 or more (empty: it is "
        "declared later)", options=_FIELD)
    active: BoolProperty(  # type: ignore[valid-type]
        name="Active", description="Whether the new constraint is in force", default=True,
        options=_FIELD)

    def _entry(self, project: Any) -> constraint_store.ListedIntention:
        """La intención de :attr:`uid` en el proyecto; :class:`ConstraintFormError` si ya no
        está."""
        with project.read() as conn:
            found = [item for item in constraint_store.listed_intentions(conn)
                     if item.intention.uid == self.uid]
        if not found:
            raise ConstraintFormError(tr("The intention is no longer in the project: open the "
                                         "window again"))
        return found[0]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo con el nombre de la intención, la persona de la sesión como decisor y
        hoy como fecha; nada cambia hasta aceptarlo."""
        self.provenance_dialog = True
        project = SESSION.project
        try:
            entry = self._entry(project)
        except ConstraintFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self.ctype = NO_TYPE
        self.name = entry.intention.name
        self.decided_by = project.session.user_host
        self.decided_on = dt.date.today().strftime(constraint_panels.DATE_FORMAT)
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=text(command_catalog().commands[CONVERT_INTENTION].label),
            confirm_text=tr("Convert"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        view = constraint_panels.view()
        shown = None if view is None else next(
            (item for item in view.intentions if item.uid == self.uid), None)
        kind = None if shown is None else GeometryKind(shown.kind)
        if shown is not None:
            layout.label(text=tr("{name} · {role} · {kind}", name=shown.name,
                                 role=constraint_panels.role_text(shown.role),
                                 kind=kind.label(i18n.language())), translate=False)
        layout.label(text=tr("Type"), translate=False)
        grid = layout.grid_flow(columns=2, align=True)
        for identifier, msgid, _about in COMPLETE_TYPE_ITEMS[1:]:
            if kind is not None and not ConstraintType[identifier].accepts(kind):
                continue  # un tipo que no cabe en su geometría no se ofrece
            grid.prop_enum(self, "ctype", identifier,
                           text=i18n.translate(i18n.language(), msgid), translate=False)
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)
        layout.prop(self, "decided_on", text=tr("Date (DD/MM/YYYY)"), translate=False)
        layout.prop(self, "priority", text=tr("Priority"), translate=False)
        layout.prop(self, "buffer_out", text=tr("Outward setback (m)"), translate=False)
        layout.prop(self, "buffer_in", text=tr("Inward setback (m)"), translate=False)
        layout.prop(self, "weight", text=tr("Weight"), translate=False)
        layout.prop(self, "active", text=tr("Active"), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Convierte la intención en una restricción (``core.edit_constraints`` con
        ``core_intention`` como entrada): su geometría y su origen, el tipo, el motivo, el decisor
        y la fecha que se declaran, su nombre (el de la intención si no se escribe otro) y los
        parámetros que se escriben (RF-012-27). La intención no cambia ni se borra; si algo no
        vale, nada se escribe. Las máscaras pasan a obsoletas: compilarlas las rehace."""
        project = SESSION.project
        try:
            entry = self._entry(project)
            if self.ctype == NO_TYPE:
                raise ConstraintFormError(tr("Choose the type of the constraint"))
            ctype = ConstraintType[self.ctype]
            reason, decider = self.reason.strip(), self.decided_by.strip()
            if not reason:
                raise ConstraintFormError(tr("Write the reason of the constraint"))
            if not decider:
                raise ConstraintFormError(tr("Write who decides the constraint"))
            decided_on = _typed_date(self.decided_on)
            values = _typed_declared(self.buffer_out, self.buffer_in, self.weight, self.active)
        except ConstraintFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(
            self.provenance_op_type,
            [Use(constraint_store.INTENTION_TABLE, constraint_provenance.INTENTION_ROLE)],
            report=self.report, dialog=self.provenance_dialog,
            version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        source = entry.document or decider
        declaration = constraint_provenance.ParamDeclaration(
            values=values, source=source, source_kind="document" if entry.document else "person",
            decided_by=decider, reason=reason)
        try:
            edited = constraint_provenance.convert_intention(
                project, entry.intention, ctype=ctype, reason=reason, decided_by=decider,
                decided_on=decided_on, params=declaration, name=self.name.strip() or None,
                priority=int(self.priority), srs_id=int(project.record.crs_epsg))
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, constraint_provenance.EDIT_CONSTRAINTS)
        made = edited.constraints[0]
        lines = [constraint_panels.Line(tr(
            "Intention «{name}» converted into the constraint «{code}»",
            name=entry.intention.name, code=made.code))]
        _show_marks_result(project, lines, self.report)
        return {"FINISHED"}


# --- Ver restricciones y límites (T26; RF-012-18) ------------------------------------------------

TOGGLE_OVERLAY = constraint_panels.TOGGLE_OVERLAY


def _overlay() -> Any:
    """El módulo de la superposición (``bl.draw.constraints``), importado al usarlo."""
    from ..draw import constraints  # al usarlo: nada pesado al registrar

    return constraints


class GEOBLENDER_OT_core_toggle_constraints_overlay(bpy.types.Operator):
    """Untouchables, limits and buffers over the view while designing"""

    bl_idname = TOGGLE_OVERLAY
    bl_label = "Show constraints and limits"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Solo lee: hace falta un proyecto abierto (también en solo lectura)."""
        if project_session.current() is None:
            cls.poll_message_set(tr("Open a project"))  # type: ignore[attr-defined]
            return False
        return True

    def execute(self, context: Any) -> set[str]:
        """Activa la superposición (se construye por pasos, sin escribir nada en el proyecto) o,
        si ya está activa, la quita."""
        overlay = _overlay()
        if overlay.enabled():
            overlay.disable()
            self.report({"INFO"}, tr("Constraints and limits hidden"))
            return {"FINISHED"}
        try:
            overlay.enable()
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr("The constraints and limits could not be shown: {detail}",
                                      detail=error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the constraints and limits"))
        return {"FINISHED"}


classes: tuple[type, ...] = (
    GEOBLENDER_OT_core_edit_limits, GEOBLENDER_OT_core_declare_limits,
    GEOBLENDER_OT_core_go_to_place, GEOBLENDER_OT_core_edit_constraints,
    GEOBLENDER_OT_core_create_constraints, GEOBLENDER_OT_core_complete_constraint,
    GEOBLENDER_OT_core_find_untouchables, GEOBLENDER_OT_core_declare_sectors,
    GEOBLENDER_OT_core_search_untouchables, GEOBLENDER_OT_core_convert_hit,
    GEOBLENDER_OT_core_discard_hit, GEOBLENDER_OT_core_close_search,
    GEOBLENDER_OT_core_edit_client_marks, GEOBLENDER_OT_core_save_client_marks,
    GEOBLENDER_OT_core_convert_intention, GEOBLENDER_OT_core_toggle_constraints_overlay)
"""Los operadores de la 012 que ya tienen su clase real (de la T22 a la T28)."""
