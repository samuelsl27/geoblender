# SPDX-License-Identifier: GPL-3.0-or-later
"""Geometría GeoPackage: cabecera ``GP`` + WKB ISO en float64 *little endian* (spec 002;
RF-002-14; GeoPackage 1.4 §2.1.3; plan 002 §5.1).

Sin GDAL ni dependencias: ``struct`` para las cabeceras y numpy para las coordenadas
(sin bucles por punto). Las coordenadas son **absolutas** (CRS del proyecto) en float64
y vuelven bit a bit; unas absolutas en float32 se rechazan (``TypeError``), como en
``core.georef.world_to_local``.

Tipos: ``POINT``, ``LINESTRING``, ``POLYGON``, ``MULTIPOINT``, ``MULTILINESTRING`` y
``MULTIPOLYGON``, con Z (código WKB ISO + 1000) o sin ella; sin M. Estructura de
``coords`` por tipo (``d`` = 3 con Z, 2 sin ella):

- ``POINT``: array ``(d,)``; ``LINESTRING`` y ``MULTIPOINT``: ``(n, d)``;
- ``POLYGON``: lista de anillos ``(n, d)`` (el primero, el exterior), cerrados y de al
  menos 4 puntos;
- ``MULTILINESTRING``: lista de ``(n, d)``; ``MULTIPOLYGON``: lista de polígonos.

Cabecera que se escribe: versión 0, *little endian*, no extendida y no vacía; envolvente
XY (código 1) o XYZ (código 2) salvo en los puntos, que no la llevan. Al leer se admiten
también las cabeceras y el WKB *big endian* y las envolventes con M (que se ignoran).
Las geometrías vacías no se escriben ni se leen: Geoblender no las usa.
:func:`geometry_wkb` solo quita la cabecera (también de una vacía) para el hash de contenido
de la spec 008, que normaliza el WKB de una capa cualquiera.

Capas de otros programas (spec 006, T15; plan 006 §5.3.6): ``decode_geometry(...,
external=True)`` lee además las geometrías con M o con Z y M (WKB ISO, tipo + 2000 o
+ 3000) y el WKB con las banderas de EWKB (Z = ``0x80000000``, M = ``0x40000000``); la M se
descarta (``Geometry.had_m``) y X, Y y Z vuelven bit a bit. Las curvas, las colecciones, el
EWKB con el SRID dentro y la cabecera extendida se rechazan igual.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..errors import GeometryError

MAGIC = b"GP"
VERSION = 0
WKB_TYPES: dict[str, int] = {
    "POINT": 1,
    "LINESTRING": 2,
    "POLYGON": 3,
    "MULTIPOINT": 4,
    "MULTILINESTRING": 5,
    "MULTIPOLYGON": 6,
}
TYPE_NAMES: dict[int, str] = {code: name for name, code in WKB_TYPES.items()}
Z_OFFSET = 1000  # WKB ISO: tipo + 1000 = con Z
M_OFFSET = 2000  # WKB ISO: tipo + 2000 = con M; + 3000 = con Z y M (solo al leer, external)
EWKB_Z = 0x8000_0000  # banderas de EWKB (solo al leer, external)
EWKB_M = 0x4000_0000
EWKB_FLAGS = EWKB_Z | EWKB_M
_MULTI_PART: dict[str, str] = {
    "MULTIPOINT": "POINT",
    "MULTILINESTRING": "LINESTRING",
    "MULTIPOLYGON": "POLYGON",
}
_ENVELOPE_DOUBLES: dict[int, int] = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}  # código E
_FLAG_LITTLE = 0b0000_0001
_FLAG_EMPTY = 0b0001_0000
_FLAG_EXTENDED = 0b0010_0000
_OBJ = "Geometría GeoPackage"


@dataclass(frozen=True)
class Geometry:
    """Una geometría leída: tipo, SRS, si lleva Z, coordenadas absolutas en float64 (con
    la estructura del módulo) y envolvente en el orden GeoPackage (minx, maxx, miny, maxy
    y, con Z, minz, maxz), o ``None`` si no la lleva. ``had_m``: la fuente traía M, que se
    ha descartado (solo con ``external``)."""

    geometry_type: str
    srs_id: int
    has_z: bool
    coords: Any
    envelope: tuple[float, ...] | None
    had_m: bool = False


def _error(code: str, reason: str, field: str, value: object) -> GeometryError:
    return GeometryError(f"core.geometry_{code}", reason, obj=_OBJ, field=field, value=value)


def _empty(name: str) -> GeometryError:
    return _error(
        "empty",
        "una geometría vacía no se escribe ni se lee (Geoblender no las usa)",
        "tipo",
        name,
    )


def _points(values: object, dims: int, what: str) -> np.ndarray:
    """Matriz ``(n, dims)`` de float64 *little endian*, contigua y finita."""
    array = np.asarray(values)
    if array.dtype.kind == "f" and array.dtype != np.float64:
        raise TypeError(
            f"{what}: las coordenadas absolutas llegan en {array.dtype} y deben llegar "
            "en float64 (ADR-0005)"
        )
    if array.dtype.kind not in "fiu":
        raise _error("coords_invalid", "no son números", what, str(array.dtype))
    array = np.ascontiguousarray(array, dtype="<f8")
    if array.ndim != 2 or array.shape[1] != dims:
        axes = "X, Y, Z" if dims == 3 else "X, Y"
        raise _error(
            "dimension",
            f"cada punto debe tener {dims} coordenadas ({axes})",
            what,
            str(array.shape),
        )
    if not np.isfinite(array).all():
        raise _error("not_finite", "hay coordenadas no finitas", what, "NaN o inf")
    return array


def _ring(values: object, dims: int) -> np.ndarray:
    ring = _points(values, dims, "anillo")
    if len(ring) < 4 or not np.array_equal(ring[0], ring[-1]):
        raise _error(
            "ring_invalid",
            "un anillo debe estar cerrado (el último punto igual al primero) y tener al "
            "menos 4 puntos",
            "anillo",
            f"{len(ring)} puntos",
        )
    return ring


def _normalise(name: str, coords: object, dims: int) -> Any:
    """Las coordenadas validadas, con la estructura del tipo, en float64."""
    if name == "POINT":
        point = np.asarray(coords)
        if point.ndim != 1:
            reason = "un punto es un solo vector de coordenadas"
            raise _error("dimension", reason, name, str(point.shape))
        return _points(point.reshape(1, -1), dims, name)[0]
    if name in ("LINESTRING", "MULTIPOINT"):
        if len(np.asarray(coords)) == 0:
            raise _empty(name)
        points = _points(coords, dims, name)
        if name == "LINESTRING" and len(points) < 2:
            reason = "una línea necesita al menos 2 puntos"
            raise _error("line_short", reason, name, len(points))
        return points
    parts = list(coords)  # type: ignore[call-overload]
    if not parts:
        raise _empty(name)
    if name == "POLYGON":
        return [_ring(ring, dims) for ring in parts]
    return [_normalise(_MULTI_PART[name], part, dims) for part in parts]


def _flat(name: str, coords: Any) -> np.ndarray:
    """Todas las coordenadas, en una matriz ``(n, d)``."""
    if name == "POINT":
        return coords.reshape(1, -1)
    if isinstance(coords, np.ndarray):
        return coords
    part = _MULTI_PART.get(name, "LINESTRING")  # un polígono es una lista de anillos
    return np.vstack([_flat(part, item) for item in coords])


def _wkb(name: str, coords: Any, has_z: bool) -> bytes:
    head = struct.pack("<BI", 1, WKB_TYPES[name] + (Z_OFFSET if has_z else 0))
    if name == "POINT":
        return head + coords.tobytes()
    if name == "LINESTRING":
        return head + struct.pack("<I", len(coords)) + coords.tobytes()
    if name == "POLYGON":
        rings = (struct.pack("<I", len(ring)) + ring.tobytes() for ring in coords)
        return head + struct.pack("<I", len(coords)) + b"".join(rings)
    parts = list(coords)  # MULTIPOINT: las filas de (n, d); si no, la lista de partes
    body = b"".join(_wkb(_MULTI_PART[name], part, has_z) for part in parts)
    return head + struct.pack("<I", len(parts)) + body


def encode_geometry(
    geometry_type: str, coords: object, srs_id: int, has_z: bool
) -> bytes:
    """El blob GeoPackage de una geometría (coordenadas **absolutas**, float64).

    :class:`GeometryError` si el tipo no se admite o la geometría está vacía o mal
    formada; ``TypeError`` si las coordenadas llegan en float32.
    """
    name = str(geometry_type).upper()
    if name not in WKB_TYPES:
        reason = f"tipo no admitido; los admitidos son {', '.join(WKB_TYPES)}"
        raise _error("type_unknown", reason, "tipo", geometry_type)
    if isinstance(srs_id, bool) or not isinstance(srs_id, int):
        raise _error("srs_invalid", "el SRS es un número entero", "srs_id", srs_id)
    dims = 3 if has_z else 2
    data = _normalise(name, coords, dims)
    flags = _FLAG_LITTLE
    envelope = b""
    if name != "POINT":
        points = _flat(name, data)
        bounds: list[float] = []
        for axis in range(dims):
            bounds += [float(points[:, axis].min()), float(points[:, axis].max())]
        envelope = struct.pack(f"<{len(bounds)}d", *bounds)
        flags |= (2 if has_z else 1) << 1
    header = MAGIC + struct.pack("<BBi", VERSION, flags, srs_id)
    return header + envelope + _wkb(name, data, has_z)


class _Reader:
    """Lector de WKB ISO con su posición."""

    def __init__(self, data: bytes, offset: int, external: bool = False) -> None:
        self.data = data
        self.offset = offset
        self.external = external

    def take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            reason = "el blob termina antes de tiempo"
            raise _error("truncated", reason, "longitud", len(self.data))
        chunk = self.data[self.offset : end]
        self.offset = end
        return chunk

    def _type(self) -> tuple[str, str, bool, bool]:
        order = self.take(1)[0]
        if order not in (0, 1):
            raise _error("byte_order", "orden de bytes WKB desconocido", "orden", order)
        endian = "<" if order == 1 else ">"
        (code,) = struct.unpack(f"{endian}I", self.take(4))
        base, has_z, has_m = code, False, False
        if Z_OFFSET < code < Z_OFFSET + 10:
            base, has_z = code - Z_OFFSET, True
        elif self.external and M_OFFSET < code < M_OFFSET + Z_OFFSET + 10:
            base, has_z, has_m = code % Z_OFFSET, code > M_OFFSET + Z_OFFSET, True
        elif self.external and code & EWKB_FLAGS and not code & ~EWKB_FLAGS & 0xFFFF_FFF0:
            base, has_z, has_m = code & 0xF, bool(code & EWKB_Z), bool(code & EWKB_M)
        name = TYPE_NAMES.get(base)
        if name is None:
            reason = (
                f"tipo WKB no admitido; los admitidos son {', '.join(WKB_TYPES)}, con o "
                "sin Z (WKB ISO)"
            )
            raise _error("type_unknown", reason, "tipo WKB", code)
        return endian, name, has_z, has_m

    def geometry(self, expected: str | None = None) -> tuple[str, bool, bool, Any]:
        endian, name, has_z, has_m = self._type()
        if expected is not None and name != expected:
            reason = f"se esperaba una parte {expected}"
            raise _error("part_invalid", reason, "tipo WKB", name)
        keep = 3 if has_z else 2
        dims = keep + has_m  # la M es siempre la última ordenada
        dtype = np.dtype(f"{endian}f8")

        def count() -> int:
            return int(struct.unpack(f"{endian}I", self.take(4))[0])

        def points(number: int) -> np.ndarray:
            raw = self.take(number * dims * 8)
            values = np.frombuffer(raw, dtype=dtype).reshape(number, dims)
            return np.array(values[:, :keep], dtype=np.float64, order="C")  # copia

        coords: Any
        if name == "POINT":
            coords = points(1)[0]
            if not np.isfinite(coords).all():  # punto vacío (NaN), convenio GeoPackage
                raise _empty(name)
        elif name == "LINESTRING":
            coords = points(count())
        elif name == "POLYGON":
            coords = [points(count()) for _ in range(count())]
        else:
            items = [self.geometry(_MULTI_PART[name]) for _ in range(count())]
            if any((item_z, item_m) != (has_z, has_m) for _, item_z, item_m, _ in items):
                raise _error("dimension", "partes con y sin Z o M", "tipo", name)
            coords = [item for _, _, _, item in items]
            if name == "MULTIPOINT":
                coords = np.array(coords, dtype=np.float64).reshape(-1, keep)
        if len(coords) == 0:
            raise _empty(name)
        return name, has_z, has_m, coords


def _envelope(code: int, values: tuple[float, ...]) -> tuple[float, ...] | None:
    if code in (1, 2):
        return values
    if code == 3:  # XYM: se ignora la M
        return values[:4]
    if code == 4:  # XYZM: se ignora la M
        return values[:6]
    return None


def decode_geometry(blob: bytes, *, external: bool = False) -> Geometry:
    """La geometría de un blob GeoPackage; :class:`GeometryError` si no es un blob
    estándar, está vacía, tiene un tipo no admitido o le sobran o faltan bytes.

    ``external``: el blob es de una capa de otro programa (spec 006): se admiten también M
    y ZM (la M se descarta y ``had_m`` lo dice) y las banderas Z y M de EWKB."""
    data = bytes(blob)
    if len(data) < 8 or data[:2] != MAGIC:
        reason = "no empieza por la cabecera «GP» de GeoPackage"
        raise _error("not_gpkg", reason, "cabecera", data[:2].hex())
    version, flags = data[2], data[3]
    if version != VERSION:
        raise _error("version", "versión de cabecera no admitida", "versión", version)
    if flags & _FLAG_EXTENDED:
        reason = "geometría GeoPackage extendida no admitida"
        raise _error("extended", reason, "cabecera", flags)
    if flags & _FLAG_EMPTY:
        raise _empty("cabecera")
    endian = "<" if flags & _FLAG_LITTLE else ">"
    (srs_id,) = struct.unpack(f"{endian}i", data[4:8])
    code = (flags >> 1) & 0b111
    if code not in _ENVELOPE_DOUBLES:
        raise _error("envelope", "código de envolvente no válido", "envolvente", code)
    size = _ENVELOPE_DOUBLES[code]
    reader = _Reader(data, 8, external)
    values = struct.unpack(f"{endian}{size}d", reader.take(size * 8)) if size else ()
    name, has_z, had_m, coords = reader.geometry()
    if reader.offset != len(data):
        reason = "sobran bytes después de la geometría"
        raise _error("trailing", reason, "bytes de más", len(data) - reader.offset)
    return Geometry(name, srs_id, has_z, coords, _envelope(code, values), had_m)


def geometry_wkb(blob: bytes | bytearray | memoryview) -> memoryview:
    """El WKB de un blob GeoPackage sin su cabecera ni su envolvente, tal como está: de
    cualquier orden de bytes, de cualquier tipo y también el de una geometría vacía
    (bandera E), para quien lo normaliza (el hash de contenido de la spec 008,
    ``core.content.wkb``), que lo comprueba entero. :class:`GeometryError` si no empieza
    por la cabecera ``GP`` de la versión 0, es extendida (bandera X) o su envolvente no es
    válida o no cabe; ``TypeError`` si no son bytes."""
    if not isinstance(blob, bytes | bytearray | memoryview):
        raise TypeError(f"un blob GeoPackage son bytes, no {type(blob).__name__}")
    data = memoryview(blob).cast("B")
    if len(data) < 8 or data[:2] != MAGIC:
        reason = "no empieza por la cabecera «GP» de GeoPackage"
        raise _error("not_gpkg", reason, "cabecera", bytes(data[:2]).hex())
    version, flags = data[2], data[3]
    if version != VERSION:
        raise _error("version", "versión de cabecera no admitida", "versión", version)
    if flags & _FLAG_EXTENDED:
        reason = "geometría GeoPackage extendida no admitida"
        raise _error("extended", reason, "cabecera", flags)
    code = (flags >> 1) & 0b111
    if code not in _ENVELOPE_DOUBLES:
        raise _error("envelope", "código de envolvente no válido", "envolvente", code)
    start = 8 + 8 * _ENVELOPE_DOUBLES[code]
    if len(data) < start:
        reason = f"la envolvente no cabe: el blob tiene {len(data)} bytes y necesita {start}"
        raise _error("envelope", reason, "envolvente", code)
    return data[start:]
