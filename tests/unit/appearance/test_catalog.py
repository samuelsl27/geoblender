# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogo del aspecto: propiedades editables, predefinidos e inventario de los cargadores (spec 019,
T02; RF-019-07, RF-019-09; plan 019 §5.2, A1; D-5, D-11; UI-13).

Sin los módulos, ``ImportError``. Cada ``kind`` de ``bl/props/core.OBJECT_KINDS`` (leído con el árbol
sintáctico: ``bl`` no se importa fuera de Blender) tiene su lista de propiedades y su predefinido; un tipo
sin una propiedad no la lista; el predefinido de lo que ya pinta un cargador es **el valor actual** de ese
cargador (también leído con el árbol sintáctico, o importado cuando es de ``core``).
"""

from __future__ import annotations

import ast
import unittest

from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR as EXT

catalog = import_geoblender("core.appearance.catalog")
model = import_geoblender("core.appearance.model")
errors = import_geoblender("core.errors")
styles = import_geoblender("core.constraints.styles")
drill_model = import_geoblender("drillholes.model")
drill_view_data = import_geoblender("drillholes.view_data")


def _module_assign(rel: str, name: str) -> ast.expr:
    tree = ast.parse((EXT / rel).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            assert node.value is not None
            return node.value
    raise AssertionError(f"{rel}: no hay {name}")


def _object_kinds() -> list[str]:
    value = _module_assign("bl/props/core.py", "OBJECT_KINDS")
    assert isinstance(value, ast.List)
    return [ast.literal_eval(item.elts[0]) for item in value.elts if isinstance(item, ast.Tuple)]


def _hex(rgba: tuple[float, ...]) -> str:
    return "#" + "".join(f"{int(value * 255 + 0.5):02X}" for value in rgba[:3])


class CatalogTest(unittest.TestCase):
    def test_every_object_kind_has_an_entry(self) -> None:
        """RF-019-07: cada ``kind`` del objeto (menos ``NONE``) tiene sus propiedades y su predefinido."""
        kinds = [kind for kind in _object_kinds() if kind != "NONE"]
        self.assertGreater(len(kinds), 10)
        self.assertEqual(sorted(kinds), sorted(catalog.KINDS))
        for kind in kinds:
            props = catalog.allowed(kind)
            self.assertIn("label", props, kind)
            self.assertIn("visible", props, kind)
            defaults = catalog.defaults_for(kind)
            self.assertEqual(defaults.kind, kind)
            for prop in props:
                if prop != "label":  # el rótulo predefinido es el nombre del dato: no es una constante
                    self.assertIn(prop, defaults.props, f"{kind}.{prop}")
                    model.validate(kind, prop, defaults.get(prop))

    def test_a_kind_without_a_property_does_not_list_it(self) -> None:
        """UI-13, plan A1: lo que el tipo no tiene no se ofrece."""
        self.assertNotIn("line_width", catalog.allowed("DTM"))
        self.assertNotIn("point_size", catalog.allowed("TIN"))
        self.assertNotIn("transparency", catalog.allowed("CONTOURS"))
        self.assertNotIn("color", catalog.allowed("VOLUME_DIFFERENCE"))
        self.assertIn("transparency", catalog.allowed("DESIGN_ENTITY"))
        self.assertIn("line_width", catalog.allowed("CONSTRAINT"))
        self.assertIn("point_size", catalog.allowed("POINTS"))
        self.assertEqual(catalog.allowed("PROJECT_ANCHOR"), ("label", "visible"))
        for kind in catalog.KINDS:
            defaults = catalog.defaults_for(kind)
            self.assertEqual(set(defaults.props), set(catalog.allowed(kind)) - {"label"}, kind)
            self.assertTrue(set(catalog.allowed(kind)) <= set(catalog.PROPERTIES), kind)

    def test_unknown_kind_is_an_error(self) -> None:
        for call in (catalog.allowed, catalog.defaults_for):
            with self.assertRaises(errors.GeoblenderError) as caught:
                call("NOPE")
            self.assertIn("NOPE", str(caught.exception))

    def test_legend_driven_kinds(self) -> None:
        """D-8: donde manda una leyenda, el color lo dice ella."""
        self.assertTrue(catalog.legend_driven("DRILLHOLES"))
        self.assertTrue(catalog.legend_driven("VOLUME_DIFFERENCE"))
        self.assertTrue(catalog.legend_driven("COMPLIANCE_GRID"))
        self.assertFalse(catalog.legend_driven("DTM"))

    def test_palette_is_okabe_ito(self) -> None:
        """D-11: de seis a ocho colores de Okabe e Ito, todos distintos y en ``#RRGGBB``."""
        self.assertTrue(6 <= len(catalog.PALETTE) <= 8)
        self.assertEqual(len(set(catalog.PALETTE)), len(catalog.PALETTE))
        for color in ("#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7"):
            self.assertIn(color, catalog.PALETTE)

    def test_defaults_basics(self) -> None:
        self.assertEqual(catalog.defaults_for("DTM"), catalog.defaults_for("DTM"))
        self.assertEqual(catalog.defaults_for("DTM").get("transparency"), "0")
        self.assertEqual(catalog.defaults_for("DTM").get("visible"), "1")


