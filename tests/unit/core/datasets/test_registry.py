# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de los datos del proyecto (spec 008, T16; RF-008-17, RF-008-52; ADR-0024 §6;
ADR-0025 §4 y §6; plan 008 §5.2.1, §5.3.1 y §5.4.8).

``core.datasets.registry`` registra cada dato que escribe una operación (capa, tabla,
rejilla, malla, informe) con nombre estable, módulo, tipo, ubicación, su lector y su
normalizador para siempre, su hash de contenido y la operación **en curso** que escribió su
contenido actual: un dato sin operación no se registra (RF-008-17, D-2). Cada contenido nuevo
deja su fila en ``gb_dataset_change`` (con el detalle del módulo) y su salida en
``gb_operation_io`` (con su papel), y se hashea con el lector y el normalizador **del dato**
(ADR-0024 §6). Una tabla del GeoPackage queda seguida (``gpkg_contents.last_change`` y la
huella de su SQL anotados tras la escritura; T10); lo importado (``immutable``) no admite
contenido nuevo y su tabla queda protegida (RF-008-52); varias entradas importan a una tabla
común con un dato importado por entrada (selector fijo) y un dato acumulado (selector de las
entradas vigentes); el sucesor de un dato sustituido se resuelve por papel; ``exports`` y
``duckdb`` se registran sin seguimiento.

Cada prueba trabaja en una copia del GeoPackage de ``tests.support.dataset_tables`` (esquema
2 con tablas de datos), con un proyecto mínimo (raíz, base y reloj simulado) y operaciones y
entradas escritas como lo hará ``core.provenance`` (T17, T20).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import dataset_tables as tables
from tests.support.core_fixtures import FakeClock
from tests.support.package import import_geoblender
from tests.support.provenance_readers import registered
from tests.unit.core.provenance.test_schema import RUNNING, input_row, operation_row

registry = import_geoblender("core.datasets.registry")
model = import_geoblender("core.datasets.model")
datasets = import_geoblender("core.datasets")
tracking = import_geoblender("core.datasets.tracking")
schema = import_geoblender("core.provenance.schema")
content = import_geoblender("core.content")
builtin = import_geoblender("core.content.builtin")
readers = import_geoblender("core.content.readers")
errors = import_geoblender("core.errors")
hashing = import_geoblender("core.hashing")
timeutil = import_geoblender("core.timeutil")

LAYER = tables.LAYER
SHARED = tables.SHARED
A = tables.INPUT_A
B = tables.INPUT_B
C = tables.INPUT_C
GPKG_READER = builtin.GPKG_LAYER.id
OP_1 = "00000000-0000-4000-8000-0000000001c1"
OP_2 = "00000000-0000-4000-8000-0000000001c2"
OP_3 = "00000000-0000-4000-8000-0000000001c3"
UNKNOWN = "00000000-0000-4000-8000-0000000001ff"
SHA_X = "a" * 64
DETAIL = {"elementos": ["P-02"], "vértices": 1}


@dataclass
class _Project:
    """Lo que el registro usa del proyecto: su raíz, su base y su reloj."""

    root: Path
    database_path: Path
    clock: FakeClock


def _equals(uid: str) -> dict[str, str]:
    return {"column": "input_uid", "equals": uid}


ACCUMULATED = {"column": "input_uid", "of": "current_inputs"}


def _insert(conn: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> None:
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values()))


def _layer(
    conn: sqlite3.Connection,
    path: Path,
    kind: str,
    layer: str,
    selector: Mapping[str, Any] | None = None,
) -> Any:
    """El ``ContentDigest`` de una tabla del proyecto con ``core.gpkg_layer@1`` y sin
    declaraciones, leída en la conexión (ve lo que aún no se ha confirmado)."""
    request = builtin.GPKG_LAYER.request(
        kind, {}, {"main": path}, {"layer": layer, "selector": selector}
    )
    for _ in builtin.layer_steps(conn, request):
        pass
    return request.hasher.digest()


def _spec(**changes: Any) -> Any:
    """Un dato derivado: la capa de límites del proyecto, escrita por una operación."""
    values: dict[str, Any] = {
        "name": "core_limites",
        "module": "core",
        "kind": "vector",
        "store": "gpkg",
        "locator": LAYER,
        "reader": GPKG_READER,
        "role": "boundary",
    }
    values.update(changes)
    positional = [values.pop(key) for key in ("name", "module", "kind", "store", "locator")]
    return model.DatasetSpec(*positional, **values)


def _imported(uid: str, name: str, *, role: str = "imported") -> Any:
    """Lo importado de la entrada ``uid`` en la tabla común: inmutable, con su selector."""
    return _spec(
        name=name, kind="table", locator=SHARED, selector=_equals(uid), input_uid=uid,
        immutable=True, role=role,
    )


def _accumulated() -> Any:
    """El dato acumulado de la tabla común: las filas de las entradas vigentes."""
    return _spec(name="core_ensayos", kind="table", locator=SHARED, selector=ACCUMULATED,
                 role="accumulated")


