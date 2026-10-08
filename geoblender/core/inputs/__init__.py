# SPDX-License-Identifier: GPL-3.0-or-later
"""Entradas registradas (spec 008; RF-008-07, RF-008-54; RF-002-19; ADR-0024; ADR-0025; plan
008 §5.1).

- :mod:`.model`: qué es una entrada (:class:`InputSpec`, :class:`InputRecord`, sus ficheros
  :class:`SourceFile` y sus huellas :class:`SourcePrint`, sus estados, sus anclas y sus CRS
  declarados) y sus declaraciones (:func:`input_declarations`).
- :mod:`.registry`: clasificar una importación (reutilizar, sustituir o nueva), registrarla
  con su importación, reutilizarla, buscarla y anclar o encontrar sus ficheros.

Sustituir, mantener la copia, descartar y editar la entrega, los originales, la guarda de
escritura y la comprobación de las fuentes llegan con las tareas siguientes (plan 008 §5.3.1).
"""

from .model import (
    ACTIVE_STATUSES,
    COORDINATE_KINDS,
    ELEVATION_KINDS,
    INACTIVE_STATUSES,
    INPUT_KINDS,
    FileAnchor,
    FileRole,
    InputFileRecord,
    InputRecord,
    InputSpec,
    InputStatus,
    OriginalState,
    SourceFile,
    SourcePrint,
    check_crs,
    crs_text,
    input_declarations,
)
from .registry import (
    Classification,
    Difference,
    New,
    Reuse,
    Substitute,
    classify_import,
    get,
    locate_source,
    register_input,
    resolve_source,
    reuse_input,
)

__all__ = [
    "ACTIVE_STATUSES",
    "COORDINATE_KINDS",
    "ELEVATION_KINDS",
    "INACTIVE_STATUSES",
    "INPUT_KINDS",
    "Classification",
    "Difference",
    "FileAnchor",
    "FileRole",
    "InputFileRecord",
    "InputRecord",
    "InputSpec",
    "InputStatus",
    "New",
    "OriginalState",
    "Reuse",
    "SourceFile",
    "SourcePrint",
    "Substitute",
    "check_crs",
    "classify_import",
    "crs_text",
    "get",
    "input_declarations",
    "locate_source",
    "register_input",
    "resolve_source",
    "reuse_input",
]
