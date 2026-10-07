# SPDX-License-Identifier: GPL-3.0-or-later
"""Coste en Python del dibujo de la interfaz y de la línea de comandos, dentro de Blender
(spec 003, T35; RNF-003-02, RNF-003-07; plan 003 §7).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con
``tools/run_blender_tests.py -- --carpeta tests/rendimiento/blender --patron "perf_ui*.py"``).
Los dibujos se llaman con un *layout* nulo (cada método devuelve el propio *layout* y no
guarda nada): se mide solo el Python de Geoblender, no el de una imitación que anota cada
llamada. Mediana de 1000 llamadas (de 200 en cada menú que no es de la barra):

- RNF-003-02: barra superior en modo Geoblender a 1920 px ≤ 0,5 ms; fila 2 de la Vista 3D
  (entera, a 1300 px, y plegada, a 650 px) ≤ 0,5 ms; barra de estado minera con proyecto
  ≤ 0,3 ms; cada menú ≤ 1 ms.
- RNF-003-07: una consulta de la línea de comandos F10 (la lista que ve la persona,
  ``bl.ui.command_line.suggestions``, con la etiqueta y dónde está) ≤ 20 ms con el catálogo
  completo (≥ 350 comandos).
"""

import importlib
import statistics
import sys
import time
import unittest
from collections.abc import Callable
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

CALLS = 1000
MENU_CALLS = 200
TOPBAR_BUDGET_MS = 0.5
ROW2_BUDGET_MS = 0.5
STATUSBAR_BUDGET_MS = 0.3
MENU_BUDGET_MS = 1.0
SEARCH_BUDGET_MS = 20.0
QUERIES = ("", "cubicar", "volume", "R-38", "r38", "planta", "sondeos", "ns", "v", "export",
           "ventana de trabajo")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class _Sink:
    """Las propiedades de un operador dibujado: se asignan y no se guardan."""

    def __setattr__(self, name: str, value: object) -> None:
        pass


_SINK = _Sink()


class NullLayout:
    """Un ``UILayout`` que no hace nada: cada método devuelve el propio *layout* (o, el de
    un operador, unas propiedades que lo aceptan todo) y asignar no guarda nada."""

    def __getattr__(self, name: str) -> Callable[..., object]:
        return self._same

    def __setattr__(self, name: str, value: object) -> None:
        pass

    def _same(self, *_args: object, **_kwargs: object) -> "NullLayout":
        return self

    def operator(self, *_args: object, **_kwargs: object) -> _Sink:
        return _SINK


class _Area:
    def __init__(self, pointer: int) -> None:
        self.type = "VIEW_3D"
        self._pointer = pointer

    def as_pointer(self) -> int:
        return self._pointer


def median_ms(function: Callable[[], object], calls: int = CALLS) -> float:
    """La mediana, en ms, de ``calls`` llamadas a ``function``."""
    times: list[float] = []
    for _ in range(calls):
        start = time.perf_counter()
        function()
        times.append((time.perf_counter() - start) * 1000.0)
    return statistics.median(times)


def _ms(value: float) -> str:
    return f"{value:.3f}".replace(".", ",")


