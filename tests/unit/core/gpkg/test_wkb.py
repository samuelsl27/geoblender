# SPDX-License-Identifier: GPL-3.0-or-later
"""Geometría GeoPackage: cabecera ``GP`` + WKB ISO float64 *little endian* (spec 002,
T05; RF-002-14; GeoPackage 1.4 §2.1.3).

Las coordenadas son absolutas (CRS del proyecto) en float64: la ida y vuelta tiene que
ser bit a bit, sin perder los milímetros de una coordenada UTM. ``geometry_wkb`` (spec 008,
T12; RF-008-08) da el WKB de un blob sin su cabecera para el hash de contenido.
"""

import struct
import unittest

import numpy as np

from tests.support.package import import_geoblender

wkb = import_geoblender("core.gpkg.wkb")
gpkg = import_geoblender("core.gpkg")
errors = import_geoblender("core.errors")

SRS = 25830
# Coordenadas UTM con milímetros (y decimales que no son exactos en binario).
P1 = (700_123.456, 4_400_987.654, 850.123)
P2 = (700_200.001, 4_401_000.999, 851.5)
P3 = (700_300.789, 4_400_900.111, 849.25)
RING = np.array([P1, P2, P3, P1])
HOLE = np.array(
    [
        (700_150.0, 4_400_950.0, 850.0),
        (700_160.0, 4_400_950.0, 850.0),
        (700_160.0, 4_400_960.0, 850.0),
        (700_150.0, 4_400_950.0, 850.0),
    ]
)

CASES = {
    "POINT": np.array(P1),
    "LINESTRING": np.array([P1, P2, P3]),
    "POLYGON": [RING, HOLE],
    "MULTIPOINT": np.array([P1, P2]),
    "MULTILINESTRING": [np.array([P1, P2]), np.array([P2, P3, P1])],
    "MULTIPOLYGON": [[RING], [RING, HOLE]],
}


def _flat(coords: object) -> np.ndarray:
    """Todas las coordenadas de una estructura anidada, en una matriz (n, d)."""
    if isinstance(coords, np.ndarray):
        return coords.reshape(-1, coords.shape[-1])
    return np.vstack([_flat(part) for part in coords])  # type: ignore[union-attr]


def _drop_z(coords: object) -> object:
    if isinstance(coords, np.ndarray):
        return np.ascontiguousarray(coords[..., :2])
    return [_drop_z(part) for part in coords]  # type: ignore[union-attr]


def _assert_same(test: unittest.TestCase, actual: object, expected: object) -> None:
    """Igualdad bit a bit de dos estructuras de coordenadas."""
    if isinstance(expected, np.ndarray):
        test.assertIsInstance(actual, np.ndarray)
        test.assertEqual(actual.dtype, np.float64)
        test.assertEqual(actual.shape, expected.shape)
        test.assertEqual(actual.tobytes(), expected.astype(np.float64).tobytes())
        return
    test.assertEqual(len(actual), len(expected))  # type: ignore[arg-type]
    for got, want in zip(actual, expected, strict=True):  # type: ignore[call-overload]
        _assert_same(test, got, want)


