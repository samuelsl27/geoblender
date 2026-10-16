# SPDX-License-Identifier: GPL-3.0-or-later
"""Validación de los sondeos (spec 005, T08 a T10; RF-005-16, RF-005-17, RF-005-18; spec §4.4.1
y §8; plan 005 §5.3.2, §5.4 y §5.6.6).

:func:`validate` aplica a un ``DrillholeSet`` las comprobaciones de la tabla 4.4.1 de la spec
y da un :class:`ValidationReport`: una :class:`Issue` por incidencia, con su código, su nivel
y su alcance (:data:`CODES`), el sondeo (posición entre las bocas y nombre), la tabla del
modelo de datos (``dh_collar``, ``dh_survey``…), la fila de esa tabla, el tramo o la
profundidad, el campo, el valor y un mensaje en español que dice qué corregir
(:meth:`Issue.message`; ``msgid`` en inglés en :data:`MESSAGES` y su español en
``core/i18n/messages.toml``). :meth:`ValidationReport.excluded` da lo que se excluye
(RF-005-17, :class:`Exclusions`): los sondeos enteros (alcance S), las tablas, esquemas o
elementos de un sondeo (T) y los registros (R); nada más.

**La parte de las bocas y las desviaciones** (T08): DH-E01 a DH-E08, DH-W02, DH-W03, DH-W04,
DH-W06, DH-W14, DH-W15 y DH-W16. **La de los tramos, los valores y los catálogos** (T09):
DH-E09 a DH-E12, DH-W01 y DH-W07 a DH-W12. **La diferencia con el MDT** (T10; RF-005-18):
DH-W05 y ``ValidationReport.collar_dem_dz``.

**El MDT** (RF-005-18; plan §5.6.6, D-19): un :class:`~.ports.SurfaceSampler` (en el trabajo,
``drillholes.surface.raster_sampler`` del ``gis_dtm_*`` elegido: la bilineal de la 006) en el
CRS y la referencia vertical de los sondeos (los del proyecto; otros son un error del
programa: nunca se suponen). Se le pide una vez la cota de las bocas que se comprueban (sin
DH-E01) con X, Y y Z; la diferencia de cada una es dz = Z de la boca − z del MDT en su
posición (m, CALCULADO), y DH-W05 avisa si |dz| pasa de ``collar_dem_tolerance_m`` (justo en
ella, no), con el campo ``z`` y sin valor (es un cálculo). **Lo que no se evalúa, el informe
lo dice** (spec §8) con una :class:`Note`: sin MDT, una nota general (``hole`` −1) y ninguna
diferencia (``collar_dem_dz`` es ``None``); una boca fuera del MDT (o con un vecino sin dato),
una nota suya y su diferencia vacía (NaN). Una boca sin X, Y o Z ya tiene su DH-E02, y una de
un nombre repetido, su DH-E01: no se muestrean ni llevan nota. **La diferencia de cada boca, a
la vista** (T56; RF-005-18, spec §6 y §8): el informe da una entrada DH-W05 por boca que se
muestrea, sobre su boca (``dh_collar``, campo ``z``): el aviso, si pasa de la tolerancia; si
no, su :class:`DemDifference` (nivel «información», con su cota, la del MDT y dz al mm en el
mensaje); fuera del MDT, su nota «sin evaluar» (con su boca). No son incidencias: no cuentan
ni excluyen nada.

**La parte de alcance S, para la desviación** (plan §5.6.6): :func:`hole_exclusions` da la
máscara de los sondeos con un error de alcance S (los que ``desurvey`` no puede calcular), sin
crear incidencias; ``dh.desurvey`` la calcula ella misma con
``desurvey(dset, holes=~hole_exclusions(dset, depth_tolerance_m=…))`` y no consume el informe.
Es la misma máscara que ``validate(...).excluded().holes``. **Para la vista** (T30; RF-005-17,
plan §5.6.8): :func:`exclusion_codes` da los códigos de alcance S de cada boca (los que marca
la superposición en las que no tienen traza), y :func:`stored_exclusions` y
:func:`stored_codes`, lo que excluye el informe guardado en ``dh_validation_issue`` (sus
tablas y registros, que no se pintan, y los códigos de alcance T de cada sondeo).

Reglas que la spec no fija (decisiones de la T08, revisables; las mismas que los casos de
``tests/data/dh/csv_errores``):

- **DH-E01**: una incidencia por repetición (el sondeo, la primera grafía; el valor, la
  repetida); se excluyen todas las bocas del nombre y no se comprueba nada más de ellas: sus
  filas hijas no se sabe de cuál son.
- **DH-E07**: por encima de la boca (profundidad negativa o no finita) siempre; por debajo del
  fondo más la tolerancia, solo con una profundidad total válida (sin DH-E03).
- **DH-E08**: el azimut vale en [0, 360]: 360 es el 0 de la fuente (spec §8, «se guarda como
  0»; la base nunca lo tiene, porque ``conventions.to_grid_azimuth`` lo pasa a 0).
- **Avisos de las desviaciones** (DH-W02, W03, W04 y W14): solo en los sondeos que tendrán traza
  (sin errores de alcance S). DH-W02 y W03, solo si la estación prolongada es medida (la
  orientación en boca y la vertical declarada definen un sondeo recto), como los avisos de la
  traza (``desurvey.TraceWarning``). El campo de DH-W04 es el ángulo que más cambia: la
  inclinación, o el azimut por su componente sobre la esfera (ΔA·cos θ).
- **DH-W15**: la posición de la capa distinta de la X, Y, Z guardada en cualquier cifra (la
  que falta en las dos es igual).
- **DH-W16**: la profundidad total CALCULADO (``depth_kind``), la que deduce
  :func:`deduce_depths` de la última estación y del último hasta (litología, análisis y zonas)
  cuando la fuente no la trae; la aplican los lectores (T14, T15). Sin nada de donde deducirla,
  sigue ausente y es DH-E03.

Las de los tramos, los valores y los catálogos (decisiones de la T09, revisables; las mismas
que los casos de ``csv_errores``):

- **Qué filas**: las de un sondeo con boca y sin DH-E01 (las demás ya son DH-E04 o DH-E01: no
  se sabe de qué boca son), aunque la boca tenga otro error de alcance S: los tramos no
  dependen de la traza.
- **Tramos** (DH-E09, E10, E12, W01 y W09): en la litología, por sondeo y esquema de logueo;
  en los análisis, por sondeo y elemento, solo los valores primarios (DH-E09, todos los que
  tienen tramo; un material de referencia o un blanco sin tramo, no); en las intersecciones
  con zonas, solo DH-E09. **DH-E09**, una incidencia por campo: desde ausente o < 0; hasta
  ausente, ≤ desde o por debajo del fondo más la tolerancia (esta, solo con una profundidad
  total válida). Los tramos con DH-E09 no entran en las demás comprobaciones de tramos.
- **Solape y hueco** (DH-E10, W01), contra el hasta más hondo de los tramos anteriores del
  grupo (ordenados por desde, hasta y fila): solape si el desde queda por encima (exacto, sin
  margen: los contiguos tienen el mismo número); hueco si queda más de la tolerancia por
  debajo. El tramo de la incidencia es el solape (del desde al menor de los dos hasta) o el
  hueco; el campo, ``from_m``. **Tramo corto** (DH-W09): hasta < desde + longitud mínima. Los
  umbrales, sumados como en DH-E07: un hueco o un tramo justo en el umbral no avisa.
- **DH-E12**: dos valores primarios del mismo elemento con el mismo desde y hasta; una
  incidencia por cada repetido (queda el primero en orden de filas), que no es DH-E10 ni entra
  en las demás comprobaciones de tramos.
- **DH-E11**: la litología por esquema de logueo y código; el elemento; el sector y el grupo de
  la boca (excluye ``(sondeo, "dh_collar", None)``, que no quita la traza); la zona de una
  intersección (``(sondeo, "dh_zone_interval", None)``) o de un corte. Una por fila.
- **DH-W07**: la unidad guardada distinta (en el texto) de la del catálogo del elemento: la
  que la conversión (``conventions.convert_assays``) no pudo llevar a la del catálogo. Un
  elemento sin catálogo es DH-E11, no DH-W07. **DH-W08**: un valor finito ≤ 0 con la marca
  «ok», de cualquier análisis con boca.
- **DH-W10**: cada litología del catálogo sin densidad, sin sondeo (al final del informe).
  **DH-W11**: el mismo código de muestra (sin mayúsculas ni espacios exteriores) en otro tramo
  (sondeo, desde y hasta): una incidencia por tramo repetido, no por elemento, tras el primero
  en orden de sondeo y desde. **DH-W12**: un sondeo planificado con algún análisis.

**Valor** de una incidencia: el número, el texto o el sí/no guardado en el campo; «» si el
campo está vacío (un número ausente o, en DH-W16, la profundidad que la fuente no traía);
``None`` si la comprobación es de un cálculo (DH-E05, W04, W05, W06, W09, W14, W15). El valor
es un número solo en los campos de :data:`NUMBER_FIELDS` (T27: así se lee otra vez el que
guarda ``dh_validation_issue`` en texto).

El orden es determinista: por boca (los registros sin boca, al final), código, tabla y fila.
Nada modifica la entrada. Python puro y numpy (ADR-0004); vectorial salvo al crear las
incidencias.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import KW_ONLY, dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar

import numpy as np

from ..core.georef import CrsRef, Window
from ..core.i18n import LANGUAGES, translate
from ..core.params import ParamKind
from .desurvey import direction, dogleg
from .model import (
    AssayColumns,
    CollarColumns,
    DetectionFlag,
    DrillholeSet,
    QaqcType,
    StationSource,
    SurveyColumns,
    name_key,
)
from .ports import SurfaceSampler

__all__ = [
    "CATALOG_TABLES",
    "CODES",
    "MESSAGES",
    "NUMBER_FIELDS",
    "TABLE_NAMES",
    "DemDifference",
    "Exclusions",
    "Issue",
    "Level",
    "Note",
    "Scope",
    "ValidationParams",
    "ValidationReport",
    "deduce_depths",
    "exclusion_codes",
    "hole_exclusions",
    "no_dem_note",
    "stored_codes",
    "stored_exclusions",
    "validate",
]

type JsonScalar = str | int | float | bool | None


class Level(StrEnum):
    """El nivel de una fila del informe (``dh_validation_issue.level``): el de una
    incidencia (:data:`CODES`: error o aviso) o, en lo que no es una incidencia (T56), el de
    la diferencia de una boca con el MDT dentro de la tolerancia (:class:`DemDifference`) y el
    de lo que no se evaluó (:class:`Note`)."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    NOT_EVALUATED = "not_evaluated"


