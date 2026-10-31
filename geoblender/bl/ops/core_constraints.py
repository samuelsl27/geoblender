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
estaban (ADR-0025 §2). Nada pesado: lo que registra ya está importado con el resto de ``bl``.

Las órdenes (T22 a T28: Límites…, Restricciones…, Buscar elementos intocables por sector…,
Intenciones del cliente…, Verificar un diseño por recinto…) las pasa a la entrada «012» del
catálogo cada una con su clase real; :data:`classes` irá creciendo con ellas. La superposición
«Ver restricciones y límites» (T26) y los cargadores de la vista (T26 a T28) se registrarán
aquí también.

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
"""

from __future__ import annotations

import datetime as dt
import functools
import logging
import math
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

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
    is_code,
)
from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.provenance import contract
from ...core.provenance.operations import Use
from ...core.provenance.undo import UndoKind
from ...core.units import convert, parse_quantity
from ...core.versions import freeze
from ...gis.masks import sources
from ...gis.masks import store as mask_store
from ...reserves import compliance_store
from ..scene import project_session, undo_watch
from ..scene import versions as scene_versions
from ..ui import constraint_panels
from ..ui import views as ui_views
from ..ui.commands import catalog as command_catalog
from ..ui.commands import text, with_note
from .core_provenance import (
    SESSION,
    ProvenanceAwareOperator,
    ensure_ready,
    error_text,
    write_unavailable,
)

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
FREEZE_MODULE = compliance_store.MODULE
"""El módulo que declara la comprobación de congelar de la 012 (``res``)."""
OPERATION_DEFS: tuple[contract.OperationDef, ...] = constraint_provenance.OPERATIONS
"""Los ``OperationDef`` de los cuatro tipos de ``core`` de las restricciones (de proyecto, sin
repetición)."""

_UNDO: list[Callable[[], None]] = []


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
    check = compliance_store.freeze_findings
    if (FREEZE_MODULE, check) not in freeze.freeze_checks():
        freeze.register_freeze_check(FREEZE_MODULE, check)
        _UNDO.append(functools.partial(_unregister_freeze_check, FREEZE_MODULE, check))


def unregister() -> None:
    """Quita lo que puso :func:`register`, en orden inverso (lo que otro cambió después es
    suyo); las traducciones instaladas se quedan; idempotente."""
    while _UNDO:
        _UNDO.pop()()


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


def _unregister_freeze_check(module: str, check: freeze.FreezeCheck) -> None:
    """Quita la comprobación ``check`` de ``module`` y deja las demás de ese módulo (en su
    orden): ``core.versions.freeze`` solo las quita por módulo."""
    others = [other for found, other in freeze.freeze_checks()
              if found == module and other is not check]
    freeze.unregister_freeze_checks(module)
    for other in others:
        freeze.register_freeze_check(module, other)


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
    for prefix in ("gis_fea_", "gis_dom_"):
        if dataset.startswith(prefix):
            return dataset.removeprefix(prefix) or dataset
    return dataset


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
    """Lo que pide «Desde una capa…» ya comprobado: la capa, cómo se leen sus entidades y los
    parámetros que se declaran de las restricciones que se creen (RF-012-01, RF-012-02)."""

    layer: str
    mapping: constraint_provenance.LayerMapping
    declaration: constraint_provenance.ParamDeclaration


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
    resguardo o el peso no valen, o la correspondencia de los valores del tipo no se lee."""
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
    values: dict[ConstraintParam, Any] = {ConstraintParam.ACTIVE: bool(form.active)}
    for param, found in (
            (ConstraintParam.BUFFER_OUT, _typed_metres(
                form.buffer_out, ConstraintParam.BUFFER_OUT,
                tr("Write the outward setback in metres (0 or more): «{value}» does not fit",
                   value="{value}"))),
            (ConstraintParam.BUFFER_IN, _typed_metres(
                form.buffer_in, ConstraintParam.BUFFER_IN,
                tr("Write the inward setback of the legal limit in metres (0 or more): "
                   "«{value}» does not fit", value="{value}"))),
            (ConstraintParam.WEIGHT, _typed_weight(form.weight))):
        if found is not None:
            values[param] = found
    declaration = constraint_provenance.ParamDeclaration(
        values=values, source=layer, source_kind="document",
        decided_by=decided_by or project.session.user_host,
        reason=reason or tr("Created from the layer «{layer}»", layer=layer))
    return CreateRequest(layer, mapping, declaration)


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
        abre su ventana; desde un guion sin ventana, solo la vista."""
        try:
            constraint_panels.fill_constraints(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
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

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _write_poll(cls)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        about = super().description(context, properties)
        note = scene_versions.not_editable_text()
        return about if note is None else with_note(about, note)

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Lee las capas de las que se pueden crear restricciones y abre el diálogo con la
        fecha de hoy; sin capas, dice cómo importarlas."""
        self.provenance_dialog = True
        project = SESSION.project
        try:
            constraint_panels.fill_constraints(project)
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

    def execute(self, context: Any) -> set[str]:
        """Comprueba lo escrito y la puerta de la 008 (la capa es la entrada), crea las
        restricciones de la capa con ``core.edit_constraints`` (sin tocar la capa de origen),
        con los parámetros que pide su tipo y se declaran, y deja en la ventana el informe de las
        creadas y de las entidades rechazadas con su motivo (RF-012-01, RF-012-02)."""
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
        try:
            edited = sources.create_constraints(
                project, request.layer, request.mapping, params=request.declaration,
                default_name=_layer_label(request.layer))
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
        "ctype", "name", "reason", "decided_by", "decided_on", "priority"))


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
        en el proyecto: solo se dan de alta los que faltan)."""
        self.provenance_dialog = True
        project = SESSION.project
        try:
            row = self._row(project)
        except (ConstraintFormError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, str(exc) if isinstance(exc, ConstraintFormError)
                        else error_text(exc))
            return {"CANCELLED"}
        shown = i18n.language()
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

    def _updated(self, row: Constraint) -> Constraint:
        """``row`` con lo que se completa: lo escrito manda y lo vacío se queda como estaba;
        :class:`ConstraintFormError` si no tiene tipo, un tipo que cabe en su geometría, nombre,
        motivo, decisor o fecha."""
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
        return replace(row, ctype=ctype, name=name, reason=reason, decided_by=decided_by,
                       decided_on=decided_on, priority=int(self.priority))

    def _declaration(self, row: Constraint
                     ) -> constraint_provenance.ParamDeclaration:
        """Los parámetros que se declaran: los tecleados (y «activa»)."""
        values: dict[ConstraintParam, Any] = {ConstraintParam.ACTIVE: bool(self.active)}
        for param, found in (
                (ConstraintParam.BUFFER_OUT, _typed_metres(
                    self.buffer_out, ConstraintParam.BUFFER_OUT,
                    tr("Write the outward setback in metres (0 or more): «{value}» does not "
                       "fit", value="{value}"))),
                (ConstraintParam.BUFFER_IN, _typed_metres(
                    self.buffer_in, ConstraintParam.BUFFER_IN,
                    tr("Write the inward setback of the legal limit in metres (0 or more): "
                       "«{value}» does not fit", value="{value}"))),
                (ConstraintParam.WEIGHT, _typed_weight(self.weight))):
            if found is not None:
                values[param] = found
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


classes: tuple[type, ...] = (
    GEOBLENDER_OT_core_edit_limits, GEOBLENDER_OT_core_declare_limits,
    GEOBLENDER_OT_core_go_to_place, GEOBLENDER_OT_core_edit_constraints,
    GEOBLENDER_OT_core_create_constraints, GEOBLENDER_OT_core_complete_constraint)
"""Los operadores de la 012 que ya tienen su clase real (de la T22 a la T28)."""
