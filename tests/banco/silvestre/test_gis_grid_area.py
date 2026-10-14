# SPDX-License-Identifier: GPL-3.0-or-later
"""Banco de Silvestre: el área real de celda de la rejilla de 1 m frente a la rejilla de la
V10 (spec 006, T36; CE-006-05; RF-006-02, RF-006-11; plan 006 §7.2, «Banco de Silvestre»).

CE-006-05: con el MDT de Silvestre, el volumen sobre la cota 100 m en una zona totalmente
cubierta coincide ±0,01 % entre la rejilla exacta de 1,000 m y la de la V10 (1,000294 ×
1,000302 m) usando el área real de cada una. Con 1 m² supuesto por celda de la V10 (el sesgo
B24 de Silvestre) la diferencia es de ≈ −0,06 %.

Lo ejecuta el arnés de los bancos de la 001 (``tools/bench_silvestre.py``) solo con
``tools/check.py --banco`` y con ``GEOBLENDER_SILVESTRE_DIR`` apuntando a la carpeta del
banco; sin la variable (o si no es una carpeta), se omite. **Solo lectura**: los ficheros del
banco solo se abren para leer, y el arnés comprueba que la carpeta queda igual (RNF-001-05).
Lo que se escribe (la rejilla de la V10 en GeoTIFF) va a una carpeta temporal de ``%TEMP%``
que se borra. Ni la ruta ni el nombre de ningún fichero del banco se escriben aquí ni en la
salida: solo las cifras de la comparación.

1. **El MDT** se reconoce sin su nombre: un GeoTIFF del banco con «MDT», «DEM» o «DTM» en el
   nombre (como palabra), de una banda en coma flotante, de 3.399 × 3.309 celdas de 0,5 m
   (spec 006 §7: «Silvestre: 3.399 × 3.309»), según su primer IFD. Se lee con el lector de
   Geoblender (RF-006-08). Las copias con las mismas cotas cuentan como uno; si hay varios
   MDT distintos, se comparan todos. Su CRS es el que declara (nunca se supone: si no
   declara ninguno, la comparación falla); la referencia vertical no cambia ningún volumen,
   y si no la declara se usa una referencia local que lo dice.
2. **La rejilla exacta**: la del proyecto de 1,000 m que cubre el MDT (``aligned_grid``),
   con la media por área, el método por defecto con un paso de fuente menor, y la fracción
   mínima por defecto (toda la celda cubierta, D-4) (RF-006-11).
3. **La rejilla de la V10**, la de Silvestre (B24): sus columnas y filas son las del MDT por
   0,5, truncadas (1.699 × 1.654), con la esquina noroeste y la extensión del MDT, así que sus
   pasos son 1,0002942907592702 × 1,0003022974607014 m. Se calcula con la misma media por área
   de Geoblender y se escribe y se lee como GeoTIFF: es una rejilla importada, cuya área de
   celda es |a·e| de su georreferencia (RF-006-02).
4. **La zona totalmente cubierta**: el mayor rectángulo de metros enteros en el que tienen
   dato todas las celdas de la rejilla exacta y todas las de la V10 que lo tocan, es decir,
   cubiertas enteras por celdas del MDT con dato (al menos 1 ha).
5. **El volumen sobre la cota 100 m** (Σ max(z − 100, 0)·área): en la rejilla exacta, con
   ``volume_between`` y la máscara del rectángulo (celdas de 1 m², enteras); en la de la V10,
   ``volume_between`` en las celdas enteras dentro del rectángulo más las del borde por la
   fracción de celda que queda dentro, todas con su área real |a·e|; y con 1 m² supuesto,
   las mismas celdas y fracciones con 1 m² cada una. Además (RF-006-11 sobre datos reales), el
   volumen neto de la rejilla exacta en la zona es el del MDT de 0,5 m con error ≤ 10⁻⁹.

Las cifras se imprimen en una línea ``CE-006-05: …`` por MDT, para anotarlas en la
verificación de la T36.
"""

import hashlib
import os
import re
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
geotiff = import_geoblender("gis.geotiff")
tiff = import_geoblender("gis.geotiff.tiff")
georef = import_geoblender("core.georef")

ENV = "GEOBLENDER_SILVESTRE_DIR"

