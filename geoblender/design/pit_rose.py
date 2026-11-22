# SPDX-License-Identifier: GPL-3.0-or-later
"""La roseta de taludes de la corta (spec 018, T04; HU-018-1; RF-018-07, RF-018-08; plan 018 §5.1, §5.2.2 y §5.2.3; ADR-0027, ADR-0029;
RF-013-20, RF-009-24, RF-008-01).

Una roseta son **dos cosas**, como los perfiles de banco (:mod:`design.profiles`) y los de pista (:mod:`design.road_profiles`): su
fila en la tabla del proyecto ``des_pit_rose`` (:data:`TABLE`: ``code``, ``name``, quién y cuándo; ni un valor) y sus rangos, que
son parámetros de ``core.params`` (``des.rose.{r}.{i}.from_deg|to_deg|face_deg|berm_m``, :mod:`design.params`: ``{r}`` el código
inmutable de la roseta e ``{i}`` ``r1``, ``r2``… la posición del rango al crearla) con su tipo, origen, decisor e historial. Los rangos
son azimuts de la cara en ° ``[desde, hasta)``, cubren de 0 a 360° **sin huecos ni solapes**, y cada uno tiene su ángulo de cara α
(°, en (0; 90) exclusivo) y su berma B (m, ≥ 0). **T04 confirma la forma de T03** (``r{i}`` y los cuatro valores): no se cambia.

**Derivados** (RF-018-07, RF-018-08; no son parámetros): el avance entre bermas ``n·h/tan α + B`` (m) y el talud general
``atan(n·h / avance)`` (°), con ``n`` los bancos por berma; sin roseta valen α y B del perfil (:func:`profile_range`). El error es el
de la aritmética de ``float`` (≪ 10⁻⁹ relativo).

:func:`edit_pit_roses` es la operación de proyecto :data:`EDIT_PIT_ROSES` (``des.edit_pit_roses``, declarada en ``provenance``; no se
repite sola): en **una** transacción crea la tabla si falta, escribe las filas de las rosetas nuevas, renombra y da de alta los rangos
como filas ``create`` del historial de la persona, en el proyecto o, con :attr:`Declaration.version`, como valores propios de esa versión
(RF-009-24). **Todo se mira antes de escribir** (una roseta sin nombre, con el nombre de otra, sin rangos, con un hueco, un solape o un
valor fuera de rango se rechaza con ``DesignError`` sin registrar nada, ni una operación fallida); lo que falla dentro de la transacción
(un valor que el ámbito ya tiene, un origen o un decisor en blanco) la deshace entera y deja la operación «fallida».

Importar este módulo no registra nada: ``bl`` registra las operaciones y las familias. Python puro (nivel 8).

**Lo genérico de los datos con código** (la tabla, las filas, el código, la comprobación de los nombres, la declaración y el alta de
valores) está aquí y lo usa también :mod:`design.pit_ramp_def`: son lo mismo con otra tabla.
"""

from __future__ import annotations

import math
import numbers
import sqlite3
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.constraints.model import constraint_code
from ..core.content.builtin import GPKG_LAYER
from ..core.datasets.model import DatasetSpec, Store
from ..core.gpkg.base import set_column_titles
from ..core.params import ParameterStore
from ..core.provenance.contract import OperationDef
from ..core.provenance.operations import OperationProject, begin_operation
from .messages import DesignError
from .params import RoseParam, check_rose_value, rose_key
from .provenance import EDIT_PIT_ROSES, MODULE, PIT_PROJECT_OPERATIONS, PIT_ROSE_COMMAND

__all__ = [
    "CODE_PREFIX",
    "DECLARED_KINDS",
    "EDIT_COMMAND",
    "EDIT_PIT_ROSES",
    "OPERATIONS",
    "ROSES_ROLE",
    "TABLE",
    "Declaration",
    "EditedRoses",
    "RangeDerived",
    "RoseEdit",
    "RoseRange",
    "StoredEntry",
    "advance_m",
    "check_rose",
    "coded_check_names",
    "coded_create_table",
    "coded_dataset_spec",
    "coded_read",
    "coded_rename",
    "coded_write_value",
    "create_table",
    "dataset_spec",
    "derived",
    "edit_pit_roses",
    "overall_slope_deg",
    "profile_range",
    "range_at",
    "range_index",
    "read_roses",
    "rose_code",
    "rose_names",
]

