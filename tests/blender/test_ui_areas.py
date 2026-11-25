# SPDX-License-Identifier: GPL-3.0-or-later
"""Las áreas del ``.blend`` de interfaz (spec 019, T16; RF-019-02, RF-019-03).

El ``.blend`` se lee con ``bpy.data.libraries.load`` (``open_mainfile`` carga los espacios de
fábrica: ``docs/trampas.md``). Comprueba lo que genera ``tools/inblender/make_ui_blend.py``:

- RF-019-01: cada área y región tiene su decisión (lista de áreas decididas, T17) y el
  documento ``areas-decididas.md`` coincide con los datos.
- RF-019-02: ninguna disposición de Geoblender lleva la hoja de claves en modo línea de
  tiempo (la barra inferior); «Fases» sí lleva su hoja de claves (con los marcadores).
- RF-019-03: en los espacios de Geoblender, las pestañas de Propiedades salvo «Objeto» están
  ocultas y Propiedades abre en Objeto; ningún otro espacio (el «Layout» de respaldo) se toca.
- La Vista 3D colorea por objeto (sólido y malla) y el Outliner oculta cámaras y luces, por
  espacio (P-7).
- P-9: cada espacio lleva ``geoblender_layout_rev`` igual a ``areas.LAYOUT_REV``.
- El generador es reproducible: dos ejecuciones dan el mismo fichero.
- P-9, R-4 (T18): un fichero con la revisión anterior avisa una vez al conmutar y no se cambia
  solo; «Actualizar la disposición» crea los espacios nuevos y conserva los anteriores;
  cancelar no deja nada; sin cambio de revisión, ni aviso ni orden activa.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

import bpy

from tests.support import blender_ext, docs
from tests.support.blender_ext import module_name

DOC_RELPATH = "docs/arquitectura/interfaz/areas-decididas.md"
ROOT = Path(__file__).resolve().parents[2]
BLEND_NAME = "geoblender_ui.blend"
GENERATOR = ROOT / "tools" / "inblender" / "make_ui_blend.py"
FALLBACK = "Layout"
PHASES = "Geoblender · Fases"
DATA = "Geoblender · Datos"
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

    def test_every_area_and_region_has_a_decision(self) -> None:
        """RF-019-01: cada área y región del ``.blend`` generado, y las de la Vista 3D
        (cabecera, fila 2, barra T, barra N, vista), la barra superior, la de estado y los
        gizmos, tienen decisión; ninguna sin ella."""
        keys = {item.key for item in self.areas.AREAS}
        found: set[str] = set()
        for name in [*self.names, FALLBACK]:
            for area in self.loaded[name].screens[0].areas:
                for region in area.regions:
                    found.add(f"{area.type}/{region.type}")
        self.assertTrue({"VIEW_3D/HEADER", "VIEW_3D/TOOL_HEADER", "VIEW_3D/TOOLS",
                         "VIEW_3D/UI", "VIEW_3D/WINDOW", "OUTLINER/WINDOW",
                         "PROPERTIES/WINDOW", "PROPERTIES/NAVIGATION_BAR"} <= found)
        self.assertEqual(sorted(found - keys), [], "áreas o regiones sin decisión")
        for pseudo in ("TOPBAR/HEADER_LEFT", "TOPBAR/HEADER_RIGHT", "STATUSBAR/MINING",
                       "STATUSBAR/REPORT", "VIEW_3D/GIZMO_NAVIGATE", "VIEW_3D/GIZMO_TOOL"):
            self.assertIn(pseudo, keys)

    def test_decisions_are_well_formed(self) -> None:
        """RF-019-01: la decisión es una de las cuatro y todo «de Blender» lleva su motivo."""
        keys = [item.key for item in self.areas.AREAS]
        self.assertEqual(len(keys), len(set(keys)), "claves repetidas")
        self.assertEqual(set(self.areas.DECISIONS),
                         {"GEOBLENDER", "REPLACED", "HIDDEN", "BLENDER"})
        for item in self.areas.AREAS:
            self.assertIn(item.decision, self.areas.DECISIONS, item.key)
            self.assertEqual(item.key, f"{item.area}/{item.region}")
            self.assertTrue(item.label.strip() and item.what.strip(), item.key)
            if item.decision == "BLENDER":
                self.assertGreaterEqual(len(item.reason.strip()), 20, item.key)
        self.assertEqual(self.areas.decision_for(next(iter(keys))),
                         self.areas.AREAS[0])
        with self.assertRaises(KeyError):
            self.areas.decision_for("NOPE/NOPE")

    @docs.requires_docs
    def test_document_matches_data(self) -> None:
        """RF-019-01: ``areas-decididas.md`` y los datos coinciden fila por fila (clave,
        decisión y motivo)."""
        rows: dict[str, tuple[str, str, str]] = {}
        for line in docs.read(DOC_RELPATH).splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if line.startswith("| `") and len(cells) == 5:
                rows[cells[0].strip("`")] = (cells[2], cells[3], cells[4])
        self.assertEqual(set(rows), {item.key for item in self.areas.AREAS})
        for item in self.areas.AREAS:
            label, what, reason = rows[item.key]
            self.assertEqual(label, self.areas.DECISIONS[item.decision], item.key)
            self.assertEqual(reason, item.reason or "—", item.key)
            self.assertEqual(what, item.what, f"{item.key}: el texto del documento y el de los datos difieren")

    def test_no_row_cites_a_pending_task(self) -> None:
        """T36 (F-4): ninguna fila de ``AREAS`` dice que una tarea está «pendiente» (el texto envejece al hacerse)."""
        for item in self.areas.AREAS:
            self.assertNotIn("pendiente", f"{item.what} {item.reason}".lower(), item.key)

    def test_generator_is_reproducible(self) -> None:
        """El generador da el mismo fichero dos veces, y el del repositorio es su salida."""
        with tempfile.TemporaryDirectory(prefix="gb-gen-out-") as folder:
            first, second = Path(folder, "a.blend"), Path(folder, "b.blend")
            _generate(first)
            _generate(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first.read_bytes(), self.blend.read_bytes(),
                             "geoblender_ui.blend no es la salida del generador: regenerarlo")


class LayoutRevisionPureTest(unittest.TestCase):
    """P-9: qué disposiciones son anteriores, sobre nombres y revisiones (sin ``bpy``)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.areas = _module("bl.ui.areas")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def test_outdated_names(self) -> None:
        rev = self.areas.LAYOUT_REV
        known = ["G", "G · Datos", "G · Fases"]
        found = self.areas.outdated_names({"G": rev - 1, "G · Datos": None, "G · Fases": rev}, known)
        self.assertEqual(found, ["G", "G · Datos"])  # sin clave = la revisión 1 (la 003)
        # Una copia nueva («G.001») con la revisión actual ya renovó la disposición.
        renewed = self.areas.outdated_names({"G": rev - 1, "G.001": rev}, known)
        self.assertEqual(renewed, [])
        self.assertEqual(self.areas.outdated_names({"G": rev}, known), [])
        self.assertEqual(self.areas.outdated_names({}, known), [])
        # Un espacio marcado que no es del catálogo no se renueva.
        self.assertEqual(self.areas.outdated_names({"Mío": 1}, known), [])


