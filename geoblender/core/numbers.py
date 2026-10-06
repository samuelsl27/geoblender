# SPDX-License-Identifier: GPL-3.0-or-later
"""Números que teclea el usuario en un diálogo (spec 002; RF-002-01, RF-002-03;
ADR-0005 §4; docs/trampas.md §1, «Decimales de un diálogo en FloatProperty»).

Las coordenadas absolutas y los decimales de un diálogo llegan como texto
(``StringProperty``: un ``FloatProperty`` los guardaría en float32) y se convierten aquí a
float64. Se acepta **coma o punto** como separador decimal (uno solo, y nunca los dos a
la vez: «700.000,4» es ambiguo) y espacios como separador de miles (también el fino y el
de no separación: «4 400 500,9»). Lo demás se rechaza con el objeto, el campo y el valor.
"""

from __future__ import annotations

import math
import re

from .errors import ValidationError

# Espacios que se admiten como separador de miles: normal, sin ruptura, fino y fino sin
# ruptura.
_GROUPING = str.maketrans("", "", "    ")
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$")


def parse_decimal(text: object, *, obj: str, field: str) -> float:
    """El número de ``text`` en float64 (coma o punto decimal, espacios de miles).
    :class:`ValidationError` con ``obj``, ``field`` y el texto tecleado si no lo es."""
    if not isinstance(text, str):
        raise ValidationError(
            "core.number_invalid",
            "debe ser un número escrito como texto (p. ej. «700 000,4»)",
            obj=obj,
            field=field,
            value=text,
        )
    compact = text.strip().translate(_GROUPING)
    if not compact:
        raise ValidationError(
            "core.number_missing",
            "falta el número; escríbalo con coma o punto decimal (p. ej. «700 000,4»)",
            obj=obj,
            field=field,
            value=text,
        )
    if not _NUMBER.match(compact):
        raise ValidationError(
            "core.number_invalid",
            "no es un número: use cifras con una sola coma o un solo punto decimal (no los "
            "dos) y, si quiere, espacios como separador de miles (p. ej. «4 400 500,9»)",
            obj=obj,
            field=field,
            value=text,
        )
    value = float(compact.replace(",", "."))
    if not math.isfinite(value):  # inalcanzable con la expresión, por si cambia
        raise ValidationError(
            "core.number_invalid", "no es un número finito", obj=obj, field=field, value=text
        )
    return value
