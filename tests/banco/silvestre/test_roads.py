# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de las pistas y rampas (spec 017, T36; CE-017-10; HU-017-1; RF-017-13, RF-017-15, RF-017-21, RF-017-24; plan 017 §7.1, §7.2 y §8; D-22; ``spec.md`` §11;
``docs/decisiones-pendientes.md``).

Solo la ejecuta el arnés de los bancos con el banco real (``tools/check.py --banco``, con ``GEOBLENDER_SILVESTRE_DIR``, de solo lectura); sin él, se omite.
``tests/unit/design/test_road_bank.py`` comprueba, con datos sintéticos y en el «verde», sus ayudas y que se omite.

**Lo que el banco trae y lo que no** (dicho al ejecutarla, sin nombrar ningún fichero): trae la verificación de la V10 con su criterio CA-6 (las **cifras** de las pistas del molino
y del taller —longitud, cotas, desnivel, pendiente media y máxima, calzada y plataforma— y la **cota mínima alcanzable** sobre la superficie restaurada), y las superficies de
explotación y final de la V10 en su rejilla de 1 m (1.654 × 1.699 celdas), donde esas cifras se midieron. **No trae** lo que hace falta para que Geoblender calcule las mismas pistas:
**el croquis de la propiedad con el eje de la pista principal «opción A15»** (608 m, 10,5 % de media, 15,0 % de máxima en 10 m, radio mínimo de 12,1 m, desmonte de 5.076 m³ y
terraplén de 9.336 m³ de ``s124``: son solo las cifras de la documentación; los croquis del banco son marcas de diseño —taludes, zonas, barrancos—, sin ninguna línea de pista), **los
ejes de las pistas del molino y del taller** (la capa de pistas de la V10) ni **los puntos de entrada** de la accesibilidad (la pista nace a 128,8 m, pero no se dice dónde: esa cota
la tienen muchas celdas) ni los umbrales de pendiente y de ancho transitables con que se midió 136,5 m. Sin los ejes, Geoblender no tiene qué calcular, y **no se inventan**: la
comparación con las tolerancias de D-22 (:func:`outside`) está escrita y probada con datos sintéticos, y ``test_the_comparison_with_the_original_axes_needs_them`` **se omite** con ese
motivo (**no cuenta como verde**, ``definicion-de-hecho.md`` §3: CE-017-10 queda «sin ejecutar con los datos originales», como CE-016-08) y, si algún día el banco trae un eje, **falla**
en vez de seguir omitiéndose: entonces se escribe su lectura (:func:`figures_of` pone las cifras de una pista de Geoblender como las de la referencia). Lo que sí se contrasta aquí
son las cifras que el banco trae: las de la referencia con las de la spec, a las tolerancias de D-22, y con las superficies donde se midieron.

**La forma del banco** (patrones, sin nombres de ficheros; sin suponer la forma de la carpeta, como las demás comparaciones): la verificación, un ``.json`` ``V<nn>_verificacion``
con ``CA-6`` (``pistas``: una lista con la pista cuyo nombre dice «molino» y la que dice «taller», cada una con ``long_m``, ``cota_ini``, ``cota_fin``, ``desnivel_m``,
``pend_media_pct``, ``pend_max_pct``, ``calzada_m`` y ``plataforma_m``; y ``cota_min_alcanzable_sup_restaurada``) y dos GeoTIFF ``V<nn>_Superficie_excavacion`` (la de explotación)
y ``V<nn>_Superficie_final`` (la restaurada); de cada uno se toma la versión de número mayor. Lo que no está se omite con su motivo; lo que está y no tiene esa forma falla.

