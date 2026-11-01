# SPDX-License-Identifier: GPL-3.0-or-later
"""Varios límites legales en una rejilla pequeña (spec 012, T44; hallazgo F-1; RF-012-11,
RF-012-12, RF-012-13, RF-012-21, RF-012-22).

Rectángulos locales (m desde ``tests.support.constraints_fixtures.BASE``) en una rejilla de
60 × 30 celdas de 1 m, con las áreas a mano:

- :func:`contiguous`: dos concesiones contiguas de 30 × 30 m (900 m² cada una, 1.800 m² la
  unión), alineadas con las celdas.
- :func:`overlapping`: dos concesiones que se solapan 20 columnas (A de 0 a 40 m y B de 20 a
  60 m): 1.200 m² cada una, 1.800 m² la unión.
- :func:`unaligned`: dos concesiones contiguas cuyo borde común cae a media celda (30,5 m): la
  columna 30 queda a caballo de las dos.

Sin el código de la 012 más allá de su modelo de restricciones (son entradas hechas a mano).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
model = import_geoblender("core.constraints.model")
params = import_geoblender("core.constraints.params")

NCOLS, NROWS = 60, 30
GRID = gis.Grid(fx.BASE[0], fx.BASE[1] + NROWS, 1.0, 1.0, NCOLS, NROWS)
"""Celdas de 1 m; la esquina suroeste es ``fx.BASE``."""

Box = tuple[float, float, float, float]


def limit(code: str, box: Box, fid: int) -> Any:
    """Un límite legal completo: el rectángulo local ``box`` ``(oeste, sur, este, norte)``."""
    return model.Constraint(
        uid=f"{fid:032d}", code=code, name=code.removeprefix("r_").title(),
        ctype=model.ConstraintType.LEGAL_LIMIT, kind=model.GeometryKind.POLYGON,
        parts=((fx.rectangle(*box),),), priority=0, reason="Prueba", decided_by="IMGA",
        decided_on=date(2026, 11, 1), decision_uid=None, intention_uid=None,
        source_input=None, source_fid=None, layer="core_constraint_polygon", fid=fid)


def resolved(items: Sequence[Any], inward: float | Mapping[str, float] = 2.0
             ) -> dict[str, object]:
    """Los valores resueltos de los límites: activos, con ``inward`` m hacia dentro (un número
    para todos o uno por código)."""
    found: dict[str, object] = {}
    for item in items:
        value = inward if isinstance(inward, int | float) else inward[item.code]
        found[params.param_key(item.code, model.ConstraintParam.ACTIVE)] = True
        found[params.param_key(item.code, model.ConstraintParam.BUFFER_IN)] = float(value)
    return found


def several(boxes: Mapping[str, Box]) -> tuple[Any, ...]:
    """Los límites legales ``código → rectángulo local``, en ese orden."""
    return tuple(limit(code, box, fid) for fid, (code, box) in enumerate(boxes.items(), start=1))


def contiguous() -> tuple[Any, ...]:
    """Dos concesiones contiguas de 900 m² cada una."""
    return several({"r_conc_a": (0, 0, 30, 30), "r_conc_b": (30, 0, 60, 30)})


def overlapping() -> tuple[Any, ...]:
    """Dos concesiones que se solapan 20 m (1.200 m² cada una)."""
    return several({"r_conc_a": (0, 0, 40, 30), "r_conc_b": (20, 0, 60, 30)})


def unaligned() -> tuple[Any, ...]:
    """Dos concesiones contiguas con el borde común a media celda (30,5 m)."""
    return several({"r_conc_a": (0, 0, 30.5, 30), "r_conc_b": (30.5, 0, 60, 30)})


def union() -> tuple[Any, ...]:
    """Un solo límite legal con el contorno de la unión de :func:`contiguous` y
    :func:`overlapping`."""
    return several({"r_conc_a": (0, 0, 60, 30)})
