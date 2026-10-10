# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de la topografía base (spec 006, T34; RNF-006-04, RNF-006-05 y RNF-006-07; plan
006 §7.2, ``tests/rendimiento/gis``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender (su numpy 2.3.4) en el
PC de referencia de la spec 001 §5, en disco local (``%TEMP%``). Cada cifra es la mediana de
5 repeticiones (spec 006 §5), se imprime en una línea ``RNF-006-nn: …`` con el equipo y el
intérprete (``tools/check.py`` las recoge) y se compara con su presupuesto. RNF-006-01, 02 y
08 se miden con los trabajos de importación y de remuestreo completos, con la copia verificada
y el hash de la fuente y de las salidas, en ``test_perf_gis_hash.py`` (T45; plan §5.6.9), y
RNF-006-03, 06 y 09, dentro de Blender (T35).

Datos (plan §7.1: se generan aquí y no se versionan): el MDT sintético de RNF-006-01
(``tests/support/gis_perf.py``: 3.399 × 3.309 celdas de 0,5 m con unos 150 m de desnivel,
ruido de 5 cm y un hueco) con sus cotas en float32, como se importa de un GeoTIFF float32, y
su rejilla de 1 m (1.700 × 1.655 = 2,81 M celdas, media por área) en el perfil ``project``.

- RNF-006-04: el TIN sin Blender (``build_tin`` con ``PureTriangulator``: duplicados,
  restricciones, triangulación y filtros) de 20.000 puntos, 2.020 de ellos en 20 roturas
  de 100 tramos (2.000 tramos): ≤ 10 s.
- RNF-006-05: las curvas de 1 m de la rejilla de 2,81 M celdas (unos 150 m de desnivel),
  con ``contours_from_raster``: ≤ 15 s.
- RNF-006-07: exportar esa rejilla a GeoTIFF float32 (leer la del proyecto y escribir el
  entregable, el trabajo ``gis_export``): ≤ 5 s; y 50.000 polilíneas con Z de 30 vértices
  (1,5 M) a un GeoPackage con sus campos de curva (``gis.vector.write_layers``, T31: temporal
  en diario clásico, inserción por lotes, índice R*Tree y renombrado, lo que hace el trabajo
  ``gis_export`` con ``format = "gpkg"``): ≤ 15 s.
