# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobaciones de apertura de un proyecto (spec 008; RF-008-09, RF-008-19, RF-008-21,
RF-008-22, RF-008-24, RF-008-57, RF-008-58, RF-008-60, RF-008-62; ADR-0025 §6; plan 008 §5.3.1,
§5.4.5 y §5.4.6).

Justo después de abrir un proyecto (RNF-002-02 no cambia: el proyecto ya es usable), un
temporizador de ``bl`` avanza :func:`open_check_steps` paso a paso; cada paso de los seis
primeros (:func:`survey_steps`) no pasa de ``budget_s`` (20 ms; el trabajo de cada uno se planea
para la mitad), y cada uno da su progreso («Comprobando el proyecto… 42 %»), que no retrocede:

1. **foto** (``foto``): la hora de inicio (lo escrito después no se aparta como resto), lo
   registrado —las operaciones «en curso», las entradas activas con sus ficheros, los originales
   guardados y, por páginas de su ``fid``, los datos seguidos (cada página con el estado de sus
   tablas en la misma lectura)— y el listado de ``rasters/``, ``meshes/`` y ``originals/`` por
   ``os.scandir`` (tamaño y fecha sin un ``stat`` por fichero; cada carpeta se lee de una vez y
   no queda abierta entre pasos);
2. **interrumpidas** (``interrumpidas``): las operaciones «en curso» de otra sesión
   (RF-008-19). En escritura el cerrojo es de esta sesión, así que lo son todas las de las
   demás; en solo lectura, no las de la sesión que tiene el cerrojo, que pueden estar
   ejecutándose en ella;
3. **entradas** (``entradas``): el prefiltro de las entradas activas —vigentes, cambiadas sin
   decidir y las que mantienen la copia— por el tamaño y la fecha de sus ficheros
   (``core.inputs.check.probe_input``; RF-008-09, RF-008-12, RF-008-13);
4. **datos** (``datos``): el prefiltro de los datos seguidos y de los originales **contra la
   foto** (RF-008-21, RF-008-57; RF-008-53): una tabla, con el estado que se leyó con su
   registro; un fichero, con el listado (sin él, con su ``stat``); lo que reclama una operación
   en curso de esta sesión no se mira. Lo que salta o falta se vuelve a leer de la base: si su
   registro cambió desde la foto (lo escribió esta sesión, o Geoblender, después), no se toma
   por una edición externa ni por una falta y queda para la próxima (``stale``; I-5);
5. **restos** (``restos``): los restos de operaciones interrumpidas, que en escritura se
   apartan a ``orphans/``, los ficheros ajenos y las capas sin registrar
   (``core.datasets.orphan_steps`` con la hora de la foto; RF-008-22, RF-008-62);
6. **versiones** (``versiones``): los tipos de operación cuyo algoritmo declara el Geoblender
   instalado con una versión mayor que la de sus operaciones vigentes, con lo que escribieron
   («Geoblender 0.3.0 cambia el algoritmo de gis.resample (1.0 → 1.1): 3 resultados
   obsoletos», RF-008-24), si la caché de la obsolescencia aún no lo sabe; y los parámetros
   cuya definición cambió (RF-008-60).

Estos pasos **no leen el contenido de nada y no escriben nada en la base**: lo que hay que
hashear (las entradas, datos y originales que saltaron en el prefiltro) queda en su resultado
(:class:`OpenCheckOutcome`) para el paso 7. Lo único que cambia en el disco es lo que pide
RF-008-22: en escritura, los restos se apartan en el paso 5 (su evento, en la transacción
final). Después:

7. **contenido** (``contenido``): la **cola de hashes** de lo que saltó y de lo que la puerta
   pidió hashear (``CheckState.requests``): lo del proyecto (datos, originales, fuentes dentro
   del proyecto) y las fuentes externas pequeñas, en el hilo por trozos (``plan_hash``); las
   fuentes externas grandes, en los trabajos de hash que pone ``bl`` (:class:`HashJobs`,
   ``core_content_hash`` de la 004, T47: ``core`` no importa ``jobs``), con la comprobación
   esperando paso a paso; sin trabajos, también en el hilo. Cerrar la comprobación cancela los
   trabajos pendientes;
8. **registro** (``registro``): **todas las escrituras en una sola transacción final** con
   ``Project.try_write`` —las operaciones interrumpidas, las entradas cambiadas o que vuelven,
   las ediciones externas, lo que falta, lo dañado, los originales, los eventos de los restos,
   de lo ajeno, de las definiciones y de los algoritmos, «revisar» y la **obsolescencia
   completa** de la caché (``refresh_all``, que corrige una caché alterada)—; si otro programa
   está leyendo (QGIS), se reintenta en el paso siguiente sin perder nada (I-7). Lo que cambió
   entre el hash y el registro no se registra: queda para la próxima (I-5).

En **solo lectura** todo se detecta igual (también lo que hay que hashear) y no se escribe ni
se mueve nada: el resultado es el informe de la sesión, que se vuelve a detectar y se registra
al abrir después en escritura. Mientras dura, la comprobación deja en ``CheckState``
(``pending``) como pendiente lo que aún no ha comprobado, y la puerta espera por ello
(RF-008-58). :func:`hash_requests_steps` hace los pasos 7 y 8 de lo que la puerta pide hashear
después.

