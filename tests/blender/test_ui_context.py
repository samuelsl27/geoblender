# SPDX-License-Identifier: GPL-3.0-or-later
"""Leyenda y Filtro de datos genéricos y sus proveedores (spec 003, T24; RF-003-09; plan
003 §5.3, contrato 6; BS §8.12, Consulta ▸; AR §3.1, n.º 26 y 27; spec §8) y menú del tipo
activo en la fila 1, el clic derecho y Mayús+Alt+B (T26; RF-003-17; PC §1, §3 y §4).

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

- RF-003-17 (T26): con un objeto sintético de cada tipo de PC §3, la fila 1 muestra
  «Herramientas ▾», «<Tipo> ▾» (el menú de ``contexts.toml``), sus dos iconos y la
  chincheta; el clic derecho de la Vista 3D y del Outliner, «Geoblender · <Tipo> ▸» con el
  mismo menú, y Mayús+Alt+B abre ese mismo menú; la colección de una versión, en el clic
  derecho de las colecciones. Sin objeto activo, solo «Herramientas ▾» (y Mayús+Alt+B abre
  Herramientas); con varios tipos seleccionados, «Selección (n) ▾»; la chincheta mantiene
  el menú al cambiar la selección (y se suelta si su objeto desaparece); en modo Blender no
  se dibuja nada; si no cabe, primero se van la chincheta y los iconos y después
  Herramientas pasa a icono (PC §1); «Parámetros…» abre la barra lateral N.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Sequence
from types import ModuleType, SimpleNamespace
from typing import Any

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


class GBTEST_PG_collection_version(bpy.types.PropertyGroup):
    """``Collection.geoblender`` sintético: solo la versión (PC §1; lo registra R-07)."""

    version_id: bpy.props.StringProperty(name="Version")  # type: ignore[valid-type]


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
        blender_ext.release()
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
        blender_ext.release()

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


TOOLS = "GEOBLENDER_MT_ui_tools"
PIN = "geoblender.ui_toggle_context_pin"
SELECTION_MENU = "GEOBLENDER_MT_ui_context_selection"


class ContextMenuTest(unittest.TestCase):
    """RF-003-17 (T26): el menú del tipo activo en la fila 1, el clic derecho y
    Mayús+Alt+B."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.headers = _module("bl.ui.headers")
        cls.context = _module("bl.ui.context")
        cls.catalog = _module("bl.ui.commands").catalog()
        bpy.utils.register_class(GBTEST_PG_object_kind)
        bpy.utils.register_class(GBTEST_PG_collection_version)
        bpy.types.Object.geoblender = bpy.props.PointerProperty(type=GBTEST_PG_object_kind)
        bpy.types.Collection.geoblender = bpy.props.PointerProperty(
            type=GBTEST_PG_collection_version)

    @classmethod
    def tearDownClass(cls) -> None:
        del bpy.types.Collection.geoblender
        del bpy.types.Object.geoblender
        bpy.utils.unregister_class(GBTEST_PG_collection_version)
        bpy.utils.unregister_class(GBTEST_PG_object_kind)
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.window = bpy.context.window_manager.windows[0]
        self.area = next(area for area in self.window.screen.areas if area.type == "VIEW_3D")
        self.addCleanup(self.context.clear)

    def make(self, name: str, kind: str) -> bpy.types.Object:
        obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        bpy.context.scene.collection.objects.link(obj)
        obj.geoblender.kind = kind

        def remove() -> None:
            if name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[name])

        self.addCleanup(remove)
        return obj

    def ctx(self, active: Any, selected: Sequence[Any] = (), *, geoblender: bool = True,
            width: float = 1300.0) -> SimpleNamespace:
        return SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=geoblender),
                               area=self.area, region=SimpleNamespace(width=width),
                               active_object=active, selected_objects=list(selected),
                               view_layer=bpy.context.view_layer, scene=bpy.context.scene,
                               collection=None)

    def drawn(self, function: Any, ctx: SimpleNamespace) -> FakeLayout:
        layout = FakeLayout()
        function(SimpleNamespace(layout=layout), ctx)
        return layout

    def label(self, menu_id: str) -> str:
        return self.catalog.commands[menu_id].label_es

    def test_each_kind(self) -> None:
        """RF-003-17: el mismo menú del tipo en la fila 1 (con sus dos iconos y la
        chincheta), en el clic derecho y con Mayús+Alt+B."""
        kinds = [kind for kind in self.catalog.contexts if kind not in ("SELECTION", "VERSION")]
        self.assertEqual(len(kinds), 12)
        for kind in kinds:
            spec = self.catalog.contexts[kind]
            obj = self.make(f"Sintético {kind}", kind)
            ctx = self.ctx(obj, [obj])
            with self.subTest(kind=kind):
                row = self.drawn(self.headers.draw_row1, ctx)
                menus = row.of_kind("menu")
                self.assertEqual([(item.target, item.text) for item in menus[:2]],
                                 [(TOOLS, "Herramientas"), (spec.id, self.label(spec.id))])
                start = row.items.index(menus[1]) + 1
                pin = next(item for item in row.items if item.target == PIN)
                icons = row.items[start:row.items.index(pin)]
                self.assertEqual(len(icons), 2, icons)
                self.assertEqual((pin.icon, pin.options.get("depress")), ("UNPINNED", False))
                right = self.drawn(self.headers.draw_context_menu, ctx).of_kind("menu")
                self.assertEqual([(item.target, item.text) for item in right],
                                 [(spec.id, f"Geoblender · {self.label(spec.id)}")])
                self.assertEqual(self.headers.context_menu_id(ctx), spec.id)
        for name in ("VIEW3D_MT_object_context_menu", "VIEW3D_MT_edit_curve_context_menu",
                     "OUTLINER_MT_object"):
            functions = getattr(bpy.types, name).draw._draw_funcs
            self.assertEqual(functions.count(self.headers.draw_context_menu), 1, name)
        row1 = bpy.types.VIEW3D_MT_editor_menus.draw._draw_funcs
        self.assertEqual(row1.count(self.headers.draw_row1), 1)

    def test_version_collection(self) -> None:
        """RF-003-17, PC §3.13: «Geoblender · Versión ▸» en el clic derecho de la
        colección de una versión; en otra colección, nada."""
        collection = bpy.data.collections.new("V10 · Sintética")
        self.addCleanup(bpy.data.collections.remove, collection)
        ctx = self.ctx(None)
        ctx.collection = collection
        self.assertEqual(self.drawn(self.headers.draw_collection_menu, ctx).items, [])
        collection.geoblender.version_id = "V10"
        menus = self.drawn(self.headers.draw_collection_menu, ctx).of_kind("menu")
        spec = self.catalog.contexts["VERSION"]
        self.assertEqual([(item.target, item.text) for item in menus],
                         [(spec.id, f"Geoblender · {self.label(spec.id)}")])

    def test_without_active_object(self) -> None:
        """RF-003-17, PC §3.1: sin objeto activo, solo «Herramientas ▾»; el clic derecho no
        añade nada y Mayús+Alt+B abre Herramientas."""
        ctx = self.ctx(None)
        row = self.drawn(self.headers.draw_row1, ctx)
        self.assertEqual([(item.kind, item.target) for item in row.items], [("menu", TOOLS)])
        self.assertEqual(self.drawn(self.headers.draw_context_menu, ctx).items, [])
        self.assertEqual(self.headers.context_menu_id(ctx), TOOLS)

    def test_selection_of_several_kinds(self) -> None:
        """RF-003-17, PC §4: varios tipos seleccionados, «Selección (n) ▾»."""
        holes = self.make("Sondeos", "DRILLHOLES")
        solids = [self.make(f"Sólido {n}", "SOLID") for n in range(2)]
        ctx = self.ctx(solids[0], [holes, *solids])
        menus = self.drawn(self.headers.draw_row1, ctx).of_kind("menu")
        self.assertEqual([(item.target, item.text) for item in menus],
                         [(TOOLS, "Herramientas"), (SELECTION_MENU, "Selección (3)")])
        self.assertEqual(self.headers.context_menu_id(ctx), SELECTION_MENU)

    def test_pin(self) -> None:
        """RF-003-17, PC §1: la chincheta mantiene el menú al cambiar la selección; sin
        ella, vuelve el del objeto activo; si su objeto desaparece, se suelta."""
        holes = self.make("Sondeos", "DRILLHOLES")
        solid = self.make("Sólido", "SOLID")
        bpy.context.view_layer.objects.active = holes
        holes.select_set(True)
        with bpy.context.temp_override(window=self.window, area=self.area):
            self.assertEqual(bpy.ops.geoblender.ui_toggle_context_pin(), {"FINISHED"})
        ctx = self.ctx(solid, [solid])
        holes_menu = self.catalog.contexts["DRILLHOLES"].id
        solid_menu = self.catalog.contexts["SOLID"].id
        self.assertEqual(self.headers.context_menu_id(ctx), holes_menu)
        pin = next(item for item in self.drawn(self.headers.draw_row1, ctx).items
                   if item.target == PIN)
        self.assertEqual((pin.icon, pin.options.get("depress")), ("PINNED", True))
        with bpy.context.temp_override(window=self.window, area=self.area):
            bpy.ops.geoblender.ui_toggle_context_pin()
        self.assertEqual(self.headers.context_menu_id(ctx), solid_menu)
        with bpy.context.temp_override(window=self.window, area=self.area):
            bpy.ops.geoblender.ui_toggle_context_pin()
        self.assertEqual(self.headers.context_menu_id(ctx), holes_menu)
        bpy.data.objects.remove(holes)
        self.assertEqual(self.headers.context_menu_id(ctx), solid_menu)

    def test_nothing_in_blender_mode(self) -> None:
        """RF-003-17: en modo Blender ni la fila 1 ni el clic derecho dibujan nada."""
        obj = self.make("Sondeos", "DRILLHOLES")
        ctx = self.ctx(obj, [obj], geoblender=False)
        self.assertEqual(self.drawn(self.headers.draw_row1, ctx).items, [])
        self.assertEqual(self.drawn(self.headers.draw_context_menu, ctx).items, [])

    def test_fold(self) -> None:
        """PC §1: si no cabe, primero la chincheta y los iconos; después Herramientas en
        icono (el menú del tipo se queda)."""
        obj = self.make("Sondeos", "DRILLHOLES")
        spec_id = self.catalog.contexts["DRILLHOLES"].id
        narrow = self.drawn(self.headers.draw_row1, self.ctx(obj, [obj], width=1000.0))
        self.assertEqual([(item.target, item.text) for item in narrow.items],
                         [(TOOLS, "Herramientas"), (spec_id, "Sondeos")])
        narrower = self.drawn(self.headers.draw_row1, self.ctx(obj, [obj], width=800.0))
        self.assertEqual([(item.target, item.text) for item in narrower.items],
                         [(TOOLS, ""), (spec_id, "Sondeos")])

    def test_parameters_open_sidebar(self) -> None:
        """PC §3.11: «Parámetros…» abre la barra lateral N de la Vista 3D; sin tipo, no se
        puede y lo dice."""
        workspace = self.window.workspace
        workspace.geoblender_mode = True
        self.addCleanup(setattr, workspace, "geoblender_mode", False)
        space = self.area.spaces.active
        space.show_region_ui = False
        bpy.context.view_layer.objects.active = None
        region = next(region for region in self.area.regions if region.type == "WINDOW")
        with bpy.context.temp_override(window=self.window, area=self.area, region=region):
            self.assertFalse(bpy.ops.geoblender.ui_show_context_panel.poll())
            obj = self.make("Entidad", "DESIGN_ENTITY")
            bpy.context.view_layer.objects.active = obj
            self.assertEqual(bpy.ops.geoblender.ui_show_context_panel(), {"FINISHED"})
        self.assertTrue(space.show_region_ui)


if __name__ == "__main__":
    unittest.main()