class Scope(StrEnum):
    """Lo que excluye un error (spec §4.4.1; ``dh_validation_issue.scope``)."""

    HOLE = "hole"  # S: el sondeo entero
    TABLE = "table"  # T: esa tabla (esquema de logueo o elemento) de ese sondeo
    RECORD = "record"  # R: ese registro


_S = (Level.ERROR, Scope.HOLE)
_T = (Level.ERROR, Scope.TABLE)
_W = (Level.WARNING, None)
CODES: Mapping[str, tuple[Level, Scope | None]] = MappingProxyType({
    "DH-E01": _S,
    "DH-E02": _S,
    "DH-E03": _S,
    "DH-E04": (Level.ERROR, Scope.RECORD),
    "DH-E05": _S,
    "DH-E06": _S,
    "DH-E07": _S,
    "DH-E08": _S,
    **{f"DH-E{k:02d}": _T for k in range(9, 13)},
    **{f"DH-W{k:02d}": _W for k in (*range(1, 13), 14, 15, 16)},
})
"""Los códigos de la tabla 4.4.1 de la spec (sin DH-W13, que queda para R-14), con su nivel
y su alcance (los avisos no excluyen)."""

TABLE_NAMES: Mapping[str, str] = MappingProxyType({
    "collars": "dh_collar",
    "surveys": "dh_survey",
    "lithology": "dh_lithology",
    "assays": "dh_assay",
    "zones": "dh_zone_interval",
    "structures": "dh_structure",
})
"""La tabla del modelo de datos (plan §5.2) de cada tabla de un ``DrillholeSet``."""
CATALOG_TABLES: tuple[str, ...] = ("dh_lithology_code", "dh_element", "dh_sector", "dh_group",
                                   "dh_zone")
"""Las tablas de los catálogos (las incidencias de un catálogo no tienen sondeo)."""
NUMBER_FIELDS: frozenset[str] = frozenset({"x", "y", "z", "depth", "azimuth", "inclination",
                                           "from_m", "to_m", "value", "density"})
"""Los campos de una incidencia cuyo valor es un número (o «» si el campo está vacío): las
coordenadas y la profundidad de una boca, la profundidad y los ángulos de una estación, el
tramo, el valor de un análisis y la densidad de una litología. En los demás es un texto o un
sí/no."""
_TABLE_ORDER ={name: k for k, name in enumerate((*TABLE_NAMES.values(), *CATALOG_TABLES))}
_COLLAR = TABLE_NAMES["collars"]
_SURVEY = TABLE_NAMES["surveys"]

MESSAGES: Mapping[str, str] = MappingProxyType({
    "DH-E01": "Hole name «{hole}» is repeated as «{repeated}» (names are compared ignoring "
              "case and outer spaces): rename or remove one of them.",
    "DH-E02": "Collar {axis} is missing or is not a finite number: enter the coordinate in "
              "the collar table.",
    "DH-E03.missing": "The total depth is missing and cannot be deduced (the hole has no "
                      "stations or intervals below the collar): enter it in the collar "
                      "table.",
    "DH-E03.invalid": "The total depth, {depth} m, is not a finite number greater than 0: "
                      "correct it in the collar table.",
    "DH-E04": "Hole «{hole}» of this record has no collar: add its collar or correct the "
              "hole name.",
    "DH-E04.unnamed": "This sample has no hole: give it its hole and its interval.",
    "DH-E05": "The hole has no survey stations and no collar orientation, and it is not "
              "declared vertical: import its surveys, give its collar orientation or declare "
              "it vertical when importing.",
    "DH-E06": "Two survey stations at the same depth, {depth} m: remove the repeated one or "
              "correct its depth.",
    "DH-E07.above": "The survey station is above the collar (negative depth) or has no "
                    "depth: correct its depth.",
    "DH-E07.below": "The survey station at {depth} m is below the bottom of the hole "
                    "({bottom} m, with a tolerance of {tolerance} m): correct its depth or "
                    "the total depth.",
    "DH-E08.azimuth": "The azimuth is not between 0° and 360°: correct it (degrees from "
                      "north, clockwise).",
    "DH-E08.inclination": "The inclination is not between −90° and 90°: correct it (degrees "
                          "from the horizontal, negative downwards).",
    "DH-E09.from": "The interval starts above the collar (negative depth) or has no from "
                   "depth: correct its from depth.",
    "DH-E09.no_to": "The interval has no to depth: enter it.",
    "DH-E09.reversed": "The interval ends at {depth_to} m, not below its start at "
                       "{depth_from} m: correct its from or to depth.",
    "DH-E09.below": "The interval ends at {depth_to} m, below the bottom of the hole "
                    "({bottom} m, with a tolerance of {tolerance} m): correct its to depth or "
                    "the total depth.",
    "DH-E10": "The interval overlaps another one of the logging scheme «{log_set}» from "
              "{depth_from} to {depth_to} m: correct their from and to depths.",
    "DH-E10.assay": "The {element} value overlaps another primary value of the same element "
                    "from {depth_from} to {depth_to} m: correct their from and to depths, or "
                    "mark one of them as not primary.",
    "DH-E11.lithology": "The lithology code «{code}» is not in the catalog of the logging "
                        "scheme «{log_set}»: add it to the catalog or correct the code.",
    "DH-E11.element": "The element «{code}» is not in the element catalog: add it to the "
                      "catalog or correct the code.",
    "DH-E11.sector": "The sector «{code}» is not in the sector catalog: add it to the catalog "
                     "or correct the code.",
    "DH-E11.group": "The group «{code}» is not in the group catalog: add it to the catalog or "
                    "correct the code.",
    "DH-E11.zone": "The zone «{code}» is not in the zone catalog: add it to the catalog or "
                   "correct the code.",
    "DH-E12": "There is more than one primary {element} value for the interval from "
              "{depth_from} to {depth_to} m: keep one as primary and mark the others as "
              "duplicates, or remove them.",
    "DH-W01": "There is a gap with no interval from {depth_from} to {depth_to} m (more than "
              "{tolerance} m): add the missing interval or correct the depths.",
    "DH-W02": "The first survey station is at {depth} m, below the collar: its orientation "
              "is extended up to the collar. If there is a measurement at the collar, add "
              "it.",
    "DH-W03": "The last survey station is at {depth} m, above the bottom ({bottom} m): its "
              "orientation is extended down to the bottom. If there are deeper "
              "measurements, add them.",
    "DH-W04": "The direction changes {rate}°/30 m between the stations at {depth_from} and "
              "{depth_to} m (more than {limit}°/30 m): check their azimuth and inclination.",
    "DH-W05": "The collar elevation, {z} m, minus the DTM elevation at its position, {dem} m, "
              "is {dz} m (more than {tolerance} m either way): check the collar Z and its "
              "vertical datum, or the DTM.",
    "DH-W05.dz": "The collar elevation, {z} m, minus the DTM elevation at its position, "
                 "{dem} m, is {dz} m (within the tolerance of {tolerance} m).",
    "DH-W05.no_dem": "No DTM was chosen: the collar elevations have not been compared with "
                     "the terrain (DH-W05 not evaluated). Choose a DTM when validating to "
                     "compare them.",
    "DH-W05.outside": "The collar is outside the DTM or next to cells without data: its "
                      "elevation has not been compared with the terrain (DH-W05 not "
                      "evaluated).",
    "DH-W06": "The collar is outside the project work window: check its coordinates and the "
              "declared CRS, or enlarge the work window.",
    "DH-W07": "The value is in {unit} and the catalog unit of {element} is {catalog_unit}; it "
              "could not be converted: check the unit.",
    "DH-W08": "The value, {value}, is zero or negative and has no detection limit mark: if it "
              "is below the detection limit, write it as «<limit» (or declare when importing "
              "that a negative value means «<x»); if it is missing, leave it empty.",
    "DH-W09": "The interval from {depth_from} to {depth_to} m is shorter than the minimum "
              "length ({limit} m): check its depths or join it to the next one.",
    "DH-W10": "The lithology «{code}» has no density: enter it in the lithology catalog, with "
              "its kind, before using it to calculate tonnes.",
    "DH-W11": "The sample code «{sample}» is also used in hole «{hole}» from {depth_from} to "
              "{depth_to} m: give each sample its own code.",
    "DH-W12": "The hole is planned but has assays: if it has been drilled, mark it as not "
              "planned; if not, check which hole the assays belong to.",
    "DH-W14": "All survey stations of the hole have a positive inclination: check the "
              "declared inclination convention (here it is negative downwards).",
    "DH-W15": "The collar in the layer is not at its X, Y, Z (it was moved outside "
              "Geoblender): the stored X, Y, Z prevails; recompute the base to put it back.",
    "DH-W16": "The source did not give the total depth: {depth} m has been deduced from the "
              "deepest station or interval (CALCULADO). If you know it, enter it in the "
              "collar table.",
})
"""El ``msgid`` (inglés) del mensaje de cada comprobación (o de cada variante,
``código.variante``, también las de las notas de :class:`Note`); su español está en
``core/i18n/messages.toml``."""
_DEM_DECIMALS = 3  # la cota del MDT y la diferencia que se muestran (mm)