**Las tolerancias de D-22 y cómo se leen** (HIPÓTESIS: el eje es otro, una *spline* de la referencia frente a curvas circulares): la longitud y las pendientes, ±2 % **relativo** a la
cifra de la referencia (no ±2 puntos); los volúmenes, ±10 %; el radio mínimo, **mayor o igual** que el de la referencia (sin curvas no hay radio más cerrado: cumple). La pendiente
máxima de la V10 es **en 10 m**: Geoblender la mide entre estaciones consecutivas, así que se compara con una pista de estación ``w`` de 10 m. Nunca se ajusta una tolerancia para que
pase.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import unittest
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import bank_folder as bank
from tests.support import road_data as rd
from tests.support.bank_folder import BankShapeError
from tests.support.package import import_geoblender

geotiff = import_geoblender("gis.geotiff")
road_profiles = import_geoblender("design.road_profiles")

NAME = "CE-017-10"
LENGTH_TOLERANCE = 0.02
SLOPE_TOLERANCE = 0.02
VOLUME_TOLERANCE = 0.10
"""D-22: la longitud y las pendientes ±2 % y los volúmenes ±10 %, relativos a la cifra de la referencia; el radio mínimo, no menor que el de la referencia."""
ROUNDING_M = 0.15
"""Las cotas y el desnivel de la verificación van redondeados a 0,1 m: el desnivel difiere de la resta de las cotas en 0,05 + 0,05 + 0,05 m como mucho."""
ROUNDING_PCT = 0.05
"""Las pendientes de la verificación van redondeadas a 0,1 %: media 0,05 puntos."""
LEVEL_M = 136.5
"""La cota mínima alcanzable sobre la superficie restaurada de la V10 (spec 017 §11 y CE-017-10), redondeada a 0,1 m: la verificación da 136,5234 m."""
LEVEL_TOLERANCE_M = 0.05
"""Medio decimal de la cota de la spec (136,5 m)."""
CELL_TOLERANCE_M = 1e-5
"""Lo que una celda de la superficie puede diferir de la cota de la verificación y ser «esa celda»: menos que la cuantización de un float32 a 140 m (1,5·10⁻⁵ m), es decir, la misma cifra."""
LEVEL_REACH_M = 0.05
"""Lo que una celda de la explotación puede diferir de la cota de inicio o de fin de una pista (que van a 0,1 m) y contarse como «de esa cota»."""
MILL_PATTERN = re.compile(r"(?i)molino")
WORKSHOP_PATTERN = re.compile(r"(?i)taller")
VERIFICATION_PATTERN = re.compile(r"(?i)^v(\d+)_verificaci[oó]n\.json$")
EXPLOITATION_PATTERN = re.compile(r"(?i)^v(\d+)_superficie_(?:excavaci[oó]n|explotaci[oó]n)\.tiff?$")
FINAL_PATTERN = re.compile(r"(?i)^v(\d+)_superficie_(?:final|restaurad[ao])\.tiff?$")
AXIS_PATTERN = re.compile(r"(?i)pista|a15|molino|taller")
"""Lo que, en el nombre de una capa o en un valor de su campo de nombre, hace pensar que el banco trae el eje de una pista."""
NAME_COLUMNS = ("capa", "nombre", "name")
GEOPACKAGE_SUFFIX = ".gpkg"


@dataclass(frozen=True, slots=True)
class RoadFigures:
    """Las cifras de una pista con las que se compara con la referencia (D-22): la longitud del eje (m), las pendientes media y máxima (%), el radio mínimo (m; ``None`` sin curvas) y el
    desmonte y el terraplén (m³; ``None`` si no se dan: las pistas del molino y del taller no traen volúmenes)."""

    length_m: float
    mean_pct: float
    max_pct: float
    min_radius_m: float | None = None
    cut_m3: float | None = None
    fill_m3: float | None = None


