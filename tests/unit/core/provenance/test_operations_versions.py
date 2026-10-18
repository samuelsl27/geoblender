# SPDX-License-Identifier: GPL-3.0-or-later
"""Operaciones de versión (spec 009, T07; RF-009-05, RF-009-04, RF-009-24, RF-009-01; plan 009
A3, D-14, D-19, D-27 y D-34).

``core.provenance.operations.begin_operation(…, version=)`` registra las operaciones según el
ámbito que declara su tipo (``OperationDef.scope``):

- una de **versión** necesita la versión activa (sin ella, ``core.version_required``: «Esta orden
  es de una versión: elija la versión activa o cree una (Proyecto ▸ Versiones)»), que tiene que
  existir y ser BORRADOR o VIGENTE (si no, ``core.version_not_editable`` con el texto de
  RF-009-04); se registra en su revisión abierta (``gb_operation.revision_uid``) y sus salidas
  son datos de esa versión (``gb_dataset.version_uid``; dos versiones pueden tener un dato con
  el mismo nombre). Consume datos del proyecto y datos vivos de su versión (por nombre, primero
  el de su versión) y, con ``Use(…, frozen=<revisión>)``, lo congelado en la revisión de la que
  parte su versión (RF-009-01, D-27), con el hash congelado; un dato de otra versión sin
  ``frozen``, o con otra revisión, alterada, que no lo congeló o con un dato del proyecto, se
  rechaza nombrando el dato y su versión;
- una de **proyecto** no consume ningún dato de una versión (``core.version_data_in_project``,
  D-14), lee los parámetros del proyecto y no se registra en ninguna revisión, aunque se le pase
  la versión activa;
- los parámetros que su módulo admite por versión se resuelven versión → proyecto, y
  ``gb_operation_param`` anota la fila, el ámbito y la revisión del historial que se usó
  (RF-009-24, D-19).

Además, el contrato de un tipo de operación gana ``reproduce`` y ``figure_tolerance``
(:class:`Tolerance`), comprobados al crearlo (RF-009-11, plan §5.3.3); ``core.versions.model``
da la ubicación de un dato de versión con el código de su versión (``version_locator``, D-34),
y ``core.datasets.registry.get`` busca un nombre en su ámbito (el proyecto, o una versión).

Cada prueba crea su proyecto sintético (esquema 3) con un reloj simulado, los tipos de prueba
de ``res`` (dos de proyecto y dos de versión), un parámetro de versión y otro del proyecto, el
dato del proyecto ``res_base`` y las versiones V01 y V02 en BORRADOR; las revisiones se congelan
con SQL (congelar es la T13), con lo congelado de cada una en ``gb_revision_item``.
"""

from __future__ import annotations

import math
import sqlite3
import unittest
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered, snapshot
from tests.unit.core.provenance.test_schema import dataset_row

create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
params = import_geoblender("core.params")
store_mod = import_geoblender("core.params.store")
provenance = import_geoblender("core.provenance")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
provenance_schema = import_geoblender("core.provenance.schema")
datasets = import_geoblender("core.datasets")
registry = import_geoblender("core.datasets.registry")
builtin = import_geoblender("core.content.builtin")
base = import_geoblender("core.gpkg.base")
versions_model = import_geoblender("core.versions.model")
versions_read = import_geoblender("core.versions.read")
versions_store = import_geoblender("core.versions.store")
timeutil = import_geoblender("core.timeutil")

SESSION = make_session()
USER = SESSION.user_host
NOW = "2026-10-18T10:00:00.000Z"
GPKG_READER = builtin.GPKG_LAYER.id

BENCH = "res.bench_height"
"""De versión (D-19): V01 tiene el suyo; el proyecto, el de por defecto."""
RECOVERY = "res.recovery"
"""Del proyecto: no admite versión."""
DEFINITIONS = (
    params.ParamDef(BENCH, "float", "m", 10.0, 0.0, 50.0, ("RF-009-24",),
                    "Prueba: altura de banco", min_exclusive=True, scope="version"),
    params.ParamDef(RECOVERY, "float", "-", 0.9, 0.0, 1.0, ("RF-009-24",),
                    "Prueba: recuperación minera"),
)

BASE = provenance.OperationDef("res.base", "1.0", "res", "Test base", False)
REPORT = provenance.OperationDef("res.report", "1.0", "res", "Test report", False)
PIT = provenance.OperationDef("res.pit", "1.0", "res", "Test pit", False, scope="version")
DESIGN = provenance.OperationDef("res.design", "1.0", "res", "Test design", False,
                                 scope="version")

