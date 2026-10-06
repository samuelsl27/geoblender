# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipos del proyecto ``.gbproj`` (spec 002; plan 002 §5.1 y §5.3).

- :class:`ProjectSettings`: lo que indica el usuario al crear un proyecto (nombre, CRS,
  ventana de trabajo tecleada, paso de rejilla y Z0), por validar.
- :class:`ProjectRecord`: la fila de ``gb_project``, la identidad y la georreferencia del
  proyecto tal como las guarda la base de datos, que es la fuente de verdad (la cabecera
  ``manifest.json`` es una copia legible que se reescribe desde ella).
- :class:`OpenMode`, :class:`ReadOnlyCode` y :class:`OpenStatus`: cómo está abierto un
  proyecto y, en solo lectura, por qué (RF-002-13).
- :class:`Progress` y :class:`OpenResult`: los pasos de una operación larga (abrir, copiar,
  migrar) y el resultado de abrir.

Coordenadas: la ventana de trabajo y el GeoOrigin son **absolutos** (CRS del proyecto,
m); el GeoOrigin, en metros enteros.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from enum import Enum
from typing import TYPE_CHECKING

from ..georef.crs import DEFAULT_HORIZONTAL_EPSG, DEFAULT_VERTICAL_EPSG
from ..georef.origin import DEFAULT_GRID_STEP_M, GeoOrigin, Window

if TYPE_CHECKING:
    from .lock import LockStatus
    from .session import Project


@dataclass(frozen=True)
class ProjectSettings:
    """Lo que indica el usuario al crear un proyecto (RF-002-01, RF-002-23), sin validar:
    lo valida ``core.project.create``.

    ``window``: la ventana de trabajo tecleada, absoluta (xmin, ymin, xmax, ymax, en m),
    antes de ampliarla a la unidad de alineación del paso. Por defecto, EPSG:25830 y
    EPSG:5782 (spec 002, D-2); ``vcrs_epsg = None`` es una referencia vertical local, que
    necesita ``vcrs_note``.
    """

    name: str
    window: Window | tuple[float, float, float, float]
    crs_epsg: int = DEFAULT_HORIZONTAL_EPSG
    vcrs_epsg: int | None = DEFAULT_VERTICAL_EPSG
    vcrs_note: str | None = None
    grid_step_m: float = DEFAULT_GRID_STEP_M
    z0: int = 0
    code: str | None = None
    client: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ProjectRecord:
    """La fila de ``gb_project`` (esquema 1; formato-proyecto §3.2).

    ``vcrs_epsg`` es ``None`` en una referencia vertical local, que lleva entonces su
    descripción en ``vcrs_note`` y no lleva ``vcrs_wkt``. Las fechas, en UTC ISO 8601 con
    milisegundos y «Z».
    """

    uid: str
    name: str
    schema_version: int
    min_reader_schema: int
    created_with: str
    last_written_with: str
    crs_epsg: int
    crs_name: str
    crs_wkt: str
    vcrs_epsg: int | None
    vcrs_name: str
    vcrs_wkt: str | None
    vcrs_note: str | None
    origin_x: int
    origin_y: int
    origin_z: int
    grid_step_m: float
    window_xmin: float
    window_ymin: float
    window_xmax: float
    window_ymax: float
    created_at: str
    modified_at: str
    code: str | None = None
    client: str | None = None
    description: str | None = None
    active_version_uid: str | None = None

    @property
    def origin(self) -> GeoOrigin:
        """El GeoOrigin (X0, Y0, Z0) en metros enteros; ``ValidationError`` si la fila
        no tiene un origen válido."""
        return GeoOrigin(self.origin_x, self.origin_y, self.origin_z)

    @property
    def window(self) -> Window:
        """La ventana de trabajo alineada, absoluta (m)."""
        return Window(self.window_xmin, self.window_ymin, self.window_xmax, self.window_ymax)

    @property
    def vertical_is_local(self) -> bool:
        """Verdadero si las cotas van referidas a una referencia local (sin EPSG)."""
        return self.vcrs_epsg is None

    def as_row(self) -> dict[str, object]:
        """Columna → valor, para escribir la fila."""
        return asdict(self)

    @classmethod
    def columns(cls) -> tuple[str, ...]:
        """Las columnas de ``gb_project`` que lleva el registro (todas salvo ``fid``)."""
        return tuple(item.name for item in fields(cls))

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> ProjectRecord:
        """El registro de una fila leída (columna → valor)."""
        return cls(**{name: row[name] for name in cls.columns()})  # type: ignore[arg-type]


class OpenMode(Enum):
    """Cómo está abierto un proyecto (spec 002 §6, «Modo de apertura»)."""

    WRITE_LOCAL = "write_local"  # escritura en disco local
    WRITE_NETWORK = "write_network"  # escritura directa en una carpeta de red
    CHECKOUT = "checkout"  # escritura en una copia local de trabajo (RF-002-31)
    READ_ONLY = "read_only"

    @property
    def writable(self) -> bool:
        """Verdadero si se puede escribir en el proyecto."""
        return self is not OpenMode.READ_ONLY


class ReadOnlyCode(Enum):
    """Por qué un proyecto está en solo lectura (RF-002-13)."""

    REQUESTED = "requested"  # a petición del usuario
    LOCKED = "locked"  # otra sesión tiene el cerrojo
    RESERVED = "reserved"  # el original está reservado para una copia local
    SCHEMA_NEWER = "schema_newer"  # esquema posterior al de esta versión
    NOT_MIGRATED = "not_migrated"  # esquema anterior sin migrar
    WAL_BUSY = "wal_busy"  # otro programa tiene la BD abierta en WAL
    LOCK_LOST = "lock_lost"  # el cerrojo dejó de ser de esta sesión
    WRITE_FAILED = "write_failed"  # falló una escritura (disco, red)


@dataclass(frozen=True)
class OpenStatus:
    """El modo de apertura con su motivo, en español, para mostrarlo siempre."""

    mode: OpenMode
    reason: ReadOnlyCode | None
    message: str

    @property
    def writable(self) -> bool:
        """Verdadero si se puede escribir en el proyecto."""
        return self.mode.writable


@dataclass(frozen=True)
class Progress:
    """Un paso de una operación larga: fase, hechos de un total (pasos o bytes), mensaje
    en español y, en el último paso, el resultado."""

    phase: str
    done: int
    total: int
    message: str
    result: object | None = None


@dataclass(frozen=True)
class OpenResult:
    """El resultado de abrir: el proyecto, su estado, los avisos y el cerrojo que se vio
    (para ofrecer forzarlo si se puede, RF-002-10)."""

    project: Project
    status: OpenStatus
    warnings: tuple[str, ...] = ()
    lock_status: LockStatus | None = None
