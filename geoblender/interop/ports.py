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
(``BIT``), ``int`` (``SHORT``, ``LONG``, ``COUNTER``), ``float`` (``DOUBLE``), ``numpy.float32``
(``SINGLE``, o su ``float`` exacto en una columna ``DBTYPE_R4``: el lector lo pasa a su decimal
más corto, RF-005-02), ``decimal.Decimal`` (``DECIMAL`` y ``CURRENCY``, exactos),
``datetime.datetime`` (``DATETIME``), ``str`` (``TEXT`` y ``MEMO``) y ``None`` en las binarias.

Un ``ports.py`` solo importa la biblioteca estándar, numpy y ``core`` (ARQ-10).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = [
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
    "RawColumn",
    "RawTable",
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
        rows = []
        for number, row in enumerate(_tuple(self.rows, f"las filas de «{self.name}»"), 1):
            row = _tuple(row, f"la fila {number} de «{self.name}»")
            if len(row) != width:
                raise ValueError(f"la fila {number} de «{self.name}» tiene {len(row)} valores y "
                                 f"la tabla {width} columnas")
            rows.append(row)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "rows", tuple(rows))

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
