# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que cuenta en un recinto con la base de los acopios, en lo que enseña la interfaz (spec 016, T30; RF-012-22, RF-012-30).

Con la base de los acopios, la verificación guarda como lo que cuenta en las zonas sin corte, de solo relleno, de solo
restauración, de resguardo y en la banda hacia dentro de un límite el **corte de terreno** (``cut_terrain``) y no el corte
(``cut``). Las líneas de la barra N «Restricción» (``_final_text``) y de la ventana de la verificación (``_group_text``) enseñaban
«movimiento» de un modo de contar que no conocían: el corte de terreno se enseña como corte (los m³ de corte de terreno).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace

from tests.support import blender_ext
from tests.support.blender_ext import module_name


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class CountsTerrainTextTest(unittest.TestCase):
    """RF-012-22, RF-012-30: el corte de terreno se lee como el corte."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.panels = _module("bl.ui.constraint_panels")

    def test_the_line_of_a_final_shows_the_terrain_cut_as_cut(self) -> None:
        """RF-012-22: la línea de un final con el corte de terreno lleva los m³ y dice lo mismo que la del corte, y no lo que
        dice del movimiento."""
        def final(counts: str) -> SimpleNamespace:
            return SimpleNamespace(surface="Retirada", verdict="fails", counted_m3=2.0, counts=counts)

        terrain, cut = self.panels._final_text(final("cut_terrain")), self.panels._final_text(final("cut"))
        self.assertEqual(terrain, cut)
        self.assertNotEqual(terrain, self.panels._final_text(final("any")))
        self.assertIn("2", terrain)

    def test_the_line_of_a_group_shows_the_terrain_cut_as_cut(self) -> None:
        """RF-012-23, RF-012-30: la línea de un grupo que incumple en un recinto de terreno es la del corte."""
        group = SimpleNamespace(volume_m3=0.5, area_m2=1.0, max_m=0.5, x=500_004.5, y=4_400_005.5)
        terrain = self.panels._group_text(group, "Zona de acopios", "cut_terrain")
        self.assertEqual(terrain, self.panels._group_text(group, "Zona de acopios", "cut"))
        self.assertNotEqual(terrain, self.panels._group_text(group, "Zona de acopios", "any"))
        self.assertNotEqual(terrain, self.panels._group_text(group, "Zona de acopios", "fill"))


if __name__ == "__main__":
    unittest.main()
