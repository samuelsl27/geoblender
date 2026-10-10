# SPDX-License-Identifier: GPL-3.0-or-later
"""Lector de contenido de prueba ``test.npy_grid@1`` (spec 008, T11; RF-008-08; ADR-0024 §5;
plan 008 §5.1 y §7.3).

Lee una rejilla de un ``.npy`` (``numpy.save`` de una matriz 2-D en orden C, filas de norte a
sur) por bandas de filas de unos ``request.chunk_bytes`` bytes, sin cargarla entera, y la
escribe en el ``ContentHasher`` de su petición con ``begin_grid``: su hash es el de
``ContentHasher.grid`` con la misma cabecera y las mismas celdas. El ``.npy`` solo trae la forma
y el tipo de celda (de él salen ``rows``, ``columns`` y ``class``: flotante → ``float``, entero
→ ``int``, booleano → ``bool``); la georreferencia, el tipo de celda, el sin dato y el CRS del
fichero llegan en los ajustes de lectura (:data:`SETTINGS_KEYS`). Nunca usa ``pickle``: lee la
cabecera con ``numpy.lib.format`` y las celdas como bytes.

Lo usan ``tests/unit/core/content/test_readers.py`` y el arnés ``BigHashTest`` de
``tests/rendimiento/core/test_provenance_perf.py`` (T42), que la 006 y la 005 reutilizan con sus
lectores de GeoTIFF y de RecMin. No se empaqueta: se registra con :func:`registered`.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
from numpy.lib import format as npy_format

from tests.support.package import import_geoblender

readers = import_geoblender("core.content.readers")

NPY_GRID_BYTES_PER_S = 100_000_000
"""Lo que lee y hashea el lector de prueba por segundo, a la baja (sha256 de las celdas en
float64 a unos 175 MB/s en el PC de referencia, más la conversión): su estimación."""
SETTINGS_KEYS: tuple[str, ...] = ("x0", "y0", "dx", "dy", "cell", "nodata", "crs")
"""Las claves de la cabecera ``gbch/1`` de una rejilla que no trae el ``.npy``: van en los
ajustes de lectura, todas."""
_CLASSES: dict[str, str] = {"f": "float", "i": "int", "u": "int", "b": "bool"}
_HEADER_READERS = {
    (1, 0): npy_format.read_array_header_1_0,
    (2, 0): npy_format.read_array_header_2_0,
}


def read_npy_grid(request: Any) -> Iterator[float]:
    """El generador del lector: la rejilla de ``request.files["main"]`` por bandas de filas,
    con su progreso (filas leídas / filas) tras cada una; 1,0 cuando el hash está hecho."""
    path = request.files["main"]
    with open(path, "rb") as stream:
        shape, dtype = _header(stream, path)
        rows, columns = shape
        feed = request.hasher.begin_grid(grid_header(shape, dtype, request.settings))
        row_bytes = columns * dtype.itemsize
        step = max(1, request.chunk_bytes // row_bytes)
        done = 0
        while done < rows:
            count = min(step, rows - done)
            data = stream.read(count * row_bytes)
            if len(data) != count * row_bytes:
                raise ValueError(
                    f"«{path.name}» está cortado: faltan celdas a partir de la fila {done + 1} "
                    f"de {rows}"
                )
            feed.update(np.frombuffer(data, dtype=dtype).reshape(count, columns))
            done += count
            if done < rows:
                yield done / rows
        feed.finish()
    yield 1.0


def _estimate(size: int) -> float:
    return size / NPY_GRID_BYTES_PER_S


NPY_GRID = readers.ContentReader(
    "test.npy_grid",
    1,
    ("raster",),
    False,
    False,
    _estimate,
    read_npy_grid,
    True,
)
"""El lector de prueba: una rejilla de un ``.npy``, por bandas de filas."""
NPY_GRID_ID = NPY_GRID.id


def grid_header(shape: tuple[int, ...], dtype: np.dtype, settings: Mapping[str, Any]) -> dict:
    """La cabecera ``gbch/1`` de la rejilla: forma y clase del ``.npy`` y lo demás de los
    ajustes (el normalizador la comprueba: le faltan o le sobran claves → ``ValueError``)."""
    value_class = _CLASSES.get(dtype.kind)
    if value_class is None:
        raise TypeError(f"un .npy de celdas {dtype} no es una rejilla: solo números o booleanos")
    return {"rows": shape[0], "columns": shape[1], "class": value_class, **settings}


def write_grid(path: Path, array: np.ndarray) -> Path:
    """Guarda ``array`` tal cual (su tipo, su orden de bytes y su orden de memoria) en
    ``path`` con ``numpy.save``, sin ``pickle``."""
    with open(path, "wb") as stream:
        np.save(stream, array, allow_pickle=False)
    return path


@contextmanager
def registered(*content_readers: Any) -> Iterator[None]:
    """Registra los lectores (por defecto, :data:`NPY_GRID`) y los quita al salir."""
    chosen = content_readers or (NPY_GRID,)
    done: list[str] = []
    try:
        for content_reader in chosen:
            readers.register_reader(content_reader)
            done.append(content_reader.id)
        yield
    finally:
        for reader_id in reversed(done):
            readers.unregister_reader(reader_id)


def _header(stream: Any, path: Path) -> tuple[tuple[int, int], np.dtype]:
    version = npy_format.read_magic(stream)
    read_header = _HEADER_READERS.get(version)
    if read_header is None:
        raise ValueError(f"«{path.name}»: versión {version} del formato .npy no admitida")
    shape, fortran_order, dtype = read_header(stream)
    if fortran_order:
        raise ValueError(
            f"«{path.name}» está en orden Fortran: el lector de prueba lee filas en orden C"
        )
    if len(shape) != 2 or min(shape) < 1:
        raise ValueError(f"«{path.name}» no es una rejilla 2-D con celdas: su forma es {shape}")
    return (int(shape[0]), int(shape[1])), dtype
