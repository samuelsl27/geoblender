# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de topografía (spec 006; plan 006 §5.2.5; ADR-0013; formato-proyecto.md §3.3).

Cada valor que cambia un resultado de ``gis`` (tolerancias, fracción mínima, umbrales) es un
parámetro con **clave, tipo de valor, unidad, rango, valor por defecto, tipo y procedencia**:
el código lo lee de aquí con su clave y nunca lo escribe a mano (principio 2). Todos son
ADOPTADO de origen ``algorithm`` (``gb_parameter.source_kind``): los fija el método, no una
medida ni una norma.

- :class:`ParamDef`: la definición; :meth:`ParamDef.check` comprueba un valor (tipo y
  rango) y lo devuelve normalizado, o lanza ``gis.messages.GisError``.
- :data:`DEFINITIONS`, las de la tabla del plan §5.2.5, y :data:`PARAMS`, por clave
  (:func:`index_definitions`, que no admite claves repetidas).
- :func:`param` y :func:`default`: la definición y el valor por defecto de una clave.

Tipos de valor, los de ``gb_parameter.value_type``: ``float``, ``int`` y ``json`` (aquí,
siempre una lista de ``length`` números en orden creciente, cada uno dentro del rango). La
unidad ``-`` es la de lo adimensional. Los rangos los decide esta definición (el plan solo
fija los valores por defecto), salvo el de ``gis.tin.blender_cdt_max_s``: nunca más de 2 s,
el final de la excepción del principio 9 (plan §9, D-12).

