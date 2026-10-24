# SPDX-License-Identifier: GPL-3.0-or-later
"""Banco del proyecto de referencia: la cubicación por unidades de su versión vigente frente a
sus volúmenes y sus toneladas por unidad (spec 011, T29; CE-011-05; HU-011-3; RF-011-12,
RF-011-16; D-14 d; plan 011 §7, «Banco privado»; constitución, principio 2).

CE-011-05: con el banco privado del proyecto de referencia, la cubicación por unidades de su
versión vigente reproduce sus volúmenes y sus toneladas por unidad dentro de ±0,01 % (D-14 d),
una vez corregida el área de celda de sus superficies (como CE-006-05: el proyecto de referencia
contaba la celda nominal; Geoblender, la real, ``|a·e|``). Cada diferencia la explica la persona
que lo ejecuta (hito H3).

Lo ejecuta el arnés de los bancos de la 001 (``tools/bench_silvestre.py``) solo con
``tools/check.py --banco`` y con ``GEOBLENDER_SILVESTRE_DIR`` apuntando a la carpeta del banco;
sin la variable (o si no es una carpeta), se omite. **Solo lectura**: los ficheros del banco
solo se abren para leer, y el arnés comprueba que la carpeta queda igual (RNF-001-05). Lo que se
escribe (las superficies llevadas a la rejilla de la final) va a una carpeta temporal de
``%TEMP%`` que se borra. Ni la ruta ni el nombre de ningún fichero, unidad o versión del banco se
escriben aquí ni en la salida: solo «unidad i de n» y las cifras de la comparación.

**La forma del banco** (sin nombres de ficheros: patrones; todo se busca en la carpeta y sus
subcarpetas, sin seguir enlaces, en un orden fijo, y las copias iguales, mismo sha256, cuentan
como una). Es la de las salidas por versión del proyecto de referencia que describe su análisis
(``Documentacion/analisis_proyecto_silvestre``, §2.5 [9] y §4); si el banco real no la tiene, se
ve en el H3 y se adapta esta comparación (nunca el banco):

1. **La versión vigente**: la carpeta ``V<nn>_<rasgo>_VIGENTE`` de número mayor (ninguna, o dos
   distintas con ese número: la comparación falla con el motivo).
2. **La superficie final**: el GeoTIFF de la versión con ``Superficie_excavacion`` en el nombre
   (la superficie de excavación de la versión, de una banda en coma flotante). Su rejilla es la
   de la cubicación; declara su CRS (nunca se supone: si no, la comparación falla); si no
   declara referencia vertical, se usa una referencia local que lo dice.
3. **La superficie de partida**: el GeoTIFF con «MDT», «DEM», «DTM» o «terreno» en el nombre
   (como palabra), de una banda en coma flotante: el de la versión o, si la versión no tiene
   ninguno, el del banco (el MDT de CE-006-05). Con otra rejilla, se lleva a la de la final con
   el remuestreo de Geoblender (el método por defecto, RF-006-11: la media por área desde el MDT
   de 0,5 m, como hizo el proyecto de referencia), en un temporal. Su CRS declarado, el de la
   final.
4. **La tabla de referencia**: el CSV de la versión (``;``, UTF-8) cuya cabecera tiene las
   columnas ``unidad``, ``base``, ``volumen_m3`` y ``toneladas_t`` (y, si las tiene,
   ``densidad_t_m3`` y ``papel``): una fila por unidad, de arriba abajo, con los volúmenes y las
   toneladas del proyecto de referencia (con la celda nominal) y, en ``base``, el nombre sin
   extensión de la superficie de su base (vacía solo en la última, que llega hasta abajo). Los
   números, con coma decimal y puntos de millares, o con punto decimal y sin millares.
5. **Las bases**: un GeoTIFF (como la partida: a la rejilla de la final si tiene otra) o un
   ``.npy`` de números con la forma de la rejilla de la final (sin ``pickle``; se escribe como
   GeoTIFF en el temporal, tal cual); de la versión o, si no está allí, del banco. Una celda sin
   dato (NaN) es una unidad que no existe allí: ausente, y su espesor pasa a la de abajo
   (RF-011-12). Si el proyecto de referencia la trataba de otro modo (su análisis habla de la
   base a 10⁴ m), es una diferencia que se explica en el H3.

**La cubicación** (``reserves.volumes.volume_steps``, como la orden «Por unidad, fase y banco…»
sin ámbito, dominios ni rodajas; espesor mínimo y umbral de presencia, 0): de la partida a la
final, con la columna de la tabla (unidades naturales in situ; el papel, ``papel`` útil o estéril
y, sin la columna, estéril, que no cambia ninguna cifra por unidad) y la densidad de cada unidad
(``densidad_t_m3`` o, sin ella, ``toneladas_t / volumen_m3`` de la tabla); las toneladas, con
``reserves.volumes.tonnage_outputs`` (in situ, ``V·ρ``: RF-011-16).

**La comparación** (D-14 d): para cada unidad, el volumen y las toneladas de Geoblender frente a
los de la tabla por ``|a·e| / A_nominal``, con ``A_nominal`` el producto de los pasos de la final
redondeados al centímetro (1 m² en la rejilla de 1,000294 × 1,000302 m): error relativo
≤ 10⁻⁴. Las cifras se imprimen en una línea ``CE-011-05: …`` por unidad, para anotarlas en la
verificación del H3.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
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
georef = import_geoblender("core.georef")
graph = import_geoblender("core.provenance.graph")
volumes = import_geoblender("reserves.volumes")
surfaces = import_geoblender("reserves.surfaces")
materials = import_geoblender("reserves.materials")
res_params = import_geoblender("reserves.params")
kernel = import_geoblender("reserves.kernel")

ENV = "GEOBLENDER_SILVESTRE_DIR"

TOLERANCE = 1e-4  # D-14 d: ±0,01 % por unidad, corregida el área de celda
NAME = "CE-011-05"  # el nombre de la cubicación (no se guarda en ningún proyecto)
VERSION_PATTERN = re.compile(r"(?i)^v(\d+)_.+_vigente$")
FINAL_PATTERN = re.compile(r"(?i)superficie_excavaci[oó]n")
START_PATTERN = re.compile(r"(?i)(?<![a-z])(mdt|dem|dtm|terreno)(?![a-z])")
TIFF_SUFFIXES = (".tif", ".tiff")
NPY_SUFFIX = ".npy"
COLUMNS = ("unidad", "base", "volumen_m3", "toneladas_t")
DENSITY = "densidad_t_m3"
ROLE = "papel"
ROLES = {
    "útil": "useful", "util": "useful", "useful": "useful", "mineral": "useful",
    "estéril": "waste", "esteril": "waste", "waste": "waste", "": "waste",
}
LOCAL_VERTICAL = "cotas de las superficies del banco (no declaran su referencia vertical)"

CATALOG = georef.load_catalog()


class BankShapeError(AssertionError):
    """El banco no tiene la forma que espera la comparación (véase el módulo)."""


# --- Salida en español ----------------------------------------------------------------------


def _number(value: float, digits: int = 1) -> str:
    """Número con punto de millares y coma decimal."""
    return f"{value:,.{digits}f}".translate(str.maketrans(",.", ".,"))


def _percent(ratio: float, digits: int = 6) -> str:
    """Diferencia relativa en %, con su signo."""
    return f"{ratio * 100:+.{digits}f} %".replace(".", ",")


def _report(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


# --- La forma del banco ---------------------------------------------------------------------


def _files(folder: Path) -> list[Path]:
    """Los ficheros de ``folder`` y sus subcarpetas, sin seguir enlaces, en un orden fijo."""
    found: list[Path] = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        found.extend(Path(root, name) for name in sorted(files))
    return found


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _distinct(paths: list[Path]) -> list[Path]:
    """Una de cada grupo de copias iguales (mismo sha256), en el orden de ``paths``."""
    seen: dict[str, Path] = {}
    for path in paths:
        seen.setdefault(_sha256(path), path)
    return list(seen.values())


def _one(paths: list[Path], what: str) -> Path:
    """La única de ``paths`` salvo copias iguales; si no, :class:`BankShapeError`."""
    distinct = _distinct(paths)
    if len(distinct) != 1:
        found = "ninguna" if not distinct else f"{len(distinct)} distintas"
        raise BankShapeError(f"{what}: se esperaba una y hay {found} (véase la forma del "
                             "banco en el docstring de la comparación)")
    return distinct[0]


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


def _tiffs(paths: list[Path], pattern: re.Pattern[str]) -> list[Path]:
    return [path for path in paths
            if path.suffix.lower() in TIFF_SUFFIXES and pattern.search(path.stem)]


def _parse_number(text: str, what: str) -> float:
    """Un número de la tabla: coma decimal con puntos de millares, o punto decimal."""
    clean = text.strip().replace(" ", "").replace(" ", "")
    if "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif clean.count(".") > 1:
        clean = clean.replace(".", "")
    try:
        value = float(clean)
    except ValueError:
        raise BankShapeError(f"{what}: «{text}» no es un número") from None
    if not math.isfinite(value) or value < 0.0:
        raise BankShapeError(f"{what}: se esperaba un número finito ≥ 0")
    return value


@dataclass(frozen=True, slots=True)
class ReferenceUnit:
    """Una fila de la tabla de referencia: la unidad (su nombre solo se usa dentro), el nombre
    sin extensión de su base (``""`` en la última), su papel, sus cifras con la celda nominal y
    su densidad (t/m³; ``None`` si no se puede saber y no hace falta)."""

    name: str
    base: str
    role: str
    volume_m3: float
    mass_t: float
    density_t_m3: float | None


def _header(path: Path) -> list[str] | None:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            line = stream.readline()
    except (OSError, UnicodeDecodeError):
        return None
    return [cell.strip().casefold() for cell in line.rstrip("\r\n").split(";")]


def read_reference(paths: list[Path]) -> tuple[ReferenceUnit, ...]:
    """La tabla de referencia de la versión: el único CSV con las columnas de :data:`COLUMNS`."""
    tables = [path for path in paths if path.suffix.lower() == ".csv"
              and set(COLUMNS) <= set(_header(path) or ())]
    path = _one(tables, "la tabla de referencia por unidades de la versión vigente")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(io.StringIO(stream.read()), delimiter=";"))
    header = [cell.strip().casefold() for cell in rows[0]]
    position = {name: header.index(name) for name in header}
    units: list[ReferenceUnit] = []
    for number, row in enumerate(rows[1:], start=1):
        if not any(cell.strip() for cell in row):
            continue
        cells = {name: row[index].strip() if index < len(row) else ""
                 for name, index in position.items()}
        what = f"la unidad {number} de la tabla de referencia"
        volume = _parse_number(cells["volumen_m3"], f"{what}, volumen")
        mass = _parse_number(cells["toneladas_t"], f"{what}, toneladas")
        density = (_parse_number(cells[DENSITY], f"{what}, densidad")
                   if cells.get(DENSITY) else (mass / volume if volume > 0.0 else None))
        role = ROLES.get(cells.get(ROLE, "").casefold())
        if role is None:
            raise BankShapeError(f"{what}: papel desconocido (útil o estéril)")
        units.append(ReferenceUnit(cells["unidad"], cells["base"], role, volume, mass, density))
    if not units:
        raise BankShapeError("la tabla de referencia no tiene ninguna unidad")
    return tuple(units)


# --- Las superficies ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Surfaces:
    """Las fuentes de la cubicación por papel, la rejilla de la final y su CRS."""

    sources: dict[str, object]
    grid: object


def _declared(source: object, what: str) -> tuple[object, object]:
    if source.declared_crs is None:
        raise AssertionError(f"{what} no declara su CRS, y no se supone (constitución, "
                             "principio 6)")
    vertical = source.declared_vertical or CATALOG.local_vertical(LOCAL_VERTICAL)
    return source.declared_crs, vertical


def _on_grid(path: Path, grid: object, crs: object, vertical: object, temp: Path,
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
        declared, _ = _declared(source, what)
        if declared != crs:
            raise AssertionError(f"{what}: su CRS no es el de la superficie final")
        if source.grid.same_geometry(grid):
            return path
        mdt = gis.Raster(source.grid, source.values, crs, vertical)
        raster, _ = gis.resample_to_grid(mdt, grid,
                                         method=gis.choose_method(source.grid, grid))
    geotiff.GeoTiffIO().write(raster, target, profile=gis.WriteProfile.PROJECT)
    return target


def _base_path(name: str, version: list[Path], bank: list[Path], what: str) -> Path:
    def matching(paths: list[Path]) -> list[Path]:
        return [path for path in paths if path.stem.casefold() == name.casefold()
                and path.suffix.lower() in (*TIFF_SUFFIXES, NPY_SUFFIX)]

    return _one(matching(version) or matching(bank), what)


def build_sources(units: tuple[ReferenceUnit, ...], version: list[Path], bank: list[Path],
                  temp: Path) -> _Surfaces:
    """Las superficies de la cubicación (pasos 2, 3 y 5 de la forma del banco)."""
    final_path = _one(_tiffs(version, FINAL_PATTERN), "la superficie final de la versión")
    final = geotiff.read_geotiff(final_path)
    crs, vertical = _declared(final, "la superficie final")
    grid = final.grid
    start_path = _one(_tiffs(version, START_PATTERN) or _tiffs(bank, START_PATTERN),
                      "la superficie de partida")
    paths = {
        volumes.START: _on_grid(start_path, grid, crs, vertical, temp, "partida",
                                "la superficie de partida"),
        volumes.FINAL: final_path,
    }
    for number, unit in enumerate(units, start=1):
        if unit.base:
            what = f"la base de la unidad {number}"
            paths[volumes.base_role(f"u{number}")] = _on_grid(
                _base_path(unit.base, version, bank, what), grid, crs, vertical, temp,
                f"base_{number}", what)
    sources = {role: surfaces.grid_source(path, name=role, crs=crs, vertical=vertical)
               for role, path in paths.items()}
    return _Surfaces(sources, grid)


# --- La comparación -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnitComparison:
    """Las cifras de una unidad: las de Geoblender y las de la referencia corregidas."""

    label: str
    volume_m3: float
    reference_m3: float
    mass_t: float | None
    reference_t: float

    @staticmethod
    def _difference(found: float | None, expected: float) -> float:
        if found is None:
            return math.inf
        if expected == 0.0:
            return 0.0 if found == 0.0 else math.inf
        return found / expected - 1.0

    @property
    def volume_difference(self) -> float:
        return self._difference(self.volume_m3, self.reference_m3)

    @property
    def mass_difference(self) -> float:
        return self._difference(self.mass_t, self.reference_t)


@dataclass(frozen=True, slots=True)
class Comparison:
    """Las cifras de la versión vigente del banco."""

    cell_area_m2: float
    nominal_m2: float
    cut_m3: float
    units: tuple[UnitComparison, ...]


def _column(units: tuple[ReferenceUnit, ...]) -> object:
    return materials.MaterialColumn(tuple(
        materials.Unit(f"u{number}", f"Unidad {number}", "natural", unit.role, "in_situ",
                       base=surfaces.SurfaceRef(dataset=f"base_{number}") if unit.base else None)
        for number, unit in enumerate(units, start=1)))


def nominal_area(grid: object) -> float:
    """El área nominal de la celda: el producto de los pasos redondeados al centímetro."""
    return round(grid.dx, 2) * round(grid.dy, 2)


def compare(folder: Path) -> Comparison:
    """CE-011-05 sobre el banco ``folder`` (véase el módulo)."""
    version_folder = find_version(folder)
    version = _files(version_folder)
    bank = _files(folder)
    units = read_reference(version)
    column = _column(units)
    request = volumes.VolumeRequest(
        NAME, surfaces.SurfaceRef(dataset="partida"), surfaces.SurfaceRef(dataset="final"),
        column=column)
    with tempfile.TemporaryDirectory(prefix="gb-banco-011-") as temp:
        built = build_sources(units, version, bank, Path(temp))
        steps = list(volumes.volume_steps(request, built.sources))
    result = steps[-1].result
    params = {res_params.density_key(f"u{number}"): unit.density_t_m3
              for number, unit in enumerate(units, start=1) if unit.density_t_m3 is not None}
    weighed = volumes.tonnage_outputs(result.rows, column, params, name=NAME).result
    found = result.kernel.unit_volume_m3[kernel.ALL]
    area, nominal = built.grid.cell_area, nominal_area(built.grid)
    factor = area / nominal
    compared = tuple(
        UnitComparison(f"unidad {number} de {len(units)}", float(found[number - 1]),
                       unit.volume_m3 * factor, weighed.row(f"u{number}").mass_t,
                       unit.mass_t * factor)
        for number, unit in enumerate(units, start=1))
    return Comparison(area, nominal, result.cut_m3, compared)


def _line(result: Comparison, unit: UnitComparison) -> str:
    mass = "sin toneladas" if unit.mass_t is None else f"{_number(unit.mass_t)} t"
    return (
        f"{NAME} (banco del proyecto de referencia, versión vigente, {unit.label}): "
        f"Geoblender {_number(unit.volume_m3)} m³ y {mass}; referencia corregida "
        f"(×{_number(result.cell_area_m2 / result.nominal_m2, 9)}: celda de "
        f"{_number(result.cell_area_m2, 10)} m² frente a {_number(result.nominal_m2, 4)} m²) "
        f"{_number(unit.reference_m3)} m³ ({_percent(unit.volume_difference)}) y "
        f"{_number(unit.reference_t)} t ({_percent(unit.mass_difference)}); tolerancia "
        f"±0,01 % (D-14 d); desmonte total {_number(result.cut_m3)} m³"
    )


class ReferenceVolumesTest(unittest.TestCase):
    """CE-011-05 con el banco del proyecto de referencia (RF-011-12, RF-011-16)."""

    result: Comparison | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = None
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
        result = compare(folder)
        for unit in result.units:
            _report(_line(result, unit))
        cls.result = result

    def test_units_split_the_cut(self) -> None:
        """RF-011-12: las unidades de la columna de la versión vigente parten su desmonte: la
        suma de sus volúmenes es el desmonte de la cubicación (≤ 10⁻⁹, D-14 b)."""
        total = sum(unit.volume_m3 for unit in self.result.units)
        self.assertGreater(self.result.cut_m3, 0.0)
        self.assertLessEqual(abs(total - self.result.cut_m3), 1e-9 * self.result.cut_m3)

    def test_volume_by_unit_matches_the_reference(self) -> None:
        """CE-011-05, RF-011-12: el volumen de cada unidad coincide ±0,01 % con el del
        proyecto de referencia corregido por el área real de la celda (D-14 d)."""
        for unit in self.result.units:
            with self.subTest(unit=unit.label):
                self.assertLessEqual(abs(unit.volume_difference), TOLERANCE)

    def test_tonnes_by_unit_match_the_reference(self) -> None:
        """CE-011-05, RF-011-16: las toneladas de cada unidad (in situ, V·ρ con la densidad
        de la referencia) coinciden ±0,01 % con las del proyecto de referencia corregidas por
        el área real de la celda (D-14 d)."""
        for unit in self.result.units:
            with self.subTest(unit=unit.label):
                self.assertIsNotNone(unit.mass_t)
                self.assertLessEqual(abs(unit.mass_difference), TOLERANCE)


if __name__ == "__main__":
    unittest.main()
