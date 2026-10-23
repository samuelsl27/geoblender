# SPDX-License-Identifier: GPL-3.0-or-later
"""El GeoTIFF propio escrito por teselas: ``gis.geotiff.writer.write_steps`` (spec 011, T12;
plan 011 T4, §5.3.2 y A10; ADR-0020).

- **RF-011-05** (la rejilla de diferencias, dato de la versión activa, como cualquier rejilla
  de la 006) y **RNF-011-04** (cada llamada del hilo de Blender, ≤ 0,2 s): ``write_steps`` da
  **los mismos bytes** que ``write_geotiff`` con los perfiles ``project`` y ``deliverable``
  (también con NaN con carga, −0,0, un subnormal y ±∞, y BigTIFF por el umbral), con **un
  paso por tesela** (el avance de cada uno) y el fichero en su sitio al terminar.
- Como ``write_geotiff`` (RF-006-28, plan 006 §5.4 A4): temporal, ``fsync`` y renombrado;
  **cerrar el generador a mitad** (Esc) no deja el temporal y el destino anterior sigue
  intacto; con ``replace=False`` el fichero queda entero en el temporal que da quien llama; un
  destino abierto por otro programa es ``gis.raster_target_locked`` sin tocar el anterior; un
  fallo del disco, ``gis.raster_write_failed``. Lo que no se puede escribir (una cota que en
  float32 es −9999, otro objeto, el destino como temporal) se rechaza al llamar, sin pasos.

Las teselas de :data:`writer.TILE_SIZE` se reducen a 16 × 16 con ``mock.patch`` para tener
varias teselas, filas y bordes con rejillas pequeñas (unos milisegundos).
"""

import math
import os
import shutil
import struct
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import resources
from tests.support.package import import_geoblender

writer = import_geoblender("gis.geotiff.writer")
reader = import_geoblender("gis.geotiff.reader")
grid_mod = import_geoblender("gis.grid")
raster_mod = import_geoblender("gis.raster")
ports = import_geoblender("gis.ports")
messages = import_geoblender("gis.messages")
georef = import_geoblender("core.georef")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
PROJECT = ports.WriteProfile.PROJECT
DELIVERABLE = ports.WriteProfile.DELIVERABLE

TILE = 16
ROWS, COLS = 37, 50  # 3 × 4 teselas de 16: bordes de 5 filas y 2 columnas
DX, DY = 1.0002942907592702, 1.0003022974607014  # los pasos de B24: no son binarios exactos
WEST, NORTH = 700123.0, 4400321.5
PAYLOAD_NAN = np.frombuffer(struct.pack("<Q", 0x7FF8_0000_0000_0123), "<f8")[0]


def _surface(rows: int = ROWS, cols: int = COLS) -> np.ndarray:
    """Diferencias sintéticas: un plano inclinado con una onda, un hueco NaN que cruza
    teselas y, en la primera fila, un NaN con carga, −0,0, un subnormal y ±∞."""
    x = (np.arange(cols) + 0.5) * DX
    y = (np.arange(rows) + 0.5) * DY
    z = -12.5 + 0.05 * x[None, :] - 0.025 * y[:, None] + 3.0 * np.sin(x / 7.0)[None, :]
    z[10:22, 12:35] = np.nan
    z[0, :5] = (PAYLOAD_NAN, -0.0, 5e-324, math.inf, -math.inf)
    return z


def _raster(values: np.ndarray) -> Any:
    rows, cols = values.shape
    grid = grid_mod.Grid(WEST, NORTH, DX, DY, cols, rows)
    return raster_mod.Raster(grid, values, CRS, VERTICAL)


def _drain(steps: Iterator[float]) -> tuple[list[float], Any]:
    """Los avances de cada paso y lo que devuelve el generador al terminar."""
    fractions: list[float] = []
    while True:
        try:
            fractions.append(next(steps))
        except StopIteration as stop:
            return fractions, stop.value


class _Folder:
    def tmp(self) -> Path:
        folder = Path(tempfile.mkdtemp(prefix="gb-tifs-"))
        self.addCleanup(shutil.rmtree, folder, True)  # type: ignore[attr-defined]
        return folder