class RoundTripTest(unittest.TestCase):
    def test_round_trip_bit_exact(self) -> None:
        """RF-002-14: de Point a MultiPolygon, con Z y sin Z, la ida y vuelta conserva
        cada coordenada UTM con milímetros bit a bit, el tipo, el SRS y la Z; volver a
        codificar lo decodificado da los mismos bytes."""
        for name, coords in CASES.items():
            for has_z in (True, False):
                data = coords if has_z else _drop_z(coords)
                with self.subTest(tipo=name, z=has_z):
                    blob = gpkg.encode_geometry(name, data, SRS, has_z)
                    geometry = gpkg.decode_geometry(blob)
                    self.assertEqual(geometry.geometry_type, name)
                    self.assertEqual(geometry.srs_id, SRS)
                    self.assertEqual(geometry.has_z, has_z)
                    _assert_same(self, geometry.coords, data)
                    again = gpkg.encode_geometry(name, geometry.coords, SRS, has_z)
                    self.assertEqual(again, blob)

    def test_header_and_wkb_layout(self) -> None:
        """RF-002-14: cabecera ``GP``, versión 0, orden *little endian*, sin envolvente en
        un punto; WKB ISO *little endian* con el código de tipo + 1000 si lleva Z."""
        blob = gpkg.encode_geometry("POINT", np.array(P1), SRS, True)
        self.assertEqual(blob[:2], b"GP")
        self.assertEqual(blob[2], 0)
        flags = blob[3]
        self.assertEqual(flags & 0b1, 1)  # little endian
        self.assertEqual((flags >> 1) & 0b111, 0)  # sin envolvente
        self.assertEqual(flags & 0b0011_0000, 0)  # estándar, no vacía
        self.assertEqual(struct.unpack("<i", blob[4:8])[0], SRS)
        self.assertEqual(blob[8], 1)  # WKB little endian
        self.assertEqual(struct.unpack("<I", blob[9:13])[0], 1001)  # Point Z
        self.assertEqual(struct.unpack("<3d", blob[13:]), P1)
        flat = gpkg.encode_geometry("LINESTRING", np.array([P1[:2], P2[:2]]), SRS, False)
        self.assertEqual(struct.unpack("<I", flat[8 + 32 + 1 : 8 + 32 + 5])[0], 2)

    def test_envelope(self) -> None:
        """RF-002-14: la envolvente (orden GeoPackage: minx, maxx, miny, maxy y, con Z,
        minz, maxz) es la de todas las coordenadas; un punto no lleva."""
        for name, coords in CASES.items():
            for has_z in (True, False):
                data = coords if has_z else _drop_z(coords)
                with self.subTest(tipo=name, z=has_z):
                    geometry = gpkg.decode_geometry(
                        gpkg.encode_geometry(name, data, SRS, has_z)
                    )
                    if name == "POINT":
                        self.assertIsNone(geometry.envelope)
                        continue
                    points = _flat(data)
                    expected = [points[:, 0].min(), points[:, 0].max()]
                    expected += [points[:, 1].min(), points[:, 1].max()]
                    if has_z:
                        expected += [points[:, 2].min(), points[:, 2].max()]
                    self.assertEqual(geometry.envelope, tuple(expected))


