# SPDX-License-Identifier: GPL-3.0-or-later
"""Cerrar el proyecto en el último evento de una orden de Diseño que calcula por pasos (spec 014,
T48; hallazgo F-9 de su verificación única).

Las órdenes de Diseño que calculan por pasos (``_StepsModal`` de ``bl.ops.core``) avanzan con cada
evento del temporizador; con un presupuesto mínimo (:data:`ONE_STEP_S`) dan un paso por evento, y
siempre los mismos. :func:`close_at_the_last_event` lanza la orden dos veces: la primera hasta el
final, para contar sus eventos (lo que deja, descartado); la segunda, hasta el penúltimo, y el
último con el proyecto de la sesión cerrado (``project_session.current`` sin proyecto, como en el
cierre a mitad de la 013), que es el evento en el que llega el resultado del cálculo. La ventana
de «Crear» (``_ask_confirmation`` de ``bl.ops.des``) no se abre: se cuenta.

No importa ``bpy``: el contexto, la sesión de proyectos y el módulo de las órdenes los da quien
llama (las pruebas de ``tests/blender``)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
"""Un evento del temporizador del modal."""
ONE_STEP_S = 1e-9
"""El presupuesto de cada evento con el que el modal da un solo paso."""
MAX_EVENTS = 20_000
TICK_S = 1e-3
"""Lo que avanza el reloj de mentira (:func:`one_unit_per_event`) en cada lectura: más que :data:`ONE_STEP_S`, así que cada unidad de trabajo cierra su paso."""


class TickingClock:
    """Un ``perf_counter`` de mentira: cada lectura avanza ``tick_s`` s, vaya el ordenador como vaya (spec 017, T39; hallazgo E-2). Con él, el número de eventos de una orden por pasos **solo depende
    del código**, no de la carga de la máquina."""

    def __init__(self, tick_s: float = TICK_S) -> None:
        self.tick_s = tick_s
        self.now = 0.0
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        self.now += self.tick_s
        return self.now


class _ClockedTime:
    """El módulo ``time`` con otro ``perf_counter``: lo demás, el de verdad."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self.perf_counter = clock

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


@contextmanager
def ticking_clock(tick_s: float, *modules: ModuleType) -> Iterator[TickingClock]:
    """Dentro del bloque, el ``time.perf_counter`` de los ``modules`` (los que miden el presupuesto de cada paso: ``bl.ops.core`` y ``gis.masks.compile``) es un :class:`TickingClock` de ``tick_s`` s.
    Solo cambia el reloj de esos módulos: el resto (las esperas de la base, el plazo de la puerta de procedencia, el cronómetro de la prueba) sigue con el de verdad."""
    clock = TickingClock(tick_s)
    fake = _ClockedTime(clock)
    with ExitStack() as stack:
        for module in modules:
            stack.enter_context(mock.patch.object(module, "time", fake))
        yield clock


@contextmanager
def one_unit_per_event(commands: tuple[type, ...], clocked: tuple[ModuleType, ...], *, tick_s: float = TICK_S) -> Iterator[TickingClock]:
    """Cada evento del temporizador da **un solo paso de una sola unidad**, sin depender del reloj (spec 017, T39; E-2): el presupuesto de las ``commands`` (clases de órdenes por pasos) es
    :data:`ONE_STEP_S` **antes de lanzarlas** —los generadores de ``design`` leen ``STEP_BUDGET_S`` al crearse, y fijarlo en el modal ya en marcha llega tarde: sus pasos agrupaban las
    unidades casi instantáneas **según el reloj** y los eventos de una corrida y de otra no coincidían— y el reloj de los módulos ``clocked`` es un :class:`TickingClock` de ``tick_s`` s."""
    with ExitStack() as stack:
        for command in commands:
            stack.enter_context(mock.patch.object(command, "STEP_BUDGET_S", ONE_STEP_S))
        yield stack.enter_context(ticking_clock(tick_s, *clocked))


def drive(modal: Any, context: Any, *, stop_after: int | None = None) -> tuple[set[str], int]:
    """Un evento del temporizador cada vez hasta que ``modal`` acaba (o hasta ``stop_after``
    eventos): cómo acaba (``RUNNING_MODAL`` si se paró antes) y cuántos eventos llevaba."""
    for index in range(MAX_EVENTS):
        if index == stop_after:
            return {"RUNNING_MODAL"}, index
        state = modal.modal(context, TIMER)
        if state != {"RUNNING_MODAL"}:
            return state, index + 1
    raise AssertionError(f"el modal no acaba en {MAX_EVENTS} eventos")


@dataclass(frozen=True)
class Closed:
    """Lo que hizo el modal en el último evento, con el proyecto ya cerrado."""

    state: set[str]
    """Cómo acabó ese evento (``CANCELLED`` si se paró)."""
    modal: Any
    """El modal de la segunda vez (su ``report_log`` y sus ``_steps``)."""
    events: int
    """Los eventos del cálculo entero, contados la primera vez."""
    asked: int
    """Las veces que pidió «Crear» la segunda vez."""


def close_at_the_last_event(command: type, start: Callable[[], Any], context: Any, *,
                            session: ModuleType, des_ops: ModuleType) -> Closed:
    """Lanza dos veces con ``start()`` (que devuelve el modal en marcha) la orden de la clase
    ``command``, con un paso por evento: la primera, hasta el final, para contar sus eventos (y
    descarta lo que deja); la segunda, hasta el penúltimo evento, y el último con el proyecto de
    la sesión cerrado (``session.current`` sin proyecto). ``AssertionError`` si la primera vez no
    acaba en ``FINISHED``."""
    with mock.patch.object(command, "STEP_BUDGET_S", ONE_STEP_S), \
            mock.patch.object(des_ops, "_ask_confirmation") as ask:
        state, events = drive(start(), context)
        if state != {"FINISHED"}:
            raise AssertionError(f"el cálculo entero acaba en {sorted(state)}")
        des_ops.discard_calculation()
        ask.reset_mock()
        modal = start()
        drive(modal, context, stop_after=events - 1)
        with mock.patch.object(session, "current", return_value=None):  # se cierra el proyecto
            last = modal.modal(context, TIMER)
    return Closed(last, modal, events, ask.call_count)
