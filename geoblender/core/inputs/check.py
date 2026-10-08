# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobación de las fuentes de las entradas (spec 008; RF-008-09, RF-008-10, RF-008-12,
RF-008-13, RF-008-14; ADR-0024 §5 y §6; ADR-0025 §6; plan 008 §5.1, §5.3.1 y §5.4.2).

:func:`check_steps` compara la fuente de cada entrada activa (vigente, cambiada o «se mantiene
la copia») con lo registrado, por pasos que el temporizador de ``bl`` avanza (ninguno pasa de
``budget_s``; el trabajo de cada paso se planea para la mitad):

1. **Prefiltro** (:func:`probe_input`), solo leyendo los metadatos: cada fichero se busca donde
   está anclado (``resolve_source``, RF-002-19) y se mira su tamaño y su fecha (``stat``) frente
   a la última comprobación (``checked_*``) o, si no la hay, a lo registrado; de una tabla del
   proyecto, su ``last_change`` en ``gpkg_contents``. Junto a una fuente SQLite (su lector lo
   declara), un ``-wal`` o un ``-journal`` no vacío lleva siempre al hash: la edición puede estar
   ahí con el principal intacto (I-3). Un fichero que no se encuentra (borrado, movido o de otro
   volumen sin su ubicación anotada en este equipo) hace la entrada **no localizable**
   (RF-008-13): no se lee, no es un cambio y se sigue con lo importado.
2. **Hash de contenido**, en la comprobación **rápida** (:attr:`CheckMode.QUICK`: al abrir y
   antes de operar) solo si el prefiltro saltó; en la **completa** (:attr:`CheckMode.FULL`:
   «Comprobar cambios en las entradas»), siempre (RF-008-09). Con **su** lector, **su**
   normalizador y sus declaraciones (ADR-0024 §6), en el hilo y por trozos; el lector recibe
   los ficheros con los papeles de :func:`reader_roles`. Los lectores leen sin escribir nada
   junto a la fuente (RF-008-14): un GeoPackage en WAL, sobre una copia privada.
3. **Veredicto** (:func:`assess`, :class:`Verdict`): frente al contenido registrado (vigente) o
   al visto al detectar el cambio o al mantener la copia (``seen_sha256``): igual → solo cambió
   el contenedor, se anota la comprobación; distinto → «cambiada» (RF-008-10), con el aviso de
   la spec §8 y lo que depende de ella (:func:`dependents`); una cambiada o mantenida que vuelve
   a su contenido registrado, otra vez «vigente». Una mantenida no avisa mientras su fuente siga
   como se vio (RF-008-12).
4. **Registro** (:func:`record_findings`), en una transacción al final (``Project.try_write``,
   con reintento en el paso siguiente si otro programa lee): la última comprobación de cada
   fichero hasheado (tamaño, fecha o ``last_change``, y cuándo), el estado y el contenido visto,
   y los eventos ``input_changed`` e ``input_restored``. Lo que no saltó no se escribe. Una
   entrada que cambió de estado mientras se comprobaba (una decisión de la persona) no se toca:
   queda para la próxima. En **solo lectura** se detecta y se avisa, sin registrar nada.