class RejectTest(unittest.TestCase):
    def assertRejected(self, call: object, *args: object) -> errors.GeometryError:
        with self.assertRaises(errors.GeometryError) as caught:
            call(*args)  # type: ignore[operator]
        self.assertTrue(str(caught.exception))
        return caught.exception

    def test_empty_geometries(self) -> None:
        """RF-002-14: una geometría vacía (sin puntos, sin anillos o sin partes) se
        rechaza con mensaje al codificar; y un blob marcado como vacío, al decodificar."""
        empty = {
            "LINESTRING": np.zeros((0, 2)),
            "POLYGON": [],
            "MULTIPOINT": np.zeros((0, 2)),
            "MULTILINESTRING": [],
            "MULTIPOLYGON": [],
        }
        for name, coords in empty.items():
            with self.subTest(tipo=name):
                error = self.assertRejected(gpkg.encode_geometry, name, coords, SRS, False)
                self.assertIn("vacía", str(error))
        blob = bytearray(gpkg.encode_geometry("POINT", np.array(P1[:2]), SRS, False))
        blob[3] |= 0b0001_0000  # marca de geometría vacía
        error = self.assertRejected(gpkg.decode_geometry, bytes(blob))
        self.assertIn("vacía", str(error))

    def test_unknown_types(self) -> None:
        """RF-002-14: un tipo desconocido se rechaza con mensaje al codificar y al
        decodificar (p. ej. CircularString, código 8, o GeometryCollection, 7)."""
        error = self.assertRejected(
            gpkg.encode_geometry, "CIRCULARSTRING", np.array([P1[:2]]), SRS, False
        )
        self.assertIn("CIRCULARSTRING", str(error))
        good = gpkg.encode_geometry("POINT", np.array(P1[:2]), SRS, False)
        for code in (7, 8, 2001, 0x80000001):
            with self.subTest(codigo=code):
                bad = good[:9] + struct.pack("<I", code) + good[13:]
                error = self.assertRejected(gpkg.decode_geometry, bad)
                self.assertIn(str(code), str(error))

    def test_malformed(self) -> None:
        """RF-002-14: un blob sin ``GP``, de otra versión, truncado o con bytes de más se
        rechaza con mensaje."""
        good = gpkg.encode_geometry("LINESTRING", np.array([P1[:2], P2[:2]]), SRS, False)
        for label, blob in {
            "sin GP": b"XX" + good[2:],
            "versión 1": good[:2] + b"\x01" + good[3:],
            "truncado": good[:-3],
            "bytes de más": good + b"\x00",
            "extendido": good[:3] + bytes([good[3] | 0b0010_0000]) + good[4:],
            "corto": b"GP",
        }.items():
            with self.subTest(label):
                self.assertRejected(gpkg.decode_geometry, blob)

    def test_bad_coordinates(self) -> None:
        """RF-002-14: absolutas en float32, dimensión que no coincide con ``has_z``,
        coordenadas no finitas, anillos abiertos o de menos de 4 puntos y líneas de un
        punto se rechazan."""
        open_ring = np.array([P1, P2, P3, P2])
        cases = {
            "float32": ("LINESTRING", np.array([P1, P2], dtype=np.float32), True),
            "Z de más": ("LINESTRING", np.array([P1, P2]), False),
            "Z de menos": ("LINESTRING", np.array([P1[:2], P2[:2]]), True),
            "NaN": ("POINT", np.array([np.nan, 1.0]), False),
            "anillo abierto": ("POLYGON", [open_ring], True),
            "anillo corto": ("POLYGON", [np.array([P1, P2, P1])], True),
            "línea de un punto": ("LINESTRING", np.array([P1]), True),
            "punto con dos": ("POINT", np.array([P1, P2]), True),
        }
        for label, (name, coords, has_z) in cases.items():
            with self.subTest(label):
                if label == "float32":
                    with self.assertRaises(TypeError):
                        gpkg.encode_geometry(name, coords, SRS, has_z)
                    continue
                self.assertRejected(gpkg.encode_geometry, name, coords, SRS, has_z)


def _header(flags: int, envelope: tuple[float, ...] = (), *, order: str = "<") -> bytes:
    """Una cabecera ``GP`` de la versión 0 con ``flags``, el SRS de las pruebas y la
    envolvente ``envelope`` en el orden de bytes ``order``."""
    srs = struct.pack(f"{order}i", SRS)
    return b"GP\x00" + bytes([flags]) + srs + struct.pack(f"{order}{len(envelope)}d", *envelope)


