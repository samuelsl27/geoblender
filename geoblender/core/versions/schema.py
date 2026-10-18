# SPDX-License-Identifier: GPL-3.0-or-later
"""El esquema 3 del proyecto: versiones, revisiones y decisiones de la propiedad (spec 009;
RF-009-02, RF-009-03, RF-009-04, RF-009-06, RF-009-12; plan 009 §5.2.1–§5.2.3; ADR-0013;
formato-proyecto §3.6).

:func:`apply_schema_3` lleva una base del esquema 2 al 3 en la transacción que recibe. La usan
crear un proyecto (``core.project.schema.create_schema``: el esquema 2 y después esta) y la
migración 2 → 3 (``core.project.migrations.m0003``): así crear y migrar dan el mismo
``sqlite_master`` y las mismas filas de ``gpkg_extensions``. Es idempotente (lo que ya está como
debe no se toca) y no escribe ninguna fila salvo la declaración de las tablas nuevas: un proyecto
del 2 no tiene versiones, y todo lo que tiene es del proyecto (``version_uid = ''``,
``revision_uid = ''``).

Lo que añade:

- cinco tablas internas (:data:`TABLES`), fuera de ``gpkg_contents`` y declaradas en
  ``gpkg_extensions`` (``imga_geoblender``, ``write-only``) como las de la 008: las versiones
  (``gb_version``: código inmutable, estado como atributo, de cuál parte), sus revisiones
  (``gb_revision``: una abierta por versión viva; las demás, congeladas con su instantánea o
  cerradas al superarse), lo que congela cada revisión (``gb_revision_item``) y las decisiones
  de la propiedad con sus enlaces (``gb_decision``, ``gb_decision_link``), con sus índices
  (:data:`INDEXES`) y sus disparadores (:data:`TRIGGERS`);
- en las tablas de la 008 (``core.provenance.schema``): sus columnas de ``SCHEMA_3_COLUMNS``
  (con ``ALTER TABLE … ADD COLUMN``, que no copia ni mueve filas), el índice de nombres vivos
  por versión y dos índices parciales (:data:`PROVENANCE_INDEXES`), los disparadores que nombran
  las columnas nuevas y dos reglas que miran las versiones (:data:`PROVENANCE_TRIGGERS`). Lo que
  sustituye, por nombre, está en :data:`REPLACED`.

Reglas (los disparadores abortan con ``<tabla>: <motivo>``; ``gb_writer()`` no es seguridad:
evita que otro programa, como QGIS, altere por error lo que solo gestiona Geoblender; en una
conexión ajena la función no existe y la sentencia ni se prepara):

- solo escribe una conexión de Geoblender, y **nada se borra** (RF-009-12), tampoco con
  ``REPLACE``, que borraría la fila que choca sin disparar los ``BEFORE DELETE``: se rechaza
  una fila con la identidad de otra (:data:`UNIQUE_KEYS`), otra versión VIGENTE (sustituiría a
  la que hay; D-3) y otra revisión abierta de la misma versión (RF-009-06);
- lo congelado, las decisiones y sus enlaces son de solo inserción (:data:`APPEND_ONLY_TABLES`);
- de una versión no cambia su identidad (:data:`FIXED_COLUMNS`); su estado solo pasa de
  BORRADOR a VIGENTE o DESCARTADO y de VIGENTE a SUPERADO o DESCARTADO (RF-009-03), y de una
  SUPERADO o DESCARTADO ya no cambia nada (RF-009-04, también para quien escribe en la base);
- una revisión nueva está abierta y es de una versión BORRADOR o VIGENTE; una abierta se
  congela o se cierra una vez; de una congelada solo cambia la marca de «alterada» (D-31), y
  una cerrada no cambia (RF-009-04: «modificar una revisión congelada»);
- de un dato no cambia su versión, ni de una operación su revisión; un nombre vivo en cada
  versión y uno en el proyecto (plan §5.2.2);
- una operación de versión se registra en la revisión abierta de una versión BORRADOR o
  VIGENTE, y una de proyecto, sin revisión (``gb_operation_scope``; RF-009-04, RF-009-05);
- un parámetro de versión solo se crea o se cambia en una versión BORRADOR o VIGENTE
  (``gb_parameter_version_ins`` y ``gb_parameter_version_upd``; RF-009-04: «cambiar un
  parámetro suyo»); escribir el mismo valor sí pasa, como en las columnas fijas de la 008.

Las condiciones se escriben de modo que un valor nulo no las cumpla: una columna obligatoria
que falta da el error ``NOT NULL`` de SQLite, no el de una regla. Este módulo no importa la
lógica de la procedencia, solo su esquema (``core.provenance.schema``, SQL y reglas de
columnas), del que es la continuación.
"""

