# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia en Blender (spec 008; plan 008 §5.1, §5.3.2 y §5.5; ADR-0025).

Hoy (T44), los textos: al registrar, :func:`register` instala en ``core.i18n`` los mensajes de
la procedencia y de los parámetros (``CATALOG_ES`` de ``core.provenance.messages`` y de
``core.params``: los rechazos y avisos de la spec §8, los nombres visibles de las operaciones
de ``core``, el estado de una entrada, las marcas de una cifra…), para que la interfaz los
muestre con ``core.i18n.tr`` en el idioma de Geoblender. Sus órdenes tienen ya su
``bl_idname`` en el catálogo de la 003 (entrada ``008``): mientras no llegue aquí su clase
real, la interfaz registra la provisional, que dice «Disponible en 008 · …».

Lo demás llega con las tareas siguientes de la fase 7: el registro de las declaraciones de
``core`` y la sesión de la procedencia (T46), el trabajo de hash (T47) y las ayudas para los
módulos (T48); los operadores de §5.3.2, con los paneles (fase 8).

``core.i18n`` no tiene cómo quitar traducciones: :func:`unregister` las deja (como los
trabajos de la 004), y volver a registrar las instala otra vez sin cambiar nada.
"""

from __future__ import annotations

from ...core import i18n, params
from ...core.provenance import messages

classes: tuple[type, ...] = ()


def register() -> None:
    """Instala los textos de la procedencia y de los parámetros en ``core.i18n``;
    idempotente."""
    i18n.install(messages.CATALOG_ES)
    i18n.install(params.CATALOG_ES)


def unregister() -> None:
    """Nada que deshacer todavía (las traducciones instaladas se quedan); idempotente."""
