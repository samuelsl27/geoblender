# SPDX-License-Identifier: GPL-3.0-or-later
"""Momentos de extracción (spec 011, T16; RF-011-19, RF-011-22; plan 011 §5.2.1, A13, D-33).

Una cubicación por momentos compara una lista de cubicaciones de la versión (los **momentos**:
explotación, desdoblado, stock…; como mucho :data:`MAX_STAGES`) con la cubicación **directa**,
desde sus tablas de volúmenes (``res_vol_``; D-33: sin releer las superficies, que sería otra
implementación del volumen). :func:`stages` compara, de cada una, tres cosas (A13):

- el desmonte total (``cut_m3``), el terraplén total (``fill_m3``) y el desmonte de cada unidad
  de la directa (``volume_m3`` de la unidad; un momento que no la tiene, otra columna o ninguna,
  no le aporta nada: nada se reparte por su cuenta);
- de cada una, su **suma** en los momentos (``math.fsum``: la suma exacta redondeada una vez, así
  que unos momentos que parten la directa suman exactamente lo mismo), el valor de la directa,
  la **diferencia** (suma − directa, m³) y la diferencia en % **sobre la directa** (sin valor, con
  la nota :data:`NO_DIRECT_VOLUME`, si la directa no tiene ese volumen y los momentos sí).

Avisos (``reserves.volumes.Notice``): ``res.stages_mismatch`` por cada comparación cuya diferencia
en % pasa de la tolerancia (``res.stages_tolerance_pct``; estrictamente: justo en ella, no), con
la suma, la directa y la diferencia en m³ y en %; ``res.stages_materials_differ`` por cada momento
cubicado con otra columna de materiales que la directa (otro hash de ``res_materials``, o sin
unidades). **Ninguna cifra se ajusta** (RF-011-19): cada momento sale tal cual, y la suma, la de
los momentos.

**Tabla** (``res_stg_``, :class:`~reserves.table.StageRow`): por momento, su desmonte, su
terraplén y el desmonte de cada una de sus unidades (``stage`` = su nombre); después, por cada
comparación, la suma, la directa, la diferencia y la diferencia en % (``stage`` vacío; los datos
``stages_*`` del desmonte y ``stages_fill_*`` del terraplén, ``reserves.table.QUANTITIES``), la de
% con la nota :data:`OVER_TOLERANCE` si pasa de la tolerancia. **Cifras** (RF-011-22; CALCULADO,
finitas): ``res.stages_sum_m3``, ``res.stages_diff_m3`` y ``res.stages_diff_pct`` (si tiene valor)
de cada comparación, con el ámbito ``{"stages": nombre, "volume": "Desmonte" | "Terraplén"}`` y,
en una unidad, ``"unit"`` (su código). Python puro (nivel 9).
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..core.i18n import format_number
from ..core.provenance.figures import FigureSpec, ScopeValue
from .table import ALL_DOMAINS, Row, StageRow, row
from .volumes import Notice

__all__ = [
    "CUT",
    "CUT_SCOPE",
    "FILL",
    "FILL_SCOPE",
    "MAX_STAGES",
    "NO_DIRECT_VOLUME",
    "OVER_TOLERANCE",
    "SCOPE",
    "UNIT_VOLUME",
    "Comparison",
    "StageTable",
    "StagesResult",
    "check_names",
    "stages",
]

MAX_STAGES = 10
"""Los momentos de una cubicación por momentos, como mucho (spec §7: hasta 10)."""
CUT = "cut_m3"
"""El desmonte total de una tabla de volúmenes."""
FILL = "fill_m3"
"""El terraplén total."""
UNIT_VOLUME = "volume_m3"
"""El desmonte de una unidad."""
SCOPE = "stages"
"""El nombre del ámbito de las cifras de una cubicación por momentos (su nombre)."""
CUT_SCOPE = "Desmonte"
"""El valor del ámbito ``volume`` de las comparaciones del desmonte (total o de una unidad)."""
FILL_SCOPE = "Terraplén"
"""El de la comparación del terraplén."""
NO_DIRECT_VOLUME = "res.note_stages_no_direct"
"""La nota de una diferencia en % que no se puede dar: la directa no tiene ese volumen."""
OVER_TOLERANCE = "res.note_stages_over_tolerance"
"""La nota de una diferencia en % que pasa de la tolerancia."""

_MISMATCH = "res.stages_mismatch"
_MATERIALS = "res.stages_materials_differ"
_PREFIXES = {CUT: "stages_", FILL: "stages_fill_", UNIT_VOLUME: "stages_"}


def check_names(moments: Sequence[str], direct: str) -> tuple[tuple[str, ...], str]:
    """Los nombres de los momentos y de la directa, comprobados: de 1 a :data:`MAX_STAGES`
    momentos, cada uno un nombre no vacío distinto de los demás y de la directa. Lo que no lo
    es, un error del programa (:class:`ValueError`; el diálogo no deja pedirlo)."""
    names = tuple(moments)
    for name in (*names, direct):
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"una cubicación de los momentos tiene nombre, no {name!r}")
    if not 1 <= len(names) <= MAX_STAGES:
        raise ValueError(f"una cubicación por momentos tiene de 1 a {MAX_STAGES} momentos, no "
                         f"{len(names)}")
    if len(set(names)) != len(names):
        raise ValueError(f"un momento se repite: {list(names)}")
    if direct in names:
        raise ValueError(f"la cubicación directa «{direct}» no puede ser también un momento")
    return names, direct


@dataclass(frozen=True, slots=True, eq=False)
class StageTable:
    """Una cubicación de los momentos (o la directa): su nombre, las filas de su tabla
    ``res_vol_`` (``reserves.table.Row``) y el hash de contenido de la columna de materiales
    con que se cubicó (``None``: sin unidades)."""

    name: str
    rows: tuple[Row, ...]
    materials: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"una cubicación de los momentos tiene nombre, no {self.name!r}")
        rows = tuple(self.rows)
        for item in rows:
            if not isinstance(item, Row):
                raise TypeError(f"una fila de «{self.name}» es una Row, no {item!r}")
        object.__setattr__(self, "rows", rows)
        if self.materials is not None and not isinstance(self.materials, str):
            raise TypeError(f"el hash de la columna de «{self.name}» es un texto o None")

    def _whole(self, item: Row) -> bool:
        return item.domain == ALL_DOMAINS and item.bench is None and item.component is None

    def total(self, quantity: str) -> float:
        """El total de ``quantity`` (desmonte o terraplén) en todos los dominios y rodajas;
        :class:`ValueError` si la tabla no lo tiene (no es de volúmenes)."""
        for item in self.rows:
            if self._whole(item) and item.unit is None and item.quantity == quantity:
                if item.value is None:
                    break
                return float(item.value)
        raise ValueError(f"la tabla de «{self.name}» no tiene el total «{quantity}»: no es una "
                         "tabla de volúmenes (res_vol_)")

    def units(self) -> dict[str, float]:
        """El desmonte de cada unidad (código → m³), en el orden de la columna."""
        return {str(item.unit): float(item.value) for item in self.rows
                if self._whole(item) and item.unit is not None and item.quantity == UNIT_VOLUME
                and item.value is not None}


@dataclass(frozen=True, slots=True)
class Comparison:
    """Una comparación de los momentos con la directa: el dato (:data:`CUT`, :data:`FILL` o
    :data:`UNIT_VOLUME`) y su unidad (``None`` en los totales); el valor de cada momento, su
    suma, el de la directa, la diferencia (suma − directa, m³) y en % sobre la directa
    (``None`` si no se puede dar) y si pasa de la tolerancia."""

    quantity: str
    unit: str | None
    moments: tuple[float, ...]
    sum_m3: float
    direct_m3: float
    diff_m3: float
    diff_pct: float | None
    over: bool


@dataclass(frozen=True, slots=True, eq=False)
class StagesResult:
    """El resultado de :func:`stages`: su nombre, los momentos y la directa (sus nombres), la
    tolerancia (%), las comparaciones, las filas de la tabla ``res_stg_``, las cifras y los
    avisos."""

    name: str
    moments: tuple[str, ...]
    direct: str
    tolerance_pct: float
    comparisons: tuple[Comparison, ...]
    rows: tuple[StageRow, ...]
    figures: tuple[FigureSpec, ...]
    warnings: tuple[Notice, ...]

    def comparison(self, quantity: str = CUT, unit: str | None = None) -> Comparison:
        """La comparación de ``quantity`` (y ``unit``); :class:`KeyError` si no está."""
        for item in self.comparisons:
            if item.quantity == quantity and item.unit == unit:
                return item
        raise KeyError(f"«{self.name}» no compara «{quantity}» ({unit})")


def _tolerance(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"la tolerancia de los momentos es un número (%), no {value!r}")
    number = float(value)
    if not math.isfinite(number) or not 0.0 < number <= 100.0:
        raise ValueError(f"la tolerancia de los momentos está en (0; 100] %, no {value!r}")
    return number


def _compare(quantity: str, unit: str | None, moments: tuple[float, ...], direct: float,
             tolerance: float) -> Comparison:
    total = math.fsum(moments)
    diff = total - direct
    pct: float | None
    if direct != 0.0:
        pct = 100.0 * diff / direct
    else:
        pct = 0.0 if diff == 0.0 else None
    over = pct is None or abs(pct) > tolerance
    return Comparison(quantity, unit, moments, total, direct, diff, pct, over)


def _label(item: Comparison, names: Mapping[str, str]) -> str:
    """Lo que compara ``item``, para el aviso: «Desmonte», «Terraplén», «Desmonte de «X»»."""
    if item.quantity == FILL:
        return FILL_SCOPE
    if item.unit is None:
        return CUT_SCOPE
    return f"{CUT_SCOPE} de «{names.get(item.unit, item.unit)}»"


def _figure(key: str, value: float, unit: str, scope: Mapping[str, ScopeValue]) -> FigureSpec:
    if not math.isfinite(value):  # inalcanzable: los valores de una tabla son finitos
        raise ValueError(f"la cifra «{key}» ({dict(scope)}) no es un número finito: {value!r}")
    return FigureSpec(key, value, unit, scope=dict(scope))


def stages(moments: Sequence[StageTable], direct: StageTable, *, name: str,
           tolerance_pct: float, unit_names: Mapping[str, str] | None = None) -> StagesResult:
    """Compara los momentos ``moments`` con la directa ``direct`` (véase el módulo) en la
    cubicación por momentos ``name``, con la tolerancia ``tolerance_pct`` (%). ``unit_names``,
    el nombre visible de cada unidad para los avisos (por defecto, su código).

    Unos momentos mal pedidos (ninguno, más de :data:`MAX_STAGES`, uno repetido, la directa
    entre ellos), una tolerancia fuera de (0; 100] % o una tabla que no es de volúmenes son
    errores del programa (:class:`ValueError`)."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"una cubicación por momentos tiene nombre, no {name!r}")
    tables = tuple(moments)
    for item in (*tables, direct):
        if not isinstance(item, StageTable):
            raise TypeError(f"un momento o la directa es una StageTable, no {item!r}")
    check_names([item.name for item in tables], direct.name)
    tolerance = _tolerance(tolerance_pct)
    names = {} if unit_names is None else dict(unit_names)

    comparisons = [
        _compare(quantity, None, tuple(item.total(quantity) for item in tables),
                 direct.total(quantity), tolerance)
        for quantity in (CUT, FILL)
    ]
    units = [item.units() for item in tables]
    for code, value in direct.units().items():
        comparisons.append(_compare(UNIT_VOLUME, code, tuple(found.get(code, 0.0)
                                                             for found in units),
                                    value, tolerance))

    rows: list[StageRow] = []
    for item, found in zip(tables, units, strict=True):
        rows.append(StageRow(item.name, row(CUT, item.total(CUT))))
        rows.append(StageRow(item.name, row(FILL, item.total(FILL))))
        rows.extend(StageRow(item.name, row(UNIT_VOLUME, value, unit=code))
                    for code, value in found.items())
    figures: list[FigureSpec] = []
    for item in comparisons:
        prefix = _PREFIXES[item.quantity]
        notes = (() if item.diff_pct is not None else (NO_DIRECT_VOLUME,)) + (
            (OVER_TOLERANCE,) if item.over else ())
        for quantity, value, note in (("sum_m3", item.sum_m3, ()),
                                      ("direct_m3", item.direct_m3, ()),
                                      ("diff_m3", item.diff_m3, ()),
                                      ("diff_pct", item.diff_pct, notes)):
            rows.append(StageRow(None, row(prefix + quantity, value, unit=item.unit,
                                           notes=note)))
        scope: dict[str, ScopeValue] = {
            SCOPE: name, "volume": FILL_SCOPE if item.quantity == FILL else CUT_SCOPE}
        if item.unit is not None:
            scope["unit"] = item.unit
        figures.append(_figure("res.stages_sum_m3", item.sum_m3, "m3", scope))
        figures.append(_figure("res.stages_diff_m3", item.diff_m3, "m3", scope))
        if item.diff_pct is not None:
            figures.append(_figure("res.stages_diff_pct", item.diff_pct, "%", scope))

    warnings = [Notice(_MATERIALS, {"name": item.name, "direct": direct.name})
                for item in tables if item.materials != direct.materials]
    warnings += [Notice(_MISMATCH, {
        "quantity": _label(item, names), "sum": format_number(item.sum_m3, 1),
        "direct": direct.name, "direct_volume": format_number(item.direct_m3, 1),
        "difference": format_number(item.diff_m3, 1),
        "value": None if item.diff_pct is None else format_number(item.diff_pct, 2),
        "tolerance": tolerance,
    }) for item in comparisons if item.over]
    return StagesResult(name, tuple(item.name for item in tables), direct.name, tolerance,
                        tuple(comparisons), tuple(rows), tuple(figures), tuple(warnings))
