# SPDX-License-Identifier: GPL-3.0-or-later
"""Las filas de los paneles de la vista regenerable (spec 010; RF-010-06, RF-010-07, RF-010-08;
plan 010 §5.1 y §5.2).

``WindowManager.geoblender_view_panels`` (:class:`GEOBLENDER_PG_core_view_panels`) guarda lo
que dibujan N ▸ Proyecto ▸ Elemento activo e Inventario y la ventana de «Cifras de la
selección»: filas de texto ya presentado, como las de la procedencia (``bl/props/provenance.py``;
plan 008 D16). Es una **vista** que se regenera desde el proyecto, nunca la fuente; vive en
``WindowManager``, que Blender no guarda en el ``.blend`` de ``scenes/`` (spec 002 D-11). No se
llama ``geoblender_views``: ese nombre ya es ``Scene.geoblender_views``, las vistas guardadas de la
003 (``bl.props.ui.VIEWS_PROPERTY``).

Spec 010, T07: el grupo, aún sin filas (las ponen los paneles de la T14 a la T16).

Spec 010, T14 (RF-010-06; plan A6, D-16): la ficha de «Elemento activo» (``card``, filas
:class:`GEOBLENDER_PG_core_card_row`), del dato ``card_uid`` del proyecto ``card_project``
(``card_found`` falso si el proyecto ya no lo tiene), que ``bl.ui.view_panels`` lee al cambiar
el objeto activo o el proyecto. Las propiedades de las filas no tienen nombre ni descripción: no
se dibujan con los suyos (como las de la procedencia). Ninguna se anima.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty, StringProperty

# Nombre de la propiedad de WindowManager (la usan los paneles de la vista, spec 010).
WINDOW_MANAGER_PROPERTY = "geoblender_view_panels"
_STATIC: set[str] = set()  # ni animable ni nada más


class GEOBLENDER_PG_core_card_row(bpy.types.PropertyGroup):
    """Una línea de la ficha de «Elemento activo» (spec 010, RF-010-06), ya presentada:
    ``kind`` dice cómo se dibuja (``bl.ui.view_panels``: su nombre, un dato de la ficha, el
    título de un apartado, una entrada o un derivado, una cifra, «ninguno» o el lugar de «al
    día», que se dibuja con el objeto activo), su texto en el idioma de Geoblender al leerla, su
    icono, si va en alerta y el uid de lo que nombra (una entrada o un dato)."""

    kind: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    text: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    icon: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    alert: BoolProperty(options=_STATIC)  # type: ignore[valid-type]
    uid: StringProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_view_panels(bpy.types.PropertyGroup):
    """Lo que dibujan los paneles de la vista regenerable (spec 010): una vista del proyecto,
    regenerada desde él."""

    # Elemento activo (T14; RF-010-06).
    card: CollectionProperty(type=GEOBLENDER_PG_core_card_row,  # type: ignore[valid-type]
                             options=_STATIC)
    card_uid: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    card_project: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    card_found: BoolProperty(options=_STATIC)  # type: ignore[valid-type]


# En orden de registro (la fila, antes del grupo que la usa).
classes: tuple[type, ...] = (GEOBLENDER_PG_core_card_row, GEOBLENDER_PG_core_view_panels)


def register() -> None:
    """Pone ``WindowManager.geoblender_view_panels`` (las clases ya están registradas)."""
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_core_view_panels, options=_STATIC))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_view_panels`` (antes de desregistrar las clases); sin
    ella, nada."""
    if hasattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY):
        delattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY)
