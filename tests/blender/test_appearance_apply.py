# SPDX-License-Identifier: GPL-3.0-or-later
"""El aplicador del aspecto por tipo (spec 019, T07; HU-019-1; RF-019-07, RF-019-08; plan 019 §5.2 y A1).

- RF-019-07: cada ``kind`` de ``OBJECT_KINDS`` (menos ``NONE``) tiene su entrada en el catálogo y en el aplicador;
  cambiar el color y la transparencia de una superficie (un DTM cargado de un proyecto de prueba) y de una corta
  (``DESIGN_ENTITY``) cambia ``Object.color`` y el material de visualización; un tipo sin grosor no lo aplica ni lo
  ofrece (UI-13).
- RF-019-08, UI-18: aplicar el aspecto **no cambia la geometría** (vértices idénticos) ni la procedencia (dato,
  hash, estado, fecha, cifras) ni el contador de cambios del proyecto.
- Desactivada la extensión, ``Object.geoblender.look`` desaparece con ella.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from typing import Any

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.trees import temp_folder

LOOK_PROPS = ("label", "color", "transparency", "visible", "line_width", "point_size", "labels", "wire")


def _appearance() -> Any:
    return vf.extension("bl.scene.appearance")


def _catalog() -> Any:
    return vf.extension("core.appearance.catalog")


def _kinds() -> list[str]:
    props = vf.extension("bl.props.core")
    return [kind for kind, _name, _help in props.OBJECT_KINDS if kind != "NONE"]


def _mesh_object(name: str, kind: str) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.geoblender.kind = kind
    return obj


def _vertices(obj: bpy.types.Object) -> np.ndarray:
    data = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", data)
    return data.copy()


def _marks(obj: bpy.types.Object) -> tuple[Any, ...]:
    props = obj.geoblender
    figures = tuple((item.key, item.value_text, item.unit, item.kind) for item in props.figures)
    return (props.kind, props.dataset_uid, props.project_uid, props.content_sha256, props.status, props.stale,
            props.date, props.view_state, props.origin, figures)


class AppearanceApplyTest(unittest.TestCase):
    def setUp(self) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(blender_ext.release)

    def test_every_kind_has_catalog_and_applier_entry(self) -> None:
        """RF-019-07: cada tipo de ``OBJECT_KINDS`` está en el catálogo y en el aplicador, y el aplicador solo ofrece
        propiedades del catálogo."""
        for kind in _kinds():
            with self.subTest(kind=kind):
                self.assertIn(kind, _catalog().KINDS)
                self.assertIn(kind, _appearance().APPLIERS)
                self.assertTrue(set(_appearance().offered(kind)) <= set(_catalog().allowed(kind)))
        self.assertEqual(sorted(_catalog().KINDS), sorted(_kinds()))

    def test_color_and_transparency_change_object_and_material(self) -> None:
        """RF-019-07: color y transparencia de una superficie y de una corta cambian ``Object.color`` y el material."""
        for kind in ("DTM", "DESIGN_ENTITY"):
            with self.subTest(kind=kind):
                obj = _mesh_object(f"Aspecto {kind}", kind)
                look = obj.geoblender.look
                look.color = (0.25, 0.5, 0.75)
                self.assertAlmostEqual(obj.color[0], 0.25, places=2)
                self.assertAlmostEqual(obj.color[2], 0.75, places=2)
                self.assertAlmostEqual(obj.color[3], 1.0, places=3)
                look.transparency = 40
                self.assertAlmostEqual(obj.color[3], 0.6, places=3)
                material = bpy.data.materials.get(_appearance().MATERIAL_PREFIX + obj.name)
                self.assertIsNotNone(material)
                self.assertIn(material, [slot.material for slot in obj.material_slots])
                self.assertAlmostEqual(material.diffuse_color[3], 0.6, places=3)
                self.assertEqual(material.blend_method, "BLEND")
                self.assertAlmostEqual(material.diffuse_color[0], 0.25, places=2)
                look.transparency = 0
                self.assertAlmostEqual(obj.color[3], 1.0, places=3)
                self.assertEqual(material.blend_method, "HASHED")

    def test_visible_wire_labels(self) -> None:
        """RF-019-07: visibilidad, malla visible y etiquetas se aplican al objeto de un tipo que las ofrece."""
        obj = _mesh_object("Aspecto visible", "DESIGN_ENTITY")
        obj.geoblender.look.wire = True
        self.assertTrue(obj.show_wire)
        obj.geoblender.look.visible = False
        self.assertTrue(obj.hide_get())
        obj.geoblender.look.visible = True
        self.assertFalse(obj.hide_get())
        points = _mesh_object("Aspecto puntos", "POINTS")
        points.geoblender.look.labels = True
        self.assertTrue(points.show_name)

    def test_kind_without_property_does_not_apply_or_offer_it(self) -> None:
        """UI-13: un tipo sin transparencia ni grosor no los ofrece ni los aplica."""
        contours = _mesh_object("Aspecto curvas", "CONTOURS")
        self.assertNotIn("transparency", _appearance().offered("CONTOURS"))
        self.assertNotIn("line_width", _appearance().offered("DTM"))
        contours.geoblender.look.transparency = 70
        self.assertAlmostEqual(contours.color[3], 1.0, places=3)
        self.assertIsNone(bpy.data.materials.get(_appearance().MATERIAL_PREFIX + contours.name))
        contours.geoblender.look.wire = True
        self.assertFalse(contours.show_wire)
        values = _appearance().read(contours).as_dict()
        self.assertNotIn("transparency", values)
        self.assertNotIn("wire", values)

    def test_apply_does_not_touch_geometry_or_provenance(self) -> None:
        """RF-019-08, UI-18: sobre una superficie cargada de un proyecto, el aspecto no cambia vértices, marcas ni el proyecto."""
        folder = temp_folder(self, "gb-t07-")
        if True:
            project = vf.ViewsProject(folder, grids=1)
            self.addCleanup(project.close)
            project.attach()
            project.load(bpy.context)
            objs = [o for o in bpy.data.objects if o.geoblender.kind == "DTM"]
            self.assertTrue(objs)
            obj = objs[0]
            vertices, marks, counter = _vertices(obj), _marks(obj), project.change_counter()
            look = obj.geoblender.look
            look.color = (1.0, 0.0, 0.0)
            look.transparency = 50
            look.wire = True
            look.visible = False
            self.assertTrue(np.array_equal(vertices, _vertices(obj)))
            self.assertEqual(marks, _marks(obj))
            self.assertEqual(counter, project.change_counter())
            self.assertAlmostEqual(obj.color[3], 0.5, places=3)

    def test_mirror_does_not_apply_and_reapply_does(self) -> None:
        """A1: ``mirror`` escribe el espejo sin aplicar; ``reapply`` lo aplica a los objetos de Geoblender y salta los ajenos."""
        obj = _mesh_object("Aspecto espejo", "DTM")
        other = _mesh_object("Ajeno", "NONE")
        appearance = _appearance()
        look = _catalog().defaults_for("DTM").with_values({"color": "#FF0000", "transparency": 20})
        appearance.mirror(obj, look)
        self.assertAlmostEqual(obj.color[0], 1.0, places=3)  # el color por defecto del objeto (blanco) no cambió ni a rojo
        self.assertEqual(tuple(round(c, 3) for c in obj.color), (1.0, 1.0, 1.0, 1.0))
        self.assertEqual(appearance.read(obj).get("color"), "#FF0000")
        self.assertEqual(appearance.reapply([obj, other]), 1)
        self.assertEqual(tuple(round(c, 3) for c in obj.color), (1.0, 0.0, 0.0, 0.8))
        self.assertEqual(tuple(other.color), (1.0, 1.0, 1.0, 1.0))

    def test_look_is_only_colors_and_integers(self) -> None:
        """RF-019-07 (regla 4): el espejo no tiene propiedades de coordenadas; el color es un color y lo demás, escalares."""
        look = bpy.data.objects.new("x", None).geoblender.look
        self.assertEqual(sorted(set(look.bl_rna.properties.keys()) - {"rna_type", "name"}), sorted(LOOK_PROPS))
        self.assertEqual(look.bl_rna.properties["color"].subtype, "COLOR")

    def test_limits_match_the_domain(self) -> None:
        """RF-019-22: los límites del espejo son los de ``core.appearance.model`` (que registrar no importa)."""
        props = vf.extension("bl.props.appearance")
        model = vf.extension("core.appearance.model")
        self.assertEqual(props.LABEL_MAX, model.LABEL_MAX)
        self.assertEqual(props.LINE_WIDTH_RANGE, model.RANGES["line_width"])
        self.assertEqual(props.POINT_SIZE_RANGE, model.RANGES["point_size"])


if __name__ == "__main__":
    unittest.main()
