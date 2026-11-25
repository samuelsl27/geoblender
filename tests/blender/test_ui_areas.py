# SPDX-License-Identifier: GPL-3.0-or-later
"""Las áreas del ``.blend`` de interfaz (spec 019, T16; RF-019-02, RF-019-03).

El ``.blend`` se lee con ``bpy.data.libraries.load`` (``open_mainfile`` carga los espacios de
fábrica: ``docs/trampas.md``). Comprueba lo que genera ``tools/inblender/make_ui_blend.py``:

- RF-019-02: ninguna disposición de Geoblender lleva la hoja de claves en modo línea de
  tiempo (la barra inferior); «Fases» sí lleva su hoja de claves (con los marcadores).
- RF-019-03: en los espacios de Geoblender, las pestañas de Propiedades salvo «Objeto» están
  ocultas y Propiedades abre en Objeto; ningún otro espacio (el «Layout» de respaldo) se toca.
- La Vista 3D colorea por objeto (sólido y malla) y el Outliner oculta cámaras y luces, por
  espacio (P-7).
- P-9: cada espacio lleva ``geoblender_layout_rev`` igual a ``areas.LAYOUT_REV``.
- El generador es reproducible: dos ejecuciones dan el mismo fichero.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

ROOT = Path(__file__).resolve().parents[2]
BLEND_NAME = "geoblender_ui.blend"
GENERATOR = ROOT / "tools" / "inblender" / "make_ui_blend.py"
FALLBACK = "Layout"
PHASES = "Geoblender · Fases"
REV_KEY = "geoblender_layout_rev"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _spaces(workspace: bpy.types.WorkSpace, kind: str) -> list[bpy.types.Space]:
    return [space for area in workspace.screens[0].areas for space in area.spaces
            if space.type == kind and space == area.spaces.active]


def _tabs(space: bpy.types.SpaceProperties) -> dict[str, bool]:
    return {name: getattr(space, name) for name in dir(space)
            if name.startswith("show_properties_") and isinstance(getattr(space, name), bool)}


def _generate(target: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="gb-gen-") as profile:
        env = dict(os.environ, BLENDER_USER_RESOURCES=profile)
        done = subprocess.run(
            [bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1",
             "--python", str(GENERATOR), "--", "--salida", str(target)],
            env=env, capture_output=True, text=True, timeout=300, check=False)
    if done.returncode != 0:
        raise AssertionError(f"el generador falló ({done.returncode}):\n{done.stdout}\n{done.stderr}")


class UiAreasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        cls.blend = Path(blender_ext.enable().__file__).parent / "resources" / BLEND_NAME
        cls.areas = _module("bl.ui.areas")
        cls.cat = _module("core.catalog").load()
        cls.names = [layout.workspace for layout in cls.cat.layouts if layout.entry == "003"]
        with bpy.data.libraries.load(str(cls.blend)) as (source, target):
            original = list(source.workspaces)
            target.workspaces = list(original)
        # «Layout» ya existe en el fichero de fábrica: Blender renombra la copia.
        cls.loaded = dict(zip(original, target.workspaces, strict=True))

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def test_no_timeline_except_phases(self) -> None:
        """RF-019-02: sin hoja de claves en modo línea de tiempo; «Fases» con su hoja."""
        self.assertIn(PHASES, self.names)
        for name in self.names:
            workspace = self.loaded[name]
            timelines = [a for a in workspace.screens[0].areas
                         if a.type == "DOPESHEET_EDITOR" and a.ui_type == "TIMELINE"]
            self.assertEqual(timelines, [], name)
            sheets = [a for a in workspace.screens[0].areas if a.type == "DOPESHEET_EDITOR"]
            self.assertEqual(len(sheets), 1 if name == PHASES else 0, name)

    def test_main_has_no_bottom_bar(self) -> None:
        """RF-019-02: la principal solo tiene Outliner, Vista 3D y Propiedades."""
        main = next(layout.workspace for layout in self.cat.layouts if layout.main)
        types = sorted(a.type for a in self.loaded[main].screens[0].areas)
        self.assertEqual(types, ["OUTLINER", "PROPERTIES", "VIEW_3D"])

    def test_property_tabs_only_in_geoblender_spaces(self) -> None:
        """RF-019-03: solo «Objeto» visible y como actual en los de Geoblender; el de
        respaldo, intacto."""
        for name in self.names:
            for space in _spaces(self.loaded[name], "PROPERTIES"):
                tabs = _tabs(space)
                self.assertGreaterEqual(len(tabs), 15, name)
                self.assertEqual([k for k, v in tabs.items() if v], ["show_properties_object"],
                                 name)
                self.assertEqual(space.context, "OBJECT", name)
        fallback = _spaces(self.loaded[FALLBACK], "PROPERTIES")
        self.assertEqual(len(fallback), 1)
        tabs = _tabs(fallback[0])
        self.assertTrue(tabs["show_properties_render"])
        self.assertTrue(tabs["show_properties_object"])
        self.assertTrue(tabs["show_properties_world"])

    def test_color_by_object(self) -> None:
        """El color por objeto, en la vista sólida y en la de malla, por espacio."""
        for name in self.names:
            views = _spaces(self.loaded[name], "VIEW_3D")
            self.assertTrue(views, name)
            for view in views:
                self.assertEqual(view.shading.color_type, "OBJECT", name)
                self.assertEqual(view.shading.wireframe_color_type, "OBJECT", name)
        for view in _spaces(self.loaded[FALLBACK], "VIEW_3D"):
            self.assertNotEqual(view.shading.color_type, "OBJECT")

    def test_outliner_hides_cameras_and_lights(self) -> None:
        """P-7: filtros por espacio; el Outliner del respaldo se queda como está."""
        for name in self.names:
            outliners = _spaces(self.loaded[name], "OUTLINER")
            self.assertTrue(outliners, name)
            for outliner in outliners:
                self.assertFalse(outliner.use_filter_object_camera, name)
                self.assertFalse(outliner.use_filter_object_light, name)
                self.assertTrue(outliner.use_filter_object_mesh, name)
        (fallback,) = _spaces(self.loaded[FALLBACK], "OUTLINER")
        self.assertTrue(fallback.use_filter_object_camera)
        self.assertTrue(fallback.use_filter_object_light)

    def test_layout_revision(self) -> None:
        """P-9: la revisión de la disposición, un entero igual al de la extensión."""
        self.assertIsInstance(self.areas.LAYOUT_REV, int)
        for name in self.names:
            self.assertEqual(self.loaded[name].get(REV_KEY), self.areas.LAYOUT_REV, name)
        self.assertNotIn(REV_KEY, self.loaded[FALLBACK].keys())

    def test_generator_is_reproducible(self) -> None:
        """El generador da el mismo fichero dos veces, y el del repositorio es su salida."""
        with tempfile.TemporaryDirectory(prefix="gb-gen-out-") as folder:
            first, second = Path(folder, "a.blend"), Path(folder, "b.blend")
            _generate(first)
            _generate(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first.read_bytes(), self.blend.read_bytes(),
                             "geoblender_ui.blend no es la salida del generador: regenerarlo")


if __name__ == "__main__":
    unittest.main()
