# SPDX-License-Identifier: GPL-3.0-or-later
"""El grosor de línea y el tamaño de punto del aspecto llegan a lo que se dibuja (spec 019, T07b; RF-019-07).

Sin pantalla: se comprueba el valor que se leerá y se pasará al *shader* (``bl.draw.style.plan``, función pura) y
que el tipo lo ofrece solo si una superposición lo lee (UI-13).

- Con un valor guardado en ``Object.geoblender.look`` el trazo sale con ese grosor (por el tamaño de píxel); sin valor
  guardado, o de 1 px o menos en las líneas, no se dibuja nada encima y las maestras conservan sus 3 px.
- ``offered`` ofrece ``line_width`` en los tipos de aristas y ``point_size`` en los puntos; no en los sondeos ni
  en las superficies.
- La superposición está registrada y desaparece al desactivar la extensión.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from typing import Any

import bpy

from tests.support import blender_ext
from tests.support import views_fixtures as vf


def _style() -> Any:
    return vf.extension("bl.draw.style")


def _object(name: str, kind: str) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [(0, 1), (1, 2)], [])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.geoblender.kind = kind
    return obj


class AppearanceDrawTest(unittest.TestCase):
    def setUp(self) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(blender_ext.release)

    def test_offered_where_an_overlay_reads_it(self) -> None:
        """RF-019-07, UI-13: grosor en los tipos de aristas, tamaño en los puntos; ni en sondeos ni en superficies."""
        offered = vf.extension("bl.scene.appearance").offered
        for kind in sorted(_style().LINE_KINDS):
            self.assertIn("line_width", offered(kind), kind)
            self.assertNotIn("point_size", offered(kind), kind)
        self.assertIn("point_size", offered("POINTS"))
        self.assertNotIn("line_width", offered("POINTS"))
        for kind in ("DRILLHOLES", "DTM", "TIN", "DESIGN_ENTITY"):
            self.assertNotIn("line_width", offered(kind), kind)
            self.assertNotIn("point_size", offered(kind), kind)

    def test_no_stored_value_draws_nothing_new(self) -> None:
        """RF-019-07: sin valor guardado nada cambia (ni trazo nuevo ni maestras distintas)."""
        style = _style()
        objects = [_object("brk", "BREAKLINES"), _object("pts", "POINTS"), _object("cnt", "CONTOURS")]
        self.assertEqual(style.plan(objects, pixel_size=1.0), [])
        self.assertIsNone(style.stored(objects[0], "line_width"))
        self.assertEqual(style.index_factor(objects[2]), 1.0)

    def test_stored_line_width_reaches_the_stroke(self) -> None:
        """RF-019-07: el grosor guardado, por el tamaño de píxel; de 1 px o menos, nada (no se afina el alambre)."""
        style = _style()
        brk = _object("brk", "BREAKLINES")
        brk.geoblender.look.line_width = 4.0
        (stroke,) = style.plan([brk], pixel_size=2.0)
        self.assertEqual((stroke.primitive, stroke.size_px, stroke.own_color), ("LINES", 8.0, False))
        brk.geoblender.look.color = (1.0, 0.0, 0.0)
        self.assertTrue(style.plan([brk], pixel_size=1.0)[0].own_color)
        brk.geoblender.look.line_width = 1.0
        self.assertEqual(style.plan([brk], pixel_size=1.0), [])

    def test_stored_point_size_reaches_the_stroke(self) -> None:
        """RF-019-07: el tamaño guardado de un punto; solo en los tipos de puntos."""
        style = _style()
        pts, dtm = _object("pts", "POINTS"), _object("dtm", "DTM")
        pts.geoblender.look.point_size = 7.0
        dtm.geoblender.look.point_size = 7.0
        strokes = style.plan([pts, dtm], pixel_size=1.0)
        self.assertEqual([(s.obj.name, s.primitive, s.size_px) for s in strokes], [("pts", "POINTS", 7.0)])

    def test_contour_index_stroke_follows_the_stored_width(self) -> None:
        """RF-019-07: las maestras: 3 px de siempre (factor 1) y × el grosor guardado."""
        style = _style()
        cnt = _object("cnt", "CONTOURS")
        contours = vf.extension("bl.draw.contours")
        self.assertEqual(contours.INDEX_LINE_WIDTH * style.index_factor(cnt), 3.0)
        cnt.geoblender.look.line_width = 2.0
        self.assertEqual(contours.INDEX_LINE_WIDTH * style.index_factor(cnt), 6.0)

    def test_candidates_are_the_objects_with_a_stored_value(self) -> None:
        """RF-019-07: cada fotograma mira solo los objetos con valor guardado; tras abrir un ``.blend`` o deshacer
        (``invalidate``) se vuelven a buscar entre todos y un objeto borrado se descarta."""
        style = _style()
        brk, pts, dtm = _object("brk", "BREAKLINES"), _object("pts", "POINTS"), _object("dtm", "DTM")
        self.assertEqual(style.candidates(), [])
        brk.geoblender.look.line_width = 3.0
        pts.geoblender.look.point_size = 5.0
        self.assertEqual(sorted(o.name for o in style.candidates()), ["brk", "pts"])
        style.invalidate()
        self.assertEqual(sorted(o.name for o in style.candidates()), ["brk", "pts"])
        self.assertNotIn(dtm, style.candidates())
        bpy.data.objects.remove(pts)
        self.assertEqual([o.name for o in style.candidates()], ["brk"])

    def test_overlay_registered_and_removed(self) -> None:
        """Principio 8: la superposición se registra y desaparece al desactivar."""
        look = vf.extension("bl.draw.look")
        self.assertTrue(look.drawing())
        blender_ext.disable()
        self.assertFalse(look.drawing())


if __name__ == "__main__":
    unittest.main()
