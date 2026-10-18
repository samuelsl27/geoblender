# SPDX-License-Identifier: GPL-3.0-or-later
"""Tablas internas de la procedencia en el GeoPackage del proyecto (spec 008; RF-008-01,
RF-008-02, RF-008-07, RF-008-17, RF-008-30; ADR-0025; plan 008 §5.2.1).

Son las tablas que el esquema 2 añade al 1 (``core.project.schema.create_schema`` las crea
con él): parámetros tipados y su historial (RF-008-01 a 06), entradas y sus ficheros
(RF-008-07 a 16), datos del proyecto y cada contenido nuevo suyo (RF-008-17, 21, 52, 56,
57), operaciones con lo que consumen y producen y los parámetros que usaron (RF-008-05,
18 a 20, 23 a 27, 51), cifras (RF-008-30, 31), la caché de la obsolescencia deducida
(RF-008-24, 28) y lo que el usuario decidió ignorar (RF-008-62).

El SQL de las tablas y de los índices es el del plan §5.2.1, con «IF NOT EXISTS» para que la
migración 1 → 2 sea idempotente: SQLite guarda el SQL sin esa cláusula, así que crear de cero
y migrar dan el mismo ``sqlite_master``. Como las de la 002, las tablas son internas:
declaradas en ``gpkg_extensions`` (``imga_geoblender``, ``write-only``) y fuera de
``gpkg_contents``. QGIS las ve, y las protegen disparadores ``BEFORE`` que abortan con
``<tabla>: <motivo>``:

- solo escribe una conexión de Geoblender (``WHEN gb_writer() IS NOT 1``; en una ajena la
  función no existe y la sentencia ni se prepara);
- nada se borra (plan §5.2.1, «Reglas de escritura») salvo las filas de la caché
  ``gb_stale`` (:data:`CACHE_TABLES`, y solo Geoblender), tampoco con ``REPLACE``: en SQLite,
  ``INSERT OR REPLACE`` y ``UPDATE OR REPLACE`` borran la fila que choca sin disparar los
  ``BEFORE DELETE`` (salvo con ``PRAGMA recursive_triggers``), así que ``<tabla>_no_replace``
  rechaza insertar una fila cuya identidad (``fid`` o una clave única, :data:`UNIQUE_KEYS`)
  ya existe;
- el historial de parámetros, los cambios de los datos, lo que consume y produce cada
  operación, los parámetros que usó y las cifras son de solo inserción, también para
  Geoblender (:data:`APPEND_ONLY_TABLES`; RF-008-02, RF-008-05, RF-008-17, RF-008-30);
- de las demás solo cambian las columnas de :data:`MUTABLE_COLUMNS`: ``<tabla>_fixed``
  rechaza cambiar una de :data:`FIXED_COLUMNS` (escribir el mismo valor sí pasa). Cambian el
  valor y la procedencia de un parámetro; el estado, el original, el nombre y la entrega de
  una entrada (D-11); la comprobación de un fichero de una entrada y la fecha de su original,
  cuya ruta, huella y tamaño se escriben una sola vez (:data:`WRITE_ONCE_COLUMNS`,
  RF-008-53); de un dato, su contenido, su estado, su seguimiento y su comprobación, nunca su
  identidad ni su ubicación, y lo importado tampoco cambia de contenido ni de la operación
  que lo escribió (``gb_dataset_immutable``, RF-008-52); de una operación, lo que se completa
  al terminar y, ya terminada, solo la que la sustituye, una vez (``gb_operation_finished``
  y ``gb_operation_once``); el motivo de lo ignorado;
- un nombre lógico tiene como mucho una entrada activa (ni sustituida ni descartada), y un
  nombre de dato, un dato vivo (vigente, que falta, bloqueado o dañado): los índices únicos
  parciales del plan y, para que ``REPLACE`` no los salte, ``gb_input_name_ins``,
  ``gb_input_name_upd``, ``gb_dataset_name_ins`` y ``gb_dataset_name_upd``; una ubicación de
  dato (almacén, tabla o ruta y selector) no se reutiliza nunca (``gb_dataset_location`` y
  ``gb_dataset_location_ins``; D21).

**El esquema 3** (spec 009, plan 009 §5.2.2) añade a ``gb_dataset`` y ``gb_operation`` las
columnas de :data:`SCHEMA_3_COLUMNS` (la versión y el título de un dato, la revisión de una
operación) con ``ALTER TABLE … ADD COLUMN``, cambia el índice de nombres vivos por versión y
rehace los disparadores que las nombran (:data:`SCHEMA_3_INDEXES`, :data:`SCHEMA_3_TRIGGERS`):
lo aplica ``core.versions.schema.apply_schema_3``. :data:`TABLES`, :data:`INDEXES` y
:data:`TRIGGERS` siguen siendo los del esquema 2, que crea :func:`create_tables` (para la
migración 1 → 2 y como primer paso de crear un proyecto) y que no cambia nunca; las reglas de
columnas (:data:`FIXED_COLUMNS`, :data:`MUTABLE_COLUMNS`) son las del esquema de esta versión.

``gb_writer()`` no es seguridad: evita que otro programa altere por error lo que solo
gestiona Geoblender. Los ``CHECK`` del plan rechazan un parámetro con un tipo fuera de los
cuatro (``HIPÓTESIS`` con tilde, como ``core.params.ParamKind``), uno CALCULADO sin operación
y uno «sin confirmar» que no es ADOPTADO ni HIPÓTESIS (RF-008-01); una fila del historial
sin motivo salvo al confirmar (RF-008-02); un dato inmutable sin entrada o sin seguimiento
fuera de ``exports`` y ``duckdb``; una operación en curso con fecha de fin o terminada sin
ella; y una cifra infinita (NaN no llega: SQLite lo guarda como NULL y ``value`` es ``NOT
NULL``), con un tipo fuera de los cuatro o sin unidad u operación (RF-008-30; el texto del
rechazo para el usuario lo da ``record_figure``). Con ``foreign_keys = ON``, toda tabla que
nombra otra necesita que esa exista para escribir en ella.
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
    "gb_dataset": """CREATE TABLE IF NOT EXISTS gb_dataset (
  fid             INTEGER  PRIMARY KEY AUTOINCREMENT,
  uid             TEXT     NOT NULL UNIQUE,
  name            TEXT     NOT NULL,                 -- estable: 'gis_dtm_proyecto', 'dh_collar'
  module          TEXT     NOT NULL,
  kind            TEXT     NOT NULL CHECK (kind IN ('vector','raster','mesh','table','drillholes','point_cloud',
                                                    'block_model','block_field','report','document')),
  store           TEXT     NOT NULL CHECK (store IN ('gpkg','rasters','meshes','duckdb','originals','exports')),
  locator         TEXT     NOT NULL,                 -- tabla del GPKG o ruta relativa
  selector        TEXT     NOT NULL DEFAULT '',      -- JSON canónico: {"column":"input_uid","equals":uid} (lo importado
                                                     -- de una entrada) | {"column":"input_uid","of":"current_inputs"} (acumulado)
  reader          TEXT     NOT NULL,                 -- su lector y su normalizador para siempre (ADR-0024 §6)
  normalizer      TEXT     NOT NULL,
  content_sha256  TEXT     NOT NULL,
  crs_epsg        INTEGER,
  operation_uid   TEXT     NOT NULL REFERENCES gb_operation(uid),  -- escribió su contenido actual
  input_uid       TEXT     REFERENCES gb_input(uid),              -- si es lo importado de una entrada
  immutable       BOOLEAN  NOT NULL DEFAULT 0,       -- lo importado (RF-008-52)
  qgis_editable   BOOLEAN  NOT NULL DEFAULT 0,       -- su módulo lo declara editable a mano (RF-008-56)
  tracked         BOOLEAN  NOT NULL DEFAULT 1,       -- 0 en 'exports' y, hasta R-22, en 'duckdb'
  status          TEXT     NOT NULL DEFAULT 'current'
                  CHECK (status IN ('current','superseded','discarded','missing','blocked','damaged')),
  superseded_by   TEXT     REFERENCES gb_dataset(uid),
  tracked_size INTEGER, tracked_mtime_ns INTEGER,             -- ficheros (ADR-0025 §6)
  tracked_last_change TEXT, tracked_schema_sha256 TEXT,       -- tablas del GPKG (gpkg_contents.last_change y SQL)
  checked_at      DATETIME,
  description     TEXT,
  created_at DATETIME NOT NULL, modified_at DATETIME NOT NULL,
  CHECK (NOT immutable OR input_uid IS NOT NULL),
  CHECK (tracked OR store IN ('exports','duckdb'))
)""",
    "gb_dataset_change": """CREATE TABLE IF NOT EXISTS gb_dataset_change (  -- solo inserción: cada contenido nuevo de un dato
  fid             INTEGER  PRIMARY KEY AUTOINCREMENT,
  dataset_uid     TEXT     NOT NULL REFERENCES gb_dataset(uid),
  from_sha256     TEXT,                              -- NULL en el primero
  to_sha256       TEXT     NOT NULL,
  operation_uid   TEXT     NOT NULL REFERENCES gb_operation(uid),
  detail          TEXT,                              -- JSON del módulo: elementos afectados (RF-005-22)
  at              DATETIME NOT NULL
)""",
    "gb_operation": """CREATE TABLE IF NOT EXISTS gb_operation (
  fid             INTEGER  PRIMARY KEY AUTOINCREMENT,
  uid             TEXT     NOT NULL UNIQUE,
  op_type         TEXT     NOT NULL,                 -- '<código>.<acción>'
  op_version      TEXT     NOT NULL,                 -- 'M.m' del algoritmo
  module          TEXT     NOT NULL,
  scope           TEXT     NOT NULL DEFAULT 'project' CHECK (scope IN ('project','version')),
  repeatable      BOOLEAN  NOT NULL,                 -- se puede repetir sola (RF-008-27)
  group_name      TEXT,                              -- grupo de operaciones acopladas (RF-008-25)
  group_uid       TEXT,                              -- una ejecución de ese grupo
  settings        TEXT     NOT NULL,                 -- ajustes de la orden (JSON canónico)
  settings_sha256 TEXT     NOT NULL,
  status          TEXT     NOT NULL CHECK (status IN ('running','done','cancelled','failed','interrupted','not_ingested')),
  status_reason   TEXT,
  supersedes_uid  TEXT     REFERENCES gb_operation(uid),  -- recálculo, reimportación o «dar por buena» de…
  superseded_by   TEXT     REFERENCES gb_operation(uid),
  geoblender_version TEXT  NOT NULL,
  software        TEXT     NOT NULL DEFAULT '{}',    -- bibliotecas que influyen en sus cifras
  executor        TEXT     NOT NULL CHECK (executor IN ('blender','job_thread','job_process','external')),
  job_uid         TEXT,
  interpreter     TEXT,                              -- JSON de InterpreterInfo de la 004
  user_host TEXT NOT NULL, host TEXT NOT NULL, session_uid TEXT NOT NULL,
  started_at      DATETIME NOT NULL,
  finished_at     DATETIME,
  message         TEXT,
  CHECK ((status = 'running') = (finished_at IS NULL))
)""",
    "gb_operation_io": """CREATE TABLE IF NOT EXISTS gb_operation_io (  -- solo inserción
  fid INTEGER PRIMARY KEY AUTOINCREMENT,
  operation_uid   TEXT     NOT NULL REFERENCES gb_operation(uid),
  direction       TEXT     NOT NULL CHECK (direction IN ('in','out')),
  item_kind       TEXT     NOT NULL CHECK (item_kind IN ('dataset','input')),
  item_uid        TEXT     NOT NULL,
  content_sha256  TEXT     NOT NULL,                 -- versión consumida o producida (normalizador del elemento)
  role            TEXT     NOT NULL,                 -- 'terrain', 'boundary', 'imported'…
  UNIQUE (operation_uid, direction, item_kind, item_uid, role)
)""",
    "gb_operation_param": """CREATE TABLE IF NOT EXISTS gb_operation_param (  -- solo inserción: lo que usó (RF-008-05); nunca escribe (S-1)
  fid INTEGER PRIMARY KEY AUTOINCREMENT,
  operation_uid   TEXT     NOT NULL REFERENCES gb_operation(uid),
  parameter_uid   TEXT     NOT NULL REFERENCES gb_parameter(uid),
  key TEXT NOT NULL, scope TEXT NOT NULL, rev INTEGER NOT NULL,
  value TEXT, unit TEXT NOT NULL, kind TEXT NOT NULL, unconfirmed BOOLEAN NOT NULL,
  value_sha256    TEXT     NOT NULL,
  UNIQUE (operation_uid, parameter_uid)
)""",
    "gb_figure": """CREATE TABLE IF NOT EXISTS gb_figure (  -- solo inserción
  fid INTEGER PRIMARY KEY AUTOINCREMENT,
  uid             TEXT     NOT NULL UNIQUE,
  key             TEXT     NOT NULL,                 -- 'res.sellable_t'
  label           TEXT     NOT NULL,                 -- texto en español
  value           DOUBLE   NOT NULL CHECK (abs(value) <= 1.7976931348623157e308),  -- NaN se guarda NULL; infinito no pasa
  unit            TEXT     NOT NULL,                 -- código de core.units ('-' adimensional)
  kind            TEXT     NOT NULL CHECK (kind IN ('MEDIDO','CALCULADO','ADOPTADO','HIPÓTESIS')),
  operation_uid   TEXT     NOT NULL REFERENCES gb_operation(uid),
  parameter_uid   TEXT     REFERENCES gb_parameter(uid),   -- si la cifra muestra un parámetro o lo calcula
  parameter_rev   INTEGER,
  scope           TEXT     NOT NULL DEFAULT '{}',    -- JSON canónico: {"phase":"1","bench":125}
  scope_key       TEXT     NOT NULL DEFAULT '',      -- sha256 abreviado de scope, para buscar
  created_at      DATETIME NOT NULL
)""",
    "gb_stale": """CREATE TABLE IF NOT EXISTS gb_stale (
  item_kind       TEXT     NOT NULL CHECK (item_kind IN ('operation','dataset')),
  item_uid        TEXT     NOT NULL,
  cause_kind      TEXT     NOT NULL CHECK (cause_kind IN ('dataset_changed','parameter_changed','input_updated',
                                    'input_discarded','dataset_missing','dataset_blocked','dataset_damaged',
                                    'algorithm','group')),
  subject_uid     TEXT     NOT NULL,                 -- lo que cambió: dato, parámetro, entrada o tipo de operación
  since           DATETIME NOT NULL,
  PRIMARY KEY (item_kind, item_uid, cause_kind, subject_uid)
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
    "gb_dataset_name_active": (  # un nombre, un dato vivo (I-9)
        "CREATE UNIQUE INDEX IF NOT EXISTS gb_dataset_name_active ON gb_dataset(name) "
        "WHERE status IN ('current','missing','blocked','damaged')"
    ),
    "gb_dataset_location": (  # una ubicación no se reutiliza
        "CREATE UNIQUE INDEX IF NOT EXISTS gb_dataset_location "
        "ON gb_dataset(store, locator, selector)"
    ),
    "gb_operation_io_item": (
        "CREATE INDEX IF NOT EXISTS gb_operation_io_item "
        "ON gb_operation_io(item_kind, item_uid, direction)"
    ),
    "gb_operation_io_version": (
        "CREATE INDEX IF NOT EXISTS gb_operation_io_version "
        "ON gb_operation_io(item_uid, content_sha256, direction)"
    ),
    "gb_operation_param_parameter": (
        "CREATE INDEX IF NOT EXISTS gb_operation_param_parameter "
        "ON gb_operation_param(parameter_uid)"
    ),
    "gb_figure_key": (
        "CREATE INDEX IF NOT EXISTS gb_figure_key ON gb_figure(key, scope_key, created_at)"
    ),
}
"""Los índices que no salen de las restricciones de las tablas."""

