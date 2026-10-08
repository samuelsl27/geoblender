# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos del proyecto (spec 008; RF-008-17, RF-008-21, RF-008-52, RF-008-56, RF-008-57;
ADR-0025; plan 008 §5.1).

Por ahora, ``tracking``: el seguimiento de las tablas de los datos por
``gpkg_contents.last_change``, la huella de su SQL y sus disparadores, y la protección de lo
importado. El registro de los datos (``model``, ``registry``), las ediciones externas y los
restos llegan con las tareas siguientes (plan 008 §5.3.1).
"""

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
    "TableState",
    "ensure_triggers",
    "protect_immutable",
    "protection_trigger_names",
    "table_states",
    "track_table",
    "tracking_trigger_names",
]
