# SPDX-License-Identifier: GPL-3.0-or-later
"""Tablas internas de la procedencia y esquema 2 del proyecto (spec 008, T07 y T08;
RF-008-01, RF-008-02, RF-008-07, RF-008-17, RF-008-30; ADR-0025; plan 008 §5.2.1).

``core.provenance.schema`` crea en el GeoPackage del proyecto las doce tablas de la
procedencia —parámetros y su historial, entradas y sus ficheros, datos y sus cambios,
operaciones con lo que consumen y producen y los parámetros que usan, cifras, la caché de
obsolescencia y lo ignorado—, con sus índices y sus disparadores:

- solo una conexión de Geoblender (la función SQL ``gb_writer()``) escribe en ellas; en una
  conexión ajena (QGIS, GDAL) la función no existe y la sentencia ni se prepara;
- nada se borra (plan §5.2.1, «Reglas de escritura») salvo las filas de la caché
  ``gb_stale``, tampoco con ``INSERT OR REPLACE`` o ``UPDATE OR REPLACE``: en SQLite el
  ``REPLACE`` borra la fila que choca sin disparar los ``BEFORE DELETE`` (salvo con
  ``recursive_triggers``), así que un disparador ``BEFORE INSERT`` rechaza una fila cuya
  identidad ya existe;
- el historial de parámetros, los cambios de los datos, lo que consume y produce cada
  operación, los parámetros que usó y las cifras son de solo inserción; de las demás tablas
  solo cambian las columnas que deja el plan: el valor y su procedencia en un parámetro; el
  estado, el original, el nombre y la entrega de una entrada (D-11); la comprobación de sus
  ficheros, con la ruta, la huella y el tamaño de su original escritos una sola vez; de un
  dato, ni su identidad ni su ubicación, y lo importado tampoco cambia de contenido; una
  operación terminada solo anota, una vez, la que la sustituye.

``core.project.schema`` crea con ellas el esquema 2 (``min_reader_schema`` 1) y comprueba
lo que le falta a una base según su esquema; abrir un proyecto echa en falta lo de su
esquema y no lo de uno posterior que aún no tiene.

Cada prueba trabaja sobre una copia de una plantilla que se crea una vez; los rechazos van
en una sola transacción (``RAISE(ABORT)`` y las restricciones deshacen solo su sentencia).
"""

from __future__ import annotations

import math
import shutil
import sqlite3
import sys
import tempfile
import unittest
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.support.core_fixtures import (
    FakeClock,
    FakePids,
    make_session,
    make_settings,
    mark_schema,
    project_tmp,
)
from tests.support.package import import_geoblender

gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
project_schema = import_geoblender("core.project.schema")
create = import_geoblender("core.project.create")
manifest_mod = import_geoblender("core.project.manifest")
open_mod = import_geoblender("core.project.open")
model = import_geoblender("core.project.model")
errors = import_geoblender("core.errors")
userdata_mod = import_geoblender("core.userdata")
schema = import_geoblender("core.provenance.schema")
versions_schema = import_geoblender("core.versions.schema")
hashing = import_geoblender("core.hashing")
params = import_geoblender("core.params")
content = import_geoblender("core.content")
georef = import_geoblender("core.georef")

CRS = georef.load_catalog().horizontal(25830)
TABLES = (
    "gb_parameter",
    "gb_parameter_history",
    "gb_input",
    "gb_input_file",
    "gb_dataset",
    "gb_dataset_change",
    "gb_operation",
    "gb_operation_io",
    "gb_operation_param",
    "gb_figure",
    "gb_stale",
    "gb_ignored",
)
SCHEMA_1_TABLES = ("gb_project", "gb_event", "gb_schema_migration")
APPEND_ONLY = (
    "gb_parameter_history",
    "gb_dataset_change",
    "gb_operation_io",
    "gb_operation_param",
    "gb_figure",
)
NOW = "2026-10-08T09:31:00.000Z"
LATER = "2026-10-09T10:00:00.000Z"
USER = "prueba@PC-PRUEBA-A"
SESSION_UID = "00000000-0000-4000-8000-000000000001"
OP_UID = "00000000-0000-4000-8000-0000000000c1"
OP2_UID = "00000000-0000-4000-8000-0000000000c2"
PARAM_UID = "00000000-0000-4000-8000-0000000000d1"
INPUT_UID = "00000000-0000-4000-8000-0000000000e1"
REF_UID = "00000000-0000-4000-8000-0000000000f1"
DATASET_UID = "00000000-0000-4000-8000-0000000000a1"
FIGURE_UID = "00000000-0000-4000-8000-0000000000b1"
UNKNOWN_UID = "00000000-0000-4000-8000-0000000000ff"
CHECK = "CHECK constraint failed"
FOREIGN_KEY = "FOREIGN KEY constraint failed"
STALE_CAUSES = (
    "dataset_changed",
    "parameter_changed",
    "input_updated",
    "input_discarded",
    "dataset_missing",
    "dataset_blocked",
    "dataset_damaged",
    "algorithm",
    "group",
)

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


def operation_row(**changes: Any) -> dict[str, Any]:
    """La importación de «Limites_v1» (``core.import_layer`` 1.0), hecha en el hilo de
    Blender."""
    return _row(
        {
            "uid": OP_UID,
            "op_type": "core.import_layer",
            "op_version": "1.0",
            "module": "core",
            "scope": "project",
            "repeatable": 0,
            "group_name": None,
            "group_uid": None,
            "settings": _json({"layer": "limites"}),
            "settings_sha256": _sha("ajustes de la importación"),
            "status": "done",
            "status_reason": None,
            "supersedes_uid": None,
            "superseded_by": None,
            "geoblender_version": "0.3.0",
            "software": "{}",
            "executor": "blender",
            "job_uid": None,
            "interpreter": None,
            "user_host": USER,
            "host": "PC-PRUEBA-A",
            "session_uid": SESSION_UID,
            "started_at": NOW,
            "finished_at": NOW,
            "message": None,
        },
        changes,
    )


RUNNING = {"status": "running", "finished_at": None}


def dataset_row(**changes: Any) -> dict[str, Any]:
    """Lo importado de «Limites_v1»: la capa ``core_imported_limites`` del proyecto, con el
    selector de su entrada e inmutable (RF-008-52)."""
    return _row(
        {
            "uid": DATASET_UID,
            "name": "core_imported_limites",
            "module": "core",
            "kind": "vector",
            "store": "gpkg",
            "locator": "core_imported_limites",
            "selector": _json({"column": "input_uid", "equals": INPUT_UID}),
            "reader": "core.gpkg_layer@1",
            "normalizer": content.NORMALIZER,
            "content_sha256": _sha("contenido"),
            "crs_epsg": 25830,
            "operation_uid": OP_UID,
            "input_uid": INPUT_UID,
            "immutable": 1,
            "qgis_editable": 0,
            "tracked": 1,
            "status": "current",
            "superseded_by": None,
            "tracked_size": None,
            "tracked_mtime_ns": None,
            "tracked_last_change": NOW,
            "tracked_schema_sha256": _sha("sql de core_imported_limites"),
            "checked_at": None,
            "description": None,
            "created_at": NOW,
            "modified_at": NOW,
        },
        changes,
    )


# Un dato derivado: un MDT en rasters/, escrito por una operación de la 006.
DERIVED = {
    "uid": _uid(0xA2),
    "name": "gis_dtm_proyecto",
    "module": "gis",
    "kind": "raster",
    "store": "rasters",
    "locator": "rasters/gis_dtm_proyecto.tif",
    "selector": "",
    "reader": "gis.geotiff@1",
    "content_sha256": _sha("mdt"),
    "input_uid": None,
    "immutable": 0,
    "tracked_size": 1_000_000,
    "tracked_mtime_ns": 1_790_000_000_000_000_000,
    "tracked_last_change": None,
    "tracked_schema_sha256": None,
}


