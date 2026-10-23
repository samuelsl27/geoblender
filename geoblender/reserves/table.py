# SPDX-License-Identifier: GPL-3.0-or-later
"""Las tablas ``report`` de una cubicación en formato largo (spec 011; RF-011-10, RF-011-22,
RF-011-23; plan 011 §5.2.1, D-26 y D-27).

Una fila por valor, como el CSV (RF-011-24): el dominio (``'*'``, todos; ``''``, «Fuera de los
dominios»; si no, el valor del campo), la rodaja ``[bench_z0, bench_z1)`` (las dos ``NULL``: todas;
solo ``bench_z0`` ``NULL``: lo que queda por debajo de la primera cota de una lista; solo
``bench_z1``, por encima de la última), la unidad y el componente (sus códigos; ``NULL``: todas o
la unidad entera), el dato (:data:`QUANTITIES`), su valor (``NULL`` con su nota si no se puede dar:
«sin densidad», «sin material útil»; **nunca NaN ni infinito**), el código de su unidad de
``core.units`` y la nota (códigos de ``reserves.messages`` separados por :data:`NOTE_SEPARATOR`).
Así la tabla no cambia de columnas con los repartos, solo de filas.

- :class:`Row` y :func:`row`: una fila (con la unidad de su dato); :data:`COLUMNS`, sus columnas
  tipadas con su título (``gpkg_data_columns``, :data:`TITLES`); :func:`create_table` e
  :func:`insert_sql`, las sentencias de una tabla ``res_vol_``, ``res_ton_`` o ``res_stg_``.
- :func:`read_rows`, :func:`filter_rows` y :func:`choices`: leerla y filtrarla para el panel.
- :func:`unit_volumes`: los m³ por unidad de la tabla de volúmenes, lo que lee ``res.tonnage``
  (D-16: sin releer las superficies); :func:`tonnage_rows`, la tabla de las toneladas.

Python puro (nivel 9).
"""

from __future__ import annotations

import math
import numbers
import re
import sqlite3
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from ..core.units import UNITS
from .materials import Role, State
from .tonnage import ALL_DOMAINS, NO_SWELL, OUTSIDE_DOMAINS, TonnageResult, UnitVolume

__all__ = [
    "ALL_DOMAINS",
    "ANY",
    "COLUMNS",
    "COLUMN_NAMES",
    "NOTE_SEPARATOR",
    "OUTSIDE_DOMAINS",
    "QUANTITIES",
    "TITLES",
    "Choices",
    "Column",
    "Quantity",
    "Row",
    "choices",
    "create_table",
    "filter_rows",
    "insert_sql",
    "read_rows",
    "row",
    "tonnage_rows",
    "unit_volumes",
]

NOTE_SEPARATOR = ";"
"""Separa los códigos de las notas de una fila."""

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

type Bench = tuple[float | None, float | None] | None
"""Una rodaja ``(z0, z1)`` (m; un extremo ``None``: por debajo o por encima de una lista de
cotas) o ``None``: todas."""


@dataclass(frozen=True, slots=True)
class Column:
    """Una columna de la tabla: su nombre, su tipo SQL y su título en español."""

    name: str
    sql: str
    title: str


COLUMNS: tuple[Column, ...] = (
    Column("domain", "TEXT", "Dominio"),
    Column("bench_z0", "DOUBLE", "Cota inferior de la rodaja (m)"),
    Column("bench_z1", "DOUBLE", "Cota superior de la rodaja (m)"),
    Column("unit", "TEXT", "Unidad"),
    Column("component", "TEXT", "Componente"),
    Column("quantity", "TEXT NOT NULL", "Dato"),
    Column("value", "DOUBLE", "Valor"),
    Column("unit_code", "TEXT NOT NULL", "Unidad de medida"),
    Column("note", "TEXT", "Nota"),
)
"""Las columnas de una tabla ``report`` de ``res`` (sin ``fid``), en su orden (plan §5.2.1)."""

COLUMN_NAMES: tuple[str, ...] = tuple(column.name for column in COLUMNS)
TITLES: Mapping[str, str] = MappingProxyType({column.name: column.title for column in COLUMNS})
"""Columna → título, para ``core.gpkg.base.set_column_titles``."""


