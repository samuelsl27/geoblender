# SPDX-License-Identifier: GPL-3.0-or-later
"""Convenios de los sondeos: de los que declara la fuente a los internos (spec 005, T04;
RF-005-27, RF-005-28, RF-005-29; plan 005 §5.3.2, §5.4 y §5.6.12).

Los internos (spec §7): azimut desde el norte de **cuadrícula**, en sentido horario y en
[0, 360); inclinación desde la horizontal, **negativa hacia abajo** (−90 = vertical
descendente); leyes en la unidad del catálogo de su elemento.

- **Inclinación** (RF-005-28, :func:`to_internal_inclination`): positiva hacia abajo,
  θ = −v; desde la vertical (0 = hacia abajo), θ = φ − 90. La conversión es exacta respecto
  al decimal de la fuente (RF-005-02): φ − 90 se calcula con el decimal más corto de φ y se
  redondea una vez (8,04 → −81,96; restar en float64 daría −81,96000000000001).
- **Azimut** (RF-005-27, :func:`to_grid_azimuth`): A = (A_m + δ − γ) mod 360 si es magnético
  (δ, la declinación, positiva al este) y A = (A_m − γ) mod 360 si es geográfico; γ es la
  convergencia de cuadrícula en la boca (positiva al este del meridiano central, el contrato
  de ``gis.ports.CrsService.grid_convergence``), que da :func:`collar_convergence`. 360 → 0.
  Un azimut medido fuera de [0, 360] o no finito no se corrige: sale tal cual, y la
  validación lo ve (DH-E08).
- **Estaciones** (:func:`convert_surveys`): las de una fuente, a las internas, guardando en
  cada una el azimut medido, su referencia y las δ y γ aplicadas (D5 del plan). La estación
  de un sondeo declarado vertical (``StationSource.DECLARED_VERTICAL``) la crea el lector ya
  interna (0°, −90°, de cuadrícula) y no se convierte.
- **Leyes** (RF-005-29, :func:`convert_values`, :func:`convert_assays`): g/t, ppm, ppb y %
  con el factor exacto de ``core.units`` (``Fraction``): el resultado es, bit a bit, el de
  ``core.units.convert`` con cada valor (el float64 por el factor exacto, redondeado una
  vez), sin un bucle por valor. Se conservan el valor y la unidad originales
  (``reported_value``, ``reported_unit``).

Nada modifica sus entradas: cada función devuelve arrays o columnas nuevas. Un número en
precisión simple (``float32``) no entra (RF-005-02). Python puro y numpy (ADR-0004);
``gis.ports`` solo se nombra en las anotaciones (no se importa ``gis`` al importar esto).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from fractions import Fraction
from typing import TYPE_CHECKING

import numpy as np

from ..core import units
from ..core.georef import CrsRef
from .model import (
    DECLINATION_LIMIT_DEG,
    AssayColumns,
    AzimuthRef,
    InclinationConvention,
    SourceDeclaration,
    StationSource,
    SurveyColumns,
    name_key,
)

if TYPE_CHECKING:
    from ..gis.ports import CrsService

__all__ = [
    "FULL_TURN_DEG",
    "collar_convergence",
    "convert_assays",
    "convert_surveys",
    "convert_values",
    "to_grid_azimuth",
    "to_internal_inclination",
]

FULL_TURN_DEG = 360.0
_RIGHT_ANGLE = Fraction(90)
_EXACT_FLOAT_INT = 2**53  # un entero hasta aquí es exacto en float64


def _float64(values: object, what: str) -> np.ndarray:
    """Una copia en float64 de ``values`` (números; nunca float32: RF-005-02)."""
    array = np.asarray(values)
    if array.dtype.kind == "f" and array.dtype != np.float64:
        raise TypeError(f"{what} van en float64, no en {array.dtype} (RF-005-02: nunca en "
                        f"precisión simple)")
    if array.dtype.kind not in "fiu":
        raise TypeError(f"{what} son números (float64), no {array.dtype}")
    return array.astype(np.float64)


def _member(value: object, kind: type, what: str) -> object:
    """El miembro de la enumeración ``kind`` que es ``value`` (su texto vale); sin declarar
    (``None``) o desconocido, ``ValueError``: nada se supone (RF-005-07)."""
    if value is None:
        raise ValueError(f"{what}: no está declarado y no se supone (RF-005-07)")
    try:
        return kind(value)
    except ValueError:
        raise ValueError(f"{what}: {value!r} no es uno de "
                         f"{[str(member) for member in kind]}") from None


# --- Inclinación (RF-005-28) -------------------------------------------------------------------


def _from_vertical(values: np.ndarray) -> np.ndarray:
    """φ − 90 con el decimal más corto de cada φ (el de la fuente), redondeado una vez."""
    out = values - 90.0
    finite = np.flatnonzero(np.isfinite(values))
    if finite.size:
        exact = [float(Fraction(repr(value)) - _RIGHT_ANGLE)
                 for value in values[finite].tolist()]
        out[finite] = exact
    return out


def to_internal_inclination(values: np.ndarray, convention: InclinationConvention | str
                            ) -> np.ndarray:
    """Las inclinaciones ``values`` (grados, en el convenio ``convention`` de la fuente)
    desde la horizontal y negativas hacia abajo (RF-005-28): ``NEGATIVE_DOWN``, tal cual;
    ``POSITIVE_DOWN``, −v; ``FROM_VERTICAL`` (0 = vertical hacia abajo), φ − 90 exacto respecto
    al decimal de la fuente. Sin −0,0; NaN sigue ausente; lo que cae fuera de [−90, 90] sale
    fuera (DH-E08). ``ValueError`` sin convenio declarado."""
    convention = _member(convention, InclinationConvention, "El convenio de la inclinación")
    array = _float64(values, "las inclinaciones")
    if convention is InclinationConvention.POSITIVE_DOWN:
        array = -array
    elif convention is InclinationConvention.FROM_VERTICAL:
        array = _from_vertical(array)
    return array + 0.0  # −0,0 → 0,0


# --- Azimut (RF-005-27) ------------------------------------------------------------------------


def _declination(ref: AzimuthRef, declination_deg: float | None) -> float:
    if ref is not AzimuthRef.MAGNETIC:
        if declination_deg is not None:
            raise ValueError(f"la declinación solo se aplica a un azimut magnético, no a uno "
                             f"«{ref}»")
        return 0.0
    if declination_deg is None:
        raise ValueError("un azimut magnético necesita su declinación declarada (RF-005-07)")
    value = float(declination_deg)
    if not -DECLINATION_LIMIT_DEG <= value <= DECLINATION_LIMIT_DEG:
        raise ValueError(f"la declinación va de −180° a 180° (positiva al este), no {value}")
    return value


def to_grid_azimuth(
    measured: np.ndarray,
    ref: AzimuthRef | str,
    declination_deg: float | None,
    convergence_deg: np.ndarray | float | None,
) -> np.ndarray:
    """Los azimutes medidos ``measured`` (grados, referidos a ``ref``) desde el norte de
    cuadrícula, en [0, 360) (RF-005-27): de cuadrícula, A_m (360 → 0); geográfico,
    (A_m − γ) mod 360; magnético, (A_m + δ − γ) mod 360, con δ = ``declination_deg``
    (positiva al este) y γ = ``convergence_deg`` (la de la boca de cada estación, o una para
    todas). Un A_m fuera de [0, 360] o no finito sale tal cual (DH-E08). ``ValueError`` sin
    referencia, con declinación en uno que no es magnético, sin ella en uno magnético o sin
    convergencia (o con otra forma) en uno magnético o geográfico."""
    ref = _member(ref, AzimuthRef, "La referencia del azimut")
    values = _float64(measured, "los azimutes")
    delta = _declination(ref, declination_deg)
    if ref is AzimuthRef.GRID:
        corrected = values
    else:
        if convergence_deg is None:
            raise ValueError(f"un azimut «{ref}» necesita la convergencia de cuadrícula de su "
                             f"boca")
        gamma = _float64(convergence_deg, "las convergencias")
        if gamma.ndim and gamma.shape != values.shape:
            raise ValueError(f"una convergencia por azimut: {gamma.shape} frente a "
                             f"{values.shape}")
        corrected = values + delta - gamma if delta else values - gamma
    valid = np.isfinite(values) & (values >= 0.0) & (values <= FULL_TURN_DEG)
    result = values.copy()
    turned = np.mod(np.broadcast_to(corrected, values.shape)[valid], FULL_TURN_DEG)
    turned[turned == FULL_TURN_DEG] = 0.0  # un resto negativo diminuto redondea a 360
    result[valid] = turned
    return result + 0.0


def collar_convergence(xy_abs: np.ndarray, service: CrsService, crs: CrsRef) -> np.ndarray:
    """La convergencia de cuadrícula γ (grados, float64 (n,)) de ``crs`` en cada boca
    ``xy_abs`` (float64 (n, 2), ABSOLUTAS), que da ``service.grid_convergence`` (el
    ``gis.ports.CrsService`` de la 006) en una sola llamada con las bocas de X e Y finitas;
    las demás (DH-E02), NaN. Sin bocas, no llama al servicio. ``ValueError`` si ``xy_abs`` no
    es (n, 2) o el servicio no da una γ por boca."""
    if not isinstance(crs, CrsRef):
        raise TypeError(f"el CRS es un CrsRef del catálogo, no {crs!r}")
    xy = _float64(xy_abs, "las coordenadas de las bocas")
    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError(f"las bocas son (n, 2) (X, Y absolutas), no {xy.shape}")
    gamma = np.full(len(xy), math.nan)
    finite = np.isfinite(xy).all(axis=1)
    count = int(finite.sum())
    if count:
        found = np.asarray(service.grid_convergence(crs, xy[finite]), dtype=np.float64)
        if found.shape != (count,):
            raise ValueError(f"el servicio de CRS dio {found.shape} convergencias para "
                             f"{count} bocas")
        gamma[finite] = found
    return gamma


# --- Estaciones de desviación (RF-005-27, RF-005-28) -------------------------------------------


def _row_convergence(surveys: SurveyColumns, convergence_deg: object) -> np.ndarray:
    """La γ de la boca de cada estación (NaN sin boca, DH-E04)."""
    if convergence_deg is None:
        raise ValueError("un azimut magnético o geográfico necesita la convergencia de "
                         "cuadrícula de cada boca (collar_convergence)")
    gamma = _float64(convergence_deg, "las convergencias de las bocas")
    if gamma.ndim != 1:
        raise ValueError(f"una convergencia por boca, (n,), no {gamma.shape}")
    hole = surveys.hole
    linked = hole >= 0
    if linked.any() and int(hole.max()) >= len(gamma):
        raise ValueError(f"las estaciones apuntan a la boca {int(hole.max())} y solo hay "
                         f"{len(gamma)} convergencias")
    rows = np.full(len(hole), math.nan)
    rows[linked] = gamma[hole[linked]]
    return rows


def convert_surveys(
    surveys: SurveyColumns,
    declaration: SourceDeclaration,
    convergence_deg: np.ndarray | None = None,
) -> SurveyColumns:
    """Las estaciones ``surveys`` de una fuente (en los convenios de ``declaration``) en los
    internos (RF-005-27, RF-005-28): ``azimuth`` de cuadrícula, ``inclination`` desde la
    horizontal y negativa hacia abajo, y en cada una ``azimuth_measured`` (el que venía),
    ``azimuth_ref`` (la declarada), ``declination_deg`` (δ, solo si es magnético) y
    ``convergence_deg`` (γ de su boca, si es magnético o geográfico; ``convergence_deg`` es
    una por boca, la de :func:`collar_convergence`). Las estaciones de un sondeo declarado
    vertical ya son internas: quedan de cuadrícula, sin δ ni γ. Una estación sin boca no
    tiene γ: su azimut magnético o geográfico queda NaN. ``ValueError`` si falta una
    declaración (RF-005-07) o la convergencia que hace falta."""
    if not isinstance(surveys, SurveyColumns):
        raise TypeError(f"las estaciones son un SurveyColumns, no {surveys!r}")
    if not isinstance(declaration, SourceDeclaration):
        raise TypeError(f"la declaración es un SourceDeclaration, no {declaration!r}")
    sources = SurveyColumns.code_values("source")
    refs = SurveyColumns.code_values("azimuth_ref")
    declared = surveys.source == sources.index(StationSource.DECLARED_VERTICAL)
    measured = surveys.azimuth.copy()
    azimuth = surveys.azimuth.copy()
    inclination = surveys.inclination.copy()
    ref_code = np.full(len(surveys), refs.index(AzimuthRef.GRID), dtype=np.int8)
    declination = np.full(len(surveys), math.nan)
    convergence = np.full(len(surveys), math.nan)
    convert = ~declared
    if convert.any():
        ref = _member(declaration.azimuth_ref, AzimuthRef, "La referencia del azimut")
        gamma = None if ref is AzimuthRef.GRID else _row_convergence(surveys, convergence_deg)
        azimuth[convert] = to_grid_azimuth(
            surveys.azimuth[convert], ref, declaration.declination_deg,
            None if gamma is None else gamma[convert])
        inclination[convert] = to_internal_inclination(surveys.inclination[convert],
                                                       declaration.inclination_convention)
        ref_code[convert] = refs.index(ref)
        if ref is AzimuthRef.MAGNETIC:
            declination[convert] = declaration.declination_deg
        if gamma is not None:
            convergence[convert] = gamma[convert]
    return surveys.take(
        np.arange(len(surveys)),
        azimuth=azimuth,
        inclination=inclination,
        azimuth_measured=measured,
        azimuth_ref=ref_code,
        declination_deg=declination,
        convergence_deg=convergence,
    )


# --- Leyes (RF-005-29) -------------------------------------------------------------------------


def _ratio(from_unit: str, to_unit: str) -> Fraction:
    """El factor exacto de ``from_unit`` a ``to_unit``; el ``UnitError`` de ``core.units``
    si alguna no está en su catálogo o son de magnitudes distintas."""
    units.convert(1, from_unit, to_unit)  # comprueba las dos unidades y su magnitud
    return units.get_unit(from_unit).factor / units.get_unit(to_unit).factor


def convert_values(values: np.ndarray, from_unit: str, to_unit: str) -> np.ndarray:
    """``values`` (float64; NaN = ausente) en ``from_unit``, expresados en ``to_unit`` con el
    factor exacto de ``core.units`` (RF-005-29): bit a bit lo que da ``core.units.convert``
    con cada valor (el factor es una potencia de 10 entre g/t, ppm, ppb y %: una división o
    una multiplicación de IEEE, redondeada una vez). ``core.units.UnitError`` si una unidad
    no está en el catálogo, si son de magnitudes distintas o si un valor no cabe en un
    float64 al convertirlo."""
    array = _float64(values, "los valores")
    ratio = _ratio(from_unit, to_unit)
    if ratio == 1:
        return array
    if ratio.numerator == 1 and ratio.denominator < _EXACT_FLOAT_INT:
        result = array / float(ratio.denominator) + 0.0
    elif ratio.denominator == 1 and ratio.numerator < _EXACT_FLOAT_INT:
        with np.errstate(over="ignore"):  # un valor que no cabe: el UnitError de abajo
            result = array * float(ratio.numerator) + 0.0
    else:  # otro factor: uno a uno con core.units (no hay ninguno así entre las leyes)
        result = np.array([units.convert(value, from_unit, to_unit) if math.isfinite(value)
                           else value for value in array.ravel().tolist()],
                          dtype=np.float64).reshape(array.shape)
    overflow = np.isfinite(array) & ~np.isfinite(result)
    if overflow.any():
        units.convert(float(array[overflow][0]), from_unit, to_unit)  # su UnitError
    return result


def _shortest(value: float) -> str:
    """El decimal más corto de ``value`` con punto (lo que se guarda como valor original)."""
    return np.format_float_positional(value, unique=True, trim="-")


def _targets(catalog_units: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(catalog_units, Mapping):
        raise TypeError(f"las unidades del catálogo son elemento → unidad, no "
                        f"{catalog_units!r}")
    targets: dict[str, str] = {}
    for code, unit in catalog_units.items():
        key = name_key(code)
        if key in targets:
            raise ValueError(f"las unidades del catálogo repiten el elemento «{code}»")
        targets[key] = unit
    return targets


def convert_assays(assays: AssayColumns, catalog_units: Mapping[str, str]) -> AssayColumns:
    """Los análisis ``assays`` con cada valor en la unidad de su elemento en el catálogo
    (``catalog_units``: código → unidad, sin distinguir mayúsculas ni espacios exteriores)
    (RF-005-29): ``value`` convertido con :func:`convert_values` (también los límites «<x» y
    «>x», que son el valor) y ``unit`` la del catálogo, conservando la unidad original en
    ``reported_unit`` (la que ya tuviera, si la tiene) y el valor original en
    ``reported_value`` (si no traía texto, el decimal más corto del valor de la fuente). No
    se tocan los de un elemento sin catálogo (DH-E11), los que ya están en su unidad ni los
    que no se pueden convertir (texto, una unidad fuera del catálogo de ``core.units`` o de
    otra magnitud: DH-W07)."""
    if not isinstance(assays, AssayColumns):
        raise TypeError(f"los análisis son un AssayColumns, no {assays!r}")
    targets = _targets(catalog_units)
    value = assays.value.copy()
    unit = assays.unit.copy()
    reported_value = assays.reported_value.copy()
    reported_unit = assays.reported_unit.copy()
    if len(assays):
        elements, element_of = np.unique(assays.element, return_inverse=True)
        sources, source_of = np.unique(assays.unit, return_inverse=True)
        for e, element in enumerate(elements.tolist()):
            target = targets.get(name_key(element))
            if target is None:
                continue
            rows_of_element = element_of == e
            for s, source in enumerate(sources.tolist()):
                if source == target or not _convertible(source, target):
                    continue
                rows = np.flatnonzero(rows_of_element & (source_of == s))
                if not rows.size:
                    continue
                original = assays.value[rows]
                value[rows] = convert_values(original, source, target)
                unit[rows] = target
                for row, number in zip(rows.tolist(), original.tolist(), strict=True):
                    if reported_unit[row] is None:
                        reported_unit[row] = source
                    if reported_value[row] is None and math.isfinite(number):
                        reported_value[row] = _shortest(number)
    return assays.take(np.arange(len(assays)), value=value, unit=unit,
                       reported_value=reported_value, reported_unit=reported_unit)


def _convertible(source: str, target: str) -> bool:
    """Si ``core.units`` convierte de ``source`` a ``target`` (las dos en su catálogo y de la
    misma magnitud)."""
    try:
        _ratio(source, target)
    except units.UnitError:
        return False
    return True
