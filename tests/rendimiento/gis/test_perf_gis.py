# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de la topografía base (spec 006, T34; RNF-006-01, RNF-006-02, RNF-006-04,
RNF-006-05, RNF-006-07 y RNF-006-08; plan 006 §7.2, ``tests/rendimiento/gis``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender (su numpy 2.3.4) en el
PC de referencia de la spec 001 §5, en disco local (``%TEMP%``). Cada cifra es la mediana de
5 repeticiones (spec 006 §5), se imprime en una línea ``RNF-006-nn: …`` con el equipo y el
intérprete (``tools/check.py`` las recoge) y se compara con su presupuesto. Los RNF-006-03,
06 y 09 se miden dentro de Blender (T35).

Datos (plan §7.1: se generan aquí y no se versionan): un MDT sintético de 3.399 × 3.309
celdas de 0,5 m (11,2 M), oeste 700.000 y sur 4.400.000, con unos 150 m de desnivel
(colinas de cientos de metros, una pendiente general, un ondulado de metros y ruido de
5 cm, como el de un LiDAR) y un hueco sin dato de 100 × 80 celdas. Se escribe en GeoTIFF
float32 de teselas de 256: en DEFLATE con predictor 3 (el escritor de Geoblender, perfil
``deliverable``) y en LZW sin predictor (las mismas teselas con el codificador LZW de esta
prueba, con las reglas del de libtiff: 39 MB de 45, casi sin comprimir, el LZW más lento de
leer; GDAL 3.13 lo lee igual que el DEFLATE), y como fuente ya importada (perfil ``project``,
float64) en EPSG:25830 y en EPSG:23030 (ED50).

- RNF-006-01: importar el MDT = leer el GeoTIFF (``GeoTiffIO.read``) y escribir el del
  proyecto (``GeoTiffIO.write``, perfil ``project``), el trabajo del worker
  ``gis_read_raster`` (T26; sin la copia de la entrada a ``in/``): ≤ 10 s con DEFLATE y
  ≤ 40 s con LZW.
- RNF-006-08: el pico de memoria adicional de esa importación, con ``tracemalloc`` (también
  la de numpy), en una ejecución aparte de cada compresión (sin cronometrar): ≤ 1,5 GB
  (1,5 × 10⁹ bytes).
- RNF-006-02: la rejilla de 1,000 m (1.700 × 1.655 = 2,81 M celdas) desde la fuente de
  0,5 m importada (leerla, ``resample_to_grid`` con la media por área y escribirla, el
  trabajo ``gis_resample``): ≤ 10 s; desde ED50 (crear el servicio de pyproj y comprobar su
  catálogo, como un worker nuevo, la transformación con ``es_ign_SPED2ETV2`` y su inversa, y
  ``reproject_to_grid`` con 4 × 4 subcentros: 45 M de puntos): ≤ 60 s.
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

import gc
import os
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
import tracemalloc
import unittest
from collections.abc import Callable
from pathlib import Path

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
crs_mod = import_geoblender("gis.crs")
geotiff = import_geoblender("gis.geotiff")
codecs = import_geoblender("gis.geotiff.codecs")
tiff = import_geoblender("gis.geotiff.tiff")
georef = import_geoblender("core.georef")
gpkg = import_geoblender("core.gpkg")
gpkg_base = import_geoblender("core.gpkg.base")
vector = import_geoblender("gis.vector")
pyproj_crs = import_geoblender("adapters.pyproj_crs")

REPETITIONS = 5  # spec 006 §5: 5 repeticiones, mediana

IMPORT_DEFLATE_BUDGET_S = 10.0  # RNF-006-01
IMPORT_LZW_BUDGET_S = 40.0  # RNF-006-01
MEMORY_BUDGET_BYTES = 1_500_000_000  # RNF-006-08: 1,5 GB
GRID_BUDGET_S = 10.0  # RNF-006-02
GRID_ED50_BUDGET_S = 60.0  # RNF-006-02
TIN_BUDGET_S = 10.0  # RNF-006-04
CONTOURS_BUDGET_S = 15.0  # RNF-006-05
EXPORT_TIFF_BUDGET_S = 5.0  # RNF-006-07
EXPORT_GPKG_BUDGET_S = 15.0  # RNF-006-07