from __future__ import annotations

import sqlite3

from ..gpkg.base import EXTENSION_NAME, register_internal_table
from ..provenance import schema as provenance_schema

TABLES: dict[str, str] = {
    "gb_version": """CREATE TABLE IF NOT EXISTS gb_version (
  fid                 INTEGER  PRIMARY KEY AUTOINCREMENT,
  uid                 TEXT     NOT NULL UNIQUE,
  code                TEXT     NOT NULL UNIQUE,            -- 'V01', 'V10'…; inmutable: nombra snapshots/
  feature             TEXT     NOT NULL,                   -- el rasgo (<rasgo> de Vnn_<rasgo>)
  title               TEXT     NOT NULL,                   -- lo cambia el renombrado (RF-009-22)
  status              TEXT     NOT NULL DEFAULT 'BORRADOR'
                      CHECK (status IN ('BORRADOR','VIGENTE','SUPERADO','DESCARTADO')),
  parent_uid          TEXT     REFERENCES gb_version(uid), -- la versión de la que parte
  parent_revision_uid TEXT,                                -- su última revisión congelada al crearla (RF-009-01); NULL si no había
  request             TEXT,                                -- encargo, texto libre hasta R-63
  reason_created      TEXT     NOT NULL CHECK (length(trim(reason_created)) > 0),
  reason_closed       TEXT,                                -- al superarse o descartarse
  created_at          DATETIME NOT NULL,
  created_by          TEXT     NOT NULL,                   -- usuario@equipo
  status_changed_at   DATETIME NOT NULL,
  status_changed_by   TEXT     NOT NULL,
  modified_at         DATETIME NOT NULL,
  CHECK (status NOT IN ('SUPERADO','DESCARTADO') OR reason_closed IS NOT NULL)
)""",
    "gb_revision": """CREATE TABLE IF NOT EXISTS gb_revision (
  fid                 INTEGER  PRIMARY KEY AUTOINCREMENT,
  uid                 TEXT     NOT NULL UNIQUE,
  version_uid         TEXT     NOT NULL REFERENCES gb_version(uid),
  number              INTEGER  NOT NULL CHECK (number >= 1),   -- V10.r2 → 2
  state               TEXT     NOT NULL DEFAULT 'open' CHECK (state IN ('open','frozen','closed')),
  reason              TEXT     NOT NULL CHECK (length(trim(reason)) > 0),
  created_at          DATETIME NOT NULL,
  created_by          TEXT     NOT NULL,
  closed_at           DATETIME,                               -- congelada o «cerrada al superarse»
  closed_by           TEXT,
  snapshot_dir        TEXT,                                   -- 'snapshots/V10.r2'
  snapshot_sha256     TEXT,                                   -- huella de su manifest.json
  snapshot_bytes      INTEGER,                                -- lo que copió (RNF-009-06; informe)
  geoblender_version  TEXT,                                   -- con la que se congeló
  accepted            TEXT,                                   -- JSON: lo aceptado al congelar (RF-009-08)
  altered_at          DATETIME,                               -- «alterada» (RF-009-09; D-31); NULL si coincide
  altered_detail      TEXT,                                   -- JSON: qué no coincide
  UNIQUE (version_uid, number),
  CHECK ((state = 'frozen') = (snapshot_dir IS NOT NULL AND snapshot_sha256 IS NOT NULL)),
  CHECK ((state = 'open') = (closed_at IS NULL)),
  CHECK (state = 'frozen' OR altered_at IS NULL)
)""",
    "gb_revision_item": """CREATE TABLE IF NOT EXISTS gb_revision_item (  -- solo inserción, al congelar
  fid                 INTEGER  PRIMARY KEY AUTOINCREMENT,
  revision_uid        TEXT     NOT NULL REFERENCES gb_revision(uid),
  item_kind           TEXT     NOT NULL CHECK (item_kind IN ('dataset','input','parameter','operation','figure')),
  item_uid            TEXT     NOT NULL,
  part                TEXT     NOT NULL CHECK (part IN ('produced','upstream','immutable','inherited')),
  item_rev            INTEGER,             -- parámetro: la fila del historial que usó
  content_sha256      TEXT,                -- dato o entrada: el contenido congelado; parámetro: value_sha256
  copied              BOOLEAN  NOT NULL DEFAULT 0,  -- copiado en ESTA instantánea
  snapshot_path       TEXT,                -- dónde está la copia (en esta o en otra instantánea); NULL en lo inmutable del proyecto
  snapshot_layer      TEXT,                -- su tabla o capa en el GeoPackage de la instantánea
  file_sha256         TEXT,                -- huella del fichero de la copia
  file_size           INTEGER,
  state               TEXT     NOT NULL DEFAULT 'current'
                      CHECK (state IN ('current','stale','review','unlocatable','not_reproducible')),
  UNIQUE (revision_uid, item_kind, item_uid)
)""",
    "gb_decision": """CREATE TABLE IF NOT EXISTS gb_decision (  -- solo inserción (RF-009-12, RF-009-13)
  fid                 INTEGER  PRIMARY KEY AUTOINCREMENT,
  uid                 TEXT     NOT NULL UNIQUE,
  decided_by          TEXT     NOT NULL,   -- quién decide («Propiedad: D. Juan …»)
  decided_at          DATE     NOT NULL,
  what                TEXT     NOT NULL CHECK (length(trim(what)) > 0),
  source_input_uid    TEXT     REFERENCES gb_input(uid),   -- documento o captura registrado (su original, RF-008-53)
  source_text         TEXT,                               -- o la referencia en texto («correo del 03/10/2026»)
  recorded_by         TEXT     NOT NULL,
  recorded_at         DATETIME NOT NULL,
  CHECK (source_input_uid IS NOT NULL OR length(trim(coalesce(source_text, ''))) > 0)
)""",
    "gb_decision_link": """CREATE TABLE IF NOT EXISTS gb_decision_link (  -- solo inserción
  fid                 INTEGER  PRIMARY KEY AUTOINCREMENT,
  decision_uid        TEXT     NOT NULL REFERENCES gb_decision(uid),
  item_kind           TEXT     NOT NULL CHECK (item_kind IN ('parameter','version')),
  item_uid            TEXT     NOT NULL,   -- gb_parameter.key (todos sus ámbitos) o gb_version.uid
  UNIQUE (decision_uid, item_kind, item_uid)
)""",
}
"""El SQL de cada tabla nueva (plan 009 §5.2.1), en el orden en que se crean."""

