# SPDX-License-Identifier: GPL-3.0-or-later
"""Códecs de las tiras y teselas de un GeoTIFF (spec 006; plan 006 §5.3.6 y §5.4 A3 y A4;
ADR-0020): LZW, PackBits, DEFLATE y los predictores 2 y 3, con biblioteca estándar y numpy.

Leer un bloque (:func:`decode_block`) es descomprimirlo (:func:`decompress`, por el código
de la etiqueta ``Compression``) y deshacer su predictor (:func:`predictor_decode`): da un
array de ``filas × ancho`` muestras, en el orden de bytes nativo y con los mismos bits que
la fuente (RF-006-08). Escribirlo (:func:`encode_block`, perfiles ``project`` y
``deliverable`` del plan §5.2.1) es aplicar el predictor en little-endian y DEFLATE de nivel
6: los mismos valores dan los mismos bytes (RF-006-24).

- **LZW** (TIFF 6.0 §13, el de libtiff desde su versión 5): códigos de 9 a 12 bits con el
  bit más significativo primero; 256 = CLEAR (vacía la tabla) y 257 = EOI (fin); el ancho
  crece por adelantado (*early change*), cuando la siguiente entrada libre llega a 511,
  1023 y 2047. Como cada código añade una entrada, se sabe cuántos códigos tiene cada tramo
  de ancho fijo: se sacan de una vez con numpy y la tabla se recorre en Python.
- **PackBits** (TIFF 6.0 §9) y **DEFLATE** (zlib; códigos 8 y 32946).
- **Predictor 2** (diferencia horizontal): suma acumulada por fila de las muestras, como
  enteros sin signo de su tamaño leídos en el orden de bytes del fichero, módulo 2ⁿ (con
  flotantes, sobre sus bits, como libtiff).
- **Predictor 3** (coma flotante, TIFF Technical Note 3): suma acumulada ``uint8`` de los
  bytes de la fila, que están por planos, del byte más significativo al menos significativo,
  sea cual sea el orden de bytes del fichero (como libtiff).

Una muestra por píxel (el lector rechaza las demás, RF-006-09). Un bloque corrupto o
incompleto, un códec o un predictor que no se admiten son :class:`CodecError` (un
``ValueError`` con el detalle en español): el lector lo convierte en un error para el
usuario con el fichero y el bloque. Una forma no positiva es un error del programa
(``ValueError``). Sin tamaño esperado, LZW y PackBits leen hasta el final de los datos: el
lector siempre lo pasa (filas × ancho × bytes por muestra).
"""

from __future__ import annotations

import operator
import zlib
from collections.abc import Mapping
from types import MappingProxyType

import numpy as np
from numpy.typing import DTypeLike

__all__ = [
    "COMPRESSIONS",
    "COMPRESSION_DEFLATE",
    "COMPRESSION_DEFLATE_OLD",
    "COMPRESSION_LZW",
    "COMPRESSION_NAMES",
    "COMPRESSION_NONE",
    "COMPRESSION_PACKBITS",
    "DEFLATE_LEVEL",
    "PREDICTORS",
    "PREDICTOR_FLOATING_POINT",
    "PREDICTOR_HORIZONTAL",
    "PREDICTOR_NONE",
    "CodecError",
    "compression_name",
    "decode_block",
    "decompress",
    "deflate_decode",
    "deflate_encode",
    "encode_block",
    "lzw_decode",
    "packbits_decode",
    "predictor_decode",
    "predictor_encode",
]

type Buffer = bytes | bytearray | memoryview

# Etiqueta Compression (259) -------------------------------------------------------------
COMPRESSION_NONE = 1
COMPRESSION_LZW = 5
COMPRESSION_DEFLATE = 8
COMPRESSION_DEFLATE_OLD = 32946
COMPRESSION_PACKBITS = 32773
COMPRESSIONS: frozenset[int] = frozenset(
    {COMPRESSION_NONE, COMPRESSION_LZW, COMPRESSION_DEFLATE, COMPRESSION_DEFLATE_OLD,
     COMPRESSION_PACKBITS}
)
"""Las compresiones que se leen (plan §5.3.6); las demás se rechazan (RF-006-09)."""