class RegistryCase(tables.DatasetTablesCase):
    """Una copia del GeoPackage por prueba como base de un proyecto en ``self.root``."""

    def setUp(self) -> None:
        super().setUp()
        self.root = self.path.parent
        self.project = _Project(self.root, self.path, FakeClock())

    # --- Escritura --------------------------------------------------------------------------

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.db.transaction() as conn:
            return work(conn)

    def begin(self, uid: str, *, supersedes: str | None = None, **changes: Any) -> None:
        """Una operación «en curso» (``core.provenance.begin_operation``, T17)."""
        row = operation_row(**{**RUNNING, "uid": uid, "supersedes_uid": supersedes,
                               **changes})
        self.write(lambda conn: _insert(conn, "gb_operation", row))

    def finish(self, uid: str) -> None:
        """La operación pasa a «hecha» (``complete``, T17)."""
        self.write(lambda conn: conn.execute(
            "UPDATE gb_operation SET status = 'done', finished_at = ? WHERE uid = ?",
            ("2026-10-08T10:00:00.000Z", uid),
        ))

    def add_input(self, uid: str, name: str, operation: str) -> None:
        """La entrada ``uid`` («Ensayos …»), importada por ``operation`` (T20)."""
        row = input_row(uid=uid, name=name, kind="table", layer=SHARED, operation_uid=operation)
        self.write(lambda conn: _insert(conn, "gb_input", row))

    def register(self, spec: Any, operation: str) -> Any:
        return self.write(lambda conn: registry.register_dataset(
            conn, self.project, spec, operation_uid=operation))

    def set_content(self, uid: str, spec: Any, operation: str) -> Any:
        return self.write(lambda conn: registry.set_content(
            conn, self.project, uid, spec, operation_uid=operation))

    # --- Lectura ----------------------------------------------------------------------------

    def snapshot(self) -> list[Any]:
        """Lo que el registro escribe: datos, cambios, salidas, disparadores y
        ``gpkg_contents``."""
        return [
            self.conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
            for table in ("gb_dataset", "gb_dataset_change", "gb_operation_io", "gb_input")
        ] + [
            self.conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY 1"
            ).fetchall(),
            self.conn.execute("SELECT * FROM gpkg_contents ORDER BY 1").fetchall(),
        ]

    def changes(self, uid: str) -> list[tuple[Any, ...]]:
        return self.conn.execute(
            "SELECT from_sha256, to_sha256, operation_uid, detail, at "
            "FROM gb_dataset_change WHERE dataset_uid = ? ORDER BY fid",
            (uid,),
        ).fetchall()

    def outputs(self, operation: str) -> list[tuple[Any, ...]]:
        return self.conn.execute(
            "SELECT item_kind, item_uid, content_sha256, role FROM gb_operation_io "
            "WHERE operation_uid = ? AND direction = 'out' ORDER BY fid",
            (operation,),
        ).fetchall()

    def assertRejected(self, code: str, work: Callable[[sqlite3.Connection], Any]) -> Any:
        """``work`` se rechaza con ``ValidationError`` ``code``, sin escribir nada y sin que
        SQLite falle (la transacción solo se deshace: el proyecto seguiría en escritura)."""
        before = self.snapshot()
        with self.assertRaises(errors.ValidationError) as caught:
            self.write(work)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.snapshot(), before)
        return caught.exception


class OperationRequiredTest(RegistryCase):
    """RF-008-17: un dato sin la operación (en curso) que escribió su contenido no se
    registra (D-2)."""

    def test_dataset_without_operation_is_rejected(self) -> None:
        """RF-008-17: sin operación, con una que no existe o con una ya terminada, el dato
        se rechaza nombrándolo, sin escribir nada; con su operación en curso, se registra."""
        self.begin(OP_1)
        self.begin(OP_2)
        self.finish(OP_2)
        spec = _spec()
        for operation in (None, "", "  "):
            error = self.assertRejected(
                "core.dataset_operation_missing",
                lambda conn, op=operation: registry.register_dataset(
                    conn, self.project, spec, operation_uid=op),
            )
            self.assertIn("core_limites", str(error))
        self.assertRejected(
            "core.dataset_operation_unknown",
            lambda conn: registry.register_dataset(
                conn, self.project, spec, operation_uid=UNKNOWN),
        )
        error = self.assertRejected(
            "core.dataset_operation_finished",
            lambda conn: registry.register_dataset(conn, self.project, spec, operation_uid=OP_2),
        )
        self.assertEqual(error.value, OP_2)
        record = self.register(spec, OP_1)
        self.assertEqual(record.operation_uid, OP_1)
        self.assertEqual(record.status, model.DatasetStatus.CURRENT)
        self.assertEqual(self.write(lambda conn: registry.get(conn, record.uid)), record)

    def test_set_content_needs_a_running_operation(self) -> None:
        """RF-008-17: un contenido nuevo también lleva la operación en curso que lo
        escribió."""
        self.begin(OP_1)
        record = self.register(_spec(), OP_1)
        self.finish(OP_1)
        for code, operation in (
            ("core.dataset_operation_missing", None),
            ("core.dataset_operation_unknown", UNKNOWN),
            ("core.dataset_operation_finished", OP_1),
        ):
            self.assertRejected(code, lambda conn, op=operation: registry.set_content(
                conn, self.project, record.uid, _spec(), operation_uid=op))


