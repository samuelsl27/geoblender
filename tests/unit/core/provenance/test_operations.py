# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de las operaciones en dos pasos (spec 008, T17; RF-008-04, RF-008-05,
RF-008-18, RF-008-23, RF-008-51; ADR-0025 §3; plan 008 §5.3.1 y §5.4.7).

``core.provenance.operations`` registra cada operación que produce resultados:

- ``begin_operation`` la deja «en curso» antes de ejecutarla, en su propia transacción, con su
  tipo y la versión de su algoritmo, sus ajustes, los parámetros resueltos (los que el proyecto
  no tenía, registrados por defecto «sin confirmar» en esa misma transacción), cada dato o
  entrada que consume con su hash de contenido y su papel, quién, cuándo y desde qué sesión
  (RF-008-04, RF-008-05, RF-008-51);
- ``OperationHandle.complete`` la termina en la transacción del módulo, la que escribe sus
  resultados: «hecha», sus salidas con hash y papel, las versiones de las bibliotecas que
  influyen en sus cifras, dónde se ejecutó y en qué equipo (RF-008-18); si esa transacción se
  deshace, no queda nada de la operación terminada; un resultado que no está guardado en el
  proyecto no se acepta (RF-008-23);
- ``OperationHandle.claim_paths`` reclama los ficheros que escribe, que constan mientras la
  operación está en curso (``claimed_paths``; ADR-0025 §3);
- ``operation()`` hace lo mismo en el hilo de Blender como gestor de contexto: si el bloque
  falla o termina sin completar el registro, la operación queda fallida.

