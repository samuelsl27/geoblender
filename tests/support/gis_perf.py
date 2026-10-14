# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo común de las pruebas de rendimiento de la topografía base (spec 006, T34 y T45;
``tests/rendimiento/gis``): el equipo y el intérprete de cada cifra, su texto en español, las
5 repeticiones con su mediana, el pico de memoria con ``tracemalloc``, el MDT sintético de
RNF-006-01 y su copia en LZW.

**El MDT de RNF-006-01** (spec 006 §5; plan §7.1: se genera y no se versiona):
:data:`MDT_COLS` × :data:`MDT_ROWS` celdas de :data:`MDT_STEP` m (11,2 M), oeste
:data:`WEST` y sur :data:`SOUTH`, con unos 150 m de desnivel (colinas de cientos de metros,
una pendiente general, un ondulado de metros y ruido de :data:`NOISE_M` m, como el de un
LiDAR) y un hueco sin dato de 100 × 80 celdas (:data:`HOLE`): :func:`mdt_values`.
:func:`lzw_copy` reescribe un GeoTIFF float32 DEFLATE + predictor 3 con sus mismas teselas en
LZW sin predictor (con las reglas del codificador de libtiff; GDAL 3.13 lo lee igual que el
DEFLATE), el LZW más lento de leer.

Python de Blender (su numpy 2.3.4) y biblioteca estándar.
"""

from __future__ import annotations

import gc
import os
import platform
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
codecs = import_geoblender("gis.geotiff.codecs")
tiff = import_geoblender("gis.geotiff.tiff")
georef = import_geoblender("core.georef")

REPETITIONS = 5  # spec 006 §5: 5 repeticiones, mediana

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
TILE = 256  # lado de las teselas del escritor de Geoblender (gis.geotiff.writer.TILE_SIZE)


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
"""El equipo y el intérprete de las cifras («…, 24 hilos; Python de Blender 3.13.13, numpy
2.3.4»)."""


def number(value: float, digits: int = 3) -> str:
    """Número con coma decimal (salida en español)."""
    return f"{value:.{digits}f}".replace(".", ",")


def count(value: int) -> str:
    """Entero con punto de millares (salida en español)."""
    return f"{value:,}".replace(",", ".")


def median_line(times: list[float]) -> str:
    """«mediana X s de N (mín. A, máx. B)»."""
    return (f"mediana {number(statistics.median(times))} s de {len(times)} "
            f"(mín. {number(min(times))}, máx. {number(max(times))})")


def report(text: str) -> None:
    """Imprime una línea de cifra (``tools/check.py`` las recoge)."""
    print(text, file=sys.stderr, flush=True)


def measure[T](action: Callable[[], T]) -> tuple[list[float], T]:
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


def peak_bytes(action: Callable[[], object]) -> int:
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


# --- El MDT de RNF-006-01 --------------------------------------------------------------------


def surface(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Cota (m) en (x, y) absolutas: colinas, pendiente general y un ondulado de metros."""
    east = x - WEST
    up = y - SOUTH
    return (850.0 + 60.0 * np.sin(east / 150.0) * np.cos(up / 120.0) + 0.02 * east
            + 2.0 * np.sin(east / 7.3) * np.sin(up / 5.1))


def mdt_grid() -> Any:
    """La rejilla del MDT de RNF-006-01."""
    return gis.Grid(WEST, NORTH, MDT_STEP, MDT_STEP, MDT_COLS, MDT_ROWS)


def mdt_values() -> np.ndarray:
    """Las cotas del MDT de 0,5 m (float64, de norte a sur), con ruido y el hueco."""
    grid = mdt_grid()
    x, y = grid.centers()
    values = surface(x, y) + np.random.default_rng(SEED).normal(0.0, NOISE_M, grid.shape)
    values[HOLE] = np.nan
    return values


def extent_in(transform: Any, grid: Any) -> Any:
    """La extensión de ``grid`` transformada con ``transform`` (sus cuatro esquinas)."""
    box = grid.extent
    corners = np.array([[box.xmin, box.ymin, 0.0], [box.xmin, box.ymax, 0.0],
                        [box.xmax, box.ymin, 0.0], [box.xmax, box.ymax, 0.0]])
    moved = transform.apply(corners)
    return georef.Window(float(moved[:, 0].min()), float(moved[:, 1].min()),
                         float(moved[:, 0].max()), float(moved[:, 1].max()))


# --- LZW de TIFF ----------------------------------------------------------------------------

_CLEAR, _EOI, _FIRST, _FULL = 256, 257, 258, 4094


def lzw_encode(data: bytes) -> bytes:
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


def lzw_copy(source: Path, target: Path) -> None:
    """``target``: el GeoTIFF float32 DEFLATE + predictor 3 ``source`` con sus mismas
    teselas en LZW sin predictor (el LZW más lento de leer: casi no comprime unas cotas
    float32 con ruido)."""
    with source.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        ifd = tiff.read_first_ifd(stream, size)
        blocks: list[bytes] = []
        for offset, length in zip(ifd.numbers(tiff.TILE_OFFSETS),
                                  ifd.numbers(tiff.TILE_BYTE_COUNTS), strict=True):
            stream.seek(offset)
            tile = codecs.decode_block(
                stream.read(length), compression=codecs.COMPRESSION_DEFLATE,
                predictor=codecs.PREDICTOR_FLOATING_POINT, dtype="<f4", width=TILE,
                rows=TILE)
            blocks.append(lzw_encode(tile.tobytes()))
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