INDEXES: dict[str, str] = {
    "gb_version_single_current": (  # una sola VIGENTE (D-3)
        "CREATE UNIQUE INDEX IF NOT EXISTS gb_version_single_current ON gb_version(status) "
        "WHERE status = 'VIGENTE'"
    ),
    "gb_revision_single_open": (  # una sola abierta por versión (RF-009-06)
        "CREATE UNIQUE INDEX IF NOT EXISTS gb_revision_single_open ON gb_revision(version_uid) "
        "WHERE state = 'open'"
    ),
    "gb_revision_item_copy": (  # un contenido ya copiado no se copia otra vez (RNF-009-06)
        "CREATE INDEX IF NOT EXISTS gb_revision_item_copy ON gb_revision_item(content_sha256) "
        "WHERE copied"
    ),
}
"""Los índices de las tablas nuevas que no salen de sus restricciones."""

INTERNAL_TABLES: tuple[str, ...] = tuple(TABLES)

APPEND_ONLY_TABLES: tuple[str, ...] = ("gb_revision_item", "gb_decision", "gb_decision_link")
"""Tablas de solo inserción: ninguna fila cambia ni se borra."""

EDITABLE_STATUSES: tuple[str, ...] = ("BORRADOR", "VIGENTE")
"""Los estados de una versión en la que se trabaja (RF-009-04): tiene revisión abierta, y en
ella se registran operaciones y se cambian sus parámetros."""
CLOSED_STATUSES: tuple[str, ...] = ("SUPERADO", "DESCARTADO")
"""Los estados de una versión que ya no cambia (RF-009-04)."""
CURRENT_STATUS = "VIGENTE"
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "BORRADOR": ("VIGENTE", "DESCARTADO"),
    "VIGENTE": ("SUPERADO", "DESCARTADO"),
}
"""Los cambios de estado admitidos (RF-009-03)."""