def dataset_change_row(**changes: Any) -> dict[str, Any]:
    """El primer contenido de lo importado de «Limites_v1»."""
    return _row(
        {
            "dataset_uid": DATASET_UID,
            "from_sha256": None,
            "to_sha256": _sha("contenido"),
            "operation_uid": OP_UID,
            "detail": None,
            "at": NOW,
        },
        changes,
    )


def io_row(**changes: Any) -> dict[str, Any]:
    """La importación produce lo importado de «Limites_v1» (papel ``imported``)."""
    return _row(
        {
            "operation_uid": OP_UID,
            "direction": "out",
            "item_kind": "dataset",
            "item_uid": DATASET_UID,
            "content_sha256": _sha("contenido"),
            "role": "imported",
        },
        changes,
    )


def op_param_row(**changes: Any) -> dict[str, Any]:
    """La operación usó ``res.swell_factor`` en su revisión 2 (RF-008-05)."""
    return _row(
        {
            "operation_uid": OP_UID,
            "parameter_uid": PARAM_UID,
            "key": "res.swell_factor",
            "scope": "project",
            "rev": 2,
            "value": _json(1.23),
            "unit": "-",
            "kind": "ADOPTADO",
            "unconfirmed": 0,
            "value_sha256": _sha("1.23 -"),
        },
        changes,
    )


def figure_row(**changes: Any) -> dict[str, Any]:
    """Una cifra CALCULADA de la fase 1 (RF-008-30)."""
    return _row(
        {
            "uid": FIGURE_UID,
            "key": "res.sellable_t",
            "label": "Toneladas vendibles",
            "value": 1_234_567.5,
            "unit": "t",
            "kind": "CALCULADO",
            "operation_uid": OP_UID,
            "parameter_uid": None,
            "parameter_rev": None,
            "scope": _json({"phase": "1"}),
            "scope_key": _sha(_json({"phase": "1"}))[:16],
            "created_at": NOW,
        },
        changes,
    )