_AXES = ("x", "y", "z")
_FULL_TURN_DEG = 360.0
_RIGHT_ANGLE_DEG = 90.0
_HALF_TURN_DEG = 180.0
_DOGLEG_LENGTH_M = 30.0  # la longitud de la unidad del umbral, °/30 m
_RATE_DECIMALS = 2  # el cambio de dirección que se muestra
_MISSING_SHOWN = "?"
_MEASURED = SurveyColumns.code_values("source").index(StationSource.MEASURED)
_CALCULADO = CollarColumns.code_values("depth_kind").index(ParamKind.CALCULADO)
_SAMPLE = AssayColumns.code_values("qaqc_type").index(QaqcType.SAMPLE)
_FLAG_OK = AssayColumns.code_values("detection_flag").index(DetectionFlag.OK)
_LITHOLOGY = TABLE_NAMES["lithology"]
_ASSAY = TABLE_NAMES["assays"]
_LITHOLOGY_CODE = CATALOG_TABLES[0]
_COLLAR_CODES = (("sector", "sectors"), ("group", "groups"))
"""Los códigos de catálogo de una boca (DH-E11): campo y catálogo de ``Catalogs``."""


# --- Umbrales, incidencias, exclusiones e informe ---------------------------------------------


def _threshold(value: object, what: str) -> float:
    """Un umbral: un número finito ≥ 0, en float64."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{what} es un número, no {value!r}")
    found = float(value)
    if not math.isfinite(found) or found < 0.0:
        raise ValueError(f"{what} es un número finito ≥ 0, no {value!r}")
    return found


@dataclass(frozen=True, slots=True)
class ValidationParams:
    """Los umbrales de la validación (spec §11; parámetros ``dh.validation.*`` de
    ``core.params``, ADOPTADO; plan §5.6.3): tolerancia de profundidad (DH-E07, DH-E09), de
    hueco (DH-W01), tramo mínimo (DH-W09), cambio de dirección en °/30 m (DH-W04) y diferencia
    con el MDT (DH-W05), en m. Sin valor por defecto: salen de los parámetros del proyecto."""

    depth_tolerance_m: float
    gap_tolerance_m: float
    min_interval_m: float
    dogleg_max_deg_30m: float
    collar_dem_tolerance_m: float

    def __post_init__(self) -> None:
        for item in dataclasses.fields(self):
            value = _threshold(getattr(self, item.name), f"el umbral {item.name}")
            object.__setattr__(self, item.name, value)


def _args(value: object) -> tuple[tuple[str, JsonScalar], ...]:
    items = value.items() if isinstance(value, Mapping) else value
    found = []
    for name, shown in items:  # type: ignore[union-attr]
        if not isinstance(name, str):
            raise TypeError(f"los valores de un mensaje van por nombre, no {name!r}")
        if shown is not None and not isinstance(shown, str | int | float | bool):
            raise TypeError(f"el valor «{name}» de un mensaje es un escalar, no {shown!r}")
        found.append((name, shown))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class Issue:
    """Una incidencia de la validación (RF-005-16; ``dh_validation_issue``).

    ``hole`` es la posición de la boca entre las del conjunto (−1 sin boca: DH-E04 o un
    catálogo) y ``hole_name``, su nombre tal como está guardado (en DH-E04, el de la fila);
    ``table``, la tabla del modelo de datos; ``row_ref``, la fila de esa tabla en el conjunto
    (``None`` si la incidencia es del sondeo o del cálculo). ``log_set`` o ``element``, el
    esquema de logueo o el elemento de un tramo; ``catalog_code``, la entrada de un catálogo;
    ``depth_from`` y ``depth_to``, el tramo o la profundidad (m; una estación, las dos
    iguales). ``field`` y ``value``, el campo y su valor (véase el módulo). ``message_id`` y
    ``message_args``, el ``msgid`` del mensaje y sus valores (escalares, por nombre)."""

    code: str
    hole: int
    hole_name: str | None
    table: str
    _: KW_ONLY
    message_id: str
    message_args: tuple[tuple[str, JsonScalar], ...] = ()
    row_ref: int | None = None
    log_set: str | None = None
    element: str | None = None
    catalog_code: str | None = None
    depth_from: float | None = None
    depth_to: float | None = None
    field: str | None = None
    value: str | float | bool | None = None

    def __post_init__(self) -> None:
        if self.code not in CODES:
            raise ValueError(f"«{self.code}» no es un código de la tabla 4.4.1 de la spec 005")
        if isinstance(self.hole, bool) or not isinstance(self.hole, int | np.integer):
            raise TypeError(f"el sondeo de una incidencia es su posición (int), no {self.hole!r}")
        if self.hole < -1:
            raise ValueError(f"el sondeo de una incidencia es su posición o −1, no {self.hole}")
        object.__setattr__(self, "hole", int(self.hole))
        if self.table not in _TABLE_ORDER:
            raise ValueError(f"«{self.table}» no es una tabla de los sondeos")
        if not isinstance(self.message_id, str) or not self.message_id:
            raise ValueError("una incidencia lleva el msgid de su mensaje")
        object.__setattr__(self, "message_args", _args(self.message_args))

    @property
    def level(self) -> Level:
        """Error o aviso (:data:`CODES`)."""
        return CODES[self.code][0]

    @property
    def scope(self) -> Scope | None:
        """Lo que excluye (S, T o R; ``None`` en un aviso)."""
        return CODES[self.code][1]

    def message(self, language: str = "es") -> str:
        """El mensaje en ``language`` (``"es"``, por defecto, o ``"en"``, el ``msgid``), con
        sus números en el formato del idioma (coma decimal en español)."""
        return _message(self.message_id, self.message_args, language)


@dataclass(frozen=True, slots=True)
class Note:
    """Lo que el informe dice de una comprobación que no se evaluó (spec §8; RF-005-18): sin
    MDT, DH-W05 en ninguna boca; con la boca fuera del MDT, en esa. ``code``, la comprobación
    (de :data:`CODES`); ``hole`` y ``hole_name``, la boca (posición y nombre; −1 y ``None``:
    todas); ``message_id`` y ``message_args``, como en :class:`Issue`; ``table``, ``row_ref``
    y ``field``, lo que no se comprobó en una boca (T56: la de una boca fuera del MDT,
    ``dh_collar``, su fila y ``z``; ``None`` en una general). No es una incidencia: su nivel
    es «sin evaluar» y no excluye nada."""

    code: str
    hole: int
    hole_name: str | None
    _: KW_ONLY
    message_id: str
    message_args: tuple[tuple[str, JsonScalar], ...] = ()
    table: str | None = None
    row_ref: int | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        if self.code not in CODES:
            raise ValueError(f"«{self.code}» no es un código de la tabla 4.4.1 de la spec 005")
        if isinstance(self.hole, bool) or not isinstance(self.hole, int | np.integer):
            raise TypeError(f"la boca de una nota es su posición (int), no {self.hole!r}")
        if self.hole < -1:
            raise ValueError(f"la boca de una nota es su posición o −1, no {self.hole}")
        object.__setattr__(self, "hole", int(self.hole))
        if not isinstance(self.message_id, str) or not self.message_id:
            raise ValueError("una nota lleva el msgid de su mensaje")
        object.__setattr__(self, "message_args", _args(self.message_args))
        if self.table is not None and self.table not in _TABLE_ORDER:
            raise ValueError(f"«{self.table}» no es una tabla de los sondeos")
        if self.row_ref is not None:
            if isinstance(self.row_ref, bool) or not isinstance(self.row_ref,
                                                                int | np.integer):
                raise TypeError(f"la fila de una nota es su posición (int), no "
                                f"{self.row_ref!r}")
            object.__setattr__(self, "row_ref", int(self.row_ref))

    @property
    def level(self) -> Level:
        """Sin evaluar."""
        return Level.NOT_EVALUATED

    def message(self, language: str = "es") -> str:
        """El mensaje en ``language`` (como :meth:`Issue.message`)."""
        return _message(self.message_id, self.message_args, language)


@dataclass(frozen=True, slots=True)
class DemDifference:
    """La diferencia de la cota de una boca con la del MDT en su posición, dentro de la
    tolerancia (T56; RF-005-18): ``hole`` y ``hole_name``, la boca (posición y nombre);
    ``dz``, su cota menos la del MDT (m, float64, CALCULADO); ``message_args``, la cota, la del
    MDT y dz al mm y la tolerancia (los de DH-W05). Es la fila DH-W05 de su boca (``dh_collar``,
    su fila, campo ``z``, sin valor: es un cálculo) con el nivel «información»: no es una
    incidencia y no excluye nada. Una boca que pasa de la tolerancia tiene, en su lugar, su
    aviso DH-W05 (con la diferencia en el mensaje)."""

    hole: int
    hole_name: str | None
    dz: float
    _: KW_ONLY
    message_args: tuple[tuple[str, JsonScalar], ...] = ()

    code: ClassVar[str] = "DH-W05"
    table: ClassVar[str] = _COLLAR
    field: ClassVar[str] = "z"
    level: ClassVar[Level] = Level.INFO
    message_id: ClassVar[str] = MESSAGES["DH-W05.dz"]

    def __post_init__(self) -> None:
        if isinstance(self.hole, bool) or not isinstance(self.hole, int | np.integer):
            raise TypeError(f"la boca de una diferencia es su posición (int), no {self.hole!r}")
        if self.hole < 0:
            raise ValueError(f"la boca de una diferencia es su posición, no {self.hole}")
        object.__setattr__(self, "hole", int(self.hole))
        if isinstance(self.dz, bool) or not isinstance(self.dz, int | float | np.floating):
            raise TypeError(f"la diferencia con el MDT es un número, no {self.dz!r}")
        if not math.isfinite(self.dz):
            raise ValueError(f"la diferencia con el MDT es un número finito, no {self.dz!r}")
        object.__setattr__(self, "dz", float(self.dz))
        object.__setattr__(self, "message_args", _args(self.message_args))

    @property
    def row_ref(self) -> int:
        """La fila de su boca en ``dh_collar`` (su posición)."""
        return self.hole

    def message(self, language: str = "es") -> str:
        """El mensaje en ``language`` (como :meth:`Issue.message`)."""
        return _message(self.message_id, self.message_args, language)


def no_dem_note() -> Note:
    """La nota de una validación sin MDT (D-19; spec §8): DH-W05 no se evaluó en ninguna
    boca. La que da :func:`validate` y la que lee la exportación de la que guardó el proyecto
    (T27)."""
    return Note("DH-W05", -1, None, message_id=MESSAGES["DH-W05.no_dem"])


def _message(message_id: str, message_args: tuple[tuple[str, JsonScalar], ...],
             language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    shown = {name: _shown(value, language) for name, value in message_args}
    return translate(language, message_id, **shown)


def _shown(value: JsonScalar, language: str) -> str:
    """Un valor de un mensaje como lo lee una persona: un decimal con coma en español y sin
    decimales si es entero; sí o no; :data:`_MISSING_SHOWN` si falta."""
    if value is None:
        return _MISSING_SHOWN
    if isinstance(value, bool):
        yes = "sí" if language == "es" else "yes"
        return yes if value else "no"
    if isinstance(value, float):
        text = str(int(value)) if value.is_integer() else repr(value)
        return text.replace(".", ",") if language == "es" else text
    return str(value)


@dataclass(frozen=True, eq=False)
class Exclusions:
    """Lo que excluyen los errores de un informe del cálculo de las trazas y de la vista
    (RF-005-17): ``holes``, una máscara por boca (alcance S); ``tables``, (posición de la boca,
    tabla, esquema de logueo o elemento) (T); ``records``, (tabla, fila) (R)."""

    holes: np.ndarray
    tables: frozenset[tuple[int, str, str | None]] = frozenset()
    records: frozenset[tuple[str, int]] = frozenset()

    @property
    def traceable(self) -> np.ndarray:
        """La máscara de los sondeos que tienen traza (los que no excluye un error S)."""
        return ~self.holes


@dataclass(frozen=True)
class ValidationReport:
    """Las incidencias de una validación, en su orden (véase el módulo), de un conjunto de
    ``hole_count`` bocas; ``notes``, lo que no se evaluó (:class:`Note`), y
    ``collar_dem_dz``, la diferencia de cada boca con el MDT (RF-005-18; m, float64, de solo
    lectura; NaN en las que no se evaluaron), o ``None`` si no hubo MDT. La diferencia no
    entra en la comparación de dos informes (``==``). ``differences`` (T56), la de cada boca
    dentro de la tolerancia, por boca (:class:`DemDifference`: las que el informe muestra
    con el nivel «información»)."""

    issues: tuple[Issue, ...]
    hole_count: int
    notes: tuple[Note, ...] = ()
    collar_dem_dz: np.ndarray | None = dataclasses.field(default=None, compare=False)
    differences: tuple[DemDifference, ...] = ()

    def __post_init__(self) -> None:
        found = tuple(self.issues)
        if not all(isinstance(issue, Issue) for issue in found):
            raise TypeError("las incidencias de un informe son Issue")
        if isinstance(self.hole_count, bool) or not isinstance(self.hole_count, int):
            raise TypeError(f"el número de bocas es un entero, no {self.hole_count!r}")
        if any(issue.hole >= self.hole_count for issue in found):
            raise ValueError(f"una incidencia apunta a una boca fuera de [0, {self.hole_count})")
        object.__setattr__(self, "issues", found)
        notes = tuple(self.notes)
        if not all(isinstance(note, Note) for note in notes):
            raise TypeError("las notas de un informe son Note")
        if any(note.hole >= self.hole_count for note in notes):
            raise ValueError(f"una nota apunta a una boca fuera de [0, {self.hole_count})")
        object.__setattr__(self, "notes", notes)
        differences = tuple(self.differences)
        if not all(isinstance(found, DemDifference) for found in differences):
            raise TypeError("las diferencias con el MDT de un informe son DemDifference")
        if any(found.hole >= self.hole_count for found in differences):
            raise ValueError(f"una diferencia con el MDT apunta a una boca fuera de "
                             f"[0, {self.hole_count})")
        object.__setattr__(self, "differences", differences)
        dz = self.collar_dem_dz
        if dz is not None:
            if not isinstance(dz, np.ndarray) or dz.dtype != np.float64:
                raise TypeError(f"la diferencia con el MDT es un array float64, no {dz!r}")
            if dz.shape != (self.hole_count,):
                raise ValueError(f"la diferencia con el MDT es una por boca "
                                 f"({self.hole_count},), no {dz.shape}")

    def excluded(self) -> Exclusions:
        """Lo que excluyen sus errores (RF-005-17): el sondeo de cada error S (y, en uno de
        una boca, la boca de su fila: las repetidas de DH-E01), la tabla, esquema o elemento
        del sondeo de cada error T y el registro de cada error R; nada más."""
        holes = np.zeros(self.hole_count, dtype=np.bool_)
        tables: set[tuple[int, str, str | None]] = set()
        records: set[tuple[str, int]] = set()
        for issue in self.issues:
            level, scope = CODES[issue.code]
            if level is not Level.ERROR:
                continue
            if scope is Scope.HOLE:
                if issue.hole >= 0:
                    holes[issue.hole] = True
                if issue.table == _COLLAR and issue.row_ref is not None:
                    holes[issue.row_ref] = True
            elif scope is Scope.TABLE:
                tables.add((issue.hole, issue.table, issue.log_set or issue.element))
            elif issue.row_ref is not None:
                records.add((issue.table, issue.row_ref))
        return Exclusions(holes=holes, tables=frozenset(tables), records=frozenset(records))


# --- Las comprobaciones de alcance S (bocas y desviaciones) ------------------------------------


@dataclass(frozen=True, eq=False)
class _Stations:
    """Las estaciones con boca, ordenadas por (sondeo, profundidad, fila): su fila en
    ``dset.surveys`` y sus campos; ``start``, los desplazamientos por boca (CSR)."""

    row: np.ndarray
    hole: np.ndarray
    md: np.ndarray
    azimuth: np.ndarray
    inclination: np.ndarray
    measured: np.ndarray
    start: np.ndarray


def _stations(dset: DrillholeSet) -> _Stations:
    surveys = dset.surveys
    count = len(dset.collars)
    linked = np.flatnonzero(surveys.hole >= 0)
    order = linked[np.lexsort((linked, surveys.depth[linked], surveys.hole[linked]))]
    hole = surveys.hole[order]
    start = np.zeros(count + 1, dtype=np.int64)
    np.cumsum(np.bincount(hole, minlength=count), out=start[1:])
    return _Stations(row=order, hole=hole, md=surveys.depth[order],
                     azimuth=surveys.azimuth[order], inclination=surveys.inclination[order],
                     measured=surveys.source[order] == _MEASURED, start=start)


@dataclass(frozen=True, eq=False)
class _Findings:
    """Lo que encuentran las comprobaciones de alcance S: por boca, la primera con su nombre,
    si está repetido (DH-E01), las coordenadas (DH-E02), la profundidad (DH-E03) y si no tiene
    estaciones (DH-E05); por estación (posiciones en ``stations``), las que repiten
    profundidad (DH-E06), están por encima de la boca o por debajo del fondo (DH-E07) o tienen
    el azimut o la inclinación fuera de rango (DH-E08); y la máscara de exclusión."""

    stations: _Stations
    first: np.ndarray
    repeated: np.ndarray
    bad_xyz: np.ndarray
    bad_depth: np.ndarray
    no_stations: np.ndarray
    same: np.ndarray
    above: np.ndarray
    below: np.ndarray
    bad_azimuth: np.ndarray
    bad_inclination: np.ndarray
    excluded: np.ndarray


def _names(collars: CollarColumns) -> tuple[np.ndarray, np.ndarray]:
    """La primera boca de cada nombre (sin mayúsculas ni espacios exteriores) y si el nombre
    está repetido, por boca."""
    count = len(collars)
    if not count:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.bool_)
    keys = np.array([name_key(name) for name in collars.name.tolist()], dtype=object)
    _unique, first, inverse, counts = np.unique(keys, return_index=True, return_inverse=True,
                                                return_counts=True)
    inverse = inverse.reshape(-1)
    return first[inverse].astype(np.int64), counts[inverse] > 1


def _find(dset: DrillholeSet, tolerance: float) -> _Findings:
    collars = dset.collars
    first, repeated = _names(collars)
    xyz = np.column_stack((collars.x, collars.y, collars.z))
    bad_xyz = ~np.isfinite(xyz)
    depth = collars.depth
    valid_depth = np.isfinite(depth) & (depth > 0.0)
    st = _stations(dset)
    md, azimuth, inclination = st.md, st.azimuth, st.inclination
    same = np.flatnonzero((st.hole[1:] == st.hole[:-1]) & (md[1:] == md[:-1])) + 1
    above = np.flatnonzero(~np.isfinite(md) | (md < 0.0))
    below = np.flatnonzero(valid_depth[st.hole] & (md > depth[st.hole] + tolerance))
    bad_azimuth = np.flatnonzero(~(np.isfinite(azimuth) & (azimuth >= 0.0)
                                   & (azimuth <= _FULL_TURN_DEG)))
    bad_inclination = np.flatnonzero(~(np.isfinite(inclination)
                                       & (np.abs(inclination) <= _RIGHT_ANGLE_DEG)))
    no_stations = np.diff(st.start) == 0
    excluded = repeated | bad_xyz.any(axis=1) | ~valid_depth | no_stations
    for index in (same, above, below, bad_azimuth, bad_inclination):
        excluded[st.hole[index]] = True
    return _Findings(stations=st, first=first, repeated=repeated, bad_xyz=bad_xyz,
                     bad_depth=~valid_depth, no_stations=no_stations, same=same, above=above,
                     below=below, bad_azimuth=bad_azimuth, bad_inclination=bad_inclination,
                     excluded=excluded)


def _check_set(dset: object) -> DrillholeSet:
    if not isinstance(dset, DrillholeSet):
        raise TypeError(f"se valida un DrillholeSet, no {dset!r}")
    return dset


def hole_exclusions(dset: DrillholeSet, *, depth_tolerance_m: float) -> np.ndarray:
    """La máscara (una por boca) de los sondeos de ``dset`` con un error de alcance S
    (DH-E01, E02, E03, E05, E06, E07 y E08): los que se quitan del cálculo de las trazas
    (RF-005-17; ``dh.desurvey``, plan §5.6.6). Es ``validate(...).excluded().holes`` sin
    crear las incidencias; ``depth_tolerance_m`` es ``dh.validation.depth_tolerance_m``."""
    tolerance = _threshold(depth_tolerance_m, "la tolerancia de profundidad")
    return _find(_check_set(dset), tolerance).excluded.copy()


def exclusion_codes(dset: DrillholeSet, *,
                    depth_tolerance_m: float) -> tuple[tuple[str, ...], ...]:
    """Los códigos de los errores de alcance S de cada boca de ``dset`` (en orden; vacía si el
    sondeo tiene traza), los que la vista marca en su boca (RF-005-17; spec 005, T30): los de
    :func:`validate` sin crear las incidencias (una boca de un nombre repetido, solo DH-E01).
    Sus bocas con algún código son la máscara de :func:`hole_exclusions`."""
    tolerance = _threshold(depth_tolerance_m, "la tolerancia de profundidad")
    found = _find(_check_set(dset), tolerance)
    count = len(dset.collars)
    st = found.stations
    per_hole: dict[str, np.ndarray] = {
        "DH-E02": found.bad_xyz.any(axis=1),
        "DH-E03": found.bad_depth,
        "DH-E05": found.no_stations,
    }
    for code, index in (("DH-E06", (found.same,)), ("DH-E07", (found.above, found.below)),
                        ("DH-E08", (found.bad_azimuth, found.bad_inclination))):
        mask = np.zeros(count, dtype=np.bool_)
        for positions in index:
            mask[st.hole[positions]] = True
        per_hole[code] = mask
    codes: list[tuple[str, ...]] = []
    for k in range(count):
        if found.repeated[k]:
            codes.append(("DH-E01",))
        else:
            codes.append(tuple(code for code in sorted(per_hole) if per_hole[code][k]))
    return tuple(codes)


# --- Lo que excluye el informe guardado (T30) --------------------------------------------------


def _stored_errors(records: Iterable[Mapping[str, Any]]) -> Iterator[tuple[Mapping[str, Any],
                                                                           Scope]]:
    """Las filas de ``dh_validation_issue`` de nivel «error» con alcance, y su alcance."""
    for record in records:
        if record["level"] != Level.ERROR or record["scope"] is None:
            continue
        yield record, Scope(record["scope"])


def _position(fid: object, what: str, count: int | None = None) -> int:
    """La posición (``fid`` − 1) de un ``fid`` guardado; ``ValueError`` si no vale."""
    if isinstance(fid, bool) or not isinstance(fid, int | np.integer) or int(fid) < 1:
        raise ValueError(f"{what} de una incidencia guardada no es un fid: {fid!r}")
    if count is not None and int(fid) > count:
        raise ValueError(f"{what} de una incidencia guardada ({fid}) pasa de las {count} bocas")
    return int(fid) - 1


def stored_exclusions(records: Iterable[Mapping[str, Any]], hole_count: int) -> Exclusions:
    """Lo que excluyen los errores del informe guardado en el proyecto (RF-005-17; spec 005,
    T30): ``records``, las filas de ``dh_validation_issue`` por el nombre de sus columnas (las
    de ``drillholes.jobs.issue_rows``: el sondeo y la fila por su ``fid``, posición + 1), de
    una base de ``hole_count`` bocas. Es :meth:`ValidationReport.excluded` del informe que las
    escribió; ``ValueError`` si una apunta fuera de las bocas."""
    holes = np.zeros(hole_count, dtype=np.bool_)
    tables: set[tuple[int, str, str | None]] = set()
    rows: set[tuple[str, int]] = set()
    for record, scope in _stored_errors(records):
        hole_id, row_fid, table = record["hole_id"], record["row_fid"], record["table_name"]
        if scope is Scope.HOLE:
            if hole_id is not None:
                holes[_position(hole_id, "el sondeo", hole_count)] = True
            if table == _COLLAR and row_fid is not None:
                holes[_position(row_fid, "la boca", hole_count)] = True
        elif scope is Scope.TABLE:
            tables.add((_position(hole_id, "el sondeo", hole_count), str(table),
                        record["log_set"] or record["element"]))
        elif row_fid is not None:
            rows.add((str(table), _position(row_fid, "la fila")))
    return Exclusions(holes=holes, tables=frozenset(tables), records=frozenset(rows))


def stored_codes(records: Iterable[Mapping[str, Any]],
                 scope: Scope | str) -> dict[int, tuple[str, ...]]:
    """Los códigos de los errores de alcance ``scope`` del informe guardado (``records``, como
    en :func:`stored_exclusions`) por la posición de su sondeo, en orden (spec 005, T30: los
    de alcance T, que la vista marca en la boca de un sondeo con traza)."""
    wanted = Scope(scope)
    found: dict[int, set[str]] = {}
    for record, found_scope in _stored_errors(records):
        if found_scope is wanted and record["hole_id"] is not None:
            found.setdefault(_position(record["hole_id"], "el sondeo"), set()).add(
                str(record["code"]))
    return {hole: tuple(sorted(codes)) for hole, codes in sorted(found.items())}


# --- La profundidad deducida (DH-W16) ----------------------------------------------------------


def deduce_depths(dset: DrillholeSet) -> DrillholeSet:
    """``dset`` con la profundidad total que falta (NaN) deducida, CALCULADO (DH-W16; spec §8):
    la más honda de sus estaciones y de los hasta de su litología, sus análisis y sus zonas, si
    es mayor que 0. Sin nada de donde deducirla, sigue ausente (DH-E03). Si no hay ninguna que
    deducir, el mismo ``dset``; nunca lo modifica. La aplican los lectores (T14, T15)."""
    collars = _check_set(dset).collars
    count = len(collars)
    missing = np.isnan(collars.depth)
    if not missing.any():
        return dset
    deepest = np.full(count, -np.inf)
    for depths, hole in ((dset.surveys.depth, dset.surveys.hole),
                         (dset.lithology.to_m, dset.lithology.hole),
                         (dset.assays.to_m, dset.assays.hole),
                         (dset.zones.to_m, dset.zones.hole)):
        linked = (hole >= 0) & np.isfinite(depths)
        np.maximum.at(deepest, hole[linked], depths[linked])
    found = missing & (deepest > 0.0)
    if not found.any():
        return dset
    depth = collars.depth.copy()
    depth[found] = deepest[found]
    kind = collars.depth_kind.copy()
    kind[found] = _CALCULADO
    rows = np.arange(count)
    return dataclasses.replace(dset, collars=collars.take(rows, depth=depth, depth_kind=kind))


# --- Las incidencias ---------------------------------------------------------------------------


def _number(value: float) -> float | str:
    """El valor de un campo numérico: el número, o «» si está vacío (NaN)."""
    return "" if math.isnan(value) else value


def _depth(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _issue(code: str, hole: int, name: str | None, table: str, *, message: str | None = None,
           args: Mapping[str, JsonScalar] | None = None, **fields: Any) -> Issue:
    return Issue(code, hole, name, table, message_id=MESSAGES[message or code],
                 message_args=args or {}, **fields)


def _collar_errors(dset: DrillholeSet, found: _Findings, checked: np.ndarray) -> list[Issue]:
    """DH-E01, DH-E02, DH-E03 y DH-E05."""
    collars = dset.collars
    names = collars.name.tolist()
    issues = []
    for k in np.flatnonzero(found.repeated & (found.first != np.arange(len(names)))).tolist():
        first = int(found.first[k])
        issues.append(_issue("DH-E01", first, names[first], _COLLAR, row_ref=k, field="name",
                             value=names[k],
                             args={"hole": names[first], "repeated": names[k]}))
    xyz = (collars.x, collars.y, collars.z)
    for axis, column in enumerate(xyz):
        for k in np.flatnonzero(found.bad_xyz[:, axis] & checked).tolist():
            issues.append(_issue("DH-E02", k, names[k], _COLLAR, row_ref=k,
                                 field=_AXES[axis], value=_number(float(column[k])),
                                 args={"axis": _AXES[axis].upper()}))
    for k in np.flatnonzero(found.bad_depth & checked).tolist():
        depth = float(collars.depth[k])
        missing = math.isnan(depth)
        issues.append(_issue("DH-E03", k, names[k], _COLLAR, row_ref=k, field="depth",
                             value=_number(depth),
                             message="DH-E03.missing" if missing else "DH-E03.invalid",
                             args=None if missing else {"depth": depth}))
    for k in np.flatnonzero(found.no_stations & checked).tolist():
        issues.append(_issue("DH-E05", k, names[k], _SURVEY))
    return issues


def _station_errors(dset: DrillholeSet, found: _Findings, checked: np.ndarray,
                    tolerance: float) -> list[Issue]:
    """DH-E06, DH-E07 y DH-E08, en las estaciones de las bocas ``checked``."""
    st = found.stations
    names = dset.collars.name.tolist()
    depth = dset.collars.depth
    issues = []

    def none(md: float, hole: int) -> dict[str, JsonScalar]:
        return {}

    def at_depth(md: float, hole: int) -> dict[str, JsonScalar]:
        return {"depth": md}

    def below(md: float, hole: int) -> dict[str, JsonScalar]:
        return {"depth": md, "bottom": float(depth[hole]), "tolerance": tolerance}

    for code, message, index, field, values, args in (
        ("DH-E06", "DH-E06", found.same, "depth", st.md, at_depth),
        ("DH-E07", "DH-E07.above", found.above, "depth", st.md, none),
        ("DH-E07", "DH-E07.below", found.below, "depth", st.md, below),
        ("DH-E08", "DH-E08.azimuth", found.bad_azimuth, "azimuth", st.azimuth, none),
        ("DH-E08", "DH-E08.inclination", found.bad_inclination, "inclination",
         st.inclination, none),
    ):
        for i in index[checked[st.hole[index]]].tolist():
            hole = int(st.hole[i])
            md = float(st.md[i])
            issues.append(_issue(code, hole, names[hole], _SURVEY, message=message,
                                 args=args(md, hole), row_ref=int(st.row[i]),
                                 depth_from=_depth(md), depth_to=_depth(md), field=field,
                                 value=_number(float(values[i]))))
    return issues


def _orphans(dset: DrillholeSet) -> list[Issue]:
    """DH-E04: los registros de un sondeo sin boca (alcance R). Un análisis sin sondeo solo si
    es de una muestra (un material de referencia o un blanco puede no tenerlo)."""
    issues = []
    for name, table in TABLE_NAMES.items():
        if name == "collars":
            continue
        columns = getattr(dset, name)
        orphan = columns.hole < 0
        if name == "assays":
            orphan &= ~np.equal(columns.hole_name, None) | (columns.qaqc_type == _SAMPLE)
        if name in ("surveys", "structures"):
            start = end = columns.depth
        else:
            start, end = columns.from_m, columns.to_m
        for row in np.flatnonzero(orphan).tolist():
            hole_name = columns.hole_name[row]
            fields: dict[str, Any] = {}
            if name == "lithology":
                fields["log_set"] = columns.log_set[row]
            elif name == "assays":
                fields["element"] = columns.element[row]
            issues.append(_issue(
                "DH-E04", -1, hole_name, table,
                message="DH-E04" if hole_name is not None else "DH-E04.unnamed",
                args={"hole": hole_name} if hole_name is not None else None, row_ref=row,
                depth_from=_depth(float(start[row])), depth_to=_depth(float(end[row])),
                field="hole", value="" if hole_name is None else hole_name, **fields))
    return issues


def _stored_geom(value: object, count: int) -> np.ndarray:
    if not isinstance(value, np.ndarray) or value.dtype != np.float64:
        raise TypeError(f"la posición de las bocas en la capa es un array float64 (absoluta), "
                        f"no {value!r}")
    if value.shape != (count, 3):
        raise ValueError(f"la posición de las bocas en la capa es ({count}, 3), no "
                         f"{value.shape}")
    return value


def _collar_warnings(dset: DrillholeSet, checked: np.ndarray, window: Window | None,
                     geom: np.ndarray | None) -> list[Issue]:
    """DH-W06, DH-W15 y DH-W16."""
    collars = dset.collars
    names = collars.name.tolist()
    issues = []
    if window is not None:
        x, y = collars.x, collars.y
        outside = (np.isfinite(x) & np.isfinite(y)
                   & ((x < window.xmin) | (x > window.xmax)
                      | (y < window.ymin) | (y > window.ymax)))
        for k in np.flatnonzero(outside & checked).tolist():
            issues.append(_issue("DH-W06", k, names[k], _COLLAR, row_ref=k))
    if geom is not None:
        xyz = np.column_stack((collars.x, collars.y, collars.z))
        same = (geom == xyz) | (np.isnan(geom) & np.isnan(xyz))
        for k in np.flatnonzero(~same.all(axis=1) & checked).tolist():
            issues.append(_issue("DH-W15", k, names[k], _COLLAR, row_ref=k, field="geom"))
    for k in np.flatnonzero((collars.depth_kind == _CALCULADO) & checked).tolist():
        issues.append(_issue("DH-W16", k, names[k], _COLLAR, row_ref=k, field="depth",
                             value="", args={"depth": float(collars.depth[k])}))
    return issues


def _check_surface(surface: object, dset: DrillholeSet) -> SurfaceSampler:
    """El MDT, si es un :class:`~.ports.SurfaceSampler` en el CRS y la referencia vertical de
    los sondeos (los del proyecto): otros, o algo que no lo es, son un error del programa."""
    if not isinstance(surface, SurfaceSampler):
        raise TypeError(f"el MDT de la validación es un drillholes.ports.SurfaceSampler, no "
                        f"{surface!r}")
    if not isinstance(surface.crs, CrsRef) or surface.crs.epsg != dset.crs.epsg:
        raise ValueError(f"el MDT está en {getattr(surface.crs, 'name', surface.crs)!r} y los "
                         f"sondeos en EPSG:{dset.crs.epsg}: se valida con un MDT del proyecto")
    if surface.vertical != dset.vertical:
        raise ValueError(f"las cotas del MDT están en {getattr(surface.vertical, 'name', '?')!r}"
                         f" y las de los sondeos en {dset.vertical.name!r}: se valida con un "
                         "MDT del proyecto")
    return surface


@dataclass(frozen=True, eq=False)
class _DemFindings:
    """Lo de DH-W05 de una validación: los avisos, las notas de lo que no se evaluó, la
    diferencia de cada boca (``None`` sin MDT) y las de las bocas dentro de la tolerancia."""

    issues: list[Issue]
    notes: list[Note]
    dz: np.ndarray | None
    differences: list[DemDifference]


def _dem_issues(dset: DrillholeSet, checked: np.ndarray, surface: SurfaceSampler | None,
                tolerance: float) -> _DemFindings:
    """DH-W05 (RF-005-18; véase el módulo): las incidencias, las notas de lo que no se evaluó,
    la diferencia de cada boca con el MDT (``None`` sin MDT) y (T56) las de las bocas dentro
    de la tolerancia."""
    if surface is None:
        return _DemFindings([], [no_dem_note()], None, [])
    collars = dset.collars
    count = len(collars)
    dz = np.full(count, np.nan)
    wanted = np.flatnonzero(checked & np.isfinite(collars.x) & np.isfinite(collars.y)
                            & np.isfinite(collars.z))
    issues: list[Issue] = []
    notes: list[Note] = []
    differences: list[DemDifference] = []
    if wanted.size:
        xy = np.column_stack((collars.x[wanted], collars.y[wanted]))
        found = surface.sample(xy)
        if not isinstance(found, np.ndarray) or found.dtype != np.float64:
            raise TypeError(f"el MDT da sus cotas en un array float64, no {found!r}")
        if found.shape != (wanted.size,):
            raise ValueError(f"el MDT da una cota por punto ({wanted.size},), no {found.shape}")
        dem = np.where(np.isfinite(found), found, np.nan)
        dz[wanted] = collars.z[wanted] - dem
        names = collars.name.tolist()
        for i, k in enumerate(wanted.tolist()):
            if math.isnan(dz[k]):
                notes.append(Note("DH-W05", k, names[k],
                                  message_id=MESSAGES["DH-W05.outside"], table=_COLLAR,
                                  row_ref=k, field="z"))
                continue
            args = {"z": float(collars.z[k]), "dem": round(float(dem[i]), _DEM_DECIMALS),
                    "dz": round(float(dz[k]), _DEM_DECIMALS), "tolerance": tolerance}
            if abs(dz[k]) > tolerance:
                issues.append(_issue("DH-W05", k, names[k], _COLLAR, row_ref=k, field="z",
                                     args=args))
            else:
                differences.append(DemDifference(k, names[k], float(dz[k]), message_args=args))
    dz.flags.writeable = False
    return _DemFindings(issues, notes, dz, differences)


def _changed_field(az1: float, az2: float, inc1: float, inc2: float) -> str:
    """El ángulo que más cambia entre dos estaciones: la inclinación o el azimut por su
    componente sobre la esfera, ΔA·cos θ (en la vertical, nada)."""
    turn = abs((az2 - az1 + _HALF_TURN_DEG) % _FULL_TURN_DEG - _HALF_TURN_DEG)
    across = turn * math.cos(math.radians((inc1 + inc2) / 2.0))
    return "azimuth" if across > abs(inc2 - inc1) else "inclination"


def _survey_warnings(dset: DrillholeSet, found: _Findings,
                     params: ValidationParams) -> list[Issue]:
    """DH-W02, DH-W03, DH-W04 y DH-W14, en los sondeos que tendrán traza."""
    st = found.stations
    names = dset.collars.name.tolist()
    depth = dset.collars.depth
    traceable = ~found.excluded
    issues = []
    holes = np.flatnonzero(traceable).tolist()
    for hole in holes:
        first, last = int(st.start[hole]), int(st.start[hole + 1]) - 1
        md_first, md_last, bottom = float(st.md[first]), float(st.md[last]), float(depth[hole])
        if md_first > 0.0 and st.measured[first]:
            issues.append(_issue("DH-W02", hole, names[hole], _SURVEY,
                                 args={"depth": md_first}, row_ref=int(st.row[first]),
                                 depth_from=0.0, depth_to=md_first, field="depth",
                                 value=md_first))
        if md_last < bottom and st.measured[last]:
            issues.append(_issue("DH-W03", hole, names[hole], _SURVEY,
                                 args={"depth": md_last, "bottom": bottom},
                                 row_ref=int(st.row[last]), depth_from=md_last,
                                 depth_to=bottom, field="depth", value=md_last))

    pairs = np.flatnonzero((st.hole[1:] == st.hole[:-1]) & traceable[st.hole[:-1]])
    if pairs.size:
        tangent = direction(st.azimuth[pairs], st.inclination[pairs])
        following = direction(st.azimuth[pairs + 1], st.inclination[pairs + 1])
        length = st.md[pairs + 1] - st.md[pairs]
        rate = np.degrees(dogleg(tangent, following)) * _DOGLEG_LENGTH_M / length
        for i, value in zip(pairs.tolist(), rate.tolist(), strict=True):
            if not value > params.dogleg_max_deg_30m:
                continue
            hole = int(st.hole[i])
            md1, md2 = float(st.md[i]), float(st.md[i + 1])
            field = _changed_field(float(st.azimuth[i]), float(st.azimuth[i + 1]),
                                   float(st.inclination[i]), float(st.inclination[i + 1]))
            issues.append(_issue(
                "DH-W04", hole, names[hole], _SURVEY,
                args={"rate": round(value, _RATE_DECIMALS), "depth_from": md1,
                      "depth_to": md2, "limit": params.dogleg_max_deg_30m},
                row_ref=int(st.row[i + 1]), depth_from=md1, depth_to=md2, field=field))

    counts = np.diff(st.start)
    has = np.flatnonzero(counts > 0)
    if has.size:
        lowest = np.minimum.reduceat(st.inclination, st.start[has])
        for hole in has[(lowest > 0.0) & traceable[has]].tolist():
            issues.append(_issue("DH-W14", hole, names[hole], _SURVEY, field="inclination"))
    return issues


# --- Las comprobaciones de los tramos, los valores y los catálogos (T09) -----------------------


def _key_codes(texts: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """El código (int64) de cada texto de ``texts`` (sin ``None``): el mismo para los que
    tienen la misma :func:`~.model.name_key`; y las claves de los códigos, en el orden en que
    aparecen. Con un diccionario de los textos distintos, sin ordenarlos: O(n)."""
    raw: dict[str, int] = {}
    found = np.fromiter((raw.setdefault(text, len(raw)) for text in texts.tolist()),
                        dtype=np.int64, count=len(texts))
    keys: dict[str, int] = {}
    key_of_raw = np.array([keys.setdefault(name_key(text), len(keys)) for text in raw],
                          dtype=np.int64)
    return key_of_raw[found], list(keys)


def _known(texts: np.ndarray, catalog: Mapping[str, Any]) -> np.ndarray:
    """Si cada texto de ``texts`` (sin ``None``) está en ``catalog`` (por su ``name_key``)."""
    codes, keys = _key_codes(texts)
    return np.array([key in catalog for key in keys], dtype=np.bool_)[codes]


def _known_lithology(log_sets: np.ndarray, codes: np.ndarray,
                     catalog: set[tuple[str, str]]) -> np.ndarray:
    """Si cada código de litología está en el catálogo de su esquema de logueo."""
    set_of, set_keys = _key_codes(log_sets)
    code_of, code_keys = _key_codes(codes)
    width = max(len(code_keys), 1)
    pairs, inverse = np.unique(set_of * width + code_of, return_inverse=True)
    member = [(set_keys[pair // width], code_keys[pair % width]) in catalog
              for pair in pairs.tolist()]
    return np.array(member, dtype=np.bool_)[inverse.reshape(-1)]


def _linked(hole: np.ndarray, checked: np.ndarray) -> np.ndarray:
    """La máscara de las filas de una tabla hija con boca, de una boca sin DH-E01 (las demás
    son DH-E04 o DH-E01: no se sabe de qué boca son y no se comprueban aquí)."""
    linked = hole >= 0
    found = linked.copy()
    found[linked] = checked[hole[linked]]
    return found


def _same(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Igualdad de números en la que un vacío (NaN) es igual a otro vacío."""
    return (a == b) | (np.isnan(a) & np.isnan(b))


