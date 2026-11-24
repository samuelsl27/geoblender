# SPDX-License-Identifier: GPL-3.0-or-later
"""«Cambiar parámetro…» de los valores de la corta que no son de la entidad, con las reglas de crear (spec 018, T41; hallazgo F-1 de la T39; RF-015-08, RF-018-04, RF-018-06,
RF-018-07, RF-018-08, RF-018-15).

«Cambiar parámetro…» (``geoblender.core_set_parameter``) solo cruzaba con las demás reglas las claves ``des.pit.{e}.<valor>`` de la entidad
(:func:`~design.entity_store.check_parameter_change`); tres familias de la corta se escribían con la sola comprobación de tipo y rango de su definición, que es el análogo de lo que
la 017 arregló con los perfiles de pista (:func:`~design.road_profiles.check_profile_change`, T40):

- **un valor de un rango de una roseta** (``des.rose.{r}.r{i}.<valor>``): con el valor nuevo, el rango y la roseta entera siguen siendo los que admite crear
  (:func:`~design.pit_rose.check_rose`: ``desde`` < ``hasta`` y de 0 a 360° sin huecos ni solapes), cuando la roseta tiene ya todos los valores de todos sus rangos;
- **un valor de una definición de rampa** (``des.pitramp.{q}.<valor>``): el valor en su rango y, al cambiar la pendiente de diseño o el perfil de pista, ``g ≤ pd`` del perfil de
  pista elegido (:func:`~design.pit_ramp_def.check_ramp_gradient`);
- **un valor por sector** (``des.pit.{e}.<valor>.{s}``): el perfil de banco del sector es de la altura y el ancla del base y de los demás sectores
  (``des.pit_profiles_differ``; RF-018-06), el número de bancos por berma es el de la corta (``des.pit_sector_n_berm``; RF-018-08) y la roseta existe en el proyecto
  (``des.pit_rose_unknown``).

Todo **antes de que la orden escriba** y **sin escribir nada**: solo lee. Los valores efectivos son los de la versión y, si no, los del proyecto (RF-009-24); con ``version`` ``None``
(el cambio es del proyecto) solo los del proyecto, y las reglas de un sector, que es de una versión, no se aplican. Lo que **no** se comprueba aquí: lo que el cambio de un valor
causa en otra definición que lo usa (la pendiente máxima de un perfil de pista frente a las rampas que lo usan, un perfil de banco frente a las cortas que lo asignan): lo dice el
cálculo al preparar la corta, sin escribir nada, como siempre. Python puro; lo importan las órdenes al usarlo, no ``bl`` al registrarse.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterStore
from . import pipeline
from .messages import DesignError
from .model import BenchParam
from .params import (
    PitParam,
    PitRampParam,
    PitSectorParam,
    RoadProfileParam,
    RoseParam,
    bench_key,
    check_pitramp_value,
    check_rose_value,
    entity_key,
    pit_sector_key,
    road_profile_key,
    rose_key,
    segment_code,
)
from .pit_ramp_def import check_ramp_gradient
from .pit_rose import check_rose

__all__ = [
    "check_pit_ramp_change",
    "check_pit_rose_change",
    "check_pit_sector_change",
    "check_ramp_edit",
    "check_rose_edit",
    "parse_ramp_key",
    "parse_rose_key",
    "parse_sector_key",
]

_ROSE_KEY = re.compile(r"des\.rose\.([a-z][a-z0-9_]*)\.(r[0-9]+)\.(" + "|".join(item.value for item in RoseParam) + r")")
_RAMP_KEY = re.compile(r"des\.pitramp\.([a-z][a-z0-9_]*)\.(" + "|".join(item.value for item in PitRampParam) + r")")
_SECTOR_KEY = re.compile(r"des\.pit\.([a-z]{2,5}_[0-9]{3,})\.(" + "|".join(item.value for item in PitSectorParam) + r")\.([a-z][a-z0-9_]*)")


def parse_rose_key(key: object) -> tuple[str, str, RoseParam] | None:
    """El código de la roseta, el rango (``r1``) y el valor de la clave ``des.rose.{r}.r{i}.<valor>``; ``None`` si ``key`` no es de un valor de un rango de una roseta."""
    found = _ROSE_KEY.fullmatch(key) if isinstance(key, str) else None
    return None if found is None else (found.group(1), found.group(2), RoseParam(found.group(3)))


def parse_ramp_key(key: object) -> tuple[str, PitRampParam] | None:
    """El código de la rampa y el valor de la clave ``des.pitramp.{q}.<valor>``; ``None`` si ``key`` no es de un valor de una definición de rampa."""
    found = _RAMP_KEY.fullmatch(key) if isinstance(key, str) else None
    return None if found is None else (found.group(1), PitRampParam(found.group(2)))


def parse_sector_key(key: object) -> tuple[str, PitSectorParam, str] | None:
    """El código de la corta, el valor y el sector (``perimeter__`` el perímetro) de la clave ``des.pit.{e}.<valor>.{s}``; ``None`` si ``key`` no es de un valor por sector de una corta."""
    found = _SECTOR_KEY.fullmatch(key) if isinstance(key, str) else None
    if found is None:
        return None
    try:
        code = segment_code(found.group(1))
    except ValueError:
        return None
    return code, PitSectorParam(found.group(2)), found.group(3)


# --- Lo puro: las reglas con los valores ya leídos -------------------------------------------------------------------------------------


def check_rose_edit(name: str, code: str, index: str, param: RoseParam | str, value: object, ranges: Mapping[str, Mapping[str, object]]) -> None:
    """El valor ``value`` de ``param`` del rango ``index`` de la roseta ``name`` (de código ``code``) con ``ranges`` (por rango: sus cuatro valores por nombre; el que falta, ausente o
    ``None``): el valor en su rango (``des.pit_rose_value_range``) y, si con él están **todos** los valores de **todos** los rangos, la roseta entera como la admite crear
    (:func:`~design.pit_rose.check_rose`: ``desde`` < ``hasta``, de 0 a 360° sin huecos ni solapes: ``des.pit_rose_gap``, ``des.pit_rose_overlap``). Sin valor (``None``) no hace nada
    (lo dice la definición del parámetro). RF-018-04, RF-018-07."""
    if value is None:
        return
    param = RoseParam(param)
    checked = check_rose_value(name, code, index, param, value)
    merged = {number: dict(values) for number, values in ranges.items()}
    merged.setdefault(index, {})[param.value] = checked
    if any(values.get(item.value) is None for values in merged.values() for item in RoseParam):
        return  # una roseta a medio escribir no tiene con qué cruzarse
    check_rose(name, code, [merged[number] for number in sorted(merged, key=lambda text: int(text[1:]))])


def check_ramp_edit(name: str, code: str, param: PitRampParam | str, value: object, current: Mapping[str, object],
                    road_profile: Callable[[str], tuple[str, float | None]]) -> None:
    """El valor ``value`` de ``param`` de la definición de rampa ``name`` (de código ``code``) con ``current`` (sus valores por nombre, los que tiene): el valor en su rango
    (``des.pit_ramp_value_range``) y, si cambia la pendiente de diseño o el perfil de pista, ``g ≤ pd`` del perfil de pista que quedaría (``des.pit_ramp_gradient_over``).
    ``road_profile`` da el nombre y la pendiente máxima de un perfil de pista por su código (``None`` si no la tiene). Sin valor (``None``) no hace nada. RF-018-04, RF-018-15."""
    if value is None:
        return
    param = PitRampParam(param)
    checked = check_pitramp_value(name, code, param, value)
    if param not in (PitRampParam.GRADIENT, PitRampParam.ROAD_PROFILE):
        return
    merged = {**current, param.value: checked}
    gradient, road = merged.get(PitRampParam.GRADIENT.value), merged.get(PitRampParam.ROAD_PROFILE.value)
    if isinstance(gradient, int | float) and isinstance(road, str) and road:
        profile_name, limit = road_profile(road)
        if limit is not None:
            check_ramp_gradient(name, code, float(gradient), limit, profile_name)


# --- Lo que lee del proyecto -------------------------------------------------------------------------------------------------------------


def _resolved(project: Any, conn: sqlite3.Connection, keys: Sequence[str], version: str | None) -> dict[str, Any]:
    """Los valores efectivos de ``keys`` (los de la versión y, si no, los del proyecto; solo los del proyecto sin versión); ``None`` si no tienen valor."""
    chain = (VERSION_SCOPE, PROJECT_SCOPE) if version is not None else (PROJECT_SCOPE,)
    found = ParameterStore(project).resolve_many(conn, tuple(keys), chain, version=version) if keys else {}
    return {key: (None if found.get(key) is None else found[key].value) for key in keys}


def check_pit_rose_change(project: Any, key: str, value: object, *, version: str | None) -> None:
    """**«Cambiar parámetro…» de un valor de una roseta** (T41; F-1; RF-018-04, RF-018-07): :func:`check_rose_edit` con los rangos que tiene la roseta en la versión ``version`` (uid) o
    en el proyecto. No hace nada si ``key`` no es de un valor de una roseta. Solo lee."""
    found = parse_rose_key(key)
    if found is None or value is None:
        return
    code, index, param = found
    from .pit_rose import rose_names

    with project.read() as conn:
        name = rose_names(conn).get(code, code)
        stored = [str(row[0]) for row in conn.execute("SELECT DISTINCT key FROM gb_parameter WHERE key LIKE ?", (f"des.rose.{code}.%",))]
        numbers = sorted({match.group(2) for match in map(_ROSE_KEY.fullmatch, stored) if match is not None and match.group(1) == code})
        keys = [rose_key(code, number, item) for number in numbers for item in RoseParam]
        values = _resolved(project, conn, keys, version)
    ranges = {number: {item.value: values[rose_key(code, number, item)] for item in RoseParam} for number in numbers}
    check_rose_edit(name, code, index, param, value, ranges)


def check_pit_ramp_change(project: Any, key: str, value: object, *, version: str | None) -> None:
    """**«Cambiar parámetro…» de un valor de una definición de rampa** (T41; F-1; RF-018-04, RF-018-15): :func:`check_ramp_edit` con los valores que tiene la rampa y el perfil de pista que
    elegiría. No hace nada si ``key`` no es de un valor de una rampa. Solo lee."""
    found = parse_ramp_key(key)
    if found is None or value is None:
        return
    code, param = found
    from .pit_ramp_def import ramp_names
    from .road_profiles import profile_names

    with project.read() as conn:
        name = ramp_names(conn).get(code, code)
        current = _resolved(project, conn, [f"des.pitramp.{code}.{item.value}" for item in PitRampParam], version)
        names = profile_names(conn)
        roads = {profile: _resolved(project, conn, [road_profile_key(profile, RoadProfileParam.MAX_GRADIENT)], version)[road_profile_key(profile, RoadProfileParam.MAX_GRADIENT)]
                 for profile in {str(value), str(current.get(f"des.pitramp.{code}.{PitRampParam.ROAD_PROFILE.value}"))} if profile in names}
    check_ramp_edit(name, code, param, value, {item.value: current[f"des.pitramp.{code}.{item.value}"] for item in PitRampParam},
                    lambda profile: (names.get(profile, profile), roads.get(profile)))


def check_pit_sector_change(project: Any, key: str, value: object, *, version: str | None) -> None:
    """**«Cambiar parámetro…» de un valor por sector de una corta** (T41; F-1; RF-018-04, RF-018-06, RF-018-08): con lo que quedaría la corta en la versión ``version`` (uid),
    **el perfil** del sector es de la altura y el ancla del perfil base y de los de los demás sectores (:func:`~design.pit_store.check_same_shape`), **el número de bancos por berma** es
    el de la corta (``des.pit_sector_n_berm``) y **la roseta** existe (``des.pit_rose_unknown``). Un valor en blanco (el sector usa el de la corta) y un cambio del proyecto (sin versión: un
    sector es de una versión) no hacen nada. No hace nada si ``key`` no es de un valor por sector de una corta o la versión no la tiene. Solo lee."""
    found = parse_sector_key(key)
    if found is None or version is None or value is None or (isinstance(value, str) and not value.strip()):
        return
    code, param, sector = found
    from . import entities
    from .pit_rose import rose_names
    from .pit_store import check_same_shape

    registry = entities.registry(project, version)
    entry = registry.get(code)
    if entry is None or entry.record.code != code:
        return
    name = entry.record.name
    base_key = entity_key(code, PitParam(param.value))
    with project.read() as conn:
        stored = [str(row[0]) for row in conn.execute("SELECT DISTINCT key FROM gb_parameter WHERE key LIKE ?", (f"{base_key}.%",))]
        sectors = {match.group(3): str(key_) for key_ in stored if (match := _SECTOR_KEY.fullmatch(key_)) is not None}
        keys = [base_key, entity_key(code, PitParam.LAYER), *sectors.values()]
        values = _resolved(project, conn, keys, version)
        roses = rose_names(conn)
    if param is PitSectorParam.ROSE:
        if value not in roses:
            layer = values[entity_key(code, PitParam.LAYER)]
            raise DesignError("des.pit_rose_unknown", obj=f"Corta «{name}» de la capa «{layer}»", field=key, value=value, layer=layer, entity=name,
                              roses=", ".join(roses.values()) or "—")
        return
    if param is PitSectorParam.N_BERM:
        base = values[base_key]
        base_n = 1 if base is None else base
        if value != base_n:
            raise DesignError("des.pit_sector_n_berm", obj=f"Corta «{name}»", field=pit_sector_key(code, param, sector), value=value, entity=name, sector=sector, other=base_n)
        return
    assigned = {segment: values[found_key] for segment, found_key in sectors.items() if values[found_key]}
    assigned[sector] = value  # type: ignore[assignment]
    ordered = [item for item in (values[base_key], *assigned.values()) if isinstance(item, str) and item]
    codes = tuple(dict.fromkeys(ordered))
    with project.read() as conn:
        bench = _resolved(project, conn, [bench_key(item, parameter) for item in codes for parameter in BenchParam], version)
    built = pipeline.bench_profiles(bench, codes)
    check_same_shape(name, code, [built[item] for item in ordered])
