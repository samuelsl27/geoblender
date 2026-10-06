# SPDX-License-Identifier: GPL-3.0-or-later
"""Único sitio con las diferencias entre versiones de Blender (principio 8).

Todo lo que cambia entre versiones de la API de Python de Blender (p. ej. las entradas
del modificador de Geometry Nodes en 5.2) se envuelve aquí, con su prueba en
``tests/blender/``, y el resto de ``bl`` lo usa a través de este módulo.

- :func:`topbar_patchable` (spec 003; RF-003-05): si la barra superior tiene la forma
  que sustituye la interfaz de Geoblender (``tests/blender/test_topbar_draw.py``).
"""

from __future__ import annotations

import inspect

import bpy


def blender_version() -> tuple[int, int, int]:
    """Versión de Blender en ejecución, p. ej. ``(5, 2, 1)`` (``bpy.app.version``)."""
    major, minor, patch = bpy.app.version
    return int(major), int(minor), int(patch)


# Barra superior (spec 003; RF-003-05; ADR-0012; CW §5) ---------------------------------

TOPBAR_HEADER = "TOPBAR_HT_upper_bar"
TOPBAR_MENUS = "TOPBAR_MT_editor_menus"


def topbar_patchable(header: type | None = None) -> bool:
    """Verdadero si la barra superior tiene la forma que Geoblender sustituye
    (ADR-0012, técnica B): un ``draw_left`` que se llama como ``draw_left(self,
    context)`` y un ``draw`` cuyo código lo llama (Blender 5.2). Si falta, tiene otra
    firma o no se puede comprobar, la interfaz usa el respaldo de compatibilidad
    (técnica A: añadir el conmutador y «Geoblender ▾» tras la Ayuda de Blender)."""
    cls = getattr(bpy.types, TOPBAR_HEADER, None) if header is None else header
    function = getattr(cls, "draw_left", None)
    if cls is None or not callable(function):
        return False
    try:
        inspect.signature(function).bind(None, None)
        source = inspect.getsource(cls.draw)
    except (TypeError, ValueError, OSError):
        return False
    return "draw_left" in source
