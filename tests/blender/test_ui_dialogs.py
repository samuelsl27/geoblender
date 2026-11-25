# SPDX-License-Identifier: GPL-3.0-or-later
"""Cada diálogo de órdenes cabe entero en la ventana (spec 019, T26; RF-019-20, CE-019-03; plan 019 A7, P-3; UI-01).

Se descubren los diálogos de ``bl/`` (las clases ``geoblender.*`` cuyo ``invoke`` abre ``invoke_props_dialog`` o
``invoke_popup``, también por una función auxiliar del módulo), se dibuja cada uno contra el *layout* falso con los valores
por defecto de sus propiedades y se mide con el modelo compartido (``tests/support/dialog_height.py``: 25 px por campo, 20
por etiqueta, 30 por botón, 10 por caja y 100 de título y botones) a las escalas efectivas 1,0, 1,25 y 1,5556 en una
ventana de 1920 × 1001. Lo que no cabe, o no se puede dibujar sin un proyecto, está en ``tests/data/ui_baseline.toml``
(``[dialogs]``: «fichero::clase -> height | width | unmeasured»): la prueba falla ante un incumplimiento nuevo y ante uno
de la lista que ya cumple; la lista solo baja y la vacía la spec 020.

**Lo que el modelo no ve** (al H3): se mide el diálogo en su estado de partida, sin proyecto abierto, con las listas vacías
(una capa, una superficie o un perfil más lo alargan: la medida es un mínimo); el ancho real de cada etiqueta; los cuadros
que se pliegan; y ``invoke_popup`` se mide con la misma tara que ``invoke_props_dialog``.

Se ejecuta con ``tools/run_blender_tests.py`` (sin pantalla: se dibuja en un diseño falso).
"""

import inspect
import re
import sys
import unittest
from collections import Counter
from types import ModuleType, SimpleNamespace
from typing import Any

import bpy

from tests.support import blender_ext
from tests.support import dialog_height as dh
from tests.support.fake_layout import FakeLayout, operator_self
from tests.support.repo import EXTENSION_DIR
from tests.support.ui_strings import load_baseline

MARKERS = ("invoke_props_dialog", "invoke_popup")
DEFAULT_WIDTH = 300  # el de ``invoke_props_dialog`` sin ``width``
BL_FOLDER = EXTENSION_DIR / "bl"
# Valores de partida que el diálogo necesita para poder dibujarse (un código sin rellenar no es válido).
OVERRIDES: dict[str, dict[str, Any]] = {
    "GEOBLENDER_OT_res_apply_swell": {"unit": "unit_1"},
}
CALL = re.compile(r"\.\s*invoke_(?:props_dialog|popup)\(")


def _rna(cls: type) -> Any:
    package, name = cls.bl_idname.split(".")
    return getattr(getattr(bpy.ops, package), name).get_rna_type()


def _defaults(cls: type) -> dict[str, Any]:
    """Los valores por defecto de las propiedades de la orden, como atributos de un ``self`` simulado."""
    values: dict[str, Any] = {}
    for prop in _rna(cls).properties:
        if prop.identifier == "rna_type":
            continue
        if prop.type == "ENUM":
            values[prop.identifier] = set(prop.default_flag) if prop.is_enum_flag else prop.default
        elif prop.type in ("COLLECTION", "POINTER"):
            values[prop.identifier] = []
        elif getattr(prop, "array_length", 0):
            values[prop.identifier] = tuple(prop.default_array)
        else:
            values[prop.identifier] = prop.default
    return values


def _source(function: Any) -> str:
    try:
        return inspect.getsource(function)
    except (OSError, TypeError):
        return ""


def _invoke_source(cls: type, module: ModuleType) -> str:
    """El código de ``invoke`` y el de las funciones del módulo y los métodos de la clase que nombra (un nivel)."""
    invoke = getattr(cls, "invoke", None)
    text = _source(invoke) if invoke is not None else ""
    for name in set(re.findall(r"\b(_?\w+)\(", text)):
        helper = getattr(module, name, None)
        if inspect.isfunction(helper):
            text += _source(helper)
    for name in set(re.findall(r"\bself\.(_?\w+)\(", text)):
        method = getattr(cls, name, None)
        if inspect.isfunction(method):
            text += _source(method)
    return text


def _width(text: str, module: ModuleType) -> float:
    match = re.search(r"width=([\w.]+)", text)
    if match is None:
        return float(DEFAULT_WIDTH)
    try:
        return float(eval(match.group(1), vars(module)))  # noqa: S307 (una constante del propio módulo)
    except Exception:  # noqa: BLE001
        return float(DEFAULT_WIDTH)


