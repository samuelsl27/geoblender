# SPDX-License-Identifier: GPL-3.0-or-later
"""Tablas internas de la procedencia en el GeoPackage del proyecto (spec 008; RF-008-01,
RF-008-02, RF-008-07; ADR-0025; plan 008 §5.2.1).

Primera parte (T07): parámetros tipados y su historial (RF-008-01 a 06), entradas y sus
ficheros (RF-008-07 a 16) y lo que el usuario decidió ignorar (RF-008-62). La segunda (T08)
añade datos, operaciones, cifras y la caché de obsolescencia, y ``core.project.schema`` las
crea con el esquema 2.

El SQL de las tablas y del índice es el del plan §5.2.1, con «IF NOT EXISTS» para que la
migración 1 → 2 sea idempotente: SQLite guarda el SQL sin esa cláusula, así que crear de cero
y migrar dan el mismo ``sqlite_master``. Como las de la 002, las tablas son internas:
declaradas en ``gpkg_extensions`` (``imga_geoblender``, ``write-only``) y fuera de
``gpkg_contents``. QGIS las ve, y las protegen disparadores ``BEFORE`` que abortan con
``<tabla>: <motivo>``:

- solo escribe una conexión de Geoblender (``WHEN gb_writer() IS NOT 1``; en una ajena la
  función no existe y la sentencia ni se prepara);
- nada se borra (plan §5.2.1, «Reglas de escritura»: solo se borran filas de la caché
  ``gb_stale``), tampoco con ``REPLACE``: en SQLite, ``INSERT OR REPLACE`` y ``UPDATE OR
  REPLACE`` borran la fila que choca sin disparar los ``BEFORE DELETE`` (salvo con
  ``PRAGMA recursive_triggers``), así que ``<tabla>_no_replace`` rechaza insertar una fila
  cuya identidad (``fid`` o una clave única, :data:`UNIQUE_KEYS`) ya existe;
- ``gb_parameter_history`` es de solo inserción, también para Geoblender (RF-008-02);
- de las demás solo cambian las columnas de :data:`MUTABLE_COLUMNS`: ``<tabla>_fixed``
  rechaza cambiar una de :data:`FIXED_COLUMNS` (escribir el mismo valor sí pasa). Cambian el
  valor y la procedencia de un parámetro; el estado, el original, el nombre y la entrega de
  una entrada (D-11); la comprobación de un fichero de una entrada y la fecha de su original,
  cuya ruta, huella y tamaño se escriben una sola vez (:data:`WRITE_ONCE_COLUMNS`,
  RF-008-53); el motivo de lo ignorado;
- un nombre lógico tiene como mucho una entrada activa (ni sustituida ni descartada): el
  índice único parcial del plan y, para que ``REPLACE`` no lo salte al insertar ni al
  renombrar, ``gb_input_name_ins`` y ``gb_input_name_upd``.

``gb_writer()`` no es seguridad: evita que otro programa altere por error lo que solo
gestiona Geoblender. Los ``CHECK`` del plan rechazan un parámetro con un tipo fuera de los
cuatro (``HIPÓTESIS`` con tilde, como ``core.params.ParamKind``), uno CALCULADO sin operación
y uno «sin confirmar» que no es ADOPTADO ni HIPÓTESIS (RF-008-01), y una fila del historial
sin motivo salvo al confirmar (RF-008-02). Las claves foráneas a ``gb_operation`` (T08)
necesitan esa tabla: con ``foreign_keys = ON``, sin ella no se puede escribir en las tablas
que la nombran.
"""

from __future__ import annotations

import sqlite3

from ..gpkg.base import EXTENSION_NAME, register_internal_table

