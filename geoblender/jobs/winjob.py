# SPDX-License-Identifier: GPL-3.0-or-later
"""*Job Object* de Windows para los workers en proceso aparte (spec 004; RF-004-10,
RF-004-13; plan 004 §5.1, §5.3.3, §5.4.5 y §6).

El lanzador asigna cada worker, justo después de lanzarlo, a su propio :class:`JobObject`,
creado con ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``:

- los procesos que lance el worker (el ``pip`` de la instalación del motor, el
  ``powershell.exe`` de la 005) entran en él solos: heredan su *Job Object*;
- :meth:`JobObject.terminate` (``TerminateJobObject``) termina el worker **y todos sus
  descendientes** de una vez: es lo que hace el lanzador al vencer el plazo de gracia de una
  cancelación (RF-004-10). ``Popen.kill`` solo terminaría el worker, y sus hijos quedarían
  huérfanos;
- al cerrarse el último *handle* del *Job Object* se termina lo que quede dentro: lo hace
  :meth:`JobObject.close` y lo hace Windows si Blender muere (RF-004-13).

El *handle* no es heredable (se crea sin atributos de seguridad), así que ningún worker lo
recibe y no puede mantener vivo su propio *Job Object*.

Solo Windows (``ctypes``, ``kernel32``): en otro sistema :func:`supported` es falso y
:class:`JobObject` da :class:`OSError`.
"""

from __future__ import annotations

import ctypes
import functools
import sys
import threading
from types import TracebackType
from typing import Any

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x0000_2000
"""Al cerrarse el último *handle* del *Job Object*, se terminan sus procesos."""

STILL_ACTIVE = 259
"""El código de salida que Windows da a un proceso vivo: nunca se usa para terminar uno
(se confundiría con «sigue vivo»)."""
_MAX_DWORD = 2**32 - 1
MAX_EXIT_CODE = _MAX_DWORD

_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100


def supported() -> bool:
    """Si este sistema tiene *Job Objects* (solo Windows)."""
    return sys.platform == "win32"


class JobObject:
    """Un *Job Object* de Windows con ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` para un worker
    y sus descendientes. :class:`OSError` si Windows no lo crea (o no es Windows).

    Se usa desde un solo hilo (el del lanzador); sus métodos son además seguros entre
    hilos. Usarlo después de :meth:`close` para asignar o contar procesos es un error de
    programación (:class:`ValueError`)."""

    __slots__ = ("_handle", "_lock")

    def __init__(self) -> None:
        if not supported():
            raise OSError("los Job Objects solo existen en Windows")
        api = _kernel32()
        handle = api.CreateJobObjectW(None, None)
        if not handle:
            raise _last_error()
        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            error = _last_error()
            api.CloseHandle(handle)
            raise error
        self._handle: int | None = handle
        self._lock = threading.Lock()

    @property
    def closed(self) -> bool:
        """Si ya se cerró (y con ello se terminó lo que tenía dentro)."""
        return self._handle is None

    def assign(self, pid: int) -> None:
        """Mete el proceso ``pid`` en el *Job Object*; los procesos que lance después
        entran solos. :class:`OSError` si Windows no lo permite (el proceso ya no existe, una
        directiva lo impide…)."""
        if isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid <= _MAX_DWORD:
            raise ValueError(f"{pid!r} no es un número de proceso")
        api = _kernel32()
        with self._lock:
            handle = self._open_handle()
            process = api.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            if not process:
                raise _last_error()
            try:
                if not api.AssignProcessToJobObject(handle, process):
                    raise _last_error()
            finally:
                api.CloseHandle(process)

    def terminate(self, exit_code: int = 1) -> bool:
        """Termina todos los procesos del *Job Object* (el worker y sus descendientes) con
        el código de salida ``exit_code``: ``TerminateJobObject`` (RF-004-10). Devuelve
        ``False``, sin hacer nada, si ya estaba cerrado (y con ello terminado); otra vez sobre
        uno ya vacío no falla. :class:`OSError` si Windows no lo termina."""
        if (isinstance(exit_code, bool) or not isinstance(exit_code, int)
                or not 0 <= exit_code <= MAX_EXIT_CODE or exit_code == STILL_ACTIVE):
            raise ValueError(
                f"{exit_code!r} no vale como código de salida (0–{MAX_EXIT_CODE}, salvo "
                f"{STILL_ACTIVE})"
            )
        with self._lock:
            if self._handle is None:
                return False
            if not _kernel32().TerminateJobObject(self._handle, exit_code):
                raise _last_error()
            return True

    def active_processes(self) -> int:
        """Cuántos procesos siguen vivos dentro del *Job Object*."""
        info = _BasicAccountingInformation()
        with self._lock:
            handle = self._open_handle()
            if not _kernel32().QueryInformationJobObject(
                handle, _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION, ctypes.byref(info),
                ctypes.sizeof(info), None,
            ):
                raise _last_error()
        return int(info.ActiveProcesses)

    def close(self) -> None:
        """Cierra su *handle*: con ``KILL_ON_JOB_CLOSE``, Windows termina lo que quede
        dentro (RF-004-13). Idempotente."""
        with self._lock:
            handle, self._handle = self._handle, None
        if handle is not None:
            _kernel32().CloseHandle(handle)

    def __enter__(self) -> JobObject:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"JobObject({'cerrado' if self.closed else 'abierto'})"

    def _open_handle(self) -> int:
        if self._handle is None:
            raise ValueError("el Job Object ya está cerrado")
        return self._handle


# --- ctypes -------------------------------------------------------------------------------


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _BasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


@functools.cache
def _kernel32() -> Any:
    """``kernel32`` con los prototipos de este módulo (una instancia propia: no toca los de
    ``ctypes.windll``, que comparten otros módulos)."""
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                            wintypes.DWORD)
    api.SetInformationJobObject.restype = wintypes.BOOL
    api.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                              wintypes.DWORD, wintypes.LPDWORD)
    api.QueryInformationJobObject.restype = wintypes.BOOL
    api.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    api.AssignProcessToJobObject.restype = wintypes.BOOL
    api.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    api.TerminateJobObject.restype = wintypes.BOOL
    api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    api.OpenProcess.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    return api


def _last_error() -> OSError:
    """El último error de Windows de este hilo, como :class:`OSError` (con ``winerror``)."""
    return ctypes.WinError(ctypes.get_last_error())
