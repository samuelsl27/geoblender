# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista previa que no tapa la vista (spec 019, T23; RF-019-19; plan 019 §5.1; UI-09, UI-11, UI-12, UI-28, UI-35).

- RF-019-19, UI-12: el texto de la vista previa (el resumen de ``bl.draw.design.summary_items``) queda anclado a la esquina superior
  izquierda y **no incluye el centro** de la región a 1920 × 1001 a las tres escalas efectivas (1,0, 1,25 y 1,5556), con la barra de
  herramientas a la izquierda y con un resumen largo (lo que no cabe se pliega en una línea que remite al informe). Un manejador de dibujo
  no recibe eventos: orbitar, acercar y seleccionar siguen siendo de Blender (M13, en el H3).
- RF-019-19: la vista previa se quita al cancelar y al conmutar (lo prueban ``test_pit_preview`` y ``test_road_preview``, apartado e); aquí,
  que sus manejadores desaparecen con ``disable``.
- UI-09: «HIPÓTESIS: sin valor por defecto, lo elige usted» no se repite bajo cada campo de un diálogo: se dice una vez
  (``des_panels.fold_kinds``) y solo conserva su línea el campo que difiere.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType

from tests.support import blender_ext
from tests.support.blender_ext import module_name

REGION = (1920.0, 1001.0)
SCALES = (1.0, 1.25, 1.5556)
TOOLBAR_PX = (0.0, 56.0, 70.0)
KIND = "HIPÓTESIS: sin valor por defecto, lo elige usted"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _measure(text: str) -> float:
    return 7.0 * len(text)  # el ancho de una fuente de mentira


def _summary(count: int) -> tuple[tuple[str, bool], ...]:
    long_line = "Semillas: 25 600 celdas (102 400 m²), cotas 650,0 a 650,0 m; dominio: 3,4 ha; " * 4
    return tuple((f"{index}. {long_line}", index % 7 == 0) for index in range(count))


class PreviewTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.design = _module("bl.draw.design")
        cls.pixels = _module("bl.draw.dh_overlay")
        cls.panels = _module("bl.ui.des_panels")

    def test_a_the_text_does_not_include_the_centre(self) -> None:
        centre = (REGION[0] / 2.0, REGION[1] / 2.0)
        for scale in SCALES:
            for covered in TOOLBAR_PX:
                for count in (1, 6, 40):
                    with self.subTest(scale=scale, covered=covered, count=count):
                        items = self.design.summary_items(_summary(count), _measure, scale, REGION, covered)
                        box = items[0]
                        inside = box.x0 <= centre[0] <= box.x1 and box.y0 <= centre[1] <= box.y1
                        self.assertFalse(inside)
                        self.assertGreater(box.y0, centre[1])  # entero por encima del centro
                        self.assertLess(box.x1, centre[0])  # y a su izquierda
                        self.assertGreaterEqual(box.x0, covered)  # a la derecha de la barra
                        texts = [item for item in items[1:] if isinstance(item, self.pixels.Text)]
                        self.assertTrue(all(item.y > centre[1] for item in texts))

    def test_b_a_long_summary_is_folded_with_a_pointer_to_the_report(self) -> None:
        items = self.design.summary_items(_summary(40), _measure, 1.5556, REGION, 70.0)
        last = [item for item in items if isinstance(item, self.pixels.Text)][-1]
        self.assertTrue(last.text.startswith("…"))
        short = self.design.summary_items(_summary(1), _measure, 1.0, REGION, 0.0)
        self.assertFalse([item for item in short if isinstance(item, self.pixels.Text)][-1].text.startswith("…"))

    def test_c_disable_removes_the_handlers(self) -> None:
        entity = _module("bl.draw.entity")
        entity.disable()
        self.assertFalse(entity.enabled())

    def test_d_the_kind_is_said_once(self) -> None:
        other = "Por defecto: 5.000.000 · ADOPTADO"
        rows, shared = self.panels.fold_kinds([KIND, KIND, other, KIND])
        self.assertEqual(shared, KIND)
        self.assertEqual(rows, ["", "", other, ""])
        rows, shared = self.panels.fold_kinds([KIND, other])
        self.assertEqual((rows, shared), ([KIND, other], ""))  # nada repetido: cada uno con el suyo
        self.assertEqual(self.panels.fold_kinds([KIND]), ([KIND], ""))
        self.assertEqual(self.panels.fold_kinds([]), ([], ""))


if __name__ == "__main__":
    unittest.main()
