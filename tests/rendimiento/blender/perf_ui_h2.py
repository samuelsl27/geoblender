# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento del modo Geoblender y del aspecto, con sus cifras (spec 019, T29; RNF-019-01 a 04; plan 019 §7.3).

Se ejecuta con ``tools/check.py --rendimiento`` o con ``tools/run_blender_tests.py -- --carpeta tests/rendimiento/blender
--patron "perf_ui_h2.py"``. Las cifras salen por ``stderr`` con el prefijo «RNF-019-nn:» (``check.py`` las recoge).

- RNF-019-01: el panel de aspecto con 50 elementos seleccionados (la mezcla, H-7) y uno activo ≤ 0,5 ms (la mejor de cinco
  medianas de cien dibujos). Su prueba es ``perf_ui_mix.py`` (T14b); aquí se mide también con uno solo, para el cociente.
- RNF-019-02: el modo Geoblender no añade más de 1 ms al redibujo de la ventana a 1920 × 1080 con la barra N cerrada y el
  filtro de paneles instalado: barra superior + fila 2 + barra de estado + los ``poll`` de todos los paneles nativos
  + el menú de la Vista 3D, con el filtro frente a sin él (mediana de cada tramo; el exceso, ≤ 1 ms).
- RNF-019-03: cambiar color y transparencia con 100 objetos seleccionados ≤ 0,4 s (el mejor de cinco).
- RNF-019-04: conmutar a Blender y volver ≤ 2 s con el estado idéntico (el más lento de cinco).

