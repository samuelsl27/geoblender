# SPDX-License-Identifier: GPL-3.0-or-later
"""Medidas de las pruebas con un presupuesto de tiempo (spec 006, T38; RNF-001-01,
RNF-007-01).

``tools/check.py`` ejecuta a la vez muchas partes de pruebas (y las de «motor» junto a
las de Blender): una prueba que mide, p. ej., que un catálogo se carga en ≤ 50 ms, puede
caer en un procesador ocupado o en uno de eficiencia y pasarse aunque el código no haya
cambiado. :func:`best_of` toma la mejor de ``ATTEMPTS`` medidas, como hasta ahora, y
mientras ninguna quepa en el presupuesto mide otra vez, hasta ``MAX_ATTEMPTS``: con la
máquina en reposo es la misma medida de siempre, con carga a ratos encuentra un momento
tranquilo, y el presupuesto no cambia (si ninguna cabe, la prueba falla igual).
"""

from __future__ import annotations

import time
from collections.abc import Callable

ATTEMPTS = 3  # las medidas de siempre: la mejor de tres
MAX_ATTEMPTS = 20  # con carga, hasta 20 (unos 0,5 s más en una prueba de 25 ms)


def best_of(
    action: Callable[[], object],
    budget_s: float,
    *,
    attempts: int = ATTEMPTS,
    max_attempts: int = MAX_ATTEMPTS,
    clock: Callable[[], float] = time.perf_counter,
) -> float:
    """La menor duración, en segundos, de ``action``: la ejecuta ``attempts`` veces y,
    mientras la mejor pase de ``budget_s``, otra vez, hasta ``max_attempts`` en total.
    Lanza ``ValueError`` si ``attempts`` < 1 o ``max_attempts`` < ``attempts``. La prueba
    compara el resultado con el mismo presupuesto (``assertLessEqual``)."""
    if attempts < 1 or max_attempts < attempts:
        raise ValueError(
            f"medidas no válidas: {attempts} y como mucho {max_attempts} (1 ≤ medidas ≤ "
            "máximo)"
        )
    best = float("inf")
    for done in range(max_attempts):
        if done >= attempts and best <= budget_s:
            break
        start = clock()
        action()
        best = min(best, clock() - start)
    return best
