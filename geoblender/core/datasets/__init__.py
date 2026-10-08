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

Las ediciones externas y los restos llegan con las tareas siguientes (plan 008 §5.3.1).
"""

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
from .registry import get, register_dataset, set_content, set_status, successor, supersede
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
    "Store",
    "TableState",
    "ensure_triggers",
    "get",
    "protect_immutable",
    "protection_trigger_names",
    "register_dataset",
    "set_content",
    "set_status",
    "successor",
    "supersede",
    "table_states",
    "track_table",
    "tracking_trigger_names",
]
