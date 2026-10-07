# SPDX-License-Identifier: GPL-3.0-or-later
"""Limpieza de las carpetas de los trabajos (spec 004; RF-004-16, RF-004-17; plan 004
§5.3.1 y §5.4.6).

- :func:`release` (``JobRunner.mark_ingested``, RF-004-16): el módulo dueño ya incorporó los
  resultados de un trabajo terminado; se borran sus entradas y sus resultados (``in/``,
  ``out/`` y todo lo que no es del registro, como el centinela ``cancel``) y quedan solo los
  ficheros del registro (:data:`REGISTRY_FILES`: ``request.json``, ``events.jsonl``,
  ``job.log``, ``result.json`` y ``state.json``).
- :func:`purge` (al abrir un proyecto y con «Limpiar trabajos terminados», RF-004-17): borra
  la carpeta entera de los trabajos en estado final que terminaron hace más de
  ``older_than_days`` días (o de todos los terminados; o solo de los de ``only``, el
  «Descartar» de la lista de trabajos) y dice cuántos MB liberó. Nunca toca un trabajo
  activo: ni los que su ``state.json`` deja «En cola» o «En curso», ni los que el lanzador
  dice que lleva (``active``), ni una carpeta sin un ``state.json`` válido. Con el
  lanzador, ``JobRunner.purge``, que sabe cuáles lleva.
- :func:`folder_size_mb`: lo que ocupa una carpeta (la raíz de trabajos, en el panel).

Las entradas de ``in/`` son de solo lectura (``paths``): se les quita el atributo antes de
borrarlas. Si otro programa tiene abierto un fichero, se reintenta
(:data:`REMOVE_RETRIES` veces); si sigue abierto, la carpeta queda con su ``state.json``
(lo último que se borra) para la limpieza siguiente y consta en ``CleanupReport.failed``.
Los MB son de 10⁶ bytes y cuentan solo lo que de verdad se borró. Nunca sigue un enlace ni
una unión de carpetas fuera de la carpeta del trabajo.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import shutil
import stat
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from ..core.timeutil import parse_utc
from .paths import BYTES_PER_MB, EVENTS_FILE, LOG_FILE, REQUEST_FILE, RESULT_FILE
from .protocol import JobFolder, folder_path
from .records import LOGGER, RECORD_FILE, as_uid_set, read_record, scan

REGISTRY_FILES: tuple[str, ...] = (REQUEST_FILE, EVENTS_FILE, LOG_FILE, RESULT_FILE,
                                   RECORD_FILE)
"""Lo que queda en la carpeta de un trabajo incorporado: su registro (RF-004-15)."""
REMOVE_RETRIES = 3
"""Reintentos al borrar algo que otro programa tiene abierto (plan §5.4.6)."""
REMOVE_PAUSE_S = 0.05
"""Pausa entre reintentos."""


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """Lo que hizo :func:`purge`: los trabajos cuya carpeta se borró, por orden, los MB
    liberados y los que no se pudieron borrar del todo (un fichero abierto por otro
    programa); estos se intentan otra vez en la limpieza siguiente."""

    removed: tuple[str, ...] = ()
    freed_mb: float = 0.0
    failed: tuple[str, ...] = ()


def release(job_dir: JobFolder) -> float:
    """Borra las entradas y los resultados de un trabajo terminado (RF-004-16): todo lo de
    su carpeta salvo :data:`REGISTRY_FILES`, que no cambian. Devuelve los MB liberados (0
    si ya no quedaba nada). :class:`ValueError` sin borrar nada si la carpeta no tiene un
    ``state.json`` válido o el trabajo sigue en cola o en curso. Lo que otro programa
    retiene tras los reintentos se queda (con un aviso en el registro de Python) y no
    cuenta como liberado."""
    folder = folder_path(job_dir)
    record = read_record(folder)
    if record is None:
        raise ValueError(f"la carpeta {folder.name} no tiene el registro de un trabajo "
                         f"({RECORD_FILE}): no se borra nada")
    if not record.is_final:
        raise ValueError(f"el trabajo {record.job_uid} sigue «{record.state}»: sus entradas y "
                         "resultados no se borran hasta que termine")
    freed, failed = _clear(folder, keep=REGISTRY_FILES)
    if failed:
        LOGGER.warning("No se pudo borrar %s del trabajo %s: otro programa lo tiene abierto",
                       ", ".join(failed), record.job_uid)
    return freed / BYTES_PER_MB


def purge(
    jobs_root: Path,
    *,
    older_than_days: float | None,
    all_finished: bool = False,
    active: Iterable[str],
    only: Iterable[str] | None = None,
    now: dt.datetime | None = None,
) -> CleanupReport:
    """Borra las carpetas de los trabajos terminados de ``jobs_root`` (RF-004-17).

    - ``older_than_days``: los que terminaron (``ended_at``) hace más de ese número de días
      antes de ``now`` (la hora actual si falta; con zona). Un número ≥ 0; ``None`` solo
      con ``all_finished``.
    - ``all_finished``: todos los terminados, sin mirar la fecha.
    - ``active``: los identificadores de los trabajos que lleva el lanzador; nunca se
      borran, como tampoco los que su ``state.json`` deja en cola o en curso ni las
      carpetas sin un ``state.json`` válido.
    - ``only``: si se da, solo esos trabajos (además de lo anterior): el «Descartar» de un
      trabajo de la lista (RF-004-08).

    Devuelve un :class:`CleanupReport` con los borrados y los MB liberados. Un argumento que
    no vale es :class:`ValueError` o :class:`TypeError` antes de borrar nada."""
    if older_than_days is None:
        if not all_finished:
            raise ValueError("falta la antigüedad (older_than_days) o all_finished: no se "
                             "sabe qué trabajos terminados borrar")
    elif (isinstance(older_than_days, bool) or not isinstance(older_than_days, int | float)
          or not math.isfinite(older_than_days) or older_than_days < 0):
        raise ValueError(f"older_than_days {older_than_days!r} no es un número de días ≥ 0")
    keep = as_uid_set(active, "active")
    chosen = None if only is None else as_uid_set(only, "only")
    moment = dt.datetime.now(dt.UTC) if now is None else now
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"la hora {moment!r} no tiene zona: las fechas del registro son UTC")
    cutoff: dt.datetime | None = None
    if not all_finished:
        assert older_than_days is not None
        try:
            cutoff = moment - dt.timedelta(days=older_than_days)
        except OverflowError:
            cutoff = dt.datetime.min.replace(tzinfo=dt.UTC)
    root = Path(jobs_root)
    removed: list[str] = []
    failed: list[str] = []
    freed = 0
    for record in scan(root):
        if not record.is_final or record.job_uid in keep:
            continue
        if chosen is not None and record.job_uid not in chosen:
            continue
        if cutoff is not None and (
            record.ended_at is None or not parse_utc(record.ended_at) < cutoff
        ):
            continue
        size, done = _remove_job_folder(root / record.job_uid)
        freed += size
        (removed if done else failed).append(record.job_uid)
    if failed:
        LOGGER.warning("No se pudieron borrar del todo las carpetas de los trabajos %s: otro "
                       "programa tiene abierto algún fichero; se intentará en la limpieza "
                       "siguiente", ", ".join(failed))
    if removed:
        LOGGER.info("Limpieza de trabajos: %d carpetas borradas, %.1f MB liberados",
                    len(removed), freed / BYTES_PER_MB)
    return CleanupReport(tuple(removed), freed / BYTES_PER_MB, tuple(failed))


def folder_size_mb(path: Path) -> float:
    """Los MB (10⁶ bytes) que ocupan los ficheros bajo ``path`` (o el propio fichero), sin
    seguir enlaces; 0 si no existe."""
    return _size(Path(path)) / BYTES_PER_MB


# --- Ayudas ---------------------------------------------------------------------------------


def _remove_job_folder(folder: Path) -> tuple[int, bool]:
    """Borra la carpeta de un trabajo: primero todo salvo ``state.json`` y, solo si eso se
    pudo, ``state.json`` y la carpeta (así una carpeta a medias se vuelve a ver en la
    limpieza siguiente). Devuelve los bytes liberados y si se borró entera."""
    freed, failed = _clear(folder, keep=(RECORD_FILE,))
    if failed:
        return freed, False
    record = folder / RECORD_FILE
    size = _size(record)
    if not _remove_retrying(record):
        return freed + size - _size(record), False
    freed += size
    if not _remove_retrying(folder):
        return freed, False
    return freed, True


def _clear(folder: Path, *, keep: Iterable[str]) -> tuple[int, list[str]]:
    """Borra lo que hay en ``folder`` salvo los nombres de ``keep``. Devuelve los bytes
    liberados y los nombres que no se pudieron borrar del todo."""
    kept = {name.casefold() for name in keep}
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return 0, []
    freed = 0
    failed: list[str] = []
    for name in names:
        if name.casefold() in kept:
            continue
        path = folder / name
        size = _size(path)
        if _remove_retrying(path):
            freed += size
        else:
            freed += size - _size(path)
            failed.append(name)
    return freed, failed


def _remove_retrying(path: Path) -> bool:
    """Borra ``path`` (:func:`_remove`) y, si falla porque otro programa retiene algo, lo
    reintenta :data:`REMOVE_RETRIES` veces. Dice si acabó bien (lo que ya no existe,
    también)."""
    for attempt in range(REMOVE_RETRIES + 1):
        try:
            _remove(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if attempt == REMOVE_RETRIES:
                return False
            _pause()
    return False  # pragma: no cover


def _pause() -> None:
    time.sleep(REMOVE_PAUSE_S)


def _remove(path: Path) -> None:
    """Borra ``path``: una carpeta con todo lo de dentro (sin seguir enlaces ni uniones),
    un fichero, o el propio enlace; a lo que es de solo lectura se le quita el atributo."""
    if path.is_symlink() or path.is_junction():
        try:
            path.unlink()
        except (IsADirectoryError, PermissionError):
            os.rmdir(path)
        return
    if path.is_dir():
        shutil.rmtree(path, onexc=_writable_and_again)
        return
    try:
        path.unlink()
    except PermissionError:
        _make_writable(path)
        path.unlink()


def _writable_and_again(function: Callable[[str], object], path: str,
                        error: BaseException) -> None:
    """Para ``shutil.rmtree``: si no pudo borrar algo de solo lectura, le quita el atributo y
    lo intenta otra vez; cualquier otro fallo (un fichero abierto) se propaga."""
    if not isinstance(error, PermissionError):
        raise error
    try:
        _make_writable(Path(path))
    except OSError:
        raise error from None
    function(path)


def _make_writable(path: Path) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def _size(path: Path) -> int:
    """Bytes de los ficheros bajo ``path`` (o del propio fichero), sin seguir enlaces ni
    uniones; lo que no se puede leer no cuenta."""
    try:
        info = path.lstat()
    except OSError:
        return 0
    if not stat.S_ISDIR(info.st_mode):
        return info.st_size if stat.S_ISREG(info.st_mode) else 0
    if path.is_junction():
        return 0
    total = 0
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not entry.is_junction():
                                pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total