COMPRESSION_NAMES: Mapping[int, str] = MappingProxyType(
    {
        1: "ninguna",
        2: "CCITT RLE",
        3: "CCITT G3",
        4: "CCITT G4",
        5: "LZW",
        6: "JPEG antiguo",
        7: "JPEG",
        8: "DEFLATE",
        32773: "PackBits",
        32946: "DEFLATE",
        34661: "JBIG",
        34712: "JPEG 2000",
        34887: "LERC",
        34925: "LZMA",
        50000: "ZSTD",
        50001: "WebP",
        50002: "JPEG XL",
    }
)
"""Nombre de cada código de compresión TIFF conocido, para los mensajes."""

UNKNOWN_COMPRESSION = "desconocida"

# Etiqueta Predictor (317) ---------------------------------------------------------------
PREDICTOR_NONE = 1
PREDICTOR_HORIZONTAL = 2
PREDICTOR_FLOATING_POINT = 3
PREDICTORS: frozenset[int] = frozenset(
    {PREDICTOR_NONE, PREDICTOR_HORIZONTAL, PREDICTOR_FLOATING_POINT}
)

DEFLATE_LEVEL = 6
"""Nivel de DEFLATE de los GeoTIFF que escribe Geoblender (plan §5.2.1)."""

# LZW de TIFF ----------------------------------------------------------------------------
_LZW_CLEAR = 256
_LZW_EOI = 257
_LZW_FIRST = 258
_LZW_MIN_BITS = 9
_LZW_MAX_BITS = 12
_LZW_BATCH = 4096  # códigos de 12 bits que se sacan de una vez


class CodecError(ValueError):
    """Bloque corrupto o incompleto, o códec o predictor que no se admite; el texto, en
    español, dice el códec y lo que falla."""


def compression_name(code: int) -> str:
    """El nombre del código de compresión TIFF ``code`` («LZW», «JPEG»…) o «desconocida»."""
    return COMPRESSION_NAMES.get(code, UNKNOWN_COMPRESSION)


# --- Descompresión ------------------------------------------------------------------------


def decompress(data: Buffer, compression: int, expected_size: int) -> bytes:
    """Los ``expected_size`` bytes de un bloque comprimido con ``compression`` (código
    TIFF). :class:`CodecError` si el códec no se admite o el bloque no los da."""
    _check_positive(expected_size=expected_size)
    if compression == COMPRESSION_NONE:
        if len(data) < expected_size:
            raise CodecError(
                f"sin compresión: el bloque tiene {len(data)} bytes y se esperaban "
                f"{expected_size}"
            )
        return bytes(data[:expected_size])
    if compression == COMPRESSION_LZW:
        return lzw_decode(data, expected_size)
    if compression in (COMPRESSION_DEFLATE, COMPRESSION_DEFLATE_OLD):
        return deflate_decode(data, expected_size)
    if compression == COMPRESSION_PACKBITS:
        return packbits_decode(data, expected_size)
    raise CodecError(
        f"compresión {compression_name(compression)} (código {compression}) no admitida"
    )


