# SPDX-License-Identifier: GPL-3.0-or-later
"""Lector del GeoTIFF propio (spec 006, T06; plan 006 §5.3.2, §5.3.6 y §5.4 A3; ADR-0020).

- **RF-006-08** (importar un MDT con cada cota igual a la de la fuente): cada GeoTIFF de
  ``tests/data/gis/geotiff/`` que se admite (T01: Float64, Float32 e Int16; sin compresión,
  LZW, PackBits y DEFLATE; tiras y teselas; TIFF y BigTIFF; «II» y «MM») se lee con la
  rejilla (oeste, norte, dx, dy, columnas y filas) que declara y con los valores de la
  fórmula del README: Float64 a ≤ 10⁻⁹ m; Float32, **su** ``numpy.float32`` pasado a
  float64 sin cambio (bit a bit); Int16, su redondeo; el sin dato declarado (−9999) y las
  teselas que no están en el fichero, NaN. *PixelIsPoint* desplaza la rejilla medio paso
  hacia el noroeste y lo dice en una nota. Los demás tipos (enteros de 8 a 32 bits y
  Float64 en «MM»), una ``ModelTransformation`` sin giro y un punto de enlace que no es el
  píxel (0, 0), con ficheros mínimos escritos en la prueba.
- **RF-006-09** (rechazar lo no admitido con fichero, característica, valor y qué hacer, sin
  importar nada): JPEG, georreferencia girada, dos bandas, escala y offset, más celdas que
  ``gis.import.max_cells`` (el límite se lee de ``gis.params`` al leer), y además el tipo de
  dato, el predictor que no corresponde al tipo, unidades que no son metros, un CRS o una
  referencia vertical fuera del catálogo, falta de georreferencia, varios puntos de
  enlace, un fichero que no es TIFF, un bloque dañado o cortado y un ráster sin datos.
- **RF-006-04** (no suponer el CRS): sin claves de CRS, ``declared_crs = None``; un CRS
  definido por parámetros (sin código EPSG), ``None`` con una nota; la referencia vertical,
  solo si el fichero la declara (``VerticalCSTypeGeoKey``).
- **RF-006-10** (no tocar la entrada): leer todos los ficheros, también los rechazados, no
  cambia el listado de la carpeta ni la fecha de ningún fichero.

Avance y cancelación cada tira o tesela (RF-006-28): el avance llega a 1 y la cancelación
para con ``JobCancelled``.
"""

import math
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

gis = import_geoblender("gis")
geotiff = import_geoblender("gis.geotiff")
reader = import_geoblender("gis.geotiff.reader")
geokeys = import_geoblender("gis.geotiff.geokeys")
tiff = import_geoblender("gis.geotiff.tiff")
raster = import_geoblender("gis.raster")
messages = import_geoblender("gis.messages")
params = import_geoblender("gis.params")
georef = import_geoblender("core.georef")
worker_api = import_geoblender("jobs.worker_api")

GEOTIFF = ROOT / "tests" / "data" / "gis" / "geotiff"
CATALOG = georef.load_catalog()

REF_E, REF_N = 700000.0, 4400000.0
WEST = 700000.0
NORTH_1M, NORTH_05M = 4400048.0, 4400024.0
NROWS, NCOLS = 48, 64
HOLE = (slice(20, 23), slice(30, 34))  # filas 20–22 y columnas 30–33 desde el NO

F32_NAMES = (
    "f32_strip.tif",
    "f32_strip_packbits.tif",
    "f32_tile.tif",
    "f32_tile_lzw_p3.tif",
    "f32_bigtiff.tif",
    "f32_mm.tif",
    "f32_epsg23030.tif",
    "f32_nocrs.tif",
    "f32_pixelispoint.tif",
)
READABLE = (
    *F32_NAMES,
    "f32_tile_sparse.tif",
    "f32_strip_deflate_p3_05m.tif",
    "f64_strip.tif",
    "f64_strip_deflate_p3.tif",
    "i16_strip.tif",
    "i16_strip_lzw_p2.tif",
)
REJECTED = ("u8_jpeg.tif", "f32_rotated.tif", "f32_2bands.tif", "f32_scale_offset.tif")


