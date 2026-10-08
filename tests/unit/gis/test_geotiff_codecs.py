# SPDX-License-Identifier: GPL-3.0-or-later
"""Códecs del GeoTIFF propio: LZW, PackBits, DEFLATE y predictores 2 y 3 (spec 006, T05;
plan 006 §5.3.6 y §5.4 A3 y A4; ADR-0020).

- **RF-006-08** (importar un MDT con cada cota igual a la de la fuente): las tiras y las
  teselas LZW, PackBits y DEFLATE que escribió el GDAL de QGIS (``tests/data/gis/geotiff/``,
  T01) se decodifican, con sus predictores, **al mismo array, bit a bit,** que la versión
  sin compresión del mismo dato, y esa versión es la superficie del README (Float64 a
  ≤ 10⁻⁹ m de la fórmula; Float32, su ``numpy.float32``; Int16, su redondeo).
- **RF-006-24** (exportar sin pérdida): los predictores 2 (enteros) y 3 (flotantes de 32 y
  64 bits) van y vuelven bit a bit (NaN con su carga, ±∞, −0, subnormales), también con
  filas de una sola celda y en los dos órdenes de bytes; el bloque del escritor (predictor
  3 y DEFLATE de nivel 6) se lee igual.

El LZW de GDAL de los datos de T01 solo llega a códigos de 10 bits; los de 11 y 12 bits, el
CLEAR de la tabla llena (4094 entradas) y el caso KwKwK se prueban con flujos de un
codificador de referencia con las reglas del de libtiff (``tif_lzw.c``), escrito aquí, sin
nada del decodificador. El lector de TIFF de estas pruebas (:func:`_tiff`) es el mínimo para
sacar las tiras y las teselas: el de verdad es el de T06.
"""

import math
import random
import struct
import unittest
import zlib

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

codecs = import_geoblender("gis.geotiff.codecs")

GEOTIFF = ROOT / "tests" / "data" / "gis" / "geotiff"
REF_E, REF_N = 700000.0, 4400000.0
WEST = 700000.0
NODATA = -9999.0
HOLE = (slice(20, 23), slice(30, 34))  # filas 20–22 y columnas 30–33 desde el NO
NROWS, NCOLS = 48, 64

# (SampleFormat, BitsPerSample) → tipo de numpy de un TIFF «II».
DTYPES = {(1, 8): "<u1", (2, 16): "<i2", (3, 32): "<f4", (3, 64): "<f8"}

CLEAR, EOI, FIRST, FULL = 256, 257, 258, 4094


# --- Lectura mínima de los TIFF de T01 ---------------------------------------------------


def _tiff(name: str) -> tuple[dict[int, tuple[int, ...]], bytes]:
    """Etiquetas SHORT y LONG del primer IFD de un TIFF clásico «II» y sus bytes."""
    data = (GEOTIFF / name).read_bytes()
    if data[:4] != b"II*\0":
        raise AssertionError(f"{name}: no es un TIFF clásico «II»")
    (offset,) = struct.unpack_from("<I", data, 4)
    (count,) = struct.unpack_from("<H", data, offset)
    tags: dict[int, tuple[int, ...]] = {}
    for i in range(count):
        entry = offset + 2 + 12 * i
        tag, kind, n, value = struct.unpack_from("<HHII", data, entry)
        if kind not in (3, 4):
            continue
        fmt = "H" if kind == 3 else "I"
        where = entry + 8 if struct.calcsize(fmt) * n <= 4 else value
        tags[tag] = struct.unpack_from(f"<{n}{fmt}", data, where)
    return tags, data


def _layout(tags: dict[int, tuple[int, ...]]) -> tuple[int, int, np.dtype, int, int]:
    dtype = np.dtype(DTYPES[(tags[339][0], tags[258][0])])
    return tags[256][0], tags[257][0], dtype, tags[259][0], tags.get(317, (1,))[0]


