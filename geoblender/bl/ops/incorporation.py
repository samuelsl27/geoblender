# SPDX-License-Identifier: GPL-3.0-or-later
"""Una cola de incorporaciones por pasos con su temporizador (spec 005, T24; RNF-005-06; plan
005 §5.6.7; como la de la topografía, spec 006, T50).

Lo que un trabajo deja en su carpeta entra en el proyecto **por pasos** desde un temporizador
de Blender: cada incorporación es un generador que da su avance (0–1) tras cada paso (leer lo
que dejó el trabajo, unas filas, la transacción corta del final, un trozo del original…), de
décimas de segundo como mucho, y entre dos llamadas Blender redibuja la interfaz y la barra de
estado («Incorporando «…» al proyecto… n %»). Lo largo (los hashes, las filas) lo hizo ya el
trabajo, con su avance y su cancelación.

:class:`StepQueue` es una cola de esas, con su temporizador (:attr:`StepQueue.timer`, el mismo
objeto siempre: Blender reconoce un temporizador por su función). Los sondeos tienen la suya
(``bl/ops/dh.py``), aparte de la de la topografía (``bl/ops/gis.py``), que no cambia; el que
la crea la vacía al desregistrar (:meth:`StepQueue.drop`).

:class:`RecomputeSteps` son los pasos de lo que recalcula «Recalcular lo obsoleto» (spec 008,
RF-008-26) en la cola de un módulo: la cubicación y la verificación (``bl/ops/res.py``) y las
máscaras de las restricciones (``bl/ops/gis.py``, spec 012, T21).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import bpy

from ...core.errors import GeoblenderError
from ...core.i18n import language, translate
from ...core.project.model import Progress
from ...core.provenance.operations import CANCEL_REASON_PREFIX, failure_reason

LOGGER = logging.getLogger("geoblender.bl.ops")
TICK_S = 0.0
"""Lo que espera el temporizador entre dos pasos: nada (Blender redibuja entre dos llamadas)."""


def status_text(text: str | None) -> None:
    """El aviso en la barra de estado de cada ventana (``None`` lo quita)."""
    manager = getattr(bpy.context, "window_manager", None)
    for window in list(getattr(manager, "windows", ()) or ()):
        workspace = getattr(window, "workspace", None)
        if workspace is None:
            continue
        try:
            workspace.status_text_set(text)
        except (RuntimeError, TypeError):
            LOGGER.debug("Sin barra de estado en una ventana", exc_info=True)


ADDING = "Adding «{name}» to the project… {percent} %"
"""Lo que dice la barra de estado de una incorporación (``msgid`` con ``name`` y ``percent``)."""


@dataclass(eq=False)
class _Incorporation:
    """Una incorporación en la cola: su operación, el nombre que enseña la barra de estado, sus
    pasos, lo hecho y el texto de la barra de estado (``msgid``)."""

    uid: str
    name: str
    steps: Iterator[float]
    done: float = 0.0
    status: str = ADDING
    started: bool = False


class StepQueue:
    """Las incorporaciones por pasos de un módulo, por orden de llegada, y su temporizador."""

    def __init__(self) -> None:
        self._items: list[_Incorporation] = []
        self.timer: Callable[[], float | None] = self.tick
        """La función del temporizador: la misma siempre (Blender la reconoce por el
        objeto)."""

    def add(self, uid: str, name: str, steps: Iterator[float], *,
            status: str = ADDING) -> None:
        """Pone en cola la incorporación ``steps`` de la operación ``uid`` (``name``, el
        nombre que enseña la barra de estado con el texto ``status``, un ``msgid`` con
        ``name`` y ``percent``: por defecto, «Incorporando «…» al proyecto… n %»; spec 005,
        T29: otros pasos de la cola, como cargar la vista) y registra el temporizador si no lo
        estaba."""
        self._items.append(_Incorporation(uid, name, steps, status=status))
        if not bpy.app.timers.is_registered(self.timer):
            bpy.app.timers.register(self.timer, first_interval=TICK_S, persistent=True)

    def pending(self) -> list[str]:
        """Las operaciones cuya incorporación espera en la cola, en orden."""
        return [item.uid for item in self._items]

    def waiting(self, uid: str) -> bool:
        """Si una incorporación de ``uid`` espera en la cola sin haber dado aún ningún paso
        (spec 005, T30: una recarga de la vista que, al empezar, ya leerá la representación
        de ese momento)."""
        return any(item.uid == uid and not item.started for item in self._items)

    def tick(self) -> float | None:
        """Un paso de la primera de la cola y su avance en la barra de estado; devuelve
        cuándo volver (``None``: no queda ninguna). Un paso que falla (un error del programa:
        los pasos tratan los suyos) la para, queda en el registro y sigue la siguiente."""
        if not self._items:
            return None
        current = self._items[0]
        current.started = True
        try:
            current.done = float(next(current.steps))
        except StopIteration:
            self._items.pop(0)
        except Exception:  # noqa: BLE001 - los pasos tratan sus errores: esto es del programa
            LOGGER.exception("La incorporación de «%s» (%s) se ha parado", current.name,
                             current.uid)
            self._items.pop(0)
            _close(current)
        if not self._items:
            status_text(None)
            return None
        shown = self._items[0]
        status_text(translate(language(), shown.status, name=shown.name,
                              percent=int(100 * min(max(shown.done, 0.0), 1.0))))
        return TICK_S

    def drop(self) -> None:
        """Olvida las incorporaciones en cola (al desregistrar): cada una se cierra sin dar ni
        un paso más (su operación sigue «en curso», como las que olvida la 008) y se quita el
        temporizador."""
        shown = bool(self._items)
        while self._items:
            _close(self._items.pop(0))
        if bpy.app.timers.is_registered(self.timer):
            bpy.app.timers.unregister(self.timer)
        if shown:
            status_text(None)


def _close(item: _Incorporation) -> None:
    close = getattr(item.steps, "close", None)
    if callable(close):
        close()


# --- Los pasos de un recálculo (spec 011, T19; spec 012, T21: D-19) ------------------------------

RECOMPUTING = "Recomputing «{name}»… {percent} %"
"""Lo que dice la barra de estado de unos pasos de recálculo (``msgid`` con ``name`` y
``percent``)."""
DROPPED_REASON = CANCEL_REASON_PREFIX + "se desactivó Geoblender antes de empezar"
"""El motivo de una operación cuyos pasos esperaban en la cola sin haber empezado al
desactivar Geoblender."""


def end_operation(stop: Callable[[str], None], reason: str) -> None:
    """Deja la operación terminada con ``stop`` (``fail`` o ``cancel`` de su ``OperationHandle``)
    y ``reason``; si ya terminó (sus pasos lo hicieron) o no se puede escribir, lo deja en el
    registro técnico."""
    try:
        stop(reason)
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.debug("La operación ya había terminado o no se pudo registrar cómo terminó",
                     exc_info=True)


class RecomputeSteps:
    """Los pasos de una operación que recalcula «Recalcular lo obsoleto» en la cola de un módulo
    (``res``, ``gis``): cada uno da su avance (0–1). Si fallan, la operación queda «fallida» con
    el motivo y se acaban; al cerrarlos (desregistrar), los empezados se cierran (su operación la
    cancelan ellos) y, si no empezaron, la operación queda «cancelada» con
    :data:`DROPPED_REASON`. ``report`` recibe el resultado del último paso (el que lleva uno) y
    lleva sus avisos al registro de Blender."""

    def __init__(self, handle: Any, name: str, steps: Iterator[Progress], *,
                 report: Callable[[object], None] | None = None) -> None:
        self._handle = handle
        self._name = name
        self._steps = steps
        self._report = report
        self._started = False
        self._finished = False

    def __iter__(self) -> RecomputeSteps:
        return self

    def __next__(self) -> float:
        if self._finished:
            raise StopIteration
        self._started = True
        try:
            step = next(self._steps)
        except StopIteration:
            self._finished = True
            raise
        except Exception as error:  # noqa: BLE001 - la operación queda fallida, sigue la cola
            self._finished = True
            LOGGER.exception("El recálculo de «%s» (%s) se ha parado", self._name,
                             self._handle.uid)
            end_operation(self._handle.fail, failure_reason(error))
            raise StopIteration from None
        if step.result is not None and self._report is not None:
            self._report(step.result)
        return step.done / step.total if step.total else 0.0

    def close(self) -> None:
        """Cierra los pasos (desregistrar): véase la clase."""
        if not self._started and not self._finished:
            end_operation(self._handle.cancel, DROPPED_REASON)
        self._finished = True
        close = getattr(self._steps, "close", None)
        if callable(close):
            close()
