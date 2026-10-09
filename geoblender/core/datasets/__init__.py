# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos del proyecto (spec 008; RF-008-17, RF-008-21, RF-008-52, RF-008-56, RF-008-57;
ADR-0025; plan 008 §5.1).

- :mod:`.model`: qué es un dato (:class:`DatasetSpec`, :class:`DatasetRecord`, sus estados y
  sus almacenes).
- :mod:`.registry`: su registro con la operación que escribió su contenido, su hash con su
  lector y su normalizador, su seguimiento, lo importado, el sucesor de lo sustituido y su
  estado.
- :mod:`.tracking`: el seguimiento de las tablas de los datos por
  ``gpkg_contents.last_change``, la huella de su SQL y sus disparadores, y la protección de lo
  importado.
- :mod:`.external`: los datos cambiados fuera de Geoblender: dato a dato (prefiltro, veredicto
  y registro de la edición externa, lo que falta, lo que vuelve y lo dañado), que usa la puerta
  antes de operar (no se reexporta: ``external.assess``, ``external.record``…), y la
  comprobación de todos los datos y de los originales (:func:`external_check_steps`), aceptar
  una edición (:func:`accept_edit`) y lo que se ofrece para resolver un dato (:func:`offers`).
- :mod:`.orphans`: los restos de operaciones interrumpidas en ``rasters/``, ``meshes/`` y
  ``originals/``, apartados a ``orphans/`` al abrir el proyecto (:func:`orphan_steps`,
  RF-008-22).

Los ficheros ajenos y las capas sin registrar llegan con la tarea siguiente (plan 008 §5.3.1).
"""

from .external import (
    ExternalOutcome,
    Offer,
    accept_edit,
    external_check_steps,
    mark_missing,
    offers,
    original_usable,
    restore,
)
from .model import (
    DATASET_KINDS,
    FILE_STORES,
    LIVE_STATUSES,
    UNTRACKED_STORES,
    DatasetRecord,
    DatasetSpec,
    DatasetStatus,
    Store,
)
from .orphans import Orphan, OrphanOutcome, OrphanState, orphan_steps
from .registry import (
    content_digest,
    get,
    register_dataset,
    set_content,
    set_status,
    spec_of,
    successor,
    supersede,
)
from .tracking import (
    TableState,
    ensure_triggers,
    protect_immutable,
    protection_trigger_names,
    table_states,
    track_table,
    tracking_trigger_names,
)

__all__ = [
    "DATASET_KINDS",
    "FILE_STORES",
    "LIVE_STATUSES",
    "UNTRACKED_STORES",
    "DatasetRecord",
    "DatasetSpec",
    "DatasetStatus",
    "ExternalOutcome",
    "Offer",
    "Orphan",
    "OrphanOutcome",
    "OrphanState",
    "Store",
    "TableState",
    "accept_edit",
    "content_digest",
    "ensure_triggers",
    "external_check_steps",
    "get",
    "mark_missing",
    "offers",
    "original_usable",
    "orphan_steps",
    "protect_immutable",
    "protection_trigger_names",
    "register_dataset",
    "restore",
    "set_content",
    "set_status",
    "spec_of",
    "successor",
    "supersede",
    "table_states",
    "track_table",
    "tracking_trigger_names",
]