class TrackedTableTest(RegistryCase):
    """RF-008-17 y RF-008-21 (ADR-0025 §6): un dato de tabla queda seguido con lo que se
    anota tras la escritura, y cada contenido deja su cambio y su salida."""

    def test_table_is_tracked_after_writing(self) -> None:
        """RF-008-17: el dato queda con su nombre, módulo, tipo, ubicación, lector,
        normalizador y hash (``core.gpkg_layer@1``, ``gbch/1``, sin declaraciones), la
        operación que lo escribió, sus disparadores de seguimiento y el ``last_change`` y la
        huella del SQL de su tabla; un contenido nuevo anota el ``last_change`` que dejó su
        escritura, su fila de cambio con el detalle del módulo y su salida con su papel."""
        self.begin(OP_1)
        record = self.register(_spec(crs_epsg=25830, detail=DETAIL), OP_1)
        first = _layer(self.conn, self.path, "vector", LAYER)
        state = tracking.table_states(self.conn, [LAYER])[LAYER]
        self.assertTrue(state.tracked)
        self.assertEqual(
            (record.name, record.module, record.kind, record.store, record.locator),
            ("core_limites", "core", "vector", model.Store.GPKG, LAYER),
        )
        self.assertEqual((record.selector, record.selector_json), (None, ""))
        self.assertEqual((record.reader, record.normalizer), (GPKG_READER, "gbch/1"))
        self.assertEqual(record.content_sha256, first.content_sha256)
        self.assertEqual((record.crs_epsg, record.input_uid), (25830, None))
        self.assertEqual((record.immutable, record.qgis_editable, record.tracked),
                         (False, False, True))
        self.assertEqual(record.tracked_last_change, tables.OLD_CHANGE)
        self.assertEqual(record.tracked_last_change, state.last_change)
        self.assertEqual(record.tracked_schema_sha256, state.schema_sha256)
        self.assertEqual((record.tracked_size, record.tracked_mtime_ns), (None, None))
        now = timeutil.format_utc(self.project.clock.now())
        self.assertEqual((record.created_at, record.modified_at, record.checked_at),
                         (now, now, now))
        detail = hashing.canonical_json(DETAIL).decode("utf-8")
        self.assertEqual(self.changes(record.uid),
                         [(None, first.content_sha256, OP_1, detail, now)])
        self.assertEqual(self.outputs(OP_1),
                         [("dataset", record.uid, first.content_sha256, "boundary")])
        self.finish(OP_1)

        # Otra operación cambia un vértice: el disparador pone la hora en last_change.
        self.begin(OP_2)
        self.project.clock.advance(minutes=5)
        self.write(lambda conn: conn.execute(
            f"UPDATE {LAYER} SET tipo = 'exclusion' WHERE codigo = 'P-02'"))
        written = tables.last_change(self.conn, LAYER)
        self.assertNotEqual(written, tables.OLD_CHANGE)
        second = _layer(self.conn, self.path, "vector", LAYER)
        self.assertNotEqual(second.content_sha256, first.content_sha256)
        updated = self.set_content(record.uid, _spec(detail={"elementos": ["P-02"]}), OP_2)
        later = timeutil.format_utc(self.project.clock.now())
        self.assertEqual(updated.content_sha256, second.content_sha256)
        self.assertEqual(updated.operation_uid, OP_2)
        self.assertEqual(updated.tracked_last_change, written)
        self.assertEqual((updated.created_at, updated.modified_at, updated.checked_at),
                         (now, later, later))
        self.assertEqual(
            self.changes(record.uid)[1],
            (first.content_sha256, second.content_sha256, OP_2, '{"elementos":["P-02"]}',
             later),
        )
        self.assertEqual(self.outputs(OP_2),
                         [("dataset", record.uid, second.content_sha256, "boundary")])

        # Una escritura ajena (QGIS) cambia el last_change: el seguimiento la verá.
        self.qgis.execute(f"UPDATE {LAYER} SET tipo = 'concesion' WHERE codigo = 'P-03'")
        self.assertNotEqual(tables.last_change(self.conn, LAYER), written)

    def test_same_content_keeps_its_change_history(self) -> None:
        """RF-008-17: una operación que vuelve a escribir el mismo contenido pasa a ser la
        que lo escribió y lo anota como su salida, sin una fila de cambio (no es un contenido
        nuevo)."""
        self.begin(OP_1)
        record = self.register(_spec(), OP_1)
        self.finish(OP_1)
        self.begin(OP_2)
        again = self.set_content(record.uid, _spec(), OP_2)
        self.assertEqual(again.content_sha256, record.content_sha256)
        self.assertEqual(again.operation_uid, OP_2)
        self.assertEqual(len(self.changes(record.uid)), 1)
        self.assertEqual(self.outputs(OP_2),
                         [("dataset", record.uid, record.content_sha256, "boundary")])
        self.assertRejected(
            "core.dataset_written_twice",
            lambda conn: registry.set_content(
                conn, self.project, record.uid, _spec(), operation_uid=OP_2),
        )