def report(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


class DrawCostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.quick_access = _module("bl.ui.quick_access")
        cls.statusbar = _module("bl.ui.statusbar")
        cls.registry = _module("bl.ui.registry")
        cls.georef = _module("bl.scene.georef")
        cls.command_line = _module("bl.ui.command_line")
        cls.owner = SimpleNamespace(layout=NullLayout())
        cls.window = bpy.context.window_manager.windows[0]

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def context(self, *, width: float, area: object | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            workspace=SimpleNamespace(geoblender_mode=True, use_filter_by_owner=False),
            screen=SimpleNamespace(show_fullscreen=False, show_statusbar=True),
            area=area or SimpleNamespace(show_menus=True, type="TOPBAR"),
            region=SimpleNamespace(type="TOOL_HEADER", width=width, alignment="LEFT"),
            mode="OBJECT", scene=bpy.context.scene, space_data=None, window=self.window,
            preferences=bpy.context.preferences,
        )

    def test_topbar(self) -> None:
        """RNF-003-02: la barra superior en modo Geoblender a 1920 px ≤ 0,5 ms."""
        draw_left = bpy.types.TOPBAR_HT_upper_bar.draw_left
        ctx = self.context(width=1920)
        value = median_ms(lambda: draw_left(self.owner, ctx))
        report(f"RNF-003-02: barra superior (modo Geoblender, 1920 px), mediana de {CALLS}: "
               f"{_ms(value)} ms (≤ {_ms(TOPBAR_BUDGET_MS)} ms)")
        self.assertLessEqual(value, TOPBAR_BUDGET_MS)

    def test_view_row(self) -> None:
        """RNF-003-02: la fila 2 de la Vista 3D, entera (1300 px) y plegada (650 px),
        ≤ 0,5 ms."""
        for width in (1300.0, 650.0):
            with self.subTest(width=width):
                ctx = self.context(width=width, area=_Area(int(width)))
                value = median_ms(lambda: self.quick_access.draw_view_row(self.owner, ctx))
                report(f"RNF-003-02: fila 2 de la Vista 3D ({width:.0f} px), mediana de "
                       f"{CALLS}: {_ms(value)} ms (≤ {_ms(ROW2_BUDGET_MS)} ms)")
                self.assertLessEqual(value, ROW2_BUDGET_MS)

    def test_statusbar(self) -> None:
        """RNF-003-02: la barra de estado minera con un proyecto (nombre, EPSG, cursor
        absoluto, encaje y recorte) ≤ 0,3 ms."""
        fake = self.georef.SceneGeoref("uid", "Cantera sintética", 25830, 0,
                                       (736500, 4435900, 0))
        ctx = self.context(width=1920)
        ctx.area = None
        with mock.patch.object(self.georef, "project_georeference", return_value=fake):
            value = median_ms(lambda: self.statusbar.draw_statusbar(self.owner, ctx))
        report(f"RNF-003-02: barra de estado minera (con proyecto), mediana de {CALLS}: "
               f"{_ms(value)} ms (≤ {_ms(STATUSBAR_BUDGET_MS)} ms)")
        self.assertLessEqual(value, STATUSBAR_BUDGET_MS)

    def test_menus(self) -> None:
        """RNF-003-02: cada menú de la interfaz (los 13 de la barra con 1000 llamadas, los
        demás con 200) ≤ 1 ms."""
        cat = _module("bl.ui.commands").catalog()
        top = set(cat.top_menus)
        menus = [cls for cls in self.registry.own_classes()
                 if issubclass(cls, bpy.types.Menu) and getattr(cls, "is_registered", False)]
        self.assertGreater(len(menus), 50)
        ctx = self.context(width=1920)
        slowest: list[tuple[float, str]] = []
        for cls in menus:
            calls = CALLS if cls.bl_idname in top else MENU_CALLS
            owner = SimpleNamespace(layout=NullLayout(), bl_idname=cls.bl_idname)
            value = median_ms(lambda cls=cls, owner=owner: cls.draw(owner, ctx), calls)
            slowest.append((value, cls.bl_idname))
        slowest.sort(reverse=True)
        worst, name = slowest[0]
        report(f"RNF-003-02: menús ({len(menus)}), el más lento {name}: {_ms(worst)} ms "
               f"(mediana; ≤ {_ms(MENU_BUDGET_MS)} ms); los 13 de la barra, hasta "
               f"{_ms(max(v for v, n in slowest if n in top))} ms")
        self.assertLessEqual(worst, MENU_BUDGET_MS, slowest[:5])

    def test_command_line(self) -> None:
        """RNF-003-07: una consulta de F10 (la lista que se ve) ≤ 20 ms con el catálogo
        completo."""
        cat = _module("bl.ui.commands").catalog()
        self.assertGreaterEqual(len(cat.commands), 350)
        times: list[float] = []
        for query in QUERIES:
            for _ in range(20):
                start = time.perf_counter()
                self.command_line.suggestions(query)
                times.append((time.perf_counter() - start) * 1000.0)
        value = statistics.median(times)
        report(f"RNF-003-07: línea de comandos (F10), {len(cat.commands)} comandos, "
               f"{len(QUERIES)} consultas × 20: mediana {_ms(value)} ms, máximo "
               f"{_ms(max(times))} ms (≤ {_ms(SEARCH_BUDGET_MS)} ms)")
        self.assertLessEqual(max(times), SEARCH_BUDGET_MS)


if __name__ == "__main__":
    unittest.main()
