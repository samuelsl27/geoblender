# SPDX-License-Identifier: GPL-3.0-or-later
"""Puerta de modo (spec 003; RF-003-04, RF-003-19; plan 003 §5.4, 3, DT3; AT §1).

Una ventana está en modo Geoblender cuando su espacio de trabajo activo tiene
``WorkSpace.geoblender_mode`` (CW §1). La exigencia de modo **solo** se aplica a lo que se
lanza desde una Vista 3D, donde viven los atajos: allí, en modo Blender, el ``poll`` de un
comando de Geoblender falla y Blender trata la tecla como siempre. Desde la barra superior
(«Geoblender ▾»), F3 sobre otro editor o un script, el ``poll`` pasa: así los comandos
disponibles se ejecutan también en modo Blender (BS §4).

Contrato 2 del plan: los operadores con atajo en el mapa «3D View» llaman a
:func:`in_geoblender_scope` (o a :func:`poll`) en su ``poll``.
"""

from __future__ import annotations

from typing import Any

from ...core.i18n import tr
from ..props.ui import WORKSPACE_PROPERTY


def is_geoblender_workspace(workspace: Any) -> bool:
    """Verdadero si ``workspace`` es un espacio de trabajo de Geoblender (marcado)."""
    return bool(workspace is not None and getattr(workspace, WORKSPACE_PROPERTY, False))


def in_geoblender_scope(context: Any) -> bool:
    """Verdadero salvo cuando se lanza desde una Vista 3D de una ventana en modo
    Blender (``context.area`` es una Vista 3D y su espacio de trabajo no está
    marcado)."""
    area = getattr(context, "area", None)
    if area is None or getattr(area, "type", "") != "VIEW_3D":
        return True
    return is_geoblender_workspace(getattr(context, "workspace", None))


def poll(cls: Any, context: Any) -> bool:
    """El ``poll`` de un comando de Geoblender con atajo en la Vista 3D: la puerta de
    modo, con su explicación si falla."""
    if in_geoblender_scope(context):
        return True
    cls.poll_message_set(tr("Only in Geoblender mode (Ctrl+F10) or from Geoblender ▾"))
    return False