def _surface(north: float, step: float) -> np.ndarray:
    """La superficie del README (float64 con ``math.sin``, en el mismo orden de
    operaciones que el generador) en el centro de cada celda de una base de 64 × 48 con
    oeste 700 000; el hueco, NaN."""
    x = (WEST - REF_E) + (np.arange(NCOLS) + 0.5) * step
    y = (north - REF_N) - (np.arange(NROWS) + 0.5) * step
    sines = np.array([math.sin(value / 7.0) for value in x.tolist()])
    z = 800.0 + 0.5 * x[None, :] - 0.25 * y[:, None] + 3.0 * sines[None, :]
    z[HOLE] = np.nan
    return z


SURFACE_1M = _surface(NORTH_1M, 1.0)
F32_1M = SURFACE_1M.astype(np.float32).astype(np.float64)
I16_1M = np.round(SURFACE_1M)
F32_05M = _surface(NORTH_05M, 0.5).astype(np.float32).astype(np.float64)

_CACHE: dict[str, object] = {}


def _read(name: str) -> object:
    """Un fichero de T01 leído una vez (las pruebas no modifican el resultado)."""
    if name not in _CACHE:
        _CACHE[name] = reader.read_geotiff(GEOTIFF / name)
    return _CACHE[name]


# --- TIFF mínimos escritos en la prueba --------------------------------------------------

_FORMATS = {1: "B", 2: "s", 3: "H", 4: "I", 11: "f", 12: "d", 16: "Q"}


def _keys(*pairs: tuple[int, int]) -> tuple[int, ...]:
    """Un GeoKeyDirectory con claves cortas (valor en el propio directorio)."""
    directory = [1, 1, 0, len(pairs)]
    for key, value in pairs:
        directory += [key, 0, 1, value]
    return tuple(directory)


KEYS_25830 = _keys((1024, 1), (1025, 1), (3072, 25830), (3076, 9001))


def _build(
    path: Path,
    image: np.ndarray,
    *,
    byteorder: str = "<",
    tags: dict[int, tuple[int, object]] | None = None,
    drop: tuple[int, ...] = (),
    data: bytes | None = None,
    compression: int = 1,
) -> Path:
    """Escribe un TIFF clásico de una tira con ``image`` (sus bytes en ``byteorder`` o
    ``data``), georreferencia (1 × 1 m, esquina NO en 700 000; 4 400 000 + filas),
    EPSG:25830 y sin dato −9999; ``tags`` añade o sustituye etiquetas ({etiqueta: (tipo,
    valores)}) y ``drop`` quita las que se nombran."""
    image = np.asarray(image)
    rows, cols = image.shape
    dtype = image.dtype
    raw = data if data is not None else image.astype(dtype.newbyteorder(byteorder)).tobytes()
    sample_format = {"u": 1, "i": 2, "f": 3}[dtype.kind]
    entries: dict[int, tuple[int, object]] = {
        256: (4, [cols]),
        257: (4, [rows]),
        258: (3, [dtype.itemsize * 8]),
        259: (3, [compression]),
        262: (3, [1]),
        273: (4, [8]),
        277: (3, [1]),
        278: (4, [rows]),
        279: (4, [len(raw)]),
        339: (3, [sample_format]),
        33550: (12, [1.0, 1.0, 0.0]),
        33922: (12, [0.0, 0.0, 0.0, 700000.0, 4400000.0 + rows, 0.0]),
        34735: (3, list(KEYS_25830)),
        42113: (2, "-9999"),
    }
    entries.update(tags or {})
    for tag in drop:
        entries.pop(tag, None)
    ifd_offset = 8 + len(raw) + len(raw) % 2
    extra_offset = ifd_offset + 2 + 12 * len(entries) + 4
    ifd = bytearray(struct.pack(f"{byteorder}H", len(entries)))
    extra = bytearray()
    for tag in sorted(entries):
        kind, values = entries[tag]
        if kind == 2:
            payload = str(values).encode("ascii") + b"\0"
            count = len(payload)
        else:
            values = list(values)  # type: ignore[call-overload]
            count = len(values)
            payload = struct.pack(f"{byteorder}{count}{_FORMATS[kind]}", *values)
        if len(payload) <= 4:
            field = payload.ljust(4, b"\0")
        else:
            field = struct.pack(f"{byteorder}I", extra_offset + len(extra))
            extra += payload + b"\0" * (len(payload) % 2)
        ifd += struct.pack(f"{byteorder}HHI", tag, kind, count) + field
    ifd += b"\0\0\0\0"
    mark = b"II" if byteorder == "<" else b"MM"
    header = mark + struct.pack(f"{byteorder}HI", 42, ifd_offset)
    path.write_bytes(header + raw + b"\0" * (len(raw) % 2) + bytes(ifd) + bytes(extra))
    return path


