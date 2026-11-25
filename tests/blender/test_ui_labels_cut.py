# SPDX-License-Identifier: GPL-3.0-or-later
"""Ninguna etiqueta se corta con «…» (spec 019, T27; RF-019-21; UI-28; plan 019 A7, P-3).

``layout.label`` no parte el texto: lo corta con «…» al ancho de su zona (``docs/trampas.md`` §5). Aquí se mide cada etiqueta
de cada diálogo de órdenes, dibujado contra el *layout* falso con los valores por defecto de sus propiedades, con el
ayudante de ``bl/ui/labels.py`` (``label_px``: el ancho ``blf`` de la fuente de la interfaz más lo que añade la etiqueta,
con icono o sin él) frente al ancho que el diálogo deja a sus etiquetas (``dialog_width``), a las escalas efectivas 1,0,
1,25 y 1,5556 y en español y en inglés. Una etiqueta que no cabe a alguna escala está en ``tests/data/ui_baseline.toml``
(``[labels]``: «fichero::clase -> texto»): la prueba falla ante un incumplimiento nuevo y ante uno de la lista ya
corregido y no quitado; la lista solo baja y la vacía la spec 020.

**Lo que la medida no ve** (al H3): se mide el diálogo en su estado de partida, sin proyecto y con las listas vacías; una
etiqueta que comparte fila con un botón se queda con menos de todo el ancho (el *layout* falso no distingue filas de
columnas); y los paneles de las barras laterales, cuyo ancho depende de la región, se miden aquí solo con el ayudante
(control positivo), no uno por uno.

Se ejecuta con ``tools/run_blender_tests.py`` (sin pantalla).
"""

import importlib
import re
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.test_ui_dialogs import OVERRIDES, _defaults, _file_of, _has_draw, _width, find_dialogs
from tests.support import blender_ext
from tests.support.fake_layout import FakeLayout, operator_self
from tests.support.ui_strings import load_baseline

SCALES = (1.0, 1.25, 1.5556)
LANGUAGES = ("es", "en")
MAX_SHOWN = 60  # lo que se copia del texto a la lista base


def _module(name: str):
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


def cut_labels(layout: FakeLayout, width_px: float, label_px: Callable[..., float],
               scales: tuple[float, ...] = SCALES) -> list[str]:
    """Los textos de las etiquetas de ``layout`` que no caben en ``width_px`` (a escala 1,0) a alguna de ``scales``."""
    cut = []
    for item in layout.items:
        if item.kind != "label" or not item.text:
            continue
        with_icon = item.icon != "NONE"
        if any(label_px(item.text, icon=with_icon, scale=scale) > width_px for scale in scales):
            cut.append(item.text)
    return cut


def shorten(text: str) -> str:
    """El texto en una línea, sin rutas del equipo (varían de un PC a otro) y acortado, como clave de la lista base."""
    one_line = re.sub(r"[A-Za-z]:[\\/]\S*", "<ruta>", " ".join(text.split()))
    return one_line if len(one_line) <= MAX_SHOWN else one_line[:MAX_SHOWN] + "…"


def compare(found: list[str], baseline: list[str]) -> tuple[list[str], list[str]]:
    """(nuevos, ya corregidos)."""
    return sorted(set(found) - set(baseline)), sorted(set(baseline) - set(found))