def _running_max(values: np.ndarray, first: np.ndarray) -> np.ndarray:
    """El máximo acumulado de ``values`` (finitos) dentro de cada grupo de filas seguidas que
    empieza donde ``first`` es verdadero. Exacto: sobre el rango entero de cada valor, sin
    sumar desplazamientos a los números."""
    unique, rank = np.unique(values, return_inverse=True)
    group = np.cumsum(first, dtype=np.int64) - 1
    key = group * unique.size + rank.reshape(-1)
    return unique[np.maximum.accumulate(key) - group * unique.size]


def _interval_fields(name: str, columns: Any, row: int) -> dict[str, Any]:
    """El esquema de logueo o el elemento de un tramo (lo que excluye su alcance T)."""
    if name == "lithology":
        return {"log_set": columns.log_set[row]}
    if name == "assays":
        return {"element": columns.element[row]}
    return {}


def _range_errors(dset: DrillholeSet, name: str, rows: np.ndarray, names: list[str],
                  tolerance: float) -> tuple[list[Issue], np.ndarray]:
    """DH-E09 de las filas ``rows`` de la tabla de tramos ``name``: desde ausente o < 0
    (campo ``from_m``); hasta ausente, ≤ desde o por debajo del fondo más la tolerancia (solo
    con una profundidad total válida; campo ``to_m``). Da las incidencias y la máscara (una
    por fila de ``rows``) de los tramos con error."""
    columns = getattr(dset, name)
    table = TABLE_NAMES[name]
    start, end = columns.from_m[rows], columns.to_m[rows]
    hole = columns.hole[rows]
    bottom = dset.collars.depth[hole]
    bad_from = ~(np.isfinite(start) & (start >= 0.0))
    no_end = ~np.isfinite(end)
    reversed_ = ~no_end & (end <= start)
    below = (~no_end & ~reversed_ & np.isfinite(bottom) & (bottom > 0.0)
             & (end > bottom + tolerance))
    bad_to = no_end | reversed_ | below
    issues = []
    for i in np.flatnonzero(bad_from | bad_to).tolist():
        row, k = int(rows[i]), int(hole[i])
        s, e = float(start[i]), float(end[i])
        common = {"row_ref": row, "depth_from": _depth(s), "depth_to": _depth(e),
                  **_interval_fields(name, columns, row)}
        if bad_from[i]:
            issues.append(_issue("DH-E09", k, names[k], table, message="DH-E09.from",
                                 field="from_m", value=_number(s), **common))
        if not bad_to[i]:
            continue
        if no_end[i]:
            message, args = "DH-E09.no_to", None
        elif reversed_[i]:
            message, args = "DH-E09.reversed", {"depth_from": s, "depth_to": e}
        else:
            message = "DH-E09.below"
            args = {"depth_to": e, "bottom": float(bottom[i]), "tolerance": tolerance}
        issues.append(_issue("DH-E09", k, names[k], table, message=message, args=args,
                             field="to_m", value=_number(e), **common))
    return issues, bad_from | bad_to