«Comprobando» y «no localizable» no se guardan (dependen del equipo y del momento: plan D7). El
trabajo de la 004 para las fuentes externas grandes lo añade la comprobación de apertura (T37):
aquí todo se hashea en el hilo. Python puro (ADR-0004).
"""

from __future__ import annotations

import datetime as dt
import ntpath
import os
import re
import sqlite3
import stat
import time
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from ..content.readers import READERS, read_steps
from ..content.readers import reader as content_reader
from ..datasets.model import LIVE_STATUSES
from ..errors import GeoblenderError
from ..i18n import LANGUAGES
from ..paths import ABSOLUTE_PATH
from ..project.events import EventKind, record_event
from ..project.model import Progress
from ..project.session import WriteState
from ..provenance.messages import ProvenanceError, render
from ..timeutil import Clock, format_utc, parse_utc
from . import registry
from .model import (
    ACTIVE_STATUSES,
    FileAnchor,
    FileRole,
    InputFileRecord,
    InputRecord,
    InputStatus,
    SourceFile,
)

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo
    from ..userdata import UserData

STEP_BUDGET_S = 0.020
"""Lo que puede durar un paso (plan 008 §2: ≤ 20 ms por tic)."""
WORK_FRACTION = 0.5
"""La parte del presupuesto de un paso que se planea para mirar y leer las fuentes."""
JOURNAL_SUFFIXES: tuple[str, ...] = ("-wal", "-journal")
"""Lo que, junto a una fuente SQLite y no vacío, lleva al hash (plan §5.4.2, I-3)."""
PHASES: tuple[str, ...] = ("prefiltro", "contenido", "registro")
"""Las fases de los pasos (:class:`~geoblender.core.project.model.Progress`)."""
MAIN_ROLE = "main"
"""El papel del fichero principal para su lector."""
SIDECAR_ROLE = "sidecar"
"""El papel de un compañero sin una extensión que lo nombre: ``sidecar<n>`` (su orden)."""
MAX_REASON_CHARS = 300
"""Largo máximo del motivo de una fuente que no se puede leer."""

_ROLE = re.compile(r"[a-z][a-z0-9_]*")
_ACTIVE = ", ".join(f"'{status}'" for status in ACTIVE_STATUSES)
_LIVE_DATASETS = ", ".join(f"'{status}'" for status in LIVE_STATUSES)
_COUNTS: Mapping[str, Mapping[str, tuple[str, str]]] = MappingProxyType({
    "es": {"datasets": ("dato", "datos"), "operations": ("operación", "operaciones"),
           "figures": ("cifra", "cifras")},
    "en": {"datasets": ("dataset", "datasets"), "operations": ("operation", "operations"),
           "figures": ("figure", "figures")},
})
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


class CheckMode(StrEnum):
    """Cómo se comprueba (RF-008-09)."""

    QUICK = "quick"  # al abrir y antes de operar: tamaño y fecha; hash si algo cambió
    FULL = "full"  # a petición: siempre el hash de contenido


class Verdict(StrEnum):
    """Lo que encontró la comprobación de una entrada."""

    UNCHANGED = "unchanged"  # el prefiltro no saltó: no se hasheó
    SAME = "same"  # el contenido es el de referencia: solo cambió el contenedor
    CHANGED = "changed"  # otro contenido: «cambiada» (RF-008-10)
    RESTORED = "restored"  # una cambiada o mantenida vuelve a su contenido registrado
    UNREACHABLE = "unreachable"  # «no localizable» (RF-008-13)
    UNREADABLE = "unreadable"  # su lector no la puede leer (o no está registrado)


class CheckProject(Protocol):
    """Lo que se usa del proyecto (``core.project.Project``): su identidad, su raíz, su base y
    los datos de usuario (las fuentes, RF-002-19), el reloj, la sesión, si se puede escribir,
    leer y escribir con reintento."""

    @property
    def uid(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def root(self) -> Path: ...

    @property
    def database_path(self) -> Path: ...

    @property
    def userdata(self) -> UserData: ...

    @property
    def clock(self) -> Clock: ...

    @property
    def session(self) -> SessionInfo: ...

    @property
    def writable(self) -> bool: ...

    def read(self) -> AbstractContextManager[Any]: ...

    def try_write(self, work: Callable[[Any], Any]) -> Any: ...


# --- Lo que se ve y lo que se encuentra ---------------------------------------------------------


@dataclass(frozen=True)
class FileSeen:
    """Lo que se vio de un fichero de la entrada (su orden): tamaño y fecha (``st_mtime_ns``)
    o, de una tabla del proyecto, su ``last_change``."""

    ord: int
    size: int | None
    mtime_ns: int | None
    last_change: str | None = None


@dataclass(frozen=True)
class Dependent:
    """Algo que depende de una entrada: su uid y su nombre (el del dato, el tipo de la
    operación o la clave de la cifra)."""

    uid: str
    name: str


@dataclass(frozen=True)
class Dependents:
    """Lo que depende de una entrada (RF-008-10): los datos (lo importado y lo que se calculó
    a partir de ello), las operaciones hechas que los leen y sus cifras, por orden de
    registro."""

    datasets: tuple[Dependent, ...] = ()
    operations: tuple[Dependent, ...] = ()
    figures: tuple[Dependent, ...] = ()

    def counts(self) -> dict[str, int]:
        """Cuántos hay de cada uno."""
        return {"datasets": len(self.datasets), "operations": len(self.operations),
                "figures": len(self.figures)}


@dataclass(frozen=True)
class Probe:
    """El prefiltro de una entrada (:func:`probe_input`): lo que se vio de sus ficheros, los
    ficheros por papel para su lector, si algo cambió frente a la última comprobación o lo
    registrado (``moved``), si hay un ``-wal`` o un ``-journal`` junto a una fuente SQLite
    (``journal``), la fecha más reciente de la fuente (UTC) y, si no se encuentra, el fichero
    que falta (``missing``)."""

    record: InputRecord
    mode: CheckMode
    observed: tuple[FileSeen, ...]
    files: Mapping[str, Path]
    moved: bool
    journal: bool
    source_date: str | None
    missing: str | None = None

    @property
    def needs_hash(self) -> bool:
        """Si hay que calcular el hash de contenido: siempre en la completa; en la rápida, si
        el prefiltro saltó. Una no localizable, nunca."""
        if self.missing is not None:
            return False
        return self.mode is CheckMode.FULL or self.moved or self.journal


@dataclass(frozen=True)
class InputFinding:
    """Lo que encontró la comprobación de una entrada: su veredicto, su estado antes y
    después, el contenido visto (si se hasheó), lo que se vio de sus ficheros, la fecha de la
    fuente (UTC), lo que depende de ella (si queda «cambiada») y, si no se pudo comprobar, el
    fichero que no se encuentra o el motivo."""

    input_uid: str
    name: str
    verdict: Verdict
    before: InputStatus
    status: InputStatus
    registered_at: str
    registered_sha256: str
    previous_seen: str | None
    reader: str
    content_sha256: str | None = None
    observed: tuple[FileSeen, ...] = ()
    source_date: str | None = None
    dependents: Dependents | None = None
    file: str | None = None
    reason: str | None = None

    @property
    def hashed(self) -> bool:
        """Si se calculó su hash de contenido."""
        return self.content_sha256 is not None

    @property
    def warning(self) -> str | None:
        """El aviso de RF-008-10 si la entrada queda «cambiada» (spec §8: «La entrada
        «Limites_v1» ha cambiado desde su registro (24/09/2026 09:31). Dependen de ella: 3
        datos, 5 operaciones y 12 cifras.», con la fecha de la fuente); si no, ``None``."""
        return self.render("es")

    def render(self, language: str = "es") -> str | None:
        """:attr:`warning` en ``language`` (``"es"`` o ``"en"``)."""
        if self.status is not InputStatus.CHANGED:
            return None
        chosen = _language(language)
        found = self.dependents or Dependents()
        text = render("core.input_changed", language=chosen, name=self.name,
                      registered=_local(self.registered_at),
                      **{key: _count(value, chosen, key)
                         for key, value in found.counts().items()})
        if self.source_date is not None:
            text += " " + render("core.input_changed_source", language=chosen,
                                 source_date=_local(self.source_date))
        return text

    @property
    def notice(self) -> str | None:
        """Por qué no se pudo comprobar (no localizable o no se puede leer); si no, ``None``."""
        return self.render_notice("es")

    def render_notice(self, language: str = "es") -> str | None:
        """:attr:`notice` en ``language``."""
        chosen = _language(language)
        if self.verdict is Verdict.UNREACHABLE:
            return render("core.input_unreachable", language=chosen, name=self.name,
                          file=self.file)
        if self.verdict is Verdict.UNREADABLE:
            return render("core.input_unreadable", language=chosen, name=self.name,
                          reader=self.reader, reason=self.reason)
        return None


@dataclass(frozen=True)
class CheckOutcome:
    """El resultado de :func:`check_steps`: el modo, lo encontrado de cada entrada (en el
    orden pedido o de registro), si quedó registrado en el proyecto (``False`` en solo
    lectura) y las entradas que cambiaron de estado mientras se comprobaban (``stale``: no se
    tocan y se comprueban la próxima vez)."""

    mode: CheckMode
    findings: tuple[InputFinding, ...]
    recorded: bool
    stale: tuple[str, ...] = ()

    @property
    def changed(self) -> tuple[InputFinding, ...]:
        """Las entradas que quedan «cambiadas», sin decidir (RF-008-10)."""
        return tuple(item for item in self.findings if item.status is InputStatus.CHANGED)

    @property
    def warnings(self) -> tuple[str, ...]:
        """El aviso de cada entrada cambiada sin decidir."""
        return tuple(item.warning or "" for item in self.changed)

    @property
    def notices(self) -> tuple[str, ...]:
        """Lo que no se pudo comprobar (no localizable o no se puede leer)."""
        return tuple(item.notice for item in self.findings if item.notice is not None)


# --- Ayudas -------------------------------------------------------------------------------------


def _language(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    return language


def _count(value: int, language: str, what: str) -> str:
    singular, plural = _COUNTS[language][what]
    return f"{value} {singular if value == 1 else plural}"


def _local(moment: str) -> str:
    """Una hora UTC guardada, como la lee una persona: «DD/MM/AAAA HH:MM» en hora local."""
    try:
        return parse_utc(moment).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return moment


def _utc_ns(mtime_ns: int) -> str:
    """Una fecha de fichero (ns desde 1970) como hora UTC guardada."""
    return format_utc(_EPOCH + dt.timedelta(microseconds=mtime_ns // 1000))


def _without_paths(text: str) -> str:
    """Un motivo sin rutas absolutas (solo el nombre de su fichero) y no muy largo."""
    shown = ABSOLUTE_PATH.sub(
        lambda match: ntpath.basename(match.group(0).rstrip("\\/")) or "…", text
    )
    if len(shown) > MAX_REASON_CHARS:
        shown = shown[: MAX_REASON_CHARS - 1] + "…"
    return shown


def _budget(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"el presupuesto de un paso es un número de segundos, no {value!r}")
    if not value > 0:
        raise ValueError(f"el presupuesto de un paso es positivo, no {value!r}")
    return float(value)


class _Pacer:
    """Mide un paso: termina cuando lo hecho más lo más lento del paso pasaría de su parte del
    presupuesto (siempre al menos una unidad de trabajo)."""

    def __init__(self, budget_s: float) -> None:
        self.target = budget_s * WORK_FRACTION
        self.restart()

    def restart(self) -> None:
        self.start = self.last = time.perf_counter()
        self.slowest = 0.0

    def lap(self) -> bool:
        now = time.perf_counter()
        self.slowest = max(self.slowest, now - self.last)
        self.last = now
        return now - self.start + self.slowest > self.target


def reader_roles(files: Sequence[SourceFile | InputFileRecord]) -> tuple[str, ...]:
    """El papel de cada fichero de una entrada para su lector (``ReadRequest.files``), en su
    orden: el principal, ``"main"``; un compañero, su extensión en minúsculas (``"prj"`` del
    ``.prj`` de un ASC) o, si no la tiene, no es un nombre válido o se repite,
    ``"sidecar<n>"`` con su orden. El importador lee con los mismos papeles al calcular el
    hash, y la comprobación, al volver a calcularlo."""
    roles: list[str] = []
    used: set[str] = set()
    for index, item in enumerate(files):
        if FileRole(item.role) is FileRole.MAIN:
            role = MAIN_ROLE
        else:
            suffix = PurePosixPath(item.path).suffix.lower().removeprefix(".")
            usable = _ROLE.fullmatch(suffix) is not None and suffix not in used
            role = suffix if usable and suffix != MAIN_ROLE else f"{SIDECAR_ROLE}{index}"
        used.add(role)
        roles.append(role)
    return tuple(roles)


def _shown_name(item: InputFileRecord) -> str:
    """El nombre del fichero como se muestra (su ruta se guarda con «/»; una tabla, su
    nombre)."""
    if item.anchor is FileAnchor.PROJECT_TABLE:
        return item.path
    return PurePosixPath(item.path).name


# --- Prefiltro ----------------------------------------------------------------------------------


def table_changes(conn: sqlite3.Connection) -> dict[str, str | None]:
    """El ``last_change`` de cada tabla de ``gpkg_contents`` del proyecto (las fuentes ancladas
    a una tabla del proyecto se comprueban con él)."""
    return {str(name): change for name, change in conn.execute(
        "SELECT table_name, last_change FROM gpkg_contents")}


def _missing(record: InputRecord, mode: CheckMode, item: InputFileRecord) -> Probe:
    return Probe(record, mode, (), MappingProxyType({}), False, False, None,
                 missing=_shown_name(item))


def probe_input(project: CheckProject, record: InputRecord, *,
                mode: CheckMode | str = CheckMode.QUICK,
                tables: Mapping[str, str | None] | None = None) -> Probe:
    """El prefiltro de la entrada ``record`` (véase el módulo, paso 1): busca cada fichero y
    mira su tamaño y su fecha, sin abrirlo; ``tables``, el ``last_change`` de las tablas del
    proyecto (:func:`table_changes`), hace falta si la entrada está anclada a una. No escribe
    nada."""
    chosen = CheckMode(mode)
    observed: list[FileSeen] = []
    files: dict[str, Path] = {}
    moved = False
    newest: int | None = None
    change: str | None = None
    for item, role in zip(record.files, reader_roles(record.files), strict=True):
        if item.anchor is FileAnchor.PROJECT_TABLE:
            if tables is None:
                raise ValueError(f"la entrada «{record.name}» está anclada a la tabla del "
                                 f"proyecto «{item.path}»: hace falta su last_change (tables)")
            if item.path not in tables:
                return _missing(record, chosen, item)
            change = tables[item.path]
            reference = (item.checked_last_change if item.checked_last_change is not None
                         else item.last_change)
            moved = moved or change != reference
            observed.append(FileSeen(item.ord, None, None, change))
            files[role] = Path(project.database_path)
            continue
        path = registry.resolve_source(item, project, project.userdata)
        if path is None:
            return _missing(record, chosen, item)
        try:
            found = os.stat(path)
        except OSError:
            return _missing(record, chosen, item)
        if not stat.S_ISREG(found.st_mode):
            return _missing(record, chosen, item)
        checked = item.checked_size is not None or item.checked_mtime_ns is not None
        reference_stat = ((item.checked_size, item.checked_mtime_ns) if checked
                          else (item.size, item.mtime_ns))
        moved = moved or (found.st_size, found.st_mtime_ns) != reference_stat
        observed.append(FileSeen(item.ord, found.st_size, found.st_mtime_ns))
        files[role] = path
        newest = found.st_mtime_ns if newest is None else max(newest, found.st_mtime_ns)
    journal = False
    found_reader = READERS.get(record.reader)
    main = files.get(MAIN_ROLE)
    if (found_reader is not None and found_reader.sqlite and main is not None
            and record.files[0].anchor is not FileAnchor.PROJECT_TABLE):
        for suffix in JOURNAL_SUFFIXES:
            try:
                aux = os.stat(f"{main}{suffix}")
            except OSError:
                continue
            if aux.st_size > 0:
                journal = True
                newest = aux.st_mtime_ns if newest is None else max(newest, aux.st_mtime_ns)
    source_date = change if newest is None else _utc_ns(newest)
    return Probe(record, chosen, tuple(observed), MappingProxyType(files), moved, journal,
                 source_date)


# --- Hash y veredicto ---------------------------------------------------------------------------


def _content_steps(probe: Probe, pacer: _Pacer, done: int,
                   total: int) -> Generator[Progress, None, tuple[str | None, str | None, bool]]:
    """El hash de contenido de la fuente con su lector, por trozos: devuelve el hash, o el
    motivo por el que no se pudo leer y si es porque ya no se encuentra."""
    record = probe.record
    message = f"Comprobando el contenido de «{record.name}»…"
    try:
        found = content_reader(record.reader)
        request = found.request(record.kind, record.declarations, probe.files,
                                dict(record.settings), normalizer=record.normalizer)
    except (GeoblenderError, ValueError) as exc:
        return None, _without_paths(str(exc)), False
    steps = read_steps(found, request)
    try:
        for _fraction in steps:
            if pacer.lap():
                yield Progress(PHASES[1], done, total, message)
                pacer.restart()
    except FileNotFoundError as exc:
        return None, _without_paths(str(exc)), True
    except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
        return None, _without_paths(str(exc)), False
    finally:
        steps.close()
    return request.hasher.digest().content_sha256, None, False


def assess(probe: Probe, content_sha256: str | None = None, *,
           error: str | None = None) -> InputFinding:
    """El veredicto de una entrada (véase el módulo, paso 3) con su prefiltro y, si se
    calculó, su hash de contenido (con ``error``, por qué no se pudo leer). Sin hash ni error,
    lo que dice el prefiltro (no localizable o sin cambios: ``ValueError`` si hacía falta el
    hash)."""
    record = probe.record
    before = record.status
    values: dict[str, Any] = {
        "input_uid": record.uid,
        "name": record.name,
        "before": before,
        "registered_at": record.registered_at,
        "registered_sha256": record.content_sha256,
        "previous_seen": record.seen_sha256,
        "reader": record.reader,
        "observed": probe.observed,
        "source_date": probe.source_date,
    }
    if probe.missing is not None:
        return InputFinding(verdict=Verdict.UNREACHABLE, status=before, file=probe.missing,
                            **values)
    if error is not None:
        return InputFinding(verdict=Verdict.UNREADABLE, status=before, reason=error, **values)
    if content_sha256 is None:
        if probe.needs_hash:
            raise ValueError(f"la entrada «{record.name}» necesita su hash de contenido: el "
                             "prefiltro saltó o la comprobación es completa")
        return InputFinding(verdict=Verdict.UNCHANGED, status=before, **values)
    values["content_sha256"] = content_sha256
    if before is not InputStatus.CURRENT and content_sha256 == record.content_sha256:
        return InputFinding(verdict=Verdict.RESTORED, status=InputStatus.CURRENT, **values)
    reference = record.content_sha256
    if before is not InputStatus.CURRENT and record.seen_sha256 is not None:
        reference = record.seen_sha256
    if content_sha256 == reference:
        return InputFinding(verdict=Verdict.SAME, status=before, **values)
    return InputFinding(verdict=Verdict.CHANGED, status=InputStatus.CHANGED, **values)


# --- Lo que depende de una entrada --------------------------------------------------------------


def dependents(conn: sqlite3.Connection, record: InputRecord) -> Dependents:
    """Lo que depende de la entrada ``record`` (RF-008-10): los datos vivos que escribió su
    importación (lo importado y, en una tabla común, el acumulado) y, aguas abajo, las
    operaciones hechas y no sustituidas que leen esos datos o la propia entrada, los datos
    vivos que escriben y sus cifras. Su importación no cuenta (no lee nada: es su registro).
    Solo lee."""
    datasets: dict[str, str] = {}
    operations: dict[str, str] = {}
    pending: list[str] = []

    def add_dataset(uid: str) -> None:
        if uid in datasets:
            return
        row = conn.execute(
            f"SELECT name FROM gb_dataset WHERE uid = ? AND status IN ({_LIVE_DATASETS})",
            (uid,),
        ).fetchone()
        if row is not None:
            datasets[uid] = str(row[0])
            pending.append(uid)

    def consumers(kind: str, uid: str) -> list[tuple[str, str]]:
        return [(str(found), str(op_type)) for found, op_type in conn.execute(
            "SELECT o.uid, o.op_type FROM gb_operation_io AS io JOIN gb_operation AS o "
            "ON o.uid = io.operation_uid WHERE io.item_kind = ? AND io.item_uid = ? "
            "AND io.direction = 'in' AND o.status = 'done' AND o.superseded_by IS NULL "
            "ORDER BY o.fid", (kind, uid))]

    def add_operation(uid: str, op_type: str) -> None:
        if uid in operations:
            return
        operations[uid] = op_type
        for (found,) in conn.execute(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' "
            "AND item_kind = 'dataset' ORDER BY fid", (uid,)
        ):
            add_dataset(str(found))

    for (found,) in conn.execute(
        "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' "
        "AND item_kind = 'dataset' ORDER BY fid", (record.operation_uid,)
    ):
        add_dataset(str(found))
    for (found,) in conn.execute("SELECT uid FROM gb_dataset WHERE input_uid = ? ORDER BY fid",
                                 (record.uid,)):
        add_dataset(str(found))
    for uid, op_type in consumers("input", record.uid):
        add_operation(uid, op_type)
    while pending:
        for uid, op_type in consumers("dataset", pending.pop(0)):
            add_operation(uid, op_type)
    figures: list[Dependent] = []
    if operations:
        marks = ", ".join("?" for _ in operations)
        figures = [Dependent(str(uid), str(key)) for uid, key in conn.execute(
            f"SELECT uid, key FROM gb_figure WHERE operation_uid IN ({marks}) ORDER BY fid",
            tuple(operations))]
    ordered = _by_fid(conn, "gb_dataset", datasets)
    return Dependents(
        datasets=tuple(Dependent(uid, datasets[uid]) for uid in ordered),
        operations=tuple(Dependent(uid, operations[uid])
                         for uid in _by_fid(conn, "gb_operation", operations)),
        figures=tuple(figures),
    )


def _by_fid(conn: sqlite3.Connection, table: str, uids: Mapping[str, str]) -> list[str]:
    """Los uid de ``uids`` por orden de registro (``fid``) en ``table``."""
    if not uids:
        return []
    marks = ", ".join("?" for _ in uids)
    return [str(row[0]) for row in conn.execute(
        f"SELECT uid FROM {table} WHERE uid IN ({marks}) ORDER BY fid", tuple(uids))]


# --- Registro -----------------------------------------------------------------------------------


def _current_state(conn: sqlite3.Connection, uid: str) -> tuple[str, str | None] | None:
    row = conn.execute("SELECT status, seen_sha256 FROM gb_input WHERE uid = ?",
                       (uid,)).fetchone()
    return None if row is None else (str(row[0]), row[1])


def _unchanged_since(conn: sqlite3.Connection, finding: InputFinding) -> bool:
    """Si la entrada sigue como estaba al comprobarla (nadie ha decidido nada mientras)."""
    return _current_state(conn, finding.input_uid) == (str(finding.before),
                                                       finding.previous_seen)


def _files_data(finding: InputFinding) -> list[dict[str, Any]]:
    return [{"ord": seen.ord, "size": seen.size, "mtime_ns": seen.mtime_ns,
             "last_change": seen.last_change} for seen in finding.observed]


def _record(conn: sqlite3.Connection, project: CheckProject, kind: EventKind,
            finding: InputFinding, message: str, data: Mapping[str, Any], at: str) -> None:
    record_event(conn, kind, message, session=project.session, at=at, entity_kind="input",
                 entity_uid=finding.input_uid, data=dict(data))


def record_findings(conn: sqlite3.Connection, project: CheckProject,
                    findings: Iterable[InputFinding]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Registra lo encontrado (véase el módulo, paso 4) en la transacción de escritura ``conn``
    de quien llama (no la confirma): la última comprobación de los ficheros de cada entrada
    hasheada y, si cambió de estado, el estado nuevo, el contenido visto y su evento. Lo que no
    se hasheó no se escribe. Devuelve los uid registrados y los que cambiaron de estado
    mientras se comprobaban (no se tocan)."""
    now = format_utc(project.clock.now())
    user = project.session.user_host
    written: list[str] = []
    stale: list[str] = []
    for finding in findings:
        if finding.verdict not in (Verdict.SAME, Verdict.CHANGED, Verdict.RESTORED):
            continue
        if not _unchanged_since(conn, finding):
            stale.append(finding.input_uid)
            continue
        conn.executemany(
            "UPDATE gb_input_file SET checked_size = ?, checked_mtime_ns = ?, "
            "checked_last_change = ?, checked_at = ? WHERE input_uid = ? AND ord = ?",
            [(seen.size, seen.mtime_ns, seen.last_change, now, finding.input_uid, seen.ord)
             for seen in finding.observed],
        )
        if finding.verdict is Verdict.CHANGED:
            if finding.before is InputStatus.CHANGED:
                conn.execute("UPDATE gb_input SET seen_sha256 = ?, modified_at = ? WHERE uid = ?",
                             (finding.content_sha256, now, finding.input_uid))
            else:
                conn.execute(
                    "UPDATE gb_input SET status = ?, seen_sha256 = ?, status_at = ?, "
                    "status_by = ?, status_reason = NULL, modified_at = ? WHERE uid = ?",
                    (str(InputStatus.CHANGED), finding.content_sha256, now, user, now,
                     finding.input_uid),
                )
            _record(conn, project, EventKind.INPUT_CHANGED, finding, finding.warning or "", {
                "name": finding.name,
                "from_status": str(finding.before),
                "content_sha256": finding.registered_sha256,
                "seen_sha256": finding.content_sha256,
                "previous_seen": finding.previous_seen,
                "source_date": finding.source_date,
                "files": _files_data(finding),
                "dependents": (finding.dependents or Dependents()).counts(),
            }, now)
        elif finding.verdict is Verdict.RESTORED:
            conn.execute(
                "UPDATE gb_input SET status = ?, seen_sha256 = NULL, status_at = ?, "
                "status_by = ?, status_reason = NULL, modified_at = ? WHERE uid = ?",
                (str(InputStatus.CURRENT), now, user, now, finding.input_uid),
            )
            _record(conn, project, EventKind.INPUT_RESTORED, finding,
                    f"Entrada «{finding.name}» vigente otra vez: su fuente vuelve a tener el "
                    "contenido registrado.", {
                        "name": finding.name,
                        "from_status": str(finding.before),
                        "content_sha256": finding.registered_sha256,
                        "previous_seen": finding.previous_seen,
                    }, now)
        written.append(finding.input_uid)
    return tuple(written), tuple(stale)


