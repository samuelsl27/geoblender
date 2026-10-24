# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogo de unidades de Geoblender (spec 008; RF-008-03, RF-008-30; plan 008 §5.3.1 y
D11).

Cada parámetro y cada cifra lleva una unidad de este catálogo. Se guarda su **código**
ASCII (``m2``, ``t/m3``, ``-``), estable y sin problemas de codificación, y se muestra su
**símbolo en español** (m², t/m³, —). Las unidades de una misma magnitud se convierten de
forma exacta: el factor de cada una es un :class:`~fractions.Fraction` y el resultado se
redondea una sola vez a float64, así que t ↔ kt, m² ↔ ha o B ↔ MB dan el número decimal
esperado. MB = 10⁶ B (los tamaños de la spec son decimales).

- ``%``, ``-`` (adimensional), ``g/t``, ``ppm`` y ``ppb`` son la misma magnitud, una
  proporción: «35 %» en un parámetro declarado en fracción es 0,35, 1 % = 10 000 g/t y
  1 g/t = 1 ppm = 1000 ppb (las leyes de los sondeos; spec 005, D-18 del plan 005).
- ``deg/30m`` («°/30 m»), el cambio de dirección entre estaciones de un sondeo (DH-W04 de
  la spec 005), es una magnitud propia: no se convierte a grados.
- Un **año** (``yr``) no se convierte a días ni a segundos: cuántos días tiene el año de una
  explotación lo decide su calendario de trabajo, no el catálogo. Por eso ``t/yr`` y
  ``m3/yr`` son también magnitudes propias.
- Las relaciones estéril/útil de la cubicación (spec 011; RF-011-18) son dos magnitudes
  propias: ``m3/m3`` («m³/m³», una relación entre volúmenes in situ) y ``t/t`` («t/t», entre
  masas). Ninguna se convierte a la otra ni a ``%`` o ``-``: 2,5 m³/m³ no son 2,5 t/t ni un
  250 % (una ley o un porcentaje).
- Entre magnitudes distintas no hay conversión, y NaN o infinito nunca son un valor.

Los errores son :class:`UnitError` (un ``ValueError``) con un ``code`` estable en inglés
para quien los traduce en un mensaje con su objeto y su campo (``core.params``):
``core.unit_unknown``, ``core.unit_not_convertible``, ``core.quantity_missing``,
``core.quantity_not_number`` y ``core.quantity_not_finite``.
"""

from __future__ import annotations

import math
import numbers
import re
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType

from .errors import ValidationError
from .numbers import parse_decimal

DIMENSIONLESS = "-"
"""El código de lo adimensional (su símbolo es «—»)."""

_DIMENSION_NAMES_ES: Mapping[str, str] = MappingProxyType({
    "length": "una longitud",
    "area": "una superficie",
    "volume": "un volumen",
    "mass": "una masa",
    "density": "una densidad",
    "ratio": "una proporción",
    "angle": "un ángulo",
    "angle_per_length": "un cambio de dirección por longitud",
    "time": "un tiempo",
    "year": "años (sin equivalencia fija en días)",
    "mass_per_year": "una masa por año",
    "volume_per_year": "un volumen por año",
    "data": "un tamaño de datos",
    "volume_ratio": "una relación entre volúmenes",
    "mass_ratio": "una relación entre masas",
})
"""Lo que mide cada magnitud, para los mensajes («la t mide una masa»)."""


@dataclass(frozen=True, slots=True)
class Unit:
    """Una unidad del catálogo: ``code`` (ASCII, lo que se guarda), ``symbol_es`` (lo que se
    muestra), ``dimension`` (la magnitud; solo se convierte dentro de ella) y ``factor``
    (exacto, respecto a la unidad de referencia de su magnitud: ``kt`` = 1000 ``t``)."""

    code: str
    symbol_es: str
    dimension: str
    factor: Fraction


class UnitError(ValueError):
    """Una unidad o una cantidad que no vale. ``code`` es estable (``core.unit_*`` o
    ``core.quantity_*``); ``from_unit`` y ``to_unit``, las unidades de una conversión
    rechazada; ``text``, el texto tecleado."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        from_unit: str | None = None,
        to_unit: str | None = None,
        text: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.from_unit = from_unit
        self.to_unit = to_unit
        self.text = text


def _unit(code: str, symbol_es: str, dimension: str, factor: int | Fraction = 1) -> Unit:
    return Unit(code, symbol_es, dimension, Fraction(factor))


