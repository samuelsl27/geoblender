# SPDX-License-Identifier: GPL-3.0-or-later
"""La definición de rampa de la corta (spec 018, T04; HU-018-3; RF-018-15; plan 018 §5.1, §5.2.2 y §5.2.3; ADR-0027; RF-017-07,
RF-009-24, RF-008-01).

Una definición de rampa son **dos cosas**, como la roseta (:mod:`design.pit_rose`): su fila en la tabla del proyecto ``des_pit_ramp``
(:data:`TABLE`: ``code`` inmutable, ``name``, quién y cuándo; ni un valor) y sus valores, que son parámetros de ``core.params``
(``des.pitramp.{q}.<valor>``, :mod:`design.params`): el tipo (``spiral`` o ``zigzag``), el sentido (``cw`` o ``ccw``), el punto de inicio
(``start``: la capa y la entidad, o el banco), la pendiente de diseño ``gradient_pct`` *g* (%; el plan y la spec 018 la llaman con otra palabra inglesa, que el
glosario §14 reserva a la ley: errata a corregir en la documentación), el perfil de pista de la 017 (``road_profile``, su código: de él salen el ancho
de la sección y las reglas, RF-017-07), la transición lineal de la cara ``transition_m`` (m, ≥ 0) y, **solo en el zig-zag**, el radio de
giro ``turn_radius_m`` y la plataforma mínima de retorno ``min_platform_m`` (m, > 0; HIPÓTESIS, D-19). Sin valor por defecto.

**La pendiente** cumple ``0 < g ≤ pd`` con *pd* la pendiente máxima de diseño del perfil de pista elegido (:func:`check_ramp_gradient`;
nada se relaja). Que la pendiente **media** pase de *pm* se confirma al calcular (``des.pit_ramp_mean_over``, T de la rampa), no aquí.
Los **derivados** (:func:`required_length_m`, :func:`derived`) no son parámetros: la longitud de eje que pide subir un banco, ``h / g``,
la transición y la sección del perfil de pista.

:func:`edit_pit_ramps` es la operación de proyecto :data:`EDIT_PIT_RAMPS` (``des.edit_pit_ramps``; no se repite sola), con la mecánica de
:func:`design.pit_rose.edit_pit_roses`: una transacción, todo mirado antes de escribir, el código inmutable, el proyecto o una versión.
Python puro (nivel 8).
"""

from __future__ import annotations

import json
import math
import numbers
import sqlite3
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ..core.constraints.model import constraint_code
from ..core.datasets.model import DatasetSpec
from ..core.params import ParameterStore
from ..core.provenance.contract import OperationDef
from ..core.provenance.operations import OperationProject, begin_operation
from .messages import DesignError
from .params import PitRampParam, RoadProfileParam, check_pitramp_value, pitramp_key, road_profile_key
from .pit_rose import (
    Declaration,
    StoredEntry,
    coded_check_names,
    coded_create_table,
    coded_dataset_spec,
    coded_read,
    coded_rename,
    coded_write_value,
)
from .provenance import EDIT_PIT_RAMPS, PIT_PROJECT_OPERATIONS, PIT_RAMP_COMMAND
from .road_profiles import RoadDerived
from .road_profiles import read_profiles as read_road_profiles

__all__ = [
    "CODE_PREFIX",
    "EDIT_COMMAND",
    "EDIT_PIT_RAMPS",
    "OPERATIONS",
    "RAMPS_ROLE",
    "TABLE",
    "EditedRamps",
    "PitRampDef",
    "RampDerived",
    "RampEdit",
    "check_ramp",
    "check_ramp_gradient",
    "create_table",
    "dataset_spec",
    "derived",
    "edit_pit_ramps",
    "ramp_code",
    "ramp_names",
    "read_ramps",
    "required_length_m",
]

TABLE = "des_pit_ramp"
"""La tabla del proyecto de las definiciones de rampa (plan 018 §5.1): una fila por rampa, sin valores."""
EDIT_COMMAND = PIT_RAMP_COMMAND
"""La orden del catálogo que lanza la operación (la provisional de las rampas hasta que haya la propia: D-20)."""
RAMPS_ROLE = "pit_ramps_def"
"""El papel de :data:`TABLE` como salida de la operación."""
OPERATIONS: tuple[OperationDef, ...] = tuple(item for item in PIT_PROJECT_OPERATIONS if item.op_type == EDIT_PIT_RAMPS)
"""La operación de este módulo (``des.edit_pit_ramps``), de proyecto y sin repetición: la declara ``provenance`` (T03)."""
CODE_PREFIX = "ramp"
"""Lo que lleva delante un código cuyo nombre no empieza por una letra (``8%`` → ``ramp_8``)."""