REQUIRED = "Esta orden es de una versión: elija la versión activa o cree una (Proyecto ▸ Versiones)"
NOT_EDITABLE = "{code} está en estado {state}: cree una versión nueva a partir de ella"
"""El rechazo de RF-009-04 («V09 está en estado SUPERADO: cree una versión nueva a partir de
ella»)."""
IN_PROJECT = ("La operación de proyecto «res.report» no puede usar «res_pit» de V01: regístrelo "
              "como entrada del proyecto")
"""El rechazo de D-14 (plan A3: «La operación de proyecto «gis.resample» no puede usar
«des_final» de V10: regístrelo como entrada del proyecto»)."""
TABLES = ("gb_operation", "gb_operation_io", "gb_operation_param", "gb_parameter",
          "gb_parameter_history", "gb_dataset", "gb_dataset_change")


def _recompute(request: Any) -> Any:  # pragma: no cover - ninguna prueba recalcula
    raise AssertionError("no se recalcula en estas pruebas")


def _reproduce(request: Any) -> Any:  # pragma: no cover - ninguna prueba reproduce
    raise AssertionError("no se reproduce en estas pruebas")


def _write_table(conn: sqlite3.Connection, name: str, values: Sequence[float]) -> None:
    """La tabla ``name`` (``valor``) con ``values``: lo que escribe un módulo."""
    exists = conn.execute("SELECT 1 FROM gpkg_contents WHERE table_name = ?",
                          (name,)).fetchone()
    if exists is None:
        base.create_attribute_table(conn, name, [base.ColumnDef("valor", "DOUBLE")], name)
    conn.executemany(f'INSERT INTO "{name}" (valor) VALUES (?)', [(v,) for v in values])


def _spec(name: str, locator: str, role: str = "result") -> Any:
    return datasets.DatasetSpec(name, "res", "table", "gpkg", locator, reader=GPKG_READER,
                                role=role)


def _insert(conn: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> None:
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values()))


class ContractTest(unittest.TestCase):
    """Lo que no necesita un proyecto: el contrato, ``Use.frozen`` y las ubicaciones."""

    def test_reproduce_and_figure_tolerance(self) -> None:
        """RF-009-11 (plan §5.3.3): un tipo declara cómo se reproduce (``reproduce``) y la
        tolerancia de sus cifras (``figure_tolerance``, una :class:`Tolerance` relativa y
        absoluta, ≥ 0 y finitas; por defecto, exactas), comprobados al crearlo; la tolerancia
        solo la declara uno que se reproduce."""
        self.assertIs(provenance.Tolerance, contract.Tolerance)
        self.assertIn("Tolerance", provenance.__all__)
        plain = provenance.OperationDef("res.pit", "1.0", "res", "Test pit", False,
                                        scope="version")
        self.assertEqual((plain.reproduce, plain.figure_tolerance), (None, None))
        tolerance = provenance.Tolerance(relative=1e-12)
        declared = provenance.OperationDef(
            "res.pit_volume", "1.0", "res", "Test pit volume", True, recompute=_recompute,
            scope="version", reproduce=_reproduce, figure_tolerance=tolerance,
        )
        self.assertIs(declared.reproduce, _reproduce)
        self.assertEqual(declared.figure_tolerance, provenance.Tolerance(1e-12, 0.0))
        exact = provenance.Tolerance()
        self.assertEqual((exact.relative, exact.absolute), (0.0, 0.0))
        whole = provenance.Tolerance(absolute=1)
        self.assertEqual(whole.absolute, 1.0)
        self.assertIsInstance(whole.absolute, float)
        for bad in (-1e-9, math.nan, math.inf):
            for field in ("relative", "absolute"):
                with self.subTest(field=field, value=bad):
                    with self.assertRaises(ValueError):
                        provenance.Tolerance(**{field: bad})
        for bad_type in (True, "0.1", None):
            with self.subTest(value=bad_type):
                with self.assertRaises(TypeError):
                    provenance.Tolerance(relative=bad_type)
        with self.assertRaises(TypeError):
            provenance.OperationDef("res.pit", "1.0", "res", "Test pit", False,
                                    reproduce="no es una función")
        with self.assertRaises(TypeError):
            provenance.OperationDef("res.pit", "1.0", "res", "Test pit", False,
                                    reproduce=_reproduce, figure_tolerance=1e-12)
        with self.assertRaisesRegex(ValueError, "reproduce"):
            provenance.OperationDef("res.pit", "1.0", "res", "Test pit", False,
                                    figure_tolerance=tolerance)

    def test_frozen_use_and_version_locator(self) -> None:
        """RF-009-01, D-27, D-34: ``Use.frozen`` es la revisión congelada (un texto no vacío) de
        la que se toma un **dato** (una entrada es del proyecto); la ubicación de un dato de
        versión lleva el código de su versión antes de la extensión (``des_final_v10.tif``,
        ``des_string_v10``)."""
        use = operations.Use("res_pit", "pit", frozen="r1")
        self.assertEqual((use.item, use.role, use.kind, use.frozen),
                         ("res_pit", "pit", operations.ItemKind.DATASET, "r1"))
        self.assertIsNone(operations.Use("res_pit", "pit").frozen)
        with self.assertRaises(ValueError):
            operations.Use("res_pit", "pit", frozen=" ")
        with self.assertRaises(TypeError):
            operations.Use("res_pit", "pit", frozen=1)
        with self.assertRaises(ValueError):
            operations.Use("Limites_v1", "boundary", kind="input", frozen="r1")
        locator = versions_model.version_locator
        self.assertEqual(locator("rasters/des_final.tif", "V10"), "rasters/des_final_v10.tif")
        self.assertEqual(locator("des_string", "V10"), "des_string_v10")
        self.assertEqual(locator("meshes/a.b/pit.npz", "V100"), "meshes/a.b/pit_v100.npz")
        self.assertEqual(locator("rasters/des", "V01"), "rasters/des_v01")
        for bad_code in ("10", "v10", "V1", "V01 ", ""):
            with self.subTest(code=bad_code):
                with self.assertRaises(ValueError):
                    locator("des_string", bad_code)
        for bad_locator in ("", " des", "rasters/"):
            with self.subTest(locator=bad_locator):
                with self.assertRaises(ValueError):
                    locator(bad_locator, "V10")
        with self.assertRaises(TypeError):
            locator(None, "V10")

    def test_get_in_a_schema_2_database(self) -> None:
        """RF-009-02 (lo que ya existe sigue igual): en un proyecto del esquema 2 abierto en
        solo lectura (``gb_dataset`` sin ``version_uid``), ``get`` sigue encontrando un dato por
        su nombre y por su uid."""
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute(provenance_schema.TABLES["gb_dataset"])
        self.assertNotIn("version_uid",
                         {row[1] for row in conn.execute("PRAGMA table_info(gb_dataset)")})
        row = dataset_row()
        _insert(conn, "gb_dataset", row)
        self.assertEqual(registry.get(conn, row["name"]).uid, row["uid"])
        self.assertEqual(registry.get(conn, row["uid"]).name, row["name"])
        self.assertIsNone(registry.get(conn, "core_otro"))


