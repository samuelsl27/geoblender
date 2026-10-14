# SPDX-License-Identifier: GPL-3.0-or-later
"""Lectores de contenido de la 006 (spec 006, T40; RF-006-26; RF-008-08, RF-008-09,
RF-008-14; ADR-0024; plan 006 §5.6.2 y D19).

``gis.content`` declara cinco lectores (``ContentReader`` de la 008): ``gis.geotiff@1``,
``gis.asc@1``, ``gis.xyz_grid@1``, ``gis.points_text@1`` y ``gis.gpkg_layer@1``. Con los datos
de ``tests/data/gis/``:

- **GeoTIFF** (RF-008-08, D-8): las variantes del MDT con los mismos valores (compresión, tiras
  o teselas, BigTIFF, «II» o «MM», float32 frente a su ampliación a float64) dan el mismo hash
  de datos, y otro sin dato, *PixelIsPoint*, otro CRS en el fichero o un valor cambiado, otro;
  el CRS declarado y el sin dato forzado solo cambian el de contenido. Lo que se hashea es lo
  que lee ``read_geotiff`` (sin dato y teselas que faltan, NaN), con la referencia de la celda
  del noroeste tal como la da el fichero. Lo que escribe ``GeoTiffIO`` con el perfil
  ``project``, leído con ``gis.geotiff@1``, da el hash de la rejilla escrita
  (``raster_digest``; ida y vuelta, también en BigTIFF).
- **ASC** (compuesto: la rejilla y, si lo hay, el ``.prj`` como documento): con y sin ``.prj``,
  esquina o centro, otro ``NODATA_value`` u otro ``.prj``, otro hash; los mismos valores
  repartidos en otras líneas y la cabecera en mayúsculas, el mismo.
- **XYZ en malla**: el orden de los puntos, el separador y el decimal no cuentan; una celda
  que falta o una cota cambiada, sí.
- **Texto de puntos** (``interop.csv_tables`` a través del puerto ``gis.ports.TableReader``:
  ``gis`` no importa ``interop``, ARQ-07): el CSV con «;» y coma decimal y el mismo con «,» y
  punto, o en Latin-1, dan el mismo hash de datos; otra correspondencia de columnas, otro hash
  de contenido; una fila que no se puede importar cuenta con su texto.
- **Capas de GeoPackage** (D19): el mismo hash de datos que ``core.gpkg_layer@1``, también con
  una edición pendiente en el ``-wal`` (sobre una copia, sin ``-wal`` ni ``-shm`` nuevos junto
  a la fuente, RF-008-14).
- Cada lector da su progreso y se cancela entre trozos (RF-006-28); ninguno toca su fuente
  (RF-006-10); registrar y quitar no deja rastro; el envoltorio del trabajo
  ``core_content_hash`` los registra con el lector de tablas (RF-008-09).
"""

import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_data import BOUNDARY_V2, DATA_DIR, LAYER, make_wal_variant
from tests.support.repo import ROOT
from tests.support.trees import age_folders
from tests.unit.gis import test_geotiff_read as built

content = import_geoblender("gis.content")
gis_reader = import_geoblender("gis.geotiff.reader")
geotiff = import_geoblender("gis.geotiff")
asc = import_geoblender("gis.asc")
xyz_grid = import_geoblender("gis.xyz_grid")
raster_mod = import_geoblender("gis.raster")
grid_mod = import_geoblender("gis.grid")
messages = import_geoblender("gis.messages")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
encoder = import_geoblender("core.content.encoder")
georef = import_geoblender("core.georef")
csv_tables = import_geoblender("interop.csv_tables")
worker = import_geoblender("workers.core_content_hash")
content_hash = import_geoblender("jobs.content_hash")
job_paths = import_geoblender("jobs.paths")
worker_api = import_geoblender("jobs.worker_api")
checks = import_geoblender("core.provenance.checks")

DATA = ROOT / "tests" / "data" / "gis"
GEOTIFF = DATA / "geotiff"
ASC = DATA / "asc"
XYZ = DATA / "xyz"
POINTS = DATA / "points"
CAPAS = DATA / "gpkg" / "capas.gpkg"
CATALOG = georef.load_catalog()

READER_IDS = ("gis.geotiff@1", "gis.asc@1", "gis.xyz_grid@1", "gis.points_text@1",
              "gis.gpkg_layer@1")
DECL = {"conventions": {}, "crs_h": {"epsg": 25830}, "crs_v": {"epsg": 5782}}
POINT_COLUMNS = {"point_id": 0, "x": 1, "y": 2, "z": 3, "code": 4, "line": 5}
POINT_SETTINGS = {"encoding": "utf-8", "separator": ";", "decimal": ",", "header_row": 0,
                  "columns": POINT_COLUMNS, "line_kind": "hard"}
