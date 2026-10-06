# SPDX-License-Identifier: GPL-3.0-or-later
"""Copia local de trabajo y publicación (spec 002, T31 a T33; RF-002-31 a RF-002-33; plan
002 §5.4, «Copia local» y «Publicación»; formato-proyecto §6).

Sacar una copia local reserva el original (su ``.lock`` en modo ``checkout``), lo copia
sin ``cache/`` ni ``.lock`` a la carpeta de copias locales, comprueba que la copia es
idéntica (las mismas huellas), anota en la cabecera de la copia la sección ``checkout``
(sin la ruta del original) y en los datos de usuario el registro con la ruta del original,
y abre la copia en escritura (modo ``CHECKOUT``). Cancelar en cualquier paso borra la
copia parcial y libera la reserva; el original no cambia (salvo su ``.lock`` mientras
está reservado).

Publicar la copia la copia junto al original como ``<Nombre>.gbproj.publicando`` (con
``checkout = null`` y el evento ``publish``), renombra el original a
``<Nombre>.gbproj.anterior`` (sustituyendo la anterior) y la publicación al nombre del
original, y libera la reserva. Cancelar antes de sustituir nada no deja nada a medias.

Si no se puede publicar (reserva perdida, original cambiado, carpeta retenida por QGIS),
el original queda con las mismas huellas, la copia local intacta y el mensaje dice el
motivo y qué hacer; con la carpeta retenida, ``.publicando`` se conserva y el reintento la
aprovecha. La carpeta retenida se simula sustituyendo el renombrado del módulo.
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

    def publish_steps(self, local, session=SESSION_A, **kwargs):
        kwargs.setdefault("clock", self.clock)
        kwargs.setdefault("pid_alive", self.pids)
        kwargs.setdefault("chunk_size", CHUNK)
        return checkout.publish_steps(local, session, self.userdata, **kwargs)

    def publish(self, local, session=SESSION_A, **kwargs):
        result = None
        for step in self.publish_steps(local, session, **kwargs):
            if step.result is not None:
                result = step.result
        return result

    def siblings(self) -> list[str]:
        """Lo que hay junto al original (en su carpeta de «red»)."""
        return sorted(item.name for item in self.parent.iterdir())


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
        """RF-002-31, RF-002-32: ``core.project`` reexporta la copia local y la
        publicación."""
        for name in ("checkout_steps", "CheckoutResult", "publish_steps", "PublishResult"):
            self.assertTrue(hasattr(project_api, name), name)


NEW_WINDOW = (700_500.4, 4_399_500.6, 701_500.2, 4_400_500.9)
ORIGINAL = "Cantera Prueba.gbproj"
PREVIOUS = "Cantera Prueba.gbproj.anterior"


class PublishTest(unittest.TestCase):
    def test_publish_replaces_original_and_releases_reservation(self) -> None:
        """RF-002-32: el original pasa a ``<Nombre>.gbproj.anterior`` (entero, sin la
        reserva) y en su lugar queda la copia publicada, con ``checkout = null``, las
        huellas de la copia (salvo su base, que suma el evento ``publish``, y su cabecera)
        y sin cerrojo: la reserva se libera. La copia local se cierra, sale del registro
        del equipo y el publicado es el primero de los recientes."""
        with project_tmp() as tmp:
            env = Env(tmp)
            original_prints = env.prints(env.root)
            result = env.checkout()
            local = result.opened.project
            origin = local.set_window(NEW_WINDOW, 1.0, 0, "Ampliación hacia el este")
            (local.root / "rasters" / "gis_dtm_nuevo.tif").write_bytes(b"nuevo" * 1000)
            local_prints = env.prints(local.root)
            local_rows = rows(local.root, "gb_project")
            local_events = event_kinds(local.root)
            published = env.publish(local)
            previous = env.parent / PREVIOUS
            self.assertEqual(published.original, env.root)
            self.assertEqual(published.previous, previous)
            self.assertEqual(published.local, local.root)
            # El original anterior, entero y sin la reserva.
            self.assertEqual(env.prints(previous), original_prints)
            self.assertFalse((previous / ".lock").exists())
            # El publicado: la copia, con checkout = null y el evento publish.
            self.assertFalse((env.root / ".lock").exists())
            header = manifest.read_manifest(env.root)
            self.assertIsNone(header.checkout)
            self.assertEqual(header.origin, origin)
            now = env.prints(env.root)
            self.assertEqual([item.path for item in now.files],
                             [item.path for item in local_prints.files])
            for item in local_prints.files:
                if item.path not in ("manifest.json", "project.gpkg"):
                    self.assertEqual(now.file(item.path), item, item.path)
            self.assertEqual(published.prints, now)
            self.assertEqual(rows(env.root, "gb_project"), local_rows)
            self.assertEqual(event_kinds(env.root), [*local_events, "publish"])
            with gpkg.GpkgConnection.open_read(env.root / "project.gpkg") as db:
                found = events.read_events(db.connection, events.EventKind.PUBLISH)
            self.assertEqual(found[0].data["base"], result.base)
            self.assertEqual(found[0].data["checkout_session"], SESSION_A.session_uid)
            self.assertEqual(paths.find_absolute_paths(rows(env.root, "gb_event")), [])
            # Nada a medias; la copia, cerrada; el equipo, sin el registro de la copia.
            self.assertEqual(env.siblings(), [ORIGINAL, PREVIOUS])
            self.assertTrue(local.closed)
            self.assertFalse((local.root / ".lock").exists())
            self.assertIsNone(env.userdata.checkout_record(env.uid))
            self.assertEqual(env.userdata.recent_projects()[0].path, env.root)
            # Otra sesión lo abre en escritura normal, con el origen nuevo.
            opened = env.open(env.root, SESSION_B).project
            self.assertIs(opened.mode, model.OpenMode.WRITE_LOCAL)
            self.assertFalse(opened.is_checkout)
            self.assertEqual(opened.origin, origin)
            opened.close()

    def test_second_publication_replaces_previous(self) -> None:
        """RF-002-32: se conserva una sola publicación anterior: la segunda sustituye a la
        primera ``.anterior`` (sin dejar restos)."""
        with project_tmp() as tmp:
            env = Env(tmp)
            first = env.checkout()
            env.publish(first.opened.project)
            first_published = env.prints(env.root)
            second = env.checkout()
            self.assertEqual(second.copy, env.dest / "Cantera Prueba-2.gbproj")
            (second.copy / "exports" / "informe.pdf").write_bytes(b"%PDF-1.7 informe")
            env.publish(second.opened.project)
            self.assertEqual(env.prints(env.parent / PREVIOUS), first_published)
            self.assertEqual(env.siblings(), [ORIGINAL, PREVIOUS])
            self.assertTrue((env.root / "exports" / "informe.pdf").is_file())
            self.assertEqual(event_kinds(env.root).count("publish"), 2)

    def test_refreshes_listings_after_renaming(self) -> None:
        """RF-002-32, RF-002-33 (docs/trampas.md §6): cada carpeta que se renombra al
        publicar (la ``.anterior`` que se aparta, el original a ``.anterior`` y la
        publicación al nombre del original) se vuelve a listar con su nombre nuevo: en la
        red, si no, Windows no deja sustituir después su cabecera (``os.replace``)."""
        with project_tmp() as tmp:
            env = Env(tmp)
            first = env.checkout()
            env.publish(first.opened.project)
            second = env.checkout()
            seen: list[tuple[str, bool]] = []
            real = checkout.refresh_listing

            def spy(folder: Path) -> None:
                seen.append((Path(folder).name, Path(folder).is_dir()))
                real(folder)

            with mock.patch.object(checkout, "refresh_listing", spy):
                env.publish(second.opened.project)
            names = [name for name, _exists in seen]
            self.assertEqual(len(names), 3, names)
            self.assertTrue(names[0].startswith(f"{PREVIOUS}.borrando-"), names)
            self.assertEqual(names[1:], [PREVIOUS, ORIGINAL])
            self.assertTrue(all(exists for _name, exists in seen))

    def test_cancel_before_replacing_leaves_nothing(self) -> None:
        """RF-002-32 (RNF-002-06): cancelar a mitad de la copia, o justo antes de
        sustituir, no deja nada junto al original, que sigue reservado y sin cambios, y
        la copia local sigue abierta e intacta."""
        with project_tmp() as tmp:
            env = Env(tmp, raster_bytes=1_000_000)
            result = env.checkout()
            local = result.opened.project
            original_files = snapshot(env.root)
            local_files = snapshot(local.root)
            record = env.userdata.checkout_record(env.uid)
            for stop in ("copia", "sustitución"):
                with self.subTest(fase=stop):
                    steps = env.publish_steps(local)
                    for step in steps:
                        if step.phase == stop and (stop != "copia" or 0 < step.done < step.total):
                            break
                    else:
                        self.fail(f"no hubo paso «{stop}»")
                    steps.close()
                    self.assertEqual(env.siblings(), [ORIGINAL])
                    self.assertEqual(snapshot(env.root), original_files)
                    self.assertEqual(snapshot(local.root), local_files)
                    self.assertTrue(local.writable)
                    self.assertEqual(env.userdata.checkout_record(env.uid), record)
            local.close()


STAGING = "Cantera Prueba.gbproj.publicando"


def held(*blocked: Path):
    """``_rename`` que falla como si QGIS tuviera abierto un fichero de las carpetas
    ``blocked`` (``PermissionError``, WinError 32) y renombra las demás."""
    real = checkout._rename

    def rename(source: Path, target: Path) -> None:
        if Path(source) in blocked:
            raise PermissionError(
                13,
                "El proceso no tiene acceso al archivo porque está siendo utilizado por otro "
                "proceso",
                str(source),
            )
        real(source, target)

    return mock.patch.object(checkout, "_rename", rename)


class PublishRefusedTest(unittest.TestCase):
    """RF-002-33: si no se puede publicar, el original queda con las mismas huellas, la
    copia local intacta y el mensaje dice el motivo y qué hacer; nunca se publica a
    medias."""

    def _prepare(self, tmp: Path, **kwargs):
        env = Env(tmp, **kwargs)
        result = env.checkout()
        local = result.opened.project
        local.set_window(NEW_WINDOW, 1.0, 0, "Ampliación hacia el este")
        (local.root / "rasters" / "gis_dtm_nuevo.tif").write_bytes(b"nuevo" * 1000)
        return env, local

    def _assert_untouched(self, env: Env, local, original_files, local_files) -> None:
        self.assertEqual(snapshot(env.root), original_files)
        self.assertEqual(snapshot(local.root), local_files)
        self.assertTrue(local.writable)
        self.assertIsNotNone(env.userdata.checkout_record(env.uid))

    def test_reservation_lost(self) -> None:
        """RF-002-33: si otra sesión forzó la reserva, no se publica; el mensaje dice
        quién lo tiene ahora y qué hacer para no perder el trabajo."""
        with project_tmp() as tmp:
            env, local = self._prepare(tmp)
            seen = lock.inspect(env.root, SESSION_B, clock=env.clock, pid_alive=env.pids)
            self.assertIs(seen.state, lock.LockState.RESERVED)
            lock.force(env.root, SESSION_B, lock.LockMode.LOCAL, seen.holder, clock=env.clock,
                       pid_alive=env.pids)
            original_files, local_files = snapshot(env.root), snapshot(local.root)
            with self.assertRaises(errors.ProjectError) as caught:
                env.publish(local)
            self.assertEqual(caught.exception.code, "core.publish_reservation_lost")
            message = str(caught.exception)
            for expected in ("ya no está reservado", "otra", "PC-PRUEBA-B", "proyecto aparte",
                             "copia nueva"):
                self.assertIn(expected, message)
            self._assert_untouched(env, local, original_files, local_files)
            self.assertEqual(env.siblings(), [ORIGINAL])
            local.close()

    def test_original_changed(self) -> None:
        """RF-002-33: si el original cambió desde que se sacó la copia (QGIS editó su
        base), no se publica; el mensaje dice qué cambió y qué hacer."""
        with project_tmp() as tmp:
            env, local = self._prepare(tmp)
            write_like_qgis(env.root / "project.gpkg")
            original_files, local_files = snapshot(env.root), snapshot(local.root)
            with self.assertRaises(errors.ProjectError) as caught:
                env.publish(local)
            self.assertEqual(caught.exception.code, "core.publish_original_changed")
            message = str(caught.exception)
            for expected in ("ha cambiado", "«project.gpkg» ha cambiado", "QGIS",
                             "solo lectura", "proyecto aparte"):
                self.assertIn(expected, message)
            self._assert_untouched(env, local, original_files, local_files)
            self.assertEqual(env.siblings(), [ORIGINAL])
            local.close()

    def test_retained_folder_keeps_staging_and_retry_completes(self) -> None:
        """RF-002-33: si el original no se puede renombrar (QGIS tiene abierto un fichero
        suyo), no se publica nada: el original sigue intacto (reservado), la copia local
        intacta, la publicación preparada queda en ``.publicando`` y el mensaje pide
        cerrar QGIS y volver a publicar; el reintento la aprovecha (no vuelve a copiar) y
        completa la publicación."""
        with project_tmp() as tmp:
            env, local = self._prepare(tmp)
            original_files, local_files = snapshot(env.root), snapshot(local.root)
            with held(env.root), self.assertRaises(errors.ProjectError) as caught:
                env.publish(local)
            self.assertEqual(caught.exception.code, "core.publish_blocked")
            message = str(caught.exception)
            for expected in ("QGIS", STAGING, "vuelva a publicar", "intacto"):
                self.assertIn(expected, message)
            self._assert_untouched(env, local, original_files, local_files)
            self.assertEqual(env.siblings(), [ORIGINAL, STAGING])
            staged = env.parent / STAGING
            self.assertIsNone(manifest.read_manifest(staged).checkout)
            self.assertEqual(event_kinds(staged)[-1], "publish")
            with mock.patch.object(checkout, "copy_steps",
                                   side_effect=AssertionError("no tenía que volver a copiar")):
                published = env.publish(local)
            self.assertEqual(env.siblings(), [ORIGINAL, PREVIOUS])
            self.assertTrue((env.root / "rasters" / "gis_dtm_nuevo.tif").is_file())
            self.assertEqual(event_kinds(env.root).count("publish"), 1)
            self.assertEqual(published.prints, env.prints(env.root))
            self.assertIsNone(env.userdata.checkout_record(env.uid))

    def test_retry_after_changing_the_copy_prepares_it_again(self) -> None:
        """RF-002-33: si después de un intento retenido se sigue trabajando en la copia,
        la publicación preparada ya no vale: el reintento la vuelve a preparar y publica
        lo último."""
        with project_tmp() as tmp:
            env, local = self._prepare(tmp)
            with held(env.root), self.assertRaises(errors.ProjectError):
                env.publish(local)
            (local.root / "exports" / "informe.pdf").write_bytes(b"%PDF-1.7 informe")
            env.publish(local)
            self.assertTrue((env.root / "exports" / "informe.pdf").is_file())
            self.assertEqual(env.siblings(), [ORIGINAL, PREVIOUS])

    def test_second_rename_fails_original_restored(self) -> None:
        """RF-002-33: si falla el segundo renombrado (la publicación preparada no puede
        tomar el nombre del original), se deshace el primero: el original vuelve a su
        nombre, intacto, la ``.anterior`` que hubiera sigue igual y ``.publicando`` queda
        para reintentar."""
        with project_tmp() as tmp:
            env, local = self._prepare(tmp)
            (env.parent / PREVIOUS).mkdir()
            (env.parent / PREVIOUS / "manifest.json").write_text("{}", encoding="utf-8")
            original_files, local_files = snapshot(env.root), snapshot(local.root)
            with held(env.parent / STAGING), self.assertRaises(errors.ProjectError) as caught:
                env.publish(local)
            self.assertEqual(caught.exception.code, "core.publish_blocked")
            self._assert_untouched(env, local, original_files, local_files)
            self.assertEqual(env.siblings(), [ORIGINAL, PREVIOUS, STAGING])
            self.assertEqual(sorted(p.name for p in (env.parent / PREVIOUS).iterdir()),
                             ["manifest.json"])
            env.publish(local)
            self.assertEqual(env.siblings(), [ORIGINAL, PREVIOUS])

    def test_undo_fails_names_both_folders(self) -> None:
        """RF-002-33: si tampoco se puede deshacer, el error nombra las dos carpetas (el
        original y la publicación, completas) y qué renombrar; no se borra ninguna."""
        with project_tmp() as tmp:
            env, local = self._prepare(tmp)
            original_prints = env.prints(env.root)
            with held(env.parent / STAGING, env.parent / PREVIOUS), \
                    self.assertRaises(errors.ProjectError) as caught:
                env.publish(local)
            self.assertEqual(caught.exception.code, "core.publish_half_done")
            message = str(caught.exception)
            self.assertIn(PREVIOUS, message)
            self.assertIn(STAGING, message)
            self.assertEqual(env.siblings(), [PREVIOUS, STAGING])
            self.assertEqual(env.prints(env.parent / PREVIOUS), original_prints)
            local.close()

    def test_foreign_staging_is_not_touched(self) -> None:
        """RF-002-33: un ``.publicando`` que no preparó esta copia (o que cambió desde
        entonces) no se toca ni se publica: el mensaje dice que se revise y se quite."""
        with project_tmp() as tmp:
            env, local = self._prepare(tmp)
            foreign = env.parent / STAGING
            foreign.mkdir()
            (foreign / "nota.txt").write_text("de otra publicación", encoding="utf-8")
            original_files, local_files = snapshot(env.root), snapshot(local.root)
            with self.assertRaises(errors.ProjectError) as caught:
                env.publish(local)
            self.assertEqual(caught.exception.code, "core.publish_staging_foreign")
            self.assertIn(STAGING, str(caught.exception))
            self._assert_untouched(env, local, original_files, local_files)
            self.assertEqual(sorted(p.name for p in foreign.iterdir()), ["nota.txt"])
            local.close()


if __name__ == "__main__":
    unittest.main()
