# SPDX-License-Identifier: GPL-3.0-or-later
"""Copia local de trabajo (spec 002, T31; RF-002-31; plan 002 §5.4, «Copia local»;
formato-proyecto §6).

Sacar una copia local reserva el original (su ``.lock`` en modo ``checkout``), lo copia
sin ``cache/`` ni ``.lock`` a la carpeta de copias locales, comprueba que la copia es
idéntica (las mismas huellas), anota en la cabecera de la copia la sección ``checkout``
(sin la ruta del original) y en los datos de usuario el registro con la ruta del original,
y abre la copia en escritura (modo ``CHECKOUT``). Cancelar en cualquier paso borra la
copia parcial y libera la reserva; el original no cambia (salvo su ``.lock`` mientras
está reservado).
"""

import hashlib
import sqlite3
import unittest
from pathlib import Path
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

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
model = import_geoblender("core.project.model")
lock = import_geoblender("core.project.lock")
manifest = import_geoblender("core.project.manifest")
schema = import_geoblender("core.project.schema")
events = import_geoblender("core.project.events")
copytree = import_geoblender("core.project.copytree")
checkout = import_geoblender("core.project.checkout")
project_api = import_geoblender("core.project")
paths = import_geoblender("core.paths")
gpkg = import_geoblender("core.gpkg")
timeutil = import_geoblender("core.timeutil")
userdata_mod = import_geoblender("core.userdata")
errors = import_geoblender("core.errors")

SESSION_A = make_session()
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra", pid=777
)
EXCLUDE = ("cache", ".lock")
CHUNK = 64 * 1024  # trozos pequeños: muchos pasos con ficheros de prueba pequeños
QGIS_TABLE = "CREATE TABLE capa_qgis (fid INTEGER PRIMARY KEY, a TEXT)"


def snapshot(root: Path, skip: tuple[str, ...] = ()) -> dict[str, object]:
    """Cada fichero (tamaño, sha256 y fecha de modificación) y cada subcarpeta de
    ``root``, sin las rutas de ``skip``."""
    found: dict[str, object] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel in skip:
            continue
        if path.is_dir():
            found[rel] = "carpeta"
        else:
            stat = path.stat()
            found[rel] = (stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest(),
                          stat.st_mtime_ns)
    return found


def rows(root: Path, table: str) -> list[tuple]:
    with gpkg.GpkgConnection.open_read(root / "project.gpkg") as db:
        return list(db.connection.execute(f"SELECT * FROM {table} ORDER BY fid"))


def event_kinds(root: Path) -> list[str]:
    with gpkg.GpkgConnection.open_read(root / "project.gpkg") as db:
        return [item.kind for item in events.read_events(db.connection)]


def write_like_qgis(database: Path) -> None:
    """Escribe en la base como lo haría QGIS (una conexión ajena, sin ``gb_writer()``)."""
    conn = sqlite3.connect(database, isolation_level=None)
    try:
        conn.execute(QGIS_TABLE)
        conn.execute("INSERT INTO capa_qgis (a) VALUES ('editado en QGIS')")
    finally:
        conn.close()