"""

import sqlite3
import statistics
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.support import gis_perf as perf
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
geotiff = import_geoblender("gis.geotiff")
georef = import_geoblender("core.georef")
gpkg = import_geoblender("core.gpkg")
gpkg_base = import_geoblender("core.gpkg.base")
vector = import_geoblender("gis.vector")

TIN_BUDGET_S = 10.0  # RNF-006-04
CONTOURS_BUDGET_S = 15.0  # RNF-006-05
EXPORT_TIFF_BUDGET_S = 5.0  # RNF-006-07
EXPORT_GPKG_BUDGET_S = 15.0  # RNF-006-07

GRID_STEP = 1.0  # la rejilla de 1,000 m de RNF-006-02
RELIEF_RANGE_M = (140.0, 160.0)  # «unos 150 m de desnivel» (RNF-006-05)
EPSG_PROJECT = 25830
EPSG_VERTICAL = 5782

TIN_POINTS = 20_000  # RNF-006-04
TIN_LINES = 20
TIN_LINE_SEGMENTS = 100  # 20 × 100 = 2.000 tramos
TIN_SIDE_M = 2000.0
TIN_CLEARANCE_M = 0.5  # los puntos sueltos, a más de esto de las roturas (como el A8)

GPKG_LINES = 50_000  # RNF-006-07
GPKG_VERTICES = 30  # 50.000 × 30 = 1,5 M de vértices
GPKG_TABLE = "gis_cnt_rendimiento"
GPKG_COLUMNS = (
    gpkg_base.ColumnDef("elevation", "DOUBLE", not_null=True),
    gpkg_base.ColumnDef("is_index", "BOOLEAN", not_null=True),
    gpkg_base.ColumnDef("closed", "BOOLEAN", not_null=True),
    gpkg_base.ColumnDef("length_m", "DOUBLE", not_null=True),
)

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(EPSG_PROJECT)
VERTICAL = CATALOG.vertical(EPSG_VERTICAL)
PROJECT = gis.WriteProfile.PROJECT
DELIVERABLE = gis.WriteProfile.DELIVERABLE
IO = geotiff.GeoTiffIO()
MACHINE = perf.MACHINE
WEST = perf.WEST
SOUTH = perf.SOUTH
SEED = perf.SEED


# --- Datos ---------------------------------------------------------------------------------


def _tin_input() -> tuple[object, list[object]]:
    """RNF-006-04: 20 roturas de 101 vértices (2.000 tramos) y 17.980 puntos sueltos al azar
    a más de 0,5 m de ellas, en 2 × 2 km: 20.000 puntos en total."""
    rng = np.random.default_rng(SEED + 4)
    lines = []
    segments = []
    for k in range(TIN_LINES):
        along = np.linspace(20.0, TIN_SIDE_M - 20.0, TIN_LINE_SEGMENTS + 1)
        across = 50.0 + 95.0 * k + 20.0 * np.sin(along / 150.0 + k)
        x, y = WEST + along, SOUTH + across
        xyz = np.column_stack((x, y, perf.surface(x, y)))
        lines.append(gis.Breakline(f"R{k + 1}", xyz, hard=True))
        segments.append((xyz[:-1, :2], xyz[1:, :2]))
    starts = np.vstack([a for a, _ in segments])
    ends = np.vstack([b for _, b in segments])
    wanted = TIN_POINTS - TIN_LINES * (TIN_LINE_SEGMENTS + 1)
    found: list[np.ndarray] = []
    total = 0
    while total < wanted:
        xy = rng.uniform(0.0, TIN_SIDE_M, (wanted, 2)) + [WEST, SOUTH]
        near = np.zeros(len(xy), bool)
        for a, b in zip(starts, ends, strict=True):
            ab = b - a
            t = np.clip(((xy - a) @ ab) / (ab @ ab), 0.0, 1.0)
            near |= np.hypot(*(xy - (a + t[:, None] * ab)).T) < TIN_CLEARANCE_M
        found.append(xy[~near])
        total += int((~near).sum())
    xy = np.vstack(found)[:wanted]
    xyz = np.column_stack((xy, perf.surface(xy[:, 0], xy[:, 1])))
    ids = tuple(f"P{i + 1}" for i in range(wanted))
    points = gis.PointSet(xyz, ids, ("",) * wanted, tuple(range(1, wanted + 1)))
    return points, lines


def _polylines() -> list[object]:
    """RNF-006-07: 50.000 polilíneas abiertas de 30 vértices (1,5 M) con Z constante, en
    2 × 2 km, como curvas de nivel."""
    rng = np.random.default_rng(SEED + 7)
    start = rng.uniform(0.0, TIN_SIDE_M, (GPKG_LINES, 1, 2)) + [WEST, SOUTH]
    steps = rng.normal(0.0, 2.0, (GPKG_LINES, GPKG_VERTICES - 1, 2))
    xy = np.concatenate((start, start + np.cumsum(steps, axis=1)), axis=1)
    levels = np.round(rng.uniform(800.0, 950.0, GPKG_LINES))
    return [
        gis.ContourLine(np.column_stack((xy[i], np.full(GPKG_VERTICES, levels[i]))),
                        float(levels[i]), bool(levels[i] % 5 == 0), False)
        for i in range(GPKG_LINES)
    ]


class _Data:
    """Lo que comparten las pruebas, creado una vez en :func:`setUpModule`."""

    folder: Path
    grid_raster: object  # la rejilla de 1 m (Raster)
    grid_file: Path  # la rejilla de 1 m en el perfil project


_DATA = _Data()
_TEMP: tempfile.TemporaryDirectory | None = None


def setUpModule() -> None:
    """Los datos de todas las pruebas, en una carpeta temporal que se borra al final."""
    global _TEMP
    _TEMP = tempfile.TemporaryDirectory(prefix="gb-gis-perf-")
    folder = Path(_TEMP.name)
    _DATA.folder = folder
    grid = perf.mdt_grid()
    # Las cotas como se importan de un GeoTIFF float32 (el sin dato, NaN).
    imported = perf.mdt_values().astype(np.float32).astype(np.float64)
    source = gis.Raster(grid, imported, CRS, VERTICAL)
    target = gis.aligned_grid(grid.extent, GRID_STEP)
    _DATA.grid_raster, _ = gis.resample_to_grid(
        source, target, method=gis.choose_method(grid, target))
    _DATA.grid_file = folder / "gis_dtm_1m.tif"
    IO.write(_DATA.grid_raster, _DATA.grid_file, profile=PROJECT)


def tearDownModule() -> None:
    global _TEMP
    if _TEMP is not None:
        _TEMP.cleanup()
        _TEMP = None


def _same(test: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    """Las mismas cotas bit a bit (NaN donde no hay dato)."""
    test.assertEqual(got.shape, expected.shape)
    test.assertTrue(np.array_equal(got, expected, equal_nan=True))


def _source(path: Path) -> object:
    read = IO.read(path)
    return gis.Raster(read.grid, read.values, read.declared_crs, read.declared_vertical)


# --- TIN sin Blender (RNF-006-04) ----------------------------------------------------------


class PureTinTest(unittest.TestCase):
    """RNF-006-04: el TIN de 20.000 puntos y 2.000 tramos con el triangulador propio."""

    def test_pure_tin(self) -> None:
        """RNF-006-04: ``build_tin`` con ``PureTriangulator`` (sin Blender) de 20.000
        puntos, 2.020 de ellos en 20 roturas duras de 100 tramos (2.000 tramos), en ≤ 10 s
        (mediana de 5); todas las roturas quedan como aristas del TIN."""
        points, lines = _tin_input()
        origin = georef.GeoOrigin(700_000, 4_400_000)
        times, (tin, report) = perf.measure(lambda: gis.build_tin(
            points, lines, triangulator=gis.PureTriangulator(), origin=origin,
            name="Rendimiento"))
        perf.report(f"RNF-006-04: TIN sin Blender (build_tin con PureTriangulator) de "
                    f"{perf.count(len(points) + sum(len(line.xyz) for line in lines))} puntos "
                    f"y {perf.count(TIN_LINES * TIN_LINE_SEGMENTS)} tramos de rotura "
                    f"({perf.count(len(tin.faces))} triángulos; {MACHINE}): "
                    f"{perf.median_line(times)}, presupuesto {perf.number(TIN_BUDGET_S, 0)} s")
        self.assertEqual(len(points) + sum(len(line.xyz) for line in lines), TIN_POINTS)
        self.assertEqual(len(tin.vertices), TIN_POINTS)
        self.assertEqual(len(tin.constraint_edges), TIN_LINES * TIN_LINE_SEGMENTS)
        self.assertLessEqual(statistics.median(times), TIN_BUDGET_S)


# --- Curvas (RNF-006-05) -------------------------------------------------------------------


class ContoursTest(unittest.TestCase):
    """RNF-006-05: las curvas de 1 m de la rejilla de 2,81 M celdas."""

    def test_contours(self) -> None:
        """RNF-006-05: las curvas de 1 m de la rejilla de 1.700 × 1.655 celdas con unos
        150 m de desnivel (``contours_from_raster``) en ≤ 15 s (mediana de 5)."""
        raster = _DATA.grid_raster
        relief = float(np.nanmax(raster.values) - np.nanmin(raster.values))
        times, lines = perf.measure(lambda: gis.contours_from_raster(raster, interval_m=1.0,
                                                                     name="Rendimiento"))
        vertices = sum(len(line.xyz) for line in lines)
        perf.report(f"RNF-006-05: curvas de 1 m de una rejilla de "
                    f"{perf.count(raster.grid.ncols * raster.grid.nrows)} celdas con "
                    f"{perf.number(relief, 1)} m de desnivel ({perf.count(len(lines))} curvas, "
                    f"{perf.count(vertices)} vértices; {MACHINE}): {perf.median_line(times)}, "
                    f"presupuesto {perf.number(CONTOURS_BUDGET_S, 0)} s")
        self.assertGreaterEqual(relief, RELIEF_RANGE_M[0])
        self.assertLessEqual(relief, RELIEF_RANGE_M[1])
        levels = {line.elevation for line in lines}
        self.assertGreaterEqual(len(levels), int(RELIEF_RANGE_M[0]) - 2)
        self.assertLessEqual(statistics.median(times), CONTOURS_BUDGET_S)


# --- Exportar (RNF-006-07) -----------------------------------------------------------------


def _export_tiff(source: Path, target: Path) -> object:
    """Exportar la rejilla del proyecto a un GeoTIFF float32, como el worker ``gis_export``."""
    raster = _source(source)
    IO.write(raster, target, profile=DELIVERABLE)
    return raster


def _export_gpkg(lines: list[object], target: Path) -> int:
    """Las polilíneas en una capa ``LINESTRING`` con Z de un GeoPackage nuevo con
    ``gis.vector.write_layers`` (T31), con sus campos de curva. Devuelve las filas escritas."""
    layer = vector.LayerToWrite(
        GPKG_TABLE, "LINESTRING", True, [line.xyz for line in lines], GPKG_COLUMNS,
        {"elevation": [line.elevation for line in lines],
         "is_index": [int(line.is_index) for line in lines],
         "closed": [int(line.closed) for line in lines],
         "length_m": [line.length_m for line in lines]},
        identifier="Curvas de rendimiento")
    vector.write_layers(target, [layer], CRS, VERTICAL)
    return len(layer.geometries)


class ExportTest(unittest.TestCase):
    """RNF-006-07: exportar la rejilla a GeoTIFF y 50.000 polilíneas a GeoPackage."""

    def test_export_geotiff(self) -> None:
        """RNF-006-07: la rejilla de 2,81 M celdas a GeoTIFF float32 (leer la del proyecto
        y escribir el entregable) en ≤ 5 s (mediana de 5)."""
        target = _DATA.folder / "export_1m.tif"
        times, raster = perf.measure(lambda: _export_tiff(_DATA.grid_file, target))
        perf.report(f"RNF-006-07: exportar a GeoTIFF float32 una rejilla de "
                    f"{perf.count(raster.grid.ncols * raster.grid.nrows)} celdas (leer la del "
                    f"proyecto y escribir el entregable; {MACHINE}): {perf.median_line(times)}, "
                    f"presupuesto {perf.number(EXPORT_TIFF_BUDGET_S, 0)} s")
        written = IO.read(target)
        self.assertEqual(written.source_dtype, "float32")
        self.assertTrue(np.array_equal(
            written.values, _DATA.grid_raster.values.astype(np.float32).astype(np.float64),
            equal_nan=True))
        self.assertLessEqual(statistics.median(times), EXPORT_TIFF_BUDGET_S)

    def test_export_gpkg(self) -> None:
        """RNF-006-07: 50.000 polilíneas con Z y 1,5 M de vértices a un GeoPackage (con
        elevación, maestra, cerrada y longitud) en ≤ 15 s (mediana de 5); las geometrías se
        leen igual."""
        lines = _polylines()
        target = _DATA.folder / "export_curvas.gpkg"
        times, written = perf.measure(lambda: _export_gpkg(lines, target))
        vertices = sum(len(line.xyz) for line in lines)
        perf.report(f"RNF-006-07: exportar a GeoPackage {perf.count(len(lines))} polilíneas "
                    f"con {perf.count(vertices)} vértices (gis.vector.write_layers con su "
                    f"índice R*Tree; {MACHINE}): {perf.median_line(times)}, presupuesto "
                    f"{perf.number(EXPORT_GPKG_BUDGET_S, 0)} s")
        self.assertEqual(written, GPKG_LINES)
        self.assertEqual(vertices, GPKG_LINES * GPKG_VERTICES)
        with sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True) as conn:
            count = conn.execute(f'SELECT COUNT(*) FROM "{GPKG_TABLE}"').fetchone()[0]
            z = conn.execute("SELECT z FROM gpkg_geometry_columns WHERE table_name = ?",
                             (GPKG_TABLE,)).fetchone()[0]
            last = conn.execute(f'SELECT geom FROM "{GPKG_TABLE}" ORDER BY fid DESC '
                                "LIMIT 1").fetchone()[0]
        conn.close()
        self.assertEqual((count, z), (GPKG_LINES, 1))
        _same(self, gpkg.decode_geometry(last).coords, lines[-1].xyz)
        self.assertLessEqual(statistics.median(times), EXPORT_GPKG_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
