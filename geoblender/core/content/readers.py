# SPDX-License-Identifier: GPL-3.0-or-later
"""Lectores de contenido: quién lee cada formato para el hash de contenido y dónde se calcula
(spec 008; RF-008-08, RF-008-09; ADR-0024 §5, §6 y §7; ADR-0025 §2 y §7; plan 008 §5.3.1 y
§5.4.1).

Cada importador declara un **lector de contenido** (:class:`ContentReader`): su identificador
``<módulo>.<nombre>`` y su versión (juntos, ``gis.geotiff@1``), los tipos de dato que da, si
lee sobre una copia, si su fuente es SQLite, su estimación de tiempo, su función ``read`` y si
puede ir al trabajo de hash. ``read(request)`` es un **generador**: convierte el formato a las
secciones de ``gbch/1`` escribiéndolo en el :class:`~.encoder.ContentHasher` de su petición
(:class:`ReadRequest`) y, tras cada trozo, da su progreso (de 0 a 1, sin retroceder); cada
``yield`` es un punto de cancelación. La misma función calcula el hash al importar (en el
trabajo de la importación) y al comprobar: nunca hay dos implementaciones de un lector.

Lo registra el módulo dueño desde ``bl/`` con :func:`register_reader` y lo quita con
:func:`unregister_reader` (ADR-0004: ``core`` no importa los módulos). :data:`READERS` es la
vista de solo lectura del registro, por identificador con versión, y :func:`reader` lo busca
así. Cada entrada y cada dato guardan el lector con que se registraron y se comparan siempre
con él (ADR-0024 §6): un lector publicado no cambia, y una versión nueva convive con las
anteriores.

:func:`read_steps` avanza un lector comprobando su progreso y su resultado, y
:func:`read_content` lo lleva hasta el final con ``progress`` y ``cancelled`` (como
``core.hashing.sha256_file``) y devuelve el :class:`~.encoder.ContentDigest`. :func:`plan_hash`
decide dónde: lo que está dentro del proyecto, siempre en el hilo de Blender por trozos
medidos por tiempo; una fuente externa estimada en más de :data:`INLINE_LIMIT_S`, en el
trabajo ``core_content_hash`` de la 004 (ADR-0025 §7). Python puro (ADR-0004).
"""

from __future__ import annotations

import math
import numbers
import os
import re
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from ..errors import ValidationError
from .encoder import KINDS, NORMALIZER, ContentDigest, ContentHasher

type ReadFunction = Callable[["ReadRequest"], Iterator[float]]
"""``read(request) -> Iterator[float]``: el generador del lector (su progreso, de 0 a 1)."""
type Estimator = Callable[[int], float | None]
"""``estimate_s(bytes) -> segundos | None``: lo que tardaría en hashear una fuente de ese
tamaño (``None``: no se sabe)."""
type HashPlan = Literal["inline", "job"]

INLINE: HashPlan = "inline"
"""En el hilo de Blender, por trozos medidos por tiempo (≤ 20 ms por tic)."""
JOB: HashPlan = "job"
"""En el trabajo ``core_content_hash`` de la 004, con la ruta de la fuente en la línea de
órdenes (``submit(paths=…)``)."""
PLANS: tuple[str, ...] = (INLINE, JOB)
INLINE_LIMIT_S = 1.0
"""La estimación más alta con la que una fuente externa se hashea en el hilo (plan §5.4.1)."""
PROJECT_LOCATIONS: tuple[str, ...] = ("project", "project_table")
"""Ubicaciones dentro del proyecto (``gb_input_file.anchor``): un fichero suyo o una tabla de
``project.gpkg``. Nunca van a un trabajo (ADR-0010, ADR-0025 §7)."""
EXTERNAL_LOCATIONS: tuple[str, ...] = ("original", "external")
"""Ubicaciones fuera del proyecto (``gb_input_file.anchor``, RF-002-19): junto al proyecto
original o con su ruta en los datos de usuario de este equipo."""
LOCATIONS: tuple[str, ...] = PROJECT_LOCATIONS + EXTERNAL_LOCATIONS
DEFAULT_CHUNK_BYTES = 1 << 20
"""Lo que lee un lector entre dos ``yield``, orientativo (1 MiB: unos milisegundos de
sha256, dentro de los 20 ms de un tic del hilo). El trabajo puede pedir trozos mayores."""
MAIN_ROLE = "main"
"""El papel del fichero principal de una fuente; los demás (``prj``, ``wal``…) los nombra
su lector."""