def lzw_decode(data: Buffer, expected_size: int | None = None) -> bytes:
    """Descomprime un bloque LZW de TIFF hasta su EOI o el final de los datos; con
    ``expected_size``, da exactamente esos bytes (lo que sobra se descarta, como libtiff).

    :class:`CodecError` con un código que no está en la tabla, un primer código tras CLEAR
    que no es un byte, menos bytes de los esperados o el LZW antiguo de libtiff (anterior a
    su versión 5, con el bit menos significativo primero), que no se admite.
    """
    raw = bytes(data)
    if len(raw) >= 2 and raw[0] == 0 and raw[1] & 1:
        raise CodecError(
            "LZW: el bloque es del LZW antiguo de libtiff (anterior a su versión 5, con el "
            "bit menos significativo primero), que no se admite"
        )
    padded = np.frombuffer(raw + b"\0\0\0", np.uint8)
    total_bits = 8 * len(raw)
    out = bytearray()
    # 256 y 257 (CLEAR y EOI) no son entradas: sus huecos nunca se leen.
    table: list[bytes] = [bytes((i,)) for i in range(256)] + [b"", b""]
    append = table.append
    pos = 0
    finished = False
    while not finished:  # cada vuelta, tras un CLEAR (o al principio)
        del table[_LZW_FIRST:]
        width = _LZW_MIN_BITS
        if total_bits - pos < width:
            break
        code = int(_lzw_codes(padded, pos, width, 1)[0])
        pos += width
        if code == _LZW_CLEAR:
            continue
        if code == _LZW_EOI:
            break
        if code > 255:
            raise CodecError(
                f"LZW: el primer código tras CLEAR es {code} y debe ser un byte (de 0 a 255)"
            )
        prev = table[code]
        out += prev
        while True:  # tramos de ancho fijo
            if expected_size is not None and len(out) >= expected_size:
                finished = True
                break
            # Cada código añade una entrada: el ancho cambia cuando la tabla llega a 2ⁿ − 1.
            wanted = (1 << width) - 1 - len(table) if width < _LZW_MAX_BITS else _LZW_BATCH
            count = min(wanted, (total_bits - pos) // width)
            if count <= 0:
                finished = True
                break
            codes = _lzw_codes(padded, pos, width, count)
            special = np.flatnonzero((codes == _LZW_CLEAR) | (codes == _LZW_EOI))
            stop = int(special[0]) if special.size else count
            for code in codes[:stop].tolist():
                try:
                    entry = table[code]
                except IndexError:
                    if code != len(table):
                        raise CodecError(
                            f"LZW: el código {code} no está en la tabla ({len(table)} "
                            "entradas)"
                        ) from None
                    entry = prev + prev[:1]  # KwKwK: la entrada que se está creando
                append(prev + entry[:1])
                out += entry
                prev = entry
            if stop < count:
                pos += (stop + 1) * width
                finished = bool(codes[stop] == _LZW_EOI)
                break
            pos += count * width
            if count < wanted:  # se acabaron los datos sin EOI
                finished = True
                break
            if width < _LZW_MAX_BITS:
                width += 1
    return _finish(out, expected_size, "LZW")


def _lzw_codes(padded: np.ndarray, pos: int, width: int, count: int) -> np.ndarray:
    """``count`` códigos de ``width`` bits (bit más significativo primero) desde el bit
    ``pos`` de ``padded`` (los datos con tres bytes cero al final)."""
    bits = pos + width * np.arange(count, dtype=np.int64)
    index = bits >> 3
    window = (
        (padded[index].astype(np.int64) << 16)
        | (padded[index + 1].astype(np.int64) << 8)
        | padded[index + 2]
    )
    return (window >> (24 - width - (bits & 7))) & ((1 << width) - 1)


def packbits_decode(data: Buffer, expected_size: int | None = None) -> bytes:
    """Descomprime un bloque PackBits: cabecera n de 0 a 127, n + 1 bytes literales; de 129
    a 255, el byte siguiente 257 − n veces; 128, nada. Con ``expected_size``, da exactamente
    esos bytes. :class:`CodecError` si una secuencia pasa del final de los datos o faltan
    bytes."""
    raw = bytes(data)
    size = len(raw)
    out = bytearray()
    i = 0
    while i < size and (expected_size is None or len(out) < expected_size):
        header = raw[i]
        i += 1
        if header < 128:
            end = i + header + 1
            if end > size:
                raise CodecError(
                    f"PackBits: la secuencia literal de {header + 1} bytes del byte {i - 1} "
                    f"pasa del final de los datos ({size} bytes)"
                )
            out += raw[i:end]
            i = end
        elif header > 128:
            if i >= size:
                raise CodecError(
                    f"PackBits: la secuencia repetida del byte {i - 1} no tiene su byte "
                    f"(fin de los datos, {size} bytes)"
                )
            out += raw[i : i + 1] * (257 - header)
            i += 1
    return _finish(out, expected_size, "PackBits")


def deflate_decode(data: Buffer, expected_size: int | None = None) -> bytes:
    """Descomprime un bloque DEFLATE (zlib); con ``expected_size``, da exactamente esos
    bytes. :class:`CodecError` si los datos están corruptos o incompletos."""
    decompressor = zlib.decompressobj()
    try:
        if expected_size is None:
            out = decompressor.decompress(data)
            if not decompressor.eof:
                raise CodecError("DEFLATE: el bloque está incompleto (sin final de flujo)")
        else:
            out = decompressor.decompress(data, expected_size) if expected_size else b""
    except zlib.error as error:
        raise CodecError(f"DEFLATE: el bloque está corrupto ({error})") from None
    return _finish(out, expected_size, "DEFLATE")


def deflate_encode(data: Buffer, level: int = DEFLATE_LEVEL) -> bytes:
    """Comprime con DEFLATE (zlib) de nivel ``level``: los mismos bytes, la misma salida."""
    return zlib.compress(data, level)


def _finish(out: bytes | bytearray, expected_size: int | None, codec: str) -> bytes:
    if expected_size is not None:
        if len(out) < expected_size:
            raise CodecError(
                f"{codec}: el bloque da {len(out)} bytes y se esperaban {expected_size}"
            )
        if len(out) > expected_size:
            out = out[:expected_size]
    return out if type(out) is bytes else bytes(out)


# --- Predictores --------------------------------------------------------------------------


def predictor_decode(
    raw: Buffer, predictor: int, dtype: DTypeLike, width: int, rows: int
) -> np.ndarray:
    """Las ``rows × width`` muestras de un bloque descomprimido, con su ``predictor``
    deshecho: ``dtype`` es el tipo del fichero, con su orden de bytes (``"<f4"``,
    ``">i2"``…); el array, del mismo tipo en el orden nativo, nuevo (no comparte memoria con
    ``raw``). :class:`CodecError` si el bloque es corto o el predictor no se admite con ese
    tipo."""
    dtype = np.dtype(dtype)
    _check_positive(width=width, rows=rows)
    size = dtype.itemsize
    count = width * rows
    nbytes = count * size
    if len(raw) < nbytes:
        raise CodecError(
            f"el bloque tiene {len(raw)} bytes y necesita {nbytes} bytes ({rows} filas × "
            f"{width} muestras de {size} bytes)"
        )
    native = dtype.newbyteorder("=")
    if predictor == PREDICTOR_NONE:
        return np.frombuffer(raw, dtype, count).reshape(rows, width).astype(native)
    if predictor == PREDICTOR_HORIZONTAL:
        unsigned = _unsigned_for(dtype, predictor)
        words = np.frombuffer(raw, unsigned.newbyteorder(dtype.byteorder), count)
        return np.cumsum(words.reshape(rows, width), axis=1, dtype=unsigned).view(native)
    if predictor == PREDICTOR_FLOATING_POINT:
        _check_float(dtype)
        planes = np.frombuffer(raw, np.uint8, nbytes).reshape(rows, size * width)
        summed = np.cumsum(planes, axis=1, dtype=np.uint8).reshape(rows, size, width)
        big = np.ascontiguousarray(summed.transpose(0, 2, 1)).view(f">f{size}")
        return big.reshape(rows, width).astype(native)
    raise CodecError(f"predictor {predictor} no admitido (sí 1, 2 y 3)")


def predictor_encode(values: np.ndarray, predictor: int, byteorder: str = "<") -> bytes:
    """Los bytes de un bloque de ``values`` (2-D, filas × ancho, de su tipo) con
    ``predictor`` aplicado, en el orden de bytes ``byteorder`` (``"<"`` o ``">"``; el
    predictor 3 no depende de él). :class:`CodecError` si el predictor no se admite con ese
    tipo."""
    array = np.asarray(values)
    if array.ndim != 2 or array.size == 0:
        raise ValueError(f"se esperaba un bloque 2-D no vacío y su forma es {array.shape}")
    if byteorder not in ("<", ">"):
        raise ValueError(f"orden de bytes «{byteorder}»: debe ser «<» o «>»")
    dtype = array.dtype
    size = dtype.itemsize
    if predictor == PREDICTOR_NONE:
        return np.ascontiguousarray(array, dtype.newbyteorder(byteorder)).tobytes()
    if predictor == PREDICTOR_HORIZONTAL:
        unsigned = _unsigned_for(dtype, predictor)
        words = np.ascontiguousarray(array, dtype.newbyteorder("=")).view(unsigned)
        diff = words.copy()
        diff[:, 1:] -= words[:, :-1]  # módulo 2ⁿ
        return diff.astype(unsigned.newbyteorder(byteorder)).tobytes()
    if predictor == PREDICTOR_FLOATING_POINT:
        _check_float(dtype)
        rows, width = array.shape
        big = np.ascontiguousarray(array, f">f{size}").view(np.uint8)
        planes = big.reshape(rows, width, size).transpose(0, 2, 1).reshape(rows, size * width)
        diff = planes.copy()
        diff[:, 1:] -= planes[:, :-1]  # módulo 256
        return diff.tobytes()
    raise CodecError(f"predictor {predictor} no admitido (sí 1, 2 y 3)")


def _unsigned_for(dtype: np.dtype, predictor: int) -> np.dtype:
    if dtype.kind not in "iuf" or dtype.itemsize not in (1, 2, 4, 8):
        raise CodecError(f"el predictor {predictor} no se admite con el tipo {dtype.name}")
    return np.dtype(f"u{dtype.itemsize}")


def _check_float(dtype: np.dtype) -> None:
    if dtype.kind != "f":
        raise CodecError(
            f"el predictor {PREDICTOR_FLOATING_POINT} es para flotantes y el tipo es "
            f"{dtype.name}"
        )


# --- Bloques ------------------------------------------------------------------------------


def decode_block(
    data: Buffer,
    *,
    compression: int,
    predictor: int,
    dtype: DTypeLike,
    width: int,
    rows: int,
) -> np.ndarray:
    """Una tira o tesela leída: ``data`` (sus bytes en el fichero) descomprimido con
    ``compression`` y con ``predictor`` deshecho, como ``rows × width`` muestras de
    ``dtype`` (el tipo del fichero, con su orden de bytes) en el orden nativo. Una tesela
    viene entera (también la del borde) y la última tira, con sus filas."""
    dtype = np.dtype(dtype)
    _check_positive(width=width, rows=rows)
    raw = decompress(data, compression, width * rows * dtype.itemsize)
    return predictor_decode(raw, predictor, dtype, width, rows)


def encode_block(
    values: np.ndarray, *, predictor: int, level: int = DEFLATE_LEVEL
) -> bytes:
    """Una tesela para escribir: ``values`` con ``predictor`` en little-endian (el orden de
    los GeoTIFF de Geoblender) y comprimida con DEFLATE de nivel ``level``."""
    return deflate_encode(predictor_encode(values, predictor, "<"), level)


def _check_positive(**values: int) -> None:
    for name, value in values.items():
        try:
            number = operator.index(value)
        except TypeError:
            number = 0
        if isinstance(value, bool) or number < 1:
            raise ValueError(f"{name} = {value!r}: debe ser un entero positivo")