INTERNAL_TABLES: tuple[str, ...] = tuple(TABLES)

APPEND_ONLY_TABLES: tuple[str, ...] = (
    "gb_parameter_history",
    "gb_dataset_change",
    "gb_operation_io",
    "gb_operation_param",
    "gb_figure",
)
"""Tablas de solo inserción: ninguna fila cambia ni se borra."""

CACHE_TABLES: tuple[str, ...] = ("gb_stale",)
"""Tablas de caché: Geoblender borra y sustituye sus filas (la obsolescencia deducida se
reescribe por diferencias, ADR-0025 §5); las demás reglas (solo Geoblender escribe, columnas
fijas) se aplican igual."""

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
    "gb_dataset": (
        "fid",
        "uid",
        "name",
        "module",
        "kind",
        "store",
        "locator",
        "selector",
        "reader",
        "normalizer",
        "input_uid",
        "immutable",
        "created_at",
        "version_uid",
    ),
    "gb_operation": (
        "fid",
        "uid",
        "op_type",
        "op_version",
        "module",
        "scope",
        "repeatable",
        "group_name",
        "group_uid",
        "settings",
        "settings_sha256",
        "supersedes_uid",
        "geoblender_version",
        "user_host",
        "host",
        "session_uid",
        "started_at",
        "revision_uid",
    ),
    "gb_stale": ("item_kind", "item_uid", "cause_kind", "subject_uid"),
    "gb_ignored": ("fid", "kind", "name"),
}
"""Las columnas que no cambian nunca en las tablas que no son de solo inserción. De un dato,
además de lo que dice el plan, su entrada y si es inmutable: si no, bastaría con quitarle la
marca para cambiar lo importado (RF-008-52); desde el esquema 3, su versión. De una operación,
lo que se fija al empezarla (RF-008-51); desde el esquema 3, su revisión (plan 009 §5.2.2)."""

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
    "gb_dataset": (
        "content_sha256",
        "crs_epsg",
        "operation_uid",
        "qgis_editable",
        "tracked",
        "status",
        "superseded_by",
        "tracked_size",
        "tracked_mtime_ns",
        "tracked_last_change",
        "tracked_schema_sha256",
        "checked_at",
        "description",
        "modified_at",
        "title",
    ),
    "gb_operation": (
        "status",
        "status_reason",
        "software",
        "executor",
        "job_uid",
        "interpreter",
        "finished_at",
        "message",
    ),
    "gb_stale": ("since",),
    "gb_ignored": ("reason", "decided_by", "decided_at"),
}
"""Las columnas que sí cambian (lo demás de cada tabla es fijo o de una sola escritura). Las
de una operación, solo mientras está «en curso» (``gb_operation_finished``): son las que se
completan al terminarla (RF-008-18, RF-008-19). Desde el esquema 3, el título de un dato
(RF-009-22: el renombrado desde el Outliner)."""