def stale_row(**changes: Any) -> dict[str, Any]:
    """La operación queda obsoleta porque cambió ``res.swell_factor`` (RF-008-24)."""
    return _row(
        {
            "item_kind": "operation",
            "item_uid": OP_UID,
            "cause_kind": "parameter_changed",
            "subject_uid": PARAM_UID,
            "since": NOW,
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


# Una fila nueva y válida de cada tabla, que no choca con la plantilla (en este orden, por
# las claves foráneas: el parámetro y la operación nuevos van antes de lo que los nombra).
NEW_ROWS: dict[str, Callable[[], dict[str, Any]]] = {
    "gb_parameter": lambda: parameter_row(uid=_uid(0xD2), key="res.density"),
    "gb_parameter_history": lambda: history_row(rev=3, action="confirm", reason=None),
    "gb_input": lambda: input_row(uid=_uid(0xE2), name="Collares"),
    "gb_input_file": lambda: file_row(ord=1, role="sidecar", path="Limites_v1.qmd"),
    "gb_dataset": lambda: dataset_row(**DERIVED),
    "gb_dataset_change": lambda: dataset_change_row(
        from_sha256=_sha("contenido"), to_sha256=_sha("contenido 2")
    ),
    "gb_operation": lambda: operation_row(
        uid=OP2_UID, op_type="gis.resample", module="gis", **RUNNING
    ),
    "gb_operation_io": lambda: io_row(
        direction="in", item_kind="input", item_uid=INPUT_UID, role="boundary"
    ),
    "gb_operation_param": lambda: op_param_row(parameter_uid=_uid(0xD2), key="res.density"),
    "gb_figure": lambda: figure_row(uid=_uid(0xB2), key="res.waste_t", label="Toneladas de estéril"),
    "gb_stale": lambda: stale_row(
        item_kind="dataset", item_uid=DATASET_UID, cause_kind="input_updated", subject_uid=INPUT_UID
    ),
    "gb_ignored": lambda: ignored_row(name="otra_capa"),
}


def _insert_sql(table: str, row: Mapping[str, Any], verb: str = "INSERT") -> tuple[str, tuple]:
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    return f"{verb} INTO {table} ({names}) VALUES ({marks})", tuple(row.values())


def _insert(conn: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> None:
    conn.execute(*_insert_sql(table, row))


def _changed(column: str) -> str:
    """Una expresión SQL que da otro valor para ``column`` (también si es nula)."""
    return (
        f"CASE WHEN typeof({column}) = 'integer' THEN {column} + 1 "
        f"ELSE coalesce({column}, '') || 'x' END"
    )


def _build(path: Path) -> None:
    """La plantilla: el esquema de esta versión (desde el 2 trae las tablas de la procedencia;
    el 3, de la spec 009, las de las versiones) y una fila en cada tabla de la procedencia (el
    parámetro con sus dos filas de historial)."""
    with gpkg.GpkgConnection.open_write(path, create=True) as db:
        with db.transaction() as conn:
            base.create_base(conn, CRS)
            project_schema.create_schema(conn)
            _insert(conn, "gb_operation", operation_row())
            _insert(conn, "gb_parameter", parameter_row())
            _insert(conn, "gb_parameter_history", history_row(**DEFAULT_HISTORY))
            _insert(conn, "gb_parameter_history", history_row())
            _insert(conn, "gb_input", input_row())
            _insert(conn, "gb_input_file", file_row())
            _insert(conn, "gb_dataset", dataset_row())
            _insert(conn, "gb_dataset_change", dataset_change_row())
            _insert(conn, "gb_operation_io", io_row())
            _insert(conn, "gb_operation_param", op_param_row())
            _insert(conn, "gb_figure", figure_row())
            _insert(conn, "gb_stale", stale_row())
            _insert(conn, "gb_ignored", ignored_row())


_TEMPLATE: list[Path] = []


def setUpModule() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="gb-008-t08-", ignore_cleanup_errors=True)
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
        tmp = tempfile.TemporaryDirectory(prefix="gb-t08-", ignore_cleanup_errors=True)
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


# Los índices que no salen de las restricciones: tabla, único, parcial y columnas (en la
# plantilla, del esquema de esta versión: el de nombres vivos de los datos es por versión desde
# el 3, spec 009).
EXPECTED_INDEXES: dict[str, tuple[str, int, int, list[str]]] = {
    "gb_input_name_active": ("gb_input", 1, 1, ["name"]),
    "gb_dataset_name_active": ("gb_dataset", 1, 1, ["version_uid", "name"]),
    "gb_dataset_location": ("gb_dataset", 1, 0, ["store", "locator", "selector"]),
    "gb_operation_io_item": ("gb_operation_io", 0, 0, ["item_kind", "item_uid", "direction"]),
    "gb_operation_io_version": (
        "gb_operation_io", 0, 0, ["item_uid", "content_sha256", "direction"]
    ),
    "gb_operation_param_parameter": ("gb_operation_param", 0, 0, ["parameter_uid"]),
    "gb_figure_key": ("gb_figure", 0, 0, ["key", "scope_key", "created_at"]),
}


class StructureTest(unittest.TestCase):
    def test_tables_indexes_and_declaration(self) -> None:
        """RF-008-01, RF-008-07, RF-008-17, RF-008-30: existen las doce tablas, los índices
        del plan (únicos parciales para los nombres activos de entradas y vivos de datos,
        único para la ubicación de un dato y los de búsqueda del grafo y las cifras) y los
        disparadores; las tablas están declaradas en ``gpkg_extensions``
        (``imga_geoblender``, ``write-only``) y fuera de ``gpkg_contents``;
        ``missing_objects`` no echa nada en falta y nombra lo que falta."""
        self.assertEqual(schema.INTERNAL_TABLES, TABLES)
        self.assertEqual(tuple(schema.TABLES), TABLES)
        self.assertEqual(set(schema.INDEXES), set(EXPECTED_INDEXES))
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
            indexes = {}
            for name, (table, *_) in EXPECTED_INDEXES.items():
                listed = {row[1]: tuple(row[2:]) for row in conn.execute(f"PRAGMA index_list({table})")}
                columns = [row[2] for row in conn.execute(f"PRAGMA index_info({name})")]
                indexes[name] = (table, listed[name][0], listed[name][2], columns, listed[name][1])
            partial_sql = {
                name: conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0]
                for name in ("gb_input_name_active", "gb_dataset_name_active")
            }
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
        for name, (table, unique, partial, columns) in EXPECTED_INDEXES.items():
            with self.subTest(name):
                self.assertEqual(indexes[name], (table, unique, partial, columns, "c"))
        self.assertIn("WHERE status NOT IN ('superseded','discarded')", partial_sql["gb_input_name_active"])
        self.assertIn(
            "WHERE status IN ('current','missing','blocked','damaged')",
            partial_sql["gb_dataset_name_active"],
        )
        # Con los del esquema 3 (spec 009) en estas tablas: los mismos nombres más tres nuevos.
        self.assertEqual(triggers, set(schema.TRIGGERS) | set(versions_schema.PROVENANCE_TRIGGERS))
        with tempfile.TemporaryDirectory(prefix="gb-t08-", ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "falta.gpkg"
            shutil.copyfile(_template(), path)
            raw = sqlite3.connect(path, isolation_level=None)
            try:
                raw.execute("DROP TRIGGER gb_parameter_history_no_upd")
                raw.execute("DROP TRIGGER gb_operation_finished")
                raw.execute("DROP INDEX gb_input_name_active")
                raw.execute("DROP INDEX gb_figure_key")
                missing = schema.missing_objects(raw)
            finally:
                raw.close()
        self.assertEqual(
            missing,
            [
                "index gb_input_name_active",
                "index gb_figure_key",
                "trigger gb_parameter_history_no_upd",
                "trigger gb_operation_finished",
            ],
        )

    def test_create_again_changes_nothing(self) -> None:
        """Plan §5.2.4 (la migración de T09): crear otra vez las tablas en una base que ya
        las tiene no cambia nada: el mismo ``sqlite_master`` (que guarda el SQL sin «IF NOT
        EXISTS»), las mismas filas y una sola declaración por tabla."""
        with tempfile.TemporaryDirectory(prefix="gb-t08-", ignore_cleanup_errors=True) as tmp:
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
        self.assertEqual(len(counts), len(project_schema.INTERNAL_TABLES))
        self.assertTrue(all(count == 1 for _, count in counts), counts)
        stored = [sql for *_, sql in master if sql is not None]
        self.assertFalse([sql for sql in stored if "IF NOT EXISTS" in sql.upper()])

    def test_every_column_has_a_rule(self) -> None:
        """RF-008-02, RF-008-07, RF-008-17, RF-008-30; plan §5.2.1, «Reglas de escritura»:
        cada columna de las tablas que se pueden cambiar es fija, cambiable o de una sola
        escritura, sin repetir (una columna nueva obliga a decidir), con lo que dice el plan;
        el historial, los cambios de los datos, lo que consume y produce cada operación, los
        parámetros que usó y las cifras son de solo inserción enteros; ``gb_stale`` es la
        caché de la que se borran filas."""
        with gpkg.GpkgConnection.open_read(_template()) as db:
            columns = {table: _columns(db.connection, table) for table in TABLES}
        self.assertEqual(schema.APPEND_ONLY_TABLES, APPEND_ONLY)
        self.assertEqual(schema.CACHE_TABLES, ("gb_stale",))
        for table in TABLES:
            with self.subTest(table):
                if table in schema.APPEND_ONLY_TABLES:
                    self.assertNotIn(table, schema.FIXED_COLUMNS)
                    self.assertNotIn(table, schema.MUTABLE_COLUMNS)
                    self.assertNotIn(table, schema.WRITE_ONCE_COLUMNS)
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
            {
                "gb_input_file": ("original_path", "original_sha256", "original_size"),
                "gb_operation": ("superseded_by",),
            },
        )
        self.assertEqual(set(schema.FIXED_COLUMNS["gb_ignored"]), {"fid", "kind", "name"})
        # gb_dataset: lo que el plan dice que no cambia, más la entrada y si es inmutable.
        self.assertTrue(
            {
                "uid", "name", "module", "kind", "store", "locator", "selector", "reader",
                "normalizer", "input_uid", "immutable",
            }
            <= set(schema.FIXED_COLUMNS["gb_dataset"])
        )
        self.assertEqual(schema.IMMUTABLE_CONTENT_COLUMNS, ("content_sha256", "operation_uid"))
        # gb_operation: lo que se completa al terminar; fuera de «en curso», nada de ello.
        self.assertEqual(
            set(schema.MUTABLE_COLUMNS["gb_operation"]),
            {
                "status", "status_reason", "software", "executor", "job_uid", "interpreter",
                "finished_at", "message",
            },
        )
        self.assertEqual(
            set(schema.FIXED_COLUMNS["gb_stale"]),
            {"item_kind", "item_uid", "cause_kind", "subject_uid"},
        )


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
    "gb_dataset": ("UPDATE gb_dataset SET description = 'otra'", "DELETE FROM gb_dataset"),
    "gb_dataset_change": (
        "UPDATE gb_dataset_change SET detail = 'otro'",
        "DELETE FROM gb_dataset_change",
    ),
    # Anotar su sustituta (de NULL a un valor): lo único que cambia en una terminada.
    "gb_operation": ("UPDATE gb_operation SET superseded_by = uid", "DELETE FROM gb_operation"),
    "gb_operation_io": ("UPDATE gb_operation_io SET role = 'otro'", "DELETE FROM gb_operation_io"),
    "gb_operation_param": (
        "UPDATE gb_operation_param SET unit = 'm'",
        "DELETE FROM gb_operation_param",
    ),
    "gb_figure": ("UPDATE gb_figure SET value = 0", "DELETE FROM gb_figure"),
    "gb_stale": ("UPDATE gb_stale SET since = 'ahora'", "DELETE FROM gb_stale"),
    "gb_ignored": ("UPDATE gb_ignored SET reason = 'otro'", "DELETE FROM gb_ignored"),
}


