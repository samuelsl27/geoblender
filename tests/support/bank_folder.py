# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo común de las comparaciones del banco privado de Silvestre (``tests/banco/silvestre/``;
spec 011, T29; spec 012, T32).

El banco llega por ``GEOBLENDER_SILVESTRE_DIR`` (:data:`ENV`) y es de **solo lectura**: aquí se
buscan sus ficheros por patrones de nombre (sin suponer la forma de la carpeta, que no está
documentada en el repositorio), en un orden fijo y sin seguir enlaces, y las copias iguales (mismo
sha256) cuentan como una. Lo que no se encuentra se dice con el motivo (:class:`BankShapeError`);
ni la ruta ni el nombre de ningún fichero, unidad o versión del banco se escriben en la salida.

- :func:`bank_folder`: la carpeta del banco o la omisión de la comparación con la orden que la
  activa (``tools/check.py --banco``).
- :func:`files`, :func:`distinct`, :func:`one`, :func:`find_version`, :func:`tiffs`: buscar en la
  carpeta (la versión vigente es la carpeta ``V<nn>_<rasgo>_VIGENTE`` de número mayor).
- :func:`declared` y :func:`on_grid`: el CRS declarado de una superficie (nunca se supone) y su
  llevada a la rejilla de otra (GeoTIFF o ``.npy``, sin ``pickle``) con el remuestreo de
  Geoblender, en un temporal.
- :func:`number`, :func:`percent` y :func:`report`: la salida en español.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import unittest
from pathlib import Path

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
geotiff = import_geoblender("gis.geotiff")
georef = import_geoblender("core.georef")

ENV = "GEOBLENDER_SILVESTRE_DIR"
VERSION_PATTERN = re.compile(r"(?i)^v(\d+)_.+_vigente$")
START_PATTERN = re.compile(r"(?i)(?<![a-z])(mdt|dem|dtm|terreno)(?![a-z])")
TIFF_SUFFIXES = (".tif", ".tiff")
NPY_SUFFIX = ".npy"
LOCAL_VERTICAL = "cotas de las superficies del banco (no declaran su referencia vertical)"

CATALOG = georef.load_catalog()


class BankShapeError(AssertionError):
    """El banco no tiene la forma que espera la comparación (véase su módulo)."""


# --- Salida en español ----------------------------------------------------------------------


def number(value: float, digits: int = 1) -> str:
    """Número con punto de millares y coma decimal."""
    return f"{value:,.{digits}f}".translate(str.maketrans(",.", ".,"))


def percent(ratio: float, digits: int = 6) -> str:
    """Diferencia relativa en %, con su signo."""
    return f"{ratio * 100:+.{digits}f} %".replace(".", ",")


def report(text: str) -> None:
    """Una línea de la comparación, en la salida de errores (la del arnés de los bancos)."""
    print(text, file=sys.stderr, flush=True)


# --- La carpeta del banco -------------------------------------------------------------------


def bank_folder() -> Path:
    """La carpeta del banco (``GEOBLENDER_SILVESTRE_DIR``); sin la variable, o si no es una
    carpeta, :class:`unittest.SkipTest` con la orden que activa la comparación."""
    text = os.environ.get(ENV, "").strip()
    if not text:
        raise unittest.SkipTest(
            f"OMITIDO: silvestre: la variable {ENV} no está definida; defínala con la "
            "carpeta del banco (solo lectura) y ejecute tools/check.py --banco"
        )
    folder = Path(text)
    if not folder.is_dir():
        raise unittest.SkipTest(f"OMITIDO: silvestre: {ENV} no apunta a una carpeta legible")
    return folder


# --- Buscar en el banco ---------------------------------------------------------------------


def files(folder: Path) -> list[Path]:
    """Los ficheros de ``folder`` y sus subcarpetas, sin seguir enlaces, en un orden fijo."""
    found: list[Path] = []
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        found.extend(Path(root, name) for name in sorted(names))
    return found