_READER_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+")
_FULL_ID = re.compile(r"(?P<id>[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)@(?P<version>[1-9][0-9]*)")
_ROLE = re.compile(r"[a-z][a-z0-9_]*")
_OBJ = "Lector de contenido"


@dataclass(frozen=True, slots=True)
class ContentReader:
    """Un lector de contenido (ADR-0024 §5), comprobado al crearlo (``ValueError`` o
    ``TypeError`` si no cumple):

    - ``reader_id``: ``<módulo>.<nombre>`` en minúsculas, sin versión (``"gis.geotiff"``);
    - ``version``: entero positivo; sube con cualquier cambio de lo que lee (ADR-0024 §6);
    - ``kinds``: los tipos de dato que da (de :data:`~.encoder.KINDS`, al menos uno);
    - ``needs_copy``: si se lee siempre sobre una copia (una base Access, ADR-0018);
    - ``sqlite``: si la fuente es SQLite (un GeoPackage): con su ``-wal`` o su ``-journal``,
      el prefiltro va al hash y el trabajo la copia con ellos (plan §5.4.2, §5.3.3);
    - ``estimate_s``: ``estimate_s(bytes)`` en segundos, ``None`` si no se sabe (o la función
      que devuelve ``None``): entonces una fuente externa va al trabajo;
    - ``read``: el generador ``read(request)`` (ver el módulo);
    - ``worker``: si puede calcularse en el trabajo ``core_content_hash`` (está en la lista
      estática de su envoltorio); si no, siempre en el hilo, por trozos.
    """

    reader_id: str
    version: int
    kinds: tuple[str, ...]
    needs_copy: bool
    sqlite: bool
    estimate_s: Estimator | None
    read: ReadFunction
    worker: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.reader_id, str) or _READER_ID.fullmatch(self.reader_id) is None:
            raise ValueError(
                f"el identificador del lector {self.reader_id!r} no es <módulo>.<nombre> en "
                "minúsculas y sin versión, como «gis.geotiff»"
            )
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError(
                f"la versión del lector «{self.reader_id}» ({self.version!r}) no es un entero"
            )
        if self.version < 1:
            raise ValueError(
                f"la versión del lector «{self.reader_id}» ({self.version}) tiene que ser 1 o "
                "más"
            )
        object.__setattr__(self, "kinds", _kinds(self.kinds, self.reader_id))
        for name in ("needs_copy", "sqlite", "worker"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(
                    f"«{name}» del lector «{self.reader_id}» es verdadero o falso, no "
                    f"{getattr(self, name)!r}"
                )
        if self.estimate_s is not None and not callable(self.estimate_s):
            raise TypeError(
                f"la estimación del lector «{self.reader_id}» es una función del tamaño en "
                f"bytes o None, no {type(self.estimate_s).__name__}"
            )
        if not callable(self.read):
            raise TypeError(
                f"«read» del lector «{self.reader_id}» no es una función "
                f"({type(self.read).__name__})"
            )

    @property
    def id(self) -> str:
        """El identificador con versión: ``"gis.geotiff@1"`` (``gb_input.reader``)."""
        return f"{self.reader_id}@{self.version}"

    @property
    def module(self) -> str:
        """El código del módulo dueño: ``"gis"`` de ``"gis.geotiff"``."""
        return self.reader_id.partition(".")[0]

    def request(
        self,
        kind: str,
        declarations: Mapping[str, Any],
        files: Mapping[str, str | os.PathLike[str]],
        settings: Mapping[str, Any] | None = None,
        *,
        normalizer: str = NORMALIZER,
        chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    ) -> ReadRequest:
        """La petición para leer con este lector (``ValueError`` si no da ``kind``)."""
        if kind not in self.kinds:
            raise ValueError(
                f"el lector «{self.id}» da {list(self.kinds)}, no «{kind}»"
            )
        return ReadRequest(
            self.id,
            kind,
            declarations,
            files,
            {} if settings is None else settings,
            normalizer=normalizer,
            chunk_bytes=chunk_bytes,
        )


@dataclass(frozen=True, slots=True)
class ReadRequest:
    """Lo que lee un lector y dónde lo escribe, de un solo uso:

    - ``reader``: el identificador con versión del lector (``"gis.geotiff@1"``);
    - ``kind`` y ``declarations``: el tipo de dato y lo declarado al importar (CRS
      horizontal y vertical, convenios): van a la cabecera del hash de contenido;
    - ``files``: los ficheros de la fuente por papel (``"main"`` siempre; ``"prj"``,
      ``"wal"``… los nombra el lector), como ``Path``; de solo lectura;
    - ``settings``: los ajustes de lectura (capa, columnas, selector…); copia de solo lectura;
    - ``normalizer``: el de la entrada o el dato (el vigente, si es nuevo: ADR-0024 §6);
    - ``chunk_bytes``: lo que lee el lector entre dos ``yield``, orientativo;
    - ``hasher``: el :class:`~.encoder.ContentHasher` donde escribe el lector, creado con
      todo lo anterior.
    """

    reader: str
    kind: str
    declarations: Mapping[str, Any]
    files: Mapping[str, Path]
    settings: Mapping[str, Any]
    normalizer: str = NORMALIZER
    chunk_bytes: int = DEFAULT_CHUNK_BYTES
    hasher: ContentHasher = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.reader, str) or _FULL_ID.fullmatch(self.reader) is None:
            raise ValueError(
                f"{self.reader!r} no es el identificador con versión de un lector, como "
                "«gis.geotiff@1»"
            )
        if isinstance(self.chunk_bytes, bool) or not isinstance(self.chunk_bytes, int):
            raise TypeError(
                f"el tamaño de trozo ({self.chunk_bytes!r}) no es un número entero de bytes"
            )
        if self.chunk_bytes < 1:
            raise ValueError(f"el tamaño de trozo ({self.chunk_bytes}) tiene que ser positivo")
        if not isinstance(self.settings, Mapping):
            raise TypeError(
                f"los ajustes de lectura son un diccionario, no {type(self.settings).__name__}"
            )
        hasher = ContentHasher(
            self.kind,
            declarations=self.declarations,
            reader=self.reader,
            normalizer=self.normalizer,
        )
        object.__setattr__(self, "declarations", MappingProxyType(dict(self.declarations)))
        object.__setattr__(self, "files", MappingProxyType(_files(self.files)))
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))
        object.__setattr__(self, "hasher", hasher)


