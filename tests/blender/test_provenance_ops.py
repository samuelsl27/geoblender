# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia en Blender: propiedades, carpetas de solo lectura y sesión (spec 008, fase 7;
plan 008 §5.1, §5.4.11, §5.4.13, §5.5 y D16).

T45:

- RF-008-32 (plan §5.4.11): ``Scene.geoblender.registry_seq`` es un ``IntProperty`` (0 al
  empezar, no animable) que viaja con la escena: sobrevive a guardar y abrir el ``.blend``,
  como la escena que restaura Ctrl+Z.
- D16 (RF-008-06, RF-008-16, RF-008-28, RF-008-29): las filas de los paneles de la procedencia
  viven en ``WindowManager.geoblender_provenance`` (parámetros con su historial, entradas, lo
  obsoleto y la procedencia, y los filtros por módulo, tipo y marca): son una vista regenerada,
  no se guardan en el ``.blend`` y ningún valor pasa por una propiedad flotante (ARQ-13).
- RF-008-15 (S-3; ADR-0025 §9): la preferencia ``core.read_only_folders`` (carpetas separadas
  por «;») se une a las de la variable ``GEOBLENDER_READ_ONLY_DIRS`` (``read_only_dirs()``, con
  los valores de cada momento); las preferencias muestran debajo las de la variable, sin
  poder editarlas, y los avisos; con la variable y la preferencia vacías lo dicen el
  diagnóstico de la instalación y un aviso por sesión (uno solo, con un temporizador que se
  quita al desactivar Geoblender).
- Principio 8: registrar y desregistrar deja ``WindowManager``, la escena, las preferencias y
  los temporizadores como estaban.

