# SPDX-License-Identifier: GPL-3.0-or-later
"""Conexión al GeoPackage del proyecto (spec 002; RF-002-12, RF-002-13, RF-002-16;
ADR-0006; plan 002 §5.2 y §5.4).

- **Escritura** (:meth:`GpkgConnection.open_write`): diario clásico
  (``journal_mode = DELETE``, nunca WAL: no funciona en la red, ARQ-17),
  ``synchronous = FULL``, claves foráneas y ``busy_timeout = 200``: el hilo de la
  interfaz no espera más de 0,2 s a QGIS u otro programa; si sigue ocupado, la escritura
  se deshace y devuelve :class:`DatabaseBusyError` para reintentar. Registra la función
  SQL ``gb_writer()``, que solo existe en las conexiones de Geoblender y que piden los
  disparadores de las tablas internas (no es seguridad: evita que otro programa las
  altere por error). Una base en WAL no se abre para escribir: antes hay que devolverla
  al diario clásico (``core.gpkg.wal``).
- **Lectura** (:meth:`GpkgConnection.open_read`): ``mode=ro`` y ``query_only``; en
  diario clásico no crea ningún fichero junto a la base. Una base en WAL o con un diario
  caliente se lee en una copia privada (``core.gpkg.wal``).
- :meth:`GpkgConnection.transaction`: ``BEGIN IMMEDIATE`` … ``COMMIT``; cualquier error
  la deshace entera, y después comprueba que la base sigue en diario clásico.

Los cerrojos de la transacción (``BEGIN IMMEDIATE`` y ``COMMIT``) no usan el
``busy_timeout`` de SQLite sino un reintento propio con un reloj preciso hasta 0,2 s: en
Windows el manejador de SQLite duerme con ``Sleep()`` en pasos de 1, 2, 5, 10… ms que el
reloj del sistema redondea a unos 15,6 ms, y ``busy_timeout = 200`` espera en realidad
0,29 s (medido con el SQLite 3.51.3 de Blender 5.2.1). El ``busy_timeout = 200`` sigue
valiendo para el resto de sentencias (una lectura mientras otro programa confirma).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from urllib.parse import quote

from ..errors import DatabaseBusyError, DatabaseError
from .header import read_header

BUSY_TIMEOUT_MS = 200
BUSY_RETRY_S = 0.005  # pausa entre reintentos al tomar el cerrojo de escritura
CLASSIC_JOURNAL = "delete"
WRITER_FUNCTION = "gb_writer"
SQLITE_BUSY = 5
_OBJ = "Base de datos del proyecto"


def sqlite_uri(path: Path, **params: str) -> str:
    """URI de SQLite para ``path`` (``Path.as_uri()``, que escapa los caracteres
    especiales) con ``params`` como consulta. Una ruta UNC da una URI con autoridad, que
    SQLite rechaza: se pasa a la forma sin autoridad (cuatro barras tras el esquema)."""
    scheme, rest = Path(path).absolute().as_uri().split(":", 1)
    if not rest.startswith("///"):
        rest = "//" + rest  # UNC: //servidor/recurso → ////servidor/recurso
    uri = f"{scheme}:{rest}"
    if params:
        uri += "?" + "&".join(f"{key}={quote(value)}" for key, value in params.items())
    return uri


def gb_writer() -> int:
    """Función SQL de las conexiones de escritura de Geoblender: vale 1."""
    return 1


def is_busy(error: BaseException) -> bool:
    """Verdadero si ``error`` es un ``SQLITE_BUSY`` (la base está ocupada)."""
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int):
        return code & 0xFF == SQLITE_BUSY
    return isinstance(error, sqlite3.OperationalError) and "locked" in str(error)


def _busy(path: Path, error: BaseException) -> DatabaseBusyError:
    return DatabaseBusyError(
        "core.gpkg_busy",
        "QGIS u otro programa está usando la base de datos; no se ha cambiado nada: "
        "reintente en unos segundos o cierre ese programa",
        obj=_OBJ,
        field="fichero",
        value=str(path),
        context={"sqlite": str(error)},
    )


class GpkgConnection:
    """Una conexión al GeoPackage, de escritura o de lectura."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        path: Path,
        writable: bool,
        source: Path | None = None,
    ) -> None:
        self._conn = conn
        self.path = Path(path)  # lo que está abierto (la copia privada, si la hay)
        self.source = Path(source) if source is not None else self.path  # la del proyecto
        self.writable = writable

    @classmethod
    def open_write(cls, path: Path, *, create: bool = False) -> GpkgConnection:
        """Abre ``path`` para escribir (con ``create``, la crea si no existe).

        :class:`DatabaseError` si no existe (sin ``create``), no es SQLite o está en WAL.
        """
        path = Path(path)
        if path.exists():
            header = read_header(path)
            if header.journal == "wal" or header.has_wal:
                raise DatabaseError(
                    "core.gpkg_wal",
                    "está en modo WAL (QGIS lo activa al editar): hay que devolverla al "
                    "diario clásico antes de escribir",
                    obj=_OBJ,
                    field="diario",
                    value=str(path),
                )
        elif not create:
            raise DatabaseError(
                "core.gpkg_missing",
                "no existe; compruebe la ruta del proyecto",
                obj=_OBJ,
                field="fichero",
                value=str(path),
            )
        conn = sqlite3.connect(
            str(path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None
        )
        try:
            mode = conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
            if str(mode).lower() != CLASSIC_JOURNAL:
                raise DatabaseError(
                    "core.gpkg_journal",
                    f"no se ha podido poner en diario clásico (sigue en «{mode}»)",
                    obj=_OBJ,
                    field="diario",
                    value=str(path),
                )
            conn.execute("PRAGMA synchronous = FULL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            conn.create_function(WRITER_FUNCTION, 0, gb_writer, deterministic=True)
        except BaseException:
            conn.close()
            raise
        return cls(conn, path, writable=True)

    @classmethod
    def open_read(cls, path: Path, private_dir: Path | None = None) -> GpkgConnection:
        """Abre ``path`` para leer sin crear ni cambiar ningún fichero junto a ella.

        Una base en WAL o con un diario caliente necesita una copia privada en
        ``private_dir`` (``core.gpkg.wal``); :class:`DatabaseError` si no la hay.
        """
        source = Path(path)
        target = source
        if read_header(source).needs_recovery:
            if private_dir is None:
                raise DatabaseError(
                    "core.gpkg_needs_private_copy",
                    "está en modo WAL o tiene una transacción a medias: se lee en una "
                    "copia privada para no crear ficheros junto a ella, y no se ha "
                    "indicado su carpeta",
                    obj=_OBJ,
                    field="diario",
                    value=str(source),
                )
            from .wal import private_copy  # wal importa este módulo

            target = private_copy(source, Path(private_dir))
        conn = sqlite3.connect(
            sqlite_uri(target, mode="ro"),
            uri=True,
            timeout=BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        try:
            conn.execute("PRAGMA query_only = ON")
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        except BaseException:
            conn.close()
            raise
        return cls(conn, target, writable=False, source=source)

    @property
    def connection(self) -> sqlite3.Connection:
        """La conexión de ``sqlite3`` (para leer; para escribir, :meth:`transaction`)."""
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` … ``COMMIT``: todo o nada.

        :class:`DatabaseBusyError` si otro programa la tiene ocupada más de 0,2 s (sin
        cambios); cualquier otro error deshace la transacción y se propaga.
        """
        if not self.writable:
            raise DatabaseError(
                "core.gpkg_read_only",
                "está abierta en solo lectura",
                obj=_OBJ,
                field="modo",
                value=str(self.path),
            )
        conn = self._conn
        try:
            self._locking("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if is_busy(exc):
                raise _busy(self.path, exc) from exc
            raise
        try:
            yield conn
            self._locking("COMMIT")
        except BaseException as exc:
            self._rollback()
            if is_busy(exc):
                raise _busy(self.path, exc) from exc
            raise
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if str(mode).lower() != CLASSIC_JOURNAL:
            raise DatabaseError(
                "core.gpkg_journal",
                f"ha dejado de estar en diario clásico (está en «{mode}»)",
                obj=_OBJ,
                field="diario",
                value=str(self.path),
            )

    def _locking(self, sql: str) -> None:
        """Ejecuta ``sql`` (``BEGIN IMMEDIATE`` o ``COMMIT``) reintentando mientras la
        base esté ocupada, hasta ``BUSY_TIMEOUT_MS`` medidos con ``perf_counter``; si
        sigue ocupada, propaga el ``SQLITE_BUSY``."""
        conn = self._conn
        deadline = time.perf_counter() + BUSY_TIMEOUT_MS / 1000
        conn.execute("PRAGMA busy_timeout = 0")
        try:
            while True:
                try:
                    conn.execute(sql)
                    return
                except sqlite3.OperationalError as exc:
                    if not is_busy(exc) or time.perf_counter() >= deadline:
                        raise
                    time.sleep(BUSY_RETRY_S)
        finally:
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")

    def _rollback(self) -> None:
        if self._conn.in_transaction:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass  # el error original es el que importa; SQLite ya la deshizo

    def close(self) -> None:
        """Deshace lo que quede a medias y cierra la conexión."""
        self._rollback()
        self._conn.close()

    def __enter__(self) -> GpkgConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