BASE_M = 100.0  # CE-006-05: «el volumen sobre la cota 100 m»
TOLERANCE = 1e-4  # CE-006-05: ±0,01 % entre las dos rejillas con su área real
CONSERVATION = 1e-9  # RF-006-11: volumen de la zona totalmente cubierta al remuestrear
GRID_STEP = 1.0  # la rejilla exacta de 1,000 m (RF-006-01)
MDT_STEP = 0.5  # el MDT de dron de 0,5 m (spec 006 §2, E1)
MDT_SHAPE = (3309, 3399)  # filas y columnas del MDT de Silvestre (spec 006 §7)
V10_STEPS = (1.000294, 1.000302)  # CE-006-05: la celda de la V10, a la micra
MIN_ZONE_M2 = 10_000.0  # una zona de al menos 1 ha
NOMINAL_CELL_M2 = 1.0  # el área supuesta de Silvestre (B24)
NAME_PATTERN = re.compile(r"(?i)(?<![a-z])(mdt|dem|dtm)(?![a-z])")
TIFF_SUFFIXES = (".tif", ".tiff")
SAMPLE_FORMAT_FLOAT = 3  # SampleFormat de TIFF: IEEE en coma flotante
LOCAL_VERTICAL = "cotas del MDT del banco (no declara su referencia vertical)"

CATALOG = georef.load_catalog()
IO = geotiff.GeoTiffIO()


# --- Salida en español ----------------------------------------------------------------------


def _number(value: float, digits: int = 1) -> str:
    """Número con punto de millares y coma decimal."""
    return f"{value:,.{digits}f}".translate(str.maketrans(",.", ".,"))


def _percent(ratio: float, digits: int = 6) -> str:
    """Diferencia relativa en %, con su signo."""
    return f"{ratio * 100:+.{digits}f} %".replace(".", ",")


