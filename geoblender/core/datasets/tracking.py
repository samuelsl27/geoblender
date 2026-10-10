# SPDX-License-Identifier: GPL-3.0-or-later
"""Seguimiento y protección de las tablas de los datos del proyecto (spec 008; RF-008-21,
RF-008-52; ADR-0025 §4 y §6; plan 008 §5.2.1 y §5.4.2).

Las tablas y capas de ``project.gpkg`` que registra un dato se siguen sin hashearlas: la
comprobación (plan 008 §5.4.2) solo hashea lo que salta de tres señales, que Geoblender
anota tras su propia escritura, en la misma transacción, y compara por igualdad:

- **``gpkg_contents.last_change``**, que ponen en cada escritura los disparadores ``AFTER
  INSERT/UPDATE/DELETE`` de :func:`track_table` (``gbtc_<tabla>_ins``, ``_upd`` y ``_del``),
  con el formato del estándar (``AAAA-MM-DDTHH:MM:SS.mmmZ``). Están en SQL estándar, sin
  ``gb_writer()``, para que actúen también cuando escribe QGIS o cualquier otro programa, y
  solo escriben ``gpkg_contents``, tabla del estándar que QGIS ya escribe: ninguna tabla
  interna queda escribible desde fuera (spec 008 §7, RF-002-15). Un ``VACUUM`` no dispara
  nada;
- la **huella del SQL** de la tabla en ``sqlite_master``: un ``ALTER TABLE`` (añadir,
  renombrar o quitar una columna) no dispara nada pero la cambia;
- la **presencia de los disparadores**: GDAL rehace una tabla al cambiar sus campos
  (temporal, copia, ``DROP TABLE`` y ``RENAME``) y con ello los pierde, sin cambiar ni
  ``last_change`` ni, a veces, el SQL; :func:`ensure_triggers` los vuelve a poner.

:func:`table_states` da las tres de una vez (:class:`TableState`).

Lo importado de una entrada no se modifica (RF-008-52): :func:`protect_immutable` pone en su
tabla disparadores ``BEFORE INSERT/UPDATE/DELETE`` (``gbim_<tabla>_…``) que abortan para
cualquier conexión con «<tabla>: es lo importado de la entrada «<nombre>»: no se modifica»,
opcionalmente solo en las filas de un selector (``{"column": "input_uid", "equals": <uid>}``,
el de ``gb_dataset.selector``), para que varias entradas importen a una tabla común. Como
``INSERT OR REPLACE`` y ``UPDATE OR REPLACE`` borran la fila con la que chocan sin disparar
los ``BEFORE DELETE`` (``docs/trampas.md`` §6), con selector se rechaza también la fila que
chocaría con una protegida por su ``rowid`` o por un índice único de la tabla (los que hay
al protegerla; los de expresiones no). Un ``ALTER TABLE … DROP COLUMN`` sobre lo importado
pasa (no dispara nada) y la tabla rehecha pierde los disparadores: los dos los ve
:func:`table_states`, y el dato queda «dañado» (ADR-0025 §4; plan 008 §5.4.9).

Solo se siguen y protegen tablas de datos: existentes, registradas en ``gpkg_contents`` y
que no son del estándar (``gpkg_*``, ``rtree_*``, ``sqlite_*``) ni internas (``gb_*``).
Las funciones que escriben reciben la conexión de una transacción de escritura
(``GpkgConnection.transaction()``) y no la confirman.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..errors import ValidationError
from ..hashing import canonical_json, sha256_bytes

TRACKING_PREFIX = "gbtc_"
PROTECTION_PREFIX = "gbim_"
RESERVED_PREFIXES: tuple[str, ...] = ("gpkg_", "rtree_", "sqlite_", "gb_")
"""Prefijos de las tablas del estándar GeoPackage, de SQLite y de Geoblender (internas),
que no son de ningún dato."""
OPERATIONS: tuple[tuple[str, str], ...] = (
    ("ins", "INSERT"),
    ("upd", "UPDATE"),
    ("del", "DELETE"),
)
"""Sufijo del nombre del disparador y sentencia que lo dispara."""
LAST_CHANGE_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
"""La hora de la escritura con el formato de ``gpkg_contents.last_change`` (GeoPackage 1.4,
con milisegundos)."""
MSG_IMPORTED = "es lo importado de la entrada «{name}»: no se modifica"
"""El motivo con el que abortan los disparadores de lo importado (tras ``<tabla>: ``)."""
SELECTOR_KEYS: tuple[str, ...] = ("column", "equals")
SELECTOR_HASH_LENGTH = 12
_OBJ = "Tabla de un dato del proyecto"


@dataclass(frozen=True)
class TableState:
    """Lo que ve la comprobación de una tabla de datos (ADR-0025 §6).

    ``registered``: tiene fila en ``gpkg_contents``; ``exists``: está en ``sqlite_master``
    como tabla; ``last_change``: el de ``gpkg_contents`` (``None`` sin fila);
    ``schema_sha256``: sha256 del SQL de la tabla en ``sqlite_master`` (``None`` si no
    existe); ``triggers``: los disparadores de Geoblender (``gbtc_*`` y ``gbim_*``) que
    tiene."""

    table: str
    registered: bool
    exists: bool
    last_change: str | None
    schema_sha256: str | None
    triggers: frozenset[str]

    @property
    def missing_tracking(self) -> tuple[str, ...]:
        """Los disparadores del seguimiento que le faltan, en orden."""
        return tuple(
            name for name in tracking_trigger_names(self.table) if name not in self.triggers
        )

    @property
    def tracked(self) -> bool:
        """Verdadero si tiene los tres disparadores del seguimiento."""
        return not self.missing_tracking


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(value: str | int) -> str:
    if isinstance(value, int):
        return str(value)
    return "'" + value.replace("'", "''") + "'"


def _error(code: str, reason: str, field: str, value: object) -> ValidationError:
    return ValidationError(f"core.{code}", reason, obj=_OBJ, field=field, value=value)


def tracking_trigger_names(table: str) -> tuple[str, str, str]:
    """Los nombres de los disparadores del seguimiento de ``table``:
    ``gbtc_<tabla>_ins``, ``_upd`` y ``_del``."""
    ins, upd, delete = (f"{TRACKING_PREFIX}{table}_{suffix}" for suffix, _ in OPERATIONS)
    return ins, upd, delete


def _check_selector(where: Mapping[str, object]) -> tuple[str, str | int]:
    if not isinstance(where, Mapping):
        raise TypeError(f"el selector es un diccionario {{column, equals}}, no {where!r}")
    column = where.get("column")
    value = where.get("equals")
    if (
        set(where) != set(SELECTOR_KEYS)
        or not isinstance(column, str)
        or not column
        or isinstance(value, bool)
        or not isinstance(value, str | int)
    ):
        raise _error(
            "dataset_selector_invalid",
            'el selector de lo importado es {"column": <columna>, "equals": <texto o '
            "entero>}",
            "selector",
            dict(where),
        )
    return column, value


def protection_trigger_names(
    table: str, where: Mapping[str, object] | None = None
) -> tuple[str, str, str]:
    """Los nombres de los disparadores de lo importado de ``table``: ``gbim_<tabla>_ins``,
    ``_upd`` y ``_del`` o, con el selector ``where``, ``gbim_<tabla>_<huella>_…`` (los 12
    primeros caracteres del sha256 de su JSON canónico)."""
    stem = f"{PROTECTION_PREFIX}{table}"
    if where is not None:
        column, value = _check_selector(where)
        digest = sha256_bytes(canonical_json({"column": column, "equals": value}))
        stem = f"{stem}_{digest[:SELECTOR_HASH_LENGTH]}"
    ins, upd, delete = (f"{stem}_{suffix}" for suffix, _ in OPERATIONS)
    return ins, upd, delete


def _check_table(conn: sqlite3.Connection, table: str) -> None:
    """Rechaza lo que no es una tabla de datos: un nombre reservado, una tabla que no
    existe y una que no está en ``gpkg_contents`` (con el nombre exacto)."""
    if not isinstance(table, str):
        raise TypeError(f"el nombre de la tabla es un texto, no {table!r}")
    if table.lower().startswith(RESERVED_PREFIXES):
        raise _error(
            "dataset_table_reserved",
            "es una tabla del estándar GeoPackage, de SQLite o interna de Geoblender: no es "
            "de ningún dato",
            "tabla",
            table,
        )
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? COLLATE NOCASE",
        (table,),
    ).fetchone()
    if exists is None:
        raise _error("dataset_table_missing", "no existe en el GeoPackage", "tabla", table)
    registered = conn.execute(
        "SELECT 1 FROM gpkg_contents WHERE table_name = ?", (table,)
    ).fetchone()
    if registered is None:
        raise _error(
            "dataset_table_unregistered",
            "no está registrada en gpkg_contents con ese nombre: un dato del proyecto es una "
            "capa o tabla del GeoPackage",
            "tabla",
            table,
        )


def _tracking_sql(table: str) -> dict[str, str]:
    """El SQL de cada disparador del seguimiento, como lo guarda ``sqlite_master``."""
    statements: dict[str, str] = {}
    names = tracking_trigger_names(table)
    for name, (_, event) in zip(names, OPERATIONS, strict=True):
        statements[name] = (
            f"CREATE TRIGGER {_quote(name)} AFTER {event} ON {_quote(table)}\n"
            f"BEGIN UPDATE gpkg_contents SET last_change = {LAST_CHANGE_NOW} "
            f"WHERE table_name = {_literal(table)}; END"
        )
    return statements


def _current_sql(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ? COLLATE NOCASE",
        (name,),
    ).fetchone()
    return None if row is None else row[0]


def track_table(conn: sqlite3.Connection, table: str) -> bool:
    """Pone en ``table`` los disparadores que escriben ``gpkg_contents.last_change`` en
    cada inserción, cambio o borrado de filas (RF-008-21; ADR-0025 §6), y sustituye uno
    con el mismo nombre y otro SQL. Verdadero si creó o sustituyó alguno; volver a llamarla
    no cambia nada.

    ``ValidationError`` (``core.dataset_table_*``) si no es una tabla de datos;
    ``TypeError`` si el nombre no es un texto."""
    _check_table(conn, table)
    return _apply(conn, _tracking_sql(table))


def _apply(conn: sqlite3.Connection, statements: Mapping[str, str]) -> bool:
    changed = False
    for name, sql in statements.items():
        current = _current_sql(conn, name)
        if current == sql:
            continue
        if current is not None:
            conn.execute(f"DROP TRIGGER {_quote(name)}")
        conn.execute(sql)
        changed = True
    return changed


def ensure_triggers(conn: sqlite3.Connection, tables: Iterable[str]) -> list[str]:
    """:func:`track_table` en cada tabla de ``tables`` (tras comprobarlas todas): repone
    los disparadores del seguimiento que falten o que no sean los de Geoblender (una tabla
    rehecha por GDAL, un disparador quitado). Devuelve las tablas en las que puso alguno,
    en su orden. No toca los de lo importado (:func:`protect_immutable`): si faltan, el dato
    está dañado (plan 008 §5.4.9)."""
    if isinstance(tables, str):
        raise TypeError(f"se esperaba una lista de tablas, no el texto {tables!r}")
    names = list(tables)
    for table in names:
        _check_table(conn, table)
    return [table for table in names if _apply(conn, _tracking_sql(table))]


def _unique_keys(conn: sqlite3.Connection, table: str) -> list[tuple[str, ...]]:
    """Las columnas de cada índice único de ``table`` (sin los de expresiones)."""
    keys: list[tuple[str, ...]] = []
    for row in conn.execute(f"PRAGMA index_list({_quote(table)})").fetchall():
        index_name, unique = row[1], row[2]
        if not unique:
            continue
        columns = conn.execute(f"PRAGMA index_info({_quote(index_name)})").fetchall()
        if columns and all(column[2] is not None for column in columns):
            keys.append(tuple(column[2] for column in columns))
    return keys


def _protection_sql(
    conn: sqlite3.Connection,
    table: str,
    where: Mapping[str, object] | None,
    input_name: str,
) -> dict[str, str]:
    """El SQL de cada disparador de lo importado, como lo guarda ``sqlite_master``."""
    names = protection_trigger_names(table, where)
    message = f"{table}: {MSG_IMPORTED.format(name=input_name)}"
    body = f"BEGIN SELECT RAISE(ABORT, {_literal(message)}); END"
    conditions: dict[str, str | None] = {"INSERT": None, "UPDATE": None, "DELETE": None}
    if where is not None:
        column, value = _check_selector(where)
        known = {
            row[1].lower() for row in conn.execute(f"PRAGMA table_info({_quote(table)})")
        }
        if column.lower() not in known:
            raise _error(
                "dataset_selector_invalid",
                f"la tabla «{table}» no tiene esa columna",
                "columna del selector",
                column,
            )
        protected = f"{_quote(column)} = {_literal(value)}"
        clashes = ["rowid = NEW.rowid"] + [
            "(" + " AND ".join(f"{_quote(key)} = NEW.{_quote(key)}" for key in columns) + ")"
            for columns in _unique_keys(conn, table)
        ]
        clash = (
            f"EXISTS (SELECT 1 FROM {_quote(table)} WHERE {protected} "
            f"AND ({' OR '.join(clashes)}))"
        )
        conditions = {
            "INSERT": f"NEW.{protected} OR {clash}",
            "UPDATE": f"OLD.{protected} OR NEW.{protected} OR {clash}",
            "DELETE": f"OLD.{protected}",
        }
    statements: dict[str, str] = {}
    for name, (_, event) in zip(names, OPERATIONS, strict=True):
        condition = conditions[event]
        when = f" WHEN {condition}" if condition else ""
        statements[name] = (
            f"CREATE TRIGGER {_quote(name)} BEFORE {event} ON {_quote(table)}{when}\n{body}"
        )
    return statements


def protect_immutable(
    conn: sqlite3.Connection,
    table: str,
    where: Mapping[str, object] | None = None,
    *,
    input_name: str,
) -> bool:
    """Protege ``table`` como lo importado de la entrada ``input_name`` (RF-008-52;
    ADR-0025 §4): toda inserción, cambio o borrado aborta, desde cualquier conexión, con
    «<tabla>: es lo importado de la entrada «<nombre>»: no se modifica»; con ``where``
    (``{"column": <columna>, "equals": <texto o entero>}``), solo en las filas con ese
    valor (también la que entraría o saldría de ellas, o chocaría con una por su ``rowid``
    o por un índice único). Verdadero si los creó; si ya están igual, falso.

    ``ValidationError``: ``core.dataset_table_*`` si no es una tabla de datos,
    ``core.dataset_selector_invalid``, ``core.dataset_input_name_missing`` y
    ``core.dataset_protection_conflict`` si esas filas ya están protegidas de otro modo
    (para otra entrada). ``TypeError`` si ``where`` no es un diccionario o el nombre no es
    un texto."""
    if not isinstance(input_name, str):
        raise TypeError(f"el nombre de la entrada es un texto, no {input_name!r}")
    if where is not None and not isinstance(where, Mapping):
        raise TypeError(f"el selector es un diccionario {{column, equals}}, no {where!r}")
    _check_table(conn, table)
    if not input_name.strip():
        raise _error(
            "dataset_input_name_missing",
            "lo importado se protege con el nombre de su entrada, que lo dice al rechazar",
            "nombre de la entrada",
            input_name,
        )
    statements = _protection_sql(conn, table, where, input_name)
    current = {name: _current_sql(conn, name) for name in statements}
    if all(current[name] == sql for name, sql in statements.items()):
        return False
    if any(sql is not None and sql != statements[name] for name, sql in current.items()):
        raise _error(
            "dataset_protection_conflict",
            "esas filas ya están protegidas como lo importado de otra entrada o de otro modo",
            "tabla",
            table,
        )
    for name, sql in statements.items():
        if current[name] is None:
            conn.execute(sql)
    return True


def table_states(
    conn: sqlite3.Connection, tables: Iterable[str] | None = None
) -> dict[str, TableState]:
    """El estado de cada tabla de datos (:class:`TableState`): sin ``tables``, las de
    ``gpkg_contents`` y las que tienen disparadores de Geoblender (aunque ya no estén
    registradas); con ``tables``, esas, existan o no. Los nombres de las tablas se comparan
    sin distinguir mayúsculas, como hace SQLite; cada estado lleva el de ``gpkg_contents``
    si lo tiene."""
    if isinstance(tables, str):
        raise TypeError(f"se esperaba una lista de tablas, no el texto {tables!r}")
    contents: dict[str, tuple[str, object]] = {
        str(name).lower(): (str(name), change)
        for name, change in conn.execute("SELECT table_name, last_change FROM gpkg_contents")
    }
    sql_of: dict[str, tuple[str, str]] = {}
    triggers_of: dict[str, set[str]] = {}
    for kind, name, owner, sql in conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE type = 'table' "
        "OR (type = 'trigger' AND lower(substr(name, 1, 5)) IN (?, ?))",
        (TRACKING_PREFIX, PROTECTION_PREFIX),
    ):
        if kind == "table":
            sql_of[name.lower()] = (name, sql or "")
        else:
            triggers_of.setdefault(owner.lower(), set()).add(name)
    if tables is None:
        keys = list(contents) + [key for key in triggers_of if key not in contents]
        wanted = [(key, None) for key in keys]
    else:
        wanted = [(str(name).lower(), name) for name in tables]
    states: dict[str, TableState] = {}
    for key, requested in wanted:
        change = contents[key][1] if key in contents else None
        table_sql = sql_of.get(key)
        if key in contents:
            name = contents[key][0]
        elif table_sql is not None:
            name = table_sql[0]
        else:
            name = requested if requested is not None else key
        states[name if requested is None else requested] = TableState(
            table=name,
            registered=key in contents,
            exists=table_sql is not None,
            last_change=None if change is None else str(change),
            schema_sha256=(
                None if table_sql is None else sha256_bytes(table_sql[1].encode("utf-8"))
            ),
            triggers=frozenset(triggers_of.get(key, ())),
        )
    return states