class LayoutUpdateTest(unittest.TestCase):
    """P-9, R-4: el aviso una vez y la orden explícita «Actualizar la disposición»."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.areas = _module("bl.ui.areas")
        cls.switcher = _module("bl.ui.switcher")
        cls.layouts = _module("bl.ui.layouts")
        cls.main = cls.switcher.main_workspace()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        blender_ext.load_file()
        self.switcher.forget()
        self.window = bpy.context.window_manager.windows[0]
        self.objects = sorted(obj.name for obj in bpy.data.objects)

    def add(self, layout_id: str) -> None:
        with bpy.context.temp_override(window=self.window):
            bpy.ops.geoblender.ui_add_layout(layout=layout_id)

    def make_old(self) -> None:
        """Un fichero guardado con la disposición anterior: la principal y «Datos» en la 1."""
        self.add("MAIN")
        self.add("DATA")
        for ws in bpy.data.workspaces:
            if ws.geoblender_mode:
                ws[REV_KEY] = self.areas.LAYOUT_REV - 1

    def snapshot(self) -> dict[str, object]:
        return {ws.name: ws.get(REV_KEY) for ws in bpy.data.workspaces}

    def notice(self) -> object:
        return mock.patch(f"{module_name()}.bl.ui.notices.post")

    def test_warns_once_and_changes_nothing(self) -> None:
        """P-9, UI-09: al conmutar con una disposición anterior, un aviso, una vez; el
        fichero no se cambia solo."""
        self.make_old()
        before = self.snapshot()
        self.assertEqual(self.switcher.outdated_layouts(), [self.main, DATA])
        with self.notice() as show:
            self.switcher.toggle(self.window, "GEOBLENDER")
            self.switcher.toggle(self.window, "BLENDER")
            self.switcher.toggle(self.window, "GEOBLENDER")
        self.assertEqual(show.call_count, 1)
        self.assertIn("anterior", show.call_args.args[1])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(sorted(obj.name for obj in bpy.data.objects), self.objects)

    def test_update_creates_new_and_keeps_old(self) -> None:
        """RF-019-03: la orden crea los espacios nuevos, conserva los anteriores y no deja
        la biblioteca; después, ya no hay nada que renovar."""
        self.make_old()
        old = self.snapshot()
        with bpy.context.temp_override(window=self.window):
            self.assertEqual(bpy.ops.geoblender.ui_update_layout(), {"FINISHED"})
        now = self.snapshot()
        for name, rev in old.items():
            self.assertIn(name, now, "se borró un espacio anterior")
            self.assertEqual(now[name], rev, "se cambió un espacio anterior")
        fresh = sorted(set(now) - set(old))
        self.assertEqual(len(fresh), 2, fresh)
        for name in fresh:
            self.assertEqual(bpy.data.workspaces[name].get(REV_KEY), self.areas.LAYOUT_REV)
            self.assertTrue(bpy.data.workspaces[name].geoblender_mode)
        self.assertEqual(len(bpy.data.libraries), 0)
        self.assertEqual(self.switcher.outdated_layouts(), [])
        self.assertFalse(bpy.ops.geoblender.ui_update_layout.poll())
        with self.notice() as show:
            self.switcher.toggle(self.window, "GEOBLENDER")
        self.assertEqual(show.call_count, 0)
        self.assertEqual(sorted(obj.name for obj in bpy.data.objects), self.objects)

    def test_cancel_leaves_nothing(self) -> None:
        """UI-15: la confirmación dice cuáles se renuevan; cancelarla no deja nada."""
        self.make_old()
        before = self.snapshot()
        # En segundo plano Blender confirma solo el diálogo: se prueba lo que ``invoke`` pide.
        operator = bpy.types.GEOBLENDER_OT_ui_update_layout
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = mock.Mock(window_manager=mock.Mock(invoke_props_dialog=dialog))
        self.assertEqual(operator.invoke(operator, context, None), {"RUNNING_MODAL"})
        dialog.assert_called_once()
        self.assertEqual(self.snapshot(), before)
        text = self.layouts.update_text()
        self.assertIn(self.main, text)
        self.assertIn(DATA, text)
        self.assertIn("no se borran", text)

    def test_up_to_date_has_no_notice_and_command_is_disabled(self) -> None:
        """UI-13: sin cambio de revisión, ni aviso ni orden activa (con su causa)."""
        self.add("MAIN")
        self.assertEqual(self.switcher.outdated_layouts(), [])
        with self.notice() as show:
            self.switcher.toggle(self.window, "GEOBLENDER")
        self.assertEqual(show.call_count, 0)
        self.assertFalse(bpy.ops.geoblender.ui_update_layout.poll())
        self.assertIn("al día", self.layouts.update_check(bpy.context))
        self.make_old()
        self.assertEqual(self.layouts.update_check(bpy.context), "")
        self.assertTrue(bpy.ops.geoblender.ui_update_layout.poll())


if __name__ == "__main__":
    unittest.main()