Cada prueba crea su proyecto sintético (esquema 2) con un reloj simulado, registra los
parámetros y los tipos de operación de prueba de ``res`` y los quita al acabar.
"""

from __future__ import annotations

import ast
import datetime as dt
import os
import sqlite3
import unittest
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.support.core_fixtures import (
    CLOCK_START,
    FakeClock,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered, snapshot
from tests.unit.core.provenance.test_schema import input_row

create = import_geoblender("core.project.create")
project_model = import_geoblender("core.project.model")
userdata_mod = import_geoblender("core.userdata")
params = import_geoblender("core.params")
store_mod = import_geoblender("core.params.store")
provenance = import_geoblender("core.provenance")
operations = import_geoblender("core.provenance.operations")
schema = import_geoblender("core.provenance.schema")
datasets = import_geoblender("core.datasets")
content = import_geoblender("core.content")
builtin = import_geoblender("core.content.builtin")
base = import_geoblender("core.gpkg.base")
errors = import_geoblender("core.errors")
hashing = import_geoblender("core.hashing")
timeutil = import_geoblender("core.timeutil")

SESSION = make_session()
GPKG_READER = builtin.GPKG_LAYER.id
MESH_READER = builtin.NPZ_MESH.id
INPUT_UID = "00000000-0000-4000-8000-0000000001e1"
UNKNOWN_UID = "00000000-0000-4000-8000-0000000001ff"
SOFTWARE = {"numpy": "2.3.4"}
INTERPRETER = {"kind": "compute", "python": "3.13.13", "numpy": "2.3.4", "blas": "openblas",
               "lock_id": "motor-1"}

SWELL = params.ParamDef(
    "res.swell_factor", "float", "-", 1.15, 1.0, 2.0, ("RF-008-04",),
    "Prueba: K de esponjamiento sin ensayo", kind="HIPÓTESIS", source_kind="document",
)
RECOVERY = params.ParamDef(
    "res.recovery", "float", "-", 0.9, 0.0, 1.0, ("RF-008-05",), "Prueba: recuperación minera",
)


def _recompute(request: Any) -> Any:  # pragma: no cover - ninguna prueba recalcula
    raise AssertionError("no se recalcula en estas pruebas")


SURVEY = provenance.OperationDef("res.survey", "1.0", "res", "Test survey", False)
BALANCE = provenance.OperationDef(
    "res.balance", "1.2", "res", "Test balance", True, recompute=_recompute,
    libraries=("numpy",),
)
PHASE_A = provenance.OperationDef("res.phase_a", "1.0", "res", "Test phase A", False,
                                  group="res.phases")
PHASE_B = provenance.OperationDef("res.phase_b", "1.0", "res", "Test phase B", False,
                                  group="res.phases")
PHASES = provenance.CoupledGroupDef("res.phases", ("res.phase_a", "res.phase_b"))

TABLES = (
    "gb_operation",
    "gb_operation_io",
    "gb_operation_param",
    "gb_parameter",
    "gb_parameter_history",
    "gb_dataset",
    "gb_dataset_change",
    "gb_input",
)


def _now(minutes: int = 0) -> str:
    return timeutil.format_utc(CLOCK_START + dt.timedelta(minutes=minutes))


def _json(value: object) -> str:
    return hashing.canonical_json(value).decode("utf-8")


def _insert(conn: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> None:
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values()))


def _table_spec(name: str, role: str) -> Any:
    """Una tabla de resultados de ``res`` en ``project.gpkg`` (hash calculado al registrarla)."""
    return datasets.DatasetSpec(name, "res", "table", "gpkg", name, reader=GPKG_READER,
                                role=role)


def _mesh_digest(label: str) -> Any:
    data = hashing.sha256_bytes(label.encode("utf-8"))
    return content.ContentDigest(
        data, content.content_sha256("mesh", {}, data, normalizer=content.NORMALIZER),
        content.NORMALIZER, MESH_READER,
    )


def _mesh_spec(name: str, role: str, label: str = "malla") -> Any:
    """Una malla de ``meshes/`` con el hash que da el módulo."""
    return datasets.DatasetSpec(name, "res", "mesh", "meshes", f"meshes/{name}.npz",
                                reader=MESH_READER, role=role, content=_mesh_digest(label))


def _write_table(conn: sqlite3.Connection, name: str, values: Sequence[float]) -> None:
    """La tabla ``name`` (``valor``) con ``values``: lo que escribe un módulo."""
    exists = conn.execute(
        "SELECT 1 FROM gpkg_contents WHERE table_name = ?", (name,)
    ).fetchone()
    if exists is None:
        base.create_attribute_table(conn, name, [base.ColumnDef("valor", "DOUBLE")], name)
    conn.executemany(f'INSERT INTO "{name}" (valor) VALUES (?)', [(v,) for v in values])


class _Abort(Exception):
    """Un fallo del módulo después de completar, dentro de su transacción."""


class OperationsCase(unittest.TestCase):
    """Un proyecto nuevo por prueba con las definiciones y los tipos de prueba de ``res``."""

    def setUp(self) -> None:
        before = snapshot()
        self.addCleanup(lambda: self.assertEqual(snapshot(), before))
        params.register_definitions((SWELL, RECOVERY))
        self.addCleanup(params.unregister_definitions, "res")
        self.enterContext(registered(SURVEY, BALANCE, PHASE_A, PHASE_B, PHASES))
        tmp = self.enterContext(project_tmp("gb-t17-"))
        parent = tmp / "proyectos"
        parent.mkdir()
        self.tmp = tmp
        self.clock = FakeClock()
        self.project = create.create_project(
            parent, make_settings(), SESSION, userdata_mod.UserData(tmp / "u"), clock=self.clock
        ).project
        self.addCleanup(self.project.close)
        self.store = store_mod.ParameterStore(self.project)

    # --- Ayudas -----------------------------------------------------------------------------

    def tick(self) -> None:
        self.clock.advance(minutes=1)

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.project.write_transaction() as conn:
            return work(conn)

    def query(self, sql: str, args: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, tuple(args)).fetchall()

    def row(self, uid: str) -> dict[str, Any]:
        with self.project.read() as conn:
            cursor = conn.execute("SELECT * FROM gb_operation WHERE uid = ?", (uid,))
            names = [column[0] for column in cursor.description]
            found = cursor.fetchone()
        self.assertIsNotNone(found, uid)
        return dict(zip(names, found, strict=True))

    def status(self, uid: str) -> str:
        return self.row(uid)["status"]

    def snapshot(self) -> list[Any]:
        """Todo lo que registra la procedencia y las tablas de datos del proyecto."""
        with self.project.read() as conn:
            return [
                conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
                for table in TABLES
            ] + [conn.execute("SELECT table_name FROM gpkg_contents ORDER BY 1").fetchall()]

    def assertRejected(self, error: type[BaseException], code: str | None,
                       work: Callable[[], Any]) -> BaseException:
        """``work`` se rechaza sin escribir nada y el proyecto sigue en escritura."""
        before = self.snapshot()
        with self.assertRaises(error) as caught:
            work()
        if code is not None:
            self.assertEqual(getattr(caught.exception, "code", None), code,
                             str(caught.exception))
        self.assertTrue(self.project.writable)
        self.assertEqual(self.snapshot(), before)
        return caught.exception

    def begin(self, op_type: str = "res.balance", **kw: Any) -> Any:
        values: dict[str, Any] = {"settings": {}, "executor": "blender"}
        values.update(kw)
        return operations.begin_operation(self.project, op_type, **values)

    def survey(self, values: Sequence[float] = (1.0, 2.0)) -> tuple[Any, Any]:
        """Una operación hecha («res.survey») que escribe la tabla ``res_terreno``."""
        handle = self.begin("res.survey", settings={"origen": "levantamiento"})

        def work(conn: sqlite3.Connection) -> Any:
            _write_table(conn, "res_terreno", values)
            return handle.complete(conn, outputs=[_table_spec("res_terreno", "terrain")])

        (record,) = self.write(work)
        return handle, record

    def add_input(self, operation_uid: str) -> None:
        """La entrada «Limites_v1», importada por ``operation_uid``."""
        row = input_row(uid=INPUT_UID, operation_uid=operation_uid)
        self.write(lambda conn: _insert(conn, "gb_input", row))


class BeginTest(OperationsCase):
    def test_running_with_params_inputs_and_who(self) -> None:
        """RF-008-51, RF-008-05, RF-008-04: al empezar queda «en curso» con su tipo y la
        versión de su algoritmo, sus ajustes, los parámetros resueltos (el que faltaba,
        registrado por defecto «sin confirmar»), cada dato y entrada con su hash y su papel,
        quién, cuándo y desde qué sesión; aún sin salidas ni final."""
        survey, terrain = self.survey()
        self.add_input(survey.uid)
        self.write(lambda conn: self.store.create(
            conn, "res.recovery", 0.92, kind="ADOPTADO", source="Plan de labores 2026",
            source_kind="document", decided_by="La propiedad", reason="Recuperación del plan",
        ))
        self.tick()
        self.assertIsNone(self.store.get("res.swell_factor"))
        settings = {"banco": 10, "método": "lerchs", "fases": [1, 2]}
        handle = self.begin(
            settings=settings,
            inputs=[operations.Use("res_terreno", "terrain"),
                    operations.Use("Limites_v1", "boundary", kind="input")],
            params=["res.swell_factor", "res.recovery"],
        )
        row = self.row(handle.uid)
        started = _now(1)
        self.assertEqual(
            {name: row[name] for name in (
                "op_type", "op_version", "module", "scope", "repeatable", "group_name",
                "group_uid", "settings", "settings_sha256", "status", "status_reason",
                "supersedes_uid", "superseded_by", "geoblender_version", "software",
                "executor", "job_uid", "interpreter", "user_host", "host", "session_uid",
                "started_at", "finished_at", "message")},
            {
                "op_type": "res.balance", "op_version": "1.2", "module": "res",
                "scope": "project", "repeatable": 1, "group_name": None, "group_uid": None,
                "settings": _json(settings),
                "settings_sha256": hashing.sha256_bytes(hashing.canonical_json(settings)),
                "status": "running", "status_reason": None, "supersedes_uid": None,
                "superseded_by": None, "geoblender_version": "0.1.0", "software": "{}",
                "executor": "blender", "job_uid": None, "interpreter": None,
                "user_host": "prueba@PC-PRUEBA-A", "host": "PC-PRUEBA-A",
                "session_uid": SESSION.session_uid, "started_at": started,
                "finished_at": None, "message": None,
            },
        )
        self.assertEqual((handle.op_type, handle.started_at, handle.executor),
                         ("res.balance", started, "blender"))
        self.assertEqual(
            self.query("SELECT direction, item_kind, item_uid, content_sha256, role "
                       "FROM gb_operation_io WHERE operation_uid = ? ORDER BY fid",
                       (handle.uid,)),
            [("in", "dataset", terrain.uid, terrain.content_sha256, "terrain"),
             ("in", "input", INPUT_UID, input_row()["content_sha256"], "boundary")],
        )
        self.assertEqual([(use.kind, use.uid, use.role) for use in handle.inputs],
                         [("dataset", terrain.uid, "terrain"), ("input", INPUT_UID, "boundary")])
        # El K que faltaba: registrado por defecto, «sin confirmar», al empezar.
        swell = self.store.get("res.swell_factor")
        self.assertEqual(
            (swell.value, swell.kind, swell.unconfirmed, swell.decided_by, swell.source,
             swell.created_at),
            (1.15, "HIPÓTESIS", True, "Geoblender (valor por defecto)",
             "valor por defecto de Geoblender 0.1.0", started),
        )
        self.assertEqual([entry.action for entry in self.store.history("res.swell_factor")],
                         ["default"])
        recovery = self.store.get("res.recovery")
        self.assertEqual(
            self.query("SELECT parameter_uid, key, scope, rev, value, unit, kind, unconfirmed, "
                       "value_sha256 FROM gb_operation_param WHERE operation_uid = ? "
                       "ORDER BY fid", (handle.uid,)),
            [(swell.uid, "res.swell_factor", "project", 1, "1.15", "-", "HIPÓTESIS", 1,
              swell.value_sha256),
             (recovery.uid, "res.recovery", "project", 1, "0.92", "-", "ADOPTADO", 0,
              recovery.value_sha256)],
        )
        self.assertEqual([(p.key, p.rev, p.unconfirmed) for p in handle.params],
                         [("res.swell_factor", 1, True), ("res.recovery", 1, False)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_operation_io WHERE "
                                    "operation_uid = ? AND direction = 'out'", (handle.uid,)),
                         [(0,)])

    def test_by_uid_and_coupled_group(self) -> None:
        """RF-008-51: un dato se consume también por su uid (el mismo, con dos papeles); una
        operación de un grupo acoplado sin ejecución del grupo abre una (``group_uid``
        nuevo) y la siguiente del grupo la reutiliza."""
        _survey, terrain = self.survey()
        first = self.begin("res.phase_a", inputs=[operations.Use(terrain.uid, "terrain"),
                                                  operations.Use("res_terreno", "limits")])
        second = self.begin("res.phase_b", group_uid=first.group_uid)
        self.assertRegex(first.group_uid, r"^[0-9a-f-]{36}$")
        self.assertEqual(
            [(self.row(h.uid)["group_name"], self.row(h.uid)["group_uid"])
             for h in (first, second)],
            [("res.phases", first.group_uid)] * 2,
        )
        self.assertEqual(
            self.query("SELECT item_uid, role FROM gb_operation_io WHERE operation_uid = ? "
                       "ORDER BY fid", (first.uid,)),
            [(terrain.uid, "terrain"), (terrain.uid, "limits")],
        )

    def test_rejections_write_nothing(self) -> None:
        """RF-008-51, RF-008-04: lo que no se puede empezar se rechaza sin escribir nada
        (tampoco el parámetro por defecto, que va en la misma transacción) y el proyecto
        sigue en escritura."""
        survey, terrain = self.survey()
        need = {"params": ["res.swell_factor"]}
        self.assertRejected(provenance.ProvenanceError, "core.operation_unregistered",
                            lambda: self.begin("res.nothing", **need))
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_dataset_unknown",
            lambda: self.begin(inputs=[operations.Use("res_nada", "terrain")], **need))
        error = self.assertRejected(
            provenance.ProvenanceError, "core.operation_input_unknown",
            lambda: self.begin(inputs=[operations.Use(UNKNOWN_UID, "boundary", kind="input")],
                               **need))
        self.assertEqual(
            str(error),
            f"La operación «res.balance» consume la entrada «{UNKNOWN_UID}», que no está "
            "registrada en el proyecto.",
        )
        self.assertRejected(params.ParamError, "core.param_undefined",
                            lambda: self.begin(params=["res.swell_factor", "res.nothing"]))
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_supersedes_unknown",
            lambda: self.begin(supersedes=UNKNOWN_UID, **need))
        for bad in (
            {"executor": "gpu"},
            {"executor": "blender", "job_uid": "j-1"},
            {"group_uid": "g-1"},
            {"settings": ["no", "es", "un", "diccionario"]},
            {"settings": {"fuente": "C:\\Datos\\cliente\\limites.gpkg"}},
            {"inputs": [operations.Use("res_terreno", "terrain"),
                        operations.Use(terrain.uid, "terrain")]},
            {"params": ["res.swell_factor", "res.swell_factor"]},
        ):
            with self.subTest(bad=bad):
                self.assertRejected((ValueError, TypeError), None,
                                    lambda bad=bad: self.begin(**{**need, **bad}))
        self.assertEqual(self.status(survey.uid), "done")
        before = self.snapshot()
        self.project.set_read_only(project_model.ReadOnlyCode.LOCKED,
                                   "otra sesión lo tiene en escritura")
        with self.assertRaises(provenance.ProvenanceError) as caught:
            self.begin(**need)
        self.assertEqual(caught.exception.code, "core.read_only")
        self.assertEqual(
            str(caught.exception),
            "El proyecto «Cantera Prueba» está abierto en solo lectura (otra sesión lo tiene "
            "en escritura): no se ha registrado nada.",
        )
        self.assertEqual(self.snapshot(), before)

    def test_history_is_not_consumed(self) -> None:
        """RF-008-51: lo sustituido o descartado queda como historia y no se consume, ni un
        dato ni una entrada."""
        survey, terrain = self.survey()
        self.add_input(survey.uid)
        self.write(lambda conn: datasets.supersede(conn, self.project, terrain.uid))
        self.write(lambda conn: conn.execute(
            "UPDATE gb_input SET status = 'discarded', status_reason = 'prueba' WHERE uid = ?",
            (INPUT_UID,)))
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_dataset_not_live",
            lambda: self.begin(inputs=[operations.Use(terrain.uid, "terrain")]))
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_input_not_live",
            lambda: self.begin(inputs=[operations.Use(INPUT_UID, "boundary", kind="input")]))


class CompleteTest(OperationsCase):
    def test_done_with_outputs_versions_and_executor(self) -> None:
        """RF-008-18, RF-008-17: ``complete`` deja en la transacción del módulo, y sin
        confirmarla, el estado «hecha», cada salida con su hash y su papel, las versiones del
        algoritmo, de Geoblender y de las bibliotecas, el ejecutor con su trabajo y el
        equipo."""
        handle = self.begin(executor="job_process", params=["res.recovery"])
        self.tick()
        mesh = Path(self.project.root, "meshes", "res_malla.npz")
        mesh.parent.mkdir(exist_ok=True)
        mesh.write_bytes(b"malla sintetica")
        uri = self.project.database_path.as_uri() + "?mode=ro"

        def work(conn: sqlite3.Connection) -> Any:
            _write_table(conn, "res_resultado", (3.5, 4.25))
            records = handle.complete(
                conn,
                outputs=[_table_spec("res_resultado", "summary"),
                         _mesh_spec("res_malla", "surface")],
                software=SOFTWARE, interpreter=INTERPRETER, job_uid="job-0001",
                message="Balance de prueba",
            )
            other = sqlite3.connect(uri, uri=True)
            try:  # nada se ve fuera de la transacción del módulo hasta que se confirma
                seen = other.execute("SELECT status FROM gb_operation WHERE uid = ?",
                                     (handle.uid,)).fetchone()
            finally:
                other.close()
            self.assertEqual(seen, ("running",))
            return records

        table, surface = self.write(work)
        row = self.row(handle.uid)
        finished = _now(1)
        self.assertEqual(
            {name: row[name] for name in (
                "status", "finished_at", "op_version", "geoblender_version", "software",
                "executor", "job_uid", "interpreter", "host", "user_host", "message")},
            {"status": "done", "finished_at": finished, "op_version": "1.2",
             "geoblender_version": "0.1.0", "software": _json(SOFTWARE),
             "executor": "job_process", "job_uid": "job-0001",
             "interpreter": _json(INTERPRETER), "host": "PC-PRUEBA-A",
             "user_host": "prueba@PC-PRUEBA-A", "message": "Balance de prueba"},
        )
        self.assertEqual(
            self.query("SELECT item_kind, item_uid, content_sha256, role FROM gb_operation_io "
                       "WHERE operation_uid = ? AND direction = 'out' ORDER BY fid",
                       (handle.uid,)),
            [("dataset", table.uid, table.content_sha256, "summary"),
             ("dataset", surface.uid, _mesh_digest("malla").content_sha256, "surface")],
        )
        self.assertEqual(
            self.query("SELECT name, operation_uid, status FROM gb_dataset ORDER BY fid"),
            [("res_resultado", handle.uid, "current"), ("res_malla", handle.uid, "current")],
        )
        self.assertEqual(len(table.content_sha256), 64)
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_not_running",
            lambda: self.write(lambda conn: handle.complete(conn, software=SOFTWARE)))

    def test_module_rollback_leaves_nothing(self) -> None:
        """RF-008-18: si la transacción del módulo se deshace después de ``complete``, no
        queda nada de la operación terminada (ni salidas, ni datos, ni sus filas) y la
        operación sigue en curso, con sus rutas reclamadas; luego se completa bien."""
        _survey, terrain = self.survey()
        handle = self.begin(inputs=[operations.Use("res_terreno", "terrain")])
        handle.claim_paths("rasters/res_tmp.tif")
        before = self.snapshot()

        def work(conn: sqlite3.Connection) -> None:
            _write_table(conn, "res_resultado", (1.0,))
            handle.complete(conn, outputs=[_table_spec("res_resultado", "summary")],
                            software=SOFTWARE)
            raise _Abort("el módulo falla al escribir su informe")

        with self.assertRaises(_Abort):
            self.write(work)
        self.assertTrue(self.project.writable)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.status(handle.uid), "running")
        self.assertEqual(operations.claimed_paths(self.project),
                         {Path(self.project.root, "rasters", "res_tmp.tif")})

        def again(conn: sqlite3.Connection) -> Any:
            _write_table(conn, "res_resultado", (1.0,))
            return handle.complete(conn, outputs=[_table_spec("res_resultado", "summary")],
                                   software=SOFTWARE)

        (record,) = self.write(again)
        self.assertEqual(self.status(handle.uid), "done")
        self.assertEqual(record.operation_uid, handle.uid)
        self.assertEqual(datasets.get(self._conn(), "res_terreno").uid, terrain.uid)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.project.database_path.as_uri() + "?mode=ro", uri=True)
        self.addCleanup(conn.close)
        return conn

    def test_result_not_saved_is_rejected(self) -> None:
        """RF-008-23: un resultado que no está guardado en el proyecto (un fichero que solo
        está en la caché o en la carpeta de un trabajo, una tabla que no se escribió) no se
        acepta: nada se registra y la operación sigue en curso."""
        handle = self.begin()
        cached = self.project.cache_dir() / "meshes" / "res_malla.npz"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"solo en la cache")
        for spec in (_mesh_spec("res_malla", "surface"), _table_spec("res_fantasma", "summary")):
            with self.subTest(spec=spec.name):
                error = self.assertRejected(
                    provenance.ProvenanceError, "core.operation_output_not_saved",
                    lambda spec=spec: self.write(lambda conn: handle.complete(
                        conn, outputs=[spec], software=SOFTWARE)))
                self.assertIn(f"«{spec.name}»", str(error))
                self.assertIn("«res.balance»", str(error))
        self.assertEqual(self.status(handle.uid), "running")

    def test_rejections(self) -> None:
        """RF-008-18: las bibliotecas que influyen son las declaradas, todas y solas; un
        trabajo lleva su identificador; ``complete`` va dentro de la transacción del
        módulo; una salida no se repite. Nada se escribe y la operación sigue en curso."""
        handle = self.begin()
        for kw in (
            {"software": None},
            {"software": {}},
            {"software": {"numpy": "2.3.4", "scipy": "1.16"}},
            {"software": {"numpy": ""}},
            {"software": SOFTWARE, "executor": "job_thread"},
            {"software": SOFTWARE, "executor": "blender", "job_uid": "job-1"},
            {"software": SOFTWARE, "interpreter": {"exe": "C:\\Blender\\python.exe"}},
            {"software": SOFTWARE, "outputs": [_table_spec("res_terreno", "a"),
                                               _table_spec("res_terreno", "b")]},
        ):
            with self.subTest(kw=kw):
                self.assertRejected((ValueError, TypeError), None,
                                    lambda kw=kw: self.write(lambda conn: handle.complete(
                                        conn, **kw)))
        with self.project.read() as conn, self.assertRaises(ValueError):
            handle.complete(conn, software=SOFTWARE)
        self.assertEqual(self.status(handle.uid), "running")

    def test_supersedes(self) -> None:
        """RF-008-18: una operación que sustituye a otra hecha (un recálculo) escribe el
        contenido nuevo del mismo dato y, al completarse, la anota en la sustituida; una
        operación ya sustituida, o que otra en curso sustituye, no se vuelve a sustituir, y
        solo se sustituye una hecha."""
        survey, terrain = self.survey((1.0, 2.0))
        running = self.begin("res.survey")
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_supersedes_not_done",
            lambda: self.begin("res.survey", supersedes=running.uid))
        again = self.begin("res.survey", supersedes=survey.uid)
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_already_superseded",
            lambda: self.begin("res.survey", supersedes=survey.uid))

        def work(conn: sqlite3.Connection) -> Any:
            conn.execute('DELETE FROM "res_terreno"')
            _write_table(conn, "res_terreno", (1.0, 2.5))
            return again.complete(conn, outputs=[_table_spec("res_terreno", "terrain")])

        (record,) = self.write(work)
        self.assertEqual(record.uid, terrain.uid)
        self.assertNotEqual(record.content_sha256, terrain.content_sha256)
        self.assertEqual(self.row(survey.uid)["superseded_by"], again.uid)
        self.assertEqual(self.row(again.uid)["supersedes_uid"], survey.uid)
        self.assertEqual(
            self.query("SELECT from_sha256, to_sha256, operation_uid FROM gb_dataset_change "
                       "ORDER BY fid"),
            [(None, terrain.content_sha256, survey.uid),
             (terrain.content_sha256, record.content_sha256, again.uid)],
        )
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_already_superseded",
            lambda: self.begin("res.survey", supersedes=survey.uid))


class ClaimsTest(OperationsCase):
    def test_claimed_while_running(self) -> None:
        """ADR-0025 §3, RF-008-51: las rutas que reclama una operación (relativas a la raíz
        del proyecto o absolutas dentro de él) constan mientras está en curso y dejan de
        constar al completarse; una ruta fuera del proyecto no se reclama."""
        root = self.project.root
        first = self.begin()
        second = self.begin("res.survey")
        first.claim_paths("rasters/res_dtm.tif.tmp-abcd", root / "rasters" / "res_dtm.tif")
        second.claim_paths(os.path.join(root, "meshes", "res_malla.npz"))
        for outside in (self.tmp / "fuera.tif", "../fuera.tif", Path(root.anchor, "x.tif")):
            with self.subTest(outside=outside), self.assertRaises(ValueError):
                first.claim_paths(outside)
        with self.assertRaises(TypeError):
            first.claim_paths(b"rasters/x.tif")
        self.assertEqual(
            operations.claimed_paths(self.project),
            {root / "rasters" / "res_dtm.tif.tmp-abcd", root / "rasters" / "res_dtm.tif",
             root / "meshes" / "res_malla.npz"},
        )
        self.assertEqual(first.claims, {root / "rasters" / "res_dtm.tif.tmp-abcd",
                                         root / "rasters" / "res_dtm.tif"})

        def work(conn: sqlite3.Connection) -> None:
            _write_table(conn, "res_terreno", (1.0,))
            second.complete(conn, outputs=[_table_spec("res_terreno", "terrain")])

        self.write(work)
        with self.project.read() as conn:
            self.assertEqual(operations.claimed_paths(self.project, conn=conn),
                             first.claims)


class ContextManagerTest(OperationsCase):
    def test_done_failed_and_not_completed(self) -> None:
        """RF-008-18, RF-008-23: ``operation()`` empieza en el hilo de Blender y se completa
        en la transacción del módulo; si el bloque falla, la operación queda fallida con el
        motivo (sin rutas absolutas) y el error sigue; si termina sin completar el registro,
        queda fallida y se avisa. En ningún caso deja rutas reclamadas."""
        with operations.operation(self.project, "res.survey", settings={}) as handle:
            handle.claim_paths("rasters/res_a.tif")
            self.assertEqual(self.status(handle.uid), "running")
            self.write(lambda conn: (_write_table(conn, "res_terreno", (1.0,)),
                                     handle.complete(conn, outputs=[
                                         _table_spec("res_terreno", "terrain")])))
        self.assertEqual((self.status(handle.uid), self.row(handle.uid)["executor"]),
                         ("done", "blender"))

        with self.assertRaises(ZeroDivisionError):
            with operations.operation(self.project, "res.survey", settings={}) as failing:
                failing.claim_paths("rasters/res_b.tif")
                raise ZeroDivisionError("no se pudo leer C:\\Datos\\cliente\\cotas.csv")
        row = self.row(failing.uid)
        self.assertEqual((row["status"], row["finished_at"]), ("failed", _now()))
        self.assertIn("ZeroDivisionError", row["status_reason"])
        self.assertIn("cotas.csv", row["status_reason"])
        self.assertNotIn("C:\\", row["status_reason"])

        with self.assertRaises(provenance.ProvenanceError) as caught:
            with operations.operation(self.project, "res.survey", settings={}) as forgotten:
                forgotten.claim_paths("rasters/res_c.tif")
        self.assertEqual(caught.exception.code, "core.operation_not_completed")
        self.assertEqual(self.status(forgotten.uid), "failed")
        self.assertEqual(operations.claimed_paths(self.project), set())
        with self.assertRaises(RuntimeError):
            forgotten.claim_paths("rasters/res_d.tif")
        self.assertEqual(
            self.query("SELECT COUNT(*) FROM gb_operation_io WHERE direction = 'out' AND "
                       "operation_uid IN (?, ?)", (failing.uid, forgotten.uid)),
            [(0,)],
        )


class VocabularyTest(unittest.TestCase):
    def test_statuses_executors_and_items_match_the_schema(self) -> None:
        """RF-008-18, RF-008-19: los estados, los ejecutores y las clases de elemento de una
        operación son los del esquema 2."""
        ddl = schema.TABLES["gb_operation"] + schema.TABLES["gb_operation_io"]
        for values in (operations.OperationStatus, operations.Executor, operations.ItemKind):
            for value in values:
                with self.subTest(value=value):
                    self.assertIn(f"'{value}'", ddl)
        self.assertEqual(operations.OperationStatus.RUNNING, schema.RUNNING)
        self.assertEqual(set(operations.JOB_EXECUTORS), {"job_thread", "job_process"})

    def test_public_api(self) -> None:
        """Plan §5.1: ``core.provenance`` reexporta la API de las operaciones."""
        for name in ("begin_operation", "operation", "claimed_paths", "OperationHandle", "Use",
                     "OperationStatus", "Executor", "ItemKind"):
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIs(getattr(provenance, name), getattr(operations, name))
        self.assertLessEqual(set(provenance.OPERATIONS_API), set(provenance.__all__))
        self.assertLessEqual(set(provenance.OPERATIONS_API), set(dir(provenance)))
        with self.assertRaises(AttributeError):
            provenance.no_such_name  # noqa: B018

    def test_package_import_stays_light(self) -> None:
        """Plan §5.1: ``core.project.schema`` importa este paquete, así que importarlo no
        carga ``operations`` (ni con él ``core.datasets``, ``core.content`` y
        ``core.params``): lo reexporta al usarlo."""
        tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                with self.subTest(line=node.lineno):
                    self.assertNotEqual(node.module, "operations")
                    self.assertNotIn("operations", [alias.name for alias in node.names])


if __name__ == "__main__":
    unittest.main()