SCHEMA_3_COLUMNS: dict[str, dict[str, str]] = {
    "gb_dataset": {"version_uid": "TEXT NOT NULL DEFAULT ''", "title": "TEXT"},
    "gb_operation": {"revision_uid": "TEXT NOT NULL DEFAULT ''"},
}
"""Las columnas que el esquema 3 añade a estas tablas, con su definición (plan 009 §5.2.2): la
versión de un dato (fija; ``''``, del proyecto) y su título (cambiable, RF-009-22), y la
revisión abierta en que se registró una operación de versión (fija; ``''``, de proyecto,
RF-009-05). No están en :data:`TABLES` ni en los disparadores de :data:`TRIGGERS` (el esquema
2): las añade ``core.versions.schema.apply_schema_3`` con ``ALTER TABLE … ADD COLUMN``, que no
copia ni mueve filas, y SQLite las pone tras la última columna y antes de las restricciones."""

WRITE_ONCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "gb_input_file": ("original_path", "original_sha256", "original_size"),
    "gb_operation": ("superseded_by",),
}
"""Columnas que pasan una vez de NULL a un valor y ya no cambian (RF-008-53: el original se
guarda tras registrar la entrada, por trozos; después, su ruta, su huella y su tamaño quedan;
plan §5.2.1: la operación que sustituye a otra se anota en ella una vez, también terminada)."""

