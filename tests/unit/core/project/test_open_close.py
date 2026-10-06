# SPDX-License-Identifier: GPL-3.0-or-later
"""Abrir y cerrar un proyecto (spec 002, T16; RF-002-04, RF-002-05, RF-002-06, RF-002-08,
RF-002-09, RF-002-10, RF-002-17; plan 002 §5.3 y §5.4).

Abrir recorre seis fases, cada una un paso de progreso (en red puede pasar de 1 s): leer
la cabecera, leer la base de datos sin escribir, comprobar que coinciden (si no, no abre y
muestra los dos valores), el esquema, el cerrojo y abrir. Con el cerrojo libre o huérfano
se abre en escritura y se registra; con otra sesión, en solo lectura con quién lo tiene;
uno caducado se fuerza solo con el titular que vio el usuario. Cerrar registra el evento,
reescribe la cabecera desde la base de datos y libera solo el cerrojo propio.
"""

import json
import sqlite3
import unittest
from pathlib import Path

from tests.support.core_fixtures import (
    FakeClock,
    FakePids,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.package import import_geoblender

project = import_geoblender("core.project")
create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
model = import_geoblender("core.project.model")
manifest = import_geoblender("core.project.manifest")
schema = import_geoblender("core.project.schema")
events = import_geoblender("core.project.events")
lock = import_geoblender("core.project.lock")
errors = import_geoblender("core.errors")
gpkg = import_geoblender("core.gpkg")
userdata_mod = import_geoblender("core.userdata")

SESSION_A = make_session()
SESSION_A2 = make_session(session_uid="00000000-0000-4000-8000-0000000000a2", pid=5151)
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra", pid=777
)
WAL_PRAGMA = "PRAGMA journal_mode=" + "WAL"


