# SPDX-License-Identifier: GPL-3.0-or-later
"""El proyecto de esta sesión de Blender (spec 002; RF-002-06, RF-002-11, RF-002-12;
plan 002 §5.1 y §5.4, «Cerrojo»).

Hay como mucho **un** proyecto abierto por sesión (:func:`current`). Lo dejan aquí los
operadores al crear o abrir (:func:`attach`) y se cierra (:func:`close`: cabecera desde
la base y cerrojo liberado, ``core.project.Project.close``) al cerrar el proyecto, al
abrir otro, al cargar un ``.blend`` de otro proyecto (``bl.scene.georef``), al desactivar
Geoblender (:func:`unregister`) y al salir de Blender (:func:`at_exit`, con ``atexit``).

- **Sesión**: una :class:`~core.sysinfo.SessionInfo` por registro de la extensión
  (equipo, usuario, proceso de Blender y versión de Geoblender del manifiesto).
- **Datos de usuario**: ``bpy.utils.extension_path_user(bl.ADDON_PACKAGE)`` (nunca el
  paquete de un submódulo), calculado al registrar y pasado a ``core`` como ``Path``.
- **Marca de actividad** (RF-002-11): un temporizador **persistente** de 300 s
  (:func:`heartbeat`) mientras el proyecto está en escritura; uno no persistente se
  perdería al abrir otro ``.blend`` y el cerrojo caducaría con la sesión viva.
  ``load_post`` comprueba que sigue registrado (:func:`ensure_heartbeat`). Si el cerrojo
  ya no es de esta sesión, o no se pudo renovar, el proyecto pasa a solo lectura (lo hace
  ``core``), el temporizador se detiene y queda un aviso (RF-002-12).
- **Avisos**: lo que pasa sin un operador que lo cuente (un manejador, el temporizador)
  queda en :func:`take_notices` para la interfaz y en el registro técnico.

En ``blender -b`` los temporizadores no se ejecutan: las pruebas llaman a
:func:`heartbeat` directamente.
"""

from __future__ import annotations

import atexit
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import bpy

from ...core.project.lock import DEFAULT_STALE_MINUTES, HEARTBEAT_INTERVAL_S
from ...core.project.model import ReadOnlyCode
from ...core.sysinfo import SessionInfo, current_session
from ...core.userdata import UserData
from ...core.i18n import tr
from ...core.version import geoblender_version
from .. import ADDON_PACKAGE

if TYPE_CHECKING:
    from ...core.project.session import Project

LOGGER = logging.getLogger("geoblender.bl.scene")
NOTICES_KEPT = 20  # avisos pendientes que se guardan (los más recientes)


