# SPDX-License-Identifier: GPL-3.0-or-later
"""Escritor del GeoTIFF propio y ``GeoTiffIO`` (spec 006, T07; plan 006 §5.2.1, §5.3.1,
§5.3.2 y §5.4 A4; ADR-0020).

- **RF-006-08** (el MDT, en el proyecto como ráster que QGIS abre georreferenciado, con
  cada cota igual a la de la fuente): el perfil ``project`` (Float64, sin dato NaN, teselas
  de 256 × 256, DEFLATE de nivel 6 con predictor 3, «II») se lee con el lector de T06 **bit
  a bit** (también un NaN con carga, −0,0 y un subnormal), con la misma rejilla (pasos de
  B24, 1,000294… × 1,000302… m) y el CRS y la referencia vertical del ráster
  (``GTModelType`` 1, ``GTRasterType`` 1 = *PixelIsArea*, ``ProjectedCSType``,
  ``VerticalCSType`` solo si es un EPSG); las teselas van por filas y las del borde se
  rellenan con el sin dato.
- **RF-006-24** (entregable float32 con sin dato −9999, compresión sin pérdida y el CRS del
  proyecto): el perfil ``deliverable`` escribe cada cota como el ``numpy.float32`` de su
  valor y cada celda sin dato (NaN o ±∞) como −9999 (``GDAL_NODATA`` = ``-9999``); una cota
  válida que en float32 es −9999 (−9999 o −9999,0004) o que no cabe en float32 se rechaza
  (``gis.export_nodata_collision``, ``gis.export_value_out_of_range``) sin escribir nada.
- Determinismo: sin ``DateTime`` ni ``Software``, dos escrituras dan los mismos bytes.
- BigTIFF solo por encima del umbral (4 GiB − 64 KiB; inyectado en la prueba): con el
  tamaño exacto del TIFF clásico, clásico; con un byte menos, BigTIFF, que se lee igual.
- Escritura con ``<destino>.tmp``, ``fsync`` y ``os.replace``: mientras se escribe, el
  destino anterior sigue intacto; cancelar o un fallo al escribir lo dejan como estaba y no
  dejan temporal; un destino abierto por otro programa es ``gis.raster_target_locked``.
- Con ``GEOBLENDER_QGIS_DIR`` (recurso ``qgis`` de la 001/002), ``gdalinfo -json`` da la
  misma georreferencia, tipo, sin dato y EPSG, sin avisos, y ``gdal_translate`` lee los
  mismos bits; si no, omisión ``[ENTORNO] qgis``.
"""

import json
import math
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import qgis, resources
from tests.support.package import import_geoblender
from tests.support.resources import requires

geotiff = import_geoblender("gis.geotiff")
writer = import_geoblender("gis.geotiff.writer")
reader = import_geoblender("gis.geotiff.reader")
codecs = import_geoblender("gis.geotiff.codecs")
geokeys = import_geoblender("gis.geotiff.geokeys")
tiff = import_geoblender("gis.geotiff.tiff")
grid_mod = import_geoblender("gis.grid")
raster_mod = import_geoblender("gis.raster")
ports = import_geoblender("gis.ports")
messages = import_geoblender("gis.messages")
georef = import_geoblender("core.georef")
worker_api = import_geoblender("jobs.worker_api")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
LOCAL = CATALOG.local_vertical("NP-0 del plano 3")
PROJECT = ports.WriteProfile.PROJECT
DELIVERABLE = ports.WriteProfile.DELIVERABLE

# Pasos de la rejilla de B24 (Silvestre, T03): no son binarios exactos.
B24_DX = 1.0002942907592702
B24_DY = 1.0003022974607014
WEST, NORTH = 700123.0, 4400321.5
ROWS, COLS = 261, 300  # 2 × 2 teselas de 256, con bordes de 5 filas y 44 columnas
HOLE = (slice(100, 140), slice(200, 230))
PAYLOAD_NAN = np.frombuffer(struct.pack("<Q", 0x7FF8_0000_0000_0123), "<f8")[0]
SUBNORMAL = 5e-324

TAGS_PROJECT = (256, 257, 258, 259, 262, 277, 284, 317, 322, 323, 324, 325, 339, 33550,
                33922, 34735, 42113)