class Env:
    """Un proyecto recién creado por la sesión A en una carpeta temporal."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.parent = tmp / "proyectos"
        self.parent.mkdir()
        self.userdata = userdata_mod.UserData(tmp / "datos_usuario")
        self.clock = FakeClock()
        self.pids = FakePids({SESSION_A.pid, SESSION_A2.pid, SESSION_B.pid})
        self.created = create.create_project(
            self.parent, make_settings(), SESSION_A, self.userdata, clock=self.clock
        )
        self.root = self.created.root

    def open(self, session, **kwargs):
        kwargs.setdefault("clock", self.clock)
        kwargs.setdefault("pid_alive", self.pids)
        return open_mod.open_project(self.root, session, self.userdata, **kwargs)

    def events(self) -> list[str]:
        with gpkg.GpkgConnection.open_read(self.root / "project.gpkg") as db:
            return [item.kind for item in events.read_events(db.connection)]

    def dump(self) -> list[str]:
        conn = sqlite3.connect(self.root / "project.gpkg")
        try:
            return list(conn.iterdump())
        finally:
            conn.close()


class OpenCloseTest(unittest.TestCase):
    def test_create_close_reopen_same_georeference(self) -> None:
        """RF-002-04, RF-002-06: crear → cerrar → abrir con otra sesión da los mismos uid,
        CRS, ventana y GeoOrigin, en escritura y con el cerrojo de la nueva sesión."""
        with project_tmp() as tmp:
            env = Env(tmp)
            created = env.created.project
            self.assertTrue(created.writable)
            self.assertEqual(created.mode, model.OpenMode.WRITE_LOCAL)
            created.close()
            self.assertFalse((env.root / ".lock").exists())
            result = env.open(SESSION_B)
            opened = result.project
            try:
                self.assertEqual(opened.mode, model.OpenMode.WRITE_LOCAL)
                for name in ("uid", "crs_epsg", "crs_wkt", "vcrs_epsg", "window", "origin",
                             "grid_step_m"):
                    self.assertEqual(getattr(opened.record, name),
                                     getattr(env.created.record, name), name)
                self.assertEqual(opened.uid, env.created.record.uid)
                holder = lock.read_holder(env.root, clock=env.clock)
                self.assertEqual(holder.session_uid, SESSION_B.session_uid)
            finally:
                opened.close()

    def test_header_with_other_origin_does_not_open(self) -> None:
        """RF-002-05: con la cabecera editada a mano con otro GeoOrigin, el proyecto no
        abre, el error muestra el valor de la cabecera y el de la base de datos, y no se
        corrige ni se crea nada."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            path = env.root / "manifest.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["geo_origin"]["x0"] = 700_100
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            before = (path.read_bytes(), env.dump(), sorted(p.name for p in env.root.iterdir()))
            with self.assertRaises(errors.ProjectError) as caught:
                env.open(SESSION_B)
            self.assertEqual(caught.exception.code, "core.project_inconsistent")
            self.assertIn("geo_origin.x0", str(caught.exception))
            self.assertIn("700100", str(caught.exception))
            self.assertIn("700000", str(caught.exception))
            after = (path.read_bytes(), env.dump(), sorted(p.name for p in env.root.iterdir()))
            self.assertEqual(after, before)

    def test_missing_parts_do_not_open(self) -> None:
        """RF-002-05: sin carpeta, sin cabecera o sin base de datos, el proyecto no abre y
        el error dice qué falta."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            with self.assertRaises(errors.ProjectError) as caught:
                open_mod.open_project(env.parent / "Otro.gbproj", SESSION_B, env.userdata)
            self.assertEqual(caught.exception.code, "core.project_missing")
            (env.root / "project.gpkg").rename(env.root / "aparte.gpkg")
            with self.assertRaises(errors.ProjectError) as caught:
                env.open(SESSION_B)
            self.assertEqual(caught.exception.code, "core.project_database_missing")
            (env.root / "aparte.gpkg").rename(env.root / "project.gpkg")
            (env.root / "manifest.json").unlink()
            with self.assertRaises(errors.ProjectError) as caught:
                env.open(SESSION_B)
            self.assertEqual(caught.exception.code, "core.manifest_missing")
            self.assertFalse((env.root / ".lock").exists())

    def test_close_rewrites_header_and_releases_own_lock(self) -> None:
        """RF-002-06: cerrar actualiza la cabecera desde la base de datos y borra el
        cerrojo de esta sesión."""
        with project_tmp() as tmp:
            env = Env(tmp)
            path = env.root / "manifest.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["modified_at"] = "2020-01-01T00:00:00.000Z"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            env.created.project.close()
            with gpkg.GpkgConnection.open_read(env.root / "project.gpkg") as db:
                record = schema.read_project(db.connection)
            self.assertEqual(manifest.read_manifest(env.root), manifest.manifest_from_record(record))
            self.assertFalse((env.root / ".lock").exists())

    def test_close_keeps_foreign_lock(self) -> None:
        """RF-002-06, RF-002-12: si otra sesión se ha quedado el cerrojo, cerrar no lo
        borra ni escribe nada en el proyecto."""
        with project_tmp() as tmp:
            env = Env(tmp)
            opened = env.created.project
            env.clock.advance(minutes=31)
            seen = lock.inspect(env.root, SESSION_B, clock=env.clock, pid_alive=env.pids)
            lock.force(env.root, SESSION_B, lock.LockMode.LOCAL, seen.holder, clock=env.clock,
                       pid_alive=env.pids)
            foreign = (env.root / ".lock").read_bytes()
            before = ((env.root / "manifest.json").read_bytes(), env.dump())
            with self.assertLogs("geoblender.core.project", "WARNING") as logged:
                warnings = opened.close()
            self.assertTrue(warnings)
            self.assertIn("lock_lost", logged.output[0])
            self.assertEqual((env.root / ".lock").read_bytes(), foreign)
            self.assertEqual(((env.root / "manifest.json").read_bytes(), env.dump()), before)

    def test_open_and_close_events(self) -> None:
        """RF-002-04, RF-002-06: abrir y cerrar en escritura quedan registrados (``open`` y
        ``close``) con la sesión; abrir y cerrar en solo lectura no escribe nada."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            env.open(SESSION_B).project.close()
            self.assertEqual(env.events(), ["create", "close", "open", "close"])
            with gpkg.GpkgConnection.open_read(env.root / "project.gpkg") as db:
                found = events.read_events(db.connection)
            self.assertEqual(found[2].session_uid, SESSION_B.session_uid)
            self.assertEqual(found[2].user_host, "otra@PC-PRUEBA-B")
            env.open(SESSION_A, want_write=False).project.close()
            self.assertEqual(env.events(), ["create", "close", "open", "close"])

    def test_recent_projects(self) -> None:
        """RF-002-08: abrir y cerrar dejan el proyecto el primero de los recientes del
        equipo."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            env.userdata.add_recent("00000000-0000-4000-8000-0000000000ff", "Otro",
                                    tmp / "otro.gbproj", "2026-10-05T07:00:00.000Z")
            env.open(SESSION_B).project.close()
            recent = env.userdata.recent_projects()
            self.assertEqual(recent[0].uid, env.created.record.uid)
            self.assertEqual(recent[0].path, env.root)


class OpenStepsTest(unittest.TestCase):
    def test_steps_cover_every_phase(self) -> None:
        """RF-002-04: ``open_steps`` emite al menos un paso por fase (cabecera, base de
        datos, coherencia, esquema, cerrojo y apertura), en orden y con el total, y su
        último paso da el mismo resultado que ``open_project``."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            steps = list(open_mod.open_steps(env.root, SESSION_B, env.userdata,
                                             clock=env.clock, pid_alive=env.pids))
            phases = [step.phase for step in steps]
            self.assertEqual(list(dict.fromkeys(phases)), list(open_mod.PHASES))
            self.assertTrue(all(step.total == len(open_mod.PHASES) for step in steps))
            self.assertEqual([step.done for step in steps], sorted(step.done for step in steps))
            self.assertTrue(all(step.result is None for step in steps[:-1]))
            stepped = steps[-1].result
            stepped.project.close()
            direct = env.open(SESSION_B)
            direct.project.close()
            self.assertEqual(stepped.status, direct.status)
            self.assertEqual(stepped.project.record.uid, direct.project.record.uid)
            self.assertEqual(stepped.project.record.origin, direct.project.record.origin)
            self.assertEqual(stepped.warnings, direct.warnings)

    def test_cancel_releases_lock(self) -> None:
        """RF-002-04: cancelar la apertura después de tomar el cerrojo lo libera."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            steps = open_mod.open_steps(env.root, SESSION_B, env.userdata,
                                        clock=env.clock, pid_alive=env.pids)
            for step in steps:
                if step.phase == "apertura":
                    break
            self.assertTrue((env.root / ".lock").exists())
            steps.close()
            self.assertFalse((env.root / ".lock").exists())


class LockOnOpenTest(unittest.TestCase):
    def test_locked_opens_read_only(self) -> None:
        """RF-002-09: con el proyecto abierto por otra sesión viva, se abre en solo
        lectura indicando su equipo, usuario y hora, sin escribir nada."""
        with project_tmp() as tmp:
            env = Env(tmp)
            holder = env.created.project
            before = ((env.root / ".lock").read_bytes(), env.dump(),
                      (env.root / "manifest.json").read_bytes())
            result = env.open(SESSION_B)
            self.assertEqual(result.project.mode, model.OpenMode.READ_ONLY)
            self.assertEqual(result.project.read_only_reason, model.ReadOnlyCode.LOCKED)
            for expected in ("prueba", "PC-PRUEBA-A", "05/10/2026"):
                self.assertIn(expected, result.status.message)
            self.assertEqual(result.lock_status.state, lock.LockState.ACTIVE)
            self.assertFalse(result.lock_status.can_force)
            result.project.close()
            after = ((env.root / ".lock").read_bytes(), env.dump(),
                     (env.root / "manifest.json").read_bytes())
            self.assertEqual(after, before)
            holder.close()

    def test_read_only_on_request(self) -> None:
        """RF-002-13: abierto en solo lectura a petición, sin cerrojo."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            result = env.open(SESSION_B, want_write=False)
            self.assertEqual(result.project.read_only_reason, model.ReadOnlyCode.REQUESTED)
            self.assertFalse((env.root / ".lock").exists())
            with result.project.read() as conn:
                self.assertEqual(schema.read_project(conn).uid, env.created.record.uid)
            with self.assertRaises(errors.ProjectError):
                with result.project.write_transaction():
                    pass
            result.project.close()

    def test_orphan_lock_replaced_and_registered(self) -> None:
        """RF-002-04: el cerrojo de un Blender de este equipo que se cerró de golpe se
        sustituye al abrir y queda registrado (``lock_orphan_replaced``)."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.pids.kill(SESSION_A.pid)
            result = env.open(SESSION_A2)
            self.assertEqual(result.project.mode, model.OpenMode.WRITE_LOCAL)
            result.project.close()
            self.assertEqual(env.events(), ["create", "lock_orphan_replaced", "open", "close"])

    def test_stale_lock_forced_with_seen_holder(self) -> None:
        """RF-002-10: un cerrojo de otra sesión sin renovar desde hace 31 min deja el
        proyecto en solo lectura con la oferta de forzarlo; forzarlo con el titular que se
        vio abre en escritura y registra el anterior (``lock_forced``)."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.clock.advance(minutes=31)
            first = env.open(SESSION_B)
            self.assertEqual(first.project.read_only_reason, model.ReadOnlyCode.LOCKED)
            self.assertTrue(first.lock_status.can_force)
            self.assertIn("perder", first.lock_status.force_warning())
            first.project.close()
            result = env.open(SESSION_B, force_holder=first.lock_status.holder)
            self.assertEqual(result.project.mode, model.OpenMode.WRITE_LOCAL)
            result.project.close()
            with gpkg.GpkgConnection.open_read(env.root / "project.gpkg") as db:
                forced = events.read_events(db.connection, events.EventKind.LOCK_FORCED)
            self.assertEqual(len(forced), 1)
            self.assertEqual(forced[0].data["holder"]["session_uid"], SESSION_A.session_uid)


