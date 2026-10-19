# SPDX-License-Identifier: GPL-3.0-or-later
"""Las esperas de la red de cada llamada del hilo de Blender (spec 009, T29; RNF-009-05, como
RNF-005-06 de la spec 005 0.5).

Con el proyecto en una unidad de red, el presupuesto de cada llamada es el de **lo que hace
Geoblender** en ella; lo que el hilo espera a la red se mide y se anota aparte, sin
presupuesto. :class:`NetworkWaits` lo mide sin perfilador, con un reloj alrededor de cada
operación sobre la carpeta de la red (``folder``) mientras está activo (``with``):

- **abrir** un fichero de la carpeta (``open`` y ``Path.open``: ``builtins.open`` e
  ``io.open``), **leer** de él (``read``, ``readinto``, ``read1``, ``readinto1``,
  ``readline``, ``readlines``, ``peek``, ``seek`` y ``tell``), **escribir** (``write``,
  ``writelines``, ``flush`` y ``truncate``), **forzar** a disco lo escrito (``os.fsync`` de uno
  de esos ficheros: el envío al servidor) y **cerrarlo**;
- los **metadatos** de una ruta de la carpeta (:data:`META_FUNCTIONS` de ``os``: ``stat``,
  también por ``Path.stat`` y ``Path.exists``, cambiar la fecha, crear, renombrar, borrar y
  listar);
- el **COMMIT** de cada transacción de escritura de los proyectos dados (salir sin error de su
  ``write_transaction``: confirmar y cerrar la conexión), como la prueba de RNF-005-06.

Lo que SQLite lee o escribe por su cuenta (su E/S, en C) no se separa así y cuenta como propio,
igual que lo que cuesta el reloj: el error es siempre a favor del presupuesto. Solo cuenta en la
llamada lo del hilo principal (el de Blender, el que se mide); lo de otros hilos, solo en el
total. :meth:`NetworkWaits.begin` empieza una llamada y :meth:`NetworkWaits.take` da sus
esperas por clase (:data:`KINDS`). Solo biblioteca estándar.
"""

from __future__ import annotations

import builtins
import io
import os
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any
from unittest import mock

OPEN = "abrir"
READ = "leer"
WRITE = "escribir"
SYNC = "forzar"
CLOSE = "cerrar"
META = "metadatos"
COMMIT = "commit"
KINDS: tuple[str, ...] = (OPEN, READ, WRITE, SYNC, CLOSE, META, COMMIT)
"""Las clases de espera de la red, en el orden en que se anotan."""

READ_METHODS = ("read", "readinto", "read1", "readinto1", "readline", "readlines", "peek",
                "seek", "tell")
WRITE_METHODS = ("write", "writelines", "flush", "truncate")
META_FUNCTIONS = ("stat", "utime", "mkdir", "rename", "replace", "rmdir", "unlink", "remove",
                  "scandir", "listdir")
"""Las funciones de ``os`` que, con una ruta de la carpeta, son una espera de metadatos."""
_TWO_PATHS = frozenset({"rename", "replace"})


class _TimedFile:
    """Un fichero abierto de la carpeta de la red: sus lecturas, escrituras y su cierre
    cronometrados; lo demás (``fileno``, ``name``, ``closed``…), el del fichero."""

    def __init__(self, raw: Any, waits: NetworkWaits) -> None:
        self._raw = raw
        self._waits = waits

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._raw)

    def __enter__(self) -> _TimedFile:
        return self

    def __exit__(self, kind: type[BaseException] | None, value: BaseException | None,
                 trace: TracebackType | None) -> None:
        self.close()

    def close(self) -> None:
        self._waits._close(self._raw)


def _timed_method(kind: str, name: str) -> Callable[..., Any]:
    def method(self: _TimedFile, *args: Any, **kwargs: Any) -> Any:
        return self._waits.timed(kind, getattr(self._raw, name), *args, **kwargs)

    method.__name__ = name
    return method


for _name in READ_METHODS:
    setattr(_TimedFile, _name, _timed_method(READ, _name))
for _name in WRITE_METHODS:
    setattr(_TimedFile, _name, _timed_method(WRITE, _name))
del _name


