# SPDX-License-Identifier: GPL-3.0-or-later
"""Geoblender: extensión de Blender 5.2 que lo convierte en un software minero.

La identidad y la versión viven en ``blender_manifest.toml`` (fuente única; no hay
``bl_info``). Este módulo no importa nada a nivel de módulo (ARQ-03): la capa de
presentación ``bl`` se importa dentro de ``register()`` y ``unregister()`` (ARQ-02),
para que el núcleo y el dominio se puedan importar sin Blender (ADR-0004).
"""


def register() -> None:
    """Registra Geoblender en Blender: importa ``bl`` en este momento y no antes."""
    from . import bl

    bl.register()


def unregister() -> None:
    """Deshace todo lo que hizo :func:`register`, en orden inverso."""
    from . import bl

    bl.unregister()