class InventoryTest(unittest.TestCase):
    """El predefinido es el valor actual de cada cargador (RF-019-07: lo que hoy se ve no cambia)."""

    def test_inventory_names_every_loader(self) -> None:
        loaders = {item.loader for item in catalog.INVENTORY}
        for loader in ("entity_views.COLORS", "constraint_views.INTENTION_STYLE", "constraints.styles.COLORS",
                       "des_views.CLASS_LEGEND", "res_views._GRAY", "drillholes.model.DEFAULT_COLOR",
                       "drillholes.view_data.DEFAULT_RAMP"):
            self.assertIn(loader, loaders)

    def test_entity_colors(self) -> None:
        value = ast.literal_eval(_module_assign("bl/scene/entity_views.py", "COLORS"))
        other = ast.literal_eval(_module_assign("bl/scene/entity_views.py", "OTHER_COLOR"))
        self.assertEqual(set(value), set(catalog.ENTITY_SUBKINDS) - {"other"})
        for subkind, rgba in value.items():
            self.assertEqual(catalog.defaults_for("DESIGN_ENTITY", subkind).get("color"), _hex(rgba), subkind)
        self.assertEqual(catalog.defaults_for("DESIGN_ENTITY", "other").get("color"), _hex(other))
        self.assertEqual(catalog.defaults_for("DESIGN_ENTITY").get("color"), _hex(other))

    def test_intention_color(self) -> None:
        node = _module_assign("bl/scene/constraint_views.py", "INTENTION_STYLE")
        assert isinstance(node, ast.Call)
        rgba = ast.literal_eval(next(k.value for k in node.keywords if k.arg == "color"))
        self.assertEqual(catalog.defaults_for("CLIENT_INTENTION").get("color"), _hex(rgba))

    def test_constraint_colors(self) -> None:
        for ctype, (r, g, b) in styles.COLORS.items():
            expected = f"#{r:02X}{g:02X}{b:02X}"
            self.assertEqual(catalog.defaults_for("CONSTRAINT", str(ctype)).get("color"), expected, ctype)
        r, g, b = styles.ELSE_COLOR
        self.assertEqual(catalog.defaults_for("CONSTRAINT").get("color"), f"#{r:02X}{g:02X}{b:02X}")
        self.assertEqual(catalog.defaults_for("CONSTRAINT").get("line_width"), "2.5")

    def test_class_legends_and_gray(self) -> None:
        legend = _module_assign("bl/scene/des_views.py", "CLASS_LEGEND")
        assert isinstance(legend, ast.Tuple)
        colors = [_hex(ast.literal_eval(item.elts[1])) for item in legend.elts if isinstance(item, ast.Tuple)]
        self.assertEqual(list(catalog.CLASS_LEGEND_COLORS["des_views.CLASS_LEGEND"]), colors)
        gray = ast.literal_eval(_module_assign("bl/scene/res_views.py", "_GRAY"))
        self.assertEqual(catalog.CLASS_LEGEND_COLORS["res_views._GRAY"], (_hex(gray),))

    def test_drillholes(self) -> None:
        self.assertEqual(catalog.DRILLHOLE_NO_DATA_COLOR, drill_model.DEFAULT_COLOR)
        self.assertEqual(catalog.DRILLHOLE_RAMP, drill_view_data.DEFAULT_RAMP)

    def test_inventory_entries_are_well_formed(self) -> None:
        for item in catalog.INVENTORY:
            self.assertIn(item.kind, catalog.KINDS)
            self.assertTrue(item.what)


if __name__ == "__main__":
    unittest.main()
