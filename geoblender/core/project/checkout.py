# SPDX-License-Identifier: GPL-3.0-or-later
"""Copia local de trabajo de un proyecto (spec 002; RF-002-31; ADR-0006 §4;
formato-proyecto §6; plan 002 §5.3 y §5.4, «Copia local»).

Para calcular deprisa sin arriesgar el original (que suele estar en ``Z:``), se trabaja en
una copia en el disco local y después se publica. :func:`checkout_steps` es un generador
de pasos (:class:`~.model.Progress`) que un operador modal avanza con progreso; cerrarlo
(``close()``) antes del final cancela y no deja nada: ni copia, ni registro, ni reserva.

1. **Comprobación** (sin escribir): el original se puede abrir (cabecera y base
   coherentes), es del esquema de esta versión (uno anterior se migra antes; uno posterior
   no se toca), no es él mismo una copia local, y la carpeta de las copias existe y no está
   dentro del original. Su cerrojo tiene que estar libre o huérfano: si lo tiene otra
   sesión no se reserva (:class:`~..errors.LockError` con quién lo tiene); si lo tiene esta
   misma sesión abierto en escritura, hay que cerrarlo antes.
2. **Reserva** del original: su ``.lock`` en modo ``checkout``, a nombre de esta sesión.
   Mientras dure, nadie lo abre en escritura (lo ven «reservado para una copia local»); la
   reserva sobrevive a la sesión y solo se quita al publicar o forzándola con aviso.
3. **Copia** sin ``cache/`` ni ``.lock`` a ``<carpeta>/<Nombre>.gbproj`` (``<Nombre>-2``…
   si ya existe: nunca se sustituye otra copia) con ``core.project.copytree``: por trozos,
   con espacio libre comprobado antes y la copia vuelta a leer y comparada con las huellas
   del original. Si el original estaba en WAL (QGIS), antes se devuelve al diario clásico;
   si otro programa escribe en su base mientras se copia, la copia se descarta.
4. **Preparación** de la copia: en su base, el evento ``checkout`` (y los que no se
   pudieron escribir en el original: ``wal_recovered``, ``lock_orphan_replaced``); en su
   cabecera, la sección ``checkout`` (sesión de la reserva, huella de partida del original,
   fecha y persona; **sin** la ruta del original, ADR-0006 §5); y en los datos de usuario
   de este equipo, ``projects/<uid>/checkout.json`` con la ruta del original y las huellas
   de partida fichero a fichero.
5. **Apertura** de la copia en escritura (``open_steps``): modo ``CHECKOUT``.

El original no cambia salvo su ``.lock`` (y, si estaba en WAL, su diario).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..errors import ProjectError
from ..gpkg.connection import BUSY_TIMEOUT_MS, GpkgConnection
from ..gpkg.header import read_header
from ..gpkg.wal import WalOutcome, to_classic_journal
from ..paths import DriveType, is_within, next_free_path
from ..sysinfo import SessionInfo, pid_alive
from ..timeutil import SYSTEM_CLOCK, Clock, format_utc
from ..userdata import UserData
from . import lock as lockmod
from .copytree import (
    CHUNK_SIZE,
    CopyResult,
    DiskUsageFn,
    TreePrints,
    copy_steps,
    remove_tree,
    tree_digest,
)
from .events import EventKind, record_event
from .lock import LockMode, LockState, PidAlive
from .manifest import PROJECT_STORE, read_manifest, write_manifest
from .model import OpenResult, ProjectRecord, Progress
from .open import ProjectInspection, SchemaRelation, inspect_project, open_steps
from .schema import SCHEMA_VERSION

PROJECT_SUFFIX = ".gbproj"
CHECKOUT_EXCLUDE: tuple[str, ...] = ("cache", ".lock")
CHECKOUT_PHASES: tuple[str, ...] = ("comprobación", "reserva", "copia", "preparación", "apertura")
WAL_WARNING = (
    "La base de datos del original estaba en modo WAL (QGIS lo activa al editar un "
    "GeoPackage); se ha devuelto al diario clásico antes de copiarla, sin perder datos."
)

_Event = tuple[EventKind, str, dict[str, object]]


@dataclass(frozen=True)
class CheckoutResult:
    """Una copia local sacada y abierta: el original (reservado), la copia, la huella de
    partida del original (:func:`~.copytree.tree_digest`) con sus huellas fichero a
    fichero, la copia abierta en escritura y los avisos."""

    original: Path
    copy: Path
    base: str
    prints: TreePrints
    opened: OpenResult
    warnings: tuple[str, ...] = ()


def _stem(root: Path) -> str:
    name = root.name
    return name[: -len(PROJECT_SUFFIX)] if name.endswith(PROJECT_SUFFIX) else name


def _source_record(inspection: ProjectInspection) -> ProjectRecord:
    """La fila de ``gb_project`` del original si se le puede sacar una copia local;
    :class:`ProjectError` si no."""
    obj = f"Proyecto «{_stem(inspection.root)}»"
    record = inspection.record
    if record is None or inspection.header_only:
        raise ProjectError(
            "core.checkout_header_only",
            "es de un esquema posterior que esta versión de Geoblender no sabe leer: no se "
            "saca copia local; use una versión más moderna",
            obj=obj,
            field="esquema",
            value=inspection.manifest.schema_version,
        )
    if inspection.schema is SchemaRelation.OLDER:
        raise ProjectError(
            "core.checkout_not_migrated",
            f"tiene el esquema {record.schema_version}, anterior al {SCHEMA_VERSION} de esta "
            "versión: ábralo y acepte migrarlo antes de sacar una copia local",
            obj=obj,
            field="esquema",
            value=record.schema_version,
        )
    if inspection.schema is SchemaRelation.NEWER:
        raise ProjectError(
            "core.checkout_schema_newer",
            f"es de un esquema posterior ({record.schema_version}) al de esta versión "
            f"({SCHEMA_VERSION}): no se saca copia local; use Geoblender "
            f"{record.last_written_with} o posterior",
            obj=obj,
            field="esquema",
            value=record.schema_version,
        )
    if inspection.manifest.checkout is not None:
        raise ProjectError(
            "core.checkout_of_checkout",
            "ya es una copia local de trabajo: no se saca una copia de una copia; trabaje en "
            "ella y publíquela en la red",
            obj=obj,
            field="copia local",
            shown="ya es una copia local",
        )
    return record


def _check_dest_dir(original: Path, dest_dir: Path, obj: str) -> None:
    if not dest_dir.is_dir():
        raise ProjectError(
            "core.checkout_dest_missing",
            "no existe la carpeta de las copias locales: elija una carpeta existente (o deje "
            "vacía la preferencia para usar la de los datos de usuario)",
            obj=obj,
            field="carpeta de las copias locales",
            value=str(dest_dir),
        )
    if is_within(dest_dir, original):
        raise ProjectError(
            "core.checkout_dest_inside",
            "la carpeta de las copias locales está dentro del proyecto original: elija otra",
            obj=obj,
            field="carpeta de las copias locales",
            value=str(dest_dir),
        )


def _check_lock(inspection: ProjectInspection, obj: str) -> None:
    status = inspection.lock
    if status.state is LockState.OURS:
        raise ProjectError(
            "core.checkout_open_here",
            "lo tiene abierto en escritura esta misma sesión: ciérrelo antes de sacar la "
            "copia local",
            obj=obj,
            field="cerrojo",
            shown=status.describe(),
        )
    if status.state not in (LockState.FREE, LockState.ORPHAN):
        raise lockmod.busy_error(inspection.root, status)


def _recover_wal(database: Path, obj: str) -> tuple[list[_Event], list[str]]:
    """La base del original en diario clásico antes de copiarla (con la reserva ya
    tomada); evento y aviso si estaba en WAL."""
    if not read_header(database).needs_recovery:
        return [], []
    recovery = to_classic_journal(database, timeout_s=BUSY_TIMEOUT_MS / 1000)
    if recovery.outcome is WalOutcome.BUSY:
        raise ProjectError(
            "core.checkout_wal_busy",
            "QGIS u otro programa tiene abierta la base de datos del original en modo WAL: "
            "no se ha copiado nada y el original queda libre; cierre ese programa y vuelva a "
            "sacar la copia",
            obj=obj,
            field="diario",
            value=str(database),
        )
    if recovery.outcome is not WalOutcome.CONVERTED:
        return [], []
    event: _Event = (
        EventKind.WAL_RECOVERED,
        "La base de datos del original estaba en modo WAL; se ha devuelto al diario "
        "clásico antes de sacar la copia local",
        {"wal_bytes": recovery.wal_bytes},
    )
    return [event], [WAL_WARNING]


def _changed(database: Path, counter: int) -> bool:
    """Verdadero si alguien escribió en la base desde que se leyó ``counter``."""
    header = read_header(database)
    return header.change_counter != counter or header.journal == "wal" or header.has_wal


def _prepare_copy(
    copy_root: Path,
    original: Path,
    section: dict[str, Any],
    events: Sequence[_Event],
    session: SessionInfo,
    now: str,
) -> None:
    """Los eventos en la base de la copia y la sección ``checkout`` en su cabecera."""
    with GpkgConnection.open_write(copy_root / PROJECT_STORE) as db, db.transaction() as conn:
        for kind, message, data in events:
            record_event(conn, kind, message, session=session, at=now, data=data)
        record_event(
            conn,
            EventKind.CHECKOUT,
            f"Copia local de trabajo sacada de «{original.name}» por {session.user_host}: el "
            "original queda reservado para ella hasta publicarla",
            session=session,
            at=now,
            data={"original": original.name, "base": section["base"]},
        )
    header = read_manifest(copy_root)
    write_manifest(copy_root, replace(header, checkout=section), session.session_uid)


def checkout_steps(
    original: Path,
    dest_dir: Path,
    session: SessionInfo,
    userdata: UserData,
    *,
    clock: Clock = SYSTEM_CLOCK,
    pid_alive: PidAlive = pid_alive,
    stale_minutes: int = lockmod.DEFAULT_STALE_MINUTES,
    network: bool | None = None,
    drive_type: DriveType | None = None,
    disk_usage: DiskUsageFn = shutil.disk_usage,
    chunk_size: int = CHUNK_SIZE,
) -> Iterator[Progress]:
    """Saca una copia local de ``original`` en ``dest_dir`` y la abre en escritura, por
    pasos (:data:`CHECKOUT_PHASES`); el último lleva el :class:`CheckoutResult`.

    ``network``/``drive_type``: la detección de la red, como al abrir (inyectable).
    :class:`ProjectError` o :class:`~..errors.LockError` con el motivo si no se puede; en
    ese caso, y al cancelar, no queda copia, ni registro, ni reserva.
    """
    original = Path(os.path.abspath(original))
    dest_dir = Path(os.path.abspath(dest_dir))
    total = len(CHECKOUT_PHASES)
    yield Progress(CHECKOUT_PHASES[0], 0, total, "Comprobando el proyecto original…")
    inspection = inspect_project(
        original, session, userdata, clock=clock, pid_alive=pid_alive,
        stale_minutes=stale_minutes, network=network, drive_type=drive_type,
    )
    record = _source_record(inspection)
    obj = f"Proyecto «{record.name}»"
    _check_dest_dir(original, dest_dir, obj)
    _check_lock(inspection, obj)
    yield Progress(CHECKOUT_PHASES[1], 1, total, "Reservando el original para la copia local…")
    acquired = lockmod.acquire(
        original, session, LockMode.CHECKOUT,
        clock=clock, pid_alive=pid_alive, stale_minutes=stale_minutes,
    )
    copy_root = next_free_path(dest_dir, _stem(original), PROJECT_SUFFIX)
    database = original / PROJECT_STORE
    finished = copied_here = recorded = False
    copied: CopyResult | None = None
    opened: OpenResult | None = None
    try:
        events, warnings = _recover_wal(database, obj)
        replaced = acquired.replaced
        if replaced is not None:
            events.insert(
                0,
                (
                    EventKind.LOCK_ORPHAN_REPLACED,
                    f"Cerrojo huérfano del original sustituido para sacar la copia local: era "
                    f"de {replaced.user} en {replaced.host} (proceso {replaced.pid}, ya "
                    f"terminado) desde {replaced.started_at}",
                    {"holder": replaced.to_dict()},
                ),
            )
        counter = read_header(database).change_counter
        for step in copy_steps(
            original, copy_root, exclude=CHECKOUT_EXCLUDE, clock=clock, disk_usage=disk_usage,
            chunk_size=chunk_size,
        ):
            if isinstance(step.result, CopyResult):
                copied, copied_here = step.result, True
            yield Progress(CHECKOUT_PHASES[2], step.done, step.total, step.message)
        if copied is None:
            raise TypeError("la copia no ha terminado con su resultado")
        if _changed(database, counter):
            raise ProjectError(
                "core.checkout_source_changed",
                "otro programa (QGIS, por ejemplo) ha escrito en la base de datos del original "
                "mientras se copiaba: la copia se ha descartado y el original queda libre; "
                "cierre ese programa y vuelva a sacar la copia",
                obj=obj,
                field=PROJECT_STORE,
                value=str(database),
            )
        yield Progress(CHECKOUT_PHASES[3], 3, total, "Preparando la copia local…")
        base = tree_digest(copied.prints)
        now = format_utc(clock.now())
        section: dict[str, Any] = {
            "session_uid": session.session_uid,
            "base": base,
            "at": now,
            "by": session.user_host,
        }
        _prepare_copy(copy_root, original, section, events, session, now)
        userdata.set_checkout_record(
            record.uid,
            {
                "original": os.fspath(original),
                "copy": os.fspath(copy_root),
                "session_uid": session.session_uid,
                "base": base,
                "at": now,
                "by": session.user_host,
                "prints": copied.prints.to_dict(),
            },
        )
        recorded = True
        opening = open_steps(
            copy_root, session, userdata, clock=clock, pid_alive=pid_alive,
            stale_minutes=stale_minutes, drive_type=drive_type,
        )
        try:
            for step in opening:
                if isinstance(step.result, OpenResult):
                    opened = step.result
                yield Progress(CHECKOUT_PHASES[4], step.done, step.total, step.message)
        finally:
            opening.close()
        if opened is None:
            raise TypeError("la apertura de la copia no ha terminado con su resultado")
        finished = True
    finally:
        if not finished:
            if copied_here:
                remove_tree(copy_root, clock)
            if recorded:
                userdata.clear_checkout_record(record.uid)
            try:
                lockmod.release(original, session, clock=clock)
            except OSError:
                pass  # la reserva quedaría: se puede forzar con aviso
    yield Progress(
        CHECKOUT_PHASES[4], total, total, "Copia local abierta",
        result=CheckoutResult(
            original, copy_root, base, copied.prints, opened, tuple(warnings)
        ),
    )
