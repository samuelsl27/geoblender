# SPDX-License-Identifier: GPL-3.0-or-later
"""Toneladas y relaciones de una cubicación por unidades (spec 011; RF-011-15, RF-011-16,
RF-011-17, RF-011-18; plan 011 A8, A9, D-8, D-11, D-16, D-28).

Es el cálculo de la segunda de las dos operaciones encadenadas de una cubicación con unidades
(D-16, ``res.tonnage``): parte de los m³ de desmonte de cada unidad por dominio y rodaja (la
tabla de ``res.volume``: :class:`UnitVolume`) y de los parámetros de la columna de materiales
(densidad in situ, K y porcentajes: familias de ``reserves.params``, resueltas versión →
proyecto), **sin releer las superficies**: cambiar un K solo rehace las toneladas.

- **Compuesta** (A8; RF-011-15): su volumen se reparte entre sus componentes por sus
  porcentajes, ``V_c = V · p_c / Σp``, así que los componentes suman su unidad salvo el
  redondeo. Si los porcentajes no suman 100 con dos decimales (``|Σp − 100| ≥ 0,005``; uno sin
  declarar no suma), ``res.percent_sum`` con la unidad y la suma, y **no se calcula nada**.
- **In situ** (RF-011-16): ``t = V·ρ`` y esponjado ``V·K``. **Suelto**: ``t = V·ρ/K`` (un
  acopio se pesa con la densidad suelta: error 67) y sin esponjado (ya lo está).
- **Sin ρ** (o, en lo suelto, **sin K**; RF-011-17, D-8): el volumen sin toneladas, la nota
  («sin densidad», «sin K»), el aviso ``res.density_missing`` con la unidad y el parámetro
  (:class:`MissingParameter`) y **sin total de toneladas** donde ese elemento tiene volumen.
  Sin el K de lo in situ, sin esponjado (nota), con toneladas y sin aviso. Un elemento sin
  volumen pesa 0 t y no necesita parámetros. Nunca un valor supuesto.
- **Relaciones** (A9; RF-011-18, D-28): estéril/útil en t/t (``Σ t estéril / Σ t útil``) y en
  m³/m³ in situ (lo in situ, ``V``; lo suelto, ``V/K``: sin su K, sin relación en m³/m³), por
  dominio y rodaja (:class:`TonnageTotals`), y la **intrínseca** de cada compuesta, sus
  componentes estériles frente a los útiles por sus porcentajes (:class:`IntrinsicRatio`).
  Sin material útil, «sin material útil» (nota) en lugar de un número.

:func:`tonnage` da un :class:`TonnageResult`: una fila por unidad y por componente
(:class:`TonnageRow`) en el orden de los volúmenes, los totales y las relaciones de cada
dominio y rodaja, las relaciones intrínsecas y los parámetros que faltan. Las notas son códigos
de ``reserves.messages`` (``res.note_*``); lo que no se puede dar es ``None`` con su nota, nunca
NaN. Python puro (nivel 9). Las entradas solo se leen.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass

from ..core.params import ResolvedParam
from .materials import Component, Kind, MaterialColumn, Role, State, Unit
from .messages import ResError, render
from .params import density_key, percent_key, swell_key

__all__ = [
    "ALL_DOMAINS",
    "NO_DENSITY",
    "NO_SWELL",
    "NO_USEFUL",
    "OUTSIDE_DOMAINS",
    "PERCENT_TOLERANCE",
    "IntrinsicRatio",
    "MissingParameter",
    "Ratio",
    "TonnageResult",
    "TonnageRow",
    "TonnageTotals",
    "UnitVolume",
    "tonnage",
]

ALL_DOMAINS = "*"
"""El dominio de las filas de toda la cubicación (como la tabla de ``res.volume``, §5.2.1)."""
OUTSIDE_DOMAINS = ""
"""El dominio de las filas de «Fuera de los dominios» (como la tabla de ``res.volume``)."""
PERCENT_TOLERANCE = 0.005
"""Los porcentajes de una compuesta suman 100 con dos decimales si ``|Σp − 100| < 0,005``."""
NO_DENSITY = "res.note_no_density"
"""La nota de lo que no tiene toneladas por falta de densidad."""
NO_SWELL = "res.note_no_swell"
"""La nota de lo que no tiene esponjado, toneladas o volumen in situ por falta de K."""
NO_USEFUL = "res.note_no_useful"
"""La nota de una relación sin material útil."""

_PATH = " ▸ "


@dataclass(frozen=True, slots=True)
class UnitVolume:
    """Los m³ de desmonte de una unidad (por su código) en un dominio (:data:`ALL_DOMAINS`, el
    valor del campo o :data:`OUTSIDE_DOMAINS`) y una rodaja (``None``, todas; si no, la clave de
    la rodaja de la tabla, que solo se agrupa: ``(z0, z1)``)."""

    domain: str
    bench: Hashable
    unit: str
    volume_m3: float


@dataclass(frozen=True, slots=True)
class TonnageRow:
    """Una unidad (``component`` ``None``) o un componente en un dominio y una rodaja: su papel
    (``None`` en una compuesta) y su estado, su volumen (m³), su volumen in situ (lo suelto,
    ``V/K``; m³), su esponjado (lo in situ, ``V·K``; m³; ``None`` en lo suelto) y sus toneladas,
    con las notas de lo que falta (``None`` y su nota). Una compuesta suma sus componentes."""

    domain: str
    bench: Hashable
    unit: str
    component: str | None
    role: Role | None
    state: State
    volume_m3: float
    in_situ_m3: float | None
    swell_m3: float | None
    mass_t: float | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Ratio:
    """Una relación estéril/útil (``value``) o, si no se puede dar, ``None`` con sus notas."""

    value: float | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TonnageTotals:
    """Lo de un dominio y una rodaja: el total de toneladas (``None`` si a algún elemento con
    volumen le faltan, con sus notas en ``total_notes``), lo útil y lo estéril en m³ in situ
    (lo suelto, ``V/K``: D-28) y en t, y las relaciones estéril/útil en m³/m³ y en t/t."""

    domain: str
    bench: Hashable
    total_t: float | None
    total_notes: tuple[str, ...]
    useful_m3: float | None
    waste_m3: float | None
    useful_t: float | None
    waste_t: float | None
    ratio_m3: Ratio
    ratio_t: Ratio


@dataclass(frozen=True, slots=True)
class IntrinsicRatio:
    """La relación intrínseca de una unidad compuesta (por su código): sus componentes
    estériles frente a los útiles, por sus porcentajes, en m³/m³ in situ y en t/t."""

    unit: str
    ratio_m3: Ratio
    ratio_t: Ratio


@dataclass(frozen=True, slots=True)
class MissingParameter:
    """Un parámetro que falta a una unidad o a un componente con volumen (RF-011-17): sus
    códigos, la clave del parámetro y su nombre para una persona («Capa útil ▸ Caliza»)."""

    unit: str
    component: str | None
    key: str
    shown: str

    def text(self, language: str = "es") -> str:
        """El aviso ``res.density_missing`` con la unidad y el parámetro."""
        return render("res.density_missing", language=language, unit=self.shown,
                      value=self.key)


@dataclass(frozen=True, slots=True)
class TonnageResult:
    """El resultado de :func:`tonnage`: las filas (cada unidad seguida de sus componentes, en
    el orden de los volúmenes), los totales de cada dominio y rodaja (en el orden en que
    aparecen), las relaciones intrínsecas de las compuestas (en el orden de la columna) y los
    parámetros que faltan (en el orden de la columna; uno por elemento y parámetro)."""

    rows: tuple[TonnageRow, ...]
    groups: tuple[TonnageTotals, ...]
    intrinsic: tuple[IntrinsicRatio, ...]
    missing: tuple[MissingParameter, ...]

    def row(self, unit: str, component: str | None = None, *, domain: str = ALL_DOMAINS,
            bench: Hashable = None) -> TonnageRow:
        """La fila de la unidad ``unit`` (o de su componente ``component``) en ``domain`` y
        ``bench``; :class:`KeyError` si no está."""
        for row in self.rows:
            if (row.unit, row.component, row.domain, row.bench) == (unit, component, domain,
                                                                     bench):
                return row
        raise KeyError(f"sin fila de «{unit}» ({component}) en {domain!r}, {bench!r}")

    def group(self, domain: str = ALL_DOMAINS, bench: Hashable = None) -> TonnageTotals:
        """Los totales de ``domain`` y ``bench``; :class:`KeyError` si no están."""
        for group in self.groups:
            if (group.domain, group.bench) == (domain, bench):
                return group
        raise KeyError(f"sin totales de {domain!r}, {bench!r}")

    @property
    def total(self) -> TonnageTotals:
        """Los totales de toda la cubicación (todos los dominios y todas las rodajas)."""
        return self.group()

    def intrinsic_of(self, unit: str) -> IntrinsicRatio:
        """La relación intrínseca de la compuesta ``unit``; :class:`KeyError` si no lo es."""
        for item in self.intrinsic:
            if item.unit == unit:
                return item
        raise KeyError(f"«{unit}» no es una unidad compuesta de la columna")


@dataclass(frozen=True, slots=True)
class _Element:
    """Lo que pesa por sí mismo: una unidad que no es compuesta o un componente, con su parte
    del volumen de su unidad (``share``: 1, o ``p_c / Σp``) y sus parámetros (``None``, sin
    declarar)."""

    unit: Unit
    component: Component | None
    share: float
    density: float | None
    swell: float | None

    @property
    def role(self) -> Role | None:
        return self.unit.role if self.component is None else self.component.role

    @property
    def code(self) -> str | None:
        return None if self.component is None else self.component.code

    @property
    def shown(self) -> str:
        if self.component is None:
            return self.unit.shown
        return self.unit.shown + _PATH + (self.component.name.strip() or self.component.code)


def tonnage(volumes: Iterable[UnitVolume], column: MaterialColumn,
            params: Mapping[str, ResolvedParam | float | None]) -> TonnageResult:
    """Las toneladas y las relaciones de los m³ por unidad ``volumes`` con la columna ``column``
    (que se valida: ``res.materials_invalid``) y los valores de sus parámetros ``params`` por
    clave (un número, el ``ResolvedParam`` que anota la operación o ``None``; la clave que no
    está, sin declarar). ``res.percent_sum`` si los porcentajes de una compuesta no suman 100
    con dos decimales. Una unidad que no es de la columna, una fila repetida, un volumen no
    finito o un parámetro que no es un número finito (positivo, salvo un porcentaje) son
    errores del programa (:class:`ValueError`)."""
    column.validate()
    units = {unit.code: unit for unit in column.units}
    elements = {unit.code: _elements(unit, params) for unit in column.units}
    rows: list[TonnageRow] = []
    leaves: dict[tuple[str, Hashable], list[TonnageRow]] = {}
    seen: set[tuple[str, Hashable, str]] = set()
    lacking: set[tuple[str, str | None, str]] = set()
    for item in volumes:
        volume = _volume(item, elements, seen)
        unit = units[item.unit]
        parts = [_weigh(item, element, volume * element.share, lacking)
                 for element in elements[item.unit]]
        if unit.kind is Kind.COMPOUND:
            rows.append(_compound(item, unit, volume, parts))
        rows.extend(parts)
        leaves.setdefault((item.domain, item.bench), []).extend(parts)
    groups = tuple(_totals(domain, bench, found) for (domain, bench), found in leaves.items())
    intrinsic = tuple(_intrinsic(unit, elements[unit.code]) for unit in column.units
                      if unit.kind is Kind.COMPOUND)
    missing = tuple(
        MissingParameter(element.unit.code, element.code, key, element.shown)
        for unit in column.units for element in elements[unit.code]
        for key in _keys(element) if (element.unit.code, element.code, key) in lacking
    )
    return TonnageResult(tuple(rows), groups, intrinsic, missing)


def _keys(element: _Element) -> tuple[str, str]:
    """Las claves de la densidad y del K de ``element``."""
    return (density_key(element.unit.code, element.code),
            swell_key(element.unit.code, element.code))


def _elements(unit: Unit, params: Mapping[str, object]) -> tuple[_Element, ...]:
    """Lo que pesa por sí mismo de ``unit`` (ella o sus componentes), con sus parámetros."""
    if unit.kind is not Kind.COMPOUND:
        return (_element(unit, None, 1.0, params),)
    percents = [_value(params, percent_key(unit.code, item.code), positive=False)
                for item in unit.components]
    total = math.fsum(value for value in percents if value is not None)
    if None in percents or not abs(total - 100.0) < PERCENT_TOLERANCE:
        raise ResError("res.percent_sum", obj=f"Unidad «{unit.shown}»", field="percent",
                       value=round(total, 2), unit=unit.shown)
    return tuple(_element(unit, item, value / total, params)
                 for item, value in zip(unit.components, percents, strict=True))


def _element(unit: Unit, component: Component | None, share: float,
             params: Mapping[str, object]) -> _Element:
    code = None if component is None else component.code
    return _Element(unit, component, share,
                    _value(params, density_key(unit.code, code), positive=True),
                    _value(params, swell_key(unit.code, code), positive=True))


def _value(params: Mapping[str, object], key: str, *, positive: bool) -> float | None:
    """El valor de ``key`` (``None`` si no está declarado); :class:`ValueError` si no es un
    número finito ≥ 0 (> 0 con ``positive``)."""
    value = params.get(key)
    if isinstance(value, ResolvedParam):
        value = value.value
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"«{key}» es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or (positive and number == 0.0):
        bound = "> 0" if positive else "≥ 0"
        raise ValueError(f"«{key}» es un número finito {bound}, no {value!r}")
    return number


def _volume(item: UnitVolume, elements: Mapping[str, object],
            seen: set[tuple[str, Hashable, str]]) -> float:
    """El volumen de ``item``, comprobado: de una unidad de la columna, sin repetir su dominio
    y su rodaja, un número finito."""
    if not isinstance(item, UnitVolume):
        raise TypeError(f"un volumen es un UnitVolume, no {item!r}")
    if item.unit not in elements:
        raise ValueError(f"«{item.unit}» no es una unidad de la columna de materiales")
    key = (item.domain, item.bench, item.unit)
    if key in seen:
        raise ValueError(f"volumen repetido de «{item.unit}» en {item.domain!r}, "
                         f"{item.bench!r}")
    seen.add(key)
    value = item.volume_m3
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(
            float(value)):
        raise ValueError(f"el volumen de «{item.unit}» es un número finito, no {value!r}")
    return float(value)


def _weigh(item: UnitVolume, element: _Element, volume: float,
           lacking: set[tuple[str, str | None, str]] | None) -> TonnageRow:
    """La fila de ``element`` con ``volume`` m³ (A8): lo que falta, ``None`` con su nota y, si
    hay volumen, en ``lacking`` (salvo el K de lo in situ, que solo quita el esponjado)."""
    in_situ_state = element.unit.state is State.IN_SITU
    density, swell = element.density, element.swell
    if volume == 0.0:
        return _row(item, element, 0.0, 0.0, 0.0 if in_situ_state else None, 0.0, ())
    notes = []
    if density is None:
        notes.append(NO_DENSITY)
    if swell is None:
        notes.append(NO_SWELL)
    if in_situ_state:
        in_situ = volume
        swelled = None if swell is None else volume * swell
        mass = None if density is None else volume * density
    else:
        in_situ = None if swell is None else volume / swell
        swelled = None
        mass = None if density is None or swell is None else volume * density / swell
    if lacking is not None:
        key_density, key_swell = _keys(element)
        if density is None:
            lacking.add((element.unit.code, element.code, key_density))
        if swell is None and not in_situ_state:
            lacking.add((element.unit.code, element.code, key_swell))
    return _row(item, element, volume, in_situ, swelled, mass, tuple(notes))


def _row(item: UnitVolume, element: _Element, volume: float, in_situ: float | None,
         swelled: float | None, mass: float | None, notes: tuple[str, ...]) -> TonnageRow:
    return TonnageRow(item.domain, item.bench, element.unit.code, element.code, element.role,
                      element.unit.state, volume, in_situ, swelled, mass, notes)


def _compound(item: UnitVolume, unit: Unit, volume: float,
              parts: list[TonnageRow]) -> TonnageRow:
    """La fila de una compuesta: su volumen y la suma de sus componentes (``None`` si a alguno
    le falta), con sus notas."""
    return TonnageRow(item.domain, item.bench, unit.code, None, None, unit.state, volume,
                      _sum(part.in_situ_m3 for part in parts),
                      _sum(part.swell_m3 for part in parts),
                      _sum(part.mass_t for part in parts),
                      _union(part.notes for part in parts))


def _sum(values: Iterable[float | None]) -> float | None:
    """La suma (``math.fsum``) o ``None`` si falta alguno."""
    found = list(values)
    if any(value is None for value in found):
        return None
    return math.fsum(found)


def _union(notes: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
    """Las notas sin repetir, en su orden."""
    return tuple(dict.fromkeys(note for group in notes for note in group))


def _totals(domain: str, bench: Hashable, leaves: list[TonnageRow]) -> TonnageTotals:
    """Los totales y las relaciones de ``leaves`` (lo que pesa por sí mismo de un dominio y
    una rodaja; A9)."""
    total_t = _sum(leaf.mass_t for leaf in leaves)
    total_notes = () if total_t is not None else _union(
        leaf.notes for leaf in leaves if leaf.mass_t is None)
    by_role = _by_role(leaves)
    return TonnageTotals(domain, bench, total_t, total_notes, *by_role)


def _by_role(leaves: list[TonnageRow]
             ) -> tuple[float | None, float | None, float | None, float | None, Ratio, Ratio]:
    """Lo útil y lo estéril de ``leaves`` en m³ in situ y en t, y las relaciones estéril/útil
    en m³/m³ y en t/t (sin material útil, «sin material útil»; sin un dato, sus notas)."""
    useful = [leaf for leaf in leaves if leaf.role is Role.USEFUL]
    waste = [leaf for leaf in leaves if leaf.role is Role.WASTE]
    useful_m3 = _sum(leaf.in_situ_m3 for leaf in useful)
    waste_m3 = _sum(leaf.in_situ_m3 for leaf in waste)
    useful_t = _sum(leaf.mass_t for leaf in useful)
    waste_t = _sum(leaf.mass_t for leaf in waste)
    has_useful = math.fsum(leaf.volume_m3 for leaf in useful) > 0.0
    lacking_t = _union(leaf.notes for leaf in useful + waste if leaf.mass_t is None)
    ratio_m3 = _ratio(waste_m3, useful_m3, has_useful, (NO_SWELL,))
    ratio_t = _ratio(waste_t, useful_t, has_useful, lacking_t)
    return useful_m3, waste_m3, useful_t, waste_t, ratio_m3, ratio_t


def _ratio(waste: float | None, useful: float | None, has_useful: bool,
           lacking: tuple[str, ...]) -> Ratio:
    """``waste / useful``; sin material útil, «sin material útil» (antes que lo que falta); sin
    un dato, ``lacking``."""
    if not has_useful:
        return Ratio(None, (NO_USEFUL,))
    if waste is None or useful is None:
        return Ratio(None, lacking)
    if useful <= 0.0:
        return Ratio(None, (NO_USEFUL,))
    return Ratio(waste / useful)


def _intrinsic(unit: Unit, elements: tuple[_Element, ...]) -> IntrinsicRatio:
    """La relación intrínseca de la compuesta ``unit``: sus componentes con su parte de 1 m³ de
    la unidad (``p_c / Σp``), estériles frente a útiles (A9)."""
    item = UnitVolume(ALL_DOMAINS, None, unit.code, 1.0)
    parts = [_weigh(item, element, element.share, None) for element in elements]
    *_, ratio_m3, ratio_t = _by_role(parts)
    return IntrinsicRatio(unit.code, ratio_m3, ratio_t)
