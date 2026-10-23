# SPDX-License-Identifier: GPL-3.0-or-later
"""Redibujar las dos barras globales de cada ventana, la superior y la de estado (spec 009, T35
y T41; RF-009-10, RF-008-28, RF-010-02; RNF-008-06).

La barra superior y la de estado son áreas globales de la ventana, fuera de
``window.screen.areas`` (``docs/trampas.md`` §5): ``Area.tag_redraw`` no llega a ellas, y un
bucle que busca un área ``TOPBAR`` en ``screen.areas`` no encuentra ninguna. Blender las
redibuja solas cuando la persona pasa el ratón por encima, pero no cuando cambia lo que
enseñan con una orden lanzada desde otra área (F3, un guion, el canal) o desde un
temporizador. :func:`redraw` es el único sitio que lo pide; tiran de él los controles de la
barra superior que cambian sin tocarlos y sus campos de la barra de estado:

- el control 7 y «! n obsoletos» (``bl.ui.provenance.redraw``, spec 008) y Refrescar
  resaltado (``bl.scene.live``, spec 010);
- el control 8 y la versión activa de la barra de estado (``bl.scene.versions.request_redraw``,
  spec 009).

Sin temporizadores ni manejadores: cuesta lo que una asignación y ``status_text_set``.
"""

from __future__ import annotations

import logging

import bpy

from ..props.ui import REDRAW_PROPERTY
from . import statusbar

LOGGER = logging.getLogger("geoblender.bl.ui")


def redraw() -> None:
    """Pide redibujar la barra superior y la de estado de todas las ventanas:

    - la de estado, con ``bl.ui.statusbar.redraw`` (``status_text_set(None)``, salvo en las
      ventanas con un operador modal, cuyo texto de estado es suyo);
    - todas las regiones de todas las ventanas, también las de las dos barras, cambiando
      ``WindowManager.geoblender_redraw``: una propiedad con función ``update``
      (``bl.props.ui.redraw_all_windows``), tras la que Blender avisa a todas ellas
      (``NC_WINDOW``). Se cambia su valor en cada petición: así nunca es la asignación del
      mismo valor. Asignar una propiedad **sin** ``update`` no avisa a nada.

    Un fallo va al registro técnico (lo llaman temporizadores): lo que se enseña no depende de
    quien lo dibuja."""
    try:
        statusbar.redraw()
        manager = getattr(bpy.context, "window_manager", None)
        if manager is not None and hasattr(manager, REDRAW_PROPERTY):
            setattr(manager, REDRAW_PROPERTY, not getattr(manager, REDRAW_PROPERTY))
    except Exception:  # noqa: BLE001 - lo que se enseña no depende de quien lo dibuja
        LOGGER.exception("No se pudo pedir que se redibujen las barras de las ventanas")
