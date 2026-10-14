# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl+Z y lo registrado en el proyecto (spec 008, T57; plan 008 §5.4.11 y D13).

- RF-008-32: cada cambio registrado (un parámetro con Cambiar, una operación de un módulo
  hecha con ``ProvenanceAwareOperator``) recibe su número del diario de Ctrl+Z de la sesión y
  sella con él todas las escenas (``Scene.geoblender.registry_seq``) sin empujar un paso de
  deshacer. Al deshacer y rehacer de verdad (``ed.undo``/``ed.redo``), los manejadores
  persistentes ``undo_post`` y ``redo_post`` comparan el número de la escena restaurada con el
  diario y avisan en la barra de estado con el texto de la spec («Ctrl+Z no deshace la
  operación «…»: sigue en el proyecto»), también en la secuencia deshacer → rehacer →
  deshacer (cada vez el suyo), sin cambiar nada de lo registrado (``project.gpkg`` con la
  misma huella, el diario igual). Una escena sin ``Scene.geoblender`` no avisa; un ``.blend``
  recién abierto (``load_post``) empieza su historia; desactivar Geoblender quita los
  manejadores.

Se ejecuta con ``tools/run_blender_tests.py``. El deshacer de Blender funciona en
``blender -b`` con ``ed.undo_push``: una orden lanzada desde un guion no empuja su paso.
"""

import hashlib
import importlib
import shutil
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.provenance_demo import DIGITIZE, Demo

MAX_TICKS = 300  # la comprobación de un proyecto vacío acaba en unas decenas de pasos
COPY_LIMIT = "core.original_copy_limit"
MODULE_ORDER = "gbtest.undo_selftest"  # la orden sintética de un módulo
UNDO_OPERATION = "Ctrl+Z no deshace la operación «demo.digitize»: sigue en el proyecto"
REDO_OPERATION = ("Ctrl+Mayús+Z no rehace la operación «demo.digitize»: no se deshizo y sigue "
                  "en el proyecto")
UNDO_PARAMETER = "Ctrl+Z no deshace el cambio de «core.original_copy_limit»: sigue en el proyecto"
HANDLERS = ("undo_post", "redo_post", "load_post")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class ProvenanceUndoTest(unittest.TestCase):
    """Con la extensión habilitada una vez para todas y una carpeta temporal."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.watch = _module("bl.scene.undo_watch")
        cls.ui = _module("bl.ui.provenance")
        cls.session = _module("bl.ops.core_provenance")
        cls.ps = _module("bl.scene.project_session")
        cls.core = _module("core.project")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def setUp(self) -> None:
        if not blender_ext.is_enabled():  # otra prueba la desactivó
            blender_ext.enable()
        self.tmp = Path(tempfile.mkdtemp(prefix="gb-t57-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(self.ps.take_notices)
        self.addCleanup(self.ps.close)

    # Ayudas -------------------------------------------------------------------------------

    def create(self) -> object:
        """Un proyecto nuevo (del esquema 2), abierto en escritura y aún fuera de la sesión."""
        settings = self.core.ProjectSettings(**settings_values())
        return self.core.create_project(self.tmp, settings, self.ps.session(),
                                        self.ps.userdata()).project

    def run_checks(self) -> None:
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                return
        self.fail("la comprobación no termina")

    def module_order(self) -> None:
        """Registra hasta el final de la prueba una orden sintética de un módulo: con
        ``ProvenanceAwareOperator``, empieza ``demo.digitize`` y la completa sin salidas."""
        session = self.session

        class GBTEST_OT_undo_selftest(session.ProvenanceAwareOperator, bpy.types.Operator):
            bl_idname = MODULE_ORDER
            bl_label = "Undo self-test"
            bl_options = {"REGISTER", "UNDO"}
            provenance_op_type = DIGITIZE

            def execute(self, context: object) -> set[str]:
                handle = self.begin(context)
                if handle is None:
                    return {"CANCELLED"}
                with handle.project.write_transaction() as conn:
                    handle.complete(conn)
                return {"FINISHED"}

        bpy.utils.register_class(GBTEST_OT_undo_selftest)
        self.addCleanup(bpy.utils.unregister_class, GBTEST_OT_undo_selftest)

    @staticmethod
    def stamped() -> list[int]:
        return [scene.geoblender.registry_seq for scene in bpy.data.scenes]

    def step(self, action: str) -> str:
        """Deshace o rehace un paso de Blender (``undo``/``redo``) y devuelve el aviso de la
        barra de estado."""
        self.assertEqual(getattr(bpy.ops.ed, action)(), {"FINISHED"})
        return self.ui.undo_notice()

    # Pruebas ------------------------------------------------------------------------------

    def test_ctrl_z_warns_and_keeps_what_is_registered(self) -> None:
        """RF-008-32: Cambiar un parámetro y una operación de un módulo hecha sellan todas las
        escenas con su número del diario, después del que traía la escena aunque el diario no
        lo conociera. Con un paso de Blender tras cada uno, deshacer avisa
        «Ctrl+Z no deshace la operación «demo.digitize»: sigue en el proyecto», rehacer
        «Ctrl+Mayús+Z no rehace la operación…: no se deshizo y sigue en el proyecto», deshacer
        otra vez lo mismo que la primera y uno más, «Ctrl+Z no deshace el cambio de
        «core.original_copy_limit»…»; ``project.gpkg`` tiene la misma huella, el diario no
        cambia y el parámetro y la operación siguen en el proyecto. Una escena sin
        ``Scene.geoblender`` no avisa ni mueve el diario, y tras ``load_post`` lo registrado
        antes del ``.blend`` no avisa."""
        project = self.create()
        self.enterContext(Demo(module_name()).registered())
        store = _module("core.params").ParameterStore(project)
        with project.write_transaction() as conn:
            store.ensure_default(conn, COPY_LIMIT, geoblender_version="0.1.0")
        self.module_order()
        self.ps.attach(project)
        self.run_checks()
        journal = self.watch.JOURNAL
        self.assertIs(self.session.SESSION.journal, journal)
        # Una escena con un número que el diario no conoce (Geoblender se habilitó con el
        # .blend ya abierto): lo registrado después va tras el suyo.
        start = journal.last + 40
        bpy.context.scene.geoblender.registry_seq = start
        bpy.ops.ed.undo_push(message="T57: antes")

        other = bpy.data.scenes.new("T57")
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=COPY_LIMIT, value="300", source="Acta de prueba", source_kind="DOCUMENT",
            decided_by="la propiedad", reason="Prueba de Ctrl+Z"), {"FINISHED"})
        self.assertEqual(self.stamped(), [start + 1, start + 1])  # todas las escenas
        bpy.data.scenes.remove(other)
        bpy.ops.ed.undo_push(message="T57: parámetro")
        self.assertEqual(bpy.ops.gbtest.undo_selftest(), {"FINISHED"})
        self.assertEqual(self.stamped(), [start + 2])
        bpy.ops.ed.undo_push(message="T57: operación")
        entries = journal.entries
        self.assertEqual([(str(entry.kind), entry.label) for entry in entries[-2:]],
                         [("parameter", COPY_LIMIT), ("operation", DIGITIZE)])
        digest = _digest(project.database_path)

        self.assertEqual(self.step("undo"), UNDO_OPERATION)
        self.assertEqual(self.stamped(), [start + 1])
        self.assertEqual(self.step("redo"), REDO_OPERATION)
        self.assertEqual(self.step("undo"), UNDO_OPERATION)
        self.assertEqual(self.step("undo"), UNDO_PARAMETER)
        self.assertEqual(_digest(project.database_path), digest)
        self.assertEqual(journal.entries, entries)
        self.assertEqual(store.get(COPY_LIMIT).value, 300.0)
        with project.read() as conn:
            done = conn.execute("SELECT status FROM gb_operation WHERE op_type = ?",
                                (DIGITIZE,)).fetchall()
        self.assertEqual(done, [("done",)])

        shown = journal.scene_seq
        with mock.patch.object(self.ui, "show_undo_notice") as show:
            self.watch.on_undo_post(SimpleNamespace(), None)
            self.watch.on_redo_post(SimpleNamespace(), None)
            show.assert_not_called()
            self.assertEqual(journal.scene_seq, shown)
            self.watch.on_load_post("")  # un .blend recién abierto, con su número
            later = SimpleNamespace(geoblender=SimpleNamespace(registry_seq=start + 2))
            self.watch.on_redo_post(later, None)
            show.assert_not_called()
        self.assertEqual(journal.entries, entries)

    def test_disabling_removes_the_handlers(self) -> None:
        """RF-008-32 (principio 8): habilitar añade los manejadores persistentes
        ``undo_post``, ``redo_post`` y ``load_post`` del diario; desactivar Geoblender los
        quita."""
        functions = dict(self.watch.HANDLERS)
        self.assertEqual(sorted(functions), sorted(HANDLERS))
        for name, function in functions.items():
            self.assertIn(function, getattr(bpy.app.handlers, name))
            self.assertTrue(hasattr(function, "_bpy_persistent"))  # lo pone @persistent
        blender_ext.disable()  # la última de la clase: no se vuelve a habilitar
        for name, function in functions.items():
            self.assertNotIn(function, getattr(bpy.app.handlers, name))


if __name__ == "__main__":
    unittest.main()