class _State:
    """Estado de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.session: SessionInfo | None = None
        self.userdata_root: Path | None = None
        self.project: Project | None = None
        self.notices: list[str] = []


_STATE = _State()


# Sesión y datos de usuario ------------------------------------------------------------


def session() -> SessionInfo:
    """La sesión de este Blender (se crea al registrar, o al pedirla)."""
    if _STATE.session is None:
        _STATE.session = current_session(geoblender_version())
    return _STATE.session


def userdata() -> UserData:
    """Los datos de usuario de la extensión (``extension_path_user(ADDON_PACKAGE)``)."""
    if _STATE.userdata_root is None:
        _STATE.userdata_root = Path(bpy.utils.extension_path_user(ADDON_PACKAGE))
    return UserData(_STATE.userdata_root)


def stale_minutes() -> int:
    """El umbral del cerrojo caducado de las preferencias (``core.lock_stale_minutes``;
    30 min si no se pueden leer)."""
    addon = bpy.context.preferences.addons.get(ADDON_PACKAGE)
    preferences = getattr(addon, "preferences", None)
    value = getattr(getattr(preferences, "core", None), "lock_stale_minutes", None)
    return int(value) if isinstance(value, int) and value > 0 else DEFAULT_STALE_MINUTES


def checkout_dir() -> Path:
    """La carpeta de las copias locales: la de las preferencias (``core.checkout_dir``) o,
    si está vacía, ``checkouts/`` de los datos de usuario (spec 002, D-4). No la crea."""
    addon = bpy.context.preferences.addons.get(ADDON_PACKAGE)
    preferences = getattr(addon, "preferences", None)
    value = getattr(getattr(preferences, "core", None), "checkout_dir", "")
    if isinstance(value, str) and value.strip():
        return Path(bpy.path.abspath(value))
    return userdata().checkouts_dir()


# Avisos -------------------------------------------------------------------------------


def notify(message: str) -> None:
    """Deja un aviso para la interfaz y en el registro técnico."""
    _STATE.notices.append(message)
    del _STATE.notices[:-NOTICES_KEPT]
    LOGGER.warning("%s", message)


def notices() -> tuple[str, ...]:
    """Los avisos pendientes de mostrar (sin vaciarlos)."""
    return tuple(_STATE.notices)


def take_notices() -> list[str]:
    """Los avisos pendientes de mostrar; los vacía."""
    found, _STATE.notices = _STATE.notices, []
    return found


# Proyecto de la sesión ----------------------------------------------------------------


def current() -> Project | None:
    """El proyecto abierto en esta sesión, o ``None``."""
    return _STATE.project


def attach(project: Project) -> tuple[str, ...]:
    """Deja ``project`` (recién creado o abierto) como el proyecto de la sesión: cierra
    antes el que hubiera (RF-002-06), sincroniza las escenas (RF-002-28) y, en
    escritura, arranca la marca de actividad (RF-002-11). Devuelve los avisos de cerrar
    el anterior."""
    warnings: tuple[str, ...] = ()
    if _STATE.project is not None and _STATE.project is not project:
        warnings = close()
    _STATE.project = project
    from . import georef  # georef usa este módulo: se importa al usarlo

    georef.sync_scenes(project)
    ensure_heartbeat()
    return warnings


def close() -> tuple[str, ...]:
    """Cierra el proyecto de la sesión (cabecera desde la base y cerrojo liberado si es
    de esta sesión; en solo lectura no escribe nada) y devuelve los avisos."""
    project = _STATE.project
    _STATE.project = None
    _stop_heartbeat()
    if project is None:
        return ()
    warnings = project.close()
    for message in warnings:
        notify(message)
    return warnings


# Marca de actividad del cerrojo --------------------------------------------------------


def heartbeat() -> float | None:
    """Función del temporizador: renueva la marca del cerrojo y pide la siguiente dentro
    de 300 s; si ya no hay proyecto en escritura, o el cerrojo se perdió o no se pudo
    renovar (el proyecto pasa a solo lectura), se detiene (``None``)."""
    project = _STATE.project
    if project is None or not project.writable:
        return None
    project.heartbeat()
    if project.writable:
        return float(HEARTBEAT_INTERVAL_S)
    if project.read_only_reason is ReadOnlyCode.LOCK_LOST:
        notify(
            tr(
                "Project «{name}»: the lock no longer belongs to this session (another "
                "session forced it or it was deleted); the project is now read-only and "
                "nothing more will be written to it.",
                name=project.name,
            )
        )
    else:
        notify(tr("Project «{name}»: {detail}", name=project.name,
                  detail=project.status.message))
    return None


def ensure_heartbeat() -> None:
    """Registra el temporizador de la marca (persistente) si hay un proyecto en
    escritura y no lo está; si no hay, lo detiene."""
    project = _STATE.project
    if project is None or not project.writable:
        _stop_heartbeat()
        return
    if not bpy.app.timers.is_registered(heartbeat):
        bpy.app.timers.register(
            heartbeat, first_interval=float(HEARTBEAT_INTERVAL_S), persistent=True
        )


def _stop_heartbeat() -> None:
    if bpy.app.timers.is_registered(heartbeat):
        bpy.app.timers.unregister(heartbeat)


# Salida de Blender y registro ----------------------------------------------------------


def at_exit() -> None:
    """Al salir de Blender (``atexit``): cierra el proyecto sin usar ``bpy``, que ya puede
    no estar disponible (RF-002-06)."""
    project = _STATE.project
    _STATE.project = None
    if project is None:
        return
    try:
        project.close()
    except Exception:  # noqa: BLE001 - al salir no hay a quién avisar; va al registro
        LOGGER.exception("No se ha podido cerrar el proyecto al salir de Blender")


def register() -> None:
    """Prepara la sesión (sin leer ningún proyecto) y la función de salida."""
    _STATE.session = current_session(geoblender_version())
    _STATE.userdata_root = Path(bpy.utils.extension_path_user(ADDON_PACKAGE))
    _STATE.notices = []
    atexit.register(at_exit)


def unregister() -> None:
    """Cierra el proyecto de la sesión (libera el cerrojo), detiene el temporizador y
    quita la función de salida (RF-002-06; principio 8)."""
    try:
        close()
    finally:
        _stop_heartbeat()
        atexit.unregister(at_exit)
        _STATE.session = None
        _STATE.userdata_root = None
        _STATE.notices = []
