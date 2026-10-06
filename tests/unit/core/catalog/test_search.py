# SPDX-License-Identifier: GPL-3.0-or-later
"""Búsqueda de la línea de comandos F10 en el catálogo (spec 003, T09; RF-003-26,
RNF-003-07; plan 003 §5.4, punto 10; HU-003-7).

- Encuentra un comando por su nombre en español o en inglés, su alias (también los de
  Datamine), un término de otro programa (RecMin) o su entrada (``R-38``, ``r38``,
  ``005``): «cubicar», «volume», «R-38» y «r38» dan la cubicación entre superficies entre
  los 3 primeros, y «T3», el TIN desde puntos (en RecMin, T3).
- Tildes, mayúsculas y los signos de los menús («…», «▸») dan igual.
- Los comandos no disponibles salen también, marcados y con su «Disponible en …»; los
  auxiliares internos, no.
- ≤ 20 ms por consulta con el catálogo completo (≥ 350 comandos), con el Python de Blender.
"""

import time
import unittest

from tests.support.package import import_geoblender

catalog = import_geoblender("core.catalog")
search_mod = import_geoblender("core.catalog.search")

VOLUME = "geoblender.res_compute_volume_between_surfaces"
TIN = "geoblender.gis_create_tin_from_points"


def nothing_available(_key: str) -> bool:
    return False


class SearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = catalog.load()

    def keys(self, query: str, language: str = "es", top: int = 3) -> list[str]:
        hits = search_mod.search(self.cat, query, language=language,
                                 is_available=nothing_available, limit=top)
        return [hit.key for hit in hits]

    def test_examples_of_the_task(self) -> None:
        """RF-003-26, HU-003-7: «cubicar», «volume», «R-38» y «r38» llevan a la cubicación
        entre superficies, y «T3» al TIN desde puntos, entre los 3 primeros, en los dos
        idiomas de la interfaz."""
        for language in ("es", "en"):
            for query in ("cubicar", "volume", "R-38", "r38"):
                with self.subTest(query=query, language=language):
                    self.assertIn(VOLUME, self.keys(query, language))
            with self.subTest(query="T3", language=language):
                self.assertIn(TIN, self.keys("T3", language))

    def test_both_languages_aliases_and_entries(self) -> None:
        """RF-003-26: el nombre en el otro idioma, los alias de Datamine (inv. 03 §10.5) y la
        entrada de una spec también encuentran el comando."""
        self.assertEqual(self.keys("Nuevo proyecto", "en", 1), ["geoblender.core_new_project"])
        self.assertEqual(self.keys("new project", "es", 1), ["geoblender.core_new_project"])
        self.assertEqual(self.keys("ns", "es", 1), ["geoblender.ui_draw_polyline"])
        self.assertEqual(self.keys("evw", "es", 1), ["geoblender.geo_compute_solid_volume"])
        top = search_mod.search(self.cat, "005", language="es", is_available=nothing_available)
        self.assertTrue(top)
        self.assertEqual({hit.entry for hit in top[:5]}, {"005"})

    def test_accents_case_and_menu_signs(self) -> None:
        """RF-003-26: tildes, mayúsculas y «…», «▸» no cuentan."""
        self.assertEqual(self.keys("CUBICACIÓN", top=5), self.keys("cubicacion", top=5))
        self.assertEqual(self.keys("Topografia", top=1), ["GEOBLENDER_MT_ui_topography"])
        self.assertEqual(self.keys("nuevo proyecto…", top=1), self.keys("NUEVO PROYECTO", top=1))
        self.assertEqual(search_mod.normalize("  Más fuentes ▸ ↗ … "), "mas fuentes")

    def test_unavailable_are_marked(self) -> None:
        """RF-003-07, RF-003-26: lo no disponible sale marcado con su «Disponible en …»
        en el idioma pedido; lo disponible, sin él."""
        def only_new_project(key: str) -> bool:
            return key == "geoblender.core_new_project"

        (new,) = search_mod.search(self.cat, "nuevo proyecto", language="es",
                                   is_available=only_new_project, limit=1)
        self.assertTrue(new.available)
        self.assertEqual(new.unavailable_text, "")
        self.assertEqual(new.label, "Nuevo proyecto…")
        volume = [hit for hit in search_mod.search(self.cat, "cubicar", language="es",
                                                   is_available=only_new_project)
                  if hit.key == VOLUME][0]
        self.assertFalse(volume.available)
        self.assertEqual(volume.unavailable_text,
                         "Disponible en R-38 · Cubicación entre superficies")
        (english,) = search_mod.search(self.cat, "volume between", language="en",
                                       is_available=only_new_project, limit=1)
        self.assertEqual((english.key, english.label), (VOLUME, "Volume between two surfaces…"))
        self.assertEqual(english.unavailable_text,
                         "Available in R-38 · Volumetrics between surfaces")

    def test_ranking_rules(self) -> None:
        """Plan 003 §5.4 (10): exacto > prefijo > prefijo de palabra > palabras > subcadena
        > subsecuencia; a igual puntuación, más frecuente y antes en el catálogo."""
        score = search_mod.field_score
        self.assertEqual(score("medir", "medir"), 100)
        self.assertEqual(score("med", "medir"), 80)
        self.assertEqual(score("tie", "lineas de enlace tie"), 60)
        self.assertEqual(score("vent tra", "ventana de trabajo"), 50)
        self.assertEqual(score("ntana", "ventana"), 40)
        self.assertAlmostEqual(score("vtn", "ventana"), 20 * 3 / 7)
        self.assertEqual(score("xyz", "ventana"), 0)
        hits = search_mod.search(self.cat, "R-38", language="es", is_available=nothing_available)
        r38 = [hit for hit in hits if hit.entry == "R-38"]
        self.assertGreater(len(r38), 3)
        self.assertEqual([hit.frequency for hit in r38],
                         sorted((hit.frequency for hit in r38), reverse=True))

    def test_scope_and_limit(self) -> None:
        """RF-003-26: sin auxiliares internos; como mucho ``limit`` resultados; una consulta
        vacía no da nada."""
        everything = search_mod.search(self.cat, "e", language="es",
                                       is_available=nothing_available, limit=1000)
        kinds = {self.cat.commands[hit.key].kind for hit in everything}
        self.assertNotIn("internal", kinds)
        self.assertEqual(len(search_mod.search(self.cat, "e", language="es",
                                               is_available=nothing_available)), 30)
        self.assertEqual(search_mod.search(self.cat, "  ", language="es",
                                           is_available=nothing_available), [])

    def test_speed(self) -> None:
        """RNF-003-07: ≤ 20 ms por consulta con el catálogo completo (≥ 350 comandos); la
        mejor de tres de cada consulta, con el índice ya construido."""
        self.assertGreaterEqual(len(self.cat.commands), 350)
        queries = ("c", "cu", "cubicar", "volume", "R-38", "r38", "T3", "ns", "nueva seccion",
                   "mirando al norte", "exportar dxf", "zzzz", "ventana de trabajo y rejilla",
                   "a", "005", "ortofoto", "planos del plan de labores", "importar sondeos")
        search_mod.search(self.cat, "warm", language="es", is_available=nothing_available)
        worst = 0.0
        for query in queries:
            best = min(self._time(query) for _ in range(3))
            worst = max(worst, best)
        self.assertLessEqual(worst * 1000, 20.0, f"{worst * 1000:.1f} ms")

    def _time(self, query: str) -> float:
        start = time.perf_counter()
        search_mod.search(self.cat, query, language="es", is_available=nothing_available)
        return time.perf_counter() - start


if __name__ == "__main__":
    unittest.main()