Hasta que R-07 dé ``core.params`` (``ParamDef``, ``ParamKind``, ``ParameterStore``), la
definición vive aquí con los mismos campos que ``gb_parameter``; con R-07 los valores del
proyecto y su historial irán a la BD y estas definiciones darán el valor inicial.
"""

from __future__ import annotations

import math
import numbers
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType

from .messages import GisError, format_value

ADOPTED = "ADOPTADO"
SOURCE_ALGORITHM = "algorithm"
KINDS = ("MEDIDO", "CALCULADO", "ADOPTADO", "HIPÓTESIS")
"""Los tipos de una cifra o parámetro (``gb_parameter.kind``; principio 2)."""
SOURCE_KINDS = ("document", "standard", "person", "operation", "algorithm")
"""Los orígenes de un parámetro (``gb_parameter.source_kind``)."""
VALUE_TYPES = ("float", "int", "json")
DIMENSIONLESS = "-"

type ParamValue = float | int | tuple[float, ...]

_KEY = re.compile(r"^gis\.[a-z]+\.[a-z][a-z0-9_]*$")
_OBJ = "Parámetro"


@dataclass(frozen=True, slots=True)
class ParamDef:
    """Definición de un parámetro de ``gis``.

    ``key`` (``gis.<grupo>.<nombre>``), ``value_type`` (``float``, ``int`` o ``json``),
    ``unit`` (``m``, ``s``, ``%`` o ``-``), ``default``, rango de ``minimum`` a
    ``maximum`` (incluidos, salvo ``minimum`` con ``min_exclusive``), ``requirements`` (los
    RF que lo usan), ``source`` (de dónde sale el valor por defecto), ``length`` (los
    elementos de un ``json``), ``kind`` y ``source_kind``. Una definición incoherente (un
    valor por defecto fuera de rango, una clave mal formada) es un error del programa:
    :class:`ValueError`.
    """

    key: str
    value_type: str
    unit: str
    default: ParamValue
    minimum: float
    maximum: float
    requirements: tuple[str, ...]
    source: str
    min_exclusive: bool = False
    length: int | None = None
    kind: str = ADOPTED
    source_kind: str = SOURCE_ALGORITHM

    def __post_init__(self) -> None:
        problem = self._problem()
        if problem is None:
            try:
                checked = self.check(self.default)
            except GisError as exc:
                problem = f"su valor por defecto no es válido ({exc})"
            else:
                if checked != self.default or type(checked) is not type(self.default):
                    problem = f"su valor por defecto no está normalizado ({checked!r})"
        if problem is not None:
            raise ValueError(f"definición del parámetro «{self.key}»: {problem}")

    def _problem(self) -> str | None:
        """Lo que hace incoherente la definición, sin mirar el valor por defecto."""
        if not _KEY.match(self.key):
            return "la clave no tiene la forma gis.<grupo>.<nombre>"
        if self.value_type not in VALUE_TYPES:
            return f"tipo de valor {self.value_type!r}; válidos: {', '.join(VALUE_TYPES)}"
        if (self.value_type == "json") != (self.length is not None and self.length >= 1):
            return "solo un parámetro json tiene longitud, y es ≥ 1"
        if self.kind not in KINDS or self.source_kind not in SOURCE_KINDS:
            return f"tipo {self.kind!r} u origen {self.source_kind!r} desconocido"
        if not self.unit or not self.source.strip() or not self.requirements:
            return "le falta la unidad, la procedencia o los requisitos"
        if not self.minimum <= self.maximum:
            return f"rango vacío ({self.minimum!r} > {self.maximum!r})"
        return None

    def check(self, value: object) -> ParamValue:
        """``value`` normalizado (``float``, ``int`` o tupla de ``float``) si es del tipo
        y está en el rango; si no, ``GisError`` con la clave y el valor
        (``gis.param_not_number``, ``gis.param_not_integer``, ``gis.param_not_list`` o
        ``gis.param_out_of_range``)."""
        if self.value_type == "json":
            return self._check_list(value)
        if not _is_finite_real(value):
            integer_wanted = self.value_type == "int"
            raise self._error(
                "gis.param_not_integer" if integer_wanted else "gis.param_not_number", value
            )
        number = float(value)  # type: ignore[arg-type]
        if self.value_type == "float":
            self._check_range(number, number)
            return number
        if not number.is_integer():
            raise self._error("gis.param_not_integer", value)
        integer = int(value)  # type: ignore[call-overload]
        self._check_range(integer, integer)
        return integer

    def _check_list(self, value: object) -> tuple[float, ...]:
        if (
            isinstance(value, str | bytes)
            or not isinstance(value, Sequence)
            or len(value) != self.length
            or not all(_is_finite_real(item) for item in value)
        ):
            raise self._error("gis.param_not_list", value, length=self.length)
        items = tuple(float(item) for item in value)
        if any(second <= first for first, second in pairwise(items)):
            raise self._error("gis.param_not_list", value, length=self.length)
        shown = "[" + "; ".join(format_value(item) for item in items) + "]"
        for item in items:
            self._check_range(item, shown)
        return items

    def _check_range(self, number: float, shown: object) -> None:
        above_min = number > self.minimum if self.min_exclusive else number >= self.minimum
        if not (above_min and number <= self.maximum):
            raise self._error("gis.param_out_of_range", shown, range=self.range_text())

    def range_text(self, language: str = "es") -> str:
        """El rango como se lee: ``[0; 2] s`` en español (``[0, 2] s`` en inglés), con
        paréntesis en el extremo excluido (``(0; 1]``) y sin unidad si es adimensional."""
        separator = "; " if language == "es" else ", "
        opening = "(" if self.min_exclusive else "["
        low = format_value(float(self.minimum), language)
        high = format_value(float(self.maximum), language)
        text = f"{opening}{low}{separator}{high}]"
        return text if self.unit == DIMENSIONLESS else f"{text} {self.unit}"

    def _error(self, code: str, value: object, **values: object) -> GisError:
        return GisError(code, obj=_OBJ, field=self.key, value=value, key=self.key, **values)


def _is_finite_real(value: object) -> bool:
    """Verdadero si ``value`` es un número real finito que cabe en un float64 (no un
    booleano)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # un entero que no cabe en un float64
        return False


def index_definitions(definitions: Iterable[ParamDef]) -> Mapping[str, ParamDef]:
    """Las definiciones por clave (solo lectura); :class:`ValueError` si una clave se
    repite (un duplicado no se pierde en silencio)."""
    index: dict[str, ParamDef] = {}
    for definition in definitions:
        if definition.key in index:
            raise ValueError(f"la clave de parámetro «{definition.key}» está repetida")
        index[definition.key] = definition
    return MappingProxyType(index)


