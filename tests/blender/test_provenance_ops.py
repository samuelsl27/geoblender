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

T46:

- ADR-0025 §2 (plan §5.3.4): habilitar registra las declaraciones de ``core`` (sus
  operaciones, el importador de capas, sus lectores de contenido y el parámetro del límite de
  los originales) y deshabilitar las quita.
- RF-008-58, RF-008-09, RNF-008-12 (plan §5.4.6): abrir un proyecto del esquema 2 no comprueba
  nada (la apertura no cambia): deja lo de la comprobación pendiente para la puerta y un
  temporizador persistente que la empieza un tic después, por pasos de 20 ms; avanzar el
  monitor a mano completa los ocho pasos y deja el informe; lo que la puerta pide hashear
  después se hace igual. Un proyecto del esquema 1 sin migrar no arranca nada y la sesión da
  el motivo que muestran los paneles; desactivar Geoblender quita el temporizador y cancela lo
  pendiente.

T47:

- RF-008-09, RNF-008-11 (plan §5.3.3; ADR-0025 §2): habilitar registra el tipo de trabajo
  ``core_content_hash`` y da a la sesión sus trabajos de hash, que van al lanzador de la sesión
  (seguidos en la barra de estado) con la ruta de la fuente aparte de la petición; la lista
  estática de lectores del trabajo es la de los lectores registrados que pueden ir a él.

T48 (plan §5.3.4 y §5.4.7), con un operador sintético de un módulo (``ProvenanceAwareOperator``)
que lanza el autodiagnóstico de la 004:

- RF-008-51, RF-008-20, RF-008-23: registra su operación «en curso» al empezar, la incorpora
  al terminar (``ingest_job_result``) y llama a ``mark_ingested``; hasta entonces, la lista de
  trabajos y la procedencia dicen «pendiente de incorporar»; descartar el trabajo en la lista
  la deja «no incorporada» con el motivo, y un trabajo que falla la deja fallida.
- RF-008-10, RF-008-61: con una entrada cambiada aguas arriba, ``ensure_ready`` abre el diálogo
  de Actualizar, Mantener la copia y Cancelar y no deja empezar la operación; con la
  comprobación de apertura en marcha, espera.
- RF-008-15: exportar a una carpeta de solo lectura (``read_only_dirs()`` con
  ``check_write_target``) se rechaza sin escribir nada, y crear un proyecto dentro, también.

