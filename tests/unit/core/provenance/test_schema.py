# SPDX-License-Identifier: GPL-3.0-or-later
"""Tablas internas de la procedencia, primera parte (spec 008, T07; RF-008-01, RF-008-02,
RF-008-07; ADR-0025; plan 008 §5.2.1).

``core.provenance.schema`` crea en el GeoPackage del proyecto ``gb_parameter``,
``gb_parameter_history``, ``gb_input``, ``gb_input_file`` y ``gb_ignored``, con sus índices
y sus disparadores:

- solo una conexión de Geoblender (la función SQL ``gb_writer()``) escribe en ellas; en una
  conexión ajena (QGIS, GDAL) la función no existe y la sentencia ni se prepara;
- nada se borra (plan §5.2.1, «Reglas de escritura»), tampoco con ``INSERT OR REPLACE`` o
  ``UPDATE OR REPLACE``: en SQLite el ``REPLACE`` borra la fila que choca sin disparar los
  ``BEFORE DELETE`` (salvo con ``recursive_triggers``), así que un disparador ``BEFORE
  INSERT`` rechaza una fila cuya identidad ya existe;
- el historial de parámetros es de solo inserción (RF-008-02), y de las demás tablas solo
  cambian las columnas que deja el plan: el valor y su procedencia en un parámetro; el
  estado, el original, el nombre y la entrega de una entrada (D-11); la comprobación de sus
  ficheros, con la ruta, la huella y el tamaño de su original escritos una sola vez.

``gb_operation`` llega con T08: mientras no esté en el esquema, :func:`_insert_operation`
crea una tabla mínima, porque con ``foreign_keys = ON`` una tabla madre que no existe impide
escribir en la hija («no such table: main.gb_operation»).

Cada prueba trabaja sobre una copia de una plantilla que se crea una vez; los rechazos van
en una sola transacción (``RAISE(ABORT)`` y las restricciones deshacen solo su sentencia).
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.support.package import import_geoblender

gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
project_schema = import_geoblender("core.project.schema")
schema = import_geoblender("core.provenance.schema")
hashing = import_geoblender("core.hashing")
params = import_geoblender("core.params")
content = import_geoblender("core.content")
georef = import_geoblender("core.georef")

CRS = georef.load_catalog().horizontal(25830)
TABLES = ("gb_parameter", "gb_parameter_history", "gb_input", "gb_input_file", "gb_ignored")
NOW = "2026-10-08T09:31:00.000Z"
LATER = "2026-10-09T10:00:00.000Z"
USER = "prueba@PC-PRUEBA-A"
SESSION_UID = "00000000-0000-4000-8000-000000000001"
OP_UID = "00000000-0000-4000-8000-0000000000c1"
PARAM_UID = "00000000-0000-4000-8000-0000000000d1"
INPUT_UID = "00000000-0000-4000-8000-0000000000e1"
REF_UID = "00000000-0000-4000-8000-0000000000f1"
UNKNOWN_UID = "00000000-0000-4000-8000-0000000000ff"

Case = tuple[str, str, Sequence[Any], str]


def _json(value: object) -> str:
    return hashing.canonical_json(value).decode("utf-8")


def _sha(label: str) -> str:
    return hashing.sha256_bytes(label.encode("utf-8"))


def _uid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012x}"


def _abort(table: str, message: str) -> str:
    """El texto con el que aborta un disparador de ``table``."""
    return f"{table}: {message}"


def _row(defaults: dict[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - set(defaults)
    if unknown:
        raise KeyError(f"columnas que no existen en la prueba: {sorted(unknown)}")
    return {**defaults, **changes}


def parameter_row(**changes: Any) -> dict[str, Any]:
    """``res.swell_factor`` = 1,23 ADOPTADO por la propiedad (rev 2; antes, HIPÓTESIS por
    defecto «sin confirmar»)."""
    return _row(
        {
            "uid": PARAM_UID,
            "key": "res.swell_factor",
            "scope": "project",
            "scope_uid": "",
            "module": "res",
            "value_type": "float",
            "value": _json(1.23),
            "unit": "-",
            "kind": "ADOPTADO",
            "source": "Ensayo de esponjamiento de la propiedad (24/09/2026)",
            "source_kind": "document",
            "decided_by": "La propiedad",
            "decided_at": "2026-09-24T09:31:00.000Z",
            "reason": "Ensayo de la propiedad",
            "operation_uid": None,
            "unconfirmed": 0,
            "review": None,
            "def_sha256": _sha("definición de res.swell_factor"),
            "value_sha256": hashing.sha256_bytes(
                hashing.canonical_json({"unit": "-", "value": 1.23})
            ),
            "rev": 2,
            "created_at": NOW,
            "modified_at": NOW,
        },
        changes,
    )


def history_row(**changes: Any) -> dict[str, Any]:
    """La fila 2 del historial de ``res.swell_factor``: pasa a 1,23 ADOPTADO."""
    return _row(
        {
            "parameter_uid": PARAM_UID,
            "rev": 2,
            "action": "change",
            "value": _json(1.23),
            "unit": "-",
            "kind": "ADOPTADO",
            "source": "Ensayo de esponjamiento de la propiedad (24/09/2026)",
            "source_kind": "document",
            "decided_by": "La propiedad",
            "decided_at": "2026-09-24T09:31:00.000Z",
            "reason": "Ensayo de la propiedad",
            "operation_uid": None,
            "unconfirmed": 0,
            "value_sha256": _sha("1.23 -"),
            "changed_at": NOW,
            "changed_by": USER,
            "session_uid": SESSION_UID,
        },
        changes,
    )


DEFAULT_HISTORY = {
    "rev": 1,
    "action": "default",
    "value": _json(1.15),
    "kind": "HIPÓTESIS",
    "source": "valor por defecto de Geoblender 0.3.0",
    "source_kind": "algorithm",
    "decided_by": "Geoblender (valor por defecto)",
    "decided_at": "2026-09-20T08:00:00.000Z",
    "reason": "Valor por defecto",
    "unconfirmed": 1,
    "value_sha256": _sha("1.15 -"),
    "changed_at": "2026-09-20T08:00:00.000Z",
    "changed_by": "Geoblender (valor por defecto)",
}


def input_row(**changes: Any) -> dict[str, Any]:
    """La entrada «Limites_v1»: una capa de un GeoPackage externo, vigente."""
    return _row(
        {
            "uid": INPUT_UID,
            "name": "Limites_v1",
            "kind": "vector",
            "module": "core",
            "reader": "core.gpkg_layer@1",
            "normalizer": content.NORMALIZER,
            "layer": "limites",
            "crs_h": _json({"epsg": 25830}),
            "crs_v": _json({"epsg": 5782}),
            "settings": _json({"layer": "limites"}),
            "settings_sha256": _sha("ajustes"),
            "bytes_sha256": _sha("bytes"),
            "data_sha256": _sha("datos"),
            "content_sha256": _sha("contenido"),
            "received_at": "2026-09-24",
            "received_from": "La propiedad",
            "registered_by": USER,
            "registered_at": NOW,
            "operation_uid": OP_UID,
            "previous_uid": None,
            "status": "current",
            "status_at": None,
            "status_by": None,
            "status_reason": None,
            "seen_sha256": None,
            "original": "not_applicable",
            "created_at": NOW,
            "modified_at": NOW,
        },
        changes,
    )


def file_row(**changes: Any) -> dict[str, Any]:
    """El fichero de «Limites_v1», en otro volumen (anotado en los datos de usuario)."""
    return _row(
        {
            "input_uid": INPUT_UID,
            "ord": 0,
            "role": "main",
            "anchor": "external",
            "path": "Limites_v1.gpkg",
            "ref_uid": REF_UID,
            "size": 49_152,
            "mtime_ns": 1_790_000_000_000_000_000,
            "last_change": None,
            "sha256": _sha("Limites_v1.gpkg"),
            "checked_size": None,
            "checked_mtime_ns": None,
            "checked_last_change": None,
            "checked_at": None,
            "original_path": None,
            "original_sha256": None,
            "original_size": None,
            "original_mtime_ns": None,
        },
        changes,
    )


def ignored_row(**changes: Any) -> dict[str, Any]:
    """Una capa del proyecto que el usuario decidió ignorar (RF-008-62)."""
    return _row(
        {
            "kind": "table",
            "name": "capa_de_trabajo",
            "reason": "Capa de apoyo de QGIS",
            "decided_by": USER,
            "decided_at": NOW,
        },
        changes,
    )


# Una fila nueva y válida de cada tabla, que no choca con la plantilla.
NEW_ROWS: dict[str, Callable[[], dict[str, Any]]] = {
    "gb_parameter": lambda: parameter_row(uid=_uid(0xD2), key="res.density"),
    "gb_parameter_history": lambda: history_row(rev=3, action="confirm", reason=None),
    "gb_input": lambda: input_row(uid=_uid(0xE2), name="Collares"),
    "gb_input_file": lambda: file_row(ord=1, role="sidecar", path="Limites_v1.qmd"),
    "gb_ignored": lambda: ignored_row(name="otra_capa"),
}


def _insert_sql(table: str, row: Mapping[str, Any], verb: str = "INSERT") -> tuple[str, tuple]:
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    return f"{verb} INTO {table} ({names}) VALUES ({marks})", tuple(row.values())


def _insert(conn: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> None:
    conn.execute(*_insert_sql(table, row))


def _insert_operation(conn: sqlite3.Connection, uid: str) -> None:
    """Una operación para las claves foráneas. ``gb_operation`` llega con T08: hasta
    entonces, una tabla mínima (cuando esté en ``schema.TABLES``, esta función tendrá que
    dar sus columnas)."""
    if "gb_operation" not in schema.TABLES:
        conn.execute("CREATE TABLE IF NOT EXISTS gb_operation (uid TEXT NOT NULL UNIQUE)")
    conn.execute("INSERT INTO gb_operation (uid) VALUES (?)", (uid,))


def _changed(column: str) -> str:
    """Una expresión SQL que da otro valor para ``column`` (también si es nula)."""
    return (
        f"CASE WHEN typeof({column}) = 'integer' THEN {column} + 1 "
        f"ELSE coalesce({column}, '') || 'x' END"
    )


def _build(path: Path) -> None:
    """La plantilla: esquema 1, las tablas de T07 y una fila en cada una (el parámetro con
    sus dos filas de historial)."""
    with gpkg.GpkgConnection.open_write(path, create=True) as db:
        with db.transaction() as conn:
            base.create_base(conn, CRS)
            project_schema.create_schema(conn)
            schema.create_tables(conn)
            _insert_operation(conn, OP_UID)
            _insert(conn, "gb_parameter", parameter_row())
            _insert(conn, "gb_parameter_history", history_row(**DEFAULT_HISTORY))
            _insert(conn, "gb_parameter_history", history_row())
            _insert(conn, "gb_input", input_row())
            _insert(conn, "gb_input_file", file_row())
            _insert(conn, "gb_ignored", ignored_row())


_TEMPLATE: list[Path] = []


def setUpModule() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="gb-008-t07-", ignore_cleanup_errors=True)
    unittest.addModuleCleanup(tmp.cleanup)
    path = Path(tmp.name) / "plantilla.gpkg"
    _build(path)
    _TEMPLATE.append(path)


def _template() -> Path:
    return _TEMPLATE[0]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


class _DbCase(unittest.TestCase):
    """Una copia de la plantilla abierta para escribir como Geoblender."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-t07-", ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "project.gpkg"
        shutil.copyfile(_template(), self.path)
        self.db = gpkg.GpkgConnection.open_write(self.path)
        self.addCleanup(self.db.close)

    def dump(self) -> list[str]:
        return list(self.db.connection.iterdump())

    def row(self, table: str, where: str, args: Sequence[Any] = ()) -> dict[str, Any]:
        cursor = self.db.connection.execute(f"SELECT * FROM {table} WHERE {where}", args)
        names = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 1, f"{table} WHERE {where}")
        return dict(zip(names, rows[0], strict=True))

    def scalar(self, sql: str, args: Sequence[Any] = ()) -> Any:
        return self.db.connection.execute(sql, args).fetchone()[0]

    def accept(self, *statements: tuple[str, Sequence[Any]]) -> None:
        """Ejecuta las sentencias en una transacción que se confirma."""
        with self.db.transaction() as conn:
            for sql, args in statements:
                conn.execute(sql, args)

    def assertRejected(self, cases: Iterable[Case]) -> None:
        """Cada caso (etiqueta, SQL, argumentos, texto esperado dentro del error) falla con
        ``IntegrityError``, en una sola transacción, y nada cambia."""
        before = self.dump()
        with self.db.transaction() as conn:
            for label, sql, args, expected in cases:
                with self.subTest(label):
                    with self.assertRaises(sqlite3.IntegrityError) as caught:
                        conn.execute(sql, args)
                    self.assertIn(expected, str(caught.exception))
        self.assertEqual(self.dump(), before)

    def fixed_cases(self, table: str, where: str) -> list[Case]:
        """Cambiar cada columna fija de ``table`` (en la fila de ``where``) se rechaza."""
        message = _abort(table, schema.MSG_FIXED[table])
        return [
            (f"{table}.{column}", f"UPDATE {table} SET {column} = {_changed(column)} "
             f"WHERE {where}", (), message)
            for column in schema.FIXED_COLUMNS[table]
        ]


