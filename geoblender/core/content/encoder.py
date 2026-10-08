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

El hash de datos es el sha256 de la forma normalizada de lo leído, por tipo. Dentro de un
flujo, un hash siempre va en sus 32 bytes (no en hexadecimal). Esta primera parte (T05) da:

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

Una versión publicada no cambia nunca (unos vectores de referencia la fijan,
``tests/data/core/content/golden_gbch1.json``): cualquier cambio de forma es un normalizador
nuevo. Las entradas del lector no se modifican: el normalizador trabaja sobre copias, por
trozos de :data:`GRID_CHUNK_CELLS` celdas como mucho (memoria acotada a un trozo más el
bloque que da el lector). Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import hashlib
import math
import numbers
import operator
import re
import struct
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..hashing import CANONICAL_NAN_BITS, canonical_float, canonical_json

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
"""Celdas que se convierten y se hashean de una vez (8 MiB en float64); como poco, una fila."""

LABEL_HEAD = b"HEAD"
LABEL_DECL = b"DECL"
LABEL_DATA = b"DATA"
LABEL_GRID = b"GRID"
LABEL_PART = b"PART"
LABEL_VALUES = b"VALS"

_CELL_BYTES = 8
_INT64_MAX = (1 << 63) - 1
_SHA256_TEXT = re.compile(r"[0-9a-f]{64}")
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


class ContentHasher:
    """Calcula el :class:`ContentDigest` de una entrada o de un dato de tipo ``kind`` (uno
    de :data:`KINDS`) con sus ``declarations`` (un ``Mapping`` con forma JSON canónica: CRS
    declarados, convenios que son contenido…), el identificador de su lector (``reader``,
    p. ej. ``"gis.geotiff@1"``) y su normalizador (por defecto, el vigente).

    Recibe los datos **una vez**, con un método por tipo (:meth:`grid`, :meth:`document`,
    :meth:`composite`), o por partes con :meth:`begin_grid` y :meth:`begin_document`, cuyo
    ``finish()`` los entrega; después, :meth:`digest`. Los métodos de datos devuelven el
    propio objeto: ``ContentHasher(…).grid(cabecera, bloques).digest()``."""

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
        self._open: GridEncoder | DocumentEncoder | None = None

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
        "crs": _file_crs(header["crs"]),
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


def _file_crs(value: object) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(
            f"el CRS que trae el fichero es {{\"epsg\": n}} o None, no {type(value).__name__}"
        )
    if set(value) != {"epsg"}:
        raise ValueError(
            f"el CRS que trae el fichero es {{\"epsg\": n}} o None, no {dict(value)!r}"
        )
    code = value["epsg"]
    if isinstance(code, bool | np.bool_) or not isinstance(code, numbers.Integral):
        raise TypeError(f"el código EPSG del fichero ({code!r}) no es un número entero")
    number = operator.index(code)
    if number < 1:
        raise ValueError(f"el código EPSG del fichero ({number}) no es válido")
    return {"epsg": number}


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
