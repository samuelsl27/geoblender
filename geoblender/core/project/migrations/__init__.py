# SPDX-License-Identifier: GPL-3.0-or-later
"""Migraciones del esquema del proyecto (spec 002; RF-002-20, RF-002-21; ADR-0006 §7;
formato-proyecto §7; plan 002 §5.4, «Migración»).

Un proyecto de un esquema anterior al de esta versión de Geoblender se abre siempre: en
solo lectura «sin migrar» si el usuario no acepta migrarlo (``core.project.open``) y, si
acepta, se migra con :func:`migrate_steps` antes de abrirlo en escritura. Reglas (spec
002 §6, I-1 a I-6):

- Cada migración (:class:`Migration`) lleva de un esquema N al N+1 y es idempotente; las
  forman una cadena sin huecos (:func:`plan_migrations`) que se comprueba **antes** de
  tocar nada. Cada una es un módulo ``m<NNNN>.py`` de este paquete (con el tipo de
  ``base``, para no importar el paquete) que se añade a :data:`REGISTRY` (la 1 → 2,
  ``m0002``, de la spec 008) y, si toca otros almacenes además del GeoPackage, declara
  cómo se recupera.
- Solo migra la sesión que tiene el cerrojo (libre, huérfano o suyo; si lo tiene otra,
  :class:`~..errors.LockError` sin tocar nada). Si otro programa dejó la base en WAL, se
  devuelve antes al diario clásico (si la tiene abierta, no se copia ni migra nada).
- **Copia previa** completa junto al original, ``<Nombre>.gbproj.respaldo-esquema-<N>``
  (``-2``, ``-3``… si ya hay una), sin ``cache/`` (regenerable) ni ``.lock`` (de la
  sesión, no del proyecto), con sus huellas comprobadas (``core.project.copytree``).
- **Una transacción**: todas las migraciones, una fila de ``gb_schema_migration`` y un
  evento ``migration`` por cada una, y el esquema nuevo en ``gb_project``. Al empezarla,
  con el cerrojo de escritura de SQLite ya tomado, se comprueba con el contador de cambios
  de la base que nadie escribió en ella desde que empezó la copia previa: si alguien lo
  hizo (QGIS), la copia ya no es la del proyecto antes de migrar, se descarta y no se
  migra nada.
- Después, la **cabecera se regenera desde la base de datos**. Si no se puede escribir,
  la base ya migrada manda: al abrir, la migración registrada explica el esquema distinto
  y la cabecera se regenera.
- Si una migración falla, ``ROLLBACK``: la base queda exactamente como estaba, la
  cabecera no se toca, se conserva la copia previa y el error dice qué migración falló y
  dónde está la copia (RF-002-21); el fallo va al registro técnico (no se puede escribir
  en el proyecto). Cancelar antes de migrar no cambia nada y descarta la copia previa.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from ...errors import DatabaseError, GeoblenderError, ProjectError
from ...gpkg.connection import BUSY_TIMEOUT_MS, GpkgConnection
from ...gpkg.header import read_header
from ...gpkg.wal import WalOutcome, to_classic_journal
from ...paths import DriveType
from ...sysinfo import SessionInfo, pid_alive
from ...timeutil import SYSTEM_CLOCK, Clock, format_utc
from ...userdata import UserData
from .. import lock as lockmod
from ..copytree import DiskUsageFn, copy_steps, remove_tree
from ..events import EventKind, log_event, record_event
from ..lock import LockMode, LockState, PidAlive
from ..manifest import PROJECT_STORE, Manifest, manifest_from_record, write_manifest
from ..model import Progress
from ..open import WAL_WARNING, inspect_project
from ..schema import SCHEMA_VERSION, read_project
from .base import Migration
from .m0002 import MIGRATION as _MIGRATION_0002

BACKUP_MARK = ".respaldo-esquema-"
BACKUP_EXCLUDE: tuple[str, ...] = ("cache", ".lock")
PHASES: tuple[str, ...] = ("comprobación", "cerrojo", "copia previa", "migración")
_CHAIN = "Migraciones del esquema del proyecto"

_Event = tuple[EventKind, str, dict[str, object]]

REGISTRY: tuple[Migration, ...] = (_MIGRATION_0002,)
"""Las migraciones de esta versión, una por esquema: 1 → 2, la procedencia (``m0002``,
spec 008)."""


@dataclass(frozen=True)
class MigrationResult:
    """Un proyecto migrado (o que no hacía falta migrar: ``applied`` vacío y sin copia)."""

    root: Path
    from_version: int
    to_version: int
    applied: tuple[tuple[int, int], ...]
    backup: Path | None
    warnings: tuple[str, ...] = ()


def _chain_error(code: str, reason: str, shown: str) -> ProjectError:
    return ProjectError(code, reason, obj=_CHAIN, field="cadena", shown=shown)


def plan_migrations(
    current: int, target: int, registry: Sequence[Migration] = REGISTRY
) -> tuple[Migration, ...]:
    """Las migraciones, en orden, que llevan del esquema ``current`` al ``target``.

    :class:`ProjectError` si el registro no es una cadena válida (una migración que no va
    de N a N+1, o dos desde el mismo esquema), si falta algún paso (hueco) o si
    ``current`` es posterior a ``target`` (no se migra hacia atrás).
    """
    if current > target:
        raise ProjectError(
            "core.migration_newer",
            f"el proyecto tiene un esquema posterior al {target} de esta versión de "
            "Geoblender: no se migra hacia atrás; ábralo con una versión más moderna",
            obj="Esquema del proyecto",
            field="schema_version",
            value=current,
        )
    by_source: dict[int, Migration] = {}
    for migration in registry:
        if migration.to_version != migration.from_version + 1:
            raise _chain_error(
                "core.migration_invalid",
                "cada migración lleva de un esquema N al N+1 (spec 002, I-4): no se migra nada",
                migration.step,
            )
        if migration.from_version in by_source:
            raise _chain_error(
                "core.migration_invalid",
                f"hay dos migraciones desde el esquema {migration.from_version}: no se migra nada",
                migration.step,
            )
        by_source[migration.from_version] = migration
    chain: list[Migration] = []
    for version in range(current, target):
        migration = by_source.get(version)
        if migration is None:
            raise _chain_error(
                "core.migration_gap",
                f"falta la migración {version} → {version + 1}: la cadena del esquema "
                f"{current} al {target} tiene un hueco y no se migra nada",
                f"{current} → {target}",
            )
        chain.append(migration)
    return tuple(chain)


def backup_path(root: Path, from_version: int) -> Path:
    """La carpeta de la copia previa, junto al original:
    ``<Nombre>.gbproj.respaldo-esquema-<N>`` o, si ya existe, con ``-2``, ``-3``…"""
    root = Path(root)
    base = f"{root.name}{BACKUP_MARK}{from_version}"
    candidate, number = root.parent / base, 1
    while candidate.exists():
        number += 1
        candidate = root.parent / f"{base}-{number}"
    return candidate


# Pasos ---------------------------------------------------------------------------------


class _SourceChanged(Exception):
    """Otro programa escribió en la base desde que empezó la copia previa."""


class _Failed(Exception):
    """Una migración (o la transacción) falló: la base quedó como estaba."""

    def __init__(self, step: str, error: BaseException) -> None:
        super().__init__(step)
        self.step = step
        self.error = error


def _recover_wal(database: Path, obj: str) -> tuple[list[_Event], list[str]]:
    """La base en diario clásico antes de copiarla (evento y aviso si estaba en WAL)."""
    if not read_header(database).needs_recovery:
        return [], []
    recovery = to_classic_journal(database, timeout_s=BUSY_TIMEOUT_MS / 1000)
    if recovery.outcome is WalOutcome.BUSY:
        raise ProjectError(
            "core.migration_wal_busy",
            "QGIS u otro programa tiene abierta la base de datos en modo WAL: no se ha "
            "copiado ni migrado nada; cierre ese programa y vuelva a intentarlo",
            obj=obj,
            field="diario",
            value=str(database),
        )
    if recovery.outcome is not WalOutcome.CONVERTED:
        return [], []
    event: _Event = (
        EventKind.WAL_RECOVERED,
        "La base de datos estaba en modo WAL; se ha devuelto al diario clásico",
        {"wal_bytes": recovery.wal_bytes},
    )
    return [event], [WAL_WARNING]


def _changed(database: Path, counter: int) -> bool:
    """Verdadero si alguien escribió en la base desde que se leyó ``counter``."""
    header = read_header(database)
    return header.change_counter != counter or header.journal == "wal" or header.has_wal


def _apply_chain(
    database: Path,
    chain: Sequence[Migration],
    target: int,
    counter: int,
    backup_name: str,
    events: Sequence[_Event],
    session: SessionInfo,
    clock: Clock,
) -> None:
    """Todas las migraciones, sus filas de ``gb_schema_migration``, sus eventos y el
    esquema nuevo, en una transacción. :class:`_SourceChanged` o :class:`_Failed`."""
    now = format_utc(clock.now())
    step = "al empezar la transacción"
    try:
        if _changed(database, counter):
            raise _SourceChanged()
        with GpkgConnection.open_write(database) as db, db.transaction() as conn:
            if _changed(database, counter):  # ya con el cerrojo de escritura de SQLite
                raise _SourceChanged()
            for kind, message, data in events:
                record_event(conn, kind, message, session=session, at=now, data=data)
            min_reader = int(conn.execute("SELECT min_reader_schema FROM gb_project").fetchone()[0])
            for migration in chain:
                step = migration.step
                migration.apply(conn)
                conn.execute(
                    "INSERT INTO gb_schema_migration (from_version, to_version, applied_at, "
                    "applied_with, backup_dir, user_host) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        migration.from_version,
                        migration.to_version,
                        now,
                        session.geoblender_version,
                        backup_name,
                        session.user_host,
                    ),
                )
                record_event(
                    conn,
                    EventKind.MIGRATION,
                    f"Esquema del proyecto migrado de {migration.from_version} a "
                    f"{migration.to_version} ({migration.description}); copia previa "
                    f"«{backup_name}» junto al original",
                    session=session,
                    at=now,
                    data={
                        "from": migration.from_version,
                        "to": migration.to_version,
                        "backup_dir": backup_name,
                    },
                )
                if migration.min_reader_schema is not None:
                    min_reader = migration.min_reader_schema
            step = "al guardar el esquema nuevo"
            conn.execute(
                "UPDATE gb_project SET schema_version = ?, min_reader_schema = ?, "
                "last_written_with = ?, modified_at = ?",
                (target, min_reader, session.geoblender_version, now),
            )
            step = "al confirmar la transacción"
    except _SourceChanged:
        raise
    except DatabaseError as exc:
        if exc.code == "core.gpkg_wal":  # otro programa la ha pasado a WAL entretanto
            raise _SourceChanged() from exc
        raise _Failed(step, exc) from exc
    except Exception as exc:  # la migración es código: cualquier fallo la deshace
        raise _Failed(step, exc) from exc


def _rewrite_header(
    root: Path, database: Path, previous: Manifest, session: SessionInfo, target: int
) -> list[str]:
    """Regenera la cabecera desde la base ya migrada (conservando de ``previous`` lo que
    la base no tiene); un aviso si no se puede."""
    try:
        with GpkgConnection.open_read(database) as db:
            record = read_project(db.connection)
        if record is None:
            raise ProjectError(
                "core.gpkg_project_missing", "falta la fila de gb_project",
                obj="Base de datos del proyecto", field="gb_project", value=str(database),
            )
        header = manifest_from_record(record, previous=previous)
        write_manifest(root, header, session.session_uid)
    except (GeoblenderError, OSError, sqlite3.Error) as exc:
        message = (
            f"La base de datos ya está migrada al esquema {target}, pero no se ha podido "
            f"actualizar la cabecera (manifest.json): {exc}. Se regenerará desde la base de "
            "datos al abrir el proyecto."
        )
        log_event(EventKind.WRITE_FAILED, message)
        return [message]
    return []


def migrate_steps(
    path: Path,
    session: SessionInfo,
    userdata: UserData,
    registry: Sequence[Migration] = REGISTRY,
    *,
    target: int | None = None,
    clock: Clock = SYSTEM_CLOCK,
    pid_alive: PidAlive = pid_alive,
    stale_minutes: int = lockmod.DEFAULT_STALE_MINUTES,
    network: bool | None = None,
    drive_type: DriveType | None = None,
    disk_usage: DiskUsageFn = shutil.disk_usage,
) -> Iterator[Progress]:
    """Migra el proyecto de ``path`` al esquema ``target`` (por defecto, el de esta
    versión) por pasos (:data:`PHASES`); el último lleva el :class:`MigrationResult`.

    Lo llama quien ha aceptado migrar (RF-002-20). Cerrar el generador antes de la fase
    «migración» cancela sin cambiar nada. :class:`ProjectError` (o :class:`LockError`) con
    el motivo si no se puede migrar o si falla (RF-002-21).
    """
    root = Path(path)
    goal = SCHEMA_VERSION if target is None else int(target)
    total = len(PHASES)
    yield Progress(PHASES[0], 0, total, "Comprobando el proyecto y sus migraciones…")
    inspection = inspect_project(
        root, session, userdata, clock=clock, pid_alive=pid_alive,
        stale_minutes=stale_minutes, network=network, drive_type=drive_type,
    )
    record = inspection.record
    if record is None:  # solo cabecera: un esquema posterior que no se sabe leer
        raise ProjectError(
            "core.migration_newer",
            "el proyecto es de un esquema posterior que esta versión de Geoblender no sabe "
            "leer: no se migra hacia atrás; ábralo con una versión más moderna",
            obj="Esquema del proyecto",
            field="schema_version",
            value=inspection.manifest.schema_version,
        )
    current = record.schema_version
    chain = plan_migrations(current, goal, registry)
    if not chain:
        yield Progress(
            PHASES[0], total, total, f"El proyecto ya tiene el esquema {goal}: no hay nada que migrar",
            result=MigrationResult(root, current, current, (), None),
        )
        return
    obj = f"Proyecto «{record.name}»"
    yield Progress(PHASES[1], 1, total, "Tomando el cerrojo del proyecto…")
    status = inspection.lock
    if status.state not in (LockState.FREE, LockState.ORPHAN, LockState.OURS):
        raise lockmod.busy_error(root, status)
    keep_lock = status.state is LockState.OURS
    mode = LockMode.NETWORK if inspection.network else LockMode.LOCAL
    acquired = lockmod.acquire(
        root, session, mode, clock=clock, pid_alive=pid_alive, stale_minutes=stale_minutes
    )
    database = root / PROJECT_STORE
    backup: Path | None = None
    keep_backup = False
    try:
        events, warnings = _recover_wal(database, obj)
        if acquired.replaced is not None:
            previous = acquired.replaced
            events.insert(
                0,
                (
                    EventKind.LOCK_ORPHAN_REPLACED,
                    f"Cerrojo huérfano sustituido para migrar: era de {previous.user} en "
                    f"{previous.host} (proceso {previous.pid}, ya terminado) desde "
                    f"{previous.started_at}",
                    {"holder": previous.to_dict()},
                ),
            )
        counter = read_header(database).change_counter
        planned = backup_path(root, current)
        for step in copy_steps(
            root, planned, exclude=BACKUP_EXCLUDE, clock=clock, disk_usage=disk_usage
        ):
            if step.result is not None:
                backup = planned
            yield Progress(PHASES[2], step.done, step.total, step.message)
        if backup is None:
            raise TypeError("la copia previa no ha terminado con su resultado")
        yield Progress(PHASES[3], 0, len(chain), f"Migrando el esquema {current} → {goal}…")
        try:
            _apply_chain(database, chain, goal, counter, backup.name, events, session, clock)
        except _SourceChanged as exc:
            raise ProjectError(
                "core.migration_source_changed",
                "otro programa (QGIS, por ejemplo) ha escrito en la base de datos mientras se "
                "hacía la copia previa, así que esa copia ya no es la del proyecto antes de "
                "migrar: se ha descartado y no se ha migrado nada (lo que escribió ese "
                "programa se conserva); cierre ese programa y vuelva a intentarlo",
                obj=obj,
                field="esquema",
                shown=f"{current} → {goal}",
            ) from exc
        except _Failed as failure:
            keep_backup = True
            detail = (
                f"la migración del esquema {failure.step} ha fallado ({failure.error}); el "
                f"proyecto se ha dejado como estaba antes de migrar (esquema {current}) y se "
                f"conserva la copia previa «{backup.name}» junto al original"
            )
            log_event(EventKind.MIGRATION_FAILED, detail, project=record.uid)
            raise ProjectError(
                "core.migration_failed",
                detail + "; no lo abra en escritura con esta versión y comunique el fallo a "
                "quien mantiene Geoblender, con el registro técnico",
                obj=obj,
                field="esquema",
                shown=f"{current} → {goal}",
            ) from failure.error
        keep_backup = True
        warnings += _rewrite_header(root, database, inspection.manifest, session, goal)
    finally:
        if backup is not None and not keep_backup:
            remove_tree(backup, clock)
        if not keep_lock:
            try:
                lockmod.release(root, session, clock=clock)
            except OSError:
                pass  # quedará huérfano: se sustituye al abrirlo en este equipo
    yield Progress(
        PHASES[3], len(chain), len(chain), f"Proyecto migrado al esquema {goal}",
        result=MigrationResult(
            root, current, goal, tuple((m.from_version, m.to_version) for m in chain), backup,
            tuple(warnings),
        ),
    )