class VersionOperationsCase(unittest.TestCase):
    """Un proyecto nuevo por prueba (``self.project``) con los tipos de prueba registrados, el
    dato del proyecto ``self.base`` (``res_base``, de ``res.base``) y las versiones ``self.v1``
    (V01) y ``self.v2`` (V02) en BORRADOR."""

    def setUp(self) -> None:
        before = snapshot()
        self.addCleanup(lambda: self.assertEqual(snapshot(), before))
        params.register_definitions(DEFINITIONS)
        self.addCleanup(params.unregister_definitions, "res")
        self.enterContext(registered(BASE, REPORT, PIT, DESIGN))
        tmp = self.enterContext(project_tmp("gb-t07-"))
        parent = tmp / "proyectos"
        parent.mkdir()
        self.clock = FakeClock()
        self.project = create.create_project(
            parent, make_settings(), SESSION, userdata_mod.UserData(tmp / "u"), clock=self.clock
        ).project
        self.addCleanup(self.project.close)
        self.store = store_mod.ParameterStore(self.project)
        (self.base,) = self.run_op("res.base", None, [("res_base", "res_base")], (1.0, 2.0))
        self.v1 = self.new_version("definitiva", "Definitiva")
        self.v2 = self.new_version("ampliacion", "Ampliación")

    # Ayudas -------------------------------------------------------------------------------

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.project.write_transaction() as conn:
            return work(conn)

    def query(self, sql: str, args: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, tuple(args)).fetchall()

    def tick(self) -> None:
        self.clock.advance(minutes=1)

    def new_version(self, feature: str, title: str, parent: str | None = None) -> Any:
        self.tick()
        version, _ = self.write(lambda conn: versions_store.create_version(
            conn, self.project, feature=feature, title=title, reason="Prueba", parent=parent))
        return version

    def begin(self, op_type: str, version: str | None, **kw: Any) -> Any:
        values: dict[str, Any] = {"settings": {}, "executor": "blender", "version": version}
        values.update(kw)
        self.tick()
        return operations.begin_operation(self.project, op_type, **values)

    def run_op(self, op_type: str, version: str | None, outputs: Sequence[tuple[str, str]],
               values: Sequence[float] = (1.0,), **kw: Any) -> tuple[Any, ...]:
        """Una operación hecha que escribe cada tabla de ``outputs`` (nombre, ubicación) con
        ``values`` y devuelve sus datos registrados."""
        handle = self.begin(op_type, version, **kw)

        def work(conn: sqlite3.Connection) -> Any:
            for _name, locator in outputs:
                _write_table(conn, locator, values)
            return handle.complete(conn, outputs=[_spec(name, locator)
                                                  for name, locator in outputs])

        return self.write(work)

    def open_revision(self, version: Any) -> Any:
        with self.project.read() as conn:
            return versions_read.open_revision(conn, version.uid)

    def freeze(self, version: Any, items: Sequence[tuple[Any, str]] = ()) -> str:
        """Congela con SQL la revisión abierta de ``version`` con lo congelado de ``items``
        (cada dato con su parte), abre la siguiente y devuelve el uid de la congelada."""

        def work(conn: sqlite3.Connection) -> str:
            uid, number = conn.execute(
                "SELECT uid, number FROM gb_revision WHERE version_uid = ? AND state = 'open'",
                (version.uid,),
            ).fetchone()
            folder = f"snapshots/{version.code}.r{number}"
            conn.execute(
                "UPDATE gb_revision SET state = 'frozen', closed_at = ?, closed_by = ?, "
                "snapshot_dir = ?, snapshot_sha256 = ?, snapshot_bytes = 0, "
                "geoblender_version = ? WHERE uid = ?",
                (NOW, USER, folder, "a" * 64, "0.1.0", uid),
            )
            for record, part in items:
                copied = part != "upstream"
                _insert(conn, "gb_revision_item", {
                    "revision_uid": uid, "item_kind": "dataset", "item_uid": record.uid,
                    "part": part, "content_sha256": record.content_sha256,
                    "copied": int(copied),
                    "snapshot_path": f"{folder}/{version.code}.r{number}.gpkg" if copied
                    else None,
                    "snapshot_layer": record.locator if copied else None,
                })
            _insert(conn, "gb_revision", {
                "uid": f"{uid}-siguiente", "version_uid": version.uid, "number": number + 1,
                "state": "open", "reason": "Siguiente", "created_at": NOW, "created_by": USER,
            })
            return str(uid)

        return self.write(work)

    def set_status(self, version: Any, target: str, reason: str | None = None) -> None:
        self.tick()
        self.write(lambda conn: versions_store.set_status(conn, self.project, version.uid,
                                                          target, reason=reason))

    def dump(self) -> dict[str, list[tuple[Any, ...]]]:
        with self.project.read() as conn:
            return {table: conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
                    for table in TABLES}

    def operation(self, uid: str) -> dict[str, Any]:
        with self.project.read() as conn:
            cursor = conn.execute("SELECT * FROM gb_operation WHERE uid = ?", (uid,))
            names = [column[0] for column in cursor.description]
            return dict(zip(names, cursor.fetchone(), strict=True))

    def consumed(self, uid: str) -> list[tuple[Any, ...]]:
        return self.query("SELECT item_kind, item_uid, content_sha256, role FROM "
                          "gb_operation_io WHERE operation_uid = ? AND direction = 'in' "
                          "ORDER BY fid", (uid,))

    def read_params(self, uid: str) -> list[tuple[Any, ...]]:
        return self.query("SELECT key, parameter_uid, scope, rev, value FROM gb_operation_param "
                          "WHERE operation_uid = ? ORDER BY key", (uid,))

    def version_of(self, *uids: str) -> dict[str, str]:
        with self.project.read() as conn:
            return versions_read.dataset_versions(conn, uids)

    def assertRejected(self, *cases: tuple[str, str | None, Callable[[sqlite3.Connection], Any]]
                       ) -> list[Any]:
        """Cada caso (código, texto o ``None``, trabajo) se rechaza con su código y su texto
        **antes de escribir nada**: en una sola transacción, y al final nada ha cambiado y el
        proyecto sigue en escritura (un rechazo no es un fallo de la base)."""
        before = self.dump()
        found: list[Any] = []
        with self.project.write_transaction() as conn:
            for code, text, work in cases:
                with self.subTest(code=code, text=text):
                    with self.assertRaises(versions_model.VersionError) as caught:
                        work(conn)
                    self.assertEqual(caught.exception.code, code, str(caught.exception))
                    if text is not None:
                        self.assertEqual(str(caught.exception), text)
                    found.append(caught.exception)
        self.assertTrue(self.project.writable)
        self.assertEqual(self.dump(), before)
        return found

    def begin_in(self, conn: sqlite3.Connection, op_type: str, version: str | None,
                 **kw: Any) -> Any:
        values: dict[str, Any] = {"settings": {}, "executor": "blender", "version": version}
        values.update(kw)
        return operations.begin_in_transaction(conn, self.project, op_type, **values)