IMMUTABLE_CONTENT_COLUMNS: tuple[str, ...] = ("content_sha256", "operation_uid")
"""Lo que no cambia en un dato ``immutable`` (lo importado, RF-008-52): su contenido y la
operación que lo escribió (``gb_dataset_immutable``)."""

UNIQUE_KEYS: dict[str, tuple[tuple[str, ...], ...]] = {
    "gb_parameter": (("fid",), ("uid",), ("key", "scope", "scope_uid")),
    "gb_parameter_history": (("fid",), ("parameter_uid", "rev")),
    "gb_input": (("fid",), ("uid",)),
    "gb_input_file": (("fid",), ("input_uid", "ord")),
    "gb_dataset": (("fid",), ("uid",)),
    "gb_dataset_change": (("fid",),),
    "gb_operation": (("fid",), ("uid",)),
    "gb_operation_io": (
        ("fid",),
        ("operation_uid", "direction", "item_kind", "item_uid", "role"),
    ),
    "gb_operation_param": (("fid",), ("operation_uid", "parameter_uid")),
    "gb_figure": (("fid",), ("uid",)),
    "gb_stale": (("item_kind", "item_uid", "cause_kind", "subject_uid"),),
    "gb_ignored": (("fid",), ("kind", "name")),
}
"""La identidad de una fila de cada tabla: una fila nueva con una que ya existe se rechaza
(``REPLACE`` borraría la anterior), salvo en la caché (:data:`CACHE_TABLES`), de la que
Geoblender sí sustituye filas. Aparte: el nombre activo de una entrada
(``gb_input_name_ins`` y ``gb_input_name_upd``), el nombre vivo de un dato
(``gb_dataset_name_ins`` y ``gb_dataset_name_upd``) y su ubicación
(``gb_dataset_location_ins``; las columnas de la ubicación son fijas)."""