Se ejecuta con ``tools/run_blender_tests.py``. Las carpetas son de unidades simuladas: nunca
se abren. En ``blender -b`` los temporizadores no corren: las pruebas avanzan el monitor
llamando a su función.
"""

import functools
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

import bpy
from bpy.props import BoolProperty, StringProperty

from tests.support import blender_ext
from tests.support.blender_ext import fingerprint_diff, module_name
from tests.support.core_fixtures import mark_schema, settings_values
from tests.support.fake_layout import draw
from tests.support.repo import ROOT

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
CORE_OPERATIONS = ("core.accept_review", "core.external_edit", "core.import_layer")
CORE_READERS = ("core.document@1", "core.gpkg_layer@1", "core.npz_mesh@1")
CORE_IMPORTERS = ("core.gpkg_layer",)
CORE_PARAMETERS = ("core.original_copy_limit",)
MIGRATE_TEXT = "Proyecto de esquema 1: migre el proyecto para usar la procedencia"
MAX_TICKS = 200  # un proyecto vacío se comprueba en una decena de pasos
HASH_WORKER = "core_content_hash"
JOB_WAIT_S = 30.0  # plazo de seguridad de un trabajo de hash en hilo
SYNTHETIC_OP = "jobs.provenance_selftest"  # el tipo de operación del operador sintético
SYNTHETIC_IDNAME = "gbtest.provenance_selftest"  # fuera del catálogo, como gbdemo.*
SELFTEST_PARAMS = {"op": "chunked_sum", "n": 1000, "chunks": 1, "sleep_s": 0.0}  # en hilo
PENDING_TEXT = "pendiente de incorporar"
DATA = ROOT / "tests" / "data" / "core" / "provenance"
LAYER = "limites"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _synthetic_operator(base: type) -> type:
    """El operador sintético de un módulo: lanza el autodiagnóstico de la 004 como la operación
    :data:`SYNTHETIC_OP` (que consume ``uses``) y, con ``ingest``, la incorpora al terminar;
    con ``export_path``, antes comprueba ese destino."""
    session = sys.modules[base.__module__]

    class GBTEST_OT_provenance_selftest(base, bpy.types.Operator):
        bl_idname = SYNTHETIC_IDNAME
        bl_label = "Self-test with provenance"
        bl_options = {"REGISTER"}
        provenance_op_type = SYNTHETIC_OP
        uses = ()  # lo que consume (sin anotación: no es una propiedad)

        ingest: BoolProperty(default=True)  # type: ignore[valid-type]
        fail: BoolProperty(default=False)  # type: ignore[valid-type]
        export_path: StringProperty(default="")  # type: ignore[valid-type]

        def provenance_inputs(self, context: object) -> tuple[object, ...]:
            return type(self).uses

        def execute(self, context: object) -> set[str]:
            if self.export_path and not self.check_write_target(self.export_path):
                return {"CANCELLED"}
            handle = self.begin(context, settings={"n": SELFTEST_PARAMS["n"]},
                                executor="job_thread")
            if handle is None:
                return {"CANCELLED"}
            params = dict(SELFTEST_PARAMS, fail_at=1) if self.fail else SELFTEST_PARAMS
            finish = (functools.partial(session.ingest_job_result, handle) if self.ingest
                      else None)
            job = self.launch_job(handle, "selftest", label="Prueba de la procedencia",
                                  params=params, on_finish=finish)
            return {"CANCELLED"} if job is None else {"FINISHED"}

    return GBTEST_OT_provenance_selftest


def _without_variable():
    """``os.environ`` sin la variable de las carpetas de solo lectura (al salir, como estaba)."""
    values = {key: value for key, value in os.environ.items() if key != VARIABLE}
    return mock.patch.dict(os.environ, values, clear=True)


def _core_preferences() -> object:
    addon = bpy.context.preferences.addons[module_name()]
    return addon.preferences.core


def _core_declarations() -> dict[str, tuple[str, ...]]:
    """Lo declarado por ``core`` en los registros de la extensión: tipos de operación,
    importadores, lectores de contenido y parámetros."""
    contract = _module("core.provenance.contract")
    readers = _module("core.content.readers")
    params = _module("core.params")
    found = {"operations": contract.OPERATIONS, "importers": contract.IMPORTERS,
             "readers": readers.READERS, "parameters": params.DEFINITIONS}
    return {name: tuple(sorted(key for key in view if key.startswith("core.")))
            for name, view in found.items()}


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
        deja la huella de Blender como al principio de la sesión de pruebas. T46 (ADR-0025
        §2): también registra las declaraciones de ``core`` y escucha los cambios de proyecto,
        y deshabilitar lo quita. T47 (RF-008-09; plan §5.3.3): y el tipo de trabajo
        ``core_content_hash``, con los trabajos de hash de la sesión. T48 (RF-008-23): y la
        escucha de las carpetas de trabajos borradas y la nota «pendiente de incorporar» de
        la lista de trabajos."""
        self.enterContext(_without_variable())
        blender_ext.enable()
        provenance = _module("bl.props.provenance")
        session = _module("bl.ops.core_provenance")
        project_session = _module("bl.scene.project_session")
        self.assertEqual(_core_declarations(), {
            "operations": CORE_OPERATIONS, "importers": CORE_IMPORTERS,
            "readers": CORE_READERS, "parameters": CORE_PARAMETERS})
        self.assertIn(session.on_project_changed, project_session.listeners())
        jobs_ops = _module("bl.ops.jobs")
        job_list = _module("bl.ui.jobs")
        self.assertIn(session.on_jobs_removed, jobs_ops.removal_listeners())
        self.assertIs(job_list.note_provider(), session.job_note)
        self.assertFalse(bpy.app.timers.is_registered(session.check_tick))  # sin proyecto
        heavy = ("core.provenance.importer", "core.provenance.gate", "core.provenance.checks")
        self.assertEqual([name for name in heavy if f"{module_name()}.{name}" in sys.modules],
                         [])  # se cargan al usarlos
        workers = _module("jobs.catalog").WORKERS
        content_hash = _module("jobs.content_hash")
        self.assertIs(workers.get(HASH_WORKER), content_hash.WORKER_INFO)
        self.assertIsInstance(session.SESSION.hash_jobs, content_hash.ContentHashJobs)
        importer = _module("core.provenance.importer")
        self.assertEqual([item.reader_id for item in importer.CORE_IMPORTERS],
                         list(CORE_IMPORTERS))
        registered = _module("core.provenance.contract").IMPORTERS[CORE_IMPORTERS[0]]
        with mock.patch.object(importer, "reimport_layer", return_value="hecho") as reimport:
            self.assertEqual(registered.reimport("petición"), "hecho")
        reimport.assert_called_once_with("petición")
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
        self.assertEqual(_core_declarations(), {
            "operations": (), "importers": (), "readers": (), "parameters": ()})
        self.assertNotIn(session.on_project_changed, project_session.listeners())
        self.assertNotIn(session.on_jobs_removed, jobs_ops.removal_listeners())
        self.assertIsNone(job_list.note_provider())
        self.assertNotIn(HASH_WORKER, workers)
        self.assertIsNone(session.SESSION.hash_jobs)
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


