# SPDX-License-Identifier: GPL-3.0-or-later
"""Validación de los sondeos (spec 005, T08; RF-005-16, RF-005-17; spec §4.4.1 y §8; plan 005
§5.3.2, §5.4 y §5.6.6).

:func:`validate` aplica a un ``DrillholeSet`` las comprobaciones de la tabla 4.4.1 de la spec
y da un :class:`ValidationReport`: una :class:`Issue` por incidencia, con su código, su nivel
y su alcance (:data:`CODES`), el sondeo (posición entre las bocas y nombre), la tabla del
modelo de datos (``dh_collar``, ``dh_survey``…), la fila de esa tabla, el tramo o la
profundidad, el campo, el valor y un mensaje en español que dice qué corregir
(:meth:`Issue.message`; ``msgid`` en inglés en :data:`MESSAGES` y su español en
``core/i18n/messages.toml``). :meth:`ValidationReport.excluded` da lo que se excluye
(RF-005-17, :class:`Exclusions`): los sondeos enteros (alcance S), las tablas, esquemas o
elementos de un sondeo (T) y los registros (R); nada más.

Esta tarea hace **la parte de las bocas y las desviaciones**: DH-E01 a DH-E08, DH-W02, DH-W03,
DH-W04, DH-W06, DH-W14, DH-W15 y DH-W16. Las de los tramos y los catálogos (DH-E09 a E12,
DH-W01 y DH-W07 a W12) llegan con la T09 y la diferencia con el MDT (DH-W05) con la T10.

**La parte de alcance S, para la desviación** (plan §5.6.6): :func:`hole_exclusions` da la
máscara de los sondeos con un error de alcance S (los que ``desurvey`` no puede calcular), sin
crear incidencias; ``dh.desurvey`` la calcula ella misma con
``desurvey(dset, holes=~hole_exclusions(dset, depth_tolerance_m=…))`` y no consume el informe.
Es la misma máscara que ``validate(...).excluded().holes``.

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

**Valor** de una incidencia: el número, el texto o el sí/no guardado en el campo; «» si el
campo está vacío (un número ausente o, en DH-W16, la profundidad que la fuente no traía);
``None`` si la comprobación es de un cálculo (DH-E05, W04, W06, W14, W15).

El orden es determinista: por boca (los registros sin boca, al final), código, tabla y fila.
Nada modifica la entrada. Python puro y numpy (ADR-0004); vectorial salvo al crear las
incidencias.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from dataclasses import KW_ONLY, dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.georef import Window
from ..core.i18n import LANGUAGES, translate
from ..core.params import ParamKind
from .desurvey import direction, dogleg
from .model import (
    AssayColumns,
    CollarColumns,
    DrillholeSet,
    QaqcType,
    StationSource,
    SurveyColumns,
    name_key,
)

__all__ = [
    "CATALOG_TABLES",
    "CODES",
    "MESSAGES",
    "TABLE_NAMES",
    "Exclusions",
    "Issue",
    "Level",
    "Scope",
    "ValidationParams",
    "ValidationReport",
    "deduce_depths",
    "hole_exclusions",
    "validate",
]

type JsonScalar = str | int | float | bool | None


class Level(StrEnum):
    """El nivel de una comprobación (``dh_validation_issue.level``)."""

    ERROR = "error"
    WARNING = "warning"


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
_TABLE_ORDER = {name: k for k, name in enumerate((*TABLE_NAMES.values(), *CATALOG_TABLES))}
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
    "DH-W02": "The first survey station is at {depth} m, below the collar: its orientation "
              "is extended up to the collar. If there is a measurement at the collar, add "
              "it.",
    "DH-W03": "The last survey station is at {depth} m, above the bottom ({bottom} m): its "
              "orientation is extended down to the bottom. If there are deeper "
              "measurements, add them.",
    "DH-W04": "The direction changes {rate}°/30 m between the stations at {depth_from} and "
              "{depth_to} m (more than {limit}°/30 m): check their azimuth and inclination.",
    "DH-W06": "The collar is outside the project work window: check its coordinates and the "
              "declared CRS, or enlarge the work window.",
    "DH-W14": "All survey stations of the hole have a positive inclination: check the "
              "declared inclination convention (here it is negative downwards).",
    "DH-W15": "The collar in the layer is not at its X, Y, Z (it was moved outside "
              "Geoblender): the stored X, Y, Z prevails; recompute the base to put it back.",
    "DH-W16": "The source did not give the total depth: {depth} m has been deduced from the "
              "deepest station or interval (CALCULADO). If you know it, enter it in the "
              "collar table.",
})
"""El ``msgid`` (inglés) del mensaje de cada comprobación (o de cada variante,
``código.variante``); su español está en ``core/i18n/messages.toml``."""

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
        if language not in LANGUAGES:
            raise ValueError(f"el idioma «{language}» no es de Geoblender: "
                             f"{', '.join(LANGUAGES)}")
        shown = {name: _shown(value, language) for name, value in self.message_args}
        return translate(language, self.message_id, **shown)


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
    ``hole_count`` bocas."""

    issues: tuple[Issue, ...]
    hole_count: int

    def __post_init__(self) -> None:
        found = tuple(self.issues)
        if not all(isinstance(issue, Issue) for issue in found):
            raise TypeError("las incidencias de un informe son Issue")
        if isinstance(self.hole_count, bool) or not isinstance(self.hole_count, int):
            raise TypeError(f"el número de bocas es un entero, no {self.hole_count!r}")
        if any(issue.hole >= self.hole_count for issue in found):
            raise ValueError(f"una incidencia apunta a una boca fuera de [0, {self.hole_count})")
        object.__setattr__(self, "issues", found)

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


def validate(dset: DrillholeSet, params: ValidationParams, *,
             work_window: Window | None = None,
             stored_geom_xyz: np.ndarray | None = None) -> ValidationReport:
    """Las incidencias de ``dset`` con los umbrales ``params`` (RF-005-16; véase el módulo):
    ``work_window``, la ventana de trabajo del proyecto (DH-W06; sin ella, no se evalúa);
    ``stored_geom_xyz``, la posición absoluta (bocas, 3) de cada boca en la capa (DH-W15; sin
    ella, no se evalúa). ``dset`` no cambia."""
    dset = _check_set(dset)
    if not isinstance(params, ValidationParams):
        raise TypeError(f"los umbrales de la validación son ValidationParams, no {params!r}")
    if work_window is not None and not isinstance(work_window, Window):
        raise TypeError(f"la ventana de trabajo es un core.georef.Window, no {work_window!r}")
    count = len(dset.collars)
    geom = None if stored_geom_xyz is None else _stored_geom(stored_geom_xyz, count)
    found = _find(dset, params.depth_tolerance_m)
    checked = ~found.repeated
    issues = (_collar_errors(dset, found, checked)
              + _station_errors(dset, found, checked, params.depth_tolerance_m)
              + _orphans(dset)
              + _collar_warnings(dset, checked, work_window, geom)
              + _survey_warnings(dset, found, params))

    def order(issue: Issue) -> tuple[int, str, int, int]:
        hole = issue.hole if issue.hole >= 0 else count
        row = -1 if issue.row_ref is None else issue.row_ref
        return (hole, issue.code, _TABLE_ORDER[issue.table], row)

    issues.sort(key=order)
    return ValidationReport(issues=tuple(issues), hole_count=count)