A15 = RoadFigures(608.0, 10.5, 15.0, 12.1, 5_076.0, 9_336.0)
"""La pista principal «opción A15» de la propiedad (``s124``, 03 §3.9; spec 017 §11 y CE-017-10): 608 m, 10,5 % de media, 15,0 % de máxima en 10 m, radio mínimo de 12,1 m, desmonte de
5.076 m³ y terraplén de 9.336 m³. **El banco no trae su croquis**: son las cifras de la documentación."""
MILL = RoadFigures(1_034.0, 7.0, 10.0)
"""La pista de alimentación al molino sobre la explotación de la V10 (spec 017 §11 y CE-017-10): 1.034 m, 7,0 % de media y 10,0 % de máxima."""
WORKSHOP = RoadFigures(685.0, 8.1, 10.0)
"""El acceso al taller y a la zona de acopio (spec 017 §11 y CE-017-10): 685 m, 8,1 % de media y 10,0 % de máxima."""


class NotInBank(BankShapeError):
    """El banco no trae lo que se busca (la comparación se omite con su motivo, no falla)."""


@dataclass(frozen=True, slots=True)
class ReferenceRoad:
    """Una pista de la verificación CA-6 de la referencia: su nombre, su longitud (m), sus cotas de inicio y de fin y su desnivel (m), sus pendientes media y máxima (%) y las anchuras de su
    calzada y de su plataforma (m)."""

    name: str
    length_m: float
    z_start_m: float
    z_end_m: float
    drop_m: float
    mean_pct: float
    max_pct: float
    carriageway_m: float
    platform_m: float

    @property
    def figures(self) -> RoadFigures:
        """Las cifras de la comparación (la longitud y las pendientes; la verificación no trae ni radio ni volúmenes)."""
        return RoadFigures(self.length_m, self.mean_pct, self.max_pct)


# --- La tolerancia de D-22 ----------------------------------------------------------------------------------------


def relative(found: float, wanted: float) -> float:
    """La diferencia relativa de ``found`` frente a ``wanted`` (``found / wanted − 1``); ``ValueError`` con una referencia que no es positiva."""
    if not wanted > 0.0:
        raise ValueError(f"la cifra de la referencia ha de ser positiva para compararla (es {wanted!r})")
    return found / wanted - 1.0


def _differs(found: float | None, wanted: float | None, tolerance: float) -> bool:
    """Si ``found`` difiere de ``wanted`` más de ``tolerance`` (relativo); sin cifra de la referencia no se compara y, con ella y sin la de la pista, queda fuera."""
    if wanted is None:
        return False
    return found is None or abs(relative(found, wanted)) > tolerance


def outside(found: RoadFigures, wanted: RoadFigures) -> list[str]:
    """Lo que de ``found`` queda fuera de la tolerancia de D-22 frente a ``wanted``, en este orden: ``longitud``, ``pendiente media``, ``pendiente máxima``, ``radio mínimo``, ``desmonte``,
    ``terraplén``. Las pendientes y la longitud, ±2 %; los volúmenes, ±10 % (solo si la referencia los tiene); el radio mínimo, no menor que el de la referencia (sin curvas, cumple)."""
    problems = []
    if _differs(found.length_m, wanted.length_m, LENGTH_TOLERANCE):
        problems.append("longitud")
    if _differs(found.mean_pct, wanted.mean_pct, SLOPE_TOLERANCE):
        problems.append("pendiente media")
    if _differs(found.max_pct, wanted.max_pct, SLOPE_TOLERANCE):
        problems.append("pendiente máxima")
    if wanted.min_radius_m is not None and found.min_radius_m is not None and found.min_radius_m < wanted.min_radius_m:
        problems.append("radio mínimo")
    if _differs(found.cut_m3, wanted.cut_m3, VOLUME_TOLERANCE):
        problems.append("desmonte")
    if _differs(found.fill_m3, wanted.fill_m3, VOLUME_TOLERANCE):
        problems.append("terraplén")
    return problems


# --- Las cifras de una pista de Geoblender, como las de la referencia ---------------------------------------------


