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
  falla o termina sin completar el registro, la operación queda fallida;
- (T18) ``OperationHandle.fail`` y ``.cancel`` la dejan fallida o cancelada con el motivo y sin
  salidas; ``interrupt_orphaned``, al abrir en escritura, deja «interrumpida», con su evento, la
  que sigue en curso de otra sesión (no las de esta); ``mark_not_ingested`` deja «no
  incorporada», con el motivo, la que sigue en curso cuando se borra su trabajo; ninguna deja un
  dato registrado como bueno (RF-008-19, RF-008-23);
- (spec 005, T55) ``begin_operations`` deja «en curso» varias operaciones del mismo tipo en una
  sola transacción, cada una como con ``begin_operation``.

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
from unittest import mock

from tests.support.core_fixtures import (
    CLOCK_START,
    FakeClock,
    FakePids,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered, snapshot
from tests.unit.core.provenance.test_schema import input_row

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
events = import_geoblender("core.project.events")
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
# Otro Blender del mismo equipo (abre tras cerrarse el de SESSION de golpe) y otro equipo.
SESSION_A2 = make_session(session_uid="00000000-0000-4000-8000-0000000000a2", pid=5151)
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra", pid=777
)
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
    "gb_event",
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
        self.userdata = userdata_mod.UserData(tmp / "u")
        self.project = create.create_project(
            parent, make_settings(), SESSION, self.userdata, clock=self.clock
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

    def logged(self, kind: Any) -> list[Any]:
        """Los eventos ``kind`` del proyecto (``gb_event``)."""
        with self.project.read() as conn:
            return events.read_events(conn, kind)

    def assertNoOutputs(self, *uids: str) -> None:
        """Ninguna de las operaciones ``uids`` deja un dato registrado como bueno: ni
        salidas, ni datos, ni contenidos escritos por ella."""
        marks = ", ".join("?" for _ in uids)
        self.assertEqual(
            [self.query(f"SELECT COUNT(*) FROM {table} WHERE operation_uid IN ({marks}){extra}",
                        uids)
             for table, extra in (("gb_operation_io", " AND direction = 'out'"),
                                  ("gb_dataset", ""), ("gb_dataset_change", ""))],
            [[(0,)]] * 3,
        )


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

    def test_several_in_one_transaction(self) -> None:
        """RF-008-51, RF-008-04, RF-008-05 (spec 005, T55; RNF-005-06): ``begin_operations``
        deja «en curso» varias operaciones del mismo tipo, una por cada uno de sus ajustes, en
        una sola transacción de escritura y en su orden, cada una con lo mismo que
        ``begin_operation`` (sus campos, lo que consume y los parámetros resueltos; el que
        faltaba, registrado una vez); sin ajustes, ninguna y sin escribir; si una no se puede
        empezar, ninguna."""
        survey, _terrain = self.survey()
        self.add_input(survey.uid)
        self.tick()
        common: dict[str, Any] = {
            "inputs": [operations.Use("res_terreno", "terrain"),
                       operations.Use(INPUT_UID, "boundary", kind="input")],
            "params": ["res.swell_factor", "res.recovery"], "executor": "job_process"}
        settings = [{"tabla": "bocas", "n": 1}, {"tabla": "litología", "n": 2},
                    {"tabla": "análisis", "n": 3}]
        writes = mock.patch.object(self.project, "write_transaction",
                                   wraps=self.project.write_transaction)
        with writes as writing:
            together = operations.begin_operations(self.project, "res.balance",
                                                   settings=settings, **common)
            self.assertEqual(writing.call_count, 1)
            self.assertEqual(operations.begin_operations(self.project, "res.balance",
                                                         settings=[], **common), [])
            self.assertEqual(writing.call_count, 1)
        one_by_one = [self.begin(settings=item, **common) for item in settings]

        def recorded(handles: Sequence[Any]) -> list[Any]:
            found = []
            for handle in handles:
                row = self.row(handle.uid)
                found.append(({name: value for name, value in row.items()
                               if name not in ("fid", "uid")},
                              self.query("SELECT direction, item_kind, item_uid, "
                                         "content_sha256, role FROM gb_operation_io WHERE "
                                         "operation_uid = ? ORDER BY fid", (handle.uid,)),
                              self.query("SELECT parameter_uid, key, scope, rev, value, unit, "
                                         "kind, unconfirmed, value_sha256 FROM "
                                         "gb_operation_param WHERE operation_uid = ? ORDER BY "
                                         "fid", (handle.uid,)),
                              (handle.op_type, handle.started_at, handle.executor,
                               handle.inputs, handle.params)))
            return found

        self.assertEqual(recorded(together), recorded(one_by_one))
        self.assertEqual([_json(item) for item in settings],
                         [self.row(handle.uid)["settings"] for handle in together])
        fids = [self.row(handle.uid)["fid"] for handle in together]
        self.assertEqual(fids, sorted(fids))
        self.assertEqual(
            [row[0] for row in self.query("SELECT key FROM gb_parameter ORDER BY fid")],
            ["res.swell_factor", "res.recovery"])
        self.assertEqual({self.status(handle.uid) for handle in together}, {"running"})
        self.assertRejected(
            ValueError, None,
            lambda: operations.begin_operations(
                self.project, "res.balance",
                settings=[{"n": 4}, {"fuente": "C:\\Datos\\cliente\\limites.gpkg"}], **common))
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_dataset_unknown",
            lambda: operations.begin_operations(
                self.project, "res.balance", settings=[{"n": 5}],
                inputs=[operations.Use("res_nada", "terrain")], executor="blender"))
        self.assertRejected(TypeError, None, lambda: operations.begin_operations(
            self.project, "res.balance", settings={"n": 6}, executor="blender"))


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


