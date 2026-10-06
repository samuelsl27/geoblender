# SPDX-License-Identifier: GPL-3.0-or-later
"""Cambiar la ventana de trabajo y con ella el GeoOrigin (spec 002, T27; RF-002-24,
RF-002-27; ADR-0005 §2, «Mover origen»; plan 002 §5.3, ``Project.set_window``).

El origen nuevo (centro de la ventana ampliada, empates hacia arriba) se guarda en la base
de datos y en la cabecera, con un evento ``move_origin`` que lleva el motivo
(obligatorio) y los dos orígenes. Ninguna coordenada absoluta guardada cambia: las capas
del proyecto quedan byte a byte. Sin motivo, en solo lectura, con la ventana fuera del CRS
o sin el cerrojo, no cambia nada.
"""

import json
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from tests.support.core_fixtures import FakeClock, FakePids, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
model = import_geoblender("core.project.model")
schema = import_geoblender("core.project.schema")
manifest_mod = import_geoblender("core.project.manifest")
events_mod = import_geoblender("core.project.events")
lock = import_geoblender("core.project.lock")
errors = import_geoblender("core.errors")
gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
origin_mod = import_geoblender("core.georef.origin")
userdata_mod = import_geoblender("core.userdata")

SESSION_A = make_session()
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra", pid=777
)
# Una capa con coordenadas absolutas con milímetros (no debe cambiar al mover el origen).
POLYGON = [[[
    (700_123.456, 4_400_987.654),
    (700_223.456, 4_400_987.654),
    (700_223.456, 4_401_087.654),
    (700_123.456, 4_400_987.654),
]]]
NEW_WINDOW = origin_mod.Window(700_500.4, 4_399_500.6, 701_500.2, 4_400_500.9)


class Env:
    """Un proyecto abierto en escritura por la sesión A, con una capa de límites."""

    def __init__(self, tmp: Path) -> None:
        self.userdata = userdata_mod.UserData(tmp / "datos_usuario")
        self.clock = FakeClock()
        self.pids = FakePids({SESSION_A.pid, SESSION_B.pid})
        parent = tmp / "proyectos"
        parent.mkdir()
        self.created = create.create_project(
            parent, make_settings(), SESSION_A, self.userdata, clock=self.clock
        )
        self.project = self.created.project
        self.root = self.created.root
        with self.project.write_transaction() as conn:
            base.create_feature_table(
                conn, "gis_limites", "MULTIPOLYGON", 25830, False, [], identifier="Límites"
            )
            blob = gpkg.encode_geometry("MULTIPOLYGON", POLYGON, 25830, False)
            conn.execute("INSERT INTO gis_limites (geom) VALUES (?)", (blob,))

    def layer(self) -> list[tuple]:
        conn = sqlite3.connect(self.root / "project.gpkg")
        try:
            return conn.execute("SELECT fid, geom FROM gis_limites ORDER BY fid").fetchall()
        finally:
            conn.close()

    def dump(self) -> list[str]:
        conn = sqlite3.connect(self.root / "project.gpkg")
        try:
            return list(conn.iterdump())
        finally:
            conn.close()

    def state(self) -> tuple[list[str], bytes]:
        return self.dump(), (self.root / "manifest.json").read_bytes()

    def record(self):
        with gpkg.GpkgConnection.open_read(self.root / "project.gpkg") as db:
            return schema.read_project(db.connection)

    def events(self, kind=None) -> list:
        with gpkg.GpkgConnection.open_read(self.root / "project.gpkg") as db:
            return events_mod.read_events(db.connection, kind)