class GeometryWkbTest(unittest.TestCase):
    """RF-008-08 (spec 008, T12): el WKB de un blob GeoPackage sin su cabecera, tal como
    está, para que lo normalice el hash de contenido (``core.content``)."""

    def test_body_after_header_and_envelope(self) -> None:
        """RF-008-08: tras la cabecera de 8 bytes y la envolvente que diga su código (0, 4,
        6 u 8 dobles), en cualquier orden de bytes, queda el WKB sin tocar."""
        point = gpkg.encode_geometry("POINT", np.array(P1[:2]), SRS, False)
        self.assertEqual(bytes(wkb.geometry_wkb(point)), point[8:])
        line = gpkg.encode_geometry("LINESTRING", np.array([P1, P2]), SRS, True)
        self.assertEqual(bytes(wkb.geometry_wkb(line)), line[8 + 48:])
        body = b"\x00" + struct.pack(">I", 1) + struct.pack(">2d", *P1[:2])
        for code, doubles in ((0, 0), (1, 4), (2, 6), (3, 6), (4, 8)):
            for order, little in ((">", 0), ("<", 1)):
                with self.subTest(envolvente=code, orden=order):
                    blob = _header(code << 1 | little, (1.5,) * doubles, order=order) + body
                    self.assertEqual(bytes(wkb.geometry_wkb(blob)), body)
                    self.assertEqual(bytes(wkb.geometry_wkb(bytearray(blob))), body)

    def test_empty_flag_is_accepted(self) -> None:
        """RF-008-08: un blob marcado como vacío (bandera E) da su WKB vacío: el hash de
        contenido distingue una geometría vacía de una nula."""
        empty_polygon = b"\x01" + struct.pack("<II", 3, 0)
        blob = _header(0b0001_0001) + empty_polygon
        self.assertEqual(bytes(wkb.geometry_wkb(blob)), empty_polygon)

    def test_malformed_headers_are_rejected(self) -> None:
        """RF-008-08: sin ``GP``, de otra versión, extendido, con un código de envolvente
        que no existe o que no cabe en el blob se rechaza con mensaje."""
        good = gpkg.encode_geometry("LINESTRING", np.array([P1[:2], P2[:2]]), SRS, False)
        cases = {
            "sin GP": b"XX" + good[2:],
            "versión 1": good[:2] + b"\x01" + good[3:],
            "extendido": good[:3] + bytes([good[3] | 0b0010_0000]) + good[4:],
            "envolvente 5": _header(5 << 1 | 1) + good[40:],
            "envolvente cortada": good[:20],
            "corto": b"GP\x00\x01",
        }
        for label, blob in cases.items():
            with self.subTest(label), self.assertRaises(errors.GeometryError) as caught:
                wkb.geometry_wkb(blob)
            self.assertTrue(caught.exception.code.startswith("core.geometry_"))
        with self.assertRaises(TypeError):
            wkb.geometry_wkb("GP")  # type: ignore[arg-type]


def _blob(body: bytes, *, envelope: tuple[float, ...] = (), code: int = 0) -> bytes:
    """Cabecera ``GP`` *little endian* (envolvente de código ``code``) + ``body``."""
    flags = 1 | (code << 1)
    return b"GP" + bytes([0, flags]) + struct.pack("<i", SRS) + struct.pack(
        f"<{len(envelope)}d", *envelope
    ) + body


def _wkb(code: int, values: np.ndarray, *, order: str = "<", count: bool = True) -> bytes:
    head = struct.pack(f"{order}BI", 1 if order == "<" else 0, code)
    size = struct.pack(f"{order}I", len(values)) if count else b""
    return head + size + np.asarray(values, dtype=f"{order}f8").tobytes()


ZM_LINE = np.array([[700_123.456, 4_400_987.654, 850.123, 0.0],
                    [700_200.001, 4_401_000.999, 851.5, 76.6]])
XYM_LINE = ZM_LINE[:, [0, 1, 3]]