@mock.patch.object(writer, "TILE_SIZE", TILE)
class SameBytesTest(_Folder, unittest.TestCase):
    """Los mismos bytes que ``write_geotiff``, un paso por tesela (RF-011-05, RNF-011-04)."""

    def test_same_bytes_one_step_per_tile(self) -> None:
        """RF-011-05, RNF-011-04: con ``project`` y ``deliverable``, los bytes de
        ``write_geotiff``; 12 pasos (3 × 4 teselas), cada uno con su avance (i/12); mientras
        hay pasos, el destino no existe y solo está el temporal; al terminar, el destino (lo
        que devuelve) y ningún temporal. La entrada no cambia."""
        folder = self.tmp()
        values = _surface()
        before = values.copy()
        for profile in (PROJECT, DELIVERABLE):
            with self.subTest(perfil=profile):
                reference = folder / f"ref_{profile}.tif"
                writer.write_geotiff(_raster(values), reference, profile=profile)
                target = folder / f"res_dif_{profile}.tif"
                steps = writer.write_steps(_raster(values), target, profile=profile)
                fractions = []
                for fraction in steps:
                    fractions.append(fraction)
                    self.assertFalse(target.exists())
                    self.assertTrue(writer.temporary_path(target).exists())
                self.assertEqual(fractions, [(i + 1) / 12 for i in range(12)])
                self.assertEqual(target.read_bytes(), reference.read_bytes())
                self.assertFalse(writer.temporary_path(target).exists())
        self.assertTrue(np.array_equal(values.view(np.uint64), before.view(np.uint64)))
        source = reader.read_geotiff(folder / "res_dif_project.tif")
        self.assertTrue(np.array_equal(source.values.view(np.uint64), values.view(np.uint64)))

    def test_returns_what_it_wrote(self) -> None:
        """RF-011-05 (plan 006 §5.6.5): al terminar devuelve el destino; con un temporal
        dado y ``replace=False``, el temporal (entero, con los mismos bytes) y el destino
        anterior intacto. Con la tesela real de 256, una rejilla pequeña es un paso."""
        folder = self.tmp()
        values = _surface()
        target = folder / "res_dif_x.tif"
        target.write_bytes(b"anterior")
        temporary = folder / "res_dif_x.tif.tmp-0a1b2c3d"
        fractions, written = _drain(writer.write_steps(
            _raster(values), target, profile=PROJECT, temporary=temporary, replace=False))
        self.assertEqual((len(fractions), written), (12, temporary))
        self.assertEqual(target.read_bytes(), b"anterior")
        reference = folder / "ref.tif"
        writer.write_geotiff(_raster(values), reference, profile=PROJECT)
        self.assertEqual(temporary.read_bytes(), reference.read_bytes())
        with mock.patch.object(writer, "TILE_SIZE", 256):
            fractions, written = _drain(writer.write_steps(_raster(values), target,
                                                           profile=PROJECT))
            self.assertEqual((fractions, written), ([1.0], target))
            writer.write_geotiff(_raster(values), reference, profile=PROJECT)
        self.assertEqual(target.read_bytes(), reference.read_bytes())

    def test_bigtiff_by_the_threshold(self) -> None:
        """Plan 006 §5.4 A4: con el tamaño exacto del TIFF clásico como umbral, clásico, y
        con un byte menos, BigTIFF; en los dos, los bytes de ``write_geotiff`` con el mismo
        umbral, y el lector da los mismos bits."""
        folder = self.tmp()
        values = _surface()
        classic = folder / "clasico.tif"
        writer.write_geotiff(_raster(values), classic, profile=PROJECT)
        size = classic.stat().st_size
        for threshold, magic in ((size, b"II*\0"), (size - 1, b"II+\0")):
            with self.subTest(umbral=threshold):
                reference, target = folder / f"ref_{threshold}.tif", folder / f"{threshold}.tif"
                writer.write_geotiff(_raster(values), reference, profile=PROJECT,
                                     bigtiff_threshold=threshold)
                _drain(writer.write_steps(_raster(values), target, profile=PROJECT,
                                          bigtiff_threshold=threshold))
                data = target.read_bytes()
                self.assertEqual(data[:4], magic)
                self.assertEqual(data, reference.read_bytes())
                source = reader.read_geotiff(target)
                self.assertTrue(np.array_equal(source.values.view(np.uint64),
                                               values.view(np.uint64)))


