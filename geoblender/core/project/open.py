# SPDX-License-Identifier: GPL-3.0-or-later
"""Abrir un proyecto ``.gbproj`` (spec 002; RF-002-04, RF-002-05, RF-002-08, RF-002-09,
RF-002-10, RF-002-13, RF-002-17, RF-002-22; plan 002 §5.3 y §5.4).

La apertura es un generador de pasos (:func:`open_steps`): en red puede pasar de 1 s y un
operador modal la avanza con progreso. Cada fase es al menos un :class:`Progress`
(:data:`PHASES`); el último lleva el :class:`OpenResult`. :func:`open_project` es el mismo
recorrido sin pausas. Cerrar el generador antes del final (cancelar) libera el cerrojo si
ya se había tomado.

1. **Cabecera**: ``manifest.json`` legible y válida, o no abre (RF-002-05).
2. **Base de datos**, sin escribir en el proyecto: ``project.gpkg`` en solo lectura (una
   base en WAL o con un diario caliente se lee en una copia privada de los datos de
   usuario: abrirla en el sitio crearía ``-wal`` y ``-shm`` junto a ella); su fila de
   ``gb_project`` y las migraciones registradas.
3. **Coherencia**: si la cabecera y la base difieren en identidad, CRS, GeoOrigin o
   esquema, no abre y muestra los dos valores (sin corregir ninguno). Un esquema que
   explican las migraciones registradas, o un GeoOrigin que explica el último cambio de
   ventana registrado (la cabecera se quedó con el anterior), se regeneran desde la base.
4. **Esquema**: igual, anterior (sin migrar: solo lectura, RF-002-20; quien acepta
   migrar lo migra antes con ``core.project.migrations``) o posterior (solo lectura
   indicando qué versión de Geoblender hace falta, RF-002-22). Si el esquema mínimo para
   leer el proyecto (``min_reader_schema``) es posterior al de esta versión, solo se lee
   la **cabecera**: la base ni se abre (leer tablas de un esquema que no se conoce podría
   mostrar cifras erróneas) y el proyecto queda limitado a su nombre, CRS y GeoOrigin.
   Lo dice la cabecera, sin abrir la base; si la cabecera no lo dice pero la base sí (la
   base manda), también se queda en la cabecera.
5. **Cerrojo** (:mod:`.lock`): libre, huérfano o propio → escritura (en red, en local o,
   si la cabecera lleva la sección ``checkout``, como copia local de trabajo); otra
   sesión → solo lectura con quién lo tiene (y la oferta de forzarlo si está caducado o
   reservado); forzar solo con el titular que vio el usuario (``force_holder``).
6. **Apertura**: en escritura, la base vuelve al diario clásico si otro programa la dejó
   en WAL (si sigue ocupada, solo lectura indicando qué cerrar), se registran en una
   transacción los eventos (``lock_orphan_replaced``, ``lock_forced``, ``wal_recovered``,
   ``manifest_rewritten`` y ``open``) y la versión de Geoblender que escribe, y se
   regenera la cabecera desde la base si hace falta. Un fallo de disco o de red en este
   paso deja el proyecto en solo lectura con el motivo. En solo lectura no se escribe
   nada en la carpeta del proyecto.

El proyecto entra en la lista de recientes del equipo (datos de usuario, RF-002-08).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..errors import DatabaseError, GeoblenderError, LockError, ProjectError
from ..gpkg.connection import BUSY_TIMEOUT_MS, GpkgConnection
from ..gpkg.header import SqliteHeader, read_header
from ..gpkg.wal import WalOutcome, to_classic_journal
from ..paths import DriveType, is_network_path
from ..sysinfo import SessionInfo, pid_alive
from ..timeutil import SYSTEM_CLOCK, Clock, format_utc
from ..userdata import UserData
from . import lock as lockmod
from .events import EventKind, last_origin_move, log_event, record_event
from .lock import Acquired, LockInfo, LockMode, LockState, LockStatus, PidAlive
from .manifest import (
    PROJECT_STORE,
    Manifest,
    ManifestCheck,
    ManifestStatus,
    OriginMove,
    compare,
    manifest_from_record,
    read_manifest,
    write_manifest,
)
from .model import OpenMode, OpenResult, OpenStatus, ProjectRecord, Progress, ReadOnlyCode
from .schema import SCHEMA_VERSION, missing_objects, read_migrations, read_project
from .session import Project, read_only_status, write_status

PHASES: tuple[str, ...] = (
    "cabecera",
    "base de datos",
    "coherencia",
    "esquema",
    "cerrojo",
    "apertura",
)
WAL_WARNING = (
    "La base de datos estaba en modo WAL (QGIS lo activa al editar un GeoPackage); se ha "
    "devuelto al diario clásico sin perder datos."
)


class SchemaRelation(Enum):
    """El esquema del proyecto frente al de esta versión de Geoblender."""

    SAME = "same"
    OLDER = "older"  # hay que migrarlo (RF-002-20)
    NEWER = "newer"  # solo lectura (RF-002-22)
    HEADER_ONLY = "header_only"  # posterior y que no se sabe leer: solo la cabecera


@dataclass(frozen=True)
class ProjectInspection:
    """Lo que se sabe de un proyecto sin escribir en él (fases 1 a 5).

    Con un esquema que esta versión no sabe leer (:attr:`header_only`), solo hay
    cabecera: ``record`` es ``None`` y, si la base ni se abrió, también ``check`` y
    ``header``.
    """

    root: Path
    manifest: Manifest
    record: ProjectRecord | None
    migrations: tuple[tuple[int, int], ...]
    check: ManifestCheck | None
    schema: SchemaRelation
    header: SqliteHeader | None
    lock: LockStatus
    network: bool

    @property
    def header_only(self) -> bool:
        """Verdadero si solo se puede usar la cabecera (RF-002-22)."""
        return self.schema is SchemaRelation.HEADER_ONLY


def _project_name(root: Path) -> str:
    name = root.name
    return name[: -len(".gbproj")] if name.endswith(".gbproj") else name


def _require_folder(root: Path) -> None:
    if not root.is_dir():
        raise ProjectError(
            "core.project_missing",
            "no existe o no es la carpeta de un proyecto (<Nombre>.gbproj); compruebe la "
            "ruta o ábralo desde «Abrir»",
            obj="Proyecto",
            field="carpeta",
            value=str(root),
        )


def _database_error(root: Path, code: str, reason: str, exc: BaseException) -> ProjectError:
    return ProjectError(
        code,
        reason,
        obj=f"Proyecto «{_project_name(root)}»",
        field=PROJECT_STORE,
        value=str(root / PROJECT_STORE),
        context={"error": str(exc)},
    )


def _read_database(
    root: Path, private_dir: Path
) -> tuple[SqliteHeader, ProjectRecord, tuple[tuple[int, int], ...], OriginMove | None]:
    path = root / PROJECT_STORE
    try:
        header = read_header(path)
    except DatabaseError as exc:
        if exc.code == "core.gpkg_missing":
            raise _database_error(
                root,
                "core.project_database_missing",
                "falta la base de datos del proyecto, que es la fuente de verdad: el "
                "proyecto no se abre; restáurela de una copia de seguridad",
                exc,
            ) from exc
        raise _database_error(
            root, "core.project_database_unreadable", f"no se puede leer: {exc.reason}", exc
        ) from exc
    try:
        with GpkgConnection.open_read(path, private_dir) as db:
            conn = db.connection
            missing = missing_objects(conn)
            record = None if missing else read_project(conn)
            migrations = () if missing else read_migrations(conn)
            origin_move = None if missing else last_origin_move(conn)
    except (sqlite3.Error, DatabaseError) as exc:
        raise _database_error(
            root,
            "core.project_database_unreadable",
            f"no se puede leer ({exc}); compruebe que no está dañada o restáurela de una "
            "copia de seguridad",
            exc,
        ) from exc
    if missing or record is None:
        absent = ", ".join(missing) if missing else "la fila de gb_project"
        raise _database_error(
            root,
            "core.project_database_incomplete",
            f"le falta la estructura del proyecto ({absent}): no es la base de un proyecto "
            "de Geoblender o está dañada; el proyecto no se abre",
            ValueError(absent),
        )
    return header, record, migrations, origin_move


def _schema_relation(version: int) -> SchemaRelation:
    if version == SCHEMA_VERSION:
        return SchemaRelation.SAME
    return SchemaRelation.OLDER if version < SCHEMA_VERSION else SchemaRelation.NEWER


def inspect_project(
    path: Path,
    session: SessionInfo,
    userdata: UserData,
    *,
    clock: Clock = SYSTEM_CLOCK,
    pid_alive: PidAlive = pid_alive,
    stale_minutes: int = lockmod.DEFAULT_STALE_MINUTES,
    network: bool | None = None,
    drive_type: DriveType | None = None,
) -> ProjectInspection:
    """Inspecciona el proyecto sin escribir en él: cabecera, base de datos, coherencia,
    esquema y cerrojo. :class:`ProjectError` si no se puede abrir (falta algo o la cabecera
    y la base no coinciden)."""
    *_, inspection = _inspect_steps(
        Path(path), session, userdata, clock, pid_alive, stale_minutes, network, drive_type
    )
    if not isinstance(inspection, ProjectInspection):
        raise TypeError("la inspección del proyecto no ha terminado con su resultado")
    return inspection


def _inspect_steps(
    root: Path,
    session: SessionInfo,
    userdata: UserData,
    clock: Clock,
    alive: PidAlive,
    stale_minutes: int,
    network: bool | None,
    drive_type: DriveType | None,
) -> Iterator[Progress | ProjectInspection]:
    total = len(PHASES)
    yield Progress(PHASES[0], 0, total, "Leyendo la cabecera del proyecto…")
    _require_folder(root)
    manifest = read_manifest(root)
    record: ProjectRecord | None = None
    migrations: tuple[tuple[int, int], ...] = ()
    check: ManifestCheck | None = None
    header: SqliteHeader | None = None
    if manifest.min_reader_schema > SCHEMA_VERSION:
        relation = SchemaRelation.HEADER_ONLY
        yield Progress(
            PHASES[1], 1, total,
            "No se lee la base de datos: es de un esquema que esta versión no sabe leer",
        )
        yield Progress(PHASES[2], 2, total, "Solo se usa la cabecera del proyecto")
        yield Progress(PHASES[3], 3, total, "Comprobando la versión del esquema…")
    else:
        yield Progress(PHASES[1], 1, total, "Leyendo la base de datos…")
        header, record, migrations, origin_move = _read_database(
            root, userdata.private_read_dir(session.session_uid)
        )
        yield Progress(PHASES[2], 2, total, "Comprobando la cabecera con la base de datos…")
        check = compare(manifest, record, migrations, origin_move)
        error = check.error(record.name)
        if error is not None:
            raise error
        yield Progress(PHASES[3], 3, total, "Comprobando la versión del esquema…")
        relation = _schema_relation(record.schema_version)
        if record.min_reader_schema > SCHEMA_VERSION:  # la base manda
            relation, record = SchemaRelation.HEADER_ONLY, None
    yield Progress(PHASES[4], 4, total, "Comprobando el cerrojo…")
    status = lockmod.inspect(
        root, session, clock=clock, pid_alive=alive, stale_minutes=stale_minutes
    )
    is_network = is_network_path(root, drive_type) if network is None else bool(network)
    yield ProjectInspection(
        root, manifest, record, migrations, check, relation, header, status, is_network
    )


class _OpenAborted(Exception):
    """La apertura en escritura no se completa: se abre en solo lectura con el motivo."""

    def __init__(self, code: ReadOnlyCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _lock_read_only(status: LockStatus) -> OpenStatus:
    code = ReadOnlyCode.RESERVED if status.state is LockState.RESERVED else ReadOnlyCode.LOCKED
    return read_only_status(code, status.describe())


def _take_lock(
    inspection: ProjectInspection,
    session: SessionInfo,
    mode: LockMode,
    force_holder: LockInfo | None,
    clock: Clock,
    alive: PidAlive,
    stale_minutes: int,
) -> tuple[Acquired, bool]:
    """El cerrojo de la sesión y si se forzó; :class:`LockError` si no se puede."""
    status = inspection.lock
    if force_holder is not None and status.can_force:
        acquired = lockmod.force(
            inspection.root, session, mode, force_holder,
            clock=clock, pid_alive=alive, stale_minutes=stale_minutes,
        )
        return acquired, True
    if status.state in (LockState.FREE, LockState.ORPHAN, LockState.OURS):
        acquired = lockmod.acquire(
            inspection.root, session, mode,
            clock=clock, pid_alive=alive, stale_minutes=stale_minutes,
        )
        return acquired, False
    raise lockmod.busy_error(inspection.root, status)


def _open_events(
    inspection: ProjectInspection,
    acquired: Acquired,
    forced: bool,
    wal_bytes: int | None,
    mode: OpenMode,
    session: SessionInfo,
) -> list[tuple[EventKind, str, dict[str, object] | None]]:
    found: list[tuple[EventKind, str, dict[str, object] | None]] = []
    previous = acquired.replaced
    if previous is not None and forced:
        found.append(
            (
                EventKind.LOCK_FORCED,
                f"Cerrojo forzado por {session.user_host}: lo tenía {previous.user} en "
                f"{previous.host} desde {previous.started_at} (última actividad "
                f"{previous.heartbeat_at})",
                {"holder": previous.to_dict()},
            )
        )
    elif previous is not None:
        found.append(
            (
                EventKind.LOCK_ORPHAN_REPLACED,
                f"Cerrojo huérfano sustituido: era de {previous.user} en {previous.host} "
                f"(proceso {previous.pid}, ya terminado) desde {previous.started_at}",
                {"holder": previous.to_dict()},
            )
        )
    if wal_bytes is not None:
        found.append(
            (
                EventKind.WAL_RECOVERED,
                "La base de datos estaba en modo WAL; se ha devuelto al diario clásico",
                {"wal_bytes": wal_bytes},
            )
        )
    if inspection.check.status is ManifestStatus.REWRITE:
        fields = [item.field for item in inspection.check.differences]
        found.append(
            (
                EventKind.MANIFEST_REWRITTEN,
                "La cabecera se ha regenerado desde la base de datos (difería en "
                f"{', '.join(fields)})",
                {"fields": fields},
            )
        )
    found.append(
        (
            EventKind.OPEN,
            f"Proyecto abierto por {session.user_host}: {write_status(mode).message}",
            {"mode": mode.value},
        )
    )
    return found


def _open_for_writing(
    inspection: ProjectInspection,
    acquired: Acquired,
    forced: bool,
    mode: OpenMode,
    session: SessionInfo,
    clock: Clock,
) -> tuple[ProjectRecord, Manifest, list[str]]:
    """Fase 6 en escritura; :class:`_OpenAborted` si hay que quedarse en solo lectura."""
    if inspection.record is None or inspection.check is None:
        raise TypeError("solo se abre en escritura un proyecto cuya base se ha leído")
    root = inspection.root
    path = root / PROJECT_STORE
    warnings: list[str] = []
    wal_bytes: int | None = None
    try:
        if read_header(path).needs_recovery:
            recovery = to_classic_journal(path, timeout_s=BUSY_TIMEOUT_MS / 1000)
            if recovery.outcome is WalOutcome.BUSY:
                raise _OpenAborted(
                    ReadOnlyCode.WAL_BUSY,
                    "QGIS u otro programa tiene abierta la base de datos en modo WAL; cierre "
                    "ese programa y vuelva a abrir el proyecto",
                )
            if recovery.outcome is WalOutcome.CONVERTED:
                wal_bytes = recovery.wal_bytes
                warnings.append(WAL_WARNING)
        now = format_utc(clock.now())
        with GpkgConnection.open_write(path) as db, db.transaction() as conn:
            if inspection.record.last_written_with != session.geoblender_version:
                conn.execute(
                    "UPDATE gb_project SET last_written_with = ?", (session.geoblender_version,)
                )
            for kind, message, data in _open_events(
                inspection, acquired, forced, wal_bytes, mode, session
            ):
                record_event(conn, kind, message, session=session, at=now, data=data)
        with GpkgConnection.open_read(path) as db:
            record = read_project(db.connection)
        if record is None:
            raise DatabaseError(
                "core.gpkg_project_missing", "falta la fila de gb_project",
                obj="Base de datos del proyecto", field="gb_project", value=str(path),
            )
        header = inspection.manifest
        if record != inspection.record or inspection.check.status is ManifestStatus.REWRITE:
            header = manifest_from_record(record, previous=inspection.manifest)
            write_manifest(root, header, session.session_uid)
    except (OSError, sqlite3.Error, DatabaseError, ProjectError) as exc:
        detail = f"no se ha podido escribir al abrir ({exc}); compruebe el disco o la red"
        raise _OpenAborted(ReadOnlyCode.WRITE_FAILED, detail) from exc
    return record, header, warnings


def open_steps(
    path: Path,
    session: SessionInfo,
    userdata: UserData,
    *,
    want_write: bool = True,
    force_holder: LockInfo | None = None,
    clock: Clock = SYSTEM_CLOCK,
    pid_alive: PidAlive = pid_alive,
    stale_minutes: int = lockmod.DEFAULT_STALE_MINUTES,
    network: bool | None = None,
    drive_type: DriveType | None = None,
) -> Iterator[Progress]:
    """Abre el proyecto por pasos (:data:`PHASES`); el último lleva el
    :class:`OpenResult` en ``result``. :class:`ProjectError` si no se puede abrir."""
    root = Path(path)
    total = len(PHASES)
    inspection: ProjectInspection | None = None
    for step in _inspect_steps(
        root, session, userdata, clock, pid_alive, stale_minutes, network, drive_type
    ):
        if isinstance(step, ProjectInspection):
            inspection = step
        else:
            yield step
    if inspection is None:
        raise TypeError("la inspección del proyecto no ha terminado con su resultado")
    warnings: list[str] = []
    check = inspection.check
    rewrite = check is not None and check.status is ManifestStatus.REWRITE
    if check is not None and rewrite and not inspection.header_only:
        fields = ", ".join(item.field for item in check.differences)
        warnings.append(
            f"La cabecera difería de la base de datos en {fields}; manda la base de datos"
            + ("" if want_write else " (se regenerará al abrirlo en escritura)")
        )
    if inspection.manifest.checkout is not None:  # una copia local de trabajo (RF-002-31)
        mode = OpenMode.CHECKOUT
    else:
        mode = OpenMode.WRITE_NETWORK if inspection.network else OpenMode.WRITE_LOCAL
    lock_mode = LockMode.NETWORK if inspection.network else LockMode.LOCAL
    status: OpenStatus
    acquired: Acquired | None = None
    forced = False
    record, header = inspection.record, inspection.manifest
    if inspection.header_only:
        status = read_only_status(
            ReadOnlyCode.SCHEMA_NEWER,
            f"creado con una versión más moderna de Geoblender (esquema "
            f"{header.schema_version}), que esta versión (esquema {SCHEMA_VERSION}) no sabe "
            "leer: solo se muestra la cabecera (nombre, CRS y GeoOrigin); ábralo con "
            f"Geoblender {header.geoblender_version} o posterior",
        )
    elif not want_write or record is None:
        status = read_only_status(ReadOnlyCode.REQUESTED, "abierto así a petición del usuario")
    elif inspection.schema is SchemaRelation.NEWER:
        status = read_only_status(
            ReadOnlyCode.SCHEMA_NEWER,
            f"creado con una versión más moderna de Geoblender (esquema "
            f"{record.schema_version}; esta versión usa el {SCHEMA_VERSION}): para escribir "
            f"en él, ábralo con Geoblender {record.last_written_with} o posterior",
        )
    elif inspection.schema is SchemaRelation.OLDER:
        status = read_only_status(
            ReadOnlyCode.NOT_MIGRATED,
            f"esquema {record.schema_version} sin migrar al {SCHEMA_VERSION}: "
            "para escribir en él hay que migrarlo (antes se hace una copia completa junto "
            "al original)",
        )
    else:
        try:
            acquired, forced = _take_lock(
                inspection, session, lock_mode, force_holder, clock, pid_alive, stale_minutes
            )
            status = write_status(mode)
        except LockError as exc:
            if exc.code in ("core.lock_changed", "core.lock_not_forceable"):
                status = read_only_status(ReadOnlyCode.LOCKED, exc.reason)
            else:
                status = _lock_read_only(inspection.lock)
    try:
        yield Progress(PHASES[5], 5, total, "Abriendo el proyecto…")
        if acquired is not None:
            try:
                record, header, extra = _open_for_writing(
                    inspection, acquired, forced, mode, session, clock
                )
                warnings.extend(extra)
            except _OpenAborted as aborted:
                lockmod.release(root, session, clock=clock)
                acquired = None
                status = read_only_status(aborted.code, aborted.detail)
                log_event(
                    EventKind.WRITE_FAILED, aborted.detail, project=header.project_uid
                )
        project = Project(
            root=root,
            record=record,
            manifest=header,
            session=session,
            userdata=userdata,
            status=status,
            network=inspection.network,
            clock=clock,
            pid_alive=pid_alive,
            stale_minutes=stale_minutes,
        )
        try:
            userdata.add_recent(project.uid, project.name, root, format_utc(clock.now()))
        except (OSError, GeoblenderError):
            pass  # la lista de recientes es una comodidad del equipo
        result = OpenResult(project, status, tuple(warnings), inspection.lock)
        acquired = None  # el cerrojo pasa al proyecto
        yield Progress(PHASES[5], total, total, "Proyecto abierto", result=result)
    finally:
        if acquired is not None:  # cancelado o fallido antes de entregar el proyecto
            lockmod.release(root, session, clock=clock)


def open_project(
    path: Path,
    session: SessionInfo,
    userdata: UserData,
    *,
    want_write: bool = True,
    force_holder: LockInfo | None = None,
    clock: Clock = SYSTEM_CLOCK,
    pid_alive: PidAlive = pid_alive,
    stale_minutes: int = lockmod.DEFAULT_STALE_MINUTES,
    network: bool | None = None,
    drive_type: DriveType | None = None,
) -> OpenResult:
    """Abre el proyecto sin pausas (el mismo recorrido que :func:`open_steps`)."""
    result: object = None
    for step in open_steps(
        path,
        session,
        userdata,
        want_write=want_write,
        force_holder=force_holder,
        clock=clock,
        pid_alive=pid_alive,
        stale_minutes=stale_minutes,
        network=network,
        drive_type=drive_type,
    ):
        if step.result is not None:
            result = step.result
    if not isinstance(result, OpenResult):
        raise TypeError("la apertura del proyecto no ha terminado con su resultado")
    return result
