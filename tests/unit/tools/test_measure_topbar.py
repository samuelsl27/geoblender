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

    def test_split_at_region_edge(self) -> None:
        """Convergencia, T42 (hallazgo D3): con el borde de la región de ``draw_left``
        conocido (1500 px con escala efectiva 1,25), la parte izquierda es lo que hay
        antes del borde y el bloque derecho, lo de después, aunque el hueco mayor esté
        dentro de la parte izquierda (un nivel que no cabe y llega casi al borde)."""
        columns = band((4, 400), (460, 900), (905, 1490), (1505, 1916))
        parts = topbar_measure.split_at(columns, 1500)
        self.assertEqual((parts.first, parts.left_end, parts.right_start, parts.last),
                         (4, 1490, 1505, 1916))
        fits = topbar_measure.split_at(band((4, 1450), (1505, 1916)), 1500)
        self.assertEqual((fits.left_px, fits.free_px), (1446, 55))
        alone = topbar_measure.split_at(band((4, 700)), 1500)
        self.assertEqual((alone.left_px, alone.right_start), (696, 1920))
        self.assertIsNone(topbar_measure.split_at(band((1505, 1916)), 1500))

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

    def test_clipped_levels_left_out(self) -> None:
        """Convergencia, T42: los niveles recortados (A y B con escala efectiva 1,25) no
        se miden; el ajuste usa los demás, de todas las muestras, por mínimos cuadrados, y
        devuelve las mismas constantes. Sin A en ninguna muestra no hay ``title_icon``;
        con menos ecuaciones distintas que incógnitas, nada."""
        k = width.TopbarWidthConstants(menu_pad=25.0, title_icon=19.0, icon_menu=33.0,
                                       fixed_b=301.0, version_compact=58.0)

        def sample(language: str, scale: float, levels: str) -> object:
            return topbar_measure.Sample(language, scale, {
                level: width.topbar_width(width.Level[level], scale=scale,
                                          titles_px=self.titles[language], k=k)
                for level in levels})

        fitted = self.fit([sample("es", 1.0, "BCDE"), sample("en", 1.0, "ABCDE"),
                           sample("es", 1.25, "CDE"), sample("en", 1.25, "CDE")])
        for name in ("menu_pad", "title_icon", "icon_menu", "fixed_b", "version_compact"):
            with self.subTest(name=name):
                self.assertAlmostEqual(fitted[name], getattr(k, name), places=6)
        without_a = self.fit([sample("es", 1.0, "BCDE"), sample("es", 1.25, "CDE")])
        self.assertNotIn("title_icon", without_a)
        self.assertAlmostEqual(without_a["fixed_b"], k.fixed_b, places=6)
        self.assertEqual(self.fit([topbar_measure.Sample("es", 1.0, {"B": 1326.0})]), {})
        self.assertEqual(self.fit([sample("es", 1.0, "CDE"), sample("en", 1.25, "CD")]), {})

    def test_right_block(self) -> None:
        """BS §2.2 y §2.3: 333 px medidos a 1,0 y 415 a 1,25 dan 333 a escala 1,0 y la
        constante 340."""
        measured = topbar_measure.right_block_px([(1920, 1587, 1.0), (1920, 1505, 1.25)])
        self.assertAlmostEqual(measured, 333.0)
        self.assertEqual(topbar_measure.suggested_right_block(measured), 340.0)


class LevelChoiceTest(unittest.TestCase):
    def test_right_region(self) -> None:
        """Convergencia, T42: el bloque derecho a escala 1,0 es la región derecha de la
        barra entre la escala efectiva (336 px a 1,0 y 420 a 1,25 → 336)."""
        self.assertAlmostEqual(topbar_measure.right_region_px([(336, 1.0), (420, 1.25)]),
                               336.0)
        self.assertEqual(topbar_measure.right_region_px([]), 0.0)

    def test_best_level(self) -> None:
        """RF-003-10 (convergencia, T42): el nivel más informativo que cabe es el primero
        de A a E que no está recortado y deja el margen libre (24 px × escala efectiva)."""
        free = {"A": 0.0, "B": 2.0, "C": 55.0, "D": 700.0, "E": 1060.0}
        self.assertEqual(topbar_measure.best_level(free, {"A", "B"}, margin_px=30.0), "C")
        self.assertEqual(topbar_measure.best_level({"A": 62.0, "B": 314.0}, set(),
                                                   margin_px=24.0), "A")
        self.assertEqual(topbar_measure.best_level({"A": 20.0, "B": 257.0}, set(),
                                                   margin_px=24.0), "B")
        self.assertIsNone(topbar_measure.best_level({"E": 3.0}, set(), margin_px=24.0))


class ChecksTest(unittest.TestCase):
    def test_automatic_level(self) -> None:
        """RF-003-10, BS §3 (convergencia, T42): con la escala efectiva, el automático da
        B en español y A o B en inglés a 1,0, C a 1,25, y en cada medida el nivel más
        informativo que cabe; uno que falta o es otro, no (el hallazgo D2: D a 1,25)."""
        chosen = {("es", 1.0): "B", ("en", 1.0): "A", ("es", 1.25): "C", ("en", 1.25): "D"}
        best = {("es", 1.0): "B", ("en", 1.0): "A", ("es", 1.25): "C", ("en", 1.25): "C"}
        result = topbar_measure.checks({}, chosen=chosen, best=best, geoblender_ms=None,
                                       blender_ms=None)
        self.assertTrue(result["BS §3 automático es 1.0 = B"])
        self.assertTrue(result["BS §3 automático en 1.0 = A o B"])
        self.assertTrue(result["BS §3 automático es 1.25 = C"])
        self.assertFalse(result["BS §3 automático en 1.25 = C"])
        self.assertTrue(result["RF-003-10 automático es 1.25 = el más informativo que cabe"])
        self.assertFalse(result["RF-003-10 automático en 1.25 = el más informativo que cabe"])
        missing = topbar_measure.checks({}, geoblender_ms=None, blender_ms=None)
        self.assertFalse(missing["BS §3 automático es 1.0 = B"])
        self.assertFalse(missing["BS §3 automático en 1.25 = C"])

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
