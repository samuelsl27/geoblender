# SPDX-License-Identifier: GPL-3.0-or-later
"""Restos de operaciones interrumpidas en las carpetas de datos del proyecto (spec 008;
RF-008-22, RF-008-14, RF-008-58; D-19 de la spec; ADR-0025 §3 y §8; plan 008 §5.2.2, §5.3.1,
§5.4.6 y §5.4.9).

Una operación que se interrumpe (Blender se cierra, cae la red de ``Z:``, otro equipo fuerza el
cerrojo) puede dejar en ``rasters/``, ``meshes/`` u ``originals/`` ficheros que no llegó a
registrar: temporales y salidas a medias. Al abrir el proyecto en escritura,
:func:`orphan_steps` los **aparta** a la carpeta de restos del proyecto (dentro de él, D-19),
``orphans/<AAAAMMDDTHHMMSSZ>_<sesión8>/<carpeta>/<fichero>``, con la ruta que tenían, y avisa
con la lista. **Nunca borra nada** (un destino que ya existe no se sustituye: se numera,
``<nombre>~2.<ext>``) y no hace falta copiar: ``os.rename`` dentro del proyecto, mismo volumen.

**Es un resto** lo que lleva nombre de los módulos y no es de nadie:

- en ``rasters/`` y ``meshes/`` (también en subcarpetas) y en ``originals/``, un fichero con
  nombre de dato (``<código>_<nombre>.<ext>``, con el código de un módulo de
  ``core.catalog.schema.MODULE_CODES``: ``gis_mdt.tif``, ``gis_mdt.tif.tmp``), un temporal de
  otra sesión (``<nombre>.tmp-<sesión>``, como los de ``originals/``) o una salida con huella
  (``<nombre>__<hash8>.<ext>``);
- en ``originals/``, una carpeta ``<uid>`` con forma de uid cuya entrada no está registrada (se
  aparta entera).

**No es un resto** (no se aparta ni se toca): lo que es de un dato registrado
(``gb_dataset.locator`` en cualquier estado, también lo sustituido y lo descartado), un original
guardado (``gb_input_file.original_path``), la fuente de una entrada guardada dentro del
proyecto (``gb_input_file`` con ancla ``project``, RF-008-14; tampoco la carpeta que la
contiene), lo que acompaña a uno de ellos con su nombre y otra extensión (el ``.aux.xml`` que
escribe QGIS junto a un ráster; un temporal, en cambio, sí es un resto), lo que reclama una
operación en curso de esta sesión (``OperationHandle.claim_paths``, y ``claimed``), un temporal
de esta misma sesión, lo escrito o cambiado después de empezar (``started_at``, con
:data:`RECENT_MARGIN_NS` de margen por la resolución de las fechas en red; I-5) y lo que no
lleva nombre de los módulos (lo avisa el aviso de ficheros ajenos, RF-008-62).

Los pasos los avanza el temporizador de ``bl`` (ninguno pasa de ``budget_s``; el trabajo de
cada paso se planea para la mitad): primero el **listado** (``os.scandir``: el tamaño y la fecha
salen del listado, sin un ``stat`` por fichero) contra lo registrado (una lectura); después
**apartar**, volviendo a leer en cada paso lo registrado y lo reclamado y a mirar el tamaño y la
fecha de cada resto justo antes de moverlo: lo que se registró, se reclamó o cambió entre dos
pasos queda para la próxima (``stale``); por último, el **registro**: el evento
``orphans_moved`` (sin rutas absolutas) con ``Project.try_write``, reintentado en el paso
siguiente si otro programa está leyendo, o en la transacción final de quien llama
(``record=False`` y :func:`record_orphans`).

Un resto que otro programa tiene abierto (``PermissionError``: QGIS) se salta sin fallar y queda
en el aviso «se reintentará»; nada se anota: se vuelve a encontrar al abrir la próxima vez. En
**solo lectura** (``write=False`` o el proyecto sin escritura) solo se avisa con la lista: no
se mueve nada, no se crea ``orphans/`` ni se escribe en la base.

Python puro (ADR-0004): al importarse no importa ``core.provenance`` ni ``core.project`` (que
pasan por este paquete), que se cargan al usarse.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import stat
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol

from ..catalog.schema import MODULE_CODES
from ..ids import SHORT_UID_CHARS
from ..paths import MAX_FILE_PATH_CHARS, MAX_FOLDER_PATH_CHARS
from ..timeutil import format_utc
from .external import _budget, _Pacer, _reason
from .model import FILE_STORES, Store

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo
    from ..timeutil import Clock

DATA_FOLDERS: tuple[str, ...] = (Store.RASTERS.value, Store.MESHES.value, Store.ORIGINALS.value)
"""Las carpetas de datos del proyecto en las que se buscan restos (plan 008 §5.4.9)."""
ORPHANS_DIR = "orphans"
"""La carpeta de restos en la raíz del proyecto (ADR-0025 §8; D-19)."""
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
"""La fecha (UTC) del nombre de la carpeta de una pasada: ``<fecha>_<sesión8>``."""
STEP_BUDGET_S = 0.020
"""Lo que puede durar un paso (plan 008 §2: ≤ 20 ms por tic)."""
RECENT_MARGIN_NS = 2 * 10**9
"""Lo escrito hasta 2 s antes de empezar también cuenta como posterior: la fecha de un fichero
en una unidad de red (o en FAT) puede ir redondeada."""
MAX_LISTED = 20
"""Cuántos restos nombra cada aviso; de los demás dice cuántos son."""
PHASES: tuple[str, ...] = ("listado", "apartar", "registro")
"""Las fases de los pasos (``core.project.model.Progress``)."""
LOCKED_REASON = "abierto en otro programa"
"""El motivo de un resto que no se pudo apartar porque otro programa lo tiene abierto."""

_MODULE_NAME = re.compile(rf"(?:{'|'.join(MODULE_CODES)})_[a-z0-9_]+(?:\..*)?", re.DOTALL)
_SESSION_TEMPORARY = re.compile(r"\.tmp-([0-9A-Za-z]{1,32})$")
_TEMPORARY = re.compile(r"\.tmp(?:-[0-9A-Za-z]{1,32})?$")
_HASHED = re.compile(r"__[0-9a-f]{8}\.[^.]+$")
_UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

__all__ = [
    "DATA_FOLDERS",
    "LOCKED_REASON",
    "ORPHANS_DIR",
    "PHASES",
    "RECENT_MARGIN_NS",
    "Orphan",
    "OrphanOutcome",
    "OrphanProject",
    "OrphanState",
    "geoblender_name",
    "orphan_steps",
    "record_orphans",
]


class OrphanProject(Protocol):
    """Lo que usa del proyecto (``core.project.Project``) el barrido de restos: su raíz, el
    reloj, la sesión, si se puede escribir, leer y escribir con reintento (y, para las rutas
    reclamadas, lo de ``core.provenance.operations.claimed_paths``)."""

    @property
    def root(self) -> Path: ...

    @property
    def clock(self) -> Clock: ...

    @property
    def session(self) -> SessionInfo: ...

    @property
    def writable(self) -> bool: ...

    def read(self) -> AbstractContextManager[Any]: ...

    def try_write(self, work: Callable[[Any], Any]) -> Any: ...


class OrphanState(StrEnum):
    """Qué pasó con un resto."""

    MOVED = "moved"  # apartado a orphans/
    LOCKED = "locked"  # abierto en otro programa: se reintenta al abrir la próxima vez
    FAILED = "failed"  # no se pudo apartar por otra causa: se reintenta al abrir la próxima vez
    FOUND = "found"  # solo visto (solo lectura): se apartará al abrir en escritura


@dataclass(frozen=True)
class Orphan:
    """Un resto: su ruta relativa a la raíz del proyecto con «/» (``rasters/gis_x.tif``; de una
    carpeta, ``originals/<uid>``), si es una carpeta, qué pasó, adónde se apartó y, si no se
    pudo, por qué."""

    path: str
    folder: bool
    state: OrphanState
    moved_to: str | None = None
    reason: str | None = None

    @property
    def shown(self) -> str:
        """Como se nombra en un aviso: una carpeta, con «/» al final."""
        return f"{self.path}/" if self.folder else self.path


def _render(code: str, *, language: str = "es", **values: Any) -> str:
    from ..provenance.messages import render

    return render(code, language=language, **values)


def _listing(items: Iterable[Orphan], language: str, *, reasons: bool = False) -> str:
    """«a», «b» y n más: los primeros :data:`MAX_LISTED` (con ``reasons``, cada uno con su
    motivo entre paréntesis)."""
    chosen = list(items)
    shown = ", ".join(f"«{item.shown}» ({item.reason})" if reasons else f"«{item.shown}»"
                      for item in chosen[:MAX_LISTED])
    if len(chosen) > MAX_LISTED:
        shown += " " + _render("core.orphans_more", language=language,
                               count=len(chosen) - MAX_LISTED)
    return shown


@dataclass(frozen=True)
class OrphanOutcome:
    """El resultado de :func:`orphan_steps`: los restos encontrados, por su ruta (apartados, que
    no se pudieron apartar o, en solo lectura, solo vistos), la carpeta de la pasada en
    ``orphans/`` (si se apartó algo), si quedó el evento en el proyecto y lo que se vio pero
    cambió, se registró o se reclamó mientras tanto (``stale``: queda para la próxima)."""

    orphans: tuple[Orphan, ...]
    folder: str | None
    recorded: bool
    stale: tuple[str, ...] = ()

    def _of(self, *states: OrphanState) -> tuple[Orphan, ...]:
        return tuple(item for item in self.orphans if item.state in states)

    @property
    def moved(self) -> tuple[Orphan, ...]:
        """Los restos apartados."""
        return self._of(OrphanState.MOVED)

    @property
    def retry(self) -> tuple[Orphan, ...]:
        """Los que no se pudieron apartar (abiertos en otro programa u otra causa): se
        reintentan al abrir la próxima vez."""
        return self._of(OrphanState.LOCKED, OrphanState.FAILED)

    @property
    def found(self) -> tuple[Orphan, ...]:
        """Los que solo se vieron (solo lectura)."""
        return self._of(OrphanState.FOUND)

    def texts(self, language: str = "es") -> tuple[str, ...]:
        """Los avisos en ``language``: lo apartado, lo abierto en otro programa, lo que no se
        pudo apartar y lo visto en solo lectura, cada uno con su lista."""
        found: list[str] = []
        if self.moved:
            found.append(_render("core.orphans_moved", language=language, folder=self.folder,
                                 files=_listing(self.moved, language)))
        locked = self._of(OrphanState.LOCKED)
        if locked:
            found.append(_render("core.orphans_locked", language=language,
                                 files=_listing(locked, language)))
        failed = self._of(OrphanState.FAILED)
        if failed:
            found.append(_render("core.orphans_failed", language=language,
                                 files=_listing(failed, language, reasons=True)))
        if self.found:
            found.append(_render("core.orphans_found", language=language,
                                 files=_listing(self.found, language)))
        return tuple(found)

    @property
    def warnings(self) -> tuple[str, ...]:
        """Los avisos en español."""
        return self.texts("es")


def geoblender_name(name: str) -> bool:
    """Si el nombre de fichero ``name`` es de los que escriben los módulos (véase el módulo):
    ``<código>_<nombre>[.<ext>…]``, ``<nombre>.tmp-<sesión>`` o ``<nombre>__<hash8>.<ext>``."""
    return bool(_MODULE_NAME.fullmatch(name) or _SESSION_TEMPORARY.search(name)
                or _HASHED.search(name))


def orphan_steps(project: OrphanProject, *, write: bool, started_at: int | None = None,
                 claimed: Iterable[str | os.PathLike[str]] = (),
                 budget_s: float = STEP_BUDGET_S, record: bool = True) -> Iterator[Any]:
    """Busca los restos de ``rasters/``, ``meshes/`` y ``originals/`` del proyecto y, con
    ``write`` y el proyecto en escritura, los aparta a ``orphans/`` (RF-008-22; véase el
    módulo), por pasos de ``budget_s`` como mucho. Cada paso es un
    ``core.project.model.Progress``; el último lleva el :class:`OrphanOutcome` en ``result``.

    - ``started_at``: cuándo empezó la comprobación, en ns desde 1970 (``time.time_ns()``, como
      ``st_mtime_ns``; por defecto, ahora): lo escrito después no se aparta;
    - ``claimed``: rutas que no se apartan (absolutas o relativas a la raíz del proyecto),
      además de las que reclaman las operaciones en curso de esta sesión, que se leen en cada
      paso;
    - ``record``: el evento ``orphans_moved`` lo escribe el último paso (con reintento); sin
      él, quien llama lo escribe con :func:`record_orphans` en su transacción.

    Cerrar el generador a medias deja apartado lo ya apartado, sin evento. :class:`TypeError` o
    :class:`ValueError` (al llamarla) con un argumento mal dado."""
    if not isinstance(write, bool):
        raise TypeError(f"«write» es verdadero o falso, no {write!r}")
    if not isinstance(record, bool):
        raise TypeError(f"«record» es verdadero o falso, no {record!r}")
    if started_at is None:
        started_at = time.time_ns()
    elif isinstance(started_at, bool) or not isinstance(started_at, int):
        raise TypeError(f"«started_at» es un instante en ns desde 1970 (time.time_ns()), no "
                        f"{started_at!r}")
    if isinstance(claimed, str | bytes | os.PathLike):
        raise TypeError(f"«claimed» es una lista de rutas, no una ruta: {claimed!r}")
    root = Path(project.root)
    extra = frozenset(key for key in (_claimed_key(root, path) for path in claimed) if key)
    now = project.clock.now().astimezone(dt.UTC)
    folder = f"{ORPHANS_DIR}/{now.strftime(STAMP_FORMAT)}_{_tag(project)}"
    return _steps(project, root, write=write, limit=started_at - RECENT_MARGIN_NS,
                  extra=extra, folder=folder, budget=_budget(budget_s), record=record)


def record_orphans(conn: Any, project: OrphanProject, outcome: OrphanOutcome) -> bool:
    """Escribe el evento ``orphans_moved`` de ``outcome`` en la transacción de escritura
    ``conn`` de quien llama (no la confirma): la carpeta, lo apartado (de dónde y adónde) y lo
    que no se pudo apartar con su motivo, sin rutas absolutas. Si no se apartó nada, no
    escribe y devuelve ``False``."""
    if not outcome.moved:
        return False
    from ..project.events import EventKind, record_event

    record_event(conn, EventKind.ORPHANS_MOVED, outcome.texts("es")[0], session=project.session,
                 at=format_utc(project.clock.now()), data={
                     "folder": outcome.folder,
                     "moved": [[item.path, item.moved_to] for item in outcome.moved],
                     "not_moved": [[item.path, str(item.state), item.reason]
                                   for item in outcome.retry],
                 })
    return True


# --- Lo que no es un resto ------------------------------------------------------------------


def _key(rel: str) -> str:
    """La clave de una ruta relativa a la raíz para compararla (sin distinguir mayúsculas ni
    separadores en Windows)."""
    return os.path.normcase(os.path.normpath(rel))


def _claimed_key(root: Path, path: object) -> str | None:
    raw = os.fspath(path)  # type: ignore[arg-type]
    if not isinstance(raw, str):
        raise TypeError(f"una ruta reclamada es un texto o una ruta, no {path!r}")
    if not os.path.isabs(raw):
        return _key(raw)
    try:
        relative = os.path.relpath(raw, root)
    except ValueError:  # otra unidad
        return None
    outside = relative == os.pardir or relative.startswith(os.pardir + os.sep)
    return None if outside else _key(relative)


def _tag(project: OrphanProject) -> str:
    """Las 8 últimas cifras de la sesión (como en los temporales de ``originals/``)."""
    return (project.session.session_uid.replace("-", "")[-SHORT_UID_CHARS:] or "sesion").lower()


_PROTECTED = (
    f"SELECT locator FROM gb_dataset WHERE store IN "
    f"({', '.join(repr(str(store)) for store in FILE_STORES if str(store) in DATA_FOLDERS)})",
    "SELECT original_path FROM gb_input_file WHERE original_path IS NOT NULL",
    "SELECT path FROM gb_input_file WHERE anchor = 'project'",
)
"""Lo registrado en las carpetas de datos: los datos, los originales guardados y las fuentes
dentro del proyecto."""


@dataclass(frozen=True)
class _Protected:
    """Lo que no se aparta: ficheros (sus claves), las carpetas que los contienen, los nombres
    de cada carpeta (para lo que los acompaña) y los uid de las entradas registradas."""

    files: frozenset[str]
    folders: frozenset[str]
    names: Mapping[str, tuple[str, ...]]
    inputs: frozenset[str]

    def companion(self, key: str) -> bool:
        """Si el fichero ``key`` acompaña a uno de ellos (su nombre y otra extensión)."""
        parent, name = os.path.split(key)
        return any(name.startswith(f"{other}.") for other in self.names.get(parent, ()))

    def holds(self, key: str) -> bool:
        """Si la carpeta ``key`` contiene algo que no se aparta."""
        return key in self.folders


def _protection(project: OrphanProject, root: Path, extra: frozenset[str]) -> _Protected:
    """Una lectura de lo registrado más lo reclamado ahora por esta sesión y ``extra``."""
    from ..provenance.operations import claimed_paths

    with project.read() as conn:
        found = [str(row[0]) for sql in _PROTECTED for row in conn.execute(sql)]
        inputs = frozenset(str(row[0]).lower() for row in conn.execute("SELECT uid FROM gb_input"))
    keys = {_key(rel) for rel in found} | set(extra)
    for path in claimed_paths(project):
        key = _claimed_key(root, path)
        if key:
            keys.add(key)
    folders: set[str] = set()
    names: dict[str, list[str]] = {}
    for key in keys:
        parent, name = os.path.split(key)
        names.setdefault(parent, []).append(name)
        while parent and parent not in folders:
            folders.add(parent)
            parent = os.path.dirname(parent)
    return _Protected(frozenset(keys), frozenset(folders),
                      {parent: tuple(items) for parent, items in names.items()}, inputs)


# --- Listado ---------------------------------------------------------------------------------


@dataclass
class _Candidate:
    """Un resto en el listado: su ruta, su clave, si es una carpeta y lo que se vio (tamaño y
    fecha; de una carpeta, los de cada fichero de dentro)."""

    path: str
    key: str
    folder: bool
    seen: object = None
    result: Orphan | None = None


@dataclass
class _Sweep:
    """Lo que lleva el barrido entre pasos."""

    root: Path
    tag: str
    limit: int
    found: list[_Candidate] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)


def _real_dir(path: Path) -> bool:
    try:
        found = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(found.st_mode) and not path.is_junction()


def _folder_contents(path: Path) -> tuple[tuple[str, int, int], ...] | None:
    """Los ficheros de la carpeta ``path`` (ruta dentro de ella, tamaño y fecha), o ``None`` si
    no se puede leer entera (un enlace dentro tampoco se aparta)."""
    found: list[tuple[str, int, int]] = []
    pending = [("", path)]
    try:
        while pending:
            prefix, folder = pending.pop()
            with os.scandir(folder) as entries:
                for entry in entries:
                    rel = f"{prefix}{entry.name}"
                    if entry.is_symlink() or entry.is_junction():
                        return None
                    if entry.is_dir(follow_symlinks=False):
                        pending.append((f"{rel}/", Path(entry.path)))
                    else:
                        info = entry.stat(follow_symlinks=False)
                        found.append((rel, info.st_size, info.st_mtime_ns))
    except OSError:
        return None
    return tuple(sorted(found))


def _newest(contents: tuple[tuple[str, int, int], ...]) -> int:
    return max((mtime for _rel, _size, mtime in contents), default=0)


def _examine(sweep: _Sweep, protected: _Protected, rel_dir: str, entry: os.DirEntry[str],
             stack: list[str]) -> None:
    """Clasifica una entrada del listado: carpeta a recorrer, resto, o nada."""
    if entry.is_symlink() or entry.is_junction():
        return
    rel = f"{rel_dir}/{entry.name}"
    key = _key(rel)
    if entry.is_dir(follow_symlinks=False):
        uid = entry.name.lower()
        if (rel_dir == Store.ORIGINALS.value and _UID.fullmatch(uid) is not None
                and uid not in protected.inputs and not protected.holds(key)
                and key not in protected.files):
            contents = _folder_contents(Path(entry.path))
            if contents is None:
                return
            if _newest(contents) >= sweep.limit:
                sweep.stale.append(rel)
            else:
                sweep.found.append(_Candidate(rel, key, True, contents))
            return
        stack.append(rel)
        return
    if not entry.is_file(follow_symlinks=False) or key in protected.files:
        return
    temporary = _SESSION_TEMPORARY.search(entry.name)
    if temporary is not None and temporary.group(1).lower() == sweep.tag:
        return  # un temporal de esta misma sesión: lo está escribiendo
    if not geoblender_name(entry.name):
        return  # ajeno: lo avisa la comprobación de ficheros ajenos (RF-008-62)
    if _TEMPORARY.search(entry.name) is None and protected.companion(key):
        return
    info = entry.stat(follow_symlinks=False)
    if info.st_mtime_ns >= sweep.limit:
        sweep.stale.append(rel)
        return
    sweep.found.append(_Candidate(rel, key, False, (info.st_size, info.st_mtime_ns)))


def _list_steps(project: OrphanProject, sweep: _Sweep, protected: _Protected,
                pacer: _Pacer) -> Iterator[Any]:
    """El listado de las carpetas de datos, por pasos (cada carpeta se lee entrada a entrada)."""
    from ..project.model import Progress

    message = "Buscando restos de operaciones interrumpidas…"
    stack = [folder for folder in reversed(DATA_FOLDERS) if _real_dir(sweep.root / folder)]
    examined = 0
    while stack:
        rel_dir = stack.pop()
        try:
            entries = os.scandir(sweep.root.joinpath(*rel_dir.split("/")))
        except OSError:
            continue  # ya no está o no se puede leer: lo que tenga, la próxima vez
        with entries:
            while True:
                try:
                    entry = next(entries)
                except StopIteration:
                    break
                except OSError:  # se cayó la red a mitad: el resto de la carpeta, la próxima vez
                    break
                try:
                    _examine(sweep, protected, rel_dir, entry, stack)
                except OSError:
                    pass  # la entrada desapareció o no se puede leer: no es un resto ahora
                examined += 1
                if pacer.lap():
                    yield Progress(PHASES[0], examined, 0, message)
                    pacer.restart()


# --- Apartar ---------------------------------------------------------------------------------


def _numbered(name: str, number: int) -> str:
    """``<nombre>~<n>.<ext…>``: otro nombre para no sustituir lo que ya está apartado."""
    head, dot, tail = name.partition(".")
    return f"{head}~{number}{dot}{tail}"


def _destination(root: Path, folder: str, item: _Candidate) -> tuple[str, Path]:
    """Dónde se aparta ``item`` (sin sustituir nada): su ruta dentro de la carpeta de la
    pasada."""
    rel = PurePosixPath(folder, item.path)
    number = 1
    while True:
        chosen = rel if number == 1 else rel.with_name(_numbered(rel.name, number))
        target = root.joinpath(*chosen.parts)
        if not os.path.lexists(target):
            return chosen.as_posix(), target
        number += 1


def _too_long(target: Path, item: _Candidate) -> str | None:
    """Por qué no cabe ``target`` en el límite de rutas de Windows (``core.paths``)."""
    text = os.path.abspath(target)
    if item.folder:
        if len(text) > MAX_FOLDER_PATH_CHARS:
            return (f"su sitio en «{ORPHANS_DIR}/» pasaría del límite de rutas de Windows "
                    f"({len(text)} > {MAX_FOLDER_PATH_CHARS} caracteres)")
        contents: tuple[tuple[str, int, int], ...] = item.seen  # type: ignore[assignment]
        longest = max((len(text) + 1 + len(rel) for rel, _size, _mtime in contents), default=0)
        if longest > MAX_FILE_PATH_CHARS:
            return (f"su sitio en «{ORPHANS_DIR}/» pasaría del límite de rutas de Windows "
                    f"({longest} > {MAX_FILE_PATH_CHARS} caracteres)")
        return None
    if len(text) > MAX_FILE_PATH_CHARS:
        return (f"su sitio en «{ORPHANS_DIR}/» pasaría del límite de rutas de Windows "
                f"({len(text)} > {MAX_FILE_PATH_CHARS} caracteres)")
    return None


def _still_orphan(sweep: _Sweep, item: _Candidate, protected: _Protected) -> bool:
    """Si ``item`` sigue siendo un resto justo antes de apartarlo: nadie lo registró ni lo
    reclamó y está como en el listado, sin cambios después de empezar."""
    if item.key in protected.files:
        return False
    path = sweep.root.joinpath(*item.path.split("/"))
    if item.folder:
        if (protected.holds(item.key)
                or PurePosixPath(item.path).name.lower() in protected.inputs):
            return False
        now = _folder_contents(path) if _real_dir(path) else None
        return now == item.seen and _newest(now) < sweep.limit
    if _TEMPORARY.search(path.name) is None and protected.companion(item.key):
        return False
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and (info.st_size, info.st_mtime_ns) == item.seen
            and info.st_mtime_ns < sweep.limit)


def _move(sweep: _Sweep, folder: str, item: _Candidate) -> Orphan | None:
    """Aparta ``item`` a la carpeta ``folder`` de ``orphans/`` con ``os.rename``, que en Windows
    nunca sustituye lo que ya está (se elige antes un nombre libre). ``None`` si ya no estaba."""
    source = sweep.root.joinpath(*item.path.split("/"))
    moved_to, target = _destination(sweep.root, folder, item)
    problem = _too_long(target, item)
    if problem is not None:
        return Orphan(item.path, item.folder, OrphanState.FAILED, reason=problem)
    try:
        os.makedirs(target.parent, exist_ok=True)
    except OSError as exc:
        return Orphan(item.path, item.folder, OrphanState.FAILED, reason=_reason(exc))
    try:
        os.rename(source, target)
    except PermissionError:
        return Orphan(item.path, item.folder, OrphanState.LOCKED, reason=LOCKED_REASON)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return Orphan(item.path, item.folder, OrphanState.FAILED, reason=_reason(exc))
    return Orphan(item.path, item.folder, OrphanState.MOVED, moved_to=moved_to)


def _move_steps(project: OrphanProject, sweep: _Sweep, folder: str, extra: frozenset[str],
                pacer: _Pacer) -> Iterator[Any]:
    """Aparta los restos por pasos; en cada paso vuelve a leer lo registrado y lo reclamado."""
    from ..project.model import Progress

    pending = sweep.found
    message = "Apartando restos de operaciones interrumpidas…"
    index = 0
    while index < len(pending) and project.writable:
        protected = _protection(project, sweep.root, extra)
        while index < len(pending):
            item = pending[index]
            index += 1
            item.result = (_move(sweep, folder, item) if _still_orphan(sweep, item, protected)
                           else None)
            if item.result is None:
                sweep.stale.append(item.path)
            if pacer.lap() and index < len(pending):
                yield Progress(PHASES[1], index, len(pending), message)
                pacer.restart()
                break


# --- Los pasos -------------------------------------------------------------------------------


def _steps(project: OrphanProject, root: Path, *, write: bool, limit: int,
           extra: frozenset[str], folder: str, budget: float, record: bool) -> Iterator[Any]:
    from ..project.model import Progress
    from ..project.session import WriteState

    sweep = _Sweep(root, _tag(project), limit)
    pacer = _Pacer(budget)
    protected = _protection(project, root, extra)
    yield from _list_steps(project, sweep, protected, pacer)
    sweep.found.sort(key=lambda item: item.path.casefold())
    total = len(sweep.found)
    yield Progress(PHASES[0], total, total, f"Restos encontrados: {total}.")
    pacer.restart()
    if write and total:
        yield from _move_steps(project, sweep, folder, extra, pacer)
    left = set(sweep.stale)
    orphans = tuple(
        item.result if item.result is not None
        else Orphan(item.path, item.folder, OrphanState.FOUND)
        for item in sweep.found if item.result is not None or item.path not in left
    )
    outcome = OrphanOutcome(
        orphans=orphans,
        folder=folder if any(item.state is OrphanState.MOVED for item in orphans) else None,
        recorded=False,
        stale=tuple(sorted(sweep.stale, key=str.casefold)),
    )
    if record and outcome.moved and project.writable:
        while True:
            attempt = project.try_write(lambda conn: record_orphans(conn, project, outcome))
            if attempt.state is WriteState.DONE:
                break
            yield Progress(PHASES[2], total, total, attempt.message)
        outcome = OrphanOutcome(outcome.orphans, outcome.folder, True, outcome.stale)
    yield Progress(PHASES[2], total, total, _summary(outcome), result=outcome)


def _summary(outcome: OrphanOutcome) -> str:
    return (f"Restos apartados: {len(outcome.moved)}; sin apartar (se reintentará): "
            f"{len(outcome.retry)}; vistos en solo lectura: {len(outcome.found)}.")
