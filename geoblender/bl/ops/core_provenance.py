# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia en Blender (spec 008; plan 008 §5.1, §5.3.2, §5.4.13 y §5.5; ADR-0025).

- Textos (T44): al registrar, :func:`register` instala en ``core.i18n`` los mensajes de la
  procedencia y de los parámetros (``CATALOG_ES`` de ``core.provenance.messages`` y de
  ``core.params``: los rechazos y avisos de la spec §8, los nombres visibles de las operaciones
  de ``core``, el estado de una entrada, las marcas de una cifra…), para que la interfaz los
  muestre con ``core.i18n.tr`` en el idioma de Geoblender. Sus órdenes tienen ya su
  ``bl_idname`` en el catálogo de la 003 (entrada ``008``): mientras no llegue aquí su clase
  real, la interfaz registra la provisional, que dice «Disponible en 008 · …».
- Carpetas de solo lectura (T45; RF-008-15; S-3 del plan; ADR-0025 §9): :func:`read_only_dirs`
  las da como están ahora (la variable ``GEOBLENDER_READ_ONLY_DIRS`` más la preferencia
  ``core.read_only_folders``), para pasarlas a ``core`` (``check_write_target``, crear, abrir,
  copiar y publicar). Si la lista está vacía (o lleva entradas que no son rutas completas),
  :func:`warn_read_only_dirs` lo avisa **una vez por sesión** (en los avisos del panel del
  proyecto y en el registro técnico): lo llama un temporizador justo después de registrar
  (en el registro aún no se pueden leer las preferencias); el diagnóstico de la instalación
  lo dice siempre (``bl.ui.help``).

Lo demás llega con las tareas siguientes de la fase 7: el registro de las declaraciones de
``core`` y la sesión de la procedencia (T46), el trabajo de hash (T47) y las ayudas para los
módulos (T48); los operadores de §5.3.2, con los paneles (fase 8).

``core.i18n`` no tiene cómo quitar traducciones: :func:`unregister` las deja (como los
trabajos de la 004), y volver a registrar las instala otra vez sin cambiar nada.
"""

from __future__ import annotations

from typing import Any

import bpy

from ...core import i18n, params
from ...core.inputs.guard import read_only_warnings
from ...core.paths import ReadOnlyDirs
from ...core.provenance import messages
from .. import ADDON_PACKAGE
from ..props.core import read_only_dirs_of
from ..scene import project_session

classes: tuple[type, ...] = ()


class _State:
    """Estado de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.read_only_checked = False  # ya se miró (y, si tocaba, se avisó) en esta sesión


_STATE = _State()


# Carpetas de solo lectura -----------------------------------------------------------------


def _core_preferences() -> Any:
    """El grupo ``core`` de las preferencias de la extensión, o ``None`` si aún no están (una
    habilitación sin ``default_set``, o durante el registro)."""
    addon = bpy.context.preferences.addons.get(ADDON_PACKAGE)
    return getattr(getattr(addon, "preferences", None), "core", None)


def read_only_dirs() -> ReadOnlyDirs:
    """Las carpetas de solo lectura de ahora (RF-008-15): las de la variable
    ``GEOBLENDER_READ_ONLY_DIRS`` más las de la preferencia ``core.read_only_folders``, leídas en
    cada llamada (una preferencia cambiada vale en la orden siguiente)."""
    return read_only_dirs_of(_core_preferences())


def warn_read_only_dirs() -> None:
    """Una vez por sesión (S-3): si no hay ninguna carpeta de solo lectura, o alguna entrada no
    es una ruta completa, deja cada aviso en los de la sesión (``project_session.notify``: el
    panel del proyecto y el registro técnico). Las siguientes llamadas no hacen nada. Es el
    temporizador de :func:`register` (sin repetición: devuelve ``None``)."""
    if _STATE.read_only_checked:
        return None
    _STATE.read_only_checked = True
    for text in read_only_warnings(read_only_dirs(), i18n.language()):
        project_session.notify(text)
    return None


def forget_read_only_warning() -> None:
    """Olvida que ya se miró en esta sesión (al desregistrar; y en las pruebas)."""
    _STATE.read_only_checked = False


# Registro ---------------------------------------------------------------------------------


def register() -> None:
    """Instala los textos de la procedencia y de los parámetros en ``core.i18n`` y pone el
    temporizador del aviso de las carpetas de solo lectura (persistente, para que no lo quite
    abrir otro ``.blend`` antes de que se dispare); idempotente."""
    i18n.install(messages.CATALOG_ES)
    i18n.install(params.CATALOG_ES)
    forget_read_only_warning()
    if not bpy.app.timers.is_registered(warn_read_only_dirs):
        bpy.app.timers.register(warn_read_only_dirs, first_interval=0.0, persistent=True)


def unregister() -> None:
    """Quita el temporizador del aviso (si aún no se disparó) y olvida que se avisó (la
    sesión siguiente avisa otra vez); las traducciones instaladas se quedan; idempotente."""
    if bpy.app.timers.is_registered(warn_read_only_dirs):
        bpy.app.timers.unregister(warn_read_only_dirs)
    forget_read_only_warning()
