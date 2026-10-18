# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores ``GEOBLENDER_OT_<módulo>_<acción>``, uno por fichero de módulo
(``bl/ops/<código>.py``). No calculan: validan, llaman al dominio y presentan el
resultado.

``jobs`` (spec 004) tiene además su propio registro: el seguimiento de los trabajos en
segundo plano (``JobMonitor``), los textos de los trabajos y sus tipos de trabajo. También
``core_provenance`` (spec 008): los textos de la procedencia y de los parámetros.

``gis`` (spec 006) registra lo que la topografía declara a las specs 004 y 008, después de lo
de ``core``. ``dh`` (spec 005), lo de los sondeos (sus parámetros, sus lectores de contenido,
sus tipos de trabajo, sus operaciones y sus importadores; T24), después de lo de ``gis``; sus
órdenes, en ``classes``, después de las de ``gis``.

``io`` (spec 006, T32): «Importar un fichero» y su manejador de ficheros (soltar en la vista).

``views`` (spec 010): las órdenes de la vista regenerable (T11: Refrescar las vistas desde el
proyecto, F5), después de las de ``core``.

``versions`` (spec 009): las órdenes de las versiones (T18: Fijar la versión activa), después de
las de ``core_provenance``.
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes
from . import core, core_provenance, dh, geo, gis, io, jobs, ui, versions, views

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): core (spec 002) y views (spec 010), ui y geo (spec 003; geo: el recorte de la
# vista, D-1), jobs (spec 004), core_provenance (spec 008) y versions (spec 009).
classes: tuple[type, ...] = (*core.classes, *views.classes, *ui.classes, *geo.classes,
                             *jobs.classes, *core_provenance.classes, *versions.classes)

# Los de la topografía (spec 006) y los de los sondeos (spec 005), después.
classes += gis.classes
classes += dh.classes

# «Importar un fichero» y su manejador (spec 006, T32), que abre los de la topografía.
classes += io.classes


def register() -> None:
    """Registra ``classes`` en orden y después lo propio de ``core_provenance`` y de
    ``jobs``; si ya lo están, no hace nada. Si uno de los dos falla, deshace lo anterior
    antes de propagar el error. Después, lo de ``gis`` y lo de ``dh``: si falla, lo deshace
    todo."""
    register_classes(classes)
    try:
        core_provenance.register()
        jobs.register()
    except BaseException:
        core_provenance.unregister()
        unregister_classes(classes)
        raise
    try:
        gis.register()
        dh.register()
    except BaseException:
        unregister()
        raise


def unregister() -> None:
    """Deshace lo propio de ``dh``, de ``gis``, de ``jobs`` y de ``core_provenance`` y
    desregistra ``classes`` en orden inverso; omite lo que no está registrado."""
    dh.unregister()
    gis.unregister()
    jobs.unregister()
    core_provenance.unregister()
    unregister_classes(classes)