class RegisterTest(VersionOperationsCase):
    def test_version_operation_in_its_open_revision(self) -> None:
        """RF-009-05, RF-009-24, D-19, D-34: una operación de versión se registra en la
        revisión abierta de su versión (por uid o por código), lee los parámetros que su módulo
        admite por versión con el valor de la versión si lo tiene y si no con el del proyecto
        (``gb_operation_param`` anota la fila, el ámbito y la revisión del historial), y sus
        salidas son datos de su versión: dos versiones tienen un dato con el mismo nombre, cada
        una el suyo, y escribirlo otra vez en V01 cambia el de V01 y no el de V02."""
        own = self.write(lambda conn: self.store.create(
            conn, BENCH, 12.0, kind="HIPÓTESIS", source="Diseño de V01", source_kind="document",
            decided_by="Samuel (IMGA)", reason="Banco de 12 m en V01", version=self.v1.uid))
        r1 = self.open_revision(self.v1)
        handle = self.begin("res.pit", "V01", inputs=[operations.Use("res_base", "base")],
                            params=[BENCH, RECOVERY])
        self.assertEqual((handle.version_uid, handle.revision_uid), (self.v1.uid, r1.uid))
        row = self.operation(handle.uid)
        self.assertEqual((row["scope"], row["revision_uid"], row["status"]),
                         ("version", r1.uid, "running"))
        self.assertEqual(self.consumed(handle.uid),
                         [("dataset", self.base.uid, self.base.content_sha256, "base")])
        project_bench = self.store.get(BENCH)
        project_recovery = self.store.get(RECOVERY)
        self.assertEqual((project_bench.value, project_bench.unconfirmed), (10.0, True))
        self.assertEqual(self.read_params(handle.uid), [
            (BENCH, own.uid, "version", 1, "12.0"),
            (RECOVERY, project_recovery.uid, "project", 1, "0.9"),
        ])
        self.assertEqual([(p.key, p.scope, p.scope_uid, p.rev) for p in handle.params],
                         [(BENCH, "version", self.v1.uid, 1), (RECOVERY, "project", "", 1)])

        locator = versions_model.version_locator("res_pit", "V01")
        self.assertEqual(locator, "res_pit_v01")

        def work(conn: sqlite3.Connection) -> Any:
            _write_table(conn, locator, (5.0,))
            return handle.complete(conn, outputs=[_spec("res_pit", locator)])

        (pit1,) = self.write(work)
        # En V02, sin valor propio, el banco es el del proyecto; su «res_pit» es otro dato.
        handle2 = self.begin("res.pit", self.v2.uid, params=[BENCH])
        self.assertEqual(self.read_params(handle2.uid),
                         [(BENCH, project_bench.uid, "project", 1, "10.0")])
        self.assertEqual(self.operation(handle2.uid)["revision_uid"],
                         self.open_revision(self.v2).uid)

        def work2(conn: sqlite3.Connection) -> Any:
            _write_table(conn, "res_pit_v02", (6.0,))
            return handle2.complete(conn, outputs=[_spec("res_pit", "res_pit_v02")])

        (pit2,) = self.write(work2)
        self.assertNotEqual(pit1.uid, pit2.uid)
        self.assertEqual(self.version_of(pit1.uid, pit2.uid, self.base.uid, "otro"),
                         {pit1.uid: self.v1.uid, pit2.uid: self.v2.uid, self.base.uid: ""})
        # Otra vez en V01: el contenido nuevo es del dato de V01, no del de V02.
        (again,) = self.run_op("res.pit", self.v1.uid, [("res_pit", locator)], (7.0, 8.0))
        self.assertEqual(again.uid, pit1.uid)
        self.assertNotEqual(again.content_sha256, pit1.content_sha256)
        with self.project.read() as conn:
            self.assertEqual(registry.get(conn, pit2.uid).content_sha256, pit2.content_sha256)
            self.assertEqual(registry.get(conn, "res_pit", version_uid=self.v1.uid).uid,
                             pit1.uid)
            self.assertEqual(registry.get(conn, "res_pit", version_uid=self.v2.uid).uid,
                             pit2.uid)
            self.assertIsNone(registry.get(conn, "res_pit"))  # el proyecto no tiene ninguno
        # Varias de una vez (spec 005, T55), todas en la revisión abierta de V01.
        handles = operations.begin_operations(self.project, "res.pit",
                                              settings=[{"n": 1}, {"n": 2}],
                                              executor="blender", version="V01")
        self.assertEqual([self.operation(h.uid)["revision_uid"] for h in handles],
                         [r1.uid, r1.uid])

    def test_project_operation_ignores_the_active_version(self) -> None:
        """RF-009-05, D-14, D-19: una operación de proyecto no se registra en ninguna revisión
        aunque se le pase la versión activa, y lee el parámetro del proyecto aunque la versión
        tenga el suyo; el ámbito es el que declara su tipo."""
        self.write(lambda conn: self.store.create(
            conn, BENCH, 12.0, kind="HIPÓTESIS", source="Diseño de V01", source_kind="document",
            decided_by="Samuel (IMGA)", reason="Banco de 12 m en V01", version=self.v1.uid))
        handle = self.begin("res.report", self.v1.uid, inputs=[operations.Use("res_base", "base")],
                            params=[BENCH])
        row = self.operation(handle.uid)
        self.assertEqual((row["scope"], row["revision_uid"]), ("project", ""))
        self.assertEqual((handle.version_uid, handle.revision_uid), ("", ""))
        project_bench = self.store.get(BENCH)
        self.assertEqual(self.read_params(handle.uid),
                         [(BENCH, project_bench.uid, "project", 1, "10.0")])

    def test_names_by_scope(self) -> None:
        """RF-009-05 (§8 de la spec: «Dos versiones con un dato del mismo nombre»), D-34: un
        nombre se busca en su ámbito: el dato del proyecto y el de V01 con el mismo nombre son
        dos; una operación de V01 consume el suyo, una de V02 (que no lo tiene) el del
        proyecto y una de proyecto el del proyecto, que es también al que escribe; ``get`` sin
        versión es el del proyecto."""
        (shared,) = self.run_op("res.base", None, [("res_shared", "res_shared")], (1.0,))
        (own,) = self.run_op("res.pit", "V01", [("res_shared", "res_shared_v01")], (2.0,))
        self.assertNotEqual(shared.uid, own.uid)
        uses = [operations.Use("res_shared", "shared")]
        in_v1 = self.begin("res.design", "V01", inputs=uses)
        in_v2 = self.begin("res.design", "V02", inputs=uses)
        in_project = self.begin("res.report", None, inputs=uses)
        self.assertEqual([self.consumed(h.uid)[0][1] for h in (in_v1, in_v2, in_project)],
                         [own.uid, shared.uid, shared.uid])
        (rewritten,) = self.run_op("res.base", None, [("res_shared", "res_shared")], (3.0,))
        self.assertEqual(rewritten.uid, shared.uid)
        with self.project.read() as conn:
            self.assertEqual(registry.get(conn, "res_shared").uid, shared.uid)
            self.assertEqual(registry.get(conn, "res_shared", version_uid="").uid, shared.uid)
            self.assertEqual(registry.get(conn, "res_shared", version_uid=self.v1.uid).uid,
                             own.uid)
            self.assertEqual(registry.get(conn, "res_shared", version_uid=self.v1.uid
                                          ).content_sha256, own.content_sha256)
            self.assertIsNone(registry.get(conn, "res_shared", version_uid=self.v2.uid))