class StructureTest(unittest.TestCase):
    def test_tables_indexes_and_declaration(self) -> None:
        """RF-008-01, RF-008-07: existen las cinco tablas, el índice único parcial de los
        nombres de las entradas activas y los disparadores; las tablas están declaradas en
        ``gpkg_extensions`` (``imga_geoblender``, ``write-only``) y fuera de
        ``gpkg_contents``; ``missing_objects`` no echa nada en falta y nombra lo que falta."""
        self.assertEqual(schema.INTERNAL_TABLES, TABLES)
        self.assertEqual(tuple(schema.TABLES), TABLES)
        marks = ", ".join("?" for _ in TABLES)
        with gpkg.GpkgConnection.open_read(_template()) as db:
            conn = db.connection
            declared = conn.execute(
                "SELECT table_name, column_name, extension_name, scope FROM gpkg_extensions "
                f"WHERE table_name IN ({marks}) ORDER BY table_name",
                TABLES,
            ).fetchall()
            registered = conn.execute(
                f"SELECT count(*) FROM gpkg_contents WHERE table_name IN ({marks})", TABLES
            ).fetchone()[0]
            index = {row[1]: tuple(row[2:]) for row in conn.execute("PRAGMA index_list(gb_input)")}
            index_columns = [
                row[2] for row in conn.execute("PRAGMA index_info(gb_input_name_active)")
            ]
            index_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'gb_input_name_active'"
            ).fetchone()[0]
            triggers = {
                name
                for (name,) in conn.execute(
                    f"SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN ({marks})",
                    TABLES,
                )
            }
            self.assertEqual(schema.missing_objects(conn), [])
        self.assertEqual(
            declared, [(table, None, "imga_geoblender", "write-only") for table in sorted(TABLES)]
        )
        self.assertEqual(registered, 0)
        self.assertEqual(index["gb_input_name_active"], (1, "c", 1))  # único, creado, parcial
        self.assertEqual(index_columns, ["name"])
        self.assertIn("WHERE status NOT IN ('superseded','discarded')", index_sql)
        self.assertEqual(triggers, set(schema.TRIGGERS))
        with tempfile.TemporaryDirectory(prefix="gb-t07-", ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "falta.gpkg"
            shutil.copyfile(_template(), path)
            raw = sqlite3.connect(path, isolation_level=None)
            try:
                raw.execute("DROP TRIGGER gb_parameter_history_no_upd")
                raw.execute("DROP INDEX gb_input_name_active")
                missing = schema.missing_objects(raw)
            finally:
                raw.close()
        self.assertEqual(
            missing, ["index gb_input_name_active", "trigger gb_parameter_history_no_upd"]
        )

    def test_create_again_changes_nothing(self) -> None:
        """Plan §5.2.4 (la migración de T09): crear otra vez las tablas en una base que ya
        las tiene no cambia nada: el mismo ``sqlite_master`` (que guarda el SQL sin «IF NOT
        EXISTS»), las mismas filas y una sola declaración por tabla."""
        with tempfile.TemporaryDirectory(prefix="gb-t07-", ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "otra_vez.gpkg"
            shutil.copyfile(_template(), path)
            with gpkg.GpkgConnection.open_write(path) as db:
                conn = db.connection
                master = conn.execute(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
                ).fetchall()
                before = list(conn.iterdump())
                with db.transaction() as writing:
                    schema.create_tables(writing)
                self.assertEqual(
                    conn.execute(
                        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
                    ).fetchall(),
                    master,
                )
                self.assertEqual(list(conn.iterdump()), before)
                counts = conn.execute(
                    "SELECT table_name, count(*) FROM gpkg_extensions WHERE table_name LIKE "
                    "'gb_%' GROUP BY table_name"
                ).fetchall()
        self.assertTrue(all(count == 1 for _, count in counts), counts)
        stored = [sql for *_, sql in master if sql is not None]
        self.assertFalse([sql for sql in stored if "IF NOT EXISTS" in sql.upper()])

    def test_every_column_has_a_rule(self) -> None:
        """RF-008-02, RF-008-07; plan §5.2.1, «Reglas de escritura»: cada columna de las
        tablas que se pueden cambiar es fija, cambiable o de una sola escritura, sin repetir
        (una columna nueva obliga a decidir), con lo que dice el plan; el historial es de
        solo inserción entero."""
        with gpkg.GpkgConnection.open_read(_template()) as db:
            columns = {table: _columns(db.connection, table) for table in TABLES}
        self.assertEqual(schema.APPEND_ONLY_TABLES, ("gb_parameter_history",))
        for table in TABLES:
            with self.subTest(table):
                if table in schema.APPEND_ONLY_TABLES:
                    self.assertNotIn(table, schema.FIXED_COLUMNS)
                    self.assertNotIn(table, schema.MUTABLE_COLUMNS)
                    continue
                ruled = (
                    *schema.FIXED_COLUMNS[table],
                    *schema.MUTABLE_COLUMNS[table],
                    *schema.WRITE_ONCE_COLUMNS.get(table, ()),
                )
                self.assertEqual(len(ruled), len(set(ruled)))
                self.assertEqual(set(ruled), set(columns[table]))
        self.assertTrue(
            {"fid", "uid", "key", "scope", "scope_uid", "module"}
            <= set(schema.FIXED_COLUMNS["gb_parameter"])
        )
        self.assertEqual(
            set(schema.MUTABLE_COLUMNS["gb_input"]),
            {
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
            },
        )
        self.assertEqual(
            set(schema.MUTABLE_COLUMNS["gb_input_file"]),
            {
                "checked_size",
                "checked_mtime_ns",
                "checked_last_change",
                "checked_at",
                "original_mtime_ns",
            },
        )
        self.assertEqual(
            schema.WRITE_ONCE_COLUMNS,
            {"gb_input_file": ("original_path", "original_sha256", "original_size")},
        )
        self.assertEqual(set(schema.FIXED_COLUMNS["gb_ignored"]), {"fid", "kind", "name"})


# UPDATE y DELETE de una conexión ajena (las INSERT, con una fila nueva y válida de NEW_ROWS,
# para que solo las pare gb_writer()).
FOREIGN_WRITES: dict[str, tuple[str, str]] = {
    "gb_parameter": ("UPDATE gb_parameter SET reason = 'otro'", "DELETE FROM gb_parameter"),
    "gb_parameter_history": (
        "UPDATE gb_parameter_history SET reason = 'otro'",
        "DELETE FROM gb_parameter_history",
    ),
    "gb_input": ("UPDATE gb_input SET name = 'Otra'", "DELETE FROM gb_input"),
    "gb_input_file": (
        "UPDATE gb_input_file SET checked_at = 'ahora'",
        "DELETE FROM gb_input_file",
    ),
    "gb_ignored": ("UPDATE gb_ignored SET reason = 'otro'", "DELETE FROM gb_ignored"),
}


class ForeignConnectionTest(unittest.TestCase):
    def test_foreign_writes_fail(self) -> None:
        """RF-008-01, RF-008-02, RF-008-07 (RF-002-15): desde una conexión sin
        ``gb_writer()`` (QGIS, GDAL), INSERT (de una fila válida), UPDATE, DELETE e INSERT
        OR REPLACE fallan en las cinco tablas, que se leen, y el volcado SQL no cambia."""
        self.assertEqual(set(FOREIGN_WRITES), set(TABLES))
        with tempfile.TemporaryDirectory(prefix="gb-t07-", ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "project.gpkg"
            shutil.copyfile(_template(), path)
            foreign = sqlite3.connect(path, isolation_level=None)
            try:
                before = list(foreign.iterdump())
                for table, (update, delete) in FOREIGN_WRITES.items():
                    replace = f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"
                    writes = (
                        _insert_sql(table, NEW_ROWS[table]()),
                        (update, ()),
                        (delete, ()),
                        (replace, ()),
                    )
                    for sql, args in writes:
                        with self.subTest(tabla=table, orden=" ".join(sql.split()[:3])):
                            with self.assertRaises(sqlite3.Error):
                                foreign.execute(sql, args)
                    with self.subTest(tabla=table, orden="SELECT"):
                        count = foreign.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                        self.assertGreater(count, 0)
                after = list(foreign.iterdump())
            finally:
                foreign.close()
        self.assertEqual(after, before)


class RequiredColumnsTest(_DbCase):
    def test_required_columns(self) -> None:
        """RF-008-01, RF-008-02, RF-008-07: sin clave, unidad, tipo, origen y su clase,
        decisor, fecha, ámbito o motivo no se guarda un parámetro; sin el estado de antes, quién
        o cuándo, una fila del historial; sin nombre, tipo, lector, normalizador, CRS horizontal
        o vertical declarados, ajustes, huellas, hashes, quién y cuándo la registra o su
        importación, una entrada; sin ruta, papel, ancla o huella, un fichero suyo. Una fila
        completa sí se guarda."""
        cases: list[Case] = []
        for table, make in NEW_ROWS.items():
            required = [
                row[1]
                for row in self.db.connection.execute(f"PRAGMA table_info({table})")
                if row[3] and not row[5]  # NOT NULL y no es la clave primaria
            ]
            self.assertTrue(required, table)
            for column in required:
                sql, args = _insert_sql(table, {**make(), column: None})
                expected = f"NOT NULL constraint failed: {table}.{column}"
                cases.append((f"{table}.{column}", sql, args, expected))
        self.assertGreaterEqual(len(cases), 60)
        self.assertRejected(cases)
        self.accept(*(_insert_sql(table, make()) for table, make in NEW_ROWS.items()))
        for table in TABLES:
            expected_rows = 3 if table == "gb_parameter_history" else 2
            self.assertEqual(self.scalar(f"SELECT count(*) FROM {table}"), expected_rows)


class ParameterTest(_DbCase):
    def test_codes(self) -> None:
        """RF-008-01: los cuatro tipos (``HIPÓTESIS`` con tilde, como ``core.params.
        ParamKind``), los cinco tipos de valor y clases de origen de ``core.params`` y los
        tres ámbitos se guardan; un tipo vacío, sin tilde («HIPOTESIS»), con la tilde
        descompuesta, en minúsculas u otro se rechaza, como un tipo de valor, una clase de
        origen o un ámbito desconocidos y una revisión 0. La misma clave en otro ámbito no
        choca."""
        accepted = [
            parameter_row(
                uid=_uid(0x100 + number),
                key=f"res.kind_{number}",
                kind=str(kind),
                operation_uid=OP_UID if kind == params.ParamKind.CALCULADO else None,
            )
            for number, kind in enumerate(params.ParamKind)
        ]
        accepted += [
            parameter_row(uid=_uid(0x110 + number), key=f"res.type_{number}", value_type=str(kind))
            for number, kind in enumerate(params.ValueType)
        ]
        accepted += [
            parameter_row(uid=_uid(0x120 + number), key=f"res.source_{number}", source_kind=str(kind))
            for number, kind in enumerate(params.SourceKind)
        ]
        accepted += [
            parameter_row(uid=_uid(0x130 + number), scope=scope, scope_uid=scope_uid)
            for number, (scope, scope_uid) in enumerate(
                (("version", _uid(0x777)), ("sector", "S-1"), ("project", "otro"))
            )
        ]
        self.assertEqual(
            {str(kind) for kind in params.ParamKind}, {"MEDIDO", "CALCULADO", "ADOPTADO", "HIPÓTESIS"}
        )
        bad = [
            ("kind", value)
            for value in (
                "",
                "HIPOTESIS",
                "HIPÓTESIS",
                "hipótesis",
                "Hipótesis",
                "ADOPTADA",
                "ADOPTADO ",
                "OTRO",
            )
        ]
        bad += [("value_type", value) for value in ("", "double", "FLOAT", "list")]
        bad += [("source_kind", value) for value in ("", "norma", "Document", "user")]
        bad += [("scope", value) for value in ("", "Project", "phase")]
        bad += [("rev", 0), ("rev", -1)]
        cases: list[Case] = []
        for number, (column, value) in enumerate(bad):
            row = parameter_row(uid=_uid(0x200 + number), key=f"res.bad_{number}", **{column: value})
            sql, args = _insert_sql("gb_parameter", row)
            cases.append((f"{column}={value!r}", sql, args, "CHECK constraint failed"))
        self.assertRejected(cases)
        self.accept(*(_insert_sql("gb_parameter", row) for row in accepted))
        self.assertEqual(self.scalar("SELECT count(*) FROM gb_parameter"), 1 + len(accepted))
        stored = {
            kind for (kind,) in self.db.connection.execute("SELECT DISTINCT kind FROM gb_parameter")
        }
        self.assertEqual(stored, {"MEDIDO", "CALCULADO", "ADOPTADO", "HIPÓTESIS"})

    def test_calculated_names_its_operation(self) -> None:
        """RF-008-01 (S-1): un parámetro CALCULADO sin operación, o con una que no está
        registrada, se rechaza, al crearlo y al cambiarlo; con la operación de la cifra que una
        persona adopta, se guarda."""
        calculated = parameter_row(uid=_uid(0xD3), key="res.balance_k", kind="CALCULADO")
        self.assertRejected(
            [
                ("sin operación", *_insert_sql("gb_parameter", calculated), "CHECK constraint failed"),
                (
                    "operación desconocida",
                    *_insert_sql("gb_parameter", {**calculated, "operation_uid": UNKNOWN_UID}),
                    "FOREIGN KEY constraint failed",
                ),
                (
                    "cambiar a CALCULADO sin operación",
                    "UPDATE gb_parameter SET kind = 'CALCULADO' WHERE uid = ?",
                    (PARAM_UID,),
                    "CHECK constraint failed",
                ),
            ]
        )
        self.accept(
            _insert_sql("gb_parameter", {**calculated, "operation_uid": OP_UID}),
            (
                "UPDATE gb_parameter SET kind = 'CALCULADO', operation_uid = ?, rev = 3 WHERE uid = ?",
                (OP_UID, PARAM_UID),
            ),
        )
        self.assertEqual(
            self.db.connection.execute(
                "SELECT kind, operation_uid FROM gb_parameter ORDER BY fid"
            ).fetchall(),
            [("CALCULADO", OP_UID), ("CALCULADO", OP_UID)],
        )

    def test_unconfirmed_only_for_default_kinds(self) -> None:
        """RF-008-01, RF-008-04: «sin confirmar» solo en un ADOPTADO o una HIPÓTESIS (los
        tipos de un valor por defecto); en un MEDIDO o un CALCULADO se rechaza, también al
        cambiar el tipo de uno sin confirmar."""
        unconfirmed = parameter_row(
            uid=_uid(0xD4), key="res.production", kind="HIPÓTESIS", unconfirmed=1
        )
        self.accept(
            _insert_sql("gb_parameter", unconfirmed),
            _insert_sql(
                "gb_parameter",
                parameter_row(uid=_uid(0xD5), key="res.cutoff", kind="ADOPTADO", unconfirmed=1),
            ),
        )
        self.assertRejected(
            [
                (
                    "MEDIDO",
                    *_insert_sql(
                        "gb_parameter",
                        parameter_row(uid=_uid(0xD6), key="res.a", kind="MEDIDO", unconfirmed=1),
                    ),
                    "CHECK constraint failed",
                ),
                (
                    "CALCULADO",
                    *_insert_sql(
                        "gb_parameter",
                        parameter_row(
                            uid=_uid(0xD7),
                            key="res.b",
                            kind="CALCULADO",
                            operation_uid=OP_UID,
                            unconfirmed=1,
                        ),
                    ),
                    "CHECK constraint failed",
                ),
                (
                    "cambiar a MEDIDO",
                    "UPDATE gb_parameter SET kind = 'MEDIDO' WHERE uid = ?",
                    (_uid(0xD4),),
                    "CHECK constraint failed",
                ),
            ]
        )
        self.accept(
            ("UPDATE gb_parameter SET kind = 'MEDIDO', unconfirmed = 0 WHERE uid = ?", (_uid(0xD4),))
        )

    def test_identity_fixed_and_nothing_deleted(self) -> None:
        """RF-008-01, RF-008-02: la identidad de un parámetro (``fid``, ``uid``, clave, ámbito,
        módulo, alta) no cambia; su valor, su tipo y su procedencia sí. Ninguna fila se borra,
        tampoco sustituyéndola con ``INSERT OR REPLACE`` (por ``fid``, ``uid`` o clave y
        ámbito)."""
        table = "gb_parameter"
        no_replace = _abort(table, schema.MSG_NO_REPLACE)
        twin = parameter_row(uid=_uid(0xD8), value=_json(9.9))
        cases = self.fixed_cases(table, "uid = '" + PARAM_UID + "'")
        cases += [
            ("borrar", "DELETE FROM gb_parameter", (), _abort(table, schema.MSG_NO_DELETE)),
            ("misma clave", *_insert_sql(table, twin), no_replace),
            ("REPLACE por clave", *_insert_sql(table, twin, "INSERT OR REPLACE"), no_replace),
            (
                "REPLACE por uid",
                *_insert_sql(table, parameter_row(key="res.otra"), "INSERT OR REPLACE"),
                no_replace,
            ),
            (
                "REPLACE por fid",
                *_insert_sql(
                    table, {"fid": 1, **parameter_row(uid=_uid(0xD9), key="res.otra")}, "INSERT OR REPLACE"
                ),
                no_replace,
            ),
        ]
        self.assertGreaterEqual(len(schema.FIXED_COLUMNS[table]), 7)
        self.assertRejected(cases)
        self.accept(
            ("UPDATE gb_parameter SET uid = uid, key = key, scope = scope, module = module", ()),
            (
                "UPDATE gb_parameter SET value_type = 'float', value = ?, unit = '-', "
                "kind = 'HIPÓTESIS', source = 'Samuel', source_kind = 'person', "
                "decided_by = ?, decided_at = ?, reason = 'Nuevo ensayo', operation_uid = NULL, "
                "unconfirmed = 0, review = ?, def_sha256 = ?, value_sha256 = ?, rev = 3, "
                "modified_at = ? WHERE uid = ?",
                (
                    _json(1.24),
                    USER,
                    LATER,
                    _json({"unit": ["-", "%"]}),
                    _sha("d2"),
                    _sha("v2"),
                    LATER,
                    PARAM_UID,
                ),
            ),
        )
        row = self.row(table, "uid = ?", (PARAM_UID,))
        self.assertEqual(
            (row["key"], row["value"], row["kind"], row["rev"], row["created_at"]),
            ("res.swell_factor", "1.24", "HIPÓTESIS", 3, NOW),
        )


class HistoryTest(_DbCase):
    def test_history_is_append_only(self) -> None:
        """RF-008-02: ninguna fila del historial cambia (ninguna columna) ni se borra, ni
        siquiera desde Geoblender ni sustituyéndola con ``INSERT OR REPLACE`` (por parámetro y
        revisión o por ``fid``): la HIPÓTESIS que pasó a ADOPTADO sigue constando como
        HIPÓTESIS en su fila 1. Una fila nueva (confirmar, sin motivo) sí se añade."""
        table = "gb_parameter_history"
        append_only = _abort(table, schema.MSG_APPEND_ONLY)
        columns = _columns(self.db.connection, table)
        cases: list[Case] = [
            (
                f"{table}.{column}",
                f"UPDATE {table} SET {column} = {_changed(column)} WHERE rev = 1",
                (),
                append_only,
            )
            for column in columns
        ]
        rewrite = history_row(**{**DEFAULT_HISTORY, "kind": "MEDIDO", "unconfirmed": 0})
        cases += [
            (
                "reescribir como MEDIDO",
                f"UPDATE {table} SET kind = 'MEDIDO', unconfirmed = 0 WHERE rev = 1",
                (),
                append_only,
            ),
            ("borrar una", f"DELETE FROM {table} WHERE rev = 1", (), append_only),
            ("borrar todas", f"DELETE FROM {table}", (), append_only),
            ("misma revisión", *_insert_sql(table, rewrite), append_only),
            ("REPLACE por revisión", *_insert_sql(table, rewrite, "INSERT OR REPLACE"), append_only),
            (
                "REPLACE por fid",
                *_insert_sql(table, {"fid": 1, **history_row(rev=7)}, "INSERT OR REPLACE"),
                append_only,
            ),
        ]
        self.assertEqual(len(columns), 18)
        self.assertRejected(cases)
        self.accept(_insert_sql(table, NEW_ROWS[table]()))
        rows = self.db.connection.execute(
            f"SELECT rev, action, kind, unconfirmed, reason FROM {table} ORDER BY rev"
        ).fetchall()
        self.assertEqual(
            rows,
            [
                (1, "default", "HIPÓTESIS", 1, "Valor por defecto"),
                (2, "change", "ADOPTADO", 0, "Ensayo de la propiedad"),
                (3, "confirm", "ADOPTADO", 0, None),
            ],
        )

    def test_reason_required_except_confirm(self) -> None:
        """RF-008-02: el motivo es obligatorio (no vacío ni en blanco) salvo al confirmar; una
        acción desconocida y un parámetro que no existe se rechazan."""
        table = "gb_parameter_history"
        check = "CHECK constraint failed"
        cases: list[Case] = []
        rev = 10
        for action in ("default", "create", "change"):
            for reason in (None, "", "   "):
                row = history_row(rev=rev, action=action, reason=reason)
                cases.append((f"{action}, {reason!r}", *_insert_sql(table, row), check))
                rev += 1
        for action in ("", "delete", "update", "Confirm"):
            row = history_row(rev=rev, action=action)
            cases.append((f"acción {action!r}", *_insert_sql(table, row), check))
            rev += 1
        cases.append(
            (
                "parámetro desconocido",
                *_insert_sql(table, history_row(rev=rev, parameter_uid=UNKNOWN_UID)),
                "FOREIGN KEY constraint failed",
            )
        )
        self.assertRejected(cases)
        self.accept(
            _insert_sql(table, history_row(rev=3, action="confirm", reason=None)),
            _insert_sql(table, history_row(rev=4, action="change", reason="Nuevo ensayo")),
        )
        self.assertEqual(self.scalar(f"SELECT count(*) FROM {table}"), 4)


class InputTest(_DbCase):
    def test_input_keeps_what_rf_008_07_asks(self) -> None:
        """RF-008-07: una entrada de varios ficheros (un ASC con su ``.prj``, anclados al
        proyecto) se guarda con nombre lógico, tipo, lector y normalizador, CRS horizontal y
        vertical declarados, ajustes, huellas, hashes, entrega, quién y cuándo, y su
        importación, y cada fichero con su papel, su ancla, su ruta, su tamaño, su fecha y su
        huella; se lee igual. Tipos, estados, originales, papeles y anclas desconocidos, y una
        importación, una entrada anterior o una entrada de un fichero que no existen, se
        rechazan."""
        asc = input_row(
            uid=_uid(0xE2),
            name="MDT_2026",
            kind="raster",
            module="gis",
            reader="gis.asc@1",
            layer=None,
            crs_v=_json({"local": "Cotas de la propiedad"}),
            settings=_json({"nodata": -9999.0}),
            received_at=None,
            received_from=None,
        )
        files = [
            file_row(
                input_uid=_uid(0xE2),
                ord=0,
                role="main",
                anchor="project",
                path="entregas/mdt_2026.asc",
                ref_uid=_uid(0xF2),
                size=1_234_567,
                sha256=_sha("mdt_2026.asc"),
            ),
            file_row(
                input_uid=_uid(0xE2),
                ord=1,
                role="sidecar",
                anchor="project",
                path="entregas/mdt_2026.prj",
                ref_uid=_uid(0xF3),
                size=412,
                sha256=_sha("mdt_2026.prj"),
            ),
        ]
        self.accept(
            _insert_sql("gb_input", asc), *(_insert_sql("gb_input_file", row) for row in files)
        )
        stored = self.row("gb_input", "uid = ?", (_uid(0xE2),))
        self.assertEqual({key: stored[key] for key in asc}, asc)
        for row in files:
            where = ("input_uid = ? AND ord = ?", (row["input_uid"], row["ord"]))
            stored_file = self.row("gb_input_file", *where)
            self.assertEqual({key: stored_file[key] for key in row}, row)
        bad_inputs = [
            ("kind", "grid"),
            ("kind", "Raster"),
            ("status", "vigente"),
            ("status", "stale"),
            ("original", "yes"),
            ("original", ""),
        ]
        check = "CHECK constraint failed"
        cases: list[Case] = []
        for number, (column, value) in enumerate(bad_inputs):
            row = input_row(uid=_uid(0x300 + number), name=f"Mal_{number}", **{column: value})
            cases.append((f"{column}={value!r}", *_insert_sql("gb_input", row), check))
        bad_files = (("role", "principal"), ("anchor", "absolute"), ("anchor", ""))
        for number, (column, value) in enumerate(bad_files):
            row = file_row(ord=10 + number, **{column: value})
            cases.append((f"{column}={value!r}", *_insert_sql("gb_input_file", row), check))
        foreign_keys = (
            (
                "importación desconocida",
                "gb_input",
                input_row(uid=_uid(0x310), name="X1", operation_uid=UNKNOWN_UID),
            ),
            (
                "anterior desconocida",
                "gb_input",
                input_row(uid=_uid(0x311), name="X2", previous_uid=UNKNOWN_UID),
            ),
            ("entrada desconocida", "gb_input_file", file_row(input_uid=UNKNOWN_UID)),
        )
        for label, table, row in foreign_keys:
            cases.append((label, *_insert_sql(table, row), "FOREIGN KEY constraint failed"))
        self.assertRejected(cases)

    def test_one_active_input_per_name(self) -> None:
        """RF-008-07, RF-008-11: dos entradas activas (vigente, cambiada o con la copia
        mantenida) con el mismo nombre lógico se rechazan, también con ``INSERT OR REPLACE``,
        al renombrar y al devolver una sustituida a vigente; una sustituida o descartada no
        choca: «Limites_v1» queda tres veces y solo una activa."""
        table = "gb_input"
        active = _abort(table, schema.MSG_ACTIVE_NAME)
        cases: list[Case] = [
            (
                status,
                *_insert_sql(table, input_row(uid=_uid(0x400 + number), status=status)),
                active,
            )
            for number, status in enumerate(("current", "changed", "kept"))
        ]
        cases.append(
            ("REPLACE", *_insert_sql(table, input_row(uid=_uid(0x410)), "INSERT OR REPLACE"), active)
        )
        self.assertRejected(cases)
        self.accept(
            (
                "UPDATE gb_input SET status = 'superseded', status_at = ?, status_by = ?, "
                "status_reason = 'Límite redibujado' WHERE uid = ?",
                (LATER, USER, INPUT_UID),
            ),
            _insert_sql(table, input_row(uid=_uid(0xE2), previous_uid=INPUT_UID)),
            _insert_sql(table, input_row(uid=_uid(0xE3), status="discarded")),
            _insert_sql(table, input_row(uid=_uid(0xE4), name="Collares")),
        )
        self.assertRejected(
            [
                (
                    "volver a vigente",
                    "UPDATE gb_input SET status = 'current' WHERE uid = ?",
                    (INPUT_UID,),
                    active,
                ),
                (
                    "renombrar",
                    "UPDATE gb_input SET name = 'Limites_v1' WHERE uid = ?",
                    (_uid(0xE4),),
                    active,
                ),
                (
                    "renombrar con REPLACE",
                    "UPDATE OR REPLACE gb_input SET name = 'Limites_v1' WHERE uid = ?",
                    (_uid(0xE4),),
                    active,
                ),
            ]
        )
        names = self.db.connection.execute(
            "SELECT uid, status FROM gb_input WHERE name = 'Limites_v1' ORDER BY fid"
        ).fetchall()
        self.assertEqual(
            names,
            [(INPUT_UID, "superseded"), (_uid(0xE2), "current"), (_uid(0xE3), "discarded")],
        )
        self.accept(("UPDATE gb_input SET status = 'discarded' WHERE uid = ?", (_uid(0xE2),)))
        self.accept(("UPDATE gb_input SET name = 'Limites_v1' WHERE uid = ?", (_uid(0xE4),)))

    def test_input_columns_and_nothing_deleted(self) -> None:
        """RF-008-07 (plan §5.2.1): de una entrada solo cambian su estado, su original, su
        nombre y su entrega (D-11); cambiar cualquier otra columna (lo leído, lo declarado,
        sus hashes, quién y cuándo la registró, su importación) se rechaza. Ninguna se borra,
        tampoco sustituyéndola con ``INSERT OR REPLACE`` (por ``uid`` o ``fid``)."""
        table = "gb_input"
        no_replace = _abort(table, schema.MSG_NO_REPLACE)
        cases = self.fixed_cases(table, "uid = '" + INPUT_UID + "'")
        cases += [
            ("borrar", "DELETE FROM gb_input", (), _abort(table, schema.MSG_NO_DELETE)),
            (
                "REPLACE por uid",
                *_insert_sql(table, input_row(name="Otra"), "INSERT OR REPLACE"),
                no_replace,
            ),
            (
                "REPLACE por fid",
                *_insert_sql(
                    table, {"fid": 1, **input_row(uid=_uid(0xE5), name="Otra")}, "INSERT OR REPLACE"
                ),
                no_replace,
            ),
        ]
        self.assertGreaterEqual(len(cases), 20)
        self.assertRejected(cases)
        self.accept(
            ("UPDATE gb_input SET uid = uid, content_sha256 = content_sha256, crs_h = crs_h", ()),
            (
                "UPDATE gb_input SET name = 'Limites_proyecto', received_at = '2026-09-25', "
                "received_from = 'Topografía', status = 'kept', status_at = ?, status_by = ?, "
                "status_reason = 'Se mantiene la copia', seen_sha256 = ?, original = 'too_large', "
                "modified_at = ? WHERE uid = ?",
                (LATER, USER, _sha("visto"), LATER, INPUT_UID),
            ),
        )
        row = self.row(table, "uid = ?", (INPUT_UID,))
        self.assertEqual(
            (row["name"], row["status"], row["received_from"], row["content_sha256"]),
            ("Limites_proyecto", "kept", "Topografía", _sha("contenido")),
        )

    def test_file_check_and_original(self) -> None:
        """RF-008-07, RF-008-09, RF-008-53: de un fichero de una entrada cambia su
        comprobación (tamaño, fecha, ``last_change`` y cuándo) y la fecha de su original; la
        ruta, la huella y el tamaño del original se escriben una vez (y se pueden volver a
        escribir iguales); lo registrado (ruta, ancla, papel, tamaño, fecha, huella) no
        cambia. Ningún fichero se borra ni se sustituye."""
        table = "gb_input_file"
        no_replace = _abort(table, schema.MSG_NO_REPLACE)
        cases = self.fixed_cases(table, "ord = 0")
        cases += [
            ("borrar", f"DELETE FROM {table}", (), _abort(table, schema.MSG_NO_DELETE)),
            ("mismo orden", *_insert_sql(table, file_row(path="otro.gpkg")), no_replace),
            (
                "REPLACE por orden",
                *_insert_sql(table, file_row(path="otro.gpkg"), "INSERT OR REPLACE"),
                no_replace,
            ),
            (
                "REPLACE por fid",
                *_insert_sql(table, {"fid": 1, **file_row(ord=5)}, "INSERT OR REPLACE"),
                no_replace,
            ),
        ]
        self.assertRejected(cases)
        original = (f"originals/{INPUT_UID}/Limites_v1.gpkg", _sha("original"), 49_152)
        check = (
            f"UPDATE {table} SET checked_size = ?, checked_mtime_ns = ?, checked_last_change = ?, "
            "checked_at = ? WHERE ord = 0"
        )
        self.accept(
            (check, (49_152, 1_790_000_000_000_000_001, None, NOW)),
            (check, (50_000, 1_790_000_000_000_000_002, None, LATER)),
            (
                f"UPDATE {table} SET original_path = ?, original_sha256 = ?, original_size = ?, "
                "original_mtime_ns = 1 WHERE ord = 0",
                original,
            ),
            (
                f"UPDATE {table} SET original_path = ?, original_sha256 = ?, original_size = ?, "
                "original_mtime_ns = 2 WHERE ord = 0",
                original,
            ),
        )
        once = _abort(table, schema.MSG_WRITE_ONCE)
        self.assertRejected(
            [
                (column, f"UPDATE {table} SET {column} = {_changed(column)} WHERE ord = 0", (), once)
                for column in schema.WRITE_ONCE_COLUMNS[table]
            ]
            + [("quitar el original", f"UPDATE {table} SET original_path = NULL WHERE ord = 0", (), once)]
        )
        row = self.row(table, "ord = 0")
        self.assertEqual(
            (
                row["checked_size"],
                row["checked_at"],
                row["original_path"],
                row["original_size"],
                row["original_mtime_ns"],
                row["size"],
            ),
            (50_000, LATER, original[0], 49_152, 2, 49_152),
        )


class IgnoredTest(_DbCase):
    def test_ignored(self) -> None:
        """RF-008-62 (plan §5.2.1): lo ignorado es una tabla o un fichero, una vez por tipo y
        nombre; no cambia de tipo ni de nombre, su motivo y quién lo decidió sí, y no se borra
        ni se sustituye."""
        table = "gb_ignored"
        no_replace = _abort(table, schema.MSG_NO_REPLACE)
        cases = self.fixed_cases(table, "name = 'capa_de_trabajo'")
        cases += [
            (
                "tipo desconocido",
                *_insert_sql(table, ignored_row(kind="folder", name="x")),
                "CHECK constraint failed",
            ),
            ("repetido", *_insert_sql(table, ignored_row()), no_replace),
            ("REPLACE", *_insert_sql(table, ignored_row(reason="otro"), "INSERT OR REPLACE"), no_replace),
            ("borrar", f"DELETE FROM {table}", (), _abort(table, schema.MSG_NO_DELETE)),
        ]
        self.assertRejected(cases)
        self.accept(
            _insert_sql(table, ignored_row(kind="file", name="capa_de_trabajo")),
            (
                f"UPDATE {table} SET reason = 'Sigue sin hacer falta', decided_by = ?, "
                "decided_at = ? WHERE kind = 'table'",
                (USER, LATER),
            ),
        )
        rows = self.db.connection.execute(
            f"SELECT kind, name, reason FROM {table} ORDER BY fid"
        ).fetchall()
        self.assertEqual(
            rows,
            [
                ("table", "capa_de_trabajo", "Sigue sin hacer falta"),
                ("file", "capa_de_trabajo", "Capa de apoyo de QGIS"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