class AddInputsTest(OperationsCase):
    """RF-008-51, RF-008-18 y, para quien la usa, RF-015-15 (spec 015, T42; C-1): ``OperationHandle.add_inputs``
    anota, en la transacción del módulo que va a completar la operación, entradas que una operación **en curso**
    solo conoce al terminar (lo que detecta su resultado), cada una con su hash de contenido de ahora y su papel:
    una operación **hecha** sigue siendo inmutable (ADR-0030 §4)."""

    def add(self, handle: Any, *uses: Any) -> Any:
        """``add_inputs`` de ``uses`` en una transacción de escritura propia (que se confirma)."""
        return self.write(lambda conn: handle.add_inputs(conn, list(uses)))

    def test_adds_what_the_result_depends_on_with_the_hash_it_has_now(self) -> None:
        """RF-008-51: la entrada nueva consta como las del principio (clase, dato, hash y papel) tras confirmar
        la transacción, ``add_inputs`` la devuelve y la operación sigue en curso; las que anotó al empezar, no
        cambian (``inputs`` es lo anotado al empezar); al completarse, es una entrada más suya."""
        _survey, terrain = self.survey()
        handle = self.begin(inputs=[operations.Use("res_terreno", "terrain")])
        before = [(item.uid, item.role) for item in handle.inputs]
        self.tick()

        def work(conn: sqlite3.Connection) -> Any:
            added = handle.add_inputs(conn, [operations.Use("res_terreno", "supported_on")])
            _write_table(conn, "res_resultado", (3.0,))
            handle.complete(conn, outputs=[_table_spec("res_resultado", "summary")], software=SOFTWARE)
            return added

        (added,) = self.write(work)
        self.assertEqual((str(added.kind), added.uid, added.name, added.content_sha256, added.role),
                         ("dataset", terrain.uid, "res_terreno", terrain.content_sha256, "supported_on"))
        self.assertEqual([(item.uid, item.role) for item in handle.inputs], before)
        self.assertEqual(
            self.query("SELECT item_kind, item_uid, content_sha256, role FROM gb_operation_io "
                       "WHERE operation_uid = ? AND direction = 'in' ORDER BY fid", (handle.uid,)),
            [("dataset", terrain.uid, terrain.content_sha256, "terrain"),
             ("dataset", terrain.uid, terrain.content_sha256, "supported_on")])
        self.assertEqual(self.status(handle.uid), "done")

    def test_what_it_adds_takes_part_in_the_cascade(self) -> None:
        """RF-008-24 (la razón de ser, C-1): lo que se anota al terminar se vigila como lo anotado al empezar: si
        el dato cambia después, la operación queda obsoleta con esa causa."""
        survey, terrain = self.survey((1.0, 2.0))
        handle = self.begin()

        def work(conn: sqlite3.Connection) -> None:
            handle.add_inputs(conn, [operations.Use("res_terreno", "supported_on")])
            _write_table(conn, "res_resultado", (3.0,))
            handle.complete(conn, outputs=[_table_spec("res_resultado", "summary")], software=SOFTWARE)

        self.write(work)
        stale = "SELECT cause_kind FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?"
        self.assertEqual(self.query(stale, (handle.uid,)), [])
        self.tick()
        again = self.begin("res.survey", supersedes=survey.uid)

        def change(conn: sqlite3.Connection) -> None:
            conn.execute('DELETE FROM "res_terreno"')
            _write_table(conn, "res_terreno", (1.0, 2.5))
            again.complete(conn, outputs=[_table_spec("res_terreno", "terrain")])

        self.write(change)
        self.assertNotEqual(self.query(stale, (handle.uid,)), [], terrain.name)

    def test_rejections_write_nothing(self) -> None:
        """RF-008-51, RF-008-18: un dato que no existe, uno repetido (con el mismo papel que ya consume la operación
        o dos veces en la misma llamada), una operación que ya no está en curso y llamar fuera de una transacción
        de escritura se rechazan sin escribir nada."""
        self.survey()
        handle = self.begin(inputs=[operations.Use("res_terreno", "terrain")])
        self.assertRejected(provenance.ProvenanceError, "core.operation_dataset_unknown",
                            lambda: self.add(handle, operations.Use("res_nada", "supported_on")))
        self.assertRejected(ValueError, None, lambda: self.add(handle, operations.Use("res_terreno", "terrain")))
        self.assertRejected(ValueError, None, lambda: self.add(
            handle, operations.Use("res_terreno", "supported_on"), operations.Use("res_terreno", "supported_on")))
        self.assertRejected(TypeError, None, lambda: self.add(handle, "res_terreno"))
        with self.project.read() as conn, self.assertRaises(ValueError):
            handle.add_inputs(conn, [operations.Use("res_terreno", "supported_on")])
        self.assertRejected(TypeError, None, lambda: handle.add_inputs(object(), []))
        self.assertEqual(self.status(handle.uid), "running")
        self.write(lambda conn: handle.complete(conn, software=SOFTWARE))
        self.assertRejected(provenance.ProvenanceError, "core.operation_not_running",
                            lambda: self.add(handle, operations.Use("res_terreno", "supported_on")))

    def test_module_rollback_leaves_nothing_and_it_can_be_added_again(self) -> None:
        """RF-008-18: si la transacción del módulo se deshace después de ``add_inputs``, no queda la entrada, la
        operación sigue en curso y se puede volver a intentar (no cuenta como repetida)."""
        self.survey()
        handle = self.begin()
        before = self.snapshot()

        def work(conn: sqlite3.Connection) -> None:
            handle.add_inputs(conn, [operations.Use("res_terreno", "supported_on")])
            raise _Abort("el módulo falla después de anotar")

        with self.assertRaises(_Abort):
            self.write(work)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.status(handle.uid), "running")
        (again,) = self.add(handle, operations.Use("res_terreno", "supported_on"))
        self.assertEqual(again.role, "supported_on")


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