class ReadCancelled(Exception):
    """Se pidió parar la lectura de un lector entre dos trozos. ``reader`` es su
    identificador con versión y ``progress`` lo que llevaba (de 0 a 1)."""

    def __init__(self, reader: str, progress: float) -> None:
        self.reader = reader
        self.progress = progress
        super().__init__(
            f"Se paró la lectura con «{reader}» al {math.floor(progress * 100)} % (la "
            "cancelación se pidió entre dos trozos)"
        )


# --- Registro -------------------------------------------------------------------------------

_REGISTRY: dict[str, ContentReader] = {}
_LOCK = threading.Lock()

READERS: Mapping[str, ContentReader] = MappingProxyType(_REGISTRY)
"""Los lectores registrados, por identificador con versión (``"gis.geotiff@1"``): vista de
solo lectura que sigue los registros."""


def register_reader(content_reader: ContentReader) -> None:
    """Registra un lector (lo llama ``bl/`` en el ``register()`` de su módulo).
    ``ValueError`` si ya hay uno con el mismo identificador y la misma versión (el registrado
    se queda); ``TypeError`` si no es un :class:`ContentReader`."""
    if not isinstance(content_reader, ContentReader):
        raise TypeError(
            f"solo se registra un ContentReader, no {type(content_reader).__name__} "
            f"({content_reader!r})"
        )
    with _LOCK:
        if content_reader.id in _REGISTRY:
            raise ValueError(
                f"lector ya registrado: «{content_reader.id}». Cada identificador y versión se "
                "registra una sola vez (unregister_reader antes de volver a registrarlo); un "
                "cambio de lo que lee es una versión nueva"
            )
        _REGISTRY[content_reader.id] = content_reader


def unregister_reader(reader_id: str) -> int:
    """Quita el lector ``reader_id`` (en ``unregister()``) y dice cuántos quitó: con versión
    (``"gis.geotiff@1"``), ese; sin ella (``"gis.geotiff"``), todas sus versiones. Quitar uno
    que no está no hace nada: ``unregister()`` es idempotente."""
    if not isinstance(reader_id, str):
        raise TypeError(f"el identificador de un lector es un texto, no {reader_id!r}")
    with _LOCK:
        if "@" in reader_id:
            return 0 if _REGISTRY.pop(reader_id, None) is None else 1
        names = [name for name, found in _REGISTRY.items() if found.reader_id == reader_id]
        for name in names:
            del _REGISTRY[name]
    return len(names)


