# SPDX-License-Identifier: GPL-3.0-or-later
"""Rodajas de una cubicación por bancos (spec 011; RF-011-09; plan 011 A3, A4 y D-22;
RF-008-03).

Una cubicación se reparte por bancos de dos maneras: con una **altura de banco y una cota de
anclaje** (m), y entonces las cotas de las rodajas son ``anclaje + k·altura`` con ``k``
entero, o con una **lista creciente de cotas** (m), que se usa tal cual. Cada rodaja es
semiabierta, ``[z_k, z_k+1)``: cerrada abajo y abierta arriba (D-22).

- :class:`Slices`: el reparto, comprobado al crearlo (la altura en el rango de
  ``res.bench_height_m``, (0; 100] m; la lista, creciente y con dos cotas al menos).
- :func:`slices_from_text`: lo que se teclea en el diálogo (``StringProperty``: un
  ``FloatProperty`` guardaría las cotas en float32), con el rechazo de cada valor con su rango.
- :func:`bounds`: las cotas que cubren lo cubicado, las mínimas.
- :func:`index`: la rodaja de cada cota ``z``; una cota justo en un límite va a la rodaja de
  arriba. Con altura y anclaje, el índice es ``floor((z − anclaje)/altura)`` (nunca
  ``round``, que redondea al par) corregido para que case **siempre** con las cotas de
  :func:`bounds`: ``index(z) = k`` si y solo si ``anclaje + k·altura <= z < anclaje +
  (k + 1)·altura`` calculados en float64 igual que :func:`bounds`, también con alturas y
  anclajes que no son exactos en binario (0,3 m). La posición de ``z`` entre las cotas de
  :func:`bounds` es ``index(z) − index(bounds[0])`` en los dos modos.

Lo que **no** se decide aquí (lo hace el núcleo, A3): el extremo superior del intervalo de una
celda justo en una cota se cuenta en la rodaja de abajo, y lo que queda fuera de una lista de
cotas que no cubre lo cubicado.

Los rechazos son :class:`~.messages.ResError` con el objeto «Bancos de la cubicación», el
campo del diálogo (``bench_height``, ``bench_anchor`` o ``bench_levels``) y el valor; las
etiquetas de los campos van en español, como el texto del error. Python puro con numpy
(nivel 9).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from ..core.params import ParamError
from ..core.units import UnitError, convert, parse_quantity
from .messages import ResError
from .params import BENCH_HEIGHT, BENCH_HEIGHT_DEF

__all__ = [
    "ANCHOR_FIELD",
    "HEIGHT_FIELD",
    "LEVELS_FIELD",
    "LEVELS_SEPARATOR",
    "Slices",
    "bounds",
    "index",
    "slices_from_text",
]

HEIGHT_FIELD = "bench_height"
"""El campo de la altura de banco (m) en el diálogo y en los ajustes de la cubicación."""
ANCHOR_FIELD = "bench_anchor"
"""El campo de la cota de anclaje (m)."""
LEVELS_FIELD = "bench_levels"
"""El campo de la lista de cotas (m)."""
LEVELS_SEPARATOR = ";"
"""El separador de las cotas de una lista (la coma es decimal)."""

_OBJ = "Bancos de la cubicación"
_LABELS = {
    HEIGHT_FIELD: "Altura de banco",
    ANCHOR_FIELD: "Cota de anclaje",
    LEVELS_FIELD: "Lista de cotas de los bancos",
}
_METRE = "m"


@dataclass(frozen=True, slots=True)
class Slices:
    """El reparto de una cubicación por bancos: ``height_m`` y ``anchor_m`` (m), o
    ``levels`` (m, crecientes), nunca los dos.

    Al crearlo, la altura fuera de (0; 100] m es :class:`ResError`
    (``res.bench_height_range``, con la clave ``res.bench_height_m``, el valor y el rango;
    RF-008-03), y la lista que no crece (``res.bench_levels_not_increasing``) o tiene menos de
    dos cotas (``res.bench_levels_too_few``), también. Los dos modos a la vez, uno a medias o
    un valor NaN o infinito son un error del programa (:class:`ValueError`): lo tecleado lo
    comprueba antes :func:`slices_from_text`. ``levels`` se guarda como tupla de float."""

    height_m: float | None
    anchor_m: float | None
    levels: tuple[float, ...] | None

    def __post_init__(self) -> None:
        by_height = self.height_m is not None or self.anchor_m is not None
        if by_height == (self.levels is not None) or (
                by_height and (self.height_m is None or self.anchor_m is None)):
            raise ValueError(
                "Slices: altura y anclaje, o una lista de cotas, nunca los dos ni uno a medias "
                f"(altura {self.height_m!r}, anclaje {self.anchor_m!r}, lista {self.levels!r})"
            )
        if self.levels is None:
            height = _finite(self.height_m, "la altura de banco")
            object.__setattr__(self, "height_m", _checked_height(height))
            object.__setattr__(self, "anchor_m", _finite(self.anchor_m, "la cota de anclaje"))
        else:
            object.__setattr__(self, "levels", _checked_levels(self.levels))


def _finite(value: object, what: str) -> float:
    """``value`` como float64 finito; :class:`ValueError` si no lo es (error del programa)."""
    if isinstance(value, bool) or not isinstance(value, int | float | np.floating | np.integer):
        raise ValueError(f"Slices: {what} es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Slices: {what} es un número finito, no {value!r}")
    return number


def _checked_height(height: float) -> float:
    """La altura en el rango de ``res.bench_height_m`` o :class:`ResError` con su rango."""
    try:
        BENCH_HEIGHT_DEF.check(height)
    except ParamError:
        raise ResError("res.bench_height_range", obj=_OBJ, field=HEIGHT_FIELD, value=height,
                       range=BENCH_HEIGHT_DEF.range_text(), key=BENCH_HEIGHT) from None
    return height


def _checked_levels(levels: object) -> tuple[float, ...]:
    """La lista como tupla de float, creciente y con dos cotas al menos, o :class:`ResError`."""
    if isinstance(levels, str | bytes) or not isinstance(levels, Sequence | np.ndarray):
        raise ValueError(f"Slices: la lista de cotas es una secuencia, no {levels!r}")
    items = tuple(_finite(level, "cada cota de la lista") for level in levels)
    if len(items) < 2:
        shown = f"{LEVELS_SEPARATOR} ".join(_shown(level) for level in items)
        raise ResError("res.bench_levels_too_few", obj=_OBJ, field=LEVELS_FIELD, value=shown)
    for previous, level in pairwise(items):
        if not level > previous:
            raise ResError("res.bench_levels_not_increasing", obj=_OBJ, field=LEVELS_FIELD,
                           value=level, previous=previous)
    return items


def _shown(level: float) -> str:
    """Una cota como se teclea (coma decimal y sin decimales si es entera)."""
    text = str(int(level)) if level.is_integer() else repr(level)
    return text.replace(".", ",")


# --- Lo tecleado (RF-008-03) ----------------------------------------------------------------


def slices_from_text(height: str, anchor: str, levels: str) -> Slices | None:
    """El reparto por bancos que se tecleó en el diálogo: la altura y el anclaje, o la lista
    de cotas separadas por «;» (la coma es decimal). Cada número, con coma o punto decimal,
    espacios de miles y, si se quiere, su unidad de longitud (se pasa a metros; RF-008-03).

    Sin nada tecleado (o solo espacios), ``None``: no se reparte por bancos. Si no,
    :class:`ResError` con el objeto, el campo y el valor: ``res.bench_value_not_number`` (lo
    que no es un número de metros, con lo tecleado), ``res.bench_value_missing`` (la altura sin
    anclaje o al revés), ``res.bench_both_ways`` (las dos maneras a la vez: nada se ignora en
    silencio), ``res.bench_levels_too_few`` (con lo tecleado) y los rechazos de
    :class:`Slices` (la altura fuera de su rango; la lista que no crece)."""
    typed = {HEIGHT_FIELD: _text(height), ANCHOR_FIELD: _text(anchor),
             LEVELS_FIELD: _text(levels)}
    if not any(typed.values()):
        return None
    if typed[LEVELS_FIELD]:
        if typed[HEIGHT_FIELD] or typed[ANCHOR_FIELD]:
            raise ResError("res.bench_both_ways", obj=_OBJ, field=LEVELS_FIELD,
                           value=typed[LEVELS_FIELD])
        items = [item.strip() for item in typed[LEVELS_FIELD].split(LEVELS_SEPARATOR)]
        if len(items) < 2:
            raise ResError("res.bench_levels_too_few", obj=_OBJ, field=LEVELS_FIELD,
                           value=typed[LEVELS_FIELD])
        return Slices(None, None, tuple(_metres(item, LEVELS_FIELD) for item in items))
    for field in (HEIGHT_FIELD, ANCHOR_FIELD):
        if not typed[field]:
            raise ResError("res.bench_value_missing", obj=_OBJ, field=field, value="",
                           label=_LABELS[field])
    return Slices(_metres(typed[HEIGHT_FIELD], HEIGHT_FIELD),
                  _metres(typed[ANCHOR_FIELD], ANCHOR_FIELD), None)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"lo tecleado es un texto, no {type(value).__name__}")
    return value.strip()


def _metres(text: str, field: str) -> float:
    """El número de metros de ``text`` (float64) o :class:`ResError`
    (``res.bench_value_not_number``) con lo tecleado."""
    try:
        number, unit = parse_quantity(text)
        return convert(number, unit or _METRE, _METRE)
    except UnitError:
        raise ResError("res.bench_value_not_number", obj=_OBJ, field=field, value=text,
                       label=_LABELS[field]) from None


# --- Cotas e índices (A3, A4) ---------------------------------------------------------------


def _level(slices: Slices, number: np.ndarray | float) -> np.ndarray | float:
    """La cota ``anclaje + k·altura`` de la rodaja ``k`` (float64): la **única** expresión de
    las cotas, la misma en :func:`bounds` y en :func:`index`."""
    return slices.anchor_m + number * slices.height_m  # type: ignore[operator]


def bounds(slices: Slices, zmin: float, zmax: float) -> np.ndarray:
    """Las cotas ``z_0 < z_1 < … < z_n`` (float64) de las rodajas que cubren lo cubicado,
    de ``zmin`` a ``zmax`` (m).

    Con altura y anclaje, las mínimas: ``z_0 <= zmin < z_1`` y ``z_n-1 < zmax <= z_n``, cotas
    ``anclaje + k·altura`` también con el anclaje fuera del rango; la máxima justo en una cota
    cierra la última rodaja (no añade otra vacía encima) y un rango plano da una rodaja. Con
    una lista, la lista tal cual (una copia), cubra o no el rango. Un rango invertido o no
    finito es un error del programa (:class:`ValueError`)."""
    low, high = float(zmin), float(zmax)
    if not (math.isfinite(low) and math.isfinite(high) and low <= high):
        raise ValueError(f"rango cubicado no válido: de {zmin!r} a {zmax!r}")
    if slices.levels is not None:
        return np.array(slices.levels, dtype=np.float64)
    first = int(index(slices, low))
    top = int(index(slices, high))
    if not (top > first and _level(slices, float(top)) == high):
        top += 1
    return np.asarray(_level(slices, np.arange(first, top + 1, dtype=np.float64)))


def index(slices: Slices, z: np.ndarray | float) -> np.ndarray:
    """La rodaja de cada cota de ``z`` (m), con su forma, en ``int64``: rodajas semiabiertas
    ``[z_k, z_k+1)``, de modo que una cota justo en un límite va a la de arriba (D-22).

    Con altura y anclaje, ``k`` con ``anclaje + k·altura <= z < anclaje + (k + 1)·altura``
    (``floor((z − anclaje)/altura)`` corregido en ±1 para casar con :func:`bounds`). Con una
    lista, su posición (``searchsorted`` por la derecha − 1): −1 por debajo de la primera cota
    y ``len(levels) − 1`` desde la última (fuera de las rodajas). Una cota NaN o infinita es un
    error del programa (:class:`ValueError`)."""
    values = np.asarray(z, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("la rodaja de una cota NaN o infinita no existe")
    if slices.levels is not None:
        levels = np.asarray(slices.levels, dtype=np.float64)
        found = np.array(np.searchsorted(levels, values, side="right"), dtype=np.int64)
        found -= 1
        return found
    number = np.asarray(np.floor((values - slices.anchor_m) / slices.height_m))
    number -= values < _level(slices, number)
    number += values >= _level(slices, number + 1.0)
    return number.astype(np.int64)
