# SPDX-License-Identifier: GPL-3.0-or-later
"""Cabecera TIFF y BigTIFF, primer IFD y sus etiquetas (spec 006; plan 006 §5.1, §5.3.6 y
§5.4 A3; ADR-0020), con biblioteca estándar y numpy.

- :func:`read_first_ifd`: la cabecera (``II`` o ``MM``; 42, TIFF clásico, o 43, BigTIFF) y
  el primer IFD, leídos de un fichero abierto en binario, sin cargarlo entero: solo la
  cabecera, el IFD y los valores de sus etiquetas, con cada desplazamiento comprobado
  contra el tamaño del fichero.
- :class:`Ifd`: el orden de bytes, si es BigTIFF y las etiquetas por número: los números,
  como tuplas de ``int`` o de ``float`` (``RATIONAL`` → cociente); ``ASCII``, como texto
  sin los NUL del final; ``BYTE`` y ``UNDEFINED``, como ``bytes``. Una etiqueta de tipo
  desconocido se ignora (TIFF 6.0 §2) y, si se repite, vale la primera.
- Constantes con el número de las etiquetas que usan el lector y el escritor.

Un fichero que no es TIFF, o con la cabecera, el IFD o un valor fuera del fichero, es
:class:`TiffError` (un ``ValueError`` con el detalle en español), que el lector convierte en
``gis.tiff_invalid`` con el nombre del fichero.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import BinaryIO

import numpy as np

__all__ = [
    "BITS_PER_SAMPLE",
    "COMPRESSION",
    "FILL_ORDER",
    "GDAL_METADATA",
    "GDAL_NODATA",
    "GEO_ASCII_PARAMS",
    "GEO_DOUBLE_PARAMS",
    "GEO_KEY_DIRECTORY",
    "IMAGE_LENGTH",
    "IMAGE_WIDTH",
    "MODEL_PIXEL_SCALE",
    "MODEL_TIEPOINT",
    "MODEL_TRANSFORMATION",
    "PLANAR_CONFIGURATION",
    "PREDICTOR",
    "ROWS_PER_STRIP",
    "SAMPLES_PER_PIXEL",
    "SAMPLE_FORMAT",
    "STRIP_BYTE_COUNTS",
    "STRIP_OFFSETS",
    "TILE_BYTE_COUNTS",
    "TILE_LENGTH",
    "TILE_OFFSETS",
    "TILE_WIDTH",
    "Ifd",
    "TagValue",
    "TiffError",
    "read_first_ifd",
]

# Etiquetas TIFF 6.0 -----------------------------------------------------------------------
IMAGE_WIDTH = 256
IMAGE_LENGTH = 257
BITS_PER_SAMPLE = 258
COMPRESSION = 259
FILL_ORDER = 266
STRIP_OFFSETS = 273
SAMPLES_PER_PIXEL = 277
ROWS_PER_STRIP = 278
STRIP_BYTE_COUNTS = 279
PLANAR_CONFIGURATION = 284
PREDICTOR = 317
TILE_WIDTH = 322
TILE_LENGTH = 323
TILE_OFFSETS = 324
TILE_BYTE_COUNTS = 325
SAMPLE_FORMAT = 339
# GeoTIFF 1.1 ------------------------------------------------------------------------------
MODEL_PIXEL_SCALE = 33550
MODEL_TIEPOINT = 33922
MODEL_TRANSFORMATION = 34264
GEO_KEY_DIRECTORY = 34735
GEO_DOUBLE_PARAMS = 34736
GEO_ASCII_PARAMS = 34737
# GDAL -------------------------------------------------------------------------------------
GDAL_METADATA = 42112
GDAL_NODATA = 42113

type TagValue = tuple[int, ...] | tuple[float, ...] | str | bytes

_TIFF = 42
_BIGTIFF = 43
_ASCII = 2
_RATIONALS = (5, 10)
_RAW = (1, 7)  # BYTE y UNDEFINED
# Tipo de campo TIFF → tipo de numpy (sin el orden de bytes).
_TYPES: Mapping[int, str] = MappingProxyType(
    {
        1: "u1", 2: "u1", 3: "u2", 4: "u4", 5: "u4", 6: "i1", 7: "u1", 8: "i2", 9: "i4",
        10: "i4", 11: "f4", 12: "f8", 13: "u4", 16: "u8", 17: "i8", 18: "u8",
    }
)
_ITEM_COUNT = {5: 2, 10: 2}  # RATIONAL y SRATIONAL: dos enteros por valor


class TiffError(ValueError):
    """El fichero no es un TIFF que se pueda leer; el texto, en español, dice por qué."""


@dataclass(frozen=True, slots=True)
class Ifd:
    """El primer IFD: ``byteorder`` (``"<"`` para ``II``, ``">"`` para ``MM``),
    ``bigtiff`` y ``tags`` (número de etiqueta → valor, solo lectura)."""

    byteorder: str
    bigtiff: bool
    tags: Mapping[int, TagValue]

    def numbers(self, tag: int) -> tuple[int, ...] | tuple[float, ...] | None:
        """Los valores numéricos de ``tag`` o ``None`` si no está; :class:`TiffError` si
        es texto o bytes."""
        value = self.tags.get(tag)
        if value is None:
            return None
        if isinstance(value, str | bytes):
            raise TiffError(f"la etiqueta {tag} no es numérica")
        return value

    def number(self, tag: int, default: int | None = None) -> int | None:
        """El primer valor entero de ``tag`` (``default`` si no está); :class:`TiffError`
        si está vacía o no es un entero."""
        values = self.numbers(tag)
        if values is None:
            return default
        if not values or not isinstance(values[0], int):
            raise TiffError(f"la etiqueta {tag} no tiene un valor entero")
        return values[0]

    def text(self, tag: int) -> str | None:
        """El texto de ``tag`` (``ASCII``) o ``None`` si no está; :class:`TiffError` si no
        es texto."""
        value = self.tags.get(tag)
        if value is None or isinstance(value, str):
            return value
        raise TiffError(f"la etiqueta {tag} no es texto")


def read_first_ifd(stream: BinaryIO, size: int) -> Ifd:
    """La cabecera y el primer IFD del fichero ``stream`` (binario, con ``seek``), de
    ``size`` bytes. :class:`TiffError` si no es un TIFF o algo apunta fuera del fichero."""
    head = _read_at(stream, 0, min(size, 16), size, "la cabecera")
    if len(head) < 8:
        raise TiffError(f"tiene {size} bytes, menos que la cabecera de un TIFF")
    if head[:2] == b"II":
        order = "<"
    elif head[:2] == b"MM":
        order = ">"
    else:
        raise TiffError("no empieza por «II» ni por «MM»: no es un TIFF")
    (version,) = struct.unpack_from(f"{order}H", head, 2)
    if version == _TIFF:
        (offset,) = struct.unpack_from(f"{order}I", head, 4)
        count_format, entry_size, pointer = "H", 12, "I"
    elif version == _BIGTIFF:
        if len(head) < 16:
            raise TiffError("la cabecera de BigTIFF está incompleta")
        bytesize, reserved, offset = struct.unpack_from(f"{order}HHQ", head, 4)
        if (bytesize, reserved) != (8, 0):
            raise TiffError(f"cabecera de BigTIFF no válida ({bytesize}, {reserved})")
        count_format, entry_size, pointer = "Q", 20, "Q"
    else:
        raise TiffError(f"versión {version}: no es TIFF (42) ni BigTIFF (43)")
    if offset == 0:
        raise TiffError("no tiene ningún IFD")
    count_size = struct.calcsize(count_format)
    (count,) = struct.unpack(
        f"{order}{count_format}", _read_at(stream, offset, count_size, size, "el primer IFD")
    )
    if count == 0:
        raise TiffError("el primer IFD no tiene etiquetas")
    table = _read_at(stream, offset + count_size, count * entry_size, size, "el primer IFD")
    inline = entry_size - 12 + 4  # bytes del valor dentro de la entrada: 4 u 8
    tags: dict[int, TagValue] = {}
    for index in range(count):
        entry = index * entry_size
        tag, kind = struct.unpack_from(f"{order}HH", table, entry)
        (number,) = struct.unpack_from(f"{order}{pointer}", table, entry + 4)
        if kind not in _TYPES or tag in tags:
            continue
        item = np.dtype(_TYPES[kind]).newbyteorder(order)
        items = number * _ITEM_COUNT.get(kind, 1)
        nbytes = items * item.itemsize
        field = entry + 4 + struct.calcsize(pointer)
        if nbytes <= inline:
            raw = table[field : field + nbytes]
        else:
            (where,) = struct.unpack_from(f"{order}{pointer}", table, field)
            raw = _read_at(stream, where, nbytes, size, f"el valor de la etiqueta {tag}")
        tags[tag] = _decode(kind, raw, item, items)
    return Ifd(order, version == _BIGTIFF, MappingProxyType(tags))


def _decode(kind: int, raw: bytes, item: np.dtype, items: int) -> TagValue:
    if kind == _ASCII:
        return raw.decode("utf-8", errors="replace").rstrip("\0")
    if kind in _RAW:
        return bytes(raw)
    values = np.frombuffer(raw, item, items)
    if kind in _RATIONALS:
        pairs = values.reshape(-1, 2).astype(np.float64)
        with np.errstate(divide="ignore", invalid="ignore"):
            return tuple((pairs[:, 0] / pairs[:, 1]).tolist())
    return tuple(values.tolist())


def _read_at(stream: BinaryIO, offset: int, length: int, size: int, what: str) -> bytes:
    """``length`` bytes desde ``offset``; :class:`TiffError` si se salen del fichero."""
    if offset < 0 or length < 0 or offset + length > size:
        raise TiffError(
            f"{what} está fuera del fichero (byte {offset} + {length}; el fichero tiene "
            f"{size} bytes)"
        )
    stream.seek(offset)
    data = stream.read(length)
    if len(data) != length:
        raise TiffError(f"{what} está cortado (se leyeron {len(data)} de {length} bytes)")
    return data