INTERRUPTED_REASON = (
    "la sesión de prueba@PC-PRUEBA-A que la ejecutaba ya no tiene el cerrojo del proyecto "
    "(Blender se cerró, se cayó la red u otro equipo forzó el cerrojo) y no pudo registrar su "
    "final"
)
NOT_INGESTED_REASON = (
    "La carpeta del trabajo «job-0001» se borró (purga por antigüedad) sin incorporar su "
    "resultado"
)


class EndTest(OperationsCase):
    """Fallar, cancelar, interrumpir y no incorporar (T18; RF-008-19, RF-008-23)."""

    def test_cancel_and_fail_keep_the_reason_and_no_outputs(self) -> None:
        """RF-008-19, RF-008-23: cancelar o fallar deja la operación cancelada o fallida, con
        su motivo (sin rutas absolutas) y su hora, sin salidas (tampoco lo que el módulo
        escribió en una transacción que se deshizo) y sin rutas reclamadas; lo que consumió
        queda anotado. Una operación terminada ya no se completa, ni se cancela, ni falla.
        RF-004-07 (spec 006, T57): su estado registrado con su motivo se lee por su uid."""
        _survey, terrain = self.survey()
        stopped = self.begin(inputs=[operations.Use("res_terreno", "terrain")],
                             params=["res.recovery"])
        stopped.claim_paths("rasters/res_tmp.tif")
        broken = self.begin("res.survey")

        def work(conn: sqlite3.Connection) -> None:
            _write_table(conn, "res_resultado", (1.0,))
            stopped.complete(conn, outputs=[_table_spec("res_resultado", "summary")],
                             software=SOFTWARE)
            raise _Abort("se pidió cancelar mientras escribía")

        with self.assertRaises(_Abort):
            self.write(work)
        self.tick()
        self.assertIsNone(stopped.cancel("Cancelado por la persona desde la barra de estado"))
        self.assertIsNone(broken.fail(
            "No se pudo leer C:\\Datos\\cliente\\cotas.csv: falta la columna «cota»"))
        fields = ("status", "status_reason", "finished_at", "software", "message")
        self.assertEqual(
            [tuple(self.row(handle.uid)[name] for name in fields) for handle in (stopped, broken)],
            [("cancelled", "Cancelado por la persona desde la barra de estado", _now(1), "{}",
              None),
             ("failed", "No se pudo leer cotas.csv: falta la columna «cota»", _now(1), "{}",
              None)],
        )
        self.assertNoOutputs(stopped.uid, broken.uid)
        # RF-008-32: el estado registrado de cada una (lo que no está, no sale), para el
        # diario de Ctrl+Z.
        running = self.begin("res.survey")
        status = operations.OperationStatus
        self.assertEqual(
            operations.operation_statuses(self.project,
                                          [stopped.uid, broken.uid, running.uid, "op-nada"]),
            {stopped.uid: status.CANCELLED, broken.uid: status.FAILED,
             running.uid: status.RUNNING},
        )
        self.assertEqual(operations.operation_statuses(self.project, []), {})
        # Spec 006, T57 (RF-004-07): el estado de una con su motivo, para decir en la barra de
        # estado y en el registro de Blender que la operación de un trabajo no se hizo.
        state = operations.OperationState
        self.assertEqual(
            [operations.operation_state(self.project, uid)
             for uid in (stopped.uid, broken.uid, running.uid, "op-nada")],
            [state(status.CANCELLED, "Cancelado por la persona desde la barra de estado"),
             state(status.FAILED, "No se pudo leer cotas.csv: falta la columna «cota»"),
             state(status.RUNNING, None), None],
        )
        running.fail("prueba")
        self.assertEqual(
            self.query("SELECT item_uid, role FROM gb_operation_io WHERE operation_uid = ? "
                       "AND direction = 'in'", (stopped.uid,)),
            [(terrain.uid, "terrain")],
        )
        self.assertEqual(self.query("SELECT key FROM gb_operation_param WHERE operation_uid = ?",
                                    (stopped.uid,)), [("res.recovery",)])
        self.assertEqual(self.query("SELECT name FROM gb_dataset ORDER BY fid"),
                         [("res_terreno",)])
        self.assertEqual(operations.claimed_paths(self.project), set())
        with self.assertRaises(RuntimeError):
            stopped.claim_paths("rasters/res_otro.tif")
        for handle in (stopped, broken):
            for end in (handle.fail, handle.cancel):
                with self.subTest(op_type=handle.op_type, end=end.__name__):
                    self.assertRejected(provenance.ProvenanceError, "core.operation_not_running",
                                        lambda end=end: end("otra vez"))
            self.assertRejected(
                provenance.ProvenanceError, "core.operation_not_running",
                lambda handle=handle: self.write(lambda conn: handle.complete(conn)))

    def test_reasons_and_read_only(self) -> None:
        """RF-008-19: el motivo es un texto no vacío (si no, un error del programa, sin
        escribir nada) de 500 caracteres como mucho; en solo lectura no se registra nada
        (``core.read_only``) y la operación sigue en curso: quedará interrumpida al abrir el
        proyecto en escritura."""
        handle = self.begin()
        for bad in (None, 42, "", "   "):
            for end in (handle.fail, handle.cancel):
                with self.subTest(bad=bad, end=end.__name__):
                    self.assertRejected((TypeError, ValueError), None,
                                        lambda end=end, bad=bad: end(bad))
        self.assertEqual(self.status(handle.uid), "running")
        handle.fail("x" * 600)
        reason = self.row(handle.uid)["status_reason"]
        self.assertEqual((len(reason), reason[-1]), (operations.MAX_REASON_CHARS, "…"))
        other = self.begin()
        before = self.snapshot()
        self.project.set_read_only(project_model.ReadOnlyCode.LOCKED,
                                   "otra sesión lo tiene en escritura")
        for end in (other.fail, other.cancel):
            with self.subTest(end=end.__name__):
                with self.assertRaises(provenance.ProvenanceError) as caught:
                    end("Cancelado por la persona")
                self.assertEqual(caught.exception.code, "core.read_only")
        self.assertEqual(self.snapshot(), before)

    def test_context_manager_cancelled_or_ended_by_the_module(self) -> None:
        """RF-008-19: en ``operation()``, parar una lectura o una huella (``ReadCancelled``,
        ``HashCancelled``) deja la operación cancelada con el motivo y el error sigue; si el
        módulo la da por fallida o la cancela dentro del bloque, queda así, también si luego
        el bloque falla."""
        for error in (content.ReadCancelled("test.npy_grid@1", 0.42),
                      hashing.HashCancelled("cotas.csv", 10, 100)):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)):
                    with operations.operation(self.project, "res.survey", settings={}) as handle:
                        handle.claim_paths("rasters/res_a.tif")
                        raise error
                self.assertEqual(
                    (self.status(handle.uid), self.row(handle.uid)["status_reason"]),
                    ("cancelled", f"cancelada durante la operación: {error}"),
                )
        with operations.operation(self.project, "res.survey", settings={}) as explicit:
            explicit.fail("Faltan las cotas de 3 sondeos")
        with self.assertRaises(ZeroDivisionError):
            with operations.operation(self.project, "res.survey", settings={}) as stopped:
                stopped.cancel("Cancelado por la persona")
                raise ZeroDivisionError("después de cancelar")
        self.assertEqual(
            [(self.status(h.uid), self.row(h.uid)["status_reason"]) for h in (explicit, stopped)],
            [("failed", "Faltan las cotas de 3 sondeos"), ("cancelled", "Cancelado por la persona")],
        )
        self.assertEqual(operations.claimed_paths(self.project), set())

    def test_interrupted_when_opened_in_write_mode(self) -> None:
        """RF-008-19: al abrir en escritura, las operaciones «en curso» de otra sesión (su
        Blender se cerró de golpe sin registrar su final) pasan a «interrumpida» con su motivo,
        su hora y su evento, sin ningún dato registrado como bueno (tampoco la tabla que
        dejaron a medias); las de esta sesión siguen en curso y las terminadas no cambian. En
        solo lectura no se registra nada; repetirlo no hace nada más; con la conexión de una
        transacción, escribe en ella."""
        survey, _terrain = self.survey()
        failed = self.begin("res.survey")
        failed.fail("Faltan las cotas de 3 sondeos")
        running = self.begin(inputs=[operations.Use("res_terreno", "terrain")],
                             params=["res.recovery"])
        job = self.begin("res.survey", executor="job_process", job_uid="job-0001")
        self.write(lambda conn: _write_table(conn, "res_resultado", (7.0,)))  # a medias
        self.tick()
        # El Blender de SESSION se cierra de golpe: no vuelve a escribir (ni al cerrar).
        self.project.set_read_only(project_model.ReadOnlyCode.LOCK_LOST, "Blender se cerró")
        pids = FakePids({SESSION_A2.pid, SESSION_B.pid})

        def open_(session: Any, **kw: Any) -> Any:
            project = open_mod.open_project(self.project.root, session, self.userdata,
                                            clock=self.clock, pid_alive=pids, **kw).project
            self.addCleanup(project.close)
            return project

        reader = open_(SESSION_B, want_write=False)
        before = self.snapshot()
        with self.assertRaises(provenance.ProvenanceError) as caught:
            operations.interrupt_orphaned(reader)
        self.assertEqual(caught.exception.code, "core.read_only")
        self.assertEqual(self.snapshot(), before)
        reader.close()

        writer = open_(SESSION_A2)
        self.assertTrue(writer.writable)
        mine = operations.begin_operation(writer, "res.balance", settings={}, executor="blender")
        self.tick()
        with self.assertRaises(_Abort), writer.write_transaction() as conn:
            self.assertEqual(operations.interrupt_orphaned(writer, conn=conn),
                             [running.uid, job.uid])
            raise _Abort("la transacción de quien llama se deshace")
        self.assertEqual([self.status(h.uid) for h in (running, job)], ["running"] * 2)
        self.assertEqual(operations.interrupt_orphaned(writer), [running.uid, job.uid])
        fields = ("status", "status_reason", "finished_at")
        self.assertEqual([tuple(self.row(h.uid)[name] for name in fields) for h in (running, job)],
                         [("interrupted", INTERRUPTED_REASON, _now(2))] * 2)
        self.assertEqual([self.status(h.uid) for h in (survey, failed, mine)],
                         ["done", "failed", "running"])
        self.assertEqual(
            [(e.at, e.user_host, e.session_uid, e.entity_kind, e.entity_uid, e.message, e.data)
             for e in self.logged(events.EventKind.OPERATION_INTERRUPTED)],
            [(_now(2), "prueba@PC-PRUEBA-A", SESSION_A2.session_uid, "operation", h.uid,
              f"Operación «{h.op_type}» interrumpida: {INTERRUPTED_REASON}",
              {"op_type": h.op_type, "session_uid": SESSION.session_uid,
               "user_host": "prueba@PC-PRUEBA-A", "started_at": _now(), "job_uid": job_uid,
               "reason": INTERRUPTED_REASON})
             for h, job_uid in ((running, None), (job, "job-0001"))],
        )
        self.assertNoOutputs(running.uid, job.uid)
        self.assertEqual(self.query("SELECT name FROM gb_dataset ORDER BY fid"),
                         [("res_terreno",)])
        self.assertIn(("res_resultado",), self.query("SELECT table_name FROM gpkg_contents"))
        before = self.snapshot()
        self.assertEqual(operations.interrupt_orphaned(writer), [])
        self.assertEqual(self.snapshot(), before)
        with writer.read() as conn, self.assertRaises(ValueError):
            operations.interrupt_orphaned(writer, conn=conn)  # fuera de una transacción

    def test_not_ingested_when_its_job_is_deleted(self) -> None:
        """RF-008-23, RF-008-19: una operación «en curso» cuyo trabajo se borra sin
        incorporarlo (descartarlo, limpiar, la purga por antigüedad) pasa a «no incorporada»
        con el motivo, su hora y su evento, sin salidas y sin rutas reclamadas; repetirlo, o
        con una ya terminada, no cambia nada. Una operación que no es de un trabajo, una que no
        existe, un motivo vacío y el proyecto en solo lectura se rechazan sin escribir nada."""
        handle = self.begin(executor="job_process", job_uid="job-0001")
        handle.claim_paths("rasters/res_tmp.tif")
        done = self.begin(executor="job_thread")
        self.write(lambda conn: done.complete(conn, software=SOFTWARE, job_uid="job-0002"))
        here = self.begin()
        later = self.begin(executor="job_thread")
        self.tick()
        self.assertTrue(operations.mark_not_ingested(self.project, handle.uid,
                                                     NOT_INGESTED_REASON))
        row = self.row(handle.uid)
        self.assertEqual(
            (row["status"], row["status_reason"], row["finished_at"], row["job_uid"]),
            ("not_ingested", NOT_INGESTED_REASON, _now(1), "job-0001"),
        )
        self.assertEqual(
            [(e.at, e.session_uid, e.entity_kind, e.entity_uid, e.message, e.data)
             for e in self.logged(events.EventKind.OPERATION_NOT_INGESTED)],
            [(_now(1), SESSION.session_uid, "operation", handle.uid,
              f"Operación «res.balance» no incorporada: {NOT_INGESTED_REASON}",
              {"op_type": "res.balance", "job_uid": "job-0001",
               "reason": NOT_INGESTED_REASON})],
        )
        self.assertNoOutputs(handle.uid)
        self.assertEqual(operations.claimed_paths(self.project), set())
        with self.assertRaises(RuntimeError):
            handle.claim_paths("rasters/res_otro.tif")
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_not_running",
            lambda: self.write(lambda conn: handle.complete(conn, software=SOFTWARE)))
        before = self.snapshot()
        for finished in (handle, done):
            with self.subTest(status=self.status(finished.uid)):
                self.assertFalse(operations.mark_not_ingested(self.project, finished.uid,
                                                              NOT_INGESTED_REASON))
        self.assertEqual(self.snapshot(), before)
        self.assertRejected(
            provenance.ProvenanceError, "core.operation_unknown",
            lambda: operations.mark_not_ingested(self.project, UNKNOWN_UID, NOT_INGESTED_REASON))
        self.assertRejected(
            ValueError, None,
            lambda: operations.mark_not_ingested(self.project, here.uid, NOT_INGESTED_REASON))
        for bad in (None, ""):
            with self.subTest(bad=bad):
                self.assertRejected(
                    (TypeError, ValueError), None,
                    lambda bad=bad: operations.mark_not_ingested(self.project, later.uid, bad))
        self.project.set_read_only(project_model.ReadOnlyCode.LOCKED,
                                   "otra sesión lo tiene en escritura")
        with self.assertRaises(provenance.ProvenanceError) as caught:
            operations.mark_not_ingested(self.project, later.uid, NOT_INGESTED_REASON)
        self.assertEqual(caught.exception.code, "core.read_only")
        self.assertEqual(self.snapshot(), before)


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

    def test_event_kinds(self) -> None:
        """RF-008-19, RF-008-23 (plan §5.2.3): los eventos de una operación interrumpida y de
        una no incorporada."""
        self.assertEqual(
            (events.EventKind.OPERATION_INTERRUPTED.value,
             events.EventKind.OPERATION_NOT_INGESTED.value),
            ("operation_interrupted", "operation_not_ingested"),
        )

    def test_public_api(self) -> None:
        """Plan §5.1: ``core.provenance`` reexporta la API de las operaciones."""
        for name in ("begin_operation", "operation", "claimed_paths", "OperationHandle", "Use",
                     "OperationStatus", "Executor", "ItemKind", "interrupt_orphaned",
                     "mark_not_ingested", "operation_statuses"):
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
