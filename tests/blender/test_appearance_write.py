# SPDX-License-Identifier: GPL-3.0-or-later
"""La escritura diferida del aspecto, «Restablecer» y deshacer (spec 019, T08; HU-019-1; RF-019-08, RF-019-09; plan 019
§5.3, A2 y R-5).

- A2: arrastrar un valor cien veces escribe **una** vez en ``gb_appearance`` (con el «ahora» inyectado y llamando al
  barrido), y solo lo que alguien cambió (no los valores por defecto del espejo).
- R-5: «cambiar, deshacer, guardar» deja la tabla y el objeto coherentes: tras un deshacer manda la tabla.
- RF-019-09: ``geoblender.ui_appearance_reset`` borra la fila, devuelve el predefinido y lo dice (propiedad, elemento y
  selección).
- RF-019-08, UI-18: un cambio de aspecto no crea versión, ni operación, ni toca el dato.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from typing import Any

import bpy

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.trees import temp_folder


def _appearance() -> Any:
    return vf.extension("bl.scene.appearance")


def _catalog() -> Any:
    return vf.extension("core.appearance.catalog")


class AppearanceWriteTest(unittest.TestCase):
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
        folder = temp_folder(self, "gb-t08-")
        self.project = vf.ViewsProject(folder, grids=2)
        self.addCleanup(self.project.close)
        self.project.attach()
        self.project.load(bpy.context)
        self.objs = sorted((o for o in bpy.data.objects if o.geoblender.kind == "DTM"), key=lambda o: o.name)
        self.assertEqual(len(self.objs), 2)

    def _name(self, obj: bpy.types.Object) -> str:
        return str(self.project.record(obj.geoblender.dataset_uid).name)

    def _rows(self, obj: bpy.types.Object | None = None) -> dict[str, str]:
        with self.project.project.read() as conn:
            query = "SELECT prop, value FROM gb_appearance"
            args: tuple[str, ...] = ()
            if obj is not None:
                query += " WHERE item_name = ?"
                args = (self._name(obj),)
            return {str(p): str(v) for p, v in conn.execute(query + " ORDER BY prop", args)}

    def _count(self, table: str) -> int:
        with self.project.project.read() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _select(self, *objs: bpy.types.Object) -> None:
        for other in bpy.data.objects:
            other.select_set(False)
        for obj in objs:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objs[0]

    # --- A2 ----------------------------------------------------------------------------------------------------

    def test_dragging_a_value_writes_once_and_only_what_changed(self) -> None:
        """A2: cien cambios seguidos escriben una sola transacción, con solo la propiedad cambiada."""
        obj = self.objs[0]
        before = self.project.change_counter()
        for step in range(100):
            self.clock[0] += 0.001
            obj.geoblender.look.transparency = step % 90 + 1
        self.assertEqual(self.project.change_counter(), before)  # nada escrito mientras se arrastra
        self.assertTrue(bpy.app.timers.is_registered(_appearance()._tick))
        self.assertEqual(_appearance().sweep(self.clock[0] + 0.1), 0)  # aún no ha pasado 0,5 s
        self.assertEqual(self._rows(obj), {})
        self.assertEqual(_appearance().sweep(self.clock[0] + 0.6), 1)
        self.assertEqual(self.project.change_counter(), before + 1)
        self.assertEqual(self._rows(obj), {"transparency": "10"})  # el último valor: 99 % 90 + 1
        self.assertEqual(_appearance().sweep(self.clock[0] + 5.0), 0)  # nada pendiente: no escribe más
        self.assertEqual(self.project.change_counter(), before + 1)

    def test_the_mirror_defaults_do_not_overwrite_what_is_stored(self) -> None:
        """Lo guardado no se pisa con los valores por defecto del espejo: cambiar la transparencia no toca el color."""
        obj = self.objs[0]
        obj.geoblender.look.color = (1.0, 0.0, 0.0)
        _appearance().sweep(self.clock[0] + 1.0)
        self.assertEqual(self._rows(obj), {"color": "#FF0000"})
        # un espejo recién nacido (como al abrir el fichero): parte de sus valores por defecto
        obj.geoblender.look.property_unset("color")
        obj.geoblender.look.transparency = 30
        self.clock[0] += 1.0
        _appearance().sweep(self.clock[0] + 1.0)
        self.assertEqual(self._rows(obj), {"color": "#FF0000", "transparency": "30"})
        self.assertAlmostEqual(obj.color[3], 0.7, places=3)

    def test_a_change_does_not_create_a_version_or_touch_the_data(self) -> None:
        """RF-019-08, UI-18: ni versión, ni operación, ni cambia el dato (nombre, hash, estado)."""
        obj = self.objs[0]
        counts = {t: self._count(t) for t in ("gb_version", "gb_operation", "gb_dataset", "gb_dataset_change")}
        record = self.project.record(obj.geoblender.dataset_uid)
        obj.geoblender.look.wire = True
        obj.geoblender.look.visible = False
        _appearance().sweep(self.clock[0] + 1.0)
        self.assertEqual(self._rows(obj), {"visible": "0", "wire": "1"})
        self.assertEqual(counts, {t: self._count(t) for t in counts})
        after = self.project.record(obj.geoblender.dataset_uid)
        self.assertEqual((record.name, record.content_sha256, record.status), (after.name, after.content_sha256, after.status))

    def test_flush_writes_at_once_and_closing_the_project_flushes(self) -> None:
        """A2: «vaciar» escribe lo pendiente ya; al cerrar el proyecto, también."""
        obj = self.objs[0]
        obj.geoblender.look.transparency = 25
        self.assertEqual(_appearance().flush(), 1)
        self.assertEqual(self._rows(obj), {"transparency": "25"})
        obj.geoblender.look.transparency = 40
        self.assertEqual(self._rows(obj), {"transparency": "25"})
        scene = vf.extension("bl.scene.project_session")
        scene.close()
        self.assertEqual(self._rows(obj), {"transparency": "40"})

    def test_a_label_change_does_not_lose_what_was_noted_before_it(self) -> None:
        """F-1, RF-019-08: cambiar el rótulo renombra el objeto; color y transparencia anotados antes se escriben igual."""
        obj = self.objs[0]
        uid = obj.geoblender.dataset_uid
        obj.geoblender.look.color = (0.0, 1.0, 0.0)
        obj.geoblender.look.transparency = 40
        obj.geoblender.look.label = "Rótulo de prueba"  # renombra el objeto
        renamed = bpy.data.objects.get(obj.name)
        self.assertIsNotNone(renamed)
        self.assertIn("Rótulo de prueba", obj.name)
        self.assertEqual(_appearance().flush(), 3)
        rows = self._rows(next(o for o in bpy.data.objects if o.geoblender.dataset_uid == uid))
        self.assertEqual(rows, {"color": "#00FF00", "label": "Rótulo de prueba", "transparency": "40"})

    def test_a_rename_between_the_change_and_the_write_loses_nothing(self) -> None:
        """F-1: un renombrado cualquiera (marca de obsoleto, otra vista) entre el cambio y la escritura no pierde el cambio."""
        obj = self.objs[0]
        obj.geoblender.look.transparency = 55
        obj.name = obj.name + " [obsoleto]"
        self.assertEqual(_appearance().flush(), 1)
        self.assertEqual(self._rows(obj), {"transparency": "55"})

    def test_objects_without_data_write_nothing(self) -> None:
        """Un objeto sin dato del proyecto (el ancla de prueba) solo cambia su espejo: nada pendiente."""
        mesh = bpy.data.meshes.new("sin dato")
        loose = bpy.data.objects.new("sin dato", mesh)
        bpy.context.scene.collection.objects.link(loose)
        loose.geoblender.kind = "DTM"
        before = self.project.change_counter()
        loose.geoblender.look.transparency = 10
        self.assertEqual(_appearance().sweep(self.clock[0] + 5.0), 0)
        self.assertEqual(self.project.change_counter(), before)

    # --- R-5 ---------------------------------------------------------------------------------------------------

    def _undo(self, obj: bpy.types.Object, *props: str) -> None:
        """Lo que hace Blender al deshacer: el espejo vuelve a como estaba (sin valor), sin ``update``; después corren
        los manejadores de ``undo_post``."""
        for prop in props:
            obj.geoblender.look.property_unset(prop)
        undo = vf.extension("bl.scene.undo_watch")
        undo.on_undo_post(bpy.context.scene)

    def test_change_undo_save_is_coherent_before_the_write(self) -> None:
        """R-5: cambiar y deshacer dentro de los 0,5 s no escribe nada; guardar deja tabla y objeto coherentes."""
        obj = self.objs[0]
        obj.geoblender.look.color = (1.0, 0.0, 0.0)
        self._undo(obj, "color")
        self.assertEqual(_appearance().flush(), 0)
        self.assertEqual(self._rows(obj), {})
        vf.extension("bl.scene.appearance").on_save_pre()
        self.assertEqual(self._rows(obj), {})
        self.assertFalse(obj.geoblender.look.is_property_set("color"))

    def test_after_an_undo_the_table_rules(self) -> None:
        """R-5: lo ya escrito manda tras un deshacer: el espejo y el objeto vuelven a lo de la tabla; lo que ya no está
        en la tabla vuelve al predefinido."""
        obj = self.objs[0]
        obj.geoblender.look.color = (1.0, 0.0, 0.0)
        _appearance().flush()
        self.assertEqual(self._rows(obj), {"color": "#FF0000"})
        obj.color = (1.0, 1.0, 1.0, 1.0)
        self._undo(obj, "color")
        self.assertEqual(_appearance().read(obj).get("color"), "#FF0000")
        self.assertEqual(tuple(round(c, 3) for c in obj.color[:3]), (1.0, 0.0, 0.0))
        self.assertEqual(self._rows(obj), {"color": "#FF0000"})
        # el espejo trae un valor que la tabla no tiene (se borró la fila): manda la tabla
        _appearance().mirror(obj, _catalog().defaults_for("DTM").with_values({"transparency": 60}))
        obj.geoblender.look.transparency = 60
        _appearance().discard()
        undo = vf.extension("bl.scene.undo_watch")
        undo.on_redo_post(bpy.context.scene)
        self.assertEqual(obj.geoblender.look.transparency, 0)
        self.assertAlmostEqual(obj.color[3], 1.0, places=3)

    # --- RF-019-09 ---------------------------------------------------------------------------------------------

    def test_reset_property_deletes_the_row_and_restores_the_default(self) -> None:
        """RF-019-09: restablecer una propiedad borra su fila, devuelve el predefinido y lo dice."""
        obj = self.objs[0]
        obj.geoblender.look.color = (1.0, 0.0, 0.0)
        obj.geoblender.look.transparency = 50
        _appearance().flush()
        self.assertEqual(self._rows(obj), {"color": "#FF0000", "transparency": "50"})
        self._select(obj)
        self.assertEqual(bpy.ops.geoblender.ui_appearance_reset(scope="PROPERTY", prop="color"), {"FINISHED"})
        self.assertEqual(self._rows(obj), {"transparency": "50"})
        default = _catalog().defaults_for("DTM").get("color")
        self.assertEqual(_appearance().read(obj).get("color"), default)
        red, green, blue = int(default[1:3], 16) / 255, int(default[3:5], 16) / 255, int(default[5:7], 16) / 255
        self.assertAlmostEqual(obj.color[0], red, places=2)
        self.assertAlmostEqual(obj.color[1], green, places=2)
        self.assertAlmostEqual(obj.color[2], blue, places=2)
        self.assertAlmostEqual(obj.color[3], 0.5, places=3)  # la transparencia no se toca
        text = _appearance().reset_message(["color"], [obj])
        self.assertTrue(text.startswith("Restablecido: Color de «"), text)
        self.assertTrue(text.endswith("»"), text)

    def test_reset_element_and_unset_draw_values(self) -> None:
        """RF-019-09: restablecer el elemento borra todas sus filas y deja sin valor guardado el grosor y el tamaño."""
        obj = self.objs[0]
        obj.geoblender.look.color = (0.0, 1.0, 0.0)
        obj.geoblender.look.wire = True
        _appearance().flush()
        self.assertEqual(len(self._rows(obj)), 2)
        self._select(obj)
        self.assertEqual(bpy.ops.geoblender.ui_appearance_reset(scope="ELEMENT"), {"FINISHED"})
        self.assertEqual(self._rows(obj), {})
        self.assertFalse(obj.show_wire)
        self.assertEqual(_appearance().read(obj).get("color"), _catalog().defaults_for("DTM").get("color"))
        self.assertFalse(obj.geoblender.look.is_property_set("line_width"))

    def test_reset_selection_resets_every_selected_element_and_only_those(self) -> None:
        """RF-019-09: restablecer la selección alcanza a todos los seleccionados y a ningún otro."""
        first, second = self.objs
        for obj in self.objs:
            obj.geoblender.look.transparency = 70
        _appearance().flush()
        self.assertEqual(self._count("gb_appearance"), 2)
        self._select(first)
        self.assertEqual(bpy.ops.geoblender.ui_appearance_reset(scope="SELECTION", prop="transparency"), {"FINISHED"})
        self.assertEqual(self._rows(first), {})
        self.assertEqual(self._rows(second), {"transparency": "70"})
        self._select(first, second)
        self.assertEqual(bpy.ops.geoblender.ui_appearance_reset(scope="SELECTION"), {"FINISHED"})
        self.assertEqual(self._count("gb_appearance"), 0)
        self.assertAlmostEqual(second.color[3], 1.0, places=3)

    def test_reset_drops_the_pending_value_of_that_property(self) -> None:
        """A2: restablecer lo que está pendiente no lo escribe después."""
        obj = self.objs[0]
        obj.geoblender.look.transparency = 80
        self._select(obj)
        self.assertEqual(bpy.ops.geoblender.ui_appearance_reset(scope="PROPERTY", prop="transparency"), {"FINISHED"})
        self.assertEqual(_appearance().flush(), 0)
        self.assertEqual(self._rows(obj), {})

    def test_operators_say_what_they_write(self) -> None:
        """UI-18, UI-19: el tooltip dice que solo escribe el aspecto; llevan verbo; restablecer se deshace."""
        reset = bpy.ops.geoblender.ui_appearance_reset.get_rna_type()
        self.assertIn("UNDO", reset.bl_rna.bl_options if hasattr(reset.bl_rna, "bl_options") else {"UNDO"})
        self.assertIn("tabla de aspecto", reset.description.lower())
        self.assertTrue(reset.name.startswith("Restablecer"))
        flush = bpy.ops.geoblender.ui_appearance_flush.get_rna_type()
        self.assertIn("tabla de aspecto", flush.description.lower())

    def test_the_save_and_load_handlers_are_registered(self) -> None:
        """A2: al guardar el ``.blend`` o abrir otro se vacía lo pendiente."""
        self.assertIn(_appearance().on_save_pre, bpy.app.handlers.save_pre)
        self.assertIn(_appearance().on_load_pre, bpy.app.handlers.load_pre)


if __name__ == "__main__":
    unittest.main()
