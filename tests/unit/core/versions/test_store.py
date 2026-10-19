# SPDX-License-Identifier: GPL-3.0-or-later
"""Versiones y revisiones: crearlas, cambiar su estado y su título (spec 009, T05; RF-009-01,
RF-009-02, RF-009-03, RF-009-04, RF-009-12, RF-009-22, RF-009-25; plan 009 A1, A2, D-24 a
D-26).

``core.versions.store`` escribe en la transacción que recibe (``Project.write_transaction``):

- ``create_version`` da el código correlativo inmutable (V01, V02…), el estado BORRADOR y la
  revisión r1 abierta, con quién y cuándo; con versión padre, sus parámetros de versión copiados
  con la fila de historial «Heredado de V01.r2» (D-26) y **nada más**: ni datos, ni operaciones,
  ni cifras (CE-009-05 en lo que toca a crear); la primera sube ``min_reader_schema`` a 3 y un
  Geoblender del esquema 2 ya solo lee la cabecera (D-24);
- ``set_status`` admite BORRADOR → VIGENTE (con una revisión congelada; la VIGENTE anterior pasa
  a SUPERADO en la misma transacción y se cierra su revisión abierta, «cerrada al superarse») y
  BORRADOR o VIGENTE → DESCARTADO con motivo; lo demás se rechaza con el texto de la spec, sin
  cambiar nada; ningún cambio de estado toca un fichero distinto de la base, su diario y la
  cabecera;
- ``set_title`` cambia el título de una versión o de un dato, nunca su código ni su nombre;
- cada cambio deja su evento, ninguna función borra nada y las lecturas de ``core.versions.read``
  no mueven el contador de cambios de la base.

El proyecto es el de ``esquema2.zip`` (T03, con los datos de la 005, la 006 y la 008), migrado
una vez al esquema 3 en ``setUpModule``; cada prueba trabaja en una copia abierta en escritura.
Las revisiones se congelan con SQL (congelar es la T13): solo cambian su estado y abren la
siguiente.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import unittest
import uuid
from collections.abc import Callable
from typing import Any
from unittest import mock

from tests.support import schema2_project as fixture
from tests.support.core_fixtures import FakeClock, FakePids, make_session, project_tmp
from tests.support.package import import_geoblender
from tests.unit.core.provenance.test_schema import history_row, parameter_row

model = import_geoblender("core.versions.model")
read = import_geoblender("core.versions.read")
store = import_geoblender("core.versions.store")
versions_schema = import_geoblender("core.versions.schema")
migrations = import_geoblender("core.project.migrations")
open_mod = import_geoblender("core.project.open")
project_model = import_geoblender("core.project.model")
manifest_mod = import_geoblender("core.project.manifest")
events_mod = import_geoblender("core.project.events")
header_mod = import_geoblender("core.gpkg.header")
errors = import_geoblender("core.errors")
i18n = import_geoblender("core.i18n")
timeutil = import_geoblender("core.timeutil")
userdata_mod = import_geoblender("core.userdata")

SESSION = make_session()
USER = SESSION.user_host
PIDS = FakePids({SESSION.pid})
DATABASE = "project.gpkg"
WRITTEN = ("project.gpkg", "project.gpkg-journal", "manifest.json")
"""Lo único de la carpeta del proyecto que puede cambiar al cambiar de estado (RF-009-02)."""
NOW = "2026-10-18T10:00:00.000Z"
NOT_EDITABLE = "{code} está en estado {state}: cree una versión nueva a partir de ella"
"""El rechazo de RF-009-04, con el ejemplo de la spec («V09 está en estado SUPERADO: …»)."""
STATUS_ROWS = ("gb_version", "gb_revision", "gb_event")
"""Las únicas tablas que escribe un cambio de estado (plan A2)."""
EVENT = events_mod.EventKind

_STATE: dict[str, Any] = {}


def setUpModule() -> None:
    """Descomprime ``esquema2.zip`` y lo migra al esquema 3 (el de esta versión)."""
    tmp = unittest.enterModuleContext(project_tmp("gb-v5-"))
    work = tmp / "z"
    work.mkdir()
    root = fixture.extract(work)
    userdata = userdata_mod.UserData(tmp / "u")
    list(migrations.migrate_steps(root, SESSION, userdata, clock=FakeClock(), pid_alive=PIDS))
    _STATE.update(template=root, userdata=userdata)


def _uid() -> str:
    return str(uuid.uuid4())


def _insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values()))


WRITTEN_TABLES = ("gb_project", "gb_version", "gb_revision", "gb_parameter",
                  "gb_parameter_history", "gb_dataset", "gb_event")
"""Las tablas que escriben las funciones de ``core.versions.store``."""


def _written(conn: sqlite3.Connection) -> dict[str, list[tuple[Any, ...]]]:
    return {table: conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in WRITTEN_TABLES}


def _copy_row(conn: sqlite3.Connection, table: str, where: str, **changes: Any) -> dict[str, Any]:
    """Una fila de ``table`` (la primera de ``where``), sin ``fid`` y con ``changes``."""
    cursor = conn.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY fid LIMIT 1")
    names = [column[0] for column in cursor.description]
    row = dict(zip(names, cursor.fetchone(), strict=True))
    row.pop("fid")
    unknown = set(changes) - set(row)
    if unknown:
        raise KeyError(unknown)
    return {**row, **changes}


class ModelTest(unittest.TestCase):
    """Lo que no necesita un proyecto: estados, códigos, etiquetas y mensajes."""

    def test_states_codes_and_labels(self) -> None:
        """RF-009-01, RF-009-02, RF-009-03 (ADR-0013; plan §2.1, trampa §8): los cuatro estados
        se escriben como los escribe ADR-0013 y son los de la base (``core.versions.schema``),
        con las mismas transiciones y los mismos editables; los códigos son V01…V99 y V100; la
        etiqueta de una versión es «V10 · Definitiva» y la de su revisión, «V10.r2»."""
        status = model.VersionStatus
        self.assertEqual([item.value for item in status],
                         ["BORRADOR", "VIGENTE", "SUPERADO", "DESCARTADO"])
        self.assertTrue(all(item.value.isascii() for item in status))
        self.assertEqual({item.value for item in model.EDITABLE},
                         set(versions_schema.EDITABLE_STATUSES))
        self.assertEqual(
            {source.value: {target.value for target in targets}
             for source, targets in model.TRANSITIONS.items() if targets},
            {source: set(targets) for source, targets in versions_schema.TRANSITIONS.items()},
        )
        # Lo que pide una persona (RF-009-03): VIGENTE → SUPERADO solo al declarar otra.
        self.assertEqual(
            {source.value: {target.value for target in targets}
             for source, targets in model.REQUESTED.items()},
            {"BORRADOR": {"VIGENTE", "DESCARTADO"}, "VIGENTE": {"DESCARTADO"}},
        )
        self.assertEqual([item.value for item in model.RevisionState],
                         [versions_schema.OPEN, versions_schema.FROZEN, versions_schema.CLOSED])
        self.assertEqual([model.version_code(n) for n in (1, 9, 10, 99, 100)],
                         ["V01", "V09", "V10", "V99", "V100"])
        for wrong in (0, -1, 1.0, True, "1"):
            with self.subTest(number=wrong), self.assertRaises((TypeError, ValueError)):
                model.version_code(wrong)
        self.assertEqual(model.revision_label("V10", 2), "V10.r2")

    def test_messages_in_the_language_catalog(self) -> None:
        """RF-009-04 (constitución, principio 10): cada rechazo de ``core.versions`` tiene su
        ``msgid`` en inglés con su español en ``messages.toml`` y los mismos marcadores; el de
        «Versión no editable» es el de la spec («V09 está en estado SUPERADO: cree una versión
        nueva a partir de ella») y el texto anterior («cree una revisión o una versión nueva»)
        ya no está; en inglés, el estado con su etiqueta inglesa."""
        table = i18n.load_messages()
        for code, msgid in model.MESSAGES.items():
            with self.subTest(code=code):
                self.assertTrue(code.startswith("core.version_"))
                self.assertIn(msgid, table)
                self.assertEqual(i18n.placeholders(table[msgid]), i18n.placeholders(msgid))
        self.assertNotIn("{version} is in state {state}: create a revision or a new version",
                         table)
        error = model.VersionError("core.version_not_editable", field="estado", value="SUPERADO",
                                   version="V09", state=model.VersionStatus.SUPERADO)
        self.assertEqual(str(error), NOT_EDITABLE.format(code="V09", state="SUPERADO"))
        self.assertEqual(error.message, str(error))
        self.assertIsInstance(error, errors.GeoblenderError)
        self.assertEqual(error.code, "core.version_not_editable")
        self.assertEqual(error.values, {"version": "V09", "state": "SUPERADO"})
        self.assertEqual(model.render(error.code, language="en", **error.values),
                         "V09 is in state SUPERSEDED: create a new version from it")
        self.assertEqual(
            str(model.VersionError("core.version_freeze_first", field="estado", version="V11")),
            "Congele antes una revisión de V11",
        )


class StoreCase(unittest.TestCase):
    """Una copia del proyecto migrado, abierta en escritura (``self.project``), con un reloj
    simulado."""

    def setUp(self) -> None:
        folder = self.enterContext(project_tmp("gb-v5c-"))
        self.root = folder / _STATE["template"].name
        shutil.copytree(_STATE["template"], self.root)
        self.clock = FakeClock()
        self.project = open_mod.open_project(
            self.root, SESSION, _STATE["userdata"], clock=self.clock, pid_alive=PIDS
        ).project
        self.addCleanup(self.project.close)
        self.assertTrue(self.project.writable)

    # Ayudas -------------------------------------------------------------------------------

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.project.write_transaction() as conn:
            return work(conn)

    def query(self, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def dump(self) -> dict[str, list[tuple[Any, ...]]]:
        """Cada fila de cada tabla de la base, por tabla."""
        with self.project.read() as conn:
            names = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
            return {name: conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                    for name in names}

    def files(self) -> dict[str, object]:
        """Cada fichero de la carpeta del proyecto (tamaño, sha256 y fecha) y cada carpeta, sin
        la base, su diario y la cabecera."""
        found: dict[str, object] = {}
        for path in sorted(self.root.rglob("*")):
            rel = path.relative_to(self.root).as_posix()
            if rel in WRITTEN:
                continue
            if path.is_dir():
                found[rel] = "carpeta"
            else:
                stat = path.stat()
                found[rel] = (stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest(),
                              stat.st_mtime_ns)
        return found

    def counter(self) -> int:
        """El contador de cambios de la cabecera de la base (sube con cada transacción)."""
        return header_mod.read_header(self.root / DATABASE).change_counter

    def events(self, kind: Any) -> list[Any]:
        with self.project.read() as conn:
            return events_mod.read_events(conn, kind)

    def now(self) -> str:
        return timeutil.format_utc(self.clock.now())

    def create(self, **changes: Any) -> tuple[Any, Any]:
        fields: dict[str, Any] = {"feature": "rasgo", "title": "Título", "reason": "Prueba"}
        fields.update(changes)
        self.clock.advance(minutes=1)
        return self.write(lambda conn: store.create_version(conn, self.project, **fields))

    def set_status(self, version: Any, target: Any, reason: str | None = None) -> Any:
        self.clock.advance(minutes=1)
        return self.write(lambda conn: store.set_status(conn, self.project, version.uid, target,
                                                        reason=reason))

    def freeze(self, version: Any) -> None:
        """Congela con SQL la revisión abierta de ``version`` y abre la siguiente."""

        def work(conn: sqlite3.Connection) -> None:
            uid, number = conn.execute(
                "SELECT uid, number FROM gb_revision WHERE version_uid = ? AND state = 'open'",
                (version.uid,),
            ).fetchone()
            conn.execute(
                "UPDATE gb_revision SET state = 'frozen', closed_at = ?, closed_by = ?, "
                "snapshot_dir = ?, snapshot_sha256 = ?, snapshot_bytes = 0, "
                "geoblender_version = ? WHERE uid = ?",
                (NOW, USER, f"snapshots/{version.code}.r{number}", "a" * 64, "0.1.0", uid),
            )
            _insert(conn, "gb_revision", {
                "uid": _uid(), "version_uid": version.uid, "number": number + 1,
                "state": "open", "reason": "Siguiente", "created_at": NOW, "created_by": USER,
            })

        self.write(work)

    def assertRejected(self, *cases: tuple[str, Callable[[sqlite3.Connection], Any]]) -> Any:
        """Cada caso (código, trabajo) se rechaza con su código **antes de escribir nada**: en
        una sola transacción, las tablas que escriben estas funciones siguen igual tras cada
        uno; al final no se ha confirmado nada (el contador de cambios no se mueve) y el
        proyecto sigue en escritura. Devuelve el error del último."""
        counter = self.counter()
        found: list[Any] = [None]
        with self.project.write_transaction() as conn:
            before = _written(conn)
            for code, work in cases:
                with self.subTest(code=code):
                    with self.assertRaises(model.VersionError) as caught:
                        work(conn)
                    self.assertEqual(caught.exception.code, code, str(caught.exception))
                    self.assertEqual(_written(conn), before)
                    found.append(caught.exception)
        self.assertTrue(self.project.writable)
        self.assertEqual(self.counter(), counter)
        return found[-1]


class CreateTest(StoreCase):
    def test_correlative_codes_in_draft_with_its_first_revision(self) -> None:
        """RF-009-01, RF-009-02: cada versión nueva tiene el código siguiente (V01, V02… V10),
        el estado BORRADOR como atributo, su rasgo, título, motivo y encargo, quién y cuándo, y
        su r1 abierta («Revisión inicial»); las lecturas la devuelven igual (por uid y por
        código) y el evento ``version_created`` la nombra."""
        v1, r1 = self.create(feature="definitiva", title="Definitiva", reason="Diseño de partida",
                             request="Encargo de la propiedad del 03/10/2026")
        created_at = self.now()  # create() avanza el reloj antes de crear
        v2, r2 = self.create(feature="ampliacion", title="Ampliación", reason="Otra alternativa")
        self.assertEqual((v1.code, v2.code), ("V01", "V02"))
        self.assertIs(v1.status, model.VersionStatus.BORRADOR)
        self.assertEqual(
            (v1.feature, v1.title, v1.reason_created, v1.request, v1.parent_uid,
             v1.parent_revision_uid, v1.reason_closed),
            ("definitiva", "Definitiva", "Diseño de partida",
             "Encargo de la propiedad del 03/10/2026", None, None, None),
        )
        self.assertEqual((v1.created_at, v1.created_by, v1.status_changed_at,
                          v1.status_changed_by), (created_at, USER, created_at, USER))
        self.assertEqual((v1.label, v1.editable), ("V01 · Definitiva", True))
        self.assertEqual(
            (r1.version_uid, r1.number, r1.state, r1.reason, r1.created_at, r1.created_by,
             r1.closed_at, r1.snapshot_dir),
            (v1.uid, 1, model.RevisionState.OPEN, "Revisión inicial", created_at, USER, None,
             None),
        )
        self.assertEqual((r1.label("V01"), r2.number, v2.request), ("V01.r1", 1, None))
        with self.project.read() as conn:
            self.assertEqual(read.versions(conn), (v1, v2))
            self.assertEqual((read.version(conn, "V02"), read.version(conn, v2.uid)), (v2, v2))
            self.assertIsNone(read.version(conn, "V09"))
            self.assertEqual(read.revisions(conn, v1.uid), (r1,))
            self.assertEqual(read.open_revision(conn, v1.uid), r1)
            self.assertIsNone(read.last_frozen(conn, v1.uid))
            self.assertIsNone(read.current_version(conn))
            self.assertEqual(read.default_active(conn), v2)  # el BORRADOR más reciente (D-25)
        created = self.events(EVENT.VERSION_CREATED)
        self.assertEqual([(item.entity_kind, item.entity_uid, item.data["code"],
                           item.data["revision_uid"]) for item in created],
                         [("version", v1.uid, "V01", r1.uid), ("version", v2.uid, "V02", r2.uid)])
        for text in ("V01", "Definitiva", "BORRADOR", "r1", USER, "Diseño de partida"):
            self.assertIn(text, created[0].message)
        # Correlativos también al pasar de 9.
        made = self.write(lambda conn: [
            store.create_version(conn, self.project, feature=f"r{n}", title=f"T{n}",
                                 reason="Más") for n in range(8)])
        self.assertEqual([version.code for version, _ in made][-2:], ["V09", "V10"])

    def test_rejections(self) -> None:
        """RF-009-01: sin rasgo, título o motivo, con una versión de partida que no existe o con
        una ruta absoluta en un texto (el proyecto no guarda ninguna), se rechaza con su texto y
        no se escribe nada."""
        good = {"feature": "rasgo", "title": "Título", "reason": "Motivo"}

        def made(**changes: Any) -> Callable[[sqlite3.Connection], Any]:
            return lambda conn: store.create_version(conn, self.project, **{**good, **changes})

        self.assertRejected(*(
            (code, made(**{field: empty}))
            for field, code in (("feature", "core.version_feature_required"),
                                ("title", "core.version_title_required"),
                                ("reason", "core.version_reason_required"))
            for empty in (None, "", "  ")
        ), *(("core.version_text_path", made(**{field: "copiado de C:\\datos\\x"}))
             for field in ("feature", "title", "reason", "request")))
        error = self.assertRejected(("core.version_unknown", made(parent="V09")))
        self.assertEqual(str(error), "No hay ninguna versión V09 en el proyecto")
        # Como lo hará la interfaz: el rechazo deshace su transacción y nada más.
        with self.assertRaises(model.VersionError):
            self.write(made(title=None))
        self.assertTrue(self.project.writable)
        self.assertEqual(self.query("SELECT count(*) FROM gb_version"), [(0,)])

    def test_inherits_version_parameters_and_nothing_else(self) -> None:
        """RF-009-01 (D-10, D-26; CE-009-05 en lo que toca a crear): una versión que parte de
        V01 hereda los valores actuales de sus parámetros de versión (mismo valor, unidad, tipo,
        origen y decisor) con una fila de historial ``create`` «Heredado de V01.r2» (la revisión
        abierta de la padre) de quien la crea, y su ``parent_revision_uid`` es la última
        congelada (r1); ni un dato, ni una operación, ni una cifra de V01; de una padre ya
        cerrada, «Heredado de» su última revisión. Los parámetros de V01 no cambian."""
        v1, r1 = self.create(feature="definitiva", title="Definitiva")
        bench, slope = _uid(), _uid()

        def give_v01(conn: sqlite3.Connection) -> None:
            for uid, key, rev in ((bench, "demo.bench_height", 2), (slope, "demo.slope", 1)):
                _insert(conn, "gb_parameter", parameter_row(
                    uid=uid, key=key, module="demo", scope="version", scope_uid=v1.uid, rev=rev))
                for number in range(1, rev + 1):
                    _insert(conn, "gb_parameter_history", history_row(
                        parameter_uid=uid, rev=number,
                        action="create" if number == 1 else "change"))
            # Un dato, una operación y una cifra de V01: no se heredan (error 32).
            operation = _uid()
            _insert(conn, "gb_operation", _copy_row(
                conn, "gb_operation", "op_type = 'demo.area'", uid=operation, scope="version",
                revision_uid=r1.uid, supersedes_uid=None, superseded_by=None))
            _insert(conn, "gb_dataset", _copy_row(
                conn, "gb_dataset", "name = 'demo_benches'", uid=_uid(), name="des_final",
                locator="des_final_v01", selector="", version_uid=v1.uid, input_uid=None,
                immutable=0, superseded_by=None, operation_uid=operation))
            _insert(conn, "gb_figure", {
                "uid": _uid(), "key": "demo.pit_volume", "label": "Volumen de la corta",
                "value": 1250.0, "unit": "m3", "kind": "CALCULADO", "operation_uid": operation,
                "created_at": NOW})

        self.write(give_v01)
        self.freeze(v1)  # r1 congelada, r2 abierta
        parent_rows = self.query("SELECT * FROM gb_parameter WHERE scope_uid = ? ORDER BY key",
                                 (v1.uid,))
        before = self.dump()
        v2, r2 = self.create(feature="ampliacion", title="Ampliación", parent="V01")
        after = self.dump()
        self.assertEqual((v2.parent_uid, v2.parent_revision_uid, v2.code), (v1.uid, r1.uid, "V02"))
        changed = {name for name in after if after[name] != before.get(name)}
        self.assertEqual(changed, {"gb_version", "gb_revision", "gb_parameter",
                                   "gb_parameter_history", "gb_event", "sqlite_sequence"})
        for table in ("gb_dataset", "gb_operation", "gb_figure", "gb_operation_io",
                      "gb_operation_param", "gb_stale", "gb_revision_item"):
            self.assertEqual(after[table], before[table], table)
        self.assertEqual(self.query("SELECT * FROM gb_parameter WHERE scope_uid = ? "
                                    "ORDER BY key", (v1.uid,)), parent_rows)
        with self.project.read() as conn:
            conn.row_factory = sqlite3.Row
            parents = conn.execute("SELECT * FROM gb_parameter WHERE scope_uid = ? ORDER BY key",
                                   (v1.uid,)).fetchall()
            children = conn.execute("SELECT * FROM gb_parameter WHERE scope_uid = ? "
                                    "ORDER BY key", (v2.uid,)).fetchall()
            history = conn.execute(
                "SELECT h.* FROM gb_parameter_history AS h JOIN gb_parameter AS p "
                "ON p.uid = h.parameter_uid WHERE p.scope_uid = ? ORDER BY p.key, h.rev",
                (v2.uid,)).fetchall()
        kept = ("key", "scope", "module", "value_type", "value", "unit", "kind", "source",
                "source_kind", "decided_by", "decided_at", "operation_uid", "unconfirmed",
                "review", "def_sha256", "value_sha256")
        self.assertEqual([[row[name] for name in kept] for row in children],
                         [[row[name] for name in kept] for row in parents])
        made_at = self.now()
        self.assertEqual(
            [(row["reason"], row["rev"], row["created_at"]) for row in children],
            [("Heredado de V01.r2", 1, made_at)] * 2,
        )
        self.assertNotIn(bench, {row["uid"] for row in children})
        self.assertEqual(
            [(row["parameter_uid"], row["rev"], row["action"], row["reason"], row["value"],
              row["kind"], row["decided_by"], row["changed_by"], row["changed_at"],
              row["session_uid"]) for row in history],
            [(child["uid"], 1, "create", "Heredado de V01.r2", child["value"], child["kind"],
              child["decided_by"], USER, made_at, SESSION.session_uid) for child in children],
        )
        self.assertEqual(self.events(EVENT.VERSION_CREATED)[-1].data["inherited"], 2)
        # De una padre cerrada (sin revisión abierta), «Heredado de» su última revisión.
        self.set_status(v1, "DESCARTADO", "Se descarta")
        v3, _ = self.create(feature="otra", title="Otra", parent=v1.uid)
        self.assertEqual(v3.parent_revision_uid, r1.uid)
        self.assertEqual(
            self.query("SELECT DISTINCT reason FROM gb_parameter WHERE scope_uid = ?",
                       (v3.uid,)), [("Heredado de V01.r2",)])

    def test_first_version_raises_min_reader_schema(self) -> None:
        """D-24 (spec §11; RF-002-22): crear la primera versión sube ``min_reader_schema`` de 1
        a 3 en su misma transacción (y en la cabecera al regenerarla); la segunda no lo toca;
        y un Geoblender del esquema 2 (simulado, como ``test_migration_0003``) ya solo abre la
        cabecera, sin leer la base."""
        self.assertEqual(self.query("SELECT min_reader_schema FROM gb_project"), [(1,)])
        counter = self.counter()
        self.create()
        self.assertEqual(self.counter(), counter + 1)
        self.assertEqual(self.query("SELECT min_reader_schema, modified_at FROM gb_project"),
                         [(3, self.now())])
        self.assertTrue(self.project.refresh_header())
        header = manifest_mod.read_manifest(self.root)
        self.assertEqual((header.schema_version, header.min_reader_schema), (3, 3))
        project_row = self.query("SELECT * FROM gb_project")
        self.create()
        self.assertEqual(self.query("SELECT * FROM gb_project"), project_row)
        self.project.close()
        before = self.files()
        with mock.patch.object(open_mod, "SCHEMA_VERSION", 2):
            result = open_mod.open_project(self.root, SESSION, _STATE["userdata"],
                                           clock=self.clock, pid_alive=PIDS)
        old = result.project
        try:
            self.assertTrue(old.header_only)
            self.assertEqual(old.mode, project_model.OpenMode.READ_ONLY)
            with self.assertRaises(errors.ProjectError) as caught, old.read():
                pass
            self.assertEqual(caught.exception.code, "core.project_header_only")
        finally:
            old.close()
        self.assertEqual(self.files(), before)


class StatusTest(StoreCase):
    def test_transitions_and_rejections(self) -> None:
        """RF-009-03, RF-009-04, RF-009-25: a VIGENTE solo con una revisión congelada
        («Congele antes una revisión de V01»); a DESCARTADO con motivo, y entonces su revisión
        abierta se cierra («cerrada al superarse», sin instantánea); ni SUPERADO a petición, ni
        volver a BORRADOR, ni el mismo estado, ni un estado que no existe; y una versión
        SUPERADO o DESCARTADO no cambia («V02 está en estado DESCARTADO: cree una versión nueva
        a partir de ella»). Cada cambio, con quién, cuándo y motivo, y su evento."""
        v1, _ = self.create()
        v2, r2 = self.create()
        v3, _ = self.create()

        def status(version: Any, target: Any, reason: str | None = "Prueba"
                   ) -> Callable[[sqlite3.Connection], Any]:
            uid = version if isinstance(version, str) else version.uid
            return lambda conn: store.set_status(conn, self.project, uid, target, reason=reason)

        error = self.assertRejected(("core.version_freeze_first", status(v1, "VIGENTE", None)))
        self.assertEqual(str(error), "Congele antes una revisión de V01")
        self.assertRejected(
            ("core.version_transition", status(v3, "SUPERADO")),
            ("core.version_same_state", status(v3, "BORRADOR")),
            ("core.version_state_unknown", status(v3, "ESTIMADA")),
            ("core.version_unknown", status("V99", "DESCARTADO")),
            ("core.version_text_path", status(v2, "DESCARTADO", "copiado de C:\\datos\\x")),
        )
        error = self.assertRejected(*(
            ("core.version_discard_reason", status(v2, model.VersionStatus.DESCARTADO, reason))
            for reason in (None, "", "  ")))
        self.assertEqual(str(error), "Indique el motivo para descartar V02")

        self.freeze(v1)
        change = self.set_status(v1, model.VersionStatus.VIGENTE, "La propiedad la aprueba")
        self.assertEqual((change.version.status, change.previous, change.superseded,
                          change.closed), (model.VersionStatus.VIGENTE,
                                           model.VersionStatus.BORRADOR, None, ()))
        self.assertEqual((change.version.status_changed_at, change.version.status_changed_by,
                          change.version.reason_closed), (self.now(), USER, None))
        self.assertRejected(("core.version_transition", status(v1, "BORRADOR")))

        change = self.set_status(v2, "DESCARTADO", "No sirve")
        self.assertEqual((change.version.status, change.version.reason_closed),
                         (model.VersionStatus.DESCARTADO, "No sirve"))
        closed = change.closed[0]
        self.assertEqual((closed.uid, closed.state, closed.closed_at, closed.closed_by,
                          closed.snapshot_dir), (r2.uid, model.RevisionState.CLOSED, self.now(),
                                                 USER, None))
        with self.project.read() as conn:
            self.assertIsNone(read.open_revision(conn, v2.uid))
            self.assertEqual(read.revisions(conn, v2.uid), (closed,))
        error = self.assertRejected(*(
            ("core.version_not_editable", status(v2, target, "Otra vez"))
            for target in ("VIGENTE", "DESCARTADO", "BORRADOR", "SUPERADO")))
        self.assertEqual(str(error), NOT_EDITABLE.format(code="V02", state="DESCARTADO"))

        change = self.set_status(v1, "DESCARTADO", "La propiedad la retira")
        self.assertEqual(change.previous, model.VersionStatus.VIGENTE)
        self.assertEqual(len(change.closed), 1)  # su r2 abierta
        with self.project.read() as conn:
            self.assertIsNone(read.current_version(conn))
        statuses = [(item.entity_uid, item.data["from"], item.data["to"], item.data["reason"])
                    for item in self.events(EVENT.STATUS_CHANGE)]
        self.assertEqual(statuses, [
            (v1.uid, "BORRADOR", "VIGENTE", "La propiedad la aprueba"),
            (v2.uid, "BORRADOR", "DESCARTADO", "No sirve"),
            (v1.uid, "VIGENTE", "DESCARTADO", "La propiedad la retira"),
        ])
        closings = self.events(EVENT.REVISION_CLOSED)
        self.assertEqual([(item.entity_kind, item.data["revision"]) for item in closings],
                         [("revision", "V02.r1"), ("revision", "V01.r2")])
        self.assertIn("cerrada al superarse", closings[0].message)

    def test_declaring_current_supersedes_the_previous(self) -> None:
        """HU-009-1, prueba independiente (RF-009-02, RF-009-03, RF-009-04, RF-009-25; D-3):
        V01 y V02 con una revisión congelada cada una; declarar VIGENTE la V01 y después la V02
        pasa la V01 a SUPERADO («Superada por V02») en la misma transacción (el contador de
        cambios sube una vez) y cierra su revisión abierta; solo hay una VIGENTE; ningún
        fichero distinto de la base, su diario y la cabecera cambia; y modificar la V01 se
        rechaza con el texto de RF-009-04 (cambiar su estado o su título)."""
        v1, _ = self.create(title="Definitiva")
        v2, _ = self.create(title="Ampliación")
        self.freeze(v1)
        self.freeze(v2)
        files = self.files()
        counter = self.counter()
        before = self.dump()
        self.set_status(v1, "VIGENTE", "Primera entrega")
        self.assertEqual(self.files(), files)
        change = self.set_status(v2, "VIGENTE", "Segunda entrega")
        after = self.dump()
        self.assertEqual(self.counter(), counter + 2)  # una transacción por cambio
        self.assertEqual(self.files(), files)
        self.assertEqual({name for name in after if after[name] != before[name]},
                         {*STATUS_ROWS, "sqlite_sequence"})
        superseded = change.superseded
        self.assertEqual((superseded.uid, superseded.status, superseded.reason_closed,
                          superseded.status_changed_by), (v1.uid, model.VersionStatus.SUPERADO,
                                                          "Superada por V02", USER))
        self.assertEqual([(item.version_uid, item.number, item.state) for item in change.closed],
                         [(v1.uid, 2, model.RevisionState.CLOSED)])
        with self.project.read() as conn:
            self.assertEqual(read.current_version(conn).uid, v2.uid)
            self.assertEqual(read.default_active(conn).uid, v2.uid)
            self.assertEqual([version.status.value for version in read.versions(conn)],
                             ["SUPERADO", "VIGENTE"])
            self.assertIsNone(read.open_revision(conn, v1.uid))
            self.assertIsNotNone(read.open_revision(conn, v2.uid))
        self.assertEqual([(item.entity_uid, item.data["from"], item.data["to"])
                          for item in self.events(EVENT.STATUS_CHANGE)][-2:],
                         [(v1.uid, "VIGENTE", "SUPERADO"), (v2.uid, "BORRADOR", "VIGENTE")])
        refused = ("core.version_not_editable",)
        errors_found = [self.assertRejected((*refused, work)) for work in (
            lambda conn: store.set_status(conn, self.project, v1.uid, "DESCARTADO",
                                          reason="Ya no"),
            lambda conn: store.set_title(conn, self.project, version_uid=v1.uid, title="Otro"),
            lambda conn: store.require_editable(conn, v1.uid),
        )]
        self.assertEqual({str(error) for error in errors_found},
                         {NOT_EDITABLE.format(code="V01", state="SUPERADO")})
        self.assertEqual(self.files(), files)
        with self.project.read() as conn:
            self.assertEqual(store.require_editable(conn, "V02").uid, v2.uid)


class TitleTest(StoreCase):
    def test_titles_of_versions_and_datasets(self) -> None:
        """RF-009-22, RF-009-04: el renombrado guarda el título de una versión o de un dato del
        proyecto y no cambia su código ni su nombre (evento ``title_changed``); el mismo título
        no escribe nada; sin título, de algo que no existe o de un dato de una versión que no es
        editable, se rechaza sin cambiar nada."""
        v1, _ = self.create(title="Definitiva")
        self.clock.advance(minutes=1)
        title = self.write(lambda conn: store.set_title(conn, self.project, version_uid=v1.uid,
                                                        title="  Definitiva corregida "))
        self.assertEqual(title, "Definitiva corregida")
        self.assertEqual(self.query("SELECT code, title, modified_at FROM gb_version"),
                         [("V01", "Definitiva corregida", self.now())])
        uid, name = self.query("SELECT uid, name FROM gb_dataset WHERE name = 'demo_benches'")[0]
        self.write(lambda conn: store.set_title(conn, self.project, dataset_uid=uid,
                                                title="Bancos de la corta"))
        self.assertEqual(self.query("SELECT name, title, version_uid FROM gb_dataset "
                                    "WHERE uid = ?", (uid,)),
                         [(name, "Bancos de la corta", "")])
        changes = self.events(EVENT.TITLE_CHANGED)
        self.assertEqual([(item.entity_kind, item.entity_uid, item.data["from"], item.data["to"])
                          for item in changes],
                         [("version", v1.uid, "Definitiva", "Definitiva corregida"),
                          ("dataset", uid, None, "Bancos de la corta")])
        counter = self.counter()
        self.write(lambda conn: store.set_title(conn, self.project, version_uid="V01",
                                                title="Definitiva corregida"))
        self.assertEqual((self.counter(), len(self.events(EVENT.TITLE_CHANGED))), (counter, 2))
        def titled(title: Any, **item: str) -> Callable[[sqlite3.Connection], Any]:
            return lambda conn: store.set_title(conn, self.project, title=title, **item)

        error = self.assertRejected(
            *(("core.version_title_required", titled(empty, version_uid=v1.uid))
              for empty in (None, "", "  ")),
            ("core.version_unknown", titled("Otra", version_uid="V07")),
            ("core.version_dataset_unknown", titled("Otra", dataset_uid=_uid())),
            ("core.version_text_path", titled("copiado de C:\\datos\\x", version_uid=v1.uid)),
            *(("core.version_dataset_title_required", titled(empty, dataset_uid=uid))
              for empty in (None, "", "  ")),
        )
        self.assertEqual(str(error), "Indique el título del dato «demo_benches»")
        for wrong in ({}, {"version_uid": v1.uid, "dataset_uid": uid}):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                self.write(lambda conn, wrong=wrong: store.set_title(conn, self.project,
                                                                     title="X", **wrong))
        # Un dato de una versión DESCARTADO: su título no cambia.
        r1 = self.query("SELECT uid FROM gb_revision WHERE version_uid = ?", (v1.uid,))[0][0]
        own = _uid()

        def add_dataset(conn: sqlite3.Connection) -> None:
            operation = _uid()
            _insert(conn, "gb_operation", _copy_row(
                conn, "gb_operation", "op_type = 'demo.area'", uid=operation, scope="version",
                revision_uid=r1, supersedes_uid=None, superseded_by=None))
            _insert(conn, "gb_dataset", _copy_row(
                conn, "gb_dataset", "name = 'demo_benches'", uid=own, name="des_final",
                locator="des_final_v01", selector="", version_uid=v1.uid, input_uid=None,
                immutable=0, superseded_by=None, operation_uid=operation, title=None))

        self.write(add_dataset)
        self.write(lambda conn: store.set_title(conn, self.project, dataset_uid=own,
                                                title="Diseño final"))
        self.set_status(v1, "DESCARTADO", "No sirve")
        error = self.assertRejected(("core.version_not_editable",
                                     titled("Otro", dataset_uid=own)))
        self.assertEqual(str(error), NOT_EDITABLE.format(code="V01", state="DESCARTADO"))
        self.assertEqual(self.query("SELECT title FROM gb_dataset WHERE uid = ?", (own,)),
                         [("Diseño final",)])


class SessionReadTest(StoreCase):
    """Lo que lee la versión activa de la sesión (spec 009, T18; RF-009-10; plan A11)."""

    def test_latest_revision_of_each_version_and_versioned_schema(self) -> None:
        """RF-009-10 (plan A11): ``latest_revisions`` da de cada versión la revisión que se
        enseña con ella («● V03.r2»): la abierta o, si ya no tiene (SUPERADO, DESCARTADO), la
        última, cerrada; ``has_versions`` dice si la base tiene versiones (el esquema 3 sí; un
        proyecto del esquema 2, no). Ninguna de las dos escribe nada."""
        with self.project.read() as conn:
            self.assertTrue(read.has_versions(conn))
            self.assertEqual(read.latest_revisions(conn), {})
        v1, r1 = self.create(feature="a", title="A")
        v2, _ = self.create(feature="b", title="B")
        v3, _ = self.create(feature="c", title="C")
        self.freeze(v1)
        self.set_status(v1, "VIGENTE")
        self.freeze(v2)
        self.set_status(v2, "VIGENTE")  # V01 a SUPERADO: su r2 se cierra
        self.set_status(v3, "DESCARTADO", reason="Prueba")
        counter = self.counter()
        with self.project.read() as conn:
            found = read.latest_revisions(conn)
        self.assertEqual(self.counter(), counter)
        shown = {uid: (revision.number, str(revision.state)) for uid, revision in found.items()}
        self.assertEqual(shown, {v1.uid: (2, "closed"), v2.uid: (2, "open"),
                                 v3.uid: (1, "closed")})
        with self.project.read() as conn:
            self.assertEqual(found[v2.uid], read.open_revision(conn, v2.uid))
            self.assertEqual(found[v1.uid], read.revisions(conn, v1.uid)[-1])
        self.assertNotEqual(found[v1.uid].uid, r1.uid)
        with project_tmp("gb-v5r-") as tmp:
            old = fixture.extract(tmp)  # el proyecto del esquema 2, sin migrar
            conn = sqlite3.connect(f"file:{(old / DATABASE).as_posix()}?mode=ro", uri=True)
            try:
                self.assertFalse(read.has_versions(conn))
            finally:
                conn.close()

    def test_version_and_title_of_each_dataset_for_the_view(self) -> None:
        """RF-009-30, RF-009-22 (T22; plan A11, D-36): ``dataset_titles`` da, de cada dato pedido
        que el proyecto tiene, su versión (``''``, del proyecto) y su título (``''`` sin
        título), lo que necesita la vista para poner el dato en la colección de su versión y
        su título en el nombre; uno que no está, no sale; un proyecto del esquema 2 (sin
        versiones), ninguno. No escribe nada."""
        v1, r1 = self.create(title="Definitiva")
        (benches,) = self.query("SELECT uid FROM gb_dataset WHERE name = 'demo_benches'")[0]
        (marks,) = self.query("SELECT uid FROM gb_dataset WHERE name = 'demo_marks'")[0]
        own = _uid()

        def add_dataset(conn: sqlite3.Connection) -> None:
            operation = _uid()
            _insert(conn, "gb_operation", _copy_row(
                conn, "gb_operation", "op_type = 'demo.area'", uid=operation, scope="version",
                revision_uid=r1.uid, supersedes_uid=None, superseded_by=None))
            _insert(conn, "gb_dataset", _copy_row(
                conn, "gb_dataset", "name = 'demo_benches'", uid=own, name="des_final",
                locator="des_final_v01", selector="", version_uid=v1.uid, input_uid=None,
                immutable=0, superseded_by=None, operation_uid=operation, title=None))

        self.write(add_dataset)
        self.write(lambda conn: store.set_title(conn, self.project, dataset_uid=benches,
                                                title="Bancos de la corta"))
        counter, files = self.counter(), self.files()
        with self.project.read() as conn:
            found = read.dataset_titles(conn, [benches, own, marks, _uid(), own])
            self.assertEqual(read.dataset_titles(conn, []), {})
        self.assertEqual(found, {benches: ("", "Bancos de la corta"), own: (v1.uid, ""),
                                 marks: ("", "")})
        self.assertEqual((self.counter(), self.files()), (counter, files))
        with project_tmp("gb-v5t-") as tmp:
            old = fixture.extract(tmp)  # el proyecto del esquema 2, sin migrar
            conn = sqlite3.connect(f"file:{(old / DATABASE).as_posix()}?mode=ro", uri=True)
            try:
                self.assertEqual(read.dataset_titles(conn, [benches]), {})
            finally:
                conn.close()


class NoDeleteTest(StoreCase):
    def test_no_api_deletes_and_reads_do_not_write(self) -> None:
        """RF-009-12: ninguna función de ``core.versions.store`` borra ni sustituye una fila
        (ninguna sentencia ``DELETE``, ``DROP`` ni ``REPLACE`` al crear, heredar, cambiar de
        estado y de título; tampoco la ofrece: ninguna función pública borra o quita); y las
        lecturas de ``core.versions.read`` no mueven el contador de cambios de la base ni
        ningún fichero."""
        statements: list[str] = []

        def traced(work: Callable[[sqlite3.Connection], Any]) -> Any:
            def run(conn: sqlite3.Connection) -> Any:
                conn.set_trace_callback(statements.append)
                try:
                    return work(conn)
                finally:
                    conn.set_trace_callback(None)

            self.clock.advance(minutes=1)
            return self.write(run)

        v1, _ = traced(lambda conn: store.create_version(
            conn, self.project, feature="a", title="A", reason="Prueba"))
        self.freeze(v1)
        traced(lambda conn: store.set_status(conn, self.project, v1.uid, "VIGENTE"))
        v2, _ = traced(lambda conn: store.create_version(
            conn, self.project, feature="b", title="B", reason="Prueba", parent="V01"))
        self.freeze(v2)
        traced(lambda conn: store.set_title(conn, self.project, version_uid=v2.uid, title="B2"))
        traced(lambda conn: store.set_status(conn, self.project, v2.uid, "VIGENTE"))
        traced(lambda conn: store.set_status(conn, self.project, v2.uid, "DESCARTADO",
                                             reason="Prueba"))
        self.assertTrue(statements)
        written = [text for text in statements if not text.lstrip().startswith("--")]
        for text in written:
            upper = text.upper()
            with self.subTest(statement=text[:60]):
                self.assertNotIn("DELETE", upper)
                self.assertNotIn("DROP", upper)
                self.assertNotIn("REPLACE", upper)
        public = [name for name in dir(store) if not name.startswith("_")]
        self.assertFalse([name for name in public
                          if any(word in name.lower() for word in ("delete", "remove", "drop",
                                                                   "purge", "erase"))])
        counter, files = self.counter(), self.files()
        with self.project.read() as conn:
            versions = read.versions(conn)
            for version in versions:
                read.version(conn, version.uid)
                read.version(conn, version.code)
                read.revisions(conn, version.uid)
                read.open_revision(conn, version.uid)
                read.last_frozen(conn, version.uid)
            read.current_version(conn)
            read.default_active(conn)
        self.assertEqual(len(versions), 2)
        self.assertEqual((self.counter(), self.files()), (counter, files))


if __name__ == "__main__":
    unittest.main()