OPEN, FROZEN, CLOSED = "open", "frozen", "closed"
"""Los estados de una revisión."""
ALTERED_COLUMNS: tuple[str, ...] = ("altered_at", "altered_detail")
"""Lo único que cambia de una revisión congelada: la marca de «alterada» (D-31)."""

FIXED_COLUMNS: dict[str, tuple[str, ...]] = {
    "gb_version": (
        "fid",
        "uid",
        "code",
        "feature",
        "parent_uid",
        "parent_revision_uid",
        "request",
        "reason_created",
        "created_at",
        "created_by",
    ),
    "gb_revision": ("fid", "uid", "version_uid", "number", "reason", "created_at", "created_by"),
}
"""Las columnas que no cambian nunca en las tablas nuevas que no son de solo inserción."""

MUTABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "gb_version": (
        "title",
        "status",
        "reason_closed",
        "status_changed_at",
        "status_changed_by",
        "modified_at",
    ),
    "gb_revision": (
        "state",
        "closed_at",
        "closed_by",
        "snapshot_dir",
        "snapshot_sha256",
        "snapshot_bytes",
        "geoblender_version",
        "accepted",
        "altered_at",
        "altered_detail",
    ),
}
"""Las columnas que cambian (con las reglas de estado de cada tabla)."""

UNIQUE_KEYS: dict[str, tuple[tuple[str, ...], ...]] = {
    "gb_version": (("fid",), ("uid",), ("code",)),
    "gb_revision": (("fid",), ("uid",), ("version_uid", "number")),
    "gb_revision_item": (("fid",), ("revision_uid", "item_kind", "item_uid")),
    "gb_decision": (("fid",), ("uid",)),
    "gb_decision_link": (("fid",), ("decision_uid", "item_kind", "item_uid")),
}
"""La identidad de una fila de cada tabla nueva: una fila nueva con una que ya existe se
rechaza (``REPLACE`` borraría la anterior). Aparte, la VIGENTE (``gb_version_current_ins`` y
``_upd``) y la revisión abierta de cada versión (``gb_revision_open_ins``)."""

MSG_WRITER_ONLY = provenance_schema.MSG_WRITER_ONLY
MSG_APPEND_ONLY = provenance_schema.MSG_APPEND_ONLY
MSG_NO_REPLACE = provenance_schema.MSG_NO_REPLACE
MSG_NO_DELETE = (
    "no se borra: descartar una versión la marca «registro, no usar» y la conserva entera"
)
MSG_FIXED: dict[str, str] = {
    "gb_version": (
        "la identidad de una versión (código, rasgo, de cuál parte, encargo, motivo y alta) "
        "no cambia"
    ),
    "gb_revision": "la identidad de una revisión (versión, número, motivo y alta) no cambia",
}
MSG_STATUS = (
    "el estado de una versión solo pasa de BORRADOR a VIGENTE o DESCARTADO y de VIGENTE a "
    "SUPERADO o DESCARTADO"
)
MSG_CLOSED = (
    "una versión SUPERADO o DESCARTADO no cambia: cree una versión nueva a partir de ella"
)
MSG_CURRENT = "ya hay otra versión VIGENTE: antes pasa a SUPERADO"
MSG_REVISION_NEW = "una revisión nueva está abierta y es de una versión BORRADOR o VIGENTE"
MSG_REVISION_OPEN = "esa versión ya tiene una revisión abierta"
MSG_REVISION_STATE = (
    "una revisión abierta se congela o se cierra una vez; de una congelada solo cambia la marca "
    "de alterada, y una cerrada no cambia"
)
MSG_OPERATION_SCOPE = (
    "una operación de versión se registra en la revisión abierta de una versión BORRADOR o "
    "VIGENTE, y una del proyecto, sin revisión"
)
MSG_PARAMETER_VERSION = (
    "un parámetro de versión solo se crea o se cambia en una versión BORRADOR o VIGENTE"
)
"""Los motivos con los que abortan los disparadores (tras ``<tabla>: ``)."""