# El MDT de RNF-006-01 (spec 006 §5): 3.399 × 3.309 celdas de 0,5 m.
MDT_COLS = 3399
MDT_ROWS = 3309
MDT_STEP = 0.5
WEST = 700_000.0
SOUTH = 4_400_000.0
NORTH = SOUTH + MDT_ROWS * MDT_STEP
HOLE = (slice(1500, 1580), slice(2000, 2100))  # filas y columnas (desde el NO) sin dato
NOISE_M = 0.05
SEED = 20_261_008
GRID_STEP = 1.0  # RNF-006-02: la rejilla de 1,000 m
GRID_CELLS = 1700 * 1655
RELIEF_RANGE_M = (140.0, 160.0)  # «unos 150 m de desnivel» (RNF-006-05)
EPSG_PROJECT = 25830
EPSG_ED50 = 23030
EPSG_VERTICAL = 5782
TILE = 256

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
CRS_ED50 = CATALOG.horizontal(EPSG_ED50)
VERTICAL = CATALOG.vertical(EPSG_VERTICAL)
PROJECT = gis.WriteProfile.PROJECT
DELIVERABLE = gis.WriteProfile.DELIVERABLE
IO = geotiff.GeoTiffIO()


# --- Equipo, intérprete y texto de las cifras ---------------------------------------------


def _processor() -> str:
    """El nombre del procesador (en Windows, el del registro) y sus hilos."""
    name = ""
    try:
        import winreg

        key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            name = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (ImportError, OSError):
        name = platform.processor()
    return f"{name or 'procesador desconocido'}, {os.cpu_count()} hilos"


def _machine() -> str:
    """Equipo e intérprete, para las líneas de cifra."""
    python = "Python de Blender" if "blender" in sys.executable.lower() else "Python"
    return f"{_processor()}; {python} {platform.python_version()}, numpy {np.__version__}"


MACHINE = _machine()


def _number(value: float, digits: int = 3) -> str:
    """Número con coma decimal (salida en español)."""
    return f"{value:.{digits}f}".replace(".", ",")


def _count(value: int) -> str:
    """Entero con punto de millares (salida en español)."""
    return f"{value:,}".replace(",", ".")


def _median_line(times: list[float]) -> str:
    """«mediana X s de N (mín. A, máx. B)»."""
    return (f"mediana {_number(statistics.median(times))} s de {len(times)} "
            f"(mín. {_number(min(times))}, máx. {_number(max(times))})")