@mock.patch.object(writer, "TILE_SIZE", TILE)
class StepsLeaveNothingHalfDoneTest(_Folder, unittest.TestCase):
    """Cerrar a mitad, destino bloqueado, fallo del disco y rechazos (RF-011-05, RF-006-28)."""

    def setUp(self) -> None:
        self.folder = self.tmp()
        self.target = self.folder / "res_dif_x.tif"
        self.target.write_bytes(b"anterior")

    def _names(self) -> list[str]:
        return sorted(p.name for p in self.folder.iterdir())

    def test_closing_halfway_leaves_no_temporary(self) -> None:
        """RF-011-05 (Esc a mitad): tras 5 de 12 pasos, cerrar el generador borra el temporal
        (el por defecto y el que da quien llama) y el destino sigue siendo el anterior;
        cerrarlo sin empezar no crea nada."""
        named = self.folder / "res_dif_x.tif.tmp-0a1b2c3d"
        for temporary in (None, named):
            with self.subTest(temporal=temporary):
                steps = writer.write_steps(_raster(_surface()), self.target, profile=PROJECT,
                                           temporary=temporary)
                for _ in range(5):
                    next(steps)
                self.assertEqual(len(self._names()), 2)
                steps.close()
                self.assertEqual(self._names(), ["res_dif_x.tif"])
                self.assertEqual(self.target.read_bytes(), b"anterior")
        writer.write_steps(_raster(_surface()), self.target, profile=PROJECT).close()
        self.assertEqual(self._names(), ["res_dif_x.tif"])

    def test_locked_target_keeps_the_previous_file(self) -> None:
        """Plan 011 §2.1 y 006 §5.6.5 (D20): si otro programa tiene abierto el destino (QGIS)
        y Windows no deja sustituirlo, el último paso es ``gis.raster_target_locked`` con el
        fichero; el destino no cambia y no queda el temporal."""
        if os.name != "nt":
            self.skipTest(resources.skip_reason(resources.WINDOWS, resources.WINDOWS_HINT))
        steps = writer.write_steps(_raster(_surface()), self.target, profile=PROJECT)
        with self.target.open("rb"), self.assertRaises(messages.GisError) as caught:
            _drain(steps)
        error = caught.exception
        self.assertEqual(error.code, "gis.raster_target_locked")
        self.assertEqual((error.obj, error.field), ("res_dif_x.tif", "destino"))
        self.assertEqual(self.target.read_bytes(), b"anterior")
        self.assertEqual(self._names(), ["res_dif_x.tif"])

    def test_disk_error_keeps_the_previous_file(self) -> None:
        """RF-006-28: un fallo del disco (sin espacio al forzar a disco) es
        ``gis.raster_write_failed`` con el fichero y el detalle; ni temporal ni destino
        cambiado."""
        error = OSError(28, "No queda espacio en el disco")
        steps = writer.write_steps(_raster(_surface()), self.target, profile=PROJECT)
        with mock.patch.object(writer.os, "fsync", side_effect=error), \
                self.assertRaises(messages.GisError) as caught:
            _drain(steps)
        self.assertEqual(caught.exception.code, "gis.raster_write_failed")
        self.assertIn("No queda espacio", str(caught.exception))
        self.assertEqual(self.target.read_bytes(), b"anterior")
        self.assertEqual(self._names(), ["res_dif_x.tif"])

    def test_rejected_when_called(self) -> None:
        """RF-006-24: una cota que en float32 es −9999 (``gis.export_nodata_collision``),
        otro objeto, un perfil que no existe o el propio destino como temporal se rechazan al
        llamar, antes de ningún paso y sin escribir nada."""
        values = _surface()
        values[3, 4] = -9999.0
        with self.assertRaises(messages.GisError) as caught:
            writer.write_steps(_raster(values), self.target, profile=DELIVERABLE)
        self.assertEqual(caught.exception.code, "gis.export_nodata_collision")
        wrong = (
            (TypeError, (values, self.target), {"profile": PROJECT}),
            (ValueError, (_raster(values), self.target), {"profile": "otro"}),
            (ValueError, (_raster(values), self.target),
             {"profile": PROJECT, "temporary": self.target}),
        )
        for kind, args, kwargs in wrong:
            with self.subTest(error=kind, opciones=kwargs), self.assertRaises(kind):
                writer.write_steps(*args, **kwargs)
        self.assertEqual(self._names(), ["res_dif_x.tif"])
        self.assertEqual(self.target.read_bytes(), b"anterior")


if __name__ == "__main__":
    unittest.main()
