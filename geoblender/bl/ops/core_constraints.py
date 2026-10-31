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
"""

from __future__ import annotations

import datetime as dt
import functools
import math
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import bpy
from bpy.props import StringProperty

from ...core import i18n
from ...core import params as core_params
from ...core.constraints import messages as constraint_messages
from ...core.constraints import params as constraint_params
from ...core.constraints import provenance as constraint_provenance
from ...core.constraints.model import ConstraintParam, ConstraintType
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
from ..ui.commands import with_note
from .core_provenance import (
    SESSION,
    ProvenanceAwareOperator,
    ensure_ready,
    error_text,
    write_unavailable,
)

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


class LimitsFormError(ValueError):
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


classes: tuple[type, ...] = (GEOBLENDER_OT_core_edit_limits, GEOBLENDER_OT_core_declare_limits,
                             GEOBLENDER_OT_core_go_to_place)
"""Los operadores de la 012 que ya tienen su clase real (de la T22 a la T28)."""
