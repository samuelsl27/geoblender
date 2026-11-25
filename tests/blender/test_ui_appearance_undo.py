# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl+Z y el aspecto ya escrito en el proyecto (spec 019, T14c; D-Z1 opción A; RF-019-08; plan 019 R-5; UI-05, UI-11, UI-15).

Con ``ed.undo()`` real en ``blender -b``:

- Antes de los 0,5 s la tabla no llegó a escribirse: Ctrl+Z **sí** deshace y no avisa.
- Pasados los 0,5 s la tabla ya lo tiene y manda (R-5): Ctrl+Z no cambia el valor y la barra de estado lo dice (10 s, un solo
  aviso aunque se hayan revertido varios elementos), sin escribir nada en el proyecto.
- Un deshacer que no revierte lo guardado no avisa.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.trees import temp_folder

NOTICE = ("El aspecto ya está guardado en el proyecto: Ctrl+Z no lo deshace. Cámbielo de nuevo o use «Restablecer» "
          "para volver al predefinido")


def _appearance() -> Any:
    return vf.extension("bl.scene.appearance")


class AppearanceUndoTest(unittest.TestCase):
    def setUp(self) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(blender_ext.release)
        self.clock = [100.0]
        _appearance().set_clock(lambda: self.clock[0])
        self.addCleanup(_appearance().set_clock, None)
        self.addCleanup(_appearance().discard)
        self.project = vf.ViewsProject(temp_folder(self, "gb-t14c-"), grids=2)
        self.addCleanup(self.project.close)
        self.project.attach()
        self.project.load(bpy.context)
        self.names = sorted(o.name for o in bpy.data.objects if o.geoblender.kind == "DTM")
        self.assertEqual(len(self.names), 2)
        self.ui = vf.extension("bl.ui.provenance")

    def obj(self, index: int = 0) -> bpy.types.Object:
        return bpy.data.objects[self.names[index]]

    def hex(self, index: int = 0) -> str:
        return _appearance().read(self.obj(index)).get("color")

    def rows(self) -> list[tuple[str, str, str]]:
        with self.project.project.read() as conn:
            return [tuple(map(str, r)) for r in conn.execute("SELECT item_name, prop, value FROM gb_appearance ORDER BY 1, 2")]

    def change(self, value: tuple[float, float, float], *indexes: int) -> None:
        for index in indexes:
            self.obj(index).geoblender.look.color = value
        bpy.ops.ed.undo_push(message="cambio de aspecto")

    @staticmethod
    def notices(show: Any) -> list[str]:
        """Los avisos de esta tarea entre los que recibió la barra (otros ``undo_post`` pueden dejar el suyo, el de la 008)."""
        return [c.args[0] for c in show.call_args_list if c.args[0] == NOTICE]

    def write_now(self) -> None:
        self.clock[0] += 1.0
        _appearance().sweep(self.clock[0] + 1.0)

    def test_undo_after_the_write_warns_and_the_value_stays(self) -> None:
        """D-Z1 (A): pasados 0,5 s, Ctrl+Z no cambia el valor, lo dice y no escribe nada."""
        bpy.ops.ed.undo_push(message="base")
        self.change((1.0, 0.0, 0.0), 0)
        self.write_now()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        counter = self.project.change_counter()
        with mock.patch.object(self.ui, "show_undo_notice") as show:
            bpy.ops.ed.undo()
        self.assertEqual(self.hex(), "#FF0000")
        self.assertEqual(self.notices(show), [NOTICE])
        self.assertEqual(self.rows(), rows)
        self.assertEqual(self.project.change_counter(), counter)

    def test_several_reverted_changes_make_one_notice(self) -> None:
        """Dos elementos con el cambio ya escrito: un solo aviso."""
        bpy.ops.ed.undo_push(message="base")
        self.change((0.0, 1.0, 0.0), 0, 1)
        self.write_now()
        with mock.patch.object(self.ui, "show_undo_notice") as show:
            bpy.ops.ed.undo()
        self.assertEqual(len(self.notices(show)), 1)
        self.assertEqual((self.hex(0), self.hex(1)), ("#00FF00", "#00FF00"))

    def test_undo_before_the_write_undoes_and_says_nothing(self) -> None:
        """Antes de los 0,5 s la tabla no lo tiene: se deshace de verdad y no se avisa."""
        bpy.ops.ed.undo_push(message="base")
        before = self.hex()
        self.change((1.0, 0.0, 0.0), 0)
        with mock.patch.object(self.ui, "show_undo_notice") as show:
            bpy.ops.ed.undo()
        self.assertEqual(self.notices(show), [])
        self.assertEqual(self.hex(), before)
        self.write_now()
        self.assertEqual(self.rows(), [])

    def test_undo_that_reverts_nothing_stored_says_nothing(self) -> None:
        """Un deshacer de otra cosa (el espejo ya coincide con la tabla) no avisa."""
        self.change((1.0, 0.0, 0.0), 0)
        self.write_now()
        bpy.ops.ed.undo_push(message="otra cosa")
        self.obj().location.x += 1.0
        bpy.ops.ed.undo_push(message="mover")
        with mock.patch.object(self.ui, "show_undo_notice") as show:
            bpy.ops.ed.undo()
        self.assertEqual(self.notices(show), [])
        self.assertEqual(self.hex(), "#FF0000")


if __name__ == "__main__":
    unittest.main()