class SetContentTest(RegistryCase):
    """RF-008-17 (ADR-0024 §6): el contenido nuevo de un dato se hashea con **su** lector y
    **su** normalizador."""

    def test_hash_uses_the_reader_and_normalizer_of_the_dataset(self) -> None:
        """RF-008-17 y ADR-0024 §6: un módulo que ya hashea con ``core.gpkg_layer@2`` y
        ``gbch/2`` escribe un contenido nuevo en un dato registrado con ``@1`` y ``gbch/1``:
        se guarda el hash de ``@1`` y ``gbch/1`` de lo escrito, y el dato conserva su lector
        y su normalizador."""
        self.begin(OP_1)
        record = self.register(_spec(), OP_1)
        self.finish(OP_1)
        self.begin(OP_2)
        self.write(lambda conn: conn.execute(f"DELETE FROM {LAYER} WHERE codigo = 'P-03'"))
        newer = content.ContentDigest(SHA_X, SHA_X, "gbch/2", "core.gpkg_layer@2")
        updated = self.set_content(
            record.uid, _spec(reader="core.gpkg_layer@2", content=newer), OP_2)
        expected = _layer(self.conn, self.path, "vector", LAYER)
        self.assertEqual(updated.content_sha256, expected.content_sha256)
        self.assertNotEqual(updated.content_sha256, record.content_sha256)
        self.assertEqual((updated.reader, updated.normalizer), (GPKG_READER, "gbch/1"))
        self.assertEqual(self.changes(record.uid)[1][1], expected.content_sha256)

    def test_digest_of_the_module_is_kept_with_the_same_versions(self) -> None:
        """RF-008-17 (ADR-0024 §1 y §6): el hash que da el módulo con el lector y el
        normalizador del dato se guarda tal cual (una malla de ``meshes/`` hasheada en su
        trabajo); uno con otro tipo o con declaraciones no es el de un dato y se rechaza; sin
        hash, el registro lee el fichero con el lector registrado. El fichero queda seguido
        por su tamaño y su fecha."""
        mesh = self.root / "meshes" / "core_malla.npz"
        mesh.parent.mkdir()
        vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.5]])
        np.savez(mesh, vertices=vertices, faces=np.array([[0, 1, 2]]),
                 meta=np.array('{"kind": "surface", "crs_epsg": 25830}'))
        with registered(builtin.NPZ_MESH):
            request = builtin.NPZ_MESH.request("mesh", {}, {"main": mesh})
            digest = content.read_content(builtin.NPZ_MESH, request)
            spec = _spec(name="core_malla", kind="mesh", store="meshes",
                         locator="meshes/core_malla.npz", reader=builtin.NPZ_MESH.id,
                         role="surface", content=digest)
            self.begin(OP_1)
            for code, wrong in (
                ("core.dataset_content_declared", content.ContentDigest(
                    digest.data_sha256,
                    content.content_sha256("mesh", {"crs_v": {"epsg": 5782}},
                                           digest.data_sha256),
                    digest.normalizer, digest.reader)),
                ("core.dataset_content_declared", content.ContentDigest(
                    digest.data_sha256,
                    content.content_sha256("raster", {}, digest.data_sha256),
                    digest.normalizer, digest.reader)),
            ):
                self.assertRejected(code, lambda conn, c=wrong: registry.register_dataset(
                    conn, self.project, _spec(**{**_mesh_fields(), "content": c}),
                    operation_uid=OP_1))
            with _counting(builtin.NPZ_MESH) as calls:
                record = self.register(spec, OP_1)
            self.assertEqual(calls, [])
            self.assertEqual(record.content_sha256, digest.content_sha256)
            stat = os.stat(mesh)
            self.assertEqual((record.tracked_size, record.tracked_mtime_ns),
                             (stat.st_size, stat.st_mtime_ns))
            self.assertEqual((record.tracked_last_change, record.tracked_schema_sha256),
                             (None, None))
            self.finish(OP_1)
            self.begin(OP_2)
            with _counting(builtin.NPZ_MESH) as calls:
                again = self.set_content(record.uid, _spec(**_mesh_fields()), OP_2)
            self.assertEqual(calls, [builtin.NPZ_MESH.id])
            self.assertEqual(again.content_sha256, digest.content_sha256)

    def test_identity_of_the_dataset_does_not_change(self) -> None:
        """RF-008-17: un contenido nuevo no cambia el nombre, el módulo, el tipo ni la
        ubicación del dato, y el dato tiene que existir."""
        self.begin(OP_1)
        record = self.register(_spec(), OP_1)
        self.finish(OP_1)
        self.begin(OP_2)
        for field, spec in (
            ("nombre", _spec(name="core_limites_2")),
            ("tipo", _spec(kind="table")),
            ("ubicación", _spec(locator=tables.OTHER)),
            ("entrada", _spec(input_uid=A)),
        ):
            error = self.assertRejected(
                "core.dataset_identity_changed",
                lambda conn, s=spec: registry.set_content(
                    conn, self.project, record.uid, s, operation_uid=OP_2),
            )
            self.assertEqual(error.field, field)
        self.assertRejected(
            "core.dataset_unknown",
            lambda conn: registry.set_content(conn, self.project, UNKNOWN, _spec(),
                                              operation_uid=OP_2),
        )


