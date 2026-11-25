# SPDX-License-Identifier: GPL-3.0-or-later
"""Coste por fotograma de leer el grosor y el tamaño del aspecto al dibujar (spec 019, T07b; RF-019-07).

Cada redibujo de la Vista 3D recorre los objetos de la capa de vista. Antes, ``bl.draw.contours`` los recorría una
vez (``_shown``); ahora ``bl.draw.look`` los recorre otra (``style.plan``). Con 2000 objetos de los tipos de
Geoblender (sin ningún valor guardado: el caso normal) se mide cada recorrido y el añadido debe quedar dentro de
:data:`BUDGET_MS` por fotograma; con valores guardados en unos pocos objetos, el coste es el de esos pocos.

Se ejecuta con ``tools/check.py --rendimiento`` o con ``tools/run_blender_tests.py -- --carpeta
tests/rendimiento/blender --patron "perf_draw_look.py"``.
"""

import statistics
import sys
import time
import unittest
from collections.abc import Callable
from typing import Any

import bpy

from tests.support import blender_ext
from tests.support import views_fixtures as vf

OBJECTS = 2000
REPEATS = 15
BUDGET_MS = 0.3  # lo que puede añadir la superposición nueva por fotograma con 2000 objetos


def _median_ms(fn: Callable[[], Any]) -> float:
    times = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000.0)
    return statistics.median(times)


class DrawLookCostTest(unittest.TestCase):
    def test_per_frame_cost(self) -> None:
        """RF-019-07: la lectura del aspecto al dibujar añade ≤ 0,3 ms por fotograma con 2000 objetos."""
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(blender_ext.release)
        kinds = ("BREAKLINES", "POINTS", "CONTOURS", "DTM", "BOUNDARY")
        mesh = bpy.data.meshes.new("perf")
        for index in range(OBJECTS):
            obj = bpy.data.objects.new(f"perf{index}", mesh)
            bpy.context.scene.collection.objects.link(obj)
            obj.geoblender.kind = kinds[index % len(kinds)]
        contours, style = vf.extension("bl.draw.contours"), vf.extension("bl.draw.style")
        bpy.context.view_layer.update()
        objects = bpy.context.view_layer.objects
        self.assertGreaterEqual(len(objects), OBJECTS)
        before = _median_ms(lambda: [o for o in objects if o.geoblender.kind == contours.CONTOURS_KIND])
        style.invalidate()
        style.candidates()
        after_none = _median_ms(lambda: style.plan(style.candidates(), pixel_size=1.0))
        for index, obj in enumerate(o for o in objects if o.geoblender.kind == "BREAKLINES"):
            if index < 20:
                obj.geoblender.look.line_width = 3.0
        after_some = _median_ms(lambda: style.plan(style.candidates(), pixel_size=1.0))
        print(f"T07b: recorrido de {OBJECTS} objetos por fotograma: antes (maestras) {before:.3f} ms; "
              f"añadido sin valores guardados {after_none:.3f} ms; con 20 guardados {after_some:.3f} ms",
              file=sys.stderr, flush=True)
        self.assertLessEqual(after_some, BUDGET_MS)


if __name__ == "__main__":
    unittest.main()