def _sequence_issues(dset: DrillholeSet, name: str, rows: np.ndarray, group: np.ndarray,
                     names: list[str], params: ValidationParams) -> list[Issue]:
    """DH-E12 (en los análisis), DH-E10, DH-W01 y DH-W09 de los tramos ``rows`` (sin DH-E09)
    por grupo (``group``, int64: el sondeo y el esquema de logueo o el elemento), ordenados
    por grupo, desde, hasta y fila; solape y hueco, contra el hasta más hondo anterior."""
    columns = getattr(dset, name)
    table = TABLE_NAMES[name]
    order = np.lexsort((rows, columns.to_m[rows], columns.from_m[rows], group))
    rows, group = rows[order], group[order]
    start, end = columns.from_m[rows], columns.to_m[rows]
    assays = name == "assays"
    issues = []
    if assays and rows.size:
        repeated = np.zeros(rows.size, dtype=np.bool_)
        repeated[1:] = ((group[1:] == group[:-1]) & (start[1:] == start[:-1])
                        & (end[1:] == end[:-1]))
        for i in np.flatnonzero(repeated).tolist():
            row = int(rows[i])
            k, element = int(columns.hole[row]), columns.element[row]
            issues.append(_issue(
                "DH-E12", k, names[k], table, row_ref=row, element=element,
                depth_from=float(start[i]), depth_to=float(end[i]), field="value",
                value=_number(float(columns.value[row])),
                args={"element": element, "depth_from": float(start[i]),
                      "depth_to": float(end[i])}))
        keep = ~repeated
        rows, group, start, end = rows[keep], group[keep], start[keep], end[keep]
    if not rows.size:
        return issues
    first = np.ones(rows.size, dtype=np.bool_)
    first[1:] = group[1:] != group[:-1]
    previous = np.full(rows.size, np.nan)
    previous[1:] = _running_max(end, first)[:-1]
    previous[first] = np.nan
    overlap = start < previous
    gap = start > previous + params.gap_tolerance_m
    short = end < start + params.min_interval_m
    for i in np.flatnonzero(overlap | gap | short).tolist():
        row = int(rows[i])
        k = int(columns.hole[row])
        s, e, above = float(start[i]), float(end[i]), float(previous[i])
        fields = _interval_fields(name, columns, row)
        if overlap[i]:
            to = min(above, e)
            message, args = (("DH-E10.assay", {"element": fields["element"]}) if assays
                             else ("DH-E10", {"log_set": fields["log_set"]}))
            issues.append(_issue("DH-E10", k, names[k], table, message=message,
                                 args={**args, "depth_from": s, "depth_to": to}, row_ref=row,
                                 depth_from=s, depth_to=to, field="from_m", value=s,
                                 **fields))
        elif gap[i]:
            issues.append(_issue("DH-W01", k, names[k], table,
                                 args={"depth_from": above, "depth_to": s,
                                       "tolerance": params.gap_tolerance_m},
                                 row_ref=row, depth_from=above, depth_to=s, field="from_m",
                                 value=s, **fields))
        if short[i]:
            issues.append(_issue("DH-W09", k, names[k], table,
                                 args={"depth_from": s, "depth_to": e,
                                       "limit": params.min_interval_m},
                                 row_ref=row, depth_from=s, depth_to=e, **fields))
    return issues


