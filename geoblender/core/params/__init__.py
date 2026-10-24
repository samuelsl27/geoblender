# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros tipados (spec 008; RF-008-01 a RF-008-06, RF-008-59, RF-008-60; plan 008 §5.3.1;
ADR-0013).

Cada módulo declara sus parámetros con :class:`ParamDef` en ``<paquete>/params.py`` y los
registra desde ``bl/`` con :func:`register_definitions` (y los quita con
:func:`unregister_definitions`); ``core`` declara los suyos en :mod:`.core_defs`. Un parámetro
por elemento de un dato (la densidad de cada unidad) se declara con una familia,
:class:`ParamFamily` (:func:`register_families`, :func:`unregister_families`; ADR-0027), y
:func:`definition` da la definición de cualquier clave, también la concreta de una familia.
Detalle en :mod:`.model`. Los valores del proyecto, con su tipo, su procedencia y su
historial, los guarda :class:`ParameterStore` (:mod:`.store`). Python puro: solo la biblioteca
estándar y ``core`` (ADR-0004).
"""

from .model import (
    CATALOG_ES,
    DEFAULT_KINDS,
    DEFINITIONS,
    FAMILIES,
    MESSAGES,
    SCOPES,
    Message,
    ParamDef,
    ParamError,
    ParamFamily,
    ParamKind,
    ParamValue,
    SourceKind,
    ValueType,
    definition,
    find_definition,
    format_range,
    format_value,
    parameter_label,
    parse_value,
    register_definitions,
    register_families,
    render,
    unregister_definitions,
    unregister_families,
)
from .store import (
    DEFAULT_DECIDER,
    PROJECT_SCOPE,
    UNSET,
    VERSION_SCOPE,
    DefinitionChange,
    HistoryAction,
    HistoryEntry,
    ParameterFilter,
    ParameterRecord,
    ParameterRow,
    ParameterStore,
    ParamMark,
    ResolvedParam,
    default_source,
    definition_sha256,
    review_text,
    undeclared_sha256,
    value_sha256,
)

__all__ = [
    "CATALOG_ES",
    "DEFAULT_DECIDER",
    "DEFAULT_KINDS",
    "DEFINITIONS",
    "FAMILIES",
    "MESSAGES",
    "PROJECT_SCOPE",
    "SCOPES",
    "UNSET",
    "VERSION_SCOPE",
    "DefinitionChange",
    "HistoryAction",
    "HistoryEntry",
    "Message",
    "ParamDef",
    "ParamError",
    "ParamFamily",
    "ParamKind",
    "ParamMark",
    "ParamValue",
    "ParameterFilter",
    "ParameterRecord",
    "ParameterRow",
    "ParameterStore",
    "ResolvedParam",
    "SourceKind",
    "ValueType",
    "default_source",
    "definition",
    "definition_sha256",
    "find_definition",
    "format_range",
    "format_value",
    "parameter_label",
    "parse_value",
    "register_definitions",
    "register_families",
    "render",
    "review_text",
    "undeclared_sha256",
    "unregister_definitions",
    "unregister_families",
    "value_sha256",
]
