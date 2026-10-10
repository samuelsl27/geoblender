# SPDX-License-Identifier: GPL-3.0-or-later
"""WKB canónico del normalizador ``gbch/1`` (spec 008; RF-008-08; ADR-0024 §4, fila
«Vectorial»).

La geometría de una entidad se hashea en **WKB ISO *little-endian* con dobles canónicos**,
escrito de nuevo desde las coordenadas leídas: el orden de bytes del original (también el de
cada parte de una colección), las banderas del WKB extendido (Z ``0x80000000``, M
``0x40000000`` y SRID ``0x20000000`` de PostGIS y del GDAL antiguo) y el SRID que lleve dentro
no influyen. Dobles canónicos: todo NaN es el canónico ``0x7FF8000000000000`` y −0,0 es 0,0
(``core.hashing.canonical_float``); lo demás, bit a bit (sin tolerancia, D-8).

- Tipos: los de ISO SQL/MM que puede guardar un GeoPackage (:data:`GEOMETRY_TYPES`): punto,
  línea, polígono, sus colecciones, colección de geometrías, curvas (arco, curva compuesta,
  polígono curvo, multicurva, multisuperficie), superficie poliédrica, TIN y triángulo.
- **Vacías**: se escriben tal cual vienen —0 puntos, 0 anillos o 0 partes—; un punto vacío
  lleva sus coordenadas NaN (convenio de GeoPackage y GDAL), que quedan canónicas.
- **Dimensiones**: ``dims`` (:data:`DIMS`) son las que conserva el importador. De cada
  geometría se escriben las suyas que estén en ``dims``: una Z o una M de más no cuenta (no
  se importa) y una que falta no se inventa (una línea XY en una capa XYZ queda XY).

Lo que no tiene forma única —un orden de bytes o un tipo desconocidos, códigos ISO y banderas
extendidas a la vez, más partes o puntos de los que caben, bytes de más, colecciones anidadas
más de :data:`MAX_DEPTH` niveles— se rechaza con ``ValueError``. Python puro (``struct``).
"""

from __future__ import annotations

import struct

from ..hashing import CANONICAL_NAN

DIMS: tuple[str, ...] = ("XY", "XYZ", "XYM", "XYZM")
"""Las dimensiones de una capa: X e Y siempre, y Z, M o las dos."""
GEOMETRY_TYPES: dict[int, str] = {
    1: "Point",
    2: "LineString",
    3: "Polygon",
    4: "MultiPoint",
    5: "MultiLineString",
    6: "MultiPolygon",
    7: "GeometryCollection",
    8: "CircularString",
    9: "CompoundCurve",
    10: "CurvePolygon",
    11: "MultiCurve",
    12: "MultiSurface",
    15: "PolyhedralSurface",
    16: "TIN",
    17: "Triangle",
}
"""Los tipos de geometría por su código WKB base (sin Z ni M)."""
MAX_DEPTH = 32
"""Niveles de colecciones anidadas que se admiten (ninguna capa real se acerca)."""

EWKB_Z = 0x80000000
EWKB_M = 0x40000000
EWKB_SRID = 0x20000000
_EWKB_FLAGS = EWKB_Z | EWKB_M | EWKB_SRID
_POINT = 1
_SEQUENCES = frozenset({2, 8})  # n puntos
_RINGS = frozenset({3, 17})  # n anillos de n puntos
_ORDERS = {1: "<", 0: ">"}
_KEEP = {"XY": (False, False), "XYZ": (True, False), "XYM": (False, True), "XYZM": (True, True)}
_HEAD = struct.Struct("<BI")
_COUNT = struct.Struct("<I")


def check_dims(dims: object) -> str:
    """``dims`` si es una de :data:`DIMS`; si no, ``ValueError``."""
    if not isinstance(dims, str) or dims not in _KEEP:
        raise ValueError(f"dimensiones desconocidas: {dims!r} (son {', '.join(DIMS)})")
    return dims


def canonical_wkb(data: bytes | bytearray | memoryview, dims: str) -> bytes:
    """El WKB canónico de ``gbch/1`` de la geometría ``data`` (WKB ISO o extendido, de
    cualquier orden de bytes) con las dimensiones ``dims`` que conserva la capa.
    ``data`` no se modifica."""
    keep_z, keep_m = _KEEP[check_dims(dims)]
    if not isinstance(data, bytes | bytearray | memoryview):
        raise TypeError(
            f"una geometría es su WKB en bytes (o None si es nula), no {type(data).__name__}"
        )
    raw = bytes(data)
    out: list[bytes] = []
    end = _geometry(raw, 0, keep_z, keep_m, out, 0)
    if end != len(raw):
        raise ValueError(
            f"sobran {len(raw) - end} bytes después de la geometría (WKB de {len(raw)} bytes)"
        )
    return b"".join(out)