def reader(reader_id: str) -> ContentReader:
    """El lector registrado con ese identificador con versión (``"gis.geotiff@1"``).
    ``ValidationError`` (``core.reader_unregistered``) si no está: el módulo que lo declara no
    está activo o es de otra versión de Geoblender; ``ValueError`` si falta la versión."""
    if not isinstance(reader_id, str) or _FULL_ID.fullmatch(reader_id) is None:
        raise ValueError(
            f"{reader_id!r} no es el identificador con versión de un lector, como "
            "«gis.geotiff@1»"
        )
    found = _REGISTRY.get(reader_id)
    if found is None:
        raise ValidationError(
            "core.reader_unregistered",
            "no hay ningún lector registrado con ese identificador: el módulo que lo declara "
            "no está activo o es de otra versión de Geoblender, y sin él no se puede comparar "
            "el contenido",
            obj=_OBJ,
            field="identificador",
            value=reader_id,
        )
    return found


# --- Lectura --------------------------------------------------------------------------------


def read_steps(content_reader: ContentReader, request: ReadRequest) -> Iterator[float]:
    """Los pasos del lector sobre la petición: su progreso tras cada trozo, comprobado (un
    número de 0 a 1 que no retrocede; si no, ``ValueError`` o ``TypeError`` con su
    identificador). Al acabar, el hasher de la petición tiene sus datos (si no,
    ``RuntimeError``). Cerrar el iterador a medias (``close()``) cancela entre dos trozos y
    cierra el generador del lector (lo que abrió se cierra)."""
    _check_pair(content_reader, request)
    steps = content_reader.read(request)
    if not isinstance(steps, Iterator):
        raise TypeError(
            f"el lector «{content_reader.id}» no es un generador: «read» devolvió "
            f"{type(steps).__name__}"
        )
    last = 0.0
    try:
        for value in steps:
            last = _progress(value, last, content_reader.id)
            yield last
    finally:
        close = getattr(steps, "close", None)
        if close is not None:
            close()
    try:
        request.hasher.digest()
    except RuntimeError as error:
        raise RuntimeError(
            f"el lector «{content_reader.id}» terminó sin entregar sus datos: {error}"
        ) from error