F32_SAME = ("f32_strip.tif", "f32_strip_packbits.tif", "f32_tile.tif", "f32_tile_lzw_p3.tif",
            "f32_bigtiff.tif", "f32_mm.tif")
LAYERS = ("puntos_z", "roturas_z", "contorno", "puntos_2d", "curvas_zm")
SMALL_CHUNK = 512  # bytes entre dos ``yield``: varios trozos con los datos de T01


def setUpModule() -> None:
    previous = content.use_table_reader(csv_tables.read_table)
    unittest.addModuleCleanup(content.use_table_reader, previous)


def _digest(reader: object, files: dict, *, settings: dict | None = None,
            declarations: dict = DECL, chunk_bytes: int = readers.DEFAULT_CHUNK_BYTES,
            progress=None, cancelled=None) -> object:
    """El ``ContentDigest`` de una fuente con un lector (``read_content``)."""
    request = reader.request(reader.kinds[0], declarations, files, settings or {},
                             chunk_bytes=chunk_bytes)
    return readers.read_content(reader, request, progress=progress, cancelled=cancelled)


def _tif(name: str, **options: object) -> object:
    return _digest(content.GEOTIFF, {"main": GEOTIFF / name}, **options)


def _grid_data(header: dict, values: np.ndarray) -> str:
    """El hash de datos de una rejilla calculado aparte, con ``ContentHasher.grid``."""
    hasher = encoder.ContentHasher("raster", declarations={})
    return hasher.grid(header, values).digest().data_sha256


def _header(rows: int, columns: int, x0: float, y0: float, *, dx: float = 1.0,
            dy: float = 1.0, cell: str = "area", nodata: float | None = -9999.0,
            crs: int | None = 25830) -> dict:
    return {"rows": rows, "columns": columns, "x0": x0, "y0": y0, "dx": dx, "dy": dy,
            "cell": cell, "class": "float", "nodata": nodata,
            "crs": None if crs is None else {"epsg": crs}}


def _steps(reader: object, files: dict, **options: object) -> list[float]:
    seen: list[float] = []
    _digest(reader, files, chunk_bytes=SMALL_CHUNK, progress=seen.append, **options)
    return seen