class ImmutableTest(RegistryCase):
    """RF-008-52: lo importado no admite contenido nuevo y su tabla queda protegida."""

    def test_imported_table_is_protected_and_rejects_new_content(self) -> None:
        """RF-008-52 (ADR-0025 §4): lo importado de una entrada se registra inmutable, con
        su entrada, y su tabla queda protegida para cualquier conexión con el nombre de la
        entrada; un contenido nuevo se rechaza sin escribir nada."""
        self.begin(OP_1)
        self.add_input(A, "Límites de la concesión", OP_1)
        spec = _spec(input_uid=A, immutable=True, role="imported")
        record = self.register(spec, OP_1)
        self.assertEqual((record.immutable, record.input_uid), (True, A))
        names = tracking.protection_trigger_names(LAYER)
        state = tracking.table_states(self.conn, [LAYER])[LAYER]
        self.assertTrue(set(names) <= state.triggers)
        self.assertTrue(state.tracked)
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            self.qgis.execute(f"UPDATE {LAYER} SET tipo = 'x'")
        self.assertEqual(
            str(caught.exception),
            f"{LAYER}: es lo importado de la entrada «Límites de la concesión»: no se modifica",
        )
        self.finish(OP_1)
        self.begin(OP_2)
        error = self.assertRejected(
            "core.dataset_immutable",
            lambda conn: registry.set_content(conn, self.project, record.uid, spec,
                                              operation_uid=OP_2),
        )
        self.assertIn("Límites de la concesión", str(error))

    def test_imported_needs_its_input(self) -> None:
        """RF-008-52: lo importado se registra con una entrada que existe."""
        self.begin(OP_1)
        self.assertRejected(
            "core.dataset_input_unknown",
            lambda conn: registry.register_dataset(
                conn, self.project, _spec(input_uid=A, immutable=True), operation_uid=OP_1),
        )
        with self.assertRaises(ValueError):
            _spec(immutable=True)


class AccumulatedTest(RegistryCase):
    """RF-008-52 y RF-005-11 (plan 008 §5.4.8, acumular; I-9): dos entradas que importan a
    una tabla común."""

    def setUp(self) -> None:
        super().setUp()
        self.write(lambda conn: conn.execute(f"DELETE FROM {SHARED}"))

    def import_rows(self, uid: str, rows: list[tuple[int, str, str, float, str]]) -> None:
        self.write(lambda conn: conn.executemany(
            f"INSERT INTO {SHARED} (fid, input_uid, codigo, ley, nota) VALUES (?, ?, ?, ?, ?)",
            rows,
        ))

    def test_two_inputs_leave_two_imported_and_one_accumulated(self) -> None:
        """RF-008-52: cada importación deja su dato importado (selector fijo, inmutable y
        con sus filas protegidas) y escribe el contenido del dato acumulado (selector de las
        entradas vigentes), que tras la segunda reúne las filas de las dos."""
        a_rows = [row for row in tables.SHARED_ROWS if row[1] == A]
        b_rows = [row for row in tables.SHARED_ROWS if row[1] == B]
        self.begin(OP_1)
        self.import_rows(A, a_rows)
        self.add_input(A, "Ensayos (entrega 1)", OP_1)
        imported_a = self.register(_imported(A, "core_ensayos_a"), OP_1)
        accumulated = self.register(_accumulated(), OP_1)
        first = _layer(self.conn, self.path, "table", SHARED, ACCUMULATED)
        self.assertEqual(accumulated.content_sha256, first.content_sha256)
        self.finish(OP_1)

        self.begin(OP_2)
        self.import_rows(B, b_rows)
        self.add_input(B, "Ensayos (entrega 2)", OP_2)
        imported_b = self.register(_imported(B, "core_ensayos_b"), OP_2)
        both = self.set_content(accumulated.uid, _accumulated(), OP_2)
        self.finish(OP_2)

        live = self.conn.execute(
            "SELECT name, selector, immutable, input_uid FROM gb_dataset ORDER BY name"
        ).fetchall()
        self.assertEqual(live, [
            ("core_ensayos", hashing.canonical_json(ACCUMULATED).decode(), 0, None),
            ("core_ensayos_a", hashing.canonical_json(_equals(A)).decode(), 1, A),
            ("core_ensayos_b", hashing.canonical_json(_equals(B)).decode(), 1, B),
        ])
        self.assertEqual(imported_a.content_sha256,
                         _layer(self.conn, self.path, "table", SHARED, _equals(A)).content_sha256)
        self.assertEqual(imported_b.content_sha256,
                         _layer(self.conn, self.path, "table", SHARED, _equals(B)).content_sha256)
        expected = _layer(self.conn, self.path, "table", SHARED, ACCUMULATED)
        self.assertEqual(both.content_sha256, expected.content_sha256)
        self.assertNotEqual(both.content_sha256, first.content_sha256)
        self.assertEqual(
            [(old, new, op) for old, new, op, _d, _at in self.changes(accumulated.uid)],
            [(None, first.content_sha256, OP_1),
             (first.content_sha256, both.content_sha256, OP_2)],
        )
        triggers = tracking.table_states(self.conn, [SHARED])[SHARED].triggers
        for uid in (A, B):
            self.assertTrue(set(tracking.protection_trigger_names(SHARED, _equals(uid)))
                            <= triggers)
        for uid, name in ((A, "Ensayos (entrega 1)"), (B, "Ensayos (entrega 2)")):
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                self.qgis.execute(f"UPDATE {SHARED} SET ley = 0 WHERE input_uid = ?", (uid,))
            self.assertIn(f"«{name}»", str(caught.exception))
        self.qgis.execute(f"INSERT INTO {SHARED} (input_uid, codigo, ley) VALUES (?, 'S-09', 1)",
                          (C,))


