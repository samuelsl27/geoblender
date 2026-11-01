# SPDX-License-Identifier: GPL-3.0-or-later
"""Banco del proyecto de referencia: las restricciones de su versión vigente frente a sus tres
superficies (spec 012, T32; CE-012-08; HU-012-5; RF-012-21, RF-012-22; plan 012 §7.1,
«Banco privado»; constitución, principio 2).

CE-012-08: con el banco privado del proyecto de referencia, las restricciones de su versión
vigente verifican sus tres superficies con CA-2 (0 m³ de corte en los recintos 2 a 5) y CA-13
(0 m³ de corte fuera del límite legal y 0 m³ de movimiento fuera del perímetro de actuación) a
0 m³, y su perímetro sin intersecar con el límite legal reproduce los 1.126 m² de relleno fuera
del límite legal del error 27 con la diferencia explicada. Cada diferencia la explica la persona
que lo ejecuta (hito H3).

Lo ejecuta el arnés de los bancos de la 001 (``tools/bench_silvestre.py``) solo con
``tools/check.py --banco`` y con ``GEOBLENDER_SILVESTRE_DIR`` apuntando a la carpeta del banco;
sin la variable (o si no es una carpeta), se omite. **Solo lectura**: los GeoPackage se copian a
una carpeta temporal de ``%TEMP%`` (``gis.vector.copy_source``: nunca se abren los del banco),
los GeoTIFF solo se leen, y el arnés comprueba que la carpeta queda igual (RNF-001-05). Ni la
ruta ni el nombre de ningún fichero, capa o versión del banco se escriben aquí ni en la salida:
solo «superficie i de n» y las cifras de la comparación.

**La forma del banco** (sin nombres de ficheros: patrones; todo se busca en la carpeta y sus
subcarpetas, sin seguir enlaces, en un orden fijo; la versión vigente primero y, si no está
allí, el resto del banco; las copias iguales, mismo sha256, cuentan como una; los GeoPackage por
el nombre del fichero y por su CRS). Es la de las salidas por versión y las entradas del proyecto
de referencia que describe su análisis (``Documentacion/analisis_proyecto_silvestre``, 01 §2.5
y §4, [9]); si el banco real no la tiene, la comparación dice **todo** lo que no encuentra, se
ve en el H3 y se adapta (nunca el banco):

1. **La versión vigente** y **la superficie de partida**: como en ``test_res_volumes``.
2. **Las tres superficies de diseño**: los GeoTIFF de la versión vigente con ``Superficie_`` en
   el nombre (menos los sombreados y la de partida): exactamente tres. Declaran su CRS (nunca se
   supone: si no, la comparación falla); si alguna tiene otra rejilla que la primera, se lleva a
   ella con el remuestreo de Geoblender (el método por defecto, RF-006-11), en un temporal. La
   rejilla de la primera es la de las máscaras.
3. **El límite legal**: el GeoPackage con «concesión», «catastro» o «límite legal» en el nombre;
   **el perímetro de actuación**: el de «límites_v<n>» o «perímetro»; **los recintos**: el de
   «recinto» o «PIT». Cada uno con una capa de polígonos en el CRS de las superficies (las capas
   de otro CRS se descartan y se cuentan).
4. **Los recintos 1 a 6** (01 §2.5): una entidad por zona; su número, el primer entero del
   primer campo ``zona``, ``recinto``, ``nombre``, ``name`` o ``id`` que lo tenga (si ninguno, el
   número de entidad). Se declaran las zonas 2 y 3 (no se tocan y hay que darles acceso) como
   «Intocable», las 4 y 5 (restauración al 100 %, sin excavación) como «Solo restauración» y la 6
   («preferiblemente a no afectar») como «Preferible no afectar»; la 1 (el área de excavación)
   no es una restricción. Faltan zonas: se dice cuáles.

**Lo declarado** (``core.constraints.provenance.constraints_from_entities``, como «Crear desde una
capa»): el límite legal y el perímetro (uno por entidad) y los recintos, con motivo y decisor de
la comparación, **sin resguardo** (0 m; el de 10 m de la explotación es un parámetro de diseño
que no entra en CA-2 ni en CA-13) y el peso 1 de la zona 6 (sin juicio). Se compilan sobre la
rejilla de la primera superficie con ``gis.masks.compile`` y se verifica cada superficie frente
a la de partida con ``reserves.compliance`` y el espesor mínimo de 0,02 m (D-6).

**La comparación**: (a) el informe de los límites: el perímetro sin intersecar sobresale del
límite legal (error 45: la franja es > 0 m²); (b) CA-2 y CA-13 a 0 m³ en cada superficie
(``counted_m3`` exactamente 0: basta una celda por encima del espesor mínimo para no cumplir); (c)
el relleno fuera del límite legal (el área de las celdas que no están enteras dentro del límite
legal cuyo relleno pasa del espesor mínimo, recontado aparte con las rejillas), de la superficie
que más tiene, frente a los 1.126 m² del error 27 de la referencia, que contó celdas nominales:
``1.126 · A / A_nominal`` (``A`` el área real de la celda; ``A_nominal`` el producto de los pasos
al centímetro, como en CE-011-05). La diferencia admitida es la que explica la regla de borde de
D-1: Geoblender cuenta como fuera del límite las celdas que no están enteras dentro, y el
proyecto de referencia, las celdas de su centro (u otra regla); solo puede diferir en las celdas
de borde (las de fuera contiguas, de lado o esquina, a una celda entera dentro) con relleno,
más medio m² nominal del redondeo de la referencia. Las cifras se imprimen en líneas
``CE-012-08: …``, para anotarlas en la verificación del H3.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np

from tests.support import bank_folder as shape
from tests.support.bank_folder import ENV, BankShapeError
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
geotiff = import_geoblender("gis.geotiff")
vector = import_geoblender("gis.vector")
gis_messages = import_geoblender("gis.messages")
model = import_geoblender("core.constraints.model")
cparams = import_geoblender("core.constraints.params")
cprov = import_geoblender("core.constraints.provenance")
combine = import_geoblender("gis.masks.combine")
compile_mod = import_geoblender("gis.masks.compile")
overlay = import_geoblender("gis.masks.overlay")
compliance = import_geoblender("reserves.compliance")

T = model.ConstraintType
P = model.ConstraintParam

NAME = "CE-012-08"  # el nombre de las líneas de la comparación
SURFACES = 3
"""Las superficies de diseño de la versión vigente (CA-13: «en las tres superficies»)."""
REFERENCE_FILL_OUTSIDE_M2 = 1126.0
"""El relleno fuera de la concesión del error 27 (m², celdas nominales de la referencia)."""
MIN_THICKNESS_M = 0.02
"""El espesor mínimo de verificación (D-6; el del proyecto de referencia)."""
BUFFER_M = 0.0
AVOID_WEIGHT = 1.0
DECLARED_ON = date(2026, 11, 1)
DECLARED_BY = "Comparación del banco (CE-012-08)"
REASON = "Declarada por la comparación del banco (CE-012-08)"
BUDGET_S = 60.0
"""Lo que dura un paso de compilar como mucho: todo de una vez, no hay interfaz que atender."""

LEGAL_PATTERN = re.compile(r"(?i)concesi|catastro|l[ií]mite[_ ]legal")
PERIMETER_PATTERN = re.compile(r"(?i)(?<![a-z])l[ií]mites?[_ ]?v\d+|per[ií]metro")
ZONES_PATTERN = re.compile(r"(?i)recinto|(?<![a-z])pit(?![a-z])")
SURFACE_PATTERN = re.compile(r"(?i)superficie[_ ]")
SHADE_PATTERN = re.compile(r"(?i)sombread|hillshade")
GPKG_SUFFIX = ".gpkg"
POLYGON_TYPES = ("POLYGON", "MULTIPOLYGON", "GEOMETRY")
ZONE_FIELDS = ("zona", "recinto", "nombre", "name", "id")
ZONE_TYPES: Mapping[str, model.ConstraintType] = {
    "2": T.UNTOUCHABLE, "3": T.UNTOUCHABLE, "4": T.RESTORATION_ONLY, "5": T.RESTORATION_ONLY,
    "6": T.AVOID,
}
"""El tipo de cada recinto (01 §2.5); la zona 1, el área de excavación, no es una restricción."""
CA2_ZONES = ("2", "3", "4", "5")
CRITERIA = ("CA-13 corte fuera del límite legal", "CA-13 movimiento fuera del perímetro",
            "CA-2 zonas 2 a 5")


# --- Buscar en el banco ---------------------------------------------------------------------


def _count(found: Sequence[object]) -> str:
    return "ninguna" if not found else f"{len(found)} distintas"


def _gpkgs(paths: list[Path], pattern: re.Pattern[str]) -> list[Path]:
    return [path for path in paths
            if path.suffix.lower() == GPKG_SUFFIX and pattern.search(path.stem)]


def _polygon_layers(paths: list[Path], crs: object, temp: Path
                    ) -> tuple[list[tuple[Path, object]], int]:
    """Las capas de polígonos en el CRS ``crs`` de los GeoPackage ``paths`` (sobre sus copias en
    ``temp``) y cuántas hay en otro CRS."""
    found: list[tuple[Path, object]] = []
    other = 0
    for number, path in enumerate(paths):
        target = temp / f"copia-{len(list(temp.iterdir()))}-{number}"
        target.mkdir()
        try:
            copy = vector.copy_source(path, target)
            layers = vector.list_layers(copy)
        except gis_messages.GisError:
            continue  # ilegible: no es una capa; si falta, se dice
        for info in layers:
            if not info.importable or info.geometry_type not in POLYGON_TYPES:
                continue
            if info.declared_crs is None or info.declared_crs.epsg != crs.epsg:
                other += 1
            else:
                found.append((copy, info))
    return found, other


def _layer(what: str, pattern: re.Pattern[str], version: list[Path], everything: list[Path],
           crs: object, temp: Path, problems: list[str]) -> object | None:
    """La capa de polígonos de ``what`` (véase la forma del banco, punto 3) como
    ``FeatureLayer``; si no está, o hay varias, se anota en ``problems``."""
    found, other = _polygon_layers(shape.distinct(_gpkgs(version, pattern)), crs, temp)
    if not found:
        rest = [path for path in _gpkgs(everything, pattern) if path not in version]
        more, others = _polygon_layers(shape.distinct(rest), crs, temp)
        found, other = more, other + others
    if len(found) != 1:
        extra = f"; {other} capas de polígonos en otro CRS" if other else ""
        problems.append(f"{what}: se esperaba un GeoPackage con una capa de polígonos en el CRS "
                        f"de las superficies (EPSG:{crs.epsg}) y hay {_count(found)}{extra}")
        return None
    copy, info = found[0]
    layer, _ = vector.features_from_layer(vector.read_layer(copy, info.name))
    if layer.kind != "polygon" or not len(layer):
        problems.append(f"{what}: la capa no tiene polígonos")
        return None
    return layer


# --- Lo declarado ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Declared:
    """Las restricciones declaradas del banco con los valores de sus parámetros, el código de
    las de cada zona y cuántas entidades de los recintos no son una restricción."""

    constraints: tuple[model.Constraint, ...]
    resolved: Mapping[str, object]
    zone_codes: Mapping[str, tuple[str, ...]]
    rejected: int


def _first_integer(value: object) -> str | None:
    match = None if value is None else re.search(r"\d+", str(value))
    return None if match is None else str(int(match.group()))


def _zone_numbers(layer: object) -> list[str]:
    """El número de zona de cada entidad de la capa de recintos (punto 4 de la forma)."""
    for wanted in ZONE_FIELDS:
        column = next((item.column for item in layer.columns
                       if item.field.casefold() == wanted), None)
        if column is None:
            continue
        numbers = [_first_integer(value) for value in layer.values[column]]
        if any(number is not None for number in numbers):
            return [number or "" for number in numbers]
    return [str(fid) for fid in layer.fids]


def _entities(layer: object, zones: Sequence[str] | None = None) -> tuple[object, ...]:
    kind = model.GeometryKind(layer.kind)
    return tuple(
        cprov.SourceEntity(int(fid), kind, parts, {} if zones is None else {"zona": zones[index]})
        for index, (fid, parts) in enumerate(zip(layer.fids, layer.parts, strict=True)))


def declare(limit: object, perimeter: object, zones: object, problems: list[str]
            ) -> Declared | None:
    """Declara las restricciones del banco (véase el módulo): el límite legal, el perímetro de
    actuación y los recintos 2 a 6."""
    named: list[tuple[str, object]] = []
    numbers = _zone_numbers(zones)
    by_fid = dict(zip(zones.fids, numbers, strict=True))
    for layer, ctype, title, zone_numbers in (
            (limit, T.LEGAL_LIMIT, "Límite legal", None),
            (perimeter, T.ACTION_PERIMETER, "Perímetro de actuación", None),
            (zones, None, "Zona", numbers)):
        mapping = cprov.LayerMapping(
            ctype=ctype, type_field=None if ctype else "zona",
            type_values=None if ctype else ZONE_TYPES, reason=REASON, decided_by=DECLARED_BY,
            decided_on=DECLARED_ON)
        rows, _ = cprov.constraints_from_entities(
            _entities(layer, zone_numbers), mapping, layer=title, source_input=None)
        for index, row in enumerate(rows, start=1):
            label = f"{title} {by_fid[row.source_fid]}" if zone_numbers else (
                title if len(rows) == 1 else f"{title} {index}")
            named.append((label, row))
    missing = sorted(set(ZONE_TYPES) - {by_fid[row.source_fid] for label, row in named
                                        if label.startswith("Zona")})
    if missing:
        problems.append("los recintos de las zonas " + ", ".join(missing) + " (una entidad por "
                        "zona, con su número en un campo zona, recinto, nombre, name o id)")
        return None
    taken: set[str] = set()
    rows: list[model.Constraint] = []
    codes: dict[str, list[str]] = {}
    for label, row in named:
        code = model.constraint_code(label, taken)
        taken.add(code)
        rows.append(replace(row, name=label, code=code))
        if label.startswith("Zona"):
            codes.setdefault(by_fid[row.source_fid], []).append(code)
    resolved: dict[str, object] = {}
    values = {P.ACTIVE: True, P.BUFFER_OUT: BUFFER_M, P.BUFFER_IN: BUFFER_M,
              P.WEIGHT: AVOID_WEIGHT}
    for row in rows:
        for param in row.ctype.requires:
            resolved[cparams.param_key(row.code, param)] = values[param]
    skipped = sum(1 for number in numbers if number not in ZONE_TYPES)
    return Declared(tuple(rows), resolved, {key: tuple(value) for key, value in codes.items()},
                    skipped)


# --- La comparación -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class SurfaceResult:
    """Una superficie verificada: su etiqueta («superficie i de n»), la verificación por recinto,
    las celdas con relleno fuera del límite legal (recontadas aparte) y, de ellas, las de borde."""

    label: str
    check: object
    fill_cells: int
    edge_fill_cells: int


@dataclass(frozen=True, slots=True, eq=False)
class Comparison:
    """Las cifras de la versión vigente del banco."""

    cell_area_m2: float
    nominal_m2: float
    report: object
    declared: int
    rejected: int
    zone_codes: Mapping[str, tuple[str, ...]]
    surfaces: tuple[SurfaceResult, ...]

    @property
    def best(self) -> SurfaceResult:
        """La superficie con más relleno fuera del límite legal (la primera si hay empate)."""
        return max(self.surfaces, key=lambda item: item.fill_cells)

    @property
    def reference_m2(self) -> float:
        """La cifra de referencia corregida por el área real de la celda (D-14 d)."""
        return REFERENCE_FILL_OUTSIDE_M2 * self.cell_area_m2 / self.nominal_m2

    def difference_m2(self) -> float:
        """Lo que sobra (+) o falta (−) del relleno fuera del límite legal frente a la referencia."""
        return self.best.fill_cells * self.cell_area_m2 - self.reference_m2

    def explained_m2(self) -> tuple[float, float]:
        """La diferencia que se admite: (mínima, máxima), la regla de borde de D-1 y el redondeo
        de la referencia al m² nominal."""
        rounding = 0.5 * self.cell_area_m2 / self.nominal_m2
        return -rounding, self.best.edge_fill_cells * self.cell_area_m2 + rounding


def nominal_area(grid: object) -> float:
    """El área nominal de la celda: el producto de los pasos redondeados al centímetro."""
    return round(grid.dx, 2) * round(grid.dy, 2)


def _fill_outside(classes: np.ndarray, start: np.ndarray, final: np.ndarray) -> tuple[int, int]:
    """Las celdas con relleno (que pasa del espesor mínimo) fuera del límite legal y, de ellas,
    las de borde: las de fuera contiguas (8 vecinas) a una celda entera dentro."""
    legal = (classes & np.uint16(combine.ClassBit.LEGAL)) != 0
    with np.errstate(invalid="ignore"):
        fill = (final - start) > MIN_THICKNESS_M
    height, width = legal.shape
    padded = np.pad(legal, 1)
    near = np.zeros_like(legal)
    for dr in (0, 1, 2):
        for dc in (0, 1, 2):
            near |= padded[dr:dr + height, dc:dc + width]
    outside = fill & ~legal
    return int(np.count_nonzero(outside)), int(np.count_nonzero(outside & near))


def _compile(declared: Declared, grid: object) -> object:
    request = compile_mod.CompileRequest(declared.constraints, declared.resolved, grid=grid)
    last = None
    for step in compile_mod.compile_steps(request, budget_s=BUDGET_S):
        last = step
    return last.result


def _check_zones(result: object) -> tuple[object, ...]:
    """Los recintos de la verificación, como los da la compilación (``gis_mskz_``)."""
    prepared = result.prepared
    zones = {code: zone.runs for code, zone in prepared.zones.items()}
    for code in prepared.limits.legal_codes:
        zones[f"{code}{compliance.INNER_SUFFIX}"] = prepared.limits.legal_bands[code]
    ctypes = {code: zone.ctype for code, zone in prepared.zones.items()}
    weights = {code: zone.weight for code, zone in prepared.zones.items()
               if zone.weight is not None}
    return compliance.check_zones(result.masks.classes, zones, ctypes, weights)


def compare(folder: Path) -> Comparison:
    """CE-012-08 sobre el banco ``folder`` (véase el módulo)."""
    version = shape.files(shape.find_version(folder))
    everything = shape.files(folder)
    problems: list[str] = []
    paths = shape.distinct([
        path for path in shape.tiffs(version, SURFACE_PATTERN)
        if not SHADE_PATTERN.search(path.stem) and not shape.START_PATTERN.search(path.stem)])
    if len(paths) != SURFACES:
        problems.append(f"las superficies de diseño de la versión vigente (GeoTIFF con "
                        f"«Superficie_» en el nombre, sin sombreados ni la de partida): se "
                        f"esperaban {SURFACES} y hay {len(paths)}")
    starts = shape.distinct(shape.tiffs(version, shape.START_PATTERN)
                            or shape.tiffs(everything, shape.START_PATTERN))
    if len(starts) != 1:
        problems.append("la superficie de partida (GeoTIFF con MDT, DEM, DTM o terreno en el "
                        f"nombre): se esperaba una y hay {_count(starts)}")
    if not paths:
        raise BankShapeError(_shape_message(problems))
    first = geotiff.read_geotiff(paths[0])
    crs, vertical = shape.declared(first, "la primera superficie de diseño")
    grid = first.grid
    with tempfile.TemporaryDirectory(prefix="gb-banco-012-") as name:
        temp = Path(name)
        limit = _layer("el límite legal", LEGAL_PATTERN, version, everything, crs, temp, problems)
        perimeter = _layer("el perímetro de actuación", PERIMETER_PATTERN, version, everything,
                           crs, temp, problems)
        zones = _layer("los recintos", ZONES_PATTERN, version, everything, crs, temp, problems)
        declared = (declare(limit, perimeter, zones, problems)
                    if None not in (limit, perimeter, zones) else None)
        if problems or declared is None or len(starts) != 1:
            raise BankShapeError(_shape_message(problems))

        def values(path: Path, role: str, what: str) -> np.ndarray:
            ready = shape.on_grid(path, grid, crs, vertical, temp, role, what)
            return geotiff.read_geotiff(ready).values

        result = _compile(declared, grid)
        zones_to_check = _check_zones(result)
        start = values(starts[0], "partida", "la superficie de partida")
        checked = []
        for number, path in enumerate(paths, start=1):
            final = values(path, f"final-{number}", f"la superficie de diseño {number}")
            check = compliance.check(grid, zones_to_check, start, final, MIN_THICKNESS_M)
            cells, edge = _fill_outside(result.masks.classes, start, final)
            checked.append(SurfaceResult(f"superficie {number} de {len(paths)}", check, cells,
                                         edge))
    return Comparison(grid.cell_area, nominal_area(grid), result.report, len(declared.constraints),
                      declared.rejected, declared.zone_codes, tuple(checked))


def _shape_message(problems: Sequence[str]) -> str:
    return ("el banco no tiene la forma que espera la comparación (véase el docstring de la "
            "comparación); no se encuentra:\n  - " + "\n  - ".join(problems))


# --- Salida en español ----------------------------------------------------------------------


def _where() -> str:
    return f"{NAME} (banco del proyecto de referencia, versión vigente"


def limits_line(result: Comparison) -> str:
    report = result.report
    outside = len(report.outside)
    return (
        f"{_where()}): restricciones declaradas: {result.declared}; entidades de los recintos "
        f"sin restricción: {result.rejected}; límite legal {shape.number(report.legal_ha, 2)} "
        f"ha, perímetro {shape.number(report.perimeter_ha, 2)} ha, intersección "
        f"{shape.number(report.intersection_ha, 2)} ha, franja perímetro ∖ límite legal "
        f"{shape.number(report.strip_ha, 2)} ha ({shape.number(report.strip_m2)} m²; partes: "
        f"{len(report.strip_parts)}); restricciones con parte fuera de la rejilla: {outside}"
    )


def surface_line(result: Comparison, item: SurfaceResult) -> str:
    check = item.check
    legal = check.zone(compliance.OUTSIDE_LEGAL)
    perimeter = check.zone(compliance.OUTSIDE_PERIMETER)
    ca2 = sum(check.zone(code).counted_m3 for number in CA2_ZONES
              for code in result.zone_codes[number])
    avoid = [check.zone(code) for code in result.zone_codes["6"]]
    return (
        f"{_where()}, {item.label}): fuera del límite legal, corte "
        f"{shape.number(legal.cut_m3)} m³ y relleno {shape.number(legal.fill_m3)} m³ "
        f"({shape.number(legal.moved_m2)} m² con movimiento); fuera del perímetro "
        f"{shape.number(perimeter.counted_m3)} m³; zonas 2 a 5 (CA-2) {shape.number(ca2)} m³; "
        f"zona 6 (informada) {shape.number(sum(zone.cut_m3 for zone in avoid))} m³ de corte y "
        f"{shape.number(sum(zone.fill_m3 for zone in avoid))} m³ de relleno en "
        f"{shape.number(sum(zone.moved_m2 for zone in avoid))} m²; recintos que no cumplen: "
        f"{sum(1 for zone in check.totals if zone.verdict is compliance.Verdict.FAILS)}"
    )


def fill_line(result: Comparison) -> str:
    best = result.best
    low, high = result.explained_m2()
    return (
        f"{_where()}, perímetro sin intersecar, {best.label}): relleno fuera del límite legal "
        f"Geoblender {shape.number(best.fill_cells * result.cell_area_m2)} m² "
        f"({best.fill_cells} celdas de {shape.number(result.cell_area_m2, 6)} m²); referencia "
        f"{shape.number(REFERENCE_FILL_OUTSIDE_M2)} m² corregida (×"
        f"{shape.number(result.cell_area_m2 / result.nominal_m2, 9)}: celda real frente a "
        f"nominal de {shape.number(result.nominal_m2, 4)} m²) "
        f"{shape.number(result.reference_m2, 2)} m²; diferencia "
        f"{shape.number(result.difference_m2(), 2)} m² "
        f"({shape.percent(result.difference_m2() / result.reference_m2, 3)}); la regla de borde "
        f"del límite legal (D-1) admite de {shape.number(low, 2)} a {shape.number(high, 2)} m² "
        f"({best.edge_fill_cells} celdas de borde con relleno)"
    )


class ReferenceConstraintsTest(unittest.TestCase):
    """CE-012-08 con el banco del proyecto de referencia (RF-012-21, RF-012-22)."""

    result: Comparison | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = None
        result = compare(shape.bank_folder())
        shape.report(limits_line(result))
        for item in result.surfaces:
            shape.report(surface_line(result, item))
        shape.report(fill_line(result))
        cls.result = result

    def test_the_perimeter_sticks_out_of_the_legal_limit(self) -> None:
        """CE-012-08 (errores 27 y 45): el perímetro de actuación sin intersecar sobresale del
        límite legal, con una franja de área > 0 m² (que RF-012-05 lista), sobre un límite
        legal y un perímetro con área."""
        report = self.result.report
        self.assertGreater(report.legal_m2, 0.0)
        self.assertGreater(report.perimeter_m2, 0.0)
        self.assertFalse(report.perimeter_from_legal)
        self.assertGreater(report.strip_m2, 0.0)

    def test_ca2_and_ca13_are_zero_in_every_surface(self) -> None:
        """CE-012-08, RF-012-21, RF-012-22 (CA-2, CA-13): en cada una de las tres superficies,
        0 m³ de corte fuera del límite legal, 0 m³ de movimiento fuera del perímetro y 0 m³ de
        corte en los recintos 2 a 5 (cualquier celda por encima del espesor mínimo incumple)."""
        self.assertEqual(len(self.result.surfaces), SURFACES)
        for item in self.result.surfaces:
            check = item.check
            volumes = (
                check.zone(compliance.OUTSIDE_LEGAL).counted_m3,
                check.zone(compliance.OUTSIDE_PERIMETER).counted_m3,
                sum(check.zone(code).counted_m3 for number in CA2_ZONES
                    for code in self.result.zone_codes[number]),
            )
            for criterion, volume in zip(CRITERIA, volumes, strict=True):
                with self.subTest(surface=item.label, criterion=criterion):
                    self.assertEqual(volume, 0.0, f"{shape.number(volume)} m³ incumplen")

    def test_unintersected_perimeter_reproduces_the_fill_outside(self) -> None:
        """CE-012-08, RF-012-21 (error 27): el relleno fuera del límite legal, con el perímetro
        sin intersecar, de la superficie que más tiene reproduce los 1.126 m² de la referencia
        (corregidos por el área real de la celda) salvo lo que explica la regla de borde de D-1;
        y coincide con el área con movimiento que da la verificación fuera del límite legal."""
        result = self.result
        best = result.best
        low, high = result.explained_m2()
        difference = result.difference_m2()
        self.assertGreater(best.fill_cells, 0)
        self.assertTrue(low <= difference <= high,
                        f"diferencia de {shape.number(difference, 2)} m² fuera de lo que "
                        f"explica la regla de borde ({shape.number(low, 2)} a "
                        f"{shape.number(high, 2)} m²)")
        outside = best.check.zone(compliance.OUTSIDE_LEGAL)
        if outside.cut_m3 == 0.0:  # todo el movimiento fuera del límite legal es relleno
            counted = best.fill_cells * result.cell_area_m2
            self.assertLessEqual(abs(outside.moved_m2 - counted), 1e-9 * max(counted, 1.0))


if __name__ == "__main__":
    unittest.main()
