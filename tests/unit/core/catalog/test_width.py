# SPDX-License-Identifier: GPL-3.0-or-later
"""Modelo de anchura de la barra superior y plegado de la fila 2 (spec 003, T10;
RF-003-10, RF-003-11, RNF-003-01; BS §2.2, §2.3 y §3; AR §3.2 y §3.3).

Con los anchos de BS §2.2 (los 13 títulos suman 686 px en español y 629 en inglés con
``blf`` a 11 pt; aquí, repartidos por letras) y las constantes de BS §2.3:

- a 1920 px y escala 1,0, nivel B en español con ≥ 150 px libres, y en inglés el nivel B
  también deja ≥ 150 px (RNF-003-01); el automático elige el primero de A a E que cabe
  (RF-003-10): en inglés, A (BS §3: «1920 px en inglés»);
- a 1,25, nivel C con ≥ 24 px libres en los dos idiomas; D a 1366 px y a 1,5; C a 1600 px;
  E por debajo de 900 px; A a 2200 px; el nivel forzado se respeta;
- la fila 2 (24 controles): entera a 1300 px; a 1,25, paso 1; a 650 px, solo Vista,
  Sección (la banda en icono), Nueva polilínea y Encaje con «»» (AR §3.3, unos 375 px);
  los cinco pasos en orden; en edición, solo su subconjunto.
"""

import unittest

from tests.support.package import import_geoblender

catalog = import_geoblender("core.catalog")
width = import_geoblender("core.catalog.width")

Level = width.Level
TITLES_ES = ("Proyecto", "Topografía", "Sondeos", "Geología", "Bloques", "Optimización",
             "Diseño", "Restauración", "Cubicación", "Planificación", "Planos",
             "Herramientas", "Ayuda")
TITLES_EN = ("Project", "Topography", "Drillholes", "Geology", "Blocks", "Optimization",
             "Design", "Reclamation", "Volumetrics", "Scheduling", "Drawings", "Tools", "Help")
MEASURED_TOTAL = {"es": 686.0, "en": 629.0}  # BS §2.2, blf a 11 pt


def titles_px(language: str) -> dict[str, float]:
    """Anchos de título por menú repartiendo el total medido por letras, y el de
    «Geoblender» (nivel E) con la misma proporción."""
    cat = catalog.load()
    titles = TITLES_ES if language == "es" else TITLES_EN
    per_char = MEASURED_TOTAL[language] / sum(len(title) for title in titles)
    found = {menu: len(title) * per_char for menu, title in zip(cat.top_menus, titles, strict=True)}
    geoblender = cat.commands[width.GEOBLENDER_MENU]
    found[width.GEOBLENDER_MENU] = len(geoblender.label_es if language == "es"
                                       else geoblender.label) * per_char
    return found


class TopbarLevelTest(unittest.TestCase):
    k = width.TopbarWidthConstants()

    def level(self, region: float, scale: float, language: str, forced: object = None) -> object:
        return width.choose_topbar_level(region_width_px=region, scale=scale,
                                         titles_px=titles_px(language), k=self.k, forced=forced)

    def free(self, level: object, region: float, scale: float, language: str) -> float:
        return width.topbar_free_px(level, region_width_px=region, scale=scale,
                                    titles_px=titles_px(language), k=self.k)

    def test_1920_at_scale_1(self) -> None:
        """RF-003-10, RNF-003-01: nivel B en español con ≥ 150 px libres (BS §2.2: 257
        medidos); en inglés también cabe A (BS §3) y B deja ≥ 150 px."""
        self.assertIs(self.level(1920, 1.0, "es"), Level.B)
        self.assertGreaterEqual(self.free(Level.B, 1920, 1.0, "es"), 150)
        self.assertIs(self.level(1920, 1.0, "en"), Level.A)
        self.assertGreaterEqual(self.free(Level.B, 1920, 1.0, "en"), 150)
        self.assertGreaterEqual(self.free(Level.A, 1920, 1.0, "en"), self.k.margin)

    def test_1920_at_scale_1_25(self) -> None:
        """RF-003-10, RNF-003-01: nivel C a 1,25 con ≥ 24 px libres, en los dos idiomas
        (BS §2.2: 49 medidos en español)."""
        for language in ("es", "en"):
            with self.subTest(language=language):
                self.assertIs(self.level(1920, 1.25, language), Level.C)
                self.assertGreaterEqual(self.free(Level.C, 1920, 1.25, language), 24)

    def test_other_windows(self) -> None:
        """RF-003-10 (BS §3): A a 2200 px, C a 1600 px, D a 1366 px y a 1,5, E por debajo
        de unos 900 px; el último nivel si nada cabe."""
        self.assertIs(self.level(2200, 1.0, "es"), Level.A)
        self.assertIs(self.level(1600, 1.0, "es"), Level.C)
        self.assertIs(self.level(1366, 1.0, "es"), Level.D)
        self.assertIs(self.level(1920, 1.5, "es"), Level.D)
        for region in (899, 800, 500, 100):
            with self.subTest(region=region):
                self.assertIs(self.level(region, 1.0, "es"), Level.E)

    def test_forced_level(self) -> None:
        """RF-003-10: el nivel fijado en las preferencias se respeta aunque no quepa."""
        for level in Level:
            with self.subTest(level=level):
                self.assertIs(self.level(800, 1.0, "es", forced=level), level)

    def test_levels_get_narrower(self) -> None:
        """BS §3: cada nivel ocupa menos que el anterior (A > B > C > D > E)."""
        widths = [width.topbar_width(level, scale=1.0, titles_px=titles_px("es"), k=self.k)
                  for level in Level]
        self.assertEqual(widths, sorted(widths, reverse=True))
        self.assertAlmostEqual(width.topbar_width(Level.B, scale=1.25, titles_px=titles_px("es"),
                                                  k=self.k), widths[1] * 1.25)

    def test_menu_button_width(self) -> None:
        """RF-003-10 (BS §3, T18): el ancho explícito de un menú de texto es su título más
        el relleno del botón (``menu_pad`` sin el espacio entre botones) y, en el nivel A,
        el icono; con el espacio entre botones, suma lo que cuenta el modelo."""
        k = self.k
        self.assertAlmostEqual(width.menu_button_px(50.0, icon=False, k=k) + k.menu_gap,
                               50.0 + k.menu_pad)
        self.assertAlmostEqual(width.menu_button_px(50.0, icon=True, k=k)
                               - width.menu_button_px(50.0, icon=False, k=k), k.title_icon)


