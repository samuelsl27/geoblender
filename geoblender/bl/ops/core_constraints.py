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
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping
from typing import Any

from ...core import i18n
from ...core import params as core_params
from ...core.constraints import messages as constraint_messages
from ...core.constraints import params as constraint_params
from ...core.constraints import provenance as constraint_provenance
from ...core.provenance import contract
from ...core.versions import freeze
from ...reserves import compliance_store

MODULE = constraint_provenance.MODULE
"""El módulo de las definiciones, las familias y los tipos de operación de las restricciones
(``core``)."""
FREEZE_MODULE = compliance_store.MODULE
"""El módulo que declara la comprobación de congelar de la 012 (``res``)."""
OPERATION_DEFS: tuple[contract.OperationDef, ...] = constraint_provenance.OPERATIONS
"""Los ``OperationDef`` de los cuatro tipos de ``core`` de las restricciones (de proyecto, sin
repetición)."""

classes: tuple[type, ...] = ()
"""Los operadores y los paneles de la 012 que ya tienen su clase real (de la T22 a la T28)."""

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