_CATALOG: tuple[Unit, ...] = (
    _unit("m", "m", "length"),
    _unit("km", "km", "length", 1000),
    _unit("m2", "m²", "area"),
    _unit("ha", "ha", "area", 10_000),
    _unit("km2", "km²", "area", 1_000_000),
    _unit("m3", "m³", "volume"),
    _unit("hm3", "hm³", "volume", 1_000_000),
    _unit("kg", "kg", "mass", Fraction(1, 1000)),
    _unit("t", "t", "mass"),
    _unit("kt", "kt", "mass", 1000),
    _unit("Mt", "Mt", "mass", 1_000_000),
    _unit("t/m3", "t/m³", "density"),
    _unit("kg/m3", "kg/m³", "density", Fraction(1, 1000)),
    _unit(DIMENSIONLESS, "—", "ratio"),
    _unit("%", "%", "ratio", Fraction(1, 100)),
    _unit("g/t", "g/t", "ratio", Fraction(1, 1_000_000)),
    _unit("ppm", "ppm", "ratio", Fraction(1, 1_000_000)),
    _unit("ppb", "ppb", "ratio", Fraction(1, 1_000_000_000)),
    _unit("deg", "°", "angle"),
    _unit("deg/30m", "°/30 m", "angle_per_length"),
    _unit("s", "s", "time"),
    _unit("min", "min", "time", 60),
    _unit("h", "h", "time", 3600),
    _unit("d", "d", "time", 86_400),
    _unit("yr", "año", "year"),
    _unit("t/yr", "t/año", "mass_per_year"),
    _unit("m3/yr", "m³/año", "volume_per_year"),
    _unit("B", "B", "data"),
    _unit("MB", "MB", "data", 10**6),
    _unit("GB", "GB", "data", 10**9),
    _unit("m3/m3", "m³/m³", "volume_ratio"),
    _unit("t/t", "t/t", "mass_ratio"),
)

UNITS: Mapping[str, Unit] = MappingProxyType({unit.code: unit for unit in _CATALOG})
"""El catálogo, por código (solo lectura)."""

# Lo que se acepta como unidad al teclear una cantidad: el código, el símbolo y dos formas
# habituales del teclado español («º», el ordinal, por «°»; «años»).
_EXTRA_ALIASES = {"º": "deg", "º/30 m": "deg/30m", "años": "yr"}


def _build_aliases() -> Mapping[str, str]:
    aliases: dict[str, str] = {}
    pairs = [(unit.code, unit.code) for unit in _CATALOG]
    pairs += [(unit.symbol_es, unit.code) for unit in _CATALOG]
    pairs += list(_EXTRA_ALIASES.items())
    for alias, code in pairs:
        if aliases.setdefault(alias, code) != code:
            raise ValueError(f"«{alias}» nombra dos unidades del catálogo")
    return MappingProxyType(aliases)


_ALIASES = _build_aliases()

# Una cantidad tecleada: el número (cifras, separadores y espacios de miles, con un signo
# delante) y lo que sigue, que es la unidad.
_QUANTITY = re.compile(
    r"(?P<number>[+-]?[0-9.,\u0020\u00a0\u2009\u202f]*)(?P<unit>.*)", re.DOTALL
)
_EXAMPLE = "«35 %» o «2,65 t/m³»"


def _check_dimensions() -> None:
    for unit in _CATALOG:
        if unit.dimension not in _DIMENSION_NAMES_ES or not unit.code.isascii():
            raise ValueError(f"la unidad «{unit.code}» está mal declarada")


_check_dimensions()


def get_unit(code: str) -> Unit:
    """La unidad de código ``code``; :class:`UnitError` (``core.unit_unknown``) si no está
    en el catálogo."""
    try:
        return UNITS[code]
    except (KeyError, TypeError):
        raise UnitError(
            "core.unit_unknown",
            f"la unidad «{code}» no está en el catálogo de unidades de Geoblender",
            from_unit=code if isinstance(code, str) else None,
        ) from None


def symbol(code: str) -> str:
    """El símbolo en español de la unidad ``code`` (``"m3"`` → «m³», ``"-"`` → «—»)."""
    return get_unit(code).symbol_es


