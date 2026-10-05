# SPDX-License-Identifier: GPL-3.0-or-later
"""Único sitio con las diferencias entre versiones de Blender (principio 8).

Todo lo que cambia entre versiones de la API de Python de Blender (p. ej. las entradas
del modificador de Geometry Nodes en 5.2) se envuelve aquí, con su prueba en
``tests/blender/``, y el resto de ``bl`` lo usa a través de este módulo.
"""

from __future__ import annotations

import bpy


def blender_version() -> tuple[int, int, int]:
    """Versión de Blender en ejecución, p. ej. ``(5, 2, 1)`` (``bpy.app.version``)."""
    major, minor, patch = bpy.app.version
    return int(major), int(minor), int(patch)