def read_content(
    content_reader: ContentReader,
    request: ReadRequest,
    *,
    progress: Callable[[float], object] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ContentDigest:
    """Lee la fuente con el lector y devuelve su :class:`~.encoder.ContentDigest`.
    ``cancelled()`` se consulta antes de cada trozo (también del primero y del que termina):
    si es verdadero, la lectura para entre dos trozos con :class:`ReadCancelled`;
    ``progress(fracción)`` se llama tras cada trozo."""
    steps = read_steps(content_reader, request)
    done = 0.0
    try:
        while True:
            if cancelled is not None and cancelled():
                raise ReadCancelled(content_reader.id, done)
            try:
                done = next(steps)
            except StopIteration:
                break
            if progress is not None:
                progress(done)
    finally:
        steps.close()
    return request.hasher.digest()


# --- Dónde se hashea ------------------------------------------------------------------------


def plan_hash(content_reader: ContentReader, location: str, stat: object) -> HashPlan:
    """Dónde se hashea una fuente: ``"inline"`` (en el hilo de Blender, por trozos medidos por
    tiempo) o ``"job"`` (en el trabajo ``core_content_hash``).

    ``location`` es su ancla (``gb_input_file.anchor``, :data:`LOCATIONS`): lo que está dentro
    del proyecto (:data:`PROJECT_LOCATIONS`) va siempre en el hilo y nunca a un trabajo. Una
    fuente externa va al trabajo si su lector puede ir (``worker``) y su estimación pasa de
    :data:`INLINE_LIMIT_S` o no se sabe. ``stat`` da su tamaño: el ``os.stat_result`` (o lo que
    tenga ``st_size``) de su fichero, una lista con el de cada uno o los bytes; en el
    proyecto puede ser ``None``."""
    if not isinstance(content_reader, ContentReader):
        raise TypeError(
            f"plan_hash necesita un ContentReader, no {type(content_reader).__name__}"
        )
    if location not in LOCATIONS:
        raise ValueError(
            f"ubicación desconocida: {location!r} (son {', '.join(LOCATIONS)})"
        )
    if location in PROJECT_LOCATIONS:
        return INLINE
    size = _total_size(stat)
    if not content_reader.worker:
        return INLINE
    estimate = None if content_reader.estimate_s is None else content_reader.estimate_s(size)
    if estimate is None:
        return JOB
    if isinstance(estimate, bool) or not isinstance(estimate, numbers.Real):
        raise TypeError(
            f"la estimación del lector «{content_reader.id}» ({estimate!r}) no es un número "
            "de segundos"
        )
    seconds = float(estimate)
    if not math.isfinite(seconds) or seconds < 0.0:
        raise ValueError(
            f"la estimación del lector «{content_reader.id}» ({seconds!r} s) no es un tiempo "
            "válido"
        )
    return JOB if seconds > INLINE_LIMIT_S else INLINE


# --- Comprobaciones -------------------------------------------------------------------------


def _kinds(kinds: object, reader_id: str) -> tuple[str, ...]:
    if isinstance(kinds, str) or not isinstance(kinds, Iterable):
        raise TypeError(
            f"los tipos del lector «{reader_id}» son una lista de tipos de dato, no {kinds!r}"
        )
    found = tuple(kinds)
    if not found:
        raise ValueError(f"el lector «{reader_id}» tiene que dar al menos un tipo de dato")
    for kind in found:
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError(
                f"tipo de dato desconocido en el lector «{reader_id}»: {kind!r} (son "
                f"{sorted(KINDS)})"
            )
    if len(set(found)) != len(found):
        raise ValueError(f"el lector «{reader_id}» repite un tipo de dato: {list(found)}")
    return found


def _files(files: object) -> dict[str, Path]:
    if not isinstance(files, Mapping):
        raise TypeError(
            f"los ficheros de una fuente son un diccionario {{papel: ruta}}, no "
            f"{type(files).__name__}"
        )
    found: dict[str, Path] = {}
    for role, path in files.items():
        if not isinstance(role, str) or _ROLE.fullmatch(role) is None:
            raise ValueError(
                f"el papel de un fichero ({role!r}) es un nombre en minúsculas, como «main» o "
                "«prj»"
            )
        found[role] = Path(os.fspath(path))  # type: ignore[arg-type]
    if MAIN_ROLE not in found:
        raise ValueError(
            f"una fuente necesita su fichero principal («{MAIN_ROLE}»); tiene {sorted(found)}"
        )
    return found


def _check_pair(content_reader: ContentReader, request: ReadRequest) -> None:
    if not isinstance(content_reader, ContentReader):
        raise TypeError(f"se lee con un ContentReader, no {type(content_reader).__name__}")
    if not isinstance(request, ReadRequest):
        raise TypeError(f"se lee una ReadRequest, no {type(request).__name__}")
    if request.reader != content_reader.id:
        raise ValueError(
            f"la petición es para el lector «{request.reader}» y se quiere leer con "
            f"«{content_reader.id}»: cada dato se lee con su lector (ADR-0024 §6)"
        )
    if request.kind not in content_reader.kinds:
        raise ValueError(
            f"el lector «{content_reader.id}» da {list(content_reader.kinds)}, no "
            f"«{request.kind}»"
        )


def _progress(value: object, last: float, reader_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(
            f"el lector «{reader_id}» dio un progreso que no es un número: {value!r}"
        )
    number = float(value)
    if not 0.0 <= number <= 1.0:  # también NaN
        raise ValueError(
            f"el lector «{reader_id}» dio un progreso fuera de [0, 1]: {number!r}"
        )
    if number < last:
        raise ValueError(
            f"el progreso del lector «{reader_id}» retrocede: de {last!r} a {number!r}"
        )
    return number


def _total_size(stat: object) -> int:
    """Los bytes de una fuente: de un ``stat`` (``st_size``), de una lista de ellos o un
    entero."""
    if stat is None or isinstance(stat, bool):
        raise TypeError(
            "una fuente externa necesita su tamaño: el stat de su fichero, una lista con el de "
            f"cada uno o los bytes, no {stat!r}"
        )
    if isinstance(stat, numbers.Integral):
        size = int(stat)
    elif hasattr(stat, "st_size"):
        size = _total_size(stat.st_size)
    elif isinstance(stat, Iterable) and not isinstance(stat, str | bytes):
        size = sum(_total_size(item) for item in stat)
    else:
        raise TypeError(
            f"el tamaño de una fuente es un stat, una lista de stat o los bytes, no {stat!r}"
        )
    if size < 0:
        raise ValueError(f"el tamaño de una fuente ({size} bytes) no puede ser negativo")
    return size