_IDENTIFIER = "Definiciones de rampa"
_ZIGZAG = ("turn_radius_m", "min_platform_m")
"""Los dos valores que solo pide el zig-zag."""
_TEXT = (PitRampParam.TYPE, PitRampParam.SENSE, PitRampParam.START, PitRampParam.ROAD_PROFILE)


# --- La definición como dato -----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PitRampDef:
    """Una definición de rampa ya comprobada (RF-018-15): ``code`` inmutable, ``name`` libre y único, ``type``, ``sense``, ``start``,
    ``gradient_pct`` (%), ``road_profile`` (código del perfil de pista), ``transition_m`` (m) y, del zig-zag (``None`` en la
    espiral si no se dan), ``turn_radius_m`` y ``min_platform_m`` (m)."""

    code: str
    name: str
    type: str
    sense: str
    start: str
    gradient_pct: float
    road_profile: str
    transition_m: float
    turn_radius_m: float | None = None
    min_platform_m: float | None = None


@dataclass(frozen=True, slots=True)
class RampDerived:
    """Lo derivado de una definición (RF-018-15): la longitud de eje que pide un banco, ``length_per_bench_m`` = ``h / g`` (m), la
    ``transition_m`` (m) y, si se da el perfil de pista, su ``section_m`` (m; si no, ``None``)."""

    length_per_bench_m: float
    transition_m: float
    section_m: float | None


def check_ramp_gradient(name: str, code: str, gradient_pct: float, max_gradient_pct: float, road_profile_name: str) -> None:
    """``g ≤ pd`` (RF-018-15): ``DesignError`` ``des.pit_ramp_gradient_over`` nombrando la rampa ``name``, el perfil de pista, la clave
    ``des.pitramp.{code}.gradient_pct``, *g* y *pd*, si la pendiente de diseño pasa de la máxima del perfil; la igualdad vale.
    :class:`ValueError` si ``max_gradient_pct`` no es un número > 0 y finito (un error del programa)."""
    limit = _real(max_gradient_pct, "la pendiente máxima de diseño")
    if limit <= 0.0:
        raise ValueError(f"la pendiente máxima de diseño {max_gradient_pct!r} no es > 0")
    if gradient_pct > limit:
        raise DesignError("des.pit_ramp_gradient_over", obj=f"Rampa «{name}»", field=pitramp_key(code, PitRampParam.GRADIENT),
                          value=gradient_pct, profile=name, limit=limit, other=road_profile_name)


def check_ramp(name: str, code: str, values: Mapping[str, object], *, max_gradient_pct: float, road_profile_name: str) -> PitRampDef:
    """La definición de rampa ``name`` de código ``code`` con ``values`` (por último segmento de la clave: ``type``, ``sense``,
    ``start``, ``gradient_pct``, ``road_profile``, ``transition_m``, ``turn_radius_m``, ``min_platform_m``), ya comprobada y completa:
    cada valor con :func:`~design.params.check_pitramp_value` (``des.pit_ramp_value_missing`` o ``_range`` nombrando la rampa, la clave
    y el valor; ``0 < g ≤ 100``, transición ≥ 0, radio y plataforma > 0, el radio y la plataforma **obligatorios solo en el zig-zag**)
    y después ``g ≤ pd`` (:func:`check_ramp_gradient`, con ``max_gradient_pct`` el *pd* del perfil de pista ``road_profile_name``).
    :class:`ValueError` si ``values`` trae un nombre que no es de una rampa o ``max_gradient_pct`` no vale, :class:`TypeError` si un
    valor no es del tipo (errores del programa; RF-018-15)."""
    unknown = [key for key in values if key not in {param.value for param in PitRampParam}]
    if unknown:
        raise ValueError(f"{', '.join(unknown)} no son valores de una definición de rampa")
    found: dict[str, Any] = {}
    kind = check_pitramp_value(name, code, PitRampParam.TYPE, values.get(PitRampParam.TYPE.value))
    found["type"] = kind
    for param in PitRampParam:
        if param is PitRampParam.TYPE:
            continue
        required = param.value not in _ZIGZAG or kind == "zigzag"
        found[param.value] = check_pitramp_value(name, code, param, values.get(param.value), required=required)
    _real(max_gradient_pct, "la pendiente máxima de diseño")
    check_ramp_gradient(name, code, found["gradient_pct"], max_gradient_pct, road_profile_name)
    return PitRampDef(code, name, found["type"], found["sense"], found["start"], found["gradient_pct"], found["road_profile"],
                      found["transition_m"], found["turn_radius_m"], found["min_platform_m"])


