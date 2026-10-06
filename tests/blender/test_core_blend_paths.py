# SPDX-License-Identifier: GPL-3.0-or-later
"""Guardar la vista y proyectos recientes (spec 002, T26; plan 002 §5.3 y §5.4).

- RF-002-07: «Guardar» guarda la vista en su fichero o, si no tiene, en
  ``scenes/principal.blend`` (sin sustituir otra vista), con rutas relativas, y la
  cabecera se actualiza desde la base; en solo lectura no escribe en ``scenes/`` y propone
  «Guardar como» fuera del proyecto, y al cargar una vista de ``scenes/`` en solo lectura
  se advierte de que Ctrl+S la guardaría dentro (spec §8).
- RF-002-18: ningún ``.blend`` de ``scenes/`` guarda rutas absolutas: ni la de los bloques
  de datos (una imagen cargada con ruta absoluta pasa a relativa al guardar, también con
  Ctrl+S) ni la del proyecto en la escena; y, en sus bytes, tampoco las de los datos de
  la interfaz de Blender, que una vista no guarda, ni la salida de render, que pasa a
  relativa a la vista (D-11; T50).
- RF-002-08: crear y abrir dejan el proyecto el primero de los recientes del equipo (10
  como mucho), guardados en los datos de usuario de la extensión y nunca en un proyecto;
  el menú «Abrir reciente» los lista y abre.

Se ejecuta con ``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import getpass
import json
import os
import re
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


ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"  # cabecera de un .blend comprimido (zstd)
PRINTABLE_RUN = re.compile(rb"[\x20-\x7e]{3,}")  # los textos del fichero, como `strings`


def view_bytes(path: Path) -> bytes:
    """Los bytes del ``.blend`` sin comprimir (Blender comprime con zstd si la preferencia
    lo pide; su Python trae ``zstandard``)."""
    data = path.read_bytes()
    if data.startswith(ZSTD_MAGIC):
        import zstandard

        with zstandard.ZstdDecompressor().stream_reader(data) as reader:
            data = reader.read()
    return data


class ViewBytesTest(BlendPathsTestCase):
    """Las vistas de ``scenes/`` sin rutas absolutas en sus bytes (spec 002, D-11 y T50;
    RF-002-18, RF-002-07): sin los datos de la interfaz de Blender (pantallas, áreas,
    gestor de ventanas y espacios de trabajo, que guardan la carpeta del último «Guardar
    como» del usuario) y con la salida de render relativa a la vista (la escena de fábrica
    trae ``/tmp\\``)."""

    def assert_view_bytes_clean(self, path: Path) -> None:
        """En los bytes de ``path`` sin comprimir no hay ninguna ruta absoluta (los textos
        del fichero, sin el prefijo ``//`` de las relativas de Blender), ni ``/tmp``, ni
        ``Users``, ni ``Documents``, ni el nombre de usuario del equipo."""
        data = view_bytes(path)
        self.assertTrue(data.startswith(b"BLENDER"), data[:12])
        texts = [
            match.group(0).decode("ascii").removeprefix("//")
            for match in PRINTABLE_RUN.finditer(data)
        ]
        self.assertEqual(self.paths.find_absolute_paths(texts), [])
        user = getpass.getuser().encode("utf-8")
        for needle in (b"/tmp", b"Users", b"Documents", user):
            with self.subTest(fichero=path.name, texto=needle):
                where = data.find(needle)
                self.assertEqual(where, -1, data[max(0, where - 40) : where + 60])

    def test_views_saved_without_interface_or_absolute_paths(self) -> None:
        """RF-002-18, RF-002-07 (D-11): una vista guardada con «Guardar» (en
        ``scenes/principal.blend``), guardada otra vez con Ctrl+S (``wm.save_mainfile``) y
        otra guardada con «Guardar como» de Blender en ``scenes/`` no tienen en sus bytes
        ninguna ruta absoluta; la sesión sigue en su fichero, sin cambios pendientes; al
        volver a cargarla, sus dos escenas conservan ``Scene.geoblender``, la salida de
        render resuelve a la carpeta de la vista y no trae los datos de la interfaz."""
        project = self.create()
        self.assertEqual(bpy.context.scene.render.filepath, "/tmp\\")  # la de fábrica
        bpy.data.scenes.new("Segunda")
        scenes = project.root / "scenes"
        principal = scenes / "principal.blend"
        self.assertEqual(bpy.ops.geoblender.core_save_project("EXEC_DEFAULT"), {"FINISHED"})
        self.assertEqual(Path(bpy.data.filepath), principal)
        self.assertFalse(bpy.data.is_dirty)
        self.assert_view_bytes_clean(principal)
        bpy.context.scene.frame_current = 7
        bpy.ops.wm.save_mainfile()  # Ctrl+S de Blender
        self.assertEqual(Path(bpy.data.filepath), principal)
        self.assertFalse(bpy.data.is_dirty)
        self.assert_view_bytes_clean(principal)
        blender_ext.load_file()  # otra vista, sin fichero
        other = scenes / "otra.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(other))
        self.assert_view_bytes_clean(other)
        self.assertEqual(self.ps.take_notices(), [])

        blender_ext.load_file(principal)
        self.assertEqual(Path(bpy.data.filepath), principal)
        self.assertEqual(sorted(scene.name for scene in bpy.data.scenes), ["Scene", "Segunda"])
        self.assertEqual(bpy.data.scenes["Scene"].frame_current, 7)
        for scene in bpy.data.scenes:
            with self.subTest(escena=scene.name):
                props = scene.geoblender
                self.assertEqual(props.project_uid, project.uid)
                self.assertEqual(props.project_path, "//../")
                self.assertEqual(
                    (props.origin_x, props.origin_y, props.origin_z), (700_000, 4_400_000, 0)
                )
                self.assertTrue(scene.render.filepath.startswith("//"), scene.render.filepath)
                resolved = Path(bpy.path.abspath(scene.render.filepath))
                self.assertEqual(resolved.resolve(), scenes.resolve())

    def test_render_output_on_another_volume_warns(self) -> None:
        """RF-002-18 (D-11): una salida de render en otra unidad no se puede expresar
        relativa a la vista: pasa a la carpeta de la vista (``//`` y su nombre) con un aviso
        que la nombra; una vista guardada fuera de ``scenes/`` no se toca."""
        project = self.create()
        drive = "D:" if not str(project.root).upper().startswith("D:") else "E:"
        bpy.context.scene.render.filepath = f"{drive}\\render\\toma_"
        # «Guardar» informa de los avisos y los vacía: se miran en el registro técnico.
        with self.assertLogs(self.ps.LOGGER, "WARNING") as logged:
            result = bpy.ops.geoblender.core_save_project("EXEC_DEFAULT")
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(Path(bpy.data.filepath), project.root / "scenes" / "principal.blend")
        self.assertEqual(bpy.context.scene.render.filepath, "//toma_")
        self.assertTrue(
            any(f"{drive}\\render\\toma_" in line for line in logged.output), logged.output
        )
        blender_ext.load_file()  # otra vista, sin fichero: la de fábrica trae «/tmp\»
        outside = self.tmp / "fuera" / "vista.blend"
        outside.parent.mkdir()
        bpy.ops.wm.save_as_mainfile(filepath=str(outside))
        self.assertEqual(bpy.context.scene.render.filepath, "/tmp\\")
        self.assertEqual(self.ps.take_notices(), [])


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
