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

Con ``tools/check.py`` y otros programas ocupando todos los procesadores, ninguna de esas
medidas cabía a veces (spec 005, T45: la carga del catálogo, 25 ms en reposo, en 50,4–51,7 ms
la mejor de veinte): el hilo que mide esperaba su turno tras los demás procesos. Por eso
:func:`best_of` toma cada medida con la prioridad del hilo subida (:func:`raised_priority`):
lo medido es el código, con la máquina llena o no, y el presupuesto sigue siendo el mismo.

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

import contextlib
import functools
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Any

ATTEMPTS = 3  # las medidas de siempre: la mejor de tres
MAX_ATTEMPTS = 20  # con carga, hasta 20 (unos 0,5 s más en una prueba de 25 ms)
# La prioridad con que mide best_of (spec 005, T45): THREAD_PRIORITY_HIGHEST de Windows, dos
# niveles sobre la normal de su proceso (la de los demás procesos de la comprobación), sin
# llegar a la de tiempo real ni pedir permisos. GetThreadPriority da _PRIORITY_ERROR si falla.
PRIORITY_HIGHEST = 2
_PRIORITY_ERROR = 0x7FFFFFFF


@functools.cache
def _kernel32() -> Any:
    """Las funciones de prioridad de los hilos de ``kernel32`` (solo en Windows)."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentThread.restype = ctypes.c_void_p
    kernel32.GetThreadPriority.argtypes = (ctypes.c_void_p,)
    kernel32.GetThreadPriority.restype = ctypes.c_int
    kernel32.SetThreadPriority.argtypes = (ctypes.c_void_p, ctypes.c_int)
    kernel32.SetThreadPriority.restype = ctypes.c_int
    return kernel32


def thread_priority() -> int | None:
    """La prioridad del hilo actual relativa a la de su proceso (0, la normal); ``None``
    fuera de Windows o si no se puede leer."""
    if os.name != "nt":
        return None
    kernel32 = _kernel32()
    value = kernel32.GetThreadPriority(kernel32.GetCurrentThread())
    return None if value == _PRIORITY_ERROR else value


@contextlib.contextmanager
def raised_priority() -> Iterator[bool]:
    """Mientras está activo (``with``), el hilo actual tiene la prioridad
    :data:`PRIORITY_HIGHEST` (spec 005, T45): con todos los procesadores ocupados no espera su
    turno tras los demás procesos, de prioridad normal. Al salir vuelve la de antes, también si
    algo falla. Da ``True`` si la subió; ``False``, sin tocar nada, si ya era esa o más alta, si
    no se pudo o fuera de Windows."""
    before = thread_priority()
    if before is None or before >= PRIORITY_HIGHEST:
        yield False
        return
    kernel32 = _kernel32()
    if not kernel32.SetThreadPriority(kernel32.GetCurrentThread(), PRIORITY_HIGHEST):
        yield False
        return
    try:
        yield True
    finally:
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), before)


def best_of(
    action: Callable[[], object],
    budget_s: float,
    *,
    attempts: int = ATTEMPTS,
    max_attempts: int = MAX_ATTEMPTS,
    clock: Callable[[], float] = time.perf_counter,
) -> float:
    """La menor duración, en segundos, de ``action``: la ejecuta ``attempts`` veces y,
    mientras la mejor pase de ``budget_s``, otra vez, hasta ``max_attempts`` en total, cada
    vez con la prioridad del hilo subida (:func:`raised_priority`). Lanza ``ValueError`` si
    ``attempts`` < 1 o ``max_attempts`` < ``attempts``. La prueba compara el resultado con el
    mismo presupuesto (``assertLessEqual``)."""

    def measure() -> float:
        with raised_priority():
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