def _trigger(name: str, timing: str, table: str, when: str | None, message: str) -> str:
    condition = f"\nWHEN {when}" if when else ""
    text = f"{table}: {message}".replace("'", "''")
    return (
        f"CREATE TRIGGER IF NOT EXISTS {name} {timing} ON {table}{condition}\n"
        f"BEGIN SELECT RAISE(ABORT, '{text}'); END"
    )


def _any_changed(columns: tuple[str, ...]) -> str:
    return " OR ".join(f"NEW.{column} IS NOT OLD.{column}" for column in columns)


def _row_exists(table: str, key: tuple[str, ...]) -> str:
    match = " AND ".join(f"{column} = NEW.{column}" for column in key)
    return f"EXISTS (SELECT 1 FROM {table} WHERE {match})"


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _not_editable(version: str) -> str:
    """``version`` (una expresión) no es una versión BORRADOR o VIGENTE; falso si es nula."""
    return (
        f"({version} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM gb_version "
        f"WHERE uid = {version} AND status IN ({_quoted(EDITABLE_STATUSES)})))"
    )


def _triggers() -> dict[str, str]:
    writer = "gb_writer() IS NOT 1"
    triggers: dict[str, str] = {}

    def add(table: str, suffix: str, timing: str, when: str | None, message: str) -> None:
        name = f"{table}_{suffix}"
        triggers[name] = _trigger(name, timing, table, when, message)

    for table in TABLES:
        append_only = table in APPEND_ONLY_TABLES
        add(table, "w_ins", "BEFORE INSERT", writer, MSG_WRITER_ONLY)
        exists = " OR ".join(_row_exists(table, key) for key in UNIQUE_KEYS[table])
        add(table, "no_replace", "BEFORE INSERT", exists,
            MSG_APPEND_ONLY if append_only else MSG_NO_REPLACE)
        if append_only:
            add(table, "no_upd", "BEFORE UPDATE", None, MSG_APPEND_ONLY)
            add(table, "no_del", "BEFORE DELETE", None, MSG_APPEND_ONLY)
            continue
        add(table, "w_upd", "BEFORE UPDATE", writer, MSG_WRITER_ONLY)
        add(table, "no_del", "BEFORE DELETE", None, MSG_NO_DELETE)
        fixed = FIXED_COLUMNS[table]
        add(table, "fixed", f"BEFORE UPDATE OF {', '.join(fixed)}", _any_changed(fixed),
            MSG_FIXED[table])

    # gb_version: los cambios de estado, lo cerrado y una sola VIGENTE.
    allowed = " OR ".join(
        f"(OLD.status = '{source}' AND NEW.status IN ({_quoted(targets)}))"
        for source, targets in TRANSITIONS.items()
    )
    add("gb_version", "status", "BEFORE UPDATE OF status",
        f"NEW.status IS NOT OLD.status AND NOT ({allowed})", MSG_STATUS)
    others = tuple(column for column in MUTABLE_COLUMNS["gb_version"] if column != "status")
    add("gb_version", "closed", f"BEFORE UPDATE OF {', '.join(others)}",
        f"OLD.status IN ({_quoted(CLOSED_STATUSES)}) AND ({_any_changed(others)})", MSG_CLOSED)
    current = f"status = '{CURRENT_STATUS}'"
    add("gb_version", "current_ins", "BEFORE INSERT",
        f"NEW.{current} AND EXISTS (SELECT 1 FROM gb_version WHERE {current})", MSG_CURRENT)
    add("gb_version", "current_upd", "BEFORE UPDATE OF status",
        f"NEW.{current} AND EXISTS (SELECT 1 FROM gb_version WHERE {current} "
        "AND fid <> OLD.fid)", MSG_CURRENT)

    # gb_revision: nueva y abierta en una versión viva, una abierta por versión, y sus estados.
    add("gb_revision", "new", "BEFORE INSERT",
        f"NEW.state <> '{OPEN}' OR {_not_editable('NEW.version_uid')}", MSG_REVISION_NEW)
    add("gb_revision", "open_ins", "BEFORE INSERT",
        f"NEW.state = '{OPEN}' AND EXISTS (SELECT 1 FROM gb_revision "
        f"WHERE version_uid = NEW.version_uid AND state = '{OPEN}')", MSG_REVISION_OPEN)
    mutable = MUTABLE_COLUMNS["gb_revision"]
    kept = tuple(column for column in mutable if column not in ALTERED_COLUMNS)
    add("gb_revision", "state", f"BEFORE UPDATE OF {', '.join(mutable)}",
        f"(OLD.state = '{FROZEN}' AND ({_any_changed(kept)})) "
        f"OR (OLD.state = '{CLOSED}' AND ({_any_changed(mutable)}))", MSG_REVISION_STATE)
    return triggers


