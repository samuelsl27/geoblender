# SPDX-License-Identifier: GPL-3.0-or-later
"""El normalizador ``gbch/1``: forma canónica y hashes de datos y de contenido (spec 008;
RF-008-08; ADR-0024 §1, §2, §4 y §6; plan 008 §5.4.1).

**Secciones.** Todo lo que se hashea es una secuencia de secciones: etiqueta ASCII de 4
bytes, longitud del contenido en ``uint64`` *little-endian* y contenido. El hash de
**contenido** (``content_sha256``) es el sha256 de tres secciones:

- ``HEAD``: el JSON canónico (``core.hashing.canonical_json``) de ``{"kind", "normalizer"}``;
- ``DECL``: el JSON canónico de las declaraciones del importador (CRS horizontal y vertical
  declarados, convenios que son contenido…);
- ``DATA``: los 32 bytes del hash de **datos** (``data_sha256``).

El hash de datos es el sha256 de la forma normalizada de lo leído, por tipo: una sección con
su cabecera en JSON canónico y una sección ``VALS`` con sus valores. Dentro de un flujo, un
hash siempre va en sus 32 bytes (no en hexadecimal). Por tipo:

- **Rejilla** (:meth:`ContentHasher.grid`, :class:`GridEncoder`): sección ``GRID`` con la
  cabecera en JSON canónico y sección ``VALS`` con las celdas por filas de norte a sur, en
  ``float64`` (clase ``float``: un float32 se amplía sin pérdida, todo NaN es el canónico
  ``0x7FF8000000000000`` y −0,0 es 0,0) o en ``int64`` (clases ``int`` y ``bool``), siempre
  *little-endian*. Teselas, bloques de lectura, orden de bytes y orden de la memoria no
  influyen. La cabecera (:data:`GRID_KEYS`, todas obligatorias):

  - ``rows`` y ``columns``: enteros positivos;
  - ``x0`` e ``y0``: la referencia de la primera celda (la del noroeste) tal como la da el
    fichero —su esquina noroeste con ``cell = "area"`` y su centro con ``"point"``—; ``dx`` y
    ``dy``: el tamaño de celda, positivos (las filas van de norte a sur: la fila ``i`` está en
    ``y0 − i·dy``); los cuatro, float64 exactos y finitos (sin giro);
  - ``cell``: ``"area"`` o ``"point"`` (:data:`CELL_TYPES`);
  - ``class``: ``"float"``, ``"int"`` o ``"bool"`` (:data:`GRID_CLASSES`);
  - ``nodata``: el valor de sin dato o ``None`` (un flotante canónico con ``float``, un
    entero con ``int`` y ``bool``);
  - ``crs``: el CRS que trae el fichero, ``{"epsg": n}`` o ``None`` (nunca el texto de sus
    GeoKeys). El CRS **declarado** al importar va en ``DECL``.

- **Documento** (:meth:`ContentHasher.document`, :class:`DocumentEncoder`): sus bytes sin más;
  el hash de datos es su huella (``core.hashing.sha256_file``).
- **Compuesto** (:meth:`ContentHasher.composite`): sección ``PART`` con
  ``{"parts": [[nombre, tipo], …]}`` ordenadas por nombre (punto de código) y sección ``VALS``
  con el hash de datos de cada parte en ese orden (una tabla por parte en unos sondeos; el
  ``.prj`` de un ASC es una parte).
- **Vectorial** (:meth:`ContentHasher.features`, :class:`FeatureEncoder`): sección ``FEAT``
  con ``{"count", "crs", "dims", "fields"}`` —número de entidades, CRS de la capa
  (``{"epsg": n}`` o ``None``), dimensiones que conserva el importador (:data:`.wkb.DIMS`) y
  campos ``[nombre, tipo]`` ordenados por nombre— y sección ``VALS`` con el sha256 de cada
  entidad, **ordenados** (un multiconjunto: el orden y el número interno de las entidades no
  cuentan y dos iguales cuentan dos veces). El sha256 de una entidad es el de su geometría en
  WKB ISO *little-endian* con dobles canónicos (:func:`.wkb.canonical_wkb`: el orden de bytes
  y las banderas extendidas del original no influyen; vacía, su WKB ISO vacío; nula, el byte
  ``0x00``) seguida del JSON canónico de sus atributos por nombre, cada valor convertido al
  tipo declarado de su campo (:data:`FIELD_TYPES`; nulo, ``null``).
- **Tabla** (:meth:`ContentHasher.rows`, :class:`RowEncoder`): sección ``TABL`` con
  ``{"columns", "count", "ordered"}`` —columnas ``[nombre, tipo]`` en el orden declarado— y
  sección ``VALS`` con el sha256 del JSON canónico de los valores de cada fila (ya
  interpretados y convertidos al tipo de su columna): en orden si ``ordered`` es verdadero y,
  si el importador declara que el orden no importa, ordenados. Un lote grande se codifica
  por columnas (spec 005, T52), con los mismos bytes.
- **Malla** (:meth:`ContentHasher.mesh`; por pasos, :class:`MeshEncoder`, spec 009, T11):
  sección ``MESH`` con ``{"arrays", "meta"}``
  —``[nombre, clase, forma]`` de cada array, ordenados por nombre, y de ``meta`` solo las
  claves que son contenido (:data:`MESH_META_KEYS`; la que falta, ``null``)— y sección
  ``VALS`` con los valores de cada array en ese orden y en orden C: flotantes en float64
  canónico, enteros y booleanos en int64. El orden de los vértices y de las caras cuenta.
- **Nube de puntos** (:meth:`ContentHasher.points`, :class:`PointEncoder`): sección ``PNTS``
  con ``{"columns", "count", "ordered"}`` —columnas ``[nombre, clase]`` en el orden declarado,
  clases de :data:`GRID_CLASSES`— y sección ``VALS`` con el sha256 (32 bytes) de los
  registros: cada punto, sus columnas en float64 canónico o int64 *little-endian*, punto a
  punto; con ``ordered`` falso, los registros ordenados byte a byte. El número de puntos solo
  se sabe al final: por eso ``VALS`` lleva su sha256 y no los registros, y los puntos en
  orden se hashean por bloques con memoria acotada (sin orden, quedan todos en memoria).

Una versión publicada no cambia nunca (unos vectores de referencia la fijan,
``tests/data/core/content/golden_gbch1.json``): cualquier cambio de forma es un normalizador
nuevo. Las entradas del lector no se modifican: el normalizador trabaja sobre copias, por
trozos de :data:`GRID_CHUNK_CELLS` celdas como mucho (memoria acotada a un trozo más el
bloque que da el lector, y 32 bytes por entidad o fila). Un bloque o un lote se comprueba
entero antes de hashear nada de él: si no vale, el codificador queda como estaba. Una capa o
una tabla de millones de elementos cierra su hash por pasos (``finish_steps``, T67): los
sha256 sin orden se agrupan por su primer byte, cada grupo se ordena aparte y la sección
``VALS`` se hashea por trozos, con los mismos bytes (y el mismo hash) que ``finish()``. Python
puro y numpy (ADR-0004).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import numbers
import operator
import re
import struct
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from json.encoder import encode_basestring
from typing import Any

import numpy as np

from ..hashing import CANONICAL_NAN_BITS, canonical_float, canonical_json
from .wkb import canonical_wkb, check_dims

try:  # el sha256 de HACL* de CPython (biblioteca estándar): el mismo resultado, unas 3 veces
    # más deprisa que el de OpenSSL con los cientos de bytes de una fila o una entidad (T52)
    from _sha2 import sha256 as _item_sha256
except ImportError:  # pragma: no cover - un Python compilado sin él
    _item_sha256 = hashlib.sha256

NORMALIZER = "gbch/1"
"""El normalizador vigente: el de las entradas y los datos nuevos (ADR-0024 §6)."""
NORMALIZERS: frozenset[str] = frozenset({NORMALIZER})
"""Los normalizadores que sabe calcular este Geoblender (todos los publicados)."""
KINDS: frozenset[str] = frozenset(
    {
        "raster",
        "vector",
        "table",
        "drillholes",
        "mesh",
        "point_cloud",
        "document",
        "other",
        "block_model",
        "block_field",
        "report",
    }
)
"""Los tipos de entrada y de dato (``gb_input.kind`` y ``gb_dataset.kind``, plan 008 §5.2.1)."""
CELL_TYPES: tuple[str, ...] = ("area", "point")
GRID_CLASSES: tuple[str, ...] = ("float", "int", "bool")
GRID_KEYS: frozenset[str] = frozenset(
    {"rows", "columns", "x0", "y0", "dx", "dy", "cell", "class", "nodata", "crs"}
)
"""Las claves de la cabecera de una rejilla: todas, y ninguna más."""
GRID_CHUNK_CELLS = 1 << 20
"""Celdas que se convierten y se hashean de una vez (8 MiB en float64); como poco, una fila.
También los valores de una malla y de una nube de puntos."""
FINISH_STEP = 1 << 15
"""Elementos (sha256 de entidades o de filas) que se ordenan y se hashean como poco entre dos
pasos de ``finish_steps`` (unos 20 ms; T67)."""
COLUMN_BATCH_ROWS = 16
"""Filas de un lote desde las que :meth:`RowEncoder.update` lo codifica por columnas (spec 005,
T52); un lote más corto, fila a fila."""
FIELD_TYPES: tuple[str, ...] = ("blob", "bool", "date", "datetime", "float", "int", "text")
"""Los tipos de un campo de una capa o de una columna de una tabla. Cada valor se convierte
al de su campo: ``float`` (un real; NaN, ±inf, −0,0 canónicos), ``int`` (un entero o un real
entero), ``bool`` (un booleano o 0 y 1), ``text`` (un texto, exacto), ``date`` (una fecha o su
texto ``AAAA-MM-DD``), ``datetime`` (una fecha y hora con zona o su texto ISO 8601 con zona;
se escribe en UTC) y ``blob`` (bytes)."""
MESH_META_KEYS: tuple[str, ...] = ("closed", "crs_epsg", "kind")
"""Las claves de ``meta`` de una malla que son contenido (ADR-0024 §4); las demás
(``schema``, ``volume_m3``, ``operation_uid``…) no cuentan."""
NULL_GEOMETRY = b"\x00"
"""Lo que se hashea en lugar del WKB de una geometría nula (un WKB empieza por 0 o 1 y tiene
al menos 5 bytes: no se confunde)."""

LABEL_HEAD = b"HEAD"
LABEL_DECL = b"DECL"
LABEL_DATA = b"DATA"
LABEL_GRID = b"GRID"
LABEL_PART = b"PART"
LABEL_FEATURES = b"FEAT"
LABEL_TABLE = b"TABL"
LABEL_MESH = b"MESH"
LABEL_POINTS = b"PNTS"
LABEL_VALUES = b"VALS"

_CELL_BYTES = 8
_DIGEST_BYTES = 32
_GROUPS = 256  # los grupos de los sha256 sin orden, por su primer byte
_INT64_MAX = (1 << 63) - 1
_SHA256_TEXT = re.compile(r"[0-9a-f]{64}")
_DATE_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_EXACT_TYPES: dict[str, type] = {"float": float, "int": int, "bool": bool, "text": str}
"""El tipo de Python que ya tiene la forma canónica de cada tipo de campo (un ``float`` la
toma en ``canonical_json``: NaN, infinitos y −0,0)."""
_NONE_TYPE = type(None)
_NULL_TEXT = "null"
_FLOAT_MARKS: dict[str, str] = {
    "nan": '{"nan":true}',
    "inf": '{"inf":1}',
    "-inf": '{"inf":-1}',
    "-0.0": "0.0",
}
"""El JSON canónico de los reales cuyo ``repr`` no lo es (``repr`` da «nan» con cualquier NaN)."""
_FLOAT_MARK_TEXTS = frozenset(_FLOAT_MARKS)
_ROW_TYPES = frozenset({list, tuple})
_READER_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+@[1-9][0-9]*")
_SIZE = struct.Struct("<Q")


@dataclass(frozen=True, slots=True)
class ContentDigest:
    """Los hashes de una entrada o de un dato (ADR-0024 §1) y con qué se calcularon, que se
    guardan con él para siempre (§6): ``data_sha256`` (la forma normalizada de lo leído),
    ``content_sha256`` (cabecera, declaraciones y datos), ``normalizer`` (``"gbch/1"``) y
    ``reader`` (``"gis.geotiff@1"``; vacío si no lo dio un lector registrado)."""

    data_sha256: str
    content_sha256: str
    normalizer: str
    reader: str

    def __post_init__(self) -> None:
        for name in ("data_sha256", "content_sha256"):
            _check_sha256(getattr(self, name), name)
        if not isinstance(self.normalizer, str) or not self.normalizer:
            raise ValueError("el normalizador de un hash no puede quedar vacío")
        if not isinstance(self.reader, str):
            raise TypeError(f"el lector {self.reader!r} no es un texto")


def content_sha256(
    kind: str,
    declarations: Mapping[str, Any],
    data_sha256: str,
    *,
    normalizer: str = NORMALIZER,
) -> str:
    """El hash de contenido de unos datos ya hasheados: ``HEAD``, ``DECL`` y ``DATA``."""
    _check_kind(kind)
    _check_normalizer(normalizer)
    _check_sha256(data_sha256, "data_sha256")
    return _content(_head(kind, normalizer), _declarations(declarations), data_sha256)


class GridEncoder:
    """El hash de datos de una rejilla, alimentado por bloques de filas de norte a sur.

    ``update(block)`` admite una fila (1-D) o un bloque de filas (2-D) de cualquier tamaño y
    con cualquier orden de bytes o de memoria; ``finish()`` comprueba que llegaron todas las
    filas y devuelve el hash de datos. Ni la cabecera ni los bloques se modifican.

    Clase ``float``: celdas de flotantes de hasta 8 bytes o de enteros de hasta 4 (que se
    convierten sin pérdida). Clase ``int``: enteros que caben en ``int64``. Clase ``bool``:
    booleanos o enteros 0 y 1. Lo demás es ``TypeError`` o ``ValueError``."""

    def __init__(
        self, header: Mapping[str, Any], *, on_finish: Callable[[str], None] | None = None
    ) -> None:
        self.header: dict[str, Any] = _grid_header(header)
        self.rows: int = self.header["rows"]
        self.columns: int = self.header["columns"]
        self.value_class: str = self.header["class"]
        self.rows_done = 0
        self._on_finish = on_finish
        self._finished = False
        self._broken = False
        self._digest = hashlib.sha256()
        self._digest.update(_section(LABEL_GRID, canonical_json(self.header)))
        self._digest.update(LABEL_VALUES + _SIZE.pack(self.rows * self.columns * _CELL_BYTES))

    def _check_open(self) -> None:
        if self._broken:
            raise RuntimeError(
                "un error dejó un bloque de la rejilla a medias: su hash ya no vale"
            )
        if self._finished:
            raise RuntimeError("la rejilla ya está terminada: no admite más filas")

    def update(self, block: object) -> None:
        """Añade un bloque de filas (las siguientes, de norte a sur). Si algo falla mientras
        se hashea el bloque, la rejilla ya no admite nada (``RuntimeError``)."""
        self._check_open()
        array = np.asarray(block)
        if array.ndim == 1:
            array = array.reshape(1, -1)
        if array.ndim != 2:
            raise ValueError(
                f"un bloque de una rejilla tiene que ser una fila o una matriz de filas, no "
                f"un array de {array.ndim} dimensiones"
            )
        count, columns = array.shape
        if count == 0:
            return
        if columns != self.columns:
            raise ValueError(
                f"un bloque de la rejilla tiene {columns} columnas y la cabecera dice "
                f"{self.columns}"
            )
        if self.rows_done + count > self.rows:
            raise ValueError(
                f"la rejilla recibe más filas ({self.rows_done + count}) de las que dice su "
                f"cabecera ({self.rows})"
            )
        check, convert = _converter(self.value_class, array.dtype)
        step = max(1, GRID_CHUNK_CELLS // self.columns)
        if check is not None:  # todo el bloque, antes de hashear nada de él
            for top in range(0, count, step):
                check(array[top:top + step])
        try:
            for top in range(0, count, step):
                self._digest.update(convert(array[top:top + step]))
        except BaseException:
            self._broken = True
            raise
        self.rows_done += count

    def finish(self) -> str:
        """El hash de datos; ``ValueError`` si faltan filas."""
        self._check_open()
        if self.rows_done != self.rows:
            raise ValueError(
                f"la rejilla recibió {self.rows_done} filas y su cabecera dice {self.rows}"
            )
        self._finished = True
        data = self._digest.hexdigest()
        if self._on_finish is not None:
            self._on_finish(data)
        return data


class DocumentEncoder:
    """El hash de datos de un documento: el sha256 de sus bytes, por trozos (su huella)."""

    def __init__(self, *, on_finish: Callable[[str], None] | None = None) -> None:
        self.bytes_done = 0
        self._on_finish = on_finish
        self._finished = False
        self._digest = hashlib.sha256()

    def update(self, chunk: bytes | bytearray | memoryview) -> None:
        """Añade los bytes siguientes."""
        if self._finished:
            raise RuntimeError("el documento ya está terminado: no admite más bytes")
        if not isinstance(chunk, bytes | bytearray | memoryview):
            raise TypeError(
                f"un trozo de documento son bytes, no {type(chunk).__name__}: un texto se "
                "codifica antes"
            )
        self._digest.update(chunk)
        self.bytes_done += memoryview(chunk).nbytes

    def finish(self) -> str:
        """El hash de datos (la huella de los bytes recibidos)."""
        if self._finished:
            raise RuntimeError("el documento ya está terminado")
        self._finished = True
        data = self._digest.hexdigest()
        if self._on_finish is not None:
            self._on_finish(data)
        return data


class _Collector:
    """Lo común de las entidades y las filas: el sha256 de cada elemento (32 bytes en
    memoria por elemento), por lotes que se comprueban enteros antes de añadirse.

    Sin orden, los sha256 se guardan en :data:`_GROUPS` grupos por su primer byte: al cerrar,
    cada grupo se ordena aparte y los grupos van en el orden de ese byte, que es el mismo
    orden que ``sorted`` sobre todos (lexicográfico por bytes), por trozos (T67)."""

    _what = "los elementos"

    def __init__(self, on_finish: Callable[[str], None] | None, *, ordered: bool) -> None:
        self.count = 0
        self._ordered = ordered
        self._groups: list[list[bytes]] = [[] for _ in range(1 if ordered else _GROUPS)]
        self._on_finish = on_finish
        self._finished = False

    def _check_open(self) -> None:
        if self._finished:
            raise RuntimeError(f"{self._what} ya se cerraron con finish(): no admiten más")

    def _item(self, item: object) -> bytes:  # pragma: no cover - lo da cada subclase
        raise NotImplementedError

    def _extend(self, items: Iterable[object]) -> None:
        self._check_open()
        self._add_digests([self._item(item) for item in items])  # todo el lote, antes

    def _add_digests(self, batch: list[bytes]) -> None:
        """Añade los sha256 de un lote ya comprobado entero."""
        if self._ordered:
            self._groups[0].extend(batch)
        else:
            groups = self._groups
            for digest in batch:
                groups[digest[0]].append(digest)
        self.count += len(batch)

    def _finish_steps(
        self, label: bytes, header: Mapping[str, Any], step: object
    ) -> Generator[float, None, str]:
        """Comprueba ``step`` y cierra (aunque los pasos no se recorran): los pasos del hash
        de datos, que se entrega (``on_finish``) y se devuelve al acabar."""
        size = _step(step)
        self._check_open()
        self._finished = True
        return self._hash_steps(label, canonical_json(header), size)

    def _hash_steps(self, label: bytes, header: bytes, step: int) -> Generator[float, None, str]:
        # La sección VALS sin juntar sus valores: etiqueta, longitud y los sha256 por trozos.
        stream = hashlib.sha256(_section(label, header))
        stream.update(LABEL_VALUES + _SIZE.pack(self.count * _DIGEST_BYTES))
        groups, self._groups = self._groups, []
        done = since = 0
        for piece in _pieces(groups, self._ordered, step):
            stream.update(b"".join(piece))
            done += len(piece)
            since += len(piece)
            if since >= step and done < self.count:
                since = 0
                yield done / self.count
        data = stream.hexdigest()
        if self._on_finish is not None:
            self._on_finish(data)
        return data


def _pieces(groups: list[list[bytes]], ordered: bool, step: int) -> Iterator[list[bytes]]:
    """Los sha256 en el orden de la sección ``VALS``: en orden, por trozos de ``step``; sin
    orden, cada grupo de su primer byte ordenado, de uno en uno (lo hecho se suelta)."""
    if ordered:
        (digests,) = groups
        for start in range(0, len(digests), step):
            yield digests[start:start + step]
        return
    for index, group in enumerate(groups):
        groups[index] = []
        group.sort()
        yield group


def _step(value: object) -> int:
    """Los elementos de un paso de ``finish_steps``: un entero positivo."""
    if isinstance(value, bool | np.bool_) or not isinstance(value, numbers.Integral):
        raise TypeError(f"los elementos de un paso («step», {value!r}) son un número entero")
    number = operator.index(value)
    if number < 1:
        raise ValueError(f"los elementos de un paso («step», {number}) tienen que ser positivos")
    return number


def _drain(steps: Generator[float, None, str]) -> str:
    """Recorre los pasos de un cierre y devuelve su hash de datos."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