def _plain(name: str) -> np.ndarray:
    """Un TIFF sin compresión ni predictor en tiras, leído solo con numpy (sin los códecs)."""
    tags, data = _tiff(name)
    width, height, dtype, compression, predictor = _layout(tags)
    if (compression, predictor, 322 in tags) != (1, 1, False):
        raise AssertionError(f"{name}: no es un TIFF sin compresión en tiras")
    raw = b"".join(data[o : o + n] for o, n in zip(tags[273], tags[279], strict=True))
    return np.frombuffer(raw, dtype).reshape(height, width).astype(dtype.newbyteorder("="))


def _decoded(name: str) -> tuple[np.ndarray, int, int]:
    """Un TIFF de T01 decodificado tira a tira o tesela a tesela con ``decode_block``; con
    su compresión y su predictor."""
    tags, data = _tiff(name)
    width, height, dtype, compression, predictor = _layout(tags)
    image = np.full((height, width), np.nan if dtype.kind == "f" else 0, dtype)
    if 322 in tags:
        tile_w, tile_h = tags[322][0], tags[323][0]
        across = -(-width // tile_w)
        for k, (offset, size) in enumerate(zip(tags[324], tags[325], strict=True)):
            row, col = divmod(k, across)
            block = codecs.decode_block(
                data[offset : offset + size], compression=compression, predictor=predictor,
                dtype=dtype, width=tile_w, rows=tile_h,
            )
            target = image[row * tile_h : (row + 1) * tile_h, col * tile_w : (col + 1) * tile_w]
            target[...] = block[: target.shape[0], : target.shape[1]]
    else:
        per_strip = tags[278][0]
        for k, (offset, size) in enumerate(zip(tags[273], tags[279], strict=True)):
            start = k * per_strip
            rows = min(per_strip, height - start)
            image[start : start + rows] = codecs.decode_block(
                data[offset : offset + size], compression=compression, predictor=predictor,
                dtype=dtype, width=width, rows=rows,
            )
    return image, compression, predictor


def _surface(north: float, step: float) -> np.ndarray:
    """La superficie del README (float64, ``math.sin``) en el centro de cada celda de una
    base de 64 × 48 con oeste 700 000; −9999 en el hueco."""
    z = np.empty((NROWS, NCOLS))
    for r in range(NROWS):
        y = (north - REF_N) - (r + 0.5) * step
        for c in range(NCOLS):
            x = (WEST - REF_E) + (c + 0.5) * step
            z[r, c] = 800.0 + 0.5 * x - 0.25 * y + 3.0 * math.sin(x / 7.0)
    z[HOLE] = NODATA
    return z


def _same_bits(test: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    test.assertEqual(got.dtype, expected.dtype)
    test.assertEqual(got.shape, expected.shape)
    test.assertTrue(got.tobytes() == expected.tobytes(), "los bits no coinciden")


# --- LZW de referencia (reglas del codificador de libtiff) -------------------------------


def _pack(codes: list[tuple[int, int]]) -> bytes:
    """Empaqueta (código, ancho) con el bit más significativo primero, como libtiff; el
    último byte se rellena con ceros."""
    out = bytearray()
    acc = nbits = 0
    for code, width in codes:
        acc = (acc << width) | code
        nbits += width
        while nbits >= 8:
            nbits -= 8
            out.append((acc >> nbits) & 0xFF)
        acc &= (1 << nbits) - 1
    if nbits:
        out.append((acc << (8 - nbits)) & 0xFF)
    return bytes(out)


def _lzw_encode(data: bytes) -> tuple[bytes, list[tuple[int, int]]]:
    """LZW con las reglas del codificador de libtiff, sin su reinicio por razón de
    compresión: CLEAR al empezar; cada código emitido añade una entrada; el ancho pasa de n
    a n + 1 bits cuando la siguiente entrada libre pasa de 2ⁿ − 1; CLEAR (con el ancho de
    entonces) cuando llega a 4094; al final, el último código, el mismo ajuste y EOI.
    Devuelve los bytes y los (código, ancho) emitidos."""
    codes = [(CLEAR, 9)]
    width = 9
    if not data:
        codes.append((EOI, width))
        return _pack(codes), codes
    table = {bytes((i,)): i for i in range(256)}
    free = FIRST
    current = data[:1]
    for i in range(1, len(data)):
        candidate = current + data[i : i + 1]
        if candidate in table:
            current = candidate
            continue
        codes.append((table[current], width))
        table[candidate] = free
        free += 1
        current = data[i : i + 1]
        if free == FULL:
            codes.append((CLEAR, width))
            table = {bytes((j,)): j for j in range(256)}
            free, width = FIRST, 9
        elif free > (1 << width) - 1:
            width += 1
    codes.append((table[current], width))
    free += 1
    if free == FULL:
        codes.append((CLEAR, width))
        width = 9
    elif free > (1 << width) - 1:
        width += 1
    codes.append((EOI, width))
    return _pack(codes), codes


def _symbols(alphabet: bytes, count: int, seed: int) -> bytes:
    rng = random.Random(seed)
    return bytes(rng.choice(alphabet) for _ in range(count))


# --- Pruebas -----------------------------------------------------------------------------


class GdalFilesTestCase(unittest.TestCase):
    """Las tiras y teselas de GDAL decodificadas = su versión sin compresión."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.f64 = _plain("f64_strip.tif")
        cls.f32 = _plain("f32_strip.tif")
        cls.i16 = _plain("i16_strip.tif")

    def test_uncompressed_follow_surface(self) -> None:
        """RF-006-08 (referencia de las demás): ``f64_strip`` está a ≤ 10⁻⁹ m de la
        superficie, ``f32_strip`` es su ``numpy.float32`` e ``i16_strip``, su redondeo al
        metro; −9999 en el hueco."""
        z = _surface(4400048.0, 1.0)
        self.assertLessEqual(float(np.max(np.abs(self.f64 - z))), 1e-9)
        _same_bits(self, self.f32, z.astype(np.float32))
        expected = np.vectorize(round)(z).astype(np.int16)
        _same_bits(self, self.i16, expected)

    def test_lzw_predictor2_int16_strips(self) -> None:
        """RF-006-08: ``i16_strip_lzw_p2`` (LZW + predictor 2, tres tiras de 16 filas, con
        códigos de 9 y 10 bits) = ``i16_strip`` (sin compresión, una tira), bit a bit."""
        image, compression, predictor = _decoded("i16_strip_lzw_p2.tif")
        self.assertEqual((compression, predictor), (codecs.COMPRESSION_LZW, 2))
        _same_bits(self, image, self.i16)
        # Cada tira pasa de CLEAR + 254 códigos de 9 bits (y el relleno): tiene de 10 bits.
        self.assertGreater(min(_tiff("i16_strip_lzw_p2.tif")[0][279]) * 8, 9 * 255 + 7)

    def test_lzw_predictor3_float32_tiles(self) -> None:
        """RF-006-08: ``f32_tile_lzw_p3`` (LZW + predictor 3, 12 teselas de 16 × 16) =
        ``f32_strip``, bit a bit."""
        image, compression, predictor = _decoded("f32_tile_lzw_p3.tif")
        self.assertEqual((compression, predictor), (codecs.COMPRESSION_LZW, 3))
        _same_bits(self, image, self.f32)

    def test_packbits_float32_strips(self) -> None:
        """RF-006-08: ``f32_strip_packbits`` (PackBits, tiras de 32 y 16 filas) =
        ``f32_strip``, bit a bit."""
        image, compression, predictor = _decoded("f32_strip_packbits.tif")
        self.assertEqual((compression, predictor), (codecs.COMPRESSION_PACKBITS, 1))
        _same_bits(self, image, self.f32)

    def test_deflate_predictor3(self) -> None:
        """RF-006-08: ``f64_strip_deflate_p3`` (DEFLATE + predictor 3, Float64) =
        ``f64_strip`` bit a bit, y ``f32_strip_deflate_p3_05m`` (Float32 de 0,5 m) es el
        ``numpy.float32`` de la superficie en su rejilla."""
        image, compression, predictor = _decoded("f64_strip_deflate_p3.tif")
        self.assertEqual((compression, predictor), (codecs.COMPRESSION_DEFLATE, 3))
        _same_bits(self, image, self.f64)
        image, _, _ = _decoded("f32_strip_deflate_p3_05m.tif")
        _same_bits(self, image, _surface(4400024.0, 0.5).astype(np.float32))

    def test_uncompressed_through_codecs(self) -> None:
        """RF-006-08: sin compresión (1) y sin predictor (1), ``decode_block`` da lo mismo
        que numpy solo, también con teselas de borde (``f32_tile``) y en big-endian
        (``f32_mm``, con la misma disposición que ``f32_strip``)."""
        image, _, _ = _decoded("f32_tile.tif")
        _same_bits(self, image, self.f32)
        tags, _ = _tiff("f32_strip.tif")
        mm = (GEOTIFF / "f32_mm.tif").read_bytes()
        offsets = struct.unpack_from(">2I", mm, _mm_tag_offset(mm, 273))
        parts = [
            codecs.decode_block(mm[o : o + n], compression=1, predictor=1, dtype=">f4",
                                width=64, rows=rows)
            for o, n, rows in zip(offsets, tags[279], (32, 16), strict=True)
        ]
        _same_bits(self, np.vstack(parts), self.f32)


def _mm_tag_offset(data: bytes, wanted: int) -> int:
    """Dónde están los valores de la etiqueta ``wanted`` (de más de 4 bytes) de un TIFF
    «MM»."""
    (offset,) = struct.unpack_from(">I", data, 4)
    (count,) = struct.unpack_from(">H", data, offset)
    for i in range(count):
        tag, _, _, value = struct.unpack_from(">HHII", data, offset + 2 + 12 * i)
        if tag == wanted:
            return value
    raise AssertionError(f"sin la etiqueta {wanted}")


class LzwTestCase(unittest.TestCase):
    """LZW de TIFF: códigos de 9 a 12 bits, cambio anticipado, CLEAR, EOI y KwKwK."""

    def _round_trip(self, data: bytes) -> list[tuple[int, int]]:
        stream, codes = _lzw_encode(data)
        self.assertEqual(codecs.lzw_decode(stream), data)
        self.assertEqual(codecs.lzw_decode(stream, len(data)), data)
        return codes

    def test_widths_9_to_12_and_full_table(self) -> None:
        """RF-006-08: un flujo con códigos de 9, 10, 11 y 12 bits (cambio al llegar la
        tabla a 511, 1023 y 2047) y CLEAR por tabla llena (4094) se decodifica entero: con
        4 símbolos (cadenas largas) y con 256 (cadenas cortas)."""
        for alphabet, count in ((b"ACGT", 40000), (bytes(range(256)), 9000)):
            with self.subTest(simbolos=len(alphabet)):
                codes = self._round_trip(_symbols(alphabet, count, seed=count))
                self.assertEqual({w for _, w in codes}, {9, 10, 11, 12})
                self.assertGreaterEqual(sum(c == CLEAR for c, _ in codes), 2)
                self.assertIn((CLEAR, 12), codes)

    def test_kwkwk_and_short_streams(self) -> None:
        """RF-006-08: rachas que piden el código que aún no está en la tabla (KwKwK), un
        solo byte, el flujo vacío (CLEAR + EOI) y los 256 bytes repetidos, de ida y
        vuelta."""
        for data in (b"\0" * 5000, b"ab" * 3000 + b"a", b"x", b"",
                     bytes(range(256)) * 3):
            with self.subTest(n=len(data)):
                self._round_trip(data)

    def test_end_of_data_without_eoi_and_trailing_bytes(self) -> None:
        """RF-006-08: un flujo sin EOI se lee hasta el final de los datos; lo que sigue al
        EOI se ignora; con un tamaño esperado menor, se recorta a él."""
        data = _symbols(b"ACGT", 3000, seed=3)
        stream, codes = _lzw_encode(data)
        self.assertEqual(codecs.lzw_decode(_pack(codes[:-1])), data)
        self.assertEqual(codecs.lzw_decode(stream + b"\xff\x00\x12"), data)
        self.assertEqual(codecs.lzw_decode(stream, 100), data[:100])

    def test_corrupt_streams(self) -> None:
        """RF-006-08, RF-006-09: un código fuera de la tabla, un primer código tras CLEAR
        que no es un byte, datos que no llegan al tamaño esperado y el LZW antiguo de
        libtiff (bit menos significativo primero) son ``CodecError``."""
        cases = {
            "fuera de la tabla": (_pack([(CLEAR, 9), (65, 9), (300, 9), (EOI, 9)]), None),
            "primer código": (_pack([(CLEAR, 9), (258, 9), (EOI, 9)]), None),
            "incompleto": (_lzw_encode(b"abcabc")[0], 7),
            "antiguo": (b"\x00\x01\x02\x03", None),
        }
        for name, (stream, expected) in cases.items():
            with self.subTest(caso=name), self.assertRaises(codecs.CodecError) as caught:
                codecs.lzw_decode(stream, expected)
            self.assertIsInstance(caught.exception, ValueError)
            self.assertIn("LZW", str(caught.exception))


class PackBitsTestCase(unittest.TestCase):
    """PackBits (Apple TN1023, TIFF 6.0 §9)."""

    def test_runs(self) -> None:
        """RF-006-08: el ejemplo de la especificación TIFF (secuencias literales, repetidas
        y el 128 que no hace nada) y el recorte al tamaño esperado."""
        packed = bytes.fromhex("FE AA 02 80 00 2A FD AA 03 80 00 2A 22 F7 AA")
        unpacked = bytes.fromhex(
            "AA AA AA 80 00 2A AA AA AA AA 80 00 2A 22 AA AA AA AA AA AA AA AA AA AA"
        )
        self.assertEqual(codecs.packbits_decode(packed), unpacked)
        self.assertEqual(codecs.packbits_decode(b"\x80" + packed + b"\x80"), unpacked)
        self.assertEqual(codecs.packbits_decode(packed, 5), unpacked[:5])
        self.assertEqual(codecs.packbits_decode(packed, len(unpacked)), unpacked)

    def test_corrupt(self) -> None:
        """RF-006-08, RF-006-09: una secuencia literal o repetida que pasa del final de los
        datos, o menos bytes de los esperados, son ``CodecError``."""
        for stream, expected in ((b"\x05abc", None), (b"\x01ab\xfd", None), (b"\x01ab", 3)):
            with self.subTest(datos=stream), self.assertRaises(codecs.CodecError) as caught:
                codecs.packbits_decode(stream, expected)
            self.assertIn("PackBits", str(caught.exception))


class DeflateAndDispatchTestCase(unittest.TestCase):
    """DEFLATE (zlib) y la elección del códec por la etiqueta ``Compression``."""

    def test_deflate(self) -> None:
        """RF-006-08, RF-006-24: DEFLATE de nivel 6 = ``zlib.compress(…, 6)`` (mismos
        bytes, determinista); se lee con los códigos 8 y 32946; recorte al tamaño
        esperado; datos corruptos o incompletos son ``CodecError``."""
        raw = _symbols(b"0123456789", 5000, seed=8)
        packed = codecs.deflate_encode(raw)
        self.assertEqual(packed, zlib.compress(raw, 6))
        self.assertEqual(codecs.DEFLATE_LEVEL, 6)
        for code in (codecs.COMPRESSION_DEFLATE, codecs.COMPRESSION_DEFLATE_OLD):
            self.assertEqual(codecs.decompress(packed, code, len(raw)), raw)
        self.assertEqual(codecs.deflate_decode(packed, 10), raw[:10])
        for bad, expected in ((b"not zlib", None), (packed[: len(packed) // 2], len(raw)),
                              (packed, len(raw) + 1)):
            with self.subTest(n=len(bad)), self.assertRaises(codecs.CodecError) as caught:
                codecs.deflate_decode(bad, expected)
            self.assertIn("DEFLATE", str(caught.exception))

    def test_dispatch(self) -> None:
        """RF-006-08, RF-006-09: ``decompress`` elige el códec por el código TIFF (1, 5, 8,
        32946, 32773); otro (JPEG 7, ZSTD 50000) o un bloque sin compresión que no llega al
        tamaño esperado son ``CodecError`` con su nombre y su código."""
        raw = b"abcabcabcabcabc"
        self.assertEqual(codecs.decompress(raw + b"zz", 1, len(raw)), raw)
        self.assertEqual(codecs.decompress(_lzw_encode(raw)[0], 5, len(raw)), raw)
        self.assertEqual(codecs.decompress(b"\xfe" + b"a", 32773, 3), b"aaa")
        self.assertEqual(
            codecs.COMPRESSIONS, frozenset({1, 5, 8, 32946, 32773})
        )
        for code, name in ((7, "JPEG"), (50000, "ZSTD")):
            self.assertEqual(codecs.compression_name(code), name)
            with self.subTest(codigo=code), self.assertRaises(codecs.CodecError) as caught:
                codecs.decompress(raw, code, len(raw))
            self.assertIn(name, str(caught.exception))
            self.assertIn(str(code), str(caught.exception))
        self.assertEqual(codecs.compression_name(12345), "desconocida")
        with self.assertRaises(codecs.CodecError):
            codecs.decompress(raw, 1, len(raw) + 1)


def _special_floats(dtype: str) -> np.ndarray:
    """Valores de borde de un flotante: NaN con carga, ±∞, ±0, subnormales, extremos,
    −9999 y cotas."""
    info = np.finfo(dtype)
    bits = np.dtype(dtype).itemsize * 8
    utype = np.dtype(f"u{bits // 8}")
    payload_nan = np.array([(1 << (bits - 1)) - 1], utype).view(dtype)[0]  # NaN con carga
    return np.array(
        [np.nan, payload_nan, np.inf, -np.inf, 0.0, -0.0, info.smallest_subnormal,
         -info.smallest_subnormal, info.max, -info.max, info.tiny, -9999.0, 812.345,
         4400000.25, 1e-300 if bits == 64 else 1e-30],
        dtype,
    )


class PredictorTestCase(unittest.TestCase):
    """Predictores 2 (diferencia horizontal) y 3 (coma flotante), ida y vuelta."""

    SHAPES = ((1, 1), (6, 1), (1, 9), (7, 13))

    def _same(self, got: np.ndarray, expected: np.ndarray) -> None:
        native = expected.astype(expected.dtype.newbyteorder("="))
        _same_bits(self, got, native)

    def test_predictor2_integers_round_trip(self) -> None:
        """RF-006-24, RF-006-08: predictor 2 en int16 (y en 8 y 32 bits, con y sin signo)
        va y vuelve bit a bit, con los extremos del tipo (la resta da la vuelta módulo
        2ⁿ), filas de una celda y los dos órdenes de bytes."""
        rng = np.random.default_rng(5)
        for name in ("<i2", "<u2", "<i1", "<u1", "<i4", "<u4"):
            info = np.iinfo(name)
            for rows, width in self.SHAPES:
                values = rng.integers(info.min, info.max, (rows, width), endpoint=True,
                                      dtype=np.dtype(name))
                values.flat[:2] = (info.max, info.min)[: values.size]
                for order in "<>":
                    with self.subTest(tipo=name, forma=(rows, width), orden=order):
                        raw = codecs.predictor_encode(values, 2, order)
                        self.assertEqual(len(raw), values.nbytes)
                        dtype = np.dtype(name).newbyteorder(order)
                        self._same(codecs.predictor_decode(raw, 2, dtype, width, rows), values)

    def test_predictor2_definition(self) -> None:
        """RF-006-08: predictor 2 es la diferencia con la muestra anterior de la fila, en
        el orden de bytes del fichero, módulo 2ⁿ: [1, 3, 6] → [1, 2, 3]; [32767, −32768] →
        [32767, 1]."""
        raw = codecs.predictor_encode(np.array([[1, 3, 6], [32767, -32768, -32767]],
                                               np.int16), 2, ">")
        self.assertEqual(struct.unpack(">6h", raw), (1, 2, 3, 32767, 1, 1))

    def test_predictor3_floats_round_trip(self) -> None:
        """RF-006-24, RF-006-08: predictor 3 en float32 y float64 va y vuelve bit a bit
        (NaN con su carga, ±∞, −0, subnormales), con filas de una celda; los bytes no
        dependen del orden del fichero (TIFF TN3: planos del más significativo al menos)."""
        rng = np.random.default_rng(7)
        for name in ("<f4", "<f8"):
            special = _special_floats(name)
            for rows, width in (*self.SHAPES, (special.size, 1), (1, special.size)):
                values = (rng.standard_normal((rows, width)) * 900.0).astype(name)
                n = min(values.size, special.size)
                values.flat[:n] = special[:n]
                little = codecs.predictor_encode(values, 3, "<")
                self.assertEqual(codecs.predictor_encode(values, 3, ">"), little)
                for order in "<>":
                    with self.subTest(tipo=name, forma=(rows, width), orden=order):
                        dtype = np.dtype(name).newbyteorder(order)
                        decoded = codecs.predictor_decode(little, 3, dtype, width, rows)
                        self._same(decoded, values)

    def test_predictor3_definition(self) -> None:
        """RF-006-08: [1,0; 2,0] en float32 → bytes big-endian 3F800000 40000000 → planos
        [3F 40][80 00][00 00][00 00] → diferencias 3F 01 40 80 00 00 00 00."""
        raw = codecs.predictor_encode(np.array([[1.0, 2.0]], np.float32), 3)
        self.assertEqual(raw.hex(" ").upper(), "3F 01 40 80 00 00 00 00")

    def test_predictor1_and_byte_order(self) -> None:
        """RF-006-08: sin predictor, los bytes son los valores en el orden pedido y se
        leen en el orden nativo."""
        values = np.array([[812.5, -9999.0, np.nan]], np.float32)
        raw = codecs.predictor_encode(values, 1, ">")
        self.assertEqual(raw, values.astype(">f4").tobytes())
        self._same(codecs.predictor_decode(raw, 1, ">f4", 3, 1), values)

    def test_predictor_errors(self) -> None:
        """RF-006-08, RF-006-09: el predictor 3 en enteros, un predictor desconocido o un
        bloque más corto que filas × ancho × tamaño son ``CodecError``."""
        cases = (
            (b"\0" * 8, 3, "<i2", "predictor 3"),
            (b"\0" * 8, 4, "<f4", "predictor 4"),
            (b"\0" * 7, 1, "<f4", "necesita 8 bytes"),
            (b"\0" * 3, 2, "<i2", "necesita 4 bytes"),
        )
        for raw, predictor, dtype, text in cases:
            with self.subTest(predictor=predictor, tipo=dtype, n=len(raw)), \
                    self.assertRaises(codecs.CodecError) as caught:
                codecs.predictor_decode(raw, predictor, dtype, 2, 1)
            self.assertIn(text, str(caught.exception))


class BlockTestCase(unittest.TestCase):
    """El bloque del escritor (predictor y DEFLATE de nivel 6) y su lectura."""

    def test_writer_block_round_trip(self) -> None:
        """RF-006-24: una tesela Float64 con NaN (perfil ``project``) y una Float32 con
        −9999 (perfil ``deliverable``), con predictor 3 y DEFLATE de nivel 6, y una Int16
        con predictor 2, se leen con ``decode_block`` bit a bit; dos codificaciones dan los
        mismos bytes."""
        z = _surface(4400048.0, 1.0)
        project = np.where(z == NODATA, np.nan, z)
        cases = ((project, 3, "<f8"), (z.astype(np.float32), 3, "<f4"),
                 (np.round(z).astype(np.int16), 2, "<i2"), (project[:, :1].copy(), 3, "<f8"))
        for values, predictor, dtype in cases:
            with self.subTest(tipo=dtype, forma=values.shape):
                block = codecs.encode_block(values, predictor=predictor)
                self.assertEqual(block, codecs.encode_block(values, predictor=predictor))
                self.assertEqual(
                    block, zlib.compress(codecs.predictor_encode(values, predictor), 6)
                )
                rows, width = values.shape
                decoded = codecs.decode_block(
                    block, compression=codecs.COMPRESSION_DEFLATE, predictor=predictor,
                    dtype=dtype, width=width, rows=rows,
                )
                _same_bits(self, decoded, values)


if __name__ == "__main__":
    unittest.main()