def _surface(rows: int = ROWS, cols: int = COLS, dx: float = B24_DX,
             dy: float = B24_DY) -> np.ndarray:
    """z = 800 + 0,5x − 0,25y + 3 sin(x/7) en los centros (x, y relativas a la esquina), con
    un hueco NaN y, en la primera fila, un NaN con carga, −0,0 y un subnormal."""
    x = (np.arange(cols) + 0.5) * dx
    y = (np.arange(rows) + 0.5) * dy
    z = 800.0 + 0.5 * x[None, :] - 0.25 * y[:, None] + 3.0 * np.sin(x / 7.0)[None, :]
    z[HOLE] = np.nan
    z[0, 0] = PAYLOAD_NAN
    z[0, 1] = -0.0
    z[0, 2] = SUBNORMAL
    return z


def _raster(values: np.ndarray, *, vertical: object = VERTICAL, dx: float = B24_DX,
            dy: float = B24_DY) -> object:
    rows, cols = values.shape
    grid = grid_mod.Grid(WEST, NORTH, dx, dy, cols, rows)
    return raster_mod.Raster(grid, values, CRS, vertical)


def _bits(values: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(values).view(np.uint64)


def _ifd(path: Path) -> object:
    with path.open("rb") as stream:
        return tiff.read_first_ifd(stream, path.stat().st_size)


def _tiles(path: Path, dtype: str) -> list[np.ndarray]:
    """Las teselas del fichero, decodificadas con los códecs de T05."""
    ifd = _ifd(path)
    data = path.read_bytes()
    width, height = ifd.number(tiff.TILE_WIDTH), ifd.number(tiff.TILE_LENGTH)
    return [
        codecs.decode_block(
            data[offset : offset + count],
            compression=ifd.number(tiff.COMPRESSION),
            predictor=ifd.number(tiff.PREDICTOR),
            dtype=dtype,
            width=width,
            rows=height,
        )
        for offset, count in zip(
            ifd.numbers(tiff.TILE_OFFSETS), ifd.numbers(tiff.TILE_BYTE_COUNTS), strict=True
        )
    ]


class _Folder:
    """Carpeta temporal por clase (``cls.folder``) y por prueba (``self.tmp()``)."""

    @classmethod
    def make_folder(cls) -> Path:
        folder = Path(tempfile.mkdtemp(prefix="gb-tifw-"))
        cls.addClassCleanup(shutil.rmtree, folder, True)  # type: ignore[attr-defined]
        return folder

    def tmp(self) -> Path:
        folder = Path(tempfile.mkdtemp(prefix="gb-tifw-"))
        self.addCleanup(shutil.rmtree, folder, True)  # type: ignore[attr-defined]
        return folder


class ProjectProfileTest(_Folder, unittest.TestCase):
    """Perfil ``project``: Float64, NaN, ida y vuelta bit a bit (RF-006-08)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = cls.make_folder()
        cls.values = _surface()
        cls.before = cls.values.copy()
        cls.raster = _raster(cls.values)
        cls.path = cls.folder / "gis_src_mdt.tif"
        writer.write_geotiff(cls.raster, cls.path, profile=PROJECT)
        cls.source = reader.read_geotiff(cls.path)

    def test_round_trip_is_bit_exact(self) -> None:
        """RF-006-08: el lector de T06 da la misma rejilla (bit a bit), los mismos bits en
        cada celda (NaN con su carga, −0,0, subnormal), Float64 con sin dato NaN, el CRS y
        la referencia vertical del ráster, *PixelIsArea* y ninguna nota; la entrada no
        cambia."""
        source = self.source
        self.assertTrue(source.grid.same_geometry(self.raster.grid))
        self.assertTrue(np.array_equal(_bits(source.values), _bits(self.values)))
        self.assertTrue(np.array_equal(_bits(self.values), _bits(self.before)))
        self.assertEqual(source.source_dtype, "float64")
        self.assertTrue(math.isnan(source.nodata_value))
        self.assertEqual(source.declared_crs.epsg, 25830)
        self.assertEqual(source.declared_vertical.epsg, 5782)
        self.assertFalse(source.pixel_is_point)
        self.assertEqual(source.notes, ())
        self.assertEqual(
            source.encoding,
            "GeoTIFF «II», Float64, compresión DEFLATE, predictor 3, teselas de 256 × 256",
        )

    def test_tags_of_the_profile(self) -> None:
        """RF-006-08, plan §5.2.1: «II», TIFF clásico, las etiquetas del perfil y ninguna
        más (sin ``DateTime`` ni ``Software``), georreferencia exacta y claves 1024 = 1,
        1025 = 1, 3072 = 25830 y 4096 = 5782."""
        ifd = _ifd(self.path)
        self.assertEqual(self.path.read_bytes()[:4], b"II*\0")
        self.assertEqual((ifd.byteorder, ifd.bigtiff), ("<", False))
        self.assertEqual(tuple(sorted(ifd.tags)), TAGS_PROJECT)
        expected = {
            256: (COLS,), 257: (ROWS,), 258: (64,), 259: (8,), 262: (1,), 277: (1,),
            284: (1,), 317: (3,), 322: (256,), 323: (256,), 339: (3,),
            33550: (B24_DX, B24_DY, 0.0), 33922: (0.0, 0.0, 0.0, WEST, NORTH, 0.0),
        }
        for tag, value in expected.items():
            with self.subTest(etiqueta=tag):
                self.assertEqual(ifd.tags[tag], value)
        self.assertEqual(ifd.text(tiff.GDAL_NODATA), "nan")
        keys = geokeys.parse_geokeys(ifd.numbers(tiff.GEO_KEY_DIRECTORY))
        self.assertEqual(keys, {1024: 1, 1025: 1, 3072: 25830, 4096: 5782})
        self.assertEqual(ifd.numbers(tiff.GEO_KEY_DIRECTORY)[:4], (1, 1, 0, 4))

    def test_tiles_by_rows_with_padded_edges(self) -> None:
        """Plan §5.4 A4: 2 × 2 teselas de 256 × 256 por filas (TIFF 6.0), cada una con su
        trozo de la rejilla, y el relleno de las del borde, NaN."""
        tiles = _tiles(self.path, "<f8")
        self.assertEqual(len(tiles), 4)
        for index, tile in enumerate(tiles):
            row, col = divmod(index, 2)
            top, left = row * 256, col * 256
            part = self.values[top : top + 256, left : left + 256]
            with self.subTest(tesela=index):
                rows, cols = part.shape
                self.assertTrue(np.array_equal(_bits(tile[:rows, :cols]), _bits(part)))
                padding = np.ones(tile.shape, bool)
                padding[:rows, :cols] = False
                self.assertTrue(np.isnan(tile[padding]).all())
                self.assertEqual(int(padding.sum()), 256 * 256 - rows * cols)

    def test_local_vertical_has_no_vertical_key(self) -> None:
        """RF-006-08: con una referencia vertical local (sin EPSG) no se escribe
        ``VerticalCSTypeGeoKey`` y el lector no declara ninguna; el CRS, sí."""
        path = self.tmp() / "local.tif"
        writer.write_geotiff(_raster(self.values, vertical=LOCAL), path, profile=PROJECT)
        ifd = _ifd(path)
        keys = geokeys.parse_geokeys(ifd.numbers(tiff.GEO_KEY_DIRECTORY))
        self.assertEqual(keys, {1024: 1, 1025: 1, 3072: 25830})
        source = reader.read_geotiff(path)
        self.assertIsNone(source.declared_vertical)
        self.assertEqual(source.declared_crs.epsg, 25830)


class DeliverableProfileTest(_Folder, unittest.TestCase):
    """Perfil ``deliverable``: Float32 con −9999 (RF-006-24)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = cls.make_folder()
        values = _surface()
        values[5, 7] = math.inf
        values[6, 7] = -math.inf
        values[7, 7] = -9999.001  # en float32, −9999,0009765625: no es el sin dato
        cls.values = values
        cls.raster = _raster(values)
        cls.path = cls.folder / "entregable.tif"
        writer.write_geotiff(cls.raster, cls.path, profile=DELIVERABLE)
        cls.source = reader.read_geotiff(cls.path)

    def test_each_elevation_is_its_float32(self) -> None:
        """RF-006-24: cada cota leída es el ``numpy.float32`` de la del proyecto (pasado a
        float64 sin cambio) y cada celda sin dato (NaN, ±∞), sin dato; Float32 con
        ``GDAL_NODATA`` = ``-9999``, la misma rejilla, CRS y referencia vertical."""
        source = self.source
        finite = np.isfinite(self.values)
        expected = np.where(finite, self.values.astype(np.float32), np.nan).astype(np.float64)
        same = (source.values == expected) | (np.isnan(source.values) & np.isnan(expected))
        self.assertTrue(same.all())
        self.assertEqual(source.values[7, 7], float(np.float32(-9999.001)))
        self.assertEqual(int(np.isnan(source.values).sum()), int((~finite).sum()))
        self.assertEqual(source.source_dtype, "float32")
        self.assertEqual(source.nodata_value, -9999.0)
        self.assertTrue(source.grid.same_geometry(self.raster.grid))
        self.assertEqual(source.declared_crs.epsg, 25830)
        self.assertEqual(source.declared_vertical.epsg, 5782)
        ifd = _ifd(self.path)
        self.assertEqual(tuple(sorted(ifd.tags)), TAGS_PROJECT)
        self.assertEqual((ifd.number(258), ifd.number(339), ifd.number(317)), (32, 3, 3))
        self.assertEqual(ifd.text(tiff.GDAL_NODATA), "-9999")

    def test_nodata_cells_and_padding_are_minus_9999(self) -> None:
        """RF-006-24: en el fichero, las celdas sin dato y el relleno de las teselas del
        borde son exactamente −9999 en float32."""
        tiles = _tiles(self.path, "<f4")
        mosaic = np.vstack([np.hstack(tiles[0:2]), np.hstack(tiles[2:4])])
        self.assertEqual(mosaic.dtype, np.float32)
        missing = np.ones(mosaic.shape, bool)
        missing[:ROWS, :COLS] = ~np.isfinite(self.values)
        self.assertTrue((mosaic[missing] == np.float32(-9999.0)).all())
        self.assertFalse((mosaic[~missing] == np.float32(-9999.0)).any())

    def test_elevation_equal_to_nodata_is_rejected(self) -> None:
        """RF-006-24: una cota válida que en float32 es −9999 (−9999 y −9999,0004) se
        rechaza con el fichero, la celda (fila y columna desde 1) y cuántas hay, sin
        escribir nada; −9999,001 sí se escribe."""
        for bad in (-9999.0, -9999.0004):
            with self.subTest(cota=bad):
                folder = self.tmp()
                values = _surface()
                values[3, 4] = bad
                values[200, 250] = -9999.0
                with self.assertRaises(messages.GisError) as caught:
                    writer.write_geotiff(_raster(values), folder / "x.tif", profile=DELIVERABLE)
                error = caught.exception
                self.assertEqual(error.code, "gis.export_nodata_collision")
                self.assertEqual((error.obj, error.field, error.value), ("x.tif", "cota", bad))
                self.assertEqual(
                    (error.values["row"], error.values["column"], error.values["count"]),
                    (4, 5, 2),
                )
                self.assertIn("−9999", str(error))
                self.assertEqual(list(folder.iterdir()), [])

    def test_elevation_out_of_float32_is_rejected(self) -> None:
        """RF-006-24: una cota finita que no cabe en float32 (1e39) se rechaza sin
        escribir nada (no se escribe como ∞)."""
        folder = self.tmp()
        values = _surface()
        values[10, 20] = 1e39
        with self.assertRaises(messages.GisError) as caught:
            writer.write_geotiff(_raster(values), folder / "x.tif", profile=DELIVERABLE)
        error = caught.exception
        self.assertEqual(error.code, "gis.export_value_out_of_range")
        self.assertEqual((error.values["row"], error.values["column"]), (11, 21))
        self.assertEqual(error.value, 1e39)
        self.assertEqual(list(folder.iterdir()), [])


class DeterminismAndBigTiffTest(_Folder, unittest.TestCase):
    """Mismos bytes en cada escritura; BigTIFF solo por encima del umbral."""

    def test_two_writes_give_the_same_bytes(self) -> None:
        """Plan §5.2.1: sin fecha ni programa, dos escrituras (con nombres distintos) dan
        los mismos bytes, en los dos perfiles."""
        folder = self.tmp()
        values = _surface(40, 50)
        for profile in (PROJECT, DELIVERABLE):
            with self.subTest(perfil=profile):
                first, second = folder / f"a_{profile}.tif", folder / f"b_{profile}.tif"
                writer.write_geotiff(_raster(values), first, profile=profile)
                writer.write_geotiff(_raster(values.copy()), second, profile=profile)
                self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_bigtiff_only_above_the_threshold(self) -> None:
        """Plan §5.4 A4: el umbral es 4 GiB − 64 KiB; con el tamaño exacto del TIFF
        clásico como umbral se escribe clásico y con un byte menos, BigTIFF (cabecera 43,
        desplazamientos LONG8), que el lector lee con los mismos bits."""
        self.assertEqual(writer.BIGTIFF_THRESHOLD, 4 * 2**30 - 64 * 2**10)
        self.assertEqual(geotiff.GeoTiffIO().bigtiff_threshold, writer.BIGTIFF_THRESHOLD)
        folder = self.tmp()
        values = _surface(30, 40)
        classic = folder / "clasico.tif"
        writer.write_geotiff(_raster(values), classic, profile=PROJECT)
        size = classic.stat().st_size
        cases = ((size, folder / "igual.tif", b"II*\0"), (size - 1, folder / "big.tif", b"II+\0"))
        for threshold, path, magic in cases:
            with self.subTest(umbral=threshold):
                io = geotiff.GeoTiffIO(bigtiff_threshold=threshold)
                io.write(_raster(values), path, profile=PROJECT)
                self.assertEqual(path.read_bytes()[:4], magic)
                source = io.read(path)
                self.assertTrue(np.array_equal(_bits(source.values), _bits(values)))
                self.assertTrue(source.grid.same_geometry(_raster(values).grid))
        self.assertEqual(classic.read_bytes(), (folder / "igual.tif").read_bytes())
        ifd = _ifd(folder / "big.tif")
        self.assertTrue(ifd.bigtiff)
        self.assertIn("BigTIFF", reader.read_geotiff(folder / "big.tif").encoding)
        for wrong in (-1, writer.BIGTIFF_THRESHOLD + 1, 1.5, True):
            with self.subTest(umbral=wrong), self.assertRaises((ValueError, TypeError)):
                geotiff.GeoTiffIO(bigtiff_threshold=wrong)


class AtomicWriteTest(_Folder, unittest.TestCase):
    """Temporal, ``fsync`` y renombrado: nunca un fichero a medias (plan §5.4 A4)."""

    def setUp(self) -> None:
        self.folder = self.tmp()
        self.target = self.folder / "gis_dtm_x.tif"
        self.target.write_bytes(b"anterior")
        self.raster = _raster(_surface(300, 280))  # 2 × 2 teselas

    def test_temporary_fsync_and_replace(self) -> None:
        """Se escribe ``<destino>.tmp``, se fuerza a disco y se sustituye el destino con
        ``os.replace``; justo antes, el temporal es un GeoTIFF completo y el destino sigue
        siendo el anterior; al final no queda el temporal. El avance llega a 1."""
        calls: list[str] = []
        real_replace, real_fsync = os.replace, os.fsync

        def replace(source: object, target: object) -> None:
            calls.append("replace")
            self.assertEqual(Path(source), self.folder / "gis_dtm_x.tif.tmp")
            self.assertEqual(Path(target), self.target)
            self.assertEqual(self.target.read_bytes(), b"anterior")
            complete = reader.read_geotiff(Path(source))
            self.assertTrue(complete.grid.same_geometry(self.raster.grid))
            real_replace(source, target)

        def fsync(descriptor: int) -> None:
            calls.append("fsync")
            real_fsync(descriptor)

        steps: list[float] = []
        with mock.patch.object(writer.os, "replace", replace), \
                mock.patch.object(writer.os, "fsync", fsync):
            writer.write_geotiff(
                self.raster, self.target, profile=PROJECT,
                progress=lambda fraction, text: steps.append(fraction),
            )
        self.assertEqual(calls, ["fsync", "replace"])
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["gis_dtm_x.tif"])
        self.assertTrue(reader.read_geotiff(self.target).grid.same_geometry(self.raster.grid))
        self.assertEqual(steps, [0.25, 0.5, 0.75, 1.0])

    def test_cancel_leaves_the_previous_file(self) -> None:
        """RF-006-28: cancelar a mitad (tras la primera tesela) es ``JobCancelled``; el
        destino sigue siendo el anterior y no queda el temporal."""
        asked: list[int] = []

        def cancelled() -> bool:
            asked.append(1)
            return len(asked) > 1

        with self.assertRaises(worker_api.JobCancelled):
            writer.write_geotiff(self.raster, self.target, profile=PROJECT, cancelled=cancelled)
        self.assertEqual(self.target.read_bytes(), b"anterior")
        self.assertEqual([p.name for p in self.folder.iterdir()], ["gis_dtm_x.tif"])

    def test_write_error_leaves_the_previous_file(self) -> None:
        """Un fallo del disco al escribir (sin espacio) es ``gis.raster_write_failed`` con
        el fichero y el detalle; el destino sigue siendo el anterior y no queda el
        temporal."""
        error = OSError(28, "No queda espacio en el disco")
        with mock.patch.object(writer.os, "fsync", side_effect=error), \
                self.assertRaises(messages.GisError) as caught:
            writer.write_geotiff(self.raster, self.target, profile=DELIVERABLE)
        self.assertEqual(caught.exception.code, "gis.raster_write_failed")
        self.assertEqual(caught.exception.obj, "gis_dtm_x.tif")
        self.assertIn("No queda espacio", str(caught.exception))
        self.assertEqual(self.target.read_bytes(), b"anterior")
        self.assertEqual([p.name for p in self.folder.iterdir()], ["gis_dtm_x.tif"])

    def test_named_temporary_without_replacing(self) -> None:
        """RF-006-28 (plan §5.6.5, T42): el temporal lo puede dar quien llama
        (``gis.store``: ``<fichero>.tmp-<sesión>``); con ``replace=False`` el fichero queda
        entero en él y el destino no cambia; con ``replace`` (por defecto) pasa a su sitio y
        no queda el temporal. El propio destino como temporal es un error del programa."""
        temporary = self.folder / "gis_dtm_x.tif.tmp-0a1b2c3d"
        written = writer.write_geotiff(self.raster, self.target, profile=PROJECT,
                                       temporary=temporary, replace=False)
        self.assertEqual(written, temporary)
        self.assertEqual(self.target.read_bytes(), b"anterior")
        self.assertTrue(reader.read_geotiff(temporary).grid.same_geometry(self.raster.grid))
        temporary.unlink()
        written = writer.write_geotiff(self.raster, self.target, profile=PROJECT,
                                       temporary=temporary)
        self.assertEqual(written, self.target)
        self.assertEqual([p.name for p in self.folder.iterdir()], ["gis_dtm_x.tif"])
        self.assertTrue(reader.read_geotiff(self.target).grid.same_geometry(self.raster.grid))
        with self.assertRaises(ValueError):
            writer.write_geotiff(self.raster, self.target, profile=PROJECT,
                                 temporary=self.target)

    def test_locked_target_is_an_error_without_leftovers(self) -> None:
        """Plan §5.4 A4 (R9) y §5.6.5 (D20): si otro programa tiene abierto el destino (QGIS)
        y Windows no deja sustituirlo, ``gis.raster_target_locked``; el destino no cambia y
        no queda el temporal (tampoco en ``rasters/``: sin ``<nombre>__<hash8>.tif``)."""
        if os.name != "nt":
            self.skipTest(resources.skip_reason(resources.WINDOWS, resources.WINDOWS_HINT))
        with self.target.open("rb"), self.assertRaises(messages.GisError) as caught:
            writer.write_geotiff(self.raster, self.target, profile=PROJECT)
        error = caught.exception
        self.assertEqual(error.code, "gis.raster_target_locked")
        self.assertEqual((error.obj, error.field), ("gis_dtm_x.tif", "destino"))
        self.assertEqual(self.target.read_bytes(), b"anterior")
        self.assertEqual([p.name for p in self.folder.iterdir()], ["gis_dtm_x.tif"])


