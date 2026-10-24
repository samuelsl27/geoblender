# SPDX-License-Identifier: GPL-3.0-or-later
"""Búsqueda de la línea de comandos F10 en el catálogo (spec 003, T09; RF-003-26,
RNF-003-07; plan 003 §5.4, punto 10; HU-003-7).

- Encuentra un comando por su nombre en español o en inglés, su alias (también los de
  Datamine), un término de otro programa (RecMin) o su entrada (``R-51``, ``r51``,
  ``005``): «cubicar» y «volume» dan la cubicación entre superficies entre los 3 primeros,
  «R-51» y «r51», las reservas por fase y año, y «T3», el TIN desde puntos (en RecMin,
  T3).
- Tildes, mayúsculas y los signos de los menús («…», «▸») dan igual.
- Los comandos no disponibles salen también, marcados y con su «Disponible en …»; los
  auxiliares internos, no.
- ≤ 20 ms por consulta con el catálogo completo (≥ 350 comandos), con el Python de Blender.
"""

import time
import unittest
from unittest import mock

from tests.support.package import import_geoblender

catalog = import_geoblender("core.catalog")
search_mod = import_geoblender("core.catalog.search")

VOLUME = "geoblender.res_compute_volume_between_surfaces"
RESERVES = "geoblender.res_compute_reserves"  # R-51, aún provisional
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
        """RF-003-26, HU-003-7: «cubicar» y «volume» llevan a la cubicación entre
        superficies, «R-51» y «r51» a las reservas por fase y año y «T3» al TIN desde puntos,
        entre los 3 primeros, en los dos idiomas de la interfaz."""
        for language in ("es", "en"):
            for query, key in (("cubicar", VOLUME), ("volume", VOLUME), ("R-51", RESERVES),
                               ("r51", RESERVES)):
                with self.subTest(query=query, language=language):
                    self.assertIn(key, self.keys(query, language))
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
        reserves = [hit for hit in search_mod.search(self.cat, "reservas", language="es",
                                                     is_available=only_new_project)
                    if hit.key == RESERVES][0]
        self.assertFalse(reserves.available)
        self.assertEqual(reserves.unavailable_text, "Disponible en R-51 · Reservas")
        (english,) = search_mod.search(self.cat, "reserves by phase", language="en",
                                       is_available=only_new_project, limit=1)
        self.assertEqual((english.key, english.label),
                         (RESERVES, "Reserves by phase and year…"))
        self.assertEqual(english.unavailable_text, "Available in R-51 · Reserves")

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
        hits = search_mod.search(self.cat, "R-57", language="es", is_available=nothing_available)
        r57 = [hit for hit in hits if hit.entry == "R-57"]
        self.assertGreater(len(r57), 3)
        self.assertEqual([hit.frequency for hit in r57],
                         sorted((hit.frequency for hit in r57), reverse=True))

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

    def first(self, query: str, language: str = "es") -> object:
        return search_mod.search(self.cat, query, language=language,
                                 is_available=nothing_available, limit=1)[0]

    def test_matched_text(self) -> None:
        """RF-003-26 (convergencia, T45): cada resultado dice qué texto del catálogo dio
        su puntuación, como está escrito (la etiqueta en el idioma activo o en el otro,
        el alias, el término de otro programa o la entrada), si coincidió palabra a
        palabra o por la entrada; si solo como subcadena o subsecuencia, nada: Blender
        5.2 vuelve a filtrar la lista con el texto que se ve, y la línea de comandos lo
        enseña."""
        hit = self.first("nuevo proyecto")
        self.assertEqual((hit.field, hit.matched), ("label", "Nuevo proyecto…"))
        hit = self.first("new project")
        self.assertEqual((hit.field, hit.matched), ("label_other", "New project…"))
        hit = self.first("ns")
        self.assertEqual(hit.field, "alias")
        self.assertIn(hit.matched, self.cat.commands[hit.key].aliases)
        hit = self.first("T3")
        self.assertEqual(hit.field, "jargon")
        self.assertIn(hit.matched, [term for _program, term in self.cat.commands[hit.key].jargon])
        hit = self.first("r51")
        self.assertEqual((hit.field, hit.matched), ("entry", "R-51"))
        hits = search_mod.search(self.cat, "cubicar", language="en",
                                 is_available=nothing_available)
        volume = next(hit for hit in hits if hit.key == VOLUME)
        self.assertEqual((volume.field, volume.matched),
                         ("alias", "cubicar"))  # su alias en español
        weak = [hit for hit in hits if not hit.matched]
        self.assertTrue(weak)
        for hit in weak:
            command = self.cat.commands[hit.key]
            texts = (command.label, command.label_es, *command.aliases,
                     *(term for _program, term in command.jargon))
            best = max(search_mod.field_score("cubicar", search_mod.normalize(text))
                       for text in texts)
            self.assertLess(best, search_mod.WORD_MATCH, hit.key)

    def test_frequent_for_an_empty_query(self) -> None:
        """RF-003-26 (convergencia, T45): con la consulta vacía, la línea de comandos
        enseña los comandos disponibles más frecuentes (de ●●● a ●; a igual frecuencia,
        en el orden del catálogo), sin auxiliares internos ni los de frecuencia ○, como
        mucho ``limit``; los no disponibles, no."""
        def everything(_key: str) -> bool:
            return True

        hits = search_mod.frequent(self.cat, language="es", is_available=everything)
        self.assertEqual(len(hits), 30)
        commands = [self.cat.commands[hit.key] for hit in hits]
        order = [(-command.frequency, command.order) for command in commands]
        self.assertEqual(order, sorted(order))
        self.assertTrue(all(command.frequency >= 1 for command in commands))
        self.assertNotIn("internal", {command.kind for command in commands})
        self.assertTrue(all(hit.available and hit.label for hit in hits))
        best = max(command.frequency for command in self.cat.commands.values()
                   if command.kind in search_mod.SEARCHED_KINDS)
        self.assertEqual(commands[0].frequency, best)
        chosen = {hit.key for hit in hits[:3]}
        few = search_mod.frequent(self.cat, language="en", is_available=chosen.__contains__,
                                  limit=10)
        self.assertEqual([hit.key for hit in few], [hit.key for hit in hits[:3]])
        self.assertEqual(few[0].label, self.cat.commands[few[0].key].label)
        self.assertEqual(search_mod.frequent(self.cat, language="es",
                                             is_available=nothing_available), [])

    def test_path_text_reads_the_translations_once(self) -> None:
        """RNF-003-03 (spec 003, T46): la ruta de un comando no rehace la tabla de
        traducciones del catálogo en cada llamada (sin proyecto, el ``poll`` de Encuadrar
        la ventana de trabajo la pide en cada redibujo de la fila 2): la misma ruta de
        siempre en español y en inglés, con la tabla leída como mucho una vez."""
        key = "geoblender.core_set_work_window"
        table = self.cat.translations()
        msgids = self.cat.path(key)
        spanish = " ▸ ".join(table.get(msgid, msgid) for msgid in msgids)
        cls = type(self.cat)
        with mock.patch.object(cls, "translations", autospec=True,
                               side_effect=cls.translations) as spy:
            for _ in range(5):
                self.assertEqual(search_mod.path_text(self.cat, key, "es"), spanish)
                self.assertEqual(search_mod.path_text(self.cat, key, "en"), " ▸ ".join(msgids))
                self.assertEqual(search_mod.path_text(self.cat, key, "es", parent=True),
                                 " ▸ ".join(table.get(m, m) for m in msgids[:-1]))
        self.assertLessEqual(spy.call_count, 1)
        self.assertIn("▸", spanish)

    def _time(self, query: str) -> float:
        start = time.perf_counter()
        search_mod.search(self.cat, query, language="es", is_available=nothing_available)
        return time.perf_counter() - start


if __name__ == "__main__":
    unittest.main()