Control: una función con un ``time.sleep`` por encima del techo falla la misma comprobación (``test_control_*``).
"""

import importlib
import statistics
import sys
import time
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.test_ui_appearance_roundtrip import RoundtripCase, draw_ms, make_mix_objects
from tests.blender.test_ui_switch_roundtrip import FakeWindow, _areas, _natives, _poll_results, _tabs
from tests.rendimiento.blender.perf_ui_draw_cost import NullLayout, _Area, median_ms
from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import module_name

MIX_BUDGET_MS = 0.5
REDRAW_EXTRA_BUDGET_MS = 1.0
APPEARANCE_BUDGET_S = 0.4
SWITCH_BUDGET_S = 2.0
CYCLES = 5


def _ms(value: float) -> str:
    return f"{value:.3f}".replace(".", ",")


def report(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def best_of(rounds: int, function: Callable[[], object]) -> float:
    """El menor tiempo, en s, de ``rounds`` llamadas a ``function`` (con la CPU compartida una sola medida engaña)."""
    times = []
    for _ in range(rounds):
        start = time.perf_counter()
        function()
        times.append(time.perf_counter() - start)
    return min(times)


def within(budget: float, measured: float) -> bool:
    """La comprobación de todos los techos: ``measured`` ≤ ``budget``."""
    return measured <= budget


class ControlTest(unittest.TestCase):
    def test_control_a_sleep_over_the_ceiling_fails(self) -> None:
        """Una función con un ``time.sleep`` por encima del techo no pasa la comprobación de cada RNF."""
        def slow() -> None:
            time.sleep(0.05)
        self.assertFalse(within(0.04, best_of(2, slow)))
        self.assertFalse(within(MIX_BUDGET_MS, median_ms(slow, 3)))
        self.assertTrue(within(0.4, best_of(2, lambda: None)))


class AppearanceCostTest(RoundtripCase):
    def test_rnf_019_01_the_mix_of_50_elements(self) -> None:
        """RNF-019-01: el panel de aspecto con 50 elementos seleccionados ≤ 0,5 ms (y, aparte, con uno solo)."""
        extra = make_mix_objects(self.data.project.uid, [o.geoblender.dataset_uid for o in self.objs], 50)
        with mock.patch.object(vf.extension("bl.ui.labels"), "sidebar_width", return_value=1000.0):
            mix = draw_ms(bpy.types.GEOBLENDER_PT_ui_element_look)
            for obj in extra[1:]:
                obj.select_set(False)
            one = draw_ms(bpy.types.GEOBLENDER_PT_ui_element_look)
        report(f"RNF-019-01: panel de aspecto, 50 elementos seleccionados: {_ms(mix)} ms (≤ {_ms(MIX_BUDGET_MS)} ms); "
               f"uno activo: {_ms(one)} ms")
        self.assertTrue(within(MIX_BUDGET_MS, mix), f"{mix:.3f} ms")

    def test_rnf_019_03_color_and_transparency_of_100_objects(self) -> None:
        """RNF-019-03: cambiar color y transparencia con 100 objetos seleccionados (con la escritura diferida) ≤ 0,4 s."""
        scene = bpy.context.scene
        extra = []
        for index in range(100):
            obj = bpy.data.objects.new(f"t29-{index:03d}", bpy.data.meshes.new(f"t29-{index:03d}"))
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
        steps = iter(range(CYCLES))

        def change() -> None:
            step = next(steps)
            extra[0].geoblender.look.color = (0.2 + 0.1 * step, 0.4, 0.6)
            extra[0].geoblender.look.transparency = 40 + step
            vf.extension("bl.scene.appearance").flush()

        best = best_of(CYCLES, change)
        report(f"RNF-019-03: color y transparencia con 100 objetos, el mejor de {CYCLES}: {best * 1000:.0f} ms "
               f"(≤ {APPEARANCE_BUDGET_S * 1000:.0f} ms)")
        self.assertTrue(within(APPEARANCE_BUDGET_S, best), f"{best:.3f} s")


class WindowCostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.mod = lambda name: importlib.import_module(f"{module_name()}.{name}")  # noqa: E731
        cls.nf = cls.mod("bl.ui.native_filter")
        cls.switcher = cls.mod("bl.ui.switcher")
        cls.quick = cls.mod("bl.ui.quick_access")
        cls.statusbar = cls.mod("bl.ui.statusbar")
        cls.georef = cls.mod("bl.scene.georef")
        cls.window = bpy.context.window_manager.windows[0]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.nf.remove()
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.gb = bpy.data.workspaces["Layout"]
        self.bl = bpy.data.workspaces["Modeling"]
        self.was = self.gb.geoblender_mode
        self.gb.geoblender_mode = True
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        self.nf.remove()
        self.switcher.forget()
        try:
            self.gb.geoblender_mode = self.was
        except AttributeError:
            pass

    def _context(self, *, width: float, area: object, region: str) -> SimpleNamespace:
        return SimpleNamespace(
            workspace=self.gb, screen=SimpleNamespace(show_fullscreen=False, show_statusbar=True), area=area,
            region=SimpleNamespace(type=region, width=width, alignment="LEFT"), mode="OBJECT", scene=bpy.context.scene,
            space_data=None, window=self.window, preferences=bpy.context.preferences)

    def _redraw(self) -> Callable[[], None]:
        """Lo que Blender repite en cada redibujo de la ventana de Geoblender a 1920 × 1080, barra N cerrada."""
        owner = SimpleNamespace(layout=NullLayout())
        top = self._context(width=1920.0, area=SimpleNamespace(show_menus=True, type="TOPBAR"), region="TOOL_HEADER")
        row = self._context(width=1300.0, area=_Area(1), region="TOOL_HEADER")
        status = self._context(width=1920.0, area=None, region="TOOL_HEADER")
        panels = _natives()
        polls = [(c, getattr(c, "poll", None)) for c in panels]
        menus = getattr(bpy.types, "VIEW3D_MT_editor_menus")
        fake = self.georef.SceneGeoref("uid", "Cantera sintética", 25830, 0, (736500, 4435900, 0))
        ctx = SimpleNamespace(workspace=self.gb)

        def redraw() -> None:
            bpy.types.TOPBAR_HT_upper_bar.draw_left(owner, top)
            self.quick.draw_view_row(owner, row)
            with mock.patch.object(self.georef, "project_georeference", return_value=fake):
                self.statusbar.draw_statusbar(owner, status)
            for _cls, poll in polls:  # los ``poll`` de los paneles nativos (con el filtro, los envueltos)
                if poll is not None:
                    try:
                        poll(ctx)
                    except Exception:  # noqa: BLE001 - como Blender: si falla, se dibuja
                        pass
            try:
                menus.draw_collapsible(bpy.context, NullLayout())
            except Exception:  # noqa: BLE001 - el parche y el original se miden igual
                pass

        return redraw

    def test_rnf_019_02_the_filter_adds_at_most_1_ms_to_a_redraw(self) -> None:
        """RNF-019-02: con el filtro de paneles instalado, el redibujo de la ventana a 1920 × 1080 cuesta ≤ 1 ms más."""
        windows = [FakeWindow(self.gb)]
        self.nf.remove()
        self.assertFalse(self.nf.installed())
        plain = self._redraw()
        without = [median_ms(plain, 300) for _ in range(CYCLES)]
        self.assertTrue(self.nf.sync(windows))
        self.assertTrue(self.nf.installed())
        filtered = self._redraw()
        with_filter = [median_ms(filtered, 300) for _ in range(CYCLES)]
        extra = min(with_filter) - min(without)
        report(f"RNF-019-02: redibujo de la ventana (1920 × 1080, barra N cerrada, {len(_natives())} paneles nativos): "
               f"sin filtro {_ms(min(without))} ms, con filtro {_ms(min(with_filter))} ms, exceso "
               f"{_ms(extra)} ms (≤ {_ms(REDRAW_EXTRA_BUDGET_MS)} ms)")
        self.assertTrue(within(REDRAW_EXTRA_BUDGET_MS, extra), f"{extra:.3f} ms")

    def test_rnf_019_04_the_round_trip_is_fast_and_leaves_the_same_state(self) -> None:
        """RNF-019-04: conmutar a Blender y volver ≤ 2 s (el más lento de cinco) y con el estado idéntico."""
        win = FakeWindow(self.gb)
        windows = [win, FakeWindow(self.bl)]
        self.assertTrue(self.nf.sync(windows))

        def state() -> dict[str, object]:
            snapshot = blender_ext.ui_snapshot()
            snapshot.pop("window_workspaces", None)
            snapshot["areas"] = _areas()
            snapshot["tabs"] = _tabs()
            snapshot["polls"] = _poll_results({"gb": self.gb, "bl": self.bl})
            snapshot["tree"] = [c.__name__ for c in self.nf._STATE.tree]
            snapshot["menu"] = self.nf.menu_installed()
            return snapshot

        before = state()
        times = []
        for _ in range(CYCLES):
            self.switcher.window_state(win).previous_blender = self.bl.name
            start = time.perf_counter()
            self.switcher.toggle(win, "BLENDER")
            self.nf.sync([win, windows[1]])
            win.workspace = self.bl
            self.switcher.toggle(win, "GEOBLENDER")
            win.workspace = self.gb
            self.switcher.window_state(win).pending = None  # la asignación ya se aplicó (como en la prueba de T21)
            self.assertIsNone(self.switcher.pending(win))
            if bpy.app.timers.is_registered(self.switcher.check_pending):  # en -b no corre: se retira como al cumplirse
                bpy.app.timers.unregister(self.switcher.check_pending)
            self.nf.sync([win, windows[1]])
            times.append(time.perf_counter() - start)
        after = state()
        report(f"RNF-019-04: conmutar a Blender y volver, {CYCLES} veces: mediana {statistics.median(times) * 1000:.0f} ms, "
               f"la más lenta {max(times) * 1000:.0f} ms (≤ {SWITCH_BUDGET_S * 1000:.0f} ms); estado idéntico: "
               f"{blender_ext.fingerprint_diff(before, after) == [] and before == after}")
        self.assertEqual(blender_ext.fingerprint_diff(before, after), [])
        self.assertEqual({k: (before[k], after[k]) for k in before if before[k] != after[k]}, {})
        self.assertTrue(within(SWITCH_BUDGET_S, max(times)), f"{max(times):.3f} s")


if __name__ == "__main__":
    unittest.main()