class SuccessorTest(RegistryCase):
    """RF-008-11 y RF-008-52 (plan 008 §5.4.4 y §5.4.8): el sucesor de un dato sustituido
    se resuelve por papel."""

    def import_input(self, operation: str, uid: str, version: int, *,
                     supersedes: str | None = None) -> tuple[Any, Any]:
        """Una importación de la entrada ``uid``: lo importado (papel ``imported``, con el
        nombre de siempre) y un resumen en ``blocks.duckdb`` (papel ``summary``)."""
        self.begin(operation, supersedes=supersedes)
        self.add_input(uid, f"Ensayos v{version}", operation)
        data = self.register(_imported(uid, "core_ensayos_importado"), operation)
        summary = self.register(_spec(
            name=f"core_resumen_v{version}", kind="table", store="duckdb",
            locator=f"bm_{version}", role="summary",
            content=content.ContentDigest(SHA_X, content.content_sha256("table", {}, SHA_X),
                                          "gbch/1", "core.duckdb_table@1"),
            reader="core.duckdb_table@1"), operation)
        return data, summary

    def supersede(self, uid: str) -> Any:
        return self.write(lambda conn: registry.supersede(conn, self.project, uid))

    def successor(self, uid: str) -> Any:
        return self.write(lambda conn: registry.successor(conn, uid))

    def test_successor_is_resolved_by_role(self) -> None:
        """RF-008-11 y RF-008-52: al actualizar dos veces una entrada, lo importado de cada
        una sigue en el proyecto (sustituido, con su nombre), y el sucesor de lo importado
        primero es, por papel, lo importado de la última (no su resumen); el de un dato vivo
        es él mismo y uno descartado no tiene."""
        data_1, summary_1 = self.import_input(OP_1, A, 1)
        self.finish(OP_1)
        self.supersede(data_1.uid)
        self.supersede(summary_1.uid)
        data_2, summary_2 = self.import_input(OP_2, B, 2, supersedes=OP_1)
        self.assertEqual(self.successor(data_1.uid).uid, data_2.uid)
        self.assertEqual(self.successor(summary_1.uid).uid, summary_2.uid)
        self.finish(OP_2)
        self.supersede(data_2.uid)
        data_3, _summary_3 = self.import_input(OP_3, C, 3, supersedes=OP_2)
        self.assertEqual(self.successor(data_1.uid).uid, data_3.uid)
        self.assertEqual(self.successor(data_3.uid).uid, data_3.uid)
        names = self.conn.execute(
            "SELECT name, status, superseded_by FROM gb_dataset "
            "WHERE name = 'core_ensayos_importado' ORDER BY fid"
        ).fetchall()
        self.assertEqual(names, [
            ("core_ensayos_importado", "superseded", None),
            ("core_ensayos_importado", "superseded", None),
            ("core_ensayos_importado", "current", None),
        ])
        found = self.write(lambda conn: registry.get(conn, "core_ensayos_importado"))
        self.assertEqual(found.uid, data_3.uid)
        self.assertEqual(self.write(lambda conn: registry.get(conn, data_1.uid)).status,
                         model.DatasetStatus.SUPERSEDED)
        self.write(lambda conn: registry.set_status(
            conn, self.project, data_3.uid, model.DatasetStatus.DISCARDED))
        self.assertIsNone(self.successor(data_1.uid))

    def test_explicit_successor_and_no_successor(self) -> None:
        """RF-008-11: un sucesor anotado manda sobre el papel; sin operación que sustituya a
        la suya ni anotación, un dato sustituido no tiene sucesor."""
        data_1, summary_1 = self.import_input(OP_1, A, 1)
        self.finish(OP_1)
        self.assertRejected(
            "core.dataset_successor_self",
            lambda conn: registry.supersede(conn, self.project, data_1.uid, by=data_1.uid),
        )
        self.write(lambda conn: registry.supersede(conn, self.project, data_1.uid,
                                                   by=summary_1.uid))
        self.assertEqual(self.successor(data_1.uid).uid, summary_1.uid)
        self.supersede(summary_1.uid)
        self.assertIsNone(self.successor(summary_1.uid))
        self.assertRejected(
            "core.dataset_not_live",
            lambda conn: registry.supersede(conn, self.project, summary_1.uid),
        )

    def test_discarded_has_no_successor(self) -> None:
        """RF-008-55: lo importado de una entrada descartada no tiene sucesor, aunque otra
        importación sustituya después a la suya."""
        data_1, _summary_1 = self.import_input(OP_1, A, 1)
        self.finish(OP_1)
        self.write(lambda conn: registry.set_status(
            conn, self.project, data_1.uid, model.DatasetStatus.DISCARDED))
        self.import_input(OP_2, B, 2, supersedes=OP_1)
        self.assertIsNone(self.successor(data_1.uid))

    def test_two_outputs_with_the_role_are_ambiguous(self) -> None:
        """RF-008-11: si la operación que la sustituye escribió dos datos con su papel, el
        sucesor no se adivina."""
        data_1, _summary_1 = self.import_input(OP_1, A, 1)
        self.finish(OP_1)
        self.supersede(data_1.uid)
        data_2, _summary_2 = self.import_input(OP_2, B, 2, supersedes=OP_1)
        self.add_input(C, "Ensayos v3", OP_2)
        self.register(_imported(C, "core_ensayos_otro"), OP_2)
        error = self.assertRejected(
            "core.dataset_successor_ambiguous",
            lambda conn: registry.successor(conn, data_1.uid),
        )
        self.assertEqual(error.value, OP_2)
        self.assertEqual(self.successor(data_2.uid).uid, data_2.uid)

    def test_two_superseding_operations_are_ambiguous(self) -> None:
        """RF-008-11: si dos operaciones en curso o hechas sustituyen a la misma, el sucesor
        no se adivina; una cancelada no cuenta."""
        data_1, _summary_1 = self.import_input(OP_1, A, 1)
        self.finish(OP_1)
        self.supersede(data_1.uid)
        data_2, _summary_2 = self.import_input(OP_2, B, 2, supersedes=OP_1)
        self.begin(OP_3, supersedes=OP_1, status="cancelled",
                   finished_at="2026-10-08T11:00:00.000Z")
        self.assertEqual(self.successor(data_1.uid).uid, data_2.uid)
        self.begin(UNKNOWN, supersedes=OP_1)
        error = self.assertRejected(
            "core.dataset_successor_ambiguous",
            lambda conn: registry.successor(conn, data_1.uid),
        )
        self.assertEqual(error.value, OP_1)