TABLES: dict[str, str] = {
    "gb_parameter": """CREATE TABLE IF NOT EXISTS gb_parameter (
  fid             INTEGER  PRIMARY KEY AUTOINCREMENT,
  uid             TEXT     NOT NULL UNIQUE,
  key             TEXT     NOT NULL,                 -- 'res.swell_factor', 'gis.resample.min_valid_fraction'
  scope           TEXT     NOT NULL DEFAULT 'project' CHECK (scope IN ('project','version','sector')),
  scope_uid       TEXT     NOT NULL DEFAULT '',      -- '' en el proyecto (versión: 009; sector: R-32)
  module          TEXT     NOT NULL,                 -- código del módulo dueño de la definición
  value_type      TEXT     NOT NULL CHECK (value_type IN ('float','int','bool','text','json')),  -- formato §3.3
  value          TEXT,                              -- JSON canónico; NULL = «sin valor»
  unit            TEXT     NOT NULL,                 -- código de core.units ('m', 't/m3', '%', '-')
  kind            TEXT     NOT NULL CHECK (kind IN ('MEDIDO','CALCULADO','ADOPTADO','HIPÓTESIS')),
  source          TEXT     NOT NULL,                 -- documento, norma, persona, operación o algoritmo
  source_kind     TEXT     NOT NULL CHECK (source_kind IN ('document','standard','person','operation','algorithm')),
  decided_by      TEXT     NOT NULL,
  decided_at      DATETIME NOT NULL,
  reason          TEXT     NOT NULL,
  operation_uid   TEXT     REFERENCES gb_operation(uid),  -- CALCULADO: la operación de la cifra que una persona adoptó (S-1)
  unconfirmed     BOOLEAN  NOT NULL DEFAULT 0,       -- «sin confirmar» (RF-008-04)
  review          TEXT,                              -- JSON del cambio de definición (RF-008-60); NULL si nada
  def_sha256      TEXT     NOT NULL,                 -- huella de la definición registrada o confirmada
  value_sha256    TEXT     NOT NULL,                 -- sha256 de {value, unit}: lo que compara la cascada
  rev             INTEGER  NOT NULL CHECK (rev >= 1),-- = rev de su última fila del historial
  created_at      DATETIME NOT NULL,
  modified_at     DATETIME NOT NULL,
  UNIQUE (key, scope, scope_uid),
  CHECK (kind <> 'CALCULADO' OR operation_uid IS NOT NULL),
  CHECK (NOT unconfirmed OR kind IN ('ADOPTADO','HIPÓTESIS'))
)""",
    "gb_parameter_history": """CREATE TABLE IF NOT EXISTS gb_parameter_history (  -- solo inserción
  fid             INTEGER  PRIMARY KEY AUTOINCREMENT,
  parameter_uid   TEXT     NOT NULL REFERENCES gb_parameter(uid),
  rev             INTEGER  NOT NULL,
  action          TEXT     NOT NULL CHECK (action IN ('default','create','change','confirm')),
  value TEXT, unit TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, source_kind TEXT NOT NULL,
  decided_by TEXT NOT NULL, decided_at DATETIME NOT NULL,
  reason          TEXT,                              -- obligatorio salvo al confirmar (RF-008-02)
  operation_uid   TEXT,                              -- solo al adoptar una cifra CALCULADA
  unconfirmed     BOOLEAN  NOT NULL,
  value_sha256    TEXT     NOT NULL,
  changed_at      DATETIME NOT NULL,
  changed_by      TEXT     NOT NULL,                 -- usuario@equipo: siempre una persona, salvo 'default'
  session_uid     TEXT     NOT NULL,
  UNIQUE (parameter_uid, rev),
  CHECK (action = 'confirm' OR (reason IS NOT NULL AND length(trim(reason)) > 0))
)""",
    "gb_input": """CREATE TABLE IF NOT EXISTS gb_input (
  fid             INTEGER  PRIMARY KEY AUTOINCREMENT,
  uid             TEXT     NOT NULL UNIQUE,
  name            TEXT     NOT NULL,                 -- nombre lógico (spec §11)
  kind            TEXT     NOT NULL CHECK (kind IN ('raster','vector','table','drillholes','mesh','point_cloud','document','other')),
  module          TEXT     NOT NULL,                 -- módulo del importador
  reader          TEXT     NOT NULL,                 -- 'gis.geotiff@1': su lector para siempre (ADR-0024 §6)
  normalizer      TEXT     NOT NULL,                 -- 'gbch/1': ídem
  layer           TEXT,                              -- capa o tabla leída
  crs_h           TEXT     NOT NULL,                 -- JSON: {"epsg":25830} | {"wkt2":…} | {"not_applicable":true}
  crs_v           TEXT     NOT NULL,                 -- JSON: {"epsg":5782} | {"local":nota} | {"ellipsoidal":…} | {"not_applicable":true}
  settings        TEXT     NOT NULL,                 -- JSON canónico de los ajustes de importación
  settings_sha256 TEXT     NOT NULL,
  bytes_sha256    TEXT     NOT NULL,                 -- huella conjunta (de las huellas de sus ficheros)
  data_sha256     TEXT     NOT NULL,                 -- ADR-0024 §1
  content_sha256  TEXT     NOT NULL,
  received_at     DATE,                              -- fecha de entrega (opcional, D-11)
  received_from   TEXT,                              -- quién la entrega (opcional, D-11)
  registered_by   TEXT     NOT NULL,
  registered_at   DATETIME NOT NULL,
  operation_uid   TEXT     NOT NULL REFERENCES gb_operation(uid),  -- su importación
  previous_uid    TEXT     REFERENCES gb_input(uid),               -- la que sustituye
  status          TEXT     NOT NULL DEFAULT 'current'
                  CHECK (status IN ('current','changed','kept','superseded','discarded')),
  status_at DATETIME, status_by TEXT, status_reason TEXT,
  seen_sha256     TEXT,                              -- contenido de la fuente al detectar el cambio o al mantener la copia
  original        TEXT     NOT NULL CHECK (original IN ('stored','too_large','not_applicable')),
  created_at DATETIME NOT NULL, modified_at DATETIME NOT NULL
)""",
    "gb_input_file": """CREATE TABLE IF NOT EXISTS gb_input_file (
  fid             INTEGER  PRIMARY KEY AUTOINCREMENT,
  input_uid       TEXT     NOT NULL REFERENCES gb_input(uid),
  ord             INTEGER  NOT NULL,
  role            TEXT     NOT NULL CHECK (role IN ('main','sidecar')),
  anchor          TEXT     NOT NULL CHECK (anchor IN ('project','project_table','original','external')),
  path            TEXT     NOT NULL,                 -- relativa al proyecto o al original; 'project_table': la tabla de
                                                     -- project.gpkg; 'external': solo el nombre
  ref_uid         TEXT,                              -- anotación en los datos de usuario (RF-002-19)
  size            INTEGER,                           -- NULL en 'project_table'
  mtime_ns        INTEGER,
  last_change     TEXT,                              -- 'project_table': gpkg_contents.last_change al registrar
  sha256          TEXT     NOT NULL,                 -- huella de sus bytes (o de su contenido, en 'project_table')
  checked_size INTEGER, checked_mtime_ns INTEGER, checked_last_change TEXT, checked_at DATETIME,
  original_path   TEXT,                              -- 'originals/<input_uid>/<nombre>' (RF-008-53)
  original_sha256 TEXT, original_size INTEGER, original_mtime_ns INTEGER,
  UNIQUE (input_uid, ord)
)""",
    "gb_ignored": """CREATE TABLE IF NOT EXISTS gb_ignored (  -- capas y ficheros que el usuario decidió ignorar (RF-008-62)
  fid INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK (kind IN ('table','file')), name TEXT NOT NULL,
  reason TEXT, decided_by TEXT NOT NULL, decided_at DATETIME NOT NULL,
  UNIQUE (kind, name)
)""",
}
"""El SQL de cada tabla, en el orden en que se crean."""

