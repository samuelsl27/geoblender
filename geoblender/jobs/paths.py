# SPDX-License-Identifier: GPL-3.0-or-later
"""Carpetas de los trabajos en segundo plano (spec 004; RF-004-01, RF-004-18; plan 004
§5.2.1 y §5.3.1).

Cada trabajo tiene su carpeta ``<raíz de trabajos>/<job_uid>/`` (plan §5.2.1)::

    request.json   la petición (``protocol.write_request``)
    in/            entradas: ``.npy`` sin *pickle* y copias verificadas de ficheros
    out/           salidas del worker
    events.jsonl   eventos recibidos y notas del lanzador
    job.log        salida de error del worker y lo que imprime
    result.json    resumen final del worker
    state.json     estado (``records.write_record``)
    cancel         centinela: si existe, el worker para en el siguiente punto de control

- :func:`new_job_uid`: ``AAAAMMDD_HHMMSS_xxxxxx`` (hora UTC y 6 cifras hexadecimales al
  azar), sin repetir en el proceso; ``protocol.new_request`` usa este mismo generador.
- :func:`job_dir` y :class:`JobDir`: la carpeta de un trabajo y sus partes. Calcularla no
  crea nada; :meth:`JobDir.create` la crea.
- :meth:`JobDir.write_array`: un array en ``in/<nombre>.npy`` tal como lo entrega el módulo,
  sin cambiar su tipo ni su precisión (``np.save`` con ``allow_pickle=False``).
- :meth:`JobDir.copy_input`: copia de un fichero externo (CSV, XLSX, base de RecMin) a
  ``in/``, con la huella sha256 de la fuente antes, de la copia y de la fuente después: si
  no coinciden, la fuente cambió mientras se copiaba (``source_changed``) y no queda nada.
- :func:`resolve_jobs_root`: ``<caché del proyecto>/jobs`` o, sin proyecto,
  ``<datos de usuario>/cache/_sin_proyecto/jobs`` (RF-004-18).

Las entradas quedan **de solo lectura**: el worker las lee y no las cambia (quien las borre
después, la limpieza, les quita antes ese atributo). Sin espacio en disco, ``disk_space``
con los MB necesarios y libres, y no queda ningún fichero a medias (spec §8).

La caché del proyecto (``Project.cache_dir()`` de la 002) ya está en los datos de usuario
si el proyecto se abrió desde la red o en solo lectura: ``bl`` la calcula y la pasa, y este
módulo no comprueba de qué unidad es una ruta (plan §6).
"""

from __future__ import annotations

import datetime as dt
import errno
import hashlib
import math
import os
import re
import secrets
import shutil
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.paths import RESERVED_NAMES, check_path_length
from ..core.userdata import UserData
from .messages import JobError

if TYPE_CHECKING:
    import numpy as np

JOB_UID_PATTERN = re.compile(r"[0-9]{8}_[0-9]{6}_[0-9a-f]{6}")
"""``AAAAMMDD_HHMMSS_xxxxxx``: hora UTC y 6 cifras hexadecimales al azar (con ``fullmatch``)."""

JOBS_DIR = "jobs"
"""Carpeta de los trabajos dentro de una caché (la del proyecto o la de «sin proyecto»)."""
REQUEST_FILE = "request.json"
INPUTS_DIR = "in"
"""Carpeta de las entradas dentro de la del trabajo: toda entrada está aquí dentro."""
OUTPUTS_DIR = "out"
"""Carpeta de los resultados dentro de la del trabajo: todo resultado está aquí dentro."""
EVENTS_FILE = "events.jsonl"
LOG_FILE = "job.log"
RESULT_FILE = "result.json"
CANCEL_FILE = "cancel"

ARRAY_SUFFIX = ".npy"
INPUT_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
"""Nombre de una entrada en ``in/`` (sin extensión): letras y cifras ASCII, «_» y «-»."""
SUFFIX_PATTERN = re.compile(r"\.[A-Za-z0-9_-]{1,16}")
"""Extensión de un fichero externo que se copia (``.csv``, ``.xlsx``, ``.accdb``…)."""

PARTIAL_SUFFIX = ".partial"
"""Sufijo del fichero a medias: se escribe aparte y se renombra al acabar."""
NPY_HEADER_BYTES = 4096
"""Margen para la cabecera de un ``.npy`` al calcular el espacio necesario."""
BYTES_PER_MB = 1_000_000
_CHUNK_BYTES = 1 << 20
"""Bloque de lectura de las copias (1 MiB)."""
_DISK_FULL_WINERRORS = frozenset({39, 112})  # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
_OBJ = "Carpeta del trabajo"


