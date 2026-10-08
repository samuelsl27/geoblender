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
- :mod:`.originals`: guardar el original de una entrada tabular o documental desde la copia
  verificada de su importación, con su huella y el límite ``core.original_copy_limit``
  (RF-008-53, RF-008-14).

- :mod:`.guard`: rechazar una escritura de Geoblender en la fuente de una entrada, en su
  carpeta fuera del proyecto o en una carpeta de solo lectura (``check_write_target``), y los
  avisos de las carpetas de solo lectura (``read_only_warnings``) (RF-008-15, RF-008-14).

La comprobación de las fuentes llega con las tareas siguientes (plan 008 §5.3.1).
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
from .guard import check_write_target, read_only_warnings
from .originals import (
    ORIGINAL_COPY_LIMIT,
    OriginalsOutcome,
    StoredOriginal,
    store_originals_steps,
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
    "ORIGINAL_COPY_LIMIT",
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
    "OriginalsOutcome",
    "Reuse",
    "SourceFile",
    "SourcePrint",
    "StoredOriginal",
    "Substitute",
    "check_crs",
    "check_name",
    "check_received_at",
    "check_received_from",
    "check_write_target",
    "classify_import",
    "crs_text",
    "discard",
    "edit_delivery",
    "get",
    "input_declarations",
    "keep_copy",
    "locate_source",
    "read_only_warnings",
    "register_input",
    "resolve_source",
    "reuse_input",
    "store_originals_steps",
    "supersede",
]
