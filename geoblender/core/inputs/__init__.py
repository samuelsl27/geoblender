# SPDX-License-Identifier: GPL-3.0-or-later
"""Entradas registradas (spec 008; RF-008-07, RF-008-54; RF-002-19; ADR-0024; ADR-0025; plan
008 §5.1).

- :mod:`.model`: qué es una entrada (:class:`InputSpec`, :class:`InputRecord`, sus ficheros
  :class:`SourceFile` y sus huellas :class:`SourcePrint`, sus estados, sus anclas y sus CRS
  declarados) y sus declaraciones (:func:`input_declarations`).
- :mod:`.registry`: clasificar una importación (reutilizar, sustituir o nueva), registrarla
  con su importación, reutilizarla, sustituirla (RF-008-11), mantener la copia de una cambiada
  (RF-008-12), descartarla (RF-008-55), editar su nombre y su entrega (D-11), buscarla y anclar
  o encontrar sus ficheros.

Los originales, la guarda de escritura y la comprobación de las fuentes llegan con las tareas
siguientes (plan 008 §5.3.1).
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
    check_name,
    check_received_at,
    check_received_from,
    crs_text,
    input_declarations,
)
from .registry import (
    UNSET,
    Classification,
    Difference,
    New,
    Reuse,
    Substitute,
    classify_import,
    discard,
    edit_delivery,
    get,
    keep_copy,
    locate_source,
    register_input,
    resolve_source,
    reuse_input,
    supersede,
)

__all__ = [
    "ACTIVE_STATUSES",
    "COORDINATE_KINDS",
    "ELEVATION_KINDS",
    "INACTIVE_STATUSES",
    "INPUT_KINDS",
    "UNSET",
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
    "check_name",
    "check_received_at",
    "check_received_from",
    "classify_import",
    "crs_text",
    "discard",
    "edit_delivery",
    "get",
    "input_declarations",
    "keep_copy",
    "locate_source",
    "register_input",
    "resolve_source",
    "reuse_input",
    "supersede",
]