def _report(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _measure[T](action: Callable[[], T]) -> tuple[list[float], T]:
    """:data:`REPETITIONS` ejecuciones seguidas de ``action`` (con la basura recogida antes
    de cada una): sus duraciones y el resultado de la última."""
    times: list[float] = []
    result: T | None = None
    for _ in range(REPETITIONS):
        result = None
        gc.collect()
        start = time.perf_counter()
        result = action()
        times.append(time.perf_counter() - start)
    assert result is not None
    return times, result


def _peak_bytes(action: Callable[[], object]) -> int:
    """El pico de memoria que reserva ``action`` (``tracemalloc``, con la de numpy)."""
    gc.collect()
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        action()
        return tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()


# --- Datos ---------------------------------------------------------------------------------


def _surface(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Cota (m) en (x, y) absolutas: colinas, pendiente general y un ondulado de metros."""
    east = x - WEST
    up = y - SOUTH
    return (850.0 + 60.0 * np.sin(east / 150.0) * np.cos(up / 120.0) + 0.02 * east
            + 2.0 * np.sin(east / 7.3) * np.sin(up / 5.1))


def _mdt_values() -> np.ndarray:
    """Las cotas del MDT de 0,5 m (float64, de norte a sur), con ruido y el hueco."""
    grid = gis.Grid(WEST, NORTH, MDT_STEP, MDT_STEP, MDT_COLS, MDT_ROWS)
    x, y = grid.centers()
    values = _surface(x, y) + np.random.default_rng(SEED).normal(0.0, NOISE_M, grid.shape)
    values[HOLE] = np.nan
    return values


_CLEAR, _EOI, _FIRST, _FULL = 256, 257, 258, 4094


def _lzw_encode(data: bytes) -> bytes:
    """LZW de TIFF con las reglas del codificador de libtiff (como ``_lzw_encode`` de
    ``tests/unit/gis/test_geotiff_codecs.py``, pero con la tabla en un diccionario de
    enteros, lo bastante rápido para 45 MB): CLEAR al empezar, una entrada por código
    emitido, CLEAR cuando la tabla llega a 4094 y EOI al final."""
    codes: list[int] = [_CLEAR]
    emit = codes.append
    table: dict[int, int] = {}
    find = table.get
    free = _FIRST
    stream = iter(data)
    current = next(stream, None)
    if current is not None:
        for byte in stream:
            key = (current << 8) | byte
            found = find(key)
            if found is not None:
                current = found
                continue
            emit(current)
            table[key] = free
            free += 1
            current = byte
            if free == _FULL:
                emit(_CLEAR)
                table.clear()
                free = _FIRST
        emit(current)
        if free + 1 == _FULL:
            emit(_CLEAR)
    emit(_EOI)
    return _pack_codes(np.asarray(codes, np.int64))


def _pack_codes(codes: np.ndarray) -> bytes:
    """Los códigos con su ancho (bit más significativo primero): el k-ésimo tras un CLEAR
    va con 9 bits mientras 258 + k ≤ 511, 10 hasta 1023, 11 hasta 2047 y luego 12; un CLEAR
    que vacía la tabla, con 12, y el del principio, con 9."""
    index = np.arange(codes.size)
    clear = codes == _CLEAR
    last = np.maximum.accumulate(np.where(clear, index, 0))
    free = _FIRST + index - last - 1
    widths = 9 + (free > 511).astype(np.int64) + (free > 1023) + (free > 2047)
    widths[clear] = 12
    widths[0] = 9
    shifts = widths[:, None] - 1 - np.arange(12)[None, :]
    bits = ((codes[:, None] >> np.maximum(shifts, 0)) & 1).astype(np.uint8)
    return np.packbits(bits[shifts >= 0]).tobytes()


def _lzw_copy(source: Path, target: Path) -> None:
    """``target``: el GeoTIFF float32 DEFLATE + predictor 3 ``source`` con sus mismas
    teselas en LZW sin predictor (el LZW más lento de leer: casi no comprime unas cotas
    float32 con ruido)."""
    with source.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        ifd = tiff.read_first_ifd(stream, size)
        blocks: list[bytes] = []
        for offset, count in zip(ifd.numbers(tiff.TILE_OFFSETS),
                                 ifd.numbers(tiff.TILE_BYTE_COUNTS), strict=True):
            stream.seek(offset)
            tile = codecs.decode_block(
                stream.read(count), compression=codecs.COMPRESSION_DEFLATE,
                predictor=codecs.PREDICTOR_FLOATING_POINT, dtype="<f4", width=TILE,
                rows=TILE)
            blocks.append(_lzw_encode(tile.tobytes()))
    offsets: list[int] = []
    position = tiff.HEADER_SIZE
    for block in blocks:
        offsets.append(position)
        position += len(block)
    ifd_offset = position + position % 2
    replaced = {
        tiff.COMPRESSION: (tiff.SHORT, [codecs.COMPRESSION_LZW]),
        tiff.PREDICTOR: (tiff.SHORT, [codecs.PREDICTOR_NONE]),
        tiff.TILE_OFFSETS: (tiff.LONG, offsets),
        tiff.TILE_BYTE_COUNTS: (tiff.LONG, [len(block) for block in blocks]),
    }
    entries = []
    for tag, value in ifd.tags.items():
        if tag in replaced:
            entries.append((tag, *replaced[tag]))
        elif isinstance(value, str):
            entries.append((tag, tiff.ASCII, value))
        elif all(isinstance(item, int) for item in value):
            kind = tiff.SHORT if max(value) < 2**16 else tiff.LONG
            entries.append((tag, kind, list(value)))
        else:
            entries.append((tag, tiff.DOUBLE, [float(item) for item in value]))
    with target.open("wb") as stream:
        stream.write(tiff.encode_header(ifd_offset, bigtiff=False))
        for block in blocks:
            stream.write(block)
        stream.write(bytes(ifd_offset - position))
        stream.write(tiff.encode_ifd(entries, ifd_offset, bigtiff=False))


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
        xyz = np.column_stack((x, y, _surface(x, y)))
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
    xyz = np.column_stack((xy, _surface(xy[:, 0], xy[:, 1])))
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
    values: np.ndarray  # el MDT de 0,5 m en float64
    deflate: Path  # GeoTIFF float32 DEFLATE + predictor 3
    lzw: Path  # las mismas teselas en LZW sin predictor
    source: Path  # la fuente importada (perfil project) en EPSG:25830
    source_ed50: Path  # la misma, declarada en ED50
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
    values = _mdt_values()
    _DATA.values = values
    grid = gis.Grid(WEST, NORTH, MDT_STEP, MDT_STEP, MDT_COLS, MDT_ROWS)
    mdt = gis.Raster(grid, values, CRS, VERTICAL)
    _DATA.deflate = folder / "mdt_deflate.tif"
    IO.write(mdt, _DATA.deflate, profile=DELIVERABLE)
    _DATA.lzw = folder / "mdt_lzw.tif"
    _lzw_copy(_DATA.deflate, _DATA.lzw)
    imported = IO.read(_DATA.deflate)
    source = gis.Raster(imported.grid, imported.values, CRS, VERTICAL)
    _DATA.source = folder / "gis_src_25830.tif"
    IO.write(source, _DATA.source, profile=PROJECT)
    _DATA.source_ed50 = folder / "gis_src_23030.tif"
    IO.write(gis.Raster(imported.grid, imported.values, CRS_ED50, VERTICAL),
             _DATA.source_ed50, profile=PROJECT)
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


# --- Importar (RNF-006-01 y RNF-006-08) ---------------------------------------------------


def _import(source: Path, target: Path) -> object:
    """Importar un MDT: leerlo y escribir el GeoTIFF del proyecto (perfil ``project``),
    como el worker ``gis_read_raster``."""
    read = IO.read(source)
    raster = gis.Raster(read.grid, read.values, read.declared_crs, read.declared_vertical)
    IO.write(raster, target, profile=PROJECT)
    return raster


class ImportTest(unittest.TestCase):
    """RNF-006-01 y RNF-006-08: importar el MDT de 11,2 M celdas."""

    def check_import(self, source: Path, label: str, budget: float) -> object:
        target = _DATA.folder / f"import_{source.stem}.tif"
        times, raster = _measure(lambda: _import(source, target))
        _report(f"RNF-006-01: importar un MDT GeoTIFF float32 de {_count(MDT_COLS)} × "
                f"{_count(MDT_ROWS)} celdas (11,2 M; {_number(source.stat().st_size / 1e6, 1)}"
                f" MB) con {label} (leer y escribir el del proyecto; {MACHINE}): "
                f"{_median_line(times)}, presupuesto {_number(budget, 0)} s")
        self.assertEqual(raster.grid.shape, (MDT_ROWS, MDT_COLS))
        self.assertTrue(np.array_equal(raster.values,
                                       _DATA.values.astype(np.float32).astype(np.float64),
                                       equal_nan=True))
        self.assertTrue(target.is_file())
        self.assertLessEqual(statistics.median(times), budget)
        return raster

    def test_import_deflate(self) -> None:
        """RNF-006-01: el MDT de 3.399 × 3.309 celdas float32 en DEFLATE + predictor 3 se
        importa (leer y escribir el GeoTIFF del proyecto) en ≤ 10 s (mediana de 5), con las
        cotas float32 del fichero."""
        self.check_import(_DATA.deflate, "DEFLATE + predictor 3", IMPORT_DEFLATE_BUDGET_S)

    def test_import_lzw(self) -> None:
        """RNF-006-01: el mismo MDT en LZW sin predictor (el LZW más lento) se importa en
        ≤ 40 s (mediana de 5), con las mismas cotas que el DEFLATE (el LZW de la prueba es
        válido)."""
        self.check_import(_DATA.lzw, "LZW sin predictor", IMPORT_LZW_BUDGET_S)

    def test_import_memory(self) -> None:
        """RNF-006-08: el pico de memoria adicional al importar el MDT de RNF-006-01
        (``tracemalloc``, con la memoria de numpy) es ≤ 1,5 GB, con DEFLATE y con LZW."""
        for source, label in ((_DATA.deflate, "DEFLATE"), (_DATA.lzw, "LZW")):
            with self.subTest(compresion=label):
                target = _DATA.folder / f"memory_{source.stem}.tif"
                peak = _peak_bytes(lambda source=source, target=target: _import(source,
                                                                                 target))
                _report(f"RNF-006-08: pico de memoria adicional al importar el MDT de "
                        f"RNF-006-01 con {label} (tracemalloc; {MACHINE}): "
                        f"{_number(peak / 1e9, 2)} GB, presupuesto 1,5 GB")
                self.assertGreater(peak, MDT_COLS * MDT_ROWS * 8)  # al menos el ráster
                self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


# --- Rejilla del proyecto (RNF-006-02) -----------------------------------------------------


def _source(path: Path) -> object:
    read = IO.read(path)
    return gis.Raster(read.grid, read.values, read.declared_crs, read.declared_vertical)


def _project_grid(source: Path, target: Path) -> object:
    """La rejilla de 1 m desde la fuente importada, como el worker ``gis_resample``."""
    src = _source(source)
    grid = gis.aligned_grid(src.grid.extent, GRID_STEP)
    out, _ = gis.resample_to_grid(src, grid, method=gis.choose_method(src.grid, grid))
    IO.write(out, target, profile=PROJECT)
    return out


def _extent_in(transform: object, grid: object) -> object:
    """La extensión de ``grid`` transformada (sus cuatro esquinas)."""
    box = grid.extent
    corners = np.array([[box.xmin, box.ymin, 0.0], [box.xmin, box.ymax, 0.0],
                        [box.xmax, box.ymin, 0.0], [box.xmax, box.ymax, 0.0]])
    moved = transform.apply(corners)
    return georef.Window(float(moved[:, 0].min()), float(moved[:, 1].min()),
                         float(moved[:, 0].max()), float(moved[:, 1].max()))


def _project_grid_ed50(source: Path, target: Path) -> tuple[object, object]:
    """La rejilla de 1 m en EPSG:25830 desde la fuente en ED50, como el worker
    ``gis_resample`` en su subproceso: crea el servicio de pyproj y comprueba su catálogo,
    pide la transformación (con la rejilla del IGN) y su inversa y reproyecta."""
    pyproj_crs.check_version()
    service = pyproj_crs.PyprojCrsService()
    service.check_catalog()
    src = _source(source)
    declaration = crs_mod.Declaration(source.name, src.crs, src.vertical)
    transform = crs_mod.transformation_for(declaration, CRS, VERTICAL, service=service)
    inverse = service.transformer(CRS, VERTICAL, src.crs, src.vertical)
    grid = gis.aligned_grid(_extent_in(transform, src.grid), GRID_STEP)
    out, report = gis.reproject_to_grid(
        src, grid, transform=transform, inverse=inverse, target_crs=CRS,
        target_vertical=VERTICAL, method=gis.choose_method(src.grid, grid), name=source.name)
    IO.write(out, target, profile=PROJECT)
    return out, report


class ProjectGridTest(unittest.TestCase):
    """RNF-006-02: la rejilla de 1,000 m (2,81 M celdas) desde el MDT de 0,5 m."""

    def test_grid_from_source(self) -> None:
        """RNF-006-02: desde la fuente de 0,5 m importada (EPSG:25830), la rejilla de 1 m
        de 1.700 × 1.655 celdas con la media por área se hace (leer, remuestrear y
        escribir) en ≤ 10 s (mediana de 5)."""
        target = _DATA.folder / "grid_1m.tif"
        times, out = _measure(lambda: _project_grid(_DATA.source, target))
        _report(f"RNF-006-02: rejilla de 1,000 m ({_count(out.grid.ncols)} × "
                f"{_count(out.grid.nrows)} = {_count(out.grid.ncols * out.grid.nrows)} celdas)"
                f" desde el MDT de 0,5 m importado, media por área (leer, remuestrear y "
                f"escribir; {MACHINE}): {_median_line(times)}, presupuesto "
                f"{_number(GRID_BUDGET_S, 0)} s")
        self.assertEqual(out.grid.ncols * out.grid.nrows, GRID_CELLS)
        self.assertTrue(np.array_equal(out.values, _DATA.grid_raster.values, equal_nan=True))
        self.assertLessEqual(statistics.median(times), GRID_BUDGET_S)

    def test_grid_from_ed50(self) -> None:
        """RNF-006-02: desde la fuente de 0,5 m declarada en ED50 (EPSG:23030), la rejilla
        de 1 m en EPSG:25830 con la transformación del IGN (``es_ign_SPED2ETV2``, 0,2 m) y
        4 × 4 subcentros por celda se hace en ≤ 60 s (mediana de 5)."""
        target = _DATA.folder / "grid_1m_ed50.tif"
        times, (out, report) = _measure(lambda: _project_grid_ed50(_DATA.source_ed50,
                                                                   target))
        cells = out.grid.ncols * out.grid.nrows
        _report(f"RNF-006-02: rejilla de 1,000 m desde ED50 ({_count(out.grid.ncols)} × "
                f"{_count(out.grid.nrows)} = {_count(cells)} celdas, "
                f"{report.supersample} × {report.supersample} subcentros: "
                f"{_count(cells * report.supersample ** 2)} puntos; "
                f"{crs_mod.transform_summary(report.transform)}; {MACHINE}): "
                f"{_median_line(times)}, presupuesto {_number(GRID_ED50_BUDGET_S, 0)} s")
        self.assertIn("es_ign_SPED2ETV2.tif", report.transform.grids)
        self.assertGreater(report.valid_cells, 0.95 * GRID_CELLS)
        self.assertLessEqual(statistics.median(times), GRID_ED50_BUDGET_S)


# --- TIN sin Blender (RNF-006-04) ----------------------------------------------------------


class PureTinTest(unittest.TestCase):
    """RNF-006-04: el TIN de 20.000 puntos y 2.000 tramos con el triangulador propio."""

    def test_pure_tin(self) -> None:
        """RNF-006-04: ``build_tin`` con ``PureTriangulator`` (sin Blender) de 20.000
        puntos, 2.020 de ellos en 20 roturas duras de 100 tramos (2.000 tramos), en ≤ 10 s
        (mediana de 5); todas las roturas quedan como aristas del TIN."""
        points, lines = _tin_input()
        origin = georef.GeoOrigin(700_000, 4_400_000)
        times, (tin, report) = _measure(lambda: gis.build_tin(
            points, lines, triangulator=gis.PureTriangulator(), origin=origin,
            name="Rendimiento"))
        _report(f"RNF-006-04: TIN sin Blender (build_tin con PureTriangulator) de "
                f"{_count(len(points) + sum(len(line.xyz) for line in lines))} puntos y "
                f"{_count(TIN_LINES * TIN_LINE_SEGMENTS)} tramos de rotura "
                f"({_count(len(tin.faces))} triángulos; {MACHINE}): {_median_line(times)}, "
                f"presupuesto {_number(TIN_BUDGET_S, 0)} s")
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
        times, lines = _measure(lambda: gis.contours_from_raster(raster, interval_m=1.0,
                                                                 name="Rendimiento"))
        vertices = sum(len(line.xyz) for line in lines)
        _report(f"RNF-006-05: curvas de 1 m de una rejilla de "
                f"{_count(raster.grid.ncols * raster.grid.nrows)} celdas con "
                f"{_number(relief, 1)} m de desnivel ({_count(len(lines))} curvas, "
                f"{_count(vertices)} vértices; {MACHINE}): {_median_line(times)}, "
                f"presupuesto {_number(CONTOURS_BUDGET_S, 0)} s")
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
        times, raster = _measure(lambda: _export_tiff(_DATA.grid_file, target))
        _report(f"RNF-006-07: exportar a GeoTIFF float32 una rejilla de "
                f"{_count(raster.grid.ncols * raster.grid.nrows)} celdas (leer la del "
                f"proyecto y escribir el entregable; {MACHINE}): {_median_line(times)}, "
                f"presupuesto {_number(EXPORT_TIFF_BUDGET_S, 0)} s")
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
        times, written = _measure(lambda: _export_gpkg(lines, target))
        vertices = sum(len(line.xyz) for line in lines)
        _report(f"RNF-006-07: exportar a GeoPackage {_count(len(lines))} polilíneas con "
                f"{_count(vertices)} vértices (gis.vector.write_layers con su índice R*Tree; "
                f"{MACHINE}): {_median_line(times)}, presupuesto "
                f"{_number(EXPORT_GPKG_BUDGET_S, 0)} s")
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
