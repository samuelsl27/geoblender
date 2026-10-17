# SPDX-License-Identifier: GPL-3.0-or-later
"""Las filas de los paneles de la vista regenerable (spec 010; RF-010-06, RF-010-07, RF-010-08;
plan 010 §5.1 y §5.2).

``WindowManager.geoblender_view_panels`` (:class:`GEOBLENDER_PG_core_view_panels`) guardará lo
que dibujan N ▸ Proyecto ▸ Elemento activo e Inventario y la ventana de «Cifras de la
selección»: filas de texto ya presentado, como las de la procedencia (``bl/props/provenance.py``;
plan 008 D16). Es una **vista** que se regenera desde el proyecto, nunca la fuente; vive en
``WindowManager``, que Blender no guarda en el ``.blend`` de ``scenes/`` (spec 002 D-11). No se
llama ``geoblender_views``: ese nombre ya es ``Scene.geoblender_views``, las vistas guardadas de la
003 (``bl.props.ui.VIEWS_PROPERTY``).

Spec 010, T07: el grupo, aún sin filas (las ponen los paneles de la T14 a la T16).
"""

from __future__ import annotations

import bpy
from bpy.props import PointerProperty

# Nombre de la propiedad de WindowManager (la usan los paneles de la vista, spec 010).
WINDOW_MANAGER_PROPERTY = "geoblender_view_panels"
_STATIC: set[str] = set()  # ni animable ni nada más


class GEOBLENDER_PG_core_view_panels(bpy.types.PropertyGroup):
    """Lo que dibujan los paneles de la vista regenerable (spec 010): una vista del proyecto,
    regenerada desde él."""


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_PG_core_view_panels,)


def register() -> None:
    """Pone ``WindowManager.geoblender_view_panels`` (las clases ya están registradas)."""
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_core_view_panels, options=_STATIC))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_view_panels`` (antes de desregistrar las clases); sin
    ella, nada."""
    if hasattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY):
        delattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY)