def sha256(path: Path) -> str:
    """El sha256 del contenido de ``path`` (por bloques de 1 MiB)."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def distinct(paths: list[Path]) -> list[Path]:
    """Una de cada grupo de copias iguales (mismo sha256), en el orden de ``paths``."""
    seen: dict[str, Path] = {}
    for path in paths:
        seen.setdefault(sha256(path), path)
    return list(seen.values())


def one(paths: list[Path], what: str) -> Path:
    """La única de ``paths`` salvo copias iguales; si no, :class:`BankShapeError`."""
    found = distinct(paths)
    if len(found) != 1:
        count = "ninguna" if not found else f"{len(found)} distintas"
        raise BankShapeError(f"{what}: se esperaba una y hay {count} (véase la forma del "
                             "banco en el docstring de la comparación)")
    return found[0]


def find_version(folder: Path) -> Path:
    """La carpeta de la versión vigente del banco: ``V<nn>_<rasgo>_VIGENTE`` de número mayor."""
    found: dict[int, list[Path]] = {}
    for root, dirs, _ in os.walk(folder):
        dirs.sort()
        for name in dirs:
            match = VERSION_PATTERN.match(name)
            if match:
                found.setdefault(int(match.group(1)), []).append(Path(root, name))
    if not found:
        raise BankShapeError("el banco no tiene ninguna carpeta de versión vigente "
                             "(V<nn>_<rasgo>_VIGENTE)")
    candidates = found[max(found)]
    if len(candidates) != 1:
        raise BankShapeError(f"el banco tiene {len(candidates)} carpetas de versión vigente con "
                             "el número mayor: no se sabe cuál es la vigente")
    return candidates[0]


def tiffs(paths: list[Path], pattern: re.Pattern[str]) -> list[Path]:
    """Los GeoTIFF de ``paths`` cuyo nombre (sin extensión) casa con ``pattern``."""
    return [path for path in paths
            if path.suffix.lower() in TIFF_SUFFIXES and pattern.search(path.stem)]


# --- Las superficies ------------------------------------------------------------------------


def declared(source: object, what: str) -> tuple[object, object]:
    """El CRS y la referencia vertical de una superficie leída: el CRS siempre lo declara (si
    no, falla: no se supone, constitución principio 6) y, sin referencia vertical, se usa una
    local que lo dice."""
    if source.declared_crs is None:
        raise AssertionError(f"{what} no declara su CRS, y no se supone (constitución, "
                             "principio 6)")
    vertical = source.declared_vertical or CATALOG.local_vertical(LOCAL_VERTICAL)
    return source.declared_crs, vertical


def on_grid(path: Path, grid: object, crs: object, vertical: object, temp: Path,
            role: str, what: str) -> Path:
    """``path`` (GeoTIFF o ``.npy``) en la rejilla ``grid``: el mismo fichero si ya lo está; si
    no, su copia en ``temp`` (remuestreada con el método por defecto, o el ``.npy`` tal cual)."""
    target = temp / f"{role}.tif"
    if path.suffix.lower() == NPY_SUFFIX:
        values = np.load(path, allow_pickle=False)
        if values.shape != grid.shape or values.dtype.kind not in "fiu":
            raise BankShapeError(f"{what}: el .npy no tiene la forma de la rejilla de la final")
        raster = gis.Raster(grid, np.asarray(values, dtype=np.float64), crs, vertical)
    else:
        source = geotiff.read_geotiff(path)
        found, _ = declared(source, what)
        if found != crs:
            raise AssertionError(f"{what}: su CRS no es el de la superficie final")
        if source.grid.same_geometry(grid):
            return path
        mdt = gis.Raster(source.grid, source.values, crs, vertical)
        raster, _ = gis.resample_to_grid(mdt, grid,
                                         method=gis.choose_method(source.grid, grid))
    geotiff.GeoTiffIO().write(raster, target, profile=gis.WriteProfile.PROJECT)
    return target
