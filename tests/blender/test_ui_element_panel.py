# SPDX-License-Identifier: GPL-3.0-or-later
"""La ficha y el panel «Elemento de Geoblender» en Propiedades ▸ Objeto (spec 019, T09; HU-019-1; RF-019-06,
RF-019-14; plan 019 §5.1, §5.5, P-1).

Con el proyecto sintético de ``tests/support/views_fixtures.py`` (una rejilla, un MDT importado y una rejilla derivada
de él). En ``blender -b`` no hay interfaz: el panel se dibuja con un *layout* simulado (``tests.support.fake_layout``) y
lo que haría ``bpy.msgbus`` al cambiar el objeto activo, llamando a la función suscrita. Se comprueba:

- la ficha de cada elemento (tipo, nombre, versión, estado, operación, cifras con su tipo, coordenadas como texto) en
  las cajas «Ficha» y «Procedencia»; sin procedencia, «Sin procedencia aún»;
- las coordenadas absolutas son **texto** (RF-019-14): ninguna propiedad de las filas de la ficha es de coma flotante;
- las líneas más de un módulo (la corta, la pista…) entran en la ficha;
- la barra N ya no repite la ficha: una línea y el botón que lleva a ella (UI-29);
- el panel va en Propiedades, pestaña Objeto, solo con un elemento del proyecto; dibujar no lee el proyecto.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import assert_fits, at_scales
from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.fake_layout import FakeLayout, draw
from tests.support.trees import temp_folder

ELEMENT = "GEOBLENDER_PT_ui_element"
SIDEBAR = "GEOBLENDER_PT_core_active_item"
SHOW_ELEMENT = "geoblender.ui_show_element"
SHOW_LINEAGE = "geoblender.core_show_lineage"
WIDE_PX = 5000.0
CARD_TITLE = "Ficha"
PROVENANCE_TITLE = "Procedencia"
NO_PROVENANCE = "Sin procedencia aún"
MDT = "MDT norte"
DERIVED = "Derivada"  # su etiqueta; el nombre generado del dato es otro
EXTRA = "Pendiente media: 12 %"


class ElementPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.panels = vf.extension("bl.ui.view_panels")
        self.labels = vf.extension("bl.ui.labels")
        self.ps = vf.extension("bl.scene.project_session")
        i18n = vf.extension("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")
        self.folder = temp_folder(self, "gb-t019-09-")
        self.addCleanup(blender_ext.load_file)
        self.data = vf.ViewsProject(self.folder, grids=1, param_readers=())
        self.addCleanup(self.data.close)
        self.addCleanup(self.ps.close)

    # --- Ayudas -------------------------------------------------------------------------------

    def activate(self, uid: str) -> bpy.types.Object:
        (obj,) = vf.objects_of(bpy.data, uid)
        self.activate_object(obj)
        return obj

    def activate_object(self, obj: bpy.types.Object) -> None:
        bpy.context.view_layer.objects.active = obj
        self.panels.on_active_changed()

    def drawn(self, panel: str = ELEMENT, *, width_px: float = WIDE_PX) -> FakeLayout:
        with mock.patch.object(self.labels, "sidebar_width", return_value=width_px):
            return draw(getattr(bpy.types, panel), bpy.context)

    def lines(self, panel: str = ELEMENT) -> list[str]:
        return [item.text for item in self.drawn(panel).of_kind("label")]

    def three(self) -> tuple[Any, Any, Any]:
        """La rejilla, el MDT importado y la rejilla derivada de él, cargados en la vista."""
        data = self.data
        mdt = data.import_grid(MDT)
        derived = data.derive(mdt.uid, DERIVED)
        data.attach()
        data.load(bpy.context, data.names[0], mdt.uid)
        return data.record(data.names[0]), mdt, derived

    # --- Pruebas ------------------------------------------------------------------------------

    def test_card_of_each_element_has_its_fields_in_two_boxes(self) -> None:
        """RF-019-06: de la rejilla y del MDT, la ficha lleva tipo, nombre, versión, estado, operación, posición y
        cifras (o «Sin cifras registradas»), la «Ficha» antes que la «Procedencia»; el MDT, con su entrada y su
        derivado en la procedencia."""
        grid, mdt, derived = self.three()
        for record in (grid, mdt):
            self.activate(record.uid)
            lines = self.lines()
            self.assertEqual(lines[0], CARD_TITLE)
            self.assertEqual(lines[1], record.name)
            for start in ("Tipo: ", "Estado: ", "Versión: ", "Operación: ", "Posición: ", "Cifras"):
                self.assertEqual(len([line for line in lines if line.startswith(start)]), 1, (start, lines))
            self.assertLess(lines.index(CARD_TITLE), lines.index(PROVENANCE_TITLE))
            self.assertLess(next(i for i, line in enumerate(lines) if line.startswith("Operación: ")),
                            lines.index(PROVENANCE_TITLE))
            self.assertIn("Estado: VIGENTE", lines)
            self.assertIn("Sin cifras registradas", lines)
        self.activate(mdt.uid)
        lines = self.lines()
        after = lines[lines.index(PROVENANCE_TITLE):]
        self.assertTrue(any(line.startswith(f"{MDT} · vigente") for line in after), after)
        self.assertTrue(any(line.startswith(derived.name) for line in after), after)
        self.assertNotIn(NO_PROVENANCE, lines)
        (button,) = [i for i in self.drawn().of_kind("operator") if i.target == SHOW_LINEAGE]
        self.assertEqual(button.properties.item_uid, mdt.uid)

    def test_new_element_says_no_provenance_yet(self) -> None:
        """Caso límite de RF-019-06: sin operación, entradas ni derivados, «Sin procedencia aún» (las filas de un
        dato recién creado, puestas a mano: el proyecto de la prueba no tiene ningún dato sin operación)."""
        grid, _mdt, _derived = self.three()
        self.activate(grid.uid)
        panels = self.panels
        line = panels.CardLine
        view = getattr(bpy.context.window_manager, vf.extension("bl.props.views").WINDOW_MANAGER_PROPERTY)
        panels._put_lines(view.card, [  # noqa: SLF001
            line(panels.ROW_NAME, grid.name), line(panels.ROW_FIELD, "Operación: —"),
            line(panels.ROW_HEADING, "↑ Entradas"), line(panels.ROW_NONE, "Ninguna entrada"),
            line(panels.ROW_HEADING, "↓ Derivados"), line(panels.ROW_NONE, "Ningún derivado")])
        lines = self.lines()
        self.assertEqual(lines.count(NO_PROVENANCE), 1)
        self.assertGreater(lines.index(NO_PROVENANCE), lines.index(PROVENANCE_TITLE))

    def test_coordinates_are_text_and_absolute(self) -> None:
        """RF-019-14: la posición es el centro de la extensión en coordenadas ABSOLUTAS (float64 más el GeoOrigin),
        escrita como texto; ninguna propiedad de las filas de la ficha ni del panel es de coma flotante."""
        grid, _mdt, _derived = self.three()
        obj = self.activate(grid.uid)
        origin = self.data.project.origin
        corners = [tuple(c) for c in obj.bound_box]
        centre = [(min(c[i] for c in corners) + max(c[i] for c in corners)) / 2.0 for i in range(3)]
        expected = vf.extension("core.i18n").format_xyz(
            centre[0] + origin.x0, centre[1] + origin.y0, centre[2] + origin.z0)
        shown = expected.replace("  ", " ")  # las etiquetas se parten por palabras
        self.assertIn(f"Posición: {shown}", self.lines())
        self.assertGreater(abs(origin.x0) + abs(origin.y0), 0)  # el origen cuenta
        view = getattr(bpy.context.window_manager, vf.extension("bl.props.views").WINDOW_MANAGER_PROPERTY)
        row_type = view.bl_rna.properties["card"].fixed_type
        floats = [p.identifier for p in row_type.properties if p.type == "FLOAT"]
        self.assertEqual(floats, [])
        self.assertEqual([i for i in self.drawn().items if i.kind == "prop"], [])

    def test_lines_of_the_module_enter_the_card(self) -> None:
        """RF-019-06: las líneas más de un módulo (una corta, una pista) salen en la ficha."""
        grid, _mdt, _derived = self.three()
        obj = vf.objects_of(bpy.data, grid.uid)[0]
        kind = str(obj.geoblender.kind)
        provider = mock.Mock(return_value=[self.panels.CardLine(self.panels.ROW_FIELD, EXTRA)])
        self.panels.register_object_lines(kind, provider)
        self.addCleanup(self.panels.unregister_object_lines, kind, provider)
        self.activate(grid.uid)
        self.assertIn(EXTRA, self.lines())

    def test_sidebar_no_longer_repeats_the_card(self) -> None:
        """UI-29: la barra N tiene una línea con el nombre y el botón que lleva a la ficha; nada de la ficha."""
        grid, _mdt, _derived = self.three()
        obj = self.activate(grid.uid)
        lines = self.lines(SIDEBAR)
        self.assertEqual(lines, [obj.name])
        (button,) = self.drawn(SIDEBAR).of_kind("operator")
        self.assertEqual((button.target, button.text), (SHOW_ELEMENT, "Mostrar la ficha del elemento"))

    def test_panel_is_in_properties_object_tab_only_for_elements(self) -> None:
        """P-1: Propiedades ▸ Objeto; solo con un proyecto abierto y un objeto que es la vista de un dato suyo."""
        grid, _mdt, _derived = self.three()
        panel = getattr(bpy.types, ELEMENT)
        self.assertEqual((panel.bl_space_type, panel.bl_region_type, panel.bl_context),
                         ("PROPERTIES", "WINDOW", "object"))
        self.assertEqual(panel.bl_label, "Elemento de Geoblender")
        self.activate(grid.uid)
        self.assertTrue(panel.poll(bpy.context))
        _work, (sketch, *_rest) = vf.user_objects(bpy.data, bpy.context.scene, count=1)
        self.activate_object(sketch)
        self.assertFalse(panel.poll(bpy.context))
        self.activate(grid.uid)
        self.ps.close()
        self.assertFalse(panel.poll(bpy.context))

    def test_drawing_does_not_read_the_project_and_fits(self) -> None:
        """RNF-019-01: dibujar no lee el proyecto; las etiquetas caben en el área a escala 1,0 y 1,25."""
        _grid, mdt, _derived = self.three()
        self.activate(mdt.uid)
        card = vf.extension("core.views.card")
        sidebar = self.labels.sidebar_width(bpy.context)
        with mock.patch.object(card, "item_card", wraps=card.item_card) as reads, \
                mock.patch.object(self.data.project, "read", wraps=self.data.project.read) as opens:
            for scale in at_scales():
                assert_fits(self, self.drawn(width_px=sidebar), sidebar, scale=scale)
        self.assertEqual((reads.call_count, opens.call_count), (0, 0))
        icons = bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items
        self.assertLessEqual({i.icon for i in self.drawn().items}, set(icons.keys()))


LOOK = "GEOBLENDER_PT_ui_element_look"
LOOK_MORE = "GEOBLENDER_PT_ui_element_look_more"
RESET = "geoblender.ui_appearance_reset"


class ElementLookPanelTest(ElementPanelTest):
    """Spec 019, T10 (HU-019-1; RF-019-07, RF-019-08, RF-019-09; plan 019 §5.5, P-2, P-4): el aspecto en el panel."""

    def setUp(self) -> None:
        super().setUp()
        self.appearance = vf.extension("bl.scene.appearance")
        self.addCleanup(self.appearance.discard)

    def surface(self) -> bpy.types.Object:
        """El objeto del MDT importado, activo, con su tipo de superficie (``DTM``)."""
        _grid, mdt, _derived = self.three()
        obj = self.activate(mdt.uid)
        obj.geoblender.kind = "DTM"
        return obj

    def props(self, panel: str) -> list[str]:
        return [item.target for item in self.drawn(panel).of_kind("prop")]

    # Heredadas de la T09: no se repiten
    test_card_of_each_element_has_its_fields_in_two_boxes = None  # type: ignore[assignment]
    test_new_element_says_no_provenance_yet = None  # type: ignore[assignment]
    test_coordinates_are_text_and_absolute = None  # type: ignore[assignment]
    test_lines_of_the_module_enter_the_card = None  # type: ignore[assignment]
    test_sidebar_no_longer_repeats_the_card = None  # type: ignore[assignment]
    test_panel_is_in_properties_object_tab_only_for_elements = None  # type: ignore[assignment]
    test_drawing_does_not_read_the_project_and_fits = None  # type: ignore[assignment]

    def test_frequent_up_front_and_the_rest_folded(self) -> None:
        """UI-02, UI-13: rótulo, color, transparencia y visibilidad arriba; el resto, en «Más aspecto», plegado y solo
        con lo que el tipo ofrece (una superficie: malla visible; unas curvas: grosor)."""
        obj = self.surface()
        self.assertEqual(self.props(LOOK), ["label", "color", "transparency", "visible"])
        self.assertEqual(self.props(LOOK_MORE), ["wire"])
        more = getattr(bpy.types, LOOK_MORE)
        self.assertEqual(more.bl_parent_id, LOOK)
        self.assertIn("DEFAULT_CLOSED", more.bl_options)
        obj.geoblender.kind = "CONTOURS"
        self.assertEqual(self.props(LOOK), ["label", "color", "visible"])
        self.assertEqual(self.props(LOOK_MORE), ["line_width"])
        obj.geoblender.kind = "POINTS"
        self.assertEqual(self.props(LOOK_MORE), ["point_size", "labels"])
        obj.geoblender.kind = "PROJECT_ANCHOR"
        self.assertEqual(self.props(LOOK), ["label", "visible"])
        self.assertFalse(getattr(bpy.types, LOOK_MORE).poll(bpy.context))

    def test_default_is_shown_as_such_and_reset_button_goes_back(self) -> None:
        """UI-03, UI-27, UI-30/31: «predefinido» junto al valor sin cambiar; con un cambio, ese texto no está y el botón
        vuelve a él (``ui_appearance_reset`` de esa propiedad), en texto y no solo en color."""
        obj = self.surface()
        drawn = self.drawn(LOOK)
        self.assertEqual(drawn.texts().count("predefinido"), 4)
        self.assertEqual([i for i in drawn.of_kind("operator") if i.target == RESET], [])
        obj.geoblender.look.transparency = 40
        drawn = self.drawn(LOOK)
        self.assertEqual(drawn.texts().count("predefinido"), 3)
        buttons = [i for i in drawn.of_kind("operator") if i.target == RESET]
        self.assertEqual([(b.properties.scope, getattr(b.properties, "prop", "")) for b in buttons],
                         [("PROPERTY", "transparency"), ("ELEMENT", "")])  # y, al final, el de todo el aspecto
        self.assertEqual(self.appearance.reset([obj], ["transparency"])[0], obj)
        self.assertEqual(self.drawn(LOOK).texts().count("predefinido"), 4)
        self.assertAlmostEqual(obj.color[3], 1.0, places=5)

    def test_color_and_transparency_are_seen_in_the_object(self) -> None:
        """RF-019-07, UI-10: color y transparencia de una superficie y de una corta cambian el objeto en el acto."""
        obj = self.surface()
        for kind in ("DTM", "DESIGN_ENTITY"):
            with self.subTest(kind=kind):
                obj.geoblender.kind = kind
                obj.geoblender.look.color = (1.0, 0.0, 0.0)
                obj.geoblender.look.transparency = 25
                self.assertEqual(tuple(round(c, 3) for c in obj.color), (1.0, 0.0, 0.0, 0.75))

    def test_label_changes_the_outliner_not_the_stable_name(self) -> None:
        """RF-019-07, P-2: el rótulo cambia el nombre del objeto (lo que ve el Outliner) por ``view_name`` y **no**
        ``gb_dataset.name``; vaciarlo vuelve al nombre generado."""
        obj = self.surface()
        uid, before = obj.geoblender.dataset_uid, obj.name
        with self.data.project.read() as conn:
            (stable,) = conn.execute("SELECT name FROM gb_dataset WHERE uid = ?", (uid,)).fetchone()
        obj.geoblender.look.label = "Fondo de la corta"
        self.assertIn("Fondo de la corta", obj.name)
        self.assertNotEqual(obj.name, before)
        with self.data.project.read() as conn:
            (name,) = conn.execute("SELECT name FROM gb_dataset WHERE uid = ?", (uid,)).fetchone()
        self.assertEqual(name, stable)
        self.assertEqual(obj.geoblender.dataset_uid, uid)
        self.appearance.reset([obj], ["label"])
        self.assertNotIn("Fondo de la corta", obj.name)
        self.assertEqual(obj.geoblender.look.label, "")

    def test_out_of_range_is_rejected_with_object_field_and_value(self) -> None:
        """RF-019-07, UI-09: un valor fuera de rango se rechaza diciendo objeto, campo y valor."""
        obj = self.surface()
        errors = vf.extension("core.errors")
        with self.assertRaises(errors.GeoblenderError) as caught:
            self.appearance.apply(obj, {"transparency": "150"})
        text = str(caught.exception)
        self.assertIn(obj.name, text)
        self.assertIn("150", text)

    def test_reset_says_what_it_restored(self) -> None:
        """RF-019-09: «Restablecer» dice qué ha restablecido y de qué elemento."""
        obj = self.surface()
        obj.geoblender.look.transparency = 40
        done = self.appearance.reset([obj], ["transparency"])
        self.assertEqual(self.appearance.reset_message(["transparency"], done),
                         f"Restablecido: Transparencia de «{obj.name}»")

    def test_look_panel_is_where_the_card_is(self) -> None:
        """P-1: el panel del aspecto va en Propiedades ▸ Objeto, con el mismo filtro que la ficha."""
        obj = self.surface()
        panel = getattr(bpy.types, LOOK)
        self.assertEqual((panel.bl_space_type, panel.bl_region_type, panel.bl_context),
                         ("PROPERTIES", "WINDOW", "object"))
        self.assertEqual(panel.bl_label, "Aspecto")
        self.assertTrue(panel.poll(bpy.context))
        self.ps.close()
        self.assertFalse(panel.poll(bpy.context))
        self.assertIsNotNone(obj)


if __name__ == "__main__":
    unittest.main()