@dataclass(frozen=True, slots=True)
class Quantity:
    """Un dato de las tablas: su nombre, el código de su unidad (``core.units``) y la clave de
    su cifra (``None``: solo fila de la tabla)."""

    name: str
    unit: str
    figure: str | None = None


QUANTITIES: Mapping[str, Quantity] = MappingProxyType({item.name: item for item in (
    # res_vol_: totales y áreas (RF-011-01, RF-011-04), unidades (RF-011-12, RF-011-13)
    Quantity("cut_m3", "m3", "res.cut_m3"),
    Quantity("fill_m3", "m3", "res.fill_m3"),
    Quantity("net_m3", "m3", "res.net_m3"),
    Quantity("area_m2", "m2", "res.area_m2"),
    Quantity("nodata_area_m2", "m2", "res.nodata_area_m2"),
    Quantity("still_area_m2", "m2", "res.still_area_m2"),
    Quantity("volume_m3", "m3", "res.unit_volume_m3"),
    Quantity("absent_area_m2", "m2"),
    Quantity("absent_nodata_area_m2", "m2"),
    Quantity("crossed_area_m2", "m2"),
    # el factor combinado (D-34)
    Quantity("mean_elevation_m", "m"),
    Quantity("grid_scale_factor", "-", "res.grid_scale_factor"),
    Quantity("ground_effect_pct", "%", "res.ground_effect_pct"),
    # res_ton_ (RF-011-15 a RF-011-18)
    Quantity("in_situ_m3", "m3"),
    Quantity("swell_m3", "m3", "res.unit_swell_m3"),
    Quantity("mass_t", "t", "res.unit_t"),
    Quantity("total_t", "t", "res.total_t"),
    Quantity("useful_m3", "m3", "res.useful_m3"),
    Quantity("waste_m3", "m3", "res.waste_m3"),
    Quantity("useful_t", "t", "res.useful_t"),
    Quantity("waste_t", "t", "res.waste_t"),
    Quantity("waste_ratio_m3", "m3/m3", "res.waste_ratio_m3"),
    Quantity("waste_ratio_t", "t/t", "res.waste_ratio_t"),
    Quantity("intrinsic_ratio_m3", "m3/m3", "res.intrinsic_ratio_m3"),
    Quantity("intrinsic_ratio_t", "t/t", "res.intrinsic_ratio_t"),
)})
"""Los datos de las tablas de ``res`` por nombre."""


