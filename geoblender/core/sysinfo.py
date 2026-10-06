# SPDX-License-Identifier: GPL-3.0-or-later
"""Sesión de Geoblender, equipo, usuario y procesos (spec 002; RF-002-04, RF-002-09;
plan 002 §5.1 y §5.4).

El cerrojo del proyecto guarda quién lo tiene: sesión, equipo, usuario, proceso y versión
de Geoblender. Un cerrojo del mismo equipo cuyo proceso ya no está en ejecución es
huérfano (Blender se cerró de golpe) y se puede sustituir.

:func:`pid_alive` en Windows usa ``OpenProcess`` y ``GetExitCodeProcess`` con ``ctypes``:
``os.kill(pid, 0)`` no comprueba si el proceso vive, lo **termina** (en Windows ``os.kill``
con una señal que no es de consola llama a ``TerminateProcess``; docs/trampas.md §2). Un
proceso que existe pero al que no se puede consultar cuenta como vivo: nunca se da por
huérfano lo que no se ha podido comprobar.
"""

from __future__ import annotations

import getpass
import os
import platform
import socket
import sys
from dataclasses import dataclass

from .ids import new_uid

UNKNOWN = "desconocido"
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5


@dataclass(frozen=True)
class SessionInfo:
    """Una sesión de Geoblender: la de este proceso o la que se lee de un cerrojo."""

    session_uid: str
    host: str
    user: str
    pid: int
    geoblender_version: str

    @property
    def user_host(self) -> str:
        """«usuario@equipo», como se registra en ``gb_event``."""
        return f"{self.user}@{self.host}"


def host_name() -> str:
    """El nombre de este equipo."""
    name = platform.node() or socket.gethostname() or os.environ.get("COMPUTERNAME")
    return name or UNKNOWN


def user_name() -> str:
    """El usuario de Windows de esta sesión."""
    try:
        return getpass.getuser() or UNKNOWN
    except (OSError, KeyError, ImportError):
        return os.environ.get("USERNAME") or UNKNOWN


def current_session(geoblender_version: str) -> SessionInfo:
    """Una sesión nueva para este proceso (uid nuevo cada vez)."""
    return SessionInfo(new_uid(), host_name(), user_name(), os.getpid(), geoblender_version)


def _pid_alive_windows(pid: int) -> bool:
    import ctypes  # solo en Windows
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Existe pero no nos deja consultarlo: vivo. Cualquier otro error: no existe.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True  # no se pudo comprobar: no se da por terminado
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    """Verdadero si el proceso ``pid`` de este equipo sigue en ejecución."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 or pid > 2**32 - 1:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)  # en POSIX, la señal 0 solo comprueba
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