class RejectTest(VersionOperationsCase):
    def test_version_required_unknown_and_not_editable(self) -> None:
        """RF-009-05, RF-009-04: una operación de versión sin versión activa se rechaza con
        «Esta orden es de una versión: elija la versión activa o cree una (Proyecto ▸
        Versiones)»; con una que no existe, ``core.version_unknown``; con una SUPERADO o
        DESCARTADO, «V01 está en estado SUPERADO: cree una versión nueva a partir de ella»;
        siempre sin escribir nada (tampoco el parámetro por defecto)."""
        for empty in (None, "", "  "):
            with self.subTest(version=empty):
                before = self.dump()
                with self.assertRaises(versions_model.VersionError) as caught:
                    self.begin("res.pit", empty, params=[BENCH])
                self.assertEqual(caught.exception.code, "core.version_required")
                self.assertEqual(str(caught.exception), REQUIRED)
                self.assertEqual(versions_model.render("core.version_required", language="en"),
                                 "This command belongs to a version: choose the active version "
                                 "or create one (Project ▸ Versions)")
                self.assertEqual(self.dump(), before)
        with self.assertRaises(TypeError):
            self.begin("res.pit", 1)
        self.freeze(self.v1)
        self.set_status(self.v1, "VIGENTE")
        self.freeze(self.v2)
        self.set_status(self.v2, "VIGENTE")  # V01 pasa a SUPERADO
        v3 = self.new_version("descartada", "Descartada")
        self.set_status(v3, "DESCARTADO", "No sirve")
        self.assertRejected(
            ("core.version_unknown", "No hay ninguna versión V09 en el proyecto",
             lambda conn: self.begin_in(conn, "res.pit", "V09", params=[BENCH])),
            ("core.version_not_editable", NOT_EDITABLE.format(code="V01", state="SUPERADO"),
             lambda conn: self.begin_in(conn, "res.pit", self.v1.uid, params=[BENCH])),
            ("core.version_not_editable", NOT_EDITABLE.format(code="V03", state="DESCARTADO"),
             lambda conn: self.begin_in(conn, "res.pit", "V03", params=[BENCH])),
        )
        with self.assertRaises(versions_model.VersionError) as caught:
            self.begin("res.pit", "V01")
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        # La VIGENTE sí admite operaciones de versión, en su revisión abierta.
        handle = self.begin("res.pit", "V02")
        self.assertEqual(self.operation(handle.uid)["revision_uid"],
                         self.open_revision(self.v2).uid)

    def test_project_operation_with_version_data(self) -> None:
        """RF-009-05, D-14: una operación de proyecto que consume un dato de una versión (por
        su nombre, por su uid o congelado) se rechaza nombrando el dato y su versión («La
        operación de proyecto «res.report» no puede usar «res_pit» de V01: regístrelo como
        entrada del proyecto»), sin escribir nada."""
        (pit,) = self.run_op("res.pit", "V01", [("res_pit", "res_pit_v01")])
        r1 = self.freeze(self.v1, [(pit, "produced")])
        self.assertRejected(*(
            ("core.version_data_in_project", IN_PROJECT,
             lambda conn, use=use: self.begin_in(conn, "res.report", None, inputs=[use]))
            for use in (operations.Use("res_pit", "pit"), operations.Use(pit.uid, "pit"),
                        operations.Use("res_pit", "pit", frozen=r1))
        ))
        error = versions_model.VersionError(
            "core.version_data_in_project", field="entradas", op_type="res.report",
            dataset="res_pit", version="V01")
        self.assertEqual(versions_model.render(error.code, language="en", **error.values),
                         "The project operation «res.report» cannot use «res_pit» of V01: "
                         "register it as a project input")


