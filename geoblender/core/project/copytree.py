# SPDX-License-Identifier: GPL-3.0-or-later
"""Copia de un proyecto por pasos con huellas (spec 002; RF-002-20, RF-002-31, RF-002-32,
RNF-002-06; plan 002 §5.4, «Copia con huellas»).

La copia previa a una migración, la copia local de trabajo y la publicación copian
carpetas enteras, que pueden ser de decenas de GB: son generadores de pasos
(:class:`~.model.Progress`, en bytes hechos de un total) que un operador modal avanza con
progreso; cerrar el generador (``close()``) cancela.

:func:`copy_steps`, en este orden:

1. **Recorrido ordenado** del original (rutas relativas con «/», carpetas vacías
   incluidas), sin lo excluido (``cache``, ``.lock``…). Un enlace simbólico o una unión de
   carpetas se rechaza: un proyecto no los tiene, y seguirlos copiaría lo que no es suyo.
2. **Longitud de las rutas** y **espacio libre** en la carpeta de destino, antes de crear
   nada: ninguna ruta de la copia (en la carpeta temporal) pasa del límite de rutas de
   Windows, que Blender 5.2.1 no admite (``core.path_too_long``, T45); y hay espacio
   (``shutil.disk_usage``, inyectable) para el total más un margen del 10 %.
3. **Copia** en una carpeta temporal junto al destino (``<destino>.copiando-<8 cifras
   hexadecimales>``), por
   trozos de 8 MiB: cada trozo es un paso (progreso cada ≤ 1 s y cancelación en ≤ 2 s
   también en red) y su sha256 se calcula a la vez que se escribe. Cada fichero se
   escribe con ``fsync`` cada :data:`SYNC_BYTES` y al final (así el último no deja un
   paso largo sin progreso) y conserva su fecha de modificación. Un fichero que retiene otro
   programa (antivirus, indexador) se reintenta :data:`RETRIES` veces cada
   :data:`RETRY_WAIT_S` s.
4. **Comprobación**: se vuelve a leer la copia y sus huellas tienen que ser las del
   original; si no, error con los ficheros que difieren.
5. Se **renombra** la temporal al destino: nunca queda una copia a medias con el nombre
   definitivo. Cancelar o fallar en cualquier paso borra la temporal. Después se vuelve a
   listar con su nombre (:func:`refresh_listing`): en la red, si no, no se podría sustituir
   después un fichero de dentro.

:func:`fingerprint_steps` / :func:`fingerprint` dan las huellas de una carpeta,
:func:`compare_prints` dice qué falta, qué sobra y qué cambió entre dos y
:func:`tree_digest` las resume en una sola huella (la de partida de una copia local).
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable, Collection, Generator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Literal, Protocol, TypeVar

from ..errors import ProjectError
from ..ids import SHORT_UID_CHARS, short_uid
from ..paths import check_path_length
from ..timeutil import SYSTEM_CLOCK, Clock
from .model import Progress

CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB por paso
# Cada cuánto se fuerza a disco lo escrito de un fichero (fsync). Con un solo fsync al
# final, el de un fichero de 192 MiB tardó 1,0–1,8 s en el PC de referencia tras escribir
# varios GiB (spec 002, T36): un paso sin progreso de más de 1 s (RNF-002-06).
SYNC_BYTES = 32 * 1024 * 1024
SPACE_MARGIN = 0.10  # margen de espacio libre sobre el tamaño de la copia
RETRIES = 3  # reintentos de un fichero retenido por otro programa
RETRY_WAIT_S = 0.5
COPYING_MARK = ".copiando-"
PHASES: tuple[str, ...] = ("espacio", "copia", "comprobación")
FINGERPRINT_PHASE = "huellas"
_OBJ = "Copia del proyecto"

_T = TypeVar("_T")


class DiskUsage(Protocol):
    """Lo que devuelve ``shutil.disk_usage`` (solo se usa ``free``)."""

    free: int


DiskUsageFn = Callable[[Path], DiskUsage]


@dataclass(frozen=True)
class FilePrint:
    """La huella de un fichero: ruta relativa con «/», tamaño en bytes y sha256."""

    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class TreePrints:
    """Las huellas de una carpeta: sus subcarpetas y sus ficheros, en orden."""

    folders: tuple[str, ...]
    files: tuple[FilePrint, ...]

    @property
    def total_bytes(self) -> int:
        """Suma de los tamaños de los ficheros."""
        return sum(item.size for item in self.files)

    def file(self, path: str) -> FilePrint | None:
        """La huella del fichero ``path`` (relativa, con «/»), o ``None``."""
        for item in self.files:
            if item.path == path:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        """Las huellas en JSON: ``{"folders": [...], "files": [[ruta, tamaño, sha256]…]}``."""
        return {
            "folders": list(self.folders),
            "files": [[item.path, item.size, item.sha256] for item in self.files],
        }

    @classmethod
    def from_dict(cls, data: object) -> TreePrints | None:
        """Las huellas de :meth:`to_dict`, o ``None`` si ``data`` no tiene esa forma."""
        if not isinstance(data, dict):
            return None
        folders, files = data.get("folders"), data.get("files")
        if not isinstance(folders, list) or not isinstance(files, list):
            return None
        if not all(isinstance(item, str) for item in folders):
            return None
        found: list[FilePrint] = []
        for item in files:
            if (
                not isinstance(item, list)
                or len(item) != 3
                or not isinstance(item[0], str)
                or not isinstance(item[1], int)
                or not isinstance(item[2], str)
            ):
                return None
            found.append(FilePrint(item[0], item[1], item[2]))
        return cls(tuple(folders), tuple(found))


def tree_digest(prints: TreePrints) -> str:
    """Una sola huella (sha256) de las huellas de una carpeta: cambia si cambia, falta o
    sobra cualquier fichero o subcarpeta (la copia local la guarda como huella de partida
    del original)."""
    digest = hashlib.sha256()
    for folder in prints.folders:
        digest.update(f"d\t{folder}\n".encode())
    for item in prints.files:
        digest.update(f"f\t{item.path}\t{item.size}\t{item.sha256}\n".encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class PrintDifference:
    """Algo en lo que dos huellas no coinciden: falta, sobra o cambió."""

    path: str
    kind: Literal["missing", "extra", "changed"]

    def describe(self) -> str:
        """La diferencia en español."""
        what = {
            "missing": "falta en la copia",
            "extra": "sobra en la copia",
            "changed": "no tiene el mismo contenido (sha256 distinto)",
        }[self.kind]
        return f"«{self.path}» {what}"


@dataclass(frozen=True)
class CopyResult:
    """Una copia terminada y comprobada: de dónde, a dónde y sus huellas."""

    source: Path
    dest: Path
    prints: TreePrints


# Errores ---------------------------------------------------------------------------------


def _size_text(size: int) -> str:
    """Un tamaño como lo lee una persona (unidades decimales, coma decimal)."""
    for unit, factor in (("GB", 10**9), ("MB", 10**6), ("kB", 10**3)):
        if size >= factor:
            return f"{size / factor:.1f} {unit}".replace(".", ",")
    return f"{size} B"


def _failed(where: Path, exc: BaseException) -> ProjectError:
    """El error de una copia que falló, con el fichero que la hizo fallar si se sabe."""
    reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
    filename = getattr(exc, "filename", None)
    if filename:
        where = Path(os.fsdecode(filename))
    return ProjectError(
        "core.copy_failed",
        f"no se ha podido copiar ({reason}); no queda ninguna copia a medias: compruebe que "
        "ningún programa lo tiene abierto, el espacio y los permisos, y vuelva a intentarlo",
        obj=_OBJ,
        field="fichero",
        value=str(where),
    )


# Recorrido ----------------------------------------------------------------------------


def _is_link(entry: os.DirEntry[str]) -> bool:
    junction = getattr(entry, "is_junction", None)
    return entry.is_symlink() or (junction is not None and bool(junction()))


def _listing(root: Path, exclude: Collection[str]) -> tuple[list[str], list[tuple[str, int]]]:
    """Las subcarpetas y los ficheros (con su tamaño) de ``root``, rutas relativas con
    «/» en orden, sin lo excluido (rutas relativas, sin distinguir mayúsculas)."""
    if not root.is_dir():
        raise ProjectError(
            "core.copy_source_missing",
            "no existe o no es una carpeta: no hay nada que copiar",
            obj=_OBJ,
            field="original",
            value=str(root),
        )
    excluded = {item.replace("\\", "/").strip("/").casefold() for item in exclude}
    folders: list[str] = []
    files: list[tuple[str, int]] = []
    pending = [""]
    while pending:
        current = pending.pop()
        with os.scandir(root / current if current else root) as found:
            entries = sorted(found, key=lambda entry: entry.name)
        for entry in entries:
            rel = f"{current}/{entry.name}" if current else entry.name
            if rel.casefold() in excluded:
                continue
            if _is_link(entry):
                raise ProjectError(
                    "core.copy_link",
                    "es un enlace o una unión de carpetas, y un proyecto no los tiene: no se "
                    "copia nada; quítelo del proyecto y vuelva a intentarlo",
                    obj=_OBJ,
                    field="enlace",
                    value=rel,
                )
            if entry.is_dir(follow_symlinks=False):
                folders.append(rel)
                pending.append(rel)
            else:
                files.append((rel, entry.stat(follow_symlinks=False).st_size))
    folders.sort()
    files.sort()
    return folders, files


# Lectura con reintentos ------------------------------------------------------------------


def _open_source(path: Path) -> IO[bytes]:
    """Abre un fichero del original para leerlo (las pruebas lo sustituyen)."""
    return Path(path).open("rb")


def _retrying(action: Callable[[], _T], clock: Clock) -> _T:
    """``action()``, reintentada :data:`RETRIES` veces cada :data:`RETRY_WAIT_S` s si otro
    programa retiene el fichero (``PermissionError``: acceso denegado o compartido)."""
    for attempt in range(RETRIES + 1):
        try:
            return action()
        except PermissionError:
            if attempt == RETRIES:
                raise
            clock.sleep(RETRY_WAIT_S)
    raise AssertionError("inalcanzable")  # pragma: no cover


def refresh_listing(folder: Path) -> None:
    """Vuelve a listar ``folder`` y sus subcarpetas (solo nombres y datos de directorio, sin
    leer ficheros) tras renombrarla. En una carpeta de red (SMB) que se listó con su nombre
    anterior, Windows no deja después sustituir un fichero de dentro (``os.replace``: «el
    proceso no tiene acceso al archivo porque está siendo utilizado por otro proceso») hasta
    que se lista con el nombre nuevo (docs/trampas.md §6). Si no se puede listar, no hace
    nada: es una ayuda, no una comprobación."""
    pending = [Path(folder)]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as found:
                for entry in found:
                    entry.stat(follow_symlinks=False)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
        except OSError:
            continue


def remove_tree(path: Path, clock: Clock = SYSTEM_CLOCK) -> None:
    """Borra una carpeta que ha creado esta copia (la temporal, o una copia que se
    descarta), con reintentos si otro programa retiene algo de ella."""
    for attempt in range(RETRIES + 1):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists() or attempt == RETRIES:
            return
        clock.sleep(RETRY_WAIT_S)


# Huellas ---------------------------------------------------------------------------------


def _hash_file(
    path: Path,
    rel: str,
    done: int,
    total: int,
    phase: str,
    chunk_size: int,
    clock: Clock,
) -> Generator[Progress, None, FilePrint]:
    digest = hashlib.sha256()
    size = 0
    with _retrying(lambda: _open_source(path), clock) as reader:
        while chunk := reader.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
            yield Progress(phase, done + size, total, f"Comprobando «{rel}»…")
    return FilePrint(rel, size, digest.hexdigest())


def _hash_tree(
    root: Path,
    folders: list[str],
    files: list[tuple[str, int]],
    total: int,
    phase: str,
    chunk_size: int,
    clock: Clock,
) -> Generator[Progress, None, TreePrints]:
    prints: list[FilePrint] = []
    done = 0
    for rel, _size in files:
        item = yield from _hash_file(root / rel, rel, done, total, phase, chunk_size, clock)
        prints.append(item)
        done += item.size
    return TreePrints(tuple(folders), tuple(prints))


def fingerprint_steps(
    root: Path,
    *,
    exclude: Collection[str] = (),
    clock: Clock = SYSTEM_CLOCK,
    chunk_size: int = CHUNK_SIZE,
) -> Iterator[Progress]:
    """Las huellas de ``root`` por pasos (un trozo por paso); el último lleva el
    :class:`TreePrints` en ``result``. No escribe nada."""
    root = Path(root)
    try:
        folders, files = _listing(root, exclude)
        total = sum(size for _rel, size in files)
        yield Progress(FINGERPRINT_PHASE, 0, total, "Calculando las huellas…")
        prints = yield from _hash_tree(
            root, folders, files, total, FINGERPRINT_PHASE, chunk_size, clock
        )
    except OSError as exc:
        raise _failed(root, exc) from exc
    yield Progress(
        FINGERPRINT_PHASE, prints.total_bytes, prints.total_bytes, "Huellas calculadas",
        result=prints,
    )


def fingerprint(
    root: Path, *, exclude: Collection[str] = (), clock: Clock = SYSTEM_CLOCK
) -> TreePrints:
    """Las huellas de ``root`` de una vez (el mismo recorrido sin pausas)."""
    return _last_result(fingerprint_steps(root, exclude=exclude, clock=clock), TreePrints)


def compare_prints(expected: TreePrints, actual: TreePrints) -> tuple[PrintDifference, ...]:
    """Lo que falta, sobra o cambió en ``actual`` respecto de ``expected`` (vacío si son
    iguales), en orden de ruta."""
    found: list[PrintDifference] = []
    wanted = {item.path: item for item in expected.files}
    present = {item.path: item for item in actual.files}
    for path in sorted(set(wanted) | set(present) | set(expected.folders) | set(actual.folders)):
        if path in wanted and path in present:
            if wanted[path] != present[path]:
                found.append(PrintDifference(path, "changed"))
        elif path in wanted or (path in expected.folders and path not in actual.folders):
            found.append(PrintDifference(path, "missing"))
        elif path in present or (path in actual.folders and path not in expected.folders):
            found.append(PrintDifference(path, "extra"))
    return tuple(found)


def _last_result(steps: Iterator[Progress], kind: type[_T]) -> _T:
    result: Any = None
    for step in steps:
        if step.result is not None:
            result = step.result
    if not isinstance(result, kind):
        raise TypeError("la operación por pasos no ha terminado con su resultado")
    return result


# Copia -----------------------------------------------------------------------------------


def _check_destination(dest: Path) -> None:
    if not dest.parent.is_dir():
        raise ProjectError(
            "core.copy_parent_missing",
            "no existe la carpeta donde se iba a copiar: elija una carpeta existente",
            obj=_OBJ,
            field="carpeta de destino",
            value=str(dest.parent),
        )
    if dest.exists():
        raise ProjectError(
            "core.copy_dest_exists",
            "ya existe: no se sobrescribe nada; elija otro destino o quite el que hay",
            obj=_OBJ,
            field="destino",
            value=str(dest),
        )


TEMPORARY_ATTEMPTS = 3  # nombres temporales distintos que se prueban si ya existe uno


def _temporary_path(dest: Path, tag: str) -> Path:
    """``<destino>.copiando-<8 cifras hexadecimales>`` junto al destino (T45)."""
    return dest.parent / f"{dest.name}{COPYING_MARK}{tag}"


def _make_temporary(dest: Path) -> Path:
    for attempt in range(TEMPORARY_ATTEMPTS):
        temporary = _temporary_path(dest, short_uid())
        try:
            temporary.mkdir()
        except FileExistsError:
            if attempt == TEMPORARY_ATTEMPTS - 1:
                raise
            continue
        return temporary
    raise AssertionError("inalcanzable")  # pragma: no cover


def _check_lengths(temporary: Path, folders: list[str], files: list[tuple[str, int]]) -> None:
    """Sin tocar el disco, :class:`ProjectError` si la ruta más larga de la copia (un
    fichero o una carpeta, en la carpeta temporal, más larga que el destino) pasaría del
    límite de rutas de Windows (RF-002-02; T45)."""
    if files:
        longest = max((rel for rel, _size in files), key=len)
        check_path_length(temporary / longest, obj=_OBJ)
    deepest = max(folders, key=len) if folders else ""
    check_path_length(temporary / deepest if deepest else temporary, folder=True, obj=_OBJ)


def _check_space(dest: Path, total: int, disk_usage: DiskUsageFn) -> None:
    needed = total + -(-total * round(SPACE_MARGIN * 100) // 100)
    free = int(disk_usage(dest.parent).free)
    if free < needed:
        raise ProjectError(
            "core.copy_no_space",
            f"no hay espacio libre suficiente: hacen falta {_size_text(needed)} (la copia, "
            f"{_size_text(total)}, más un margen del 10 %) y hay {_size_text(free)}; libere "
            "espacio o elija otra carpeta. No se ha copiado nada",
            obj=_OBJ,
            field="carpeta de destino",
            value=str(dest.parent),
        )


def _copy_file(
    source: Path,
    target: Path,
    rel: str,
    done: int,
    total: int,
    chunk_size: int,
    clock: Clock,
) -> Generator[Progress, None, FilePrint]:
    digest = hashlib.sha256()
    size = 0
    unsynced = 0
    with _retrying(lambda: _open_source(source), clock) as reader, target.open("xb") as writer:
        while chunk := reader.read(chunk_size):
            writer.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            unsynced += len(chunk)
            if unsynced >= SYNC_BYTES:  # el fsync final de un fichero grande no para
                writer.flush()  # el progreso más de 1 s (RNF-002-06)
                os.fsync(writer.fileno())
                unsynced = 0
            yield Progress("copia", done + size, total, f"Copiando «{rel}»…")
        writer.flush()
        os.fsync(writer.fileno())
    stat = source.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    return FilePrint(rel, size, digest.hexdigest())


def _mismatch(dest: Path, found: tuple[PrintDifference, ...]) -> ProjectError:
    shown = "; ".join(item.describe() for item in found[:5])
    more = f" y {len(found) - 5} más" if len(found) > 5 else ""
    return ProjectError(
        "core.copy_mismatch",
        f"la copia no es idéntica al original ({shown}{more}): se ha descartado y no queda "
        "nada a medias; compruebe el disco o la red y vuelva a intentarlo",
        obj=_OBJ,
        field="destino",
        value=str(dest),
        context={"differences": [item.describe() for item in found]},
    )


def copy_steps(
    source: Path,
    dest: Path,
    *,
    exclude: Collection[str] = (),
    clock: Clock = SYSTEM_CLOCK,
    disk_usage: DiskUsageFn = shutil.disk_usage,
    chunk_size: int = CHUNK_SIZE,
) -> Iterator[Progress]:
    """Copia la carpeta ``source`` en ``dest`` (que no debe existir) por pasos
    (:data:`PHASES`); el último lleva el :class:`CopyResult` en ``result``.

    ``exclude``: rutas relativas que no se copian (``"cache"``, ``".lock"``).
    :class:`ProjectError` si el original no existe o tiene enlaces, el destino ya existe o
    su carpeta no, no hay espacio, falla la copia o la copia no es idéntica; en todos los
    casos, y al cancelar, no queda nada a medias.
    """
    source, dest = Path(source), Path(dest)
    try:
        folders, files = _listing(source, exclude)
    except OSError as exc:
        raise _failed(source, exc) from exc
    total = sum(size for _rel, size in files)
    _check_destination(dest)
    _check_lengths(_temporary_path(dest, "0" * SHORT_UID_CHARS), folders, files)
    yield Progress(PHASES[0], 0, total, "Comprobando el espacio libre…")
    _check_space(dest, total, disk_usage)
    temporary: Path | None = None
    finished = False
    try:
        try:
            temporary = _make_temporary(dest)
            for folder in folders:
                (temporary / folder).mkdir(parents=True, exist_ok=True)
            prints: list[FilePrint] = []
            done = 0
            for rel, _size in files:
                item = yield from _copy_file(
                    source / rel, temporary / rel, rel, done, total, chunk_size, clock
                )
                prints.append(item)
                done += item.size
            expected = TreePrints(tuple(folders), tuple(prints))
            yield Progress(PHASES[2], 0, expected.total_bytes, "Comprobando la copia…")
            copied_folders, copied_files = _listing(temporary, ())
            actual = yield from _hash_tree(
                temporary, copied_folders, copied_files, expected.total_bytes, PHASES[2],
                chunk_size, clock,
            )
        except OSError as exc:
            raise _failed(source, exc) from exc
        found = compare_prints(expected, actual)
        if found:
            raise _mismatch(dest, found)
        try:
            _retrying(lambda: temporary.rename(dest), clock)
        except OSError as exc:
            raise _failed(dest, exc) from exc
        finished = True
        refresh_listing(dest)  # en la red, para poder sustituir después su cabecera
    finally:
        if not finished and temporary is not None:
            remove_tree(temporary, clock)
    total_done = expected.total_bytes
    yield Progress(
        PHASES[2], total_done, total_done, "Copia comprobada",
        result=CopyResult(source, dest, expected),
    )


def copy_tree(
    source: Path,
    dest: Path,
    *,
    exclude: Collection[str] = (),
    clock: Clock = SYSTEM_CLOCK,
    disk_usage: DiskUsageFn = shutil.disk_usage,
    chunk_size: int = CHUNK_SIZE,
) -> CopyResult:
    """Copia ``source`` en ``dest`` de una vez (el mismo recorrido que
    :func:`copy_steps`, sin pausas)."""
    return _last_result(
        copy_steps(
            source, dest, exclude=exclude, clock=clock, disk_usage=disk_usage,
            chunk_size=chunk_size,
        ),
        CopyResult,
    )
