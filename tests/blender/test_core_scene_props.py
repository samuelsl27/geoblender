# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades de la escena y preferencias de la extensión (spec 002, T22; plan 002 §5.2).

- RF-002-28: la georreferencia del proyecto vive en ``Scene.geoblender``
  (``GEOBLENDER_PG_core_project``): identidad, nombre, ruta relativa, CRS horizontal y
  vertical y GeoOrigin en **enteros** (``IntProperty``, ADR-0005), que sobreviven a
  guardar y recargar el ``.blend``; un valor fuera de 32 bits (2³¹) se rechaza.
- RF-002-10: el umbral del cerrojo caducado es una preferencia de la extensión
  (``core.lock_stale_minutes``, de 10 a 1 440 min, 30 por defecto) en la **única**
  ``GeoblenderPreferences``, enlazada con ``bl.ADDON_PACKAGE`` (PLT-02).
- Desactivar Geoblender quita ``Scene.geoblender`` y sus clases (principio 8).

Se ejecuta con ``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

# El GeoOrigin de Silvestre con una Z0 negativa (plan 002 §5.2 [V]).
ORIGIN = (736_200, 4_435_300, -180)
INT32_LIMIT = 2**31


class CoreScenePropsTestCase(unittest.TestCase):
    """Cada prueba parte de la extensión deshabilitada y de la escena de fábrica."""

    def setUp(self) -> None:
        blender_ext.release()
        blender_ext.load_file()  # la escena de fábrica, sin restos de otra prueba
        self.tmp = Path(tempfile.mkdtemp(prefix="geoblender-t22-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # Al terminar, primero se deshabilita (cierra el proyecto) y después la escena de
        # fábrica, ya sin manejadores que la sincronicen.
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(blender_ext.release)

    def bl(self) -> object:
        return sys.modules[module_name() + ".bl"]

    def scene_property(self) -> str:
        """El nombre de la propiedad de la escena (``geoblender``), del propio módulo."""
        return sys.modules[module_name() + ".bl.props.core"].SCENE_PROPERTY


class ScenePropsTest(CoreScenePropsTestCase):
    def test_geoorigin_survives_save_and_reload(self) -> None:
        """RF-002-28: (736 200; 4 435 300; −180), el uid, el nombre, la ruta relativa y
        los EPSG de la escena sobreviven a guardar y recargar el ``.blend``, como
        enteros."""
        blender_ext.enable()
        props = bpy.context.scene.geoblender
        props.project_uid = "00000000-0000-4000-8000-000000000022"
        props.project_name = "Cantera Prueba"
        props.project_path = "//../"
        props.crs_epsg = 25830
        props.vcrs_epsg = 5782
        props.origin_x, props.origin_y, props.origin_z = ORIGIN
        target = self.tmp / "vista.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(target))
        blender_ext.load_file()
        self.assertEqual(bpy.context.scene.geoblender.origin_x, 0)
        blender_ext.load_file(target)
        props = bpy.context.scene.geoblender
        self.assertEqual((props.origin_x, props.origin_y, props.origin_z), ORIGIN)
        for value in (props.origin_x, props.origin_y, props.origin_z):
            self.assertIs(type(value), int)
        self.assertEqual(props.project_uid, "00000000-0000-4000-8000-000000000022")
        self.assertEqual(props.project_name, "Cantera Prueba")
        self.assertEqual(props.project_path, "//../")
        self.assertEqual((props.crs_epsg, props.vcrs_epsg), (25830, 5782))

    def test_out_of_int32_rejected(self) -> None:
        """RF-002-28: un origen de 2³¹ (o menor que −2³¹) no cabe en un ``IntProperty`` de
        32 bits: se rechaza y el valor anterior no cambia."""
        blender_ext.enable()
        props = bpy.context.scene.geoblender
        props.origin_x, props.origin_y, props.origin_z = ORIGIN
        for name, value in (
            ("origin_x", INT32_LIMIT),
            ("origin_y", INT32_LIMIT),
            ("origin_z", -INT32_LIMIT - 1),
        ):
            with self.subTest(propiedad=name, valor=value):
                before = getattr(props, name)
                with self.assertRaises((ValueError, OverflowError, TypeError)):
                    setattr(props, name, value)
                self.assertEqual(getattr(props, name), before)

    def test_georeference_properties_are_integers(self) -> None:
        """RF-002-28 (ADR-0005): el GeoOrigin y los EPSG son ``IntProperty`` sin límites
        que recorten un valor en silencio; ``view_stale`` es booleana; ninguna propiedad
        del grupo es flotante (float32)."""
        blender_ext.enable()
        name = self.scene_property()
        self.assertEqual(
            getattr(bpy.context.scene, name).as_pointer(),
            bpy.context.scene.geoblender.as_pointer(),
        )
        rna = bpy.types.Scene.bl_rna.properties[name]
        self.assertEqual(rna.type, "POINTER")
        group = rna.fixed_type
        self.assertEqual(group.identifier, "GEOBLENDER_PG_core_project")
        props = group.properties
        for name in ("origin_x", "origin_y", "origin_z", "crs_epsg", "vcrs_epsg"):
            with self.subTest(propiedad=name):
                self.assertEqual(props[name].type, "INT")
                self.assertEqual(props[name].hard_min, -INT32_LIMIT)
                self.assertEqual(props[name].hard_max, INT32_LIMIT - 1)
                self.assertFalse(props[name].is_animatable, "no se anima el GeoOrigin")
        for name in ("project_uid", "project_name", "project_path"):
            self.assertEqual(props[name].type, "STRING")
        self.assertEqual(props["view_stale"].type, "BOOLEAN")
        self.assertEqual(
            [p.identifier for p in props if p.type == "FLOAT"], [], "nada en float32"
        )

    def test_unregister_removes_scene_property(self) -> None:
        """Principio 8: desactivar Geoblender quita ``Scene.geoblender`` y desregistra
        sus grupos de propiedades y sus preferencias."""
        blender_ext.enable()
        name = self.scene_property()
        self.assertIn(name, bpy.types.Scene.bl_rna.properties)
        bl = self.bl()
        groups = [
            sys.modules[bl.__name__ + ".props.core"].GEOBLENDER_PG_core_project,
            sys.modules[bl.__name__ + ".props.core"].GEOBLENDER_PG_core_preferences,
            sys.modules[bl.__name__ + ".props.preferences"].GeoblenderPreferences,
        ]
        self.assertTrue(all(cls.is_registered for cls in groups))
        blender_ext.disable()
        self.assertNotIn(name, bpy.types.Scene.bl_rna.properties)
        self.assertFalse(hasattr(bpy.types.Scene, name))
        self.assertEqual([cls.__name__ for cls in groups if cls.is_registered], [])


class PreferencesTest(CoreScenePropsTestCase):
    def test_preferences_linked_with_defaults(self) -> None:
        """RF-002-10: con la extensión habilitada desde ``gb_tests``,
        ``preferences.addons[bl.ADDON_PACKAGE].preferences`` existe y su grupo ``core``
        tiene ``lock_stale_minutes`` = 30 (de 10 a 1 440) y ``checkout_dir`` vacío (la
        carpeta ``checkouts/`` de los datos de usuario, spec 002 D-4)."""
        blender_ext.enable()
        package = self.bl().ADDON_PACKAGE
        self.assertEqual(package, module_name())
        preferences = bpy.context.preferences.addons[package].preferences
        self.assertIsNotNone(preferences)
        core = preferences.core
        self.assertEqual(core.lock_stale_minutes, 30)
        stale = core.bl_rna.properties["lock_stale_minutes"]
        self.assertEqual((stale.hard_min, stale.hard_max), (10, 1440))
        self.assertEqual(core.checkout_dir, "")
        self.assertEqual(core.bl_rna.properties["checkout_dir"].subtype, "DIR_PATH")

    def test_single_preferences_class(self) -> None:
        """PLT-02: la extensión registra **una** clase de preferencias, con
        ``bl_idname`` = ``bl.ADDON_PACKAGE``."""
        blender_ext.enable()
        mine = [
            cls
            for cls in bpy.types.AddonPreferences.__subclasses__()
            if cls.__module__.startswith(module_name() + ".")
            and getattr(cls, "is_registered", False)
        ]
        self.assertEqual([cls.__name__ for cls in mine], ["GeoblenderPreferences"])
        self.assertEqual(mine[0].bl_idname, self.bl().ADDON_PACKAGE)


if __name__ == "__main__":
    unittest.main()