def _has_draw(cls: type) -> bool:
    return any("draw" in klass.__dict__ for klass in cls.__mro__[:-3])


def _file_of(cls: type) -> str:
    name = cls.__module__.split(".bl.", 1)[-1].replace(".", "/")
    return f"bl/{name}.py"


def find_dialogs() -> list[tuple[type, ModuleType, str]]:
    """(clase, módulo, código de ``invoke`` y sus auxiliares) de cada orden de Geoblender que abre un diálogo."""
    found = []
    for cls in bpy.types.Operator.__subclasses__():
        if not getattr(cls, "bl_idname", "").startswith("geoblender."):
            continue
        if not getattr(cls, "is_registered", False):  # las de un habilitar anterior, aún sin recolectar: usan el idioma de su módulo (T31)
            continue
        module = sys.modules[cls.__module__]
        text = _invoke_source(cls, module)
        if any(marker in text for marker in MARKERS):
            found.append((cls, module, text))
    return sorted(found, key=lambda entry: (_file_of(entry[0]), entry[0].__name__))


def measure(cls: type, module: ModuleType, text: str) -> tuple[str, int, float]:
    """(veredicto, altura a escala 1,0, ancho) de un diálogo dibujado con sus valores por defecto."""
    width = _width(text, module)
    attributes = {**_defaults(cls), **OVERRIDES.get(cls.__name__, {})}
    fake = operator_self(cls, report=lambda kind, message: None,
                         properties=SimpleNamespace(is_property_set=lambda name: False),
                         bl_idname=cls.bl_idname, **attributes)
    try:
        if _has_draw(cls):
            cls.draw(fake, bpy.context)
            tall = dh.height(fake.layout)
        else:  # Blender dibuja solo todas las propiedades visibles
            tall = dh.height_of_fields(sum(1 for prop in _rna(cls).properties
                                           if prop.identifier != "rna_type" and not prop.is_hidden))
    except Exception:  # noqa: BLE001  (sin proyecto, el dibujo de algunos diálogos no es posible)
        return "unmeasured", 0, width
    return dh.verdict(tall, width), tall, width


def findings(results: list[tuple[type, str, int, float]]) -> list[str]:
    """«fichero::clase -> veredicto» de cada diálogo que no cumple."""
    return sorted(f"{_file_of(cls)}::{cls.__name__} -> {verdict}" for cls, verdict, _h, _w in results if verdict != "fits")


def compare(found: list[str], baseline: list[str]) -> tuple[list[str], list[str]]:
    """(nuevos, ya corregidos): lo que incumple y no está en la lista base, y lo de la lista que ya no incumple."""
    return sorted(set(found) - set(baseline)), sorted(set(baseline) - set(found))


def per_file(entries: list[str]) -> Counter[str]:
    """El recuento de la lista base por fichero (para estimar la 020)."""
    return Counter(entry.split("::", 1)[0] for entry in entries)


def fake_dialog(fields: int, labels: int = 0) -> FakeLayout:
    layout = FakeLayout()
    data = SimpleNamespace(**{f"f{index}": 0 for index in range(fields)})
    for index in range(fields):
        layout.prop(data, f"f{index}", text=f"Campo {index}")
    for index in range(labels):
        layout.label(text=f"Etiqueta {index}")
    return layout


class DialogModelTest(unittest.TestCase):
    """El modelo y la comparación, con diálogos de mentira (control positivo)."""

    def test_a_a_dialog_of_40_fields_does_not_fit(self) -> None:
        shown = fake_dialog(40)
        self.assertEqual(dh.height(shown), 40 * 25 + 100)
        self.assertEqual(dh.verdict(dh.height(shown), 520), "height")
        self.assertEqual([item.scale for item in dh.misfits(dh.height(shown), 520)], [1.0, 1.25, 1.5556])

    def test_b_the_scale_matters_and_the_model_adds_every_piece(self) -> None:
        layout = FakeLayout()
        data = SimpleNamespace(a=1, b=2)
        layout.prop(data, "a")
        layout.prop_search(data, "b", data, "c")
        layout.label(text="x")
        layout.operator("geoblender.x", text="Ok")
        layout.box().label(text="y")
        self.assertEqual(dh.height(layout), 2 * 25 + 2 * 20 + 30 + 10 + 100)
        self.assertEqual(dh.verdict(700, 520), "height")  # cabe a 1,0 y no a 1,5556 (700 × 1,5556 > 1001)
        self.assertEqual([item.scale for item in dh.misfits(700, 520)], [1.5556])
        self.assertEqual(dh.verdict(600, 520), "fits")
        self.assertEqual(dh.verdict(100, 1300), "width")  # 1300 × 1,5556 > 1920

    def test_c_a_new_failure_and_a_fixed_one_still_listed_both_fail(self) -> None:
        self.assertEqual(compare(["a::A -> height", "b::B -> height"], ["a::A -> height"]), (["b::B -> height"], []))
        self.assertEqual(compare(["a::A -> height"], ["a::A -> height", "b::B -> height"]), ([], ["b::B -> height"]))
        self.assertEqual(compare(["a::A -> height"], ["a::A -> height"]), ([], []))


class DialogsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.dialogs = find_dialogs()
        cls.results = [(klass, *measure(klass, module, text)) for klass, module, text in cls.dialogs]

    def test_a_every_file_with_a_dialog_call_gives_dialogs(self) -> None:
        """El descubrimiento no pierde ningún fichero de ``bl/`` con una llamada a un diálogo."""
        wanted = set()
        for path in sorted(BL_FOLDER.glob("**/*.py")):
            code = [line for line in path.read_text(encoding="utf-8").splitlines() if CALL.search(line)
                    and not line.lstrip().startswith(("#", '"', "``"))]
            if [line for line in code if "return" in line or "manager." in line]:
                wanted.add(path.relative_to(EXTENSION_DIR).as_posix())
        found = {_file_of(klass) for klass, _module, _text in self.dialogs}
        self.assertEqual(sorted(wanted - found), [], "ficheros con una llamada a un diálogo sin ninguna clase descubierta")
        self.assertGreaterEqual(len(self.dialogs), 80)

    def test_a2_a_stale_class_of_an_earlier_enable_is_not_a_dialog(self) -> None:
        """Spec 019 T31 (la fuga de idioma de ``test_ui_labels_cut``): tras habilitar y deshabilitar la extensión varias veces en un Blender, las clases
        de antes siguen en ``bpy.types.Operator.__subclasses__()`` mientras el recolector no las libera; su ``draw`` usa el ``tr`` y el idioma de
        **su** módulo, no el que fija la prueba, y salían en español bajo «en:». Solo cuentan las registradas."""

        class StaleProbe(bpy.types.Operator):
            bl_idname = "geoblender.zz_stale_probe"
            bl_label = "Stale probe"

            def invoke(self, context: Any, event: Any) -> set[str]:
                return context.window_manager.invoke_props_dialog(self)

        self.assertFalse(StaleProbe.is_registered)
        self.assertIn(StaleProbe, bpy.types.Operator.__subclasses__())
        found = [klass for klass, _module, _text in find_dialogs()]
        self.assertNotIn(StaleProbe, found, "una clase sin registrar no es un diálogo")
        self.assertTrue(all(klass.is_registered for klass in found), "todos los diálogos descubiertos están registrados")

    def test_b_every_dialog_is_measured_at_the_three_scales(self) -> None:
        for klass, verdict, tall, width in self.results:
            with self.subTest(dialog=klass.__name__):
                self.assertIn(verdict, ("fits", "height", "width", "height+width", "unmeasured"))
                self.assertGreater(width, 0)
                if verdict != "unmeasured":
                    self.assertGreaterEqual(tall, dh.CHROME_PX)

    def test_c_no_new_failure_and_the_baseline_only_goes_down(self) -> None:
        """RF-019-20, CE-019-03: un diálogo nuevo o cambiado que se sale falla; uno de la lista que ya cumple, también."""
        new, fixed = compare(findings(self.results), load_baseline("dialogs"))
        self.assertEqual(new, [], "diálogo que no cabe a 1920 × 1001 a alguna de las tres escalas: pliéguelo o agrúpelo (UI-01)")
        self.assertEqual(fixed, [], "ya cabe: quítelo de [dialogs] de la lista base")

    def test_d_the_baseline_file_is_well_formed(self) -> None:
        entries = load_baseline("dialogs")
        self.assertEqual(entries, sorted(entries))
        self.assertEqual(len(entries), len(set(entries)))
        for entry in entries:
            self.assertRegex(entry, r"^bl/[\w/]+\.py::GEOBLENDER_OT_\w+ -> (height|width|height\+width|unmeasured)$")
        self.assertGreaterEqual(len(self.dialogs), len(entries))


if __name__ == "__main__":
    unittest.main()