class ProvenanceSessionTest(unittest.TestCase):
    """La sesión de la procedencia, con la extensión habilitada una vez para todas y una
    carpeta temporal para los proyectos."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.session = _module("bl.ops.core_provenance")
        cls.ps = _module("bl.scene.project_session")
        cls.core = _module("core.project")
        cls.checks = _module("core.provenance.checks")
        cls.gate = _module("core.provenance.gate")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gb-t46-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(self.ps.take_notices)
        self.addCleanup(self.ps.close)
        self.ps.take_notices()
        self.monitor = self.session.SESSION

    def create(self) -> object:
        """Un proyecto nuevo (del esquema 2), abierto en escritura y aún fuera de la sesión."""
        settings = self.core.ProjectSettings(**settings_values())
        return self.core.create_project(self.tmp, settings, self.ps.session(),
                                        self.ps.userdata()).project

    def run_checks(self) -> list[object]:
        """Avanza el monitor a mano hasta que se retira; devuelve el progreso de cada tic."""
        shown: list[object] = []
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                return shown
            shown.append(self.monitor.progress)
        self.fail("la comprobación no termina")

    def test_checks_start_one_tick_after_opening(self) -> None:
        """RF-008-58, RF-008-09, RNF-008-12: al abrir un proyecto del esquema 2 no se comprueba
        nada (la apertura no cambia), pero la puerta ya espera por todo y queda el temporizador
        persistente; el primer tic empieza la comprobación de apertura (con lo que se pueda
        escribir, el ``CheckState`` del proyecto y pasos de 20 ms) y avanzarla a mano recorre
        sus pasos sin retroceder, deja el informe registrado, sus avisos en los de la sesión, y
        retira el temporizador. Lo que la puerta pide hashear después se hace con los pasos 7 y
        8; cerrar el proyecto lo olvida todo."""
        self.assertEqual(self.session.PROVENANCE_SCHEMA, self.checks.PROVENANCE_SCHEMA)
        monitor = self.monitor
        project = self.create()
        foreign = project.root / "rasters" / "ajeno.txt"
        foreign.write_text("de otro programa", encoding="utf-8")
        with mock.patch.object(self.checks, "open_check_steps",
                               wraps=self.checks.open_check_steps) as started:
            self.ps.attach(project)
            self.assertEqual(started.call_count, 0)
            self.assertTrue(bpy.app.timers.is_registered(self.session.check_tick))
            self.assertIs(monitor.project, project)
            self.assertIsNone(monitor.unavailable())
            self.assertTrue(monitor.running)
            self.assertIsNone(monitor.progress)
            self.assertTrue(monitor.pending.is_pending("input", "cualquiera"))
            self.assertEqual(monitor.status_text(), "Comprobando el proyecto… 0 %")
            shown = self.run_checks()
        started.assert_called_once()
        self.assertIs(started.call_args.args[0], project)
        kwargs = started.call_args.kwargs
        self.assertEqual((kwargs["write"], kwargs["budget_s"]), (True, 0.02))
        self.assertIs(kwargs["pending"], monitor.pending)
        phases = list(dict.fromkeys(step.phase for step in shown))
        self.assertEqual((phases[0], phases[-1]), ("foto", "registro"))
        self.assertLessEqual(set(phases), set(self.checks.OPEN_CHECK_STEPS))
        done = [step.done for step in shown]
        self.assertEqual(done, sorted(done))
        report = monitor.report
        self.assertIsInstance(report, self.checks.OpenCheckOutcome)
        self.assertTrue(report.writing and report.recorded)
        self.assertEqual([item.name for item in report.orphans.foreign_files],
                         ["rasters/ajeno.txt"])
        self.assertEqual(self.ps.take_notices(), list(report.texts("es")))
        self.assertEqual(monitor.percent, 100)
        self.assertFalse(monitor.running or monitor.pending.running)
        self.assertIsNone(monitor.status_text())
        self.assertFalse(bpy.app.timers.is_registered(self.session.check_tick))

        operations = _module("core.provenance.operations")
        asked = self.gate.PendingItem(operations.ItemKind.INPUT, "ya-no-esta", "Limites_v1",
                                      self.gate.PendingReason.HASHING)
        self.assertTrue(monitor.pending.request_hash(asked))
        self.assertTrue(monitor.request_hashes())
        self.assertTrue(bpy.app.timers.is_registered(self.session.check_tick))
        self.assertEqual(self.run_checks()[-1].phase, "registro")
        self.assertEqual(monitor.pending.requests, ())
        self.assertIs(monitor.report, report)
        self.assertFalse(monitor.request_hashes())  # nada pedido: nada que hacer

        self.ps.close()
        self.assertIsNone(monitor.project)
        self.assertIsNone(monitor.report)
        self.assertEqual(monitor.unavailable(), "Abra un proyecto")

    def test_schema_1_project_starts_nothing(self) -> None:
        """RF-008-58 (plan §5.3.2 y §5.4.6): un proyecto del esquema 1 sin migrar (en solo
        lectura «sin migrar») no arranca ninguna comprobación ni deja nada pendiente para la
        puerta, y la sesión da el motivo que muestran los paneles."""
        project = self.create()
        root = project.root
        project.close()
        mark_schema(root, 1)
        opened = self.core.open_project(root, self.ps.session(), self.ps.userdata()).project
        self.assertEqual(opened.read_only_reason, self.core.ReadOnlyCode.NOT_MIGRATED)
        self.ps.attach(opened)
        monitor = self.monitor
        self.assertIs(monitor.project, opened)
        self.assertEqual(monitor.unavailable(), MIGRATE_TEXT)
        self.assertFalse(monitor.running or monitor.pending.running)
        self.assertFalse(bpy.app.timers.is_registered(self.session.check_tick))
        self.assertIsNone(self.session.check_tick())
        self.assertIsNone(monitor.progress)
        self.assertIsNone(monitor.report)
        self.assertIsNone(monitor.status_text())

    def test_a_failing_check_stops_and_says_so(self) -> None:
        """RF-008-58: si la comprobación falla, el monitor se para (sin temporizador), la
        puerta deja de esperar y queda un aviso con el motivo (y el error en el registro
        técnico)."""
        def broken(*_args: object, **_kwargs: object):
            raise OSError("disco desconectado")
            yield  # un generador, como el de verdad

        self.ps.attach(self.create())
        with (mock.patch.object(self.checks, "open_check_steps", broken),
              self.assertLogs("geoblender.bl.ops", level="ERROR")):
            self.assertIsNone(self.session.check_tick())
        self.assertFalse(self.monitor.running or self.monitor.pending.running)
        self.assertFalse(bpy.app.timers.is_registered(self.session.check_tick))
        self.assertIsNone(self.monitor.report)
        self.assertEqual(self.ps.take_notices(),
                         ["La comprobación del proyecto se ha parado: disco desconectado"])

    def test_disabling_cancels_the_checks(self) -> None:
        """RF-008-58 (principio 8): con la comprobación a medias, desactivar Geoblender quita
        el temporizador y cancela lo pendiente: la comprobación no sigue, la puerta deja de
        esperar y la sesión olvida el proyecto."""
        monitor = self.monitor
        self.ps.attach(self.create())
        self.assertIsNotNone(self.session.check_tick())
        pending = monitor.pending
        self.assertTrue(monitor.running and pending.running)
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        self.assertFalse(bpy.app.timers.is_registered(self.session.check_tick))
        self.assertFalse(monitor.running or pending.running)
        self.assertIsNone(monitor.project)
        self.assertIsNone(monitor.report)

    def test_hash_jobs_go_to_the_session_runner(self) -> None:
        """RF-008-09, RNF-008-11 (plan §5.3.3; ADR-0025 §2): la lista estática de lectores del
        trabajo ``core_content_hash`` es la de los lectores registrados que pueden ir a él; un
        trabajo de hash de la sesión va al lanzador de la sesión con el monitor de los trabajos
        (que lo sigue en la barra de estado), con la ruta de la fuente aparte de la petición, da
        el hash del hilo y, al recogerlo, queda incorporado (sin sus entradas)."""
        worker = _module("workers.core_content_hash")
        readers = _module("core.content.readers")
        self.assertEqual(sorted(found.id for found in worker.worker_readers()),
                         sorted(found.id for found in readers.READERS.values() if found.worker))
        jobs_ops = _module("bl.ops.jobs")
        records = _module("jobs.records")
        self.addCleanup(jobs_ops.MONITOR.stop)
        document = self.tmp / "fuentes" / "informe.bin"
        document.parent.mkdir()
        document.write_bytes(os.urandom(3 << 20))
        found = readers.reader("core.document@1")
        request = self.checks.HashRequest("uid-informe", "informe", found.id, "document", {},
                                          {}, {"main": document}, "gbch/1",
                                          document.stat().st_size)
        hash_jobs = self.monitor.hash_jobs
        with mock.patch.object(jobs_ops.MONITOR, "submit",
                               wraps=jobs_ops.MONITOR.submit) as submitted:
            handle = hash_jobs.submit(request)
        self.assertEqual(submitted.call_args.kwargs["paths"], {"source_main": document})
        self.assertTrue(jobs_ops.MONITOR.watching)
        deadline = time.monotonic() + JOB_WAIT_S
        while handle.result() is None and time.monotonic() < deadline:
            jobs_ops.tick()  # en «blender -b» no corren los temporizadores
            time.sleep(0.01)
        expected = readers.read_content(found, found.request("document", {},
                                                             {"main": document}))
        self.assertEqual(hash_jobs.poll(handle), self.checks.HashResult(digest=expected))
        text = (handle.job_dir.path / "request.json").read_text("utf-8")
        for shown in (str(self.tmp), json.dumps(str(self.tmp))[1:-1]):
            self.assertNotIn(shown, text)
        self.assertIsNotNone(records.read_record(handle.job_dir).ingested_at)
        self.assertEqual(records.read_record(handle.job_dir).executor, "inprocess")

    # Ayudas para los módulos (T48) --------------------------------------------------------

    def synthetic(self) -> type:
        """Registra el tipo de operación y el operador sintéticos hasta el final de la
        prueba."""
        contract = _module("core.provenance.contract")
        contract.register_operation(contract.OperationDef(
            SYNTHETIC_OP, "1.0", "jobs", "Self-test with provenance", False))
        self.addCleanup(contract.unregister_operation, SYNTHETIC_OP)
        cls = _synthetic_operator(self.session.ProvenanceAwareOperator)
        bpy.utils.register_class(cls)
        self.addCleanup(bpy.utils.unregister_class, cls)
        return cls

    def snapshot(self, job_uid: str) -> object:
        runner = _module("bl.ops.jobs").MONITOR.runner
        return next(found for found in runner.snapshots() if found.job_uid == job_uid)

    def finish(self, job_uid: str) -> object:
        """Avanza el monitor de los trabajos a mano hasta que el trabajo termina (y se llama a
        su aviso de fin); devuelve su foto."""
        jobs_ops = _module("bl.ops.jobs")
        deadline = time.monotonic() + JOB_WAIT_S
        while time.monotonic() < deadline:
            jobs_ops.tick()  # en «blender -b» no corren los temporizadores
            snapshot = self.snapshot(job_uid)
            if not snapshot.active:
                return snapshot
            time.sleep(0.002)
        self.fail(f"el trabajo {job_uid} no termina")

    def launched(self) -> tuple[str, str]:
        """El trabajo pendiente de incorporar que acaba de lanzar el operador sintético y su
        operación."""
        (found,) = self.session.pending_ingests().items()
        return found

    @staticmethod
    def operation(project: object, uid: str) -> tuple[object, ...]:
        with project.read() as conn:
            return conn.execute("SELECT status, executor, job_uid, interpreter, status_reason "
                                "FROM gb_operation WHERE uid = ?", (uid,)).fetchone()

    def test_job_operation_is_ingested_when_it_ends(self) -> None:
        """RF-008-51, RF-008-20, RF-008-23 (plan §5.3.4 «Calcular» y §5.4.7): el operador
        sintético de un módulo (``ProvenanceAwareOperator``) registra su operación «en curso»
        al empezar y lanza el autodiagnóstico de la 004 con su ``operation_uid``; hasta
        incorporarla, la lista de trabajos y la procedencia dicen «pendiente de incorporar»; al
        terminar, ``ingest_job_result`` la incorpora con la procedencia técnica del trabajo y
        llama a ``mark_ingested``. Sin incorporarla, descartar el trabajo en la lista de
        trabajos la deja «no incorporada» con el motivo; un trabajo que falla la deja fallida
        con el motivo de la 004 y queda incorporado."""
        self.synthetic()
        project = self.create()
        self.ps.attach(project)
        jobs_ops = _module("bl.ops.jobs")
        job_list = _module("bl.ui.jobs")
        lineage = _module("core.provenance.lineage")
        self.addCleanup(jobs_ops.MONITOR.stop)

        self.assertEqual(bpy.ops.gbtest.provenance_selftest("EXEC_DEFAULT"), {"FINISHED"})
        job_uid, op_uid = self.launched()
        snapshot = self.snapshot(job_uid)
        request = json.loads((snapshot.folder / "request.json").read_text("utf-8"))
        self.assertEqual((request["operation_uid"], request["project_uid"], request["owner"]),
                         (op_uid, project.uid, "jobs"))
        self.assertEqual(self.operation(project, op_uid)[:3], ("running", "job_thread", None))
        self.assertEqual(lineage.result_state(project, op_uid).text(), PENDING_TEXT)
        self.assertIn(PENDING_TEXT, job_list.details_text(snapshot))
        snapshot = self.finish(job_uid)
        self.assertEqual((snapshot.state, snapshot.ingested), ("succeeded", True))
        self.assertNotIn(PENDING_TEXT, job_list.details_text(snapshot))
        self.assertEqual(self.session.pending_ingests(), {})
        status, executor, job, interpreter, _reason = self.operation(project, op_uid)
        self.assertEqual((status, executor, job), ("done", "job_thread", job_uid))
        self.assertEqual(json.loads(interpreter)["kind"], "blender")
        self.assertTrue(lineage.result_state(project, op_uid).saved)
        self.assertFalse((snapshot.folder / "out").exists())  # mark_ingested: sin resultados

        self.assertEqual(bpy.ops.gbtest.provenance_selftest("EXEC_DEFAULT", ingest=False),
                         {"FINISHED"})
        job_uid, op_uid = self.launched()
        snapshot = self.finish(job_uid)
        self.assertEqual((snapshot.state, snapshot.ingested), ("succeeded", False))
        self.assertIn(PENDING_TEXT, job_list.details_text(snapshot))
        self.assertEqual(lineage.result_state(project, op_uid).text(), PENDING_TEXT)
        self.assertEqual(bpy.ops.geoblender.jobs_clean("EXEC_DEFAULT", scope="ONE",
                                                       job_uid=job_uid), {"FINISHED"})
        self.assertEqual(self.session.pending_ingests(), {})
        state = lineage.result_state(project, op_uid)
        self.assertEqual(state.state, lineage.ResultState.NOT_INGESTED)
        self.assertEqual(state.text(), "no incorporada: se descartó su trabajo «Prueba de la "
                                       "procedencia» en la lista de trabajos sin incorporarlo")

        self.assertEqual(bpy.ops.gbtest.provenance_selftest("EXEC_DEFAULT", ingest=False,
                                                            fail=True), {"FINISHED"})
        job_uid, op_uid = self.launched()
        snapshot = self.finish(job_uid)
        self.assertEqual((snapshot.state, snapshot.ingested), ("failed", True))
        self.assertEqual(self.session.pending_ingests(), {})
        status, _executor, _job, _interpreter, reason = self.operation(project, op_uid)
        self.assertEqual((status, reason), ("failed", snapshot.error.text))

    def test_gate_and_write_target_before_operating(self) -> None:
        """RF-008-58, RF-008-10, RF-008-61, RF-008-15 (plan §5.3.4 y §5.4.13): con la
        comprobación de apertura en marcha, ``ensure_ready`` espera y lo dice; con una entrada
        cambiada aguas arriba, al lanzar la orden abre el diálogo de RF-008-10 (Actualizar,
        Mantener la copia, Cancelar) con esa entrada y no empieza la operación (sin diálogo
        si se ejecuta desde un guion). Exportar a una carpeta de solo lectura o a la carpeta de
        la fuente de una entrada se rechaza nombrándola, sin escribir nada, y crear un
        proyecto dentro de una carpeta de solo lectura, también."""
        cls = self.synthetic()
        self.enterContext(_without_variable())
        prefs = _core_preferences()
        self.addCleanup(setattr, prefs, "read_only_folders", prefs.read_only_folders)
        dossiers = self.tmp / "expedientes"
        dossiers.mkdir()
        prefs.read_only_folders = str(dossiers)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_new_project(
                "EXEC_DEFAULT", directory=str(dossiers), name="Cantera", xmin="699500",
                ymin="4399500", xmax="700500", ymax="4400500")
        self.assertIn(f"«{dossiers}», una carpeta de solo lectura", str(caught.exception))
        self.assertEqual(list(dossiers.iterdir()), [])

        sources = self.tmp / "fuentes"
        sources.mkdir()
        source = sources / "Limites.gpkg"
        shutil.copyfile(DATA / "Limites_v1.gpkg", source)
        project = self.create()
        self.ps.attach(project)  # con la comprobación de apertura prevista
        importer = _module("core.provenance.importer")
        imported = importer.import_layer(project, LAYER, source=source)
        cls.uses = (_module("core.provenance.operations").Use(imported.dataset.name,
                                                              "boundary"),)
        reports: list[tuple[set[str], str]] = []

        def report(kind: set[str], text: str) -> None:
            reports.append((set(kind), text))

        self.assertIsNone(self.session.ensure_ready(SYNTHETIC_OP, cls.uses, report=report))
        ((kind, text),) = reports
        self.assertEqual(kind, {"WARNING"})
        self.assertTrue(text.startswith("Comprobando el proyecto…: espere a que termine ("),
                        text)
        self.assertIn("«Limites»", text)
        self.monitor.cancel()

        shutil.copyfile(DATA / "Limites_v2.gpkg", source)
        later = time.time() + 10
        os.utime(source, (later, later))
        opened: list[tuple[object, set[str]]] = []
        real = self.session.open_input_dialog

        def spy(reason: object) -> set[str]:
            result = real(reason)
            opened.append((reason, result))
            return result

        # En «blender -b» no hay evento: «INVOKE_DEFAULT» ejecuta sin invoke. El invoke de la
        # base marca que la orden viene de la interfaz y ejecuta; la puerta, con el diálogo.
        launched = mock.Mock(provenance_dialog=False, execute=mock.Mock(return_value={"X"}))
        self.assertEqual(cls.invoke(launched, bpy.context, None), {"X"})
        self.assertTrue(launched.provenance_dialog)
        reports.clear()
        with mock.patch.object(self.session, "open_input_dialog", spy):
            self.assertIsNone(self.session.ensure_ready(SYNTHETIC_OP, cls.uses, report=report,
                                                        dialog=True))
        ((reason, result),) = opened
        self.assertEqual((reason.kind, reason.uid), (_module("core.provenance.gate").BlockKind
                                                     .INPUT_CHANGED, imported.input.uid))
        self.assertEqual(result, {"CANCELLED"})  # la orden provisional, hasta T52
        ((kind, text),) = reports
        self.assertEqual(kind, {"WARNING"})  # el diálogo ya lo enseña
        self.assertTrue(text.startswith("La entrada «Limites» ha cambiado desde su registro"),
                        text)
        with (mock.patch.object(self.session, "open_input_dialog", spy),
              self.assertRaises(RuntimeError) as caught):
            bpy.ops.gbtest.provenance_selftest("EXEC_DEFAULT")  # desde un guion: sin diálogo
        self.assertIn("La entrada «Limites» ha cambiado", str(caught.exception))
        self.assertEqual(len(opened), 1)

        cls.uses = ()
        for target, expected in (
            (dossiers / "plano.dxf", f"La carpeta «{dossiers}» es de solo lectura"),
            (sources / "copia.gpkg", "No se puede escribir en la carpeta «fuentes»: contiene "
                                     "la fuente de la entrada «Limites»."),
        ):
            with self.subTest(destino=target.name):
                with self.assertRaises(RuntimeError) as caught:
                    bpy.ops.gbtest.provenance_selftest("EXEC_DEFAULT", export_path=str(target))
                self.assertIn(expected, str(caught.exception))
                self.assertFalse(target.exists())
        with project.read() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                                          (SYNTHETIC_OP,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT status FROM gb_input WHERE uid = ?",
                                          (imported.input.uid,)).fetchone()[0], "changed")
        self.assertEqual(self.session.pending_ingests(), {})


if __name__ == "__main__":
    unittest.main()