TRIGGERS: dict[str, str] = _triggers()
"""El SQL de cada disparador de las tablas nuevas, por nombre (``<tabla>_<regla>``)."""


def _provenance_triggers() -> dict[str, str]:
    triggers = dict(provenance_schema.SCHEMA_3_TRIGGERS)
    open_revision = (
        "SELECT 1 FROM gb_revision AS r JOIN gb_version AS v ON v.uid = r.version_uid "
        f"WHERE r.uid = NEW.revision_uid AND r.state = '{OPEN}' "
        f"AND v.status IN ({_quoted(EDITABLE_STATUSES)})"
    )
    triggers["gb_operation_scope"] = _trigger(
        "gb_operation_scope", "BEFORE INSERT", "gb_operation",
        "(NEW.scope = 'version') <> (NEW.revision_uid <> '') "
        f"OR (NEW.revision_uid <> '' AND NOT EXISTS ({open_revision}))",
        MSG_OPERATION_SCOPE,
    )
    triggers["gb_parameter_version_ins"] = _trigger(
        "gb_parameter_version_ins", "BEFORE INSERT", "gb_parameter",
        f"NEW.scope = 'version' AND {_not_editable('NEW.scope_uid')}", MSG_PARAMETER_VERSION,
    )
    changed = provenance_schema.MUTABLE_COLUMNS["gb_parameter"]
    triggers["gb_parameter_version_upd"] = _trigger(
        "gb_parameter_version_upd", f"BEFORE UPDATE OF {', '.join(changed)}", "gb_parameter",
        f"NEW.scope = 'version' AND ({_any_changed(changed)}) "
        f"AND {_not_editable('NEW.scope_uid')}", MSG_PARAMETER_VERSION,
    )
    return triggers


PROVENANCE_TRIGGERS: dict[str, str] = _provenance_triggers()
"""Los disparadores del esquema 3 en las tablas de la 008: los que rehace porque nombran sus
columnas nuevas (``core.provenance.schema.SCHEMA_3_TRIGGERS``) y ``gb_operation_scope``,
``gb_parameter_version_ins`` y ``gb_parameter_version_upd``."""

PROVENANCE_INDEXES: dict[str, str] = dict(provenance_schema.SCHEMA_3_INDEXES)
"""Los índices del esquema 3 en las tablas de la 008
(``core.provenance.schema.SCHEMA_3_INDEXES``)."""

REPLACED: tuple[tuple[str, str], ...] = (
    *(("index", name) for name in PROVENANCE_INDEXES if name in provenance_schema.INDEXES),
    *(("trigger", name) for name in PROVENANCE_TRIGGERS if name in provenance_schema.TRIGGERS),
)
"""Lo del esquema 2 que el 3 sustituye (tipo y nombre): el índice de nombres vivos y los
disparadores que nombran las columnas nuevas."""


