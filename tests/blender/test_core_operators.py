# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores del proyecto (spec 002, T25; plan 002 §5.3; ADR-0011).

- RF-002-01, RF-002-03: «Nuevo proyecto…» crea el proyecto con las coordenadas de la
  ventana tecleadas con coma o punto decimal (texto, nunca float32) y lo deja abierto en
  escritura; con X e Y intercambiadas (o un número que no lo es) no crea nada y el
  mensaje nombra el campo.
- RF-002-04, RF-002-09: «Abrir proyecto…» es **modal** y avanza ``open_steps`` con
  progreso (en red puede pasar de 1 s); Esc cancela. Con el cerrojo libre, en escritura;
  si lo tiene otra sesión, en solo lectura con su titular.
- RF-002-10: un cerrojo caducado solo se fuerza con la confirmación del usuario y con el
  titular que vio; sin confirmar no cambia nada (también desde «Cerrojo del proyecto…»).
- RF-002-20: un esquema anterior se migra solo si el usuario lo acepta (con copia previa)
  y después se abre; si no, solo lectura «sin migrar».
- RF-002-06: «Cerrar proyecto» libera el cerrojo.
- ADR-0011: nombres ``GEOBLENDER_OT_core_<acción>`` y ``geoblender.core_<acción>``; sin
  ``UNDO`` (solo escriben en el proyecto y no crean objetos de la vista).
- RF-002-23, RF-002-24 (T27): «Sistema de referencia…» (en esta spec, solo consulta) y
  «Origen local…» muestran el CRS horizontal y vertical y el GeoOrigin del proyecto
  abierto.
- RF-002-34, RF-002-13, RF-002-30 (T28): la pestaña «Proyecto» de la Vista 3D (dibujada
  con un *layout* simulado) muestra el nombre, el modo (y en solo lectura su motivo, en
  alerta), el CRS horizontal y vertical, el GeoOrigin, la ventana y el paso, con espacio
  fino de miles, en español y, si se cambia el idioma, en inglés; sin traducciones que
  falten; y cada ruta de los datos de usuario sale de
  ``extension_path_user(bl.ADDON_PACKAGE, …)``.
- RF-002-27, RF-002-26 (T27): «Ventana de trabajo…» sin motivo se rechaza; con motivo, el
  origen nuevo queda en la base, la cabecera y la escena, con el evento ``move_origin``,
  las vistas desfasadas y ninguna coordenada absoluta guardada cambiada; una ventana de
  más de ±8 km avisa con el error estimado.

En ``blender -b`` no hay bucle de eventos: las pruebas de los modales los toman de
``window.modal_operators`` y les pasan los eventos ``TIMER`` y ``ESC``. Se ejecuta con
``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import datetime as dt
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

from gbtools import manifest  # noqa: E402

# El contexto de traducción de las clases es el nombre visible de la extensión (plan 003
# §5.3, contrato 1; docs/trampas.md §5).
CONTEXT = manifest.load(ROOT / manifest.MANIFEST_RELPATH)["name"]

WINDOW_TEXT = {
    "xmin": "699 500,4",
    "ymin": "4399500,6",
    "xmax": "700500.2",
    "ymax": "4 400 500,9",
}
WINDOW = (699_500.4, 4_399_500.6, 700_500.2, 4_400_500.9)
ORIGIN = (700_000, 4_400_000, 0)
OPERATORS = (
    "new_project", "open_project", "close_project", "save_project", "show_lock", "set_crs",
    "show_geoorigin", "set_work_window",
)
MOVED_TEXT = {
    "xmin": "700 500,4",
    "ymin": "4399500,6",
    "xmax": "701500.2",
    "ymax": "4 400 500,9",
}


def ext(name: str) -> ModuleType:
    """El módulo ``name`` de la copia de pruebas de la extensión (ya importado)."""
    return sys.modules[f"{module_name()}.{name}"]