class OpenDetailsTest(unittest.TestCase):
    def test_wal_left_by_qgis_is_recovered(self) -> None:
        """RF-002-17: una base que QGIS dejó en WAL (ya cerrado) vuelve al diario clásico
        al abrir en escritura, con aviso y evento ``wal_recovered``, sin perder filas."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            conn = sqlite3.connect(env.root / "project.gpkg", isolation_level=None)
            try:
                conn.execute(WAL_PRAGMA)
                conn.execute("CREATE TABLE capa_qgis (fid INTEGER PRIMARY KEY, a TEXT)")
                conn.execute("INSERT INTO capa_qgis (a) VALUES ('editado en QGIS')")
            finally:
                conn.close()
            self.assertEqual(gpkg.read_header(env.root / "project.gpkg").journal, "wal")
            result = env.open(SESSION_B)
            self.assertEqual(result.project.mode, model.OpenMode.WRITE_LOCAL)
            self.assertTrue(any("WAL" in item for item in result.warnings))
            result.project.close()
            self.assertEqual(gpkg.read_header(env.root / "project.gpkg").journal, "classic")
            self.assertIn("wal_recovered", env.events())
            with gpkg.GpkgConnection.open_read(env.root / "project.gpkg") as db:
                row = db.connection.execute("SELECT a FROM capa_qgis").fetchone()
            self.assertEqual(row[0], "editado en QGIS")

    def test_header_rewritten_when_only_dates_differ(self) -> None:
        """RF-002-05, RF-002-06: si la cabecera solo difiere en fechas o versión, se abre y
        se regenera desde la base de datos (``manifest_rewritten``)."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            path = env.root / "manifest.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["geoblender_version"] = "0.0.9"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = env.open(SESSION_B)
            self.assertEqual(manifest.read_manifest(env.root).geoblender_version, "0.1.0")
            result.project.close()
            self.assertIn("manifest_rewritten", env.events())

    def test_cache_dir(self) -> None:
        """RF-002-30 (plan 002 §5.2): en disco local y escritura la caché es
        ``<proyecto>/cache``; en solo lectura, ``cache/<uid>/`` de los datos de usuario.
        Calcularla no crea nada en el proyecto."""
        with project_tmp() as tmp:
            env = Env(tmp)
            writer = env.created.project
            self.assertEqual(writer.cache_dir(), env.root / "cache")
            reader = env.open(SESSION_B).project
            self.assertEqual(reader.cache_dir(), env.userdata.cache_dir(env.created.record.uid))
            self.assertFalse((env.root / "cache").exists())
            reader.close()
            writer.close()

    def test_api_exports(self) -> None:
        """RF-002-01, RF-002-04: el paquete ``core.project`` reexporta la API pública."""
        for name in ("create_project", "open_project", "open_steps", "inspect_project",
                     "Project", "ProjectSettings", "OpenMode", "ReadOnlyCode"):
            self.assertTrue(hasattr(project, name), name)


