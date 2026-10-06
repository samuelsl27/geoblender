# SPDX-License-Identifier: GPL-3.0-or-later
"""Leyenda y Filtro de datos genéricos y sus proveedores (spec 003, T24; RF-003-09; plan
003 §5.3, contrato 6; BS §8.12, Consulta ▸; AR §3.1, n.º 26 y 27; spec §8).

- RF-003-09 (spec §8): sin proveedor para el tipo del objeto activo (o sin objeto activo),
  «Leyenda: colorear por campo…» y «Filtro de datos por expresión…» no se pueden ejecutar
  y su mensaje dice «Seleccione sondeos (005) o un modelo de bloques (R-22)»; sus ventanas
  emergentes (las del acceso rápido y de Mayús+Alt+L y Mayús+Alt+F) muestran ese texto,
  desactivado.
- Contrato 6: con un proveedor sintético registrado para un tipo (``Object.geoblender.kind``
  lo registra la 006; aquí, una propiedad sintética), la Leyenda muestra sus campos (el
  elegido, hundido) y aplica el que se elige; un campo que no es suyo no se aplica (error
  para el usuario). El Filtro de datos muestra la expresión vigente y los campos, y aplica
  la expresión; una expresión que el proveedor rechaza no cambia nada e informa su motivo
  como error.
- Contrato 6: quitar el proveedor deja otra vez los controles desactivados.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Sequence
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout, draw

KIND = "TEST_KIND"  # un tipo sintético (los de PC §1 llegan con la 006)
NO_PROVIDER = "Seleccione sondeos (005) o un modelo de bloques (R-22)"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class GBTEST_PG_object_kind(bpy.types.PropertyGroup):
    """``Object.geoblender`` sintético: solo el tipo (PC §1; lo registra la 006)."""

    kind: bpy.props.StringProperty(name="Kind")  # type: ignore[valid-type]


class SyntheticLegend:
    """Un proveedor de leyenda: dos campos y lo que se aplicó."""

    def __init__(self, context_module: ModuleType) -> None:
        self.field = context_module.Field
        self.applied: list[str] = []
        self.chosen = "lithology"

    def fields(self, context: object) -> Sequence[object]:
        return (self.field("lithology", "Litología"), self.field("grade", "Ley de Au"))

    def current(self, context: object) -> str:
        return self.chosen

    def apply(self, context: object, field: str) -> None:
        self.applied.append(field)
        self.chosen = field


class SyntheticFilter:
    """Un proveedor de filtro: rechaza lo que contiene «??»."""

    def __init__(self, context_module: ModuleType, errors: ModuleType) -> None:
        self.field = context_module.Field
        self.error = errors.ValidationError
        self.applied: list[str] = []

    def fields(self, context: object) -> Sequence[object]:
        return (self.field("au_ppm", "Au (ppm)"), self.field("depth", "Profundidad"))

    def current(self, context: object) -> str:
        return self.applied[-1] if self.applied else ""

    def apply(self, context: object, expression: str) -> None:
        if "??" in expression:
            raise self.error("test.bad_expression", "no se entiende la expresión",
                             obj="Filtro de datos", field="expresión", value=expression)
        self.applied.append(expression)


class ContextControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.context = _module("bl.ui.context")
        cls.errors = _module("core.errors")
        bpy.utils.register_class(GBTEST_PG_object_kind)
        bpy.types.Object.geoblender = bpy.props.PointerProperty(type=GBTEST_PG_object_kind)

    @classmethod
    def tearDownClass(cls) -> None:
        del bpy.types.Object.geoblender
        bpy.utils.unregister_class(GBTEST_PG_object_kind)
        blender_ext.load_file()
        blender_ext.unload()

    def setUp(self) -> None:
        mesh = bpy.data.meshes.new("Sintético")
        self.obj = bpy.data.objects.new("Sintético", mesh)
        bpy.context.scene.collection.objects.link(self.obj)
        bpy.context.view_layer.objects.active = self.obj
        self.addCleanup(bpy.data.objects.remove, self.obj)
        self.window = bpy.context.window_manager.windows[0]

    def with_provider(self) -> tuple[SyntheticLegend, SyntheticFilter]:
        legend = SyntheticLegend(self.context)
        data_filter = SyntheticFilter(self.context, self.errors)
        self.context.register_legend_provider(KIND, legend)
        self.context.register_data_filter_provider(KIND, data_filter)
        self.addCleanup(self.context.unregister_legend_provider, KIND)
        self.addCleanup(self.context.unregister_data_filter_provider, KIND)
        self.obj.geoblender.kind = KIND
        return legend, data_filter

    def panel(self, name: str) -> FakeLayout:
        ctx = SimpleNamespace(active_object=bpy.context.view_layer.objects.active,
                              object=bpy.context.view_layer.objects.active,
                              view_layer=bpy.context.view_layer, scene=bpy.context.scene,
                              workspace=SimpleNamespace(geoblender_mode=True), area=None)
        return draw(getattr(bpy.types, name), ctx)

    def test_without_provider(self) -> None:
        """RF-003-09 (spec §8): sin proveedor, y sin objeto activo, los dos comandos no se
        pueden ejecutar y lo dicen; sus ventanas muestran el texto desactivado."""
        for active in (self.obj, None):
            bpy.context.view_layer.objects.active = active
            with self.subTest(active=active), bpy.context.temp_override(window=self.window):
                for operator in (bpy.ops.geoblender.ui_edit_legend,
                                 bpy.ops.geoblender.ui_edit_data_filter):
                    self.assertFalse(operator.poll())
                    with self.assertRaisesRegex(RuntimeError, NO_PROVIDER.replace("(", r"\(")
                                                .replace(")", r"\)")):
                        operator()
            for name in ("GEOBLENDER_PT_ui_legend", "GEOBLENDER_PT_ui_data_filter"):
                labels = [item for item in self.panel(name).items if item.text]
                self.assertEqual([(item.text, item.enabled) for item in labels],
                                 [(NO_PROVIDER, False)], name)

    def test_legend_with_provider(self) -> None:
        """Contrato 6: la Leyenda muestra los campos del proveedor (el vigente, hundido) y
        aplica el elegido; uno que no es suyo no se aplica."""
        legend, _filter = self.with_provider()
        items = [item for item in self.panel("GEOBLENDER_PT_ui_legend").items
                 if item.kind == "operator"]
        self.assertEqual([(item.text, item.properties.field, item.options.get("depress"))
                          for item in items],
                         [("Litología", "lithology", True), ("Ley de Au", "grade", False)])
        with bpy.context.temp_override(window=self.window):
            self.assertTrue(bpy.ops.geoblender.ui_edit_legend.poll())
            self.assertEqual(bpy.ops.geoblender.ui_edit_legend(field="grade"), {"FINISHED"})
            # Un error para el usuario: invocado por script, Blender lo lanza.
            with self.assertRaisesRegex(RuntimeError, "«otro» no es del tipo activo"):
                bpy.ops.geoblender.ui_edit_legend(field="otro")
        self.assertEqual(legend.applied, ["grade"])

    def test_data_filter_with_provider(self) -> None:
        """Contrato 6: el Filtro de datos muestra los campos y aplica la expresión; una que
        el proveedor rechaza no se aplica."""
        _legend, data_filter = self.with_provider()
        texts = [item.text for item in self.panel("GEOBLENDER_PT_ui_data_filter").items]
        self.assertIn("Au (ppm)", texts)
        self.assertIn("Profundidad", texts)
        with bpy.context.temp_override(window=self.window):
            ok = bpy.ops.geoblender.ui_edit_data_filter(expression="au_ppm > 0.5")
            self.assertEqual(ok, {"FINISHED"})
            with self.assertRaisesRegex(RuntimeError, "«au_ppm \\?\\? 3»: no se entiende"):
                bpy.ops.geoblender.ui_edit_data_filter(expression="au_ppm ?? 3")
        self.assertEqual(data_filter.applied, ["au_ppm > 0.5"])
        texts = [item.text for item in self.panel("GEOBLENDER_PT_ui_data_filter").items]
        self.assertIn("au_ppm > 0.5", texts)

    def test_provider_removed(self) -> None:
        """Contrato 6: al quitar el proveedor, los controles vuelven a estar desactivados."""
        self.with_provider()
        self.context.unregister_legend_provider(KIND)
        with bpy.context.temp_override(window=self.window):
            self.assertFalse(bpy.ops.geoblender.ui_edit_legend.poll())
            self.assertTrue(bpy.ops.geoblender.ui_edit_data_filter.poll())


if __name__ == "__main__":
    unittest.main()