class QuickAccessFoldTest(unittest.TestCase):
    k = width.QuickAccessWidthConstants()

    @classmethod
    def setUpClass(cls) -> None:
        cls.items = catalog.load().quick_access("view")
        cls.groups = {item.key: item.group for item in cls.items}

    def fold(self, region: float, scale: float = 1.0, *, edit_mode: bool = False) -> object:
        available = width.quick_access_available_px(
            region_width_px=region, scale=scale, native_px=self.k.native_object_mode, k=self.k)
        return width.fold_view_quick_access(available_px=available, scale=scale,
                                            edit_mode=edit_mode, items=self.items, k=self.k)

    def test_full_row_at_1300(self) -> None:
        """RF-003-11 (AR §3.2): a 1300 px y 1,0 caben los 24 controles, en su orden, sin
        «»»; la fila mide unos 920 px con la regla del encargo."""
        result = self.fold(1300)
        self.assertEqual(result.step, 0)
        self.assertEqual(result.visible, tuple(item.key for item in self.items))
        self.assertFalse(result.more)
        self.assertLess(result.width_px, 1300 - self.k.native_object_mode)

    def test_scale_1_25_folds_step_1(self) -> None:
        """RF-003-11 (AR §3.2): a 1,25 no cabe entera (≈ −20 px) y pliega el paso 1: Banda y
        Objeto actual en solo icono."""
        result = self.fold(1300, 1.25)
        self.assertEqual(result.step, 1)
        self.assertEqual(result.compact, frozenset({"GEOBLENDER_PT_geo_band",
                                                    "GEOBLENDER_PT_ui_current_object"}))
        self.assertEqual(len(result.visible), 24)

    def test_two_views_side_by_side(self) -> None:
        """RF-003-11 (AR §3.3): a 650 px quedan Vista, Sección (con la banda en icono),
        Nueva polilínea y Encaje, más «»» (unos 375 px)."""
        result = self.fold(650)
        self.assertEqual(result.step, 5)
        self.assertEqual({self.groups[key] for key in result.visible}, {"view", "section", "draw"})
        self.assertEqual([key for key in result.visible if self.groups[key] == "draw"],
                         ["geoblender.ui_draw_polyline", "tool_settings.use_snap"])
        self.assertIn("GEOBLENDER_PT_geo_band", result.compact)
        self.assertTrue(result.more)
        self.assertAlmostEqual(result.width_px, 375, delta=30)

    def test_five_steps_in_order(self) -> None:
        """RF-003-11 (AR §3.3): al estrecharse, primero Banda y Objeto actual a icono; después
        a «»» Comando, Cálculo y control, Consulta y, por último, Plano de trabajo, Edición
        de polilíneas, Filtro de selección y Objeto actual; nunca Vista, Sección, Nueva
        polilínea ni Encaje."""
        folded_by_step: dict[int, set[str]] = {}
        previous_step = 0
        for region in range(1400, 0, -5):
            result = self.fold(region)
            self.assertGreaterEqual(result.step, previous_step)
            previous_step = result.step
            folded_by_step.setdefault(result.step, set(result.folded))
        self.assertEqual(sorted(folded_by_step), [0, 1, 2, 3, 4, 5])
        groups = {step: {self.groups[key] for key in keys} for step, keys in folded_by_step.items()}
        self.assertEqual(groups[0], set())
        self.assertEqual(groups[1], set())
        self.assertEqual(groups[2], {"command"})
        self.assertEqual(groups[3], {"command", "compute"})
        self.assertEqual(groups[4], {"command", "compute", "query"})
        self.assertEqual(folded_by_step[5] - folded_by_step[4],
                         {"GEOBLENDER_PT_ui_work_plane", "GEOBLENDER_PT_ui_current_object",
                          "GEOBLENDER_MT_gis_polyline_edit", "GEOBLENDER_PT_ui_selection_filter"})
        never = self.fold(0)
        self.assertEqual(never.step, 5)
        self.assertEqual(len(never.visible), 10)

    def test_edit_modes(self) -> None:
        """RF-003-11 (AR §3.3): en edición de malla y de curva solo Vista, Sección, Nueva
        polilínea, Encaje, Plano de trabajo y Objeto actual, más «»» con lo demás."""
        result = self.fold(1300, edit_mode=True)
        self.assertEqual(result.step, 0)
        self.assertEqual(len(result.visible), 12)
        self.assertTrue(all(item.edit_modes for item in self.items if item.key in result.visible))
        self.assertTrue(result.more)
        self.assertEqual(len(result.folded), 12)


if __name__ == "__main__":
    unittest.main()
