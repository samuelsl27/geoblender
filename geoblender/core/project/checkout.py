# SPDX-License-Identifier: GPL-3.0-or-later
"""Copia local de trabajo de un proyecto y su publicación (spec 002; RF-002-31,
RF-002-32, RF-002-33; ADR-0006 §4; formato-proyecto §6; plan 002 §5.3 y §5.4, «Copia
local» y «Publicación»).

Para calcular deprisa sin arriesgar el original (que suele estar en ``Z:``), se trabaja en
una copia en el disco local y después se publica. :func:`checkout_steps` y
:func:`publish_steps` son generadores de pasos (:class:`~.model.Progress`) que un operador
modal avanza con progreso; cerrarlos (``close()``) antes del final cancela.

Sacar la copia (:func:`checkout_steps`); cancelar no deja nada (ni copia, ni registro, ni
reserva):

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

Publicar la copia (:func:`publish_steps`); el original nunca queda a medias:

1. **Comprobación**: la copia está abierta en escritura y es una copia local; este equipo
   sabe dónde está su original (``checkout.json``), que es del mismo proyecto; y el
   original **sigue reservado para esta copia** (su ``.lock`` en modo ``checkout`` con la
   sesión de la sección ``checkout``).
2. **Original**: sus huellas (sin ``cache/`` ni ``.lock``) siguen siendo las de partida;
   si no, alguien lo cambió (QGIS) y publicar perdería esos cambios.
3. **Copia** de la copia local, sin ``cache/`` ni ``.lock``, a
   ``<Nombre>.gbproj.publicando`` junto al original, con sus huellas comprobadas.
4. **Preparación** de ``.publicando``: el evento ``publish`` en su base y su cabecera
   regenerada desde ella con ``checkout = null``. La copia local no se toca.
5. **Sustitución**, en un solo paso (no se puede cancelar a mitad): el original pasa a
   ``<Nombre>.gbproj.anterior`` (la anterior se aparta antes y se borra al final: se
   conserva una sola) y ``.publicando`` al nombre del original; después se borra el
   ``.lock`` de ``.anterior``, que era la reserva. Cancelar antes de este paso borra
   ``.publicando``. Al terminar se cierra la copia local, se quita su registro del equipo y
   el publicado pasa a ser el primero de los recientes.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..errors import GeoblenderError, ProjectError
from ..gpkg.connection import BUSY_TIMEOUT_MS, GpkgConnection
from ..gpkg.header import read_header
from ..gpkg.wal import WalOutcome, to_classic_journal
from ..ids import new_uid
from ..paths import DriveType, is_within, next_free_path
from ..sysinfo import SessionInfo, pid_alive
from ..timeutil import SYSTEM_CLOCK, Clock, format_utc
from ..userdata import UserData
from . import lock as lockmod
from .copytree import (
    CHUNK_SIZE,
    RETRIES,
    RETRY_WAIT_S,
    CopyResult,
    DiskUsageFn,
    FilePrint,
    TreePrints,
    copy_steps,
    fingerprint_steps,
    remove_tree,
    tree_digest,
)
from .events import EventKind, record_event
from .lock import LockMode, LockState, PidAlive
from .manifest import (
    MANIFEST_FILE,
    PROJECT_STORE,
    manifest_from_record,
    read_manifest,
    write_manifest,
)
from .model import OpenResult, ProjectRecord, Progress
from .open import ProjectInspection, SchemaRelation, inspect_project, open_steps
from .schema import SCHEMA_VERSION, read_project

if TYPE_CHECKING:
    from .session import Project

PROJECT_SUFFIX = ".gbproj"
CHECKOUT_EXCLUDE: tuple[str, ...] = ("cache", ".lock")
CHECKOUT_PHASES: tuple[str, ...] = ("comprobación", "reserva", "copia", "preparación", "apertura")
PUBLISH_PHASES: tuple[str, ...] = (
    "comprobación", "original", "copia", "preparación", "sustitución"
)
PUBLISHING_MARK = ".publicando"
PREVIOUS_MARK = ".anterior"
DISCARD_MARK = ".borrando-"
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


# Publicación ----------------------------------------------------------------------------


@dataclass(frozen=True)
class PublishResult:
    """Una copia local publicada: el original (ya con el contenido de la copia), el
    original anterior (``<Nombre>.gbproj.anterior``), la copia local (cerrada: se puede
    borrar), las huellas del publicado (sin ``.lock``) y los avisos."""

    original: Path
    previous: Path
    local: Path
    prints: TreePrints
    warnings: tuple[str, ...] = ()


def publishing_path(original: Path) -> Path:
    """``<Nombre>.gbproj.publicando``, junto al original."""
    original = Path(original)
    return original.parent / f"{original.name}{PUBLISHING_MARK}"


def previous_path(original: Path) -> Path:
    """``<Nombre>.gbproj.anterior``, junto al original."""
    original = Path(original)
    return original.parent / f"{original.name}{PREVIOUS_MARK}"


def _rename(source: Path, target: Path) -> None:
    """Renombra una carpeta (las pruebas lo sustituyen para simular una carpeta retenida).
    En Windows no sustituye un destino que ya existe."""
    source.rename(target)


def _rename_retrying(source: Path, target: Path, clock: Clock) -> None:
    """:func:`_rename`, reintentado :data:`~.copytree.RETRIES` veces cada
    :data:`~.copytree.RETRY_WAIT_S` s si otro programa retiene algo (antivirus,
    indexador)."""
    for attempt in range(RETRIES + 1):
        try:
            _rename(source, target)
            return
        except PermissionError:
            if attempt == RETRIES:
                raise
            clock.sleep(RETRY_WAIT_S)


def _local_section(local: Project) -> Mapping[str, Any]:
    """La sección ``checkout`` de la copia local, si se puede publicar."""
    obj = f"Proyecto «{local.name}»"
    section = local.manifest.checkout
    if section is None:
        raise ProjectError(
            "core.publish_not_checkout",
            "no es una copia local de trabajo: solo se publica una copia sacada con «Trabajar "
            "en copia local»",
            obj=obj,
            field="copia local",
            shown="no es una copia local",
        )
    if not local.writable:
        raise ProjectError(
            "core.publish_read_only",
            "la copia local no está abierta en escritura: ábrala en escritura para publicarla",
            obj=obj,
            field="modo",
            shown=local.status.message,
        )
    if not isinstance(section.get("base"), str) or not isinstance(section.get("session_uid"), str):
        raise ProjectError(
            "core.publish_section_invalid",
            "a la sección «checkout» de su cabecera le falta la huella de partida o la sesión "
            "de la reserva: no se publica nada",
            obj=obj,
            field="checkout",
            shown="incompleta",
        )
    return section


def _original_of(local: Project, record: Mapping[str, Any] | None) -> Path:
    """La carpeta del original de la copia local (del registro del equipo)."""
    obj = f"Proyecto «{local.name}»"
    text = None if record is None else record.get("original")
    if not isinstance(text, str) or not text:
        raise ProjectError(
            "core.publish_original_unknown",
            "en este equipo no consta de qué original se sacó esta copia local (falta su "
            "registro en los datos de usuario): no se publica nada; publíquela desde el "
            "equipo donde se sacó",
            obj=obj,
            field="original",
            shown="no consta",
        )
    original = Path(text)
    try:
        header = read_manifest(original)
    except ProjectError as exc:
        raise ProjectError(
            "core.publish_original_missing",
            f"no se puede leer el original ({exc.reason}): no se publica nada; compruebe que "
            "su carpeta (en la red) está disponible y vuelva a intentarlo",
            obj=obj,
            field="original",
            value=str(original),
        ) from exc
    if header.project_uid != local.uid:
        raise ProjectError(
            "core.publish_original_other",
            "la carpeta del original es de otro proyecto: no se publica nada",
            obj=obj,
            field="original",
            value=str(original),
        )
    return original


def _reservation_lost(original: Path, obj: str, now: str) -> ProjectError:
    return ProjectError(
        "core.publish_reservation_lost",
        f"el original ya no está reservado para esta copia ({now}): no se publica, porque "
        "sustituiría lo que se haya hecho en él desde entonces. La copia local se conserva "
        "intacta: para no perder su trabajo, cópiela a otra carpeta como un proyecto aparte, "
        "o saque una copia nueva del original y rehaga en ella los cambios",
        obj=obj,
        field="reserva del original",
        value=str(original),
    )


def _check_reservation(
    original: Path,
    section: Mapping[str, Any],
    session: SessionInfo,
    obj: str,
    clock: Clock,
    alive: PidAlive,
    stale_minutes: int,
) -> bytes:
    """Los bytes de la reserva del original si sigue siendo la de esta copia;
    :class:`ProjectError` si no."""
    content, holder = lockmod.read_lock(original, clock=clock)
    if (
        content is not None
        and holder is not None
        and holder.mode is LockMode.CHECKOUT
        and holder.session_uid == section["session_uid"]
    ):
        return content
    status = lockmod.inspect(
        original, session, clock=clock, pid_alive=alive, stale_minutes=stale_minutes
    )
    raise _reservation_lost(original, obj, status.describe())


def _change_list(before: TreePrints | None, after: TreePrints) -> list[str]:
    """Qué cambió en una carpeta, en español (vacío si no se saben las huellas de antes)."""
    if before is None:
        return []
    found: list[str] = []
    old = {item.path: item for item in before.files}
    new = {item.path: item for item in after.files}
    for path in sorted(set(old) | set(new)):
        if path not in new:
            found.append(f"«{path}» ya no está")
        elif path not in old:
            found.append(f"«{path}» es nuevo")
        elif old[path] != new[path]:
            found.append(f"«{path}» ha cambiado")
    found.extend(f"«{name}/» es nueva" for name in sorted(set(after.folders) - set(before.folders)))
    found.extend(
        f"«{name}/» ya no está" for name in sorted(set(before.folders) - set(after.folders))
    )
    return found


def _original_changed(original: Path, obj: str, changes: list[str]) -> ProjectError:
    shown = "; ".join(changes[:5])
    if len(changes) > 5:
        shown += f" y {len(changes) - 5} más"
    listed = f" ({shown})" if shown else ""
    return ProjectError(
        "core.publish_original_changed",
        f"el original ha cambiado desde que se sacó la copia{listed}, por ejemplo al "
        "editarlo con QGIS: no se publica, porque esos cambios se perderían. La copia local "
        "se conserva intacta: abra el original en solo lectura para ver qué cambió y, si "
        "quiere conservar los dos, copie esta copia a otra carpeta como un proyecto aparte",
        obj=obj,
        field="original",
        value=str(original),
        context={"changes": changes},
    )


def _recover_local_wal(database: Path, obj: str) -> list[str]:
    """La base de la copia local en diario clásico antes de copiarla (QGIS pudo editarla
    en WAL); un aviso si lo estaba."""
    if not read_header(database).needs_recovery:
        return []
    recovery = to_classic_journal(database, timeout_s=BUSY_TIMEOUT_MS / 1000)
    if recovery.outcome is WalOutcome.BUSY:
        raise ProjectError(
            "core.publish_local_wal_busy",
            "QGIS u otro programa tiene abierta la base de la copia local en modo WAL: no se "
            "ha publicado nada; cierre ese programa y vuelva a publicar",
            obj=obj,
            field="diario",
            value=str(database),
        )
    if recovery.outcome is not WalOutcome.CONVERTED:
        return []
    return [
        "La base de la copia local estaba en modo WAL (QGIS lo activa al editar un "
        "GeoPackage); se ha devuelto al diario clásico antes de publicarla, sin perder datos."
    ]


def _prepare_staging(
    staging: Path,
    original: Path,
    section: Mapping[str, Any],
    session: SessionInfo,
    clock: Clock,
) -> None:
    """En ``.publicando``: el evento ``publish`` en su base y la cabecera regenerada desde
    ella con ``checkout = null``."""
    now = format_utc(clock.now())
    message = (
        f"Copia local publicada en «{original.name}» por {session.user_host} (la sacó "
        f"{section.get('by')} el {section.get('at')})"
    )
    data = {
        "base": section["base"],
        "checkout_session": section["session_uid"],
        "checkout_at": section.get("at"),
        "checkout_by": section.get("by"),
    }
    with GpkgConnection.open_write(staging / PROJECT_STORE) as db, db.transaction() as conn:
        record_event(conn, EventKind.PUBLISH, message, session=session, at=now, data=data)
        record = read_project(conn)
    if record is None:
        raise ProjectError(
            "core.publish_staging_invalid",
            "a la copia preparada le falta la fila de gb_project: no se publica nada",
            obj="Publicación de la copia local",
            field=PROJECT_STORE,
            value=str(staging),
        )
    header = manifest_from_record(record, previous=read_manifest(staging))
    write_manifest(staging, replace(header, checkout=None), session.session_uid)


def _file_print(path: Path, rel: str) -> FilePrint:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as reader:
        while chunk := reader.read(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return FilePrint(rel, size, digest.hexdigest())


def _restamp(prints: TreePrints, root: Path, names: Collection[str]) -> TreePrints:
    """``prints`` con las huellas de ``names`` vueltas a calcular en ``root`` (lo que se
    cambió después de copiar)."""
    files = tuple(
        _file_print(root / item.path, item.path) if item.path in names else item
        for item in prints.files
    )
    return TreePrints(prints.folders, files)


class _HalfDone(Exception):
    """No se pudo terminar la sustitución ni deshacerla: las dos carpetas, completas."""

    def __init__(self, error: ProjectError) -> None:
        super().__init__(error.message)
        self.error = error


def _put_back(aside: Path | None, previous: Path, clock: Clock) -> None:
    """Devuelve a su nombre la publicación anterior que se apartó (si se puede)."""
    if aside is None:
        return
    try:
        _rename_retrying(aside, previous, clock)
    except OSError:
        pass  # queda apartada, entera: no se pierde nada


def _swap(
    original: Path, staging: Path, seen: bytes, obj: str, clock: Clock
) -> tuple[Path, list[str]]:
    """Sustituye el original por ``staging`` y libera la reserva; devuelve
    ``.anterior`` y los avisos. Si un renombrado falla, lo hecho se deshace y se lanza el
    ``OSError``; si tampoco se puede deshacer, :class:`_HalfDone`."""
    previous = previous_path(original)
    content, _holder = lockmod.read_lock(original, clock=clock)
    if content != seen:
        raise _reservation_lost(original, obj, "ha cambiado mientras se preparaba la publicación")
    aside: Path | None = None
    if previous.exists():
        aside = original.parent / f"{previous.name}{DISCARD_MARK}{new_uid()}"
        _rename_retrying(previous, aside, clock)
    try:
        _rename_retrying(original, previous, clock)
    except OSError:
        _put_back(aside, previous, clock)
        raise
    try:
        _rename_retrying(staging, original, clock)
    except OSError as exc:
        try:
            _rename_retrying(previous, original, clock)
        except OSError as undo:
            raise _HalfDone(
                ProjectError(
                    "core.publish_half_done",
                    f"no se ha podido terminar la publicación ({exc.strerror or exc}) ni "
                    f"deshacerla ({undo.strerror or undo}): el original, completo, está ahora "
                    f"en «{previous.name}» y la copia publicada, completa, en «{staging.name}», "
                    f"junto a donde estaba «{original.name}». Cuando se pueda, renombre "
                    f"«{previous.name}» a «{original.name}» para dejarlo como estaba (o "
                    f"«{staging.name}» para publicar)",
                    obj=obj,
                    field="carpetas",
                    value=str(original.parent),
                )
            ) from undo
        _put_back(aside, previous, clock)
        raise
    warnings: list[str] = []
    try:
        if not lockmod.remove_if_unchanged(previous, seen, clock=clock):
            warnings.append(
                f"La reserva del original anterior («{previous.name}/.lock») ha cambiado y no "
                "se ha borrado; bórrela a mano si sobra."
            )
    except OSError as exc:
        warnings.append(
            f"No se ha podido borrar la reserva de «{previous.name}» ({exc}); bórrela a mano."
        )
    if aside is not None:
        remove_tree(aside, clock)
        if aside.exists():
            warnings.append(
                f"No se ha podido borrar «{aside.name}» (la publicación anterior a la "
                "anterior); bórrela a mano."
            )
    return previous, warnings


def publish_steps(
    local: Project,
    session: SessionInfo,
    userdata: UserData,
    *,
    clock: Clock | None = None,
    pid_alive: PidAlive = pid_alive,
    stale_minutes: int = lockmod.DEFAULT_STALE_MINUTES,
    disk_usage: DiskUsageFn = shutil.disk_usage,
    chunk_size: int = CHUNK_SIZE,
) -> Iterator[Progress]:
    """Publica la copia local ``local`` (abierta en escritura) sobre su original, por pasos
    (:data:`PUBLISH_PHASES`); el último lleva el :class:`PublishResult`.

    :class:`ProjectError` con el motivo y qué hacer si no se puede; entonces el original y
    la copia local quedan como estaban. Cerrar el generador antes de la sustitución cancela
    sin dejar nada.
    """
    clock = local.clock if clock is None else clock
    total = len(PUBLISH_PHASES)
    yield Progress(
        PUBLISH_PHASES[0], 0, total, "Comprobando la copia local y la reserva del original…"
    )
    section = _local_section(local)
    obj = f"Proyecto «{local.name}»"
    record = userdata.checkout_record(local.uid)
    original = _original_of(local, record)
    seen = _check_reservation(original, section, session, obj, clock, pid_alive, stale_minutes)
    yield Progress(PUBLISH_PHASES[1], 0, 0, "Comprobando que el original no ha cambiado…")
    current: TreePrints | None = None
    for step in fingerprint_steps(
        original, exclude=CHECKOUT_EXCLUDE, clock=clock, chunk_size=chunk_size
    ):
        if isinstance(step.result, TreePrints):
            current = step.result
        yield Progress(PUBLISH_PHASES[1], step.done, step.total, step.message)
    if current is None:
        raise TypeError("las huellas del original no han terminado con su resultado")
    if tree_digest(current) != section["base"]:
        before = TreePrints.from_dict(None if record is None else record.get("prints"))
        raise _original_changed(original, obj, _change_list(before, current))
    staging = publishing_path(original)
    database = local.database_path
    warnings = _recover_local_wal(database, obj)
    counter = read_header(database).change_counter
    finished = staged = keep = False
    try:
        copied: CopyResult | None = None
        for step in copy_steps(
            local.root, staging, exclude=CHECKOUT_EXCLUDE, clock=clock, disk_usage=disk_usage,
            chunk_size=chunk_size,
        ):
            if isinstance(step.result, CopyResult):
                copied, staged = step.result, True
            yield Progress(PUBLISH_PHASES[2], step.done, step.total, step.message)
        if copied is None:
            raise TypeError("la copia no ha terminado con su resultado")
        if _changed(database, counter):
            raise ProjectError(
                "core.publish_local_changed",
                "otro programa (QGIS, por ejemplo) ha escrito en la copia local mientras se "
                "publicaba: no se ha publicado nada; cierre ese programa y vuelva a publicar",
                obj=obj,
                field=PROJECT_STORE,
                value=str(database),
            )
        yield Progress(PUBLISH_PHASES[3], 3, total, "Preparando la publicación…")
        _prepare_staging(staging, original, section, session, clock)
        prints = _restamp(copied.prints, staging, (PROJECT_STORE, MANIFEST_FILE))
        yield Progress(PUBLISH_PHASES[4], 4, total, "Sustituyendo el original…")
        try:
            previous, swapped = _swap(original, staging, seen, obj, clock)
        except _HalfDone as half:
            keep = True
            raise half.error from half
        except OSError as exc:
            raise ProjectError(
                "core.publish_failed",
                f"no se ha podido sustituir el original ({exc.strerror or exc}): no se ha "
                "publicado nada y el original sigue como estaba; vuelva a intentarlo",
                obj=obj,
                field="original",
                value=str(original),
            ) from exc
        finished = True
    finally:
        if not finished and staged and not keep:
            remove_tree(staging, clock)
    warnings.extend(swapped)
    userdata.clear_checkout_record(local.uid)
    warnings.extend(local.close())
    try:
        userdata.add_recent(local.uid, local.name, original, format_utc(clock.now()))
    except (OSError, GeoblenderError):
        pass  # la lista de recientes es una comodidad del equipo
    yield Progress(
        PUBLISH_PHASES[4], total, total, "Copia local publicada",
        result=PublishResult(original, previous, local.root, prints, tuple(warnings)),
    )