Se ejecuta con ``tools/run_blender_tests.py``. Las carpetas son de unidades simuladas: nunca
se abren.
"""

import importlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import fingerprint_diff, module_name
from tests.support.fake_layout import draw

VARIABLE = "GEOBLENDER_READ_ONLY_DIRS"
DOSSIERS = "Q:\\expedientes"  # unidad de red simulada (la prueba nunca la abre)
OTHERS = "Q:\\otros"
CLIENTS = "R:\\clientes"
WM_PROPERTY = "geoblender_provenance"
VIEW_GROUP = "GEOBLENDER_PG_core_provenance"
ROW_COLLECTIONS = {
    "parameters": "GEOBLENDER_PG_core_parameter_row",
    "parameter_history": "GEOBLENDER_PG_core_parameter_history_row",
    "inputs": "GEOBLENDER_PG_core_input_row",
    "stale": "GEOBLENDER_PG_core_stale_row",
    "lineage": "GEOBLENDER_PG_core_lineage_row",
}
LABEL = "Carpetas de solo lectura"
EMPTY_TEXT = ("No hay ninguna carpeta de solo lectura: ni la variable GEOBLENDER_READ_ONLY_DIRS "
              "ni las preferencias de Geoblender declaran ninguna, así que los expedientes de "
              "clientes no están protegidos de las escrituras de Geoblender.")
IGNORED_TEXT = ("No se tiene en cuenta la carpeta de solo lectura «relativa»: no es una ruta "
                "completa, con su unidad o de red.")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _without_variable():
    """``os.environ`` sin la variable de las carpetas de solo lectura (al salir, como estaba)."""
    values = {key: value for key, value in os.environ.items() if key != VARIABLE}
    return mock.patch.dict(os.environ, values, clear=True)


def _core_preferences() -> object:
    addon = bpy.context.preferences.addons[module_name()]
    return addon.preferences.core


def _float_properties(struct: bpy.types.Struct, path: str, seen: set[str]) -> list[str]:
    """Las propiedades flotantes de ``struct`` y de los grupos a los que apunta (``path`` es
    su ruta, para el mensaje)."""
    found: list[str] = []
    if struct.identifier in seen:
        return found
    seen.add(struct.identifier)
    for prop in struct.properties:
        if prop.identifier == "rna_type":
            continue
        where = f"{path}.{prop.identifier}"
        if prop.type == "FLOAT":
            found.append(where)
        elif prop.type in ("POINTER", "COLLECTION") and prop.fixed_type is not None:
            if prop.fixed_type.identifier.startswith("GEOBLENDER_"):
                found.extend(_float_properties(prop.fixed_type, where, seen))
    return found


class ProvenanceRegistrationTest(unittest.TestCase):
    """Parte de la extensión deshabilitada y fuera de ``sys.modules``."""

    def setUp(self) -> None:
        blender_ext.unload()
        self.addCleanup(blender_ext.unload)

    def test_register_and_unregister_leave_blender_as_it_was(self) -> None:
        """RF-008-32, RF-008-15, D16 (principio 8): habilitar pone
        ``WindowManager.geoblender_provenance``, ``Scene.geoblender.registry_seq`` (entero, 0,
        no animable), la preferencia ``core.read_only_folders`` (texto vacío) y el
        temporizador del aviso de las carpetas de solo lectura; deshabilitar lo quita todo y
        deja la huella de Blender como al principio de la sesión de pruebas."""
        self.enterContext(_without_variable())
        blender_ext.enable()
        provenance = _module("bl.props.provenance")
        session = _module("bl.ops.core_provenance")
        rna = bpy.types.WindowManager.bl_rna.properties[WM_PROPERTY]
        self.assertEqual((rna.type, rna.fixed_type.identifier), ("POINTER", VIEW_GROUP))
        view = getattr(bpy.context.window_manager, WM_PROPERTY)
        for name, group in ROW_COLLECTIONS.items():
            with self.subTest(filas=name):
                prop = view.bl_rna.properties[name]
                self.assertEqual((prop.type, prop.fixed_type.identifier), ("COLLECTION", group))
                self.assertEqual(len(getattr(view, name)), 0)
        seq = bpy.context.scene.geoblender.bl_rna.properties["registry_seq"]
        self.assertEqual((seq.type, seq.default, seq.is_animatable), ("INT", 0, False))
        self.assertEqual(bpy.context.scene.geoblender.registry_seq, 0)
        folders = _core_preferences().bl_rna.properties["read_only_folders"]
        self.assertEqual((folders.type, folders.default), ("STRING", ""))
        self.assertEqual(_core_preferences().read_only_folders, "")
        self.assertTrue(bpy.app.timers.is_registered(session.warn_read_only_dirs))
        classes = [*provenance.classes]
        self.assertTrue(all(cls.is_registered for cls in classes))

        blender_ext.disable()
        self.assertNotIn(WM_PROPERTY, bpy.types.WindowManager.bl_rna.properties)
        self.assertFalse(hasattr(bpy.types.WindowManager, WM_PROPERTY))
        self.assertEqual([cls.__name__ for cls in classes if cls.is_registered], [])
        self.assertFalse(bpy.app.timers.is_registered(session.warn_read_only_dirs))
        after = blender_ext.state_fingerprint()
        baseline = blender_ext.session_baseline()
        if after != baseline:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(baseline, after)))


class ProvenancePropsTest(unittest.TestCase):
    """Con la extensión habilitada una vez para todas."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.session = _module("bl.ops.core_provenance")
        cls.help = _module("bl.ui.help")
        cls.project_session = _module("bl.scene.project_session")
        cls.preferences = _module("bl.props.preferences")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def setUp(self) -> None:
        self.enterContext(_without_variable())
        prefs = _core_preferences()
        self.addCleanup(setattr, prefs, "read_only_folders", prefs.read_only_folders)
        prefs.read_only_folders = ""
        self.project_session.take_notices()
        self.addCleanup(self.project_session.take_notices)

    def view(self) -> object:
        return getattr(bpy.context.window_manager, WM_PROPERTY)

    def test_no_float_property(self) -> None:
        """ARQ-13, D16 (RF-008-32): ni las filas de los paneles (y sus filtros), ni
        ``Scene.geoblender``, ni el grupo ``core`` de las preferencias tienen una propiedad
        flotante: los valores van como texto ya presentado («35 %»)."""
        seen: set[str] = set()
        found = _float_properties(self.view().bl_rna, WM_PROPERTY, seen)
        found += _float_properties(bpy.context.scene.geoblender.bl_rna, "Scene.geoblender", seen)
        found += _float_properties(_core_preferences().bl_rna, "core", seen)
        self.assertEqual(found, [])
        self.assertTrue({VIEW_GROUP, *ROW_COLLECTIONS.values()} <= seen, seen)
        row = self.view().parameters.add()
        self.addCleanup(self.view().parameters.clear)
        row.value = "35 %"
        self.assertEqual(row.bl_rna.properties["value"].type, "STRING")
        filters = {name: self.view().bl_rna.properties[name] for name in
                   ("filter_module", "filter_kind", "filter_mark")}
        for name, prop in filters.items():
            with self.subTest(filtro=name):
                self.assertEqual((prop.type, prop.default), ("ENUM", "ALL"))
        self.assertIn("gis", filters["filter_module"].enum_items.keys())
        self.assertEqual(filters["filter_kind"].enum_items.keys(),
                         ["ALL", "MEDIDO", "CALCULADO", "ADOPTADO", "HIPOTESIS"])
        self.assertEqual(filters["filter_mark"].enum_items.keys(),
                         ["ALL", "UNCONFIRMED", "REVIEW"])

    def test_rows_are_not_saved_and_registry_seq_is(self) -> None:
        """D16, RF-008-32: guardar y abrir el ``.blend`` no trae las filas de los paneles (se
        regeneran desde el proyecto) y sí el número de la escena (``registry_seq`` = 7)."""
        tmp = Path(tempfile.mkdtemp(prefix="gb-t45-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.addCleanup(blender_ext.load_file)
        view = self.view()
        for name in ROW_COLLECTIONS:
            getattr(view, name).add()
        view.parameters[0].key = "demo.swell_factor"
        view.filter_kind = "HIPOTESIS"
        bpy.context.scene.geoblender.registry_seq = 7
        target = tmp / "vista.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(target))
        blender_ext.load_file()
        self.assertEqual(bpy.context.scene.geoblender.registry_seq, 0)
        blender_ext.load_file(target)
        self.assertEqual(bpy.context.scene.geoblender.registry_seq, 7)
        view = self.view()
        self.assertEqual({name: len(getattr(view, name)) for name in ROW_COLLECTIONS},
                         dict.fromkeys(ROW_COLLECTIONS, 0))
        self.assertEqual(view.filter_kind, "ALL")

    def test_read_only_dirs_join_variable_and_preference(self) -> None:
        """RF-008-15 (S-3): ``read_only_dirs()`` une las carpetas de la variable (separadas por
        «;») y las de la preferencia, con los valores de cada momento."""
        self.assertTrue(self.session.read_only_dirs().empty)
        os.environ[VARIABLE] = f"{DOSSIERS}; {OTHERS}"
        _core_preferences().read_only_folders = f"{CLIENTS};"
        dirs = self.session.read_only_dirs()
        self.assertEqual([str(f) for f in dirs.env_folders], [DOSSIERS, OTHERS])
        self.assertEqual([str(f) for f in dirs.preference_folders], [CLIENTS])
        self.assertEqual(dirs.ignored, ())
        _core_preferences().read_only_folders = ""
        self.assertEqual(self.session.read_only_dirs().preference_folders, ())

    def test_preferences_show_the_variable_folders(self) -> None:
        """RF-008-15 (plan §5.5): las preferencias dibujan el campo de las carpetas del usuario
        y, debajo, las de la variable, sin poder editarlas; con las dos vacías, el aviso; con
        una entrada que no es una ruta completa, el suyo."""
        prefs = bpy.context.preferences.addons[module_name()].preferences

        def drawn() -> object:
            return draw(self.preferences.GeoblenderPreferences, bpy.context,
                        core=prefs.core, ui=prefs.ui, jobs=prefs.jobs)

        layout = drawn()
        props = [item for item in layout.of_kind("prop") if item.target == "read_only_folders"]
        self.assertEqual([item.text for item in props], [LABEL])
        self.assertIn("La variable GEOBLENDER_READ_ONLY_DIRS no declara ninguna carpeta",
                      layout.texts())
        alerts = [item.text for item in layout.of_kind("label") if item.alert]
        self.assertEqual(alerts, [EMPTY_TEXT])

        os.environ[VARIABLE] = f"{DOSSIERS};{OTHERS}"
        prefs.core.read_only_folders = "relativa"
        layout = drawn()
        texts = layout.texts()
        start = texts.index("De la variable GEOBLENDER_READ_ONLY_DIRS:")
        self.assertEqual(texts[start + 1:start + 3], [DOSSIERS, OTHERS])
        props = [item.target for item in layout.of_kind("prop")]
        self.assertEqual(props.count("read_only_folders"), 1)  # las de la variable, etiquetas
        alerts = [item.text for item in layout.of_kind("label") if item.alert]
        self.assertEqual(alerts, [IGNORED_TEXT])

    def test_diagnostics_line(self) -> None:
        """RF-008-15 (plan §5.4.13): el diagnóstico de la instalación tiene la línea de las
        carpetas de solo lectura: con la variable y la preferencia vacías, el aviso; si no,
        cada carpeta con su origen."""
        rows = dict(self.help.diagnostics())
        self.assertEqual(rows[LABEL], EMPTY_TEXT)
        labels = [label for label, _value in self.help.diagnostics()]
        self.assertEqual(labels[labels.index(LABEL) + 1], "PROJ")
        os.environ[VARIABLE] = DOSSIERS
        _core_preferences().read_only_folders = CLIENTS
        rows = dict(self.help.diagnostics())
        self.assertEqual(rows[LABEL],
                         f"{DOSSIERS} ({VARIABLE}); {CLIENTS} (preferencias)")
        self.assertIn(f"{LABEL}: {DOSSIERS} ({VARIABLE}); {CLIENTS} (preferencias)",
                      self.help.diagnostics_text().splitlines())

    def test_warning_once_per_session(self) -> None:
        """RF-008-15 (S-3): con la variable y la preferencia vacías, el temporizador del
        arranque deja un aviso en la sesión (y en el registro técnico); una segunda vez, no.
        Con alguna carpeta declarada no avisa."""
        self.session.forget_read_only_warning()
        os.environ[VARIABLE] = DOSSIERS
        self.assertIsNone(self.session.warn_read_only_dirs())  # con una carpeta, nada
        self.assertEqual(self.project_session.take_notices(), [])

        self.session.forget_read_only_warning()
        del os.environ[VARIABLE]
        with self.assertLogs("geoblender.bl.scene", level="WARNING") as logs:
            self.assertIsNone(self.session.warn_read_only_dirs())
        self.assertEqual(self.project_session.take_notices(), [EMPTY_TEXT])
        self.assertEqual(len(logs.records), 1)
        self.session.warn_read_only_dirs()
        self.assertEqual(self.project_session.take_notices(), [])


if __name__ == "__main__":
    unittest.main()
