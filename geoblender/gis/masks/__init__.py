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

Los demás módulos (compilar, guardar y la interfaz de los operadores) los
añaden las tareas siguientes de la 012.
"""

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