def _report(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


# --- El MDT del banco -----------------------------------------------------------------------


def _looks_like_mdt(path: Path) -> bool:
    """Si el primer IFD de ``path`` es el de un MDT como el de Silvestre: una banda en coma
    flotante de :data:`MDT_SHAPE` celdas de :data:`MDT_STEP` m. Solo lee la cabecera."""
    try:
        with path.open("rb") as stream:
            ifd = tiff.read_first_ifd(stream, os.fstat(stream.fileno()).st_size)
            scale = ifd.numbers(tiff.MODEL_PIXEL_SCALE) or ()
            return (
                (ifd.number(tiff.IMAGE_LENGTH), ifd.number(tiff.IMAGE_WIDTH)) == MDT_SHAPE
                and ifd.number(tiff.SAMPLES_PER_PIXEL, 1) == 1
                and ifd.number(tiff.SAMPLE_FORMAT, 1) == SAMPLE_FORMAT_FLOAT
                and tuple(scale[:2]) == (MDT_STEP, MDT_STEP)
            )
    except (OSError, tiff.TiffError):
        return False


def _candidates(folder: Path) -> list[Path]:
    """Los GeoTIFF de ``folder`` (y sus subcarpetas, sin seguir enlaces) que son un MDT como
    el de Silvestre, en un orden fijo."""
    found: list[Path] = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            path = Path(root, name)
            if (
                path.suffix.lower() in TIFF_SUFFIXES
                and NAME_PATTERN.search(path.stem)
                and _looks_like_mdt(path)
            ):
                found.append(path)
    return found


def _distinct_mdts(paths: list[Path]) -> list[tuple[object, int]]:
    """Los MDT distintos (rejilla y cotas, bit a bit) de ``paths``, con su número de copias."""
    seen: dict[bytes, list] = {}
    for path in paths:
        source = geotiff.read_geotiff(path)
        grid = source.grid
        digest = hashlib.sha256(
            repr((grid.west, grid.north, grid.dx, grid.dy, grid.ncols, grid.nrows)).encode()
        )
        digest.update(np.ascontiguousarray(source.values).tobytes())
        entry = seen.setdefault(digest.digest(), [source, 0])
        entry[1] += 1
    return [(source, copies) for source, copies in seen.values()]


# --- Rejillas y zona ------------------------------------------------------------------------


def _v10_grid(mdt: object) -> object:
    """La rejilla «de 1 m» de la V10 de Silvestre (B24) sobre el MDT ``mdt``: sus columnas y
    filas, las del MDT por paso/1 m truncadas; su esquina noroeste y su extensión, las del
    MDT (la transformación del MDT escalada por columnas/columnas nuevas)."""
    grid = mdt.grid
    ncols = int(grid.ncols * (grid.dx / GRID_STEP))
    nrows = int(grid.nrows * (grid.dy / GRID_STEP))
    return gis.Grid(
        grid.west,
        grid.north,
        grid.dx * (grid.ncols / ncols),
        grid.dy * (grid.nrows / nrows),
        ncols,
        nrows,
    )


def _x_edges(grid: object) -> np.ndarray:
    """Los bordes de las columnas, de oeste a este (m, absolutos)."""
    return grid.west + np.arange(grid.ncols + 1, dtype=np.float64) * grid.dx


def _u_edges(grid: object) -> np.ndarray:
    """Los bordes de las filas como u = −y, crecientes de norte a sur (m, absolutos)."""
    return -grid.north + np.arange(grid.nrows + 1, dtype=np.float64) * grid.dy


def _covering(edges: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Para cada celda de un eje con bordes ``edges``, la primera y la última celda del eje
    ``other`` que solapan con ella (con longitud positiva); −1 o ``len(other) − 1`` si la
    celda se sale de ``other``."""
    first = np.searchsorted(other, edges[:-1], side="right") - 1
    last = np.searchsorted(other, edges[1:], side="left") - 1
    return first, last


def _covered_by(grid: object, other: object, valid: np.ndarray) -> np.ndarray:
    """Las celdas de ``grid`` que solo tocan celdas de ``other`` con dato (``valid``), sin
    salirse de ``other``."""
    first_x, last_x = _covering(_x_edges(grid), _x_edges(other))
    first_y, last_y = _covering(_u_edges(grid), _u_edges(other))
    inside_x = (first_x >= 0) & (last_x < other.ncols)
    inside_y = (first_y >= 0) & (last_y < other.nrows)
    covered = inside_y[:, None] & inside_x[None, :]
    span_x = int((last_x - first_x)[inside_x].max(initial=0))
    span_y = int((last_y - first_y)[inside_y].max(initial=0))
    for step_y in range(span_y + 1):
        rows = np.clip(first_y + step_y, 0, other.nrows - 1)
        used_y = first_y + step_y <= last_y
        for step_x in range(span_x + 1):
            cols = np.clip(first_x + step_x, 0, other.ncols - 1)
            used_x = first_x + step_x <= last_x
            touched = used_y[:, None] & used_x[None, :]
            covered &= valid[np.ix_(rows, cols)] | ~touched
    return covered


def _largest_rectangle(mask: np.ndarray) -> tuple[int, int, int, int]:
    """El rectángulo de más celdas de ``mask`` (booleana) con todas verdaderas: filas
    [r0, r1) y columnas [c0, c1); con empate, el primero de arriba abajo e izquierda a
    derecha. Histograma por filas con una pila."""
    nrows, ncols = mask.shape
    heights = np.zeros(ncols, dtype=np.int64)
    best = (0, 0, 0, 0, 0)
    for row in range(nrows):
        heights = np.where(mask[row], heights + 1, 0)
        if int(heights.max(initial=0)) * ncols <= best[0]:
            continue
        stack: list[tuple[int, int]] = []
        for col, height in enumerate([*heights.tolist(), 0]):
            start = col
            while stack and stack[-1][1] >= height:
                start, top = stack.pop()
                area = top * (col - start)
                if area > best[0]:
                    best = (area, row + 1 - top, row + 1, start, col)
            stack.append((start, height))
    return best[1:]


@dataclass(frozen=True, slots=True)
class _Zone:
    """Rectángulo absoluto de metros enteros (m)."""

    west: float
    south: float
    east: float
    north: float

    @property
    def area_m2(self) -> float:
        return (self.east - self.west) * (self.north - self.south)


def _fractions(edges: np.ndarray, low: float, high: float) -> tuple[np.ndarray, np.ndarray]:
    """Por celda de un eje: la fracción de su longitud dentro de [low, high] y si está
    entera dentro."""
    left, right = edges[:-1], edges[1:]
    inside = np.clip(np.minimum(right, high) - np.maximum(left, low), 0.0, None)
    whole = (left >= low) & (right <= high)
    return np.where(whole, 1.0, inside / (right - left)), whole


# --- La comparación -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Comparison:
    """Las cifras de un MDT del banco."""

    label: str
    copies: int
    exact_method: str
    exact_fraction: float
    exact_area_m2: float
    v10_method: str
    v10_derived: object  # la rejilla de la V10 calculada (Grid)
    v10_imported: object  # la misma, leída de su GeoTIFF (Grid)
    v10_same_values: bool
    zone: _Zone
    exact_m3: float  # volumen sobre 100 m, rejilla exacta
    exact_net_m3: float  # Σ (z − 100)·área, rejilla exacta
    exact_nodata_m2: float
    mdt_net_m3: float  # Σ (z − 100)·área, MDT de 0,5 m
    v10_real_m3: float  # volumen sobre 100 m, rejilla de la V10 con |a·e|
    v10_nominal_m3: float  # el mismo con 1 m² por celda
    v10_zone_m2: float  # el área de la zona según las celdas de la V10
    v10_nodata_m2: float

    @property
    def real_difference(self) -> float:
        return self.v10_real_m3 / self.exact_m3 - 1.0

    @property
    def nominal_difference(self) -> float:
        return self.v10_nominal_m3 / self.exact_m3 - 1.0

    @property
    def conservation_error(self) -> float:
        return abs(self.exact_net_m3 / self.mdt_net_m3 - 1.0)


def _plane(raster: object) -> object:
    """La cota de :data:`BASE_M` en la rejilla de ``raster``."""
    return gis.Raster(
        raster.grid, np.full(raster.grid.shape, BASE_M), raster.crs, raster.vertical
    )


def _weighted(raster: object, zone: _Zone) -> tuple[np.ndarray, ...]:
    """Las celdas de ``raster`` que tocan ``zone``: sus filas y sus columnas, y en el array
    de esas filas y columnas, sus cotas, la fracción de cada celda dentro de la zona y si
    está entera dentro. Todas deben tener dato."""
    fx, whole_x = _fractions(_x_edges(raster.grid), zone.west, zone.east)
    fu, whole_u = _fractions(_u_edges(raster.grid), -zone.north, -zone.south)
    rows = np.flatnonzero(fu > 0.0)
    cols = np.flatnonzero(fx > 0.0)
    values = raster.values[np.ix_(rows, cols)]
    weights = fu[rows][:, None] * fx[cols][None, :]
    whole = whole_u[rows][:, None] & whole_x[cols][None, :]
    if not np.isfinite(values).all():
        raise AssertionError("la zona toca celdas sin dato: no está totalmente cubierta")
    return rows, cols, values, weights, whole


def _compare(source: object, copies: int, label: str, temp: Path) -> _Comparison:
    """Las cifras de CE-006-05 para el MDT ``source`` (pasos 2 a 5 del docstring del
    módulo); ``temp``, la carpeta temporal del GeoTIFF de la V10."""
    if source.declared_crs is None:
        raise AssertionError(
            f"{label}: el MDT no declara su CRS, y no se supone (constitución, principio 6)"
        )
    vertical = source.declared_vertical or CATALOG.local_vertical(LOCAL_VERTICAL)
    mdt = gis.Raster(source.grid, source.values, source.declared_crs, vertical)

    exact_grid = gis.aligned_grid(mdt.grid.extent, GRID_STEP)
    exact, exact_report = gis.resample_to_grid(
        mdt, exact_grid, method=gis.choose_method(mdt.grid, exact_grid)
    )
    derived = _v10_grid(mdt)
    v10_raster, v10_report = gis.resample_to_grid(
        mdt, derived, method=gis.choose_method(mdt.grid, derived)
    )
    path = temp / "v10.tif"
    IO.write(v10_raster, path, profile=gis.WriteProfile.PROJECT)
    imported = geotiff.read_geotiff(path)
    same_values = bool(
        np.array_equal(imported.values, v10_raster.values, equal_nan=True)
    )
    v10 = gis.Raster(imported.grid, imported.values, mdt.crs, mdt.vertical)

    valid = np.isfinite(exact.values) & _covered_by(
        exact.grid, v10.grid, np.isfinite(v10.values)
    )
    r0, r1, c0, c1 = _largest_rectangle(valid)
    zone = _Zone(
        exact.grid.west + c0 * GRID_STEP,
        exact.grid.north - r1 * GRID_STEP,
        exact.grid.west + c1 * GRID_STEP,
        exact.grid.north - r0 * GRID_STEP,
    )
    if zone.area_m2 < MIN_ZONE_M2:
        raise AssertionError(
            f"{label}: la mayor zona totalmente cubierta mide {_number(zone.area_m2)} m², "
            f"menos de {_number(MIN_ZONE_M2)} m²"
        )

    mask = np.zeros(exact.grid.shape, dtype=bool)
    mask[r0:r1, c0:c1] = True
    exact_volume = gis.volume_between(exact, _plane(exact), mask=mask)

    _, _, values, weights, _ = _weighted(mdt, zone)
    mdt_net = float(np.sum((values - BASE_M) * weights)) * mdt.grid.cell_area

    rows, cols, values, weights, whole = _weighted(v10, zone)
    full_mask = np.zeros(v10.grid.shape, dtype=bool)
    full_mask[np.ix_(rows, cols)] = whole
    full = gis.volume_between(v10, _plane(v10), mask=full_mask)
    above = np.maximum(values - BASE_M, 0.0)
    border = float(np.sum(np.where(whole, 0.0, above * weights)))
    nominal = float(np.sum(above * weights)) * NOMINAL_CELL_M2

    return _Comparison(
        label=label,
        copies=copies,
        exact_method=exact_report.method,
        exact_fraction=exact_report.min_valid_fraction,
        exact_area_m2=exact_report.cell_area_m2,
        v10_method=v10_report.method,
        v10_derived=derived,
        v10_imported=imported.grid,
        v10_same_values=same_values,
        zone=zone,
        exact_m3=exact_volume.cut_m3,
        exact_net_m3=exact_volume.net_m3,
        exact_nodata_m2=exact_volume.nodata_area_m2,
        mdt_net_m3=mdt_net,
        v10_real_m3=full.cut_m3 + border * v10.grid.cell_area,
        v10_nominal_m3=nominal,
        v10_zone_m2=float(np.sum(weights)) * v10.grid.cell_area,
        v10_nodata_m2=full.nodata_area_m2,
    )


def _line(result: _Comparison) -> str:
    zone = result.zone
    copies = "" if result.copies == 1 else f", {result.copies} copias iguales"
    grid = result.v10_imported
    return (
        f"CE-006-05 (banco de Silvestre, {result.label}{copies}): zona totalmente "
        f"cubierta de {_number(zone.east - zone.west, 0)} × "
        f"{_number(zone.north - zone.south, 0)} m ({_number(zone.area_m2 / 10_000, 2)} ha); "
        f"volumen sobre la cota {_number(BASE_M, 0)} m: rejilla exacta de 1,000 m "
        f"{_number(result.exact_m3)} m³; rejilla de la V10 ({_number(grid.dx, 16)} × "
        f"{_number(grid.dy, 16)} m, "
        f"{_number(grid.cell_area, 10)} m² por celda) {_number(result.v10_real_m3)} m³ "
        f"({_percent(result.real_difference)}; tolerancia ±0,01 %); con 1 m² supuesto "
        f"{_number(result.v10_nominal_m3)} m³ ({_percent(result.nominal_difference)}); "
        f"volumen neto del MDT de 0,5 m en la zona {_number(result.mdt_net_m3)} m³ "
        f"(rejilla exacta: error relativo {result.conservation_error:.1e}; máximo 1e-9)"
    )


class SilvestreGridAreaTest(unittest.TestCase):
    """CE-006-05 con el MDT del banco de Silvestre (RF-006-02, RF-006-11)."""

    results: list[_Comparison] = []

    @classmethod
    def setUpClass(cls) -> None:
        text = os.environ.get(ENV, "").strip()
        if not text:
            raise unittest.SkipTest(
                f"OMITIDO: silvestre: la variable {ENV} no está definida; defínala con la "
                "carpeta del banco (solo lectura) y ejecute tools/check.py --banco"
            )
        folder = Path(text)
        if not folder.is_dir():
            raise unittest.SkipTest(
                f"OMITIDO: silvestre: {ENV} no apunta a una carpeta legible"
            )
        mdts = _distinct_mdts(_candidates(folder))
        if not mdts:
            raise AssertionError(
                "no se encontró en el banco ningún MDT como el de Silvestre: un GeoTIFF con "
                "«MDT», «DEM» o «DTM» en el nombre, de una banda en coma flotante, de "
                "3.399 × 3.309 celdas de 0,5 m"
            )
        results = []
        with tempfile.TemporaryDirectory(prefix="gb-banco-") as temp:
            for index, (source, copies) in enumerate(mdts, start=1):
                label = f"MDT {index} de {len(mdts)}"
                result = _compare(source, copies, label, Path(temp))
                _report(_line(result))
                results.append(result)
        cls.results = results

    def test_v10_grid_is_imported_with_its_real_cell_area(self) -> None:
        """RF-006-02, CE-006-05: la rejilla de la V10 sobre el MDT del banco es la de
        1,000294 × 1,000302 m, y leída de su GeoTIFF (rejilla importada) su área de celda es
        |a·e| de la georreferencia, no 1 m²."""
        for result in self.results:
            with self.subTest(mdt=result.label):
                derived, imported = result.v10_derived, result.v10_imported
                self.assertEqual((round(derived.dx, 6), round(derived.dy, 6)), V10_STEPS)
                self.assertTrue(imported.same_geometry(derived))
                self.assertTrue(result.v10_same_values)
                a, _, _, _, e, _ = imported.transform
                self.assertEqual(imported.cell_area, abs(a * e))
                self.assertGreater(imported.cell_area, 1.0005)
                self.assertEqual(result.v10_method, gis.ResampleMethod.AREA_MEAN)

    def test_exact_grid_keeps_the_mdt_volume(self) -> None:
        """RF-006-11, RF-006-02: la rejilla exacta de 1,000 m sale del MDT de 0,5 m con la
        media por área (el método por defecto, en su informe) y toda la celda cubierta; en la
        zona totalmente cubierta, con celdas de 1 m² exactos, conserva el volumen del MDT con
        error relativo ≤ 1e-9 y no tiene celdas sin dato."""
        for result in self.results:
            with self.subTest(mdt=result.label):
                self.assertEqual(result.exact_method, gis.ResampleMethod.AREA_MEAN)
                self.assertEqual(result.exact_fraction, 1.0)
                self.assertEqual(result.exact_area_m2, 1.0)
                self.assertEqual(result.exact_nodata_m2, 0.0)
                self.assertLessEqual(result.conservation_error, CONSERVATION)

    def test_volume_matches_with_the_real_cell_area(self) -> None:
        """CE-006-05, RF-006-02: el volumen sobre la cota 100 m en la zona totalmente
        cubierta coincide ±0,01 % entre la rejilla exacta y la de la V10 con su área real, y
        las dos rejillas miden la misma zona."""
        for result in self.results:
            with self.subTest(mdt=result.label):
                self.assertEqual(result.v10_nodata_m2, 0.0)
                self.assertAlmostEqual(
                    result.v10_zone_m2 / result.zone.area_m2, 1.0, delta=1e-9
                )
                self.assertGreater(result.exact_m3, 0.0)
                self.assertLessEqual(abs(result.real_difference), TOLERANCE)

    def test_nominal_cell_area_gives_the_b24_bias(self) -> None:
        """CE-006-05, RF-006-02 (Silvestre B24): con 1 m² supuesto por celda de la V10, el
        volumen queda ≈ −0,06 % por debajo del de la rejilla exacta (1/1,0005967 − 1 ±
        0,01 %): el sesgo que evita el área real."""
        for result in self.results:
            with self.subTest(mdt=result.label):
                bias = 1.0 / result.v10_imported.cell_area - 1.0
                self.assertLess(result.nominal_difference, 0.0)
                self.assertLessEqual(abs(result.nominal_difference - bias), TOLERANCE)


if __name__ == "__main__":
    unittest.main()
