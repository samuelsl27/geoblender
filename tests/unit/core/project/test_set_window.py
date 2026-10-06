# SPDX-License-Identifier: GPL-3.0-or-later
"""Cambiar la ventana de trabajo y con ella el GeoOrigin (spec 002, T27; RF-002-24,
RF-002-27; ADR-0005 §2, «Mover origen»; plan 002 §5.3, ``Project.set_window``).

El origen nuevo (centro de la ventana ampliada, empates hacia arriba) se guarda en la base
de datos y en la cabecera, con un evento ``move_origin`` que lleva el motivo
(obligatorio) y los dos orígenes. Ninguna coordenada absoluta guardada cambia: las capas
del proyecto quedan byte a byte. Sin motivo, en solo lectura, con la ventana fuera del CRS
o sin el cerrojo, no cambia nada.
"""

import sqlite3
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
