# SPDX-License-Identifier: GPL-3.0-or-later
"""Guardar la vista y proyectos recientes (spec 002, T26; plan 002 §5.3 y §5.4).

- RF-002-07: «Guardar» guarda la vista en su fichero o, si no tiene, en
  ``scenes/principal.blend`` (sin sustituir otra vista), con rutas relativas, y la
  cabecera se actualiza desde la base; en solo lectura no escribe en ``scenes/`` y propone
  «Guardar como» fuera del proyecto, y al cargar una vista de ``scenes/`` en solo lectura
  se advierte de que Ctrl+S la guardaría dentro (spec §8).
- RF-002-18: ningún ``.blend`` de ``scenes/`` guarda rutas absolutas: ni la de los bloques
  de datos (una imagen cargada con ruta absoluta pasa a relativa al guardar, también con
  Ctrl+S) ni la del proyecto en la escena.
- RF-002-08: crear y abrir dejan el proyecto el primero de los recientes del equipo (10
  como mucho), guardados en los datos de usuario de la extensión y nunca en un proyecto;
  el menú «Abrir reciente» los lista y abre.

Se ejecuta con ``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw

WINDOW = (699_500.4, 4_399_500.6, 700_500.2, 4_400_500.9)
RECENT_LIMIT = 10


def ext(name: str) -> ModuleType:
    """El módulo ``name`` de la copia de pruebas de la extensión (ya importado)."""
    return sys.modules[f"{module_name()}.{name}"]


class BlendPathsTestCase(unittest.TestCase):
    """Cada prueba parte de la extensión habilitada, la escena de fábrica y una carpeta
    temporal para sus proyectos."""

    def setUp(self) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        self.tmp = Path(tempfile.mkdtemp(prefix="geoblender-t26-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(blender_ext.unload)
        blender_ext.enable()
        self.ps = ext("bl.scene.project_session")
        self.core = ext("core.project")
        self.paths = ext("core.paths")
        self.ps.take_notices()
        # Los recientes son del perfil temporal de toda la sesión: cada prueba, sin ellos.
        (Path(self.ps.userdata().root) / "projects" / "recent.json").unlink(missing_ok=True)

    def create(self, name: str = "Cantera Prueba", *, attach: bool = True) -> object:
        settings = self.core.ProjectSettings(
            name=name, window=WINDOW, crs_epsg=25830, vcrs_epsg=5782
        )
        result = self.core.create_project(
            self.tmp, settings, self.ps.session(), self.ps.userdata()
        )
        if attach:
            self.ps.attach(result.project)
        return result.project

    def image_outside(self) -> tuple[bpy.types.Image, Path]:
        """Una imagen en un PNG fuera del proyecto, cargada con su ruta absoluta (con
        usuario falso: si no, Blender no la guarda)."""
        png = self.tmp / "texturas" / "ortofoto.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        source = bpy.data.images.new("generada", 4, 4)
        source.filepath_raw = str(png)
        source.file_format = "PNG"
        source.save()
        bpy.data.images.remove(source)
        image = bpy.data.images.load(str(png))
        image.use_fake_user = True
        self.assertTrue(os.path.isabs(image.filepath))
        return image, png

    def assert_no_absolute_paths(self) -> None:
        """Ninguna ruta de los bloques de datos ni de la georreferencia de las escenas
        del ``.blend`` cargado es absoluta (``//`` es «relativa al .blend»)."""
        found: list[str] = []
        for id_block, used in bpy.data.file_path_map(include_libraries=True).items():
            for path in used:
                if path and not path.startswith("//"):
                    found.append(f"{id_block.name}: {path}")
        for scene in bpy.data.scenes:
            props = scene.geoblender
            for name in ("project_uid", "project_name", "project_path"):
                value = getattr(props, name).removeprefix("//")
                found.extend(f"{scene.name}.{name}: {p}" for p in self.paths.find_absolute_paths(value))
        self.assertEqual(found, [])


class SaveProjectTest(BlendPathsTestCase):
    def test_unsaved_view_goes_to_scenes_principal(self) -> None:
        """RF-002-07: una vista sin fichero se guarda en ``scenes/principal.blend`` con la
        ruta del proyecto relativa (``//../``); si ya existe, la siguiente vista sin
        fichero va a ``principal-2.blend`` y no la sustituye."""
        project = self.create()
        self.assertTrue(bpy.ops.geoblender.core_save_project.poll())
        self.assertEqual(bpy.ops.geoblender.core_save_project("EXEC_DEFAULT"), {"FINISHED"})
        principal = project.root / "scenes" / "principal.blend"
        self.assertTrue(principal.is_file())
        self.assertEqual(Path(bpy.data.filepath), principal)
        self.assertEqual(bpy.context.scene.geoblender.project_path, "//../")
        before = principal.read_bytes()
        blender_ext.load_file()  # una vista nueva, sin fichero, del mismo proyecto
        self.assertEqual(bpy.ops.geoblender.core_save_project("EXEC_DEFAULT"), {"FINISHED"})
        self.assertEqual(Path(bpy.data.filepath), project.root / "scenes" / "principal-2.blend")
        self.assertEqual(principal.read_bytes(), before)

    def test_saved_view_has_no_absolute_paths(self) -> None:
        """RF-002-18, RF-002-07: una imagen cargada con ruta absoluta del mismo volumen
        queda relativa al guardar con «Guardar» y con Ctrl+S (``wm.save_mainfile``), y al
        volver a cargar la vista ninguna ruta de sus bloques de datos ni de su
        georreferencia es absoluta; la imagen sigue apuntando a su fichero."""
        project = self.create()
        image, png = self.image_outside()
        bpy.ops.geoblender.core_save_project("EXEC_DEFAULT")
        self.assertTrue(image.filepath.startswith("//"), image.filepath)
        second = bpy.data.images.load(str(png), check_existing=False)
        second.use_fake_user = True
        self.assertTrue(os.path.isabs(second.filepath))
        bpy.ops.wm.save_mainfile()  # Ctrl+S de Blender
        blender_ext.load_file(project.root / "scenes" / "principal.blend")
        self.assertEqual(len([i for i in bpy.data.images if i.filepath]), 2)
        for loaded in bpy.data.images:
            if loaded.filepath:
                self.assertTrue(loaded.filepath.startswith("//"), loaded.filepath)
                self.assertEqual(Path(bpy.path.abspath(loaded.filepath)).resolve(), png.resolve())
        self.assert_no_absolute_paths()

    def test_header_updated_on_save(self) -> None:
        """RF-002-07: guardar la vista actualiza la cabecera desde la base de datos."""
        project = self.create()
        path = project.root / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["modified_at"] = "2020-01-01T00:00:00.000Z"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        bpy.ops.geoblender.core_save_project("EXEC_DEFAULT")
        header = ext("core.project.manifest").read_manifest(project.root)
        self.assertEqual(header.modified_at, project.record.modified_at)

    def test_read_only_does_not_write_scenes(self) -> None:
        """RF-002-07, RF-002-13: en solo lectura, «Guardar» no escribe en ``scenes/`` (y
        propone «Guardar como» fuera del proyecto); al cargar una vista de ``scenes/`` con
        el proyecto en solo lectura se advierte de que Ctrl+S la guardaría dentro."""
        project = self.create()
        bpy.ops.geoblender.core_save_project("EXEC_DEFAULT")
        principal = project.root / "scenes" / "principal.blend"
        self.ps.close()
        reopened = self.core.open_project(
            project.root, self.ps.session(), self.ps.userdata(), want_write=False
        )
        self.ps.attach(reopened.project)
        self.ps.take_notices()
        blender_ext.load_file(principal)
        notices = self.ps.take_notices()
        self.assertTrue(any("Ctrl+S" in text and "solo lectura" in text for text in notices),
                        notices)
        before = sorted(p.name for p in (project.root / "scenes").iterdir())
        blender_ext.load_file()  # vista sin fichero
        self.assertEqual(bpy.ops.geoblender.core_save_project("EXEC_DEFAULT"), {"CANCELLED"})
        self.assertEqual(sorted(p.name for p in (project.root / "scenes").iterdir()), before)


class RecentProjectsTest(BlendPathsTestCase):
    def test_recent_limit_location_and_menu(self) -> None:
        """RF-002-08: tras crear 12 proyectos, los recientes son los 10 últimos, del más
        reciente al más antiguo, en los datos de usuario de la extensión y en ninguna
        carpeta de proyecto; el menú «Abrir reciente» lista esos 10 con
        ``geoblender.core_open_project`` y su carpeta, y abrir uno lo pone el primero."""
        roots = []
        for number in range(12):
            project = self.create(f"Proyecto {number:02d}", attach=False)
            project.close()
            roots.append(project.root)
        recent = self.ps.userdata().recent_projects()
        self.assertEqual(len(recent), RECENT_LIMIT)
        self.assertEqual([item.path for item in recent], list(reversed(roots))[:RECENT_LIMIT])
        user_root = Path(bpy.utils.extension_path_user(ext("bl").ADDON_PACKAGE))
        self.assertTrue((user_root / "projects" / "recent.json").is_file())
        self.assertEqual(list(self.tmp.rglob("recent*.json")), [])
        menu = ext("bl.ui.core_menus").GEOBLENDER_MT_core_recent
        self.assertTrue(menu.is_registered)
        layout = draw(menu, bpy.context)
        entries = layout.of_kind("operator")
        self.assertEqual(len(entries), RECENT_LIMIT)
        self.assertTrue(all(item.target == "geoblender.core_open_project" for item in entries))
        self.assertEqual([Path(item.properties.directory) for item in entries],
                         [item.path for item in recent])
        self.assertIn("Proyecto 11", entries[0].text)
        oldest = recent[-1].path
        result = bpy.ops.geoblender.core_open_project("EXEC_DEFAULT", directory=str(oldest))
        self.assertEqual(result, {"RUNNING_MODAL"})
        self.finish_open()
        self.assertEqual(self.ps.userdata().recent_projects()[0].path, oldest)

    def test_empty_menu(self) -> None:
        """RF-002-08: sin recientes, el menú lo dice y no ofrece nada que abrir."""
        layout = draw(ext("bl.ui.core_menus").GEOBLENDER_MT_core_recent, bpy.context)
        self.assertEqual(layout.of_kind("operator"), [])
        self.assertEqual(len(layout.of_kind("label")), 1)

    def finish_open(self) -> None:
        from types import SimpleNamespace

        cls = ext("bl.ops.core").GEOBLENDER_OT_core_open_project
        (operator,) = [
            op for op in bpy.context.window.modal_operators
            if isinstance(op, cls) and getattr(op, "_steps", None) is not None
        ]
        for _ in range(10_000):
            if operator.modal(bpy.context, SimpleNamespace(type="TIMER", value="NOTHING")) != {
                "RUNNING_MODAL"
            }:
                break


if __name__ == "__main__":
    unittest.main()
