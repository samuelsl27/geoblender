# SPDX-License-Identifier: GPL-3.0-or-later
"""Constructor de WKB para las pruebas del normalizador ``gbch/1`` (spec 008, T06;
RF-008-08; ADR-0024 §4, fila «Vectorial»).

Escribe una geometría en cualquiera de las variantes que puede dar un fichero: WKB ISO
(tipo + 1000 con Z, + 2000 con M), WKB extendido de PostGIS y del GDAL antiguo (banderas
``0x80000000`` Z, ``0x40000000`` M y ``0x20000000`` con SRID), *little* o *big endian*, y
con otro orden de bytes en las partes de una colección. Es independiente de
``core.content``: solo ``struct``, para que las pruebas comparen el normalizador con bytes
escritos por otro camino.

Una geometría es ``(tipo, contenido)``:

- ``("Point", [x, y, …])``; ``("Point", None)`` es el punto vacío (coordenadas NaN, como lo
  escriben GeoPackage y GDAL);
- ``("LineString", puntos)`` y ``("CircularString", puntos)``;
- ``("Polygon", anillos)`` y ``("Triangle", anillos)``: listas de puntos;
- las colecciones (``MultiPoint``, ``MultiLineString``, ``MultiPolygon``,
  ``GeometryCollection``, ``CompoundCurve``, ``CurvePolygon``, ``MultiCurve``,
  ``MultiSurface``, ``PolyhedralSurface``, ``TIN``): lista de geometrías.

``dims`` es ``"XY"``, ``"XYZ"``, ``"XYM"`` o ``"XYZM"``: cada punto tiene esas coordenadas.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from typing import Any

CODES: dict[str, int] = {
    "Point": 1,
    "LineString": 2,
    "Polygon": 3,
    "MultiPoint": 4,
    "MultiLineString": 5,
    "MultiPolygon": 6,
    "GeometryCollection": 7,
    "CircularString": 8,
    "CompoundCurve": 9,
    "CurvePolygon": 10,
    "MultiCurve": 11,
    "MultiSurface": 12,
    "PolyhedralSurface": 15,
    "TIN": 16,
    "Triangle": 17,
}
SEQUENCES = frozenset({"LineString", "CircularString"})
RINGS = frozenset({"Polygon", "Triangle"})
WIDTH = {"XY": 2, "XYZ": 3, "XYM": 3, "XYZM": 4}
EWKB_Z = 0x80000000
EWKB_M = 0x40000000
EWKB_SRID = 0x20000000
NAN_BITS = 0x7FF8000000000000

type Geom = tuple[str, Any]


def _code(name: str, dims: str, flavor: str, srid: int | None) -> int:
    base = CODES[name]
    has_z, has_m = "Z" in dims, "M" in dims
    if flavor == "iso":
        if srid is not None:
            raise ValueError("el WKB ISO no lleva SRID")
        return base + 1000 * has_z + 2000 * has_m
    if flavor != "ewkb":
        raise ValueError(f"variante desconocida: {flavor!r}")
    code = base | (EWKB_Z if has_z else 0) | (EWKB_M if has_m else 0)
    return code | (EWKB_SRID if srid is not None else 0)


def _points(points: Sequence[Sequence[float]], dims: str, order: str) -> bytes:
    width = WIDTH[dims]
    values: list[float] = []
    for point in points:
        if len(point) != width:
            raise ValueError(f"un punto {dims} tiene {width} coordenadas, no {len(point)}")
        values.extend(point)
    return struct.pack(f"{order}{len(values)}d", *values)


def encode(
    geom: Geom,
    dims: str = "XY",
    *,
    order: str = "<",
    flavor: str = "iso",
    srid: int | None = None,
    parts_order: str | None = None,
) -> bytes:
    """El WKB de ``geom``. ``order``: ``"<"`` o ``">"``; ``flavor``: ``"iso"`` o ``"ewkb"``;
    ``srid``: solo en ``"ewkb"`` (en la geometría de fuera); ``parts_order``: el orden de
    bytes de las partes de una colección (por defecto, el mismo)."""
    name, body = geom
    head = struct.pack(f"{order}BI", 1 if order == "<" else 0, _code(name, dims, flavor, srid))
    if srid is not None:
        head += struct.pack(f"{order}I", srid)
    if name == "Point":
        if body is None:
            nan = struct.unpack("<d", struct.pack("<Q", NAN_BITS))[0]
            body = [nan] * WIDTH[dims]
        return head + _points([body], dims, order)
    count = struct.pack(f"{order}I", len(body))
    if name in SEQUENCES:
        return head + count + _points(body, dims, order)
    if name in RINGS:
        rings = b"".join(
            struct.pack(f"{order}I", len(ring)) + _points(ring, dims, order) for ring in body
        )
        return head + count + rings
    inner = order if parts_order is None else parts_order
    parts = b"".join(
        encode(part, dims, order=inner, flavor=flavor, parts_order=parts_order)
        for part in body
    )
    return head + count + parts


def iso_le(geom: Geom, dims: str = "XY") -> bytes:
    """El WKB ISO *little endian*: la forma canónica de ``gbch/1`` si las coordenadas ya son
    canónicas (sin NaN con carga ni −0,0)."""
    return encode(geom, dims)


def square(x0: float, y0: float, side: float, *, z: float | None = None) -> list[list[float]]:
    """Anillo exterior cerrado de un cuadrado (antihorario), con Z si se da."""
    corners = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side), (x0, y0)]
    return [[x, y] if z is None else [x, y, z] for x, y in corners]