class FrozenTest(VersionOperationsCase):
    """V01 escribe ``res_pit`` en r1 y la congela (con ``res_base`` aguas arriba); en r2 lo
    cambia y escribe ``res_extra``; V03 parte de V01 (de V01.r1)."""

    def setUp(self) -> None:
        super().setUp()
        (self.pit,) = self.run_op("res.pit", "V01", [("res_pit", "res_pit_v01")], (1.0,))
        self.r1 = self.freeze(self.v1, [(self.pit, "produced"), (self.base, "upstream")])
        (self.changed,) = self.run_op("res.pit", "V01", [("res_pit", "res_pit_v01")], (9.0,))
        (self.extra,) = self.run_op("res.pit", "V01", [("res_extra", "res_extra_v01")])
        self.v3 = self.new_version("desde_v01", "Desde V01", parent=self.v1.uid)

    def test_frozen_from_its_parent_revision(self) -> None:
        """RF-009-01, D-27: una versión que parte de V01 consume lo congelado en V01.r1 (por
        nombre o por uid) con el hash congelado, no con el que tiene ahora en V01; además, los
        datos del proyecto, como cualquier operación."""
        self.assertEqual(self.v3.parent_revision_uid, self.r1)
        self.assertEqual(self.changed.uid, self.pit.uid)
        self.assertNotEqual(self.changed.content_sha256, self.pit.content_sha256)
        for item in ("res_pit", self.pit.uid):
            with self.subTest(item=item):
                handle = self.begin("res.design", "V03", inputs=[
                    operations.Use(item, "pit", frozen=self.r1),
                    operations.Use("res_base", "base"),
                ])
                self.assertEqual(self.consumed(handle.uid), [
                    ("dataset", self.pit.uid, self.pit.content_sha256, "pit"),
                    ("dataset", self.base.uid, self.base.content_sha256, "base"),
                ])
                self.assertEqual([(c.uid, c.content_sha256, c.frozen) for c in handle.inputs],
                                 [(self.pit.uid, self.pit.content_sha256, self.r1),
                                  (self.base.uid, self.base.content_sha256, None)])
                self.assertEqual(self.operation(handle.uid)["revision_uid"],
                                 self.open_revision(self.v3).uid)

    def test_other_version_rejected(self) -> None:
        """RF-009-01, RF-009-05, D-27: un dato de otra versión sin ``frozen``, con una revisión
        que no es la de la que parte su versión (la abierta de V01, o en V02, que no parte de
        ninguna), uno que esa revisión no congeló, uno del proyecto o una revisión alterada se
        rechazan nombrando el dato y la versión o la revisión, sin escribir nada."""
        r2 = self.open_revision(self.v1).uid
        other = ("La operación «res.design» de V03 no puede usar «res_pit» de V01: de otra "
                 "versión solo se usa lo congelado en la revisión de la que parte")
        self.assertRejected(
            ("core.version_data_other", other,
             lambda conn: self.begin_in(conn, "res.design", "V03",
                                        inputs=[operations.Use("res_pit", "pit")])),
            ("core.version_data_other", other,
             lambda conn: self.begin_in(conn, "res.design", "V03",
                                        inputs=[operations.Use(self.pit.uid, "pit")])),
            ("core.version_frozen_not_parent",
             "V03 solo puede tomar lo congelado en la revisión de la que parte (V01.r1), no "
             "«res_pit» de V01.r2",
             lambda conn: self.begin_in(conn, "res.design", "V03",
                                        inputs=[operations.Use("res_pit", "pit", frozen=r2)])),
            ("core.version_frozen_not_parent",
             "V02 solo puede tomar lo congelado en la revisión de la que parte (—), no "
             "«res_pit» de V01.r1",
             lambda conn: self.begin_in(conn, "res.design", "V02", inputs=[
                 operations.Use("res_pit", "pit", frozen=self.r1)])),
            ("core.version_frozen_not_parent",
             "V03 solo puede tomar lo congelado en la revisión de la que parte (V01.r1), no "
             "«res_pit» de no-existe",
             lambda conn: self.begin_in(conn, "res.design", "V03", inputs=[
                 operations.Use("res_pit", "pit", frozen="no-existe")])),
            ("core.version_frozen_missing", "«res_extra» no está congelado en V01.r1",
             lambda conn: self.begin_in(conn, "res.design", "V03", inputs=[
                 operations.Use("res_extra", "extra", frozen=self.r1)])),
            ("core.version_frozen_project",
             "«res_base» es del proyecto: se usa su contenido vigente, no el congelado en V01.r1",
             lambda conn: self.begin_in(conn, "res.design", "V03", inputs=[
                 operations.Use("res_base", "base", frozen=self.r1)])),
        )
        self.write(lambda conn: conn.execute(
            "UPDATE gb_revision SET altered_at = ?, altered_detail = ? WHERE uid = ?",
            (NOW, '{"files":["V01.r1.gpkg"]}', self.r1)))
        self.assertRejected(
            ("core.version_frozen_altered",
             "La revisión V01.r1 está alterada: no se usa lo congelado en ella («res_pit»)",
             lambda conn: self.begin_in(conn, "res.design", "V03", inputs=[
                 operations.Use("res_pit", "pit", frozen=self.r1)])),
        )

    def test_queries_use_their_indexes(self) -> None:
        """Plan §2.1 (trampa §6): las consultas nuevas sobre ``gb_dataset`` por nombre y sobre
        ``gb_revision_item`` usan sus índices (``EXPLAIN QUERY PLAN`` sin recorrer la tabla)."""
        statements: list[str] = []
        with self.project.write_transaction() as conn:
            conn.set_trace_callback(statements.append)
            try:
                self.begin_in(conn, "res.design", "V03", inputs=[
                    operations.Use("res_pit", "pit", frozen=self.r1),
                    operations.Use("res_base", "base")])
                registry.get(conn, "res_base")
                with self.assertRaises(versions_model.VersionError):  # de otra versión
                    self.begin_in(conn, "res.design", "V03",
                                  inputs=[operations.Use("res_extra", "extra")])
            finally:
                conn.set_trace_callback(None)
            new = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")
                   and ("gb_revision_item" in sql or "version_uid" in sql)]
            self.assertTrue(any("gb_revision_item" in sql for sql in new), statements)
            self.assertTrue(any("FROM gb_dataset WHERE version_uid" in sql for sql in new),
                            statements)
            self.assertTrue(any("FROM gb_version AS v WHERE EXISTS" in sql for sql in new),
                            statements)
            for sql in new:
                with self.subTest(sql=sql):
                    plan = [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")]
                    self.assertFalse(
                        [step for step in plan if step.startswith("SCAN")
                         and ("gb_dataset" in step or "gb_revision_item" in step
                              or step.split()[1] in ("d", "i"))],
                        plan,
                    )


if __name__ == "__main__":
    unittest.main()