# --- Pasos --------------------------------------------------------------------------------------


def _selected(conn: sqlite3.Connection, project: CheckProject,
              inputs: Iterable[str | InputRecord] | None) -> list[InputRecord]:
    """Las entradas activas que se comprueban: todas, por orden de registro, o las pedidas
    (por uid, por nombre lógico o su registro), en su orden y sin repetir; las sustituidas y
    descartadas no se comprueban."""
    if inputs is None:
        keys: list[str] = [str(row[0]) for row in conn.execute(
            f"SELECT uid FROM gb_input WHERE status IN ({_ACTIVE}) ORDER BY fid")]
    else:
        if isinstance(inputs, str | InputRecord) or not isinstance(inputs, Iterable):
            raise TypeError(f"las entradas que se comprueban son una lista (o None: todas), no "
                            f"{inputs!r}")
        keys = []
        for item in inputs:
            if isinstance(item, InputRecord):
                keys.append(item.uid)
            elif isinstance(item, str):
                keys.append(item)
            else:
                raise TypeError(f"una entrada se indica por su uid, su nombre o su registro, no "
                                f"{item!r}")
    found: dict[str, InputRecord] = {}
    for key in keys:
        record = registry.get(conn, key)
        if record is None:
            raise ProvenanceError("core.input_unknown", input=key, project=project.name)
        if record.active:
            found.setdefault(record.uid, record)
    return list(found.values())