class ForeignConnectionTest(unittest.TestCase):
    def test_foreign_writes_fail(self) -> None:
        """RF-008-01, RF-008-02, RF-008-07, RF-008-17, RF-008-30 (RF-002-15): desde una
        conexión sin ``gb_writer()`` (QGIS, GDAL), INSERT (de una fila válida), UPDATE,
        DELETE (también en la caché) e INSERT OR REPLACE fallan en las doce tablas, que se
        leen, y el volcado SQL no cambia."""
        self.assertEqual(set(FOREIGN_WRITES), set(TABLES))
        with tempfile.TemporaryDirectory(prefix="gb-t08-", ignore_cleanup_errors=True) as tmp:
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
        """RF-008-01, RF-008-02, RF-008-07, RF-008-17, RF-008-30: sin clave, unidad, tipo,
        origen y su clase, decisor, fecha, ámbito o motivo no se guarda un parámetro; sin el
        estado de antes, quién o cuándo, una fila del historial; sin nombre, tipo, lector,
        normalizador, CRS horizontal o vertical declarados, ajustes, huellas, hashes, quién y
        cuándo la registra o su importación, una entrada; sin ruta, papel, ancla o huella, un
        fichero suyo; sin nombre, módulo, tipo, ubicación, lector, normalizador, hash de
        contenido u operación que lo escribió, un dato (D-2); sin tipo, versión, ajustes,
        estado, ejecutor, quién, dónde o cuándo, una operación; sin clave, texto, valor,
        unidad, tipo u operación, una cifra. Una fila completa sí se guarda."""
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
        self.assertGreaterEqual(len(cases), 120)
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
                "HIPO\u0301TESIS",  # la tilde descompuesta (NFD)
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
            cases.append((f"{column}={value!r}", sql, args, CHECK))
        self.assertRejected(cases)
        # Desde el esquema 3 (spec 009), un parámetro de versión es de una versión viva.
        version = (
            "INSERT INTO gb_version (uid, code, feature, title, reason_created, created_at, "
            "created_by, status_changed_at, status_changed_by, modified_at) "
            "VALUES (?, 'V01', 'prueba', 'Prueba', 'Prueba', ?, ?, ?, ?, ?)",
            (_uid(0x777), NOW, USER, NOW, USER, NOW),
        )
        self.accept(version, *(_insert_sql("gb_parameter", row) for row in accepted))
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
                ("sin operación", *_insert_sql("gb_parameter", calculated), CHECK),
                (
                    "operación desconocida",
                    *_insert_sql("gb_parameter", {**calculated, "operation_uid": UNKNOWN_UID}),
                    FOREIGN_KEY,
                ),
                (
                    "cambiar a CALCULADO sin operación",
                    "UPDATE gb_parameter SET kind = 'CALCULADO' WHERE uid = ?",
                    (PARAM_UID,),
                    CHECK,
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
                    CHECK,
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
                    CHECK,
                ),
                (
                    "cambiar a MEDIDO",
                    "UPDATE gb_parameter SET kind = 'MEDIDO' WHERE uid = ?",
                    (_uid(0xD4),),
                    CHECK,
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
        cases: list[Case] = []
        rev = 10
        for action in ("default", "create", "change"):
            for reason in (None, "", "   "):
                row = history_row(rev=rev, action=action, reason=reason)
                cases.append((f"{action}, {reason!r}", *_insert_sql(table, row), CHECK))
                rev += 1
        for action in ("", "delete", "update", "Confirm"):
            row = history_row(rev=rev, action=action)
            cases.append((f"acción {action!r}", *_insert_sql(table, row), CHECK))
            rev += 1
        cases.append(
            (
                "parámetro desconocido",
                *_insert_sql(table, history_row(rev=rev, parameter_uid=UNKNOWN_UID)),
                FOREIGN_KEY,
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
        cases: list[Case] = []
        for number, (column, value) in enumerate(bad_inputs):
            row = input_row(uid=_uid(0x300 + number), name=f"Mal_{number}", **{column: value})
            cases.append((f"{column}={value!r}", *_insert_sql("gb_input", row), CHECK))
        bad_files = (("role", "principal"), ("anchor", "absolute"), ("anchor", ""))
        for number, (column, value) in enumerate(bad_files):
            row = file_row(ord=10 + number, **{column: value})
            cases.append((f"{column}={value!r}", *_insert_sql("gb_input_file", row), CHECK))
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
            cases.append((label, *_insert_sql(table, row), FOREIGN_KEY))
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
        once = _abort(table, schema.MSG_WRITE_ONCE[table])
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


class DatasetTest(_DbCase):
    def test_dataset_keeps_what_rf_008_17_asks(self) -> None:
        """RF-008-17, RF-008-52: un dato se guarda con nombre estable, módulo dueño, tipo,
        ubicación, lector y normalizador, hash de contenido y la operación que escribió su
        contenido actual (lo importado, también con su entrada, inmutable); se lee igual. Un
        acumulado comparte la tabla con otro selector, y lo exportado y lo de DuckDB van sin
        seguimiento. Un dato sin operación (sin procedencia), con un tipo, almacén o estado
        desconocidos, inmutable sin entrada, sin seguimiento fuera de ``exports`` y
        ``duckdb``, o con una operación, una entrada o un sucesor que no existen, se
        rechaza."""
        table = "gb_dataset"
        rows = [
            dataset_row(**DERIVED),
            dataset_row(
                uid=_uid(0xA3),
                name="core_inputs_limites",
                selector=_json({"column": "input_uid", "of": "current_inputs"}),
                content_sha256=_sha("acumulado"),
                input_uid=None,
                immutable=0,
                description="Límites de las entradas vigentes",
            ),
            dataset_row(
                uid=_uid(0xA4),
                name="exp_plano",
                kind="report",
                store="exports",
                locator="exports/plano.pdf",
                selector="",
                reader="core.document@1",
                crs_epsg=None,
                input_uid=None,
                immutable=0,
                tracked=0,
            ),
            dataset_row(
                uid=_uid(0xA5),
                name="bm_bloques",
                module="bm",
                kind="block_model",
                store="duckdb",
                locator="blocks.duckdb",
                selector="",
                reader="bm.duckdb@1",
                input_uid=None,
                immutable=0,
                tracked=0,
            ),
        ]
        self.accept(*(_insert_sql(table, row) for row in rows))
        for row in rows:
            stored = self.row(table, "uid = ?", (row["uid"],))
            self.assertEqual({key: stored[key] for key in row}, row)

        def bad(number: int, **changes: Any) -> dict[str, Any]:
            return dataset_row(
                uid=_uid(0x500 + number), name=f"mal_{number}", locator=f"mal_{number}", **changes
            )

        cases: list[Case] = [
            ("sin procedencia", *_insert_sql(table, bad(0, operation_uid=None)),
             "NOT NULL constraint failed: gb_dataset.operation_uid"),
            ("tipo 'grid'", *_insert_sql(table, bad(1, kind="grid")), CHECK),
            ("tipo 'Vector'", *_insert_sql(table, bad(2, kind="Vector")), CHECK),
            ("almacén 'cache'", *_insert_sql(table, bad(3, store="cache")), CHECK),
            ("almacén 'GPKG'", *_insert_sql(table, bad(4, store="GPKG")), CHECK),
            ("estado 'stale'", *_insert_sql(table, bad(5, status="stale")), CHECK),
            ("estado 'vigente'", *_insert_sql(table, bad(6, status="vigente")), CHECK),
            ("inmutable sin entrada", *_insert_sql(table, bad(7, input_uid=None)), CHECK),
            ("sin seguimiento en gpkg", *_insert_sql(table, bad(8, tracked=0)), CHECK),
            ("operación desconocida", *_insert_sql(table, bad(9, operation_uid=UNKNOWN_UID)), FOREIGN_KEY),
            ("entrada desconocida", *_insert_sql(table, bad(10, input_uid=UNKNOWN_UID)), FOREIGN_KEY),
            ("sucesor desconocido", *_insert_sql(table, bad(11, superseded_by=UNKNOWN_UID)), FOREIGN_KEY),
        ]
        self.assertRejected(cases)

    def test_one_live_dataset_per_name(self) -> None:
        """RF-008-17 (D21; plan §5.2.1): un nombre tiene como mucho un dato vivo (vigente,
        que falta, bloqueado o dañado): otro vivo con el mismo nombre se rechaza, también con
        ``INSERT OR REPLACE`` y al devolver a vivo uno sustituido o descartado (también con
        ``UPDATE OR REPLACE``); uno sustituido o descartado no choca: el nombre queda tres
        veces y solo uno vivo."""
        table = "gb_dataset"
        live = _abort(table, schema.MSG_LIVE_DATASET)

        def twin(number: int, **changes: Any) -> dict[str, Any]:
            return dataset_row(
                uid=_uid(0x600 + number), locator=f"core_imported_limites_{number}", **changes
            )

        cases: list[Case] = [
            (status, *_insert_sql(table, twin(number, status=status)), live)
            for number, status in enumerate(("current", "missing", "blocked", "damaged"))
        ]
        cases.append(("REPLACE", *_insert_sql(table, twin(9), "INSERT OR REPLACE"), live))
        self.assertRejected(cases)
        successor, discarded = twin(10), twin(11, status="discarded")
        self.accept(
            ("UPDATE gb_dataset SET status = 'superseded' WHERE uid = ?", (DATASET_UID,)),
            _insert_sql(table, successor),
            (
                "UPDATE gb_dataset SET superseded_by = ? WHERE uid = ?",
                (successor["uid"], DATASET_UID),
            ),
            _insert_sql(table, discarded),
        )
        self.assertRejected(
            [
                (
                    "volver a vigente",
                    "UPDATE gb_dataset SET status = 'current' WHERE uid = ?",
                    (DATASET_UID,),
                    live,
                ),
                (
                    "volver con REPLACE",
                    "UPDATE OR REPLACE gb_dataset SET status = 'missing' WHERE uid = ?",
                    (DATASET_UID,),
                    live,
                ),
                (
                    "descartado a dañado",
                    "UPDATE gb_dataset SET status = 'damaged' WHERE uid = ?",
                    (discarded["uid"],),
                    live,
                ),
            ]
        )
        names = self.db.connection.execute(
            "SELECT uid, status, superseded_by FROM gb_dataset "
            "WHERE name = 'core_imported_limites' ORDER BY fid"
        ).fetchall()
        self.assertEqual(
            names,
            [
                (DATASET_UID, "superseded", successor["uid"]),
                (successor["uid"], "current", None),
                (discarded["uid"], "discarded", None),
            ],
        )
        self.accept(("UPDATE gb_dataset SET status = 'discarded' WHERE uid = ?", (successor["uid"],)))
        self.accept(("UPDATE gb_dataset SET status = 'current' WHERE uid = ?", (DATASET_UID,)))

    def test_location_is_never_reused(self) -> None:
        """RF-008-17 (D21; plan §5.2.1): dos datos con la misma ubicación (almacén, tabla o
        ruta y selector) se rechazan siempre, aunque el que la ocupa esté sustituido o
        descartado y también con ``INSERT OR REPLACE``; la misma tabla con otro selector (un
        acumulado, lo importado de otra entrada) o la misma ruta en otro almacén, sí."""
        table = "gb_dataset"
        location = _abort(table, schema.MSG_LOCATION)

        def other(number: int, **changes: Any) -> dict[str, Any]:
            return dataset_row(uid=_uid(0x700 + number), name=f"otro_{number}", **changes)

        cases: list[Case] = [
            (status, *_insert_sql(table, other(number, status=status)), location)
            for number, status in enumerate(("current", "superseded", "discarded"))
        ]
        cases.append(("REPLACE", *_insert_sql(table, other(5), "INSERT OR REPLACE"), location))
        self.assertRejected(cases)
        self.accept(("UPDATE gb_dataset SET status = 'discarded' WHERE uid = ?", (DATASET_UID,)))
        self.assertRejected([("ocupada por un descartado", *_insert_sql(table, other(6)), location)])
        self.accept(
            _insert_sql(
                table, other(7, selector=_json({"column": "input_uid", "equals": _uid(0xE9)}))
            ),
            _insert_sql(table, other(8, store="exports", tracked=0, immutable=0, input_uid=None)),
        )
        self.assertEqual(
            self.scalar("SELECT count(*) FROM gb_dataset WHERE locator = 'core_imported_limites'"), 3
        )

    def test_identity_fixed_imported_content_fixed_and_nothing_deleted(self) -> None:
        """RF-008-17, RF-008-52 (plan §5.2.1): de un dato no cambian su identidad, su nombre,
        su módulo, su tipo, su ubicación, su lector, su normalizador, su entrada ni si es
        inmutable; lo importado (inmutable) tampoco cambia de contenido ni de la operación que
        lo escribió, y uno derivado sí. Su estado, su seguimiento y su comprobación cambian.
        Ninguno se borra ni se sustituye con ``INSERT OR REPLACE``."""
        table = "gb_dataset"
        no_replace = _abort(table, schema.MSG_NO_REPLACE)
        cases = self.fixed_cases(table, "uid = '" + DATASET_UID + "'")
        cases += [
            ("borrar", f"DELETE FROM {table}", (), _abort(table, schema.MSG_NO_DELETE)),
            (
                "REPLACE por uid",
                *_insert_sql(table, dataset_row(name="otro", locator="otro"), "INSERT OR REPLACE"),
                no_replace,
            ),
            (
                "REPLACE por fid",
                *_insert_sql(
                    table,
                    {"fid": 1, **dataset_row(uid=_uid(0xA9), name="otro", locator="otro")},
                    "INSERT OR REPLACE",
                ),
                no_replace,
            ),
        ]
        self.assertGreaterEqual(len(schema.FIXED_COLUMNS[table]), 13)
        self.assertRejected(cases)
        derived = dataset_row(**DERIVED)
        self.accept(
            _insert_sql("gb_operation", operation_row(uid=OP2_UID, op_type="core.external_edit")),
            _insert_sql(table, derived),
        )
        immutable = _abort(table, schema.MSG_IMMUTABLE)
        self.assertRejected(
            [
                (
                    "contenido de lo importado",
                    f"UPDATE {table} SET content_sha256 = ? WHERE uid = ?",
                    (_sha("editado en QGIS"), DATASET_UID),
                    immutable,
                ),
                (
                    "operación de lo importado",
                    f"UPDATE {table} SET operation_uid = ? WHERE uid = ?",
                    (OP2_UID, DATASET_UID),
                    immutable,
                ),
            ]
        )
        self.accept(
            (f"UPDATE {table} SET uid = uid, name = name, locator = locator, "
             "content_sha256 = content_sha256, operation_uid = operation_uid", ()),
            (
                f"UPDATE {table} SET status = 'damaged', tracked_last_change = ?, "
                "tracked_schema_sha256 = ?, checked_at = ?, qgis_editable = 1, "
                "description = 'Editado fuera de Geoblender', modified_at = ? WHERE uid = ?",
                (LATER, _sha("sql 2"), LATER, LATER, DATASET_UID),
            ),
            (
                f"UPDATE {table} SET content_sha256 = ?, operation_uid = ?, tracked_size = 2, "
                "crs_epsg = 25830, modified_at = ? WHERE uid = ?",
                (_sha("mdt editado"), OP2_UID, LATER, derived["uid"]),
            ),
        )
        imported = self.row(table, "uid = ?", (DATASET_UID,))
        self.assertEqual(
            (imported["status"], imported["content_sha256"], imported["operation_uid"]),
            ("damaged", _sha("contenido"), OP_UID),
        )
        edited = self.row(table, "uid = ?", (derived["uid"],))
        self.assertEqual(
            (edited["content_sha256"], edited["operation_uid"], edited["created_at"]),
            (_sha("mdt editado"), OP2_UID, NOW),
        )

    def test_dataset_change_and_operation_links(self) -> None:
        """RF-008-17, RF-008-18: cada contenido nuevo de un dato queda en
        ``gb_dataset_change`` con la operación que lo escribió, y lo que consume y produce
        una operación en ``gb_operation_io`` (dato o entrada, con su hash y su papel; el
        mismo elemento con otro papel no choca); un dato, una operación o un parámetro que no
        existen, una dirección o un tipo de elemento desconocidos, se rechazan."""
        cases: list[Case] = [
            (
                "dato desconocido",
                *_insert_sql("gb_dataset_change", dataset_change_row(dataset_uid=UNKNOWN_UID)),
                FOREIGN_KEY,
            ),
            (
                "operación del cambio desconocida",
                *_insert_sql("gb_dataset_change", dataset_change_row(operation_uid=UNKNOWN_UID)),
                FOREIGN_KEY,
            ),
            ("dirección", *_insert_sql("gb_operation_io", io_row(direction="both")), CHECK),
            ("tipo de elemento", *_insert_sql("gb_operation_io", io_row(item_kind="parameter")), CHECK),
            (
                "operación desconocida",
                *_insert_sql("gb_operation_io", io_row(operation_uid=UNKNOWN_UID, role="otro")),
                FOREIGN_KEY,
            ),
            (
                "parámetro desconocido",
                *_insert_sql("gb_operation_param", op_param_row(parameter_uid=UNKNOWN_UID)),
                FOREIGN_KEY,
            ),
        ]
        self.assertRejected(cases)
        self.accept(
            _insert_sql("gb_dataset_change", NEW_ROWS["gb_dataset_change"]()),
            _insert_sql("gb_operation_io", NEW_ROWS["gb_operation_io"]()),
            _insert_sql("gb_operation_io", io_row(role="imported_copy")),
        )
        self.assertEqual(
            self.db.connection.execute(
                "SELECT from_sha256, to_sha256 FROM gb_dataset_change ORDER BY fid"
            ).fetchall(),
            [(None, _sha("contenido")), (_sha("contenido"), _sha("contenido 2"))],
        )
        self.assertEqual(self.scalar("SELECT count(*) FROM gb_operation_io"), 3)


class OperationTest(_DbCase):
    def test_states_and_completion(self) -> None:
        """RF-008-18, RF-008-19, RF-008-51: una operación se registra «en curso» sin fecha de
        fin y se completa con su estado, su fin, dónde se ejecutó (también en un proceso
        aparte, con su trabajo e intérprete), las bibliotecas y su mensaje; una en curso con
        fin, una terminada sin fin, un estado, un ejecutor o un ámbito desconocidos, y una
        operación sustituida o sustituta que no existe, se rechazan. Cancelada, fallida,
        interrumpida y no incorporada son estados terminados."""
        table = "gb_operation"

        def op(number: int, **changes: Any) -> dict[str, Any]:
            return operation_row(uid=_uid(0x800 + number), **changes)

        self.assertRejected(
            [
                ("en curso con fin", *_insert_sql(table, op(0, status="running")), CHECK),
                ("hecha sin fin", *_insert_sql(table, op(1, finished_at=None)), CHECK),
                ("estado 'hecha'", *_insert_sql(table, op(2, status="hecha")), CHECK),
                ("estado 'stale'", *_insert_sql(table, op(3, status="stale")), CHECK),
                ("ejecutor 'gpu'", *_insert_sql(table, op(4, executor="gpu")), CHECK),
                ("ámbito 'sector'", *_insert_sql(table, op(5, scope="sector")), CHECK),
                ("sustituye a una desconocida", *_insert_sql(table, op(6, supersedes_uid=UNKNOWN_UID)),
                 FOREIGN_KEY),
                ("sustituida por una desconocida", *_insert_sql(table, op(7, superseded_by=UNKNOWN_UID)),
                 FOREIGN_KEY),
            ]
        )
        interpreter = _json({"python": "3.13.13", "numpy": "2.3.4", "blas": "openblas"})
        software = _json({"numpy": "2.3.4"})
        self.accept(
            _insert_sql(table, operation_row(uid=OP2_UID, **RUNNING)),
            (
                "UPDATE gb_operation SET status = 'done', finished_at = ?, executor = 'job_process', "
                "job_uid = ?, interpreter = ?, software = ?, message = 'Hecho' WHERE uid = ?",
                (LATER, _uid(0x99), interpreter, software, OP2_UID),
            ),
        )
        row = self.row(table, "uid = ?", (OP2_UID,))
        self.assertEqual(
            (row["status"], row["finished_at"], row["executor"], row["interpreter"], row["started_at"]),
            ("done", LATER, "job_process", interpreter, NOW),
        )
        for number, status in enumerate(("cancelled", "failed", "interrupted", "not_ingested")):
            with self.subTest(status):
                uid = _uid(0x810 + number)
                self.accept(
                    _insert_sql(table, operation_row(uid=uid, **RUNNING)),
                    (
                        "UPDATE gb_operation SET status = ?, status_reason = 'motivo', "
                        "finished_at = ? WHERE uid = ?",
                        (status, LATER, uid),
                    ),
                )
                self.assertRejected(
                    [
                        (
                            "cambiar el motivo",
                            "UPDATE gb_operation SET status_reason = 'otro' WHERE uid = ?",
                            (uid,),
                            _abort(table, schema.MSG_FINISHED),
                        )
                    ]
                )

    def test_finished_operation_only_records_its_successor(self) -> None:
        """RF-008-18, RF-008-19 (plan §5.2.1): una operación terminada no cambia nada salvo
        ``superseded_by``, y solo de NULL a un valor: cambiar cualquier otra columna que se
        completa al terminar, volver a «en curso», cambiar o quitar su sustituta se rechazan;
        su identidad no cambia ni en curso; ninguna se borra ni se sustituye."""
        table = "gb_operation"
        finished = _abort(table, schema.MSG_FINISHED)
        no_replace = _abort(table, schema.MSG_NO_REPLACE)
        where = f"uid = '{OP_UID}'"
        self.accept(_insert_sql(table, operation_row(uid=OP2_UID, **RUNNING)))
        cases: list[Case] = [
            (f"terminada.{column}", f"UPDATE {table} SET {column} = {_changed(column)} WHERE {where}",
             (), finished)
            for column in schema.MUTABLE_COLUMNS[table]
        ]
        cases.append(
            (
                "volver a en curso",
                f"UPDATE {table} SET status = 'running', finished_at = NULL WHERE {where}",
                (),
                finished,
            )
        )
        cases += self.fixed_cases(table, where)
        cases += [(f"en curso: {label}", *rest) for label, *rest in self.fixed_cases(table, f"uid = '{OP2_UID}'")]
        cases += [
            ("borrar", f"DELETE FROM {table}", (), _abort(table, schema.MSG_NO_DELETE)),
            ("REPLACE por uid", *_insert_sql(table, operation_row(), "INSERT OR REPLACE"), no_replace),
            (
                "REPLACE por fid",
                *_insert_sql(table, {"fid": 1, **operation_row(uid=_uid(0x8FF))}, "INSERT OR REPLACE"),
                no_replace,
            ),
        ]
        self.assertGreaterEqual(len(cases), 45)
        self.assertRejected(cases)
        successor = operation_row(uid=_uid(0x820), supersedes_uid=OP_UID)
        self.accept(
            _insert_sql(table, successor),
            (f"UPDATE {table} SET superseded_by = ? WHERE {where}", (successor["uid"],)),
            (f"UPDATE {table} SET status = status, message = message, superseded_by = superseded_by "
             f"WHERE {where}", ()),
        )
        once = _abort(table, schema.MSG_WRITE_ONCE[table])
        self.assertRejected(
            [
                ("otra sustituta", f"UPDATE {table} SET superseded_by = ? WHERE {where}", (OP2_UID,), once),
                ("quitar la sustituta", f"UPDATE {table} SET superseded_by = NULL WHERE {where}", (), once),
            ]
        )
        row = self.row(table, where)
        self.assertEqual(
            (row["status"], row["finished_at"], row["superseded_by"]), ("done", NOW, successor["uid"])
        )


class AppendOnlyTest(_DbCase):
    def test_append_only_tables(self) -> None:
        """RF-008-05, RF-008-17, RF-008-18, RF-008-30: ninguna fila de los cambios de los
        datos, de lo que consume y produce una operación, de los parámetros que usó ni de las
        cifras cambia (ninguna columna) ni se borra, tampoco desde Geoblender ni sustituyéndola
        con ``INSERT OR REPLACE`` (por ``fid`` o por su clave única); una fila nueva sí se
        añade."""
        cases: list[Case] = []
        duplicates = {
            "gb_operation_io": io_row(),
            "gb_operation_param": op_param_row(),
            "gb_figure": figure_row(key="res.otra"),
        }
        for table in APPEND_ONLY[1:]:
            append_only = _abort(table, schema.MSG_APPEND_ONLY)
            cases += [
                (f"{table}.{column}", f"UPDATE {table} SET {column} = {_changed(column)}", (), append_only)
                for column in _columns(self.db.connection, table)
            ]
            cases += [
                (f"{table}: borrar", f"DELETE FROM {table}", (), append_only),
                (
                    f"{table}: REPLACE por fid",
                    *_insert_sql(table, {"fid": 1, **NEW_ROWS[table]()}, "INSERT OR REPLACE"),
                    append_only,
                ),
            ]
            if table in duplicates:
                cases += [
                    (f"{table}: la misma", *_insert_sql(table, duplicates[table]), append_only),
                    (
                        f"{table}: REPLACE por clave",
                        *_insert_sql(table, duplicates[table], "INSERT OR REPLACE"),
                        append_only,
                    ),
                ]
        self.assertGreaterEqual(len(cases), 50)
        self.assertRejected(cases)
        self.accept(
            _insert_sql("gb_parameter", NEW_ROWS["gb_parameter"]()),
            *(_insert_sql(table, NEW_ROWS[table]()) for table in APPEND_ONLY[1:]),
        )
        for table in APPEND_ONLY[1:]:
            self.assertEqual(self.scalar(f"SELECT count(*) FROM {table}"), 2, table)


class FigureTest(_DbCase):
    def test_figure_needs_type_unit_operation_and_a_finite_value(self) -> None:
        """RF-008-30: una cifra sin clave, texto, tipo, unidad u operación de origen, con un
        tipo fuera de los cuatro (``HIPOTESIS`` sin tilde, en minúsculas), con una operación
        o un parámetro que no existen, NaN (que SQLite guarda como NULL) o infinita (±) no se
        registra (el texto del rechazo lo da ``record_figure``, T19); el mayor finito, el
        menor subnormal, cero y los valores corrientes se guardan exactos; una cifra que
        muestra un parámetro lo nombra con su revisión."""
        table = "gb_figure"

        def fig(number: int, **changes: Any) -> dict[str, Any]:
            return figure_row(uid=_uid(0x900 + number), **changes)

        cases: list[Case] = [
            ("NaN", *_insert_sql(table, fig(0, value=math.nan)),
             "NOT NULL constraint failed: gb_figure.value"),
            ("+infinito", *_insert_sql(table, fig(1, value=math.inf)), CHECK),
            ("-infinito", *_insert_sql(table, fig(2, value=-math.inf)), CHECK),
            ("sin tipo", *_insert_sql(table, fig(3, kind=None)), "NOT NULL constraint failed: gb_figure.kind"),
            ("HIPOTESIS", *_insert_sql(table, fig(4, kind="HIPOTESIS")), CHECK),
            ("en minúsculas", *_insert_sql(table, fig(5, kind="calculado")), CHECK),
            ("sin unidad", *_insert_sql(table, fig(6, unit=None)), "NOT NULL constraint failed: gb_figure.unit"),
            ("sin operación", *_insert_sql(table, fig(7, operation_uid=None)),
             "NOT NULL constraint failed: gb_figure.operation_uid"),
            ("operación desconocida", *_insert_sql(table, fig(8, operation_uid=UNKNOWN_UID)), FOREIGN_KEY),
            ("parámetro desconocido", *_insert_sql(table, fig(9, parameter_uid=UNKNOWN_UID, parameter_rev=1)),
             FOREIGN_KEY),
            ("sin clave", *_insert_sql(table, fig(10, key=None)), "NOT NULL constraint failed: gb_figure.key"),
            ("sin texto", *_insert_sql(table, fig(11, label=None)), "NOT NULL constraint failed: gb_figure.label"),
        ]
        self.assertRejected(cases)
        values = (sys.float_info.max, -sys.float_info.max, 5e-324, 0.0, 0.1, 13.43, -2.5e-12)
        self.accept(
            *(_insert_sql(table, fig(0x20 + number, value=value)) for number, value in enumerate(values)),
            _insert_sql(
                table,
                fig(0x30, key="res.swell_factor", label="Esponjamiento", value=1.23, unit="-",
                    kind="ADOPTADO", parameter_uid=PARAM_UID, parameter_rev=2),
            ),
        )
        stored = [
            value
            for (value,) in self.db.connection.execute(
                f"SELECT value FROM {table} WHERE uid BETWEEN ? AND ? ORDER BY fid",
                (_uid(0x920), _uid(0x92F)),
            )
        ]
        self.assertEqual(stored, list(values))
        shown = self.row(table, "uid = ?", (_uid(0x930),))
        self.assertEqual((shown["kind"], shown["parameter_uid"], shown["parameter_rev"]), ("ADOPTADO", PARAM_UID, 2))


class StaleTest(_DbCase):
    def test_stale_is_a_cache(self) -> None:
        """RF-008-24, RF-008-28 (plan §5.2.1; ADR-0025 §5): ``gb_stale`` es la caché de la
        obsolescencia deducida, la única tabla de la que Geoblender borra filas (y la que
        sustituye con ``INSERT OR REPLACE``); guarda las nueve causas de una operación o un
        dato, una vez cada una; un elemento o una causa desconocidos y cambiar el elemento o la
        causa de una fila se rechazan."""
        table = "gb_stale"
        rows = [
            stale_row(cause_kind=cause, subject_uid=_uid(0xA00 + number))
            for number, cause in enumerate(STALE_CAUSES)
        ]
        self.accept(*(_insert_sql(table, row) for row in rows))
        self.assertRejected(
            [
                ("elemento 'input'", *_insert_sql(table, stale_row(item_kind="input")), CHECK),
                ("causa desconocida", *_insert_sql(table, stale_row(cause_kind="edited")), CHECK),
                ("repetida", *_insert_sql(table, stale_row()), "UNIQUE constraint failed"),
                *self.fixed_cases(table, f"subject_uid = '{PARAM_UID}'"),
            ]
        )
        replaced = stale_row(cause_kind=STALE_CAUSES[0], subject_uid=_uid(0xA00), since=LATER)
        self.accept(
            (f"UPDATE {table} SET since = ? WHERE subject_uid = ?", (LATER, PARAM_UID)),
            _insert_sql(table, replaced, "INSERT OR REPLACE"),
            (f"DELETE FROM {table} WHERE cause_kind = 'algorithm'", ()),
        )
        # La plantilla y las nueve causas, menos la borrada (la sustituida sigue siendo una).
        self.assertEqual(self.scalar(f"SELECT count(*) FROM {table}"), len(STALE_CAUSES))
        self.assertEqual(
            self.scalar(f"SELECT since FROM {table} WHERE subject_uid = ?", (_uid(0xA00),)), LATER
        )
        self.accept((f"DELETE FROM {table}", ()))
        self.assertEqual(self.scalar(f"SELECT count(*) FROM {table}"), 0)


class IgnoredTest(_DbCase):
    def test_ignored(self) -> None:
        """RF-008-62 (plan §5.2.1): lo ignorado es una tabla o un fichero, una vez por tipo y
        nombre; no cambia de tipo ni de nombre, su motivo y quién lo decidió sí, y no se borra
        ni se sustituye."""
        table = "gb_ignored"
        no_replace = _abort(table, schema.MSG_NO_REPLACE)
        cases = self.fixed_cases(table, "name = 'capa_de_trabajo'")
        cases += [
            ("tipo desconocido", *_insert_sql(table, ignored_row(kind="folder", name="x")), CHECK),
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


class ProjectSchemaTest(unittest.TestCase):
    """El esquema 2 del proyecto (``core.project.schema``) y su comprobación al abrir."""

    def _create(self, tmp: Path) -> Any:
        parent = tmp / "proyectos"
        parent.mkdir()
        created = create.create_project(
            parent, make_settings(), make_session(), userdata_mod.UserData(tmp / "datos"),
            clock=FakeClock(),
        )
        created.project.close()
        return created

    def _open(self, tmp: Path, root: Path) -> Any:
        session = make_session()
        return open_mod.open_project(
            root, session, userdata_mod.UserData(tmp / "datos"), clock=FakeClock(),
            pid_alive=FakePids({session.pid}),
        )

    def test_new_project_has_the_current_schema(self) -> None:
        """RF-008-17, RF-008-30 (RF-002-14, RF-002-22; plan §5.2): un proyecto nuevo tiene
        el esquema de esta versión (el 2 de la 008 y, desde la spec 009, el 3) con
        ``min_reader_schema`` 1 (un Geoblender de la 002 lo abre en solo lectura), en su base y
        en su cabecera; sus tablas internas son las tres de la 002, las doce de la procedencia
        y las cinco de las versiones, vacías y declaradas en ``gpkg_extensions`` con una
        definición sin número de esquema, y ``missing_objects`` no echa nada en falta."""
        self.assertEqual((project_schema.SCHEMA_VERSION, project_schema.MIN_READER_SCHEMA), (4, 1))
        self.assertEqual(project_schema.INTERNAL_TABLES,
                         SCHEMA_1_TABLES + TABLES + versions_schema.INTERNAL_TABLES
                         + (project_schema.APPEARANCE_TABLE,))
        self.assertNotIn("esquema", base.EXTENSION_DEFINITION)
        with project_tmp("gb-t08-") as tmp:
            created = self._create(tmp)
            header = manifest_mod.read_manifest(created.root)
            with gpkg.GpkgConnection.open_read(created.root / "project.gpkg") as db:
                conn = db.connection
                versions = conn.execute(
                    "SELECT schema_version, min_reader_schema FROM gb_project"
                ).fetchone()
                missing = project_schema.missing_objects(conn, 3)
                counts = {
                    table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    for table in TABLES + versions_schema.INTERNAL_TABLES
                }
                declared = conn.execute(
                    "SELECT table_name, definition, scope FROM gpkg_extensions "
                    "WHERE extension_name = 'imga_geoblender' ORDER BY table_name"
                ).fetchall()
        self.assertEqual(tuple(versions), (4, 1))
        self.assertEqual((created.record.schema_version, created.record.min_reader_schema), (4, 1))
        self.assertEqual((header.schema_version, header.min_reader_schema), (4, 1))
        self.assertEqual(missing, [])
        self.assertEqual(counts, dict.fromkeys(TABLES + versions_schema.INTERNAL_TABLES, 0))
        self.assertEqual(
            declared,
            [
                (table, base.EXTENSION_DEFINITION, "write-only")
                for table in sorted(project_schema.INTERNAL_TABLES)
            ],
        )

    def test_missing_objects_by_version(self) -> None:
        """RF-002-20, RF-002-22 (plan §5.1): ``missing_objects(conn, version)`` echa en falta
        lo del esquema pedido: en el 1, solo lo de la 002; en el 2, también las tablas, los
        índices y los disparadores de la procedencia; en uno posterior, lo que conoce esta
        versión (el 2). Un esquema que no es un entero desde 1 es un error."""
        with tempfile.TemporaryDirectory(prefix="gb-t08-", ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "falta.gpkg"
            shutil.copyfile(_template(), path)
            raw = sqlite3.connect(path, isolation_level=None)
            try:
                self.assertEqual(project_schema.missing_objects(raw, 2), [])
                raw.execute("DROP TRIGGER gb_event_no_upd")
                raw.execute("DROP TABLE gb_figure")
                found = {version: project_schema.missing_objects(raw, version) for version in (1, 2, 3)}
                for wrong, error in ((0, ValueError), (-1, ValueError), (True, TypeError), ("2", TypeError)):
                    with self.subTest(version=wrong), self.assertRaises(error):
                        project_schema.missing_objects(raw, wrong)
            finally:
                raw.close()
        figure = ["table gb_figure", "index gb_figure_key"] + [
            f"trigger {name}" for name in schema.TRIGGERS if name.startswith("gb_figure_")
        ]
        self.assertEqual(found[1], ["trigger gb_event_no_upd"])
        self.assertEqual(found[2], ["trigger gb_event_no_upd", *figure])
        self.assertEqual(found[3], found[2])
        self.assertGreaterEqual(len(figure), 6)

    def test_open_checks_the_objects_of_its_schema(self) -> None:
        """RF-002-05, RF-002-20 (plan §5.1): al abrir, a un proyecto del esquema 2 que ha
        perdido un disparador de la procedencia se le echa en falta y no se abre; uno del
        esquema 1, sin las tablas de la procedencia, abre (en solo lectura, sin migrar) sin
        que le falte nada."""
        with project_tmp("gb-t08-") as tmp:
            created = self._create(tmp)
            database = created.root / "project.gpkg"
            raw = sqlite3.connect(database, isolation_level=None)
            try:
                raw.execute("DROP TRIGGER gb_figure_no_upd")
            finally:
                raw.close()
            with self.assertRaises(errors.ProjectError) as caught:
                self._open(tmp, created.root)
            self.assertEqual(caught.exception.code, "core.project_database_incomplete")
            self.assertIn("trigger gb_figure_no_upd", str(caught.exception))
            raw = sqlite3.connect(database, isolation_level=None)
            try:
                for table in reversed(TABLES):
                    raw.execute(f"DROP TABLE {table}")
            finally:
                raw.close()
            mark_schema(created.root, 1)
            result = self._open(tmp, created.root)
            try:
                self.assertEqual(result.project.read_only_reason, model.ReadOnlyCode.NOT_MIGRATED)
                self.assertEqual(result.project.schema_version, 1)
            finally:
                result.project.close()


if __name__ == "__main__":
    unittest.main()