_D4 = "Spec 006, D-4 (DP-43): sin dato salvo cobertura total"
_D5 = "Spec 006, D-5 (DP-44): 1 mm en planta y 0,01 m en cota"
_A12 = "Plan 006 §5.2.5 y A12 (TIN desde curvas)"
_CONTOURS = "Spec 006 §11: curvas del terreno (R-61 fija las de los diseños)"

DEFINITIONS: tuple[ParamDef, ...] = (
    ParamDef("gis.resample.min_valid_fraction", "float", DIMENSIONLESS, 1.0, 0.0, 1.0,
             ("RF-006-11",), _D4, min_exclusive=True),
    ParamDef("gis.reproject.supersample", "int", DIMENSIONLESS, 4, 1, 16,
             ("RF-006-05",), "Plan 006 §6, D7: submuestreo de 4 × 4 por celda"),
    ParamDef("gis.points.dup_xy_tol_m", "float", "m", 0.001, 0.0, 1.0,
             ("RF-006-14",), _D5, min_exclusive=True),
    ParamDef("gis.points.dup_z_tol_m", "float", "m", 0.01, 0.0, 1.0,
             ("RF-006-14",), _D5),
    ParamDef("gis.tin.contour_densify_m", "float", "m", 5.0, 0.0, 100.0,
             ("RF-006-16",), _A12, min_exclusive=True),
    ParamDef("gis.tin.flat_max_passes", "int", DIMENSIONLESS, 3, 0, 10,
             ("RF-006-16",), _A12),
    ParamDef("gis.tin.max_flat_pct", "float", "%", 1.0, 0.0, 100.0,
             ("RF-006-16",), "Spec 006, RF-006-16 (D-6)"),
    ParamDef("gis.tin.blender_cdt_max_s", "float", "s", 2.0, 0.0, 2.0,
             ("RF-006-13", "RF-006-28"),
             "Plan 006 §9, D-12 (DP-54): excepción del principio 9, hasta 2 s"),
    ParamDef("gis.contours.interval_m", "float", "m", 1.0, 0.0, 1000.0,
             ("RF-006-18",), _CONTOURS, min_exclusive=True),
    ParamDef("gis.contours.index_every_m", "float", "m", 5.0, 0.0, 10000.0,
             ("RF-006-18",), _CONTOURS, min_exclusive=True),
    ParamDef("gis.contours.index_offset_m", "float", "m", 0.0, -100.0, 100.0,
             ("RF-006-18",), _CONTOURS),
    ParamDef("gis.contours.simplify_m", "float", "m", 0.0, 0.0, 100.0,
             ("RF-006-18",), _CONTOURS),
    ParamDef("gis.contours.min_length_m", "float", "m", 0.0, 0.0, 10000.0,
             ("RF-006-18",), _CONTOURS),
    ParamDef("gis.vertical.ellipsoidal_band_m", "json", "m", (40.0, 60.0), 0.0, 200.0,
             ("RF-006-06",), "Spec 006, D-8 (DP-46): península y Baleares", length=2),
    ParamDef("gis.validate.z_range_m", "json", "m", (-500.0, 5000.0), -11000.0, 9000.0,
             ("RF-006-23",), "Spec 006 §11: rango plausible de cotas", length=2),
    ParamDef("gis.import.max_cells", "int", DIMENSIONLESS, 100_000_000, 1, 100_000_000,
             ("RF-006-09",), "Spec 006 §8 y §11 (memoria: RNF-006-08)"),
    ParamDef("gis.view.lod_steps_m", "json", "m", (2.0, 5.0), 0.5, 100.0,
             ("RF-006-22",), "Spec 006, RF-006-22: versiones de 2 y 5 m", length=2),
)
"""Los parámetros de la tabla del plan 006 §5.2.5, en su orden."""

PARAMS: Mapping[str, ParamDef] = index_definitions(DEFINITIONS)
"""Las definiciones por clave (solo lectura)."""


def param(key: str) -> ParamDef:
    """La definición de ``key``; :class:`KeyError` si no es un parámetro de ``gis`` (un
    error del programa)."""
    try:
        return PARAMS[key]
    except KeyError:
        raise KeyError(f"«{key}» no es un parámetro de gis (gis/params.py)") from None


def default(key: str) -> ParamValue:
    """El valor por defecto de ``key`` (ADOPTADO)."""
    return param(key).default
