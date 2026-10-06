# SPDX-License-Identifier: GPL-3.0-or-later
"""Un proyecto abierto en esta sesión (spec 002; RF-002-06, RF-002-08, RF-002-11,
RF-002-12, RF-002-13, RF-002-30; plan 002 §5.1 a §5.4).

:class:`Project` es lo que devuelven crear y abrir: la carpeta, la fila de ``gb_project``
(la fuente de verdad), la cabecera, el modo de apertura con su motivo y lo necesario para
leer y escribir:

- :meth:`Project.read`: una conexión de solo lectura que no crea ningún fichero junto a la
  base (en WAL o con un diario caliente, sobre una copia privada en los datos de usuario).
- :meth:`Project.write_transaction`: una transacción de escritura, solo en un modo de
  escritura y con el cerrojo de esta sesión; cada una abre y cierra su conexión, así que
  entre dos escrituras no queda ningún fichero abierto.
- :meth:`Project.heartbeat`: la marca de actividad del cerrojo; si se perdió, o no se pudo
  renovar por un error de disco o de red, el proyecto pasa a solo lectura con el motivo.
- :meth:`Project.cache_dir`: la única caché del proyecto, ``<proyecto>/cache/`` en disco
  local y escritura, y ``<datos de usuario>/cache/<uid>/`` en red o en solo lectura
  (ADR-0010).
- :meth:`Project.close`: en escritura, registra ``close``, reescribe la cabecera desde la
  base de datos y libera el cerrojo, y solo si el cerrojo sigue siendo de esta sesión; en
  solo lectura no escribe nada en la carpeta del proyecto.

Coordenadas: la ventana y el GeoOrigin del registro son absolutos (CRS del proyecto, m).
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..errors import GeoblenderError, LockError, ProjectError
from ..georef.origin import GeoOrigin, Window
from ..gpkg.connection import GpkgConnection
from ..sysinfo import SessionInfo, pid_alive
from ..timeutil import SYSTEM_CLOCK, Clock, format_utc
from ..userdata import UserData
from . import lock
from .events import EventKind, log_event, record_event
from .lock import DEFAULT_STALE_MINUTES, LockCheck, PidAlive
from .manifest import PROJECT_STORE, Manifest, manifest_from_record, write_manifest
from .model import OpenMode, OpenStatus, ProjectRecord, ReadOnlyCode
from .schema import read_project

CACHE_DIR = "cache"
WRITE_MESSAGES: dict[OpenMode, str] = {
    OpenMode.WRITE_LOCAL: "Escritura (disco local)",
    OpenMode.WRITE_NETWORK: "Escritura en red (la caché va al disco local de este equipo)",
    OpenMode.CHECKOUT: "Escritura en una copia local de trabajo",
}


def write_status(mode: OpenMode) -> OpenStatus:
    """El estado de un proyecto abierto en un modo de escritura."""
    return OpenStatus(mode, None, WRITE_MESSAGES[mode])


def read_only_status(code: ReadOnlyCode, detail: str) -> OpenStatus:
    """El estado de un proyecto en solo lectura, con su motivo («Solo lectura: …»)."""
    return OpenStatus(OpenMode.READ_ONLY, code, f"Solo lectura: {detail}")


class Project:
    """Un proyecto abierto en esta sesión (en escritura o en solo lectura)."""

    def __init__(
        self,
        *,
        root: Path,
        record: ProjectRecord,
        manifest: Manifest,
        session: SessionInfo,
        userdata: UserData,
        status: OpenStatus,
        network: bool,
        clock: Clock = SYSTEM_CLOCK,
        pid_alive: PidAlive = pid_alive,
        stale_minutes: int = DEFAULT_STALE_MINUTES,
    ) -> None:
        self.root = Path(root)
        self.record = record
        self.manifest = manifest
        self.session = session
        self.userdata = userdata
        self.is_network = bool(network)
        self.clock = clock
        self.pid_alive = pid_alive
        self.stale_minutes = stale_minutes
        self._status = status
        self._closed = False

    # Identidad y georreferencia ---------------------------------------------------

    @property
    def uid(self) -> str:
        """Identidad del proyecto (``gb_project.uid``)."""
        return self.record.uid

    @property
    def name(self) -> str:
        """Nombre visible."""
        return self.record.name

    @property
    def origin(self) -> GeoOrigin:
        """GeoOrigin en metros enteros."""
        return self.record.origin

    @property
    def window(self) -> Window:
        """Ventana de trabajo alineada, absoluta (m)."""
        return self.record.window

    @property
    def grid_step_m(self) -> float:
        """Paso de rejilla (m)."""
        return float(self.record.grid_step_m)

    @property
    def schema_version(self) -> int:
        """Versión del esquema del proyecto."""
        return self.record.schema_version

    # Modo de apertura -------------------------------------------------------------

    @property
    def status(self) -> OpenStatus:
        """Modo de apertura con su motivo."""
        return self._status

    @property
    def mode(self) -> OpenMode:
        """Modo de apertura."""
        return self._status.mode

    @property
    def read_only_reason(self) -> ReadOnlyCode | None:
        """Por qué está en solo lectura (``None`` en escritura)."""
        return self._status.reason

    @property
    def writable(self) -> bool:
        """Verdadero si se puede escribir (modo de escritura y sin cerrar)."""
        return self._status.writable and not self._closed

    @property
    def closed(self) -> bool:
        """Verdadero tras :meth:`close`."""
        return self._closed

    def set_read_only(self, code: ReadOnlyCode, detail: str) -> None:
        """Pasa a solo lectura con su motivo; queda en el registro técnico."""
        self._status = read_only_status(code, detail)

    # Rutas ------------------------------------------------------------------------

    @property
    def database_path(self) -> Path:
        """``<proyecto>/project.gpkg``."""
        return self.root / PROJECT_STORE

    def private_dir(self) -> Path:
        """Carpeta de las copias privadas de lectura de esta sesión (datos de usuario)."""
        return self.userdata.private_read_dir(self.session.session_uid)

    def cache_dir(self) -> Path:
        """La caché del proyecto (no la crea): ``<proyecto>/cache/`` en disco local y
        escritura; ``<datos de usuario>/cache/<uid>/`` en red o en solo lectura."""
        if self.writable and not self.is_network:
            return self.root / CACHE_DIR
        return self.userdata.cache_dir(self.uid)

    # Lectura y escritura ----------------------------------------------------------

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Una conexión de solo lectura a la base del proyecto (se cierra al salir)."""
        db = GpkgConnection.open_read(self.database_path, self.private_dir())
        try:
            yield db.connection
        finally:
            db.close()

    def _require_writable(self) -> None:
        if self._closed:
            raise ProjectError(
                "core.project_closed",
                "el proyecto ya está cerrado: ábralo de nuevo",
                obj=f"Proyecto «{self.name}»",
                field="modo",
                shown="cerrado",
            )
        if not self._status.writable:
            raise ProjectError(
                "core.project_read_only",
                "no se puede escribir en un proyecto abierto en solo lectura",
                obj=f"Proyecto «{self.name}»",
                field="modo",
                shown=self._status.message,
            )

    def _require_lock(self) -> None:
        holder = lock.read_holder(self.root, clock=self.clock)
        if holder is None or holder.session_uid != self.session.session_uid:
            detail = "otra sesión ha forzado el cerrojo o ya no existe; no se ha escrito nada"
            self.set_read_only(ReadOnlyCode.LOCK_LOST, detail)
            log_event(EventKind.LOCK_LOST, detail, project=self.uid)
            raise LockError(
                "core.lock_lost",
                "el cerrojo ya no es de esta sesión: el proyecto pasa a solo lectura y no "
                "se ha escrito nada",
                obj=f"Proyecto «{self.name}»",
                field="cerrojo",
                shown="perdido",
            )

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Una transacción de escritura (``BEGIN IMMEDIATE`` … ``COMMIT``): solo en un
        modo de escritura y con el cerrojo de esta sesión."""
        self._require_writable()
        self._require_lock()
        db = GpkgConnection.open_write(self.database_path)
        try:
            with db.transaction() as conn:
                yield conn
        finally:
            db.close()

    def reload(self) -> ProjectRecord:
        """Vuelve a leer la fila de ``gb_project``."""
        with self.read() as conn:
            record = read_project(conn)
        if record is not None:
            self.record = record
        return self.record

    # Cerrojo ----------------------------------------------------------------------

    def heartbeat(self) -> LockCheck:
        """Renueva la marca del cerrojo (cada 5 min). En solo lectura no hay cerrojo que
        renovar: ``LOST``. Si se perdió o falló, el proyecto pasa a solo lectura."""
        if not self.writable:
            return LockCheck.LOST
        check = lock.heartbeat(self.root, self.session, clock=self.clock)
        if check is LockCheck.LOST:
            detail = "otra sesión ha forzado el cerrojo o ya no existe"
            self.set_read_only(ReadOnlyCode.LOCK_LOST, detail)
            log_event(EventKind.LOCK_LOST, detail, project=self.uid)
        elif check is LockCheck.FAILED:
            detail = "no se ha podido renovar el cerrojo (error de disco o de red)"
            self.set_read_only(ReadOnlyCode.WRITE_FAILED, detail)
            log_event(EventKind.WRITE_FAILED, detail, project=self.uid)
        return check

    # Cierre -----------------------------------------------------------------------

    def _close_writing(self) -> list[str]:
        warnings: list[str] = []
        if lock.heartbeat(self.root, self.session, clock=self.clock) is not LockCheck.OK:
            message = (
                "El cerrojo ya no era de esta sesión: al cerrar no se ha escrito nada en el "
                "proyecto ni se ha tocado su cerrojo."
            )
            log_event(EventKind.LOCK_LOST, message, project=self.uid)
            return [message]
        try:
            with self.write_transaction() as conn:
                record_event(
                    conn,
                    EventKind.CLOSE,
                    f"Proyecto cerrado por {self.session.user_host}",
                    session=self.session,
                    at=format_utc(self.clock.now()),
                )
            record = self.reload()
            self.manifest = manifest_from_record(record, previous=self.manifest)
            write_manifest(self.root, self.manifest, self.session.session_uid)
        except (GeoblenderError, OSError, sqlite3.Error) as exc:
            message = f"Al cerrar no se ha podido actualizar el proyecto: {exc}"
            log_event(EventKind.WRITE_FAILED, message, project=self.uid)
            warnings.append(message)
        finally:
            try:
                lock.release(self.root, self.session, clock=self.clock)
            except OSError as exc:
                warnings.append(f"No se ha podido liberar el cerrojo: {exc}")
        return warnings

    def close(self) -> tuple[str, ...]:
        """Cierra el proyecto y devuelve los avisos (vacío si todo fue bien). En escritura
        actualiza la cabecera desde la base de datos y libera el cerrojo de esta sesión;
        en solo lectura no escribe nada en el proyecto. Cerrar dos veces no hace nada."""
        if self._closed:
            return ()
        warnings: list[str] = []
        if self._status.writable:
            warnings.extend(self._close_writing())
        shutil.rmtree(self.private_dir(), ignore_errors=True)
        try:
            self.userdata.add_recent(self.uid, self.name, self.root, format_utc(self.clock.now()))
        except OSError:
            pass  # la lista de recientes es una comodidad del equipo
        self._closed = True
        return tuple(warnings)