def figures_of(figures: Iterable[Any]) -> RoadFigures:
    """Las cifras de una pista de Geoblender (``RoadOutcome.figures``: ``FigureSpec`` de RF-017-23) como las de la referencia: la longitud, las pendientes media y máxima, el radio mínimo
    (``None`` sin curvas) y el desmonte y el terraplén **de la sección y del borde juntos** (``None`` si no los trae). ``KeyError`` con la cifra que falta si no es una pista."""
    by_key = {figure.key: figure.value for figure in figures}

    def need(key: str) -> float:
        value = by_key.get(key)
        if value is None:
            raise KeyError(key)
        return float(value)

    def total(section: str, edge: str) -> float | None:
        if by_key.get(section) is None or by_key.get(edge) is None:
            return None
        return float(by_key[section]) + float(by_key[edge])

    radius = by_key.get("des.road_radius_min_m")
    return RoadFigures(need("des.road_length_m"), need("des.road_gradient_mean_pct"), need("des.road_gradient_max_pct"), None if radius is None else float(radius),
                       total("des.road_cut_m3", "des.road_edge_cut_m3"), total("des.road_fill_m3", "des.road_edge_fill_m3"))


def widths_of(profile: Any) -> tuple[float, float]:
    """La anchura de la calzada y la de la plataforma (la sección) que derivan de un perfil de pista (``road_profiles.derived``), en m."""
    widths = road_profiles.derived(profile)
    return float(widths.carriageway_m), float(widths.section_m)


# --- La verificación de la referencia ------------------------------------------------------------------------------


def _check(verification: Mapping[str, Any]) -> Mapping[str, Any]:
    check = verification.get("CA-6")
    if not isinstance(check, Mapping):
        raise BankShapeError("la verificación del banco no trae el criterio CA-6 (las pistas y la cota mínima alcanzable)")
    return check