class FeatureEncoder(_Collector):
    """El hash de datos de una capa vectorial: un multiconjunto de entidades.

    ``fields``: los campos, ``{nombre: tipo}`` o pares ``[nombre, tipo]`` (tipos de
    :data:`FIELD_TYPES`; el orden no cuenta); ``dims``: las dimensiones que conserva el
    importador (``"XY"``, ``"XYZ"``, ``"XYM"`` o ``"XYZM"``); ``crs``: el CRS de la capa,
    ``{"epsg": n}`` o ``None``. Cada entidad es ``(geometría, atributos)``: su WKB (ISO o
    extendido, de cualquier orden de bytes) o ``None`` si es nula, y ``{campo: valor}`` con
    todos los campos (``None`` es un atributo nulo). ``add`` añade una y ``update`` un lote
    (que se comprueba entero: si una entidad no vale, no se añade ninguna). ``finish`` da el
    hash de una vez y ``finish_steps``, por pasos (una capa de millones de entidades)."""

    _what = "las entidades de la capa"

    def __init__(
        self,
        fields: Mapping[str, str] | Iterable[Iterable[str]],
        dims: str,
        crs: Mapping[str, int] | None,
        *,
        on_finish: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(on_finish, ordered=False)
        self.fields: list[tuple[str, str]] = sorted(_named_types(fields, FIELD_TYPES, "campo"))
        self.dims: str = check_dims(dims)
        self.crs: dict[str, int] | None = _crs(crs, "el CRS de la capa")
        self._types = dict(self.fields)

    def add(
        self, geometry: bytes | bytearray | memoryview | None, attributes: Mapping[str, Any]
    ) -> None:
        """Añade una entidad."""
        self._extend([(geometry, attributes)])

    def update(self, features: Iterable[object]) -> None:
        """Añade un lote de entidades ``(geometría, atributos)``."""
        self._extend(features)

    def finish(self) -> str:
        """El hash de datos de la capa."""
        return _drain(self.finish_steps())

    def finish_steps(self, step: int = FINISH_STEP) -> Generator[float, None, str]:
        """El hash de datos de la capa por pasos (T67; RNF-008-11): cierra la capa y devuelve
        un generador que da el avance (0–1) cada ``step`` entidades como poco y, al acabar,
        entrega el hash (``on_finish``) y lo devuelve (``StopIteration.value``). Cada paso es
        un punto de cancelación: dejarlo a medias no entrega nada. El mismo hash que
        :meth:`finish`."""
        header = {
            "count": self.count,
            "crs": self.crs,
            "dims": self.dims,
            "fields": [[name, kind] for name, kind in self.fields],
        }
        return self._finish_steps(LABEL_FEATURES, header, step)

    def _item(self, item: object) -> bytes:
        geometry, attributes = _pair(item, "una entidad", "(geometría, atributos)")
        shape = NULL_GEOMETRY if geometry is None else canonical_wkb(geometry, self.dims)
        if type(attributes) is not dict and not isinstance(attributes, Mapping):
            raise TypeError(
                f"los atributos de una entidad son un diccionario {{campo: valor}}, no "
                f"{type(attributes).__name__}"
            )
        _same_names(attributes, self._types, "los atributos de una entidad", "campos")
        values = {
            name: _field_value(kind, attributes[name], f"el atributo «{name}»")
            for name, kind in self.fields
        }
        return _item_sha256(shape + canonical_json(values)).digest()


class RowEncoder(_Collector):
    """El hash de datos de una tabla, fila a fila.

    ``columns``: ``{nombre: tipo}`` o pares ``[nombre, tipo]`` en el orden declarado (al menos
    una; tipos de :data:`FIELD_TYPES`); ``ordered``: si el orden de las filas es contenido.
    Cada fila es una secuencia con un valor por columna, en ese orden, o un diccionario con
    todas las columnas; sus valores llegan ya interpretados (el «1,5» de un CSV es 1.5) y se
    convierten al tipo de su columna. ``add`` añade una, ``update`` un lote y
    ``update_columns`` un lote dado por columnas (cada lote se comprueba entero). ``finish`` da
    el hash de una vez y ``finish_steps``, por pasos.

    Un lote de :data:`COLUMN_BATCH_ROWS` filas o más (en listas o tuplas) o dado por columnas
    se codifica **por columnas** (spec 005, T52): el texto JSON canónico de cada valor de una
    columna cuyos valores son todos de su tipo exacto (``float``, ``int``, ``str`` o ``bool``,
    o nulos) sale de una vez para toda la columna (``repr``, el de ``json`` para los textos,
    las marcas de NaN e infinitos y 0,0 por −0,0), y el de las demás, valor a valor con
    ``canonical_json``; cada fila es ``[`` + sus textos separados por comas + ``]``, el mismo
    JSON canónico, y el mismo hash, que fila a fila. Si algo no vale, el lote se vuelve a
    hacer fila a fila: el error es el de siempre (el de la primera fila que no vale)."""

    _what = "las filas de la tabla"

    def __init__(
        self,
        columns: Mapping[str, str] | Iterable[Iterable[str]],
        ordered: bool,
        *,
        on_finish: Callable[[str], None] | None = None,
    ) -> None:
        named = _named_types(columns, FIELD_TYPES, "columna")
        if not named:
            raise ValueError("una tabla necesita al menos una columna")
        flag = _flag(ordered, "ordered")
        super().__init__(on_finish, ordered=flag)
        self.columns: list[tuple[str, str]] = named
        self.ordered: bool = flag
        self._names = {name: kind for name, kind in self.columns}

    def add(self, row: object) -> None:
        """Añade una fila."""
        self._extend([row])

    def update(self, rows: Iterable[object]) -> None:
        """Añade un lote de filas."""
        self._extend(rows)

    def update_columns(self, columns: Sequence[Sequence[object]]) -> None:
        """Añade un lote de filas dado por columnas: una secuencia por columna de la tabla, en
        su orden y del mismo largo (las filas); el mismo hash que :meth:`update` con esas
        filas. ``ValueError`` con otro número de columnas o columnas de distinto largo y
        ``TypeError`` si no son secuencias, sin añadir nada."""
        self._check_open()
        if isinstance(columns, str | bytes | bytearray) or not isinstance(columns, Sequence):
            raise TypeError(
                f"las columnas de un lote son una secuencia por columna, no "
                f"{type(columns).__name__}"
            )
        if len(columns) != len(self.columns):
            raise ValueError(
                f"el lote tiene {len(columns)} columnas y la tabla {len(self.columns)}"
            )
        for (name, _kind), column in zip(self.columns, columns, strict=True):
            if isinstance(column, str | bytes | bytearray | Mapping) or not isinstance(
                column, Sequence
            ):
                raise TypeError(
                    f"la columna «{name}» de un lote es una secuencia de valores, no "
                    f"{type(column).__name__}"
                )
        lengths = {len(column) for column in columns}
        if len(lengths) != 1:
            raise ValueError(
                f"las columnas de un lote tienen largos distintos: {sorted(lengths)}"
            )
        (count,) = lengths
        if not count:
            return
        digests = self._column_digests(columns)
        if digests is None:  # fila a fila: el error de siempre
            digests = [self._item(row) for row in zip(*columns, strict=True)]
        self._add_digests(digests)

    def _extend(self, items: Iterable[object]) -> None:
        self._check_open()
        batch = items if type(items) is list else list(items)
        digests = None
        if len(batch) >= COLUMN_BATCH_ROWS and self._plain_rows(batch):
            digests = self._column_digests(list(zip(*batch, strict=True)))
        if digests is None:  # todo el lote, antes de añadir nada
            digests = [self._item(item) for item in batch]
        self._add_digests(digests)

    def _plain_rows(self, batch: list[object]) -> bool:
        """Si todas las filas son listas o tuplas con un valor por columna."""
        return set(map(type, batch)) <= _ROW_TYPES and set(map(len, batch)) == {
            len(self.columns)
        }

    def _column_digests(self, columns: Sequence[Sequence[object]]) -> list[bytes] | None:
        """Los sha256 de las filas de un lote dado por columnas, o ``None`` si algún valor no
        vale (el lote se hace entonces fila a fila, con su error)."""
        try:
            texts = [
                _column_texts(kind, column, name)
                for (name, kind), column in zip(self.columns, columns, strict=True)
            ]
            lines: Iterable[str] = texts[0] if len(texts) == 1 else map(",".join, zip(*texts))
            sha256 = _item_sha256
            return [sha256(f"[{line}]".encode()).digest() for line in lines]
        except (TypeError, ValueError, ArithmeticError):  # UnicodeEncodeError es ValueError
            return None

    def finish(self) -> str:
        """El hash de datos de la tabla."""
        return _drain(self.finish_steps())

    def finish_steps(self, step: int = FINISH_STEP) -> Generator[float, None, str]:
        """El hash de datos de la tabla por pasos, como :meth:`FeatureEncoder.finish_steps`."""
        header = {
            "columns": [[name, kind] for name, kind in self.columns],
            "count": self.count,
            "ordered": self.ordered,
        }
        return self._finish_steps(LABEL_TABLE, header, step)

    def _item(self, item: object) -> bytes:
        values: Any
        if type(item) is list or type(item) is tuple:
            values = item
        elif isinstance(item, Mapping):
            _same_names(item, self._names, "una fila", "columnas")
            values = [item[name] for name, _ in self.columns]
        elif isinstance(item, str | bytes | bytearray | memoryview) or not isinstance(
            item, Iterable
        ):
            raise TypeError(
                f"una fila es una secuencia de valores o un diccionario {{columna: valor}}, no "
                f"{type(item).__name__}"
            )
        else:
            values = list(item)
        if len(values) != len(self.columns):
            raise ValueError(
                f"una fila tiene {len(values)} valores y la tabla {len(self.columns)} columnas"
            )
        converted = [
            _field_value(kind, value, f"la columna «{name}»")
            for (name, kind), value in zip(self.columns, values, strict=True)
        ]
        return _item_sha256(canonical_json(converted)).digest()


class PointEncoder:
    """El hash de datos de una nube de puntos, por bloques.

    ``columns``: ``{nombre: clase}`` o pares ``[nombre, clase]`` en el orden declarado (al
    menos una; clases ``float``, ``int`` o ``bool``, como las celdas de una rejilla);
    ``ordered`` (por defecto, verdadero): si el orden de los puntos es contenido. Cada bloque
    es un diccionario ``{columna: valores 1-D}`` con todas las columnas y la misma longitud, o
    un array estructurado con esos campos. Un bloque se comprueba entero antes de hashear nada
    de él; si algo falla mientras se hashea, la nube ya no admite nada (``RuntimeError``)."""

    def __init__(
        self,
        columns: Mapping[str, str] | Iterable[Iterable[str]],
        ordered: bool = True,
        *,
        on_finish: Callable[[str], None] | None = None,
    ) -> None:
        self.columns: list[tuple[str, str]] = _named_types(columns, GRID_CLASSES, "columna")
        if not self.columns:
            raise ValueError("una nube de puntos necesita al menos una columna")
        self.ordered: bool = _flag(ordered, "ordered")
        self.count = 0
        self._names = {name: kind for name, kind in self.columns}
        self._digest = hashlib.sha256()
        self._records: list[np.ndarray] = []
        self._on_finish = on_finish
        self._finished = False
        self._broken = False

    def _check_open(self) -> None:
        if self._broken:
            raise RuntimeError(
                "un error dejó un bloque de la nube de puntos a medias: su hash ya no vale"
            )
        if self._finished:
            raise RuntimeError("la nube de puntos ya está terminada: no admite más puntos")

    def update(self, block: Mapping[str, object] | np.ndarray) -> None:
        """Añade un bloque de puntos (los siguientes)."""
        self._check_open()
        columns = self._columns(block)
        count = len(columns[0])
        converters: list[_Cells] = []
        for (_, value_class), column in zip(self.columns, columns, strict=True):
            check, convert = _converter(value_class, column.dtype)
            if check is not None:  # todo el bloque, antes de hashear nada de él
                check(column)
            converters.append(convert)
        width = len(self.columns)
        step = max(1, GRID_CHUNK_CELLS // width)
        try:
            for top in range(0, count, step):
                size = min(step, count - top)
                records = np.empty((size, width), dtype="<u8")
                for index, (convert, column) in enumerate(zip(converters, columns, strict=True)):
                    records[:, index] = convert(column[top:top + size]).view("<u8")
                if self.ordered:
                    self._digest.update(records)
                else:
                    self._records.append(records)
        except BaseException:
            self._broken = True
            raise
        self.count += count

    def finish(self) -> str:
        """El hash de datos de la nube de puntos."""
        self._check_open()
        self._finished = True
        if self.ordered:
            inner = self._digest.digest()
        else:
            inner = hashlib.sha256(_sorted_records(self._records)).digest()
            self._records = []
        header = {
            "columns": [[name, kind] for name, kind in self.columns],
            "count": self.count,
            "ordered": self.ordered,
        }
        stream = _section(LABEL_POINTS, canonical_json(header)) + _section(LABEL_VALUES, inner)
        data = hashlib.sha256(stream).hexdigest()
        if self._on_finish is not None:
            self._on_finish(data)
        return data

    def _columns(self, block: object) -> list[np.ndarray]:
        if isinstance(block, np.ndarray) and block.dtype.names is not None:
            source: Mapping[str, object] = {name: block[name] for name in block.dtype.names}
        elif isinstance(block, Mapping):
            source = block
        else:
            raise TypeError(
                "un bloque de puntos es un diccionario {columna: valores} o un array "
                f"estructurado, no {type(block).__name__}"
            )
        _same_names(source, self._names, "un bloque de puntos", "columnas")
        columns = [np.asarray(source[name]) for name, _ in self.columns]
        for (name, _), column in zip(self.columns, columns, strict=True):
            if column.ndim != 1:
                raise ValueError(
                    f"la columna «{name}» de un bloque de puntos tiene que ser 1-D, no de "
                    f"{column.ndim} dimensiones"
                )
        lengths = {len(column) for column in columns}
        if len(lengths) != 1:
            raise ValueError(
                f"las columnas de un bloque de puntos tienen longitudes distintas: "
                f"{sorted(lengths)}"
            )
        return columns


class MeshEncoder:
    """El hash de datos de una malla (ver :meth:`ContentHasher.mesh`), de una vez
    (:meth:`finish`) o por pasos (:meth:`finish_steps`; spec 009, T11, D-30: una malla de
    millones de vértices se comprueba en el hilo de Blender sin pasar de 0,2 s por llamada).

    Al crearlo se comprueban el diccionario de arrays, sus nombres y el ``meta``; al cerrar,
    cada array por nombre (su clase y, si hace falta, sus celdas, por trozos de
    :data:`GRID_CHUNK_CELLS`) antes del siguiente y antes de hashear nada: los mismos errores,
    con el mismo texto y en el mismo orden, de una vez o por pasos. Los arrays no se copian ni
    se modifican; el diccionario sí se copia (lo que se añada después no cuenta)."""

    def __init__(
        self,
        arrays: Mapping[str, object],
        meta: Mapping[str, Any],
        *,
        on_finish: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(arrays, Mapping):
            raise TypeError(
                f"los arrays de una malla son un diccionario {{nombre: array}}, no "
                f"{type(arrays).__name__}"
            )
        if not arrays:
            raise ValueError("una malla necesita al menos un array")
        for name in arrays:
            if not isinstance(name, str) or not name:
                raise ValueError(
                    f"el nombre de un array de la malla ({name!r}) tiene que ser un texto"
                )
        self.meta: dict[str, Any] = _mesh_meta(meta)
        self._arrays: dict[str, object] = dict(arrays)
        self._on_finish = on_finish
        self._finished = False

    def finish(self) -> str:
        """El hash de datos de la malla, de una vez."""
        return _drain(self.finish_steps(GRID_CHUNK_CELLS))

    def finish_steps(self, step: int = GRID_CHUNK_CELLS) -> Generator[float, None, str]:
        """El hash de datos de la malla por pasos: cierra la malla y devuelve un generador que
        da el avance (0–1, sin llegar a 1) y, al acabar, entrega el hash (``on_finish``) y lo
        devuelve (``StopIteration.value``). Cada paso convierte y hashea ``step`` celdas como
        mucho (los arrays pequeños, juntos; uno grande, en trozos de filas de ``step`` celdas
        como mucho, y nunca más de :data:`GRID_CHUNK_CELLS`, 8 MiB en float64, salvo una fila
        más larga); comprobar las celdas de un array de enteros sin signo de 8 bytes avanza 0
        (no hay nada hasheado aún). Cada paso es un punto de cancelación: dejarlo a medias no
        entrega nada. El mismo hash que :meth:`finish`."""
        size = _step(step)
        if self._finished:
            raise RuntimeError("la malla ya está terminada")
        self._finished = True
        arrays, self._arrays = self._arrays, {}
        return self._steps(arrays, size)

    def _steps(self, arrays: dict[str, object], step: int) -> Generator[float, None, str]:
        listed: list[list[object]] = []
        blocks: list[tuple[np.ndarray, _Cells]] = []
        since = 0
        for name in sorted(arrays):
            array = np.asarray(arrays[name])
            value_class = _array_class(array.dtype, name)
            check, convert = _converter(value_class, array.dtype)
            rows = _as_rows(array)
            if check is not None:  # todo el array, antes del siguiente y de hashear nada
                for top, count in _chunks(rows):
                    check(rows[top:top + count])
                    since += count * rows.shape[1]
                    if since >= step:
                        since = 0
                        yield 0.0
            listed.append([name, value_class, list(array.shape)])
            blocks.append((rows, convert))
        header = {"arrays": listed, "meta": self.meta}
        stream = hashlib.sha256(_section(LABEL_MESH, canonical_json(header)))
        total = sum(rows.size for rows, _ in blocks)
        stream.update(LABEL_VALUES + _SIZE.pack(total * _CELL_BYTES))
        piece = min(step, GRID_CHUNK_CELLS)
        done = since = 0
        for rows, convert in blocks:
            for top, count in _chunks(rows, piece):
                cells = count * rows.shape[1]
                if since and since + cells > step:  # cada paso, ≤ step celdas (o un trozo)
                    since = 0
                    yield done / total
                stream.update(convert(rows[top:top + count]))
                done += cells
                since += cells
        data = stream.hexdigest()
        if self._on_finish is not None:
            self._on_finish(data)
        return data


def mesh_sha256(arrays: Mapping[str, object], meta: Mapping[str, Any]) -> str:
    """El hash de datos de una malla (ver :meth:`ContentHasher.mesh`)."""
    return MeshEncoder(arrays, meta).finish()


class ContentHasher:
    """Calcula el :class:`ContentDigest` de una entrada o de un dato de tipo ``kind`` (uno
    de :data:`KINDS`) con sus ``declarations`` (un ``Mapping`` con forma JSON canónica: CRS
    declarados, convenios que son contenido…), el identificador de su lector (``reader``,
    p. ej. ``"gis.geotiff@1"``) y su normalizador (por defecto, el vigente).

    Recibe los datos **una vez**, con un método por tipo (:meth:`grid`, :meth:`document`,
    :meth:`composite`, :meth:`features`, :meth:`rows`, :meth:`mesh`, :meth:`points`), o por
    partes con los ``begin_*``, cuyo ``finish()`` los entrega; después, :meth:`digest`. Los
    métodos de datos devuelven el propio objeto:
    ``ContentHasher(…).grid(cabecera, bloques).digest()``."""

    def __init__(
        self,
        kind: str,
        *,
        declarations: Mapping[str, Any],
        reader: str = "",
        normalizer: str = NORMALIZER,
    ) -> None:
        _check_kind(kind)
        _check_normalizer(normalizer)
        if not isinstance(reader, str):
            raise TypeError(f"el lector {reader!r} no es un texto")
        if reader and _READER_ID.fullmatch(reader) is None:
            raise ValueError(
                f"«{reader}» no es un identificador de lector: <módulo>.<nombre>@<versión>, "
                "como «gis.geotiff@1»"
            )
        self.kind = kind
        self.reader = reader
        self.normalizer = normalizer
        self._head = _head(kind, normalizer)
        self._decl = _declarations(declarations)
        self._data: str | None = None
        self._open: (
            GridEncoder
            | DocumentEncoder
            | FeatureEncoder
            | RowEncoder
            | MeshEncoder
            | PointEncoder
            | None
        ) = None

    # --- Rejillas ------------------------------------------------------------------------

    def begin_grid(self, header: Mapping[str, Any]) -> GridEncoder:
        """Empieza una rejilla por partes: su ``finish()`` entrega el hash de datos."""
        self._check_empty()
        feed = GridEncoder(header, on_finish=self._accept)
        self._open = feed
        return feed

    def grid(self, header: Mapping[str, Any], rows: Iterable[object]) -> ContentHasher:
        """Una rejilla con su cabecera y sus filas de norte a sur, en bloques de cualquier
        tamaño (filas 1-D o matrices 2-D)."""
        feed = self.begin_grid(header)
        for block in rows:
            feed.update(block)
        feed.finish()
        return self

    # --- Documentos -----------------------------------------------------------------------

    def begin_document(self) -> DocumentEncoder:
        """Empieza un documento por trozos: su ``finish()`` entrega el hash de datos."""
        self._check_empty()
        feed = DocumentEncoder(on_finish=self._accept)
        self._open = feed
        return feed

    def document(self, chunks: Iterable[bytes | bytearray | memoryview]) -> ContentHasher:
        """Un documento: sus bytes, en trozos de cualquier tamaño."""
        feed = self.begin_document()
        for chunk in chunks:
            feed.update(chunk)
        feed.finish()
        return self

    # --- Compuestos -----------------------------------------------------------------------

    def composite(self, parts: Mapping[str, tuple[str, str]]) -> ContentHasher:
        """Un compuesto: ``{nombre: (tipo, hash de datos)}`` de cada parte (al menos una)."""
        self._check_empty()
        self._accept(composite_sha256(parts))
        return self

    # --- Capas vectoriales ----------------------------------------------------------------

    def begin_features(
        self,
        fields: Mapping[str, str] | Iterable[Iterable[str]],
        dims: str,
        crs: Mapping[str, int] | None,
    ) -> FeatureEncoder:
        """Empieza una capa por lotes: su ``finish()`` entrega el hash de datos."""
        self._check_empty()
        feed = FeatureEncoder(fields, dims, crs, on_finish=self._accept)
        self._open = feed
        return feed

    def features(
        self,
        fields: Mapping[str, str] | Iterable[Iterable[str]],
        dims: str,
        crs: Mapping[str, int] | None,
        features: Iterable[object],
    ) -> ContentHasher:
        """Una capa: sus campos, sus dimensiones, su CRS y sus entidades
        ``(geometría, atributos)`` en cualquier orden (ver :class:`FeatureEncoder`)."""
        feed = self.begin_features(fields, dims, crs)
        feed.update(features)
        feed.finish()
        return self

    # --- Tablas ---------------------------------------------------------------------------

    def begin_rows(
        self, columns: Mapping[str, str] | Iterable[Iterable[str]], ordered: bool
    ) -> RowEncoder:
        """Empieza una tabla por lotes: su ``finish()`` entrega el hash de datos."""
        self._check_empty()
        feed = RowEncoder(columns, ordered, on_finish=self._accept)
        self._open = feed
        return feed

    def rows(
        self,
        columns: Mapping[str, str] | Iterable[Iterable[str]],
        ordered: bool,
        rows: Iterable[object],
    ) -> ContentHasher:
        """Una tabla: sus columnas en el orden declarado, si su orden es contenido y sus filas
        (ver :class:`RowEncoder`)."""
        feed = self.begin_rows(columns, ordered)
        feed.update(rows)
        feed.finish()
        return self

    # --- Mallas ---------------------------------------------------------------------------

    def begin_mesh(self, arrays: Mapping[str, object], meta: Mapping[str, Any]) -> MeshEncoder:
        """Empieza una malla para hashearla por pasos (spec 009, T11): su ``finish()`` o su
        ``finish_steps()`` entrega el hash de datos, el mismo que :meth:`mesh`."""
        self._check_empty()
        feed = MeshEncoder(arrays, meta, on_finish=self._accept)
        self._open = feed
        return feed

    def mesh(self, arrays: Mapping[str, object], meta: Mapping[str, Any]) -> ContentHasher:
        """Una malla: sus arrays por nombre (``vertices``, ``faces``…; flotantes, enteros o
        booleanos) y su ``meta``, de la que solo cuentan :data:`MESH_META_KEYS`. Por pasos,
        :meth:`begin_mesh`."""
        self._check_empty()
        self._accept(MeshEncoder(arrays, meta).finish())
        return self

    # --- Nubes de puntos ------------------------------------------------------------------

    def begin_points(
        self, columns: Mapping[str, str] | Iterable[Iterable[str]], ordered: bool = True
    ) -> PointEncoder:
        """Empieza una nube de puntos por bloques: su ``finish()`` entrega el hash de datos."""
        self._check_empty()
        feed = PointEncoder(columns, ordered, on_finish=self._accept)
        self._open = feed
        return feed

    def points(
        self,
        columns: Mapping[str, str] | Iterable[Iterable[str]],
        ordered: bool,
        blocks: Iterable[Mapping[str, object] | np.ndarray],
    ) -> ContentHasher:
        """Una nube de puntos: sus columnas en el orden declarado, si su orden es contenido y
        sus bloques (ver :class:`PointEncoder`)."""
        feed = self.begin_points(columns, ordered)
        for block in blocks:
            feed.update(block)
        feed.finish()
        return self

    # --- Resultado ------------------------------------------------------------------------

    def digest(self) -> ContentDigest:
        """Los hashes; ``RuntimeError`` si aún no hay datos o están a medias."""
        if self._data is None:
            if self._open is not None:
                raise RuntimeError("los datos están a medias: falta su finish()")
            raise RuntimeError("todavía no hay datos que hashear")
        return ContentDigest(
            data_sha256=self._data,
            content_sha256=_content(self._head, self._decl, self._data),
            normalizer=self.normalizer,
            reader=self.reader,
        )

    def _check_empty(self) -> None:
        if self._data is not None or self._open is not None:
            raise RuntimeError("este ContentHasher ya tiene sus datos: se usa una sola vez")

    def _accept(self, data: str) -> None:
        self._data = data


def composite_sha256(parts: Mapping[str, tuple[str, str]]) -> str:
    """El hash de datos de un compuesto (ver :meth:`ContentHasher.composite`)."""
    if not isinstance(parts, Mapping):
        raise TypeError(
            f"las partes de un compuesto son un diccionario {{nombre: (tipo, hash)}}, no "
            f"{type(parts).__name__}"
        )
    if not parts:
        raise ValueError("un compuesto necesita al menos una parte")
    names = sorted(parts)
    listed: list[list[str]] = []
    digests: list[bytes] = []
    for name in names:
        if not isinstance(name, str) or not name:
            raise ValueError(f"el nombre de una parte ({name!r}) tiene que ser un texto")
        kind, data = parts[name]
        _check_kind(kind)
        _check_sha256(data, f"el hash de datos de la parte «{name}»")
        listed.append([name, kind])
        digests.append(bytes.fromhex(data))
    stream = _section(LABEL_PART, canonical_json({"parts": listed}))
    stream += _section(LABEL_VALUES, b"".join(digests))
    return hashlib.sha256(stream).hexdigest()


# --- Secciones y validación ------------------------------------------------------------------


def _section(label: bytes, payload: bytes) -> bytes:
    return label + _SIZE.pack(len(payload)) + payload


def _head(kind: str, normalizer: str) -> bytes:
    return canonical_json({"kind": kind, "normalizer": normalizer})


def _declarations(declarations: Mapping[str, Any]) -> bytes:
    if not isinstance(declarations, Mapping):
        raise TypeError(
            "las declaraciones son un diccionario (CRS declarados, convenios…), no "
            f"{type(declarations).__name__}"
        )
    return canonical_json(declarations)


def _content(head: bytes, decl: bytes, data_sha256: str) -> str:
    stream = _section(LABEL_HEAD, head) + _section(LABEL_DECL, decl)
    stream += _section(LABEL_DATA, bytes.fromhex(data_sha256))
    return hashlib.sha256(stream).hexdigest()


def _check_kind(kind: object) -> None:
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError(f"tipo de dato desconocido: {kind!r} (son {sorted(KINDS)})")


def _check_normalizer(normalizer: object) -> None:
    if normalizer not in NORMALIZERS:
        raise ValueError(
            f"normalizador desconocido: {normalizer!r} (este Geoblender calcula "
            f"{sorted(NORMALIZERS)})"
        )


def _check_sha256(value: object, name: str) -> None:
    if not isinstance(value, str) or _SHA256_TEXT.fullmatch(value) is None:
        raise ValueError(f"{name} ({value!r}) no es un sha256 en 64 cifras hexadecimales")


def _grid_header(header: Mapping[str, Any]) -> dict[str, Any]:
    """La cabecera canónica de una rejilla (un diccionario nuevo)."""
    if not isinstance(header, Mapping):
        raise TypeError(
            f"la cabecera de una rejilla es un diccionario, no {type(header).__name__}"
        )
    keys = set(header)
    if keys != GRID_KEYS:
        missing = sorted(GRID_KEYS - keys)
        extra = sorted(map(str, keys - GRID_KEYS))
        raise ValueError(
            f"la cabecera de la rejilla no tiene las claves de gbch/1: faltan {missing}, "
            f"sobran {extra}"
        )
    value_class = header["class"]
    if value_class not in GRID_CLASSES:
        raise ValueError(f"clase de celda desconocida: {value_class!r} (son {GRID_CLASSES})")
    cell = header["cell"]
    if cell not in CELL_TYPES:
        raise ValueError(f"tipo de celda desconocido: {cell!r} (son {CELL_TYPES})")
    found: dict[str, Any] = {
        "rows": _positive_int(header["rows"], "rows"),
        "columns": _positive_int(header["columns"], "columns"),
        "x0": _finite(header["x0"], "x0"),
        "y0": _finite(header["y0"], "y0"),
        "dx": _finite(header["dx"], "dx", positive=True),
        "dy": _finite(header["dy"], "dy", positive=True),
        "cell": str(cell),
        "class": str(value_class),
        "nodata": _nodata(header["nodata"], value_class),
        "crs": _crs(header["crs"], "el CRS que trae el fichero"),
    }
    return found


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool | np.bool_) or not isinstance(value, numbers.Integral):
        raise TypeError(f"«{name}» de la rejilla ({value!r}) no es un número entero")
    number = operator.index(value)
    if number < 1:
        raise ValueError(f"«{name}» de la rejilla ({number}) tiene que ser positivo")
    return number


def _finite(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool | np.bool_) or not isinstance(value, numbers.Real):
        raise TypeError(f"«{name}» de la rejilla ({value!r}) no es un número")
    number = canonical_float(value)  # type: ignore[arg-type]
    if not math.isfinite(number):
        raise ValueError(f"«{name}» de la rejilla ({number!r}) no es un número finito")
    if positive and number <= 0.0:
        raise ValueError(f"«{name}» de la rejilla ({number!r}) tiene que ser positivo")
    return number


def _nodata(value: object, value_class: str) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool | np.bool_) or not isinstance(value, numbers.Real):
        raise TypeError(f"el valor de sin dato ({value!r}) no es un número")
    if value_class == "float":
        return canonical_float(value)  # type: ignore[arg-type]
    if isinstance(value, numbers.Integral):
        return operator.index(value)
    number = float(value)
    if not number.is_integer():
        raise ValueError(
            f"el valor de sin dato ({number!r}) no es entero y la rejilla es de clase "
            f"«{value_class}»"
        )
    return int(number)


def _crs(value: object, what: str) -> dict[str, int] | None:
    """``{"epsg": n}`` o ``None``: el CRS de un fichero o de una capa (``what``)."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(f"{what} es {{\"epsg\": n}} o None, no {type(value).__name__}")
    if set(value) != {"epsg"}:
        raise ValueError(f"{what} es {{\"epsg\": n}} o None, no {dict(value)!r}")
    return {"epsg": _epsg(value["epsg"], what)}


def _epsg(code: object, what: str) -> int:
    if isinstance(code, bool | np.bool_) or not isinstance(code, numbers.Integral):
        raise TypeError(f"el código EPSG de {what} ({code!r}) no es un número entero")
    number = operator.index(code)
    if number < 1:
        raise ValueError(f"el código EPSG de {what} ({number}) no es válido")
    return number


# --- Campos, columnas y valores --------------------------------------------------------------


def _named_types(items: object, allowed: tuple[str, ...], what: str) -> list[tuple[str, str]]:
    """Los pares ``(nombre, tipo)`` de un diccionario o de una secuencia de pares, en su
    orden: nombres de texto no vacíos y únicos, tipos de ``allowed``."""
    if isinstance(items, str | bytes) or not isinstance(items, Mapping | Iterable):
        raise TypeError(
            f"se esperaba un diccionario {{nombre: tipo}} o una lista de pares [nombre, tipo] "
            f"({what}), no {type(items).__name__}"
        )
    pairs = list(items.items()) if isinstance(items, Mapping) else [tuple(i) for i in items]
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pair in pairs:
        if len(pair) != 2:
            raise ValueError(f"se esperaba un par [nombre, tipo] ({what}), no {list(pair)!r}")
        name, kind = pair
        if not isinstance(name, str) or not name:
            raise ValueError(f"el nombre ({what}) tiene que ser un texto no vacío: {name!r}")
        if not isinstance(kind, str) or kind not in allowed:
            raise ValueError(
                f"tipo desconocido para «{name}» ({what}): {kind!r} (son {', '.join(allowed)})"
            )
        if name in seen:
            raise ValueError(f"nombre repetido ({what}): «{name}»")
        seen.add(name)
        found.append((str.__str__(name), str.__str__(kind)))
    return found


def _same_names(given: Mapping[str, object], declared: Mapping[str, str], what: str,
                plural: str) -> None:
    if given.keys() == declared.keys():
        return
    names = set(given)
    missing = sorted(set(declared) - names)
    extra = sorted(map(str, names - set(declared)))
    raise ValueError(
        f"{what} no tiene las {plural} declaradas: faltan {missing}, sobran {extra}"
    )


def _pair(item: object, what: str, shape: str) -> tuple[Any, Any]:
    values: Any
    if type(item) is tuple or type(item) is list:
        values = item
    elif isinstance(item, str | bytes | bytearray | memoryview | Mapping) or not isinstance(
        item, Iterable
    ):
        raise TypeError(f"{what} es un par {shape}, no {type(item).__name__}")
    else:
        values = tuple(item)
    if len(values) != 2:
        raise ValueError(f"{what} es un par {shape}, no {len(values)} valores")
    return values[0], values[1]


def _flag(value: object, name: str) -> bool:
    if not isinstance(value, bool | np.bool_):
        raise TypeError(f"«{name}» es verdadero o falso, no {value!r}")
    return bool(value)


def _field_value(kind: str, value: object, where: str) -> object:
    """``value`` convertido al tipo ``kind`` de su campo o columna (``where``), con forma
    JSON canónica; ``None`` es un valor nulo. ``TypeError`` si no es de ese tipo y
    ``ValueError`` si lo es pero no cabe (un 1,5 en un entero, una fecha mal escrita…)."""
    if value is None or type(value) is _EXACT_TYPES.get(kind):
        return value  # el caso de casi todos los valores: ya es del tipo de su campo
    if kind == "float":
        if isinstance(value, bool | np.bool_) or not isinstance(value, numbers.Real):
            raise TypeError(f"{where} es un número (float) y su valor {value!r} no lo es")
        return canonical_float(value)  # type: ignore[arg-type]
    if kind == "int":
        if isinstance(value, bool | np.bool_) or not isinstance(value, numbers.Real):
            raise TypeError(f"{where} es un entero y su valor {value!r} no es un número")
        if isinstance(value, numbers.Integral):
            return operator.index(value)
        number = float(value)
        if not number.is_integer():
            raise ValueError(f"{where} es un entero y su valor {number!r} no lo es")
        return int(number)
    if kind == "bool":
        if isinstance(value, bool | np.bool_):
            return bool(value)
        if isinstance(value, numbers.Integral):
            number = operator.index(value)
            if number in (0, 1):
                return bool(number)
            raise ValueError(f"{where} es verdadero o falso (1 o 0) y su valor es {number}")
        raise TypeError(f"{where} es verdadero o falso y su valor {value!r} no lo es")
    if kind == "text":
        if isinstance(value, str):
            return str.__str__(value)
        raise TypeError(f"{where} es un texto y su valor {value!r} no lo es")
    if kind == "date":
        return _date(value, where)
    if kind == "datetime":
        return _datetime(value, where)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value)
    raise TypeError(f"{where} es un binario y su valor ({type(value).__name__}) no son bytes")


def _column_texts(kind: str, column: Sequence[object], name: str) -> list[str]:
    """El JSON canónico (en texto) de cada valor de la columna ``name`` de tipo ``kind`` de un
    lote: de una vez si todos son de su tipo exacto o nulos; si no, valor a valor
    (:func:`_field_value` y ``canonical_json``, con sus errores)."""
    types = set(map(type, column))
    nulls = _NONE_TYPE in types
    types.discard(_NONE_TYPE)
    exact = _EXACT_TYPES.get(kind)
    if exact is not None and types <= {exact}:
        if kind == "float":
            texts = _texts(float.__repr__, column, nulls)
            if not _FLOAT_MARK_TEXTS.isdisjoint(texts):
                texts = [_FLOAT_MARKS.get(text, text) for text in texts]
            return texts
        if kind == "int":
            return _texts(int.__repr__, column, nulls)
        if kind == "text":
            return _texts(encode_basestring, column, nulls)
        return [_NULL_TEXT if value is None else ("true" if value else "false")
                for value in column]
    where = f"la columna «{name}»"
    return [canonical_json(_field_value(kind, value, where)).decode("utf-8") for value in column]


def _texts(text: Callable[[Any], str], column: Sequence[object], nulls: bool) -> list[str]:
    """``text(valor)`` de cada valor de ``column`` y «null» por cada nulo."""
    if not nulls:
        return list(map(text, column))
    return [_NULL_TEXT if value is None else text(value) for value in column]


def _date(value: object, where: str) -> dt.date:
    if isinstance(value, dt.datetime):
        raise TypeError(f"{where} es una fecha y su valor {value!r} es una fecha y hora")
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{where} es una fecha y su valor {value!r} no lo es")
    if _DATE_TEXT.fullmatch(value) is None:
        raise ValueError(f"{where} es una fecha AAAA-MM-DD y su valor es «{value}»")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{where} es una fecha y «{value}» no existe") from error


def _datetime(value: object, where: str) -> dt.datetime:
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(
                f"{where} es una fecha y hora ISO 8601 con zona y su valor es «{value}»"
            ) from error
    elif not isinstance(value, dt.datetime):
        raise TypeError(f"{where} es una fecha y hora y su valor {value!r} no lo es")
    if value.utcoffset() is None:
        raise ValueError(f"{where} es una fecha y hora con zona y su valor no la lleva")
    return value


# --- Mallas y nubes de puntos ----------------------------------------------------------------


def _mesh_meta(meta: object) -> dict[str, Any]:
    """Las claves de ``meta`` que son contenido (:data:`MESH_META_KEYS`; la que falta,
    ``None``), comprobadas."""
    if not isinstance(meta, Mapping):
        raise TypeError(f"el meta de una malla es un diccionario, no {type(meta).__name__}")
    kind = meta.get("kind")
    if kind is not None and not isinstance(kind, str):
        raise TypeError(f"«kind» del meta de una malla ({kind!r}) no es un texto")
    crs = meta.get("crs_epsg")
    closed = meta.get("closed")
    if closed is not None and not isinstance(closed, bool | np.bool_):
        raise TypeError(f"«closed» del meta de una malla ({closed!r}) no es verdadero o falso")
    return {
        "closed": None if closed is None else bool(closed),
        "crs_epsg": None if crs is None else _epsg(crs, "la malla"),
        "kind": None if kind is None else str.__str__(kind),
    }


def _array_class(dtype: np.dtype, name: str) -> str:
    if dtype.kind == "f":
        return "float"
    if dtype.kind in "iu":
        return "int"
    if dtype.kind == "b":
        return "bool"
    raise TypeError(
        f"el array «{name}» de la malla es de {dtype}: solo flotantes, enteros o booleanos"
    )


def _as_rows(array: np.ndarray) -> np.ndarray:
    """``array`` como matriz de filas (su primer eje; el resto, aplanado en orden C)."""
    if array.ndim == 2:
        return array
    if array.ndim < 2:
        return array.reshape(-1, 1)
    return array.reshape(array.shape[0], -1)


def _chunks(rows: np.ndarray, cells: int = GRID_CHUNK_CELLS) -> Iterable[tuple[int, int]]:
    """``(primera fila, filas)`` de cada trozo de ``cells`` celdas como mucho (como poco, una
    fila)."""
    count = rows.shape[0]
    if not rows.size:
        return
    step = max(1, cells // max(1, rows.shape[1]))
    for top in range(0, count, step):
        yield top, min(step, count - top)


def _sorted_records(blocks: list[np.ndarray]) -> bytes:
    """Los registros de los puntos ordenados byte a byte (el orden de ``sorted`` sobre sus
    bytes): cada columna, leída como entero *big-endian* de sus 8 bytes, es una clave."""
    if not blocks:
        return b""
    records = np.concatenate(blocks) if len(blocks) > 1 else blocks[0]
    keys = records.view(">u8").astype(np.uint64)
    order = np.lexsort(keys.T[::-1])
    return np.ascontiguousarray(records[order]).tobytes()


# --- Conversión de las celdas ----------------------------------------------------------------


type _Cells = Callable[[np.ndarray], np.ndarray]
type _Check = Callable[[np.ndarray], None]


def _converter(value_class: str, dtype: np.dtype) -> tuple[_Check | None, _Cells]:
    """La comprobación (si hace falta) y la conversión de un trozo de filas a sus bytes
    canónicos (una copia C contigua); ``TypeError`` si las celdas no son de esa clase."""
    kind = dtype.kind
    if value_class == "float":
        if (kind == "f" and dtype.itemsize <= 8) or (kind in "iu" and dtype.itemsize <= 4):
            return None, _float_cells
        raise TypeError(
            f"las celdas de una rejilla de clase «float» son flotantes de hasta 8 bytes o "
            f"enteros de hasta 4, no {dtype} (se perdería precisión o no es un número)"
        )
    if value_class == "int":
        if kind in "iu":
            wide = kind == "u" and dtype.itemsize == 8
            return (_check_int64 if wide else None), _int64_cells
        raise TypeError(f"las celdas de una rejilla de clase «int» son enteros, no {dtype}")
    if kind == "b":
        return None, _int64_cells
    if kind in "iu":
        return _check_bool, _int64_cells
    raise TypeError(f"las celdas de una rejilla de clase «bool» son booleanos, no {dtype}")


def _float_cells(block: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        cells = block.astype("<f8", order="C")
        cells += 0.0  # −0,0 → 0,0
        nan = np.isnan(cells)
    if nan.any():
        cells.view("<u8")[nan] = CANONICAL_NAN_BITS
    return cells


def _int64_cells(block: np.ndarray) -> np.ndarray:
    return block.astype("<i8", order="C")


def _check_int64(block: np.ndarray) -> None:
    if block.size and int(block.max()) > _INT64_MAX:
        raise ValueError(
            f"una celda ({int(block.max())}) no cabe en un entero de 64 bits con signo"
        )


def _check_bool(block: np.ndarray) -> None:
    if block.size and bool(np.any((block != 0) & (block != 1))):
        raise ValueError("una celda de una rejilla de clase «bool» no es 0 ni 1")