def _lithology_issues(dset: DrillholeSet, checked: np.ndarray, names: list[str],
                      params: ValidationParams) -> list[Issue]:
    """DH-E09, DH-E10, DH-E11, DH-W01 y DH-W09 de la litología."""
    lithology = dset.lithology
    rows = np.flatnonzero(_linked(lithology.hole, checked))
    issues, bad = _range_errors(dset, "lithology", rows, names, params.depth_tolerance_m)
    catalog = {(name_key(code.log_set), name_key(code.code))
               for code in dset.catalogs.lithology}
    known = _known_lithology(lithology.log_set[rows], lithology.code[rows], catalog)
    for row in rows[~known].tolist():
        k, code, log_set = int(lithology.hole[row]), lithology.code[row], lithology.log_set[row]
        issues.append(_issue("DH-E11", k, names[k], _LITHOLOGY, message="DH-E11.lithology",
                             args={"code": code, "log_set": log_set}, row_ref=row,
                             log_set=log_set, depth_from=_depth(float(lithology.from_m[row])),
                             depth_to=_depth(float(lithology.to_m[row])), field="lithology",
                             value=code))
    rows = rows[~bad]
    set_of, set_keys = _key_codes(lithology.log_set[rows])
    group = lithology.hole[rows] * max(len(set_keys), 1) + set_of
    return issues + _sequence_issues(dset, "lithology", rows, group, names, params)