SMALL = np.array(
    [[801.25, 802.5, 803.75, -9999.0], [804.0, 805.5, 806.125, 807.0], [1.5, 2.0, 3.0, 4.0]],
    np.float32,
)
SMALL_READ = np.where(SMALL == -9999.0, np.nan, SMALL).astype(np.float64)


class _TempMixin:
    def tmp(self, name: str) -> Path:
        folder = getattr(self, "_folder", None)
        if folder is None:
            folder = Path(tempfile.mkdtemp(prefix="gb-tif-"))
            self._folder = folder
            self.addCleanup(shutil.rmtree, folder, True)  # type: ignore[attr-defined]
        return folder / name


def _same(test: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    test.assertEqual(got.dtype, np.float64)
    test.assertEqual(got.shape, expected.shape)
    equal = (got == expected) | (np.isnan(got) & np.isnan(expected))
    test.assertTrue(equal.all(), f"valores distintos en {int((~equal).sum())} celdas")


# --- Los ficheros de T01 -----------------------------------------------------------------


class ReadDataFilesTest(unittest.TestCase):
    """RF-006-08 y RF-006-04 con los GeoTIFF de ``tests/data/gis/geotiff/``."""

    def _grid(self, source: object, north: float = NORTH_1M, step: float = 1.0) -> None:
        g = source.grid
        self.assertEqual(
            (g.west, g.north, g.dx, g.dy, g.ncols, g.nrows),
            (WEST, north, step, step, NCOLS, NROWS),
        )

    def test_float64_matches_formula(self) -> None:
        """RF-006-08: Float64 sin compresión y DEFLATE + predictor 3, a ≤ 10⁻⁹ m de la
        fórmula, iguales entre sí bit a bit y con el hueco (−9999) como NaN."""
        plain = _read("f64_strip.tif")
        packed = _read("f64_strip_deflate_p3.tif")
        for source in (plain, packed):
            self._grid(source)
            self.assertEqual(source.values.dtype, np.float64)
            self.assertEqual(source.source_dtype, "float64")
            self.assertEqual(source.nodata_value, -9999.0)
            nan = np.isnan(source.values)
            self.assertTrue(np.array_equal(nan, np.isnan(SURFACE_1M)))
            self.assertLessEqual(float(np.max(np.abs(source.values[~nan] - SURFACE_1M[~nan]))),
                                 1e-9)
        _same(self, packed.values, plain.values)

    def test_float32_is_its_float32_without_change(self) -> None:
        """RF-006-08: cada variante Float32 da, bit a bit, el ``numpy.float32`` de la
        fórmula pasado a float64 (sin redondeo adicional) y la rejilla declarada."""
        for name in F32_NAMES:
            with self.subTest(name=name):
                source = _read(name)
                self._grid(source)
                self.assertEqual(source.source_dtype, "float32")
                _same(self, source.values, F32_1M)
                back = source.values[~np.isnan(source.values)]
                self.assertTrue(np.array_equal(back.astype(np.float32).astype(np.float64),
                                               back))

    def test_int16_is_rounded_surface(self) -> None:
        """RF-006-08: Int16 sin compresión y LZW + predictor 2: la cota redondeada."""
        for name in ("i16_strip.tif", "i16_strip_lzw_p2.tif"):
            with self.subTest(name=name):
                source = _read(name)
                self._grid(source)
                self.assertEqual(source.source_dtype, "int16")
                self.assertEqual(source.nodata_value, -9999.0)
                _same(self, source.values, I16_1M)

    def test_half_metre_grid(self) -> None:
        """RF-006-08: paso de 0,5 m (DEFLATE + predictor 3): rejilla y valores."""
        source = _read("f32_strip_deflate_p3_05m.tif")
        self._grid(source, NORTH_05M, 0.5)
        self.assertEqual(source.grid.cell_area, 0.25)
        _same(self, source.values, F32_05M)

    def test_sparse_tiles_are_nodata(self) -> None:
        """RF-006-08: las teselas (0, 3) y (2, 0), sin bytes en el fichero, son NaN."""
        expected = F32_1M.copy()
        expected[0:16, 48:64] = np.nan
        expected[32:48, 0:16] = np.nan
        source = _read("f32_tile_sparse.tif")
        self._grid(source)
        _same(self, source.values, expected)

    def test_declared_crs(self) -> None:
        """RF-006-04: el EPSG que declara cada fichero; sin claves de CRS, ``None``; sin
        clave vertical, ``declared_vertical = None`` (nunca se supone)."""
        for name in READABLE:
            with self.subTest(name=name):
                source = _read(name)
                expected = {"f32_epsg23030.tif": 23030, "f32_nocrs.tif": None}.get(name, 25830)
                if expected is None:
                    self.assertIsNone(source.declared_crs)
                else:
                    self.assertEqual(source.declared_crs, CATALOG.horizontal(expected))
                self.assertIsNone(source.declared_vertical)

    def test_pixel_is_point_moves_half_a_cell_with_note(self) -> None:
        """RF-006-08: *PixelIsPoint* (enlace en el centro 700 000,5; 4 400 047,5) da la
        misma rejilla que *PixelIsArea*, con su nota; los demás, sin nota."""
        point = _read("f32_pixelispoint.tif")
        self.assertTrue(point.pixel_is_point)
        self._grid(point)
        self.assertEqual(point.notes,
                         (messages.render("gis.pixel_is_point", file="f32_pixelispoint.tif"),))
        area = _read("f32_strip.tif")
        self.assertFalse(area.pixel_is_point)
        self.assertEqual(area.notes, ())

    def test_encoding_describes_the_file(self) -> None:
        """El informe dice cómo está guardado el fichero."""
        self.assertIn("BigTIFF", _read("f32_bigtiff.tif").encoding)
        self.assertIn("«MM»", _read("f32_mm.tif").encoding)
        lzw = _read("f32_tile_lzw_p3.tif").encoding
        for text in ("Float32", "LZW", "predictor 3", "teselas de 16 × 16"):
            self.assertIn(text, lzw)
        self.assertIn("tiras de 16 filas", _read("i16_strip_lzw_p2.tif").encoding)

    def test_rejected_with_file_feature_and_value(self) -> None:
        """RF-006-09: JPEG, giro, dos bandas y escala/offset, con código, fichero y
        valor en el error (y en su texto)."""
        rotation = "700000; 0,8; 0,6; 4400048; 0,6; -0,8"
        cases = {
            "u8_jpeg.tif": ("gis.tiff_compression_unsupported", 7, {"name": "JPEG"},
                            "compresión JPEG (código 7)"),
            "f32_rotated.tif": ("gis.raster_rotated", rotation, {}, f"({rotation})"),
            "f32_2bands.tif": ("gis.raster_bands_unsupported", 2, {}, "tiene 2 bandas"),
            "f32_scale_offset.tif": ("gis.raster_scale_offset", "0,1; 100",
                                     {"scale": 0.1, "offset": 100.0},
                                     "escala 0,1 y offset 100"),
        }
        for name, (code, value, values, shown) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(gis.GisError) as caught:
                    reader.read_geotiff(GEOTIFF / name)
                error = caught.exception
                self.assertEqual(error.code, code)
                self.assertEqual(error.obj, name)
                self.assertEqual(error.values["file"], name)
                self.assertEqual(error.value, value)
                for key, expected in values.items():
                    self.assertEqual(error.values[key], expected)
                self.assertIn(f"«{name}»", str(error))
                self.assertIn(shown, str(error))
        jpeg = messages.render("gis.tiff_compression_unsupported", file="u8_jpeg.tif",
                               name="JPEG", value=7)
        with self.assertRaises(gis.GisError) as caught:
            reader.read_geotiff(GEOTIFF / "u8_jpeg.tif")
        self.assertEqual(str(caught.exception), jpeg)

    def test_cell_limit(self) -> None:
        """RF-006-09: más celdas que el límite (64 × 48 = 3072 > 3071) se rechaza con el
        número de celdas y el límite; con 3072, se lee. Sin ``max_cells``, el límite es
        ``gis.import.max_cells`` de ``gis.params``, leído al leer."""
        with self.assertRaises(gis.GisError) as caught:
            reader.read_geotiff(GEOTIFF / "f32_strip.tif", max_cells=3071)
        error = caught.exception
        self.assertEqual((error.code, error.value), ("gis.raster_too_large", 3072))
        self.assertEqual((error.values["file"], error.values["limit"]), ("f32_strip.tif", 3071))
        self.assertIn("3072", str(error))
        self.assertEqual(reader.read_geotiff(GEOTIFF / "f32_strip.tif",
                                             max_cells=3072).grid.ncols, NCOLS)
        self.assertEqual(params.default("gis.import.max_cells"), 100_000_000)
        real = params.default

        def small(key: str) -> object:
            return 3000 if key == "gis.import.max_cells" else real(key)

        with mock.patch.object(params, "default", side_effect=small):
            with self.assertRaises(gis.GisError) as caught:
                reader.read_geotiff(GEOTIFF / "f32_strip.tif")
        self.assertEqual(caught.exception.values["limit"], 3000)

    def test_input_untouched(self) -> None:
        """RF-006-10: leer todos los ficheros (también los rechazados) no cambia el
        listado de la carpeta ni la fecha de modificación de ninguno."""

        def snapshot() -> dict[str, int]:
            return {entry.name: entry.stat().st_mtime_ns for entry in os.scandir(GEOTIFF)}

        before = snapshot()
        for name in (*READABLE, *REJECTED):
            try:
                reader.read_geotiff(GEOTIFF / name)
            except gis.GisError:
                pass
        self.assertEqual(snapshot(), before)

    def test_progress_and_cancel(self) -> None:
        """RF-006-28: avance tras cada tesela (12 de 16 × 16) hasta 1; si se cancela, para
        con ``JobCancelled`` y no devuelve nada."""
        seen: list[float] = []
        reader.read_geotiff(GEOTIFF / "f32_tile_lzw_p3.tif",
                            progress=lambda frac, text: seen.append(frac))
        self.assertEqual(len(seen), 12)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 1.0)
        calls = []

        def cancelled() -> bool:
            calls.append(1)
            return len(calls) > 3

        with self.assertRaises(worker_api.JobCancelled) as caught:
            reader.read_geotiff(GEOTIFF / "f32_tile_lzw_p3.tif", cancelled=cancelled)
        self.assertIn("4 de 12", str(caught.exception))

    def test_exports(self) -> None:
        """``RasterSource`` en ``gis`` y ``read_geotiff`` en ``gis.geotiff``."""
        self.assertIs(gis.RasterSource, raster.RasterSource)
        self.assertIn("RasterSource", gis.__all__)
        self.assertIs(geotiff.read_geotiff, reader.read_geotiff)


