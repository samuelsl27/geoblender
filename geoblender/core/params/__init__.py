# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros tipados (spec 008; RF-008-01 a RF-008-06, RF-008-59, RF-008-60; plan 008 §5.3.1;
ADR-0013).

Cada módulo declara sus parámetros con :class:`ParamDef` en ``<paquete>/params.py`` y los
registra desde ``bl/`` con :func:`register_definitions` (y los quita con
:func:`unregister_definitions`); ``core`` declara los suyos en :mod:`.core_defs`. Detalle en
:mod:`.model`. Los valores del proyecto, con su tipo, su procedencia y su historial, los
guarda :class:`ParameterStore` (:mod:`.store`). Python puro: solo la biblioteca estándar y
``core`` (ADR-0004).
"""

from .model import (
    CATALOG_ES,
    DEFAULT_KINDS,
    DEFINITIONS,
    MESSAGES,
    SCOPES,
    Message,
    ParamDef,
    ParamError,
    ParamKind,
    ParamValue,
    SourceKind,
    ValueType,
    format_range,
    format_value,
    parse_value,
    register_definitions,
    render,
    unregister_definitions,
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
    "definition_sha256",
    "format_range",
    "format_value",
    "parse_value",
    "register_definitions",
    "render",
    "review_text",
    "undeclared_sha256",
    "unregister_definitions",
    "value_sha256",
]