class GeoTiffIOTest(_Folder, unittest.TestCase):
    """``GeoTiffIO`` implementa el puerto ``RasterIO`` (plan §5.3.1)."""

    def test_implements_the_port(self) -> None:
        """``GeoTiffIO`` cumple ``gis.ports.RasterIO``: ``read`` es el lector de T06 y
        ``write`` acepta el perfil como ``WriteProfile`` o como su texto; otro perfil u
        otro objeto que no es un ``Raster`` son errores del programa."""
        io = geotiff.GeoTiffIO()
        self.assertIsInstance(io, ports.RasterIO)
        folder = self.tmp()
        values = _surface(20, 30)
        path = folder / "x.tif"
        io.write(_raster(values), path, profile="deliverable")
        steps: list[float] = []
        source = io.read(path, progress=lambda f, t: steps.append(f))
        self.assertEqual(source.source_dtype, "float32")
        self.assertEqual(steps, [1.0])
        with self.assertRaises(ValueError):
            io.write(_raster(values), folder / "y.tif", profile="otro")
        with self.assertRaises(TypeError):
            io.write(values, folder / "y.tif", profile=PROJECT)
        self.assertEqual([p.name for p in folder.iterdir()], ["x.tif"])


class EncodingHelpersTest(unittest.TestCase):
    """Las piezas del escritor en ``tiff`` y ``geokeys`` (plan §5.4 A4)."""

    def test_ifd_round_trip_and_program_errors(self) -> None:
        """``encode_ifd`` + ``encode_header`` dan un IFD que ``read_first_ifd`` lee igual,
        en TIFF y en BigTIFF (con los valores largos detrás, en bytes pares); un tipo que
        no escribe, ``LONG8`` en un TIFF clásico, una etiqueta repetida, un valor que no
        cabe o un desplazamiento impar son errores del programa."""
        entries = [
            (tiff.IMAGE_LENGTH, tiff.LONG, [7]),
            (tiff.IMAGE_WIDTH, tiff.SHORT, [5]),
            (tiff.GDAL_NODATA, tiff.ASCII, "-9999"),
            (tiff.MODEL_PIXEL_SCALE, tiff.DOUBLE, [0.5, 0.25, 0.0]),
        ]
        for bigtiff, offsets in ((False, tiff.LONG), (True, tiff.LONG8)):
            with self.subTest(bigtiff=bigtiff):
                ifd = tiff.encode_ifd([*entries, (tiff.TILE_OFFSETS, offsets, [16, 2**31])],
                                      16, bigtiff=bigtiff)
                data = tiff.encode_header(16, bigtiff=bigtiff).ljust(16, b"\0") + ifd
                with tempfile.TemporaryFile() as stream:
                    stream.write(data)
                    parsed = tiff.read_first_ifd(stream, len(data))
                self.assertEqual(parsed.bigtiff, bigtiff)
                self.assertEqual(dict(parsed.tags), {
                    256: (5,), 257: (7,), 324: (16, 2**31), 33550: (0.5, 0.25, 0.0),
                    42113: "-9999",
                })
        wrong = (
            ([(256, 11, [1.0])], 16, False),          # FLOAT: no se escribe
            ([(324, tiff.LONG8, [1])], 16, False),    # LONG8 en un TIFF clásico
            ([(256, 3, [1]), (256, 3, [2])], 16, False),
            ([(256, tiff.SHORT, [70000])], 16, False),
            ([(256, tiff.SHORT, [-1])], 16, False),
            ([(256, tiff.LONG, [1.5])], 16, False),
            ([(256, tiff.SHORT, [1])], 15, False),
        )
        for entries_, offset, bigtiff in wrong:
            with self.subTest(entradas=entries_, desplazamiento=offset), \
                    self.assertRaises(ValueError):
                tiff.encode_ifd(entries_, offset, bigtiff=bigtiff)

    def test_geokeys_and_nodata(self) -> None:
        """``encode_geokeys`` ordena las claves y ``parse_geokeys`` las lee igual; una que
        no cabe en un SHORT es un error del programa. ``format_nodata``, como GDAL."""
        directory = geokeys.encode_geokeys({3072: 25830, 1024: 1, 4096: 5782, 1025: 1})
        self.assertEqual(directory, (1, 1, 0, 4, 1024, 0, 1, 1, 1025, 0, 1, 1,
                                     3072, 0, 1, 25830, 4096, 0, 1, 5782))
        self.assertEqual(geokeys.parse_geokeys(directory),
                         {1024: 1, 1025: 1, 3072: 25830, 4096: 5782})
        for keys in ({3072: 70000}, {3072: -1}, {3072: True}):
            with self.subTest(claves=keys), self.assertRaises(ValueError):
                geokeys.encode_geokeys(keys)
        cases = ((math.nan, "nan"), (-9999.0, "-9999"), (-3.4e38, "-3.4e+38"), (0.25, "0.25"))
        for value, text in cases:
            with self.subTest(valor=value):
                self.assertEqual(geokeys.format_nodata(value), text)
                parsed = geokeys.parse_nodata(text)
                self.assertTrue(parsed == value or (math.isnan(parsed) and math.isnan(value)))


