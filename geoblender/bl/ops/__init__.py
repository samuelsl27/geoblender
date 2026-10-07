# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores ``GEOBLENDER_OT_<módulo>_<acción>``, uno por fichero de módulo
(``bl/ops/<código>.py``). No calculan: validan, llaman al dominio y presentan el
resultado.

``jobs`` (spec 004) tiene además su propio registro: el seguimiento de los trabajos en
segundo plano (``JobMonitor``), los textos de los trabajos y sus tipos de trabajo.
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes
from . import core, geo, jobs, ui

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): core (spec 002), ui y geo (spec 003; geo: el recorte de la vista, D-1) y
# jobs (spec 004).
classes: tuple[type, ...] = (*core.classes, *ui.classes, *geo.classes, *jobs.classes)


def register() -> None:
    """Registra ``classes`` en orden y después lo propio de ``jobs``; si ya lo están, no
    hace nada. Si ``jobs`` falla, desregistra antes las clases."""
    register_classes(classes)
    try:
        jobs.register()
    except BaseException:
        unregister_classes(classes)
        raise


def unregister() -> None:
    """Deshace lo propio de ``jobs`` y desregistra ``classes`` en orden inverso; omite lo
    que no está registrado."""
    jobs.unregister()
    unregister_classes(classes)