def _real(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{what} es un número real, no {value!r}")
    found = float(value)
    if not math.isfinite(found):
        raise ValueError(f"{what} {value!r} no es finito")
    return found


def required_length_m(height_m: float, gradient_pct: float) -> float:
    """La longitud de eje (m) que pide subir o bajar un banco de ``height_m`` m con la pendiente ``gradient_pct`` %, ``h / g``
    (RF-018-15): 125 m con 10 m y el 8 %. :class:`ValueError` si alguno no es > 0 y finito; :class:`TypeError` si no es un número."""
    height = _real(height_m, "la altura")
    gradient = _real(gradient_pct, "la pendiente")
    if height <= 0.0:
        raise ValueError(f"la altura {height_m!r} no es > 0")
    if gradient <= 0.0:
        raise ValueError(f"la pendiente {gradient_pct!r} no es > 0")
    return height * 100.0 / gradient


def derived(ramp: PitRampDef, height_m: float, road: RoadDerived | None = None) -> RampDerived:
    """Los derivados de ``ramp`` para un banco de ``height_m`` m (RF-018-15); con los derivados del perfil de pista ``road``
    (:func:`design.road_profiles.derived`), también la sección."""
    return RampDerived(required_length_m(height_m, ramp.gradient_pct), ramp.transition_m, None if road is None else road.section_m)


# --- La tabla ----------------------------------------------------------------------------------------------------------------


def create_table(conn: sqlite3.Connection) -> bool:
    """Crea la tabla :data:`TABLE` en la transacción de ``conn`` si falta y dice si la creó. No confirma."""
    return coded_create_table(conn, TABLE, _IDENTIFIER)


def dataset_spec() -> DatasetSpec:
    """El dato del proyecto de :data:`TABLE` (tabla de atributos de ``des``, no editable en QGIS)."""
    return coded_dataset_spec(TABLE, RAMPS_ROLE)


def read_ramps(conn: sqlite3.Connection) -> tuple[StoredEntry, ...]:
    """Las definiciones de rampa del proyecto en el orden en que se crearon (ninguna si aún no hay tabla)."""
    return coded_read(conn, TABLE)


def ramp_names(conn: sqlite3.Connection) -> dict[str, str]:
    """Código → nombre de las rampas del proyecto (RF-018-04). Vacío si no hay tabla."""
    return {item.code: item.name for item in read_ramps(conn)}


def ramp_code(name: str, taken: Iterable[str]) -> str:
    """El código de una rampa nueva: su nombre en ASCII y en minúsculas, sin tildes y con «_» en lugar de lo demás
    (``RAMPA NORTE`` → ``rampa_norte``), con ``ramp_`` delante si no empieza por una letra (``ramp`` si no queda nada), de como mucho
    32 caracteres, y ``_2``, ``_3``… si ya está en ``taken``: el código de una rampa existente no se reutiliza ni cambia."""
    return constraint_code(name, set(taken), prefix=CODE_PREFIX)


# --- Lo que pide la persona ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RampEdit:
    """Una edición de una definición de rampa. Sin ``code``, una **nueva**: su ``name`` y sus ``values`` (los de
    :class:`~design.params.PitRampParam`; el radio y la plataforma solo en el zig-zag; sin valor por defecto); el código sale del
    nombre. Con ``code``, una que ya existe: ``name`` la renombra (sin tocar el código) y ``values`` completa lo que falta en el
    ámbito de la declaración (los que el ámbito ya tiene se rechazan: cambiarlos es de «Parámetros»). Otra clave es un error del
    programa (``ValueError``)."""

    name: str | None = None
    code: str = ""
    values: Mapping[PitRampParam | str, object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType({PitRampParam(key): value for key, value in dict(self.values or {}).items()}))


@dataclass(frozen=True, slots=True)
class EditedRamps:
    """Lo que dejó :func:`edit_pit_ramps`: su ``operation_uid``, todas las ``ramps`` del proyecto después, y los códigos de las rampas
    ``created``, ``renamed`` y ``completed``."""

    operation_uid: str
    ramps: tuple[StoredEntry, ...]
    created: tuple[str, ...]
    renamed: tuple[str, ...]
    completed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Plan:
    created: tuple[tuple[str, str, Mapping[PitRampParam, float | str]], ...]
    renamed: tuple[tuple[str, str], ...]
    completed: tuple[tuple[str, Mapping[PitRampParam, float | str]], ...]

    def settings(self, declaration: Declaration | None) -> dict[str, Any]:
        return {
            "created": [[code, name] for code, name, _values in self.created],
            "renamed": [[code, name] for code, name in self.renamed],
            "completed": [[code, [param.value for param in values]] for code, values in self.completed],
            "version": None if declaration is None else declaration.version,
        }


def _text(value: object, what: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    return value


def _effective(conn: sqlite3.Connection, store: ParameterStore, keys: Mapping[str, str], version: str | None) -> dict[str, Any]:
    """Los valores con valor de ``keys`` (último segmento → clave) en el ámbito: los de la versión y, si no, los del proyecto."""
    chain = ("version", "project") if version is not None else ("project",)
    found = store.resolve_many(conn, keys.values(), chain, version=version)
    return {last: json.loads(found[key].value_json) for last, key in keys.items() if key in found and found[key].value_json is not None}


def _max_gradient(conn: sqlite3.Connection, store: ParameterStore, name: str, road: str, version: str | None) -> tuple[float, str]:
    """La pendiente máxima de diseño *pd* (%) y el nombre del perfil de pista ``road`` (su código) en el ámbito: ``DesignError``
    ``des.pit_ramp_value_range`` si el perfil no existe en el proyecto y ``des.road_profile_value_missing`` si no tiene *pd*."""
    stored = {item.code: item.name for item in read_road_profiles(conn)}
    if road not in stored:
        listed = ", ".join(f"«{code}»" for code in stored) or "ninguno"
        raise DesignError("des.pit_ramp_value_range", obj=f"Rampa «{name}»", field="road_profile", value=road, profile=name,
                          range=f"un perfil de pista del proyecto ({listed})")
    key = road_profile_key(road, RoadProfileParam.MAX_GRADIENT)
    found = _effective(conn, store, {"max_gradient_pct": key}, version)
    if "max_gradient_pct" not in found:
        raise DesignError("des.road_profile_value_missing", obj=f"Perfil de pista «{stored[road]}»", field=key, value=None,
                          profile=stored[road])
    return float(found["max_gradient_pct"]), stored[road]


def _plan(conn: sqlite3.Connection, store: ParameterStore, stored: Sequence[StoredEntry], edits: Sequence[RampEdit],
          declaration: Declaration | None) -> _Plan:
    """Comprueba ``edits`` sobre las rampas ``stored`` sin escribir nada y devuelve lo que se escribirá: ``DesignError`` (sin nombre,
    nombre repetido, valor sin valor o fuera de rango, ``g > pd``); ``ValueError`` si la rampa no existe, sale dos veces, la edición
    no cambia nada o hay valores sin declaración; ``TypeError`` si un nombre o un valor no es del tipo."""
    version = None if declaration is None else declaration.version
    by_code = {item.code: item for item in stored}
    taken = set(by_code)
    names = {item.code: item.name for item in stored}
    fresh = sum(1 for edit in edits if not edit.code)
    created: list[tuple[str, str, Mapping[PitRampParam, float | str]]] = []
    renamed: list[tuple[str, str]] = []
    completed: list[tuple[str, Mapping[PitRampParam, float | str]]] = []
    seen: set[str] = set()
    position = 0
    for edit in edits:
        values = edit.values or {}
        if values and declaration is None:
            raise ValueError("escribir los valores de una rampa necesita su declaración: origen, decisor y motivo (Declaration)")
        raw = _text(edit.name, "el nombre de una rampa")
        if not edit.code:
            position += 1
            name = (raw or "").strip()
            if not name:
                shown = "nueva" if fresh == 1 else f"nueva {position}"
                raise DesignError("des.pit_ramp_name_missing", obj=f"Rampa «{shown}»", field="name", value=raw, profile=shown)
            code = ramp_code(name, taken)
            taken.add(code)
            names[code] = name
            plain = {param.value: value for param, value in values.items()}
            road = plain.get("road_profile")
            if isinstance(road, str) and road.strip():
                limit, road_name = _max_gradient(conn, store, name, road.strip(), version)
            else:  # check_ramp lo rechaza por falta de valor (o de tipo) antes de usar el límite
                limit, road_name = 1.0, ""
            ramp = check_ramp(name, code, plain, max_gradient_pct=limit, road_profile_name=road_name)
            created.append((code, name, MappingProxyType({param: getattr(ramp, param.value) for param in PitRampParam
                                                          if getattr(ramp, param.value) is not None})))
            continue
        row = by_code.get(edit.code)
        if row is None:
            raise ValueError(f"la rampa {edit.code!r} no existe en el proyecto")
        if edit.code in seen:
            raise ValueError(f"la rampa {edit.code!r} sale dos veces en la misma edición")
        seen.add(edit.code)
        name = row.name if raw is None else raw.strip()
        if not name:
            raise DesignError("des.pit_ramp_name_missing", obj=f"Rampa «{edit.code}»", field="name", value=raw, profile=edit.code)
        checked = {param: check_pitramp_value(name, edit.code, param, value, required=True) for param, value in values.items()}
        if name == row.name and not checked:
            raise ValueError(f"la edición de la rampa {edit.code!r} no cambia nada")
        if name != row.name:
            names[edit.code] = name
            renamed.append((edit.code, name))
        if checked:
            keys = {param.value: pitramp_key(edit.code, param) for param in PitRampParam}
            merged = {**_effective(conn, store, keys, version), **{param.value: value for param, value in checked.items()}}
            if "gradient_pct" in merged and merged.get("road_profile"):  # con los valores efectivos del ámbito (RF-018-15)
                limit, road_name = _max_gradient(conn, store, name, str(merged["road_profile"]), version)
                check_ramp_gradient(name, edit.code, float(merged["gradient_pct"]), limit, road_name)
            completed.append((edit.code, MappingProxyType(checked)))
    coded_check_names(names.items(), "des.pit_ramp_name_repeated", "definiciones de rampa")
    return _Plan(tuple(created), tuple(renamed), tuple(completed))


def _write_values(conn: sqlite3.Connection, store: ParameterStore, code: str, values: Mapping[PitRampParam, float | str],
                  declared: Declaration) -> None:
    for param in PitRampParam:
        if param in values:
            coded_write_value(conn, store, pitramp_key(code, param), values[param], declared)


def edit_pit_ramps(project: OperationProject, edits: Iterable[RampEdit], declaration: Declaration | None = None) -> EditedRamps:
    """Registra ``des.edit_pit_ramps``: aplica ``edits`` (:class:`RampEdit`) en **una** transacción y devuelve lo que dejó. Cada rampa
    nueva recibe su código del nombre y sus valores, y cada una que se completa los que da; ``declaration`` dice con qué origen,
    decisor, motivo y tipo se escriben (obligatoria si hay valores) y en qué ámbito (el proyecto o una versión).

    Se mira todo antes de registrar nada: ``DesignError`` ``des.pit_ramp_name_missing``, ``_name_repeated``, ``_value_missing``,
    ``_value_range`` o ``_gradient_over`` nombrando la rampa, el campo y el valor (RF-018-15), con la pendiente máxima de diseño del
    perfil de pista **del ámbito**; ``ValueError`` o ``TypeError`` si la edición es un error del programa. Lo que falla después
    (``ParamError`` por un valor que ya existe o un origen sin decir…) lo deshace todo y deja la operación fallida."""
    edits = tuple(edits)
    if not edits:
        raise ValueError("una edición de las definiciones de rampa cambia al menos una")
    store = ParameterStore(project)  # type: ignore[arg-type]
    with project.read() as conn:
        stored = read_ramps(conn)
        plan = _plan(conn, store, stored, edits, declaration)
    handle = begin_operation(project, EDIT_PIT_RAMPS, settings=plan.settings(declaration), executor="blender")
    try:
        with project.write_transaction() as conn:
            made = create_table(conn)
            for code, name, _values in plan.created:
                conn.execute(f"INSERT INTO {TABLE} (uid, code, name, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                             (uuid.uuid4().hex, code, name, project.session.user_host, handle.started_at))
            if plan.renamed:
                coded_rename(conn, TABLE, plan.renamed)
            if declaration is not None:
                for code, _name, values in plan.created:
                    _write_values(conn, store, code, values, declaration)
                for code, values in plan.completed:
                    _write_values(conn, store, code, values, declaration)
            handle.complete(
                conn, outputs=(dataset_spec(),) if made or plan.created or plan.renamed else (),
                message=(f"Definiciones de rampa: {len(plan.created)} creadas, {len(plan.renamed)} renombradas, "
                         f"{len(plan.completed)} completadas"))
    except Exception as error:
        handle.fail(str(error) or type(error).__name__)
        raise
    with project.read() as conn:
        after = read_ramps(conn)
    return EditedRamps(handle.uid, after, tuple(code for code, _name, _values in plan.created), tuple(code for code, _name in plan.renamed),
                       tuple(code for code, _values in plan.completed))