def _optional_text(value: object, what: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{what} es un texto o None, no {value!r}")
    return value


def _optional_number(value: object, what: str) -> float | None:
    """``None`` o un float finito (nunca NaN ni infinito: RF-011-22)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{what} es un número o None, no {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} es un número finito o None, no {value!r}")
    return number


@dataclass(frozen=True, slots=True)
class Row:
    """Una fila de una tabla ``report`` de ``res`` (véase el módulo). Lo que no es una fila
    (un valor NaN o infinito, una unidad que no es de ``core.units``, un texto que no lo es) es
    un error del programa (:class:`ValueError`)."""

    domain: str
    bench_z0: float | None
    bench_z1: float | None
    unit: str | None
    component: str | None
    quantity: str
    value: float | None
    unit_code: str
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.domain, str):
            raise ValueError(f"el dominio de una fila es un texto, no {self.domain!r}")
        for name in ("bench_z0", "bench_z1", "value"):
            object.__setattr__(self, name, _optional_number(getattr(self, name), name))
        for name in ("unit", "component", "note"):
            _optional_text(getattr(self, name), name)
        if not isinstance(self.quantity, str) or not self.quantity:
            raise ValueError(f"el dato de una fila es un texto, no {self.quantity!r}")
        if self.unit_code not in UNITS:
            raise ValueError(f"«{self.unit_code}» no es una unidad de core.units")

    @property
    def bench(self) -> Bench:
        """La rodaja ``(z0, z1)`` o ``None`` (todas)."""
        if self.bench_z0 is None and self.bench_z1 is None:
            return None
        return (self.bench_z0, self.bench_z1)

    @property
    def notes(self) -> tuple[str, ...]:
        """Los códigos de las notas."""
        return () if not self.note else tuple(self.note.split(NOTE_SEPARATOR))

    def values(self) -> tuple[object, ...]:
        """Los valores en el orden de :data:`COLUMN_NAMES` (para :func:`insert_sql`)."""
        return (self.domain, self.bench_z0, self.bench_z1, self.unit, self.component,
                self.quantity, self.value, self.unit_code, self.note)

    @classmethod
    def from_values(cls, values: Sequence[Any]) -> Row:
        """La fila de unos valores en el orden de :data:`COLUMN_NAMES`."""
        return cls(*values)


def row(quantity: str, value: float | None, *, domain: str = ALL_DOMAINS, bench: Bench = None,
        unit: str | None = None, component: str | None = None,
        notes: Iterable[str] = ()) -> Row:
    """La fila del dato ``quantity`` (de :data:`QUANTITIES`, con su unidad) con ``value`` en
    ``domain``, ``bench``, ``unit`` y ``component``; ``notes``, códigos de nota."""
    found = QUANTITIES.get(quantity)
    if found is None:
        raise ValueError(f"«{quantity}» no es un dato de las tablas de res")
    low, high = (None, None) if bench is None else bench
    note = NOTE_SEPARATOR.join(notes) or None
    return Row(domain, low, high, unit, component, quantity, value, found.unit, note)


# --- La tabla en el GeoPackage -------------------------------------------------------------


def _table_name(name: str) -> str:
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ValueError(f"«{name}» no es un nombre de tabla")
    return name


def create_table(name: str) -> str:
    """La sentencia que crea la tabla ``name`` (``res_vol_<nombre>_<vNN>``…; plan §5.2.1)."""
    columns = ",\n  ".join(f"{column.name} {column.sql}" for column in COLUMNS)
    return (f"CREATE TABLE {_table_name(name)} (\n  fid INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            f"  {columns}\n)")


def insert_sql(name: str) -> str:
    """La sentencia que añade una fila (:meth:`Row.values`) a la tabla ``name``."""
    marks = ", ".join("?" for _ in COLUMNS)
    return f"INSERT INTO {_table_name(name)} ({', '.join(COLUMN_NAMES)}) VALUES ({marks})"


def read_rows(conn: sqlite3.Connection, name: str) -> tuple[Row, ...]:
    """Las filas de la tabla ``name``, en su orden (``fid``)."""
    query = f"SELECT {', '.join(COLUMN_NAMES)} FROM {_table_name(name)} ORDER BY fid"
    return tuple(Row.from_values(values) for values in conn.execute(query))


# --- Filtrar -------------------------------------------------------------------------------


class _Any:
    """Cualquier valor (un filtro que no filtra)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "ANY"


ANY: Final = _Any()
"""El filtro que no filtra (``None`` sí filtra: todas las rodajas, todas las unidades…)."""


def filter_rows(rows: Iterable[Row], *, domain: object = ANY, bench: object = ANY,
                unit: object = ANY, component: object = ANY,
                quantity: object = ANY) -> tuple[Row, ...]:
    """Las filas de ``rows`` con ese dominio, rodaja (``(z0, z1)`` o ``None``: todas), unidad,
    componente y dato (``None``: la columna vacía; :data:`ANY`, cualquiera), en su orden."""
    wanted = [(name, value) for name, value in (
        ("domain", domain), ("bench", bench), ("unit", unit), ("component", component),
        ("quantity", quantity)) if value is not ANY]
    return tuple(item for item in rows
                 if all(getattr(item, name) == value for name, value in wanted))


@dataclass(frozen=True, slots=True)
class Choices:
    """Lo que se puede elegir en los filtros del panel: los dominios (en su orden; ``'*'`` y
    ``''`` incluidos), las rodajas (de abajo arriba) y las unidades (en su orden)."""

    domains: tuple[str, ...]
    benches: tuple[tuple[float | None, float | None], ...]
    units: tuple[str, ...]


def _bench_order(bench: tuple[float | None, float | None]) -> tuple[float, float]:
    low, high = bench
    return (-math.inf if low is None else low, math.inf if high is None else high)


def choices(rows: Iterable[Row]) -> Choices:
    """Los dominios, las rodajas y las unidades que aparecen en ``rows``."""
    domains: dict[str, None] = {}
    benches: set[tuple[float | None, float | None]] = set()
    units: dict[str, None] = {}
    for item in rows:
        domains.setdefault(item.domain)
        bench = item.bench
        if bench is not None:
            benches.add(bench)
        if item.unit is not None:
            units.setdefault(item.unit)
    return Choices(tuple(domains), tuple(sorted(benches, key=_bench_order)), tuple(units))


# --- Volúmenes por unidad y toneladas ----------------------------------------------------------


def unit_volumes(rows: Iterable[Row]) -> tuple[UnitVolume, ...]:
    """Los m³ de desmonte de cada unidad por dominio y rodaja de la tabla de volúmenes (las
    filas ``volume_m3`` de una unidad entera), en su orden: lo que lee ``res.tonnage``."""
    return tuple(UnitVolume(item.domain, item.bench, item.unit, float(item.value))
                 for item in rows
                 if item.quantity == "volume_m3" and item.unit is not None
                 and item.component is None and item.value is not None)


def _bench_of(bench: Hashable) -> Bench:
    if bench is None:
        return None
    low, high = bench  # type: ignore[misc]
    return (low, high)


def tonnage_rows(result: TonnageResult) -> tuple[Row, ...]:
    """La tabla de las toneladas (``res_ton_``): por unidad y componente, su volumen, su
    volumen in situ, su esponjado (solo lo in situ) y sus toneladas; por dominio y rodaja, el
    total de toneladas, lo útil y lo estéril (m³ in situ y t) y las relaciones; por compuesta,
    su relación intrínseca. Lo que no se puede dar, sin valor y con su nota."""
    found: list[Row] = []
    lacking: dict[tuple[str, Hashable, object], dict[str, None]] = {}
    for item in result.rows:  # las notas de lo que pesa por sí mismo sin toneladas, por papel
        if item.role is not None and item.mass_t is None:
            lacking.setdefault((item.domain, item.bench, item.role), {}).update(
                dict.fromkeys(item.notes))

    def add(quantity: str, value: float | None, notes: Iterable[str], **where: Any) -> None:
        found.append(row(quantity, value, notes=() if value is not None else notes, **where))

    for item in result.rows:
        where = {"domain": item.domain, "bench": _bench_of(item.bench), "unit": item.unit,
                 "component": item.component}
        add("volume_m3", item.volume_m3, (), **where)
        add("in_situ_m3", item.in_situ_m3, item.notes, **where)
        if item.state is State.IN_SITU:
            add("swell_m3", item.swell_m3, item.notes, **where)
        add("mass_t", item.mass_t, item.notes, **where)
    for group in result.groups:
        where = {"domain": group.domain, "bench": _bench_of(group.bench)}
        add("total_t", group.total_t, group.total_notes, **where)
        add("useful_m3", group.useful_m3, (NO_SWELL,), **where)  # lo suelto sin K (D-28)
        add("waste_m3", group.waste_m3, (NO_SWELL,), **where)
        for quantity, value, role in (("useful_t", group.useful_t, Role.USEFUL),
                                      ("waste_t", group.waste_t, Role.WASTE)):
            add(quantity, value, lacking.get((group.domain, group.bench, role), {}), **where)
        add("waste_ratio_m3", group.ratio_m3.value, group.ratio_m3.notes, **where)
        add("waste_ratio_t", group.ratio_t.value, group.ratio_t.notes, **where)
    for intrinsic in result.intrinsic:
        add("intrinsic_ratio_m3", intrinsic.ratio_m3.value, intrinsic.ratio_m3.notes,
            unit=intrinsic.unit)
        add("intrinsic_ratio_t", intrinsic.ratio_t.value, intrinsic.ratio_t.notes,
            unit=intrinsic.unit)
    return tuple(found)
