# SPDX-License-Identifier: GPL-3.0-or-later
"""El ``.blend`` de la interfaz, ``resources/geoblender_ui.blend`` (spec 003, T14; CW §6.1,
§6.2 y §7; PC §5.5).

- RF-003-02, RF-003-16: contiene las disposiciones de la 003 de ``layouts.toml`` (con su
  nombre de espacio de trabajo) y el «Layout» de respaldo, y nada más: ni objetos ni
  escenas. Todas, salvo «Layout», llevan ``geoblender_mode``; ninguna fija la escena y
  todas están en modo Objeto.
- CW §6.1: la principal tiene Outliner (configurado como PC §5.5), Vista 3D con la fila 2
  visible y la barra N cerrada (convergencia, T46; RNF-003-03) y Propiedades.
- CW §6.2: «Sección y planta», dos Vistas 3D (planta y sección, ortográficas) con su fila 2;
  «Datos», la Hoja de cálculo; «Diseño y perfil», dos Vistas 3D; «Fases», la hoja de claves.

El reparto de las áreas (anchos) solo se ve en la interfaz gráfica: verificación de la T14.
Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

BLEND_NAME = "geoblender_ui.blend"
FALLBACK = "Layout"
ENTRY = "003"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _areas(workspace: bpy.types.WorkSpace) -> list[bpy.types.Area]:
    return list(workspace.screens[0].areas)


def _types(workspace: bpy.types.WorkSpace) -> list[str]:
    return sorted(area.type for area in _areas(workspace))


def _views(workspace: bpy.types.WorkSpace) -> Iterator[bpy.types.SpaceView3D]:
    for area in _areas(workspace):
        if area.type == "VIEW_3D":
            yield next(space for space in area.spaces if space.type == "VIEW_3D")


class UiResourcesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        root = blender_ext.enable()
        cls.path = Path(root.__file__).parent / "resources" / BLEND_NAME
        cls.cat = _module("core.catalog").load()
        cls.layouts = [layout for layout in cls.cat.layouts if layout.entry == ENTRY]
        cls.names = [layout.workspace for layout in cls.layouts]
        cls.main = next(layout.workspace for layout in cls.cat.layouts if layout.main)
        with bpy.data.libraries.load(str(cls.path)) as (source, target):
            cls.content = {name: list(getattr(source, name)) for name in
                           ("workspaces", "objects", "scenes", "meshes", "collections")}
            target.workspaces = list(source.workspaces)
        cls.loaded = dict(zip(cls.content["workspaces"], target.workspaces, strict=True))

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()  # el fichero de fábrica, sin los espacios anexados
        blender_ext.release()

    def test_content(self) -> None:
        """RF-003-02, RF-003-16: las disposiciones de la 003 y «Layout», sin objetos ni
        escenas."""
        self.assertIn(self.main, self.names)
        self.assertEqual(sorted(self.content["workspaces"]), sorted([*self.names, FALLBACK]))
        for kind in ("objects", "scenes", "meshes", "collections"):
            self.assertEqual(self.content[kind], [], kind)

    def test_marks(self) -> None:
        """CW §6, §3.3: todas marcadas salvo «Layout», sin escena fijada y en modo Objeto."""
        for name, workspace in self.loaded.items():
            self.assertEqual(workspace.geoblender_mode, name != FALLBACK, name)
            self.assertFalse(workspace.use_pin_scene, name)
            self.assertEqual(workspace.object_mode, "OBJECT", name)

    def test_main_layout(self) -> None:
        """CW §6.1, PC §5.5: Outliner, Vista 3D con la fila 2 y la barra T, y Propiedades;
        la barra N, cerrada (convergencia, T46; RNF-003-03: abierta, el redibujo de la
        ventana costaba unos 0,6 ms más; la pestaña «Proyecto» está a un N); el Outliner
        en «Capa de vista», sin contenido de objeto ni hijos, con las columnas de ocultar
        y seleccionable y en orden alfabético."""
        workspace = self.loaded[self.main]
        types = _types(workspace)
        for kind in ("OUTLINER", "VIEW_3D", "PROPERTIES"):
            self.assertEqual(types.count(kind), 1, types)
        (view,) = _views(workspace)
        self.assertTrue(view.show_region_tool_header)
        self.assertTrue(view.show_region_toolbar)
        self.assertFalse(view.show_region_ui)
        outliner = next(space for area in _areas(workspace) for space in area.spaces
                        if space.type == "OUTLINER")
        self.assertEqual(outliner.display_mode, "VIEW_LAYER")
        self.assertFalse(outliner.use_filter_object_content)
        self.assertFalse(outliner.use_filter_children)
        self.assertTrue(outliner.show_restrict_column_hide)
        self.assertTrue(outliner.show_restrict_column_select)
        self.assertTrue(outliner.use_sort_alpha)

    def test_optional_layouts(self) -> None:
        """CW §6.2: el contenido de cada disposición opcional de la 003."""
        by_id = {layout.id: self.loaded[layout.workspace] for layout in self.layouts}
        views = list(_views(by_id["SECTION_PLAN"]))
        self.assertEqual(len(views), 2)
        self.assertTrue(all(v.show_region_tool_header for v in views))
        self.assertEqual({v.region_3d.view_perspective for v in views}, {"ORTHO"})
        self.assertIn("SPREADSHEET", _types(by_id["DATA"]))
        self.assertEqual(_types(by_id["DESIGN_PROFILE"]).count("VIEW_3D"), 2)
        sheets = [area.ui_type for area in _areas(by_id["PHASES"])
                  if area.type == "DOPESHEET_EDITOR"]
        self.assertIn("DOPESHEET", sheets)


if __name__ == "__main__":
    unittest.main()