def parse_quantity(text: str, *, decimal: str = ",") -> tuple[float, str | None]:
    """El número y la unidad de un texto tecleado: «35 %» → ``(35.0, "%")``,
    «1,23» → ``(1.23, None)``.

    El número, en float64, con las reglas de :func:`core.numbers.parse_decimal`: coma o
    punto decimal (con ``decimal="."``, solo el punto: en la interfaz en inglés la coma es
    de miles) y espacios de miles. La unidad es opcional y puede ir pegada; se escribe con
    su código o su símbolo, y se devuelve su código. NaN, infinito, un texto vacío o una
    unidad fuera del catálogo: :class:`UnitError`.
    """
    if not isinstance(text, str):
        raise TypeError(f"la cantidad debe ser un texto, no {type(text).__name__}")
    if decimal not in (",", "."):
        raise ValueError(f"separador decimal «{decimal}» no admitido: «,» o «.»")
    stripped = text.strip()
    if not stripped:
        raise UnitError(
            "core.quantity_missing",
            f"falta el número; escríbalo con su unidad, p. ej. {_EXAMPLE}",
            text=text,
        )
    match = _QUANTITY.fullmatch(stripped)
    assert match is not None  # la expresión admite cualquier texto
    number, unit_text = match["number"].strip(), match["unit"].strip()
    if decimal == "." and "," in number:
        raise UnitError(
            "core.quantity_not_number",
            f"«{text}» no es un número: use el punto como separador decimal",
            text=text,
        )
    value = _parse_number(number, text)
    if not unit_text:
        return value, None
    code = _ALIASES.get(unit_text)
    if code is None:
        raise UnitError(
            "core.unit_unknown",
            f"la unidad «{unit_text}» de «{text}» no está en el catálogo de unidades de "
            "Geoblender",
            from_unit=unit_text,
            text=text,
        )
    return value, code


def _parse_number(number: str, text: str) -> float:
    if not number or number in ("+", "-"):
        raise UnitError(
            "core.quantity_not_number",
            f"«{text}» no es un número: escriba cifras con coma o punto decimal y, si quiere, "
            f"la unidad (p. ej. {_EXAMPLE})",
            text=text,
        )
    try:
        return parse_decimal(number, obj="Cantidad", field="valor")
    except ValidationError:
        try:  # bien escrito, pero no cabe en un float64 («1» y 400 ceros)
            finite = not math.isinf(float("".join(number.split()).replace(",", ".")))
        except ValueError:
            finite = True
        raise UnitError(
            "core.quantity_not_number" if finite else "core.quantity_not_finite",
            f"«{text}» no es un número{'' if finite else ' finito'}: escriba cifras con una "
            f"sola coma o un solo punto decimal (no los dos) y, si quiere, la unidad (p. ej. "
            f"{_EXAMPLE})",
            text=text,
        ) from None


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """``value`` en ``from_unit``, expresado en ``to_unit`` (float64, redondeado una sola
    vez desde la conversión exacta). :class:`UnitError` si alguna unidad no está en el
    catálogo, si son de magnitudes distintas (nombra las dos) o si el valor es NaN o
    infinito; :class:`TypeError` si no es un número (un sí/no tampoco lo es)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"el valor a convertir debe ser un número, no {type(value).__name__}")
    source, target = get_unit(from_unit), get_unit(to_unit)
    if source.dimension != target.dimension:
        a, b = source.symbol_es, target.symbol_es
        raise UnitError(
            "core.unit_not_convertible",
            f"no se puede convertir de «{a}» a «{b}»: «{a}» mide "
            f"{_DIMENSION_NAMES_ES[source.dimension]} y «{b}», "
            f"{_DIMENSION_NAMES_ES[target.dimension]}",
            from_unit=from_unit,
            to_unit=to_unit,
        )
    ratio = source.factor / target.factor
    if isinstance(value, numbers.Integral):
        exact = Fraction(int(value))
    else:
        number = float(value)
        if not math.isfinite(number):
            raise _not_finite(
                f"el valor {number} no es un número finito: no se convierte de "
                f"«{source.symbol_es}» a «{target.symbol_es}»",
                source,
                target,
            )
        if ratio == 1:
            return number
        exact = Fraction(number)
    try:
        return float(exact * ratio)
    except OverflowError:
        raise _not_finite(
            f"el valor {value} {source.symbol_es} no cabe en un número de coma flotante "
            f"(float64) al pasarlo a «{target.symbol_es}»",
            source,
            target,
        ) from None


def _not_finite(message: str, source: Unit, target: Unit) -> UnitError:
    return UnitError(
        "core.quantity_not_finite", message, from_unit=source.code, to_unit=target.code
    )