Python puro (ADR-0004); ``core.provenance`` lo reexporta al usarlo.
"""

from __future__ import annotations

import ntpath
import os
import sqlite3
import stat
import time
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from ..content.encoder import ContentDigest
from ..content.readers import JOB, READERS, plan_hash
from ..datasets import registry as dataset_registry
from ..datasets.external import (
    MAX_REASON_CHARS,
    SURVEYED_STATUSES,
    DatasetFinding,
    DatasetProbe,
    DatasetVerdict,
    OriginalFinding,
    OriginalVerdict,
    Signal,
    _Check,
    _hash_dataset,
    _hash_original,
    _Original,
    _OriginalCheck,
    _record_all,
    checkable,
    probe_dataset,
)
from ..datasets.external import assess as assess_dataset
from ..datasets.model import LIVE_STATUSES, RECORD_COLUMNS, DatasetRecord, DatasetStatus, Store
from ..datasets.orphans import DATA_FOLDERS, OrphanOutcome, orphan_steps, record_orphans
from ..datasets.orphans import PHASES as ORPHAN_PHASES
from ..datasets.tracking import TableState, table_states
from ..errors import GeoblenderError
from ..i18n import LANGUAGES
from ..inputs import registry as input_registry
from ..inputs.check import (
    CheckMode,
    InputFinding,
    Probe,
    _content_steps,
    _shown_name,
    dependents,
    probe_input,
    record_findings,
    table_changes,
)
from ..inputs.check import Verdict as InputVerdict
from ..inputs.check import assess as assess_input
from ..inputs.model import (
    ACTIVE_STATUSES,
    FILE_COLUMNS,
    INPUT_COLUMNS,
    InputFileRecord,
    InputRecord,
    InputStatus,
)
from ..params import DEFINITIONS, DefinitionChange, ParamDef, ParameterStore
from ..paths import ABSOLUTE_PATH
from ..project.events import EventKind, record_event
from ..project.lock import decode_lock, lock_path
from ..project.model import Progress
from ..project.session import WriteState
from ..timeutil import format_utc
from .contract import parse_version
from .gate import CheckState, PendingItem
from .graph import installed_versions
from .messages import render
from .operations import ItemKind, OperationStatus, claimed_paths, interrupt_orphaned
from .stale import CacheUpdate, refresh_all

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo
    from ..timeutil import Clock
    from ..userdata import UserData

SURVEY_STEPS: tuple[str, ...] = ("foto", "interrumpidas", "entradas", "datos", "restos",
                                 "versiones")
"""Los pasos 1 a 6 (:func:`survey_steps`), en su orden: no leen el contenido de nada ni escriben
en la base."""
HASH_STEP = "contenido"
"""El paso 7: la cola de hashes."""
RECORD_STEP = "registro"
"""El paso 8: la transacción final (o, en solo lectura, el informe)."""
OPEN_CHECK_STEPS: tuple[str, ...] = (*SURVEY_STEPS, HASH_STEP, RECORD_STEP)
"""Los pasos de la comprobación de apertura, en su orden (la fase de cada ``Progress``)."""
REQUEST_STEPS: tuple[str, ...] = (HASH_STEP, RECORD_STEP)
"""Los pasos de :func:`hash_requests_steps`."""
PROGRESS_TOTAL = 1000
"""El total del progreso (``Progress.total``): lo hecho va en milésimas de toda la
comprobación, cada paso una parte igual."""
STEP_BUDGET_S = 0.020
"""Lo que puede durar un paso (plan 008 §5.4.6: ≤ 20 ms por tic)."""
WORK_FRACTION = 0.5
"""La parte del presupuesto de un paso que se planea para el trabajo."""
PAGE_ROWS = 200
"""Los datos que se leen de una vez en la foto (una página por su ``fid``)."""
VALIDATE_ROWS = 500
"""Los datos cuyo registro se vuelve a leer de una vez antes de darlos por cambiados."""
PROVENANCE_SCHEMA = 2
"""El esquema desde el que el proyecto tiene la procedencia: uno anterior no se comprueba."""
SNAPSHOT_FIELDS: tuple[str, ...] = (
    "status", "content_sha256", "operation_uid", "tracked_size", "tracked_mtime_ns",
    "tracked_last_change", "tracked_schema_sha256",
)
"""Lo que, si cambió desde la foto, dice que Geoblender registró el dato después."""

_PHOTO_PAGES = 0.8  # la parte de la foto que son las páginas de los datos (el resto, el listado)
_SURVEYED = ", ".join(f"'{status}'" for status in SURVEYED_STATUSES)
_ACTIVE = ", ".join(f"'{status}'" for status in ACTIVE_STATUSES)
_LIVE = ", ".join(f"'{status}'" for status in LIVE_STATUSES)
_RUNNING_SQL = (
    "SELECT uid, op_type, session_uid, user_host, started_at, job_uid FROM gb_operation "
    "WHERE status = ? AND session_uid <> ? ORDER BY fid"
)
_INPUTS_SQL = (
    f"SELECT {', '.join(INPUT_COLUMNS)} FROM gb_input WHERE status IN ({_ACTIVE}) ORDER BY fid"
)
_FILES_SQL = (
    f"SELECT input_uid, {', '.join(FILE_COLUMNS)} FROM gb_input_file WHERE input_uid IN "
    f"(SELECT uid FROM gb_input WHERE status IN ({_ACTIVE})) ORDER BY input_uid, ord"
)
_ORIGINALS_SQL = (
    "SELECT f.input_uid, i.name, f.ord, f.original_path, f.original_sha256, f.original_size, "
    "f.original_mtime_ns FROM gb_input_file AS f JOIN gb_input AS i ON i.uid = f.input_uid "
    "WHERE f.original_path IS NOT NULL ORDER BY i.fid, f.ord"
)
_LAST_FID_SQL = "SELECT MAX(fid) FROM gb_dataset"  # para el progreso (contar los datos, 4 ms)
_PAGE_SQL = (
    f"SELECT fid, {', '.join(RECORD_COLUMNS)} FROM gb_dataset WHERE tracked = 1 AND status IN "
    f"({_SURVEYED}) AND fid > ? ORDER BY fid LIMIT ?"
)
_GROUPS_SQL = (
    "SELECT op_type, op_version, COUNT(*) FROM gb_operation WHERE status = 'done' "
    "AND superseded_by IS NULL GROUP BY op_type, op_version"
)
# De las operaciones vigentes de un tipo y una versión, en una pasada: cuántas tienen ya en la
# caché la causa de su algoritmo y cuántos datos vivos escribieron (por las salidas de cada una,
# con el índice de gb_operation_io: recorrer gb_operation_io o gb_dataset enteros eran 10–12 ms
# con el volumen de D-13). Un dato vivo tiene una sola operación (la de su contenido), así que la
# suma no repite ninguno.
_ALGORITHM_SQL = (
    "SELECT COUNT(*), "
    "TOTAL((SELECT 1 FROM gb_stale AS s WHERE s.item_kind = 'operation' AND s.item_uid = o.uid "
    "AND s.cause_kind = 'algorithm' AND s.subject_uid = o.op_type)), "
    "TOTAL((SELECT COUNT(DISTINCT io.item_uid) FROM gb_operation_io AS io "
    "CROSS JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = o.uid AND io.direction = 'out' AND io.item_kind = 'dataset' "
    f"AND d.operation_uid = o.uid AND d.status IN ({_LIVE}))) "
    "FROM gb_operation AS o WHERE o.status = 'done' AND o.superseded_by IS NULL "
    "AND o.op_type = ? AND o.op_version = ?"
)
_RESULTS: Mapping[str, tuple[str, str]] = MappingProxyType({
    "es": ("resultado obsoleto", "resultados obsoletos"),
    "en": ("stale result", "stale results"),
})


class OpenCheckProject(Protocol):
    """Lo que se usa del proyecto (``core.project.Project``): su identidad, su raíz, su base,
    los datos de usuario (las fuentes, RF-002-19), el reloj, la sesión, si se puede escribir,
    leer y escribir con reintento (y, si los tiene, ``schema_version`` y ``header_only``)."""

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


# --- Lo que declara el Geoblender que abre el proyecto ------------------------------------------


@dataclass(frozen=True, eq=True)
class Registries:
    """Lo que declara el Geoblender que abre el proyecto (sus módulos activos): la versión
    «M.m» del algoritmo de cada tipo de operación (``versions``) y las definiciones de los
    parámetros por clave (``definitions``). Es una copia: lo que se registre después no cambia
    la comprobación en curso. :class:`TypeError` o :class:`ValueError` si una versión no es
    «M.m» o una definición no es un ``ParamDef`` con su clave."""

    versions: Mapping[str, str]
    definitions: Mapping[str, ParamDef]

    def __post_init__(self) -> None:
        if not isinstance(self.versions, Mapping):
            raise TypeError(f"las versiones son un diccionario tipo → «M.m», no {self.versions!r}")
        versions: dict[str, str] = {}
        for op_type, version in self.versions.items():
            if not isinstance(op_type, str) or not isinstance(version, str):
                raise TypeError(f"versión no válida: {op_type!r} → {version!r}")
            parse_version(version)
            versions[op_type] = version
        if not isinstance(self.definitions, Mapping):
            raise TypeError(f"las definiciones son un diccionario clave → ParamDef, no "
                            f"{self.definitions!r}")
        definitions: dict[str, ParamDef] = {}
        for key, defn in self.definitions.items():
            if not isinstance(defn, ParamDef):
                raise TypeError(f"la definición de «{key}» no es un ParamDef: {defn!r}")
            if key != defn.key:
                raise ValueError(f"la definición de «{defn.key}» está con la clave «{key}»")
            definitions[key] = defn
        object.__setattr__(self, "versions", MappingProxyType(versions))
        object.__setattr__(self, "definitions", MappingProxyType(definitions))

    __hash__ = None  # type: ignore[assignment]

    @classmethod
    def installed(cls) -> Registries:
        """Lo registrado ahora (``core.provenance.OPERATIONS`` y ``core.params.DEFINITIONS``)."""
        return cls(installed_versions(), DEFINITIONS)


# --- Lo que se encuentra ------------------------------------------------------------------------


def _language(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    return language


@dataclass(frozen=True)
class InterruptedOperation:
    """Una operación «en curso» de una sesión que ya no tiene el cerrojo (RF-008-19): queda
    «interrumpida» en la transacción final (``interrupt_orphaned``)."""

    uid: str
    op_type: str
    session_uid: str
    user_host: str
    started_at: str
    job_uid: str | None = None

    def text(self, language: str = "es") -> str:
        """El aviso en ``language`` (el que registra la operación interrumpida)."""
        return render("core.operation_interrupted", language=_language(language),
                      op_type=self.op_type, user_host=self.user_host)


@dataclass(frozen=True)
class OriginalProbe:
    """Un original de ``originals/`` (el fichero ``ord`` de la entrada ``input_uid``,
    ``name``) cuyo tamaño o fecha no son los guardados: su huella se calcula en el paso 7.
    ``seen``, el tamaño y la fecha que se vieron (``None`` si falta)."""

    input_uid: str
    name: str
    ord: int
    path: str
    sha256: str
    size: int
    mtime_ns: int
    seen: tuple[int, int] | None

    @property
    def file(self) -> str:
        """El nombre del fichero."""
        return PurePosixPath(self.path).name

    @property
    def needs_hash(self) -> bool:
        """Si hay que calcular su huella: está, con otro tamaño u otra fecha."""
        return self.seen is not None and self.seen != (self.size, self.mtime_ns)


@dataclass(frozen=True)
class AlgorithmChange:
    """Un tipo de operación cuyo algoritmo declara el Geoblender instalado (``installed``,
    ``geoblender_version``) con una versión mayor que la de sus ``operations`` operaciones
    vigentes (``registered``), con los datos vivos que escribieron (``results``; RF-008-24)."""

    op_type: str
    registered: str
    installed: str
    geoblender_version: str
    operations: int
    results: int

    def text(self, language: str = "es") -> str:
        """«Geoblender 0.3.0 cambia el algoritmo de gis.resample (1.0 → 1.1): 3 resultados
        obsoletos», en ``language``."""
        chosen = _language(language)
        singular, plural = _RESULTS[chosen]
        return render("core.algorithm_changed", language=chosen,
                      version=self.geoblender_version, op_type=self.op_type,
                      registered=self.registered, installed=self.installed,
                      results=f"{self.results} {singular if self.results == 1 else plural}")


@dataclass(frozen=True)
class OpenCheckOutcome:
    """El resultado de la comprobación de apertura: el de los pasos 1 a 6
    (:func:`survey_steps`) y, al final de :func:`open_check_steps`, el de los ocho, que es
    también el informe de la sesión en solo lectura:

    - ``writing``: si se pudo escribir (``write`` y el proyecto en escritura al empezar);
      ``started_at_ns``, la hora de la foto (``time.time_ns()``);
    - ``interrupted``: las operaciones «en curso» de otras sesiones (RF-008-19);
    - ``inputs``: lo concluido de las entradas (sin cambios, no localizables y, tras el paso 7,
      lo hasheado: el mismo contenido, cambiadas —con lo que depende de ellas— o que vuelven a
      su contenido registrado); ``input_probes``, las que saltaron en el prefiltro y esperan su
      hash (vacío al terminar);
    - ``datasets``: lo concluido de los datos (lo que falta, lo importado sin su protección, lo
      que no se pudo mirar y, tras el paso 7, las ediciones externas —con su operación si se
      registró—, lo dañado y lo que vuelve); ``dataset_probes``, los que saltaron y esperan su
      hash (vacío al terminar); ``checked_datasets``, los uid de los comprobados (tampoco lo
      reclamado por una operación en curso de esta sesión); ``stale``, lo que cambió mientras
      se comprobaba (los uid de los datos que Geoblender registró después de la foto y de lo
      que cambió entre su hash y su registro, y las rutas de esos originales): no se toma por
      cambiado y se comprueba la próxima vez;
    - ``originals``: los originales que faltan o tienen otra huella; ``original_probes``, los
      que saltaron y esperan su huella (vacío al terminar);
    - ``orphans``: los restos (apartados en escritura), lo ajeno y las capas sin registrar;
    - ``algorithms``: los tipos con un algoritmo mayor (RF-008-24); ``definitions``, los
      parámetros cuya marca «revisar» cambia (RF-008-60; las que se marcaron, si se registró);
    - ``recorded``: si lo encontrado quedó registrado en el proyecto (la transacción final del
      paso 8; ``False`` en solo lectura y en los pasos 1 a 6); ``cache``, lo que hizo la
      obsolescencia completa con la caché (``None`` si no se registró).
    """

    writing: bool
    started_at_ns: int
    interrupted: tuple[InterruptedOperation, ...] = ()
    inputs: tuple[InputFinding, ...] = ()
    input_probes: tuple[Probe, ...] = ()
    datasets: tuple[DatasetFinding, ...] = ()
    dataset_probes: tuple[DatasetProbe, ...] = ()
    checked_datasets: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()
    originals: tuple[OriginalFinding, ...] = ()
    original_probes: tuple[OriginalProbe, ...] = ()
    orphans: OrphanOutcome = field(default_factory=lambda: OrphanOutcome((), None, False))
    algorithms: tuple[AlgorithmChange, ...] = ()
    definitions: tuple[DefinitionChange, ...] = ()
    recorded: bool = False
    cache: CacheUpdate | None = None

    @property
    def checked_inputs(self) -> tuple[str, ...]:
        """Los uid de las entradas comprobadas."""
        return tuple(item.input_uid for item in self.inputs)

    def texts(self, language: str = "es") -> tuple[str, ...]:
        """Los avisos en ``language``, en orden: las interrumpidas, las entradas que quedan
        cambiadas (el aviso de la spec §8), no localizables o que no se pueden leer, los datos
        y los originales editados fuera, que faltan, dañados o con otra huella, los restos y lo
        ajeno, los algoritmos y las definiciones (el cambio de una definición, en español)."""
        chosen = _language(language)
        found = [item.text(chosen) for item in self.interrupted]
        found += [text for item in self.inputs
                  if (text := (item.render(chosen) if item.verdict is InputVerdict.CHANGED
                               else item.render_notice(chosen)))]
        found += [text for item in self.datasets if (text := item.text(chosen))]
        found += [text for item in self.originals if (text := item.text(chosen))]
        found += self.orphans.texts(chosen)
        found += [item.text(chosen) for item in self.algorithms]
        found += [item.text for item in self.definitions if item.review is not None]
        return tuple(found)

    @property
    def warnings(self) -> tuple[str, ...]:
        """Los avisos en español."""
        return self.texts("es")


# --- Trabajos de hash (los pone ``bl``) ----------------------------------------------------------


@dataclass(frozen=True)
class HashRequest:
    """Lo que necesita un trabajo de hash (``core_content_hash`` de la 004, T47) para la fuente
    externa de una entrada: la entrada (``input_uid``, ``name``), su lector registrado con su
    versión (``reader``), su tipo (``kind``), sus declaraciones y sus ajustes, sus ficheros por
    el papel de cada uno para su lector (``files``: la ruta donde está; el trabajo la recibe
    por la línea de órdenes, nunca en ``request.json``), su normalizador y su tamaño en bytes
    (``size``). Nada del proyecto llega a un trabajo (plan §5.3.3)."""

    input_uid: str
    name: str
    reader: str
    kind: str
    declarations: Mapping[str, Any]
    settings: Mapping[str, Any]
    files: Mapping[str, Path]
    normalizer: str
    size: int

    def __post_init__(self) -> None:
        for name in ("declarations", "settings", "files"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(frozen=True)
class HashResult:
    """Cómo terminó un trabajo de hash: el hash de la fuente (``digest``), por qué no se pudo
    leer (``error``; también si la fuente cambió mientras se copiaba) o que ya no está
    (``gone``): solo uno. :class:`TypeError` o :class:`ValueError` si no."""

    digest: ContentDigest | None = None
    error: str | None = None
    gone: bool = False

    def __post_init__(self) -> None:
        if self.digest is not None and not isinstance(self.digest, ContentDigest):
            raise TypeError(f"el hash de un trabajo es un ContentDigest, no {self.digest!r}")
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError(f"el error de un trabajo es un texto, no {self.error!r}")
        if not isinstance(self.gone, bool):
            raise TypeError(f"«gone» es verdadero o falso, no {self.gone!r}")
        if (self.digest is not None) + (self.error is not None) + self.gone != 1:
            raise ValueError("un trabajo de hash termina con su hash, con un error o sin la "
                             "fuente: solo uno")


class HashJobs(Protocol):
    """Los trabajos de hash de las fuentes externas grandes (``core_content_hash`` de la 004,
    T47), que pone ``bl`` (``core`` no importa ``jobs``, ADR-0004): ``submit`` lanza uno y
    devuelve su resguardo (``None`` si ahora no se puede: se hashea en el hilo); ``poll`` dice
    cómo terminó (``None`` mientras sigue); ``cancel`` lo cancela (al cerrar la comprobación a
    medias)."""

    def submit(self, request: HashRequest) -> object | None: ...

    def poll(self, ticket: object) -> HashResult | None: ...

    def cancel(self, ticket: object) -> None: ...


# --- Ayudas -------------------------------------------------------------------------------------


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


class _Meter:
    """El progreso de toda la comprobación (``steps``, sus pasos), en milésimas: cada paso, una
    parte igual; nunca retrocede."""

    def __init__(self, steps: tuple[str, ...], label: str = "Comprobando el proyecto…") -> None:
        self.steps = steps
        self.label = label
        self.done = 0

    def at(self, step: int | str, fraction: float, result: object | None = None, *,
           message: str | None = None) -> Progress:
        """El progreso en el paso ``step`` (su orden o su nombre), con ``fraction`` de él
        hecho; ``message`` en lugar de «Comprobando el proyecto… n %»."""
        index = self.steps.index(step) if isinstance(step, str) else step
        share = min(max(fraction, 0.0), 1.0)
        value = int((index + share) * PROGRESS_TOTAL / len(self.steps))
        self.done = max(self.done, min(value, PROGRESS_TOTAL))
        shown = (message if message is not None
                 else f"{self.label} {self.done * 100 // PROGRESS_TOTAL} %")
        return Progress(self.steps[index], self.done, PROGRESS_TOTAL, shown, result)


def _key(rel: str) -> str:
    """La clave de una ruta relativa a la raíz para compararla (sin distinguir mayúsculas ni
    separadores en Windows)."""
    return os.path.normcase(os.path.normpath(rel))


def _stat(path: Path) -> tuple[int, int] | None:
    """El tamaño y la fecha de un fichero, o ``None`` si no está (o no es un fichero)."""
    try:
        found = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    if not stat.S_ISREG(found.st_mode):
        return None
    return found.st_size, found.st_mtime_ns


@dataclass(frozen=True)
class _Stored:
    """Un original guardado, como está registrado (``gb_input_file.original_*``)."""

    input_uid: str
    name: str
    ord: int
    path: str
    sha256: str
    size: int
    mtime_ns: int


@dataclass
class _Photo:
    """La foto del paso 1: la hora de inicio, lo registrado y el listado."""

    started_at_ns: int
    holder: str | None
    running: tuple[InterruptedOperation, ...]
    inputs: tuple[InputRecord, ...]
    contents: dict[str, str | None]
    input_names: dict[str, str]
    originals: tuple[_Stored, ...]
    last_fid: int
    datasets: list[DatasetRecord] = field(default_factory=list)
    tables: dict[str, TableState] = field(default_factory=dict)  # por uid de dato
    files: dict[str, tuple[int, int]] = field(default_factory=dict)
    listed: set[str] = field(default_factory=set)
    unlisted: list[str] = field(default_factory=list)

    def covers(self, key: str) -> bool:
        """Si el listado dice lo que hay en ``key`` (su carpeta de datos se listó y nada por
        encima de él se quedó sin leer): si no está en el listado, no está."""
        if key.split(os.sep, 1)[0] not in self.listed:
            return False
        return not any(key == folder or key.startswith(folder + os.sep)
                       for folder in self.unlisted)


@dataclass
class _Found:
    """Lo que se va encontrando entre pasos."""

    interrupted: tuple[InterruptedOperation, ...] = ()
    inputs: list[InputFinding] = field(default_factory=list)
    input_probes: list[Probe] = field(default_factory=list)
    datasets: list[DatasetFinding] = field(default_factory=list)
    dataset_probes: list[DatasetProbe] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    originals: list[OriginalFinding] = field(default_factory=list)
    original_probes: list[OriginalProbe] = field(default_factory=list)
    orphans: OrphanOutcome | None = None
    # lo que se vio del contenedor de cada dato que falta o está dañado (para registrarlo solo
    # si sigue así: I-5)
    bases: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _Survey:
    """Lo de los pasos 1 a 6: su resultado, la foto y lo encontrado."""

    outcome: OpenCheckOutcome
    photo: _Photo
    found: _Found


# --- Los pasos ----------------------------------------------------------------------------------


def _arguments(write: object, registries: object,
               budget_s: object) -> tuple[Registries, float]:
    if not isinstance(write, bool):
        raise TypeError(f"«write» es verdadero o falso, no {write!r}")
    if registries is None:
        registries = Registries.installed()
    elif not isinstance(registries, Registries):
        raise TypeError(f"lo que declara el Geoblender que abre el proyecto es un Registries, "
                        f"no {registries!r}")
    return registries, _budget(budget_s)


def _pending(value: object) -> CheckState | None:
    if value is not None and not isinstance(value, CheckState):
        raise TypeError(f"lo pendiente de la comprobación de apertura es un CheckState, no "
                        f"{value!r}")
    return value


def _jobs(value: object) -> HashJobs | None:
    if value is not None and not all(callable(getattr(value, name, None))
                                     for name in ("submit", "poll", "cancel")):
        raise TypeError(f"los trabajos de hash tienen «submit», «poll» y «cancel» (HashJobs), "
                        f"no {value!r}")
    return value  # type: ignore[return-value]


def _provenance(project: OpenCheckProject) -> bool:
    """Si el proyecto tiene la procedencia (esquema 2 o posterior, con su base)."""
    return not (getattr(project, "header_only", False)
                or getattr(project, "schema_version", PROVENANCE_SCHEMA) < PROVENANCE_SCHEMA)


def survey_steps(project: OpenCheckProject, registries: Registries | None = None, *,
                 write: bool, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Los pasos 1 a 6 de la comprobación de apertura de ``project`` (véase el módulo), por
    pasos de ``budget_s`` como mucho; cada uno es un ``core.project.model.Progress`` en la fase
    de su paso (:data:`SURVEY_STEPS`) y el último lleva el :class:`OpenCheckOutcome` en
    ``result``, con lo que hay que hashear. ``registries``: lo que declara el Geoblender que lo
    abre (por defecto, :meth:`Registries.installed`); ``write``: si se puede apartar los restos
    (con el proyecto en escritura). No lee el contenido de nada ni escribe nada en la base. Un
    proyecto sin la procedencia (esquema anterior al 2) no tiene nada que comprobar.
    :class:`TypeError` o :class:`ValueError` (al llamarla) con un argumento mal dado."""
    chosen, budget = _arguments(write, registries, budget_s)
    return _survey_only(project, chosen, write and bool(project.writable), budget)