def _summary(findings: Sequence[InputFinding]) -> str:
    changed = sum(1 for item in findings if item.status is InputStatus.CHANGED)
    unreachable = sum(1 for item in findings if item.verdict is Verdict.UNREACHABLE)
    unreadable = sum(1 for item in findings if item.verdict is Verdict.UNREADABLE)
    return (f"Entradas comprobadas: {len(findings)}; cambiadas sin decidir: {changed}; no "
            f"localizables: {unreachable}; sin leer: {unreadable}.")


def check_steps(
    project: CheckProject,
    inputs: Iterable[str | InputRecord] | None = None,
    *,
    mode: CheckMode | str = CheckMode.QUICK,
    budget_s: float = STEP_BUDGET_S,
) -> Iterator[Progress]:
    """Comprueba las fuentes de las entradas activas ``inputs`` (por uid, nombre o registro;
    ``None``: todas) en el modo ``mode`` (:class:`CheckMode`), por pasos de ``budget_s`` como
    mucho (RF-008-09, RF-008-10, RF-008-12, RF-008-13; véase el módulo). Cada paso es un
    :class:`~geoblender.core.project.model.Progress`; el último lleva el
    :class:`CheckOutcome` en ``result``. Cerrar el generador a medias no registra nada.
    ``ProvenanceError`` (``core.input_unknown``) si se pide una entrada que no está."""
    chosen = CheckMode(mode)
    budget = _budget(budget_s)
    with project.read() as conn:
        records = _selected(conn, project, inputs)
        tables = (table_changes(conn) if any(
            item.anchor is FileAnchor.PROJECT_TABLE for record in records for item in record.files
        ) else None)
    total = len(records)
    yield Progress(PHASES[0], 0, total, "Comprobando las entradas…")
    pacer = _Pacer(budget)
    probes: list[Probe] = []
    for index, record in enumerate(records, start=1):
        probes.append(probe_input(project, record, mode=chosen, tables=tables))
        if pacer.lap() and index < total:
            yield Progress(PHASES[0], index, total, "Comprobando las entradas…")
            pacer.restart()
    to_hash = sum(1 for probe in probes if probe.needs_hash)
    findings: list[InputFinding] = []
    hashed = 0
    for probe in probes:
        if not probe.needs_hash:
            findings.append(assess(probe))
            continue
        content, error, gone = yield from _content_steps(probe, pacer, hashed, to_hash)
        hashed += 1
        if gone:  # se borró mientras se leía: no localizable
            probe = replace(probe, missing=_shown_name(probe.record.files[0]))
        findings.append(assess(probe, content, error=None if gone else error))
        if pacer.lap() and hashed < to_hash:
            yield Progress(PHASES[1], hashed, to_hash, "Comprobando el contenido de las "
                                                        "entradas…")
            pacer.restart()
    yield Progress(PHASES[2], total, total, "Registrando la comprobación de las entradas…")
    stale: tuple[str, ...] = ()
    current: list[InputFinding] = []
    with project.read() as conn:
        for record, item in zip(records, findings, strict=True):
            if not _unchanged_since(conn, item):
                stale += (item.input_uid,)
                continue
            if item.status is InputStatus.CHANGED:
                item = replace(item, dependents=dependents(conn, record))
            current.append(item)
    findings = current
    recorded = bool(project.writable)
    if recorded and any(item.verdict in (Verdict.SAME, Verdict.CHANGED, Verdict.RESTORED)
                        for item in findings):
        while True:
            attempt = project.try_write(lambda conn: record_findings(conn, project, findings))
            if attempt.state is WriteState.DONE:
                break
            yield Progress(PHASES[2], total, total, attempt.message)
        _written, late = attempt.value
        if late:
            stale += late
            findings = [item for item in findings if item.input_uid not in late]
    outcome = CheckOutcome(chosen, tuple(findings), recorded, stale)
    yield Progress(PHASES[2], total, total, _summary(outcome.findings), result=outcome)