class UntrackedTest(RegistryCase):
    """RF-008-17 (ADR-0025 §6): ``exports`` y ``duckdb`` se registran sin seguimiento."""

    def test_exports_and_duckdb_are_not_tracked(self) -> None:
        """RF-008-17: un entregable de ``exports/`` (hasheado con ``core.document@1``) y un
        modelo de ``blocks.duckdb`` (con el hash de su módulo) quedan registrados con su
        operación y sin seguimiento: ni tamaño, ni fecha, ni ``last_change``, ni
        comprobación; ``duckdb`` sin hash no se puede leer aquí y se rechaza."""
        plan = self.root / "exports" / "core.r1" / "plano.pdf"
        plan.parent.mkdir(parents=True)
        plan.write_bytes(b"%PDF-1.4 plano\n")
        self.begin(OP_1)
        with registered(builtin.DOCUMENT):
            report = self.register(_spec(
                name="core_plano", kind="report", store="exports",
                locator="exports/core.r1/plano.pdf", reader=builtin.DOCUMENT.id,
                role="deliverable"), OP_1)
        request = builtin.DOCUMENT.request("report", {}, {"main": plan})
        self.assertEqual(report.content_sha256,
                         content.read_content(builtin.DOCUMENT, request).content_sha256)
        blocks = self.register(_spec(
            name="core_bloques", kind="block_model", store="duckdb", locator="bm_12",
            reader="core.duckdb_table@1", role="blocks",
            content=content.ContentDigest(
                SHA_X, content.content_sha256("block_model", {}, SHA_X), "gbch/1",
                "core.duckdb_table@1")), OP_1)
        for record in (report, blocks):
            self.assertFalse(record.tracked)
            self.assertEqual(
                (record.tracked_size, record.tracked_mtime_ns, record.tracked_last_change,
                 record.tracked_schema_sha256, record.checked_at),
                (None, None, None, None, None),
            )
            self.assertEqual(record.operation_uid, OP_1)
        self.assertRejected(
            "core.dataset_content_missing",
            lambda conn: registry.register_dataset(conn, self.project, _spec(
                name="core_bloques_2", kind="block_model", store="duckdb", locator="bm_13",
                reader="core.duckdb_table@1", role="blocks"), operation_uid=OP_1),
        )
        triggers = self.conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'gbtc%'"
        ).fetchone()[0]
        self.assertEqual(triggers, 0)