class Env:
    """Un proyecto local de la sesión A, cerrado, con ficheros en ``rasters/``,
    ``meshes/``, ``scenes/`` y una ``cache/``; una carpeta de copias locales y los datos de
    usuario del equipo, todo en una carpeta temporal."""

    def __init__(self, tmp: Path, raster_bytes: int = 100_000) -> None:
        self.tmp = tmp
        self.parent = tmp / "red"
        self.parent.mkdir()
        self.dest = tmp / "copias"
        self.dest.mkdir()
        self.userdata = userdata_mod.UserData(tmp / "datos_usuario")
        self.clock = FakeClock()
        self.pids = FakePids({SESSION_A.pid, SESSION_B.pid})
        created = create.create_project(
            self.parent, make_settings(), SESSION_A, self.userdata, clock=self.clock
        )
        self.root = created.root
        self.uid = created.record.uid
        pattern = bytes(range(256))
        raster = pattern * (raster_bytes // len(pattern) + 1)
        (self.root / "rasters" / "gis_dtm_prueba.tif").write_bytes(raster[:raster_bytes])
        (self.root / "meshes" / "des_final.npz").write_bytes(b"malla" * 1000)
        (self.root / "scenes" / "principal.blend").write_bytes(b"BLENDER-v502" + bytes(1000))
        (self.root / "cache" / "jobs").mkdir(parents=True)
        (self.root / "cache" / "jobs" / "temporal.bin").write_bytes(b"regenerable" * 10)
        created.project.close()

    def steps(self, session=SESSION_A, **kwargs):
        kwargs.setdefault("clock", self.clock)
        kwargs.setdefault("pid_alive", self.pids)
        kwargs.setdefault("chunk_size", CHUNK)
        return checkout.checkout_steps(self.root, self.dest, session, self.userdata, **kwargs)

    def checkout(self, session=SESSION_A, **kwargs):
        result = None
        for step in self.steps(session, **kwargs):
            if step.result is not None:
                result = step.result
        return result

    def prints(self, root: Path):
        return copytree.fingerprint(root, exclude=EXCLUDE)

    def open(self, root: Path, session, **kwargs):
        kwargs.setdefault("clock", self.clock)
        kwargs.setdefault("pid_alive", self.pids)
        return open_mod.open_project(root, session, self.userdata, **kwargs)

    def leftovers(self) -> list[str]:
        """Lo que hay en la carpeta de copias locales."""
        return sorted(item.name for item in self.dest.iterdir())


class CheckoutTest(unittest.TestCase):
    def test_reserves_original_copies_identical_and_opens_copy(self) -> None:
        """RF-002-31: el original queda reservado (``mode = checkout``) y sin otros
        cambios; la copia tiene las mismas huellas, sin ``cache/`` ni el ``.lock`` del
        original; su cabecera lleva la sección ``checkout`` (sin rutas); los datos de
        usuario, el registro con la ruta del original; y la copia queda abierta en
        escritura (modo copia local) con su propio cerrojo."""
        with project_tmp() as tmp:
            env = Env(tmp)
            before = env.prints(env.root)
            original_files = snapshot(env.root)
            original_rows = rows(env.root, "gb_project")
            original_events = event_kinds(env.root)
            result = env.checkout()
            # El original: reservado para esta sesión y sin más cambios.
            holder = lock.read_holder(env.root)
            self.assertIs(holder.mode, lock.LockMode.CHECKOUT)
            self.assertEqual(holder.session_uid, SESSION_A.session_uid)
            seen = lock.inspect(env.root, SESSION_B, clock=env.clock, pid_alive=env.pids)
            self.assertIs(seen.state, lock.LockState.RESERVED)
            self.assertEqual(snapshot(env.root, skip=(".lock",)), original_files)
            # La copia: mismas huellas que el original, sin cache/ ni su .lock.
            copy = result.copy
            self.assertEqual(copy, env.dest / "Cantera Prueba.gbproj")
            self.assertEqual(result.original, env.root)
            self.assertEqual(result.prints, before)
            self.assertEqual(result.base, copytree.tree_digest(before))
            self.assertFalse((copy / "cache").exists())
            copied = env.prints(copy)
            self.assertEqual([item.path for item in copied.files],
                             [item.path for item in before.files])
            self.assertEqual(copied.folders, before.folders)
            for item in before.files:
                if item.path not in ("manifest.json", "project.gpkg"):
                    self.assertEqual(copied.file(item.path), item, item.path)
            self.assertEqual(rows(copy, "gb_project"), original_rows)
            self.assertEqual(event_kinds(copy), [*original_events, "checkout", "open"])
            # La cabecera de la copia: la sección checkout, sin la ruta del original.
            header = manifest.read_manifest(copy)
            self.assertEqual(
                dict(header.checkout),
                {
                    "session_uid": SESSION_A.session_uid,
                    "base": result.base,
                    "at": timeutil.format_utc(CLOCK_START),
                    "by": "prueba@PC-PRUEBA-A",
                },
            )
            self.assertEqual(paths.find_absolute_paths(header.to_dict()), [])
            self.assertEqual(paths.find_absolute_paths(rows(copy, "gb_event")), [])
            # El registro del equipo, con la ruta del original y las huellas de partida.
            record = env.userdata.checkout_record(env.uid)
            self.assertEqual(record["original"], str(env.root))
            self.assertEqual(record["copy"], str(copy))
            self.assertEqual(record["base"], result.base)
            self.assertEqual(copytree.TreePrints.from_dict(record["prints"]), before)
            self.assertEqual(env.userdata.checkout_original(env.uid), env.root)
            # Abierta en escritura, como copia local, con su propio cerrojo.
            project = result.opened.project
            self.assertIs(project.mode, model.OpenMode.CHECKOUT)
            self.assertTrue(project.writable)
            self.assertTrue(project.is_checkout)
            self.assertEqual(project.root, copy)
            self.assertEqual(project.cache_dir(), copy / "cache")
            copy_lock = lock.read_holder(copy)
            self.assertIs(copy_lock.mode, lock.LockMode.LOCAL)
            self.assertEqual(copy_lock.session_uid, SESSION_A.session_uid)
            project.close()

    def test_reserved_original_is_read_only_for_others(self) -> None:
        """RF-002-31, RF-002-09: mientras dura la reserva, otra sesión abre el original en
        solo lectura «reservado para una copia local» sin cambiar nada; un original
        cualquiera abierto de nuevo no es una copia local."""
        with project_tmp() as tmp:
            env = Env(tmp)
            result = env.checkout()
            before = snapshot(env.root)
            other = env.open(env.root, SESSION_B)
            self.assertEqual(other.project.read_only_reason, model.ReadOnlyCode.RESERVED)
            self.assertIn("reservado para una copia local", other.status.message)
            self.assertFalse(other.project.is_checkout)
            other.project.close()
            self.assertEqual(snapshot(env.root), before)
            result.opened.project.close()

    def test_next_free_name(self) -> None:
        """RF-002-31: si en la carpeta de copias ya hay una con ese nombre, la nueva es
        ``<Nombre>-2.gbproj`` y la otra no se toca."""
        with project_tmp() as tmp:
            env = Env(tmp)
            other = env.dest / "Cantera Prueba.gbproj"
            other.mkdir()
            (other / "nota.txt").write_text("otra copia", encoding="utf-8")
            result = env.checkout()
            self.assertEqual(result.copy, env.dest / "Cantera Prueba-2.gbproj")
            self.assertEqual(sorted(p.name for p in other.iterdir()), ["nota.txt"])
            result.opened.project.close()


class CheckoutCancelTest(unittest.TestCase):
    def _assert_nothing_left(self, env: Env, original_files: dict[str, object]) -> None:
        self.assertEqual(env.leftovers(), [])
        self.assertFalse((env.root / ".lock").exists())
        self.assertEqual(snapshot(env.root), original_files)
        self.assertIsNone(env.userdata.checkout_record(env.uid))

    def test_cancel_during_copy(self) -> None:
        """RF-002-31 (RNF-002-06): cancelar a mitad de la copia borra la copia parcial y
        libera la reserva; el original queda como estaba."""
        with project_tmp() as tmp:
            env = Env(tmp, raster_bytes=1_000_000)
            original_files = snapshot(env.root)
            steps = env.steps()
            for step in steps:
                if step.phase == "copia" and 0 < step.done < step.total:
                    break
            self.assertTrue((env.root / ".lock").exists())
            self.assertTrue(any(".copiando-" in name for name in env.leftovers()))
            steps.close()
            self._assert_nothing_left(env, original_files)

    def test_cancel_while_opening_the_copy(self) -> None:
        """RF-002-31: cancelar ya copiada, mientras se abre la copia, también la borra
        (con su registro) y libera la reserva."""
        with project_tmp() as tmp:
            env = Env(tmp)
            original_files = snapshot(env.root)
            steps = env.steps()
            for step in steps:
                if step.phase == "apertura" and step.result is None:
                    break
            self.assertTrue((env.dest / "Cantera Prueba.gbproj").exists())
            self.assertIsNotNone(env.userdata.checkout_record(env.uid))
            steps.close()
            self._assert_nothing_left(env, original_files)

    def test_qgis_writing_during_copy_discards_it(self) -> None:
        """RF-002-31: si otro programa (QGIS) escribe en la base del original mientras se
        copia, la copia no es la del original: se descarta, se libera la reserva y el
        error dice qué hacer; lo que escribió ese programa se conserva."""
        with project_tmp() as tmp:
            env = Env(tmp, raster_bytes=1_000_000)
            steps = env.steps()
            with self.assertRaises(errors.ProjectError) as caught:
                for step in steps:
                    if step.phase == "copia" and 0 < step.done < step.total:
                        if not (env.tmp / "escrito").exists():
                            write_like_qgis(env.root / "project.gpkg")
                            (env.tmp / "escrito").touch()
            self.assertEqual(caught.exception.code, "core.checkout_source_changed")
            self.assertIn("QGIS", str(caught.exception))
            self.assertEqual(env.leftovers(), [])
            self.assertFalse((env.root / ".lock").exists())
            self.assertEqual(rows(env.root, "capa_qgis")[0][1], "editado en QGIS")


class CheckoutRefusedTest(unittest.TestCase):
    def test_lock_of_another_session(self) -> None:
        """RF-002-31, RF-002-09: con el original abierto en escritura por otra sesión no
        se reserva ni se copia nada, y el error dice quién lo tiene."""
        with project_tmp() as tmp:
            env = Env(tmp)
            holder = env.open(env.root, SESSION_B).project
            before = snapshot(env.root)
            with self.assertRaises(errors.LockError) as caught:
                env.checkout()
            self.assertIn("otra", str(caught.exception))
            self.assertIn("PC-PRUEBA-B", str(caught.exception))
            self.assertEqual(snapshot(env.root), before)
            self.assertEqual(env.leftovers(), [])
            holder.close()

    def test_open_here_must_be_closed_first(self) -> None:
        """RF-002-31: si esta misma sesión lo tiene abierto en escritura, hay que cerrarlo
        antes (no se reserva ni se copia nada)."""
        with project_tmp() as tmp:
            env = Env(tmp)
            opened = env.open(env.root, SESSION_A).project
            with self.assertRaises(errors.ProjectError) as caught:
                env.checkout()
            self.assertEqual(caught.exception.code, "core.checkout_open_here")
            self.assertIs(lock.read_holder(env.root).mode, lock.LockMode.LOCAL)
            self.assertEqual(env.leftovers(), [])
            opened.close()

    def test_copy_of_a_copy_and_bad_destinations(self) -> None:
        """RF-002-31: no se saca copia de una copia local, ni a una carpeta que no existe
        o que está dentro del original; nada se reserva ni se copia."""
        with project_tmp() as tmp:
            env = Env(tmp)
            result = env.checkout()
            copy_project = result.opened.project
            copy_project.close()
            with self.assertRaises(errors.ProjectError) as caught:
                list(checkout.checkout_steps(result.copy, env.tmp, SESSION_A, env.userdata,
                                             clock=env.clock, pid_alive=env.pids))
            self.assertEqual(caught.exception.code, "core.checkout_of_checkout")
            self.assertFalse((result.copy / ".lock").exists())
        with project_tmp() as tmp:
            env = Env(tmp)
            for dest, code in ((env.tmp / "no-existe", "core.checkout_dest_missing"),
                               (env.root / "exports", "core.checkout_dest_inside")):
                with self.subTest(destino=dest.name):
                    with self.assertRaises(errors.ProjectError) as caught:
                        list(checkout.checkout_steps(env.root, dest, SESSION_A, env.userdata,
                                                     clock=env.clock, pid_alive=env.pids))
                    self.assertEqual(caught.exception.code, code)
                    self.assertFalse((env.root / ".lock").exists())

    def test_older_schema_must_be_migrated_first(self) -> None:
        """RF-002-31, RF-002-20: un esquema anterior se migra antes de sacar la copia."""
        with project_tmp() as tmp:
            env = Env(tmp)
            with mock.patch.object(open_mod, "SCHEMA_VERSION", 2):
                with self.assertRaises(errors.ProjectError) as caught:
                    env.checkout()
            self.assertEqual(caught.exception.code, "core.checkout_not_migrated")
            self.assertFalse((env.root / ".lock").exists())
            self.assertEqual(env.leftovers(), [])

    def test_api_exports(self) -> None:
        """RF-002-31: ``core.project`` reexporta la copia local."""
        for name in ("checkout_steps", "CheckoutResult"):
            self.assertTrue(hasattr(project_api, name), name)


if __name__ == "__main__":
    unittest.main()