def _assay_issues(dset: DrillholeSet, checked: np.ndarray, names: list[str],
                  params: ValidationParams) -> list[Issue]:
    """DH-E09 a DH-E12, DH-W01, DH-W07, DH-W08, DH-W09, DH-W11 y DH-W12 de los análisis."""
    assays = dset.assays
    linked = _linked(assays.hole, checked)
    rows = np.flatnonzero(linked)
    issues = []
    units = {name_key(element.code): element.unit for element in dset.catalogs.elements}
    element_of, keys = _key_codes(assays.element[rows])
    known = np.array([key in units for key in keys], dtype=np.bool_)[element_of]
    unit_of = np.array([units.get(key) for key in keys], dtype=object)[element_of]
    other_unit = known & (assays.unit[rows] != unit_of)
    value = assays.value[rows]
    not_positive = (assays.detection_flag[rows] == _FLAG_OK) & (value <= 0.0)
    for code, mask in (("DH-E11", ~known), ("DH-W07", other_unit), ("DH-W08", not_positive)):
        for i in np.flatnonzero(mask).tolist():
            row = int(rows[i])
            k, element = int(assays.hole[row]), assays.element[row]
            common = {"row_ref": row, "element": element,
                      "depth_from": _depth(float(assays.from_m[row])),
                      "depth_to": _depth(float(assays.to_m[row]))}
            if code == "DH-E11":
                issues.append(_issue(code, k, names[k], _ASSAY, message="DH-E11.element",
                                     args={"code": element}, field="element", value=element,
                                     **common))
            elif code == "DH-W07":
                unit = assays.unit[row]
                issues.append(_issue(code, k, names[k], _ASSAY,
                                     args={"unit": unit, "element": element,
                                           "catalog_unit": unit_of[i]},
                                     field="unit", value=unit, **common))
            else:
                number = float(value[i])
                issues.append(_issue(code, k, names[k], _ASSAY, args={"value": number},
                                     field="value", value=number, **common))

    has_interval = ((assays.qaqc_type[rows] == _SAMPLE) | np.isfinite(assays.from_m[rows])
                    | np.isfinite(assays.to_m[rows]))
    intervals = rows[has_interval]
    found, bad = _range_errors(dset, "assays", intervals, names, params.depth_tolerance_m)
    issues += found
    primary = intervals[~bad & assays.is_primary[intervals]]
    element_of, keys = _key_codes(assays.element[primary])
    group = assays.hole[primary] * max(len(keys), 1) + element_of
    issues += _sequence_issues(dset, "assays", primary, group, names, params)
    issues += _repeated_samples(dset, linked, names)

    collars = dset.collars
    has_assays = np.zeros(len(collars), dtype=np.bool_)
    has_assays[assays.hole[rows]] = True
    for k in np.flatnonzero(collars.planned & checked & has_assays).tolist():
        issues.append(_issue("DH-W12", k, names[k], _COLLAR, row_ref=k, field="planned",
                             value=True))
    return issues