def _truncated(data: bytes, needed: int, offset: int) -> ValueError:
    return ValueError(
        f"el WKB termina antes de tiempo: faltan {needed - (len(data) - offset)} bytes en la "
        f"posición {offset} (tiene {len(data)})"
    )


def _count(data: bytes, offset: int, endian: str) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise _truncated(data, 4, offset)
    (count,) = struct.unpack_from(endian + "I", data, offset)
    return count, offset + 4


def _geometry(
    data: bytes, offset: int, keep_z: bool, keep_m: bool, out: list[bytes], depth: int
) -> int:
    """Escribe en ``out`` la geometría que empieza en ``offset``; devuelve dónde acaba."""
    if depth > MAX_DEPTH:
        raise ValueError(f"colecciones anidadas más de {MAX_DEPTH} niveles")
    if offset + 5 > len(data):
        raise _truncated(data, 5, offset)
    endian = _ORDERS.get(data[offset])
    if endian is None:
        raise ValueError(
            f"orden de bytes WKB desconocido: {data[offset]} en la posición {offset} "
            "(1 es little endian y 0, big endian)"
        )
    (code,) = struct.unpack_from(endian + "I", data, offset + 1)
    offset += 5
    flags = code & _EWKB_FLAGS
    thousands, base = divmod(code & ~_EWKB_FLAGS, 1000)
    if base not in GEOMETRY_TYPES or thousands > 3:
        raise ValueError(f"tipo de geometría WKB desconocido: {code} (0x{code:08X})")
    if thousands and flags & (EWKB_Z | EWKB_M):
        raise ValueError(
            f"el tipo WKB {code} (0x{code:08X}) mezcla el código ISO de Z y M con las banderas "
            "del WKB extendido"
        )
    has_z = thousands in (1, 3) or bool(flags & EWKB_Z)
    has_m = thousands in (2, 3) or bool(flags & EWKB_M)
    if flags & EWKB_SRID:  # el SRID de dentro del WKB no cuenta: va el CRS de la capa
        if offset + 4 > len(data):
            raise _truncated(data, 4, offset)
        offset += 4
    out_z = has_z and keep_z
    out_m = has_m and keep_m
    out.append(_HEAD.pack(1, base + 1000 * out_z + 2000 * out_m))
    width = 2 + has_z + has_m
    axes = (0, 1) + ((2,) if out_z else ()) + ((2 + has_z,) if out_m else ())
    if base == _POINT:
        return _points(data, offset, endian, 1, width, axes, out)
    count, offset = _count(data, offset, endian)
    out.append(_COUNT.pack(count))
    if base in _SEQUENCES:
        return _points(data, offset, endian, count, width, axes, out)
    if base in _RINGS:
        for _ in range(count):
            size, offset = _count(data, offset, endian)
            out.append(_COUNT.pack(size))
            offset = _points(data, offset, endian, size, width, axes, out)
        return offset
    if count * 5 > len(data) - offset:  # cada parte ocupa al menos 5 bytes
        raise _truncated(data, count * 5, offset)
    for _ in range(count):
        offset = _geometry(data, offset, keep_z, keep_m, out, depth + 1)
    return offset


def _points(
    data: bytes,
    offset: int,
    endian: str,
    count: int,
    width: int,
    axes: tuple[int, ...],
    out: list[bytes],
) -> int:
    """Escribe ``count`` puntos de ``width`` dobles con solo los ejes ``axes``, canónicos."""
    if not count:
        return offset
    total = count * width
    size = total * 8
    if offset + size > len(data):
        raise _truncated(data, size, offset)
    values = struct.unpack_from(f"{endian}{total}d", data, offset)
    if len(axes) != width:
        values = tuple(
            values[start + axis] for start in range(0, total, width) for axis in axes
        )
    canonical = [CANONICAL_NAN if value != value else value + 0.0 for value in values]
    out.append(struct.pack(f"<{len(canonical)}d", *canonical))
    return offset + size
