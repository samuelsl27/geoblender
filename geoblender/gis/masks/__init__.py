# SPDX-License-Identifier: GPL-3.0-or-later
"""Las restricciones compiladas a máscaras en la rejilla del proyecto (spec 012; plan 012 §5.1,
A1–A5; ADR-0028). Dominio puro (nivel 2): numpy y la geometría 2D propia de ``gis.polygons`` y
``gis.coverage``, sin bibliotecas de geometría (D-19).

- ``gis.masks.zones``: la zona de cada restricción y los límites en la rejilla, como tramos de
  fila (:class:`~.zones.Runs`), con la regla de la celda entera del lado seguro (D-1).

Los demás módulos (combinar, el informe, compilar, guardar y la interfaz de los operadores) los
añaden las tareas siguientes de la 012.
"""

from .zones import LimitRuns, Runs, area_inside, edges_of, inside_runs, limit_runs, limit_steps
from .zones import near_runs, segments_of, zone_runs, zone_steps

__all__ = [
    "LimitRuns",
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
