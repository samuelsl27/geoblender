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

:func:`least_of` hace lo mismo con lo que mide la propia prueba (spec 006, T48): una
latencia, como el tiempo desde que se pide parar un cálculo hasta que para, o desde que se
pide escribir hasta que llega «ocupado». Una medida, la de siempre, y otra mientras pase del
presupuesto.

:func:`drive_steps` recorre una operación por pasos de ``core`` (una copia, una
publicación) como el operador modal que la avanza, y dice cuánto tardó cada llamada al
generador y cuánto de la más larga fue esperar dentro de ``os.fsync`` (:class:`SyncTimer`):
si el paso más largo de una copia pasa de 1 s (RNF-002-06) casi entero en ``fsync``, lo marca
el disco, no la copia (spec 006, T49; ``docs/trampas.md`` §6).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from types import TracebackType

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

    def measure() -> float:
        start = clock()
        action()
        return clock() - start

    return least_of(measure, budget_s, attempts=attempts, max_attempts=max_attempts)


def least_of(
    measure: Callable[[], float],
    budget_s: float,
    *,
    attempts: int = 1,
    max_attempts: int = MAX_ATTEMPTS,
) -> float:
    """El menor de los valores, en segundos, que da ``measure`` (lo que mide la prueba;
    ``inf`` si no llegó a ocurrir): la llama ``attempts`` veces y, mientras el menor pase
    de ``budget_s``, otra vez, hasta ``max_attempts`` en total. Lanza ``ValueError`` si
    ``attempts`` < 1 o ``max_attempts`` < ``attempts``. La prueba compara el resultado con
    el mismo presupuesto."""
    if attempts < 1 or max_attempts < attempts:
        raise ValueError(
            f"medidas no válidas: {attempts} y como mucho {max_attempts} (1 ≤ medidas ≤ "
            "máximo)"
        )
    least = float("inf")
    for done in range(max_attempts):
        if done >= attempts and least <= budget_s:
            break
        least = min(least, measure())
    return least


class SyncTimer:
    """Mientras está activo (``with``), cuenta las llamadas a ``os.fsync`` (forzar a disco
    lo escrito) y el tiempo dentro de ellas: sustituye ``os.fsync`` por la misma función
    cronometrada y la repone al salir, también si algo falla. Solo para pruebas que miden
    una operación entera en su proceso (no es seguro con otro hilo que también la cambie)."""

    def __init__(self, *, clock: Callable[[], float] = time.perf_counter) -> None:
        self.clock = clock
        self.calls = 0
        self.total_s = 0.0
        self._previous: Callable[[int], None] | None = None

    def __enter__(self) -> SyncTimer:
        previous = os.fsync
        self._previous = previous

        def timed(fd: int) -> None:
            started = self.clock()
            try:
                previous(fd)
            finally:
                self.total_s += self.clock() - started
                self.calls += 1

        os.fsync = timed
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if self._previous is not None:
            os.fsync = self._previous
            self._previous = None


@dataclass(frozen=True)
class StepsRun:
    """Lo que tardó recorrer una operación por pasos: el total, cuántos pasos, la llamada
    más larga al generador (el mayor hueco sin progreso), cuánto de ella fue esperar dentro
    de ``os.fsync``, lo esperado en ``os.fsync`` en total y el resultado del último paso que
    lo lleva (``None`` si ninguno)."""

    total_s: float
    steps: int
    longest_s: float
    longest_sync_s: float
    sync_s: float
    result: object

    @property
    def disk_bound(self) -> bool:
        """Más de la mitad de la llamada más larga fue esperar dentro de ``os.fsync``: la
        marca el disco, no lo que hace el paso."""
        return self.longest_sync_s * 2 > self.longest_s


def drive_steps(
    steps: Iterator[object], *, clock: Callable[[], float] = time.perf_counter
) -> StepsRun:
    """Recorre ``steps`` entero midiendo cada llamada al generador, también la última (la
    que termina), y, con :class:`SyncTimer`, cuánto de cada una fue ``os.fsync``. Un error
    del generador se propaga (y ``os.fsync`` vuelve a ser el de antes)."""
    calls: list[tuple[float, float]] = []  # (duración, de ella en os.fsync)
    result: object = None
    started = clock()
    with SyncTimer(clock=clock) as timer:
        while True:
            before, synced = clock(), timer.total_s
            try:
                step = next(steps)
            except StopIteration:
                calls.append((clock() - before, timer.total_s - synced))
                break
            calls.append((clock() - before, timer.total_s - synced))
            if getattr(step, "result", None) is not None:
                result = step.result
    longest, longest_sync = max(calls)
    return StepsRun(
        clock() - started, len(calls) - 1, longest, longest_sync, timer.total_s, result
    )