def _repeated_samples(dset: DrillholeSet, linked: np.ndarray, names: list[str]) -> list[Issue]:
    """DH-W11: el mismo código de muestra en otro tramo (sondeo, desde y hasta); una
    incidencia por tramo repetido, tras el primero en orden de sondeo, desde, hasta y fila."""
    assays = dset.assays
    rows = np.flatnonzero(linked & ~np.equal(assays.sample_id, None))
    if not rows.size:
        return []
    key, _keys = _key_codes(assays.sample_id[rows])
    hole, start, end = assays.hole[rows], assays.from_m[rows], assays.to_m[rows]
    order = np.lexsort((rows, end, start, hole, key))
    rows, key, hole, start, end = rows[order], key[order], hole[order], start[order], end[order]
    same_key = key[1:] == key[:-1]
    same_interval = (same_key & (hole[1:] == hole[:-1]) & _same(start[1:], start[:-1])
                     & _same(end[1:], end[:-1]))
    first = np.ones(rows.size, dtype=np.bool_)
    first[1:] = ~same_key
    repeated = np.zeros(rows.size, dtype=np.bool_)
    repeated[1:] = same_key & ~same_interval
    origin = np.maximum.accumulate(np.where(first, np.arange(rows.size), 0))
    issues = []
    for i in np.flatnonzero(repeated).tolist():
        row, k, o = int(rows[i]), int(hole[i]), int(origin[i])
        sample = assays.sample_id[row]
        issues.append(_issue(
            "DH-W11", k, names[k], _ASSAY, row_ref=row, depth_from=_depth(float(start[i])),
            depth_to=_depth(float(end[i])), field="sample_id", value=sample,
            args={"sample": sample, "hole": names[int(hole[o])],
                  "depth_from": _depth(float(start[o])), "depth_to": _depth(float(end[o]))}))
    return issues


def _catalog_issues(dset: DrillholeSet, checked: np.ndarray, names: list[str],
                    params: ValidationParams) -> list[Issue]:
    """DH-E11 del sector y el grupo de las bocas y de la zona de las intersecciones y los
    cortes; DH-E09 de las intersecciones; DH-W10 de las litologías sin densidad."""
    collars, catalogs = dset.collars, dset.catalogs
    issues = []
    for field, kind in _COLLAR_CODES:
        catalog = {name_key(entry.code): entry for entry in getattr(catalogs, kind)}
        column = getattr(collars, field)
        rows = np.flatnonzero(checked & ~np.equal(column, None))
        for k in rows[~_known(column[rows], catalog)].tolist():
            issues.append(_issue("DH-E11", k, names[k], _COLLAR, message=f"DH-E11.{field}",
                                 args={"code": column[k]}, row_ref=k, field=field,
                                 value=column[k]))
    zones = {name_key(entry.code): entry for entry in catalogs.zones}
    for name in ("zones", "structures"):
        columns = getattr(dset, name)
        table = TABLE_NAMES[name]
        linked = _linked(columns.hole, checked)
        rows = np.flatnonzero(linked & ~np.equal(columns.zone, None))
        for row in rows[~_known(columns.zone[rows], zones)].tolist():
            k, zone = int(columns.hole[row]), columns.zone[row]
            start, end = ((columns.from_m[row], columns.to_m[row]) if name == "zones"
                          else (columns.depth[row], columns.depth[row]))
            issues.append(_issue("DH-E11", k, names[k], table, message="DH-E11.zone",
                                 args={"code": zone}, row_ref=row,
                                 depth_from=_depth(float(start)), depth_to=_depth(float(end)),
                                 field="zone", value=zone))
        if name == "zones":
            issues += _range_errors(dset, name, np.flatnonzero(linked), names,
                                    params.depth_tolerance_m)[0]
    for row, code in enumerate(catalogs.lithology):
        if code.density is None:
            issues.append(_issue("DH-W10", -1, None, _LITHOLOGY_CODE, args={"code": code.code},
                                 row_ref=row, log_set=code.log_set, catalog_code=code.code,
                                 field="density", value=""))
    return issues


def validate(dset: DrillholeSet, params: ValidationParams, *,
             surface: SurfaceSampler | None = None,
             work_window: Window | None = None,
             stored_geom_xyz: np.ndarray | None = None) -> ValidationReport:
    """Las incidencias de ``dset`` con los umbrales ``params`` (RF-005-16; véase el módulo):
    ``surface``, el MDT del proyecto (DH-W05 y la diferencia de cada boca, RF-005-18; sin él,
    no se evalúa y el informe lo dice); ``work_window``, la ventana de trabajo del proyecto
    (DH-W06; sin ella, no se evalúa); ``stored_geom_xyz``, la posición absoluta (bocas, 3) de
    cada boca en la capa (DH-W15; sin ella, no se evalúa). ``dset`` no cambia."""
    dset = _check_set(dset)
    if not isinstance(params, ValidationParams):
        raise TypeError(f"los umbrales de la validación son ValidationParams, no {params!r}")
    if work_window is not None and not isinstance(work_window, Window):
        raise TypeError(f"la ventana de trabajo es un core.georef.Window, no {work_window!r}")
    if surface is not None:
        surface = _check_surface(surface, dset)
    count = len(dset.collars)
    geom = None if stored_geom_xyz is None else _stored_geom(stored_geom_xyz, count)
    found = _find(dset, params.depth_tolerance_m)
    checked = ~found.repeated
    names = dset.collars.name.tolist()
    dem = _dem_issues(dset, checked, surface, params.collar_dem_tolerance_m)
    issues = (_collar_errors(dset, found, checked)
              + _station_errors(dset, found, checked, params.depth_tolerance_m)
              + _orphans(dset)
              + _collar_warnings(dset, checked, work_window, geom)
              + dem.issues
              + _survey_warnings(dset, found, params)
              + _lithology_issues(dset, checked, names, params)
              + _assay_issues(dset, checked, names, params)
              + _catalog_issues(dset, checked, names, params))

    def order(issue: Issue) -> tuple[int, str, int, int]:
        hole = issue.hole if issue.hole >= 0 else count
        row = -1 if issue.row_ref is None else issue.row_ref
        return (hole, issue.code, _TABLE_ORDER[issue.table], row)

    issues.sort(key=order)
    return ValidationReport(issues=tuple(issues), hole_count=count, notes=tuple(dem.notes),
                            collar_dem_dz=dem.dz, differences=tuple(dem.differences))