# --- Ficheros mínimos --------------------------------------------------------------------


class ReadBuiltFilesTest(_TempMixin, unittest.TestCase):
    """RF-006-04, RF-006-08 y RF-006-09 con TIFF de una tira escritos aquí."""

    def _error(self, path: Path, code: str) -> object:
        with self.assertRaises(gis.GisError) as caught:
            reader.read_geotiff(path)
        error = caught.exception
        self.assertEqual(error.code, code, str(error))
        self.assertEqual(error.values["file"], path.name)
        self.assertIn(f"«{path.name}»", str(error))
        return error

    def test_base_file_reads(self) -> None:
        """RF-006-08: el fichero base (Float32 «II») y su versión «MM»."""
        for order in ("<", ">"):
            with self.subTest(order=order):
                source = reader.read_geotiff(_build(self.tmp(f"base{order == '<'}.tif"), SMALL,
                                                    byteorder=order))
                _same(self, source.values, SMALL_READ)
                g = source.grid
                self.assertEqual((g.west, g.north, g.ncols, g.nrows),
                                 (700000.0, 4400003.0, 4, 3))
                self.assertEqual(source.declared_crs.epsg, 25830)

    def test_integer_and_float64_types(self) -> None:
        """RF-006-08: Byte, Int8, UInt16, Int32, UInt32 y Float64 («MM»): cada valor,
        exacto; el sin dato, NaN solo si cabe en el tipo."""
        cases = (
            (np.uint8, [[0, 255, 7]], "-9999", [[0.0, 255.0, 7.0]]),
            (np.int8, [[-128, 127, 0]], "0", [[-128.0, 127.0, np.nan]]),
            (np.uint16, [[65535, 1, 2]], "65535", [[np.nan, 1.0, 2.0]]),
            (np.int32, [[-9999, 2**31 - 1, -(2**31)]], "-9999",
             [[np.nan, 2147483647.0, -2147483648.0]]),
            (np.uint32, [[4294967295, 0, 5]], "-9999", [[4294967295.0, 0.0, 5.0]]),
            (np.float64, [[805.123456789012, -9999.0, 1e-300]], "-9999",
             [[805.123456789012, np.nan, 1e-300]]),
        )
        for dtype, image, nodata, expected in cases:
            with self.subTest(dtype=np.dtype(dtype).name):
                path = _build(self.tmp(f"{np.dtype(dtype).name}.tif"), np.array(image, dtype),
                              byteorder=">", tags={42113: (2, nodata)})
                source = reader.read_geotiff(path)
                self.assertEqual(source.source_dtype, np.dtype(dtype).name)
                _same(self, source.values, np.array(expected))

    def test_nodata_variants(self) -> None:
        """RF-006-08: sin ``GDAL_NODATA``, −9999 es una cota; con ``nan``, solo los NaN
        son sin dato; un sin dato que no es un número se rechaza (RF-006-09)."""
        none = reader.read_geotiff(_build(self.tmp("none.tif"), SMALL, drop=(42113,)))
        self.assertIsNone(none.nodata_value)
        _same(self, none.values, SMALL.astype(np.float64))
        with_nan = SMALL.copy()
        with_nan[2, 0] = np.nan
        nan = reader.read_geotiff(_build(self.tmp("nan.tif"), with_nan,
                                         tags={42113: (2, "nan")}))
        self.assertTrue(math.isnan(nan.nodata_value))
        expected = with_nan.astype(np.float64)
        _same(self, nan.values, expected)
        error = self._error(_build(self.tmp("bad.tif"), SMALL, tags={42113: (2, "nada")}),
                            "gis.tiff_feature_unsupported")
        self.assertEqual(error.value, "nada")

    def test_georeference_variants(self) -> None:
        """RF-006-08: punto de enlace en el píxel (2, 3) y ``ModelTransformation`` sin
        giro dan la esquina noroeste del píxel (0, 0) y el paso (dx ≠ dy)."""
        tie = _build(self.tmp("tie.tif"), SMALL, tags={
            33550: (12, [2.0, 0.5, 0.0]),
            33922: (12, [2.0, 3.0, 0.0, 700104.0, 4400001.5, 0.0]),
        })
        g = reader.read_geotiff(tie).grid
        self.assertEqual((g.west, g.north, g.dx, g.dy), (700100.0, 4400003.0, 2.0, 0.5))
        matrix = [2.0, 0.0, 0.0, 700010.0, 0.0, -0.5, 0.0, 4400020.0,
                  0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        transformed = _build(self.tmp("matrix.tif"), SMALL, tags={34264: (12, matrix)},
                             drop=(33550, 33922))
        g = reader.read_geotiff(transformed).grid
        self.assertEqual((g.west, g.north, g.dx, g.dy), (700010.0, 4400020.0, 2.0, 0.5))
        point = _build(self.tmp("point.tif"), SMALL, tags={
            34264: (12, matrix),
            34735: (3, list(_keys((1024, 1), (1025, 2), (3072, 25830)))),
        }, drop=(33550, 33922))
        source = reader.read_geotiff(point)
        self.assertTrue(source.pixel_is_point)
        self.assertEqual((source.grid.west, source.grid.north), (700009.0, 4400020.25))

    def test_georeference_rejected(self) -> None:
        """RF-006-09: sin georreferencia, varios puntos de enlace, paso negativo y
        ``ModelTransformation`` con cizalla."""
        self._error(_build(self.tmp("none.tif"), SMALL, drop=(33550, 33922)),
                    "gis.raster_not_georeferenced")
        many = _build(self.tmp("gcp.tif"), SMALL, tags={
            33922: (12, [0.0, 0.0, 0.0, 700000.0, 4400003.0, 0.0,
                         4.0, 3.0, 0.0, 700004.0, 4400000.0, 0.0])})
        self.assertEqual(self._error(many, "gis.tiff_feature_unsupported").value, 2)
        flipped = _build(self.tmp("flip.tif"), SMALL, tags={33550: (12, [1.0, -1.0, 0.0])})
        self._error(flipped, "gis.tiff_feature_unsupported")
        sheared = [1.0, 0.25, 0.0, 700000.0, 0.0, -1.0, 0.0, 4400003.0,
                   0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        error = self._error(_build(self.tmp("shear.tif"), SMALL, tags={34264: (12, sheared)},
                                   drop=(33550, 33922)), "gis.raster_rotated")
        self.assertEqual(error.value, "700000; 1; 0,25; 4400003; 0; -1")

    def test_crs_keys(self) -> None:
        """RF-006-04: CRS por parámetros (``ProjectedCSTypeGeoKey`` = 32767, o modelo
        proyectado sin código) → ``None`` con nota; sin GeoKeyDirectory → ``None`` sin nota;
        ``VerticalCSTypeGeoKey`` del catálogo → su ``VerticalRef``."""
        user = _keys((1024, 1), (3072, 32767))
        bare = _keys((1024, 1))
        for name, keys in (("user.tif", user), ("bare.tif", bare)):
            with self.subTest(name=name):
                source = reader.read_geotiff(_build(self.tmp(name), SMALL,
                                                    tags={34735: (3, list(keys))}))
                self.assertIsNone(source.declared_crs)
                self.assertEqual(source.notes,
                                 (messages.render("gis.crs_user_defined", file=name),))
        none = reader.read_geotiff(_build(self.tmp("nokeys.tif"), SMALL, drop=(34735,)))
        self.assertEqual((none.declared_crs, none.declared_vertical, none.notes),
                         (None, None, ()))
        vertical = _keys((1024, 1), (3072, 25830), (4096, 5782), (4099, 9001))
        source = reader.read_geotiff(_build(self.tmp("vertical.tif"), SMALL,
                                            tags={34735: (3, list(vertical))}))
        self.assertEqual(source.declared_vertical, CATALOG.vertical(5782))
        self.assertEqual(source.declared_crs, CATALOG.horizontal(25830))

    def test_crs_outside_catalog_rejected(self) -> None:
        """RF-006-09: un CRS horizontal o vertical fuera del catálogo y un CRS geográfico
        se rechazan con su código; unidades que no son metros, también."""
        cases = (
            ("mercator.tif", _keys((1024, 1), (3072, 3857)), "gis.raster_crs_unsupported",
             "EPSG:3857"),
            ("wgs84.tif", _keys((1024, 2), (2048, 4326)), "gis.raster_crs_unsupported",
             "EPSG:4326"),
            ("egm.tif", _keys((1024, 1), (3072, 25830), (4096, 3855)),
             "gis.raster_vertical_unsupported", "EPSG:3855"),
            ("feet.tif", _keys((1024, 1), (3072, 25830), (3076, 9002)),
             "gis.tiff_feature_unsupported", 9002),
            ("vfeet.tif", _keys((1024, 1), (3072, 25830), (4096, 5782), (4099, 9002)),
             "gis.tiff_feature_unsupported", 9002),
        )
        for name, keys, code, value in cases:
            with self.subTest(name=name):
                path = _build(self.tmp(name), SMALL, tags={34735: (3, list(keys))})
                self.assertEqual(self._error(path, code).value, value)

    def test_format_rejected(self) -> None:
        """RF-006-09: tipo de dato, predictor que no es del tipo y unidad de las cotas que
        no es el metro (``GDAL_METADATA``)."""
        half = _build(self.tmp("f16.tif"), SMALL.astype(np.float16))
        self.assertEqual(self._error(half, "gis.raster_dtype_unsupported").value, "Float16")
        wide = _build(self.tmp("i64.tif"), SMALL.astype(np.int64))
        self.assertEqual(self._error(wide, "gis.raster_dtype_unsupported").value, "Int64")
        for name, image, predictor in (("p2.tif", SMALL, 2),
                                       ("p3.tif", SMALL.astype(np.int16), 3),
                                       ("p4.tif", SMALL, 4)):
            with self.subTest(name=name):
                path = _build(self.tmp(name), image, tags={317: (3, [predictor])})
                self.assertEqual(self._error(path, "gis.tiff_feature_unsupported").value,
                                 predictor)
        feet = ('<GDALMetadata>\n  <Item name="UNITTYPE" sample="0" role="unittype">ft'
                "</Item>\n</GDALMetadata>\n")
        path = _build(self.tmp("ft.tif"), SMALL, tags={42112: (2, feet)})
        self.assertEqual(self._error(path, "gis.tiff_feature_unsupported").value, "ft")
        metres = feet.replace(">ft<", ">metre<").replace("</GDALMetadata>", (
            '  <Item name="SCALE" sample="0" role="scale">1</Item>\n'
            '  <Item name="OFFSET" sample="0" role="offset">0</Item>\n</GDALMetadata>'))
        source = reader.read_geotiff(_build(self.tmp("m.tif"), SMALL, tags={42112: (2, metres)}))
        _same(self, source.values, SMALL_READ)

    def test_damaged_files_rejected(self) -> None:
        """RF-006-09: lo que no es TIFF, un IFD fuera del fichero, una tira que falta, un
        bloque DEFLATE dañado, una tira cortada y un ráster sin ninguna cota."""
        text = self.tmp("text.tif")
        text.write_bytes(b"no soy un TIFF")
        self._error(text, "gis.tiff_invalid")
        empty = self.tmp("empty.tif")
        empty.write_bytes(b"")
        self._error(empty, "gis.tiff_invalid")
        outside = self.tmp("outside.tif")
        outside.write_bytes(b"II*\0" + struct.pack("<I", 10_000) + b"\0" * 8)
        self._error(outside, "gis.tiff_invalid")
        self._error(_build(self.tmp("nocounts.tif"), SMALL, drop=(279,)), "gis.tiff_invalid")
        broken = _build(self.tmp("deflate.tif"), SMALL, compression=8, data=b"\x78\x9c" + b"x" * 30)
        error = self._error(broken, "gis.tiff_block_corrupt")
        self.assertEqual((error.values["block"], error.values["blocks"]), (1, 1))
        short = _build(self.tmp("short.tif"), SMALL, tags={279: (4, [10_000])})
        self._error(short, "gis.tiff_block_corrupt")
        blank = np.full((2, 2), -9999.0, np.float32)
        self._error(_build(self.tmp("blank.tif"), blank), "gis.raster_empty")


class GeoKeysTest(unittest.TestCase):
    """Las claves GeoTIFF (``geokeys``), de las que salen el CRS y el tipo de píxel."""

    def test_parse(self) -> None:
        """Claves cortas, en ``GeoDoubleParams`` y en ``GeoAsciiParams`` (sin el «|»)."""
        directory = (1, 1, 0, 3, 1026, 34737, 22, 0, 2049, 34737, 7, 22, 3072, 0, 1, 25830)
        keys = geokeys.parse_geokeys(directory, ascii="ETRS89 / UTM zone 30N|ETRS89|")
        self.assertEqual(keys, {1026: "ETRS89 / UTM zone 30N", 2049: "ETRS89", 3072: 25830})
        doubles = geokeys.parse_geokeys((1, 1, 0, 1, 2057, 34736, 1, 1), doubles=(0.0, 6378137.0))
        self.assertEqual(doubles, {2057: (6378137.0,)})

    def test_malformed(self) -> None:
        """Un directorio corto, de otra versión o que apunta fuera es ``GeoKeyError``."""
        for directory in ((1, 1, 0), (2, 1, 0, 0), (1, 1, 0, 2, 1024, 0, 1, 1),
                          (1, 1, 0, 1, 1026, 34737, 50, 0), (1, 1, 0, 1, 1024, 9999, 1, 0)):
            with self.subTest(directory=directory):
                with self.assertRaises(geokeys.GeoKeyError):
                    geokeys.parse_geokeys(directory, ascii="abc|")

    def test_tiff_header(self) -> None:
        """El primer IFD de un TIFF y de un BigTIFF, con su orden de bytes."""
        with (GEOTIFF / "f32_bigtiff.tif").open("rb") as stream:
            ifd = tiff.read_first_ifd(stream, (GEOTIFF / "f32_bigtiff.tif").stat().st_size)
        self.assertTrue(ifd.bigtiff)
        self.assertEqual(ifd.byteorder, "<")
        self.assertEqual(ifd.tags[tiff.IMAGE_WIDTH], (64,))
        self.assertEqual(ifd.tags[tiff.GDAL_NODATA], "-9999")
        with (GEOTIFF / "f32_mm.tif").open("rb") as stream:
            ifd = tiff.read_first_ifd(stream, (GEOTIFF / "f32_mm.tif").stat().st_size)
        self.assertFalse(ifd.bigtiff)
        self.assertEqual(ifd.byteorder, ">")
        self.assertEqual(ifd.tags[tiff.MODEL_PIXEL_SCALE], (1.0, 1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