class SetWindowTest(unittest.TestCase):
    def test_moves_origin_in_database_header_and_event(self) -> None:
        """RF-002-27, RF-002-24: con motivo, la ventana se amplía, el GeoOrigin nuevo
        (701 000; 4 400 000; 0) queda en la base y en la cabecera, hay un evento
        ``move_origin`` con el motivo y los dos orígenes, y la capa de límites (coordenadas
        absolutas) no cambia ni un byte."""
        with project_tmp() as tmp:
            env = Env(tmp)
            layer = env.layer()
            moved = env.project.set_window(NEW_WINDOW, 1.0, 0, "  Ampliación hacia el este  ")
            self.assertEqual((moved.x0, moved.y0, moved.z0), (701_000, 4_400_000, 0))
            record = env.record()
            self.assertEqual((record.origin_x, record.origin_y, record.origin_z), (701_000, 4_400_000, 0))
            self.assertEqual(
                (record.window_xmin, record.window_ymin, record.window_xmax, record.window_ymax),
                (700_500.0, 4_399_500.0, 701_501.0, 4_400_501.0),
            )
            header = manifest_mod.read_manifest(env.root)
            self.assertEqual((header.origin.x0, header.origin.y0), (701_000, 4_400_000))
            self.assertIs(
                manifest_mod.compare(header, record, ()).status,
                manifest_mod.ManifestStatus.CONSISTENT,
            )
            self.assertEqual(env.project.origin, moved)
            (event,) = env.events(events_mod.EventKind.MOVE_ORIGIN)
            self.assertIn("Ampliación hacia el este", event.message)
            self.assertEqual(event.data["reason"], "Ampliación hacia el este")
            self.assertEqual(event.data["from"], [700_000, 4_400_000, 0])
            self.assertEqual(event.data["to"], [701_000, 4_400_000, 0])
            self.assertEqual(env.layer(), layer)
            env.project.close()
            reopened = open_mod.open_project(
                env.root, SESSION_B, env.userdata, clock=env.clock, pid_alive=env.pids
            ).project
            self.assertEqual(reopened.origin, moved)
            reopened.close()

    def test_step_and_z0(self) -> None:
        """RF-002-24, RF-002-27: con paso 1,5 m la ventana se amplía a múltiplos de 3 m y
        Z0 se guarda."""
        with project_tmp() as tmp:
            env = Env(tmp)
            moved = env.project.set_window(NEW_WINDOW, 1.5, -180, "Cotas de la base")
            record = env.record()
            self.assertEqual(moved.z0, -180)
            self.assertEqual(record.grid_step_m, 1.5)
            self.assertEqual(record.window_xmin % 3, 0)
            self.assertEqual(record.window_xmax % 3, 0)
            env.project.close()

    def test_origin_from_the_aligned_window(self) -> None:
        """RF-002-24, RF-002-27 (hueco de prueba I6 de la verificación; convergencia, T52):
        al cambiar la ventana, el origen nuevo sale del centro de la ventana ya ampliada, no
        de la tecleada. X de 700 000,0 a 700 099,6 con paso 1 → 700 000–700 100 y
        X0 = 700 100 (con la tecleada saldría 700 000, el origen de antes); con paso 1,5
        (unidad de alineación 3 m) → 699 999–700 101 y X0 = 700 100. La base, la cabecera y
        el evento ``move_origin`` llevan ese origen."""
        typed = origin_mod.Window(700_000.0, 4_399_500.0, 700_099.6, 4_400_500.0)
        expected = (700_100, 4_400_000, 0)
        for step, aligned_x in ((1.0, (700_000.0, 700_100.0)), (1.5, (699_999.0, 700_101.0))):
            with self.subTest(paso=step), project_tmp() as tmp:
                env = Env(tmp)
                moved = env.project.set_window(typed, step, 0, "Ventana de la prueba I6")
                self.assertEqual(moved.as_tuple(), expected)
                record = env.record()
                self.assertEqual((record.window_xmin, record.window_xmax), aligned_x)
                self.assertEqual(record.origin.as_tuple(), expected)
                header = manifest_mod.read_manifest(env.root)
                self.assertEqual(header.origin.as_tuple(), expected)
                (event,) = env.events(events_mod.EventKind.MOVE_ORIGIN)
                self.assertEqual(event.data["to"], list(expected))
                env.project.close()

    def test_rejected_without_change(self) -> None:
        """RF-002-27, RF-002-03: sin motivo (vacío o en blanco), con un motivo que lleva una
        ruta absoluta, con la ventana fuera del ámbito del CRS, con un paso o una Z0 que no
        valen, no cambia nada (volcado SQL y cabecera idénticos) y el error nombra el
        campo."""
        with project_tmp() as tmp:
            env = Env(tmp)
            before = env.state()
            cases = (
                ((NEW_WINDOW, 1.0, 0, ""), "motivo"),
                ((NEW_WINDOW, 1.0, 0, "   "), "motivo"),
                ((NEW_WINDOW, 1.0, 0, "copiado de C:\\datos\\x"), "motivo"),
                ((origin_mod.Window(4_399_500, 700_000, 4_400_500, 701_000), 1.0, 0, "x"),
                 "ventana"),
                ((NEW_WINDOW, 0.3, 0, "x"), "paso"),
                ((NEW_WINDOW, 1.0, 20_000, "x"), "z0"),
            )
            for args, field in cases:
                with self.subTest(campo=field, args=args[1:]):
                    with self.assertRaises(errors.ValidationError) as caught:
                        env.project.set_window(*args)
                    self.assertIn(field, str(caught.exception).lower())
                    self.assertEqual(env.state(), before)
            self.assertTrue(env.project.writable)
            env.project.close()

    def test_read_only_or_lost_lock_writes_nothing(self) -> None:
        """RF-002-13, RF-002-12: en solo lectura no se puede cambiar la ventana; sin el
        cerrojo, tampoco, y el proyecto pasa a solo lectura «cerrojo perdido»."""
        with project_tmp() as tmp:
            env = Env(tmp)
            reader = open_mod.open_project(
                env.root, SESSION_B, env.userdata, clock=env.clock, pid_alive=env.pids
            ).project
            before = env.state()
            with self.assertRaises(errors.ProjectError) as caught:
                reader.set_window(NEW_WINDOW, 1.0, 0, "x")
            self.assertEqual(caught.exception.code, "core.project_read_only")
            self.assertEqual(env.state(), before)
            reader.close()
            env.clock.advance(minutes=31)
            seen = lock.inspect(env.root, SESSION_B, clock=env.clock, pid_alive=env.pids)
            lock.force(env.root, SESSION_B, lock.LockMode.LOCAL, seen.holder, clock=env.clock,
                       pid_alive=env.pids)
            before = env.state()
            with self.assertLogs("geoblender.core.project", "WARNING"):
                with self.assertRaises(errors.LockError):
                    env.project.set_window(NEW_WINDOW, 1.0, 0, "x")
            self.assertEqual(env.state(), before)
            self.assertEqual(env.project.read_only_reason, model.ReadOnlyCode.LOCK_LOST)
            env.project.close()


