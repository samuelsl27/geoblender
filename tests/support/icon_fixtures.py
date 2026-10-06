# SPDX-License-Identifier: GPL-3.0-or-later
"""Fuentes SVG de ejemplo y PNG sintéticos para las pruebas de los iconos (spec 003, T30;
II §1.6 y §1.7). Python puro.

- :data:`VALID_SVG`: un icono válido y asimétrico (un cuadrado gris claro arriba a la
  izquierda y la marca de familia azul abajo a la derecha), con los metadatos CC0.
- :data:`INVALID_SVG`: con texto y una referencia externa.
- :func:`png_bytes`: un PNG RGBA de 8 bits de un color, del tamaño pedido.
- :func:`png_rgba`: los píxeles (de arriba abajo) de un PNG RGBA de 8 bits sin
  entrelazar, para comprobar lo que escribe Blender sin leerlo con Blender.
"""

from __future__ import annotations

import struct
import zlib

METADATA = """  <metadata>
    <rdf:RDF>
      <cc:Work rdf:about="">
        <dc:creator><cc:Agent><dc:title>IMGA</dc:title></cc:Agent></dc:creator>
        <dc:rights>CC0-1.0</dc:rights>
        <cc:license rdf:resource="https://creativecommons.org/publicdomain/zero/1.0/"/>
      </cc:Work>
    </rdf:RDF>
  </metadata>
"""

HEADER = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:cc="http://creativecommons.org/ns#" '
    'viewBox="0 0 16 16" width="16" height="16">\n'
)

VALID_SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n' + HEADER + METADATA
    + '  <rect x="0" y="0" width="8" height="8" fill="#E6E6E6"/>\n'
    + '  <rect x="12" y="12" width="4" height="4" fill="#4C8ED9"/>\n'
    + "</svg>\n"
)

INVALID_SVG = (
    HEADER + METADATA
    + '  <text x="2" y="12">GB</text>\n'
    + '  <rect x="0" y="0" width="16" height="16" style="fill:url(http://ejemplo.es/p.svg#a)"/>\n'
    + "</svg>\n"
)

WITHOUT_LICENSE_SVG = HEADER + '  <circle cx="8" cy="8" r="6" fill="#E6E6E6"/>\n</svg>\n'

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def png_bytes(width: int, height: int, rgba: tuple[int, int, int, int] = (230, 230, 230, 255)
              ) -> bytes:
    """Un PNG RGBA de 8 bits de un solo color."""
    row = b"\x00" + bytes(rgba) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (_SIGNATURE + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(row * height)) + _chunk(b"IEND", b""))


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def png_rgba(data: bytes) -> tuple[int, int, list[bytes]]:
    """(ancho, alto, filas de arriba abajo) de un PNG RGBA de 8 bits sin entrelazar."""
    if not data.startswith(_SIGNATURE):
        raise ValueError("no es un PNG")
    position = len(_SIGNATURE)
    width = height = 0
    compressed = b""
    while position < len(data):
        (length,) = struct.unpack(">I", data[position:position + 4])
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            width, height, depth, color, _c, _f, interlace = struct.unpack(">IIBBBBB", body)
            if (depth, color, interlace) != (8, 6, 0):
                raise ValueError(f"PNG no RGBA de 8 bits: profundidad {depth}, tipo {color}")
        elif kind == b"IDAT":
            compressed += body
    raw = zlib.decompress(compressed)
    stride = width * 4
    rows: list[bytes] = []
    previous = bytearray(stride)
    for index in range(height):
        start = index * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):
            left = line[i - 4] if i >= 4 else 0
            up = previous[i]
            corner = previous[i - 4] if i >= 4 else 0
            if kind == 1:
                line[i] = (line[i] + left) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + up) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif kind == 4:
                line[i] = (line[i] + _paeth(left, up, corner)) & 0xFF
        rows.append(bytes(line))
        previous = line
    return width, height, rows