class _Temp(unittest.TestCase):
    """Una carpeta temporal por prueba, de ruta corta."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gb-cr-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def progress_and_cancel(self, reader: object, files: dict, **options: object) -> None:
        """Ayuda: avance creciente tras cada trozo hasta 1; cancelar tras el primero para
        entre dos trozos (``ReadCancelled``) y deja el fichero cerrado (se puede borrar)."""
        copies = {}
        for role, path in files.items():
            copies[role] = self.tmp / f"copia_{role}{Path(path).suffix}"
            shutil.copyfile(path, copies[role])
        seen = _steps(reader, copies, **options)
        self.assertGreaterEqual(len(seen), 3)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 1.0)
        self.assertLess(seen[-2], 1.0)
        stopped: list[float] = []
        with self.assertRaises(readers.ReadCancelled) as caught:
            _digest(reader, copies, chunk_bytes=SMALL_CHUNK, progress=stopped.append,
                    cancelled=lambda: bool(stopped), **options)
        self.assertEqual(stopped, seen[:1])
        self.assertLess(caught.exception.progress, 1.0)
        for path in copies.values():
            os.remove(path)  # en Windows falla si sigue abierto


class DeclarationsTest(unittest.TestCase):
    """Los cinco lectores, su registro y dónde se hashean."""

    def test_the_five_readers(self) -> None:
        """RF-006-26, RF-008-09 (plan §5.6.2): ``CONTENT_READERS`` son los cinco lectores de la
        006, del módulo ``gis``, con su tipo; todos pueden ir al trabajo de hash; solo el de
        capas de GeoPackage es SQLite y se lee sobre una copia (``needs_copy``)."""
        found = {reader.id: reader for reader in content.CONTENT_READERS}
        self.assertEqual(tuple(found), READER_IDS)
        kinds = {"gis.geotiff@1": ("raster",), "gis.asc@1": ("raster",),
                 "gis.xyz_grid@1": ("raster",), "gis.points_text@1": ("table",),
                 "gis.gpkg_layer@1": ("vector",)}
        for reader_id, reader in found.items():
            with self.subTest(lector=reader_id):
                self.assertIsInstance(reader, readers.ContentReader)
                self.assertEqual(reader.module, "gis")
                self.assertEqual(reader.kinds, kinds[reader_id])
                self.assertTrue(reader.worker)
                gpkg = reader_id == "gis.gpkg_layer@1"
                self.assertEqual((reader.needs_copy, reader.sqlite), (gpkg, gpkg))

    def test_register_and_unregister_leave_no_trace(self) -> None:
        """ADR-0025 §2: los cinco se registran en ``core.content`` y se quitan sin dejar
        rastro; registrar dos veces el mismo es un error del programa."""
        before = dict(readers.READERS)
        for reader in content.CONTENT_READERS:
            readers.register_reader(reader)
            self.addCleanup(readers.unregister_reader, reader.id)
        for reader_id in READER_IDS:
            self.assertEqual(readers.reader(reader_id).id, reader_id)
        with self.assertRaises(ValueError):
            readers.register_reader(content.GEOTIFF)
        for reader in content.CONTENT_READERS:
            self.assertEqual(readers.unregister_reader(reader.id), 1)
        self.assertEqual(dict(readers.READERS), before)

    def test_estimates_choose_where_to_hash(self) -> None:
        """RF-008-09 (ADR-0025 §7): una fuente externa pequeña se hashea en el hilo y una
        grande, en el trabajo; lo del proyecto, siempre en el hilo."""
        for reader in content.CONTENT_READERS:
            with self.subTest(lector=reader.id):
                self.assertEqual(readers.plan_hash(reader, "external", 50_000), "inline")
                self.assertEqual(readers.plan_hash(reader, "external", 10**9), "job")
                self.assertEqual(readers.plan_hash(reader, "project", None), "inline")

    def test_unknown_settings_are_rejected(self) -> None:
        """ADR-0024 §5: cada lector admite sus ajustes de lectura y rechaza los demás (un error
        del programa, ``ValueError``), antes de leer nada."""
        cases = (
            (content.GEOTIFF, {"main": GEOTIFF / "f32_strip.tif"}, {"layer": "x"}),
            (content.ASC, {"main": ASC / "corner.asc"}, {"separator": ";"}),
            (content.XYZ_GRID, {"main": XYZ / "grid.xyz"}, {"columns": {}}),
            (content.POINTS_TEXT, {"main": POINTS / "taludes.csv"},
             {**POINT_SETTINGS, "sheet": "1"}),
            (content.GPKG_LAYER, {"main": CAPAS}, {"layer": "puntos_z", "selector": None}),
        )
        for reader, files, settings in cases:
            with self.subTest(lector=reader.id), self.assertRaises(ValueError):
                _digest(reader, files, settings=settings)


class GeoTiffTest(_Temp):
    """``gis.geotiff@1``."""

    def test_same_values_give_the_same_hash(self) -> None:
        """RF-008-08 (D-8; ADR-0024 §4): compresión, tiras o teselas, BigTIFF y orden de bytes
        no cuentan, ni float32 frente a su ampliación a float64 (un Float64 escrito con los
        float32 de ``f32_strip``); Float64, Float32 e Int16 con otros valores, sí. El hash de
        datos es el de la rejilla de 64 × 48 con oeste 700 000 y norte 4 400 048, sin dato
        −9999, EPSG:25830 y las cotas de T01 con el hueco en NaN."""
        widened = np.where(np.isnan(built.F32_1M), -9999.0, built.F32_1M)
        f64 = built._build(self.tmp / "f64_de_f32.tif", widened.astype(np.float64))
        f32 = built._build(self.tmp / "f32_propio.tif", widened.astype(np.float32))
        groups = {
            "f32": [_tif(name) for name in F32_SAME]
            + [_digest(content.GEOTIFF, {"main": path}) for path in (f64, f32)],
            "f64": [_tif("f64_strip.tif"), _tif("f64_strip_deflate_p3.tif")],
            "i16": [_tif("i16_strip.tif"), _tif("i16_strip_lzw_p2.tif")],
        }
        for name, digests in groups.items():
            with self.subTest(grupo=name):
                self.assertEqual({d.data_sha256 for d in digests}, {digests[0].data_sha256})
                self.assertEqual({d.content_sha256 for d in digests},
                                 {digests[0].content_sha256})
                self.assertEqual(digests[0].reader, "gis.geotiff@1")
        self.assertEqual(len({digests[0].data_sha256 for digests in groups.values()}), 3)
        expected = _grid_data(_header(48, 64, 700000.0, 4400048.0), built.F32_1M)
        self.assertEqual(groups["f32"][0].data_sha256, expected)
        decl = encoder.content_sha256("raster", DECL, expected)
        self.assertEqual(groups["f32"][0].content_sha256, decl)

    def test_hash_is_what_the_importer_reads(self) -> None:
        """RF-006-08, RF-008-08: cada GeoTIFF de T01 que se admite da el hash de lo que lee
        ``read_geotiff`` (sin dato y teselas que no están en el fichero, NaN), con la
        referencia de la celda del noroeste tal como la da el fichero (con *PixelIsPoint*,
        su centro: medio paso al sureste de la esquina que importa), el sin dato de
        ``GDAL_NODATA`` y el CRS de sus claves (``None`` sin ellas)."""
        for name in built.READABLE:
            with self.subTest(fichero=name):
                source = gis_reader.read_geotiff(GEOTIFF / name)
                grid = source.grid
                x0, y0 = grid.west, grid.north
                if source.pixel_is_point:
                    x0, y0 = x0 + grid.dx / 2.0, y0 - grid.dy / 2.0
                crs = None if source.declared_crs is None else source.declared_crs.epsg
                header = _header(grid.nrows, grid.ncols, x0, y0, dx=grid.dx, dy=grid.dy,
                                 cell="point" if source.pixel_is_point else "area",
                                 nodata=source.nodata_value, crs=crs)
                self.assertEqual(_tif(name).data_sha256, _grid_data(header, source.values))

    def test_what_changes_the_hash(self) -> None:
        """RF-008-08 (D-8): otro hash de datos con *PixelIsPoint* (centro 700 000,5; 4 400 047,5),
        otro CRS en el fichero (EPSG:23030) o ninguno, otro sin dato (−32 768 en lugar de
        −9999, con las mismas celdas) y una cota cambiada en un ulp de float32. El CRS
        declarado (23030) y un sin dato forzado (``nodata_override`` en las convenciones)
        cambian solo el hash de contenido."""
        base = _tif("f32_strip.tif")
        point = _tif("f32_pixelispoint.tif")
        self.assertEqual(point.data_sha256, _grid_data(
            _header(48, 64, 700000.5, 4400047.5, cell="point"), built.F32_1M))
        image = built.F32_1M.astype(np.float32)  # el hueco, NaN: ningún −9999 ni −32 768
        nodata = [_digest(content.GEOTIFF, {"main": built._build(
            self.tmp / f"sin_dato_{text}.tif", image, tags={42113: (2, text)})})
            for text in ("-9999", "-32768")]
        changed = image.copy()
        changed[0, 0] = np.nextafter(changed[0, 0], np.float32(np.inf))
        other_value = _digest(content.GEOTIFF, {"main": built._build(self.tmp / "valor.tif",
                                                                     changed)})
        others = [point, _tif("f32_epsg23030.tif"), _tif("f32_nocrs.tif"), nodata[1],
                  other_value]
        datas = [base.data_sha256] + [d.data_sha256 for d in others]
        self.assertEqual(len(set(datas)), len(datas))
        self.assertEqual(nodata[0].data_sha256, base.data_sha256)  # NaN = el −9999 del hueco
        for declarations in ({**DECL, "crs_h": {"epsg": 23030}},
                             {**DECL, "conventions": {"nodata_override": -32768.0}}):
            with self.subTest(declarado=declarations):
                other = _tif("f32_strip.tif", declarations=declarations,
                             settings={"nodata_override": -32768.0}
                             if declarations["conventions"] else None)
                self.assertEqual(other.data_sha256, base.data_sha256)
                self.assertNotEqual(other.content_sha256, base.content_sha256)

    def test_round_trip_through_geotiffio(self) -> None:
        """RF-006-08 (ADR-0024, ida y vuelta): lo que escribe ``GeoTiffIO`` con el perfil
        ``project`` (Float64, NaN, teselas de 256 rellenas en el borde), leído con
        ``gis.geotiff@1``, da el hash de la rejilla escrita (``content.raster_digest``), también
        en BigTIFF; con −0,0, un NaN con carga y una rejilla de 257 × 3 de paso 0,5."""
        source = gis_reader.read_geotiff(GEOTIFF / "f64_strip.tif")
        crs, vertical = CATALOG.horizontal(25830), CATALOG.vertical(5782)
        first = raster_mod.Raster(source.grid, source.values, crs, vertical)
        values = np.linspace(780.0, 820.0, 257 * 3).reshape(257, 3)
        values[0, 0] = -0.0
        values[5, 1] = np.frombuffer(np.uint64(0x7FF8_0000_0000_0123).tobytes(), np.float64)[0]
        odd = grid_mod.Grid(700000.0, 4400128.5, 0.5, 0.5, 3, 257)
        second = raster_mod.Raster(odd, values, crs, vertical)
        for label, raster in (("f64_strip", first), ("257 × 3", second)):
            expected = content.raster_digest(raster, DECL)
            self.assertEqual(expected.reader, "gis.geotiff@1")
            for threshold in (geotiff.writer.BIGTIFF_THRESHOLD, 0):
                with self.subTest(rejilla=label, bigtiff=threshold == 0):
                    path = self.tmp / f"r_{threshold}.tif"
                    geotiff.GeoTiffIO(bigtiff_threshold=threshold).write(
                        raster, path, profile="project")
                    self.assertEqual(_digest(content.GEOTIFF, {"main": path}), expected)

    def test_raster_digest_by_bands_with_progress(self) -> None:
        """RF-006-28 (T33: 11,2 M celdas son medio segundo de hash): ``raster_digest`` hashea
        por bandas de filas (aquí de 7 celdas: 2 filas de 3) con el mismo hash que de una vez,
        da su avance tras cada banda, hasta 1, y si se pide parar, ``JobCancelled`` antes de
        la siguiente."""
        crs, vertical = CATALOG.horizontal(25830), CATALOG.vertical(5782)
        values = np.linspace(780.0, 820.0, 257 * 3).reshape(257, 3)
        values[4, 2] = np.nan
        raster = raster_mod.Raster(grid_mod.Grid(700000.0, 4400128.5, 0.5, 0.5, 3, 257), values,
                                   crs, vertical)
        expected = content.raster_digest(raster, DECL)  # 771 celdas: una sola banda
        seen: list[tuple[float, str]] = []
        with mock.patch.object(content, "DIGEST_BLOCK_CELLS", 7):
            got = content.raster_digest(raster, DECL,
                                        progress=lambda frac, text: seen.append((frac, text)))
            self.assertEqual(got, expected)
            self.assertEqual(len(seen), 129)  # 257 filas de 2 en 2
            self.assertEqual([frac for frac, _ in seen], sorted(frac for frac, _ in seen))
            self.assertEqual(seen[-1], (1.0, content.DIGEST_TEXT))
            seen.clear()
            with self.assertRaises(worker_api.JobCancelled):
                content.raster_digest(raster, DECL,
                                      progress=lambda frac, text: seen.append((frac, text)),
                                      cancelled=lambda: len(seen) >= 3)
        self.assertEqual(len(seen), 3)

    def test_progress_and_cancel(self) -> None:
        """RF-006-28: por tiras (``f64_strip``: 3 de 16 filas) y por teselas (``f32_tile``:
        4 de 32 × 32)."""
        for name in ("f64_strip.tif", "f32_tile.tif"):
            with self.subTest(fichero=name):
                self.progress_and_cancel(content.GEOTIFF, {"main": GEOTIFF / name})

    def test_rejected_files_raise_the_importer_error(self) -> None:
        """RF-006-09: lo que el importador rechaza no tiene hash (el mismo ``GisError``)."""
        for name in built.REJECTED:
            with self.subTest(fichero=name), self.assertRaises(messages.GisError):
                _tif(name)


class AscTest(_Temp):
    """``gis.asc@1``: la rejilla y su ``.prj`` (compuesto)."""

    def rewrite(self, name: str, text: str, prj: bytes | None = None) -> dict:
        path = self.tmp / name
        path.write_bytes(text.encode("ascii"))
        files = {"main": path}
        if prj is not None:
            files["prj"] = path.with_suffix(".prj")
            files["prj"].write_bytes(prj)
        return files

    def test_composite_of_grid_and_prj(self) -> None:
        """RF-008-08 (ADR-0024 §4: el ``.prj`` es una parte): la rejilla es la parte «main»
        (lo que lee ``read_asc``, con su esquina noroeste o, con ``xllcenter``, el centro de
        la celda del noroeste, tipo de celda área o punto y su ``NODATA_value``) y el
        ``.prj``, la parte «prj» (sus bytes); con y sin ``.prj`` y esquina o centro, otro
        hash."""
        values = asc.read_asc(ASC / "corner.asc").values
        corner = _grid_data(_header(48, 64, 700000.0, 4400048.0, crs=None), values)
        center = _grid_data(_header(48, 64, 700000.5, 4400047.5, cell="point", crs=None),
                            values)
        prj = (ASC / "corner.prj").read_bytes()
        prj_data = encoder.ContentHasher("document", declarations={}).document(
            [prj]).digest().data_sha256
        cases = {
            "corner": ({"main": ASC / "corner.asc"}, {"main": ("raster", corner)}),
            "corner+prj": ({"main": ASC / "corner.asc", "prj": ASC / "corner.prj"},
                           {"main": ("raster", corner), "prj": ("document", prj_data)}),
            "center": ({"main": ASC / "center.asc"}, {"main": ("raster", center)}),
        }
        found = set()
        for label, (files, parts) in cases.items():
            with self.subTest(caso=label):
                digest = _digest(content.ASC, files)
                self.assertEqual(digest.data_sha256, encoder.composite_sha256(parts))
                found.add(digest.data_sha256)
        self.assertEqual(len(found), 3)

    def test_layout_does_not_count_and_values_do(self) -> None:
        """RF-008-08: los mismos valores en una línea por valor, con CRLF y la cabecera en
        mayúsculas, dan el mismo hash; otro ``NODATA_value`` (el hueco pasa a ser cota) u otro
        ``.prj`` (un espacio al final), otro."""
        text = (ASC / "corner.asc").read_text("ascii")
        header, _, body = text.partition("\n788")
        lines = header.upper().splitlines()  # las claves, sin distinguir mayúsculas
        flat = "\r\n".join([*lines, *("788" + body).split()]) + "\r\n"
        prj = (ASC / "corner.prj").read_bytes()
        reference = _digest(content.ASC, {"main": ASC / "corner.asc", "prj": ASC / "corner.prj"})
        same = _digest(content.ASC, self.rewrite("plano.asc", flat, prj))
        self.assertEqual(same, reference)
        nodata = _digest(content.ASC, self.rewrite(
            "nodata.asc", text.replace("NODATA_value -9999.000", "NODATA_value -9998.000"), prj))
        other_prj = _digest(content.ASC, self.rewrite("prj.asc", text, prj + b" "))
        self.assertEqual(len({reference.data_sha256, nodata.data_sha256,
                              other_prj.data_sha256}), 3)

    def test_progress_and_cancel(self) -> None:
        """RF-006-28: por trozos de ``chunk_bytes`` del cuerpo."""
        self.progress_and_cancel(content.ASC, {"main": ASC / "corner.asc",
                                               "prj": ASC / "corner.prj"})


class XyzGridTest(_Temp):
    """``gis.xyz_grid@1``."""

    def test_hash_is_the_grid_of_the_points(self) -> None:
        """RF-006-08, RF-008-08: la rejilla de 20 × 15 cuyos centros son los puntos (la
        referencia, el centro de la celda del noroeste: 700 000,5; 4 400 014,5), tipo punto,
        sin dato ni CRS del fichero."""
        values = xyz_grid.read_xyz_grid(XYZ / "grid.xyz").values
        expected = _grid_data(_header(15, 20, 700000.5, 4400014.5, cell="point",
                                      nodata=None, crs=None), values)
        self.assertEqual(_digest(content.XYZ_GRID, {"main": XYZ / "grid.xyz"}).data_sha256,
                         expected)

    def test_order_separator_and_decimal_do_not_count(self) -> None:
        """RF-008-08 («separador decimal ya aplicado», ADR-0024 §3): los mismos puntos al
        revés, con cabecera, «;» y coma decimal, el mismo hash; con una celda menos
        (``grid_hole.xyz``: 6) o una cota cambiada en 1 mm, otro."""
        lines = (XYZ / "grid.xyz").read_text("ascii").splitlines()
        swapped = ["X;Y;Z", *(line.replace(" ", ";").replace(".", ",")
                              for line in reversed(lines))]
        path = self.tmp / "puntos.xyz"
        path.write_text("\n".join(swapped) + "\n", "ascii")
        settings = {"separator": ";", "decimal": ","}
        reference = _digest(content.XYZ_GRID, {"main": XYZ / "grid.xyz"})
        self.assertEqual(_digest(content.XYZ_GRID, {"main": path}, settings=settings),
                         reference)
        hole = _digest(content.XYZ_GRID, {"main": XYZ / "grid_hole.xyz"}, settings=settings)
        x, y, z = lines[40].split()
        changed = self.tmp / "cambiado.xyz"
        changed.write_text("\n".join([*lines[:40], f"{x} {y} {float(z) + 0.001:.3f}",
                                      *lines[41:]]) + "\n", "ascii")
        other = _digest(content.XYZ_GRID, {"main": changed})
        self.assertEqual(len({reference.data_sha256, hole.data_sha256,
                              other.data_sha256}), 3)

    def test_progress_and_cancel(self) -> None:
        """RF-006-28: por trozos de ``chunk_bytes`` al leer los puntos."""
        self.progress_and_cancel(content.XYZ_GRID, {"main": XYZ / "grid.xyz"})


class PointsTextTest(_Temp):
    """``gis.points_text@1`` (con el lector de tablas de ``interop``)."""

    def points(self, path: Path, **settings: object) -> object:
        return _digest(content.POINTS_TEXT, {"main": path},
                       settings={**POINT_SETTINGS, **settings})

    def test_separator_decimal_and_encoding_do_not_count(self) -> None:
        """RF-008-08 (ADR-0024 §4: filas ya interpretadas): el CSV con «;» y coma decimal y
        el mismo con «,» y punto (la cabecera con otros nombres), o en Windows-1252, dan el
        mismo hash de datos y de contenido; es una tabla en el orden del fichero con X, Y y Z
        en float64 y el punto, el código y la línea en texto."""
        text = (POINTS / "taludes.csv").read_text("utf-8")
        commas = text.replace(",", ".").replace(";", ",").replace("Código", "COD")
        comma_path = self.tmp / "comas.csv"
        comma_path.write_text(commas, "utf-8")
        latin = self.tmp / "latin.csv"
        latin.write_bytes(text.encode("cp1252"))
        reference = self.points(POINTS / "taludes.csv")
        self.assertEqual(self.points(comma_path, separator=",", decimal="."), reference)
        self.assertEqual(self.points(latin, encoding="cp1252"), reference)
        table = csv_tables.read_table(POINTS / "taludes.csv", encoding="utf-8", separator=";")
        rows = [[float(f[1].replace(",", ".")), float(f[2].replace(",", ".")),
                 float(f[3].replace(",", ".")), f[0], f[4], f[5], None] for f in table.rows]
        columns = [["x", "float"], ["y", "float"], ["z", "float"], ["point_id", "text"],
                   ["code", "text"], ["line", "text"], ["raw", "text"]]
        expected = encoder.ContentHasher("table", declarations={}).rows(
            columns, True, rows).digest().data_sha256
        self.assertEqual(reference.data_sha256, expected)

    def test_mapping_is_content(self) -> None:
        """RF-008-08, RF-008-54: otra correspondencia de columnas (X e Y cambiadas), declarada
        en las convenciones, da otro hash de contenido (y de datos); el tipo de línea, solo
        el de contenido."""
        swapped = {**POINT_COLUMNS, "x": 2, "y": 1}
        reference = self.points(POINTS / "taludes.csv")
        other = _digest(content.POINTS_TEXT, {"main": POINTS / "taludes.csv"},
                        settings={**POINT_SETTINGS, "columns": swapped},
                        declarations={**DECL, "conventions": {"columns": swapped}})
        self.assertNotEqual(other.content_sha256, reference.content_sha256)
        self.assertNotEqual(other.data_sha256, reference.data_sha256)
        soft = _digest(content.POINTS_TEXT, {"main": POINTS / "taludes.csv"},
                       settings={**POINT_SETTINGS, "line_kind": "soft"},
                       declarations={**DECL, "conventions": {"line_kind": "soft"}})
        self.assertEqual(soft.data_sha256, reference.data_sha256)
        self.assertNotEqual(soft.content_sha256, reference.content_sha256)

    def test_rows_that_cannot_be_imported_count_with_their_text(self) -> None:
        """RF-008-08 (D-8, exacto): ``errores.csv`` (Z vacía, X con letras, columnas de menos)
        tiene hash; cambiar el texto de una X que no es un número lo cambia."""
        reference = self.points(POINTS / "errores.csv")
        text = (POINTS / "errores.csv").read_text("utf-8")
        path = self.tmp / "errores.csv"
        path.write_text(text.replace("7OO030,000", "7OO030,001"), "utf-8")
        self.assertNotEqual(self.points(path).data_sha256, reference.data_sha256)

    def test_without_table_reader(self) -> None:
        """ARQ-07: sin el lector de tablas que da ``bl`` (o el envoltorio del trabajo), el
        lector de puntos lo dice (``RuntimeError``) sin leer nada."""
        previous = content.use_table_reader(None)
        self.addCleanup(content.use_table_reader, previous)
        with self.assertRaises(RuntimeError) as caught:
            self.points(POINTS / "taludes.csv")
        self.assertIn("interop", str(caught.exception))

    def test_progress_and_cancel(self) -> None:
        """RF-006-28: tras leer la tabla y por lotes de filas."""
        self.progress_and_cancel(content.POINTS_TEXT, {"main": POINTS / "taludes.csv"},
                                 settings=POINT_SETTINGS)


class GpkgLayerTest(_Temp):
    """``gis.gpkg_layer@1``, que delega en ``core.gpkg_layer@1`` (D19)."""

    def both(self, path: Path, layer: str, **settings: object) -> tuple[object, object]:
        gis = _digest(content.GPKG_LAYER, {"main": path}, settings={"layer": layer, **settings})
        core = _digest(builtin.GPKG_LAYER, {"main": path}, settings={"layer": layer})
        return gis, core

    def test_same_hash_as_the_core_reader(self) -> None:
        """RF-008-08, D19: cada capa de ``capas.gpkg`` da el mismo hash de datos y de contenido
        que con ``core.gpkg_layer@1`` (el lector es otro); el papel y el campo de cota son
        ajustes que no se leen (son convenciones)."""
        for layer in LAYERS:
            with self.subTest(capa=layer):
                gis, core = self.both(CAPAS, layer, role="points", elevation_field=None)
                self.assertEqual((gis.data_sha256, gis.content_sha256),
                                 (core.data_sha256, core.content_sha256))
                self.assertEqual((gis.reader, core.reader),
                                 ("gis.gpkg_layer@1", "core.gpkg_layer@1"))

    def test_pending_edit_in_the_wal_on_a_copy(self) -> None:
        """RF-008-08, RF-008-14: con la edición de la 008 pendiente en el ``-wal``, el mismo
        hash que ``core.gpkg_layer@1`` (el de ``Limites_v2.gpkg``), leído sobre una copia: junto
        a la fuente no se crea, cambia ni borra nada; una base sin ``-wal`` no queda con
        ``-wal`` ni ``-shm``."""
        wal_folder = self.tmp / "wal"
        wal_folder.mkdir()
        variant = make_wal_variant(wal_folder)
        quiet = self.tmp / "sin_wal"
        quiet.mkdir()
        shutil.copyfile(CAPAS, quiet / CAPAS.name)
        for folder in (wal_folder, quiet):
            age_folders(folder)
        with assert_source_untouched(wal_folder), assert_source_untouched(quiet):
            gis, core = self.both(variant.path, LAYER)
            self.both(quiet / CAPAS.name, "roturas_z")
        self.assertEqual(gis.data_sha256, core.data_sha256)
        v2 = _digest(builtin.GPKG_LAYER, {"main": DATA_DIR / BOUNDARY_V2},
                     settings={"layer": LAYER})
        self.assertEqual(gis.data_sha256, v2.data_sha256)
        self.assertEqual(sorted(p.name for p in quiet.iterdir()), [CAPAS.name])

    def test_progress_and_cancel(self) -> None:
        """RF-006-28: tras abrir la base y por lotes de entidades."""
        self.progress_and_cancel(content.GPKG_LAYER, {"main": CAPAS},
                                 settings={"layer": "puntos_z"})


class SourceUntouchedTest(_Temp):
    """RF-006-10, RF-008-14: ningún lector toca su fuente."""

    def test_reading_everything_changes_nothing(self) -> None:
        """Leer con cada lector una copia de los datos de T01 no crea, cambia ni borra nada en
        su carpeta (ni ``.aux.xml``, ni ``-wal``, ni ``-shm``)."""
        folder = self.tmp / "datos"
        shutil.copytree(DATA, folder, ignore=shutil.ignore_patterns("*.py", "*.md"))
        age_folders(folder)
        with assert_source_untouched(folder):
            for name in built.READABLE:
                _digest(content.GEOTIFF, {"main": folder / "geotiff" / name})
            _digest(content.ASC, {"main": folder / "asc" / "corner.asc",
                                  "prj": folder / "asc" / "corner.prj"})
            _digest(content.XYZ_GRID, {"main": folder / "xyz" / "grid.xyz"})
            _digest(content.POINTS_TEXT, {"main": folder / "points" / "taludes.csv"},
                    settings=POINT_SETTINGS)
            for layer in LAYERS:
                _digest(content.GPKG_LAYER, {"main": folder / "gpkg" / CAPAS.name},
                        settings={"layer": layer})


class WorkerTest(_Temp):
    """El envoltorio en proceso aparte de ``core_content_hash`` (RF-008-09; ADR-0025 §2)."""

    def test_worker_registers_gis_readers_with_the_table_reader(self) -> None:
        """RF-008-09: ``workers/core_content_hash.py`` tiene ``gis`` en su lista estática
        (también ``interop``, los de los sondeos de la 005, T39);
        ``main`` registra sus lectores y les da el lector de tablas de ``interop`` (en un
        proceso nuevo no hay nada registrado), y el texto de puntos y una capa de GeoPackage
        (copiada con ``needs_copy``) dan el hash del hilo."""
        self.assertEqual(tuple(worker.READER_PACKAGES), ("core", "gis", "interop"))
        self.assertIs(worker.READER_PACKAGES["gis"], content)
        sources = {
            "puntos": (content.POINTS_TEXT, "table", {"main": POINTS / "taludes.csv"},
                       POINT_SETTINGS),
            "capa": (content.GPKG_LAYER, "vector", {"main": CAPAS}, {"layer": "roturas_z"}),
        }
        jobs_root = self.tmp / "jobs"
        jobs_root.mkdir()
        for label, (reader, kind, files, settings) in sources.items():
            with self.subTest(fuente=label):
                expected = _digest(reader, files, settings=settings)
                request = checks.HashRequest(f"uid-{label}", label, reader.id, kind, DECL,
                                             settings, files, "gbch/1", 10**12)
                job = content_hash.new_job(request)
                folder = job_paths.job_dir(jobs_root, job.job_uid).create()
                ctx = worker_api.WorkerContext(job, folder, worker_api.QueueSink(),
                                               cancel_event=threading.Event(),
                                               paths=content_hash.job_paths(request))
                previous = content.use_table_reader(None)  # un proceso nuevo: nada enlazado
                self.addCleanup(content.use_table_reader, previous)
                with mock.patch.dict(readers._REGISTRY, clear=True):
                    summary = worker.main(ctx)
                    self.assertIs(readers.READERS[reader.id], reader)
                    self.assertIs(content.table_reader(), csv_tables.read_table)
                self.assertEqual((summary["data_sha256"], summary["content_sha256"]),
                                 (expected.data_sha256, expected.content_sha256))


if __name__ == "__main__":
    unittest.main()
