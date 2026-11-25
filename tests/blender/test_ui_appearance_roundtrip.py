# SPDX-License-Identifier: GPL-3.0-or-later
"""Ida y vuelta del aspecto con el proyecto: guardar, cerrar, abrir, refrescar y solo lectura (spec 019, T14; HU-019-1;
RF-019-08, RF-019-09; RNF-019-03; plan 019 §5.2, §5.3, A1, A2, R-6 y R-9; ADR-0033 puntos 3 y 4).

- Cambiar color y transparencia → guardar el ``.blend`` → cerrar el proyecto → abrir el ``.blend`` y el proyecto:
  **persisten** (manda la tabla ``gb_appearance``, no el espejo del fichero).
- «Cambiar, refrescar» conserva; volver a cargar (regenerar) la vista no pierde nada.
- Con el proyecto en solo lectura el cambio queda en el espejo y el panel lo dice.
- Ningún hash, versión, operación ni marca de obsoleto cambia (RF-019-08).
- Con 100 objetos, cambiar color y transparencia cuesta ≤ 0,4 s (RNF-019-03).
- El aviso de migrar al esquema 4 dice su coste antes (UI-24).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.fake_layout import draw, operator_self
from tests.support.trees import temp_folder

KINDS = ("DTM", "DESIGN", "DESIGN_ENTITY")  # una superficie, una corta y una pista (el tipo que lleva su vista)
TABLES = ("gb_version", "gb_operation", "gb_dataset", "gb_dataset_change", "gb_stale")


def _appearance() -> Any:
    return vf.extension("bl.scene.appearance")


def _hex(obj: bpy.types.Object) -> str:
    return "#%02X%02X%02X" % tuple(round(c * 255) for c in obj.color[:3])


class RoundtripCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.ps = vf.extension("bl.scene.project_session")
        self.addCleanup(_appearance().discard)
        self.addCleanup(blender_ext.load_file)
        self.folder = temp_folder(self, "gb-t14-")
        self.data = vf.ViewsProject(self.folder, grids=3)
        self.data.attach()
        self.addCleanup(self.data.close)
        self.data.load(bpy.context)
        self.objs = sorted((o for o in bpy.data.objects if o.geoblender.kind == "DTM"), key=lambda o: o.name)
        self.assertEqual(len(self.objs), 3)
        for obj, kind in zip(self.objs, KINDS):
            obj.geoblender.kind = kind

    def rows(self) -> dict[str, dict[str, str]]:
        with self.data.project.read() as conn:
            found: dict[str, dict[str, str]] = {}
            for name, prop, value in conn.execute("SELECT item_name, prop, value FROM gb_appearance ORDER BY 1, 2"):
                found.setdefault(str(name), {})[str(prop)] = str(value)
            return found

    def counts(self) -> dict[str, Any]:
        with self.data.project.read() as conn:
            found: dict[str, Any] = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
            found["hashes"] = conn.execute("SELECT uid, content_sha256, status FROM gb_dataset ORDER BY uid").fetchall()
        return found

    def name(self, obj: bpy.types.Object) -> str:
        return str(self.data.record(obj.geoblender.dataset_uid).name)

    def reopen(self, *, write: bool = True) -> Any:
        """Cierra el proyecto de la sesión y lo abre otra vez (``open_project``), como la persona que lo cierra y lo abre."""
        self.data.close()
        opened = vf.extension("core.project").open_project(
            self.data.root, self.ps.session(), self.ps.userdata(), want_write=write).project
        self.ps.attach(opened)
        self.ps.take_notices()
        self.data.project = opened
        return opened


class AppearanceRoundtripTest(RoundtripCase):
    def test_change_save_close_open_persists(self) -> None:
        """RF-019-08, ADR-0033 punto 4: cambiar color y transparencia, guardar, cerrar, abrir: persisten, aunque el espejo
        del fichero no esté (manda la tabla); y nada cambia en hashes, versiones ni obsoletos."""
        before = self.counts()
        for index, obj in enumerate(self.objs):
            obj.geoblender.look.color = (1.0, 0.0, 0.2 * index)
            obj.geoblender.look.transparency = 20 + index * 10
        path = str(Path(self.folder) / "ida.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)  # save_pre vacía lo pendiente
        wanted = {self.name(o): {"color": _hex(o), "transparency": str(20 + i * 10)} for i, o in enumerate(self.objs)}
        self.assertEqual(self.rows(), wanted)
        self.data.close()
        blender_ext.load_file(path)
        objs = sorted((o for o in bpy.data.objects if o.geoblender.kind in KINDS), key=lambda o: o.name)
        self.assertEqual(len(objs), 3)
        for obj in objs:  # un fichero sin espejo y con la vista por defecto: lo que dice la tabla manda
            obj.geoblender.look.property_unset("color")
            obj.geoblender.look.property_unset("transparency")
            obj.color = (0.5, 0.5, 0.5, 1.0)
        self.reopen()
        by_uid = {o.geoblender.dataset_uid: o for o in objs}
        for uid, obj in by_uid.items():
            name = str(self.data.record(uid).name)
            self.assertEqual(_hex(obj), wanted[name]["color"], name)
            self.assertAlmostEqual(obj.color[3], 1 - int(wanted[name]["transparency"]) / 100, places=3)
            self.assertEqual(_hex_of_mirror(obj), wanted[name]["color"])
            self.assertEqual(obj.geoblender.look.transparency, int(wanted[name]["transparency"]))
        self.assertEqual(self.rows(), wanted)
        self.assertEqual(before, self.counts())

    def test_change_then_refresh_keeps_it(self) -> None:
        """«Cambiar, refrescar» conserva: la rejilla recalculada se vuelve a cargar y recupera lo guardado."""
        grid = self.objs[0]
        grid.geoblender.look.color = (0.0, 1.0, 0.0)
        grid.geoblender.look.transparency = 35
        uid, session = grid.geoblender.dataset_uid, grid.session_uid
        before = self.counts()["gb_version"]
        _appearance().flush()
        self.data.recompute(uid)
        self.assertEqual(bpy.ops.geoblender.core_refresh("EXEC_DEFAULT"), {"FINISHED"})
        (reloaded,) = vf.objects_of(bpy.data, uid)
        self.assertNotEqual(reloaded.session_uid, session)  # de verdad se volvió a cargar
        self.assertEqual(_hex(reloaded), "#00FF00")
        self.assertAlmostEqual(reloaded.color[3], 0.65, places=3)
        self.assertEqual(reloaded.geoblender.look.transparency, 35)
        self.assertEqual(self.counts()["gb_version"], before)

    def test_reloading_the_view_does_not_lose_it(self) -> None:
        """Regenerar la vista (cargar otra vez el dato) conserva el aspecto guardado."""
        obj = self.objs[1]
        uid = obj.geoblender.dataset_uid
        obj.geoblender.look.color = (0.0, 0.0, 1.0)
        obj.geoblender.look.visible = False
        _appearance().flush()
        self.data.load(bpy.context, uid)
        (again,) = vf.objects_of(bpy.data, uid)
        self.assertEqual(_hex(again), "#0000FF")
        self.assertTrue(again.hide_get() or not again.visible_get() or again.hide_viewport)
        self.assertFalse(again.geoblender.look.visible)

    def test_read_only_keeps_the_mirror_and_the_panel_says_so(self) -> None:
        """RF-019-08, ADR-0033 punto 3: con el proyecto en solo lectura el cambio solo está en el espejo del ``.blend``,
        no escribe nada y el panel lo dice."""
        self.reopen(write=False)
        self.assertFalse(self.data.project.writable)
        counter = self.data.change_counter()
        obj = self.objs[0]
        obj.geoblender.look.color = (1.0, 0.0, 0.0)
        self.assertEqual(_appearance().flush(), 0)
        self.assertEqual(self.rows(), {})
        self.assertEqual(self.data.change_counter(), counter)
        self.assertEqual(_hex(obj), "#FF0000")
        self.assertEqual(self.ps.take_notices(), ["Aspecto guardado solo en este fichero: el proyecto está en solo lectura"])
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        panel = getattr(bpy.types, "GEOBLENDER_PT_ui_element_look")
        with mock.patch.object(vf.extension("bl.ui.labels"), "sidebar_width", return_value=1000.0):
            layout = draw(panel, bpy.context)
        texts = " ".join(item.text for item in layout.of_kind("label"))
        self.assertIn("solo lectura", texts)

    def test_a_100_object_change_costs_at_most_0_4_s(self) -> None:
        """RNF-019-03: cambiar color y transparencia de 100 elementos seleccionados (aplicar, mezclar y anotar), con
        la escritura diferida incluida, ≤ 0,4 s."""
        scene = bpy.context.scene
        extra = []
        for index in range(100):
            obj = bpy.data.objects.new(f"t14-{index:03d}", bpy.data.meshes.new(f"t14-{index:03d}"))
            scene.collection.objects.link(obj)
            obj.geoblender.kind = "DTM"
            obj.geoblender.project_uid = self.data.project.uid
            obj.geoblender.dataset_uid = self.objs[0].geoblender.dataset_uid
            extra.append(obj)
        for other in bpy.data.objects:
            other.select_set(False)
        for obj in extra:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = extra[0]
        times = []
        for step in range(5):  # el mejor de cinco: con la CPU compartida (check.py en partes) una sola medida engaña
            level = 0.2 + 0.1 * step
            start = time.perf_counter()
            extra[0].geoblender.look.color = (level, 0.4, 0.6)
            extra[0].geoblender.look.transparency = 40 + step
            _appearance().flush()
            times.append(time.perf_counter() - start)
        expected = "#%02X%02X%02X" % (round(0.6 * 255), 102, 153)
        print(f"[T14] 100 objetos, color y transparencia: {min(times) * 1000:.0f} ms (mejor de cinco)")
        self.assertTrue(all(_hex(o) == expected for o in extra))
        self.assertLessEqual(min(times), 0.4, f"{min(times):.3f} s")

    def test_b_a_50_element_mix_is_not_much_dearer_than_one_element(self) -> None:
        """RNF-019-01 (H-7, H1, T14b): la mezcla de 50 elementos seleccionados de valores distintos («varios valores») no
        encarece el dibujo del panel de aspecto más de 12 veces el de un solo elemento (medido en la misma ejecución: no
        depende de la CPU; antes de T14b eran unas 40). La cifra absoluta (≤ 0,5 ms) la mide ``tests/rendimiento/blender/
        perf_ui_mix.py`` con la CPU en reposo."""
        extra = make_mix_objects(self.data.project.uid, [o.geoblender.dataset_uid for o in self.objs], 50)
        with mock.patch.object(vf.extension("bl.ui.labels"), "sidebar_width", return_value=1000.0):
            texts = [item.text for item in draw(bpy.types.GEOBLENDER_PT_ui_element_look, bpy.context).of_kind("label")]
            self.assertIn("varios valores", texts)
            mix = draw_ms(bpy.types.GEOBLENDER_PT_ui_element_look)
            for obj in extra[1:]:
                obj.select_set(False)
            one = draw_ms(bpy.types.GEOBLENDER_PT_ui_element_look)
        print(f"[T14b] panel de aspecto: 50 elementos {mix:.3f} ms, uno {one:.3f} ms")
        self.assertLessEqual(mix, 12 * one, f"{mix:.3f} ms frente a {one:.3f} ms")


def make_mix_objects(project_uid: str, dataset_uids: list[str], count: int) -> list[bpy.types.Object]:
    """``count`` objetos de rejilla seleccionados, de colores distintos, con el primero activo (la mezcla de la selección)."""
    extra = []
    for index in range(count):
        obj = bpy.data.objects.new(f"mix-{index:03d}", bpy.data.meshes.new(f"mix-{index:03d}"))
        bpy.context.scene.collection.objects.link(obj)
        obj.geoblender.kind = "DTM"
        obj.geoblender.project_uid = project_uid
        obj.geoblender.dataset_uid = dataset_uids[index % len(dataset_uids)]
        obj.geoblender.look.color = (0.1 + (index % 5) * 0.1, 0.5, 0.5)
        extra.append(obj)
    for other in bpy.data.objects:
        other.select_set(False)
    for obj in extra:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = extra[0]
    return extra


def draw_ms(panel: type, *, rounds: int = 5, repeats: int = 100) -> float:
    """El coste de un dibujo de ``panel``: la mejor de ``rounds`` medianas de ``repeats`` dibujos, en ms."""
    medians = []
    for _ in range(rounds):
        times = []
        for _ in range(repeats):
            start = time.perf_counter()
            draw(panel, bpy.context)
            times.append((time.perf_counter() - start) * 1000.0)
        medians.append(sorted(times)[len(times) // 2])
    return min(medians)


def _hex_of_mirror(obj: bpy.types.Object) -> str:
    return "#%02X%02X%02X" % tuple(round(c * 255) for c in obj.geoblender.look.color)


class MigrationNoticeTest(unittest.TestCase):
    def test_the_notice_says_the_cost_before_migrating(self) -> None:
        """UI-24/25: el diálogo de abrir dice a qué esquema se migra, la copia previa y que un Geoblender anterior ya no
        abrirá el proyecto (el coste), **antes** de hacerlo."""
        blender_ext.release()
        blender_ext.enable()
        self.addCleanup(blender_ext.release)
        project = vf.extension("core.project")
        lock = vf.extension("core.project.lock")
        opened = vf.extension("core.project.open")
        i18n = vf.extension("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")
        inspection = SimpleNamespace(
            lock=SimpleNamespace(state=lock.LockState.FREE, can_force=False, holder=None),
            schema=opened.SchemaRelation.OLDER, record=SimpleNamespace(schema_version=3),
            root=Path("Cantera Prueba.gbproj"))
        cls = getattr(bpy.types, "GEOBLENDER_OT_core_open_project")
        operator = operator_self(cls, read_only=False)
        cls._prepare_dialog(operator, inspection)
        text = operator.notice
        self.assertIn(f"esquema {project.SCHEMA_VERSION}", text)
        self.assertIn("copia completa", text)
        self.assertIn("no podrá abrirlo", text)


if __name__ == "__main__":
    unittest.main()