def _m1_2(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS gb_test_m2 (fid INTEGER PRIMARY KEY, nota TEXT)")


def _m2_3(conn: sqlite3.Connection) -> None:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(gb_test_m2)")]
    if "extra" not in columns:
        conn.execute("ALTER TABLE gb_test_m2 ADD COLUMN extra TEXT")


class OperatorsTestCase(unittest.TestCase):
    """Cada prueba parte de la extensión habilitada, la escena de fábrica y una carpeta
    temporal para sus proyectos."""

    def setUp(self) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        self.tmp = Path(tempfile.mkdtemp(prefix="geoblender-t25-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(blender_ext.unload)
        blender_ext.enable()
        self.ps = ext("bl.scene.project_session")
        self.ops = ext("bl.ops.core")
        self.core = ext("core.project")
        self.lock = ext("core.project.lock")
        self.ps.take_notices()

    # Ayudas -------------------------------------------------------------------------

    def other_session(self) -> object:
        return ext("core.sysinfo").SessionInfo(
            "00000000-0000-4000-8000-0000000000c1", "PC-OTRO", "andres", 4242, "0.1.0"
        )

    def create_closed(self, name: str = "Cantera Prueba", session: object = None) -> Path:
        """Un proyecto creado con ``core`` y cerrado (o con el cerrojo de ``session``)."""
        settings = self.core.ProjectSettings(name=name, window=WINDOW)
        owner = self.ps.session() if session is None else session
        result = self.core.create_project(self.tmp, settings, owner, self.ps.userdata())
        if session is None:
            result.project.close()
        return result.root

    def write_stale_lock(self, root: Path, hours: float = 2.0) -> object:
        """Pone en ``root`` el cerrojo de otra sesión sin renovar desde hace ``hours``."""
        old = dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)
        when = ext("core.timeutil").format_utc(old)
        info = self.lock.LockInfo(
            "00000000-0000-4000-8000-0000000000c2", "PC-OTRO", "andres", 4242, when, when,
            "0.1.0", self.lock.LockMode.LOCAL,
        )
        (root / ".lock").write_bytes(self.lock.encode_lock(info))
        return info

    def events(self, root: Path) -> list[str]:
        gpkg = ext("core.gpkg")
        events = ext("core.project.events")
        with gpkg.GpkgConnection.open_read(root / "project.gpkg") as db:
            return [item.kind for item in events.read_events(db.connection)]

    def run_open(self, budget: float | None = None, **props: object) -> object:
        """Lanza «Abrir proyecto…» y lo lleva hasta el final con eventos ``TIMER``;
        devuelve el operador (con su ``progress_log`` y su ``outcome``)."""
        result = bpy.ops.geoblender.core_open_project("EXEC_DEFAULT", **props)
        self.assertEqual(result, {"RUNNING_MODAL"})
        operator = self.modal_operator()
        patch = (
            mock.patch.object(type(operator), "STEP_BUDGET_S", budget)
            if budget is not None
            else mock.patch.object(type(operator), "STEP_BUDGET_S", type(operator).STEP_BUDGET_S)
        )
        with patch:
            for _ in range(10_000):
                state = operator.modal(bpy.context, SimpleNamespace(type="TIMER", value="NOTHING"))
                if state != {"RUNNING_MODAL"}:
                    break
        self.assertIn(state, ({"FINISHED"}, {"CANCELLED"}))
        return operator

    def modal_operator(self) -> object:
        # Los que ya terminaron siguen en la lista (sin bucle de eventos, Blender no se
        # entera): el que está en marcha es el que aún tiene pasos.
        cls = self.ops.GEOBLENDER_OT_core_open_project
        running = [
            op
            for op in bpy.context.window.modal_operators
            if isinstance(op, cls) and getattr(op, "_steps", None) is not None
        ]
        self.assertEqual(len(running), 1, "«Abrir proyecto…» no está en marcha como modal")
        return running[0]


class NamingTest(OperatorsTestCase):
    def test_names_and_options(self) -> None:
        """ADR-0011, plan 002 §5.3: los cuatro operadores existen con
        ``geoblender.core_<acción>`` y su clase ``GEOBLENDER_OT_core_<acción>``, en el
        contexto de traducción «Geoblender» y **sin** ``UNDO`` (Ctrl+Z no deshace el
        proyecto)."""
        for action in OPERATORS:
            with self.subTest(operador=action):
                cls = getattr(self.ops, f"GEOBLENDER_OT_core_{action}")
                self.assertTrue(cls.is_registered)
                self.assertEqual(cls.bl_idname, f"geoblender.core_{action}")
                self.assertNotIn("UNDO", cls.bl_options)
                self.assertIn("REGISTER", cls.bl_options)
                self.assertEqual(cls.bl_translation_context, CONTEXT)
                self.assertTrue(hasattr(bpy.ops.geoblender, f"core_{action}"))
        self.assertTrue(hasattr(self.ops.GEOBLENDER_OT_core_open_project, "modal"))


class NewProjectTest(OperatorsTestCase):
    def test_create_with_decimal_comma(self) -> None:
        """RF-002-01, RF-002-03, RF-002-24: la ventana tecleada con coma decimal y
        espacios de miles crea el proyecto, ampliado y con su GeoOrigin, abierto en
        escritura con el cerrojo de la sesión y la georreferencia en la escena."""
        result = bpy.ops.geoblender.core_new_project(
            "EXEC_DEFAULT", directory=str(self.tmp), name="Cantera Prueba", **WINDOW_TEXT
        )
        self.assertEqual(result, {"FINISHED"})
        project = self.ps.current()
        self.assertIsNotNone(project)
        self.assertTrue(project.writable)
        self.assertEqual(project.root, self.tmp / "Cantera Prueba.gbproj")
        self.assertEqual((project.origin.x0, project.origin.y0, project.origin.z0), ORIGIN)
        window = project.window
        self.assertEqual(
            (window.xmin, window.ymin, window.xmax, window.ymax),
            (699_500.0, 4_399_500.0, 700_501.0, 4_400_501.0),
        )
        self.assertEqual(project.manifest.crs_epsg, 25830)
        self.assertEqual(project.manifest.vcrs_epsg, 5782)
        holder = self.lock.read_holder(project.root)
        self.assertEqual(holder.session_uid, self.ps.session().session_uid)
        props = bpy.context.scene.geoblender
        self.assertEqual((props.origin_x, props.origin_y, props.origin_z), ORIGIN)

    def test_local_vertical_and_grid_step(self) -> None:
        """RF-002-23, RF-002-24: una referencia vertical local con su descripción, un paso
        de 1,5 m y Z0 = −180 llegan al proyecto (ventana a múltiplos de 3 m)."""
        result = bpy.ops.geoblender.core_new_project(
            "EXEC_DEFAULT", directory=str(self.tmp), name="Local", vcrs="LOCAL",
            vcrs_note="NP-0 del plano 3", grid_step="1.5", z0=-180, **WINDOW_TEXT,
        )
        self.assertEqual(result, {"FINISHED"})
        project = self.ps.current()
        self.assertIsNone(project.manifest.vcrs_epsg)
        self.assertEqual(project.manifest.vcrs_note, "NP-0 del plano 3")
        self.assertEqual(project.grid_step_m, 1.5)
        self.assertEqual(project.origin.z0, -180)
        self.assertEqual(project.window.xmin % 3, 0)

    def test_swapped_axes_report_the_field(self) -> None:
        """RF-002-03: con X e Y intercambiadas no se crea nada y el mensaje nombra el
        campo (la ventana) y dice que pueden estar intercambiadas."""
        swapped = {
            "xmin": WINDOW_TEXT["ymin"], "ymin": WINDOW_TEXT["xmin"],
            "xmax": WINDOW_TEXT["ymax"], "ymax": WINDOW_TEXT["xmax"],
        }
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_new_project(
                "EXEC_DEFAULT", directory=str(self.tmp), name="Cantera Prueba", **swapped
            )
        message = str(caught.exception)
        self.assertIn("ventana", message)
        self.assertIn("intercambiadas", message)
        self.assertEqual(list(self.tmp.iterdir()), [])
        self.assertIsNone(self.ps.current())

    def test_bad_number_reports_the_field(self) -> None:
        """RF-002-03: un número que no lo es (dos separadores decimales) no crea nada y el
        mensaje nombra el campo y el valor."""
        values = dict(WINDOW_TEXT, xmin="700.000,4")
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_new_project(
                "EXEC_DEFAULT", directory=str(self.tmp), name="Cantera Prueba", **values
            )
        self.assertIn("xmin", str(caught.exception))
        self.assertIn("700.000,4", str(caught.exception))
        self.assertEqual(list(self.tmp.iterdir()), [])


class OpenProjectTest(OperatorsTestCase):
    def test_open_is_modal_with_progress(self) -> None:
        """RF-002-04: abrir es modal, avanza ``open_steps`` con un paso de progreso por
        fase (cabecera … apertura) y deja el proyecto abierto en escritura, con el cerrojo
        de la sesión y la georreferencia en la escena."""
        root = self.create_closed()
        operator = self.run_open(budget=0.0, directory=str(root))
        self.assertEqual(operator.outcome, "FINISHED")
        phases = [phase for phase, _message in operator.progress_log]
        unique = [phase for index, phase in enumerate(phases) if phase not in phases[:index]]
        self.assertEqual(unique, list(ext("core.project.open").PHASES))
        project = self.ps.current()
        self.assertIsNotNone(project)
        self.assertTrue(project.writable)
        self.assertEqual(project.root, root)
        self.assertEqual(self.lock.read_holder(root).session_uid, self.ps.session().session_uid)
        self.assertEqual(bpy.context.scene.geoblender.project_uid, project.uid)
        self.assertEqual(self.events(root)[-1], "open")

    def test_escape_cancels(self) -> None:
        """RF-002-04 (principio 9): Esc antes de terminar cancela sin abrir nada ni dejar
        el cerrojo."""
        root = self.create_closed()
        result = bpy.ops.geoblender.core_open_project("EXEC_DEFAULT", directory=str(root))
        self.assertEqual(result, {"RUNNING_MODAL"})
        operator = self.modal_operator()
        with mock.patch.object(type(operator), "STEP_BUDGET_S", 0.0):
            for _ in range(10):  # un paso por evento, hasta tomar el cerrojo
                if (root / ".lock").exists():
                    break
                state = operator.modal(bpy.context, SimpleNamespace(type="TIMER", value="NOTHING"))
                self.assertEqual(state, {"RUNNING_MODAL"})
            self.assertTrue((root / ".lock").exists())
            state = operator.modal(bpy.context, SimpleNamespace(type="ESC", value="PRESS"))
        self.assertEqual(state, {"CANCELLED"})
        self.assertIsNone(self.ps.current())
        self.assertFalse((root / ".lock").exists())

    def test_locked_opens_read_only_with_holder(self) -> None:
        """RF-002-09: si otra sesión tiene el cerrojo, se abre en solo lectura con su
        equipo, usuario y hora, y el cerrojo no cambia."""
        root = self.create_closed(session=self.other_session())
        before = (root / ".lock").read_bytes()
        operator = self.run_open(directory=str(root))
        self.assertEqual(operator.outcome, "FINISHED")
        project = self.ps.current()
        self.assertFalse(project.writable)
        self.assertEqual(project.read_only_reason, self.core.ReadOnlyCode.LOCKED)
        self.assertIn("andres", project.status.message)
        self.assertIn("PC-OTRO", project.status.message)
        self.assertEqual((root / ".lock").read_bytes(), before)

    def test_force_without_confirmation_keeps_lock(self) -> None:
        """RF-002-10: un cerrojo caducado no se fuerza sin confirmar: se abre en solo
        lectura, el aviso dice que se puede forzar y el cerrojo no cambia; tampoco desde
        «Cerrojo del proyecto…» sin confirmar."""
        root = self.create_closed()
        self.write_stale_lock(root)
        before = (root / ".lock").read_bytes()
        operator = self.run_open(directory=str(root))
        self.assertEqual(operator.outcome, "FINISHED")
        project = self.ps.current()
        self.assertFalse(project.writable)
        self.assertEqual((root / ".lock").read_bytes(), before)
        self.assertTrue(any("forzar" in text for text in operator.report_log), operator.report_log)
        self.assertEqual(bpy.ops.geoblender.core_show_lock("EXEC_DEFAULT"), {"FINISHED"})
        self.assertEqual((root / ".lock").read_bytes(), before)
        self.assertNotIn("lock_forced", self.events(root))

    def test_force_with_confirmation_and_seen_holder(self) -> None:
        """RF-002-10: confirmado y con el titular que vio el usuario, el cerrojo
        caducado se fuerza (escritura y evento ``lock_forced``); con otro titular, no."""
        root = self.create_closed()
        seen = self.write_stale_lock(root)
        other = json.dumps(dict(seen.to_dict(), session_uid="00000000-0000-4000-8000-0000000000c9"))
        before = (root / ".lock").read_bytes()
        operator = self.run_open(directory=str(root), force_lock=True, seen_lock=other)
        self.assertFalse(self.ps.current().writable)
        self.assertEqual((root / ".lock").read_bytes(), before)
        self.ps.close()
        operator = self.run_open(
            directory=str(root), force_lock=True, seen_lock=json.dumps(seen.to_dict())
        )
        self.assertEqual(operator.outcome, "FINISHED")
        project = self.ps.current()
        self.assertTrue(project.writable)
        self.assertEqual(self.lock.read_holder(root).session_uid, self.ps.session().session_uid)
        self.assertIn("lock_forced", self.events(root))

    def test_show_lock_forces_with_confirmation(self) -> None:
        """RF-002-10: desde «Cerrojo del proyecto…», con la confirmación y el titular que
        se vio, el proyecto abierto en solo lectura pasa a escritura forzando el cerrojo."""
        root = self.create_closed()
        seen = self.write_stale_lock(root)
        self.run_open(directory=str(root))
        self.assertFalse(self.ps.current().writable)
        result = bpy.ops.geoblender.core_show_lock(
            "EXEC_DEFAULT", force=True, seen_lock=json.dumps(seen.to_dict())
        )
        self.assertEqual(result, {"FINISHED"})
        operator = self.modal_operator()
        for _ in range(10_000):
            state = operator.modal(bpy.context, SimpleNamespace(type="TIMER", value="NOTHING"))
            if state != {"RUNNING_MODAL"}:
                break
        self.assertTrue(self.ps.current().writable)
        self.assertIn("lock_forced", self.events(root))

    def test_older_schema_migrates_only_if_accepted(self) -> None:
        """RF-002-20: con un esquema anterior, sin aceptar se abre en solo lectura «sin
        migrar» sin copia previa; aceptando, se hace la copia junto al original, se migra
        y se abre en escritura con el esquema nuevo."""
        root = self.create_closed()
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
            self.run_open(directory=str(root))
            project = self.ps.current()
            self.assertEqual(project.read_only_reason, self.core.ReadOnlyCode.NOT_MIGRATED)
            backup = self.tmp / "Cantera Prueba.gbproj.respaldo-esquema-1"
            self.assertFalse(backup.exists())
            self.ps.close()
            operator = self.run_open(directory=str(root), accept_migration=True)
            self.assertEqual(operator.outcome, "FINISHED")
            project = self.ps.current()
            self.assertTrue(project.writable)
            self.assertEqual(project.schema_version, 3)
            self.assertTrue(backup.is_dir())
            phases = {phase for phase, _message in operator.progress_log}
            self.assertLessEqual(set(migrations.PHASES), phases)


class CloseProjectTest(OperatorsTestCase):
    def test_close_releases_lock(self) -> None:
        """RF-002-06: «Cerrar proyecto» registra el cierre, libera el cerrojo y deja la
        sesión sin proyecto; sin proyecto no está disponible."""
        bpy.ops.geoblender.core_new_project(
            "EXEC_DEFAULT", directory=str(self.tmp), name="Cantera Prueba", **WINDOW_TEXT
        )
        root = self.ps.current().root
        self.assertTrue(bpy.ops.geoblender.core_close_project.poll())
        self.assertEqual(bpy.ops.geoblender.core_close_project("EXEC_DEFAULT"), {"FINISHED"})
        self.assertIsNone(self.ps.current())
        self.assertFalse((root / ".lock").exists())
        self.assertEqual(self.events(root)[-1], "close")
        self.assertFalse(bpy.ops.geoblender.core_close_project.poll())
        self.assertFalse(bpy.ops.geoblender.core_show_lock.poll())


class GeorefOperatorsTest(OperatorsTestCase):
    def new_project(self) -> object:
        result = bpy.ops.geoblender.core_new_project(
            "EXEC_DEFAULT", directory=str(self.tmp), name="Cantera Prueba", **WINDOW_TEXT
        )
        self.assertEqual(result, {"FINISHED"})
        return self.ps.current()

    def add_layer(self, project: object) -> None:
        """Una capa con coordenadas absolutas con milímetros, escrita por ``core``."""
        base = ext("core.gpkg.base")
        gpkg = ext("core.gpkg")
        polygon = [[[(700_123.456, 4_400_987.654), (700_223.456, 4_400_987.654),
                     (700_223.456, 4_401_087.654), (700_123.456, 4_400_987.654)]]]
        with project.write_transaction() as conn:
            base.create_feature_table(
                conn, "gis_limites", "MULTIPOLYGON", 25830, False, [], identifier="Límites"
            )
            blob = gpkg.encode_geometry("MULTIPOLYGON", polygon, 25830, False)
            conn.execute("INSERT INTO gis_limites (geom) VALUES (?)", (blob,))

    def layer(self, root: Path) -> list[tuple]:
        conn = sqlite3.connect(root / "project.gpkg")
        try:
            return conn.execute("SELECT fid, geom FROM gis_limites ORDER BY fid").fetchall()
        finally:
            conn.close()

    def test_consult_crs_and_geoorigin(self) -> None:
        """RF-002-23, RF-002-24: con un proyecto abierto, «Sistema de referencia…» y
        «Origen local…» terminan y su texto da el CRS horizontal y vertical (código y
        nombre) y el GeoOrigin con espacio fino de miles; sin proyecto no están
        disponibles."""
        self.new_project()
        self.assertEqual(bpy.ops.geoblender.core_set_crs("EXEC_DEFAULT"), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.core_show_geoorigin("EXEC_DEFAULT"), {"FINISHED"})
        crs_text = " ".join(self.ops.crs_lines(self.ps.current()))
        self.assertIn("EPSG:25830", crs_text)
        self.assertIn("ETRS89 / UTM zone 30N", crs_text)
        self.assertIn("EPSG:5782", crs_text)
        origin_text = " ".join(self.ops.origin_lines(self.ps.current()))
        self.assertIn("X 700\u202f000  Y 4\u202f400\u202f000  Z 0", origin_text)
        self.assertIn("699\u202f500", origin_text)
        bpy.ops.geoblender.core_close_project("EXEC_DEFAULT")
        self.assertFalse(bpy.ops.geoblender.core_set_crs.poll())
        self.assertFalse(bpy.ops.geoblender.core_show_geoorigin.poll())
        self.assertFalse(bpy.ops.geoblender.core_set_work_window.poll())

    def test_window_change_requires_reason(self) -> None:
        """RF-002-27: cambiar la ventana sin motivo se rechaza (el mensaje nombra el
        motivo) y no cambia nada: ni el origen, ni la cabecera, ni hay evento."""
        project = self.new_project()
        header = (project.root / "manifest.json").read_bytes()
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_set_work_window("EXEC_DEFAULT", reason="  ", **MOVED_TEXT)
        self.assertIn("motivo", str(caught.exception))
        self.assertEqual((project.origin.x0, project.origin.y0), ORIGIN[:2])
        self.assertEqual((project.root / "manifest.json").read_bytes(), header)
        self.assertNotIn("move_origin", self.events(project.root))
        self.assertEqual(bpy.context.scene.geoblender.origin_x, ORIGIN[0])

    def test_window_change_moves_origin(self) -> None:
        """RF-002-27: con motivo, el origen nuevo (701 000; 4 400 000; 0) queda en la base,
        la cabecera y todas las escenas, hay un evento ``move_origin`` con el motivo, las
        vistas quedan desfasadas y la capa con coordenadas absolutas no cambia ni un
        byte."""
        project = self.new_project()
        bpy.data.scenes.new("Segunda")
        self.add_layer(project)
        before = self.layer(project.root)
        result = bpy.ops.geoblender.core_set_work_window(
            "EXEC_DEFAULT", reason="Ampliación hacia el este", **MOVED_TEXT
        )
        self.assertEqual(result, {"FINISHED"})
        moved = (701_000, 4_400_000, 0)
        record = project.reload()
        self.assertEqual((record.origin_x, record.origin_y, record.origin_z), moved)
        header = ext("core.project.manifest").read_manifest(project.root)
        self.assertEqual(header.origin.as_tuple(), moved)
        for scene in bpy.data.scenes:
            props = scene.geoblender
            self.assertEqual((props.origin_x, props.origin_y, props.origin_z), moved)
            self.assertTrue(props.view_stale)
        self.assertEqual(self.events(project.root)[-1], "move_origin")
        self.assertEqual(self.layer(project.root), before)

    def test_window_change_with_header_failure(self) -> None:
        """RF-002-27, RF-002-12: si la cabecera no se puede escribir después de guardar el
        origen nuevo en la base (``os.replace`` falla), «Ventana de trabajo…» termina, todas
        las escenas pasan al origen de la base con la vista desfasada, el proyecto queda en
        solo lectura con su motivo y el aviso (la cabecera se regenerará al abrirlo) queda
        para la interfaz (convergencia, T40)."""
        project = self.new_project()
        header = (project.root / "manifest.json").read_bytes()
        failure = OSError(5, "red caída (simulada)")
        with mock.patch.object(ext("core.project.manifest").os, "replace", side_effect=failure):
            result = bpy.ops.geoblender.core_set_work_window(
                "EXEC_DEFAULT", reason="Ampliación hacia el este", **MOVED_TEXT
            )
        self.assertEqual(result, {"FINISHED"})
        moved = (701_000, 4_400_000, 0)
        self.assertEqual(project.origin.as_tuple(), moved)
        self.assertEqual((project.root / "manifest.json").read_bytes(), header)
        for scene in bpy.data.scenes:
            props = scene.geoblender
            self.assertEqual((props.origin_x, props.origin_y, props.origin_z), moved)
            self.assertTrue(props.view_stale)
        self.assertFalse(project.writable)
        notices = self.ps.take_notices()
        self.assertTrue(any("cabecera" in text for text in notices), notices)

    def test_window_far_from_origin_warns(self) -> None:
        """RF-002-26: una ventana de 20 × 20 km se acepta con un aviso de las esquinas a
        más de 8 km del GeoOrigin y el error estimado en mm."""
        self.new_project()
        wide = {"xmin": "690000", "ymin": "4390000", "xmax": "710000", "ymax": "4410000"}
        result = bpy.ops.geoblender.core_set_work_window(
            "EXEC_DEFAULT", reason="Ventana regional", **wide
        )
        self.assertEqual(result, {"FINISHED"})
        notices = self.ps.take_notices()
        self.assertTrue(any("esquinas" in text and "mm" in text for text in notices), notices)

    def test_read_only_cannot_change_window(self) -> None:
        """RF-002-13, RF-002-27: con el proyecto en solo lectura, «Ventana de trabajo…» no
        está disponible."""
        root = self.create_closed(session=self.other_session())
        self.run_open(directory=str(root))
        self.assertFalse(self.ps.current().writable)
        self.assertFalse(bpy.ops.geoblender.core_set_work_window.poll())
        self.assertTrue(bpy.ops.geoblender.core_show_geoorigin.poll())


class PanelTest(OperatorsTestCase):
    THIN = "\u202f"

    def setUp(self) -> None:
        super().setUp()
        self.i18n = ext("core.i18n")
        self.addCleanup(self.i18n.set_language, "es")
        self.panel = ext("bl.ui.core_panel").GEOBLENDER_PT_core_project

    def new_project(self) -> object:
        bpy.ops.geoblender.core_new_project(
            "EXEC_DEFAULT", directory=str(self.tmp), name="Cantera Prueba", **WINDOW_TEXT
        )
        return self.ps.current()

    def test_panel_registered_in_project_tab(self) -> None:
        """RF-002-34 (ADR-0011): ``GEOBLENDER_PT_core_project`` está registrado en la región
        lateral de la Vista 3D, en la pestaña «Proyecto» (traducida al registrar)."""
        self.assertTrue(self.panel.is_registered)
        self.assertEqual((self.panel.bl_space_type, self.panel.bl_region_type), ("VIEW_3D", "UI"))
        self.assertEqual(self.panel.bl_category, "Proyecto")
        self.assertEqual(self.panel.bl_translation_context, CONTEXT)

    def test_panel_shows_the_six_data(self) -> None:
        """RF-002-34: con un proyecto abierto, el panel muestra su nombre, el modo, el CRS
        horizontal y vertical, el GeoOrigin, la ventana de trabajo y el paso de rejilla,
        con espacio fino de miles y coma decimal, el diario «clásico» y los botones del
        proyecto; ningún texto se queda sin traducir."""
        self.new_project()
        layout = draw(self.panel, bpy.context)
        texts = "\n".join(layout.texts())
        thin = self.THIN
        for expected in (
            "Nombre: Cantera Prueba",
            "Modo: escritura (disco local)",
            "CRS horizontal: EPSG:25830 · ETRS89 / UTM zone 30N",
            "CRS vertical: EPSG:5782",
            f"GeoOrigin: X 700{thin}000  Y 4{thin}400{thin}000  Z 0 m",
            f"Ventana de trabajo: X 699{thin}500 – 700{thin}501, Y 4{thin}399{thin}500 – "
            f"4{thin}400{thin}501 m",
            "Paso de rejilla: 1,0 m",
            "Diario: clásico",
        ):
            with self.subTest(dato=expected):
                self.assertIn(expected, texts)
        operators = {item.target for item in layout.of_kind("operator")}
        self.assertLessEqual(
            {f"geoblender.core_{name}" for name in (
                "save_project", "set_work_window", "set_crs", "show_geoorigin", "show_lock",
                "open_project", "new_project", "close_project",
            )},
            operators,
        )
        self.assertEqual([m for m in self.i18n.missing_translations()], [])

    def test_read_only_mode_with_reason_in_alert(self) -> None:
        """RF-002-13: en solo lectura, el modo dice «solo lectura» con su motivo (quién lo
        tiene) y se dibuja en alerta, siempre a la vista."""
        root = self.create_closed(session=self.other_session())
        self.run_open(directory=str(root))
        layout = draw(self.panel, bpy.context)
        (mode,) = [item for item in layout.of_kind("label") if item.text.startswith("Modo:")]
        self.assertIn("solo lectura", mode.text)
        self.assertIn("andres", mode.text)
        self.assertTrue(mode.alert)

    def test_english_interface(self) -> None:
        """RF-002-34 (ADR-0012): con el idioma en inglés, los mismos datos en inglés y las
        coordenadas sin separador de miles."""
        self.new_project()
        self.i18n.set_language("en")
        texts = "\n".join(draw(self.panel, bpy.context).texts())
        self.assertIn("Name: Cantera Prueba", texts)
        self.assertIn("Mode: writing (local disk)", texts)
        self.assertIn("GeoOrigin: X 700000  Y 4400000  Z 0 m", texts)
        self.assertIn("Grid step: 1.0 m", texts)

    def test_without_project_and_notices(self) -> None:
        """RF-002-34, RF-002-29: sin proyecto, el panel lo dice y ofrece crear, abrir y los
        recientes; un aviso pendiente (vista de un proyecto que no está abierto) se ve en
        alerta y se descarta con su botón."""
        project = self.new_project()
        bpy.ops.geoblender.core_save_project("EXEC_DEFAULT")
        blend = bpy.data.filepath
        bpy.ops.geoblender.core_close_project("EXEC_DEFAULT")
        self.ps.take_notices()
        blender_ext.load_file(blend)
        layout = draw(self.panel, bpy.context)
        texts = layout.texts()
        self.assertIn("No hay ningún proyecto abierto", texts)
        self.assertIn("geoblender.core_new_project", {i.target for i in layout.of_kind("operator")})
        self.assertIn("GEOBLENDER_MT_core_recent", {i.target for i in layout.of_kind("menu")})
        alerts = [item.text for item in layout.items if item.alert and item.kind == "label"]
        self.assertTrue(any(project.name in text for text in alerts), alerts)
        self.assertEqual(bpy.ops.geoblender.core_clear_notices("EXEC_DEFAULT"), {"FINISHED"})
        self.assertEqual(self.ps.notices(), ())

    def test_user_data_paths_from_extension_path_user(self) -> None:
        """RF-002-08, RF-002-13, RF-002-19, RF-002-30, RF-002-31 (plan 001 §2.1, 14): cada
        ruta de los datos de usuario (recientes, rutas externas, copia local, cachés,
        copias privadas y carpeta de copias) se resuelve con
        ``extension_path_user(bl.ADDON_PACKAGE, …)`` sin error, y se puede escribir en
        ella."""
        package = ext("bl").ADDON_PACKAGE
        userdata = self.ps.userdata()
        root = Path(bpy.utils.extension_path_user(package))
        self.assertEqual(Path(userdata.root), root)
        uid = "00000000-0000-4000-8000-0000000000d1"
        session = self.ps.session().session_uid
        cases = {
            "projects/recent.json": root / "projects" / "recent.json",
            f"projects/{uid}/external_refs.json": userdata.project_dir(uid) / "external_refs.json",
            f"projects/{uid}/checkout.json": userdata.project_dir(uid) / "checkout.json",
            f"cache/{uid}": userdata.cache_dir(uid),
            "cache/_sin_proyecto": userdata.no_project_cache_dir(),
            f"readonly/{session}": userdata.private_read_dir(session),
            "checkouts": userdata.checkouts_dir(),
        }
        for relative, expected in cases.items():
            with self.subTest(ruta=relative):
                folder = relative if "." not in Path(relative).name else str(Path(relative).parent)
                resolved = Path(bpy.utils.extension_path_user(package, path=folder, create=True))
                self.assertTrue(resolved.is_dir())
                self.assertEqual(resolved / Path(relative).name if folder != relative else resolved,
                                 expected)
        userdata.add_recent(uid, "Prueba", self.tmp / "Prueba.gbproj", "2026-10-06T08:00:00.000Z")
        userdata.set_external_ref(uid, "ref1", self.tmp / "otra" / "datos.gpkg")
        userdata.set_checkout_record(uid, {"original": str(self.tmp / "Prueba.gbproj")})
        for name in ("projects/recent.json", f"projects/{uid}/external_refs.json",
                     f"projects/{uid}/checkout.json"):
            self.assertTrue((root / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
