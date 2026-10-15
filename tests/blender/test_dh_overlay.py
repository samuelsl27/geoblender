# SPDX-License-Identifier: GPL-3.0-or-later
"""Las etiquetas, las leyendas y las marcas de los sondeos en la vista, su representación y la
Leyenda genérica (spec 005, T30; HU-005-5; RF-005-17, RF-005-23, RF-005-24, RF-005-25; plan 005
§5.3.1, §5.5 y §5.6.8; principio 8).

Sin proyecto ni trabajos (el presupuesto de ``tools/check.py``; lo que deja la carga de un
proyecto lo mira ``test_dh_view``): tres sondeos con el modelo de la extensión, A-1 vertical,
B-1 con dos estaciones a la misma profundidad (DH-E06, alcance S: sin traza) y C-1 inclinado
con dos tramos de litología solapados (DH-E10, alcance T: su litología no se pinta); su vista,
calculada en el proceso con ``drillholes.view_data`` como el trabajo ``dh_view_arrays``, y lo
que ``bl.scene.dh_view.build_overlay`` deja a la superposición, con el informe guardado de su
validación (las filas de ``dh_validation_issue``) y C-1 de traza obsoleta.

- RF-005-25, RF-005-23, RF-005-24 (plan §5.5): lo que dibuja la superposición
  (``bl.draw.dh_overlay.screen_items``, en píxeles de la región con la matriz de la vista):
  en la boca de cada sondeo su etiqueta «A-1 (100,00 m)» (con «la profundidad en el fondo»,
  también la del fondo; sin etiquetas, ninguna) y abajo a la izquierda la leyenda de la
  litología del esquema y la de las clases del elemento con su «< LD», con sus colores.
- RF-005-17, RF-005-22 (plan §5.6.8): un aspa roja con su código en la boca de B-1, el código
  de C-1 en rojo sin aspa y «Traza obsoleta» en la de C-1; nada en A-1.
- Principio 8: habilitar pone el manejador ``POST_PIXEL`` y la Leyenda genérica de los
  sondeos; quitarlos y ponerlos otra vez es idempotente.
- Plan §5.3.1 y §5.5: ``geoblender.dh_show_display`` abre la barra lateral en la pestaña
  «Sondeos» (sin proyecto, no se puede); la Leyenda genérica de la 003 con unos sondeos activos
  ofrece «Litología (esquema)» y cada elemento de ley y los aplica a la representación; el
  radio cambia en vivo los tubos; las clases propias parten de la leyenda de la vista; cambiar
  la representación con la vista cargada pone en la cola una sola recarga, que no carga nada
  si la vista ya es la de la representación.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name

X0, Y0, Z0 = 700_000.0, 4_400_000.0, 800.0  # el GeoOrigin de la prueba
SIZE = (400, 300)  # la región, en píxeles
HALF = 50.0  # la vista: 100 m de ancho centrados en A-1, desde arriba
STALE = ("C-1",)


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _top_view(centre: tuple[float, float]) -> np.ndarray:
    """La matriz de una vista desde arriba (ortográfica) de 2·:data:`HALF` m de ancho y el
    alto de la región, centrada en ``centre`` (locales)."""
    width, height = SIZE
    sx, sy = 1.0 / HALF, width / (height * HALF)
    return np.array([[sx, 0.0, 0.0, -centre[0] * sx],
                     [0.0, sy, 0.0, -centre[1] * sy],
                     [0.0, 0.0, -0.001, 0.0],
                     [0.0, 0.0, 0.0, 1.0]])


def _pixel(matrix: np.ndarray, local: tuple[float, float, float]) -> tuple[float, float]:
    clip = matrix @ np.array([*local, 1.0])
    return ((clip[0] / clip[3] + 1.0) / 2.0 * SIZE[0], (clip[1] / clip[3] + 1.0) / 2.0 * SIZE[1])


class DrillholeOverlayTest(unittest.TestCase):
    """Con la extensión habilitada una vez (sin importarla otra vez)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.model = _module("drillholes.model")
        cls.validate = _module("drillholes.validate")
        cls.view_data = _module("drillholes.view_data")
        cls.dh_view = _module("bl.scene.dh_view")
        cls.overlay_mod = _module("bl.draw.dh_overlay")
        cls.dh_ops = _module("bl.ops.dh")
        cls.props = _module("bl.props.dh")
        cls.session = _module("bl.scene.project_session")
        cls.ui_context = _module("bl.ui.context")
        cls.georef = _module("core.georef")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.display = getattr(bpy.context.scene, self.props.SCENE_PROPERTY)
        self.display.grade_classes.clear()
        self.display.element = "Au"
        self.display.log_set = "lithology"
        self.display.show_labels = True
        self.display.labels_at_end = False
        self.display.show_legend = True
        self.addCleanup(self.dh_ops.INCORPORATIONS.drop)

    # --- Ayudas -----------------------------------------------------------------------------

    def drillholes(self) -> Any:
        """Los tres sondeos (véase el módulo), en EPSG:25830 + 5782."""
        m = self.model
        catalog = self.georef.load_catalog()
        collars = [m.Collar("A-1", X0, Y0, Z0, 100.0), m.Collar("B-1", X0 + 20.0, Y0, Z0, 80.0),
                   m.Collar("C-1", X0, Y0 + 20.0, Z0, 60.0)]
        surveys = [m.SurveyStation("A-1", 0.0, 0.0, -90.0),
                   m.SurveyStation("B-1", 0.0, 0.0, -90.0),
                   m.SurveyStation("B-1", 0.0, 10.0, -80.0),
                   m.SurveyStation("C-1", 0.0, 90.0, -60.0)]
        lithology = [m.LithologyInterval("A-1", 0.0, 40.0, "SUE"),
                     m.LithologyInterval("A-1", 40.0, 100.0, "MIN"),
                     m.LithologyInterval("C-1", 0.0, 30.0, "SUE"),
                     m.LithologyInterval("C-1", 20.0, 60.0, "MIN")]
        assays = [m.AssayValue("A-1", 40.0, 50.0, "Au", 0.5, "g/t"),
                  m.AssayValue("A-1", 50.0, 60.0, "Au", 2.5, "g/t")]
        catalogs = m.Catalogs(
            lithology=(m.LithologyCode("SUE", description="Suelo", color="#8B6B3D"),
                       m.LithologyCode("MIN", description="Mineral", color="#C0392B")),
            elements=(m.Element("Au", "g/t"), m.Element("Cu", "%"), m.Element("Tex", "text")))
        return m.DrillholeSet.from_records(
            crs=catalog.horizontal(25830), vertical=catalog.vertical(5782), collars=collars,
            surveys=surveys, lithology=lithology, assays=assays, catalogs=catalogs)

    def overlay(self, *, at_end: bool = True) -> tuple[Any, Any, Any]:
        """El conjunto, su vista (como ``dh_view_arrays``) y lo que deja a la superposición."""
        params = _module("drillholes.params")
        dset = self.drillholes()
        tolerance = params.default(params.DEPTH_TOLERANCE)
        thresholds = self.validate.ValidationParams(
            **{key.rpartition(".")[2]: params.default(key) for key in params.VALIDATION_KEYS})
        report = self.validate.validate(dset, thresholds)
        columns = _module("drillholes.schema").LAYOUTS["dh_validation_issue"].insert_columns
        records = [dict(zip(columns, row, strict=True))
                   for row in _module("drillholes.jobs").issue_rows(report)]
        excluded = self.validate.stored_exclusions(records, len(dset.collars))
        holes = self.validate.hole_exclusions(dset, depth_tolerance_m=tolerance)
        exclusions = self.validate.Exclusions(holes, excluded.tables, excluded.records)
        traces = _module("drillholes.desurvey").desurvey(dset, holes=~holes)
        vd = self.view_data
        step = params.default(params.TRACE_STEP)
        legend = vd.default_grade_legend(vd.grade_values(dset, "Au", "g/t", excluded=exclusions),
                                         "g/t")
        view = _module("drillholes.jobs").ViewArrays(
            vd.lithology_curves(dset, traces, "lithology", step, excluded=exclusions),
            vd.lithology_legend(dset, "lithology"),
            vd.grade_bars(dset, traces, "Au", legend, 1.0, 0.5, excluded=exclusions), legend,
            tuple(vd.labels(dset, traces, at_end)))
        origin = self.georef.GeoOrigin(int(X0), int(Y0), int(Z0))
        found = self.dh_view.build_overlay(
            dset, view, origin=origin, stale=STALE, records=records, depth_tolerance_m=tolerance,
            log_set="lithology", element="Au", display_key=self.dh_view.display_key(self.display))
        return dset, view, found

    def tubes(self, name: str = "Sondeos de prueba") -> Any:
        """Un objeto de tubos de sondeos (tipo ``DRILLHOLES``) enlazado y activo."""
        curves = bpy.data.hair_curves.new(name)
        obj = bpy.data.objects.new(name, curves)
        bpy.context.scene.collection.objects.link(obj)
        obj.geoblender.kind = "DRILLHOLES"
        obj.geoblender.project_uid = "proyecto-t30"
        _module("bl.gn.drill_tubes").add_tubes(obj, 0.5)
        bpy.context.view_layer.objects.active = obj

        def remove() -> None:
            bpy.data.objects.remove(obj)
            bpy.data.hair_curves.remove(curves)

        self.addCleanup(remove)
        return obj

    # --- Pruebas ----------------------------------------------------------------------------

    def test_labels_legends_and_marks(self) -> None:
        """RF-005-25, RF-005-23, RF-005-24, RF-005-17, RF-005-22 (plan §5.5 y §5.6.8): las
        etiquetas en la boca de cada sondeo (y en el fondo, si se pide), la leyenda de la
        litología y la de las clases del oro abajo a la izquierda, el aspa roja con su código
        en la boca del sondeo sin traza, el código de alcance T sin aspa y «Traza obsoleta», en
        píxeles de la región; sin etiquetas ni leyenda, solo las marcas. Pintarlo da cada texto
        con ``blf``."""
        ov = self.overlay_mod
        dset, view, found = self.overlay()
        local = self.georef.world_to_local(
            np.column_stack((dset.collars.x, dset.collars.y, dset.collars.z)),
            self.georef.GeoOrigin(int(X0), int(Y0), int(Z0)))
        self.assertEqual([(label.text, label.bottom) for label in found.labels],
                         [("A-1 (100,00 m)", False), ("100,00 m", True), ("B-1 (80,00 m)", False),
                          ("C-1 (60,00 m)", False), ("60,00 m", True)])
        self.assertEqual(found.labels[0].xyz, tuple(local[0].tolist()))
        self.assertEqual([(mark.hole, mark.kind, mark.codes) for mark in found.marks],
                         [("B-1", ov.EXCLUDED, ("DH-E06",)), ("C-1", ov.PARTIAL, ("DH-E10",)),
                          ("C-1", ov.STALE, ())])
        self.assertEqual(found.marks[0].xyz, tuple(local[1].tolist()))
        self.assertEqual((found.lithology, found.grade, found.element),
                         (view.lithology_legend, view.grade_legend, "Au"))
        self.assertEqual(found.log_sets, ("lithology",))
        self.assertEqual(found.elements, (("Au", "g/t"), ("Cu", "%")))

        rows = ov.legend_rows(found, self.display)
        self.assertEqual([row.text for row in rows],
                         ["Litología (lithology)", "MIN · Mineral", "SUE · Suelo", "Sin dato",
                          "Au (g/t)", *(entry.label for entry in view.grade_legend.entries())])
        self.assertEqual(rows[1].color, "#C0392B")  # por su orden y su código
        self.assertIsNone(rows[0].color)
        self.assertEqual(rows[-1].text, "< LD")

        matrix = _top_view((0.0, 0.0))
        items = ov.screen_items([found], self.display, matrix, SIZE, measure=lambda t: 7.0 * len(t))
        texts = {item.text: item for item in items if isinstance(item, ov.Text)}
        for name, k in (("A-1 (100,00 m)", 0), ("B-1 (80,00 m)", 1), ("C-1 (60,00 m)", 2)):
            x, y = _pixel(matrix, tuple(local[k].tolist()))
            np.testing.assert_allclose((texts[name].x, texts[name].y),
                                       (x + ov.LABEL_OFFSET[0], y + ov.LABEL_OFFSET[1]))
            self.assertEqual(texts[name].color, ov.LABEL_COLOR)
        self.assertNotIn("100,00 m", texts)  # sin «la profundidad en el fondo»
        x, y = _pixel(matrix, tuple(local[1].tolist()))
        (cross,) = [item for item in items if isinstance(item, ov.Lines)]
        size = ov.MARK_PX
        self.assertEqual(cross.color, ov.EXCLUDED_COLOR)
        np.testing.assert_allclose(cross.points, [[x - size, y - size], [x + size, y + size],
                                                  [x - size, y + size], [x + size, y - size]])
        self.assertEqual(texts["DH-E06"].color, ov.EXCLUDED_COLOR)
        self.assertEqual(texts["DH-E10"].color, ov.EXCLUDED_COLOR)
        self.assertEqual(texts["Traza obsoleta"].color, ov.STALE_COLOR)
        boxes = [item for item in items if isinstance(item, ov.Box)]
        panel = boxes[0]  # el fondo, abajo a la izquierda, y después los colores
        self.assertEqual((panel.x0, panel.y0, panel.color),
                         (ov.MARGIN_PX - ov.PAD_PX, ov.MARGIN_PX - ov.PAD_PX, ov.PANEL))
        self.assertEqual([box.color[:3] for box in boxes[1:]],
                         [tuple(int(row.color[i:i + 2], 16) / 255 for i in (1, 3, 5))
                          for row in rows if row.color is not None])
        legend = [item for item in items if isinstance(item, ov.Text)
                  and item.x <= ov.MARGIN_PX + ov.SWATCH_PX + ov.GAP_PX]
        self.assertEqual([item.text for item in legend], [row.text for row in rows])
        heights = [item.y for item in legend]
        self.assertEqual(heights, sorted(heights, reverse=True))  # de arriba abajo
        self.assertLess(heights[0], panel.y1)

        self.display.labels_at_end = True
        shown = {item.text: item for item in ov.screen_items([found], self.display, matrix, SIZE,
                                                             measure=len)
                 if isinstance(item, ov.Text)}
        x, y = _pixel(matrix, found.labels[1].xyz)  # el fondo de A-1, vertical: bajo su boca
        np.testing.assert_allclose((shown["100,00 m"].x, shown["100,00 m"].y),
                                   (x + ov.BOTTOM_OFFSET[0], y + ov.BOTTOM_OFFSET[1]))
        self.display.show_labels = False
        self.display.show_legend = False
        marks_only = ov.screen_items([found], self.display, matrix, SIZE, measure=len)
        self.assertEqual(sorted(item.text for item in marks_only if isinstance(item, ov.Text)),
                         ["DH-E06", "DH-E10", "Traza obsoleta"])

        with mock.patch.object(ov, "blf") as blf, mock.patch.object(ov, "gpu"), \
                mock.patch.object(ov, "batch_for_shader"):
            ov.paint(items, SIZE)
        self.assertEqual([call.args[1] for call in blf.draw.call_args_list],
                         [item.text for item in items if isinstance(item, ov.Text)])

    def test_handler_and_legend_provider_registered(self) -> None:
        """Principio 8 (plan §5.5): habilitada, la superposición dibuja en cada Vista 3D
        (``POST_PIXEL``) y los sondeos tienen su Leyenda genérica; quitar y poner la
        superposición es idempotente."""
        ov = self.overlay_mod
        self.assertTrue(ov.drawing())
        self.assertIs(self.ui_context.kind_legend_provider("DRILLHOLES"),
                      self.dh_ops.LEGEND_PROVIDER)
        self.addCleanup(ov.register)
        for _ in range(2):
            ov.unregister()
            self.assertFalse(ov.drawing())
        ov.register()
        handle = ov._handle
        ov.register()
        self.assertIs(ov._handle, handle)
        self.assertTrue(ov.drawing())

    def test_show_display_legend_radius_and_reload(self) -> None:
        """Plan §5.3.1 y §5.5 (RF-005-23, RF-005-24): sin proyecto, «Representación…» no se
        puede y lo dice; con él, abre la barra lateral de la Vista 3D. Con unos sondeos
        activos, la Leyenda genérica ofrece «Litología (lithology)» y cada elemento de ley y
        los aplica a la representación; el radio cambia en vivo sus tubos; las clases propias
        parten de la leyenda de la vista. Con la vista cargada, cambiar la representación pone
        en la cola una sola recarga, que no carga nada si la vista ya es la de la
        representación."""
        ops = self.dh_ops
        self.assertFalse(bpy.ops.geoblender.dh_show_display.poll())
        window = bpy.context.window_manager.windows[0]
        area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
        area.spaces.active.show_region_ui = False
        project = SimpleNamespace(uid="proyecto-t30")
        with mock.patch.object(self.session, "current", lambda: project):
            region = next(item for item in area.regions if item.type == "WINDOW")
            with bpy.context.temp_override(window=window, area=area, region=region):
                self.assertEqual(bpy.ops.geoblender.dh_show_display(), {"FINISHED"})
        self.assertTrue(area.spaces.active.show_region_ui)

        obj = self.tubes()
        _dset, view, found = self.overlay()
        self.dh_view.remember([obj], found)
        self.assertIs(self.dh_view.overlay_of(obj), found)
        provider = self.ui_context.legend_provider(bpy.context)
        self.assertIs(provider, ops.LEGEND_PROVIDER)
        self.assertEqual([(field.id, field.label) for field in provider.fields(bpy.context)],
                         [("log_set:lithology", "Litología (lithology)"),
                          ("element:Au", "Au (g/t)"), ("element:Cu", "Cu (%)")])
        self.assertEqual(provider.current(bpy.context), "element:Au")
        self.assertEqual(bpy.ops.geoblender.ui_edit_legend(field="element:Cu"), {"FINISHED"})
        self.assertEqual(self.display.element, "Cu")
        provider.apply(bpy.context, "log_set:lithology")
        self.assertEqual((self.display.log_set, self.display.element), ("lithology", ""))
        self.assertEqual(provider.current(bpy.context), "log_set:lithology")

        self.display.tube_radius = 1.25
        self.assertEqual(_module("bl.gn.drill_tubes").tube_radius(obj), 1.25)
        self.display.element = "Au"
        self.display.own_classes = True
        legend = view.grade_legend
        self.assertEqual([(item.lower, self.dh_view._hex(item.color))
                          for item in self.display.grade_classes],
                         [("", legend.colors[0]),
                          *((np.format_float_positional(value, unique=True, trim="-")
                             .replace(".", ","), color)
                            for value, color in zip(legend.breaks, legend.colors[1:]))])
        self.assertEqual(self.dh_view.grade_legend(self.display, "Au", "g/t"), legend)
        self.display.own_classes = False
        self.assertEqual(len(self.display.grade_classes), 0)

        # La vista cargada: una sola recarga en la cola, que no carga si ya está al día.
        self.assertEqual(ops.pending_incorporations(), [])
        with mock.patch.object(self.session, "current", lambda: project):
            self.display.element = "Cu"
            self.display.bar_width = 3.0
            self.assertEqual(ops.pending_incorporations(), [ops.VIEW_QUEUE])
            self.dh_view.remember([obj], self.overlay()[2])  # ya con la representación de ahora
            views = _module("bl.scene.views")
            with mock.patch.object(views, "load_steps", side_effect=AssertionError("recarga")):
                while ops.incorporation_tick() is not None:
                    pass
        self.assertEqual(ops.pending_incorporations(), [])


if __name__ == "__main__":
    unittest.main()
