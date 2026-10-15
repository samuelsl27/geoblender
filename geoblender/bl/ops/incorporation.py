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
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import bpy

from ...core.i18n import tr

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


@dataclass(eq=False)
class _Incorporation:
    """Una incorporación en la cola: su operación, el nombre que enseña la barra de estado, sus
    pasos y lo hecho."""

    uid: str
    name: str
    steps: Iterator[float]
    done: float = 0.0


class StepQueue:
    """Las incorporaciones por pasos de un módulo, por orden de llegada, y su temporizador."""

    def __init__(self) -> None:
        self._items: list[_Incorporation] = []
        self.timer: Callable[[], float | None] = self.tick
        """La función del temporizador: la misma siempre (Blender la reconoce por el
        objeto)."""

    def add(self, uid: str, name: str, steps: Iterator[float]) -> None:
        """Pone en cola la incorporación ``steps`` de la operación ``uid`` (``name``, el
        nombre que enseña la barra de estado) y registra el temporizador si no lo estaba."""
        self._items.append(_Incorporation(uid, name, steps))
        if not bpy.app.timers.is_registered(self.timer):
            bpy.app.timers.register(self.timer, first_interval=TICK_S, persistent=True)

    def pending(self) -> list[str]:
        """Las operaciones cuya incorporación espera en la cola, en orden."""
        return [item.uid for item in self._items]

    def tick(self) -> float | None:
        """Un paso de la primera de la cola y su avance en la barra de estado; devuelve
        cuándo volver (``None``: no queda ninguna). Un paso que falla (un error del programa:
        los pasos tratan los suyos) la para, queda en el registro y sigue la siguiente."""
        if not self._items:
            return None
        current = self._items[0]
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
        status_text(tr("Adding «{name}» to the project… {percent} %", name=shown.name,
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