INACTIVE_INPUT_STATUSES: tuple[str, ...] = ("superseded", "discarded")
"""Los estados de una entrada que no ocupan su nombre lógico (índice ``gb_input_name_active``)."""

LIVE_DATASET_STATUSES: tuple[str, ...] = ("current", "missing", "blocked", "damaged")
"""Los estados de un dato que ocupan su nombre (índice ``gb_dataset_name_active``): todos
menos sustituido y descartado."""

LOCATION_COLUMNS: tuple[str, ...] = ("store", "locator", "selector")
"""La ubicación de un dato (índice ``gb_dataset_location``): no la reutiliza ningún otro,
tampoco cuando el que la ocupa está sustituido o descartado (D21)."""

RUNNING = "running"
"""El estado de una operación «en curso», la única que aún cambia (RF-008-51)."""

MSG_WRITER_ONLY = "solo Geoblender escribe en esta tabla interna (gb_writer)"
MSG_APPEND_ONLY = "registro de solo inserción: no se modifica ni se borra"
MSG_NO_DELETE = "no se borra ninguna fila: es la procedencia del proyecto"
MSG_NO_REPLACE = "esa fila ya existe: no se sustituye ni se borra"
MSG_ACTIVE_NAME = "ya hay otra entrada activa (ni sustituida ni descartada) con ese nombre"
MSG_LIVE_DATASET = "ya hay otro dato vivo (ni sustituido ni descartado) con ese nombre"
MSG_LOCATION = (
    "esa ubicación (almacén, tabla o ruta y selector) ya es de otro dato: no se reutiliza"
)
MSG_IMMUTABLE = (
    "es lo importado de una entrada: su contenido y la operación que lo escribió no cambian"
)
MSG_FINISHED = (
    "una operación terminada no cambia: solo se anota, una vez, la que la sustituye "
    "(superseded_by)"
)
MSG_WRITE_ONCE: dict[str, str] = {
    "gb_input_file": "la ruta, la huella y el tamaño del original se escriben una vez y no cambian",
    "gb_operation": "la operación que sustituye a esta se anota una vez y no cambia",
}
MSG_FIXED: dict[str, str] = {
    "gb_parameter": "la identidad de un parámetro (uid, clave, ámbito, módulo y alta) no cambia",
    "gb_input": "de una entrada solo cambian su estado, su original, su nombre y su entrega",
    "gb_input_file": "de un fichero de una entrada solo cambian su comprobación y su original",
    "gb_dataset": (
        "la identidad de un dato (uid, nombre, módulo, tipo, ubicación, lector, normalizador, "
        "entrada, si es inmutable y alta) no cambia"
    ),
    "gb_operation": (
        "lo que se fijó al empezar una operación (tipo, versión, módulo, ámbito, grupo, "
        "ajustes, a cuál sustituye, quién, dónde y cuándo) no cambia"
    ),
    "gb_stale": "una causa de obsolescencia no cambia de elemento ni de causa: se borra",
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


def _rules(rules: dict[str, tuple[str, ...]], table: str, schema: int) -> tuple[str, ...]:
    """Las columnas de ``rules[table]`` que existen en el esquema ``schema`` (en el 2, sin
    las de :data:`SCHEMA_3_COLUMNS`)."""
    columns = rules[table]
    if schema >= 3:
        return columns
    added = SCHEMA_3_COLUMNS.get(table, {})
    return tuple(column for column in columns if column not in added)


def _triggers(schema: int) -> dict[str, str]:
    """Los disparadores de estas tablas en el esquema ``schema`` (2 o 3)."""
    writer = "gb_writer() IS NOT 1"
    triggers: dict[str, str] = {}

    def add(table: str, suffix: str, timing: str, when: str | None, message: str) -> None:
        name = f"{table}_{suffix}"
        triggers[name] = _trigger(name, timing, table, when, message)

    for table in TABLES:
        append_only = table in APPEND_ONLY_TABLES
        cache = table in CACHE_TABLES
        add(table, "w_ins", "BEFORE INSERT", writer, MSG_WRITER_ONLY)
        if not cache:
            exists = " OR ".join(_row_exists(table, key) for key in UNIQUE_KEYS[table])
            add(table, "no_replace", "BEFORE INSERT", exists,
                MSG_APPEND_ONLY if append_only else MSG_NO_REPLACE)
        if append_only:
            add(table, "no_upd", "BEFORE UPDATE", None, MSG_APPEND_ONLY)
            add(table, "no_del", "BEFORE DELETE", None, MSG_APPEND_ONLY)
            continue
        add(table, "w_upd", "BEFORE UPDATE", writer, MSG_WRITER_ONLY)
        if cache:
            add(table, "w_del", "BEFORE DELETE", writer, MSG_WRITER_ONLY)
        else:
            add(table, "no_del", "BEFORE DELETE", None, MSG_NO_DELETE)
        fixed = _rules(FIXED_COLUMNS, table, schema)
        add(table, "fixed", f"BEFORE UPDATE OF {', '.join(fixed)}", _any_changed(fixed),
            MSG_FIXED[table])
        once = WRITE_ONCE_COLUMNS.get(table, ())
        if once:
            rewritten = " OR ".join(
                f"(OLD.{column} IS NOT NULL AND NEW.{column} IS NOT OLD.{column})"
                for column in once
            )
            add(table, "once", f"BEFORE UPDATE OF {', '.join(once)}", rewritten,
                MSG_WRITE_ONCE[table])
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
    live = ", ".join(f"'{status}'" for status in LIVE_DATASET_STATUSES)
    live_new = f"NEW.status IN ({live})"
    # Desde el esquema 3, un nombre vivo por versión (y uno en el proyecto, version_uid = '').
    same_version = " AND version_uid = NEW.version_uid" if schema >= 3 else ""
    other_live = f"name = NEW.name{same_version} AND status IN ({live})"
    add("gb_dataset", "name_ins", "BEFORE INSERT",
        f"{live_new} AND EXISTS (SELECT 1 FROM gb_dataset WHERE {other_live})",
        MSG_LIVE_DATASET)
    add("gb_dataset", "name_upd", "BEFORE UPDATE OF status",  # el nombre y la versión son fijos
        f"{live_new} AND EXISTS (SELECT 1 FROM gb_dataset WHERE {other_live} "
        "AND fid <> OLD.fid)",
        MSG_LIVE_DATASET)
    add("gb_dataset", "location_ins", "BEFORE INSERT",
        _row_exists("gb_dataset", LOCATION_COLUMNS), MSG_LOCATION)
    add("gb_dataset", "immutable",
        f"BEFORE UPDATE OF {', '.join(IMMUTABLE_CONTENT_COLUMNS)}",
        f"OLD.immutable AND ({_any_changed(IMMUTABLE_CONTENT_COLUMNS)})",
        MSG_IMMUTABLE)
    completed = _rules(MUTABLE_COLUMNS, "gb_operation", schema)
    add("gb_operation", "finished", f"BEFORE UPDATE OF {', '.join(completed)}",
        f"OLD.status IS NOT '{RUNNING}' AND ({_any_changed(completed)})",
        MSG_FINISHED)
    return triggers


TRIGGERS: dict[str, str] = _triggers(2)
"""El SQL de cada disparador del esquema 2, por nombre (``<tabla>_<regla>``): los que crea
:func:`create_tables`."""

SCHEMA_3_TRIGGERS: dict[str, str] = {
    name: sql for name, sql in _triggers(3).items() if sql != TRIGGERS[name]
}
"""Los disparadores de :data:`TRIGGERS` que el esquema 3 rehace porque nombran sus columnas
nuevas (plan 009 §5.2.2): las columnas fijas de un dato (con su versión) y de una operación
(con su revisión), y el nombre vivo de un dato, por versión (``gb_dataset_fixed``,
``gb_operation_fixed``, ``gb_dataset_name_ins`` y ``gb_dataset_name_upd``)."""

SCHEMA_3_INDEXES: dict[str, str] = {
    "gb_dataset_name_active": (  # un nombre, un dato vivo en cada versión y en el proyecto
        "CREATE UNIQUE INDEX gb_dataset_name_active ON gb_dataset(version_uid, name) "
        "WHERE status IN ('current','missing','blocked','damaged')"
    ),
    "gb_dataset_version": (  # los datos de una versión, sin recorrer la tabla
        "CREATE INDEX gb_dataset_version ON gb_dataset(version_uid) WHERE version_uid <> ''"
    ),
    "gb_operation_revision": (  # las operaciones (y las cifras) de una revisión
        "CREATE INDEX gb_operation_revision ON gb_operation(revision_uid) "
        "WHERE revision_uid <> ''"
    ),
}
"""Los índices del esquema 3 en estas tablas, como los guarda ``sqlite_master`` (plan 009
§5.2.2): el de nombres vivos sustituye al de :data:`INDEXES`; los otros dos son parciales, así
que una consulta los usa si repite su condición (``AND version_uid <> ''``)."""


def _declared(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM gpkg_extensions WHERE table_name = ? AND column_name IS NULL "
        "AND extension_name = ?",
        (table, EXTENSION_NAME),
    ).fetchone()
    return row is not None


def create_tables(conn: sqlite3.Connection, *, tables_only: bool = False) -> None:
    """Crea las tablas, los índices y los disparadores que falten (con ``tables_only``, solo
    las tablas) y declara en ``gpkg_extensions`` las tablas que no lo estén, en la transacción
    de ``conn`` (tras ``core.gpkg.base.create_base``). Volver a llamarla no cambia nada."""
    for table, ddl in TABLES.items():
        conn.execute(ddl)
        if not _declared(conn, table):
            register_internal_table(conn, table)
    if tables_only:
        return
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