class RulesTest(RegistryCase):
    """RF-008-17 (plan 008 §5.2.1, D21; I-9): nombres, ubicaciones, estados y lo que se
    declara de un dato."""

    def test_live_name_and_location_are_unique(self) -> None:
        """RF-008-17: un nombre tiene como mucho un dato vivo y una ubicación no se reutiliza
        nunca (tampoco la de uno sustituido); se rechazan antes de escribir."""
        self.begin(OP_1)
        first = self.register(_spec(), OP_1)
        self.assertRejected(
            "core.dataset_name_taken",
            lambda conn: registry.register_dataset(
                conn, self.project, _spec(locator=tables.OTHER, kind="table"),
                operation_uid=OP_1),
        )
        self.write(lambda conn: registry.supersede(conn, self.project, first.uid))
        self.assertRejected(
            "core.dataset_location_taken",
            lambda conn: registry.register_dataset(
                conn, self.project, _spec(name="core_limites_2"), operation_uid=OP_1),
        )
        other = self.register(_spec(locator=tables.OTHER, kind="table"), OP_1)
        self.assertEqual(other.name, "core_limites")
        self.assertRejected(
            "core.dataset_table_reserved",
            lambda conn: registry.register_dataset(
                conn, self.project, _spec(name="core_x", locator="gb_dataset", kind="table"),
                operation_uid=OP_1),
        )

    def test_statuses(self) -> None:
        """RF-008-17, RF-008-21, RF-008-57 y RF-008-56: los seis estados son los del esquema
        y los vivos ocupan su nombre; un dato que falta, bloqueado o dañado vuelve a estar
        vigente con un contenido nuevo; sustituido y descartado son finales."""
        self.assertEqual(
            [str(status) for status in model.DatasetStatus],
            ["current", "superseded", "discarded", "missing", "blocked", "damaged"],
        )
        self.assertEqual(tuple(model.LIVE_STATUSES), schema.LIVE_DATASET_STATUSES)
        self.assertEqual(tuple(str(store) for store in model.Store),
                         ("gpkg", "rasters", "meshes", "duckdb", "originals", "exports"))
        self.assertEqual(model.UNTRACKED_STORES, (model.Store.DUCKDB, model.Store.EXPORTS))
        ddl = schema.TABLES["gb_dataset"]
        for status in model.DatasetStatus:
            self.assertIn(f"'{status}'", ddl)
        for kind in model.DATASET_KINDS:
            self.assertIn(f"'{kind}'", ddl)
        self.begin(OP_1)
        record = self.register(_spec(), OP_1)
        for status in ("missing", "blocked", "damaged"):
            changed = self.write(lambda conn, s=status: registry.set_status(
                conn, self.project, record.uid, model.DatasetStatus(s)))
            self.assertEqual(changed.status, status)
            self.assertTrue(changed.live)
        self.finish(OP_1)
        self.begin(OP_2)
        back = self.set_content(record.uid, _spec(), OP_2)
        self.assertEqual(back.status, model.DatasetStatus.CURRENT)
        with self.assertRaises(ValueError):
            self.write(lambda conn: registry.set_status(
                conn, self.project, record.uid, model.DatasetStatus.SUPERSEDED))
        self.write(lambda conn: registry.set_status(
            conn, self.project, record.uid, model.DatasetStatus.DISCARDED))
        self.assertRejected(
            "core.dataset_status_final",
            lambda conn: registry.set_status(conn, self.project, record.uid,
                                             model.DatasetStatus.CURRENT),
        )
        self.assertRejected(
            "core.dataset_not_live",
            lambda conn: registry.set_content(conn, self.project, record.uid, _spec(),
                                              operation_uid=OP_2),
        )
        self.assertIsNone(self.write(lambda conn: registry.get(conn, "core_limites")))

    def test_spec_is_checked_when_declared(self) -> None:
        """RF-008-17: un dato mal declarado por su módulo no llega a registrarse."""
        bad: tuple[tuple[type[Exception], dict[str, Any]], ...] = (
            (ValueError, {"name": ""}),
            (ValueError, {"name": "limites"}),
            (ValueError, {"name": "gis_limites"}),
            (ValueError, {"name": "core_Límites"}),
            (ValueError, {"module": "xyz", "name": "xyz_limites"}),
            (ValueError, {"kind": "surface"}),
            (ValueError, {"store": "cache"}),
            (ValueError, {"locator": ""}),
            (ValueError, {"store": "rasters", "locator": "/rasters/a.tif", "kind": "raster"}),
            (ValueError, {"store": "rasters", "locator": "rasters\\a.tif", "kind": "raster"}),
            (ValueError, {"store": "rasters", "locator": "meshes/a.npz", "kind": "raster"}),
            (ValueError, {"store": "rasters", "locator": "rasters/../a.tif", "kind": "raster"}),
            (ValueError, {"store": "rasters", "locator": "C:/rasters/a.tif", "kind": "raster"}),
            (ValueError, {"reader": "core.gpkg_layer"}),
            (ValueError, {"role": ""}),
            (ValueError, {"role": "Papel"}),
            (ValueError, {"selector": {"column": "input_uid"}}),
            (ValueError, {"selector": {"column": "input_uid", "equals": True}}),
            (ValueError, {"selector": {"column": "input_uid", "of": "all"}}),
            (ValueError, {"store": "rasters", "locator": "rasters/a.tif", "kind": "raster",
                          "selector": _equals(A)}),
            (ValueError, {"immutable": True, "input_uid": A, "selector": ACCUMULATED}),
            (ValueError, {"crs_epsg": 0}),
            (TypeError, {"crs_epsg": 25830.0}),
            (TypeError, {"immutable": 1}),
            (TypeError, {"content": "hash"}),
            (ValueError, {"content": content.ContentDigest(SHA_X, SHA_X, "gbch/1",
                                                           "core.otro@1")}),
            (TypeError, {"detail": {1, 2}}),
        )
        for kind, changes in bad:
            with self.subTest(changes=changes), self.assertRaises(kind):
                _spec(**changes)
        spec = _spec(store=model.Store.GPKG, selector="")
        self.assertEqual((spec.store, spec.selector, spec.selector_json, spec.tracked),
                         (model.Store.GPKG, None, "", True))
        self.assertEqual(_spec(selector=_equals(A)).selector_json,
                         '{"column":"input_uid","equals":"' + A + '"}')
        self.assertEqual(datasets.DatasetSpec, model.DatasetSpec)
        self.assertIs(datasets.register_dataset, registry.register_dataset)


def _mesh_fields() -> dict[str, Any]:
    return {"name": "core_malla", "kind": "mesh", "store": "meshes",
            "locator": "meshes/core_malla.npz", "reader": builtin.NPZ_MESH.id,
            "role": "surface"}


@contextmanager
def _counting(content_reader: Any) -> Iterator[list[str]]:
    """Mientras dura el bloque, el lector registrado ``content_reader`` apunta cada lectura
    (ya registrado; al salir, vuelve a estar el original)."""
    calls: list[str] = []
    original = content_reader.read

    def read(request: Any) -> Any:
        calls.append(request.reader)
        return original(request)

    readers.unregister_reader(content_reader.id)
    readers.register_reader(replace(content_reader, read=read))
    try:
        yield calls
    finally:
        readers.unregister_reader(content_reader.id)
        readers.register_reader(content_reader)
