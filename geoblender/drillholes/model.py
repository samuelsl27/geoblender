# SPDX-License-Identifier: GPL-3.0-or-later
"""Modelo de los sondeos (spec 005, T03; RF-005-02, RF-005-07; plan 005 §5.2, §5.2.2 y
§5.3.2; D5 y D15 del plan).

Registro a registro (importación, edición) y en columnas (cálculo vectorizado):

- **Registros** (dataclasses inmutables): :class:`Collar` (boca), :class:`SurveyStation`
  (estación de desviación), :class:`LithologyInterval`, :class:`AssayValue` (un valor de un
  elemento en un tramo, formato largo), :class:`ZoneInterval` y :class:`StructureMeasure`
  (intersecciones y cortes de RecMin), y los de los catálogos (:class:`LithologyCode`,
  :class:`Element` y :class:`CatalogEntry` de sectores, grupos y zonas, juntos en
  :class:`Catalogs`). Sus campos son los de las tablas ``dh_*`` (plan §5.2) sin sus claves:
  un registro hijo nombra su sondeo (``hole``) y sus códigos de catálogo por su texto.
- **Columnas**: :class:`DrillholeSet`, con una clase de columnas numpy por tabla
  (:class:`CollarColumns`, :class:`SurveyColumns`, :class:`IntervalColumns`,
  :class:`AssayColumns`, :class:`ZoneColumns` y :class:`StructureColumns`), los catálogos,
  su CRS (``CrsRef``) y su referencia vertical (``VerticalRef``), las del catálogo de la 002.
  Números en float64 (ausente = NaN), sí/no en ``bool``, enteros en int64, enumeraciones en
  int8 (la posición del valor en ``code_values(campo)``; ausente = −1) y textos, fechas,
  enteros opcionales y ``extra`` como objetos (ausente = ``None``). Cada fila de una tabla
  hija lleva el índice de su boca (``hole``, int64; −1 si no tiene, DH-E04) y el nombre del
  sondeo tal como venía (``hole_name``).
- **La fuente**: :class:`SourceDeclaration` (lo que declara quien importa, RF-005-07) con sus
  :class:`ValueRules`, e :class:`ImportDto` (una importación pendiente). Viven aquí y no en
  ``interop``: ``drillholes`` es de nivel 3 y no puede importar ``interop`` (nivel 10; D15).

**RF-005-02, el valor decimal de la fuente.** Registros → columnas → registros, y columnas →
registros → columnas, conservan los bits de cada float64. Un número en precisión simple
(``numpy.float32``) no entra, ni en un registro ni en una columna: el Single de RecMin llega
por su decimal más corto (``drillholes.values``), y una coordenada nunca va en float32
(ADR-0005).

**RF-005-07, nada se supone.** La declaración no tiene valor por defecto para el CRS, la
referencia vertical, la del azimut, la declinación, el convenio de la inclinación, las
unidades ni las reglas de los valores: lo no declarado es ``None`` y lo nombra la importación
(``interop.base.missing_declarations``). Un ``DrillholeSet`` exige su CRS y su referencia
vertical.

**Lo que nunca es un dato válido** (claves, enumeraciones y nombres; plan §5.2, criterio de
restricciones) se rechaza al crear un registro o unas columnas con ``TypeError`` o
``ValueError``: es un error del programa, porque el lector rechaza antes la fila con su
motivo. Los rangos (desde ≥ hasta, azimut fuera de [0, 360), profundidad negativa…) sí
entran: los marca la validación (DH-E). En las columnas se comprueban el tipo, la forma, la
longitud y los códigos de las enumeraciones; los textos, no uno a uno.

**Nombres.** Los sondeos y los códigos de catálogo se comparan sin los espacios exteriores y
sin distinguir mayúsculas (:func:`name_key`; plan §5.2.2, RF-005-11); el texto se guarda tal
como venía.

Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field, fields
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, NamedTuple, Self

import numpy as np

from ..core.content import ContentDigest
from ..core.errors import ValidationError
from ..core.georef import CrsRef, VerticalRef
from ..core.numbers import parse_decimal
from ..core.params import ParamKind
from ..core.paths import find_absolute_paths

__all__ = [
    "CATALOG_KINDS",
    "CHILD_TABLES",
    "CONVENTION_KEYS",
    "DECIMAL_MARKS",
    "DECLINATION_LIMIT_DEG",
    "DEFAULT_COLOR",
    "DENSITY_KINDS",
    "DEPTH_KINDS",
    "LITHOLOGY_LOG_SET",
    "TABLES",
    "AssayColumns",
    "AssayValue",
    "AzimuthRef",
    "CatalogEntry",
    "Catalogs",
    "Collar",
    "CollarColumns",
    "DetectionFlag",
    "DrillholeSet",
    "Element",
    "FilePrint",
    "HoleType",
    "ImportDto",
    "ImportSource",
    "InclinationConvention",
    "IntervalColumns",
    "LithologyCode",
    "LithologyInterval",
    "OrientationSource",
    "QaqcType",
    "Rejection",
    "SourceDeclaration",
    "StationSource",
    "StructureColumns",
    "StructureMeasure",
    "StructureType",
    "SurveyColumns",
    "SurveyStation",
    "ValueRules",
    "ZoneColumns",
    "ZoneInterval",
    "name_key",
    "parse_declination",
]


# --- Enumeraciones (valores de las tablas dh_*, plan §5.2) -----------------------------------


class AzimuthRef(StrEnum):
    """La referencia de un azimut medido (``dh_survey.azimuth_ref``; RF-005-27)."""

    GRID = "grid"  # norte de cuadrícula
    TRUE = "true"  # norte geográfico
    MAGNETIC = "magnetic"  # norte magnético (con su declinación)


class InclinationConvention(StrEnum):
    """Cómo da la fuente la inclinación (RF-005-28). La interna es ``NEGATIVE_DOWN``."""

    NEGATIVE_DOWN = "negative_down"  # desde la horizontal, negativa hacia abajo (−90 = vertical)
    POSITIVE_DOWN = "positive_down"  # desde la horizontal, positiva hacia abajo
    FROM_VERTICAL = "from_vertical"  # desde la vertical, 0 = vertical hacia abajo


class DetectionFlag(StrEnum):
    """La marca de un valor de laboratorio (``dh_assay.detection_flag``; RF-005-09)."""

    OK = "ok"
    BELOW_DL = "below_dl"  # «<x»: bajo el límite de detección (valor = x)
    ABOVE_UL = "above_ul"  # «>x»: sobre el límite superior (valor = x)
    NOT_ANALYSED = "not_analysed"


class StationSource(StrEnum):
    """De dónde sale una estación de desviación (``dh_survey.source``)."""

    MEASURED = "measured"  # medida, de la tabla de desviaciones
    COLLAR = "collar"  # la orientación en boca de la tabla de bocas
    DECLARED_VERTICAL = "declared_vertical"  # sondeo declarado vertical al importar


class HoleType(StrEnum):
    """El tipo de un sondeo (``dh_collar.hole_type``; lista cerrada, D-9 de la spec)."""

    DD = "DD"  # diamantina
    RC = "RC"  # circulación inversa
    RP = "RP"  # rotopercusión
    AC = "AC"  # air core
    TR = "TR"  # zanja
    CA = "CA"  # calicata
    OT = "OT"  # otro


class QaqcType(StrEnum):
    """El tipo de una muestra para el control de calidad (``dh_assay.qaqc_type``)."""

    SAMPLE = "sample"
    CRM = "crm"  # material de referencia certificado
    BLANK = "blank"
    FIELD_DUP = "field_dup"
    PREP_DUP = "prep_dup"
    PULP_DUP = "pulp_dup"
    UMPIRE = "umpire"


class StructureType(StrEnum):
    """El tipo de una medida estructural (``dh_structure.structure_type``)."""

    BEDDING = "bedding"
    FAULT = "fault"
    JOINT = "joint"
    CONTACT = "contact"
    VEIN = "vein"
    FOLIATION = "foliation"
    ZONE_PLANE = "zone_plane"


class OrientationSource(StrEnum):
    """De dónde sale la orientación de una medida estructural (``dh_structure``)."""

    MEASURED = "measured"
    ALPHA_BETA = "alpha_beta"
    RECMIN_CORTES = "recmin_cortes"  # literal de la tabla CORTES de RecMin (D-7)


DEPTH_KINDS: tuple[ParamKind, ...] = (ParamKind.MEDIDO, ParamKind.CALCULADO)
"""Los tipos de la profundidad total de una boca: MEDIDO o CALCULADO (deducida, DH-W16)."""
DENSITY_KINDS: tuple[ParamKind, ...] = (ParamKind.MEDIDO, ParamKind.ADOPTADO,
                                        ParamKind.HIPOTESIS)
"""Los tipos de una densidad de catálogo (una densidad nunca es CALCULADO)."""
LITHOLOGY_LOG_SET = "lithology"
"""El esquema de logueo de la litología (las tablas adicionales de RecMin, ``recmin_<tabla>``)."""
DEFAULT_COLOR = "#808080"
"""El color de una litología sin color («#RRGGBB», sRGB)."""
DECIMAL_MARKS: tuple[str, ...] = (",", ".")
DECLINATION_LIMIT_DEG = 180.0
"""La declinación magnética va de −180° a 180° (positiva al este)."""
CATALOG_KINDS: tuple[str, ...] = ("lithology", "element", "sector", "group", "zone")
"""Los catálogos de los códigos nuevos de una importación (:attr:`ImportDto.new_codes`)."""
CONVENTION_KEYS: tuple[str, ...] = (
    "all_vertical",
    "azimuth_ref",
    "declination_deg",
    "density_kind",
    "inclination_convention",
    "negative_is_below_dl",
    "sentinels",
    "units",
)
"""Las claves de :meth:`SourceDeclaration.conventions`, en orden."""

_COLOR = re.compile(r"#[0-9A-F]{6}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DECLINATION_OBJ = "Declinación magnética"
_DECLINATION_FIELD = "declination"


def name_key(name: str) -> str:
    """La forma con que se comparan los nombres de los sondeos y los códigos de los catálogos:
    sin los espacios exteriores y sin distinguir mayúsculas (plan §5.2.2; RF-005-11)."""
    if not isinstance(name, str):
        raise TypeError(f"un nombre o un código es un texto, no {name!r}")
    return name.strip().casefold()


def parse_declination(text: object) -> float:
    """La declinación magnética tecleada (texto con coma o punto decimal, positiva al este) en
    float64, exacta: «0,25» → 0.25, nunca el float32 de un ``FloatProperty`` (RF-005-07,
    RF-005-27). :class:`~geoblender.core.errors.ValidationError` si no es un número
    (``core.number_invalid``/``core.number_missing``) o está fuera de [−180, 180]
    (``dh.declination_out_of_range``)."""
    value = parse_decimal(text, obj=_DECLINATION_OBJ, field=_DECLINATION_FIELD)
    if not -DECLINATION_LIMIT_DEG <= value <= DECLINATION_LIMIT_DEG:
        raise ValidationError(
            "dh.declination_out_of_range",
            "la declinación magnética va de −180° a 180° (positiva al este)",
            obj=_DECLINATION_OBJ,
            field=_DECLINATION_FIELD,
            value=text,
        )
    return value


# --- Campos: cómo se comprueba cada uno y cómo se guarda en columnas -------------------------


@dataclass(frozen=True, slots=True)
class _Field:
    """Un campo de un registro: su nombre, su clase (``kind``) y, en una enumeración, sus
    valores en el orden de sus códigos int8.

    Clases: ``key`` (texto no vacío; ``key?``, o ``None``), ``hole`` (el sondeo de un registro
    hijo, en la columna ``hole_name``; ``hole?``, o ``None``), ``text`` (texto o ``None``),
    ``float`` (float64; un NaN se conserva), ``float?`` (float64 o ``None`` = NaN), ``bool``,
    ``int``, ``int?``, ``date?`` (un día, sin hora), ``color`` («#RRGGBB»), ``extra`` (un
    diccionario con claves de texto) y ``code``/``code?`` (una enumeración)."""

    name: str
    kind: str
    values: tuple[Any, ...] = ()

    @property
    def column(self) -> str:
        """El nombre de su columna: el del campo, salvo el sondeo (``hole_name``)."""
        return "hole_name" if self.kind in ("hole", "hole?") else self.name


def _fields(*items: str | tuple[str, str, tuple[Any, ...]]) -> tuple[_Field, ...]:
    """Los campos de un registro: «nombre clase» o (nombre, clase, valores)."""
    found = []
    for item in items:
        if isinstance(item, str):
            name, kind = item.split()
            found.append(_Field(name, kind))
        else:
            found.append(_Field(*item))
    return tuple(found)


def _key(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    if not value.strip():
        raise ValueError(f"{what} no puede quedar vacío")
    return value


def _text(value: object, what: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{what} es un texto o None, no {value!r}")
    return value


def _float(value: object, what: str) -> float:
    """Un número en float64, sin cambiar su valor (RF-005-02)."""
    if isinstance(value, float):  # también numpy.float64, que lo es
        return value if type(value) is float else float(value)
    if isinstance(value, np.floating):
        raise TypeError(
            f"{what} = {value!r} es de precisión {value.dtype} y no float64: el valor decimal de "
            f"la fuente llega en float64, y un Single de RecMin por su decimal más corto "
            f"(RF-005-02)"
        )
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise TypeError(f"{what} es un número (float64), no {value!r}")
    converted = float(value)
    if converted != value:
        raise ValueError(f"{what} = {value} no cabe exacto en float64")
    return converted


def _optional_float(value: object, what: str) -> float | None:
    if value is None:
        return None
    converted = _float(value, what)
    return None if math.isnan(converted) else converted


def _bool(value: object, what: str) -> bool:
    if not isinstance(value, bool | np.bool_):
        raise TypeError(f"{what} es sí o no (bool), no {value!r}")
    return bool(value)


def _int(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise TypeError(f"{what} es un entero, no {value!r}")
    return int(value)


def _date(value: object, what: str) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
        raise TypeError(f"{what} es un día (date, sin hora) o None, no {value!r}")
    return value


def _extra(value: object, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{what} es un diccionario (los campos sin columna), no {value!r}")
    copied = dict(value)
    for key in copied:
        if not isinstance(key, str):
            raise TypeError(f"las claves de {what} son textos, no {key!r}")
    return MappingProxyType(copied)


def _member(value: object, values: tuple[Any, ...], what: str) -> Any:
    """El valor de la enumeración ``values`` que es ``value`` (su miembro o su texto)."""
    if isinstance(value, str):
        for member in values:
            if value == member:
                return member
        raise ValueError(f"{what} es uno de {[str(v) for v in values]}, no {value!r}")
    raise TypeError(f"{what} es uno de {[str(v) for v in values]}, no {value!r}")


def _color(value: object, what: str) -> str:
    if not isinstance(value, str) or _COLOR.fullmatch(value) is None:
        raise ValueError(f"{what} es «#RRGGBB» con cifras hexadecimales en mayúsculas, no "
                         f"{value!r}")
    return value


def _normalized(spec: _Field, value: object, what: str) -> Any:
    """``value`` comprobado y con su tipo canónico para la clase de ``spec``."""
    kind = spec.kind
    if kind in ("key", "hole"):
        return _key(value, what)
    if kind in ("key?", "hole?"):
        return None if value is None else _key(value, what)
    if kind == "text":
        return _text(value, what)
    if kind == "float":
        return _float(value, what)
    if kind == "float?":
        return _optional_float(value, what)
    if kind == "bool":
        return _bool(value, what)
    if kind == "int":
        return _int(value, what)
    if kind == "int?":
        return None if value is None else _int(value, what)
    if kind == "date?":
        return _date(value, what)
    if kind == "color":
        return _color(value, what)
    if kind == "extra":
        return _extra(value, what)
    if kind == "code":
        return _member(value, spec.values, what)
    if kind == "code?":
        return None if value is None else _member(value, spec.values, what)
    raise AssertionError(f"clase de campo desconocida: {kind}")  # pragma: no cover


def _normalize(record: Any) -> None:
    """Comprueba cada campo de ``record`` y le da su tipo canónico (registro inmutable)."""
    owner = type(record).__name__
    for spec in record._SPECS:
        value = getattr(record, spec.name)
        new = _normalized(spec, value, f"{owner}.{spec.name}")
        if new is not value:
            object.__setattr__(record, spec.name, new)


def _check_density(record: Any) -> None:
    if record.density is not None and record.density_kind is None:
        raise ValueError(f"{type(record).__name__} «{record.code}»: una densidad lleva su tipo "
                         f"(MEDIDO, ADOPTADO o HIPÓTESIS)")


# --- Registros ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Collar:
    """Una boca (``dh_collar``): ``name`` tal como venía; ``x``, ``y`` y ``z`` absolutas (m)
    en el CRS de su conjunto; ``depth``, la profundidad total (m), MEDIDO o CALCULADO
    (deducida de la última medida, DH-W16); su tipo (:class:`HoleType`), si es planificado o
    de control de leyes, categoría y prioridad, sector y grupo (códigos de catálogo),
    campaña, fechas, método de levantamiento, identificador de origen
    (``recmin:SONDEOS:1234``), comentarios y ``extra`` (los campos de la fuente sin columna).
    Una coordenada o una profundidad ausente es ``None`` (DH-E02, DH-E03), nunca un
    centinela."""

    name: str
    x: float | None
    y: float | None
    z: float | None
    depth: float | None
    _: KW_ONLY
    depth_kind: ParamKind = ParamKind.MEDIDO
    hole_type: HoleType | None = None
    planned: bool = False
    grade_control: bool = False
    category: int | None = None
    priority: int | None = None
    sector: str | None = None
    group: str | None = None
    campaign: str | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    survey_method: str | None = None
    external_id: str | None = None
    comments: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    _SPECS: ClassVar[tuple[_Field, ...]] = _fields(
        "name key", "x float?", "y float?", "z float?", "depth float?",
        ("depth_kind", "code", DEPTH_KINDS), ("hole_type", "code?", tuple(HoleType)),
        "planned bool", "grade_control bool", "category int?", "priority int?",
        "sector key?", "group key?", "campaign text", "start_date date?", "end_date date?",
        "survey_method text", "external_id text", "comments text", "extra extra",
    )

    def __post_init__(self) -> None:
        _normalize(self)


@dataclass(frozen=True, slots=True)
class SurveyStation:
    """Una estación de desviación (``dh_survey``): el sondeo, la profundidad (m), el azimut y
    la inclinación (°), y de dónde sale (:class:`StationSource`).

    En el ``DrillholeSet`` de una fuente (el de un :class:`ImportDto`), ``azimuth`` e
    ``inclination`` están en los convenios que declara su :class:`SourceDeclaration` (los
    demás campos de ángulos pueden quedar sin rellenar: manda la declaración). Convertida (la
    base del proyecto), ``azimuth`` es de cuadrícula, en sentido horario; ``inclination``,
    desde la horizontal y negativa hacia abajo; ``azimuth_measured`` y ``azimuth_ref``, el
    azimut tal como venía y su referencia; ``declination_deg`` y ``convergence_deg``, la δ y
    la γ aplicadas (D5 del plan; RF-005-27)."""

    hole: str
    depth: float
    azimuth: float
    inclination: float
    _: KW_ONLY
    azimuth_measured: float | None = None
    azimuth_ref: AzimuthRef | None = None
    declination_deg: float | None = None
    convergence_deg: float | None = None
    source: StationSource = StationSource.MEASURED
    method: str | None = None
    external_id: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    _SPECS: ClassVar[tuple[_Field, ...]] = _fields(
        "hole hole", "depth float", "azimuth float", "inclination float",
        "azimuth_measured float?", ("azimuth_ref", "code?", tuple(AzimuthRef)),
        "declination_deg float?", "convergence_deg float?",
        ("source", "code", tuple(StationSource)), "method text", "external_id text",
        "extra extra",
    )

    def __post_init__(self) -> None:
        _normalize(self)


@dataclass(frozen=True, slots=True)
class LithologyInterval:
    """Un tramo ``[from_m, to_m)`` (m) de litología (``dh_lithology``) con su código de
    catálogo y su esquema de logueo (``lithology``; las tablas adicionales de RecMin,
    ``recmin_<tabla>``)."""

    hole: str
    from_m: float
    to_m: float
    code: str
    _: KW_ONLY
    log_set: str = LITHOLOGY_LOG_SET
    description: str | None = None
    logged_by: str | None = None
    external_id: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    _SPECS: ClassVar[tuple[_Field, ...]] = _fields(
        "hole hole", "from_m float", "to_m float", "code key", "log_set key",
        "description text", "logged_by text", "external_id text", "extra extra",
    )

    def __post_init__(self) -> None:
        _normalize(self)


@dataclass(frozen=True, slots=True)
class AssayValue:
    """Un valor de un elemento en un tramo (``dh_assay``, formato largo; RF-005-09): ``value``
    en ``unit`` (``None`` = ausente; bajo el límite, el límite con ``BELOW_DL``; «>x», x con
    ``ABOVE_UL``), el texto y la unidad originales (``reported_value``, ``reported_unit``),
    laboratorio, método, muestra, lote y control de calidad. Un material de referencia o un
    blanco puede no tener sondeo ni tramo (``None``)."""

    hole: str | None
    from_m: float | None
    to_m: float | None
    element: str
    value: float | None
    unit: str
    _: KW_ONLY
    detection_flag: DetectionFlag = DetectionFlag.OK
    reported_value: str | None = None
    reported_unit: str | None = None
    lab: str | None = None
    method: str | None = None
    sample_id: str | None = None
    batch: str | None = None
    qaqc_type: QaqcType = QaqcType.SAMPLE
    crm_code: str | None = None
    parent_sample_id: str | None = None
    is_primary: bool = True
    external_id: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    _SPECS: ClassVar[tuple[_Field, ...]] = _fields(
        "hole hole?", "from_m float?", "to_m float?", "element key", "value float?",
        "unit key", ("detection_flag", "code", tuple(DetectionFlag)), "reported_value text",
        "reported_unit text", "lab text", "method text", "sample_id text", "batch text",
        ("qaqc_type", "code", tuple(QaqcType)), "crm_code text", "parent_sample_id text",
        "is_primary bool", "external_id text", "extra extra",
    )

    def __post_init__(self) -> None:
        _normalize(self)


@dataclass(frozen=True, slots=True)
class ZoneInterval:
    """Un tramo de un sondeo en una zona (``dh_zone_interval``; INTERSECCIONES de RecMin), con
    su ángulo literal de RecMin (D-7)."""

    hole: str
    from_m: float
    to_m: float
    zone: str
    _: KW_ONLY
    angle_deg: float | None = None
    external_id: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    _SPECS: ClassVar[tuple[_Field, ...]] = _fields(
        "hole hole", "from_m float", "to_m float", "zone key", "angle_deg float?",
        "external_id text", "extra extra",
    )

    def __post_init__(self) -> None:
        _normalize(self)


@dataclass(frozen=True, slots=True)
class StructureMeasure:
    """Una medida estructural a una profundidad (``dh_structure``; CORTES de RecMin, literal,
    D-7): tipo, buzamiento y dirección, α y β, de dónde sale la orientación y zona."""

    hole: str
    depth: float
    structure_type: StructureType
    _: KW_ONLY
    dip: float | None = None
    dip_direction: float | None = None
    alpha: float | None = None
    beta: float | None = None
    orientation_source: OrientationSource = OrientationSource.MEASURED
    zone: str | None = None
    confidence: str | None = None
    comments: str | None = None
    external_id: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    _SPECS: ClassVar[tuple[_Field, ...]] = _fields(
        "hole hole", "depth float", ("structure_type", "code", tuple(StructureType)),
        "dip float?", "dip_direction float?", "alpha float?", "beta float?",
        ("orientation_source", "code", tuple(OrientationSource)), "zone key?",
        "confidence text", "comments text", "external_id text", "extra extra",
    )

    def __post_init__(self) -> None:
        _normalize(self)


# --- Catálogos ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LithologyCode:
    """Un código de litología (``dh_lithology_code``) de un esquema de logueo: color
    «#RRGGBB» (sRGB), trama, densidad (t/m³) con su tipo, orden y si sale en la leyenda."""

    code: str
    _: KW_ONLY
    log_set: str = LITHOLOGY_LOG_SET
    description: str | None = None
    color: str = DEFAULT_COLOR
    pattern: str | None = None
    density: float | None = None
    density_kind: ParamKind | None = None
    sort_order: int = 0
    show_in_legend: bool = True
    external_id: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    _SPECS: ClassVar[tuple[_Field, ...]] = _fields(
        "code key", "log_set key", "description text", "color color", "pattern text",
        "density float?", ("density_kind", "code?", DENSITY_KINDS), "sort_order int",
        "show_in_legend bool", "external_id text", "extra extra",
    )

    def __post_init__(self) -> None:
        _normalize(self)
        _check_density(self)


@dataclass(frozen=True, slots=True)
class Element:
    """Un elemento (``dh_element``): código, unidad (``g/t``, ``ppm``, ``ppb``, ``%`` o
    ``text``), nombre, decimales, orden, si se muestra y se usa en los cálculos, límite de
    detección, expresión (los calculados de RecMin) y leyenda de color."""

    code: str
    unit: str
    _: KW_ONLY
    name: str | None = None
    decimals: int = 2
    sort_order: int = 0
    show_in_tables: bool = True
    use_in_calc: bool = True
    detection_limit: float | None = None
    expression: str | None = None
    color_legend: str | None = None
    external_id: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    _SPECS: ClassVar[tuple[_Field, ...]] = _fields(
        "code key", "unit key", "name text", "decimals int", "sort_order int",
        "show_in_tables bool", "use_in_calc bool", "detection_limit float?",
        "expression text", "color_legend text", "external_id text", "extra extra",
    )

    def __post_init__(self) -> None:
        _normalize(self)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """Una entrada de los catálogos de sectores, grupos y zonas (``dh_sector``, ``dh_group``,
    ``dh_zone``); la densidad (t/m³, con su tipo), solo en las zonas."""

    code: str
    _: KW_ONLY
    description: str | None = None
    density: float | None = None
    density_kind: ParamKind | None = None
    external_id: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    _SPECS: ClassVar[tuple[_Field, ...]] = _fields(
        "code key", "description text", "density float?",
        ("density_kind", "code?", DENSITY_KINDS), "external_id text", "extra extra",
    )

    def __post_init__(self) -> None:
        _normalize(self)
        _check_density(self)


def _entries(value: object, kind: type, what: str) -> tuple[Any, ...]:
    if isinstance(value, str | bytes | Mapping) or not isinstance(value, Iterable):
        raise TypeError(f"{what} es una lista de {kind.__name__}, no {value!r}")
    entries = tuple(value)
    for entry in entries:
        if type(entry) is not kind:
            raise TypeError(f"{what} es una lista de {kind.__name__}, no tiene {entry!r}")
    return entries


@dataclass(frozen=True)
class Catalogs:
    """Los catálogos de un conjunto de sondeos: litologías (únicas por esquema de logueo y
    código), elementos, sectores, grupos y zonas (únicos por código), sin distinguir
    mayúsculas ni espacios exteriores."""

    lithology: tuple[LithologyCode, ...] = ()
    elements: tuple[Element, ...] = ()
    sectors: tuple[CatalogEntry, ...] = ()
    groups: tuple[CatalogEntry, ...] = ()
    zones: tuple[CatalogEntry, ...] = ()

    def __post_init__(self) -> None:
        for name, kind in (("lithology", LithologyCode), ("elements", Element),
                           ("sectors", CatalogEntry), ("groups", CatalogEntry),
                           ("zones", CatalogEntry)):
            entries = _entries(getattr(self, name), kind, f"el catálogo «{name}»")
            seen: dict[tuple[str, str], str] = {}
            for entry in entries:
                log_set = name_key(entry.log_set) if kind is LithologyCode else ""
                key = (log_set, name_key(entry.code))
                if key in seen:
                    raise ValueError(f"el catálogo «{name}» repite el código «{entry.code}» "
                                     f"(«{seen[key]}»)")
                seen[key] = entry.code
            object.__setattr__(self, name, entries)


# --- Columnas ---------------------------------------------------------------------------------

_DTYPES: Mapping[str, Any] = MappingProxyType({
    "float": np.dtype(np.float64),
    "float?": np.dtype(np.float64),
    "bool": np.dtype(np.bool_),
    "int": np.dtype(np.int64),
    "code": np.dtype(np.int8),
    "code?": np.dtype(np.int8),
})
_OBJECT = np.dtype(object)
_HOLE_INDEX = np.dtype(np.int64)


def _encode(values: list[Any], spec: _Field) -> np.ndarray:
    """La columna de los valores (ya normalizados) de un campo."""
    kind = spec.kind
    if kind == "float":
        return np.array(values, dtype=np.float64)
    if kind == "float?":
        return np.array([math.nan if v is None else v for v in values], dtype=np.float64)
    if kind == "bool":
        return np.array(values, dtype=np.bool_)
    if kind == "int":
        return np.array(values, dtype=np.int64)
    if kind in ("code", "code?"):
        index = {member: code for code, member in enumerate(spec.values)}
        return np.array([-1 if v is None else index[v] for v in values], dtype=np.int8)
    return np.fromiter(values, dtype=object, count=len(values))


def _decode(column: np.ndarray, spec: _Field) -> list[Any]:
    """Los valores de los registros de una columna."""
    kind = spec.kind
    if kind == "float?":
        return [None if v != v else v for v in column.tolist()]
    if kind in ("code", "code?"):
        members = spec.values
        return [None if code < 0 else members[code] for code in column.tolist()]
    return column.tolist()


@dataclass(frozen=True, eq=False)
class _Columns:
    """Las columnas de una tabla: un array numpy de una dimensión por campo, todos de la misma
    longitud (véase el módulo)."""

    _RECORD: ClassVar[type]

    def __post_init__(self) -> None:
        owner = type(self).__name__
        dtypes = {spec.column: _DTYPES.get(spec.kind, _OBJECT)
                  for spec in self._RECORD._SPECS}
        if "hole_name" in dtypes:
            dtypes["hole"] = _HOLE_INDEX
        length: int | None = None
        for item in fields(self):
            column = getattr(self, item.name)
            what = f"{owner}.{item.name}"
            if not isinstance(column, np.ndarray) or column.ndim != 1:
                raise TypeError(f"{what} es un array numpy de una dimensión, no {column!r}")
            expected = dtypes[item.name]
            if column.dtype != expected:
                rule = " (RF-005-02: nunca en precisión simple)" if expected.kind == "f" else ""
                raise TypeError(f"{what} es {expected}{rule}, no {column.dtype}")
            if length is None:
                length = len(column)
            elif len(column) != length:
                raise ValueError(f"las columnas de {owner} tienen longitudes distintas: "
                                 f"{item.name} tiene {len(column)} y no {length}")
        for spec in self._RECORD._SPECS:
            column = getattr(self, spec.column)
            if spec.kind in ("code", "code?") and column.size:
                lowest = -1 if spec.kind == "code?" else 0
                if column.min() < lowest or column.max() >= len(spec.values):
                    raise ValueError(f"{owner}.{spec.name} tiene códigos fuera de "
                                     f"[{lowest}, {len(spec.values) - 1}]")
        if "hole" in dtypes and length and self.hole.min() < -1:  # type: ignore[attr-defined]
            raise ValueError(f"{owner}.hole es el índice de la boca o −1, no menos")

    def __len__(self) -> int:
        return len(getattr(self, fields(self)[0].name))

    @classmethod
    def code_values(cls, name: str) -> tuple[Any, ...]:
        """Los valores de la columna de códigos ``name``: el código int8 es su posición."""
        for spec in cls._RECORD._SPECS:
            if spec.name == name and spec.kind in ("code", "code?"):
                return spec.values
        raise ValueError(f"«{name}» no es una columna de códigos de {cls.__name__}")

    @classmethod
    def _arrays(cls, records: Iterable[Any]) -> dict[str, np.ndarray]:
        record_type = cls._RECORD
        rows = tuple(records)
        for row in rows:
            if type(row) is not record_type:
                raise TypeError(f"las filas de {cls.__name__} son {record_type.__name__}, no "
                                f"{row!r}")
        return {spec.column: _encode([getattr(row, spec.name) for row in rows], spec)
                for spec in record_type._SPECS}

    def records(self) -> tuple[Any, ...]:
        """Los registros de las columnas, en su orden (con los mismos bits en cada número)."""
        specs = self._RECORD._SPECS
        names = [spec.name for spec in specs]
        columns = [_decode(getattr(self, spec.column), spec) for spec in specs]
        record_type = self._RECORD
        return tuple(record_type(**dict(zip(names, row, strict=True)))
                     for row in zip(*columns, strict=True))

    def take(self, index: np.ndarray, **columns: np.ndarray) -> Self:
        """Las filas ``index`` (índices o máscara de numpy), con ``columns`` en lugar de las
        suyas."""
        values = {item.name: getattr(self, item.name)[index] for item in fields(self)}
        values.update(columns)
        return type(self)(**values)


@dataclass(frozen=True, eq=False)
class CollarColumns(_Columns):
    """Las bocas en columnas (campos de :class:`Collar`)."""

    name: np.ndarray
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    depth: np.ndarray
    depth_kind: np.ndarray
    hole_type: np.ndarray
    planned: np.ndarray
    grade_control: np.ndarray
    category: np.ndarray
    priority: np.ndarray
    sector: np.ndarray
    group: np.ndarray
    campaign: np.ndarray
    start_date: np.ndarray
    end_date: np.ndarray
    survey_method: np.ndarray
    external_id: np.ndarray
    comments: np.ndarray
    extra: np.ndarray

    _RECORD: ClassVar[type] = Collar

    @classmethod
    def from_records(cls, records: Iterable[Collar]) -> CollarColumns:
        """Las columnas de las bocas ``records``."""
        return cls(**cls._arrays(records))

    @classmethod
    def empty(cls) -> CollarColumns:
        return cls.from_records(())

    def lookup(self, names: Iterable[str | None]) -> np.ndarray:
        """El índice (int64) de la boca de cada nombre, sin distinguir mayúsculas ni espacios
        exteriores: con dos bocas del mismo nombre (DH-E01), la primera; sin boca o ``None``,
        −1."""
        first: dict[str, int] = {}
        for index, name in enumerate(self.name.tolist()):
            first.setdefault(name_key(name), index)
        found = [-1 if name is None else first.get(name_key(name), -1) for name in names]
        return np.array(found, dtype=np.int64)


@dataclass(frozen=True, eq=False)
class _HoleColumns(_Columns):
    """Las columnas de una tabla hija: ``hole`` (índice de la boca, −1 sin ella) y
    ``hole_name`` (el sondeo tal como venía) además de los campos de su registro."""

    @classmethod
    def from_records(cls, records: Iterable[Any], collars: CollarColumns) -> Self:
        """Las columnas de ``records``, enlazados a ``collars`` por el nombre del sondeo
        (:meth:`CollarColumns.lookup`)."""
        arrays = cls._arrays(records)
        arrays["hole"] = collars.lookup(arrays["hole_name"].tolist())
        return cls(**arrays)

    @classmethod
    def empty(cls) -> Self:
        return cls.from_records((), CollarColumns.empty())


@dataclass(frozen=True, eq=False)
class SurveyColumns(_HoleColumns):
    """Las estaciones de desviación en columnas (campos de :class:`SurveyStation`)."""

    hole: np.ndarray
    hole_name: np.ndarray
    depth: np.ndarray
    azimuth: np.ndarray
    inclination: np.ndarray
    azimuth_measured: np.ndarray
    azimuth_ref: np.ndarray
    declination_deg: np.ndarray
    convergence_deg: np.ndarray
    source: np.ndarray
    method: np.ndarray
    external_id: np.ndarray
    extra: np.ndarray

    _RECORD: ClassVar[type] = SurveyStation


@dataclass(frozen=True, eq=False)
class IntervalColumns(_HoleColumns):
    """Los tramos de litología en columnas (campos de :class:`LithologyInterval`)."""

    hole: np.ndarray
    hole_name: np.ndarray
    from_m: np.ndarray
    to_m: np.ndarray
    code: np.ndarray
    log_set: np.ndarray
    description: np.ndarray
    logged_by: np.ndarray
    external_id: np.ndarray
    extra: np.ndarray

    _RECORD: ClassVar[type] = LithologyInterval


@dataclass(frozen=True, eq=False)
class AssayColumns(_HoleColumns):
    """Los análisis en columnas (campos de :class:`AssayValue`)."""

    hole: np.ndarray
    hole_name: np.ndarray
    from_m: np.ndarray
    to_m: np.ndarray
    element: np.ndarray
    value: np.ndarray
    unit: np.ndarray
    detection_flag: np.ndarray
    reported_value: np.ndarray
    reported_unit: np.ndarray
    lab: np.ndarray
    method: np.ndarray
    sample_id: np.ndarray
    batch: np.ndarray
    qaqc_type: np.ndarray
    crm_code: np.ndarray
    parent_sample_id: np.ndarray
    is_primary: np.ndarray
    external_id: np.ndarray
    extra: np.ndarray

    _RECORD: ClassVar[type] = AssayValue


@dataclass(frozen=True, eq=False)
class ZoneColumns(_HoleColumns):
    """Los tramos en zonas en columnas (campos de :class:`ZoneInterval`)."""

    hole: np.ndarray
    hole_name: np.ndarray
    from_m: np.ndarray
    to_m: np.ndarray
    zone: np.ndarray
    angle_deg: np.ndarray
    external_id: np.ndarray
    extra: np.ndarray

    _RECORD: ClassVar[type] = ZoneInterval


@dataclass(frozen=True, eq=False)
class StructureColumns(_HoleColumns):
    """Las medidas estructurales en columnas (campos de :class:`StructureMeasure`)."""

    hole: np.ndarray
    hole_name: np.ndarray
    depth: np.ndarray
    structure_type: np.ndarray
    dip: np.ndarray
    dip_direction: np.ndarray
    alpha: np.ndarray
    beta: np.ndarray
    orientation_source: np.ndarray
    zone: np.ndarray
    confidence: np.ndarray
    comments: np.ndarray
    external_id: np.ndarray
    extra: np.ndarray

    _RECORD: ClassVar[type] = StructureMeasure


TABLES: Mapping[str, type[_Columns]] = MappingProxyType({
    "collars": CollarColumns,
    "surveys": SurveyColumns,
    "lithology": IntervalColumns,
    "assays": AssayColumns,
    "zones": ZoneColumns,
    "structures": StructureColumns,
})
"""Las tablas de un :class:`DrillholeSet` y la clase de sus columnas."""
CHILD_TABLES: tuple[str, ...] = ("surveys", "lithology", "assays", "zones", "structures")
"""Las tablas hijas de un :class:`DrillholeSet` (con ``hole`` y ``hole_name``)."""


def _check_specs() -> None:
    """Cada registro declara sus campos en orden y cada clase de columnas tiene una columna
    por campo (más ``hole`` en las hijas): un error aquí es del programa."""
    for name, columns in TABLES.items():
        record = columns._RECORD
        record_names = tuple(item.name for item in fields(record))
        if record_names != tuple(spec.name for spec in record._SPECS):
            raise TypeError(f"los campos de {record.__name__} no son los de su _SPECS")
        expected = [spec.column for spec in record._SPECS]
        if name in CHILD_TABLES:
            expected.insert(0, "hole")
        if [item.name for item in fields(columns)] != expected:
            raise TypeError(f"las columnas de {columns.__name__} no son los campos de "
                            f"{record.__name__}")
    for record in (LithologyCode, Element, CatalogEntry):
        if tuple(item.name for item in fields(record)) != tuple(s.name for s in record._SPECS):
            raise TypeError(f"los campos de {record.__name__} no son los de su _SPECS")


_check_specs()


# --- El conjunto de sondeos -------------------------------------------------------------------


@dataclass(frozen=True, eq=False, kw_only=True)
class DrillholeSet:
    """Un conjunto de sondeos en columnas (véase el módulo): su CRS y su referencia vertical
    (las del catálogo: nunca se suponen, RF-005-07), una clase de columnas por tabla
    (:data:`TABLES`) y los catálogos.

    Las coordenadas son absolutas y en float64, en ``crs`` y ``vertical``: los de la fuente en
    el de una importación (:class:`ImportDto`) y los del proyecto en el que lee el almacén.
    El ``hole`` de cada fila hija está en [−1, número de bocas)."""

    crs: CrsRef
    vertical: VerticalRef
    collars: CollarColumns = field(default_factory=CollarColumns.empty)
    surveys: SurveyColumns = field(default_factory=SurveyColumns.empty)
    lithology: IntervalColumns = field(default_factory=IntervalColumns.empty)
    assays: AssayColumns = field(default_factory=AssayColumns.empty)
    zones: ZoneColumns = field(default_factory=ZoneColumns.empty)
    structures: StructureColumns = field(default_factory=StructureColumns.empty)
    catalogs: Catalogs = field(default_factory=Catalogs)

    def __post_init__(self) -> None:
        if not isinstance(self.crs, CrsRef):
            raise TypeError(f"el CRS de un conjunto de sondeos es un CrsRef del catálogo (nunca "
                            f"se supone, RF-005-07), no {self.crs!r}")
        if not isinstance(self.vertical, VerticalRef):
            raise TypeError(f"la referencia vertical de un conjunto de sondeos es un "
                            f"VerticalRef (nunca se supone, RF-005-07), no {self.vertical!r}")
        for name, columns in TABLES.items():
            if type(getattr(self, name)) is not columns:
                raise TypeError(f"«{name}» de un conjunto de sondeos es un {columns.__name__}, "
                                f"no {getattr(self, name)!r}")
        if not isinstance(self.catalogs, Catalogs):
            raise TypeError(f"los catálogos son un Catalogs, no {self.catalogs!r}")
        holes = len(self.collars)
        for name in CHILD_TABLES:
            hole = getattr(self, name).hole
            if hole.size and hole.max() >= holes:
                raise ValueError(f"«{name}» apunta a la boca {int(hole.max())} y solo hay "
                                 f"{holes}")

    @classmethod
    def from_records(
        cls,
        *,
        crs: CrsRef,
        vertical: VerticalRef,
        collars: Iterable[Collar] = (),
        surveys: Iterable[SurveyStation] = (),
        lithology: Iterable[LithologyInterval] = (),
        assays: Iterable[AssayValue] = (),
        zones: Iterable[ZoneInterval] = (),
        structures: Iterable[StructureMeasure] = (),
        catalogs: Catalogs | None = None,
    ) -> DrillholeSet:
        """El conjunto de unos registros, con las filas hijas enlazadas a sus bocas por el
        nombre del sondeo (:meth:`CollarColumns.lookup`)."""
        collar_columns = CollarColumns.from_records(collars)
        return cls(
            crs=crs,
            vertical=vertical,
            collars=collar_columns,
            surveys=SurveyColumns.from_records(surveys, collar_columns),
            lithology=IntervalColumns.from_records(lithology, collar_columns),
            assays=AssayColumns.from_records(assays, collar_columns),
            zones=ZoneColumns.from_records(zones, collar_columns),
            structures=StructureColumns.from_records(structures, collar_columns),
            catalogs=Catalogs() if catalogs is None else catalogs,
        )

    def hole_index(self, names: Sequence[str]) -> np.ndarray:
        """La posición (int64) de cada sondeo de ``names`` entre las bocas, sin distinguir
        mayúsculas ni espacios exteriores (de dos con el mismo nombre, la primera).
        ``KeyError`` con los que no están."""
        if isinstance(names, str):
            raise TypeError(f"hole_index recibe una lista de nombres, no un texto: {names!r}")
        wanted = list(names)
        found = self.collars.lookup(wanted)
        missing = [str(name) for name, index in zip(wanted, found.tolist(), strict=True)
                   if index < 0]
        if missing:
            raise KeyError(f"sondeos que no están en el conjunto: {', '.join(missing)}")
        return found

    def select(self, hole_index: np.ndarray) -> DrillholeSet:
        """Las bocas ``hole_index`` (posiciones distintas, en el orden pedido, o una máscara
        de una por boca) con sus filas hijas, en su orden de antes y con el índice nuevo de su
        boca; las que no tienen boca no pasan. Los catálogos, el CRS y la referencia vertical
        son los mismos. ``IndexError`` con una posición fuera de rango; ``ValueError`` con una
        repetida o una máscara de otra longitud."""
        holes = len(self.collars)
        index = np.asarray(hole_index)
        if index.ndim != 1:
            raise ValueError(f"select recibe un array de una dimensión, no de {index.ndim}")
        if index.dtype == np.bool_:
            if index.shape != (holes,):
                raise ValueError(f"una máscara de bocas tiene {holes} valores, no {index.size}")
            index = np.flatnonzero(index)
        elif not np.issubdtype(index.dtype, np.integer):
            raise TypeError(f"select recibe posiciones enteras o una máscara, no {index.dtype}")
        index = index.astype(np.int64, copy=False)
        if index.size and (index.min() < 0 or index.max() >= holes):
            raise IndexError(f"posiciones de boca fuera de [0, {holes})")
        if np.unique(index).size != index.size:
            raise ValueError("select recibe cada boca una sola vez")
        position = np.full(holes, -1, dtype=np.int64)
        position[index] = np.arange(index.size, dtype=np.int64)
        children: dict[str, _Columns] = {}
        for name in CHILD_TABLES:
            columns = getattr(self, name)
            linked = columns.hole >= 0
            moved = np.full(columns.hole.shape, -1, dtype=np.int64)
            moved[linked] = position[columns.hole[linked]]
            keep = np.flatnonzero(moved >= 0)
            children[name] = columns.take(keep, hole=moved[keep])
        return DrillholeSet(crs=self.crs, vertical=self.vertical,
                            collars=self.collars.take(index), catalogs=self.catalogs,
                            **children)


# --- Lo que declara la fuente -----------------------------------------------------------------


@dataclass(frozen=True)
class ValueRules:
    """Cómo se leen los valores de una fuente (RF-005-09): el separador decimal (coma o
    punto), los centinelas declarados (textos que significan «ausente», como «−99» o «ND») y
    si un negativo −x significa «<x»."""

    decimal_mark: str
    sentinels: frozenset[str] = frozenset()
    negative_is_below_dl: bool = False

    def __post_init__(self) -> None:
        if self.decimal_mark not in DECIMAL_MARKS:
            raise ValueError(f"el separador decimal es «,» o «.», no {self.decimal_mark!r}")
        sentinels = self.sentinels
        if isinstance(sentinels, str | bytes) or not isinstance(sentinels, Iterable):
            raise TypeError(f"los centinelas son una lista de textos, no {sentinels!r}")
        found = frozenset(sentinels)
        for sentinel in found:
            _key(sentinel, "un centinela")
        if not isinstance(self.negative_is_below_dl, bool):
            raise TypeError(f"«−x = <x» es sí o no, no {self.negative_is_below_dl!r}")
        object.__setattr__(self, "sentinels", found)


def _units(units: object) -> Mapping[str, str]:
    if not isinstance(units, Mapping):
        raise TypeError(f"las unidades son un diccionario elemento → unidad, no {units!r}")
    found: dict[str, str] = {}
    seen: dict[str, str] = {}
    for code, unit in units.items():
        _key(code, "el código de un elemento")
        _key(unit, f"la unidad de «{code}»")
        key = name_key(code)
        if key in seen:
            raise ValueError(f"las unidades repiten el elemento «{code}» («{seen[key]}»)")
        seen[key] = code
        found[code] = unit
    return MappingProxyType(found)


@dataclass(frozen=True, kw_only=True)
class SourceDeclaration:
    """Lo que declara quien importa una fuente (RF-005-07: nada de esto se supone).

    - ``crs`` y ``vertical``: el CRS horizontal y la referencia vertical de las coordenadas,
      los del catálogo (``CrsRef``, ``VerticalRef``; ``None`` = sin declarar);
    - ``azimuth_ref``: la referencia del azimut (:class:`AzimuthRef`); ``declination_deg``:
      la declinación magnética en grados, positiva al este, solo con azimut magnético (la
      tecleada, con :func:`parse_declination`); ``inclination_convention``: el convenio de
      la inclinación;
    - ``units``: la unidad de cada elemento (código → ``g/t``, ``ppm``, ``ppb``, ``%``…; un
      elemento sin ella, sin declarar); ``value_rules``: las :class:`ValueRules`;
    - ``all_vertical``: los sondeos sin desviaciones ni orientación en boca son verticales;
      ``density_kind``: el tipo de las densidades de los catálogos (ADOPTADO salvo que se
      declare MEDIDO, spec §11); ``date_format``: el de las fechas en texto (``strptime``;
      ``None`` = sin declarar).

    Los siete primeros no tienen valor por defecto: hay que decirlos, aunque sea ``None``."""

    crs: CrsRef | None
    vertical: VerticalRef | None
    azimuth_ref: AzimuthRef | None
    declination_deg: float | None
    inclination_convention: InclinationConvention | None
    units: Mapping[str, str]
    value_rules: ValueRules
    all_vertical: bool = False
    density_kind: ParamKind = ParamKind.ADOPTADO
    date_format: str | None = None

    def __post_init__(self) -> None:
        if self.crs is not None and not isinstance(self.crs, CrsRef):
            raise TypeError(f"el CRS declarado es un CrsRef del catálogo o None, no "
                            f"{self.crs!r}")
        if self.vertical is not None and not isinstance(self.vertical, VerticalRef):
            raise TypeError(f"la referencia vertical declarada es un VerticalRef o None, no "
                            f"{self.vertical!r}")
        what = "SourceDeclaration"
        azimuth = (None if self.azimuth_ref is None
                   else _member(self.azimuth_ref, tuple(AzimuthRef), f"{what}.azimuth_ref"))
        inclination = (None if self.inclination_convention is None
                       else _member(self.inclination_convention, tuple(InclinationConvention),
                                    f"{what}.inclination_convention"))
        declination = _optional_float(self.declination_deg, f"{what}.declination_deg")
        if declination is not None:
            if azimuth is not AzimuthRef.MAGNETIC:
                raise ValueError("la declinación solo se declara con azimut magnético")
            if not -DECLINATION_LIMIT_DEG <= declination <= DECLINATION_LIMIT_DEG:
                raise ValueError(f"la declinación va de −180° a 180°, no {declination}")
        if not isinstance(self.value_rules, ValueRules):
            raise TypeError(f"las reglas de los valores son un ValueRules, no "
                            f"{self.value_rules!r}")
        if not isinstance(self.all_vertical, bool):
            raise TypeError(f"«todos verticales» es sí o no, no {self.all_vertical!r}")
        density = _member(self.density_kind, DENSITY_KINDS, f"{what}.density_kind")
        if self.date_format is not None:
            if not isinstance(self.date_format, str):
                raise TypeError(f"el formato de fecha es un texto de strptime, no "
                                f"{self.date_format!r}")
            if "%" not in self.date_format:
                raise ValueError(f"el formato de fecha es de strptime («%d/%m/%Y»), no "
                                 f"{self.date_format!r}")
        for name, value in (("azimuth_ref", azimuth), ("inclination_convention", inclination),
                            ("declination_deg", declination), ("units", _units(self.units)),
                            ("density_kind", density)):
            object.__setattr__(self, name, value)

    def unit_of(self, element: str) -> str | None:
        """La unidad declarada de ``element`` (sin distinguir mayúsculas), o ``None``."""
        key = name_key(element)
        for code, unit in self.units.items():
            if name_key(code) == key:
                return unit
        return None

    def conventions(self) -> dict[str, Any]:
        """Lo declarado que es contenido de la entrada (cambia lo que significan sus datos):
        las convenciones de ``core.inputs.input_declarations`` (ADR-0024 §3), en JSON y con
        las claves de :data:`CONVENTION_KEYS`. Los CRS no están (van en ``crs_h`` y
        ``crs_v``), ni el separador decimal ni el formato de fecha (son ajustes de lectura:
        un dato mal leído cambia los datos, no su significado)."""
        return {
            "all_vertical": self.all_vertical,
            "azimuth_ref": None if self.azimuth_ref is None else str(self.azimuth_ref),
            "declination_deg": self.declination_deg,
            "density_kind": str(self.density_kind),
            "inclination_convention": (None if self.inclination_convention is None
                                       else str(self.inclination_convention)),
            "negative_is_below_dl": self.value_rules.negative_is_below_dl,
            "sentinels": sorted(self.value_rules.sentinels),
            "units": dict(self.units),
        }


# --- Una importación pendiente ----------------------------------------------------------------


class Rejection(NamedTuple):
    """Una fila rechazada al leer una fuente: su tabla, su número de fila en la fuente (desde
    1), el campo, el valor tal como venía (``None`` si faltaba) y el motivo."""

    table: str
    row: int
    field: str
    value: str | None
    reason: str


def _strings(value: object, what: str) -> tuple[str, ...]:
    if isinstance(value, str | bytes | Mapping) or not isinstance(value, Iterable):
        raise TypeError(f"{what} son una lista de textos, no {value!r}")
    return tuple(_key(item, what) for item in value)


def _label(value: object, what: str) -> str:
    """Un nombre que se guarda en el proyecto: no vacío, sin espacios a los lados y sin rutas
    absolutas (ADR-0006 §5), como ``core.inputs.check_name``."""
    text = _key(value, what)
    if text != text.strip():
        raise ValueError(f"{what} no lleva espacios a los lados: {text!r}")
    if find_absolute_paths(text):
        raise ValueError(f"{what} no puede llevar rutas absolutas (ADR-0006 §5): {text!r}")
    return text


@dataclass(frozen=True)
class FilePrint:
    """La huella de un fichero de una entrada al leerlo: su sha256 (64 cifras hexadecimales en
    minúsculas), su tamaño (bytes) y su fecha de modificación (``st_mtime_ns``). Son los campos
    de ``core.inputs.SourcePrint`` (spec 008), que construye ``bl/`` al registrar la entrada:
    ``core.inputs`` carga ``core.project``, y este modelo lo importan los workers (ARQ-11)."""

    sha256: str
    _: KW_ONLY
    size: int | None = None
    mtime_ns: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.sha256, str) or _SHA256.fullmatch(self.sha256) is None:
            raise ValueError(f"la huella de un fichero es un sha256 en 64 cifras hexadecimales "
                             f"en minúsculas, no {self.sha256!r}")
        if self.size is not None and _int(self.size, "el tamaño de un fichero") < 0:
            raise ValueError(f"el tamaño de un fichero no es negativo: {self.size}")
        if self.mtime_ns is not None:
            _int(self.mtime_ns, "la fecha de un fichero (ns)")


@dataclass(frozen=True, kw_only=True)
class ImportSource:
    """Una entrada de una importación (una por fichero; por hoja de un XLSX; la base de RecMin,
    una): ``name``, el nombre del fichero sin carpetas; ``layer``, la hoja; ``roles``, las
    tablas de la fuente que da (``collar``, ``survey``…; en RecMin, sus tablas); ``digest``,
    su ``ContentDigest`` (spec 008) y ``prints``, la huella de cada fichero
    (:class:`FilePrint`, el principal el primero)."""

    name: str
    roles: tuple[str, ...]
    digest: ContentDigest
    prints: tuple[FilePrint, ...]
    layer: str | None = None

    def __post_init__(self) -> None:
        name = _label(self.name, "el nombre de una entrada")
        if "/" in name or "\\" in name:
            raise ValueError(f"de una entrada se guarda el nombre del fichero sin carpetas, no "
                             f"{name!r}")
        if self.layer is not None:
            _label(self.layer, "la hoja de una entrada")
        roles = _strings(self.roles, "los papeles de una entrada")
        if not roles:
            raise ValueError(f"la entrada «{name}» da al menos una tabla")
        if not isinstance(self.digest, ContentDigest):
            raise TypeError(f"el hash de la entrada «{name}» es un ContentDigest, no "
                            f"{self.digest!r}")
        prints = _entries(self.prints, FilePrint, f"las huellas de «{name}»")
        if not prints:
            raise ValueError(f"la entrada «{name}» lleva la huella de su fichero")
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "prints", prints)


@dataclass(frozen=True, kw_only=True)
class ImportDto:
    """Una importación pendiente (plan §5.3.2): el :class:`DrillholeSet` leído, en el CRS, la
    referencia vertical y los convenios que declara la fuente (``declaration``), sus entradas
    (``sources``, cada una con su hash y sus huellas), los códigos que no están en los
    catálogos del proyecto (``new_codes``, por catálogo de :data:`CATALOG_KINDS`), los
    sondeos que ya existen (``existing_holes``), los recuentos por tabla (``counts``: leídos,
    importados, rechazados…) y las filas rechazadas (:class:`Rejection`)."""

    dset: DrillholeSet
    declaration: SourceDeclaration
    sources: tuple[ImportSource, ...]
    new_codes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    existing_holes: tuple[str, ...] = ()
    counts: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    rejected: tuple[Rejection, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.dset, DrillholeSet):
            raise TypeError(f"el conjunto de una importación es un DrillholeSet, no "
                            f"{self.dset!r}")
        if not isinstance(self.declaration, SourceDeclaration):
            raise TypeError(f"la declaración es un SourceDeclaration, no {self.declaration!r}")
        declared = self.declaration
        if declared.crs is None or declared.crs.epsg != self.dset.crs.epsg:
            raise ValueError(f"el conjunto está en EPSG:{self.dset.crs.epsg} y no en el CRS "
                             f"declarado ({declared.crs!r})")
        if declared.vertical != self.dset.vertical:
            raise ValueError(f"el conjunto está en «{self.dset.vertical.name}» y no en la "
                             f"referencia vertical declarada ({declared.vertical!r})")
        sources = _entries(self.sources, ImportSource, "las entradas de una importación")
        if not sources:
            raise ValueError("una importación tiene al menos una entrada")
        names = [(name_key(s.name), None if s.layer is None else name_key(s.layer))
                 for s in sources]
        if len(set(names)) != len(names):
            raise ValueError("una importación no repite una entrada (fichero y hoja)")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "new_codes", self._new_codes())
        object.__setattr__(self, "existing_holes",
                           _strings(self.existing_holes, "los sondeos que ya existen"))
        object.__setattr__(self, "counts", self._counts())
        object.__setattr__(self, "rejected", self._rejected())

    def _new_codes(self) -> Mapping[str, tuple[str, ...]]:
        if not isinstance(self.new_codes, Mapping):
            raise TypeError(f"los códigos nuevos son catálogo → códigos, no {self.new_codes!r}")
        found = {}
        for kind, codes in self.new_codes.items():
            if kind not in CATALOG_KINDS:
                raise ValueError(f"catálogo desconocido {kind!r}: es uno de "
                                 f"{', '.join(CATALOG_KINDS)}")
            found[kind] = _strings(codes, f"los códigos nuevos de «{kind}»")
        return MappingProxyType(found)

    def _counts(self) -> Mapping[str, Mapping[str, int]]:
        if not isinstance(self.counts, Mapping):
            raise TypeError(f"los recuentos son tabla → {{qué: número}}, no {self.counts!r}")
        found = {}
        for table, counts in self.counts.items():
            _key(table, "la tabla de un recuento")
            if not isinstance(counts, Mapping):
                raise TypeError(f"los recuentos de «{table}» son {{qué: número}}, no "
                                f"{counts!r}")
            numbers = {}
            for what, number in counts.items():
                _key(what, f"un recuento de «{table}»")
                if _int(number, f"el recuento «{what}» de «{table}»") < 0:
                    raise ValueError(f"el recuento «{what}» de «{table}» no es negativo: "
                                     f"{number}")
                numbers[what] = int(number)
            found[table] = MappingProxyType(numbers)
        return MappingProxyType(found)

    def _rejected(self) -> tuple[Rejection, ...]:
        if isinstance(self.rejected, str | bytes) or not isinstance(self.rejected, Iterable):
            raise TypeError(f"los rechazos son una lista, no {self.rejected!r}")
        found = []
        for item in self.rejected:
            rejection = Rejection(*item)
            _key(rejection.table, "la tabla de un rechazo")
            if _int(rejection.row, "la fila de un rechazo") < 1:
                raise ValueError(f"la fila de un rechazo va desde 1, no {rejection.row}")
            _key(rejection.field, "el campo de un rechazo")
            _text(rejection.value, "el valor de un rechazo")
            _key(rejection.reason, "el motivo de un rechazo")
            found.append(rejection)
        return tuple(found)