INDEXES: dict[str, str] = {
    "gb_input_name_active": (
        "CREATE UNIQUE INDEX IF NOT EXISTS gb_input_name_active ON gb_input(name) "
        "WHERE status NOT IN ('superseded','discarded')"
    ),
}
"""Los índices que no salen de las restricciones de las tablas."""

INTERNAL_TABLES: tuple[str, ...] = tuple(TABLES)

APPEND_ONLY_TABLES: tuple[str, ...] = ("gb_parameter_history",)
"""Tablas de solo inserción: ninguna fila cambia ni se borra."""

FIXED_COLUMNS: dict[str, tuple[str, ...]] = {
    "gb_parameter": ("fid", "uid", "key", "scope", "scope_uid", "module", "created_at"),
    "gb_input": (
        "fid",
        "uid",
        "kind",
        "module",
        "reader",
        "normalizer",
        "layer",
        "crs_h",
        "crs_v",
        "settings",
        "settings_sha256",
        "bytes_sha256",
        "data_sha256",
        "content_sha256",
        "registered_by",
        "registered_at",
        "operation_uid",
        "previous_uid",
        "created_at",
    ),
    "gb_input_file": (
        "fid",
        "input_uid",
        "ord",
        "role",
        "anchor",
        "path",
        "ref_uid",
        "size",
        "mtime_ns",
        "last_change",
        "sha256",
    ),
    "gb_ignored": ("fid", "kind", "name"),
}
"""Las columnas que no cambian nunca en las tablas que no son de solo inserción."""

MUTABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "gb_parameter": (
        "value_type",
        "value",
        "unit",
        "kind",
        "source",
        "source_kind",
        "decided_by",
        "decided_at",
        "reason",
        "operation_uid",
        "unconfirmed",
        "review",
        "def_sha256",
        "value_sha256",
        "rev",
        "modified_at",
    ),
    "gb_input": (
        "name",
        "received_at",
        "received_from",
        "status",
        "status_at",
        "status_by",
        "status_reason",
        "seen_sha256",
        "original",
        "modified_at",
    ),
    "gb_input_file": (
        "checked_size",
        "checked_mtime_ns",
        "checked_last_change",
        "checked_at",
        "original_mtime_ns",
    ),
    "gb_ignored": ("reason", "decided_by", "decided_at"),
}
"""Las columnas que sí cambian (lo demás de cada tabla es fijo o de una sola escritura)."""

WRITE_ONCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "gb_input_file": ("original_path", "original_sha256", "original_size"),
}
"""Columnas que pasan una vez de NULL a un valor y ya no cambian (RF-008-53: el original se
guarda tras registrar la entrada, por trozos; después, su ruta, su huella y su tamaño quedan)."""