def _survey_only(project: OpenCheckProject, registries: Registries, writing: bool,
                 budget: float) -> Iterator[Progress]:
    meter = _Meter(SURVEY_STEPS)
    if not _provenance(project):
        yield meter.at(len(SURVEY_STEPS) - 1, 1.0,
                       OpenCheckOutcome(writing=writing, started_at_ns=time.time_ns()))
        return
    survey = yield from _survey(project, registries, writing, budget, meter, None)
    yield meter.at(len(SURVEY_STEPS) - 1, 1.0, survey.outcome)


def open_check_steps(project: OpenCheckProject, registries: Registries | None = None, *,
                     write: bool, pending: CheckState | None = None,
                     jobs: HashJobs | None = None,
                     budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """La comprobación de apertura de ``project``, sus ocho pasos (véase el módulo): cada uno
    es un ``core.project.model.Progress`` en la fase de su paso (:data:`OPEN_CHECK_STEPS`) y el
    último lleva el :class:`OpenCheckOutcome` en ``result`` (en solo lectura, el informe).
    ``registries``: lo que declara el Geoblender que lo abre (por defecto,
    :meth:`Registries.installed`); ``write``: si se puede escribir (apartar los restos y la
    transacción final, con el proyecto en escritura); ``pending``: el ``CheckState`` del
    proyecto, que deja como pendiente lo que aún no se ha comprobado y cuyos hashes pedidos
    hace la cola; ``jobs``: los trabajos de hash de las fuentes externas grandes (sin ellos,
    en el hilo); ``budget_s``: lo que dura cada paso de los seis primeros y cada trozo de un
    hash. Cerrar el generador a medias cancela los trabajos y no registra nada. Un proyecto
    sin la procedencia (esquema anterior al 2) no tiene nada que comprobar.
    :class:`TypeError` o :class:`ValueError` (al llamarla) con un argumento mal dado; al
    registrar, los rechazos de lo que registra (p. ej. ``core.operation_unregistered`` sin
    ``core.external_edit`` registrado)."""
    chosen, budget = _arguments(write, registries, budget_s)
    return _open_check(project, chosen, write and bool(project.writable), budget,
                       _pending(pending), _jobs(jobs))


def _open_check(project: OpenCheckProject, registries: Registries, writing: bool,
                budget: float, pending: CheckState | None,
                jobs: HashJobs | None) -> Iterator[Progress]:
    meter = _Meter(OPEN_CHECK_STEPS)
    if pending is not None:
        pending.start()
    settlement = _Settlement(project, writing, jobs, pending, budget, meter)
    try:
        if not _provenance(project):
            outcome = OpenCheckOutcome(writing=writing, started_at_ns=time.time_ns())
        else:
            survey = yield from _survey(project, registries, writing, budget, meter, pending)
            settlement.add_survey(survey)
            settlement.add_requests()
            yield from settlement.hash_steps()
            outcome = yield from settlement.record_steps(survey, registries)
            settlement.release()
    finally:
        settlement.cancel()
        if pending is not None:
            pending.finish()
    yield meter.at(RECORD_STEP, 1.0, outcome)


def hash_requests_steps(project: OpenCheckProject, pending: CheckState, *,
                        jobs: HashJobs | None = None,
                        budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Los pasos 7 y 8 (:data:`REQUEST_STEPS`) para lo que la puerta pidió hashear fuera de la
    comprobación de apertura (``pending.requests``): la cola de hashes y una transacción
    final con lo encontrado (en solo lectura, solo el informe); después, lo pedido deja de
    esperarse (``CheckState.hashed``). Lo pedido que ya no hay que hashear solo se quita. El
    último paso lleva un :class:`OpenCheckOutcome` con lo de las entradas y los datos.
    :class:`TypeError` o :class:`ValueError` (al llamarla) con un argumento mal dado."""
    chosen = _pending(pending)
    if chosen is None:
        raise TypeError("lo pedido está en el CheckState del proyecto, no en None")
    return _requests(project, chosen, _jobs(jobs), _budget(budget_s))


def _requests(project: OpenCheckProject, pending: CheckState, jobs: HashJobs | None,
              budget: float) -> Iterator[Progress]:
    meter = _Meter(REQUEST_STEPS, "Comprobando el contenido…")
    settlement = _Settlement(project, bool(project.writable), jobs, pending, budget, meter)
    try:
        settlement.add_requests()
        yield from settlement.hash_steps()
        outcome = yield from settlement.record_steps(None, None)
        settlement.release()
    finally:
        settlement.cancel()
    yield meter.at(RECORD_STEP, 1.0, outcome)


def _survey(project: OpenCheckProject, registries: Registries, writing: bool, budget: float,
            meter: _Meter, pending: CheckState | None) -> Generator[Progress, None, _Survey]:
    """Los pasos 1 a 6; lo que se comprueba sin hash deja de estar pendiente en ``pending``."""
    pacer = _Pacer(budget)
    photo = _photo(project)
    yield meter.at(0, 0.0)
    pacer.restart()
    yield from _page_steps(project, photo, pacer, meter)
    yield from _list_steps(project, photo, pacer, meter)
    if pending is not None:
        pending.start(inputs=[record.uid for record in photo.inputs],
                      datasets=[record.uid for record in photo.datasets])
    yield meter.at(0, 1.0)
    found = _Found()
    found.interrupted = tuple(item for item in photo.running if item.session_uid != photo.holder)
    yield meter.at(1, 1.0)
    pacer.restart()
    yield from _input_steps(project, photo, found, pacer, meter)
    if pending is not None:
        pending.checked(inputs=[item.input_uid for item in found.inputs])
    yield from _dataset_steps(project, photo, found, pacer, meter)
    if pending is not None:
        # lo comprobado sin nada que registrar y lo que Geoblender registró después de la foto
        pending.checked(datasets=[*(uid for uid in found.checked if uid not in found.bases),
                                  *found.stale])
    for step in orphan_steps(project, write=writing, started_at=photo.started_at_ns,
                             budget_s=budget, record=False):
        if isinstance(step.result, OrphanOutcome):
            found.orphans = step.result
        else:
            yield meter.at(4, _orphan_fraction(step))
    yield meter.at(4, 1.0)
    pacer.restart()
    algorithms: list[AlgorithmChange] = []
    yield from _algorithm_steps(project, registries, algorithms, pacer, meter)
    definitions = tuple(ParameterStore(project).definition_changes(  # type: ignore[arg-type]
        registries.definitions))
    outcome = OpenCheckOutcome(
        writing=writing,
        started_at_ns=photo.started_at_ns,
        interrupted=found.interrupted,
        inputs=tuple(found.inputs),
        input_probes=tuple(found.input_probes),
        datasets=tuple(found.datasets),
        dataset_probes=tuple(found.dataset_probes),
        checked_datasets=tuple(found.checked),
        stale=tuple(found.stale),
        originals=tuple(found.originals),
        original_probes=tuple(found.original_probes),
        orphans=(found.orphans if found.orphans is not None
                 else OrphanOutcome((), None, False)),
        algorithms=tuple(algorithms),
        definitions=definitions,
    )
    return _Survey(outcome, photo, found)


# --- 1. Foto ------------------------------------------------------------------------------------


def _holder(project: OpenCheckProject) -> str | None:
    """La sesión que tiene el cerrojo del proyecto (una lectura del fichero, sin esperas), o
    ``None`` si no hay o no se puede leer."""
    try:
        return decode_lock(lock_path(Path(project.root)).read_bytes()).session_uid
    except (OSError, ValueError):
        return None


def _photo(project: OpenCheckProject) -> _Photo:
    """Lo pequeño de la foto, en una lectura: la hora de inicio, las operaciones en curso de
    otras sesiones, las entradas activas con sus ficheros, los nombres de las entradas, los
    originales guardados y hasta qué ``fid`` hay datos (para el progreso); en solo lectura,
    quién tiene el cerrojo."""
    started = time.time_ns()
    session_uid = project.session.session_uid
    holder = None if project.writable else _holder(project)
    with project.read() as conn:
        running = tuple(
            InterruptedOperation(str(uid), str(op_type), str(session), str(user_host),
                                 str(started_at), None if job is None else str(job))
            for uid, op_type, session, user_host, started_at, job in conn.execute(
                _RUNNING_SQL, (str(OperationStatus.RUNNING), session_uid))
        )
        files: dict[str, list[InputFileRecord]] = {}
        for row in conn.execute(_FILES_SQL):
            files.setdefault(str(row[0]), []).append(InputFileRecord.from_row(row[1:]))
        inputs = tuple(InputRecord.from_row(row, files.get(str(row[0]), ()))
                       for row in conn.execute(_INPUTS_SQL).fetchall())
        contents = table_changes(conn)
        names = {str(uid): str(name)
                 for uid, name in conn.execute("SELECT uid, name FROM gb_input")}
        originals = tuple(
            _Stored(str(uid), str(name), int(ord_), str(path), str(sha), int(size), int(ns))
            for uid, name, ord_, path, sha, size, ns in conn.execute(_ORIGINALS_SQL)
        )
        last_fid = int(conn.execute(_LAST_FID_SQL).fetchone()[0] or 0)
    return _Photo(started, holder, running, inputs, contents, names, originals, last_fid)


def _page_steps(project: OpenCheckProject, photo: _Photo, pacer: _Pacer,
                meter: _Meter) -> Iterator[Progress]:
    """Los datos seguidos de la foto, por páginas de su ``fid``: en cada paso, una lectura con
    las páginas que caben y el estado de sus tablas (el que se compara con su registro)."""
    last = 0
    finished = False
    while not finished:
        with project.read() as conn:
            gpkg: list[DatasetRecord] = []
            while True:
                rows = conn.execute(_PAGE_SQL, (last, PAGE_ROWS)).fetchall()
                for row in rows:
                    record = DatasetRecord.from_row(row[1:])
                    photo.datasets.append(record)
                    if record.store is Store.GPKG:
                        gpkg.append(record)
                if rows:
                    last = int(rows[-1][0])
                if len(rows) < PAGE_ROWS:
                    finished = True
                    break
                if pacer.lap():
                    break
            if gpkg:
                states = table_states(conn, sorted({record.locator for record in gpkg}))
                for record in gpkg:
                    photo.tables[record.uid] = states[record.locator]
        if not finished:
            # (lo registrado después de empezar tiene un fid mayor: el progreso no pasa de ahí)
            yield meter.at(0, _PHOTO_PAGES * min(last / max(photo.last_fid, 1), 1.0))
            pacer.restart()


def _folder(path: Path) -> bool | None:
    """Si ``path`` es una carpeta que se puede listar (``None`` si no está: no hay nada)."""
    try:
        found = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        return False
    return stat.S_ISDIR(found.st_mode) and not path.is_junction()


def _list_steps(project: OpenCheckProject, photo: _Photo, pacer: _Pacer,
                meter: _Meter) -> Iterator[Progress]:
    """El listado de las carpetas de datos (``os.scandir``): cada carpeta se lee de una vez y
    se cierra, y lo leído se recorre entre pasos. Lo que no se pudo leer (o es un enlace) se
    mira después con su ``stat``."""
    root = Path(project.root)
    stack: list[str] = []
    for folder in DATA_FOLDERS:
        state = _folder(root / folder)
        if state is None:
            photo.listed.add(_key(folder))
        elif state:
            photo.listed.add(_key(folder))
            stack.append(folder)
    stack.reverse()
    while stack:
        rel_dir = stack.pop()
        try:
            with os.scandir(root.joinpath(*rel_dir.split("/"))) as listing:
                entries = list(listing)
        except OSError:  # se cayó la red o no se puede leer: lo de dentro, con su stat
            photo.unlisted.append(_key(rel_dir))
            entries = []
        for entry in entries:
            rel = f"{rel_dir}/{entry.name}"
            try:
                if entry.is_symlink() or entry.is_junction():
                    photo.unlisted.append(_key(rel))
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(rel)
                elif entry.is_file(follow_symlinks=False):
                    info = entry.stat(follow_symlinks=False)
                    photo.files[_key(rel)] = (info.st_size, info.st_mtime_ns)
            except OSError:
                photo.unlisted.append(_key(rel))
            if pacer.lap():
                yield meter.at(0, _PHOTO_PAGES)
                pacer.restart()
        if stack and pacer.lap():
            yield meter.at(0, _PHOTO_PAGES)
            pacer.restart()


# --- 3. Entradas --------------------------------------------------------------------------------


def _input_steps(project: OpenCheckProject, photo: _Photo, found: _Found, pacer: _Pacer,
                 meter: _Meter) -> Iterator[Progress]:
    """El prefiltro de las entradas activas de la foto (también las cambiadas sin decidir y
    las que mantienen la copia): lo que salta queda para su hash."""
    total = len(photo.inputs)
    for index, record in enumerate(photo.inputs, start=1):
        probe = probe_input(project, record, mode=CheckMode.QUICK,  # type: ignore[arg-type]
                            tables=photo.contents)
        if probe.needs_hash:
            found.input_probes.append(probe)
        else:
            found.inputs.append(assess_input(probe))
        if pacer.lap() and index < total:
            yield meter.at(2, index / total)
            pacer.restart()
    yield meter.at(2, 1.0)
    pacer.restart()


# --- 4. Datos y originales ----------------------------------------------------------------------


def _claimed(project: OpenCheckProject) -> frozenset[str]:
    """Los ficheros que reclaman ahora las operaciones en curso de esta sesión."""
    return frozenset(os.path.normcase(os.path.normpath(path))
                     for path in claimed_paths(project))  # type: ignore[arg-type]


def _claimed_key(root: Path, record: DatasetRecord) -> str:
    """La clave del fichero de ``record`` para compararlo con lo reclamado."""
    return os.path.normcase(os.path.normpath(Path(root, *record.locator.split("/"))))


def _shown(text: str) -> str:
    """Un motivo sin rutas absolutas (solo el nombre de su fichero) y no muy largo."""
    shown = ABSOLUTE_PATH.sub(
        lambda match: ntpath.basename(match.group(0).rstrip("\\/")) or "…", text)
    return shown if len(shown) <= MAX_REASON_CHARS else shown[: MAX_REASON_CHARS - 1] + "…"


def _reason(error: BaseException) -> str:
    """Por qué no se pudo mirar (como :func:`_shown`)."""
    return _shown(str(error))


def _listed_probe(record: DatasetRecord, seen: tuple[int, int] | None) -> DatasetProbe:
    """El prefiltro de un fichero con lo que dice de él el listado (como ``probe_dataset``)."""
    if seen is None:
        return DatasetProbe(record, Signal.MISSING)
    moved = (record.status is DatasetStatus.MISSING
             or seen != (record.tracked_size, record.tracked_mtime_ns))
    return DatasetProbe(record, Signal.MOVED if moved else Signal.UNCHANGED, *seen)


def _snapshot(record: DatasetRecord) -> tuple[Any, ...]:
    """Lo que dice de ``record`` la foto (:data:`SNAPSHOT_FIELDS`, como en la base)."""
    return tuple(str(record.status) if name == "status" else getattr(record, name)
                 for name in SNAPSHOT_FIELDS)


def _dataset_steps(project: OpenCheckProject, photo: _Photo, found: _Found, pacer: _Pacer,
                   meter: _Meter) -> Iterator[Progress]:
    """El prefiltro de los datos y de los originales de la foto; lo que salta o falta se
    vuelve a leer de la base antes de darlo por cambiado."""
    root = Path(project.root)
    claimed = _claimed(project) if any(record.store is not Store.GPKG
                                       for record in photo.datasets) else frozenset()
    total = len(photo.datasets) + len(photo.originals)
    candidates: list[DatasetProbe] = []
    done = 0
    for record in photo.datasets:
        done += 1
        probe: DatasetProbe | None = None
        if record.store is Store.GPKG:
            probe = probe_dataset(project, record, {record.locator: photo.tables[record.uid]})
        elif _claimed_key(root, record) not in claimed:  # lo reclamado, ni se mira
            key = _key(record.locator)
            if photo.covers(key):
                probe = _listed_probe(record, photo.files.get(key))
            else:
                try:
                    probe = probe_dataset(project, record, {})
                except OSError as exc:
                    found.datasets.append(DatasetFinding(
                        record, DatasetVerdict.UNREADABLE, record.status,
                        input_name=_input_name(photo, record), reason=_reason(exc)))
                    found.checked.append(record.uid)
        if probe is not None:
            if probe.signal is Signal.UNCHANGED or (probe.signal is Signal.MISSING
                                                    and record.status is DatasetStatus.MISSING):
                # sin cambios, o lo que ya faltaba sigue faltando
                found.checked.append(record.uid)
            else:
                candidates.append(probe)
        if pacer.lap() and done < total:
            yield meter.at(3, 0.9 * done / total)
            pacer.restart()
    for item in photo.originals:
        done += 1
        key = _key(item.path)
        seen = (photo.files.get(key) if photo.covers(key)
                else _stat(Path(root, *item.path.split("/"))))
        if seen is None:
            found.originals.append(OriginalFinding(item.input_uid, item.name, item.ord,
                                                   item.path, OriginalVerdict.MISSING))
        elif seen != (item.size, item.mtime_ns):
            found.original_probes.append(OriginalProbe(item.input_uid, item.name, item.ord,
                                                       item.path, item.sha256, item.size,
                                                       item.mtime_ns, seen))
        if pacer.lap() and done < total:
            yield meter.at(3, 0.9 * done / total)
            pacer.restart()
    while candidates:
        chunk, candidates = candidates[:VALIDATE_ROWS], candidates[VALIDATE_ROWS:]
        with project.read() as conn:
            current = _snapshots(conn, [probe.record.uid for probe in chunk])
        for probe in chunk:
            record = probe.record
            if current.get(record.uid) != _snapshot(record):
                found.stale.append(record.uid)  # Geoblender lo registró después de la foto
            elif probe.signal is Signal.MOVED:
                found.dataset_probes.append(probe)
            else:
                finding = replace(assess_dataset(probe), input_name=_input_name(photo, record))
                found.datasets.append(finding)
                found.checked.append(record.uid)
                if finding.changed:  # falta o está dañado: se registra si sigue así
                    found.bases[record.uid] = probe.observed
        if candidates and pacer.lap():
            yield meter.at(3, 0.95)
            pacer.restart()
    yield meter.at(3, 1.0)
    pacer.restart()


def _input_name(photo: _Photo, record: DatasetRecord) -> str | None:
    if record.input_uid is None:
        return None
    return photo.input_names.get(record.input_uid, record.input_uid)


def _snapshots(conn: Any, uids: list[str]) -> dict[str, tuple[Any, ...]]:
    """Lo que dice ahora la base de los datos ``uids`` (:data:`SNAPSHOT_FIELDS`)."""
    marks = ", ".join("?" for _ in uids)
    return {str(row[0]): tuple(row[1:]) for row in conn.execute(
        f"SELECT uid, {', '.join(SNAPSHOT_FIELDS)} FROM gb_dataset WHERE uid IN ({marks})",
        uids)}


# --- 5. Restos ----------------------------------------------------------------------------------


def _orphan_fraction(step: Progress) -> float:
    """Cuánto lleva el barrido de restos: cada una de sus fases, una parte igual."""
    try:
        phase = ORPHAN_PHASES.index(step.phase)
    except ValueError:
        phase = 0
    within = step.done / step.total if step.total > 0 else 0.0
    return (phase + min(within, 1.0)) / len(ORPHAN_PHASES)


# --- 6. Versiones -------------------------------------------------------------------------------


def _older(registries: Registries, op_type: str, op_version: str) -> str | None:
    """La versión declarada de ``op_type`` si es mayor que ``op_version``; si no, ``None``."""
    installed = registries.versions.get(op_type)
    if installed is None:
        return None
    try:
        older = parse_version(op_version) < parse_version(installed)
    except ValueError:  # pragma: no cover - el esquema la guarda de su OperationDef
        return None
    return installed if older else None


def _algorithm_steps(project: OpenCheckProject, registries: Registries,
                     found: list[AlgorithmChange], pacer: _Pacer,
                     meter: _Meter) -> Iterator[Progress]:
    """Los tipos de operación con operaciones vigentes de un algoritmo anterior al declarado
    (por tipo y versión registrada), con lo que escribieron, salvo si la caché ya tiene esa
    causa en todas ellas; en ``found``, por tipo y versión."""
    version = project.session.geoblender_version
    with project.read() as conn:
        pending = [(str(op_type), str(op_version), installed)
                   for op_type, op_version, _count in conn.execute(_GROUPS_SQL).fetchall()
                   if (installed := _older(registries, str(op_type), str(op_version)))]
    while pending:
        yield meter.at(5, 0.25)
        pacer.restart()
        with project.read() as conn:
            while pending:
                op_type, op_version, installed = pending.pop(0)
                count, known, results = conn.execute(_ALGORITHM_SQL,
                                                     (op_type, op_version)).fetchone()
                if int(known) < int(count):  # si no, ya lo sabe la caché (de otra apertura)
                    found.append(AlgorithmChange(op_type, op_version, installed, version,
                                                 int(count), int(results)))
                if pacer.lap():
                    break
    found.sort(key=lambda item: (item.op_type, parse_version(item.registered)))
    yield meter.at(5, 0.5)
    pacer.restart()


# --- 7. Cola de hashes y 8. transacción final ---------------------------------------------------

_RECORDED_INPUTS: tuple[InputVerdict, ...] = (InputVerdict.SAME, InputVerdict.CHANGED,
                                              InputVerdict.RESTORED)
"""Lo de una entrada que escribe la transacción final (lo demás no se registra)."""


@dataclass
class _InputHash:
    """Una entrada en la cola de hashes: su prefiltro, lo concluido y, mientras su hash está en
    un trabajo, su resguardo."""

    probe: Probe
    finding: InputFinding | None = None
    ticket: object | None = None


@dataclass(frozen=True)
class _Written:
    """Lo que escribió la transacción final: lo de las entradas (con lo que depende de las
    cambiadas), lo que cambió desde que se comprobó (no se registró), lo registrado de cada
    dato, si quedó el evento de los restos y lo ajeno, las definiciones marcadas y lo que hizo
    la obsolescencia completa."""

    inputs: tuple[InputFinding, ...]
    late: frozenset[str]
    datasets: Mapping[str, DatasetFinding]
    orphans: bool
    definitions: tuple[DefinitionChange, ...]
    cache: CacheUpdate | None


def _concluded(item: object) -> bool:
    """Si un elemento de la cola ya está concluido (o queda para la próxima)."""
    return getattr(item, "finding", None) is not None or bool(getattr(item, "stale", False))


def _job_finding(probe: Probe, result: HashResult) -> InputFinding:
    """El veredicto de una entrada con lo que devolvió su trabajo de hash."""
    record = probe.record
    if result.gone:
        return assess_input(replace(probe, missing=_shown_name(record.files[0])))
    digest = result.digest
    if digest is None:
        return assess_input(probe, error=_shown(result.error or ""))
    if (digest.reader, digest.normalizer) != (record.reader, record.normalizer):
        return assess_input(probe, error=(
            f"el trabajo de hash leyó con «{digest.reader}» ({digest.normalizer}), no con "
            f"«{record.reader}» ({record.normalizer})"))
    return assess_input(probe, digest.content_sha256)


class _Settlement:
    """Los pasos 7 y 8 (véase el módulo): la cola de hashes de lo que saltó en el prefiltro y
    de lo que pidió la puerta, y la transacción final (o, en solo lectura, el informe)."""

    def __init__(self, project: OpenCheckProject, writing: bool, jobs: HashJobs | None,
                 pending: CheckState | None, budget: float, meter: _Meter) -> None:
        self.project = project
        self.writing = writing
        self.jobs = jobs
        self.pending = pending
        self.pacer = _Pacer(budget)
        self.meter = meter
        self.started_at_ns = time.time_ns()
        self.inputs: list[_InputHash] = []
        self.concluded: list[InputFinding] = []  # de lo pedido: lo que no se localiza
        self.checks: list[_Check] = []
        self.reported: list[DatasetFinding] = []  # lo que no se pudo mirar: solo se avisa
        self.originals: list[_OriginalCheck] = []
        self.requests: list[PendingItem] = []

    # --- Lo que hay que hashear y registrar -----------------------------------------------

    def add_survey(self, survey: _Survey) -> None:
        """Lo de los pasos 1 a 6: lo que saltó en el prefiltro, a la cola; lo que falta o está
        dañado, para registrarlo si sigue como se vio."""
        outcome, photo, found = survey.outcome, survey.photo, survey.found
        self.started_at_ns = outcome.started_at_ns
        self.inputs += [_InputHash(probe) for probe in outcome.input_probes]
        for finding in outcome.datasets:
            uid = finding.record.uid
            if uid in found.bases:
                self.checks.append(_Check(finding.record, finding.input_name,
                                          basis=found.bases[uid], finding=finding))
            else:
                self.reported.append(finding)
        self.checks += [_Check(probe.record, _input_name(photo, probe.record),
                               basis=probe.observed) for probe in outcome.dataset_probes]
        stored = {(item.input_uid, item.ord): item for item in photo.originals}
        for missing in outcome.originals:
            kept = stored[(missing.input_uid, missing.ord)]
            check = _OriginalCheck(_Original(kept.input_uid, kept.name, kept.ord, kept.path,
                                             kept.sha256, kept.size, kept.mtime_ns))
            check.conclude(OriginalVerdict.MISSING)
            self.originals.append(check)
        self.originals += [
            _OriginalCheck(_Original(probe.input_uid, probe.name, probe.ord, probe.path,
                                     probe.sha256, probe.size, probe.mtime_ns), seen=probe.seen)
            for probe in outcome.original_probes
        ]

    def add_requests(self) -> None:
        """Lo que la puerta pidió hashear (``CheckState.requests``): lo que ya está en la cola
        va con lo suyo; lo demás se vuelve a mirar (si ya no hay que hashearlo, solo se
        quita)."""
        if self.pending is None:
            return
        self.requests = list(self.pending.requests)
        if not self.requests:
            return
        inputs = {item.probe.record.uid for item in self.inputs}
        datasets = {item.record.uid for item in self.checks}
        with self.project.read() as conn:
            names = {str(uid): str(name)
                     for uid, name in conn.execute("SELECT uid, name FROM gb_input")}
            changes = table_changes(conn)
            for request in self.requests:
                if request.item_kind == ItemKind.INPUT and request.uid not in inputs:
                    inputs.add(request.uid)
                    self._request_input(conn, request.uid, changes)
                elif request.item_kind == ItemKind.DATASET and request.uid not in datasets:
                    datasets.add(request.uid)
                    self._request_dataset(conn, request.uid, names)

    def _request_input(self, conn: sqlite3.Connection, uid: str,
                       changes: Mapping[str, str | None]) -> None:
        record = input_registry.get(conn, uid)
        if record is None or record.uid != uid or not record.active:
            return
        probe = probe_input(self.project, record, mode=CheckMode.QUICK,  # type: ignore[arg-type]
                            tables=changes)
        if probe.needs_hash:
            self.inputs.append(_InputHash(probe))
        elif probe.missing is not None:
            self.concluded.append(assess_input(probe))

    def _request_dataset(self, conn: sqlite3.Connection, uid: str,
                         names: Mapping[str, str]) -> None:
        record = dataset_registry.get(conn, uid)
        if record is None or record.uid != uid or not checkable(record):
            return
        states = table_states(conn, [record.locator]) if record.store is Store.GPKG else {}
        try:
            probe = probe_dataset(self.project, record, states)
        except OSError:  # no se puede mirar: la puerta lo verá al repetir la orden
            return
        if probe.signal is Signal.UNCHANGED:
            return
        name = None if record.input_uid is None else names.get(record.input_uid,
                                                               record.input_uid)
        item = _Check(record, name, basis=probe.observed)
        if probe.signal is not Signal.MOVED:  # falta o está dañado
            item.conclude(assess_dataset(probe))
        self.checks.append(item)

    # --- 7. La cola de hashes -------------------------------------------------------------

    def hash_steps(self) -> Iterator[Progress]:
        """El paso 7: las fuentes externas grandes, a los trabajos; lo demás, en el hilo por
        trozos mientras tanto; después, se espera a los trabajos paso a paso."""
        work: list[object] = [
            *(item for item in self.inputs if item.finding is None),
            *(item for item in self.checks if not _concluded(item)),
            *(item for item in self.originals if not _concluded(item)),
        ]
        total = max(len(work), 1)

        def fraction() -> float:
            return sum(1 for item in work if _concluded(item)) / total

        yield self.meter.at(HASH_STEP, 0.0)
        self.pacer.restart()
        for item in self.inputs:
            self._submit(item)
        for done, item in enumerate(work):
            if _concluded(item) or getattr(item, "ticket", None) is not None:
                continue
            steps: Iterator[Any]
            if isinstance(item, _InputHash):
                steps = self._hash_input(item, done, total)
            elif isinstance(item, _Check):
                steps = _hash_dataset(self.project, item, self.pacer, done, total)
            elif isinstance(item, _OriginalCheck):
                steps = _hash_original(self.project, item, self.pacer, done, total)
            else:  # pragma: no cover - en la cola solo hay entradas, datos y originales
                continue
            for _step in steps:
                yield self.meter.at(HASH_STEP, fraction())
            if self.pacer.lap():
                yield self.meter.at(HASH_STEP, fraction())
                self.pacer.restart()
        while True:
            self._poll()
            if not any(item.ticket is not None for item in self.inputs):
                break
            yield self.meter.at(HASH_STEP, fraction())
            self.pacer.restart()

    def _submit(self, item: _InputHash) -> None:
        """Lanza en un trabajo el hash de la fuente de ``item`` si hay trabajos y su lector la
        manda allí (``plan_hash``: una fuente externa grande; nada del proyecto); si no, o si
        ahora no se puede lanzar, se hashea en el hilo."""
        if self.jobs is None:
            return
        probe = item.probe
        record = probe.record
        found = READERS.get(record.reader)
        if found is None:
            return  # en el hilo, que dice por qué no se puede leer
        size = sum(seen.size or 0 for seen in probe.observed)
        try:
            found.request(record.kind, record.declarations, probe.files, dict(record.settings),
                          normalizer=record.normalizer)
            if plan_hash(found, str(record.files[0].anchor), size) != JOB:
                return
        except (GeoblenderError, TypeError, ValueError):
            return
        ticket = self.jobs.submit(HashRequest(
            record.uid, record.name, record.reader, record.kind, record.declarations,
            record.settings, probe.files, record.normalizer, size))
        if ticket is not None:
            item.ticket = ticket

    def _hash_input(self, item: _InputHash, done: int,
                    total: int) -> Generator[Progress, None, None]:
        """El hash de la fuente de una entrada en el hilo, por trozos."""
        probe = item.probe
        content, error, gone = yield from _content_steps(
            probe, self.pacer, done, total)  # type: ignore[arg-type]
        if gone:  # se borró mientras se leía: no localizable
            probe = replace(probe, missing=_shown_name(probe.record.files[0]))
        item.finding = assess_input(probe, content, error=None if gone else error)

    def _poll(self) -> None:
        """Lo que ya terminó en los trabajos."""
        if self.jobs is None:
            return
        for item in self.inputs:
            if item.ticket is None:
                continue
            result = self.jobs.poll(item.ticket)
            if result is None:
                continue
            if not isinstance(result, HashResult):
                raise TypeError(f"un trabajo de hash termina con un HashResult, no {result!r}")
            item.finding = _job_finding(item.probe, result)
            item.ticket = None

    def cancel(self) -> None:
        """Cancela los trabajos que no han terminado (al cerrar la comprobación a medias)."""
        if self.jobs is None:
            return
        for item in self.inputs:
            if item.ticket is not None:
                ticket, item.ticket = item.ticket, None
                self.jobs.cancel(ticket)

    # --- 8. La transacción final ----------------------------------------------------------

    def _hashed(self) -> list[InputFinding]:
        return [item.finding for item in self.inputs if item.finding is not None]

    def _anything(self) -> bool:
        """Si hay algo que registrar de lo hasheado y de lo concluido."""
        return (any(finding.verdict in _RECORDED_INPUTS for finding in self._hashed())
                or any(item.pending for item in self.checks)
                or any(item.pending for item in self.originals))

    def _with_dependents(self, conn: sqlite3.Connection) -> tuple[InputFinding, ...]:
        """Lo hasheado de las entradas, las cambiadas con lo que depende de ellas ahora."""
        records = {item.probe.record.uid: item.probe.record for item in self.inputs}
        return tuple(
            replace(finding, dependents=dependents(conn, records[finding.input_uid]))
            if finding.status is InputStatus.CHANGED else finding
            for finding in self._hashed()
        )

    def record_steps(self, survey: _Survey | None,
                     registries: Registries | None) -> Generator[Progress, None,
                                                                 OpenCheckOutcome]:
        """El paso 8: todo en una transacción con ``try_write``, reintentada en el paso
        siguiente mientras otro programa lee (sin escribir nada mientras tanto); en solo
        lectura, nada. Devuelve el resultado."""
        yield self.meter.at(RECORD_STEP, 0.0)
        written: _Written | None = None
        if self.writing and self.project.writable and (survey is not None or self._anything()):
            while True:
                attempt = self.project.try_write(
                    lambda conn: self._write(conn, survey, registries))
                if attempt.state is WriteState.DONE:
                    break
                yield self.meter.at(RECORD_STEP, 0.5, message=attempt.message)
            written = attempt.value
            return self._outcome(survey, written, written.inputs)
        if any(finding.status is InputStatus.CHANGED for finding in self._hashed()):
            with self.project.read() as conn:
                return self._outcome(survey, None, self._with_dependents(conn))
        return self._outcome(survey, None, tuple(self._hashed()))

    def _write(self, conn: sqlite3.Connection, survey: _Survey | None,
               registries: Registries | None) -> _Written:
        """La transacción final, en ``conn`` (se repite entera si hay que reintentarla)."""
        project = self.project
        now = format_utc(project.clock.now())
        if survey is not None and survey.outcome.interrupted:
            interrupt_orphaned(project, conn=conn)  # type: ignore[arg-type]
        findings = self._with_dependents(conn)
        _done, inputs_late = record_findings(conn, project, findings)  # type: ignore[arg-type]
        late, datasets = _record_all(conn, project, self.checks, self.originals)
        orphans = False
        definitions: tuple[DefinitionChange, ...] = ()
        cache = None
        if survey is not None and registries is not None:
            orphans = record_orphans(conn, project,  # type: ignore[arg-type]
                                     survey.outcome.orphans)
            store = ParameterStore(project)  # type: ignore[arg-type]
            definitions = tuple(store.mark_definition_changes(conn, registries.definitions))
            for change in definitions:
                record_event(conn, EventKind.DEFINITION_CHANGED,
                             change.text or render("core.definition_redeclared", key=change.key),
                             session=project.session, at=now, entity_kind="parameter",
                             entity_uid=change.parameter_uid,
                             data={"key": change.key, "scope": change.scope,
                                   "review": change.review})
            for item in survey.outcome.algorithms:
                record_event(conn, EventKind.ALGORITHM_CHANGED, item.text(),
                             session=project.session, at=now,
                             data={"op_type": item.op_type, "registered": item.registered,
                                   "installed": item.installed,
                                   "geoblender_version": item.geoblender_version,
                                   "operations": item.operations, "results": item.results})
            cache = refresh_all(conn, now=now, versions=registries.versions)
        return _Written(findings, frozenset(late) | frozenset(inputs_late),
                        MappingProxyType(dict(datasets)), orphans, definitions, cache)

    def _outcome(self, survey: _Survey | None, written: _Written | None,
                 hashed: Iterable[InputFinding]) -> OpenCheckOutcome:
        """El resultado: lo de los pasos 1 a 6 con lo hasheado y lo registrado."""
        base = (survey.outcome if survey is not None
                else OpenCheckOutcome(writing=self.writing, started_at_ns=self.started_at_ns))
        late = frozenset() if written is None else written.late
        recorded = {} if written is None else written.datasets
        stale = list(base.stale)
        inputs = [*base.inputs, *self.concluded]
        for finding in hashed:
            if finding.input_uid in late:  # cambió de estado mientras se comprobaba
                stale.append(finding.input_uid)
            else:
                inputs.append(finding)
        checked = [uid for uid in base.checked_datasets if uid not in late]
        datasets = list(self.reported)
        for item in self.checks:
            uid = item.record.uid
            if item.stale or uid in late:
                stale.append(uid)
            elif item.finding is not None:
                checked.append(uid)
                finding = recorded.get(uid, item.finding)
                if finding.verdict is not DatasetVerdict.UNCHANGED:
                    datasets.append(finding)
        originals: list[OriginalFinding] = []
        for check in self.originals:
            if check.stale or check.item.path in late:
                stale.append(check.item.path)
            elif (check.finding is not None
                  and check.finding.verdict is not OriginalVerdict.UNCHANGED):
                originals.append(check.finding)
        orphans, definitions = base.orphans, base.definitions
        if written is not None and survey is not None:
            orphans = replace(base.orphans, recorded=written.orphans)
            definitions = written.definitions
        return replace(
            base,
            inputs=tuple(inputs),
            input_probes=(),
            datasets=tuple(datasets),
            dataset_probes=(),
            checked_datasets=tuple(dict.fromkeys(checked)),
            stale=tuple(dict.fromkeys(stale)),
            originals=tuple(originals),
            original_probes=(),
            orphans=orphans,
            definitions=definitions,
            recorded=written is not None,
            cache=None if written is None else written.cache,
        )

    def release(self) -> None:
        """Lo que pidió la puerta y se ha hecho deja de esperarse."""
        if self.pending is not None:
            for request in self.requests:
                self.pending.hashed(request.item_kind, request.uid)
