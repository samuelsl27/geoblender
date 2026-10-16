# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera los datos sintéticos de sondeos de la spec 005 (T01; plan 005 §7).

Nada de clientes: todo sale de las constantes de este fichero y de dos semillas fijas
(``random.Random``), con los números como enteros en su última cifra decimal para que el
texto no dependa del redondeo de los float. Desde la raíz del repositorio de código, con el
Python de Blender::

    & $PY -B -s -X utf8 -m tests.data.dh.sintetico                  # juegos pequeños + README
    & $PY -B -s -X utf8 -m tests.data.dh.sintetico --out <carpeta>   # en otra carpeta
    & $PY -B -s -X utf8 -m tests.data.dh.sintetico --vref <carpeta> [--escala 1] [--semilla N]

- Sin opciones, reescribe ``csv_basico/``, ``csv_convenios/`` y ``csv_errores/`` en esta
  carpeta y la tabla de ficheros del ``README.md`` (entre sus marcas). Lo hace una persona
  cuando cambian; la prueba ``tests/unit/drillholes/test_data_files.py`` comprueba que dos
  ejecuciones dan los bytes versionados.
- ``--out`` los escribe en otra carpeta sin tocar el ``README.md``.
- ``--vref`` escribe V-ref (spec 005 §5: 2 000 sondeos, 20 000 estaciones, 50 000 tramos de
  litología y 25 000 tramos con 20 elementos) en el formato de ``csv_basico``; con
  ``--escala`` 0,01, una centésima. No se versiona: lo generan las pruebas de rendimiento
  en la carpeta temporal (unos 5 MB, en menos de 1 s).

Todos los ficheros, en UTF-8 sin BOM y LF; las variantes en otras codificaciones las
generan las pruebas que las leen (T12).
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import math
import random
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
README = HERE / "README.md"
MARK_START = "<!-- ficheros: inicio -->"
MARK_END = "<!-- ficheros: fin -->"

SMALL_SEED = 5000  # leyes de csv_basico (y, convertidas, de csv_convenios y csv_errores)
VREF_SEED = 5001  # V-ref

# La superficie de tests/data/gis/README.md: las bocas de csv_basico están sobre ella.
REF_E_MM, REF_N_MM = 700_000_000, 4_400_000_000
SURFACE = (
    "z = 800 + 0,5·x − 0,25·y + 3·sin(x/7), con x = E − 700 000 e y = N − 4 400 000 (m), "
    "la de tests/data/gis/README.md"
)
WORK_WINDOW = [699900.0, 4399900.0, 700200.0, 4400200.0]  # xmin, ymin, xmax, ymax (m)
# Umbrales por defecto de la validación (spec 005 §11; plan 005 §5.2.4), ADOPTADO.
VALIDATION_PARAMS = {
    "depth_tolerance_m": 0.01,
    "gap_tolerance_m": 0.01,
    "min_interval_m": 0.05,
    "dogleg_max_deg_30m": 3.0,
    "collar_dem_tolerance_m": 2.0,
}
# Convenios de csv_convenios con azimut magnético: declinación δ (positiva al este) y la
# convergencia γ que da el CrsService falso de las pruebas en todas las bocas.
DECLINATION_CDEG = 25  # δ = +0,25°
CONVERGENCE_CDEG = 150  # γ = +1,50°


def surface(x: float, y: float) -> float:
    """La cota de la superficie de ``tests/data/gis`` en (x, y), en el mismo orden."""
    return 800.0 + 0.5 * x - 0.25 * y + 3.0 * math.sin(x / 7.0)


def surface_mm(east_mm: int, north_mm: int) -> int:
    """La cota de la superficie en milímetros enteros (redondeo al más próximo)."""
    x = (east_mm - REF_E_MM) / 1000.0
    y = (north_mm - REF_N_MM) / 1000.0
    return round(surface(x, y) * 1000.0)


def fixed(units: int, places: int, mark: str = ",") -> str:
    """El entero ``units`` (en unidades de 10^-places) como número con ``places``
    decimales y la marca decimal ``mark``: ``fixed(-6050, 2)`` → «-60,50»."""
    sign = "-" if units < 0 else ""
    whole, frac = divmod(abs(units), 10**places)
    if places == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}{mark}{frac:0{places}d}"