class NetworkWaits:
    """Mientras está activo (``with``), mide las esperas de la red de cada llamada (véase el
    módulo): ``folder``, la carpeta de la red; ``projects``, los proyectos cuyo COMMIT se mide;
    ``clock``, el reloj (inyectable). ``totals``, ``counts`` y ``longest`` (clase y segundos
    de la operación más larga) acumulan todo lo medido, de todos los hilos. Al salir, también
    si algo falla, todo vuelve a ser como antes."""

    def __init__(self, folder: Path | str, *, projects: Iterable[Any] = (),
                 clock: Callable[[], float] = time.perf_counter) -> None:
        self.folder = os.path.normcase(os.path.abspath(os.fspath(folder)))
        self.projects = tuple(projects)
        self.clock = clock
        self.totals: dict[str, float] = dict.fromkeys(KINDS, 0.0)
        self.counts: dict[str, int] = dict.fromkeys(KINDS, 0)
        self.longest: tuple[str, float] = ("", 0.0)
        self._current: dict[str, float] = dict.fromkeys(KINDS, 0.0)
        self._fds: set[int] = set()
        self._stack: ExitStack | None = None

    # --- Lo medido ------------------------------------------------------------------------

    def begin(self) -> None:
        """Empieza una llamada, sin esperas todavía."""
        self._current = dict.fromkeys(KINDS, 0.0)

    def take(self) -> dict[str, float]:
        """Las esperas de la llamada desde :meth:`begin` (o desde el último ``take``), por
        clase; empieza otra."""
        found = self._current
        self.begin()
        return found

    def inside(self, path: object) -> bool:
        """Si ``path`` (una ruta, no un descriptor) es la carpeta de la red o está dentro."""
        if isinstance(path, int):
            return False
        try:
            text = os.fsdecode(os.fspath(path))  # type: ignore[arg-type]
        except TypeError:
            return False
        full = os.path.normcase(os.path.abspath(text))
        return full == self.folder or full.startswith(self.folder.rstrip("\\/") + os.sep)

    def timed(self, kind: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """``function(*args, **kwargs)`` como una espera de la red de clase ``kind``."""
        started = self.clock()
        try:
            return function(*args, **kwargs)
        finally:
            self._add(kind, self.clock() - started)

    def _add(self, kind: str, seconds: float) -> None:
        self.totals[kind] += seconds
        self.counts[kind] += 1
        if seconds > self.longest[1]:
            self.longest = (kind, seconds)
        if threading.current_thread() is threading.main_thread():
            self._current[kind] += seconds

    def _close(self, raw: Any) -> None:
        try:
            fd = None if raw.closed else raw.fileno()
        except (OSError, ValueError, AttributeError):
            fd = None
        try:
            self.timed(CLOSE, raw.close)
        finally:
            if fd is not None:
                self._fds.discard(fd)

    # --- Lo que sustituye mientras está activo --------------------------------------------

    def _open(self, real: Callable[..., Any]) -> Callable[..., Any]:
        def opened(file: Any, *args: Any, **kwargs: Any) -> Any:
            if not self.inside(file):
                return real(file, *args, **kwargs)
            raw = self.timed(OPEN, real, file, *args, **kwargs)
            try:
                self._fds.add(raw.fileno())
            except (OSError, ValueError, AttributeError):
                pass
            return _TimedFile(raw, self)

        return opened

    def _fsync(self, real: Callable[[Any], None]) -> Callable[[Any], None]:
        def fsync(fd: Any) -> None:
            number = fd if isinstance(fd, int) else fd.fileno()
            if number in self._fds:
                self.timed(SYNC, real, fd)
            else:
                real(fd)

        return fsync

    def _meta(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def function(*args: Any, **kwargs: Any) -> Any:
            paths = list(args[:2] if name in _TWO_PATHS else args[:1])
            paths += [kwargs[key] for key in ("path", "src", "dst") if key in kwargs]
            if any(self.inside(path) for path in paths):
                return self.timed(META, real, *args, **kwargs)
            return real(*args, **kwargs)

        function.__name__ = name
        return function

    def _transaction(self, real: Callable[..., Any]) -> Callable[..., Any]:
        """``write_transaction`` con su COMMIT medido: salir de ella sin error."""

        @contextmanager
        def transaction(*args: Any, **kwargs: Any) -> Iterator[Any]:
            manager = real(*args, **kwargs)
            conn = manager.__enter__()
            try:
                yield conn
            except BaseException as exc:
                if not manager.__exit__(type(exc), exc, exc.__traceback__):
                    raise
            else:
                self.timed(COMMIT, manager.__exit__, None, None, None)

        return transaction

    def __enter__(self) -> NetworkWaits:
        stack = ExitStack()
        try:
            stack.enter_context(mock.patch.object(builtins, "open", self._open(builtins.open)))
            stack.enter_context(mock.patch.object(io, "open", self._open(io.open)))
            stack.enter_context(mock.patch.object(os, "fsync", self._fsync(os.fsync)))
            for name in META_FUNCTIONS:
                stack.enter_context(mock.patch.object(os, name,
                                                      self._meta(name, getattr(os, name))))
            for project in self.projects:
                stack.enter_context(mock.patch.object(
                    project, "write_transaction", self._transaction(project.write_transaction)))
        except BaseException:
            stack.close()
            raise
        self._stack = stack
        self.begin()
        return self

    def __exit__(self, kind: type[BaseException] | None, value: BaseException | None,
                 trace: TracebackType | None) -> None:
        stack, self._stack = self._stack, None
        if stack is not None:
            stack.close()
