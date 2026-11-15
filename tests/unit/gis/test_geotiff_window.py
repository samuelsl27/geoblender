# SPDX-License-Identifier: GPL-3.0-or-later
"""Leer una ventana de un GeoTIFF sin decodificar los demás bloques (spec 015, T37; RNF-015-03, RNF-015-08;
plan 015 §5.4 A0).

``reader.read_window`` da las celdas de unas filas y unas columnas leyendo **solo** las teselas o tiras que las
tocan: las mismas celdas que ``read_geotiff(...).values[filas, columnas]``, bit a bit, con el sin dato y los bloques
que faltan en NaN, para todos los ficheros admitidos de ``tests/data/gis/geotiff/`` (tiras y teselas, TIFF y BigTIFF,
«II» y «MM», cada compresión y predictor, Float64, Float32 e Int16).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

reader = import_geoblender("gis.geotiff.reader")
georef = import_geoblender("core.georef")

GEOTIFF = ROOT / "tests" / "data" / "gis" / "geotiff"
CATALOG = georef.load_catalog()
READABLE = (
    "f32_strip.tif", "f32_strip_packbits.tif", "f32_tile.tif", "f32_tile_lzw_p3.tif", "f32_bigtiff.tif",
    "f32_mm.tif", "f32_epsg23030.tif", "f32_nocrs.tif", "f32_pixelispoint.tif", "f32_tile_sparse.tif",
    "f32_strip_deflate_p3_05m.tif", "f64_strip.tif", "f64_strip_deflate_p3.tif", "i16_strip.tif",
    "i16_strip_lzw_p2.tif")
WINDOWS = (
    ((0, 48), (0, 64)),  # la imagen entera
    ((0, 1), (0, 1)),  # la esquina del noroeste
    ((47, 48), (63, 64)),  # la del sureste
    ((20, 23), (30, 34)),  # el hueco sin dato
    ((10, 30), (5, 40)),  # el centro, a caballo de varias teselas
    ((0, 48), (17, 18)),  # una columna
    ((33, 34), (0, 64)),  # una fila
    ((15, 17), (15, 17)),  # a caballo de la esquina de cuatro teselas de 16
    ((16, 32), (16, 32)),  # justo una tesela de 16
)


def window_of(name: str, rows: tuple[int, int], cols: tuple[int, int]) -> np.ndarray:
    path = GEOTIFF / name
    with path.open("rb") as stream:
        header = reader.read_header(stream, path.stat().st_size, path.name, catalog=CATALOG)
        return reader.read_window(stream, header, rows, cols)


class ReadWindowTest(unittest.TestCase):
    def test_a_a_window_is_the_same_cells_as_reading_everything(self) -> None:
        """RNF-015-03 (A0): para cada fichero admitido y cada ventana, ``read_window`` da, bit a bit, lo que
        ``read_geotiff`` da en esas filas y columnas (el sin dato y las teselas que faltan, NaN)."""
        for name in READABLE:
            whole = reader.read_geotiff(GEOTIFF / name).values
            for rows, cols in WINDOWS:
                with self.subTest(file=name, rows=rows, cols=cols):
                    found = window_of(name, rows, cols)
                    self.assertEqual(found.shape, (rows[1] - rows[0], cols[1] - cols[0]))
                    self.assertEqual(found.dtype, np.float64)
                    np.testing.assert_array_equal(found, whole[rows[0]:rows[1], cols[0]:cols[1]])

    def test_a_only_the_blocks_that_touch_the_window_are_decoded(self) -> None:
        """RNF-015-03: en un fichero de teselas de 16 × 16, una ventana dentro de una sola tesela decodifica una;
        a caballo de la esquina de cuatro, cuatro; una fila entera de 64 columnas, las cuatro de su fila; en uno
        de tiras, solo las tiras de sus filas."""
        path = GEOTIFF / "f32_tile.tif"
        with path.open("rb") as stream:
            header = reader.read_header(stream, path.stat().st_size, path.name, catalog=CATALOG)
            self.assertTrue(header.layout.tiled)
            side = header.layout.block_w
            total = len(header.layout.offsets)
            for rows, cols, expected in (
                    ((1, 5), (1, 5), 1), ((side - 1, side + 1), (side - 1, side + 1), 4),
                    ((0, 1), (0, header.width), -(-header.width // side)),
                    ((0, header.height), (0, header.width), total)):
                with self.subTest(rows=rows, cols=cols), mock.patch.object(
                        reader, "decode_block", wraps=reader.decode_block) as decoded:
                    reader.read_window(stream, header, rows, cols)
                self.assertEqual(decoded.call_count, expected)
        path = GEOTIFF / "f32_strip.tif"
        with path.open("rb") as stream:
            header = reader.read_header(stream, path.stat().st_size, path.name, catalog=CATALOG)
            self.assertFalse(header.layout.tiled)
            total = len(header.layout.offsets)
            with mock.patch.object(reader, "decode_block", wraps=reader.decode_block) as decoded:
                reader.read_window(stream, header, (0, 1), (10, 20))
            self.assertEqual(decoded.call_count, 1)
            self.assertLess(decoded.call_count, total)

    def test_a_a_window_that_is_not_in_the_image_is_a_program_error(self) -> None:
        """Una ventana vacía, al revés o fuera de la imagen es un error del programa (``ValueError``); con algo que
        no son enteros, ``TypeError``."""
        path = GEOTIFF / "f32_tile.tif"
        with path.open("rb") as stream:
            header = reader.read_header(stream, path.stat().st_size, path.name, catalog=CATALOG)
            for rows, cols in (((3, 3), (0, 4)), ((0, 4), (5, 5)), ((4, 2), (0, 4)), ((-1, 4), (0, 4)),
                               ((0, 49), (0, 4)), ((0, 4), (0, 65))):
                with self.subTest(rows=rows, cols=cols), self.assertRaises(ValueError):
                    reader.read_window(stream, header, rows, cols)
            with self.assertRaises(TypeError):
                reader.read_window(stream, header, (0.0, 4), (0, 4))  # type: ignore[arg-type]

    def test_a_the_file_is_only_read(self) -> None:
        """RF-006-10: leer una ventana no cambia el fichero."""
        path = Path(GEOTIFF / "f32_tile_lzw_p3.tif")
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        window_of("f32_tile_lzw_p3.tif", (10, 30), (5, 40))
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)


if __name__ == "__main__":
    unittest.main()
