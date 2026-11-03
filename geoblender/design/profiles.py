# SPDX-License-Identifier: GPL-3.0-or-later
"""Los perfiles de banco del proyecto (spec 013, T16; HU-013-4; RF-013-18, RF-013-19; plan 013
§5.2.1, §5.2.2, D-17 y D-24; ADR-0027; RF-008-01).

Un perfil son **dos cosas**: su fila en la tabla del proyecto ``des_bench_profile`` (:data:`TABLE`:
``code``, ``name``, quién y cuándo; ni un valor) y sus cinco valores, que son parámetros de
``core.params`` (familias ``des.bench.{p}.…``, :mod:`design.params`) con su tipo, origen, decisor e
historial. El ``code`` (``[a-z][a-z0-9_]*``, ASCII; :func:`profile_code`) sale del nombre al crear
el perfil, es único y **no cambia nunca**: es la clave de sus parámetros. El ``name`` es libre
(``EXPL_10_60_6``) y único sin distinguir mayúsculas; renombrar no toca el código ni los valores.

:func:`edit_bench_profiles` es la operación de proyecto :data:`EDIT_BENCH_PROFILES`
(``des.edit_bench_profiles``; no se repite sola): en **una** transacción crea la tabla si falta,
escribe las filas de los perfiles nuevos, renombra y da de alta, como filas ``create`` del
historial de la persona, la altura, la cara, la berma y el ancla (y el factor de malla si se da) de
los perfiles que se crean o se completan (como ``core.edit_constraints`` con las restricciones de
la 012), en el proyecto o, con :attr:`ProfileDeclaration.version`, como valor propio de esa versión
(RF-009-24, RF-009-29). Completar rellena lo que falta en ese ámbito: un valor que el ámbito ya
tiene se rechaza (``core.param_exists``; cambiarlo es de «Parámetros») y uno que tiene vacío «sin
confirmar» (lo deja una operación que lo pidió antes de que nadie lo declarara) se rellena
cambiándolo.

**Todo se mira antes de escribir** (RF-013-19): un perfil sin nombre, con el nombre de otro, o con
un valor sin valor (no hay valor por defecto, D-7) o fuera de rango se rechaza con un
``DesignError`` que nombra el perfil, la clave del campo y el valor, sin registrar nada, ni una
operación fallida. Lo que falla dentro de la transacción (un valor que ya existe, un origen o un
decisor en blanco, una versión que no se puede editar) lo deshace entero y deja la operación
«fallida», como en la 012.

Importar este módulo no registra nada: ``bl`` registra :data:`OPERATIONS` (T21) y las familias de
:mod:`design.params`; las pruebas, a mano. Python puro (nivel 8: ``core``).
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, NamedTuple

from ..core.constraints.model import constraint_code
from ..core.content.builtin import GPKG_LAYER
from ..core.datasets.model import DatasetSpec, Store
from ..core.gpkg.base import set_column_titles
from ..core.params import ParameterStore
from ..core.provenance.contract import OperationDef
from ..core.provenance.operations import OperationProject, begin_operation
from .messages import DesignError
from .model import BenchProfile, check_profiles
from .params import BenchParam, bench_key, check_bench_value
from .provenance import MODULE, OP_VERSION

__all__ = [
    "CODE_PREFIX",
    "DECLARED_KINDS",
    "EDIT_BENCH_PROFILES",
    "EDIT_COMMAND",
    "OPERATIONS",
    "PROFILES_ROLE",
    "TABLE",
    "EditedProfiles",
    "ProfileDeclaration",
    "ProfileEdit",
    "StoredProfile",
    "create_table",
    "dataset_spec",
    "edit_bench_profiles",
    "profile_code",
    "profile_names",
    "read_profiles",
]

TABLE = "des_bench_profile"
"""La tabla del proyecto de los perfiles (plan §5.2.1): una fila por perfil, sin valores."""
EDIT_BENCH_PROFILES = "des.edit_bench_profiles"
"""La operación de proyecto que crea, completa y renombra perfiles (plan §5.2.3)."""
EDIT_COMMAND = "geoblender.des_edit_bench_profiles"
"""La orden «Perfiles de banco…» del catálogo, que la lanza (plan §5.3.3)."""
PROFILES_ROLE = "profiles"
"""El papel de :data:`TABLE` como salida de la operación."""
CODE_PREFIX = "p"
"""Lo que lleva delante un código cuyo nombre no empieza por una letra (``10-60`` → ``p_10_60``)."""
DECLARED_KINDS = ("ADOPTADO", "HIPÓTESIS")
"""Los tipos con que una persona declara los valores de un perfil (RF-013-18)."""

_LABEL = "Edition of the bench profiles"
_IDENTIFIER = "Perfiles de banco"
_DDL = f"""CREATE TABLE {TABLE} (
  fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  uid TEXT NOT NULL UNIQUE,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL UNIQUE,
  created_by TEXT NOT NULL,
  created_at DATETIME NOT NULL
)"""
_TITLES: Mapping[str, str] = MappingProxyType({
    "uid": "Identificador", "code": "Código", "name": "Nombre", "created_by": "Creado por",
    "created_at": "Creado el",
})
"""Los títulos en español de las columnas, que QGIS muestra como alias."""
_REQUIRED = (BenchParam.HEIGHT, BenchParam.FACE, BenchParam.BERM, BenchParam.ANCHOR)
"""Los cuatro valores que una persona declara siempre al crear (el factor de malla es opcional)."""
_COLUMNS = "fid, uid, code, name, created_by, created_at"

OPERATIONS: tuple[OperationDef, ...] = (
    OperationDef(EDIT_BENCH_PROFILES, OP_VERSION, MODULE, _LABEL, False,
                 commands=(EDIT_COMMAND,)),
)
"""Las operaciones de este módulo, de proyecto y sin repetición: ``bl`` las registra (T21)."""


# --- La tabla ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredProfile:
    """Una fila de ``des_bench_profile``: ``code`` inmutable, ``name`` libre y único, quién la
    creó (``created_by``: usuario@equipo) y cuándo (``created_at``, UTC)."""

    fid: int
    uid: str
    code: str
    name: str
    created_by: str
    created_at: str


def _exists(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (TABLE,)).fetchone() is not None


def create_table(conn: sqlite3.Connection) -> bool:
    """Crea en la transacción de ``conn`` la tabla :data:`TABLE` si falta (como tabla de
    atributos de ``gpkg_contents``, con los títulos de sus columnas) y dice si la creó. No
    confirma."""
    if _exists(conn):
        return False
    conn.execute(_DDL)
    conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description) "
                 "VALUES (?, 'attributes', ?, '')", (TABLE, _IDENTIFIER))
    set_column_titles(conn, TABLE, _TITLES)
    return True


def dataset_spec() -> DatasetSpec:
    """El dato del proyecto de :data:`TABLE` (plan §5.2.1): tabla de atributos de ``des`` en
    ``project.gpkg``, leída con ``core.gpkg_layer@1`` y no editable en QGIS (los valores del
    perfil no están aquí: son parámetros)."""
    return DatasetSpec(TABLE, MODULE, "table", Store.GPKG, TABLE, reader=GPKG_LAYER.id,
                       role=PROFILES_ROLE)


def read_profiles(conn: sqlite3.Connection) -> tuple[StoredProfile, ...]:
    """Los perfiles del proyecto en el orden en que se crearon (ninguno si aún no hay tabla)."""
    if not _exists(conn):
        return ()
    return tuple(StoredProfile(*row) for row in conn.execute(
        f"SELECT {_COLUMNS} FROM {TABLE} ORDER BY fid"))


def profile_names(conn: sqlite3.Connection) -> dict[str, str]:
    """Código → nombre de los perfiles del proyecto: con lo que los mensajes nombran un perfil
    (RF-013-19). Vacío si aún no hay tabla."""
    return {item.code: item.name for item in read_profiles(conn)}


def profile_code(name: str, taken: Iterable[str]) -> str:
    """El código de un perfil nuevo (D-17): su nombre en ASCII y en minúsculas, sin tildes y con
    «_» en lugar de lo demás (``EXPL_10_60_6`` → ``expl_10_60_6``), con ``p_`` delante si no
    empieza por una letra (``p`` si no queda nada), de como mucho 32 caracteres, y ``_2``,
    ``_3``… si ya está en ``taken``: el código de un perfil existente no se reutiliza ni cambia."""
    return constraint_code(name, set(taken), prefix=CODE_PREFIX)


# --- Lo que pide la persona ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileDeclaration:
    """Lo que declara la persona de los valores que escribe (RF-013-18, RF-008-01; D-7: ningún
    valor por defecto): su origen (``source``; ``source_kind``: ``person``, ``document``…), quién
    lo decide (``decided_by``), por qué (``reason``) y su tipo (``kind``: ``HIPÓTESIS`` o
    ``ADOPTADO``). Con ``version`` (código o uid), los valores son los propios de esa versión
    (RF-009-24) y no se escriben los del proyecto."""

    source: str
    decided_by: str
    reason: str
    source_kind: str = "person"
    kind: str = "HIPÓTESIS"
    version: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in DECLARED_KINDS:
            raise ValueError(f"el valor de un perfil se declara {' o '.join(DECLARED_KINDS)}, "
                             f"no {self.kind!r}")


@dataclass(frozen=True, slots=True)
class ProfileEdit:
    """Una edición de un perfil. Sin ``code``, un perfil **nuevo**: su ``name`` y sus ``values``
    (``height_m``, ``face_deg``, ``berm_m`` y ``anchor_m``, y el ``mesh_factor`` si se da) en m,
    ° y —; el código sale del nombre. Con ``code``, uno que ya existe: ``name`` lo renombra (sin
    tocar el código) y ``values`` lo completa en el ámbito de la declaración. Las claves de
    ``values`` son los valores de :class:`~design.params.BenchParam`; otra es un error del
    programa (``ValueError``). Un valor ``None`` es «sin valor»."""

    name: str | None = None
    code: str = ""
    values: Mapping[BenchParam | str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(
            {BenchParam(key): value for key, value in dict(self.values).items()}))


@dataclass(frozen=True, slots=True)
class EditedProfiles:
    """Lo que dejó :func:`edit_bench_profiles`: su ``operation_uid``, todos los ``profiles`` del
    proyecto después, y los códigos de los perfiles ``created``, ``renamed`` y ``completed``."""

    operation_uid: str
    profiles: tuple[StoredProfile, ...]
    created: tuple[str, ...]
    renamed: tuple[str, ...]
    completed: tuple[str, ...]


# --- Comprobar ------------------------------------------------------------------------------------


class _Entry(NamedTuple):
    """Un perfil como lo ve la comprobación de nombres: su código y su nombre."""

    code: str
    name: str


@dataclass(frozen=True, slots=True)
class _NewProfile:
    code: str
    name: str
    values: Mapping[BenchParam, float]


@dataclass(frozen=True, slots=True)
class _Plan:
    """Lo que escribirá una edición, ya comprobado: los perfiles nuevos, los renombrados
    (código, nombre nuevo) y los que se completan (código, valores)."""

    created: tuple[_NewProfile, ...]
    renamed: tuple[tuple[str, str], ...]
    completed: tuple[tuple[str, Mapping[BenchParam, float]], ...]

    def settings(self, declaration: ProfileDeclaration | None) -> dict[str, Any]:
        """Los ajustes de la operación (JSON, sin rutas)."""
        return {
            "created": [[item.code, item.name] for item in self.created],
            "renamed": [[code, name] for code, name in self.renamed],
            "completed": [[code, [param.value for param in values]]
                          for code, values in self.completed],
            "version": None if declaration is None else declaration.version,
        }


def _text(value: object, what: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    return value


def _plan(stored: Sequence[StoredProfile], edits: Sequence[ProfileEdit],
          declaration: ProfileDeclaration | None) -> _Plan:
    """Comprueba ``edits`` sobre los perfiles ``stored`` sin escribir nada y devuelve lo que se
    escribirá: ``DesignError`` (sin nombre, nombre repetido, valor sin valor o fuera de rango; el
    perfil se nombra por su nombre y, si no lo tiene, por su código o por «nuevo»);
    ``ValueError`` si el perfil no existe, sale dos veces, la edición no cambia nada o hay valores
    sin declaración; ``TypeError`` si un nombre o un valor no es del tipo."""
    by_code = {item.code: item for item in stored}
    taken = set(by_code)
    names = {item.code: item.name for item in stored}
    fresh = sum(1 for edit in edits if not edit.code)
    created: list[_NewProfile] = []
    renamed: list[tuple[str, str]] = []
    completed: list[tuple[str, Mapping[BenchParam, float]]] = []
    seen: set[str] = set()
    position = 0
    for edit in edits:
        if edit.values and declaration is None:
            raise ValueError("escribir valores de un perfil necesita su declaración: origen, "
                             "decisor y motivo (ProfileDeclaration)")
        raw = _text(edit.name, "el nombre de un perfil")
        if not edit.code:
            position += 1
            name = (raw or "").strip()
            if not name:
                shown = "nuevo" if fresh == 1 else f"nuevo {position}"
                raise DesignError("des.profile_name_missing", obj=f"Perfil de banco «{shown}»",
                                  field="name", value=raw, profile=shown)
            code = profile_code(name, taken)
            taken.add(code)
            extra = ({BenchParam.MESH_FACTOR.value: edit.values[BenchParam.MESH_FACTOR]}
                     if BenchParam.MESH_FACTOR in edit.values else {})
            profile = BenchProfile(code, name, **{param.value: edit.values.get(param)
                                                  for param in _REQUIRED}, **extra)
            names[code] = profile.name
            created.append(_NewProfile(code, profile.name, MappingProxyType({
                param: getattr(profile, param.value) for param in BenchParam
                if param in _REQUIRED or param in edit.values})))
            continue
        row = by_code.get(edit.code)
        if row is None:
            raise ValueError(f"el perfil {edit.code!r} no existe en el proyecto")
        if edit.code in seen:
            raise ValueError(f"el perfil {edit.code!r} sale dos veces en la misma edición")
        seen.add(edit.code)
        name = row.name if raw is None else raw.strip()
        if not name:
            raise DesignError("des.profile_name_missing", obj=f"Perfil de banco «{edit.code}»",
                              field="name", value=raw, profile=edit.code)
        checked = {param: check_bench_value(name, edit.code, param, value)
                   for param, value in edit.values.items()}
        if name == row.name and not checked:
            raise ValueError(f"la edición del perfil {edit.code!r} no cambia nada")
        if name != row.name:
            names[edit.code] = name
            renamed.append((edit.code, name))
        if checked:
            completed.append((edit.code, MappingProxyType(checked)))
    check_profiles(_Entry(code, name) for code, name in names.items())
    return _Plan(tuple(created), tuple(renamed), tuple(completed))


# --- Escribir --------------------------------------------------------------------------------------


def _write_values(conn: sqlite3.Connection, store: ParameterStore, code: str,
                  values: Mapping[BenchParam, float], declared: ProfileDeclaration) -> None:
    """Da de alta, en la transacción ``conn``, los ``values`` del perfil ``code`` en el ámbito de
    ``declared`` (filas ``create`` del historial; RF-008-01): un valor que el ámbito tiene vacío
    «sin confirmar» se rellena cambiándolo; uno que ya tiene valor es ``core.param_exists``."""
    for param in BenchParam:
        if param not in values:
            continue
        key = bench_key(code, param)
        existing = store.get(key, version=declared.version, conn=conn)
        by = {"kind": declared.kind, "source": declared.source,
              "source_kind": declared.source_kind, "decided_by": declared.decided_by,
              "reason": declared.reason, "version": declared.version}
        if existing is not None and existing.value is None:
            store.change(conn, key, value=values[param], **by)
        else:
            store.create(conn, key, values[param], **by)


def _rename(conn: sqlite3.Connection, renamed: Sequence[tuple[str, str]]) -> None:
    """Pone a cada perfil su nombre nuevo. En dos pasos: el nombre es único y SQLite lo comprueba
    fila a fila, así que intercambiar los de dos perfiles chocaría a mitad."""
    conn.executemany(f"UPDATE {TABLE} SET name = '=' || uid WHERE code = ?",
                     [(code,) for code, _name in renamed])
    conn.executemany(f"UPDATE {TABLE} SET name = ? WHERE code = ?",
                     [(name, code) for code, name in renamed])


def edit_bench_profiles(project: OperationProject, edits: Iterable[ProfileEdit],
                        declaration: ProfileDeclaration | None = None) -> EditedProfiles:
    """Registra ``des.edit_bench_profiles``: aplica ``edits`` (:class:`ProfileEdit`) en **una**
    transacción y devuelve lo que dejó. Cada perfil nuevo recibe su código del nombre y sus
    valores, y cada perfil que se completa los que da; ``declaration`` dice con qué origen,
    decisor, motivo y tipo se escriben (obligatoria si hay valores) y en qué ámbito (el proyecto o
    una versión).

    Se mira todo antes de registrar nada: ``DesignError`` ``des.profile_name_missing``,
    ``des.profile_name_repeated``, ``des.profile_value_missing`` o ``des.profile_value_range``
    nombrando el perfil, el campo y el valor (RF-013-19); ``ValueError`` o ``TypeError`` si la
    edición es un error del programa. Lo que falla después (``ParamError`` por un valor que ya
    existe o un origen sin decir, ``VersionError``…) lo deshace todo y deja la operación fallida.
    """
    edits = tuple(edits)
    if not edits:
        raise ValueError("una edición de los perfiles de banco cambia al menos uno")
    with project.read() as conn:
        stored = read_profiles(conn)
    plan = _plan(stored, edits, declaration)
    handle = begin_operation(project, EDIT_BENCH_PROFILES, settings=plan.settings(declaration),
                             executor="blender")
    try:
        with project.write_transaction() as conn:
            made = create_table(conn)
            for item in plan.created:
                conn.execute(
                    f"INSERT INTO {TABLE} (uid, code, name, created_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, item.code, item.name, project.session.user_host,
                     handle.started_at))
            if plan.renamed:
                _rename(conn, plan.renamed)
            if declaration is not None:
                store = ParameterStore(project)  # type: ignore[arg-type]
                for item in plan.created:
                    _write_values(conn, store, item.code, item.values, declaration)
                for code, values in plan.completed:
                    _write_values(conn, store, code, values, declaration)
            handle.complete(
                conn, outputs=(dataset_spec(),) if made or plan.created or plan.renamed else (),
                message=(f"Perfiles de banco: {len(plan.created)} creados, "
                         f"{len(plan.renamed)} renombrados, {len(plan.completed)} completados"))
    except Exception as error:
        handle.fail(str(error) or type(error).__name__)
        raise
    with project.read() as conn:
        after = read_profiles(conn)
    return EditedProfiles(handle.uid, after, tuple(item.code for item in plan.created),
                          tuple(code for code, _name in plan.renamed),
                          tuple(code for code, _values in plan.completed))