class _UidIssuer:
    """Identificadores ``AAAAMMDD_HHMMSS_xxxxxx`` sin repetir dentro de este proceso: 6
    cifras hexadecimales al azar por segundo, y otras si ya salieron en ese segundo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stamp = ""
        self._issued: set[str] = set()

    def new(self, moment: dt.datetime) -> str:
        stamp = f"{moment.astimezone(dt.UTC):%Y%m%d_%H%M%S}"
        with self._lock:
            if stamp != self._stamp:
                self._stamp = stamp
                self._issued.clear()
            while True:
                uid = f"{stamp}_{secrets.token_hex(3)}"
                if uid not in self._issued:
                    self._issued.add(uid)
                    return uid


_UIDS = _UidIssuer()


def new_job_uid(now: dt.datetime | None = None) -> str:
    """Un identificador de trabajo nuevo (RF-004-01): ``AAAAMMDD_HHMMSS_xxxxxx`` con la hora
    ``now`` en UTC (la actual si falta) y 6 cifras hexadecimales al azar, sin repetir en este
    proceso. Una hora sin zona es :class:`ValueError`: no se supone UTC ni la local."""
    moment = dt.datetime.now(dt.UTC) if now is None else now
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"la hora {moment!r} no tiene zona: el job_uid lleva la hora UTC")
    return _UIDS.new(moment)


@dataclass(frozen=True, slots=True)
class JobDir:
    """La carpeta de un trabajo, ``<raíz de trabajos>/<job_uid>/`` (plan §5.2.1): una ruta
    absoluta que acaba en un ``job_uid`` válido (:class:`ValueError` si no). Es lo que
    reciben ``protocol.write_request``/``read_request`` y ``records.write_record``."""

    path: Path

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not path.is_absolute():
            raise ValueError(
                f"la carpeta del trabajo «{path}» no es una ruta completa: la raíz de "
                "trabajos la da bl con la caché del proyecto o los datos de usuario"
            )
        if not JOB_UID_PATTERN.fullmatch(path.name):
            raise ValueError(
                f"«{path.name}» no es el identificador de un trabajo (AAAAMMDD_HHMMSS_xxxxxx)"
            )
        object.__setattr__(self, "path", path)

    @property
    def job_uid(self) -> str:
        return self.path.name

    @property
    def inputs_dir(self) -> Path:
        return self.path / INPUTS_DIR

    @property
    def outputs_dir(self) -> Path:
        return self.path / OUTPUTS_DIR

    @property
    def events_file(self) -> Path:
        return self.path / EVENTS_FILE

    @property
    def log_file(self) -> Path:
        return self.path / LOG_FILE

    @property
    def result_file(self) -> Path:
        return self.path / RESULT_FILE

    @property
    def cancel_file(self) -> Path:
        return self.path / CANCEL_FILE

    def create(self) -> JobDir:
        """Crea la carpeta del trabajo con ``in/`` y ``out/`` (y la raíz, si falta) y la
        devuelve. Una carpeta que ya existe no se reutiliza: ``FileExistsError``."""
        check_path_length(self.inputs_dir, folder=True, obj=_OBJ)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.mkdir()
        self.inputs_dir.mkdir()
        self.outputs_dir.mkdir()
        return self

    def write_array(self, name: str, array: np.ndarray) -> str:
        """Guarda ``array`` en ``in/<name>.npy`` tal como llega (RF-004-01): mismo tipo,
        orden de bytes, forma y orden en memoria, y los decimales bit a bit (NaN con su
        carga útil incluidos), con ``np.save(..., allow_pickle=False)``. Devuelve la ruta
        relativa para ``inputs`` de la petición (``"in/<name>.npy"``).

        ``name``: :data:`INPUT_NAME_PATTERN` y no un nombre reservado de Windows
        (:class:`ValueError`). Un array con objetos necesitaría *pickle*
        (:class:`ValueError`) y lo que no es un ``ndarray`` no se convierte
        (:class:`TypeError`). Una entrada que ya existe no se sobrescribe
        (``FileExistsError``). Sin espacio, :class:`JobError` ``disk_space``. El fichero
        queda de solo lectura y nunca a medias."""
        import numpy as np  # solo aquí: importar jobs no carga numpy (plan §5.4.3)

        stem = _input_name(name)
        if not isinstance(array, np.ndarray):
            raise TypeError(
                f"la entrada «{stem}» es {type(array).__name__} y no un numpy.ndarray: se "
                "guarda tal como llega, sin convertirla"
            )
        if array.dtype.hasobject:
            raise ValueError(
                f"la entrada «{stem}» tiene objetos de Python (dtype {array.dtype}): "
                "guardarla necesitaría pickle; use tipos numéricos, texto de longitud fija "
                "o JSON en los parámetros"
            )
        filename = stem + ARRAY_SUFFIX
        target, temporary = self._targets(filename)
        self._check_space(array.nbytes + NPY_HEADER_BYTES)
        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        try:
            with temporary.open("xb") as handle:
                np.save(handle, array, allow_pickle=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except BaseException as exc:
            temporary.unlink(missing_ok=True)
            if isinstance(exc, OSError) and _disk_full(exc):
                raise self._disk_space(array.nbytes + NPY_HEADER_BYTES) from None
            raise
        _make_read_only(target)
        return f"{INPUTS_DIR}/{filename}"

    def copy_input(self, source: Path, name: str, *, job: str | None = None,
                   progress: Callable[[float], object] | None = None) -> str:
        """Copia el fichero ``source`` a ``in/<name><extensión de source>`` (RF-004-01; lo
        pide la 005 para CSV, XLSX y bases de RecMin) y devuelve su ruta relativa
        (``"in/collares.csv"``). La fuente solo se lee.

        Toma la huella sha256 de la fuente antes, la de la copia mientras se escribe y la de
        la fuente después: si no son las tres iguales, la fuente cambió durante la copia,
        :class:`JobError` ``source_changed`` (que nombra la fuente y el trabajo ``job``, por
        defecto su ``job_uid``) y no queda nada en ``in/``. Una fuente que no existe o no es
        un fichero, ``request_invalid``; sin espacio, ``disk_space`` antes de leerla.
        ``name`` como en :meth:`write_array`; la copia queda de solo lectura.

        ``progress(fracción)`` (spec 006, T33; RF-006-28), si se da, recibe lo hecho de las
        tres lecturas (0–1) tras cada bloque de 1 MiB: una fuente grande o en red avisa de su
        avance, y lo que lance (``JobCancelled`` del contexto del trabajo) para la copia sin
        dejar nada en ``in/``."""
        source = Path(source)
        stem = _input_name(name)
        label = job if isinstance(job, str) and job.strip() else self.job_uid
        try:
            info = source.stat()
        except OSError as exc:
            raise _unreadable(label, stem, source, _reason(exc)) from None
        if not stat.S_ISREG(info.st_mode):
            raise _unreadable(label, stem, source, "no es un fichero")
        suffix = source.suffix
        if suffix and not SUFFIX_PATTERN.fullmatch(suffix):
            raise JobError(
                "request_invalid", job=label,
                detail=f"la extensión «{suffix}» de la entrada «{stem}» ({source}) no es válida",
            )
        filename = stem + suffix
        target, temporary = self._targets(filename)
        self._check_space(info.st_size)
        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        passes = None if progress is None else _Passes(progress, info.st_size)

        def digest(sink: Callable[[bytes], object] | None = None) -> str:
            if passes is None:
                return _digest(source, sink)
            return _digest(source, sink, done=passes.done)

        try:
            before = digest()
            with temporary.open("xb") as handle:
                copied = digest(handle.write)
                handle.flush()
                os.fsync(handle.fileno())
            after = digest()
            if not before == copied == after:
                raise JobError("source_changed", job=label, path=source)
            os.replace(temporary, target)
        except BaseException as exc:
            temporary.unlink(missing_ok=True)
            if isinstance(exc, OSError):
                if _disk_full(exc):
                    raise self._disk_space(info.st_size) from None
                raise _unreadable(label, stem, source, _reason(exc)) from None
            raise
        _make_read_only(target)
        return f"{INPUTS_DIR}/{filename}"

    # --- Ayudas ---------------------------------------------------------------------

    def _targets(self, filename: str) -> tuple[Path, Path]:
        """El fichero de una entrada y su temporal; ``FileExistsError`` si alguno existe."""
        target = self.inputs_dir / filename
        temporary = self.inputs_dir / f"{filename}{PARTIAL_SUFFIX}"
        check_path_length(temporary, obj=_OBJ)
        for path in (target, temporary):
            if os.path.lexists(path):
                raise FileExistsError(
                    f"la entrada {INPUTS_DIR}/{path.name} del trabajo {self.job_uid} ya "
                    "existe: una entrada no se sobrescribe"
                )
        return target, temporary

    def _check_space(self, needed: int) -> None:
        """:class:`JobError` ``disk_space`` si en la unidad de ``in/`` no caben ``needed``
        bytes; no escribe nada."""
        if _free_bytes(_existing(self.inputs_dir)) < needed:
            raise self._disk_space(needed)

    def _disk_space(self, needed: int) -> JobError:
        try:
            free = _free_bytes(_existing(self.inputs_dir))
        except OSError:
            free = 0
        return JobError(
            "disk_space",
            drive=self.path.drive or self.path.anchor,
            needed=math.ceil(needed / (BYTES_PER_MB / 10)) / 10,
            free=math.floor(free / (BYTES_PER_MB / 10)) / 10,
        )


def job_dir(jobs_root: Path, job_uid: str) -> JobDir:
    """La carpeta del trabajo ``job_uid`` dentro de ``jobs_root`` (no la crea). Un
    ``job_uid`` que no es ``AAAAMMDD_HHMMSS_xxxxxx`` (con barras, ``..``, mayúsculas…) o una
    raíz relativa son :class:`ValueError`: la carpeta nunca sale de la raíz."""
    if not isinstance(job_uid, str) or not JOB_UID_PATTERN.fullmatch(job_uid):
        raise ValueError(
            f"{job_uid!r} no es el identificador de un trabajo (AAAAMMDD_HHMMSS_xxxxxx)"
        )
    root = Path(jobs_root)
    if not root.is_absolute():
        raise ValueError(f"la raíz de trabajos «{root}» no es una ruta completa")
    return JobDir(root / job_uid)


def resolve_jobs_root(*, project_cache_dir: Path | None, user_dir: Path) -> Path:
    """La raíz de trabajos (RF-004-18): ``project_cache_dir / "jobs"`` con un proyecto
    abierto (``Project.cache_dir()`` de la 002, que ya está en los datos de usuario si el
    proyecto está en red o en solo lectura) o ``user_dir/cache/_sin_proyecto/jobs`` sin
    proyecto (``user_dir`` = los datos de usuario de la extensión). No crea nada; una ruta
    relativa es :class:`ValueError`."""
    user = Path(user_dir)
    if not user.is_absolute():
        raise ValueError(f"los datos de usuario «{user}» no son una ruta completa")
    if project_cache_dir is None:
        return UserData(user).no_project_cache_dir() / JOBS_DIR
    cache = Path(project_cache_dir)
    if not cache.is_absolute():
        raise ValueError(f"la caché del proyecto «{cache}» no es una ruta completa")
    return cache / JOBS_DIR


def _input_name(name: object) -> str:
    """``name`` si vale como nombre de una entrada; :class:`ValueError` si no."""
    if not isinstance(name, str) or not INPUT_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            f"{name!r} no vale como nombre de una entrada: de 1 a 64 letras y cifras ASCII, "
            "«_» o «-», sin extensión, empezando por letra o cifra"
        )
    if name.upper() in RESERVED_NAMES:
        raise ValueError(f"«{name}» es un nombre reservado de Windows")
    return name


def _digest(path: Path, sink: Callable[[bytes], object] | None = None, *,
            done: Callable[[int], object] | None = None) -> str:
    """Huella sha256 de ``path`` leído por bloques; cada bloque leído va también a ``sink``
    (la copia), así la huella de la copia es la de lo que se escribió, y su tamaño a
    ``done``."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(_CHUNK_BYTES):
            digest.update(block)
            if sink is not None:
                sink(block)
            if done is not None:
                done(len(block))
    return digest.hexdigest()