def stored_sql(sql: str) -> str:
    """El SQL de ``sql`` como lo guarda ``sqlite_master`` (sin «IF NOT EXISTS»)."""
    return sql.replace(" IF NOT EXISTS ", " ", 1)


def _declared(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM gpkg_extensions WHERE table_name = ? AND column_name IS NULL "
        "AND extension_name = ?",
        (table, EXTENSION_NAME),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _replace(conn: sqlite3.Connection, kind: str, name: str, sql: str) -> None:
    """Deja el índice o el disparador ``name`` con ``sql``: si ya lo tiene, no lo toca."""
    wanted = stored_sql(sql)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?", (kind, name)
    ).fetchone()
    if row is not None and row[0] == wanted:
        return
    if row is not None:
        conn.execute(f"DROP {kind.upper()} {name}")
    conn.execute(wanted)


def add_columns(conn: sqlite3.Connection) -> None:
    """Añade a las tablas de la 008 las columnas del esquema 3 que les falten
    (``core.provenance.schema.SCHEMA_3_COLUMNS``), con ``ALTER TABLE … ADD COLUMN``.

    Cada una hace que SQLite vuelva a leer el esquema entero: con los disparadores de la 008 ya
    creados cuesta unos 0,9 ms; crear un proyecto las añade antes de crearlos
    (``core.project.schema.create_schema``), con el mismo SQL de la tabla."""
    for table, columns in provenance_schema.SCHEMA_3_COLUMNS.items():
        present = _columns(conn, table)
        for column, definition in columns.items():
            if column not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def apply_schema_3(conn: sqlite3.Connection) -> None:
    """Lleva la base del esquema 2 al 3 en la transacción de ``conn`` (de una conexión de
    escritura de Geoblender; sin confirmar ni deshacer: lo hace quien la llama). Crea lo que
    falte, añade las columnas que falten y rehace lo que el esquema 3 sustituye si no lo está
    ya; no escribe ninguna fila salvo la declaración de las tablas nuevas. Volver a llamarla no
    cambia nada."""
    for table, ddl in TABLES.items():
        conn.execute(ddl)
        if not _declared(conn, table):
            register_internal_table(conn, table)
    for ddl in INDEXES.values():
        conn.execute(ddl)
    for ddl in TRIGGERS.values():
        conn.execute(ddl)
    add_columns(conn)
    for name, sql in PROVENANCE_INDEXES.items():
        _replace(conn, "index", name, sql)
    for name, sql in PROVENANCE_TRIGGERS.items():
        _replace(conn, "trigger", name, sql)


def missing_objects(conn: sqlite3.Connection) -> list[str]:
    """Lo que le falta a la base del esquema 3 sobre el 2 (``"table gb_version"``, ``"column
    gb_dataset.version_uid"``, ``"index gb_dataset_name_active"``…), en orden: tablas, índices
    y disparadores nuevos, columnas añadidas y lo del esquema 3 en las tablas de la 008 (que
    falta o sigue como en el 2); lista vacía si está completo."""
    names = (*TABLES, *INDEXES, *TRIGGERS, *PROVENANCE_INDEXES, *PROVENANCE_TRIGGERS)
    marks = ", ".join("?" for _ in names)
    present: dict[tuple[str, str], str | None] = {
        (str(kind), str(name)): sql
        for kind, name, sql in conn.execute(
            f"SELECT type, name, sql FROM sqlite_master WHERE name IN ({marks})", names
        )
    }
    missing = [f"table {table}" for table in TABLES if ("table", table) not in present]
    missing += [f"index {name}" for name in INDEXES if ("index", name) not in present]
    missing += [f"trigger {name}" for name in TRIGGERS if ("trigger", name) not in present]
    for table, columns in provenance_schema.SCHEMA_3_COLUMNS.items():
        found = _columns(conn, table)
        missing += [f"column {table}.{column}" for column in columns if column not in found]
    missing += [
        f"index {name}" for name, sql in PROVENANCE_INDEXES.items()
        if present.get(("index", name)) != stored_sql(sql)
    ]
    missing += [
        f"trigger {name}" for name, sql in PROVENANCE_TRIGGERS.items()
        if present.get(("trigger", name)) != stored_sql(sql)
    ]
    return missing
