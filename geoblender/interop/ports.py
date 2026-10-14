# SPDX-License-Identifier: GPL-3.0-or-later
"""Puertos de ``interop`` (spec 005; plan 005 §5.1, §5.3.2 y §5.3.4; ADR-0004, ADR-0018).

Las interfaces que ``interop`` define y que implementan otros: el dominio no sabe de motores de
bases de datos (principios 3 y 4).

- :class:`RawTable` y :class:`RawColumn`: una tabla de una base de Access (RecMin) tal como la
  extrae el motor, sin interpretar: su nombre, sus columnas con el tipo de dato de OLE DB
  (``DATA_TYPE``: las constantes ``DBTYPE_*``) y sus filas. La lee ``interop.recmin`` (T15);
  la da el extractor de la base (``MdbExtractor``, T16: ``adapters/mdb_reader.py``, que
  descodifica los ``"d:"``, ``"f:"``, ``"t:"`` y ``"n:"`` de su JSON, plan §5.3.4).

**Los valores de una fila** tienen el tipo de Python del motor: ``None`` (nulo), ``bool``
(``BIT``), ``int`` (``SHORT``, ``LONG``, ``COUNTER``, ``BYTE``), ``float`` (``DOUBLE``),
``numpy.float32`` (``SINGLE``, o su ``float`` exacto en una columna ``DBTYPE_R4``: el lector lo
pasa a su decimal más corto, RF-005-02), ``decimal.Decimal`` (``DECIMAL`` y ``CURRENCY``,
exactos), ``datetime.datetime`` (``DATETIME``), ``str`` (``TEXT`` y ``MEMO``; el texto
invariante de un tipo raro) y ``None`` en las binarias.

**El extractor** (T16; ADR-0018):

- :class:`MdbExtractor`: el puerto. ``probe`` dice el formato de la base y qué motores la abren;
  ``extract`` deja el crudo en una carpeta de salida y devuelve las tablas de usuario, con
  avance y cancelación. Lo implementa ``adapters/mdb_reader.py`` en un ``powershell.exe`` aparte
  (ningún proceso de Geoblender carga el motor de Access); el dominio lo obtiene con
  ``adapters.registry.mdb_extractor()``, dentro de una función (ARQ-07). **Solo se le da una
  copia de la base** (la de ``JobDir.copy_input`` de la 004): el motor crea su fichero de
  bloqueo junto a la base que abre (ADR-0018 §4).
- :class:`MdbFormat` y :func:`read_format`: el formato por la cabecera (byte 0x14: Jet 3, Jet 4
  o ACE, aunque la extensión sea ``.mdb``), sin motor.
- :func:`lock_file`: el ``.ldb`` o ``.laccdb`` de una base abierta por otro programa
  (RF-005-15), que se mira junto al **original** antes de copiarlo.
- :class:`MdbEngine`, :class:`MdbInfo`, :class:`MdbError` (códigos ``io.mdb_*``),
  :class:`MdbCancelled` y :func:`engine_missing` (RF-005-14: el formato detectado, qué instalar
  y la alternativa; el motor, nombrado de forma genérica en :data:`ACCESS_ENGINE` hasta que IMGA
  nombre el instalable, DP-70).

Un ``ports.py`` solo importa la biblioteca estándar, numpy y ``core`` (ARQ-10).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..core.errors import GeoblenderError

__all__ = [
    "ACCESS_ENGINE",
    "DBTYPE_BOOL",
    "DBTYPE_BYTES",
    "DBTYPE_CY",
    "DBTYPE_DATE",
    "DBTYPE_DECIMAL",
    "DBTYPE_I2",
    "DBTYPE_I4",
    "DBTYPE_NUMERIC",
    "DBTYPE_R4",
    "DBTYPE_R8",
    "DBTYPE_UI1",
    "DBTYPE_WSTR",
    "ENGINE_ALTERNATIVE",
    "LOCK_SUFFIXES",
    "MDB_ENGINE_MISSING",
    "MDB_EXTRACT_FAILED",
    "MDB_NOT_ACCESS",
    "MDB_UNREADABLE",
    "MdbCancelled",
    "MdbEngine",
    "MdbError",
    "MdbExtractor",
    "MdbFormat",
    "MdbInfo",
    "RawColumn",
    "RawTable",
    "engine_missing",
    "lock_file",
    "read_format",
]

# DATA_TYPE de OLE DB (DBTYPE_*) de las columnas de Jet y ACE.
DBTYPE_I2 = 2  # SHORT
DBTYPE_I4 = 3  # LONG, COUNTER
DBTYPE_R4 = 4  # SINGLE (precisión simple)
DBTYPE_R8 = 5  # DOUBLE
DBTYPE_CY = 6  # CURRENCY
DBTYPE_DATE = 7  # DATETIME
DBTYPE_BOOL = 11  # BIT
DBTYPE_DECIMAL = 14
DBTYPE_UI1 = 17  # BYTE
DBTYPE_BYTES = 128  # binarias (OLE, BINARY): llegan como None
DBTYPE_WSTR = 130  # TEXT, MEMO
DBTYPE_NUMERIC = 131


@dataclass(frozen=True, slots=True)
class RawColumn:
    """Una columna de una tabla extraída: su nombre tal como está en la base, su tipo de OLE DB
    (``DBTYPE_*``) y su tamaño (``TEXT(n)``: n; ``None`` en las que no son de texto)."""

    name: str
    type: int
    size: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"el nombre de una columna es un texto no vacío, no {self.name!r}")
        if isinstance(self.type, bool) or not isinstance(self.type, int):
            raise TypeError(f"el tipo de la columna «{self.name}» es su DATA_TYPE de OLE DB "
                            f"(un entero), no {self.type!r}")


@dataclass(frozen=True, slots=True)
class RawTable:
    """Una tabla de una base de Access tal como la extrae el motor (véase el módulo): nombre
    tal como está en la base, columnas sin repetir (sin distinguir mayúsculas, como Jet) y filas
    del ancho de las columnas. Inmutable: es la fuente, y nada la modifica."""

    name: str
    columns: tuple[RawColumn, ...]
    rows: tuple[tuple[object, ...], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"el nombre de una tabla es un texto no vacío, no {self.name!r}")
        columns = _tuple(self.columns, f"las columnas de «{self.name}»")
        seen: dict[str, str] = {}
        for column in columns:
            if not isinstance(column, RawColumn):
                raise TypeError(f"las columnas de «{self.name}» son RawColumn, no {column!r}")
            key = column.name.casefold()
            if key in seen:
                raise ValueError(f"la tabla «{self.name}» repite la columna «{column.name}» "
                                 f"(«{seen[key]}»)")
            seen[key] = column.name
        width = len(columns)
        rows = _tuple(self.rows, f"las filas de «{self.name}»")
        if any(type(row) is not tuple or len(row) != width for row in rows):
            # Las filas que no son tuplas del ancho (lo raro): una a una, con su mensaje. Las
            # que ya lo son (lo que da el extractor) no cuestan más que esta pasada (T16).
            checked = []
            for number, row in enumerate(rows, 1):
                row = _tuple(row, f"la fila {number} de «{self.name}»")
                if len(row) != width:
                    raise ValueError(f"la fila {number} de «{self.name}» tiene {len(row)} "
                                     f"valores y la tabla {width} columnas")
                checked.append(row)
            rows = tuple(checked)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "rows", rows)

    def position(self, column: str) -> int | None:
        """La posición de la columna ``column`` (sin distinguir mayúsculas), o ``None``."""
        key = column.casefold()
        for position, found in enumerate(self.columns):
            if found.name.casefold() == key:
                return position
        return None

    def values(self, column: str) -> list[object]:
        """Los valores de la columna ``column`` en el orden de las filas (``KeyError`` si la
        tabla no la tiene)."""
        position = self.position(column)
        if position is None:
            raise KeyError(f"la tabla «{self.name}» no tiene la columna «{column}»")
        return [row[position] for row in self.rows]


def _tuple(value: object, what: str) -> tuple[object, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        raise TypeError(f"{what} son una lista, no {value!r}")
    return tuple(value)


# ---------------------------------------------------------------------------------------
# El extractor de bases de Access (T16; ADR-0018; plan 005 §5.3.4)
# ---------------------------------------------------------------------------------------

MDB_UNREADABLE = "io.mdb_unreadable"
"""La base no se puede leer: no existe, no hay permiso, o el motor no la abre por algo que no
es el formato (contraseña, base dañada)."""
MDB_NOT_ACCESS = "io.mdb_not_access"
"""El fichero no tiene la cabecera de una base de Access (Jet o ACE)."""
MDB_ENGINE_MISSING = "io.mdb_engine_missing"
"""Ningún motor del equipo lee el formato de la base (RF-005-14)."""
MDB_EXTRACT_FAILED = "io.mdb_extract_failed"
"""El proceso que extrae la base falló: una directiva que impide el guion, un error del
motor a mitad, una salida que no se entiende o un proceso que deja de responder."""

ACCESS_ENGINE = "el motor gratuito de bases de datos de Access de Microsoft de 64 bits"
"""Qué instalar si falta el motor (RF-005-14). Genérico hasta que IMGA nombre el instalable
concreto con soporte vigente (DP-70); entonces, su nombre aquí."""
ENGINE_ALTERNATIVE = "exporte los datos desde RecMin a CSV e impórtelos como tablas"
"""La alternativa sin motor (RF-005-14)."""

LOCK_SUFFIXES: tuple[str, ...] = (".ldb", ".laccdb")
"""Ficheros de bloqueo de Access junto a una base abierta: ``.ldb`` (Jet), ``.laccdb`` (ACE)."""

_HEADER_SIZE = 0x20
_HEADER_START = b"\x00\x01\x00\x00"
_HEADER_MAGICS = (b"Standard Jet DB\x00", b"Standard ACE DB\x00")
_VERSION_OFFSET = 0x14


class MdbError(GeoblenderError):
    """Una base de Access que no se puede extraer (códigos ``io.mdb_*``): el objeto es el
    nombre del fichero."""


class MdbCancelled(Exception):
    """Se pidió cancelar la extracción y se paró (el proceso hijo, terminado)."""

    def __init__(self, message: str = "extracción de la base de Access cancelada") -> None:
        super().__init__(message)


class MdbFormat(StrEnum):
    """El formato de una base de Access por el byte 0x14 de su cabecera (plan §5.3.4)."""

    JET3 = "jet3"
    JET4 = "jet4"
    ACE = "ace"

    @property
    def label(self) -> str:
        """El formato para el usuario."""
        return _FORMAT_LABELS[self]


_FORMAT_LABELS = {
    MdbFormat.JET3: "Jet 3 (Access 97)",
    MdbFormat.JET4: "Jet 4 (Access 2000 a 2003)",
    MdbFormat.ACE: "ACE (Access 2007 o posterior)",
}


def read_format(path: Path | str) -> tuple[MdbFormat, int]:
    """El formato de la base ``path`` y su byte de versión (0 Jet 3, 1 Jet 4, ≥ 2 ACE), por su
    cabecera y sin motor: una base de RecMin Pro es ACE aunque su extensión sea ``.mdb``.
    :class:`MdbError` ``io.mdb_unreadable`` si no se puede leer o ``io.mdb_not_access`` si no
    es una base de Access."""
    path = Path(path)
    try:
        with path.open("rb") as handle:
            head = handle.read(_HEADER_SIZE)
    except OSError as exc:
        raise MdbError(
            MDB_UNREADABLE,
            f"no se puede leer el fichero ({exc.strerror or exc}); compruebe que existe y que "
            "tiene permiso de lectura",
            obj=path.name, field="ruta", value=str(path),
        ) from exc
    if (len(head) <= _VERSION_OFFSET or not head.startswith(_HEADER_START)
            or head[4:20] not in _HEADER_MAGICS):
        raise MdbError(
            MDB_NOT_ACCESS,
            "no es una base de Access (MDB o ACCDB): su cabecera no es la de Jet ni la de ACE",
            obj=path.name, field="cabecera", value=None, shown="no reconocida",
        )
    version = head[_VERSION_OFFSET]
    if version == 0:
        return MdbFormat.JET3, version
    if version == 1:
        return MdbFormat.JET4, version
    return MdbFormat.ACE, version


def lock_file(path: Path | str) -> Path | None:
    """El fichero de bloqueo de la base ``path`` (``<base>.ldb`` o ``<base>.laccdb``) si
    existe: otro programa (RecMin, Access) la tiene abierta (RF-005-15). Se mira junto al
    original, antes de copiarlo; ``None`` si no hay."""
    path = Path(path)
    for suffix in LOCK_SUFFIXES:
        candidate = path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True, slots=True)
class MdbEngine:
    """Un motor de Access: su proveedor OLE DB y el ``powershell.exe`` (64 o 32 bits) en que
    se carga."""

    provider: str
    bits: int

    def __post_init__(self) -> None:
        if (not isinstance(self.provider, str) or not self.provider.strip()
                or any(c in self.provider for c in ";=\"'")):
            raise ValueError(f"{self.provider!r} no es el nombre de un proveedor OLE DB")
        if self.bits not in (32, 64) or isinstance(self.bits, bool):
            raise ValueError(f"un motor es de 32 o de 64 bits, no de {self.bits!r}")

    @property
    def label(self) -> str:
        """«Proveedor (64 bits)»."""
        return f"{self.provider} ({self.bits} bits)"


@dataclass(frozen=True, slots=True)
class MdbInfo:
    """Lo que se sabe de una base sin extraerla: su formato y su byte de versión; los motores
    que la abren (``OleDbConnection.Open()``), en el orden en que se prefieren; y los que se
    probaron y no, con su motivo. Un motor que no lee ese formato no se prueba."""

    format: MdbFormat
    version: int
    engines: tuple[MdbEngine, ...] = ()
    unavailable: tuple[tuple[MdbEngine, str], ...] = ()

    @property
    def engine(self) -> MdbEngine | None:
        """El motor con el que se extraería (el primero que la abre), o ``None``."""
        return self.engines[0] if self.engines else None


ProgressCallback = Callable[[float, str], None]
"""Avance de 0 a 1 con su mensaje en español. Puede lanzar (el ``JobCancelled`` de un
worker): la excepción sale de ``extract`` con el proceso hijo terminado."""


@runtime_checkable
class MdbExtractor(Protocol):
    """Extrae las tablas de usuario de una base de Access (MDB o ACCDB, Jet 3, Jet 4 o ACE)
    sin cargar su motor en el proceso que llama (ADR-0018). ``path`` es siempre una copia."""

    def probe(self, path: Path) -> MdbInfo:
        """El formato de la base y qué motores del equipo la abren."""
        ...

    def extract(self, path: Path, out_dir: Path, on_progress: ProgressCallback,
                cancelled: Callable[[], bool]) -> list[RawTable]:
        """Las tablas de usuario (sin ``MSys*``), con el crudo en ``out_dir`` (nueva o vacía):
        ``schema.json`` y un ``.jsonl`` por tabla. Avance cada ≤ 0,5 s, también dentro de una
        tabla; ``cancelled()`` verdadero → :class:`MdbCancelled` en ≤ 2 s con el hijo
        terminado. Sin motor para el formato, :class:`MdbError` ``io.mdb_engine_missing``
        (:func:`engine_missing`) y nada extraído."""
        ...


def engine_missing(name: str, fmt: MdbFormat, tried: Sequence[str] = ()) -> MdbError:
    """El error de RF-005-14 para la base ``name``: el formato detectado, qué instalar
    (:data:`ACCESS_ENGINE`), la alternativa (:data:`ENGINE_ALTERNATIVE`) y que no se importa
    nada; ``tried``, los motores probados con su motivo."""
    reason = (
        f"este equipo no tiene un motor que lea las bases de este formato: instale "
        f"{ACCESS_ENGINE} o, como alternativa, {ENGINE_ALTERNATIVE}; no se ha importado nada"
    )
    if tried:
        reason += ". Motores probados: " + "; ".join(tried)
    return MdbError(MDB_ENGINE_MISSING, reason, obj=name, field="formato", value=fmt.label,
                    context={"format": fmt.value, "tried": list(tried)})