class _Passes:
    """El avance de las tres lecturas de :meth:`JobDir.copy_input` (antes, copia y después)
    de una fuente de ``size`` bytes, para ``progress(fracción)``."""

    def __init__(self, progress: Callable[[float], object], size: int) -> None:
        self._progress = progress
        self._total = 3 * max(1, size)
        self._read = 0

    def done(self, count: int) -> None:
        self._read += count
        self._progress(min(1.0, self._read / self._total))


def _free_bytes(folder: Path) -> int:
    """Bytes libres en la unidad de ``folder`` (que existe)."""
    return int(shutil.disk_usage(folder).free)


def _existing(path: Path) -> Path:
    """``path`` o su primera carpeta madre que existe."""
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return path


def _disk_full(exc: OSError) -> bool:
    return exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) in _DISK_FULL_WINERRORS


def _make_read_only(path: Path) -> None:
    """Quita el permiso de escritura (en Windows, el atributo «solo lectura»)."""
    os.chmod(path, stat.S_IREAD)


def _reason(exc: OSError) -> str:
    if isinstance(exc, FileNotFoundError):
        return "no existe"
    return exc.strerror or str(exc) or type(exc).__name__


def _unreadable(job: str, name: str, source: Path, reason: str) -> JobError:
    return JobError(
        "request_invalid", job=job,
        detail=f"no se puede copiar la entrada «{name}» desde {source}: {reason}",
    )
