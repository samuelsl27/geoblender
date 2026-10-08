# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros tipados (spec 008; RF-008-01 a RF-008-06, RF-008-59, RF-008-60; plan 008 §5.3.1;
ADR-0013).

Cada módulo declara sus parámetros con :class:`ParamDef` en ``<paquete>/params.py`` y los
registra desde ``bl/`` con :func:`register_definitions` (y los quita con
:func:`unregister_definitions`); ``core`` declara los suyos en :mod:`.core_defs`. Detalle en
:mod:`.model`. Python puro: solo la biblioteca estándar y ``core`` (ADR-0004).
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
    format_value,
    parse_value,
    register_definitions,
    render,
    unregister_definitions,
)

__all__ = [
    "CATALOG_ES",
    "DEFAULT_KINDS",
    "DEFINITIONS",
    "MESSAGES",
    "SCOPES",
    "Message",
    "ParamDef",
    "ParamError",
    "ParamKind",
    "ParamValue",
    "SourceKind",
    "ValueType",
    "format_value",
    "parse_value",
    "register_definitions",
    "render",
    "unregister_definitions",
]