def _number(item: Mapping[str, Any], key: str, what: str) -> float:
    if key not in item:
        raise BankShapeError(f"{what}: falta «{key}»")
    value = item[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BankShapeError(f"{what}: «{key}» no es un número")
    return float(value)


def reference_roads(verification: Mapping[str, Any]) -> tuple[ReferenceRoad, ReferenceRoad]:
    """Las pistas del molino y del taller de la verificación CA-6 de la referencia (las que su nombre dice, sin importar mayúsculas), en ese orden. :class:`BankShapeError` con lo que falta o
    no es un número."""
    pistas = _check(verification).get("pistas")
    if not isinstance(pistas, Sequence) or isinstance(pistas, str) or not pistas:
        raise BankShapeError("CA-6 de la verificación del banco no trae «pistas»")
    found = []
    for label, pattern in (("molino", MILL_PATTERN), ("taller", WORKSHOP_PATTERN)):
        matching = [item for item in pistas if isinstance(item, Mapping) and pattern.search(str(item.get("nombre", "")))]
        if len(matching) != 1:
            raise BankShapeError(f"CA-6 de la verificación del banco: se esperaba una pista del {label} y hay {len(matching)}")
        item, what = matching[0], f"la pista del {label}"
        found.append(ReferenceRoad(str(item["nombre"]), *(_number(item, key, what) for key in (
            "long_m", "cota_ini", "cota_fin", "desnivel_m", "pend_media_pct", "pend_max_pct", "calzada_m", "plataforma_m"))))
    return found[0], found[1]


def reference_level(verification: Mapping[str, Any]) -> float:
    """La cota mínima alcanzable sobre la superficie restaurada de la verificación CA-6 de la referencia (m)."""
    check = _check(verification)
    if check.get("cota_min_alcanzable_sup_restaurada") is None:
        raise BankShapeError("CA-6 de la verificación del banco no trae la cota mínima alcanzable sobre la restaurada")
    return _number(check, "cota_min_alcanzable_sup_restaurada", "la cota mínima alcanzable")


# --- Buscar en el banco --------------------------------------------------------------------------------------------


def latest(paths: Sequence[Path], pattern: re.Pattern[str], what: str) -> Path:
    """El fichero de ``paths`` cuyo nombre casa con ``pattern`` (el grupo 1 es el número de versión ``V<nn>``) de **número mayor**; las copias iguales cuentan como una.
    :class:`NotInBank` si no hay ninguno y :class:`BankShapeError` si, con el número mayor, hay varios distintos."""
    grouped: dict[int, list[Path]] = {}
    for path in paths:
        match = pattern.match(path.name)
        if match:
            grouped.setdefault(int(match.group(1)), []).append(path)
    if not grouped:
        raise NotInBank(f"{what}: ninguna (véase la forma del banco en el docstring de la comparación)")
    return bank.one(grouped[max(grouped)], what)


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _candidates_of(connection: sqlite3.Connection) -> int:
    count = 0
    for (layer,) in connection.execute("SELECT table_name FROM gpkg_contents WHERE data_type = 'features'").fetchall():
        if AXIS_PATTERN.search(layer):
            count += 1
        columns = {str(row[1]).lower(): str(row[1]) for row in connection.execute(f"PRAGMA table_info({_quoted(layer)})").fetchall()}
        for key in NAME_COLUMNS:
            if key not in columns:
                continue
            column = _quoted(columns[key])
            count += sum(1 for (value,) in connection.execute(f"SELECT DISTINCT {column} FROM {_quoted(layer)}").fetchall()
                         if isinstance(value, str) and AXIS_PATTERN.search(value))
    return count


def axis_candidates(paths: Iterable[Path]) -> int:
    """Cuántas capas o valores del campo de nombre (``capa``, ``nombre`` o ``name``) de los GeoPackage de ``paths`` hacen pensar en el eje de una pista (:data:`AXIS_PATTERN`). Solo lee
    (``mode=ro`` e ``immutable=1``: ni diario ni ``-wal``); un fichero que no es un GeoPackage legible no cuenta."""
    found = 0
    for path in paths:
        if path.suffix.lower() != GEOPACKAGE_SUFFIX:
            continue
        try:
            connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        except sqlite3.Error:
            continue
        try:
            found += _candidates_of(connection)
        except sqlite3.Error:
            pass
        finally:
            connection.close()
    return found


def _read(path: Path, what: str) -> Any:
    surface = geotiff.read_geotiff(path)
    bank.declared(surface, what)
    return surface


class RoadsBankTest(unittest.TestCase):
    """CE-017-10: las pistas de la V10 contra el banco, con lo que el banco trae (véase el módulo)."""

    folder: Path
    everything: list[Path]
    verification: Mapping[str, Any]
    exploitation: Any
    restored: Any
    mill: ReferenceRoad
    workshop: ReferenceRoad
    level_m: float

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = bank.bank_folder()
        cls.everything = bank.files(cls.folder)
        try:
            sheet = latest(cls.everything, VERIFICATION_PATTERN, "la verificación CA-6 de la V10")
            exploitation = latest(cls.everything, EXPLOITATION_PATTERN, "la superficie de explotación de la V10")
            restored = latest(cls.everything, FINAL_PATTERN, "la superficie restaurada de la V10")
        except NotInBank as error:
            raise unittest.SkipTest(f"OMITIDO: silvestre: el banco no trae lo de CE-017-10: {error}") from None
        cls.verification = json.loads(sheet.read_text(encoding="utf-8"))
        cls.mill, cls.workshop = reference_roads(cls.verification)
        cls.level_m = reference_level(cls.verification)
        cls.exploitation = _read(exploitation, "la superficie de explotación")
        cls.restored = _read(restored, "la superficie restaurada")

    def test_the_reference_roads_of_the_bank_are_the_ones_of_the_spec_and_fit_the_reference_profile(self) -> None:
        """CE-017-10, D-22, RF-017-15, RF-017-21: las pistas del molino y del taller de la verificación CA-6 del banco dan **las cifras de la spec** (1.034 m y 685 m; 7,0 % y 8,1 % de media; 10,0 %
        de máxima) dentro de la tolerancia de D-22 (longitud y pendientes ±2 %); su desnivel es la resta de sus cotas (a 0,1 m de redondeo) y su pendiente media no baja del desnivel entre la
        longitud (D-7: Σ|Δcota| ≥ el desnivel neto); y **caben en el perfil de referencia**: la calzada de 10,5 m y la plataforma de 11,5 m son las que derivan de él (``road_profiles.derived``) y
        sus pendientes no pasan de pd ni de pm. Escribe cada cifra con su diferencia."""
        profile = rd.PROFILE
        carriageway, section = widths_of(rd.road_profile(profile))
        for label, found, wanted in (("molino", self.mill, MILL), ("taller", self.workshop, WORKSHOP)):
            bank.report(f"{NAME}: pista del {label} de la referencia: {bank.number(found.length_m, 1)} m ({bank.percent(relative(found.length_m, wanted.length_m), 2)} de la spec), "
                        f"pendiente media {bank.number(found.mean_pct, 1)} % ({bank.percent(relative(found.mean_pct, wanted.mean_pct), 2)}), máxima {bank.number(found.max_pct, 1)} % "
                        f"({bank.percent(relative(found.max_pct, wanted.max_pct), 2)}), de {bank.number(found.z_start_m, 1)} m a {bank.number(found.z_end_m, 1)} m "
                        f"(desnivel {bank.number(found.drop_m, 1)} m), calzada {bank.number(found.carriageway_m, 1)} m y plataforma {bank.number(found.platform_m, 1)} m")
            with self.subTest(pista=label):
                self.assertEqual(outside(found.figures, wanted), [])
                self.assertAlmostEqual(found.drop_m, found.z_end_m - found.z_start_m, delta=ROUNDING_M)
                self.assertGreaterEqual(found.mean_pct + ROUNDING_PCT, 100.0 * found.drop_m / found.length_m)
                self.assertAlmostEqual(found.carriageway_m, carriageway, delta=1e-9)
                self.assertAlmostEqual(found.platform_m, section, delta=1e-9)
                self.assertLessEqual(found.max_pct, profile.max_gradient_pct + ROUNDING_PCT)
                self.assertLessEqual(found.mean_pct, profile.max_mean_gradient_pct + ROUNDING_PCT)

    def test_the_minimum_reachable_level_is_a_cell_of_the_restored_surface(self) -> None:
        """CE-017-10, RF-017-24: la cota mínima alcanzable de la verificación (136,5234 m) es la de la spec (136,5 m, a medio decimal) y **es la cota de alguna celda** de la superficie
        restaurada del banco, que declara su CRS y está en la misma rejilla que la de explotación: las cifras y las superficies del banco son de los mismos datos. Escribe cuántas
        celdas la tienen. (Qué celdas se alcanzan desde una entrada, con qué pendiente y qué ancho, no se puede contrastar: el banco no trae la entrada ni los umbrales.)"""
        values = np.asarray(self.restored.values, dtype=np.float64)
        cells = int(np.count_nonzero(np.isclose(values, self.level_m, rtol=0.0, atol=CELL_TOLERANCE_M)))
        grid = self.restored.grid
        bank.report(f"{NAME}: cota mínima alcanzable de la referencia sobre la restaurada: {bank.number(self.level_m, 4)} m (spec: {bank.number(LEVEL_M, 1)} m); la restaurada tiene "
                    f"{bank.number(float(np.nanmin(values)), 1)} a {bank.number(float(np.nanmax(values)), 1)} m en {bank.number(float(grid.nrows), 0)} × {bank.number(float(grid.ncols), 0)} celdas de {bank.number(grid.dx, 3)} m, "
                    f"y {bank.number(float(cells), 0)} celdas a esa cota")
        self.assertAlmostEqual(self.level_m, LEVEL_M, delta=LEVEL_TOLERANCE_M)
        self.assertGreaterEqual(cells, 1)
        self.assertTrue(float(np.nanmin(values)) <= self.level_m <= float(np.nanmax(values)))
        self.assertTrue(grid.same_geometry(self.exploitation.grid))
        self.assertEqual(self.restored.declared_crs, self.exploitation.declared_crs)

    def test_the_levels_of_the_roads_are_levels_of_the_exploitation_surface(self) -> None:
        """CE-017-10, RF-017-15: las cotas de inicio y de fin de las pistas del molino y del taller están dentro del rango de la superficie de explotación del banco y la tienen celdas (a medio
        decimal): las pistas se midieron sobre esa superficie. La pista parte por encima del fondo de la corta (la cota mínima de la explotación). Escribe cuántas celdas hay a cada cota."""
        values = np.asarray(self.exploitation.values, dtype=np.float64)
        lowest, highest = float(np.nanmin(values)), float(np.nanmax(values))
        for label, found in (("molino", self.mill), ("taller", self.workshop)):
            counts = {}
            for which, level in (("inicio", found.z_start_m), ("fin", found.z_end_m)):
                counts[which] = int(np.count_nonzero(np.abs(values - level) <= LEVEL_REACH_M))
            bank.report(f"{NAME}: pista del {label}: la explotación tiene {bank.number(float(counts['inicio']), 0)} celdas a la cota de inicio ({bank.number(found.z_start_m, 1)} m) y "
                        f"{bank.number(float(counts['fin']), 0)} a la de fin "
                        f"({bank.number(found.z_end_m, 1)} m); su rango es de {bank.number(lowest, 1)} a {bank.number(highest, 1)} m")
            with self.subTest(pista=label):
                self.assertTrue(lowest < found.z_start_m <= highest and lowest < found.z_end_m <= highest)
                self.assertGreaterEqual(min(counts.values()), 1)

    def test_the_comparison_with_the_original_axes_needs_them(self) -> None:
        """CE-017-10, D-22, RF-017-13, RF-017-15, RF-017-21: la comparación de **Geoblender** con las cifras de la referencia (:func:`outside`) necesita el croquis de la propiedad con el eje
        de la «opción A15», los ejes de las pistas del molino y del taller y los puntos de entrada de la accesibilidad. Si el banco **no** los trae (se busca en sus GeoPackage), se
        **omite** con ese motivo (no cuenta como verde: «sin ejecutar con los datos originales») y escribe las cifras de la referencia que quedan sin contrastar; si alguna capa o nombre
        parece uno, **falla**: hay datos y falta escribir su lectura."""
        candidates = axis_candidates(self.everything)
        if not candidates:
            bank.report(f"{NAME}: la pista principal «opción A15» NO se contrasta: el banco no trae su croquis (la referencia da {bank.number(A15.length_m, 0)} m, "
                        f"{bank.number(A15.mean_pct, 1)} % de media, {bank.number(A15.max_pct, 1)} % de máxima en 10 m, radio mínimo de {bank.number(A15.min_radius_m, 1)} m, desmonte de "
                        f"{bank.number(A15.cut_m3, 0)} m³ y terraplén de {bank.number(A15.fill_m3, 0)} m³)")
            bank.report(f"{NAME}: las pistas del molino y del taller NO se contrastan con Geoblender: el banco trae sus cifras y las superficies, pero no sus ejes")
            bank.report(f"{NAME}: la cota mínima alcanzable ({bank.number(LEVEL_M, 1)} m) NO se contrasta con la accesibilidad de Geoblender: el banco no trae la entrada ni los umbrales")
            raise unittest.SkipTest(
                "OMITIDO: silvestre: CE-017-10 sin ejecutar con los datos originales: el banco no trae el croquis de la propiedad con el eje de la opción A15, los ejes de las pistas del "
                "molino y del taller ni los puntos de entrada de la accesibilidad; se contrastan solo las cifras de la referencia que el banco sí trae (las demás pruebas) y la comparación con "
                "las tolerancias de D-22 queda escrita y probada con datos sintéticos (tests/unit/design/test_road_bank.py)")
        self.fail(f"el banco trae {candidates} capas o nombres que parecen ejes de pista: CE-017-10 se puede ejecutar con ellos; escriba su lectura y compare con outside() "
                  "(véase el docstring del módulo)")


if __name__ == "__main__":
    unittest.main()
