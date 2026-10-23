# SPDX-License-Identifier: GPL-3.0-or-later
"""La columna de materiales del proyecto (spec 011; RF-011-11 a RF-011-14; plan 011 §5.2.1,
§5.3.1, A7, D-12, D-18, D-23, D-24).

La columna es **del proyecto** (D-12): las unidades de arriba abajo, cada una con

- su **código** (D-18): inmutable, ``[a-z][a-z0-9_]*``, único en la columna; es la clave de sus
  parámetros (``reserves.params``: densidad, K y porcentajes) y no cambia al renombrar la unidad
  (:meth:`Unit.renamed`). :func:`unit_code` lo propone al crearla, desde su nombre;
- su nombre visible, su clase (:class:`Kind`: natural, antrópica o compuesta), su papel
  (:class:`Role`: útil o estéril; una compuesta no lo tiene, lo tienen sus componentes) y su
  estado (:class:`State`: in situ o suelto);
- su **base** (D-24): un dato del proyecto en su rejilla (por nombre) o una cota constante; la
  última unidad no tiene base (llega hasta la superficie final);
- una antrópica (escombro, acopio, relleno antiguo), su **rejilla de espesores** (D-23, m, ≥ 0):
  está donde su espesor pasa del umbral de presencia y su volumen va desde su base hacia
  arriba (RF-011-14; el núcleo, ``reserves.kernel``, A7);
- una compuesta, sus **componentes** (:class:`Component`: código, nombre y papel), con el estado
  de su unidad.

**Ninguna densidad ni ningún K** viven aquí ni tienen valor por defecto (D-8): son parámetros
con tipo e historial (``reserves.params.FAMILIES``).

- :meth:`MaterialColumn.problems` y :meth:`MaterialColumn.validate`: lo que la hace inválida,
  como lista (:class:`Problem`) o como :class:`MaterialsError` (``res.materials_invalid``).
  Lo que la interfaz nunca construye (una clase desconocida, un espesor en una unidad natural)
  es un error del programa (:class:`ValueError`) al crear la unidad.
- La tabla ``res_materials`` (§5.2.1): :data:`TABLE`, :data:`CREATE_TABLE`, :data:`COLUMNS`,
  :func:`column_rows` (una fila por unidad y por componente) y :func:`read_column`.
- :func:`negative_thickness`: el error para el usuario de una rejilla de espesores con
  espesores negativos (``res.thickness_negative``), que el núcleo detecta.

Python puro (nivel 9). Las entradas solo se leen.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from .messages import ResError, render
from .surfaces import SurfaceRef

__all__ = [
    "CODE_MAX_LENGTH",
    "COLUMNS",
    "CREATE_TABLE",
    "TABLE",
    "Component",
    "Kind",
    "MaterialColumn",
    "MaterialsError",
    "Problem",
    "Role",
    "State",
    "Unit",
    "column_rows",
    "negative_thickness",
    "read_column",
    "unit_code",
]

TABLE = "res_materials"
"""La tabla de la columna en el GeoPackage del proyecto (dato «res_materials»)."""

CREATE_TABLE = f"""CREATE TABLE {TABLE} (
  fid INTEGER PRIMARY KEY AUTOINCREMENT,
  position INTEGER NOT NULL,
  parent TEXT NOT NULL DEFAULT '',
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('natural','anthropic','compound','component')),
  role TEXT CHECK (role IN ('useful','waste')),
  state TEXT NOT NULL CHECK (state IN ('in_situ','loose')),
  base_dataset TEXT,
  base_elevation TEXT,
  thickness_dataset TEXT,
  UNIQUE (parent, code)
)"""
"""La sentencia que crea :data:`TABLE` (plan §5.2.1): una fila por unidad (``parent`` vacío) y
por componente (``parent``, el código de su unidad); ``position`` de arriba abajo (unidades) o
dentro de su unidad (componentes), desde 1; la cota constante, como texto exacto (m)."""

COLUMNS: tuple[str, ...] = (
    "position", "parent", "code", "name", "kind", "role", "state", "base_dataset",
    "base_elevation", "thickness_dataset",
)
"""Las columnas que se escriben (sin ``fid``), en el orden de :func:`column_rows`."""

CODE_MAX_LENGTH = 32
"""La longitud máxima de un código que propone :func:`unit_code`."""

_CODE = re.compile(r"[a-z][a-z0-9_]*")
_NOT_CODE = re.compile(r"[^a-z0-9]+")
_TABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OBJ = "Columna de materiales"
_PATH = " ▸ "


class Kind(StrEnum):
    """La clase de una fila de la columna: una unidad natural, antrópica o compuesta, o un
    componente de una compuesta."""

    NATURAL = "natural"
    ANTHROPIC = "anthropic"
    COMPOUND = "compound"
    COMPONENT = "component"


class Role(StrEnum):
    """El papel de una unidad o de un componente: material útil o estéril."""

    USEFUL = "useful"
    WASTE = "waste"


class State(StrEnum):
    """El estado de una unidad: in situ (se pesa con V·ρ) o suelto (con V·ρ/K; error 67)."""

    IN_SITU = "in_situ"
    LOOSE = "loose"


def _text(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    return value


def _role(value: object) -> Role | None:
    """El papel (``None`` si aún no se ha elegido); uno desconocido, :class:`ValueError`."""
    return None if value is None else Role(value)


@dataclass(frozen=True, slots=True)
class Component:
    """Un componente de una unidad compuesta: su código (D-18, inmutable, único en su unidad),
    su nombre y su papel (``None`` si aún no se ha elegido: un problema de la columna)."""

    code: str
    name: str
    role: Role | str | None

    def __post_init__(self) -> None:
        _text(self.code, "el código de un componente")
        _text(self.name, "el nombre de un componente")
        object.__setattr__(self, "role", _role(self.role))

    @property
    def kind(self) -> Kind:
        """:attr:`Kind.COMPONENT`."""
        return Kind.COMPONENT


@dataclass(frozen=True, slots=True)
class Unit:
    """Una unidad de la columna (plan §5.3.1): código (D-18), nombre, clase (:class:`Kind`),
    papel (:class:`Role`; ``None`` en una compuesta o si aún no se ha elegido), estado
    (:class:`State`), base (un dato del proyecto o una cota constante, D-24; ``None`` en la
    última), rejilla de espesores (solo una antrópica, un dato del proyecto, D-23) y
    componentes (solo una compuesta).

    Lo que la interfaz nunca construye es un error del programa: una clase, papel o estado
    desconocidos o la clase «componente» (:class:`ValueError`); un espesor fuera de una
    antrópica, componentes fuera de una compuesta o papel en una compuesta; una base o un
    espesor congelados o que no son :class:`~reserves.surfaces.SurfaceRef`, o un espesor que
    no es un dato (:class:`ValueError` o :class:`TypeError`). Lo que falta (la base, el
    espesor, los componentes, el papel) lo dice :meth:`MaterialColumn.problems`."""

    code: str
    name: str
    kind: Kind | str
    role: Role | str | None
    state: State | str
    base: SurfaceRef | None = None
    thickness: SurfaceRef | None = None
    components: tuple[Component, ...] = ()

    def __post_init__(self) -> None:
        _text(self.code, "el código de una unidad")
        _text(self.name, "el nombre de una unidad")
        kind = Kind(self.kind)
        if kind is Kind.COMPONENT:
            raise ValueError(f"«{self.code}»: un componente no es una unidad de la columna")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "role", _role(self.role))
        object.__setattr__(self, "state", State(self.state))
        components = tuple(self.components)
        for component in components:
            if not isinstance(component, Component):
                raise TypeError(f"«{self.code}»: un componente es un Component, no "
                                f"{component!r}")
        object.__setattr__(self, "components", components)
        for name in ("base", "thickness"):
            ref = getattr(self, name)
            if ref is not None and not isinstance(ref, SurfaceRef):
                raise TypeError(f"«{self.code}»: la {name} es una SurfaceRef, no {ref!r}")
            if ref is not None and ref.frozen is not None:
                raise ValueError(f"«{self.code}»: la {name} de una unidad es un dato del "
                                 "proyecto o una cota constante, no un dato congelado (D-24)")
        problem = self._structure_problem()
        if problem is not None:
            raise ValueError(f"«{self.code}»: {problem}")

    def _structure_problem(self) -> str | None:
        if self.thickness is not None:
            if self.kind is not Kind.ANTHROPIC:
                return "solo una unidad antrópica tiene rejilla de espesores (D-23)"
            if self.thickness.dataset is None:
                return "la rejilla de espesores es un dato del proyecto (D-23)"
        if self.components and self.kind is not Kind.COMPOUND:
            return "solo una unidad compuesta tiene componentes"
        if self.kind is Kind.COMPOUND and self.role is not None:
            return "una unidad compuesta no tiene papel: lo tienen sus componentes"
        return None

    def renamed(self, name: str) -> Unit:
        """La misma unidad con otro nombre visible: el código (y con él sus parámetros) no
        cambia (D-18)."""
        return replace(self, name=name)

    @property
    def shown(self) -> str:
        """El nombre para una persona: el nombre o, si está vacío, el código."""
        return self.name.strip() or self.code


@dataclass(frozen=True, slots=True)
class Problem:
    """Un problema de la columna: su código de nota (``res.materials_empty``,
    ``res.unit_*``), la unidad o el componente («Capa útil ▸ Caliza») y, si lo hay, el código
    que no vale o se repite."""

    code: str
    unit: str = ""
    value: str | None = None

    def text(self, language: str = "es") -> str:
        """El problema como un elemento de la lista de ``res.materials_invalid``."""
        return render(self.code, language=language, unit=self.unit, code=self.value)


class MaterialsError(ResError):
    """``res.materials_invalid``: la columna no vale; ``problems`` es la lista
    (:class:`Problem`) y el valor del error, cuántos problemas hay."""

    def __init__(self, found: Sequence[Problem]) -> None:
        found = tuple(found)
        super().__init__("res.materials_invalid", obj=_OBJ, field="units", value=len(found),
                         problems="; ".join(problem.text() for problem in found))
        self.problems = found


@dataclass(frozen=True, slots=True)
class MaterialColumn:
    """La columna de materiales del proyecto (D-12): las unidades de arriba abajo."""

    units: tuple[Unit, ...]

    def __post_init__(self) -> None:
        units = tuple(self.units)
        for unit in units:
            if not isinstance(unit, Unit):
                raise TypeError(f"una unidad de la columna es una Unit, no {unit!r}")
        object.__setattr__(self, "units", units)

    @property
    def codes(self) -> tuple[str, ...]:
        """Los códigos de las unidades, de arriba abajo."""
        return tuple(unit.code for unit in self.units)

    def unit(self, code: str) -> Unit:
        """La unidad de código ``code``; :class:`KeyError` si no está."""
        for unit in self.units:
            if unit.code == code:
                return unit
        raise KeyError(f"la columna no tiene la unidad «{code}»")

    def problems(self) -> tuple[Problem, ...]:
        """Lo que hace inválida la columna (RF-011-11), unidad a unidad de arriba abajo: la
        columna vacía; el nombre vacío; un código que no vale o se repite (también entre los
        componentes de una unidad); sin papel; una unidad sin base que no es la última, la
        última con base o antrópica; una antrópica sin rejilla de espesores; una compuesta sin
        componentes."""
        if not self.units:
            return (Problem("res.materials_empty"),)
        found: list[Problem] = []
        seen: set[str] = set()
        last = len(self.units) - 1
        for position, unit in enumerate(self.units):
            shown = unit.shown
            found.extend(_identity(unit.code, unit.name, shown, seen))
            if unit.kind is not Kind.COMPOUND and unit.role is None:
                found.append(Problem("res.unit_role_missing", shown))
            found.extend(_layout(unit, shown, position == last))
            if unit.kind is Kind.COMPOUND and not unit.components:
                found.append(Problem("res.unit_components_missing", shown))
            inside: set[str] = set()
            for component in unit.components:
                where = shown + _PATH + (component.name.strip() or component.code)
                found.extend(_identity(component.code, component.name, where, inside))
                if component.role is None:
                    found.append(Problem("res.unit_role_missing", where))
        return tuple(found)

    def validate(self) -> None:
        """Comprueba la columna: con algún problema (:meth:`problems`), :class:`MaterialsError`
        con la lista, y no se guarda ni se cubica con ella."""
        found = self.problems()
        if found:
            raise MaterialsError(found)


def _identity(code: str, name: str, shown: str, seen: set[str]) -> list[Problem]:
    """El nombre vacío y el código que no vale o que ya está en ``seen`` (y lo añade)."""
    found: list[Problem] = []
    if not name.strip():
        found.append(Problem("res.unit_name_empty", shown))
    if _CODE.fullmatch(code) is None:
        found.append(Problem("res.unit_code_invalid", shown, code))
    elif code in seen:
        found.append(Problem("res.unit_code_repeated", shown, code))
    seen.add(code)
    return found


def _layout(unit: Unit, shown: str, last: bool) -> list[Problem]:
    """La base y el espesor según el lugar de la unidad (D-23, D-24)."""
    if last and unit.kind is Kind.ANTHROPIC:
        return [Problem("res.unit_last_anthropic", shown)]
    found: list[Problem] = []
    if last and unit.base is not None:
        found.append(Problem("res.unit_last_with_base", shown))
    elif not last and unit.base is None:
        found.append(Problem("res.unit_base_missing", shown))
    if unit.kind is Kind.ANTHROPIC and unit.thickness is None:
        found.append(Problem("res.unit_thickness_missing", shown))
    return found


def unit_code(name: str, taken: Collection[str]) -> str:
    """El código de una unidad (o de un componente) nueva (D-18): su nombre en ASCII y en
    minúsculas, sin tildes y con «_» en lugar de lo demás (``Capa útil`` → ``capa_util``),
    con ``u_`` delante si no empieza por una letra (``u`` si no queda nada), de como mucho
    :data:`CODE_MAX_LENGTH` caracteres, y ``_2``, ``_3``… si ya está en ``taken``."""
    plain = "".join(char for char in unicodedata.normalize("NFKD", name)
                    if not unicodedata.combining(char))
    base = _NOT_CODE.sub("_", plain.lower().encode("ascii", "ignore").decode("ascii"))
    base = base.strip("_")
    if not base:
        base = "u"
    elif not base[0].isalpha():
        base = f"u_{base}"
    base = base[:CODE_MAX_LENGTH].rstrip("_")
    candidate, number = base, 2
    while candidate in taken:
        suffix = f"_{number}"
        candidate = base[:CODE_MAX_LENGTH - len(suffix)].rstrip("_") + suffix
        number += 1
    return candidate


def column_rows(column: MaterialColumn) -> list[tuple[object, ...]]:
    """Las filas de :data:`TABLE` (en el orden de :data:`COLUMNS`): cada unidad seguida de sus
    componentes; la cota constante de una base, como texto exacto (``repr`` del float64)."""
    rows: list[tuple[object, ...]] = []
    for position, unit in enumerate(column.units, start=1):
        base = unit.base
        rows.append((
            position, "", unit.code, unit.name, unit.kind.value,
            None if unit.role is None else unit.role.value, unit.state.value,
            None if base is None else base.dataset,
            None if base is None or base.elevation is None else repr(base.elevation),
            None if unit.thickness is None else unit.thickness.dataset,
        ))
        for number, component in enumerate(unit.components, start=1):
            rows.append((
                number, unit.code, component.code, component.name, Kind.COMPONENT.value,
                None if component.role is None else component.role.value, unit.state.value,
                None, None, None,
            ))
    return rows


def read_column(conn: sqlite3.Connection, table: str = TABLE) -> MaterialColumn | None:
    """La columna guardada en ``table`` (:data:`TABLE`; otra, la de una instantánea), o
    ``None`` si no hay tabla o no tiene filas. No la valida (:meth:`MaterialColumn.validate`).
    Una tabla incoherente (un componente sin su unidad, una clase desconocida) es
    :class:`ValueError`."""
    if _TABLE_NAME.fullmatch(table) is None:
        raise ValueError(f"nombre de tabla no válido: {table!r}")
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                          (table,)).fetchone()
    if exists is None:
        return None
    names = ", ".join(COLUMNS)
    rows = conn.execute(f"SELECT {names} FROM {table} ORDER BY parent, position, fid"
                        ).fetchall()
    if not rows:
        return None
    components: dict[str, list[Component]] = {}
    unit_rows = []
    for row in rows:
        record = dict(zip(COLUMNS, row, strict=True))
        if record["parent"]:
            if record["kind"] != Kind.COMPONENT.value:
                raise ValueError(f"{table}: «{record['code']}» tiene unidad y no es componente")
            components.setdefault(record["parent"], []).append(
                Component(record["code"], record["name"], record["role"]))
        else:
            unit_rows.append(record)
    units = []
    for record in unit_rows:
        base = None
        if record["base_dataset"] is not None:
            base = SurfaceRef(dataset=record["base_dataset"])
        elif record["base_elevation"] is not None:
            base = SurfaceRef(elevation=float(record["base_elevation"]))
        thickness = None
        if record["thickness_dataset"] is not None:
            thickness = SurfaceRef(dataset=record["thickness_dataset"])
        units.append(Unit(record["code"], record["name"], record["kind"], record["role"],
                          record["state"], base, thickness,
                          tuple(components.pop(record["code"], ()))))
    if components:
        raise ValueError(f"{table}: componentes sin su unidad: {', '.join(sorted(components))}")
    return MaterialColumn(tuple(units))


def negative_thickness(unit: Unit, value: float) -> ResError:
    """El error para el usuario de la rejilla de espesores de ``unit`` con espesores negativos
    (``res.thickness_negative``; RF-011-14), con el menor (``value``, m): lo lanza quien
    recibe ``reserves.kernel.NegativeThickness``."""
    surface = "" if unit.thickness is None else unit.thickness.shown
    return ResError("res.thickness_negative", obj=f"Unidad «{unit.shown}»",
                    field="thickness_dataset", value=float(value), surface=surface,
                    unit=unit.shown)