UNIQUE_KEYS: dict[str, tuple[tuple[str, ...], ...]] = {
    "gb_parameter": (("fid",), ("uid",), ("key", "scope", "scope_uid")),
    "gb_parameter_history": (("fid",), ("parameter_uid", "rev")),
    "gb_input": (("fid",), ("uid",)),
    "gb_input_file": (("fid",), ("input_uid", "ord")),
    "gb_ignored": (("fid",), ("kind", "name")),
}
"""La identidad de una fila de cada tabla: una fila nueva con una que ya existe se rechaza
(``REPLACE`` borraría la anterior). El nombre activo de una entrada lo vigilan aparte
``gb_input_name_ins`` y ``gb_input_name_upd``."""

INACTIVE_INPUT_STATUSES: tuple[str, ...] = ("superseded", "discarded")
"""Los estados de una entrada que no ocupan su nombre lógico (índice ``gb_input_name_active``)."""

MSG_WRITER_ONLY = "solo Geoblender escribe en esta tabla interna (gb_writer)"
MSG_APPEND_ONLY = "registro de solo inserción: no se modifica ni se borra"
MSG_NO_DELETE = "no se borra ninguna fila: es la procedencia del proyecto"
MSG_NO_REPLACE = "esa fila ya existe: no se sustituye ni se borra"
MSG_ACTIVE_NAME = "ya hay otra entrada activa (ni sustituida ni descartada) con ese nombre"
MSG_WRITE_ONCE = "la ruta, la huella y el tamaño del original se escriben una vez y no cambian"
MSG_FIXED: dict[str, str] = {
    "gb_parameter": "la identidad de un parámetro (uid, clave, ámbito, módulo y alta) no cambia",
    "gb_input": "de una entrada solo cambian su estado, su original, su nombre y su entrega",
    "gb_input_file": "de un fichero de una entrada solo cambian su comprobación y su original",
    "gb_ignored": "lo ignorado no cambia de tipo ni de nombre",
}
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
        once = WRITE_ONCE_COLUMNS.get(table, ())
        if once:
            rewritten = " OR ".join(
                f"(OLD.{column} IS NOT NULL AND NEW.{column} IS NOT OLD.{column})"
                for column in once
            )
            add(table, "once", f"BEFORE UPDATE OF {', '.join(once)}", rewritten,
                MSG_WRITE_ONCE)
    inactive = ", ".join(f"'{status}'" for status in INACTIVE_INPUT_STATUSES)
    active_new = f"NEW.status NOT IN ({inactive})"
    other_active = f"name = NEW.name AND status NOT IN ({inactive})"
    add("gb_input", "name_ins", "BEFORE INSERT",
        f"{active_new} AND EXISTS (SELECT 1 FROM gb_input WHERE {other_active})",
        MSG_ACTIVE_NAME)
    add("gb_input", "name_upd", "BEFORE UPDATE OF name, status",
        f"{active_new} AND EXISTS (SELECT 1 FROM gb_input WHERE {other_active} "
        "AND fid <> OLD.fid)",
        MSG_ACTIVE_NAME)
    return triggers


TRIGGERS: dict[str, str] = _triggers()
"""El SQL de cada disparador, por nombre (``<tabla>_<regla>``)."""


def _declared(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM gpkg_extensions WHERE table_name = ? AND column_name IS NULL "
        "AND extension_name = ?",
        (table, EXTENSION_NAME),
    ).fetchone()
    return row is not None


def create_tables(conn: sqlite3.Connection) -> None:
    """Crea las tablas, los índices y los disparadores que falten y declara en
    ``gpkg_extensions`` las tablas que no lo estén, en la transacción de ``conn`` (tras
    ``core.gpkg.base.create_base``). Volver a llamarla no cambia nada."""
    for table, ddl in TABLES.items():
        conn.execute(ddl)
        if not _declared(conn, table):
            register_internal_table(conn, table)
    for ddl in INDEXES.values():
        conn.execute(ddl)
    for ddl in TRIGGERS.values():
        conn.execute(ddl)


def missing_objects(conn: sqlite3.Connection) -> list[str]:
    """Lo que le falta a la base de estas tablas (``"table gb_input"``, ``"index
    gb_input_name_active"``, ``"trigger gb_input_fixed"``…), en orden: tablas, índices y
    disparadores; lista vacía si está completo."""
    present = set(
        conn.execute(
            "SELECT type || ' ' || name FROM sqlite_master "
            "WHERE type IN ('table', 'index', 'trigger')"
        ).fetchall()
    )
    expected = (
        [f"table {table}" for table in TABLES]
        + [f"index {index}" for index in INDEXES]
        + [f"trigger {name}" for name in TRIGGERS]
    )
    return [item for item in expected if (item,) not in present]