TABLE = "des_pit_rose"
"""La tabla del proyecto de las rosetas (plan 018 §5.1): una fila por roseta, sin valores."""
EDIT_COMMAND = PIT_ROSE_COMMAND
"""La orden del catálogo que lanza la operación (la de «Nueva corta…» hasta que haya la propia: D-20)."""
ROSES_ROLE = "pit_roses"
"""El papel de :data:`TABLE` como salida de la operación."""
OPERATIONS: tuple[OperationDef, ...] = tuple(item for item in PIT_PROJECT_OPERATIONS if item.op_type == EDIT_PIT_ROSES)
"""La operación de este módulo (``des.edit_pit_roses``), de proyecto y sin repetición: la declara ``provenance`` (T03) y ``bl`` la
registra; **no se crea otra** definición."""
CODE_PREFIX = "rose"
"""Lo que lleva delante un código cuyo nombre no empieza por una letra (``10-60`` → ``rose_10_60``)."""
DECLARED_KINDS = ("ADOPTADO", "HIPÓTESIS")
"""Los tipos con que una persona declara los valores (D-5, D-6: ADOPTADO con su fuente, o HIPÓTESIS)."""

_IDENTIFIER = "Rosetas de taludes"
_DDL = """CREATE TABLE {table} (
  fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  uid TEXT NOT NULL UNIQUE,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL UNIQUE,
  created_by TEXT NOT NULL,
  created_at DATETIME NOT NULL
)"""
_TITLES = {"uid": "Identificador", "code": "Código", "name": "Nombre", "created_by": "Creado por", "created_at": "Creado el"}
"""Los títulos en español de las columnas, que QGIS muestra como alias."""
_COLUMNS = "fid, uid, code, name, created_by, created_at"
_ORDER = (RoseParam.FROM_DEG, RoseParam.TO_DEG, RoseParam.FACE_DEG, RoseParam.BERM)


# --- Lo genérico de un dato del proyecto con código (la roseta y la rampa) ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredEntry:
    """Una fila de ``des_pit_rose`` o ``des_pit_ramp``: ``code`` inmutable, ``name`` libre y único, quién la creó (``created_by``:
    usuario@equipo) y cuándo (``created_at``, UTC)."""

    fid: int
    uid: str
    code: str
    name: str
    created_by: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Declaration:
    """Lo que declara la persona de los valores que escribe (RF-008-01; D-5, D-6, D-19: ningún valor por defecto): su origen
    (``source``: la fuente), quién lo decide (``decided_by``), por qué (``reason``) y su tipo (``kind``: ``ADOPTADO`` o
    ``HIPÓTESIS``). Con ``version`` (código o uid), los valores son los propios de esa versión (RF-009-24) y no se escriben los del
    proyecto."""

    source: str
    decided_by: str
    reason: str
    source_kind: str = "person"
    kind: str = "ADOPTADO"
    version: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in DECLARED_KINDS:
            raise ValueError(f"un valor se declara {' o '.join(DECLARED_KINDS)}, no {self.kind!r}")


