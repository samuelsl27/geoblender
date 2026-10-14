# SPDX-License-Identifier: GPL-3.0-or-later
"""Valores de las fuentes de sondeos: columnas de texto a float64 con sus marcas, y los
Single de RecMin por su decimal más corto (spec 005, T05; RF-005-02, RF-005-09; plan 005
§5.3.2 y §5.4).

**Una columna de texto** (:func:`parse_column`, con las :class:`ValueRules` de la fuente,
las del modelo) da, por cada texto, su valor en float64, su marca (:class:`DetectionFlag`,
en int8 como la columna ``detection_flag`` de ``AssayColumns``), su texto original y, si no
es un número, su rechazo con el motivo (RF-005-09):

- **vacío** (o solo espacios) o **centinela** declarado (sin distinguir mayúsculas; uno
  numérico, como «−99», también escrito «−99,0»): ausente (NaN, marca ``OK``);
- «**<x**»: x con ``BELOW_DL``; «**>x**»: x con ``ABOVE_UL``;
- **negativo**: tal cual (lo avisa la validación, DH-W08), salvo que se declare «−x = <x»
  (``negative_is_below_dl``): entonces, x con ``BELOW_DL``. El centinela se mira antes;
- **no numérico**: rechazado (NaN y su fila en ``rejected_rows``, con su motivo). Con el
  separador decimal que no es el declarado («0.5» con coma declarada, o «1.234,5»), también:
  no se adivina (spec §8, «coma decimal mezclada con punto»).

Un número es un signo opcional, cifras con un separador decimal como mucho (el declarado:
«,5» y «5,» valen) y, si acaso, un exponente («1,5E-03»). Se admiten los espacios de miles
(normal, fino y sin ruptura, como ``core.numbers``) y el signo menos tipográfico («−»); no,
«nan», «inf», «1_000» ni un número que no cabe en float64. El texto original se conserva
siempre tal como venía (``reported``; ``None`` si estaba vacío).

**RF-005-02, el decimal de la fuente.** El valor es ``float`` del decimal: un solo redondeo
(correcto) a float64, idéntico al de la fuente; −0 se guarda como 0.

**Vía rápida** (plan §5.4). Los textos que son un número corriente (sin espacios de miles,
exponente ni marca) y los vacíos se reconocen y convierten de una vez para toda la columna
(``map`` sobre una expresión regular compilada y la conversión de numpy, sin un bucle de
Python por valor); los centinelas numéricos y «−x = <x» se aplican con numpy. Solo los demás
(«<x», «>x», centinelas de texto, rechazos…) pasan por el analizador de especiales.

**Single de RecMin** (RF-005-02; :func:`from_single`, :func:`from_single_column`):
``float(numpy.format_float_positional(numpy.float32(v), unique=True, trim='-'))``, su decimal
más corto: ``float32(0.1)`` → 0,1 y no 0,10000000149011612. No ``repr``: en numpy 2 incluye
el tipo.

Nada modifica sus entradas. Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from operator import methodcaller, not_
from types import MappingProxyType
from typing import Any

import numpy as np

from .model import AssayColumns, DetectionFlag, ValueRules

__all__ = [
    "FLAGS",
    "FLAG_CODES",
    "DetectionFlag",
    "ParsedColumn",
    "ValueRules",
    "from_single",
    "from_single_column",
    "parse_column",
]

FLAGS: tuple[DetectionFlag, ...] = AssayColumns.code_values("detection_flag")
"""Las marcas en el orden de sus códigos int8 (los de la columna ``detection_flag``)."""
FLAG_CODES: Mapping[DetectionFlag, int] = MappingProxyType(
    {flag: code for code, flag in enumerate(FLAGS)})
"""El código int8 de cada marca."""

_OK = FLAG_CODES[DetectionFlag.OK]
_BELOW = FLAG_CODES[DetectionFlag.BELOW_DL]
_ABOVE = FLAG_CODES[DetectionFlag.ABOVE_UL]
_MARKS = {"<": DetectionFlag.BELOW_DL, ">": DetectionFlag.ABOVE_UL}

# Los espacios de miles que se quitan (normal, sin ruptura, fino y fino sin ruptura, como
# core.numbers) y el signo menos tipográfico, que pasa a «-».
_COMPACT = str.maketrans({" ": None, " ": None, " ": None, " ": None,
                          "−": "-"})
# Con coma decimal, coma y punto se intercambian: el número corriente queda con punto (lo
# que lee float) y un punto de la fuente, con coma, que no casa con el patrón.
_SWAP = str.maketrans({",": ".", ".": ","})


def _patterns(mark: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """El número corriente (vía rápida, con punto) y el número completo con el separador
    ``mark`` y exponente opcional (analizador de especiales). Solo cifras ASCII."""
    plain = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
    sep = re.escape(mark)
    number = rf"[+-]?(?:\d+(?:{sep}\d*)?|{sep}\d+)(?:[eE][+-]?\d+)?"
    return re.compile(plain, re.ASCII), re.compile(number, re.ASCII)


_PLAIN = _patterns(".")[0]
_NUMBER = {mark: _patterns(mark)[1] for mark in (",", ".")}
_OTHER = {",": ".", ".": ","}


def _not_number() -> str:
    return "no es un número"


def _wrong_mark(mark: str) -> str:
    other = _OTHER[mark]
    return (f"lleva «{other}» y el separador decimal declarado es «{mark}» (sin separador "
            f"de miles)")


@dataclass(frozen=True, eq=False)
class ParsedColumn:
    """Una columna de texto leída (RF-005-09): ``values`` (float64; NaN = ausente o
    rechazado), ``flags`` (int8, :data:`FLAG_CODES`), ``reported`` (el texto original, o
    ``None`` si estaba vacío), ``rejected_rows`` (int64, las posiciones de los textos que no
    son un número, en orden) y ``rejected_reasons`` (el motivo de cada una, en español)."""

    values: np.ndarray
    flags: np.ndarray
    reported: np.ndarray
    rejected_rows: np.ndarray
    rejected_reasons: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.values)


def _texts(texts: object) -> list[Any]:
    """Los textos de la columna como lista (``None`` = vacío); un error del programa si no son
    textos."""
    if isinstance(texts, str | bytes) or not isinstance(texts, Sequence | np.ndarray):
        raise TypeError(f"una columna es una secuencia de textos, no {texts!r}")
    found = list(texts)
    for kind in set(map(type, found)):
        if kind is not type(None) and not issubclass(kind, str):
            raise TypeError(f"los valores de una columna son textos (o None), no {kind.__name__}")
    return found


def _sentinels(rules: ValueRules) -> tuple[frozenset[str], np.ndarray]:
    """Las formas de los centinelas: su texto (sin espacios ni mayúsculas) y, los que son
    números con el separador de la fuente, su valor."""
    keys = frozenset(_key(sentinel) for sentinel in rules.sentinels)
    numbers = [_number(_compact(sentinel), rules.decimal_mark) for sentinel in rules.sentinels]
    return keys, np.array(sorted(n for n in numbers if n is not None), dtype=np.float64)


def _compact(text: str) -> str:
    return text.strip().translate(_COMPACT)


def _key(text: str) -> str:
    return _compact(text).casefold()


def _number(text: str, mark: str) -> float | None:
    """El float64 del número ``text`` (separador ``mark``), o ``None`` si no lo es."""
    if not _NUMBER[mark].fullmatch(text):
        return None
    value = float(text.replace(mark, ".") if mark != "." else text)
    return value + 0.0 if math.isfinite(value) else None


def _special(text: str, rules: ValueRules, keys: frozenset[str],
             numbers: np.ndarray) -> tuple[float, DetectionFlag, str | None]:
    """Un texto que no es un número corriente (ya sin espacios a los lados): su valor, su
    marca y el motivo si se rechaza."""
    compact = text.translate(_COMPACT)
    if compact.casefold() in keys:
        return math.nan, DetectionFlag.OK, None
    flag = _MARKS.get(compact[:1], DetectionFlag.OK)
    body = compact if flag is DetectionFlag.OK else compact[1:]
    mark = rules.decimal_mark
    value = _number(body, mark)
    if value is None:
        wrong = _OTHER[mark] in body
        return math.nan, DetectionFlag.OK, _wrong_mark(mark) if wrong else _not_number()
    if flag is DetectionFlag.OK:
        if value in numbers:
            return math.nan, flag, None
        if rules.negative_is_below_dl and value < 0:
            return -value, DetectionFlag.BELOW_DL, None
    return value, flag, None


def parse_column(texts: Sequence[str | None], rules: ValueRules) -> ParsedColumn:
    """Los valores de una columna de texto de una fuente con sus reglas (véase el módulo;
    RF-005-02, RF-005-09). ``texts`` no cambia."""
    if not isinstance(rules, ValueRules):
        raise TypeError(f"las reglas de los valores son ValueRules, no {rules!r}")
    raw = _texts(texts)
    count = len(raw)
    reported = np.empty(count, dtype=object)
    reported[:] = raw
    filled = reported.copy()
    filled[np.equal(filled, None)] = ""
    stripped = list(map(str.strip, filled))
    empty = np.fromiter(map(not_, stripped), dtype=bool, count=count)
    reported[empty] = None
    swapped = stripped if rules.decimal_mark == "." else list(
        map(methodcaller("translate", _SWAP), stripped))
    plain = np.fromiter(map(bool, map(_PLAIN.fullmatch, swapped)), dtype=bool, count=count)

    values = np.full(count, math.nan)
    flags = np.full(count, _OK, dtype=np.int8)
    rejected: dict[int, str] = {}
    keys, numbers = _sentinels(rules)

    fast = np.flatnonzero(plain)
    if fast.size:
        chosen = np.empty(count, dtype=object)
        chosen[:] = swapped
        found = chosen[fast].astype(np.float64) + 0.0
        infinite = ~np.isfinite(found)
        if infinite.any():  # cifras de más: no cabe en float64
            rejected.update(dict.fromkeys(fast[infinite].tolist(), _not_number()))
            found[infinite] = math.nan
        if numbers.size:
            found[np.isin(found, numbers)] = math.nan
        if rules.negative_is_below_dl:
            negative = found < 0
            found[negative] = -found[negative]
            flags[fast[negative]] = _BELOW
        values[fast] = found

    for row in np.flatnonzero(~(plain | empty)).tolist():
        value, flag, reason = _special(stripped[row], rules, keys, numbers)
        values[row] = value
        flags[row] = FLAG_CODES[flag]
        if reason is not None:
            rejected[row] = reason

    rows = sorted(rejected)
    return ParsedColumn(
        values=values,
        flags=flags,
        reported=reported,
        rejected_rows=np.array(rows, dtype=np.int64),
        rejected_reasons=tuple(rejected[row] for row in rows),
    )


def _singles(values: np.ndarray) -> np.ndarray:
    """Los Single de ``values`` (float32, o float64 que lo son exactamente)."""
    if values.dtype == np.float32:
        return values
    if values.dtype.kind != "f":
        raise TypeError(f"un Single es un número en coma flotante, no {values.dtype}")
    with np.errstate(over="ignore"):
        singles = values.astype(np.float32)
    same = (singles.astype(values.dtype) == values) | np.isnan(values)
    if not same.all():
        wrong = values[~same][0]
        raise ValueError(f"{wrong!r} no es un número en precisión simple: se perdería su valor "
                         f"(RF-005-02)")
    return singles


def _shortest(single: np.float32) -> float:
    return float(np.format_float_positional(single, unique=True, trim="-")) + 0.0


def from_single(value: float | np.floating) -> float:
    """El float64 del decimal más corto de un Single de RecMin (RF-005-02): ``float32(0.1)``
    → 0.1. También acepta el Single ya pasado a float64 (0.10000000149011612 → 0.1); otro
    float64 es un error (``ValueError``): se perdería su valor. NaN sigue NaN; −0, 0."""
    if isinstance(value, bool) or not isinstance(value, float | np.floating):
        raise TypeError(f"un Single es un número en coma flotante, no {value!r}")
    single = _singles(np.array([value]))[0]
    return _shortest(single)


def from_single_column(values: np.ndarray) -> np.ndarray:
    """:func:`from_single` de cada valor de un array (float32, o float64 que son Single), en
    un array float64 nuevo. Cada valor distinto se convierte una vez (en una base, los
    tramos y las leyes se repiten)."""
    if not isinstance(values, np.ndarray):
        raise TypeError(f"una columna de Single es un array numpy, no {values!r}")
    singles = _singles(values.ravel())
    if not singles.size:
        return np.empty(values.shape, dtype=np.float64)
    distinct, inverse = np.unique(singles, return_inverse=True)
    shortest = np.array([_shortest(single) for single in distinct], dtype=np.float64)
    return shortest[inverse].reshape(values.shape)
