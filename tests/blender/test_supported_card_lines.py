# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que la barra N dice de un cuerpo apoyado, sin proyecto (spec 016, T48; hallazgo D-9 de la verificación única; RF-016-21).

La barra N de un cuerpo da **lo lejano** —lo que queda a más de la distancia máxima de un dato— con esa distancia: con 12,5 m decía «a
más de 13 m» (la escribía sin decimales). Ahora la escribe con los suyos y sin ceros de más (12,5, 30, 12,25). Se prueba con las líneas
que escribe ``des_panels._body_card_lines`` de un informe a mano, sin proyecto; se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType

from tests.support import blender_ext


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


def _report(distance: float, far_m2: float) -> list[tuple[str, float | None, str | None, str | None]]:
    """Las filas del informe de un cuerpo que usa la barra N: la distancia máxima y lo lejano (con su volumen y su mayor distancia)."""
    return [("thickness_max_m", 3.0, "m", "725010.5;4400020.5"), ("max_distance_m", distance, "m", None), ("far_m2", far_m2, "m2", None),
            ("far_m3", far_m2 * 2.0, "m3", None), ("farthest_m", distance + 25.5, "m", None)]


class BodyCardLinesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.panels = _module("bl.ui.des_panels")
        cls.i18n = _module("core.i18n")

    def setUp(self) -> None:
        self.addCleanup(self.i18n.set_language, self.i18n.language())

    def lines(self, language: str, report: list) -> list[tuple[str, bool]]:
        self.i18n.set_language(language)
        return [(line.text, line.alert) for line in self.panels._body_card_lines(None, {}, report)]

    def test_the_far_distance_is_written_with_its_decimals(self) -> None:
        """RF-016-21 (D-9): con 12,5 m de distancia máxima, lo lejano dice «farther than 12.5 m» (en español, «12,5 m») y no «13 m»; con
        12,25 m, «12.25»; con una distancia entera (30 m), «30 m» sin «,0»; en alerta, y la mayor distancia como siempre."""
        for distance, shown_en, shown_es in ((12.5, "12.5", "12,5"), (12.25, "12.25", "12,25"), (30.0, "30", "30"), (0.5, "0.5", "0,5")):
            with self.subTest(distance=distance):
                english = self.lines("en", _report(distance, 450.0))
                (far,) = [text for text, alert in english if "farther than" in text]
                self.assertIn(f"farther than {shown_en} m from a datum", far)
                if distance != round(distance):
                    self.assertNotIn(f"farther than {round(distance)} m", far, "sin decimales")
                self.assertIn("the farthest at", far)
                self.assertTrue(dict(english)[far], "lo lejano va en alerta")
                spanish = self.lines("es", _report(distance, 450.0))
                self.assertTrue(any(f"{shown_es} m" in text and "{" not in text for text, _alert in spanish), spanish)

    def test_when_nothing_is_far_the_distance_has_its_decimals_too(self) -> None:
        """RF-016-21 (D-9): sin nada lejano, «Nothing is farther than 12.5 m from a datum» (en español, «12,5 m»)."""
        english = self.lines("en", _report(12.5, 0.0))
        self.assertIn("Nothing is farther than 12.5 m from a datum", [text for text, _alert in english])
        self.assertTrue(any("12,5 m" in text for text, _alert in self.lines("es", _report(12.5, 0.0))))


if __name__ == "__main__":
    unittest.main()