@requires(qgis.QGIS, qgis.QGIS_HINT)
class GdalReadsWhatIsWrittenTest(unittest.TestCase):
    """RF-006-08, RF-006-24: lo que dice el GDAL de QGIS de los dos perfiles."""

    @classmethod
    def setUpClass(cls) -> None:
        folder = Path(tempfile.mkdtemp(prefix="gb-tifw-"))
        cls.addClassCleanup(shutil.rmtree, folder, True)
        cls.folder = folder
        cls.values = _surface()
        cls.cases = {}
        for profile, vertical in ((PROJECT, VERTICAL), (DELIVERABLE, LOCAL)):
            path = folder / f"{profile}.tif"
            writer.write_geotiff(_raster(cls.values, vertical=vertical), path, profile=profile)
            info = qgis.run_tool("gdalinfo", "-json", str(path))
            raw = folder / f"{profile}.bin"
            translate = qgis.run_tool("gdal_translate", "-q", "-of", "ENVI", str(path), str(raw))
            cls.cases[profile] = (path, info, translate, raw)
        # GDAL solo lee VerticalCSTypeGeoKey con esta opción (por defecto, el horizontal).
        cls.compound = qgis.run_tool(
            "gdalinfo", "-json", "--config", "GTIFF_REPORT_COMPD_CS", "YES",
            str(cls.cases[PROJECT][0]),
        )

    def test_gdalinfo_same_georeference_type_nodata_and_epsg(self) -> None:
        """``gdalinfo -json`` sin avisos: tamaño, ``geoTransform`` (oeste, dx, 0, norte, 0,
        −dy) bit a bit, *Area*, una banda Float64 con NaN o Float32 con −9999, y
        EPSG:25830."""
        expected_type = {PROJECT: ("Float64", "NaN"), DELIVERABLE: ("Float32", -9999.0)}
        for profile, (_path, info, _translate, _raw) in self.cases.items():
            with self.subTest(perfil=profile):
                found = self._json(info)
                self.assertEqual(found["size"], [COLS, ROWS])
                self.assertEqual(found["geoTransform"], [WEST, B24_DX, 0.0, NORTH, 0.0, -B24_DY])
                self.assertEqual(found["metadata"][""]["AREA_OR_POINT"], "Area")
                self.assertEqual(len(found["bands"]), 1)
                band = found["bands"][0]
                self.assertEqual((band["type"], band["noDataValue"]), expected_type[profile])
                self.assertEqual(found["stac"]["proj:epsg"], 25830)
                wkt = found["coordinateSystem"]["wkt"]
                self.assertTrue(wkt.startswith("PROJCRS["), wkt[:80])
                self.assertTrue(wkt.rstrip().endswith('ID["EPSG",25830]]'), wkt[-80:])

    def test_gdal_reads_the_vertical_crs(self) -> None:
        """Con ``GTIFF_REPORT_COMPD_CS=YES``, GDAL lee la referencia vertical del perfil
        del proyecto: el CRS compuesto EPSG:25830 + EPSG:5782 (altitud de Alicante)."""
        wkt = self._json(self.compound)["coordinateSystem"]["wkt"]
        self.assertTrue(wkt.startswith('COMPOUNDCRS["ETRS89 / UTM zone 30N + Alicante'), wkt[:80])
        self.assertIn('ID["EPSG",25830]', wkt)
        self.assertTrue(wkt.rstrip().endswith('ID["EPSG",5782]]]'), wkt[-80:])

    def _json(self, info: object) -> dict:
        output = qgis.output_of(info)
        self.assertEqual(info.returncode, 0, output)
        self.assertEqual(info.stderr.strip(), "", output)
        return json.loads(info.stdout)

    def test_gdal_reads_the_same_bits(self) -> None:
        """GDAL decodifica las teselas (DEFLATE + predictor 3) con los mismos bits:
        Float64, los del proyecto (NaN con carga incluido); Float32, el ``float32`` de cada
        cota y −9999 en las celdas sin dato."""
        finite = np.isfinite(self.values)
        deliverable = np.where(finite, self.values, -9999.0).astype("<f4")
        expected = {PROJECT: (self.values.astype("<f8"), "<f8"), DELIVERABLE: (deliverable, "<f4")}
        for profile, (_path, _info, translate, raw) in self.cases.items():
            with self.subTest(perfil=profile):
                self.assertEqual(translate.returncode, 0, qgis.output_of(translate))
                values, dtype = expected[profile]
                got = np.fromfile(raw, dtype).reshape(ROWS, COLS)
                self.assertTrue(np.array_equal(got.view(f"u{got.itemsize}"),
                                               values.view(f"u{values.itemsize}")))


if __name__ == "__main__":
    unittest.main()
