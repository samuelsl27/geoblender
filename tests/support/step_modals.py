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

from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
"""Un evento del temporizador del modal."""
ONE_STEP_S = 1e-9
"""El presupuesto de cada evento con el que el modal da un solo paso."""
MAX_EVENTS = 20_000


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
