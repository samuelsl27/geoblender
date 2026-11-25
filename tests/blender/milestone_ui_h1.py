# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H1 de la spec 019 (HU-019-1; RF-019-06 a 13; RNF-019-03; plan 019 §7.4): el panel y el aspecto funcionan en Blender
(``blender -b``) con una superficie, una corta y una pista, sobreviven a guardar, cerrar, reabrir y refrescar, y no cambian
ninguna cifra, versión ni marca de obsoleto.

Una sola cadena, como la hace una persona: elegir el elemento (ficha, aspecto), cambiar color y transparencia, guardar el
``.blend``, cerrar el proyecto, abrir el fichero y el proyecto, recalcular y refrescar, abrirlo en solo lectura. Lo suelto
está en ``test_ui_element_panel`` y ``test_ui_appearance_roundtrip``; aquí, lo junto. Lo hace pasar la sesión principal con
``tools/check.py --completo`` (paso «hito»).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from pathlib import Path
from unittest import mock

import bpy

from tests.blender.test_ui_appearance_roundtrip import KINDS, RoundtripCase, _appearance, _hex
from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.fake_layout import draw

ELEMENT = "GEOBLENDER_PT_ui_element"
LOOK = "GEOBLENDER_PT_ui_element_look"
PROJECT = "GEOBLENDER_PT_ui_project"


class UiH1Test(RoundtripCase):
    def drawn(self, panel: str) -> list[str]:
        with mock.patch.object(vf.extension("bl.ui.labels"), "sidebar_width", return_value=1000.0):
            layout = draw(getattr(bpy.types, panel), bpy.context)
        return [item.text for item in layout.of_kind("label")]

    def activate(self, obj: bpy.types.Object) -> None:
        for other in bpy.data.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

    def test_panel_and_appearance_survive_save_close_open_refresh_and_read_only(self) -> None:
        """H1: la cadena entera con superficie, corta y pista; ningún hash, versión, operación ni obsoleto cambia."""
        before = self.counts()
        changed = {}
        for index, obj in enumerate(self.objs):
            self.activate(obj)
            self.assertTrue(getattr(bpy.types, ELEMENT).poll(bpy.context), obj.geoblender.kind)
            self.assertTrue(getattr(bpy.types, LOOK).poll(bpy.context), obj.geoblender.kind)
            defaults = self.drawn(LOOK).count("predefinido")
            self.assertGreater(defaults, 0)
            obj.geoblender.look.color = (0.1 * (index + 1), 0.5, 0.9)
            obj.geoblender.look.transparency = 25 + 10 * index
            changed[self.name(obj)] = (_hex(obj), 25 + 10 * index)
            self.assertEqual(self.drawn(LOOK).count("predefinido"), defaults - 2)  # color y transparencia ya no
        self.assertEqual(_appearance().flush(), 6)
        # Sin elemento activo: el estado del proyecto, no un panel vacío.
        for obj in bpy.data.objects:
            obj.select_set(False)
        bpy.context.view_layer.objects.active = None
        self.assertTrue(any("Cantera Prueba" in text for text in self.drawn(PROJECT)))

        # Guardar, cerrar, abrir.
        path = str(Path(self.folder) / "h1.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        self.data.close()
        blender_ext.load_file(path)
        objs = [o for o in bpy.data.objects if o.geoblender.kind in KINDS]
        for obj in objs:  # sin espejo ni color: lo que dice la tabla manda
            obj.geoblender.look.property_unset("color")
            obj.geoblender.look.property_unset("transparency")
            obj.color = (0.5, 0.5, 0.5, 1.0)
        self.reopen()
        for obj in objs:
            name = str(self.data.record(obj.geoblender.dataset_uid).name)
            self.assertEqual((_hex(obj), obj.geoblender.look.transparency), changed[name], name)

        # Recalcular y refrescar: lo vuelto a cargar conserva su aspecto, y es de verdad otro objeto.
        grid = next(o for o in objs if o.geoblender.kind == "DTM")
        uid, session = grid.geoblender.dataset_uid, grid.session_uid
        recomputed = self.data.recompute(uid)
        self.assertEqual(bpy.ops.geoblender.core_refresh("EXEC_DEFAULT"), {"FINISHED"})
        (again,) = vf.objects_of(bpy.data, uid)
        self.assertNotEqual(again.session_uid, session)
        name = str(self.data.record(uid).name)
        self.assertEqual((_hex(again), again.geoblender.look.transparency), changed[name])
        self.assertEqual(again.geoblender.content_sha256, recomputed.content_sha256)
        self.assertEqual(self.rows(), {n: {"color": v[0], "transparency": str(v[1])} for n, v in changed.items()})

        # Las cifras, versiones y obsoletos: solo cambia lo que cambió el recálculo (un hash nuevo), nunca el aspecto.
        after = self.counts()
        for table in ("gb_version", "gb_stale"):
            self.assertEqual(before[table], after[table], table)

        # Solo lectura: el espejo sigue, la tabla no se toca y el panel lo dice.
        self.reopen(write=False)
        for obj in (o for o in bpy.data.objects if o.geoblender.kind in KINDS):
            self.assertIn(_hex(obj), {v[0] for v in changed.values()})
        self.activate(again)
        again.geoblender.look.color = (0.0, 0.0, 0.0)
        stored = self.rows()
        self.assertEqual(_appearance().flush(), 0)
        self.assertEqual(self.rows(), stored)
        self.assertTrue(any("solo lectura" in text for text in self.drawn(LOOK)))


if __name__ == "__main__":
    unittest.main()
