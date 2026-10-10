# SPDX-License-Identifier: GPL-3.0-or-later
"""Originales de las entradas tabulares y documentales (spec 008; RF-008-14, RF-008-53; D-3 y
D-18 de la spec; ADR-0025 §8; plan 008 §5.2.2, §5.3.1, §5.3.4 y §5.4.8).

Una entrada tabular o documental (CSV, TXT, XLSX, MDB, ACCDB, PDF, imagen no georreferenciada o
encargo) guarda en el proyecto, además de lo importado, una **copia inmutable de los ficheros
recibidos** con su huella: ``originals/<input_uid>/<nombre>``. :func:`store_originals_steps` la
guarda **después** de registrar la entrada (``register_input`` y ``complete`` de su
importación), por pasos que el temporizador de ``bl`` avanza:

1. **Decidir**, leyendo el proyecto (no escribe nada salvo en el caso «demasiado grande»):

   - de un ráster o una nube de puntos nunca se guarda el original (D-3: queda lo importado),
     ni de los tipos que no son ``table`` ni ``document`` salvo que su importador los declare
     tabulares (``tabular``: unos sondeos de un CSV, un encargo), ni de una tabla del proyecto
     (no hay fichero): ``not_applicable``, sin escribir nada;
   - si sus ficheros pasan juntos del límite ``core.original_copy_limit`` (el del proyecto o, si
     aún no lo tiene, el valor por defecto de su definición: 200 MB, MB = 10⁶ B; D-18), no se
     copia nada: la entrada queda «original no guardado» (``too_large``) con el aviso de la spec
     §8 (:attr:`OriginalsOutcome.warning`) y el evento ``original_not_stored``;
   - si no, antes de copiar nada se comprueba que cada copia verificada está y tiene el tamaño
     registrado y que su sitio en ``originals/`` cabe en el límite de rutas de Windows y está
     libre.

2. **Copiar** cada fichero desde la **copia verificada** que hizo el trabajo de su importación
   (``JobDir.copy_input`` de la 004: huella antes, durante y después), nunca desde la fuente
   (RF-008-14): en el volumen del proyecto se comprueba su huella y se **mueve**; en otro (los
   trabajos en el disco local y el proyecto en la red) o si moverla falla por ser otro volumen,
   se copia con su huella y ``fsync``. Lo uno y lo otro, por trozos medidos por tiempo: ningún
   paso pasa de ``budget_s`` (20 ms; el trabajo de cada paso se planea para la mitad, el resto
   es del temporizador y de la interfaz). La huella y el tamaño tienen que ser los registrados
   del fichero (``gb_input_file.sha256`` y ``size``); si no, no se guarda nada.

3. **Registrar**: cada fichero pasa de su temporal (``<nombre>.tmp-<sesión>``) a su nombre, sin
   sustituir nunca un fichero que ya esté, con permiso de escritura (**sin** atributo de solo
   lectura: lo dejaría ``remove_tree`` de la 002 y no lo conserva ``copy_steps``, I-13) y con
   la fecha de la fuente; y, en una transacción, su ruta, su huella, su tamaño y su fecha
   (``gb_input_file.original_*``, que se escriben una vez), la entrada ``stored`` y, si el
   proyecto aún no lo tenía, el límite con su valor por defecto «sin confirmar» (RF-008-04).

El nombre de un original es el del fichero recibido; si se repite en la entrada,
``<ord>_<nombre>``, y si su ruta pasaría del límite de Windows (``core.paths``),
``<ord>_<nombre recortado>`` con su extensión: el nombre completo sigue en la base
(``gb_input_file.path``).

Parar los pasos (``close()``), un fallo o una copia que no coincide no dejan nada a medias: lo
copiado se borra (es una copia propia sin registrar), lo movido vuelve a su sitio con su
atributo y su fecha, y las carpetas creadas que quedan vacías se quitan; la base no cambia. Con
otro programa leyendo el proyecto, la escritura se reintenta en el paso siguiente
(``Project.try_write``). Los rechazos para la persona son ``ProvenanceError``
(``core.read_only`` en solo lectura, sin tocar nada; ``core.input_unknown``;
``core.original_copy_missing``, ``_copy_mismatch``, ``_exists`` y ``_copy_failed``), el
``ProjectError`` de una ruta demasiado larga (``core.path_too_long``) y el ``ParamError`` de un
límite sin definición registrada (``core.param_undefined``); los del programa,
``TypeError``/``ValueError``. Python puro (ADR-0004).
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol

from ..datasets.model import Store
from ..ids import SHORT_UID_CHARS
from ..params.model import DEFINITIONS, ParamError
from ..params.store import ParameterStore
from ..paths import MAX_FILE_PATH_CHARS, check_path_length
from ..project.events import EventKind, record_event
from ..project.model import OpenStatus, Progress
from ..project.session import WriteAttempt, WriteState
from ..provenance.messages import ProvenanceError, render
from ..provenance.operations import READ_ONLY_PREFIX
from ..timeutil import Clock, format_utc
from ..units import convert
from . import registry
from .model import FileAnchor, InputFileRecord, InputRecord, OriginalState

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo

ORIGINAL_COPY_LIMIT = "core.original_copy_limit"
"""El parámetro del límite de los originales (``core/params/core_defs.py``; D-18)."""
ORIGINALS_DIR = Store.ORIGINALS.value
"""La carpeta de los originales en la raíz del proyecto (ADR-0025 §8)."""
NEVER_KINDS: tuple[str, ...] = ("raster", "point_cloud")
"""Los tipos de entrada que nunca guardan su original (D-3): de ellos queda lo importado."""
TABULAR_KINDS: tuple[str, ...] = ("table", "document")
"""Los tipos de entrada que guardan su original si su importador no dice otra cosa."""
STEP_BUDGET_S = 0.020
"""Lo que puede durar un paso (plan 008 §2: ≤ 20 ms por tic)."""
WORK_FRACTION = 0.5
"""La parte del presupuesto de un paso que se planea para leer, copiar y hashear."""
CHUNK_BYTES = 256 * 1024
"""Lo que se lee de una vez: unos 1,5 ms de sha256 en el PC de referencia."""
SYNC_BYTES = 2 * 1024 * 1024
"""Cada cuánto se fuerza a disco lo copiado (``fsync``), dentro de un paso."""
TEMPORARY_MARK = ".tmp-"
"""``<nombre>.tmp-<sesión>``: el temporal de un original, con las 8 últimas cifras de la
sesión (como ``manifest.json.tmp-<sesión>``)."""
PHASES: tuple[str, ...] = ("límite", "comprobación", "copia", "registro")
"""Las fases de los pasos (:class:`~geoblender.core.project.model.Progress`)."""
BYTES = "B"
_OBJ = "Originales de la entrada"


class OriginalsProject(Protocol):
    """Lo que se usa del proyecto (``core.project.Project``): su identidad y su raíz, su
    estado (solo lectura), el reloj, la sesión, leer y escribir con reintento."""

    @property
    def uid(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def root(self) -> Path: ...

    @property
    def clock(self) -> Clock: ...

    @property
    def session(self) -> SessionInfo: ...

    @property
    def writable(self) -> bool: ...

    @property
    def closed(self) -> bool: ...

    @property
    def status(self) -> OpenStatus: ...

    def read(self) -> AbstractContextManager[Any]: ...

    def try_write(self, work: Callable[[Any], Any]) -> WriteAttempt: ...


@dataclass(frozen=True)
class StoredOriginal:
    """Un original guardado: el orden de su fichero en la entrada, el nombre recibido, su ruta
    en el proyecto (``originals/<uid>/<nombre>``), su huella, su tamaño y su fecha
    (``st_mtime_ns``, la de la fuente)."""

    ord: int
    name: str
    path: str
    sha256: str
    size: int
    mtime_ns: int


def _megabytes(size: int, limit: float) -> float:
    """El tamaño en MB (10⁶ B) con un decimal o, si así no se ve mayor que el límite, exacto
    (un byte de más que 1 MB: 1,000001)."""
    exact = Fraction(size, 10**6)
    shown = round(exact, 1)
    return float(shown if shown > Fraction(limit) else exact)


@dataclass(frozen=True)
class OriginalsOutcome:
    """Lo que hizo :func:`store_originals_steps` con la entrada ``input_uid`` (``name``):
    ``state`` (:class:`~.model.OriginalState`), los originales guardados (``files``), el
    fichero principal (``file``), lo que pesan sus ficheros (``size``, bytes) y el límite que
    se aplicó (``limit``, en MB; ``None`` si no se miró)."""

    input_uid: str
    name: str
    state: OriginalState
    files: tuple[StoredOriginal, ...] = ()
    file: str | None = None
    size: int = 0
    limit: float | None = None

    @property
    def warning(self) -> str | None:
        """El aviso de la spec §8 si el original no se guardó por pasar del límite: «El
        original de «Sondeos.mdb» (350 MB) pasa del límite de 200 MB: se guarda solo lo
        importado.»; si no, ``None``."""
        return self.render("es")

    def render(self, language: str = "es") -> str | None:
        """:attr:`warning` en ``language`` (``"es"`` o ``"en"``)."""
        if self.state is not OriginalState.TOO_LARGE or self.limit is None:
            return None
        return render("core.original_too_large", language=language, file=self.file,
                      size=_megabytes(self.size, self.limit), limit=self.limit)


@dataclass
class _Item:
    """Un fichero que se guarda y por dónde va (para deshacer)."""

    ord: int
    name: str
    stored: str
    sha256: str
    size: int
    mtime_ns: int
    copy: Path
    temp: Path
    final: Path
    relative: str
    current: Path | None = None  # dónde está ahora lo que es de esta guarda
    moved_from: Path | None = None  # la copia verificada que se movió
    copy_mode: int | None = None
    copy_times: tuple[int, int] | None = None
    result: StoredOriginal | None = None


@dataclass
class _Plan:
    """Lo decidido para una entrada."""

    record: InputRecord
    state: OriginalState
    file: str
    size: int
    limit: float | None = None
    limit_unit: str | None = None
    limit_bytes: float | None = None
    default_limit: bool = False
    folder: Path | None = None
    items: list[_Item] = field(default_factory=list)

    def outcome(self) -> OriginalsOutcome:
        files = tuple(item.result for item in self.items if item.result is not None)
        return OriginalsOutcome(self.record.uid, self.record.name, self.state, files=files,
                                file=self.file, size=self.size, limit=self.limit)


class _Pacer:
    """Mide un paso: termina cuando lo hecho más el trozo más lento del paso pasaría de su
    parte del presupuesto (siempre al menos un trozo)."""

    def __init__(self, budget_s: float) -> None:
        self.target = budget_s * WORK_FRACTION
        self.restart()

    def restart(self) -> None:
        self.start = self.last = time.perf_counter()
        self.slowest = 0.0

    def lap(self) -> bool:
        """Tras un trozo: verdadero si el paso tiene que terminar ya."""
        now = time.perf_counter()
        self.slowest = max(self.slowest, now - self.last)
        self.last = now
        return now - self.start + self.slowest > self.target


# --- Comprobaciones -----------------------------------------------------------------------------


def _input_uid(value: object) -> str:
    if isinstance(value, InputRecord):
        return value.uid
    if not isinstance(value, str):
        raise TypeError(f"una entrada se indica por su uid o su InputRecord, no {value!r}")
    return value


def _copies(value: object) -> tuple[Path, ...]:
    """Las copias verificadas, una por fichero de la entrada y en su orden, con su ruta
    completa (las da el trabajo de la importación)."""
    if isinstance(value, str | bytes | os.PathLike) or not isinstance(value, Sequence):
        raise TypeError(f"las copias verificadas son una lista de rutas, no {value!r}")
    found: list[Path] = []
    for item in value:
        if not isinstance(item, str | os.PathLike):
            raise TypeError(f"una copia verificada es una ruta, no {item!r}")
        path = Path(os.fspath(item))
        if not path.is_absolute():
            raise ValueError(f"una copia verificada se da con su ruta completa, no {item!r}")
        found.append(path)
    return tuple(found)


def _budget(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"el presupuesto de un paso es un número de segundos, no {value!r}")
    if not value > 0:
        raise ValueError(f"el presupuesto de un paso es positivo, no {value!r}")
    return float(value)


def _require_writable(project: OriginalsProject) -> None:
    """En solo lectura no se guarda nada (``core.read_only``, plan §5.3.1)."""
    if project.writable:
        return
    if project.closed:
        reason = "cerrado"
    else:
        reason = str(project.status.message).removeprefix(READ_ONLY_PREFIX)
    raise ProvenanceError("core.read_only", project=project.name, reason=reason)


def _received_name(file: InputFileRecord) -> str:
    """El nombre del fichero recibido (su ruta se guarda con «/»; en otro volumen, solo él)."""
    return PurePosixPath(file.path).name


def _limit(conn: Any, project: OriginalsProject) -> tuple[float, str, bool]:
    """El límite (valor, unidad y si es el valor por defecto que aún no tiene el proyecto)."""
    found = ParameterStore(project).get(ORIGINAL_COPY_LIMIT, conn=conn)
    if found is not None:
        return float(found.value), found.unit, False  # type: ignore[arg-type]
    defn = DEFINITIONS.get(ORIGINAL_COPY_LIMIT)
    if defn is None:
        raise ParamError("core.param_undefined", key=ORIGINAL_COPY_LIMIT)
    return float(defn.default), defn.unit, True  # type: ignore[arg-type]


def _tag(project: OriginalsProject) -> str:
    return project.session.session_uid.replace("-", "")[-SHORT_UID_CHARS:] or "sesion"


def _shortened(name: str, ord_: int, room: int, folder: Path, tag: str) -> str:
    """``<ord>_<nombre recortado>`` con su extensión, de ``room`` caracteres como mucho."""
    prefix = f"{ord_}_"
    suffix = PurePosixPath(name).suffix
    stem = name[: len(name) - len(suffix)] if suffix else name
    if len(prefix) + len(suffix) + 1 > room:
        suffix = ""
    keep = room - len(prefix) - len(suffix)
    if keep < 1:  # ni recortado cabe: el error de la ruta más larga
        check_path_length(folder / f"{name}{TEMPORARY_MARK}{tag}", obj=_OBJ)
    # Windows quita los puntos y espacios del final de un nombre: no se dejan.
    return prefix + (stem[:keep].rstrip(" .") or "original") + suffix


def _items(plan: _Plan, project: OriginalsProject, copies: tuple[Path, ...]) -> list[_Item]:
    """Lo que se va a guardar, comprobado antes de copiar nada."""
    record = plan.record
    folder = Path(project.root) / ORIGINALS_DIR / record.uid
    check_path_length(folder, folder=True, obj=_OBJ)
    tag = _tag(project)
    room = MAX_FILE_PATH_CHARS - len(os.path.abspath(folder)) - 1 - len(TEMPORARY_MARK) - len(tag)
    used: set[str] = set()
    items: list[_Item] = []
    for file, copy in zip(record.files, copies, strict=True):
        name = _received_name(file)
        stored = name if name.casefold() not in used else f"{file.ord}_{name}"
        if len(stored) > room:
            stored = _shortened(name, file.ord, room, folder, tag)
        used.add(stored.casefold())
        relative = f"{ORIGINALS_DIR}/{record.uid}/{stored}"
        final = folder / stored
        temp = folder / f"{stored}{TEMPORARY_MARK}{tag}"
        for path in (final, temp):
            if os.path.lexists(path):
                raise ProvenanceError("core.original_exists",
                                      path=f"{ORIGINALS_DIR}/{record.uid}/{path.name}")
        try:
            found = os.stat(copy)
        except OSError:
            found = None
        if found is None or not stat.S_ISREG(found.st_mode):
            raise ProvenanceError("core.original_copy_missing", file=name, name=record.name)
        if found.st_size != file.size:
            raise ProvenanceError("core.original_copy_mismatch", file=name, name=record.name)
        items.append(_Item(file.ord, name, stored, file.sha256, int(file.size or 0),
                           int(file.mtime_ns or 0), copy, temp, final, relative))
    plan.folder = folder
    return items


def _decide(conn: Any, project: OriginalsProject, uid: str, copies: tuple[Path, ...],
            tabular: bool | None) -> _Plan:
    """Qué se hace con la entrada ``uid`` (véase el módulo). Solo lee."""
    record = registry.get(conn, uid)
    if record is None or record.uid != uid:
        raise ProvenanceError("core.input_unknown", input=uid, project=project.name)
    if record.original is not OriginalState.NOT_APPLICABLE:
        raise ValueError(f"el original de la entrada «{record.name}» ya está decidido "
                         f"({record.original}): se guarda una vez, al registrarla")
    names = [_received_name(file) for file in record.files]
    plan = _Plan(record, OriginalState.NOT_APPLICABLE, names[0],
                 sum(int(file.size or 0) for file in record.files))
    if record.kind in NEVER_KINDS:
        if tabular:
            raise ValueError(f"de un {record.kind} («{record.name}») nunca se guarda el original "
                             "(D-3): no se declara tabular")
        return plan
    wanted = record.kind in TABULAR_KINDS if tabular is None else tabular
    tables = any(file.anchor is FileAnchor.PROJECT_TABLE for file in record.files)
    if not wanted or tables:
        return plan
    if len(copies) != len(record.files):
        raise ValueError(f"la entrada «{record.name}» tiene {len(record.files)} ficheros y se "
                         f"dan {len(copies)} copias verificadas: una por fichero, en su orden")
    plan.limit, plan.limit_unit, plan.default_limit = _limit(conn, project)
    plan.limit_bytes = convert(plan.limit, plan.limit_unit, BYTES)
    if plan.size > plan.limit_bytes:
        plan.state = OriginalState.TOO_LARGE
        return plan
    plan.state = OriginalState.STORED
    plan.items = _items(plan, project, copies)
    return plan


# --- Escrituras en la base ----------------------------------------------------------------------


def _still_undecided(conn: Any, plan: _Plan) -> None:
    record = registry.get(conn, plan.record.uid)
    if record is None or record.original is not OriginalState.NOT_APPLICABLE:
        raise ValueError(f"el original de la entrada «{plan.record.name}» se ha decidido mientras "
                         "tanto: no se guarda dos veces")


def _ensure_limit(conn: Any, project: OriginalsProject, plan: _Plan) -> None:
    """El límite que se aplicó, registrado con su valor por defecto «sin confirmar» si el
    proyecto aún no lo tenía (RF-008-04)."""
    if plan.default_limit:
        ParameterStore(project).ensure_default(
            conn, ORIGINAL_COPY_LIMIT, geoblender_version=project.session.geoblender_version
        )


def _set_original(conn: Any, plan: _Plan, now: str) -> None:
    conn.execute("UPDATE gb_input SET original = ?, modified_at = ? WHERE uid = ?",
                 (str(plan.state), now, plan.record.uid))


def _write_too_large(conn: Any, project: OriginalsProject, plan: _Plan) -> None:
    _still_undecided(conn, plan)
    _ensure_limit(conn, project, plan)
    now = format_utc(project.clock.now())
    _set_original(conn, plan, now)
    limit_bytes = plan.limit_bytes or 0.0
    warning = plan.outcome().warning or ""
    record_event(conn, EventKind.ORIGINAL_NOT_STORED, warning, session=project.session, at=now,
                 entity_kind="input", entity_uid=plan.record.uid, data={
                     "name": plan.record.name,
                     "file": plan.file,
                     "files": [_received_name(file) for file in plan.record.files],
                     "size_bytes": plan.size,
                     "limit_bytes": int(limit_bytes) if limit_bytes.is_integer() else limit_bytes,
                     "limit_value": plan.limit,
                     "limit_unit": plan.limit_unit,
                 })


def _write_stored(conn: Any, project: OriginalsProject, plan: _Plan) -> None:
    _still_undecided(conn, plan)
    _ensure_limit(conn, project, plan)
    conn.executemany(
        "UPDATE gb_input_file SET original_path = ?, original_sha256 = ?, original_size = ?, "
        "original_mtime_ns = ? WHERE input_uid = ? AND ord = ?",
        [(item.result.path, item.result.sha256, item.result.size, item.result.mtime_ns,
          plan.record.uid, item.ord) for item in plan.items if item.result is not None],
    )
    _set_original(conn, plan, format_utc(project.clock.now()))


def _written(project: OriginalsProject, work: Callable[[Any], None], phase: str, done: int,
             total: int) -> Iterator[Progress]:
    """``work`` en una transacción de escritura; con otro programa leyendo el proyecto, se
    reintenta en el paso siguiente."""
    while True:
        attempt = project.try_write(work)
        if attempt.state is WriteState.DONE:
            return
        yield Progress(phase, done, total, attempt.message)


# --- Ficheros -----------------------------------------------------------------------------------


def _rename_new(source: Path, target: Path) -> None:
    """Renombra ``source`` a ``target`` sin sustituir nunca un fichero que ya esté
    (``FileExistsError``; en Windows, ``os.rename`` no sustituye)."""
    if os.path.lexists(target):
        raise FileExistsError(errno.EEXIST, "ya existe", os.fspath(target))
    os.rename(source, target)


def _same_volume(first: Path, second: Path) -> bool:
    """Si dos rutas están en el mismo volumen (se puede mover sin copiar)."""
    try:
        return os.stat(first).st_dev == os.stat(second).st_dev
    except OSError:
        return False


def _failed(plan: _Plan, item: _Item, exc: OSError) -> ProvenanceError:
    """El error de un fichero que no se pudo guardar, sin rutas en el motivo."""
    if isinstance(exc, FileNotFoundError) and exc.filename is not None and Path(
        os.fsdecode(exc.filename)
    ) == item.copy:
        return ProvenanceError("core.original_copy_missing", file=item.name,
                               name=plan.record.name)
    reason = exc.strerror or type(exc).__name__
    return ProvenanceError("core.original_copy_failed", file=item.name, name=plan.record.name,
                           reason=reason)


def _make_folder(folder: Path, created: list[Path]) -> None:
    """``originals/`` y ``originals/<uid>/``, si no están (se apuntan para deshacer)."""
    for path in (folder.parent, folder):
        if not path.is_dir():
            path.mkdir()
            created.append(path)


def _check_print(plan: _Plan, item: _Item, digest: str, size: int) -> None:
    if size != item.size or digest != item.sha256:
        raise ProvenanceError("core.original_copy_mismatch", file=item.name,
                              name=plan.record.name)


def _hash_copy(plan: _Plan, item: _Item, pacer: _Pacer, done: int,
               total: int) -> Iterator[Progress]:
    """La huella de la copia verificada, por trozos; no escribe nada."""
    digest = hashlib.sha256()
    size = 0
    message = f"Comprobando la copia de «{item.name}»…"
    try:
        with open(item.copy, "rb") as reader:
            while chunk := reader.read(CHUNK_BYTES):
                digest.update(chunk)
                size += len(chunk)
                if pacer.lap():
                    yield Progress(PHASES[1], done + size, total, message)
                    pacer.restart()
    except OSError as exc:
        raise _failed(plan, item, exc) from exc
    _check_print(plan, item, digest.hexdigest(), size)


def _copy_chunks(plan: _Plan, item: _Item, created: list[Path], pacer: _Pacer, done: int,
                 total: int) -> Iterator[Progress]:
    """La copia verificada, copiada a su temporal por trozos con su huella y ``fsync``."""
    digest = hashlib.sha256()
    size = 0
    unsynced = 0
    message = f"Copiando el original de «{item.name}»…"
    try:
        _make_folder(item.temp.parent, created)
        with open(item.copy, "rb") as reader:
            try:
                writer = open(item.temp, "xb")  # se cierra con el «with writer» de abajo
            except FileExistsError:
                raise ProvenanceError("core.original_exists",
                                      path=f"{ORIGINALS_DIR}/{plan.record.uid}/{item.temp.name}"
                                      ) from None
            item.current = item.temp
            with writer:
                while chunk := reader.read(CHUNK_BYTES):
                    if unsynced >= SYNC_BYTES:
                        writer.flush()
                        os.fsync(writer.fileno())
                        unsynced = 0
                    writer.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                    unsynced += len(chunk)
                    if pacer.lap():
                        yield Progress(PHASES[2], done + size, total, message)
                        pacer.restart()
                writer.flush()
                os.fsync(writer.fileno())
    except OSError as exc:
        raise _failed(plan, item, exc) from exc
    _check_print(plan, item, digest.hexdigest(), size)


def _prepare(plan: _Plan, item: _Item, project: OriginalsProject, created: list[Path],
             pacer: _Pacer, same_volume: Callable[[Path, Path], bool], done: int,
             total: int) -> Iterator[Progress]:
    """Deja el fichero en su temporal: la copia verificada, comprobada y movida si está en el
    volumen del proyecto; si no (o si moverla falla por ser otro volumen), copiada."""
    if same_volume(item.copy, Path(project.root)):
        yield from _hash_copy(plan, item, pacer, done, total)
        try:
            found = os.stat(item.copy)
            _make_folder(item.temp.parent, created)
            _rename_new(item.copy, item.temp)
        except FileExistsError:
            raise ProvenanceError("core.original_exists",
                                  path=f"{ORIGINALS_DIR}/{plan.record.uid}/{item.temp.name}"
                                  ) from None
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise _failed(plan, item, exc) from exc
        else:
            item.current = item.temp
            item.moved_from = item.copy
            item.copy_mode = stat.S_IMODE(found.st_mode)
            item.copy_times = (found.st_atime_ns, found.st_mtime_ns)
            return
    yield from _copy_chunks(plan, item, created, pacer, done, total)


def _place(plan: _Plan) -> None:
    """Cada temporal, a su nombre, con permiso de escritura y la fecha de la fuente."""
    for item in plan.items:
        try:
            if item.current is None:  # pragma: no cover - lo deja _prepare
                raise ValueError(f"«{item.name}» no está preparado")
            _rename_new(item.current, item.final)
            item.current = item.final
            os.chmod(item.final, stat.S_IREAD | stat.S_IWRITE)
            os.utime(item.final, ns=(os.stat(item.final).st_atime_ns, item.mtime_ns))
            found = os.stat(item.final)
        except FileExistsError:
            raise ProvenanceError("core.original_exists", path=item.relative) from None
        except OSError as exc:
            raise _failed(plan, item, exc) from exc
        item.result = StoredOriginal(item.ord, item.name, item.relative, item.sha256,
                                     found.st_size, found.st_mtime_ns)


def _undo(plan: _Plan, created: list[Path]) -> None:
    """Deshace lo que no llegó a registrarse: lo copiado se borra (es propio y no está en la
    base) y lo movido vuelve a su sitio con su atributo y su fecha; las carpetas creadas, si
    quedan vacías, se quitan. Lo que no se puede deshacer queda como resto de ``originals/``
    (lo aparta la comprobación al abrir, RF-008-22)."""
    for item in reversed(plan.items):
        current = item.current
        if current is None:
            continue
        try:
            if item.moved_from is None:
                os.unlink(current)
            else:
                os.rename(current, item.moved_from)
                if item.copy_times is not None:
                    os.chmod(item.moved_from, stat.S_IREAD | stat.S_IWRITE)
                    os.utime(item.moved_from, ns=item.copy_times)
                if item.copy_mode is not None:
                    os.chmod(item.moved_from, item.copy_mode)
        except OSError:
            continue
        item.current = None
        item.result = None
    for folder in reversed(created):
        try:
            folder.rmdir()
        except OSError:
            continue


# --- Pasos --------------------------------------------------------------------------------------


def store_originals_steps(
    project: OriginalsProject,
    input_uid: str | InputRecord,
    verified_copies: Sequence[str | os.PathLike[str]],
    *,
    tabular: bool | None = None,
    budget_s: float = STEP_BUDGET_S,
    same_volume: Callable[[Path, Path], bool] | None = None,
) -> Iterator[Progress]:
    """Guarda el original de la entrada ``input_uid`` (su uid o su ``InputRecord``) desde
    ``verified_copies`` (la copia verificada de cada fichero de la entrada, en su orden, con
    su ruta completa) por pasos de ``budget_s`` como mucho (RF-008-53, RF-008-14; véase el
    módulo). ``tabular``: lo que declara su importador (``None``: ``table`` y ``document``
    sí, lo demás no; un ráster o una nube, nunca). ``same_volume(copia, raíz)``: si la copia se
    puede mover (por defecto, el mismo volumen). Cada paso es un
    :class:`~geoblender.core.project.model.Progress` en bytes; el último lleva el
    :class:`OriginalsOutcome` en ``result``; cerrar el generador cancela sin dejar nada."""
    uid = _input_uid(input_uid)
    copies = _copies(verified_copies)
    if tabular is not None and not isinstance(tabular, bool):
        raise TypeError(f"tabular es verdadero, falso o None, no {tabular!r}")
    budget = _budget(budget_s)
    if same_volume is None:
        same_volume = _same_volume
    elif not callable(same_volume):
        raise TypeError(f"same_volume es una función, no {same_volume!r}")
    _require_writable(project)
    with project.read() as conn:
        plan = _decide(conn, project, uid, copies, tabular)
    if plan.state is OriginalState.NOT_APPLICABLE:
        yield Progress(PHASES[0], 0, 0, f"No se guarda el original de «{plan.file}».",
                       result=plan.outcome())
        return
    if plan.state is OriginalState.TOO_LARGE:
        yield from _written(project, lambda conn: _write_too_large(conn, project, plan),
                            PHASES[0], 0, 0)
        outcome = plan.outcome()
        yield Progress(PHASES[0], 0, 0, outcome.warning or "", result=outcome)
        return
    total = plan.size
    created: list[Path] = []
    committed = False
    try:
        yield Progress(PHASES[0], 0, total, f"Guardando el original de «{plan.file}»…")
        pacer = _Pacer(budget)
        done = 0
        for item in plan.items:
            yield from _prepare(plan, item, project, created, pacer, same_volume, done, total)
            done += item.size
        yield Progress(PHASES[3], total, total, f"Registrando el original de «{plan.file}»…")
        _place(plan)
        yield from _written(project, lambda conn: _write_stored(conn, project, plan),
                            PHASES[3], total, total)
        committed = True
    finally:
        if not committed:
            _undo(plan, created)
    yield Progress(PHASES[3], total, total, f"Original de «{plan.file}» guardado.",
                   result=plan.outcome())
