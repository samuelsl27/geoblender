# SPDX-License-Identifier: GPL-3.0-or-later
"""Línea de comandos F10 (spec 003, T32; RF-003-26; HU-003-7; AR §3.1, n.º 32; AT §2).

- RF-003-26: lo que lista la línea de comandos al escribir son los resultados de
  ``core.catalog.search.search`` en su orden, con la etiqueta en el idioma de Geoblender y
  dónde está en la barra; los no disponibles, marcados con su «Disponible en …».
- RF-003-26 (convergencia, T45; visto con interfaz en Blender 5.2.1): Blender no enseña
  ni busca el segundo elemento de cada sugerencia, y vuelve a filtrar la lista con su
  búsqueda difusa sobre el texto que se ve. Por eso el «Disponible en …» va en el texto,
  tras dónde está, y el término que coincidió (el nombre en el otro idioma, el alias, el
  término de otro programa o la entrada), tras la etiqueta y una raya («Nueva polilínea —
  ns») si no se ve ya: cada palabra de la consulta empieza una palabra suelta del texto.
  Con la consulta vacía, los comandos disponibles más frecuentes, en vez de una lista
  vacía; Ejecutar sin texto no ejecuta ninguno.
- RF-003-26: elegir un comando disponible (de la lista o con el texto escrito) lo ejecuta
  en la Vista 3D de destino: la que lanzó F10 o, desde la barra superior, la mayor.
- RF-003-26, RF-003-07: elegir uno no disponible informa «Disponible en …» y no cambia la
  escena, los datos ni el proyecto; un texto sin coincidencias, también lo dice.
- Contrato 2 del plan 003: su atajo (F10) está en la Vista 3D, así que en modo Blender sobre
  una Vista 3D su ``poll`` falla con la explicación y desde la barra superior pasa.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType

import bpy
from mathutils import Vector

from tests.support import blender_ext
from tests.support.blender_ext import module_name

VOLUME = "geoblender.res_compute_volume_between_surfaces"
PLAN = "geoblender.ui_set_view?view=PLAN"
SEPARATOR = "  ·  "


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


def view3d_area() -> bpy.types.Area:
    return max((a for a in window().screen.areas if a.type == "VIEW_3D"),
               key=lambda a: a.width * a.height)


def main_region(area: bpy.types.Area) -> bpy.types.Region:
    return next(region for region in area.regions if region.type == "WINDOW")


@contextmanager
def in_view() -> Iterator[None]:
    area = view3d_area()
    with bpy.context.temp_override(window=window(), area=area, region=main_region(area)):
        yield


@contextmanager
def from_topbar() -> Iterator[None]:
    with bpy.context.temp_override(window=window(), area=None, region=None):
        yield


def data_counts() -> dict[str, int]:
    """Cuántos datos de cada tipo hay en el fichero (para ver que nada cambia)."""
    names = ("objects", "meshes", "collections", "materials", "scenes", "workspaces",
             "texts", "images", "node_groups", "libraries")
    return {name: len(getattr(bpy.data, name)) for name in names}


class CommandLineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.command_line = _module("bl.ui.command_line")
        cls.commands = _module("bl.ui.commands")
        cls.search = _module("core.catalog.search")
        cls.i18n = _module("core.i18n")
        cls.cat = cls.commands.catalog()
        cls.workspace = window().workspace
        cls.was_marked = cls.workspace.geoblender_mode

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.workspace.geoblender_mode = True  # la ventana, en modo Geoblender
        self.addCleanup(setattr, self.workspace, "geoblender_mode", self.was_marked)
        self.addCleanup(self.i18n.set_language, "es")

    def test_suggestions_are_the_search_results(self) -> None:
        """RF-003-26: la lista es la de ``search()``, en su orden, con la etiqueta en
        español, dónde está y, en los no disponibles, su «Disponible en …» en el mismo
        texto (T45)."""
        for query in ("cubicar", "volume", "R-38", "planta", "ns"):
            with self.subTest(query=query):
                hits = self.search.search(self.cat, query, language="es",
                                          is_available=self.commands.is_available)
                shown = self.command_line.suggestions(query)
                self.assertEqual([self.command_line.resolve(text).key for text in shown],
                                 [hit.key for hit in hits])
                for text, hit in zip(shown, hits):
                    self.assertTrue(text.startswith(hit.label), text)
                    if hit.available:
                        self.assertNotIn("Disponible en", text)
                    else:
                        self.assertTrue(text.endswith(SEPARATOR + hit.unavailable_text), text)
        text = self.command_line.suggestions("cubicar")[0]
        self.assertEqual(self.command_line.resolve(text).key, VOLUME)
        self.assertEqual(text, "Cubicar entre dos superficies…  ·  Cubicación ▸ Cubicar  ·  "
                               "Disponible en R-38 · Cubicación entre superficies")

    def test_suggestions_follow_the_language(self) -> None:
        """RF-003-21, RF-003-26: en inglés, las etiquetas y el «Available in …» en inglés."""
        self.i18n.set_language("en")
        text = self.command_line.suggestions("volume")[0]
        self.assertEqual(self.command_line.resolve(text).key, VOLUME)
        self.assertTrue(text.startswith("Volume between two surfaces"), text)
        self.assertIn("Available in R-38 · ", text)

    def test_what_matched_is_seen(self) -> None:
        """RF-003-26 (T45): Blender 5.2 solo deja en la lista lo que su búsqueda difusa
        encuentra en el texto que se ve, y un término pegado a un paréntesis lo puntúa
        peor («(ns)» quedaba detrás de lo que solo contiene «ns»); aquí, una regla más
        estricta, con las palabras separadas solo por espacios: en cada resultado que
        coincidió palabra a palabra o por la entrada
        (``matched``), cada palabra de la consulta empieza una palabra de su texto,
        también si coincidió por el nombre en el otro idioma, un alias, un término de
        otro programa o la entrada; el término, tras la etiqueta y una raya, solo si no
        se ve ya. Lo que coincidió solo como subcadena o subsecuencia lo decide la
        búsqueda de Blender."""
        cases = (("es", "volume between"), ("es", "new project"), ("es", "ns"),
                 ("es", "evw"), ("es", "T3"), ("es", "R-38"), ("es", "005"),
                 ("es", "planta"), ("en", "cubicar"), ("en", "R-38"))
        for language, query in cases:
            self.i18n.set_language(language)
            with self.subTest(language=language, query=query):
                strong = {hit.key for hit in self.command_line.hits(query) if hit.matched}
                self.assertTrue(strong)
                words = query.lower().split()
                for text in self.command_line.suggestions(query):
                    if self.command_line.resolve(text).key not in strong:
                        continue
                    found = text.lower().split()
                    for word in words:
                        self.assertTrue(any(item.startswith(word) for item in found),
                                        f"«{word}» no está en «{text}»")
        self.i18n.set_language("es")
        new = self.command_line.suggestions("new project")[0]
        self.assertTrue(new.startswith("Nuevo proyecto… — New project…  ·  "), new)
        plain = self.command_line.suggestions("nuevo proyecto")[0]
        self.assertTrue(plain.startswith("Nuevo proyecto…  ·  "), plain)
        r38 = self.command_line.suggestions("R-38")[0]
        self.assertNotIn("— R-38", r38)  # ya lo dice su «Disponible en R-38 · …»

    def test_empty_query(self) -> None:
        """RF-003-26 (T45): con la consulta vacía, la lista no está vacía: los comandos
        disponibles más frecuentes (``search.frequent``), cada uno con dónde está; Ejecutar
        sin texto no ejecuta ninguno y lo dice."""
        shown = self.command_line.suggestions("")
        hits = self.search.frequent(self.cat, language="es",
                                    is_available=self.commands.is_available)
        self.assertGreaterEqual(len(shown), 10)
        self.assertEqual([self.command_line.resolve(text).key for text in shown],
                         [hit.key for hit in hits])
        self.assertTrue(all(self.commands.is_available(hit.key) for hit in hits))
        self.assertTrue(all(SEPARATOR in text for text in shown[:5]), shown[:5])
        outcome = self.command_line.choose("")
        self.assertIsNone(outcome.key)
        self.assertEqual(outcome.status, {"CANCELLED"})
        with in_view():
            self.assertEqual(bpy.ops.geoblender.ui_open_command_line(query=""), {"CANCELLED"})

    def test_available_command_runs_in_the_view(self) -> None:
        """RF-003-26: elegir «Planta» de la lista, desde la Vista 3D y desde la barra
        superior, pone en planta la Vista 3D de destino."""
        rv3d = view3d_area().spaces.active.region_3d
        text = next(text for text in self.command_line.suggestions("planta")
                    if self.command_line.resolve(text).key == PLAN)
        for launch in (in_view, from_topbar):
            with self.subTest(desde=launch.__name__):
                rv3d.view_perspective = "PERSP"
                rv3d.view_rotation = (1.0, 0.0, 0.0, 0.0)
                with launch():
                    self.assertTrue(bpy.ops.geoblender.ui_open_command_line.poll())
                    result = bpy.ops.geoblender.ui_open_command_line(query=text)
                self.assertEqual(result, {"FINISHED"})
                self.assertEqual(rv3d.view_perspective, "ORTHO")
                look = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
                self.assertLess((look - Vector((0.0, 0.0, -1.0))).length, 1e-6)

    def test_typed_text_runs_the_best_hit(self) -> None:
        """RF-003-26: sin elegir de la lista, se ejecuta el primer resultado."""
        outcome = self.command_line.choose("planta")
        self.assertEqual(outcome.key, PLAN)
        self.assertTrue(outcome.available)

    def test_unavailable_command_informs_and_changes_nothing(self) -> None:
        """RF-003-26, RF-003-07: «cubicar» informa «Disponible en R-38 · …» y no cambia
        nada; un texto sin coincidencias lo dice."""
        before = data_counts()
        scene = bpy.context.scene.name
        with in_view():
            outcome = self.command_line.run(bpy.context, "cubicar")
            result = bpy.ops.geoblender.ui_open_command_line(query="cubicar")
        self.assertEqual(result, {"CANCELLED"})
        self.assertEqual(outcome.status, {"CANCELLED"})
        self.assertEqual(outcome.key, VOLUME)
        self.assertEqual(outcome.level, "INFO")
        self.assertTrue(outcome.message.startswith("Disponible en R-38 · "), outcome.message)
        self.assertEqual(data_counts(), before)
        self.assertEqual(bpy.context.scene.name, scene)
        with in_view():
            nothing = self.command_line.run(bpy.context, "qqzzxxqq")
        self.assertEqual(nothing.status, {"CANCELLED"})
        self.assertIsNone(nothing.key)
        self.assertEqual(nothing.message, "Ningún comando coincide con «qqzzxxqq»")

    def test_mode_gate(self) -> None:
        """Contrato 2: en modo Blender, desde una Vista 3D, F10 queda para Blender (el
        ``poll`` falla); desde la barra superior, pasa."""
        self.workspace.geoblender_mode = False
        with in_view():
            self.assertFalse(bpy.ops.geoblender.ui_open_command_line.poll())
        with from_topbar():
            self.assertTrue(bpy.ops.geoblender.ui_open_command_line.poll())

    def test_real_operator_in_the_catalog(self) -> None:
        """Contrato 1: es el operador real (no un provisional) y lleva el ``msgid`` del
        catálogo; está disponible."""
        cls = self.commands.registered_class("geoblender.ui_open_command_line")
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertTrue(self.commands.is_available("geoblender.ui_open_command_line"))


if __name__ == "__main__":
    unittest.main()
