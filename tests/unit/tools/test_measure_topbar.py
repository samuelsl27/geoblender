# SPDX-License-Identifier: GPL-3.0-or-later
"""El análisis de la medida de la barra en la GUI (spec 003, T19;
``tools/inblender/measure_topbar.py``; RF-003-10; RNF-003-01, RNF-003-03; BS §2.2 y §2.3).

``gbtools.topbar_measure`` es puro: parte cada franja capturada (columnas con contenido)
por su hueco mayor, ajusta las constantes del modelo de BS §2.3 a las anchuras medidas de
los cinco niveles y comprueba RNF-003-01 y RNF-003-03 con lo medido.
"""

import unittest

from tests.support.package import import_geoblender
from tests.support.repo import tools_on_path

tools_on_path()

from gbtools import topbar_measure  # noqa: E402

width = import_geoblender("core.catalog.width")
catalog = import_geoblender("core.catalog")


def band(*segments: tuple[int, int], total: int = 1920) -> list[bool]:
    """Una franja de ``total`` columnas con contenido en los tramos dados."""
    columns = [False] * total
    for start, end in segments:
        columns[start:end] = [True] * (end - start)
    return columns


class SplitTest(unittest.TestCase):
    def test_left_part_gap_and_right_block(self) -> None:
        """BS §2.2: la parte izquierda (botones con huecos pequeños entre ellos), el hueco
        mayor y el bloque derecho; lo libre es el hueco."""
        columns = band((4, 60), (66, 700), (705, 1330), (1587, 1700), (1706, 1916))
        parts = topbar_measure.split(columns)
        self.assertEqual((parts.first, parts.left_end, parts.right_start, parts.last),
                         (4, 1330, 1587, 1916))
        self.assertEqual((parts.left_px, parts.free_px, parts.right_px), (1326, 257, 329))

    def test_single_block_and_empty(self) -> None:
        """Sin hueco, todo es la parte izquierda; una franja vacía no tiene medida."""
        parts = topbar_measure.split(band((10, 400), (405, 900)))
        self.assertEqual((parts.left_px, parts.right_start), (890, 1920))
        self.assertIsNone(topbar_measure.split(band()))

    def test_native_settings(self) -> None:
        """AR §3.2: los ajustes nativos de la fila 2 son el contenido sin el hueco central
        (modos de selección a la izquierda y «Opciones» a la derecha)."""
        self.assertEqual(topbar_measure.native_px(band((60, 153), (1236, 1300), total=1300)),
                         93 + 64)
        self.assertEqual(topbar_measure.native_px(band((60, 153), total=1300)), 93)
        self.assertEqual(topbar_measure.native_px(band(total=1300)), 0)


class FitTest(unittest.TestCase):
    """Las constantes que reproducen las anchuras medidas."""

    @classmethod
    def setUpClass(cls) -> None:
        cat = catalog.load()
        cls.flow = [m for m in cat.top_menus if m not in (width.TOOLS_MENU, width.HELP_MENU)]
        names = {"es": ("Proyecto", "Topografía", "Sondeos", "Geología", "Bloques",
                        "Optimización", "Diseño", "Restauración", "Cubicación",
                        "Planificación", "Planos", "Herramientas", "Ayuda"),
                 "en": ("Project", "Topography", "Drillholes", "Geology", "Blocks",
                        "Optimization", "Design", "Reclamation", "Volumetrics", "Scheduling",
                        "Drawings", "Tools", "Help")}
        cls.titles = {}
        for language, titles in names.items():
            found = {menu: 6.3 * len(title) for menu, title in zip(cat.top_menus, titles,
                                                                    strict=True)}
            found[width.GEOBLENDER_MENU] = 6.3 * 10  # el título del nivel E, 10 letras
            cls.titles[language] = found

    def fit(self, samples: list[object]) -> dict[str, float]:
        return topbar_measure.fit_topbar_constants(
            samples, self.titles, flow=self.flow, tools=width.TOOLS_MENU,
            help_=width.HELP_MENU, geoblender=width.GEOBLENDER_MENU)

    def test_round_trip(self) -> None:
        """BS §2.3: con anchuras calculadas por el modelo (``topbar_width``) con unas
        constantes cualesquiera, a 1,0 y a 1,25 y en los dos idiomas, el ajuste devuelve
        esas constantes."""
        k = width.TopbarWidthConstants(menu_pad=25.0, title_icon=19.0, icon_menu=33.0,
                                       fixed_b=301.0, version_compact=58.0)
        samples = []
        for language in ("es", "en"):
            for scale in (1.0, 1.25):
                widths = {level.value: width.topbar_width(level, scale=scale,
                                                          titles_px=self.titles[language], k=k)
                          for level in width.Level}
                samples.append(topbar_measure.Sample(language, scale, widths))
        fitted = self.fit(samples)
        for name in ("menu_pad", "title_icon", "icon_menu", "fixed_b", "version_compact"):
            with self.subTest(name=name):
                self.assertAlmostEqual(fitted[name], getattr(k, name), places=6)

    def test_incomplete_samples_ignored(self) -> None:
        """Una muestra sin los cinco niveles no cuenta; sin ninguna completa, nada."""
        self.assertEqual(self.fit([topbar_measure.Sample("es", 1.0, {"B": 1326.0})]), {})

    def test_right_block(self) -> None:
        """BS §2.2 y §2.3: 333 px medidos a 1,0 y 415 a 1,25 dan 333 a escala 1,0 y la
        constante 340."""
        measured = topbar_measure.right_block_px([(1920, 1587, 1.0), (1920, 1505, 1.25)])
        self.assertAlmostEqual(measured, 333.0)
        self.assertEqual(topbar_measure.suggested_right_block(measured), 340.0)


class ChecksTest(unittest.TestCase):
    def test_rnf(self) -> None:
        """RNF-003-01 y RNF-003-03 con lo medido: los valores de BS §2.2 (257 y 49 px en
        español) pasan; uno que falta o se queda corto, no; y el redibujo con más de 1 ms
        de diferencia, tampoco."""
        free = {("es", 1.0, "B"): 257.0, ("en", 1.0, "B"): 314.0,
                ("es", 1.25, "C"): 49.0, ("en", 1.25, "C"): 23.0}
        result = topbar_measure.checks(free, geoblender_ms=8.4, blender_ms=7.9)
        self.assertTrue(result["RNF-003-01 B es 1.0 >= 150"])
        self.assertTrue(result["RNF-003-01 B en 1.0 >= 150"])
        self.assertTrue(result["RNF-003-01 C es 1.25 >= 24"])
        self.assertFalse(result["RNF-003-01 C en 1.25 >= 24"])
        self.assertTrue(result["RNF-003-03 redibujo <= Blender + 1 ms"])
        late = topbar_measure.checks({}, geoblender_ms=9.0, blender_ms=7.9)
        self.assertFalse(late["RNF-003-03 redibujo <= Blender + 1 ms"])
        self.assertFalse(late["RNF-003-01 B es 1.0 >= 150"])
        self.assertAlmostEqual(topbar_measure.redraw_ms(1.6, 200), 8.0)


if __name__ == "__main__":
    unittest.main()
