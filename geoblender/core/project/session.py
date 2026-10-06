# SPDX-License-Identifier: GPL-3.0-or-later
"""Un proyecto abierto en esta sesión (spec 002; RF-002-06, RF-002-08, RF-002-11,
RF-002-12, RF-002-13, RF-002-30; plan 002 §5.1 a §5.4).

:class:`Project` es lo que devuelven crear y abrir: la carpeta, la fila de ``gb_project``
(la fuente de verdad), la cabecera, el modo de apertura con su motivo y lo necesario para
leer y escribir:

- :meth:`Project.read`: una conexión de solo lectura que no crea ningún fichero junto a la
  base (en WAL o con un diario caliente, sobre una copia privada en los datos de usuario).
- :meth:`Project.write_transaction`: una transacción de escritura con el protocolo del
  plan 002 §5.4: 1) solo en un modo de escritura; 2) con el cerrojo de esta sesión (si se
  perdió, solo lectura «cerrojo perdido»); 3) con la base en diario clásico, devolviéndola
  a él si otro programa la dejó en WAL (aviso y evento ``wal_recovered``; si la tiene
  abierta, solo lectura «WAL ocupado» indicando qué cerrar); 4) ``BEGIN IMMEDIATE`` …
  ``COMMIT``; 5) la base sigue en diario clásico. Cualquier error de disco, de red o de
  SQLite deshace la transacción, cierra la conexión y deja el proyecto en solo lectura con
  el motivo (y suelta el cerrojo); un error de Geoblender del propio trabajo (una
  validación) solo la deshace. Si otro programa está leyendo, :class:`DatabaseBusyError`
  tras esperar ≤ 0,2 s, sin cambios y sin pasar a solo lectura: :meth:`Project.try_write`
  lo convierte en el estado «reintentando» para reintentar desde un temporizador. Cada
  escritura abre y cierra su conexión: entre dos no queda ningún fichero abierto.
- :meth:`Project.heartbeat`: la marca de actividad del cerrojo; si se perdió, o no se pudo
  renovar por un error de disco o de red, el proyecto pasa a solo lectura con el motivo.
- :meth:`Project.cache_dir`: la única caché del proyecto, ``<proyecto>/cache/`` en disco
  local y escritura, y ``<datos de usuario>/cache/<uid>/`` en red o en solo lectura
  (ADR-0010).
- :meth:`Project.refresh_header`: al guardar la vista, la cabecera se reescribe desde la
  base de datos si difiere (RF-002-07), solo en escritura y con el cerrojo propio.
- :meth:`Project.set_window`: cambia la ventana de trabajo y con ella el GeoOrigin
  (RF-002-27): nuevo origen en la base y en la cabecera, evento ``move_origin`` con el
  motivo (obligatorio); ninguna coordenada absoluta guardada cambia. Si la cabecera no se
  puede escribir después de confirmar, la base manda: solo lectura con aviso, y la
  cabecera se regenera al volver a abrirlo (T40).
- :meth:`Project.close`: en escritura, registra ``close``, reescribe la cabecera desde la
  base de datos y libera el cerrojo, y solo si el cerrojo sigue siendo de esta sesión; en
  solo lectura no escribe nada en la carpeta del proyecto.

Un proyecto de un esquema posterior que esta versión no sabe leer se abre **solo con la
cabecera** (:attr:`Project.header_only`, RF-002-22): sin fila de ``gb_project``
(``record`` es ``None``), con la identidad, el nombre, el CRS y el GeoOrigin de la
cabecera, sin ventana de trabajo, y :meth:`Project.read` y :meth:`Project.reload` se
niegan a abrir la base.

Coordenadas: la ventana y el GeoOrigin del registro son absolutos (CRS del proyecto, m).
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from ..errors import (
    DatabaseBusyError,
    DatabaseError,
    GeoblenderError,
    LockError,
    ProjectError,
    ValidationError,
)
from ..georef.crs import CrsCatalog, load_catalog
from ..georef.origin import GeoOrigin, Window, align_window, check_grid_step, choose_origin
from ..gpkg.connection import BUSY_TIMEOUT_MS, GpkgConnection
from ..gpkg.header import read_header
from ..gpkg.wal import WalOutcome, to_classic_journal
from ..paths import find_absolute_paths
from ..sysinfo import SessionInfo, pid_alive
from ..timeutil import SYSTEM_CLOCK, Clock, format_utc
from ..userdata import UserData
from . import lock
from .events import EventKind, log_event, record_event
from .lock import DEFAULT_STALE_MINUTES, LockCheck, PidAlive
from .manifest import (
    PROJECT_STORE,
    Manifest,
    manifest_from_record,
    manifest_path,
    manifest_text,
    write_manifest,
)
from .model import OpenMode, OpenStatus, ProjectRecord, ReadOnlyCode
from .schema import read_project

CACHE_DIR = "cache"
BUSY_MESSAGE = "QGIS u otro programa está leyendo el proyecto; reintentando…"
WAL_NOTICE = (
    "La base de datos estaba en modo WAL (QGIS lo activa al editar un GeoPackage); se ha "
    "devuelto al diario clásico sin perder datos."
)
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


class WriteState(Enum):
    """Resultado de :meth:`Project.try_write`."""

    DONE = "done"
    RETRYING = "retrying"  # otro programa está leyendo: reintentar en un momento


@dataclass(frozen=True)
class WriteAttempt:
    """Un intento de escritura: hecho (con el valor que devolvió el trabajo) o
    «reintentando» (con el mensaje para la barra de estado)."""

    state: WriteState
    value: Any = None
    message: str = ""


class Project:
    """Un proyecto abierto en esta sesión (en escritura o en solo lectura)."""

    def __init__(
        self,
        *,
        root: Path,
        record: ProjectRecord | None,
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
        self._notices: list[str] = []
        self._pending_wal: int | None = None

    # Identidad y georreferencia (de la base; solo con la cabecera, de la cabecera) ----

    @property
    def header_only(self) -> bool:
        """Verdadero si el proyecto se abrió solo con la cabecera: es de un esquema que
        esta versión no sabe leer (RF-002-22)."""
        return self.record is None

    @property
    def uid(self) -> str:
        """Identidad del proyecto (``gb_project.uid``)."""
        return self.manifest.project_uid if self.record is None else self.record.uid

    @property
    def name(self) -> str:
        """Nombre visible."""
        return self.manifest.name if self.record is None else self.record.name

    @property
    def origin(self) -> GeoOrigin:
        """GeoOrigin en metros enteros."""
        return self.manifest.origin if self.record is None else self.record.origin

    @property
    def window(self) -> Window | None:
        """Ventana de trabajo alineada, absoluta (m); ``None`` solo con la cabecera (no
        la guarda)."""
        return None if self.record is None else self.record.window

    @property
    def grid_step_m(self) -> float:
        """Paso de rejilla (m)."""
        step = self.manifest.grid_step_m if self.record is None else self.record.grid_step_m
        return float(step)

    @property
    def is_checkout(self) -> bool:
        """Verdadero si es una copia local de trabajo: su cabecera lleva la sección
        ``checkout`` (RF-002-31); en el original es ``null``."""
        return self.manifest.checkout is not None

    @property
    def schema_version(self) -> int:
        """Versión del esquema del proyecto."""
        if self.record is None:
            return self.manifest.schema_version
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
        """Pasa a solo lectura con su motivo."""
        self._status = read_only_status(code, detail)

    def take_notices(self) -> list[str]:
        """Los avisos pendientes de mostrar (p. ej., la vuelta desde WAL); los vacía."""
        notices, self._notices = self._notices, []
        return notices

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

    def _require_database(self) -> None:
        if self.record is None:
            raise ProjectError(
                "core.project_header_only",
                "es de un esquema posterior que esta versión de Geoblender no sabe leer: solo "
                "se puede ver su cabecera (nombre, CRS y GeoOrigin); ábralo con Geoblender "
                f"{self.manifest.geoblender_version} o posterior",
                obj=f"Proyecto «{self.name}»",
                field="esquema",
                value=self.manifest.schema_version,
            )

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Una conexión de solo lectura a la base del proyecto (se cierra al salir).
        :class:`ProjectError` si solo se abrió la cabecera."""
        self._require_database()
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

    def _give_up_writing(self, code: ReadOnlyCode, detail: str, kind: EventKind) -> None:
        """Pasa a solo lectura, lo deja en el registro técnico y suelta el cerrojo propio
        (si se puede: sin red, caducará)."""
        self.set_read_only(code, detail)
        log_event(kind, detail, project=self.uid)
        try:
            lock.release(self.root, self.session, clock=self.clock)
        except OSError:
            pass

    def _write_failed(self, exc: BaseException) -> ProjectError:
        reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
        detail = f"falló una escritura en el proyecto ({reason}); no se ha cambiado nada"
        self._give_up_writing(ReadOnlyCode.WRITE_FAILED, detail, EventKind.WRITE_FAILED)
        return ProjectError(
            "core.project_write_failed",
            f"no se ha podido escribir ({reason}): la escritura se ha deshecho y el "
            "proyecto pasa a solo lectura; compruebe el disco o la red y vuelva a abrirlo",
            obj=f"Proyecto «{self.name}»",
            field=PROJECT_STORE,
            value=str(self.database_path),
        )

    def _ensure_classic_journal(self) -> None:
        """Paso 3: la base en diario clásico; si otro programa la dejó en WAL, se devuelve
        a él (o, si la tiene abierta, solo lectura)."""
        path = self.database_path
        if not read_header(path).needs_recovery:
            return
        recovery = to_classic_journal(path, timeout_s=BUSY_TIMEOUT_MS / 1000)
        if recovery.outcome is WalOutcome.BUSY:
            detail = (
                "QGIS u otro programa tiene abierta la base de datos en modo WAL; cierre ese "
                "programa y vuelva a abrir el proyecto"
            )
            self._give_up_writing(ReadOnlyCode.WAL_BUSY, detail, EventKind.WRITE_FAILED)
            raise ProjectError(
                "core.project_wal_busy",
                "no se ha escrito nada: " + detail,
                obj=f"Proyecto «{self.name}»",
                field="diario",
                value=str(path),
            )
        if recovery.outcome is WalOutcome.CONVERTED:
            self._pending_wal = recovery.wal_bytes
            self._notices.append(WAL_NOTICE)
            log_event(EventKind.WAL_RECOVERED, WAL_NOTICE, project=self.uid)

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Una transacción de escritura con el protocolo del módulo; todo o nada."""
        self._require_writable()
        self._require_lock()
        try:
            self._ensure_classic_journal()
            db = GpkgConnection.open_write(self.database_path)
        except ProjectError:
            raise
        except (OSError, sqlite3.Error, DatabaseError) as exc:
            raise self._write_failed(exc) from exc
        try:
            with db.transaction() as conn:
                if self._pending_wal is not None:
                    record_event(
                        conn,
                        EventKind.WAL_RECOVERED,
                        "La base de datos estaba en modo WAL; se ha devuelto al diario clásico",
                        session=self.session,
                        at=format_utc(self.clock.now()),
                        data={"wal_bytes": self._pending_wal},
                    )
                yield conn
            self._pending_wal = None
        except DatabaseBusyError:
            raise
        except DatabaseError as exc:
            raise self._write_failed(exc) from exc
        except GeoblenderError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise self._write_failed(exc) from exc
        finally:
            db.close()

    def try_write(self, work: Callable[[sqlite3.Connection], Any]) -> WriteAttempt:
        """Ejecuta ``work`` en una transacción de escritura. Si otro programa está
        leyendo, devuelve enseguida (espera ≤ 0,2 s) el estado «reintentando» sin cambiar
        nada; los demás errores, como :meth:`write_transaction`."""
        try:
            with self.write_transaction() as conn:
                value = work(conn)
        except DatabaseBusyError:
            return WriteAttempt(WriteState.RETRYING, None, BUSY_MESSAGE)
        return WriteAttempt(WriteState.DONE, value)

    def reload(self) -> ProjectRecord:
        """Vuelve a leer la fila de ``gb_project``. :class:`ProjectError` si solo se abrió
        la cabecera."""
        with self.read() as conn:
            record = read_project(conn)
        if record is not None:
            self.record = record
        if self.record is None:  # inalcanzable: read() ya lo ha rechazado
            raise TypeError("el proyecto no tiene la fila de gb_project")
        return self.record

    def refresh_header(self) -> bool:
        """Reescribe la cabecera desde la base de datos (al guardar la vista, RF-002-07) y
        devuelve si la reescribió: solo en escritura, con el cerrojo de esta sesión y si
        la cabecera difiere de la que sale de la base (si no, no se toca el fichero).
        :class:`LockError` si el cerrojo ya no es de esta sesión (el proyecto pasa a solo
        lectura sin escribir nada)."""
        if not self.writable:
            return False
        self._require_lock()
        record = self.reload()
        header = manifest_from_record(record, previous=self.manifest)
        try:
            current = manifest_path(self.root).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            current = None
        if current == manifest_text(header):
            self.manifest = header
            return False
        write_manifest(self.root, header, self.session.session_uid)
        self.manifest = header
        return True

    # Ventana de trabajo y GeoOrigin -------------------------------------------------

    def set_window(
        self,
        window: Window | tuple[float, float, float, float],
        grid_step_m: float,
        z0: int,
        reason: str,
        *,
        catalog: CrsCatalog | None = None,
    ) -> GeoOrigin:
        """Cambia la ventana de trabajo (absoluta, m) y con ella el GeoOrigin (RF-002-27):
        la ventana se amplía a la unidad de alineación del paso y el origen nuevo es su
        centro redondeado a 100 m (RF-002-24), con ``z0``. En una transacción se guardan el
        origen, la ventana y el paso en ``gb_project`` y el evento ``move_origin`` con el
        motivo y los dos orígenes; después, la cabecera. Ninguna coordenada absoluta
        guardada cambia (el origen solo afecta a las vistas). Devuelve el origen nuevo.

        :class:`ValidationError` sin motivo o con uno que lleva una ruta absoluta, o si la
        ventana, el paso o ``z0`` no valen; :class:`ProjectError` en solo lectura;
        :class:`LockError` sin el cerrojo. En todos esos casos no cambia nada.

        Si la cabecera no se puede escribir **después** de confirmar la transacción (un
        error de disco o de red), el origen nuevo ya está en la base, que manda: se
        devuelve igual, la cabecera anterior queda intacta y el proyecto pasa a solo
        lectura «fallo de escritura» (RF-002-12) con un aviso en :meth:`take_notices`, el
        registro técnico y el cerrojo soltado. Al abrirlo otra vez en escritura, la
        diferencia de GeoOrigin la explica el evento ``move_origin`` y la cabecera se
        regenera desde la base (``compare``; convergencia de la spec 002, T40)."""
        obj = f"Ventana de trabajo de «{self.name}»"
        text = reason.strip() if isinstance(reason, str) else ""
        if not text:
            raise ValidationError(
                "core.window_reason_required",
                "hace falta un motivo: queda registrado con el cambio del GeoOrigin",
                obj=obj,
                field="motivo",
                value=reason,
            )
        if find_absolute_paths(text):
            raise ValidationError(
                "core.window_reason_path",
                "el motivo no puede llevar rutas absolutas (el proyecto no guarda ninguna)",
                obj=obj,
                field="motivo",
                value=reason,
            )
        self._require_writable()
        record = self.record
        if record is None:  # inalcanzable: solo con la cabecera no se abre en escritura
            raise TypeError("el proyecto no tiene la fila de gb_project")
        from .create import check_window_inside  # create usa este módulo

        step = check_grid_step(grid_step_m)
        typed = window if isinstance(window, Window) else Window(*window)
        aligned = align_window(typed, step)
        crs = (load_catalog() if catalog is None else catalog).horizontal(record.crs_epsg)
        check_window_inside(crs, typed, aligned)
        origin = choose_origin(aligned, z0)
        previous = record.origin
        now = format_utc(self.clock.now())
        message = (
            f"Ventana de trabajo cambiada por {self.session.user_host}: GeoOrigin "
            f"({previous.x0}; {previous.y0}; {previous.z0}) → ({origin.x0}; {origin.y0}; "
            f"{origin.z0}), ventana ({aligned.xmin:.0f}; {aligned.ymin:.0f}) – "
            f"({aligned.xmax:.0f}; {aligned.ymax:.0f}), paso {step:g} m. Motivo: {text}"
        )
        with self.write_transaction() as conn:
            conn.execute(
                "UPDATE gb_project SET origin_x = ?, origin_y = ?, origin_z = ?, "
                "grid_step_m = ?, window_xmin = ?, window_ymin = ?, window_xmax = ?, "
                "window_ymax = ?, modified_at = ?, last_written_with = ?",
                (
                    origin.x0, origin.y0, origin.z0, step,
                    aligned.xmin, aligned.ymin, aligned.xmax, aligned.ymax,
                    now, self.session.geoblender_version,
                ),
            )
            record_event(
                conn,
                EventKind.MOVE_ORIGIN,
                message,
                session=self.session,
                at=now,
                data={
                    "reason": text,
                    "from": list(previous.as_tuple()),
                    "to": list(origin.as_tuple()),
                    "window": [aligned.xmin, aligned.ymin, aligned.xmax, aligned.ymax],
                    "grid_step_m": step,
                },
            )
        # Confirmado: la base ya tiene el origen nuevo y manda. La fila de la sesión se
        # actualiza con lo escrito, sin volver a leer la base (en red podría fallar ahora).
        self.record = replace(
            record,
            origin_x=origin.x0, origin_y=origin.y0, origin_z=origin.z0, grid_step_m=step,
            window_xmin=aligned.xmin, window_ymin=aligned.ymin,
            window_xmax=aligned.xmax, window_ymax=aligned.ymax,
            modified_at=now, last_written_with=self.session.geoblender_version,
        )
        header = manifest_from_record(self.record, previous=self.manifest)
        try:
            write_manifest(self.root, header, self.session.session_uid)
        except ProjectError as exc:
            self._header_failed_after_commit(origin, exc)
        else:
            self.manifest = header
        return origin

    def _header_failed_after_commit(self, origin: GeoOrigin, exc: ProjectError) -> None:
        """La base tiene el origen nuevo y la cabecera no se pudo reescribir: solo
        lectura con el motivo, aviso, registro técnico y cerrojo soltado (RF-002-12)."""
        cause = exc.__cause__
        reason = getattr(cause, "strerror", None) or str(cause or exc.reason)
        detail = (
            f"el GeoOrigin ya es ({origin.x0}; {origin.y0}; {origin.z0}) en la base de datos, "
            f"pero no se ha podido actualizar la cabecera, manifest.json ({reason}); se "
            "regenerará desde la base de datos al abrir el proyecto en escritura"
        )
        self._give_up_writing(ReadOnlyCode.WRITE_FAILED, detail, EventKind.WRITE_FAILED)
        self._notices.append(
            f"Proyecto «{self.name}»: {detail}. El proyecto pasa a solo lectura: compruebe "
            "el disco o la red y vuelva a abrirlo."
        )

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