def coded_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Si la tabla ``table`` existe en el proyecto."""
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def coded_create_table(conn: sqlite3.Connection, table: str, identifier: str) -> bool:
    """Crea en la transacción de ``conn`` la tabla ``table`` si falta (como tabla de atributos de ``gpkg_contents``, con los
    títulos de sus columnas) y dice si la creó. No confirma."""
    if coded_exists(conn, table):
        return False
    conn.execute(_DDL.format(table=table))
    conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description) VALUES (?, 'attributes', ?, '')",
                 (table, identifier))
    set_column_titles(conn, table, _TITLES)
    return True


def coded_read(conn: sqlite3.Connection, table: str) -> tuple[StoredEntry, ...]:
    """Las filas de ``table`` en el orden en que se crearon (ninguna si aún no hay tabla)."""
    if not coded_exists(conn, table):
        return ()
    return tuple(StoredEntry(*row) for row in conn.execute(f"SELECT {_COLUMNS} FROM {table} ORDER BY fid"))


def coded_dataset_spec(table: str, role: str) -> DatasetSpec:
    """El dato del proyecto de ``table``: tabla de atributos de ``des`` en ``project.gpkg``, leída con ``core.gpkg_layer@1`` y no
    editable en QGIS (los valores no están aquí: son parámetros)."""
    return DatasetSpec(table, MODULE, "table", Store.GPKG, table, reader=GPKG_LAYER.id, role=role)


def coded_rename(conn: sqlite3.Connection, table: str, renamed: Sequence[tuple[str, str]]) -> None:
    """Pone a cada fila su nombre nuevo. En dos pasos: el nombre es único y SQLite lo comprueba fila a fila, así que intercambiar
    los de dos filas chocaría a mitad."""
    conn.executemany(f"UPDATE {table} SET name = '=' || uid WHERE code = ?", [(code,) for code, _name in renamed])
    conn.executemany(f"UPDATE {table} SET name = ? WHERE code = ?", [(name, code) for code, name in renamed])


def coded_check_names(items: Iterable[tuple[str, str]], code: str, what: str) -> None:
    """Comprueba el conjunto de ``(código, nombre)`` de un proyecto: ``DesignError`` ``code`` (``des.pit_rose_name_repeated`` o
    ``des.pit_ramp_name_repeated``) si uno repite el nombre de otro (sin distinguir mayúsculas), nombrando los dos;
    :class:`ValueError` si dos tienen el mismo código (un error del programa: el sistema lo fija al crear y es único)."""
    codes: dict[str, str] = {}
    names: dict[str, str] = {}
    for item_code, name in items:
        if item_code in codes:
            raise ValueError(f"el código {item_code!r} está en dos {what}")
        codes[item_code] = name
        key = name.casefold()
        if key in names:
            raise DesignError(code, obj=f"{what.capitalize()} «{item_code}»", field="name", value=name, profile=item_code,
                              other=names[key])
        names[key] = item_code


def coded_write_value(conn: sqlite3.Connection, store: ParameterStore, key: str, value: float | str, declared: Declaration) -> None:
    """Da de alta, en la transacción ``conn``, el valor ``key`` en el ámbito de ``declared`` (fila ``create`` del historial;
    RF-008-01): un valor que el ámbito tiene vacío «sin confirmar» se rellena cambiándolo; uno que ya tiene valor es
    ``core.param_exists``."""
    existing = store.get(key, version=declared.version, conn=conn)
    by = {"kind": declared.kind, "source": declared.source, "source_kind": declared.source_kind, "decided_by": declared.decided_by,
          "reason": declared.reason, "version": declared.version}
    if existing is not None and existing.value is None:
        store.change(conn, key, value=value, **by)
    else:
        store.create(conn, key, value, **by)


def _text(value: object, what: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    return value


# --- La tabla ------------------------------------------------------------------------------------------------------------------


def create_table(conn: sqlite3.Connection) -> bool:
    """Crea la tabla :data:`TABLE` en la transacción de ``conn`` si falta y dice si la creó. No confirma."""
    return coded_create_table(conn, TABLE, _IDENTIFIER)


def dataset_spec() -> DatasetSpec:
    """El dato del proyecto de :data:`TABLE` (tabla de atributos de ``des``, no editable en QGIS)."""
    return coded_dataset_spec(TABLE, ROSES_ROLE)


def read_roses(conn: sqlite3.Connection) -> tuple[StoredEntry, ...]:
    """Las rosetas del proyecto en el orden en que se crearon (ninguna si aún no hay tabla)."""
    return coded_read(conn, TABLE)


def rose_names(conn: sqlite3.Connection) -> dict[str, str]:
    """Código → nombre de las rosetas del proyecto: con lo que los mensajes nombran una roseta (RF-018-04). Vacío si no hay tabla."""
    return {item.code: item.name for item in read_roses(conn)}


def rose_code(name: str, taken: Iterable[str]) -> str:
    """El código de una roseta nueva: su nombre en ASCII y en minúsculas, sin tildes y con «_» en lugar de lo demás
    (``ROSETA TAJO`` → ``roseta_tajo``), con ``rose_`` delante si no empieza por una letra (``rose`` si no queda nada), de como
    mucho 32 caracteres, y ``_2``, ``_3``… si ya está en ``taken``: el código de una roseta existente no se reutiliza ni cambia."""
    return constraint_code(name, set(taken), prefix=CODE_PREFIX)


def range_index(position: int) -> str:
    """El código del rango que está en la posición ``position`` (desde 0) de la roseta al crearla: ``r1``, ``r2``…"""
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        raise ValueError(f"la posición de un rango es un entero ≥ 0, no {position!r}")
    return f"r{position + 1}"


# --- Los rangos y sus derivados (RF-018-07, RF-018-08) -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoseRange:
    """Un rango de azimut de la cara ``[from_deg, to_deg)`` (°) con su ángulo de cara ``face_deg`` α (°) y su berma ``berm_m`` B
    (m). No comprueba nada: lo hace :func:`check_rose`, que conoce la roseta y nombra la clave."""

    from_deg: float
    to_deg: float
    face_deg: float
    berm_m: float


@dataclass(frozen=True, slots=True)
class RangeDerived:
    """Lo derivado de un rango (RF-018-07, RF-018-08): su ``advance_m`` entre bermas, ``n·h/tan α + B`` (m), y su talud general
    ``overall_slope_deg``, ``atan(n·h / avance)`` (°)."""

    range: RoseRange
    advance_m: float
    overall_slope_deg: float


def _as_range(item: object) -> tuple[object, object, object, object]:
    """Los cuatro valores de un rango dado como :class:`RoseRange`, ``Mapping`` (por los nombres de :class:`~design.params.RoseParam`;
    el que falta es ``None``) o secuencia de cuatro (desde, hasta, α, B): :class:`ValueError` si no es una de las tres."""
    if isinstance(item, RoseRange):
        return item.from_deg, item.to_deg, item.face_deg, item.berm_m
    if isinstance(item, Mapping):
        unknown = [key for key in item if key not in {param.value for param in RoseParam}]
        if unknown:
            raise ValueError(f"{', '.join(map(str, unknown))} no son valores de un rango de una roseta")
        return tuple(item.get(param.value) for param in _ORDER)  # type: ignore[return-value]
    if isinstance(item, Sequence) and not isinstance(item, str) and len(item) == len(_ORDER):
        return item[0], item[1], item[2], item[3]
    raise ValueError(f"un rango es un RoseRange, un diccionario o (desde, hasta, α, B), no {item!r}")


def _gap(name: str, code: str, from_deg: float, to_deg: float) -> DesignError:
    return DesignError("des.pit_rose_gap", obj=f"Roseta de taludes «{name}»", field=f"des.rose.{code}", value=None, profile=name,
                       from_deg=from_deg, to_deg=to_deg)


def check_rose(name: str, code: str, ranges: Sequence[object]) -> tuple[RoseRange, ...]:
    """Los ``ranges`` de la roseta ``name`` de código ``code``, ya comprobados y **en orden de azimut**: cada valor con
    :func:`~design.params.check_rose_value` (``des.pit_rose_value_missing`` o ``_range`` nombrando la roseta, la clave
    ``des.rose.{code}.r{i}.<valor>`` —``{i}`` por la posición en ``ranges``— y el valor; α en (0; 90)°, B ≥ 0, azimuts de 0 a 360°),
    ``desde`` < ``hasta`` en cada rango, y que cubran **de 0 a 360° sin huecos ni solapes** (``des.pit_rose_gap`` o
    ``des.pit_rose_overlap`` con los azimuts). Sin rangos, ``des.pit_rose_no_ranges``. :class:`ValueError` si un rango no es de
    la forma de :func:`_as_range` y :class:`TypeError` si un valor no es un número (errores del programa; RF-018-07)."""
    items = tuple(ranges)
    if not items:
        raise DesignError("des.pit_rose_no_ranges", obj=f"Roseta de taludes «{name}»", field=f"des.rose.{code}", value=None, profile=name)
    found: list[RoseRange] = []
    for position, item in enumerate(items):
        index = range_index(position)
        values = [check_rose_value(name, code, index, param, value) for param, value in zip(_ORDER, _as_range(item), strict=True)]
        start, end, face, berm = values
        if end <= start:
            raise DesignError("des.pit_rose_value_range", obj=f"Roseta de taludes «{name}»", field=rose_key(code, index, RoseParam.TO_DEG),
                              value=end, profile=name, range=f"({start:g}; 360] °")
        found.append(RoseRange(start, end, face, berm))
    found.sort(key=lambda item: item.from_deg)
    if found[0].from_deg > 0.0:
        raise _gap(name, code, 0.0, found[0].from_deg)
    for before, after in zip(found, found[1:], strict=False):
        if after.from_deg > before.to_deg:
            raise _gap(name, code, before.to_deg, after.from_deg)
        if after.from_deg < before.to_deg:
            raise DesignError("des.pit_rose_overlap", obj=f"Roseta de taludes «{name}»", field=f"des.rose.{code}", value=None,
                              profile=name, from_deg=after.from_deg, to_deg=min(before.to_deg, after.to_deg))
    if found[-1].to_deg < 360.0:
        raise _gap(name, code, found[-1].to_deg, 360.0)
    return tuple(found)


def _real(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{what} es un número real, no {value!r}")
    found = float(value)
    if not math.isfinite(found):
        raise ValueError(f"{what} {value!r} no es finito")
    return found


def _check_advance_inputs(height_m: float, face_deg: float, berm_m: float, n_berm: int) -> tuple[float, float, float, int]:
    if isinstance(n_berm, bool) or not isinstance(n_berm, numbers.Integral):
        raise TypeError(f"los bancos por berma son un entero, no {n_berm!r}")
    if n_berm < 1:
        raise ValueError(f"los bancos por berma son ≥ 1, no {n_berm!r}")
    height = _real(height_m, "la altura")
    face = _real(face_deg, "el ángulo de cara")
    berm = _real(berm_m, "la berma")
    if height <= 0.0:
        raise ValueError(f"la altura {height_m!r} no es > 0")
    if not 0.0 < face < 90.0:
        raise ValueError(f"el ángulo de cara {face_deg!r} no está en (0; 90)°")
    if berm < 0.0:
        raise ValueError(f"la berma {berm_m!r} es < 0")
    return height, face, berm, int(n_berm)


def advance_m(height_m: float, face_deg: float, berm_m: float, n_berm: int = 1) -> float:
    """El avance horizontal entre bermas (m), ``n·h/tan α + B`` (RF-018-07, RF-018-08): con ``n_berm`` bancos por berma la cara es la de
    una altura ``n·h`` con el ángulo de cara α. :class:`ValueError` o :class:`TypeError` si algo está fuera de rango o no es del tipo
    (un error del programa: los valores de una roseta o de un perfil ya están comprobados)."""
    height, face, berm, count = _check_advance_inputs(height_m, face_deg, berm_m, n_berm)
    return count * height / math.tan(math.radians(face)) + berm


def overall_slope_deg(height_m: float, face_deg: float, berm_m: float, n_berm: int = 1) -> float:
    """El talud general (°), ``atan(n·h / avance)`` (RF-018-07), el ángulo del plano que une los pies de dos bermas consecutivas."""
    height, face, berm, count = _check_advance_inputs(height_m, face_deg, berm_m, n_berm)
    return math.degrees(math.atan(count * height / advance_m(height, face, berm, count)))


def profile_range(face_deg: float, berm_m: float) -> RoseRange:
    """El rango único de 0 a 360° con α y B **del perfil**: lo que vale «sin roseta» (RF-018-07)."""
    return RoseRange(0.0, 360.0, float(face_deg), float(berm_m))


def derived(ranges: Iterable[RoseRange], height_m: float, n_berm: int = 1) -> tuple[RangeDerived, ...]:
    """El avance y el talud general de cada uno de ``ranges`` para la altura ``height_m`` y ``n_berm`` bancos por berma
    (RF-018-07, RF-018-08), en el orden dado."""
    return tuple(RangeDerived(item, advance_m(height_m, item.face_deg, item.berm_m, n_berm),
                              overall_slope_deg(height_m, item.face_deg, item.berm_m, n_berm)) for item in ranges)


def range_at(ranges: Sequence[RoseRange], azimuth_deg: float) -> RoseRange:
    """El rango de ``ranges`` (ya comprobados) que contiene el azimut ``azimuth_deg`` (°, módulo 360; ``[desde, hasta)``).
    :class:`ValueError` si ninguno (``ranges`` no cubre el círculo: un error del programa)."""
    azimuth = _real(azimuth_deg, "el azimut") % 360.0
    for item in ranges:
        if item.from_deg <= azimuth < item.to_deg:
            return item
    raise ValueError(f"el azimut {azimuth_deg!r} no está en ningún rango")


# --- Lo que pide la persona ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoseEdit:
    """Una edición de una roseta. Sin ``code``, una **nueva**: su ``name`` y sus ``ranges`` (:class:`RoseRange`, diccionarios o
    ``(desde, hasta, α, B)``; sin valor por defecto: D-5, D-6); el código sale del nombre. Con ``code``, una que ya existe: ``name``
    la renombra (sin tocar el código) y ``ranges`` escribe **todos** sus rangos en el ámbito de la declaración (los del proyecto o
    los propios de una versión; los que el ámbito ya tiene se rechazan: cambiarlos es de «Parámetros»)."""

    name: str | None = None
    code: str = ""
    ranges: Sequence[object] | None = None


@dataclass(frozen=True, slots=True)
class EditedRoses:
    """Lo que dejó :func:`edit_pit_roses`: su ``operation_uid``, todas las ``roses`` del proyecto después, y los códigos de las
    rosetas ``created``, ``renamed`` y ``completed``."""

    operation_uid: str
    roses: tuple[StoredEntry, ...]
    created: tuple[str, ...]
    renamed: tuple[str, ...]
    completed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Plan:
    created: tuple[tuple[str, str, tuple[RoseRange, ...]], ...]
    renamed: tuple[tuple[str, str], ...]
    completed: tuple[tuple[str, tuple[RoseRange, ...]], ...]

    def settings(self, declaration: Declaration | None) -> dict[str, Any]:
        """Los ajustes de la operación (JSON, sin rutas)."""
        return {
            "created": [[code, name, len(ranges)] for code, name, ranges in self.created],
            "renamed": [[code, name] for code, name in self.renamed],
            "completed": [[code, len(ranges)] for code, ranges in self.completed],
            "version": None if declaration is None else declaration.version,
        }


def _plan(stored: Sequence[StoredEntry], edits: Sequence[RoseEdit], declaration: Declaration | None) -> _Plan:
    """Comprueba ``edits`` sobre las rosetas ``stored`` sin escribir nada y devuelve lo que se escribirá: ``DesignError`` (sin nombre,
    nombre repetido, sin rangos, hueco, solape, valor sin valor o fuera de rango); ``ValueError`` si la roseta no existe, sale dos
    veces, la edición no cambia nada o hay rangos sin declaración; ``TypeError`` si un nombre o un valor no es del tipo."""
    by_code = {item.code: item for item in stored}
    taken = set(by_code)
    names = {item.code: item.name for item in stored}
    fresh = sum(1 for edit in edits if not edit.code)
    created: list[tuple[str, str, tuple[RoseRange, ...]]] = []
    renamed: list[tuple[str, str]] = []
    completed: list[tuple[str, tuple[RoseRange, ...]]] = []
    seen: set[str] = set()
    position = 0
    for edit in edits:
        if edit.ranges is not None and declaration is None:
            raise ValueError("escribir los rangos de una roseta necesita su declaración: origen, decisor y motivo (Declaration)")
        raw = _text(edit.name, "el nombre de una roseta")
        if not edit.code:
            position += 1
            name = (raw or "").strip()
            if not name:
                shown = "nueva" if fresh == 1 else f"nueva {position}"
                raise DesignError("des.pit_rose_name_missing", obj=f"Roseta de taludes «{shown}»", field="name", value=raw, profile=shown)
            code = rose_code(name, taken)
            taken.add(code)
            names[code] = name
            created.append((code, name, check_rose(name, code, edit.ranges or ())))
            continue
        row = by_code.get(edit.code)
        if row is None:
            raise ValueError(f"la roseta {edit.code!r} no existe en el proyecto")
        if edit.code in seen:
            raise ValueError(f"la roseta {edit.code!r} sale dos veces en la misma edición")
        seen.add(edit.code)
        name = row.name if raw is None else raw.strip()
        if not name:
            raise DesignError("des.pit_rose_name_missing", obj=f"Roseta de taludes «{edit.code}»", field="name", value=raw, profile=edit.code)
        checked = None if edit.ranges is None else check_rose(name, edit.code, edit.ranges)
        if name == row.name and checked is None:
            raise ValueError(f"la edición de la roseta {edit.code!r} no cambia nada")
        if name != row.name:
            names[edit.code] = name
            renamed.append((edit.code, name))
        if checked is not None:
            completed.append((edit.code, checked))
    coded_check_names(names.items(), "des.pit_rose_name_repeated", "rosetas de taludes")
    return _Plan(tuple(created), tuple(renamed), tuple(completed))


def _write_ranges(conn: sqlite3.Connection, store: ParameterStore, code: str, ranges: Sequence[RoseRange], declared: Declaration) -> None:
    """Da de alta los rangos de la roseta ``code`` (``r1``, ``r2``… por su posición en azimut) en el ámbito de ``declared``."""
    for position, item in enumerate(ranges):
        index = range_index(position)
        for param, value in zip(_ORDER, (item.from_deg, item.to_deg, item.face_deg, item.berm_m), strict=True):
            coded_write_value(conn, store, rose_key(code, index, param), value, declared)


def edit_pit_roses(project: OperationProject, edits: Iterable[RoseEdit], declaration: Declaration | None = None) -> EditedRoses:
    """Registra ``des.edit_pit_roses``: aplica ``edits`` (:class:`RoseEdit`) en **una** transacción y devuelve lo que dejó. Cada
    roseta nueva recibe su código del nombre y sus rangos, y cada una que se completa los que da; ``declaration`` dice con qué
    origen, decisor, motivo y tipo se escriben (obligatoria si hay rangos) y en qué ámbito (el proyecto o una versión).

    Se mira todo antes de registrar nada: ``DesignError`` ``des.pit_rose_name_missing``, ``_name_repeated``, ``_no_ranges``, ``_gap``,
    ``_overlap``, ``_value_missing`` o ``_value_range`` nombrando la roseta, el campo y el valor (RF-018-07); ``ValueError`` o
    ``TypeError`` si la edición es un error del programa. Lo que falla después (``ParamError`` por un valor que ya existe o un origen
    sin decir, ``VersionError``…) lo deshace todo y deja la operación fallida."""
    edits = tuple(edits)
    if not edits:
        raise ValueError("una edición de las rosetas de taludes cambia al menos una")
    with project.read() as conn:
        stored = read_roses(conn)
    plan = _plan(stored, edits, declaration)
    handle = begin_operation(project, EDIT_PIT_ROSES, settings=plan.settings(declaration), executor="blender")
    try:
        with project.write_transaction() as conn:
            made = create_table(conn)
            for code, name, _ranges in plan.created:
                conn.execute(f"INSERT INTO {TABLE} (uid, code, name, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                             (uuid.uuid4().hex, code, name, project.session.user_host, handle.started_at))
            if plan.renamed:
                coded_rename(conn, TABLE, plan.renamed)
            if declaration is not None:
                store = ParameterStore(project)  # type: ignore[arg-type]
                for code, _name, ranges in plan.created:
                    _write_ranges(conn, store, code, ranges, declaration)
                for code, ranges in plan.completed:
                    _write_ranges(conn, store, code, ranges, declaration)
            handle.complete(
                conn, outputs=(dataset_spec(),) if made or plan.created or plan.renamed else (),
                message=(f"Rosetas de taludes: {len(plan.created)} creadas, {len(plan.renamed)} renombradas, "
                         f"{len(plan.completed)} completadas"))
    except Exception as error:
        handle.fail(str(error) or type(error).__name__)
        raise
    with project.read() as conn:
        after = read_roses(conn)
    return EditedRoses(handle.uid, after, tuple(code for code, _name, _ranges in plan.created), tuple(code for code, _name in plan.renamed),
                       tuple(code for code, _ranges in plan.completed))