@dataclass(frozen=True)
class Table:
    """Una tabla de texto: cabecera y filas, todo como se escribe."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def text(self, sep: str) -> str:
        lines = [sep.join(self.header), *(sep.join(row) for row in self.rows)]
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------
# csv_basico: seis sondeos con solución analítica
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hole:
    """Un sondeo de ``csv_basico``. Ángulos en centésimas de grado, profundidades en cm y
    coordenadas en mm. ``trajectory``: «straight» (estaciones con la misma orientación),
    «arc» (arco en un plano vertical: la inclinación cambia ``turn_cdeg`` en cada
    estación), «vertical» (estaciones a −90°), «collar» (solo orientación en la boca) y
    «declared_vertical» (sin estaciones ni orientación: vertical por declaración)."""

    name: str
    hole_type: str
    east_mm: int
    north_mm: int
    depth_cm: int
    trajectory: str
    azimuth_cdeg: int
    top_cdeg: int
    step_cm: int
    turn_cdeg: int
    start: datetime.date
    end: datetime.date
    lithology: tuple[tuple[int, int, str], ...]  # (desde, hasta) en cm, código
    samples: tuple[int, int] | None = None  # desde (cm) y número de muestras de 2 m

    @property
    def z_mm(self) -> int:
        return surface_mm(self.east_mm, self.north_mm)

    def stations(self) -> list[tuple[int, int, int]]:
        """(profundidad cm, azimut cdeg, inclinación cdeg) de cada estación."""
        if not self.step_cm:
            return []
        count = self.depth_cm // self.step_cm
        return [
            (k * self.step_cm, self.azimuth_cdeg, self.top_cdeg + k * self.turn_cdeg)
            for k in range(count + 1)
        ]

    def bottom(self) -> list[float]:
        """El fondo analítico (E, N, Z en m), redondeado a la micra. Recta: boca +
        profundidad · t. Arco en un plano vertical de azimut A con I = 90° + θ lineal en la
        profundidad (curvatura κ = ΔI/L): desplazamiento horizontal (cos I0 − cos I1)/κ y
        hacia abajo (sin I1 − sin I0)/κ."""
        east, north = self.east_mm / 1000.0, self.north_mm / 1000.0
        z = self.z_mm / 1000.0
        depth = self.depth_cm / 100.0
        a = math.radians(self.azimuth_cdeg / 100.0)
        i0 = math.radians(90.0 + self.top_cdeg / 100.0)
        if self.trajectory == "arc":
            turns = self.depth_cm // self.step_cm
            i1 = math.radians(90.0 + (self.top_cdeg + turns * self.turn_cdeg) / 100.0)
            kappa = (i1 - i0) / depth
            horizontal = (math.cos(i0) - math.cos(i1)) / kappa
            down = (math.sin(i1) - math.sin(i0)) / kappa
        else:
            horizontal = depth * math.sin(i0)
            down = depth * math.cos(i0)
        point = (east + horizontal * math.sin(a), north + horizontal * math.cos(a), z - down)
        return [round(v, 6) for v in point]


def _date(year: int, month: int, day: int) -> datetime.date:
    return datetime.date(year, month, day)


HOLES: tuple[Hole, ...] = (
    Hole("S-01", "DD", 700_010_500, 4_400_040_500, 15000, "straight", 4500, -6000, 3000, 0,
         _date(2025, 3, 3), _date(2025, 3, 7),
         ((0, 300, "SUE"), (300, 4500, "CAL"), (4500, 6050, "MAR"), (6050, 7225, "MIN"),
          (7225, 15000, "CAL")),
         (5850, 8)),
    Hole("S-02", "DD", 700_050_500, 4_400_040_500, 30000, "arc", 12000, -5000, 3000, -200,
         _date(2025, 3, 10), _date(2025, 3, 21),
         ((0, 240, "SUE"), (240, 8500, "ARE"), (8500, 19070, "PIZ"), (19070, 20530, "MIN"),
          (20530, 30000, "PIZ")),
         (18800, 10)),
    Hole("S-03", "DD", 700_030_500, 4_400_010_500, 24000, "arc", 35950, -8000, 3000, 200,
         _date(2025, 3, 24), _date(2025, 4, 2),
         ((0, 150, "SUE"), (150, 12000, "CAL"), (12000, 18000, "DOL"), (18000, 19680, "MIN"),
          (19680, 24000, "DOL")),
         (17800, 10)),
    Hole("S-04", "RC", 700_020_500, 4_400_020_500, 10000, "vertical", 0, -9000, 5000, 0,
         _date(2025, 4, 7), _date(2025, 4, 8),
         ((0, 100, "SUE"), (100, 1200, "ARC"), (1200, 10000, "ARE"))),
    Hole("S-12", "RC", 700_055_500, 4_400_015_500, 16000, "collar", 30000, -7500, 0, 0,
         _date(2025, 4, 9), _date(2025, 4, 11),
         ((0, 200, "SUE"), (200, 4000, "MAR"), (4000, 15000, "CAL"), (15000, 16000, "DOL"))),
    Hole("C-01", "CA", 700_005_500, 4_400_005_500, 450, "declared_vertical", 0, -9000, 0, 0,
         _date(2025, 4, 14), _date(2025, 4, 14),
         ((0, 60, "SUE"), (60, 450, "ARC"))),
)  # fmt: skip
CAMPAIGN = "C-2025"

# Catálogo de litologías: código, descripción, color sRGB, densidad (cent. de t/m³), orden.
LITHOLOGY_CODES: tuple[tuple[str, str, str, int, int], ...] = (
    ("SUE", "Suelo vegetal", "#8B6B3D", 180, 1),
    ("ARC", "Arcilla", "#C49A6C", 200, 2),
    ("ARE", "Arenisca", "#E3C16F", 240, 3),
    ("MAR", "Marga", "#A9B18F", 230, 4),
    ("CAL", "Caliza", "#9DB7D5", 265, 5),
    ("DOL", "Dolomía", "#7F9CC0", 280, 6),
    ("PIZ", "Pizarra", "#5A5F6B", 275, 7),
    ("MIN", "Mineralización", "#C0392B", 310, 8),
)


@dataclass(frozen=True)
class Element:
    """Un elemento del catálogo. Los valores son enteros en 10^-``decimals`` de ``unit``;
    en ``csv_convenios`` van en ``other_unit``, multiplicados por ``other_factor`` con
    ``other_places`` decimales, y se vuelven a la del catálogo dividiendo por
    ``divide_by`` (una potencia de 10 exacta)."""

    code: str
    name: str
    unit: str
    decimals: int
    detection_limit: int
    other_unit: str
    other_factor: int
    other_places: int
    divide_by: int
    inside: tuple[int, int]  # leyes en la zona mineralizada (aleatorias, uniformes)
    outside: tuple[int, int]  # y fuera de ella


ELEMENTS: tuple[Element, ...] = (
    Element("Au", "Oro", "g/t", 2, 1, "ppb", 10, 0, 1000, (80, 850), (2, 40)),
    Element("Ag", "Plata", "ppm", 1, 5, "g/t", 1, 1, 1, (50, 450), (6, 40)),
    Element("Cu", "Cobre", "%", 3, 1, "ppm", 10, 0, 10000, (150, 1800), (5, 120)),
)
# Valores especiales de csv_basico: (muestra, elemento) → (marca, valor entero o None).
SPECIAL_VALUES: dict[tuple[str, str], tuple[str, int | None]] = {
    ("M-0101", "Au"): ("<", 1),  # «<0,01»: bajo el límite de detección
    ("M-0201", "Ag"): ("<", 5),  # «<0,5»
    ("M-0206", "Au"): (">", 1000),  # «>10,00»: sobre el límite superior
    ("M-0307", "Ag"): ("", None),  # vacío: ausente
}

ROLES = (
    "collar",
    "survey",
    "lithology",
    "assay_wide",
    "assay_long",
    "lithology_catalog",
    "element_catalog",
)
BASICO_FILES = dict(
    zip(
        ROLES,
        (
            "bocas.csv",
            "desviaciones.csv",
            "litologia.csv",
            "analisis_columnas.csv",
            "analisis_filas.csv",
            "litologias.csv",
            "elementos.csv",
        ),
        strict=True,
    )
)
COLLAR_HEADER = (
    "Sondeo", "X", "Y", "Z", "Profundidad", "Azimut", "Inclinación", "Tipo", "Campaña",
    "Fecha inicio", "Fecha fin", "Planificado",
)  # fmt: skip


@dataclass(frozen=True)
class Sample:
    hole: str
    from_cm: int
    to_cm: int
    sample_id: str
    values: dict[str, tuple[str, int | None]]  # elemento → (marca, valor)


def _code_at(hole: Hole, depth_cm: int) -> str:
    for start, end, code in hole.lithology:
        if start <= depth_cm < end:
            return code
    raise ValueError(f"{hole.name}: sin litología a {depth_cm} cm")


def basico_samples() -> list[Sample]:
    """Las muestras de ``csv_basico`` (2 m, contiguas), con leyes aleatorias de semilla
    fija: altas en la zona mineralizada (MIN) y bajas fuera, y los valores especiales."""
    rng = random.Random(SMALL_SEED)
    samples: list[Sample] = []
    for number, hole in enumerate(HOLES, start=1):
        if hole.samples is None:
            continue
        start, count = hole.samples
        for k in range(count):
            from_cm = start + 200 * k
            sample_id = f"M-{number:02d}{k + 1:02d}"
            mineral = _code_at(hole, from_cm + 100) == "MIN"
            values: dict[str, tuple[str, int | None]] = {}
            for element in ELEMENTS:
                low, high = element.inside if mineral else element.outside
                values[element.code] = ("", rng.randint(low, high))
                special = SPECIAL_VALUES.get((sample_id, element.code))
                if special is not None:
                    values[element.code] = special
            samples.append(Sample(hole.name, from_cm, from_cm + 200, sample_id, values))
    return samples


def _value_es(element: Element, value: tuple[str, int | None]) -> str:
    mark, units = value
    return "" if units is None else mark + fixed(units, element.decimals)


def _value_other(element: Element, value: tuple[str, int | None]) -> str:
    mark, units = value
    if units is None:
        return ""
    return mark + fixed(units * element.other_factor, element.other_places, ".")


def _dmy(day: datetime.date) -> str:
    return day.strftime("%d/%m/%Y")


def _collar_row(hole: Hole) -> tuple[str, ...]:
    oriented = hole.trajectory == "collar"
    return (
        hole.name,
        fixed(hole.east_mm, 3),
        fixed(hole.north_mm, 3),
        fixed(hole.z_mm, 3),
        fixed(hole.depth_cm, 2),
        fixed(hole.azimuth_cdeg, 2) if oriented else "",
        fixed(hole.top_cdeg, 2) if oriented else "",
        hole.hole_type,
        CAMPAIGN,
        _dmy(hole.start),
        _dmy(hole.end),
        "no",
    )


def basico_tables() -> dict[str, Table]:
    """Las siete tablas de ``csv_basico`` por papel: «;» y coma decimal (Excel español)."""
    samples = basico_samples()
    surveys = tuple(
        (hole.name, fixed(md, 2), fixed(az, 2), fixed(inc, 2))
        for hole in HOLES
        for md, az, inc in hole.stations()
    )
    lithology = tuple(
        (hole.name, fixed(start, 2), fixed(end, 2), code)
        for hole in HOLES
        for start, end, code in hole.lithology
    )
    span = ("Sondeo", "Desde", "Hasta", "Muestra")
    wide = tuple(
        (s.hole, fixed(s.from_cm, 2), fixed(s.to_cm, 2), s.sample_id,
         *(_value_es(e, s.values[e.code]) for e in ELEMENTS))
        for s in samples
    )  # fmt: skip
    long = tuple(
        (s.hole, fixed(s.from_cm, 2), fixed(s.to_cm, 2), s.sample_id, e.code,
         _value_es(e, s.values[e.code]), e.unit)
        for s in samples
        for e in ELEMENTS
    )  # fmt: skip
    return {
        "collar": Table(COLLAR_HEADER, tuple(_collar_row(h) for h in HOLES)),
        "survey": Table(("Sondeo", "Profundidad", "Azimut", "Inclinación"), surveys),
        "lithology": Table(("Sondeo", "Desde", "Hasta", "Litología"), lithology),
        "assay_wide": Table((*span, *(e.code for e in ELEMENTS)), wide),
        "assay_long": Table((*span, "Elemento", "Valor", "Unidad"), long),
        "lithology_catalog": Table(
            ("Código", "Descripción", "Color", "Densidad", "Orden"),
            tuple((c, d, rgb, fixed(rho, 2), str(o)) for c, d, rgb, rho, o in LITHOLOGY_CODES),
        ),
        "element_catalog": Table(
            ("Código", "Nombre", "Unidad", "Decimales", "Límite de detección"),
            tuple(
                (e.code, e.name, e.unit, str(e.decimals), fixed(e.detection_limit, e.decimals))
                for e in ELEMENTS
            ),
        ),
    }


def basico_expected(tables: dict[str, Table]) -> dict:
    """``csv_basico/esperado.json``: declaraciones, ficheros, filas, valores especiales,
    ventana de trabajo, superficie, incidencias (ninguna) y fondo analítico de cada
    sondeo."""
    texts = [row[5] for row in tables["assay_long"].rows]
    return {
        "about": (
            "Juego limpio de la spec 005: seis sondeos con solución analítica, cero "
            "incidencias con estas declaraciones, la ventana de trabajo y la superficie "
            "(DH-W05). «rows» son las filas de datos de cada fichero (el informe de "
            "importación de M1); análisis en columnas y en filas son los mismos valores: "
            "se importa uno de los dos."
        ),
        "declaration": {
            "crs_epsg": 25830,
            "azimuth_ref": "grid",
            "declination_deg": None,
            "inclination_convention": "negative_down",
            "units": {e.code: e.unit for e in ELEMENTS},
            "separator": ";",
            "decimal_mark": ",",
            "encoding": "utf-8",
            "sentinels": [],
            "negative_is_below_dl": False,
            "all_vertical": True,
            "density_kind": "ADOPTADO",
            "date_format": "%d/%m/%Y",
        },
        "files": BASICO_FILES,
        "rows": {role: len(tables[role].rows) for role in ROLES},
        "values": {
            "read": len(texts),
            "absent": texts.count(""),
            "below_dl": sum(t.startswith("<") for t in texts),
            "above_ul": sum(t.startswith(">") for t in texts),
        },
        "work_window": WORK_WINDOW,
        "surface": SURFACE,
        "issues": [],
        "holes": [
            {
                "name": h.name,
                "trajectory": h.trajectory,
                "azimuth": h.azimuth_cdeg / 100.0,
                "inclination_top": h.top_cdeg / 100.0,
                "inclination_bottom": (
                    h.top_cdeg + (h.depth_cm // h.step_cm) * h.turn_cdeg if h.step_cm
                    else h.top_cdeg
                ) / 100.0,
                "depth": h.depth_cm / 100.0,
                "bottom": h.bottom(),
            }
            for h in HOLES
        ],
    }  # fmt: skip


# ---------------------------------------------------------------------------------------
# csv_convenios: los mismos sondeos con otros convenios, unidades y dialecto
# ---------------------------------------------------------------------------------------

# Variante → (convenio de inclinación, referencia del azimut, nombre de la columna).
VARIANTS: dict[str, tuple[str, str, str]] = {
    "positive_dip": ("positive_down", "grid", "Dip"),
    "from_vertical": ("from_vertical", "grid", "Inclination"),
    "magnetic": ("negative_down", "magnetic", "Dip"),
}


def _inclination_as(convention: str, cdeg: int) -> int:
    """La inclinación interna θ (negativa hacia abajo) en el convenio de la fuente:
    positiva hacia abajo, −θ; desde la vertical (0 = hacia abajo), θ + 90°."""
    if convention == "positive_down":
        return -cdeg
    if convention == "from_vertical":
        return cdeg + 9000
    return cdeg


def _azimuth_as(ref: str, cdeg: int) -> int:
    """El azimut de cuadrícula en la referencia de la fuente: magnético, A_m = A − δ + γ
    (porque A = A_m + δ − γ, RF-005-27), en [0, 360)."""
    if ref == "magnetic":
        return (cdeg - DECLINATION_CDEG + CONVERGENCE_CDEG) % 36000
    return cdeg


def convenios_tables() -> dict[str, Table]:
    """Las tablas de ``csv_convenios`` por nombre de fichero: «,» y punto decimal,
    cabeceras en inglés, fechas ISO, análisis en filas en ppb, g/t y ppm."""
    tables: dict[str, Table] = {}
    for variant, (convention, ref, column) in VARIANTS.items():
        collars = []
        for hole in HOLES:
            oriented = hole.trajectory == "collar"
            azimuth = _azimuth_as(ref, hole.azimuth_cdeg)
            inclination = _inclination_as(convention, hole.top_cdeg)
            collars.append((
                hole.name, fixed(hole.east_mm, 3, "."), fixed(hole.north_mm, 3, "."),
                fixed(hole.z_mm, 3, "."), fixed(hole.depth_cm, 2, "."),
                fixed(azimuth, 2, ".") if oriented else "",
                fixed(inclination, 2, ".") if oriented else "",
                hole.hole_type, CAMPAIGN, hole.start.isoformat(), hole.end.isoformat(), "no",
            ))  # fmt: skip
        tables[f"collars_{variant}.csv"] = Table(
            ("HoleID", "East", "North", "RL", "Depth", "Azimuth", column, "Type",
             "Campaign", "StartDate", "EndDate", "Planned"),
            tuple(collars),
        )  # fmt: skip
        tables[f"surveys_{variant}.csv"] = Table(
            ("HoleID", "Depth", "Azimuth", column),
            tuple(
                (hole.name, fixed(md, 2, "."), fixed(_azimuth_as(ref, az), 2, "."),
                 fixed(_inclination_as(convention, inc), 2, "."))
                for hole in HOLES
                for md, az, inc in hole.stations()
            ),
        )  # fmt: skip
    tables["lithology.csv"] = Table(
        ("HoleID", "From", "To", "Lith"),
        tuple(
            (hole.name, fixed(start, 2, "."), fixed(end, 2, "."), code)
            for hole in HOLES
            for start, end, code in hole.lithology
        ),
    )
    tables["assays.csv"] = Table(
        ("HoleID", "From", "To", "SampleID", "Element", "Value", "Unit"),
        tuple(
            (s.hole, fixed(s.from_cm, 2, "."), fixed(s.to_cm, 2, "."), s.sample_id, e.code,
             _value_other(e, s.values[e.code]), e.other_unit)
            for s in basico_samples()
            for e in ELEMENTS
        ),
    )  # fmt: skip
    tables["lithology_codes.csv"] = Table(
        ("Code", "Description", "Color", "Density", "Order"),
        tuple((c, d, rgb, fixed(rho, 2, "."), str(o)) for c, d, rgb, rho, o in LITHOLOGY_CODES),
    )
    tables["elements.csv"] = Table(
        ("Code", "Name", "Unit", "Decimals", "DetectionLimit"),
        tuple(
            (e.code, e.name, e.unit, str(e.decimals), fixed(e.detection_limit, e.decimals, "."))
            for e in ELEMENTS
        ),
    )
    return tables


def convenios_expected() -> dict:
    """``csv_convenios/esperado.json``: declaraciones comunes y de cada variante, y los
    factores de las unidades."""
    return {
        "about": (
            "Los sondeos de csv_basico con otros convenios: «,» y punto decimal, cabeceras "
            "en inglés, fechas ISO y análisis en ppb, g/t y ppm. Cada variante cambia un "
            "convenio en las bocas y en las desviaciones; litología, análisis y catálogos "
            "son comunes. Al deshacer el convenio (y dividir por «divide_by»), los "
            "valores de csv_basico, bit a bit. Las coordenadas son las mismas cifras: el "
            "CRS no va en el fichero, lo declara quien importa. «convergence_deg» es la γ "
            "que da el CrsService falso de las pruebas en todas las bocas."
        ),
        "same_holes_as": "csv_basico",
        "declaration": {
            "crs_epsg": 25830,
            "separator": ",",
            "decimal_mark": ".",
            "encoding": "utf-8",
            "sentinels": [],
            "negative_is_below_dl": False,
            "all_vertical": True,
            "density_kind": "ADOPTADO",
            "date_format": "%Y-%m-%d",
        },
        "files": {
            "lithology": "lithology.csv",
            "assay_long": "assays.csv",
            "lithology_catalog": "lithology_codes.csv",
            "element_catalog": "elements.csv",
        },
        "variants": {
            variant: {
                "collar": f"collars_{variant}.csv",
                "survey": f"surveys_{variant}.csv",
                "inclination_convention": convention,
                "azimuth_ref": ref,
                "declination_deg": DECLINATION_CDEG / 100.0 if ref == "magnetic" else None,
                "convergence_deg": CONVERGENCE_CDEG / 100.0 if ref == "magnetic" else None,
            }
            for variant, (convention, ref, _column) in VARIANTS.items()
        },
        "unit_factors": {
            e.code: {"from": e.other_unit, "to": e.unit, "divide_by": e.divide_by}
            for e in ELEMENTS
        },
    }


# ---------------------------------------------------------------------------------------
# csv_errores: un caso por código de la tabla 4.4.1
# ---------------------------------------------------------------------------------------

# Alcance de cada error (spec 005, tabla 4.4.1): S, T o R; los avisos no tienen.
SCOPES = {
    **dict.fromkeys(("DH-E01", "DH-E02", "DH-E03", "DH-E05", "DH-E06", "DH-E07"), "hole"),
    "DH-E08": "hole",
    "DH-E04": "record",
    **dict.fromkeys(("DH-E09", "DH-E10", "DH-E11", "DH-E12"), "table"),
}


def issue(
    code: str,
    hole: str | None,
    table: str,
    *,
    depth: tuple[float, float] | None = None,
    field: str | None = None,
    value: str | None = None,
    catalog_code: str | None = None,
) -> dict:
    """Una incidencia esperada: código, nivel, alcance, sondeo, tabla, entrada del
    catálogo, tramo o profundidad (m), campo y texto de la fuente (``None`` si la
    comprobación es de un cálculo)."""
    return {
        "code": code,
        "level": "error" if code.startswith("DH-E") else "warning",
        "scope": SCOPES.get(code),
        "hole": hole,
        "table": table,
        "catalog_code": catalog_code,
        "depth_from": None if depth is None else depth[0],
        "depth_to": None if depth is None else depth[1],
        "field": field,
        "value": value,
    }


@dataclass
class ErrorCase:
    code: str
    role: str
    about: str
    table: Table
    issues: list[dict]
    declaration: dict | None = None

    @property
    def file(self) -> str:
        stem = "geom" if self.role == "collar_geom" else BASICO_FILES[self.role][:-4]
        return f"dh_{self.code[3:].lower()}_{stem}.csv"


def _extra_collar(name: str, east_mm: int, north_mm: int, depth: str) -> tuple[str, ...]:
    """Una boca nueva, vertical por la declaración, sobre la superficie y sin tramos."""
    return (
        name, fixed(east_mm, 3), fixed(north_mm, 3), fixed(surface_mm(east_mm, north_mm), 3),
        depth, "", "", "RC", CAMPAIGN, "15/04/2025", "15/04/2025", "no",
    )  # fmt: skip


class _Rows:
    """Copia editable de las filas de una tabla de ``csv_basico``."""

    def __init__(self, table: Table) -> None:
        self.header = table.header
        self.rows = [list(row) for row in table.rows]

    def find(self, **match: str) -> int:
        cols = {name: self.header.index(name) for name in match}
        hits = [
            i
            for i, row in enumerate(self.rows)
            if all(row[cols[k]] == v for k, v in match.items())
        ]
        if len(hits) != 1:
            raise ValueError(f"{match}: {len(hits)} filas")
        return hits[0]

    def set(self, index: int, column: str, value: str) -> None:
        self.rows[index][self.header.index(column)] = value

    def table(self) -> Table:
        return Table(self.header, tuple(tuple(row) for row in self.rows))


def _sample_span(sample_id: str) -> tuple[float, float]:
    sample = next(s for s in basico_samples() if s.sample_id == sample_id)
    return (sample.from_cm / 100.0, sample.to_cm / 100.0)


def error_cases(base: dict[str, Table]) -> list[ErrorCase]:
    """Los casos de ``csv_errores``: cada uno sustituye una tabla de ``csv_basico`` (o da
    la posición de las bocas en la capa, DH-W15) y produce exactamente sus incidencias,
    validando el ``DrillholeSet`` que dan los ficheros tal como están (sin convertir
    unidades), con los umbrales, la ventana y la superficie de ``esperado.json``."""
    cases: list[ErrorCase] = []

    def add(code: str, role: str, about: str, rows: _Rows, issues: list[dict],
            declaration: dict | None = None) -> None:  # fmt: skip
        cases.append(ErrorCase(code, role, about, rows.table(), issues, declaration))

    def rows(role: str) -> _Rows:
        return _Rows(base[role])

    # DH-E01: nombre repetido sin distinguir mayúsculas ni espacios exteriores.
    r = rows("collar")
    r.rows.append(list(_extra_collar("S-90", 700_060_500, 4_400_045_500, "30,00")))
    r.rows.append(list(_extra_collar(" s-90 ", 700_061_500, 4_400_046_500, "30,00")))
    add("DH-E01", "collar", "«S-90» y « s-90 », dos bocas nuevas sin tramos", r,
        [issue("DH-E01", "S-90", "dh_collar", field="name", value=" s-90 ")])

    # DH-E02: Z de la boca ausente.
    r = rows("collar")
    r.set(r.find(Sondeo="S-04"), "Z", "")
    add("DH-E02", "collar", "S-04 sin Z", r,
        [issue("DH-E02", "S-04", "dh_collar", field="z", value="")])

    # DH-E03: profundidad ≤ 0 y ausente sin nada de donde deducirla.
    r = rows("collar")
    r.rows.append(list(_extra_collar("S-97", 700_040_500, 4_400_005_500, "0,00")))
    r.rows.append(list(_extra_collar("S-98", 700_045_500, 4_400_005_500, "")))
    add("DH-E03", "collar", "S-97 con 0 m y S-98 sin profundidad ni tramos", r,
        [issue("DH-E03", "S-97", "dh_collar", field="depth", value="0,00"),
         issue("DH-E03", "S-98", "dh_collar", field="depth", value="")])

    # DH-E04: tramos sin boca.
    r = rows("lithology")
    r.rows.append(["S-99", "0,00", "10,00", "CAL"])
    r.rows.append(["S-99", "10,00", "25,00", "MAR"])
    add("DH-E04", "lithology", "dos tramos de S-99, que no tiene boca", r,
        [issue("DH-E04", "S-99", "dh_lithology", depth=(0.0, 10.0), field="hole", value="S-99"),
         issue("DH-E04", "S-99", "dh_lithology", depth=(10.0, 25.0), field="hole",
               value="S-99")])

    # DH-E05: sin estaciones, ni orientación en boca, ni declaración de vertical.
    r = rows("survey")
    r.rows = [row for row in r.rows if row[0] != "S-02"]
    add("DH-E05", "survey", "S-02 sin estaciones y «all_vertical» falso (también C-01)", r,
        [issue("DH-E05", "S-02", "dh_survey"), issue("DH-E05", "C-01", "dh_survey")],
        {"all_vertical": False})

    # DH-E06: dos estaciones a la misma profundidad (la misma orientación: sin DH-W04).
    r = rows("survey")
    i = r.find(Sondeo="S-02", Profundidad="60,00")
    r.rows.insert(i + 1, list(r.rows[i]))
    add("DH-E06", "survey", "la estación de 60 m de S-02, repetida", r,
        [issue("DH-E06", "S-02", "dh_survey", depth=(60.0, 60.0), field="depth",
               value="60,00")])

    # DH-E07: estación más allá del fondo y por encima de la boca.
    r = rows("survey")
    i = r.find(Sondeo="S-01", Profundidad="150,00")
    r.rows.insert(i + 1, ["S-01", "155,00", "45,00", "-60,00"])
    i = r.find(Sondeo="S-03", Profundidad="0,00")
    r.rows.insert(i, ["S-03", "-2,00", "359,50", "-80,00"])
    add("DH-E07", "survey", "S-01 con una estación a 155 m (fondo 150) y S-03 a −2 m", r,
        [issue("DH-E07", "S-01", "dh_survey", depth=(155.0, 155.0), field="depth",
               value="155,00"),
         issue("DH-E07", "S-03", "dh_survey", depth=(-2.0, -2.0), field="depth",
               value="-2,00")])

    # DH-E08: azimut fuera de [0, 360) e inclinación fuera de [−90, 90] (360 es válido).
    r = rows("survey")
    r.set(r.find(Sondeo="S-04", Profundidad="50,00"), "Azimut", "361,00")
    i = r.find(Sondeo="S-04", Profundidad="100,00")
    r.set(i, "Azimut", "360,00")
    r.set(i, "Inclinación", "-90,50")
    add("DH-E08", "survey", "S-04 (vertical): azimut 361 a 50 m; 360 y −90,5° a 100 m", r,
        [issue("DH-E08", "S-04", "dh_survey", depth=(50.0, 50.0), field="azimuth",
               value="361,00"),
         issue("DH-E08", "S-04", "dh_survey", depth=(100.0, 100.0), field="inclination",
               value="-90,50")])

    # DH-E09: tramo con desde < 0 y con hasta más allá del fondo.
    r = rows("lithology")
    r.set(r.find(Sondeo="S-01", Desde="0,00"), "Desde", "-0,50")
    r.set(r.find(Sondeo="S-12", Desde="150,00"), "Hasta", "165,00")
    add("DH-E09", "lithology", "S-01 desde −0,5 m y S-12 hasta 165 m (fondo 160)", r,
        [issue("DH-E09", "S-01", "dh_lithology", depth=(-0.5, 3.0), field="from_m",
               value="-0,50"),
         issue("DH-E09", "S-12", "dh_lithology", depth=(150.0, 165.0), field="to_m",
               value="165,00")])

    # DH-E10: tramos solapados (el solape, de 120 a 125 m).
    r = rows("lithology")
    r.set(r.find(Sondeo="S-03", Desde="1,50"), "Hasta", "125,00")
    add("DH-E10", "lithology", "S-03: CAL hasta 125 m y DOL desde 120 m", r,
        [issue("DH-E10", "S-03", "dh_lithology", depth=(120.0, 125.0), field="from_m",
               value="120,00")])

    # DH-E11: código de litología fuera del catálogo.
    r = rows("lithology")
    r.set(r.find(Sondeo="S-02", Desde="85,00"), "Litología", "GRA")
    add("DH-E11", "lithology", "S-02 con «GRA», que no está en el catálogo", r,
        [issue("DH-E11", "S-02", "dh_lithology", depth=(85.0, 190.7), field="lithology",
               value="GRA")])

    # DH-E12: dos valores primarios para el mismo tramo y elemento (otra muestra).
    r = rows("assay_long")
    i = r.find(Muestra="M-0103", Elemento="Au")
    duplicate = list(r.rows[i])
    au = ELEMENTS[0]
    _mark, units = basico_samples()[2].values["Au"]
    assert units is not None
    duplicate[3] = "M-0103B"
    duplicate[5] = fixed(units + 5, au.decimals)
    r.rows.insert(i + 1, duplicate)
    add("DH-E12", "assay_long", "Au de M-0103 (S-01) repetido como M-0103B con otro valor",
        r, [issue("DH-E12", "S-01", "dh_assay", depth=_sample_span("M-0103"), field="value",
                  value=duplicate[5])])  # fmt: skip

    # DH-W01: hueco de 1 m entre tramos.
    r = rows("lithology")
    r.set(r.find(Sondeo="S-03", Desde="120,00"), "Desde", "121,00")
    add("DH-W01", "lithology", "S-03: hueco de 120 a 121 m", r,
        [issue("DH-W01", "S-03", "dh_lithology", depth=(120.0, 121.0), field="from_m",
               value="121,00")])

    # DH-W02: primera estación por debajo de la boca.
    r = rows("survey")
    del r.rows[r.find(Sondeo="S-01", Profundidad="0,00")]
    add("DH-W02", "survey", "S-01 sin la estación de 0 m", r,
        [issue("DH-W02", "S-01", "dh_survey", depth=(0.0, 30.0), field="depth",
               value="30,00")])

    # DH-W03: última estación por encima del fondo.
    r = rows("survey")
    del r.rows[r.find(Sondeo="S-01", Profundidad="150,00")]
    add("DH-W03", "survey", "S-01 sin la estación de 150 m (fondo 150)", r,
        [issue("DH-W03", "S-01", "dh_survey", depth=(120.0, 150.0), field="depth",
               value="120,00")])

    # DH-W04: cambio de dirección de 10°/30 m.
    r = rows("survey")
    r.set(r.find(Sondeo="S-01", Profundidad="150,00"), "Inclinación", "-50,00")
    add("DH-W04", "survey", "S-01 a −50° en la estación de 150 m (−60° a 120 m)", r,
        [issue("DH-W04", "S-01", "dh_survey", depth=(120.0, 150.0), field="inclination")])

    # DH-W05: boca 5 m por encima de la superficie.
    r = rows("collar")
    s12 = next(h for h in HOLES if h.name == "S-12")
    r.set(r.find(Sondeo="S-12"), "Z", fixed(s12.z_mm + 5000, 3))
    add("DH-W05", "collar", "S-12 5 m por encima de la superficie (MDT)", r,
        [issue("DH-W05", "S-12", "dh_collar", field="z")])

    # DH-W06: boca fuera de la ventana de trabajo.
    r = rows("collar")
    r.rows.append(list(_extra_collar("S-96", 700_500_500, 4_400_020_500, "40,00")))
    add("DH-W06", "collar", "S-96, una boca nueva a 300 m al este de la ventana", r,
        [issue("DH-W06", "S-96", "dh_collar")])

    # DH-W07: unidad distinta de la del catálogo (sin convertir).
    r = rows("assay_long")
    i = r.find(Muestra="M-0205", Elemento="Cu")
    cu = ELEMENTS[2]
    cu_value = next(s for s in basico_samples() if s.sample_id == "M-0205").values["Cu"]
    r.set(i, "Valor", _value_other(cu, cu_value))
    r.set(i, "Unidad", "ppm")
    add("DH-W07", "assay_long", "Cu de M-0205 (S-02) en ppm (el catálogo, en %)", r,
        [issue("DH-W07", "S-02", "dh_assay", depth=_sample_span("M-0205"), field="unit",
               value="ppm")])

    # DH-W08: valores ≤ 0 sin marca de límite de detección.
    r = rows("assay_long")
    r.set(r.find(Muestra="M-0102", Elemento="Ag"), "Valor", "0")
    r.set(r.find(Muestra="M-0302", Elemento="Ag"), "Valor", "-0,5")
    add("DH-W08", "assay_long", "Ag de M-0102 (S-01) = 0 y de M-0302 (S-03) = −0,5", r,
        [issue("DH-W08", "S-01", "dh_assay", depth=_sample_span("M-0102"), field="value",
               value="0"),
         issue("DH-W08", "S-03", "dh_assay", depth=_sample_span("M-0302"), field="value",
               value="-0,5")])

    # DH-W09: tramo más corto que la longitud mínima.
    r = rows("lithology")
    i = r.find(Sondeo="S-02", Desde="2,40")
    r.set(i, "Hasta", "84,98")
    r.rows.insert(i + 1, ["S-02", "84,98", "85,00", "ARE"])
    add("DH-W09", "lithology", "S-02: ARE partido con un tramo de 2 cm (84,98–85 m)", r,
        [issue("DH-W09", "S-02", "dh_lithology", depth=(84.98, 85.0))])

    # DH-W10: litología sin densidad.
    r = rows("lithology_catalog")
    r.set(r.find(Código="PIZ"), "Densidad", "")
    add("DH-W10", "lithology_catalog", "PIZ sin densidad", r,
        [issue("DH-W10", None, "dh_lithology_code", catalog_code="PIZ", field="density",
               value="")])

    # DH-W11: código de muestra repetido (en otro tramo y otro sondeo).
    r = rows("assay_wide")
    r.set(r.find(Muestra="M-0301"), "Muestra", "M-0101")
    add("DH-W11", "assay_wide", "la primera muestra de S-03 se llama M-0101, como la de S-01",
        r, [issue("DH-W11", "S-03", "dh_assay", depth=_sample_span("M-0301"),
                  field="sample_id", value="M-0101")])  # fmt: skip

    # DH-W12: sondeo planificado con análisis.
    r = rows("collar")
    r.set(r.find(Sondeo="S-02"), "Planificado", "sí")
    add("DH-W12", "collar", "S-02 planificado, con análisis", r,
        [issue("DH-W12", "S-02", "dh_collar", field="planned", value="sí")])

    # DH-W14: todas las estaciones con inclinación > 0.
    r = rows("survey")
    for index, row in enumerate(r.rows):
        if row[0] == "S-01":
            r.set(index, "Inclinación", "60,00")
    add("DH-W14", "survey", "S-01 con +60° en todas sus estaciones", r,
        [issue("DH-W14", "S-01", "dh_survey", field="inclination")])

    # DH-W15: la boca de la capa no está en su X, Y, Z.
    geom = Table(
        ("Sondeo", "X", "Y", "Z"),
        tuple(
            (h.name, fixed(h.east_mm + (2000 if h.name == "S-04" else 0), 3),
             fixed(h.north_mm, 3), fixed(h.z_mm, 3))
            for h in HOLES
        ),
    )  # fmt: skip
    cases.append(ErrorCase(
        "DH-W15", "collar_geom", "posición de las bocas en la capa: S-04, 2 m al este", geom,
        [issue("DH-W15", "S-04", "dh_collar", field="geom")],
    ))  # fmt: skip

    # DH-W16: profundidad deducida (máximo de la última estación y del último hasta).
    r = rows("collar")
    r.set(r.find(Sondeo="S-01"), "Profundidad", "")
    add("DH-W16", "collar", "S-01 sin profundidad: se deduce 150 m", r,
        [issue("DH-W16", "S-01", "dh_collar", field="depth", value="")])
    return cases


def errores_expected(cases: Sequence[ErrorCase]) -> dict:
    """``csv_errores/esperado.json``: umbrales, ventana, superficie y los casos."""
    return {
        "about": (
            "Un caso por código de la tabla 4.4.1 de la spec 005 (sin DH-W13). Cada "
            "fichero sustituye la tabla de csv_basico de su papel («role»; con "
            "«assay_long», los análisis en filas en lugar de en columnas); «collar_geom» "
            "es la posición de las bocas en la capa (DH-W15; en los demás casos, la de "
            "sus X, Y, Z). Validando el DrillholeSet de los ficheros tal como están (sin "
            "convertir unidades), con la declaración de csv_basico cambiada por "
            "«declaration», los umbrales, la ventana de trabajo y la superficie (DH-W05) "
            "de aquí, salen exactamente sus «issues». «value» es el texto de la fuente "
            "del campo; null si la comprobación es de un cálculo. Los tramos con DH-E09 "
            "no entran en las demás comprobaciones de tramos, y un tramo repetido entero "
            "es DH-E12, no DH-E10."
        ),
        "base": "csv_basico",
        "params": VALIDATION_PARAMS,
        "work_window": WORK_WINDOW,
        "surface": SURFACE,
        "cases": [
            {
                "code": case.code,
                "file": case.file,
                "role": case.role,
                "about": case.about,
                "declaration": case.declaration or {},
                "issues": case.issues,
            }
            for case in cases
        ],
    }


# ---------------------------------------------------------------------------------------
# Escritura de los juegos pequeños
# ---------------------------------------------------------------------------------------


def _write(path: Path, text: str) -> str:
    """Escribe ``text`` en UTF-8 sin BOM y con LF; devuelve su sha256."""
    data = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _json_text(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


SETS = ("csv_basico", "csv_convenios", "csv_errores")


def small_files() -> dict[str, tuple[str, str]]:
    """Ruta relativa → (texto, descripción) de cada fichero de los juegos pequeños."""
    files: dict[str, tuple[str, str]] = {}
    base = basico_tables()
    described = {
        "collar": "Bocas: X, Y, Z (sobre la superficie), profundidad, orientación en boca "
        "(solo S-12), tipo, campaña, fechas (dd/mm/aaaa) y planificado",
        "survey": "Desviaciones: 29 estaciones de S-01, S-02, S-03 y S-04",
        "lithology": "Litología: tramos contiguos de 0 m al fondo en los seis sondeos",
        "assay_wide": "Análisis en columnas (Au g/t, Ag ppm, Cu %): 28 muestras de 2 m",
        "assay_long": "Los mismos análisis en filas, con la unidad en cada fila",
        "lithology_catalog": "Catálogo de litologías: color «#RRGGBB», densidad y orden",
        "element_catalog": "Catálogo de elementos: unidad, decimales y límite de detección",
    }
    for role in ROLES:
        files[f"csv_basico/{BASICO_FILES[role]}"] = (base[role].text(";"), described[role])
    files["csv_basico/esperado.json"] = (
        _json_text(basico_expected(base)),
        "Declaraciones, filas por fichero, valores especiales, ventana, superficie y fondo "
        "analítico de cada sondeo",
    )
    conv_described = {
        "positive_dip": "inclinación positiva hacia abajo",
        "from_vertical": "inclinación desde la vertical (0 = hacia abajo)",
        "magnetic": "azimut magnético (δ = +0,25°, γ = +1,50°)",
    }
    for name, table in convenios_tables().items():
        if name.startswith(("collars_", "surveys_")):
            kind, variant = name[:-4].split("_", 1)
            what = "Bocas" if kind == "collars" else "Desviaciones"
            about = f"{what} con {conv_described[variant]}"
        else:
            about = {
                "lithology.csv": "Litología de csv_basico",
                "assays.csv": "Análisis en filas en ppb (Au), g/t (Ag) y ppm (Cu)",
                "lithology_codes.csv": "Catálogo de litologías de csv_basico",
                "elements.csv": "Catálogo de elementos de csv_basico (g/t, ppm, %)",
            }[name]
        files[f"csv_convenios/{name}"] = (table.text(","), about)
    files["csv_convenios/esperado.json"] = (
        _json_text(convenios_expected()),
        "Declaraciones comunes y de cada variante, δ, γ y factores de las unidades",
    )
    cases = error_cases(base)
    for case in cases:
        files[f"csv_errores/{case.file}"] = (case.table.text(";"), f"{case.code}: {case.about}")
    files["csv_errores/esperado.json"] = (
        _json_text(errores_expected(cases)),
        "Umbrales, ventana, superficie y, por caso, papel, declaración e incidencias",
    )
    return files


def write_small(out: Path) -> dict[str, str]:
    """Escribe ``csv_basico/``, ``csv_convenios/`` y ``csv_errores/`` en ``out`` (antes
    borra los ``.csv`` y ``.json`` que hubiera en ellas); devuelve ruta relativa →
    sha256."""
    for name in SETS:
        folder = out / name
        if folder.is_dir():
            for path in folder.iterdir():
                if path.suffix in (".csv", ".json"):
                    path.unlink()
    return {rel: _write(out / rel, text) for rel, (text, _about) in small_files().items()}


def update_readme(readme: Path = README) -> None:
    """Rehace la tabla de ficheros del README (entre sus marcas)."""
    files = small_files()
    lines = ["| Fichero | Contenido | sha256 |", "| --- | --- | --- |"]
    for rel in sorted(files):
        text, about = files[rel]
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        lines.append(f"| `{rel}` | {about} | `{digest}` |")
    old = readme.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(MARK_START) + r".*?" + re.escape(MARK_END), re.DOTALL)
    if not pattern.search(old):
        raise SystemExit(f"{readme}: no están las marcas {MARK_START} … {MARK_END}")
    block = "\n".join([MARK_START, *lines, MARK_END])
    _write(readme, pattern.sub(lambda _m: block, old))


# ---------------------------------------------------------------------------------------
# V-ref (spec 005 §5)
# ---------------------------------------------------------------------------------------

VREF_HOLES = 2000
VREF_STATIONS = 10  # por sondeo, de la boca al fondo
VREF_LITHOLOGY = 25  # tramos por sondeo, contiguos
VREF_GRID_COLUMNS = 50  # bocas en una malla de 25 m, 50 por fila
VREF_FIRST_DAY = datetime.date(2024, 1, 8)


@dataclass(frozen=True)
class VrefElement:
    """Un elemento de V-ref: leyes lognormales (mediana ``median`` en ``unit``, σ del
    logaritmo ``sigma``) con ``decimals`` decimales; ``detection_limit`` en 10^-decimals."""

    code: str
    name: str
    unit: str
    decimals: int
    detection_limit: int
    median: float
    sigma: float


VREF_ELEMENTS: tuple[VrefElement, ...] = (
    VrefElement("Au", "Oro", "g/t", 2, 1, 0.3, 1.2),
    VrefElement("Ag", "Plata", "ppm", 1, 5, 3.0, 1.0),
    VrefElement("Cu", "Cobre", "%", 3, 1, 0.15, 1.0),
    VrefElement("Pb", "Plomo", "%", 3, 1, 0.05, 1.1),
    VrefElement("Zn", "Cinc", "%", 3, 1, 0.08, 1.1),
    VrefElement("As", "Arsénico", "ppm", 0, 5, 60.0, 1.0),
    VrefElement("Sb", "Antimonio", "ppm", 1, 5, 5.0, 1.0),
    VrefElement("Bi", "Bismuto", "ppm", 1, 1, 2.0, 1.0),
    VrefElement("Mo", "Molibdeno", "ppm", 1, 5, 8.0, 1.0),
    VrefElement("W", "Wolframio", "ppm", 0, 2, 20.0, 1.0),
    VrefElement("Sn", "Estaño", "ppm", 0, 1, 10.0, 1.0),
    VrefElement("Fe", "Hierro", "%", 2, 1, 4.0, 0.5),
    VrefElement("S", "Azufre", "%", 2, 1, 1.5, 0.8),
    VrefElement("Ni", "Níquel", "ppm", 0, 2, 30.0, 0.7),
    VrefElement("Co", "Cobalto", "ppm", 0, 1, 15.0, 0.7),
    VrefElement("Mn", "Manganeso", "ppm", 0, 5, 600.0, 0.6),
    VrefElement("Ba", "Bario", "ppm", 0, 10, 300.0, 0.7),
    VrefElement("Hg", "Mercurio", "ppb", 0, 10, 50.0, 1.0),
    VrefElement("Te", "Telurio", "ppm", 2, 5, 0.4, 1.0),
    VrefElement("Cd", "Cadmio", "ppm", 1, 2, 1.0, 1.0),
)
VREF_LITHOLOGY_CODES: tuple[tuple[str, str, str, int, int], ...] = (
    *LITHOLOGY_CODES,
    ("GRA", "Granito", "#E8A0A0", 265, 9),
    ("CUA", "Cuarcita", "#F2F2E6", 265, 10),
)


def _vref_stations(rng: random.Random, depth_cm: int) -> list[tuple[int, int, int]]:
    """Diez estaciones de la boca al fondo; entre dos, la inclinación y el azimut
    horizontal cambian a lo sumo 1,2°/30 m cada uno (≈ 1,7°/30 m de dogleg, < 3°)."""
    azimuth = rng.uniform(0.0, 360.0)
    inclination = rng.uniform(-85.0, -50.0)
    stations: list[tuple[int, int, int]] = []
    previous = 0
    for k in range(VREF_STATIONS):
        md = round(depth_cm * k / (VREF_STATIONS - 1))
        if k:
            limit = 1.2 * (md - previous) / 100.0 / 30.0
            inclination = min(-10.0, max(-89.0, inclination + rng.uniform(-limit, limit)))
            sin_i = math.sin(math.radians(90.0 + inclination))
            azimuth += rng.uniform(-limit, limit) / max(sin_i, 0.2)
        stations.append((md, round(azimuth * 100.0) % 36000, round(inclination * 100.0)))
        previous = md
    return stations


def _vref_value(rng: random.Random, element: VrefElement) -> str:
    """Una ley lognormal con sus decimales; un 3 % (y lo que no llega al límite), «<LD»."""
    scale = 10**element.decimals
    units = round(math.exp(rng.gauss(math.log(element.median), element.sigma)) * scale)
    if rng.random() < 0.03 or units < element.detection_limit:
        return "<" + fixed(element.detection_limit, element.decimals)
    return fixed(units, element.decimals)


def vref_tables(scale: float = 1.0, seed: int = VREF_SEED) -> dict[str, Table]:
    """V-ref en el formato de ``csv_basico``: ``round(2000 · scale)`` sondeos en una malla
    de 25 m (con ±5 m al azar), de 100 a 400 m, con 10 estaciones, 25 tramos de litología
    y 12 o 13 tramos analizados (alternos: 12,5 de media) de 20 elementos cada uno."""
    rng = random.Random(seed)
    holes = max(1, round(VREF_HOLES * scale))
    collars, surveys, lithology, assays = [], [], [], []
    codes = [code for code, *_rest in VREF_LITHOLOGY_CODES]
    for i in range(holes):
        name = f"V-{i + 1:04d}"
        col, row = divmod(i, VREF_GRID_COLUMNS)[::-1]
        east = REF_E_MM + 25_000 * col + rng.randint(-5000, 5000)
        north = REF_N_MM + 25_000 * row + rng.randint(-5000, 5000)
        depth = rng.randint(10000, 40000)
        start = VREF_FIRST_DAY + datetime.timedelta(days=i)
        collars.append((
            name, fixed(east, 3), fixed(north, 3), fixed(surface_mm(east, north), 3),
            fixed(depth, 2), "", "", rng.choice(("DD", "RC", "RC", "AC")), "V-2024",
            _dmy(start), _dmy(start + datetime.timedelta(days=3)), "no",
        ))  # fmt: skip
        for md, az, inc in _vref_stations(rng, depth):
            surveys.append((name, fixed(md, 2), fixed(az, 2), fixed(inc, 2)))
        bounds = [0]
        spacing = depth / VREF_LITHOLOGY
        for k in range(1, VREF_LITHOLOGY):
            bounds.append(round(spacing * k + rng.uniform(-0.3, 0.3) * spacing))
        bounds.append(depth)
        for k in range(VREF_LITHOLOGY):
            lithology.append(
                (name, fixed(bounds[k], 2), fixed(bounds[k + 1], 2), rng.choice(codes))
            )
        top = round(rng.uniform(0.15, 0.6) * depth / 10) * 10
        for k in range(13 if i % 2 == 0 else 12):
            length = rng.choice((100, 200))
            values = [_vref_value(rng, e) for e in VREF_ELEMENTS]
            assays.append(
                (name, fixed(top, 2), fixed(top + length, 2), f"V{i + 1:04d}-{k + 1:02d}",
                 *values)
            )  # fmt: skip
            top += length
    return {
        "bocas.csv": Table(COLLAR_HEADER, tuple(collars)),
        "desviaciones.csv": Table(("Sondeo", "Profundidad", "Azimut", "Inclinación"),
                                  tuple(surveys)),
        "litologia.csv": Table(("Sondeo", "Desde", "Hasta", "Litología"), tuple(lithology)),
        "analisis_columnas.csv": Table(
            ("Sondeo", "Desde", "Hasta", "Muestra", *(e.code for e in VREF_ELEMENTS)),
            tuple(assays),
        ),
        "litologias.csv": Table(
            ("Código", "Descripción", "Color", "Densidad", "Orden"),
            tuple(
                (c, d, rgb, fixed(rho, 2), str(o)) for c, d, rgb, rho, o in VREF_LITHOLOGY_CODES
            ),
        ),
        "elementos.csv": Table(
            ("Código", "Nombre", "Unidad", "Decimales", "Límite de detección"),
            tuple(
                (e.code, e.name, e.unit, str(e.decimals),
                 fixed(e.detection_limit, e.decimals))
                for e in VREF_ELEMENTS
            ),
        ),
    }  # fmt: skip


def write_vref(out: Path, *, scale: float = 1.0, seed: int = VREF_SEED) -> dict[str, str]:
    """Escribe V-ref en ``out`` (``vref_tables``); devuelve fichero → sha256."""
    return {
        name: _write(out / name, table.text(";"))
        for name, table in vref_tables(scale, seed).items()
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.data.dh.sintetico",
        description="Datos sintéticos de sondeos de la spec 005 (tests/data/dh/README.md).",
    )
    parser.add_argument("--out", type=Path, help="carpeta de los juegos pequeños "
                        "(sin tocar el README)")  # fmt: skip
    parser.add_argument("--vref", type=Path, help="carpeta donde escribir V-ref")
    parser.add_argument("--escala", type=float, default=1.0, help="fracción de V-ref")
    parser.add_argument("--semilla", type=int, default=VREF_SEED, help="semilla de V-ref")
    args = parser.parse_args(argv)
    if args.vref is not None:
        hashes = write_vref(args.vref, scale=args.escala, seed=args.semilla)
    else:
        hashes = write_small(args.out or HERE)
        if args.out is None:
            update_readme()
    for name in sorted(hashes):
        print(f"{hashes[name]}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
