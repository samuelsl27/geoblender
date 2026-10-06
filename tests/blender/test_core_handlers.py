# SPDX-License-Identifier: GPL-3.0-or-later
"""El proyecto de la sesión y la georreferencia de las escenas (spec 002, T23; plan 002
§5.4, «Cerrojo» y «Escena»).

- RF-002-28: mientras hay un proyecto abierto, todas las escenas llevan su identidad, su
  ruta relativa al ``.blend``, su CRS y su GeoOrigin, también tras deshacer y rehacer
  (``undo_post``/``redo_post``) y en una escena nueva al guardar (``save_pre``).
- RF-002-11: la marca de actividad del cerrojo la renueva un temporizador
  **persistente** de 300 s, que sigue registrado tras abrir otro ``.blend`` del mismo
  proyecto (y ``load_post`` lo vuelve a registrar si se perdió); si el cerrojo dejó de ser
  de esta sesión, el proyecto pasa a solo lectura con aviso (RF-002-12).
- RF-002-06: desactivar Geoblender, salir de Blender (``atexit``) o cargar un ``.blend``
  de otro proyecto cierran el proyecto abierto: cabecera desde la base y cerrojo liberado;
  al desactivar no queda ningún manejador ni el temporizador.
- RF-002-07: al guardar la vista con un proyecto en escritura, la cabecera se actualiza
  desde la base (``save_post``).
- RF-002-28, RF-002-27, RF-002-20 (T54; spec §8, «Ctrl+Z tras abrir, mover el origen o
  migrar»): deshacer y rehacer tras «Ventana de trabajo…» dejan las escenas con el origen
  nuevo y desfasadas, y tras abrir con migración, el proyecto abierto en el esquema nuevo y
  la copia previa intacta: nada del proyecto se deshace.
- RF-002-29 (T24): un ``.blend`` con otra georreferencia que la del proyecto abierto, o con
  la de un proyecto cuando no hay ninguno abierto, da un aviso con las dos y deja la vista
  desfasada (``view_stale``); su georreferencia no se usa: la del proyecto abierto manda y,
  sin proyecto, no hay georreferencia para ningún comando.

En ``blender -b`` los temporizadores no se ejecutan: las pruebas llaman a la función del
temporizador directamente (docs/trampas.md §3). Se ejecuta con
``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import atexit
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

# Ventana sintética de la spec 002 (T01): origen (700 000; 4 400 000; 0).
WINDOW = (699_500.4, 4_399_500.6, 700_500.2, 4_400_500.9)
ORIGIN = (700_000, 4_400_000, 0)
HANDLER_LISTS = ("load_post", "undo_post", "redo_post", "save_pre", "save_post")
# «Ventana de trabajo…» con el origen nuevo (701 000; 4 400 000; 0), como en la T27.
MOVED_TEXT = {
    "xmin": "700 500,4",
    "ymin": "4399500,6",
    "xmax": "701500.2",
    "ymax": "4 400 500,9",
}
MOVED = (701_000, 4_400_000, 0)


def ext(name: str) -> ModuleType:
    """El módulo ``name`` de la copia de pruebas de la extensión (ya importado)."""
    return sys.modules[f"{module_name()}.{name}"]


def _m1_2(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS gb_test_m2 (fid INTEGER PRIMARY KEY, nota TEXT)")


def _m2_3(conn: sqlite3.Connection) -> None:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(gb_test_m2)")]
    if "extra" not in columns:
        conn.execute("ALTER TABLE gb_test_m2 ADD COLUMN extra TEXT")


def _tree_digest(folder: Path) -> dict[str, tuple[int, str]]:
    """Ruta relativa → (tamaño, sha256) de cada fichero bajo ``folder``."""
    return {
        path.relative_to(folder).as_posix(): (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


class HandlersTestCase(unittest.TestCase):
    """Cada prueba parte de la extensión deshabilitada y de la escena de fábrica, en una
    carpeta temporal para sus proyectos."""

    def setUp(self) -> None:
        blender_ext.unload()
        blender_ext.load_file()  # la escena de fábrica, sin restos de otra prueba
        self.tmp = Path(tempfile.mkdtemp(prefix="geoblender-t23-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # Al terminar, primero se deshabilita (cierra el proyecto) y después la escena de
        # fábrica, ya sin manejadores que la sincronicen.
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(blender_ext.unload)

    def start(self) -> None:
        """Habilita la extensión y toma sus módulos."""
        blender_ext.enable()
        self.ps = ext("bl.scene.project_session")
        self.georef = ext("bl.scene.georef")
        self.core = ext("core.project")
        self.lock = ext("core.project.lock")

    def create(self, name: str = "Cantera Prueba", *, attach: bool = True) -> object:
        """Crea un proyecto con la sesión de este Blender y, si se pide, lo deja como el
        proyecto de la sesión."""
        settings = self.core.ProjectSettings(
            name=name, window=WINDOW, crs_epsg=25830, vcrs_epsg=5782
        )
        result = self.core.create_project(
            self.tmp, settings, self.ps.session(), self.ps.userdata()
        )
        if attach:
            self.ps.attach(result.project)
        return result.project

    def events(self, root: Path) -> list[str]:
        gpkg = ext("core.gpkg")
        events = ext("core.project.events")
        with gpkg.GpkgConnection.open_read(root / "project.gpkg") as db:
            return [item.kind for item in events.read_events(db.connection)]

    def assert_scenes_synced(
        self, project: object, path: str, origin: tuple[int, int, int] = ORIGIN
    ) -> None:
        """Todas las escenas llevan la georreferencia del proyecto (con ``origin``)."""
        self.assertGreater(len(bpy.data.scenes), 0)
        for scene in bpy.data.scenes:
            with self.subTest(escena=scene.name):
                props = scene.geoblender
                self.assertEqual(props.project_uid, project.uid)
                self.assertEqual(props.project_name, project.name)
                self.assertEqual(props.project_path, path)
                self.assertEqual((props.crs_epsg, props.vcrs_epsg), (25830, 5782))
                self.assertEqual((props.origin_x, props.origin_y, props.origin_z), origin)

    def run_open(self, **props: object) -> object:
        """Lanza «Abrir proyecto…» y lo lleva hasta el final con eventos ``TIMER`` (en
        ``blender -b`` no hay bucle de eventos); devuelve el operador."""
        result = bpy.ops.geoblender.core_open_project("EXEC_DEFAULT", **props)
        self.assertEqual(result, {"RUNNING_MODAL"})
        cls = ext("bl.ops.core").GEOBLENDER_OT_core_open_project
        (operator,) = [
            op
            for op in bpy.context.window.modal_operators
            if isinstance(op, cls) and getattr(op, "_steps", None) is not None
        ]
        for _ in range(10_000):
            state = operator.modal(bpy.context, SimpleNamespace(type="TIMER", value="NOTHING"))
            if state != {"RUNNING_MODAL"}:
                break
        self.assertIn(state, ({"FINISHED"}, {"CANCELLED"}))
        return operator

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(path))

    def stale(self) -> list[bool]:
        return [scene.geoblender.view_stale for scene in bpy.data.scenes]


class SceneSyncTest(HandlersTestCase):
    def test_undo_redo_keep_georeference(self) -> None:
        """RF-002-28: tras deshacer hasta antes de abrir el proyecto y rehacer, todas las
        escenas conservan uid, ruta, CRS y origen (``undo_post`` y ``redo_post``)."""
        self.start()
        bpy.data.scenes.new("Segunda")
        self.assertEqual([s.geoblender.project_uid for s in bpy.data.scenes], ["", ""])
        bpy.ops.ed.undo_push(message="inicio")  # sin georreferencia en las escenas
        project = self.create()
        self.save(project.root / "scenes" / "principal.blend")
        bpy.ops.ed.undo_push(message="proyecto abierto")
        bpy.context.scene.frame_current = 9
        bpy.ops.ed.undo_push(message="cambio")
        bpy.ops.ed.undo()
        bpy.ops.ed.undo()
        self.assert_scenes_synced(project, "//../")
        bpy.ops.ed.redo()
        bpy.ops.ed.redo()
        self.assertEqual(bpy.context.scene.frame_current, 9)
        self.assert_scenes_synced(project, "//../")

    def test_new_scene_receives_georeference_on_save(self) -> None:
        """RF-002-28, RF-002-18: una escena creada después de abrir el proyecto recibe su
        georreferencia al guardar, con la ruta relativa al fichero de destino."""
        self.start()
        project = self.create()
        new = bpy.data.scenes.new("Nueva")
        self.assertEqual(new.geoblender.project_uid, "")
        self.save(project.root / "scenes" / "vista.blend")
        self.assert_scenes_synced(project, "//../")
        self.save(self.tmp / "fuera" / "vista.blend")
        self.assert_scenes_synced(project, f"//../{project.root.name}/")

    def test_undo_redo_after_window_change(self) -> None:
        """RF-002-28, RF-002-27 (spec §8, «Ctrl+Z tras … mover el origen»; convergencia,
        T54): tras «Ventana de trabajo…» (origen 700 000 → 701 000), deshacer hasta antes
        del cambio y rehacer dejan todas las escenas en (701 000; 4 400 000; 0) y
        desfasadas (sus datos se cargaron con el origen anterior), y la base y la cabecera
        con 701 000: nada del proyecto se deshace."""
        self.start()
        bpy.data.scenes.new("Segunda")
        project = self.create()
        self.save(project.root / "scenes" / "principal.blend")
        bpy.ops.ed.undo_push(message="proyecto abierto")
        result = bpy.ops.geoblender.core_set_work_window(
            "EXEC_DEFAULT", reason="Ampliación hacia el este", **MOVED_TEXT
        )
        self.assertEqual(result, {"FINISHED"})
        bpy.context.scene.frame_current = 9
        bpy.ops.ed.undo_push(message="cambio")
        for step in ("undo", "redo"):
            with self.subTest(paso=step):
                getattr(bpy.ops.ed, step)()
                self.assertEqual(bpy.context.scene.frame_current, 9 if step == "redo" else 1)
                self.assert_scenes_synced(project, "//../", MOVED)
                self.assertEqual(self.stale(), [True, True])
                self.assertEqual(project.reload().origin.as_tuple(), MOVED)
                header = ext("core.project.manifest").read_manifest(project.root)
                self.assertEqual(header.origin.as_tuple(), MOVED)
                self.assertIs(self.ps.current(), project)
                self.assertTrue(project.writable)

    def test_undo_after_opening_with_migration(self) -> None:
        """RF-002-28, RF-002-20 (spec §8, «Ctrl+Z tras … migrar»; convergencia, T54): tras
        abrir con migración (migraciones de prueba 1 → 3, como en la T25), deshacer hasta
        antes de abrir deja el proyecto abierto en escritura en el esquema 3, la copia
        previa intacta y las escenas con su georreferencia."""
        self.start()
        project = self.create()
        root = project.root
        self.ps.close()
        migrations = ext("core.project.migrations")
        registry = (
            migrations.Migration(1, 2, "tabla de prueba", _m1_2),
            migrations.Migration(2, 3, "columna de prueba", _m2_3),
        )
        with (
            mock.patch.object(ext("core.project.open"), "SCHEMA_VERSION", 3),
            mock.patch.object(migrations, "SCHEMA_VERSION", 3),
            mock.patch.object(migrations, "REGISTRY", registry),
        ):
            bpy.ops.ed.undo_push(message="antes de abrir")
            operator = self.run_open(directory=str(root), accept_migration=True)
            self.assertEqual(operator.outcome, "FINISHED")
            opened = self.ps.current()
            self.assertEqual((opened.schema_version, opened.writable), (3, True))
            backup = self.tmp / "Cantera Prueba.gbproj.respaldo-esquema-1"
            copy = _tree_digest(backup)
            self.assertTrue(copy)
            bpy.ops.ed.undo_push(message="abierto")
            bpy.context.scene.frame_current = 9
            bpy.ops.ed.undo_push(message="cambio")
            bpy.ops.ed.undo()
            bpy.ops.ed.undo()
            self.assertEqual(bpy.context.scene.frame_current, 1)
            self.assertIs(self.ps.current(), opened)
            self.assertEqual((opened.schema_version, opened.writable), (3, True))
            self.assertEqual(opened.reload().schema_version, 3)
            self.assertEqual(self.lock.read_holder(root).session_uid, self.ps.session().session_uid)
            self.assertEqual(_tree_digest(backup), copy)
            self.assert_scenes_synced(opened, "")

    def test_save_post_updates_header(self) -> None:
        """RF-002-07: al guardar la vista con el proyecto en escritura, la cabecera se
        reescribe desde la base de datos (``save_post``)."""
        self.start()
        project = self.create()
        path = project.root / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["modified_at"] = "2020-01-01T00:00:00.000Z"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.save(project.root / "scenes" / "principal.blend")
        header = ext("core.project.manifest").read_manifest(project.root)
        self.assertEqual(header.modified_at, project.record.modified_at)


class SessionLockTest(HandlersTestCase):
    def test_heartbeat_timer_survives_loading_same_project(self) -> None:
        """RF-002-11: el temporizador de la marca es persistente: tras abrir otro ``.blend``
        del mismo proyecto sigue registrado y el proyecto sigue abierto con su cerrojo; si
        se hubiera perdido, ``load_post`` lo vuelve a registrar."""
        self.start()
        project = self.create()
        heartbeat = self.ps.heartbeat
        self.assertTrue(bpy.app.timers.is_registered(heartbeat))
        first = project.root / "scenes" / "a.blend"
        second = project.root / "scenes" / "b.blend"
        self.save(first)
        self.save(second)
        blender_ext.load_file(first)
        self.assertTrue(bpy.app.timers.is_registered(heartbeat))
        self.assertIs(self.ps.current(), project)
        holder = self.lock.read_holder(project.root)
        self.assertEqual(holder.session_uid, self.ps.session().session_uid)
        bpy.app.timers.unregister(heartbeat)
        blender_ext.load_file(second)
        self.assertTrue(bpy.app.timers.is_registered(heartbeat))

    def test_heartbeat_renews_lock_and_detects_loss(self) -> None:
        """RF-002-11, RF-002-12: la función del temporizador renueva la marca y pide la
        siguiente a los 300 s; si otra sesión se ha quedado el cerrojo, deja de
        repetirse, el proyecto pasa a solo lectura «cerrojo perdido» con un aviso y el
        cerrojo ajeno no se toca."""
        self.start()
        project = self.create()
        before = self.lock.read_holder(project.root).heartbeat_at
        time.sleep(0.02)
        self.assertEqual(self.ps.heartbeat(), 300.0)
        self.assertGreater(self.lock.read_holder(project.root).heartbeat_at, before)
        other = ext("core.sysinfo").SessionInfo(
            "00000000-0000-4000-8000-0000000000b2", "PC-OTRO", "otra", 4242, "0.1.0"
        )
        self.lock.release(project.root, self.ps.session())
        self.lock.acquire(project.root, other, self.lock.LockMode.LOCAL)
        foreign = (project.root / ".lock").read_bytes()
        core_log = ext("core.project.events").LOGGER
        with self.assertLogs(core_log, "WARNING"), self.assertLogs(self.ps.LOGGER, "WARNING"):
            self.assertIsNone(self.ps.heartbeat())
        self.assertFalse(project.writable)
        self.assertEqual(project.read_only_reason, self.core.ReadOnlyCode.LOCK_LOST)
        notices = self.ps.take_notices()
        self.assertTrue(any("cerrojo" in notice for notice in notices), notices)
        self.assertEqual((project.root / ".lock").read_bytes(), foreign)

    def test_unregister_releases_lock_and_leaves_nothing(self) -> None:
        """RF-002-06: desactivar Geoblender cierra el proyecto (evento ``close`` y cerrojo
        liberado) y no deja manejadores, temporizador ni función de salida."""
        with (
            mock.patch.object(atexit, "register") as registered,
            mock.patch.object(atexit, "unregister") as unregistered,
        ):
            self.start()
            project = self.create()
            at_exit = self.ps.at_exit
            registered.assert_any_call(at_exit)
            heartbeat = self.ps.heartbeat
            handlers = list(self.georef.HANDLERS)
            self.assertEqual(sorted({name for name, _ in handlers}), sorted(HANDLER_LISTS))
            for name, function in handlers:
                self.assertIn(function, getattr(bpy.app.handlers, name))
            self.assertTrue((project.root / ".lock").exists())
            blender_ext.disable()
            unregistered.assert_any_call(at_exit)
        self.assertFalse((project.root / ".lock").exists())
        self.assertTrue(project.closed)
        self.assertEqual(self.events(project.root)[-1], "close")
        self.assertFalse(bpy.app.timers.is_registered(heartbeat))
        for name, function in handlers:
            self.assertNotIn(function, getattr(bpy.app.handlers, name))
        self.assertIsNone(self.ps.current())

    def test_at_exit_closes_project(self) -> None:
        """RF-002-06: al salir de Blender, la función de ``atexit`` cierra el proyecto:
        cabecera desde la base, evento ``close`` y cerrojo liberado."""
        self.start()
        project = self.create()
        self.ps.at_exit()
        self.assertTrue(project.closed)
        self.assertFalse((project.root / ".lock").exists())
        self.assertEqual(self.events(project.root)[-1], "close")
        self.assertIsNone(self.ps.current())

    def test_loading_other_project_closes_open_one(self) -> None:
        """RF-002-06: cargar un ``.blend`` de otro proyecto cierra el abierto (evento
        ``close`` y cerrojo liberado) y no abre el del fichero."""
        self.start()
        other = self.create(name="Otra")
        other_blend = other.root / "scenes" / "otra.blend"
        self.save(other_blend)
        self.ps.close()
        self.assertFalse((other.root / ".lock").exists())
        project = self.create()
        self.assertTrue((project.root / ".lock").exists())
        self.ps.take_notices()
        blender_ext.load_file(other_blend)
        self.assertIsNone(self.ps.current())
        self.assertTrue(project.closed)
        self.assertFalse((project.root / ".lock").exists())
        self.assertEqual(self.events(project.root)[-1], "close")
        self.assertFalse((other.root / ".lock").exists())
        # RF-002-29: aviso con los dos proyectos y la vista desfasada.
        self.assertEqual(self.stale(), [True])
        (notice,) = self.ps.take_notices()
        self.assertIn("«Otra»", notice)
        self.assertIn("«Cantera Prueba»", notice)


def _digits(text: str) -> str:
    """``text`` sin espacios (también el fino de miles), para buscar cifras."""
    return "".join(text.split()).replace(" ", "").replace(" ", "")


class GeorefMismatchTest(HandlersTestCase):
    def test_same_project_other_origin(self) -> None:
        """RF-002-29: un ``.blend`` del mismo proyecto con otro GeoOrigin da un aviso con
        los dos orígenes, deja la vista desfasada y sus escenas pasan a la georreferencia
        del proyecto (la del fichero no se usa)."""
        self.start()
        project = self.create()
        blend = project.root / "scenes" / "principal.blend"
        self.save(blend)
        self.ps.close()
        bpy.context.scene.geoblender.origin_x = 700_100  # una vista de otro origen
        self.save(blend)
        reopened = self.core.open_project(project.root, self.ps.session(), self.ps.userdata())
        self.ps.attach(reopened.project)
        self.ps.take_notices()
        blender_ext.load_file(blend)
        self.assertIs(self.ps.current(), reopened.project)
        self.assertEqual(self.stale(), [True])
        self.assert_scenes_synced(reopened.project, "//../")
        (notice,) = self.ps.take_notices()
        self.assertIn("700100", _digits(notice))
        self.assertIn("700000", _digits(notice))
        self.assertIn("«Cantera Prueba»", notice)
        found = self.georef.project_georeference()
        self.assertEqual(found.origin, ORIGIN)

    def test_same_georeference_is_quiet(self) -> None:
        """RF-002-29: un ``.blend`` del mismo proyecto con su misma georreferencia no da
        aviso ni deja la vista desfasada."""
        self.start()
        project = self.create()
        blend = project.root / "scenes" / "principal.blend"
        self.save(blend)
        self.ps.take_notices()
        blender_ext.load_file(blend)
        self.assertEqual(self.ps.take_notices(), [])
        self.assertEqual(self.stale(), [False])

    def test_project_blend_without_open_project(self) -> None:
        """RF-002-29: un ``.blend`` de un proyecto cuando no hay ninguno abierto da un aviso
        con su georreferencia y deja la vista desfasada; su georreferencia no se usa: no
        hay georreferencia de proyecto para ningún comando y no se abre ni se bloquea el
        proyecto."""
        self.start()
        project = self.create()
        blend = project.root / "scenes" / "principal.blend"
        self.save(blend)
        self.ps.close()
        self.ps.take_notices()
        blender_ext.load_file(blend)
        self.assertIsNone(self.ps.current())
        self.assertIsNone(self.georef.project_georeference())
        self.assertFalse((project.root / ".lock").exists())
        self.assertEqual(self.stale(), [True])
        (notice,) = self.ps.take_notices()
        self.assertIn("«Cantera Prueba»", notice)
        self.assertIn("700000", _digits(notice))
        props = bpy.context.scene.geoblender
        self.assertEqual((props.origin_x, props.origin_y, props.origin_z), ORIGIN)


if __name__ == "__main__":
    unittest.main()