MOVED = (701_000, 4_400_000, 0)
HEADER_FAILURE = OSError(5, "red caída (simulada)")


class HeaderFailureTest(unittest.TestCase):
    """La cabecera no se puede escribir después de confirmar el origen nuevo en la base
    (convergencia, T40; RF-002-05 de la spec 0.4, enmienda aprobada el 06/10/2026): la
    base manda y el proyecto sigue abriéndose."""

    def fail_header(self, env: Env) -> object:
        with (
            mock.patch.object(manifest_mod.os, "replace", side_effect=HEADER_FAILURE),
            self.assertLogs("geoblender.core.project", "WARNING") as logged,
        ):
            moved = env.project.set_window(NEW_WINDOW, 1.0, 0, "Ampliación hacia el este")
        self.assertTrue(any("write_failed" in line for line in logged.output), logged.output)
        return moved

    def test_header_failure_after_commit_goes_read_only(self) -> None:
        """RF-002-27, RF-002-12: si ``os.replace`` de la cabecera falla después de
        confirmar la transacción, el origen nuevo queda en la base (y en el proyecto de la
        sesión), la cabecera anterior intacta y sin temporal, y el proyecto pasa a solo
        lectura «fallo de escritura» con un aviso que lo explica y suelta su cerrojo."""
        with project_tmp() as tmp:
            env = Env(tmp)
            header = (env.root / "manifest.json").read_bytes()
            moved = self.fail_header(env)
            self.assertEqual(moved.as_tuple(), MOVED)
            self.assertEqual(env.project.origin.as_tuple(), MOVED)
            self.assertEqual(env.record().origin.as_tuple(), MOVED)
            self.assertEqual((env.root / "manifest.json").read_bytes(), header)
            self.assertEqual(sorted(p.name for p in env.root.glob("manifest.json*")),
                             ["manifest.json"])
            self.assertFalse(env.project.writable)
            self.assertIs(env.project.read_only_reason, model.ReadOnlyCode.WRITE_FAILED)
            notices = env.project.take_notices()
            self.assertEqual(len(notices), 1, notices)
            self.assertIn("cabecera", notices[0])
            self.assertIn("701000", notices[0].replace(" ", "").replace(" ", ""))
            self.assertFalse((env.root / ".lock").exists())
            self.assertEqual(env.project.close(), ())

    def test_lost_session_reopens_with_regenerated_header(self) -> None:
        """RF-002-05, RF-002-27: tras ese fallo, aunque la sesión se pierda sin cerrar
        (Blender cerrado de golpe), otra sesión abre el proyecto en escritura: la
        diferencia de GeoOrigin la explica el último evento ``move_origin`` (de = la
        cabecera, a = la base), así que la cabecera se regenera desde la base (evento
        ``manifest_rewritten`` y aviso), igual que con una migración."""
        with project_tmp() as tmp:
            env = Env(tmp)
            self.fail_header(env)
            # La sesión A se pierde: no se llama a close().
            opened = open_mod.open_project(
                env.root, SESSION_B, env.userdata, clock=env.clock, pid_alive=env.pids
            )
            self.assertTrue(opened.project.writable, opened.status.message)
            self.assertEqual(opened.project.origin.as_tuple(), MOVED)
            self.assertTrue(any("geo_origin" in text for text in opened.warnings), opened.warnings)
            header = manifest_mod.read_manifest(env.root)
            self.assertEqual(header.origin.as_tuple(), MOVED)
            self.assertIs(
                manifest_mod.compare(header, env.record()).status,
                manifest_mod.ManifestStatus.CONSISTENT,
            )
            kinds = [item.kind for item in env.events()]
            self.assertEqual(kinds[-2:], ["manifest_rewritten", "open"])
            opened.project.close()

    def test_unexplained_origin_still_blocks(self) -> None:
        """RF-002-05: una cabecera con un GeoOrigin que no es el de antes del último
        cambio registrado (editada a mano, de otro proyecto) sigue sin abrir, con los dos
        valores, y no se corrige nada."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.project.set_window(NEW_WINDOW, 1.0, 0, "Ampliación hacia el este")
            env.project.close()
            path = env.root / "manifest.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["geo_origin"]["x0"] = 699_000
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            before = env.state()
            with self.assertRaises(errors.ProjectError) as caught:
                open_mod.open_project(
                    env.root, SESSION_B, env.userdata, clock=env.clock, pid_alive=env.pids
                )
            self.assertEqual(caught.exception.code, "core.project_inconsistent")
            self.assertIn("699000", str(caught.exception))
            self.assertIn("701000", str(caught.exception))
            self.assertEqual(env.state(), before)


if __name__ == "__main__":
    unittest.main()
