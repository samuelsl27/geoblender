# SPDX-License-Identifier: GPL-3.0-or-later
"""Las restricciones compiladas a máscaras en la rejilla del proyecto (spec 012; plan 012 §5.1,
A1–A5; ADR-0028). Dominio puro (nivel 2): numpy y la geometría 2D propia de ``gis.polygons`` y
``gis.coverage``, sin bibliotecas de geometría (D-19).

- ``gis.masks.zones``: la zona de cada restricción y los límites en la rejilla, como tramos de
  fila (:class:`~.zones.Runs`), con la regla de la celda entera del lado seguro (D-1).
- ``gis.masks.combine``: comprobar las restricciones, prepararlas (zonas, límites, avisos) y
  combinarlas en el dominio, el corte y el relleno admitidos, la franja, los conflictos con sus
  causas y la rejilla de clases (A3, D-25).
- ``gis.masks.overlay``: el informe de los límites (áreas en m² y ha, la franja con sus partes y
  lo que queda fuera de la rejilla; A4).

- ``gis.masks.export`` (no se reexporta aquí): la rejilla de clases registrada como GeoTIFF
  entregable con su leyenda en español, en sus metadatos y en un ``.qml`` paletado (RF-012-20).

Los demás módulos (compilar, guardar y la interfaz de los operadores) los
añaden las tareas siguientes de la 012.

**Lo reexportado se importa al primer uso** (spec 012, T38; RNF-001-03 de la spec 001):
``gis.masks.provenance`` es la declaración ligera que ``bl`` registra al habilitar, y importarla
importa este paquete; si el paquete cargase ``combine``, ``overlay`` y ``zones`` (con la geometría
2D), habilitar Geoblender los pagaría sin usarlos. Por eso los nombres de ``__all__`` se resuelven
en ``__getattr__`` (PEP 562) la primera vez que alguien los pide —``from geoblender.gis.masks
import Runs`` sigue valiendo— y quedan guardados en el paquete.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .combine import ClassBit, Conflict, IncompleteConstraints, Limits, Masks, Notice
    from .combine import Outside, Prepared, Zone, prepare, prepare_steps
    from .overlay import LimitsReport, limits_report, report_of
    from .zones import LimitRuns, Runs, area_inside, edges_of, inside_runs, limit_runs, limit_steps
    from .zones import near_runs, segments_of, zone_runs, zone_steps

__all__ = [
    "ClassBit",
    "Conflict",
    "IncompleteConstraints",
    "LimitRuns",
    "Limits",
    "LimitsReport",
    "Masks",
    "Notice",
    "Outside",
    "Prepared",
    "Zone",
    "limits_report",
    "prepare",
    "prepare_steps",
    "report_of",
    "Runs",
    "area_inside",
    "edges_of",
    "inside_runs",
    "limit_runs",
    "limit_steps",
    "near_runs",
    "segments_of",
    "zone_runs",
    "zone_steps",
]

_SOURCES: dict[str, str] = {
    **dict.fromkeys(("ClassBit", "Conflict", "IncompleteConstraints", "Limits", "Masks", "Notice",
                     "Outside", "Prepared", "Zone", "prepare", "prepare_steps"), "combine"),
    **dict.fromkeys(("LimitsReport", "limits_report", "report_of"), "overlay"),
    **dict.fromkeys(("LimitRuns", "Runs", "area_inside", "edges_of", "inside_runs", "limit_runs",
                     "limit_steps", "near_runs", "segments_of", "zone_runs", "zone_steps"),
                    "zones"),
}
"""Cada nombre de ``__all__`` y el módulo de este paquete que lo define."""


def __getattr__(name: str) -> Any:
    """Un nombre de ``__all__`` (cualquier otro: ``AttributeError``, como un módulo sin él): importa
    su módulo la primera vez y lo deja guardado en el paquete."""
    source = _SOURCES.get(name)
    if source is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f".{source}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