class LabelCutModelTest(unittest.TestCase):
    """El control positivo y la comparación, con un *layout* falso."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.labels = _module("bl.ui.labels")

    def test_a_an_80_character_label_in_a_narrow_zone_is_cut(self) -> None:
        layout = FakeLayout()
        layout.label(text="Esta etiqueta es larga, de ochenta caracteres, y no cabe en una zona muy estrecha.")
        layout.label(text="Corta")
        narrow = self.labels.sidebar_width(SimpleNamespace(region=SimpleNamespace(width=300)))
        self.assertEqual(cut_labels(layout, narrow, self.labels.label_px),
                         ["Esta etiqueta es larga, de ochenta caracteres, y no cabe en una zona muy estrecha."])

    def test_b_the_same_text_split_by_the_helper_is_not_cut(self) -> None:
        text = "Esta etiqueta es larga, de ochenta caracteres, y no cabe en una zona muy estrecha."
        width = self.labels.dialog_width(300)
        for scale in SCALES:  # el ayudante parte a la escala efectiva de la interfaz, sea cual sea
            layout = FakeLayout()
            self.labels.draw_wrapped(layout, text, width, scale=scale)
            self.assertGreater(len(layout.items), 1)
            self.assertEqual(cut_labels(layout, width, self.labels.label_px, (scale,)), [])

    def test_c_the_icon_adds_width(self) -> None:
        text = "x" * 30
        without = self.labels.label_px(text)
        self.assertGreater(self.labels.label_px(text, icon=True), without)
        layout = FakeLayout()
        layout.label(text=text, icon="ERROR")
        edge = (without + self.labels.label_px(text, icon=True)) / 2
        self.assertEqual(cut_labels(layout, edge, self.labels.label_px), [text])

    def test_d_a_new_failure_and_a_fixed_one_still_listed_both_fail(self) -> None:
        self.assertEqual(compare(["a::A -> t", "b::B -> t"], ["a::A -> t"]), (["b::B -> t"], []))
        self.assertEqual(compare(["a::A -> t"], ["a::A -> t", "b::B -> t"]), ([], ["b::B -> t"]))


class DialogLabelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.labels = _module("bl.ui.labels")
        cls.i18n = _module("core.i18n")
        cls.dialogs = find_dialogs()

    def setUp(self) -> None:
        self.addCleanup(self.i18n.set_language, self.i18n.language())

    def _drawn(self, cls: type, module, text: str, scale: float = 1.0) -> FakeLayout | None:
        attributes = {**_defaults(cls), **OVERRIDES.get(cls.__name__, {})}
        fake = operator_self(cls, report=lambda kind, message: None,
                             properties=SimpleNamespace(is_property_set=lambda name: False),
                             bl_idname=cls.bl_idname, **attributes)
        if not _has_draw(cls):
            return None
        try:
            with mock.patch.object(self.labels.compat, "ui_scale", return_value=scale):
                cls.draw(fake, bpy.context)
        except Exception:  # noqa: BLE001  (sin proyecto, el dibujo de algunos diálogos no es posible)
            return None
        return fake.layout

    def findings(self) -> list[str]:
        found = []
        for language in LANGUAGES:
            self.i18n.set_language(language)
            for cls, module, text in self.dialogs:
                width = self.labels.dialog_width(_width(text, module))
                for scale in SCALES:  # a cada escala, el diálogo se dibuja (y parte sus textos) con ella
                    layout = self._drawn(cls, module, text, scale)
                    if layout is None:
                        break
                    for shown in cut_labels(layout, width, self.labels.label_px, (scale,)):
                        found.append(f"{_file_of(cls)}::{cls.__name__} -> {language}:{shorten(shown)}")
        return sorted(set(found))

    def test_a_dialogs_are_drawn_to_measure_their_labels(self) -> None:
        self.assertGreaterEqual(len(self.dialogs), 80)
        drawn = 0
        for cls, module, text in self.dialogs:
            layout = self._drawn(cls, module, text)
            if layout is not None and any(item.kind == "label" for item in layout.items):
                drawn += 1
        self.assertGreaterEqual(drawn, 10, "casi ningún diálogo dibujó etiquetas: la medida no ve nada")

    def test_b_no_new_cut_label_and_the_baseline_only_goes_down(self) -> None:
        """RF-019-21: una etiqueta nueva o cambiada que se corta falla; una de la lista que ya cabe, también."""
        new, fixed = compare(self.findings(), load_baseline("labels"))
        self.assertEqual(new, [], "etiqueta que no cabe a alguna de las tres escalas: pártala con labels.draw_wrapped (UI-28)")
        self.assertEqual(fixed, [], "ya cabe: quítela de [labels] de la lista base")

    def test_c_the_baseline_file_is_well_formed(self) -> None:
        entries = load_baseline("labels")
        self.assertEqual(entries, sorted(entries))
        self.assertEqual(len(entries), len(set(entries)))
        for entry in entries:
            self.assertRegex(entry, r"^bl/[\w/]+\.py::GEOBLENDER_OT_\w+ -> (es|en):.+$")


if __name__ == "__main__":
    unittest.main()