class ExternalGeometryTest(unittest.TestCase):
    """Geometrías de las capas de otros programas (spec 006, T15; plan 006 §5.3.6): con
    ``external=True`` se leen también las de M o ZM (la M se descarta: ``had_m``) y el WKB
    con las banderas de EWKB; sin él, el GeoPackage del proyecto sigue igual de estricto."""

    def test_m_and_zm_dropped(self) -> None:
        """RF-006-12: Point M, LineString M y ZM y MultiLineString ZM (WKB ISO): X, Y (y
        Z) bit a bit, sin la M, con ``had_m``; sin ``external``, se rechazan."""
        multi = struct.pack("<BII", 1, 3005, 2) + _wkb(3002, ZM_LINE) + _wkb(
            3002, ZM_LINE[::-1]
        )
        cases = {
            "Point M": (_wkb(2001, XYM_LINE[0], count=False), "POINT", False,
                        ZM_LINE[0, :2]),
            "LineString M": (_wkb(2002, XYM_LINE), "LINESTRING", False, ZM_LINE[:, :2]),
            "LineString ZM": (_wkb(3002, ZM_LINE), "LINESTRING", True, ZM_LINE[:, :3]),
            "MultiLineString ZM": (multi, "MULTILINESTRING", True,
                                   [ZM_LINE[:, :3], ZM_LINE[::-1, :3]]),
        }
        for label, (body, name, has_z, expected) in cases.items():
            with self.subTest(label):
                blob = _blob(body)
                geometry = gpkg.decode_geometry(blob, external=True)
                self.assertEqual((geometry.geometry_type, geometry.has_z, geometry.had_m),
                                 (name, has_z, True))
                _assert_same(self, geometry.coords, expected)
                if isinstance(geometry.coords, np.ndarray):
                    self.assertTrue(geometry.coords.flags.c_contiguous)
                with self.assertRaises(errors.GeometryError):
                    gpkg.decode_geometry(blob)

    def test_ewkb_flags(self) -> None:
        """RF-006-12: EWKB (Z = 0x80000000, M = 0x40000000) con ``external``: igual que el
        ISO; con SRID dentro (0x20000000) u otros bits, no: tipo no admitido."""
        for label, code, values, has_z in (
            ("Z", 0x8000_0002, ZM_LINE[:, :3], True),
            ("M", 0x4000_0002, XYM_LINE, False),
            ("ZM", 0xC000_0002, ZM_LINE, True),
        ):
            with self.subTest(label):
                geometry = gpkg.decode_geometry(_blob(_wkb(code, values)), external=True)
                self.assertEqual(geometry.has_z, has_z)
                self.assertEqual(geometry.had_m, label != "Z")
                _assert_same(self, geometry.coords, ZM_LINE[:, : 3 if has_z else 2])
        srid = struct.pack("<I", SRS)
        for code, body in (
            (0x2000_0002, _wkb(0x2000_0002, ZM_LINE[:, :2])),
            (0xA000_0002, _wkb(0xA000_0002, ZM_LINE[:, :3])[:5] + srid
             + _wkb(0xA000_0002, ZM_LINE[:, :3])[5:]),
            (0x8000_0102, _wkb(0x8000_0102, ZM_LINE[:, :3])),
        ):
            with self.subTest(codigo=hex(code)):
                with self.assertRaises(errors.GeometryError) as caught:
                    gpkg.decode_geometry(_blob(body), external=True)
                self.assertEqual(caught.exception.code, "core.geometry_type_unknown")
                self.assertEqual(caught.exception.value, code)

    def test_envelope_with_m(self) -> None:
        """RF-006-12: una envolvente XYZM (código 4) se lee sin la M."""
        envelope = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)
        geometry = gpkg.decode_geometry(_blob(_wkb(3002, ZM_LINE), envelope=envelope, code=4),
                                        external=True)
        self.assertEqual(geometry.envelope, envelope[:6])

    def test_still_rejected(self) -> None:
        """RF-006-12: con ``external`` siguen rechazadas las curvas, las colecciones, las
        partes con y sin M mezcladas, la cabecera extendida y las vacías."""
        mixed = struct.pack("<BII", 1, 3005, 2) + _wkb(3002, ZM_LINE) + _wkb(
            1002, ZM_LINE[:, :3]
        )
        point = gpkg.encode_geometry("POINT", np.array(P1[:2]), SRS, False)
        empty = point[:3] + bytes([point[3] | 0b0001_0000]) + point[4:]
        extended = point[:3] + bytes([point[3] | 0b0010_0000]) + point[4:]
        for label, blob in {
            "CircularString": _blob(_wkb(8, ZM_LINE[:, :2])),
            "CircularString ZM": _blob(_wkb(3008, ZM_LINE)),
            "GeometryCollection": _blob(struct.pack("<BII", 1, 7, 0)),
            "partes mezcladas": _blob(mixed),
            "extendida": extended,
            "vacía": empty,
        }.items():
            with self.subTest(label):
                with self.assertRaises(errors.GeometryError):
                    gpkg.decode_geometry(blob, external=True)

    def test_project_geometries_unchanged(self) -> None:
        """RF-002-14: lo que escribe Geoblender se lee igual con y sin ``external`` y sin
        ``had_m``."""
        for name, coords in CASES.items():
            with self.subTest(tipo=name):
                blob = gpkg.encode_geometry(name, coords, SRS, True)
                strict = gpkg.decode_geometry(blob)
                lenient = gpkg.decode_geometry(blob, external=True)
                self.assertFalse(strict.had_m or lenient.had_m)
                _assert_same(self, lenient.coords, strict.coords)


if __name__ == "__main__":
    unittest.main()