class RefreshHeaderTest(unittest.TestCase):
    """``Project.refresh_header()``: la cabecera se reescribe desde la base al guardar la
    vista (RF-002-07; plan 002 §5.4, ``save_post``)."""

    def test_rewrites_header_from_database(self) -> None:
        """RF-002-07: en escritura, una cabecera que difiere de la base (aquí, la fecha de
        modificación) se reescribe desde la base y se devuelve ``True``; si ya coincide,
        no se toca el fichero y se devuelve ``False``. El proyecto sigue en escritura."""
        with project_tmp() as tmp:
            env = Env(tmp)
            opened = env.created.project
            path = env.root / "manifest.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["modified_at"] = "2020-01-01T00:00:00.000Z"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.assertTrue(opened.refresh_header())
            with gpkg.GpkgConnection.open_read(env.root / "project.gpkg") as db:
                record = schema.read_project(db.connection)
            self.assertEqual(manifest.read_manifest(env.root), manifest.manifest_from_record(record))
            before = (path.read_bytes(), path.stat().st_mtime_ns)
            self.assertFalse(opened.refresh_header())
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            self.assertTrue(opened.writable)
            self.assertTrue((env.root / ".lock").exists())
            opened.close()

    def test_read_only_writes_nothing(self) -> None:
        """RF-002-07, RF-002-13: en solo lectura no se escribe la cabecera."""
        with project_tmp() as tmp:
            env = Env(tmp)
            reader = env.open(SESSION_B).project
            self.assertFalse(reader.writable)
            path = env.root / "manifest.json"
            before = (path.read_bytes(), path.stat().st_mtime_ns)
            self.assertFalse(reader.refresh_header())
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            reader.close()
            env.created.project.close()

    def test_lost_lock_writes_nothing(self) -> None:
        """RF-002-07, RF-002-12: si otra sesión se ha quedado el cerrojo, no se escribe la
        cabecera, el proyecto pasa a solo lectura «cerrojo perdido» y se informa."""
        with project_tmp() as tmp:
            env = Env(tmp)
            opened = env.created.project
            env.clock.advance(minutes=31)
            seen = lock.inspect(env.root, SESSION_B, clock=env.clock, pid_alive=env.pids)
            lock.force(env.root, SESSION_B, lock.LockMode.LOCAL, seen.holder, clock=env.clock,
                       pid_alive=env.pids)
            path = env.root / "manifest.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["modified_at"] = "2020-01-01T00:00:00.000Z"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            before = path.read_bytes()
            with self.assertLogs("geoblender.core.project", "WARNING"):
                with self.assertRaises(errors.LockError):
                    opened.refresh_header()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(opened.read_only_reason, model.ReadOnlyCode.LOCK_LOST)
            opened.close()


if __name__ == "__main__":
    unittest.main()
