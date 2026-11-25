# SPDX-License-Identifier: GPL-3.0-or-later
"""Avisos de la barra de estado con plazo (spec 019, T22; RF-019-18; D-10; plan 019 A5; UI-09, UI-11, UI-22/23,
UI-38).

- RF-019-18: lo que una orden de Geoblender escribe por ``report`` queda también en la cola de avisos y el campo
  «notice» de la barra de estado muestra el último vivo; vive 15 s (a los 14 s está, a los 15 no: el «ahora» se
  inyecta); el aviso de Ctrl+Z, 10 s; cambiar la selección o el objeto activo lo retira.
- RF-019-18: cancelar (una orden que devuelve ``CANCELLED`` sin informar de nada), cambiar de proyecto o de versión y
  conmutar a Blender limpian los avisos; ningún temporizador queda vivo tras limpiar ni al desactivar Geoblender.
- UI-09: un aviso repetido se cuenta una vez.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout

T0 = 1000.0
TEXT = "Proyecto «M2_limite» abierto"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class NoticesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.notices = _module("bl.ui.notices")
        cls.reporting = _module("bl.reporting")
        cls.statusbar = _module("bl.ui.statusbar")
        cls.switcher = _module("bl.ui.switcher")
        cls.provenance = _module("bl.ui.provenance")
        cls.ps = _module("bl.scene.project_session")
        cls.versions = _module("bl.scene.versions")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.notices.clear("cancel")
        self.addCleanup(self.notices.clear, "cancel")

    def objects(self, *names: str) -> list[bpy.types.Object]:
        found = []
        for name in names:
            obj = bpy.data.objects.new(name, None)
            bpy.context.scene.collection.objects.link(obj)
            self.addCleanup(bpy.data.objects.remove, obj)
            found.append(obj)
        return found

    def timer(self) -> bool:
        return bpy.app.timers.is_registered(self.notices.tick)

    # El plazo ------------------------------------------------------------------------------

    def test_alive_at_14_seconds_and_not_at_15(self) -> None:
        """RF-019-18, D-10: el aviso está a los 14 s y no a los 15; el barrido lo retira."""
        notices = self.notices
        notices.post("info", TEXT, now=T0)
        self.assertEqual(notices.latest_text(T0 + 14), TEXT)
        self.assertEqual(notices.sweep(T0 + 14), 0)
        self.assertEqual(notices.latest_text(T0 + 14), TEXT)
        self.assertEqual(notices.latest_text(T0 + 15), "")
        self.assertEqual(notices.sweep(T0 + 15), 1)
        self.assertEqual(len(notices.queue()), 0)

    def test_undo_notice_lasts_ten_seconds(self) -> None:
        """RF-019-18 (T14c, T18): el aviso de Ctrl+Z y el de la disposición anterior van a la cola con 10 s."""
        notices = self.notices
        with mock.patch.object(notices, "_clock", return_value=T0):
            self.provenance.show_undo_notice(TEXT)
        self.assertEqual(notices.latest_text(T0 + 9.9), TEXT)
        self.assertEqual(notices.latest_text(T0 + 10), "")

    def test_repeated_notice_counts_once(self) -> None:
        """UI-09, UI-22/23: el mismo aviso dos veces es uno, con el plazo renovado."""
        notices = self.notices
        notices.post("warning", TEXT, now=T0)
        notices.post("warning", TEXT, now=T0 + 10)
        self.assertEqual(len(notices.queue()), 1)
        self.assertEqual(notices.latest_text(T0 + 24), TEXT)

    def test_latest_alive_wins(self) -> None:
        """RF-019-18: el campo muestra el último aviso vivo."""
        notices = self.notices
        notices.post("info", "uno", now=T0)
        notices.post("error", "dos", now=T0 + 1)
        self.assertEqual(notices.latest_text(T0 + 2), "dos")

    # La selección --------------------------------------------------------------------------

    def test_changing_the_selection_retires_it(self) -> None:
        """RF-019-18, DIFF-019 b: al cambiar la selección o el objeto activo, el aviso se retira; lo que ya
        estaba seleccionado al avisar no lo retira."""
        notices = self.notices
        one, two = self.objects("T22_uno", "T22_dos")
        layer = bpy.context.view_layer
        one.select_set(True)
        layer.objects.active = one
        notices.post("info", TEXT, now=T0)
        self.assertEqual(notices.sweep(T0 + 1), 0)
        two.select_set(True)
        self.assertEqual(notices.sweep(T0 + 2), 1)
        notices.post("info", TEXT, now=T0)
        layer.objects.active = two
        notices.on_selection_event()
        self.assertEqual(len(notices.queue()), 0)

    # Cancelar, cambiar y conmutar ------------------------------------------------------------

    def test_clear_on_project_version_and_switch(self) -> None:
        """RF-019-18: cambiar de proyecto, de versión y conmutar a Blender limpian los avisos y no queda
        temporizador."""
        notices = self.notices
        self.assertIn(notices.on_project_changed, self.ps.listeners())
        self.assertIn(notices.on_version_changed, self.versions.listeners())
        self.assertIn(notices.on_entered_blender, self.switcher.blender_hooks())
        for call in (lambda: notices.on_project_changed(None), notices.on_version_changed,
                     notices.on_entered_blender):
            notices.post("info", TEXT, now=T0)
            self.assertTrue(self.timer())
            call()
            self.assertEqual(len(notices.queue()), 0)
            self.assertFalse(self.timer())

    def test_cancelled_operator_clears_unless_it_reported(self) -> None:
        """RF-019-18: una orden que se cancela sin informar deja la barra limpia; una que informa de un error y
        se cancela conserva su aviso. Lo que escribe por ``report`` llega a la cola con su nivel."""
        notices, reporting = self.notices, self.reporting

        class GBTEST_OT_t22_quiet(bpy.types.Operator):
            bl_idname = "geoblender.gbtest_t22_quiet"
            bl_label = "T22 quiet"

            def execute(self, context: object) -> set[str]:
                return {"CANCELLED"}

        class GBTEST_OT_t22_failing(bpy.types.Operator):
            bl_idname = "geoblender.gbtest_t22_failing"
            bl_label = "T22 failing"

            def execute(self, context: object) -> set[str]:
                self.report({"ERROR"}, "No se pudo")
                return {"CANCELLED"}

        class GBTEST_OT_t22_told(bpy.types.Operator):
            bl_idname = "geoblender.gbtest_t22_told"
            bl_label = "T22 told"

            def execute(self, context: object) -> set[str]:
                self.report({"WARNING"}, "Ojo")
                self.report({"DEBUG"}, "ruido")
                return {"FINISHED"}

        classes = (GBTEST_OT_t22_quiet, GBTEST_OT_t22_failing, GBTEST_OT_t22_told)
        for cls in classes:
            reporting.instrument(cls)
            bpy.utils.register_class(cls)
            self.addCleanup(bpy.utils.unregister_class, cls)
        ops = bpy.ops.geoblender
        notices.post("info", TEXT)
        self.assertEqual(ops.gbtest_t22_quiet(), {"CANCELLED"})
        self.assertEqual(len(notices.queue()), 0)
        with self.assertRaises(RuntimeError):  # bpy.ops convierte el informe de error en excepción
            ops.gbtest_t22_failing()
        self.assertEqual(notices.latest_text(), "No se pudo")
        self.assertEqual(ops.gbtest_t22_told(), {"FINISHED"})
        self.assertEqual(notices.latest_text(), "Ojo")
        self.assertEqual([n.level for n in notices.queue().alive(notices._clock())], ["error", "warning"])

    # El campo y el registro -------------------------------------------------------------------

    def test_field_draws_the_latest_notice_in_both_modes(self) -> None:
        """RF-019-18: el campo de la barra de estado dibuja el último aviso vivo, también plegado, en los dos
        modos, y nada sin aviso."""
        notices, statusbar = self.notices, self.statusbar
        field = next(f for f in statusbar.fields() if f.key == notices.FIELD)
        self.assertEqual(field.modes, frozenset({statusbar.GEOBLENDER, statusbar.BLENDER}))
        self.assertIsNotNone(field.folded_draw)
        ctx = SimpleNamespace()
        self.assertEqual(field.width_px(ctx), 0.0)
        notices.post("error", TEXT)
        for draw, width in ((field.draw, field.width_px), (field.folded_draw, field.folded_width_px)):
            layout = FakeLayout()
            draw(layout, ctx)
            self.assertGreater(width(ctx), 0.0)
            self.assertEqual([item.text for item in layout.items if item.kind == "label"], [TEXT])

    def test_disabling_removes_everything(self) -> None:
        """RF-019-18 (principio 8): desactivar Geoblender quita el campo, la escucha, el gancho de conmutar y el
        temporizador."""
        notices = self.notices
        notices.post("info", TEXT)
        self.assertTrue(self.timer())
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        self.assertNotIn(notices.FIELD, {f.key for f in self.statusbar.fields()})
        self.assertNotIn(notices.on_project_changed, self.ps.listeners())
        self.assertNotIn(notices.on_version_changed, self.versions.listeners())
        self.assertNotIn(notices.on_entered_blender, self.switcher.blender_hooks())
        self.assertFalse(self.timer())
        self.assertEqual(len(notices.queue()), 0)


if __name__ == "__main__":
    unittest.main()
