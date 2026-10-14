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

T51 (Registro de entradas y Comprobar cambios en las entradas):

- RF-008-16, RF-008-13: ``geoblender.core_show_inputs`` abre ``GEOBLENDER_PT_core_inputs``,
  cuya lista (``GEOBLENDER_UL_core_inputs``) dice de cada entrada su estado —también
  «comprobando» mientras la comprobación la tiene pendiente y «no localizable» si no se
  encontró su fuente—, su tipo, su entrega, sus CRS declarados, su hash de contenido abreviado
  y si guarda su original; en solo lectura se consulta, y lo demás está desactivado con el
  motivo.
- RF-008-09, RF-008-21: ``geoblender.core_check_inputs`` hashea en segundo plano (con el
  temporizador de la sesión, tras la comprobación en marcha) todas las entradas y los datos
  del proyecto: encuentra cambiada una fuente con otro contenido y el mismo tamaño y fecha, y
  lo dice.

T52 (Actualizar, Mantener la copia, Descartar… y Editar… una entrada), con el área de la
demostración de la 008 calculada con el límite:

- RF-008-10, RF-008-11, RF-008-12, RF-008-61: ``geoblender.core_resolve_input`` abre el diálogo
  de una entrada cambiada (el aviso de la spec §8, Actualizar, Mantener la copia y el motivo;
  cancelarlo no cambia nada); Mantener la copia la saca de «⚠ n entradas»; Actualizar la
  reimporta con el importador de su módulo (si pide otra vez sus ajustes, se los pide a la
  persona) como una entrada nueva que la sustituye y deja obsoleto lo que dependía de ella.
- RF-008-55: ``geoblender.core_discard_input`` exige el motivo, no borra nada y deja obsoleto lo
  que dependía de la entrada; ``geoblender.core_edit_input`` (D-11) cambia el nombre y la
  entrega sin cambiar la entrada. En solo lectura, ninguna se puede.

T53 (Recalcular lo obsoleto), con los bancos, los años por banco y el grupo acoplado de los
acopios de la demostración de la 008:

- RF-008-26, RF-008-25, RF-008-28: ``geoblender.core_recompute_stale`` es un modal con
  temporizador que recalcula, en orden de dependencia y por unidades (las dos operaciones del
  grupo juntas), lo obsoleto de un elemento (el botón Recalcular de su fila en el panel de lo
  obsoleto), lo que depende de un cambio (la producción) o todo, como operaciones nuevas que
  sustituyen a las anteriores, con su progreso, y deja la cuenta de «! n obsoletos» a 0; Esc a
  mitad deja lo ya recalculado y lo demás obsoleto. No empieza mientras se comprueba el
  proyecto ni con otro recálculo en marcha, y en solo lectura no está disponible.

T54 (lo que no se puede usar, dar por buena, capas sin registrar y cancelar), con la
demostración de la 008:

- RF-008-56, RF-008-21: los años por banco (no editables) editados fuera quedan bloqueados y
  salen, con su aviso, en el panel de lo obsoleto con Aceptar la edición y Recalcular
  (``geoblender.core_resolve_dataset``); recalcularlos repite su operación y aceptar la edición
  pide el motivo.
- RF-008-27: la edición aceptada, con la producción cambiada, espera revisión a mano: el panel
  la lista con «Dar por buena…» (``geoblender.core_accept_review``), que pide el motivo.
- RF-008-57, RF-008-52: una tabla eliminada desde QGIS «falta» y se recalcula; lo importado
  que pierde una columna está dañado y solo se reimporta.
- RF-008-62: una capa creada desde QGIS en el proyecto sale en el registro de entradas con
  Registrar como entrada… e Ignorar… (``geoblender.core_resolve_unregistered``).
- RF-008-58: «Cancelar las comprobaciones» (``geoblender.core_cancel_checks``, el botón del
  campo «Comprobando el proyecto…») para la comprobación en marcha enseguida.

T65 (RNF-008-12): la sesión carga ``core.provenance.checks`` y hace una recolección completa del
GC de Python al recibir un proyecto con la procedencia, no en un tic de la comprobación.

T57 (Ctrl+Z; el detalle, en ``test_provenance_undo.py``):

- RF-008-32: Mantener la copia, Descartar…, Editar… y lo recalculado se apuntan en el diario de
  Ctrl+Z de la sesión (su clase y su nombre o su tipo) y sellan la escena con su número.

En ``blender -b`` no hay bucle de eventos: las pruebas toman el modal de
``window.modal_operators`` y le pasan los eventos ``TIMER`` y ``ESC``.

Se ejecuta con ``tools/run_blender_tests.py``. Las carpetas son de unidades simuladas: nunca
se abren. En ``blender -b`` los temporizadores no corren: las pruebas avanzan el monitor
llamando a su función.
"""

import functools
import gc
import importlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy
from bpy.props import BoolProperty, StringProperty

from tests.support import blender_ext
from tests.support.blender_ext import fingerprint_diff, module_name
from tests.support.core_fixtures import mark_schema, settings_values
from tests.support.fake_layout import FakeLayout, draw
from tests.support.provenance_demo import (
    BENCH_YEARS,
    DETECT_STOCKPILES,
    FILTER_STOCKPILES,
    PRODUCTION,
    SWELL_FACTOR,
    YEARS_FIGURE,
    YEARS_TABLE,
    Demo,
)
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
# Los lectores de contenido (spec 006, T40), los tipos de trabajo y las definiciones de
# parámetros (T26) de la topografía, los registra bl/ops/gis.py.
GIS_READERS = ("gis.asc@1", "gis.geotiff@1", "gis.gpkg_layer@1", "gis.points_text@1",
               "gis.xyz_grid@1")
DATA = ROOT / "tests" / "data" / "core" / "provenance"
LAYER = "limites"
INPUTS_PANEL = "GEOBLENDER_PT_core_inputs"
INPUTS_LIST = "GEOBLENDER_UL_core_inputs"
CHECK_INPUTS = "geoblender.core_check_inputs"
RESOLVE_INPUT = "geoblender.core_resolve_input"
DISCARD_INPUT = "geoblender.core_discard_input"
EDIT_INPUT = "geoblender.core_edit_input"
INPUT_BUTTONS = {(RESOLVE_INPUT, "Actualizar"), (RESOLVE_INPUT, "Mantener la copia"),
                 (DISCARD_INPUT, "Descartar entrada…"), (EDIT_INPUT, "Editar entrada…")}
HEADER = ["Nombre", "Estado", "Tipo", "Entrega", "Entregada por", "CRS horizontal",
          "CRS vertical", "Hash de contenido", "Original"]
READ_ONLY = "Proyecto en solo lectura:"  # y el motivo del proyecto
UPDATE_REASON = "Nueva entrega del cliente"
KEPT = "cambiada · se mantiene la copia"
DISCARDED = "descartada · registro, no usar"
RECOMPUTE = "geoblender.core_recompute_stale"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESC = SimpleNamespace(type="ESC", value="PRESS")
STOCKPILE_UNIT = (DETECT_STOCKPILES, FILTER_STOCKPILES)  # el grupo, en su orden
RESOLVE_DATASET = "geoblender.core_resolve_dataset"
ACCEPT_REVIEW = "geoblender.core_accept_review"
RESOLVE_UNREGISTERED = "geoblender.core_resolve_unregistered"
BLOCKED = ("La capa «demo_bench_years» se editó fuera de Geoblender y no se edita a mano: "
           "acepte la edición con un motivo, recalcule o reimporte")
OFFERS = ("Aceptar la edición", "Recalcular", "Reimportar")
IMPORTED = "core_imported_limites"


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


def _foreign(project: object, *statements: str) -> None:
    """Otro programa (QGIS) escribe en ``project.gpkg`` con su propia conexión."""
    with closing(sqlite3.connect(project.database_path, isolation_level=None)) as conn:
        for sql in statements:
            conn.execute(sql)


def _view() -> object:
    return bpy.context.window_manager.geoblender_provenance


def _buttons(layout: object, target: str) -> list[tuple[str, dict, bool]]:
    """Los botones de la orden ``target`` dibujados: su texto, sus propiedades y si están
    activos."""
    return [(item.text, vars(item.properties), item.enabled) for item in layout.items
            if item.kind == "operator" and item.target == target]


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
    """Parte de la extensión deshabilitada y fuera de ``sys.modules``
    (``blender_ext.fresh``)."""

    def setUp(self) -> None:
        self.enterContext(blender_ext.fresh())

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
        la lista de trabajos. T65 (RNF-008-12, RF-008-58; plan §5.4.6): la sesión carga
        ``core.provenance.checks`` al recibir un proyecto con la procedencia (no uno del esquema
        1), en lo que tarda abrir, y no en el primer tic de su comprobación (en frío son unos
        40 ms); y, si es grande (``MANY_DATASETS`` datos o más), hace antes una recolección
        completa del GC de Python, para que la que provocarían los objetos de su comprobación
        no caiga en un tic (uno pequeño no la hace)."""
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
        self.prepared_checks()
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

    def prepared_checks(self) -> None:
        """Lo de T65 en la prueba de registrar: con la extensión recién habilitada, sin
        ``core.provenance.checks`` cargado, recibir proyectos (del esquema 1, uno pequeño y uno
        «grande») y cerrarlos."""
        checks = f"{module_name()}.core.provenance.checks"
        core = _module("core.project")
        project_session = _module("bl.scene.project_session")
        tmp = Path(tempfile.mkdtemp(prefix="gb-t65-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        settings = core.ProjectSettings(**settings_values())
        session, userdata = project_session.session(), project_session.userdata()
        (tmp / "viejo").mkdir()
        (tmp / "nuevo").mkdir()
        old = core.create_project(tmp / "viejo", settings, session, userdata).project
        root = old.root
        old.close()
        mark_schema(root, 1)
        try:
            with mock.patch.object(gc, "collect", wraps=gc.collect) as collected:
                project_session.attach(core.open_project(root, session, userdata).project)
                self.assertFalse(checks in sys.modules, "un proyecto del esquema 1 la carga")
                project_session.close()
                project = core.create_project(tmp / "nuevo", settings, session,
                                              userdata).project
                root = project.root
                project_session.attach(project)
                self.assertTrue(checks in sys.modules, "recibir el proyecto no la carga")
                collected.assert_not_called()  # un proyecto pequeño
                self.assertIsNone(_module("bl.ops.core_provenance").SESSION.progress)
                project_session.close()
                with mock.patch.object(sys.modules[checks], "MANY_DATASETS", 0):
                    project_session.attach(core.open_project(root, session, userdata).project)
            collected.assert_called_once_with()
        finally:
            project_session.close()


class ProvenancePropsTest(unittest.TestCase):
    """Con la extensión habilitada una vez para todas."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.session = _module("bl.ops.core_provenance")
        cls.help = _module("bl.ui.help")
        cls.project_session = _module("bl.scene.project_session")
        cls.preferences = _module("bl.props.preferences")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

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
        blender_ext.release()
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
        blender_ext.release()

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

    def test_gis_readers_register_and_unregister(self) -> None:
        """RF-006-26, RF-008-09 (spec 006, T40; ADR-0025 §2; principio 8): con la extensión
        habilitada están los cinco lectores de contenido de ``gis`` y su lector de tablas de
        ``interop`` (``gis`` no puede importarlo, ARQ-07); ``bl/ops/gis.py`` los quita y los
        vuelve a poner, las dos cosas idempotentes, y quitarlos deja el registro como
        estaba."""
        gis_ops = _module("bl.ops.gis")
        readers = _module("core.content.readers")
        content = _module("gis.content")
        read_table = _module("interop.csv_tables").read_table

        def ours() -> list[str]:
            return sorted(key for key in readers.READERS if key.startswith("gis."))

        self.assertEqual(ours(), list(GIS_READERS))
        self.assertIs(content.table_reader(), read_table)
        self.addCleanup(gis_ops.register)  # la clase sigue con la extensión habilitada
        for _ in range(2):
            gis_ops.unregister()
            self.assertEqual((ours(), content.table_reader()), ([], None))
        before = dict(readers.READERS)
        for _ in range(2):
            gis_ops.register()
            self.assertEqual(ours(), list(GIS_READERS))
            self.assertIs(content.table_reader(), read_table)
        gis_ops.unregister()
        self.assertEqual(dict(readers.READERS), before)

    def test_gis_jobs_and_parameters_register_and_unregister(self) -> None:
        """RF-006-28, RF-008-01, RF-008-06 (spec 006, T26; plan 006 §5.3.4 y §5.6.1;
        principio 8): con la extensión habilitada están los trece tipos de trabajo de ``gis``
        (``jobs.catalog``, los de ``gis.jobs``) y sus 17 definiciones de parámetros
        (``core.params``); ``bl/ops/gis.py`` los quita y los vuelve a poner, las dos cosas
        idempotentes, y quitarlos deja los dos registros como estaban."""
        gis_ops = _module("bl.ops.gis")
        catalog = _module("jobs.catalog")
        params = _module("core.params")
        gis_jobs = _module("gis.jobs")
        gis_params = _module("gis.params")
        keys = sorted(defn.key for defn in gis_params.DEFINITIONS)

        def ours() -> tuple[list[str], list[str]]:
            workers = sorted(name for name in catalog.WORKERS if name.startswith("gis_"))
            return workers, sorted(key for key in params.DEFINITIONS if key.startswith("gis."))

        expected = (sorted(gis_jobs.WORKER_NAMES), keys)
        self.assertEqual((len(expected[0]), len(keys)), (13, 17))  # 3 tipos de la T29
        self.assertEqual(ours(), expected)
        for name in gis_jobs.WORKER_NAMES:
            self.assertIs(catalog.WORKERS[name], gis_jobs.WORKER_INFOS_BY_NAME[name])
        self.addCleanup(gis_ops.register)  # la clase sigue con la extensión habilitada
        for _ in range(2):
            gis_ops.unregister()
            self.assertEqual(ours(), ([], []))
        workers_before, params_before = dict(catalog.WORKERS), dict(params.DEFINITIONS)
        for _ in range(2):
            gis_ops.register()
            self.assertEqual(ours(), expected)
        gis_ops.unregister()
        self.assertEqual((dict(catalog.WORKERS), dict(params.DEFINITIONS)),
                         (workers_before, params_before))

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

        sent = len(jobs_ops.sent_reports())
        self.assertEqual(bpy.ops.gbtest.provenance_selftest("EXEC_DEFAULT", ingest=False,
                                                            fail=True), {"FINISHED"})
        job_uid, op_uid = self.launched()
        snapshot = self.finish(job_uid)
        self.assertEqual((snapshot.state, snapshot.ingested), ("failed", True))
        self.assertEqual(self.session.pending_ingests(), {})
        status, _executor, _job, _interpreter, reason = self.operation(project, op_uid)
        self.assertEqual((status, reason), ("failed", snapshot.error.text))
        # RF-004-07 (spec 006, T57): un trabajo que falla ya lo dice su aviso («Fallido» y el
        # mensaje del §8); su operación fallida no se dice otra vez.
        self.assertIsNone(jobs_ops.MONITOR.view().ending)
        self.assertEqual(jobs_ops.sent_reports()[sent:], ())

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
        # En «blender -b» la orden real no abre su diálogo: ejecuta sin decisión y no cambia nada.
        self.assertEqual(result, {"CANCELLED"})
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

    # Registro de entradas y Comprobar (T51) -----------------------------------------------

    def two_inputs(self) -> tuple[object, Path, Path, object, object]:
        """Un proyecto nuevo (aún fuera de la sesión) con dos entradas importadas de
        ``fuentes/``: «Limites» (``Limites_v1``, entregada por la propiedad) y «Vecino»
        (``Limites_v2``). Devuelve el proyecto, las dos fuentes y las dos entradas."""
        sources = self.tmp / "fuentes"
        sources.mkdir()
        first, second = sources / "Limites.gpkg", sources / "Vecino.gpkg"
        shutil.copyfile(DATA / "Limites_v1.gpkg", first)
        shutil.copyfile(DATA / "Limites_v2.gpkg", second)
        project = self.create()
        importer = _module("core.provenance.importer")
        limits = importer.import_layer(project, LAYER, source=first, received_at="2026-09-24",
                                       received_from="La propiedad").input
        neighbour = importer.import_layer(project, LAYER, source=second).input
        return project, first, second, limits, neighbour

    def show_inputs(self) -> object:
        """Proyecto ▸ Control ▸ Registro de entradas (``wm.call_panel`` sustituido): la vista
        de ``WindowManager`` con sus filas."""
        window = bpy.context.window_manager.windows[0]
        with mock.patch.object(self.session, "_call_panel", return_value={"FINISHED"}) as call:
            with bpy.context.temp_override(window=window):
                self.assertEqual(bpy.ops.geoblender.core_show_inputs(), {"FINISHED"})
        call.assert_called_once_with(INPUTS_PANEL)
        return bpy.context.window_manager.geoblender_provenance

    @staticmethod
    def input_rows(view: object) -> list[list[str]]:
        """Lo que dibuja la lista de entradas, fila a fila (los textos de cada una)."""
        found = []
        for index, row in enumerate(view.inputs):
            layout = FakeLayout()
            bpy.types.GEOBLENDER_UL_core_inputs.draw_item(
                SimpleNamespace(), bpy.context, layout, view, row, 0, view, "input_index", index)
            found.append(layout.texts())
        return found

    def test_input_register_lists_each_input_with_its_state(self) -> None:
        """RF-008-16, RF-008-13 (plan §5.5): sin proyecto, ni el registro ni Comprobar están
        disponibles. Con uno abierto, el registro de entradas lista cada entrada con su
        estado («comprobando» mientras la comprobación de apertura no la ha mirado; después,
        «vigente», o «no localizable» si no se encuentra su fuente), su tipo, su entrega, sus
        CRS horizontal y vertical, su hash de contenido abreviado (12 caracteres) y su
        original; el panel tiene la cabecera de las columnas, la lista, Actualizar, Mantener la
        copia, Descartar… y Editar… del seleccionado (de una vigente, solo Descartar… y Editar…,
        con su uid) y Comprobar. En solo lectura el registro se consulta, pero lo demás está
        desactivado con el motivo."""
        self.assertFalse(bpy.ops.geoblender.core_show_inputs.poll())
        self.assertFalse(bpy.ops.geoblender.core_check_inputs.poll())
        project, _first, second, limits, neighbour = self.two_inputs()
        second.unlink()  # «Vecino»: su fuente ya no está
        with project.write_transaction() as conn:  # como si guardase su original
            conn.execute("UPDATE gb_input SET original = 'stored' WHERE uid = ?", (limits.uid,))
        self.ps.attach(project)
        view = self.show_inputs()
        self.assertEqual([(row.uid, row.name, row.status) for row in view.inputs],
                         [(limits.uid, "Limites", "current"),
                          (neighbour.uid, "Vecino", "current")])
        self.assertEqual([texts[1] for texts in self.input_rows(view)],
                         ["comprobando", "comprobando"])
        self.run_checks()
        self.assertEqual(self.input_rows(view), [
            ["Limites", "vigente", "vectorial", "24/09/2026", "La propiedad", "EPSG:25830",
             "no aplica", limits.content_sha256[:12], "guardado"],
            ["Vecino", "no localizable", "vectorial", "—", "—", "EPSG:25830", "no aplica",
             neighbour.content_sha256[:12], "—"],
        ])
        panel = draw(bpy.types.GEOBLENDER_PT_core_inputs, bpy.context)
        self.assertEqual([item.target for item in panel.of_kind("template_list")],
                         [INPUTS_LIST])
        texts = panel.texts()
        start = texts.index(HEADER[0])
        self.assertEqual(texts[start:start + len(HEADER)], HEADER)
        buttons = {(item.target, item.text): item for item in panel.of_kind("operator")}
        self.assertLessEqual(INPUT_BUTTONS, set(buttons))
        self.assertEqual({key: buttons[key].enabled for key in INPUT_BUTTONS}, {
            (RESOLVE_INPUT, "Actualizar"): False, (RESOLVE_INPUT, "Mantener la copia"): False,
            (DISCARD_INPUT, "Descartar entrada…"): True, (EDIT_INPUT, "Editar entrada…"): True,
        })  # «Limites» está vigente: no hay cambio que decidir
        self.assertEqual(vars(buttons[(RESOLVE_INPUT, "Actualizar")].properties),
                         {"input_uid": limits.uid, "decision": "UPDATE"})
        self.assertEqual(vars(buttons[(RESOLVE_INPUT, "Mantener la copia")].properties),
                         {"input_uid": limits.uid, "decision": "KEEP"})
        for key in ((DISCARD_INPUT, "Descartar entrada…"), (EDIT_INPUT, "Editar entrada…")):
            self.assertEqual(vars(buttons[key].properties), {"input_uid": limits.uid})
        check = buttons[(CHECK_INPUTS, "Comprobar cambios en las entradas")]
        self.assertTrue(check.enabled)

        project.set_read_only(self.core.ReadOnlyCode.REQUESTED, "prueba")
        self.assertTrue(bpy.ops.geoblender.core_show_inputs.poll())
        self.assertFalse(bpy.ops.geoblender.core_check_inputs.poll())
        self.assertEqual(len(self.show_inputs().inputs), 2)
        panel = draw(bpy.types.GEOBLENDER_PT_core_inputs, bpy.context)
        self.assertFalse([item for item in panel.of_kind("operator") if item.enabled])
        reasons = [text for text in panel.texts() if text.startswith(READ_ONLY)]
        self.assertEqual(len(reasons), 1, panel.texts())
        self.assertIn("prueba", reasons[0])
        self.assertFalse(self.monitor.check_inputs())

    def test_check_inputs_hashes_everything_in_the_background(self) -> None:
        """RF-008-09, RF-008-21 (plan §5.3.2 y §5.4.2): Comprobar cambios en las entradas,
        lanzado con la comprobación de apertura en marcha, queda para después de ella y no
        hace nada al llamarla; todas las entradas activas están «comprobando». Los tics del
        temporizador la hacen por pasos (``full_check_steps`` con lo pendiente de la puerta,
        los trabajos de hash de la sesión y pasos de 20 ms): el hash de «Limites», con otro
        contenido y el mismo tamaño y fecha (el prefiltro de la apertura no lo ve), la deja
        cambiada, y lo dicen sus avisos y el resumen de lo comprobado; «Vecino» sigue
        vigente, con su comprobación anotada. El registro la enseña «cambiada»."""
        project, first, _second, limits, neighbour = self.two_inputs()
        seen = first.stat()
        shutil.copyfile(DATA / "Limites_v2.gpkg", first)
        os.utime(first, ns=(seen.st_atime_ns, seen.st_mtime_ns))
        self.assertEqual(first.stat().st_size, seen.st_size)
        monitor = self.monitor
        self.ps.attach(project)
        self.ps.take_notices()
        with mock.patch.object(self.checks, "full_check_steps",
                               wraps=self.checks.full_check_steps) as started:
            self.assertEqual(bpy.ops.geoblender.core_check_inputs(), {"FINISHED"})
            self.assertEqual(bpy.ops.geoblender.core_check_inputs(), {"FINISHED"})  # una vez
            started.assert_not_called()
            self.assertEqual([monitor.input_state(uid) for uid in (limits.uid, neighbour.uid)],
                             ["checking", "checking"])
            self.assertEqual(monitor.status_text(), "Comprobando el proyecto… 0 %")
            shown = self.run_checks()
        started.assert_called_once()
        self.assertIs(started.call_args.args[0], project)
        kwargs = started.call_args.kwargs
        self.assertIs(kwargs["pending"], monitor.pending)
        self.assertIs(kwargs["jobs"], monitor.hash_jobs)
        self.assertEqual(kwargs["budget_s"], 0.02)
        self.assertEqual(shown[-1].phase, "registro")
        self.assertIsNone(monitor.input_state(limits.uid))
        self.assertFalse(bpy.app.timers.is_registered(self.session.check_tick))
        with project.read() as conn:
            found = dict(conn.execute("SELECT name, status FROM gb_input"))
            checked = conn.execute("SELECT checked_at FROM gb_input_file WHERE input_uid = ?",
                                   (neighbour.uid,)).fetchone()[0]
        self.assertEqual(found, {"Limites": "changed", "Vecino": "current"})
        self.assertIsNotNone(checked)
        notices = self.ps.take_notices()
        self.assertTrue(any(text.startswith("La entrada «Limites» ha cambiado")
                            for text in notices), notices)
        self.assertEqual(notices[-1], "Comprobación terminada: 2 entradas y 2 datos "
                                      "comprobados")
        view = self.show_inputs()
        self.assertEqual([texts[1] for texts in self.input_rows(view)], ["cambiada", "vigente"])

    # Decidir sobre una entrada, descartarla y editarla (T52) -------------------------------

    def boundary_with_area(self, demo: Demo) -> tuple[object, Path, object, object, object]:
        """Un proyecto nuevo (aún fuera de la sesión) con la entrada «Limites» de
        ``fuentes/Limites.gpkg`` (``Limites_v1``, entregada por la propiedad) y el área de la
        demostración calculada con lo importado. Devuelve el proyecto, la fuente, la entrada, lo
        importado y la operación del área."""
        sources = self.tmp / "fuentes"
        sources.mkdir()
        source = sources / "Limites.gpkg"
        shutil.copyfile(DATA / "Limites_v1.gpkg", source)
        project = self.create()
        imported = _module("core.provenance.importer").import_layer(
            project, LAYER, source=source, received_at="2026-09-24",
            received_from="La propiedad")
        area = demo.area(project, imported.dataset.name)
        return project, source, imported.input, imported.dataset, area

    @staticmethod
    def journaled() -> tuple[str, str, bool]:
        """Lo último apuntado en el diario de Ctrl+Z: su clase, su etiqueta y si la escena
        lleva su número."""
        entry = _module("bl.scene.undo_watch").JOURNAL.entries[-1]
        stamped = bpy.context.scene.geoblender.registry_seq
        return str(entry.kind), entry.label, stamped == entry.seq

    @staticmethod
    def registry_state(project: object) -> tuple[object, ...]:
        """Lo que guarda el proyecto de las entradas, de los datos y de las operaciones, con
        el número de eventos: lo que no debe cambiar al cancelar o al rechazar."""
        with project.read() as conn:
            return tuple(conn.execute(sql).fetchall() for sql in (
                "SELECT uid, name, status, status_by, status_reason, received_at, "
                "received_from, seen_sha256, content_sha256 FROM gb_input ORDER BY fid",
                "SELECT uid, name, status, locator FROM gb_dataset ORDER BY fid",
                "SELECT uid, op_type, status, superseded_by FROM gb_operation ORDER BY fid",
                "SELECT count(*) FROM gb_event",
            ))

    @staticmethod
    def dialog(cls: type, **values: object) -> tuple[object, mock.Mock, FakeLayout]:
        """Abre el diálogo de la orden ``cls`` (``invoke``, con ``values`` como lo que le
        pasa quien la lanza) sin ventana y lo dibuja: devuelve sus valores tras ``invoke``,
        la llamada a ``invoke_props_dialog`` y lo dibujado."""
        given = set(values)
        defaults = {"input_uid": "", "decision": "UPDATE", "reason": "", "settings": [],
                    "choices": "", "name": "", "received_at": "", "received_from": "",
                    "dataset_uid": "", "operation_uid": "", "kind": "TABLE"}
        group, idname = cls.bl_idname.split(".")
        rna = getattr(getattr(bpy.ops, group), idname).get_rna_type()
        own = {name for name in defaults if name in rna.properties.keys()}
        operator = SimpleNamespace(**{name: values.get(name, defaults[name]) for name in own},
                                   properties=SimpleNamespace(is_property_set=given.__contains__),
                                   report=mock.Mock())
        opened = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window_manager=SimpleNamespace(invoke_props_dialog=opened))
        result = cls.invoke(operator, context, None)
        operator.report.assert_not_called()
        if result != {"RUNNING_MODAL"}:
            raise AssertionError(f"el diálogo no se abre: {result}")
        fields = {key: value for key, value in vars(operator).items()
                  if key not in ("properties", "report")}
        return operator, opened, draw(cls, bpy.context, **fields)

    def test_changed_input_is_updated_or_its_copy_kept(self) -> None:
        """RF-008-10, RF-008-11, RF-008-12, RF-008-61 (plan §5.3.2 y §5.4.8): con
        ``Limites_v2`` en lugar de ``Limites_v1``, la comprobación de apertura deja «Limites»
        cambiada y «⚠ 1 entrada». Su diálogo (el que abre la puerta, solo con su uid) dice el
        aviso de la spec §8 —su registro, lo que depende de ella y la fecha de la fuente— con
        Actualizar (elegida) y Mantener la copia y el motivo; abrirlo y cancelarlo no cambia
        nada. Mantener la copia la deja «cambiada · se mantiene la copia», con quién, y la saca
        de «⚠ n entradas». Actualizar sin motivo se rechaza sin cambiar nada; si el importador
        vuelve a pedir sus ajustes (la capa), lo dice sin cambiar nada (desde la interfaz, abre
        otra vez el diálogo con ellos, que los pide) y, con ellos, la reimporta con el
        importador de ``core.import_layer`` como una entrada nueva que la sustituye: la
        anterior queda «sustituida» con lo importado intacto, y el área calculada con ella,
        obsoleta. En solo lectura no se puede. RF-008-32: Mantener la copia se apunta en el
        diario de Ctrl+Z."""
        demo = self.enterContext(Demo(module_name()).registered())
        project, source, limits, imported, area = self.boundary_with_area(demo)
        shutil.copyfile(DATA / "Limites_v2.gpkg", source)
        later = time.time() + 10
        os.utime(source, (later, later))
        self.ps.attach(project)
        self.run_checks()
        ui = _module("bl.ui.provenance")
        ui.refresh(force=True)
        self.assertEqual(ui.inputs_text(), "⚠ 1 entrada")
        changed = self.registry_state(project)
        self.assertEqual(changed[0][0][2], "changed")

        cls = self.session.GEOBLENDER_OT_core_resolve_input
        operator, opened, shown = self.dialog(cls, input_uid=limits.uid)
        self.assertEqual(operator.decision, "UPDATE")
        self.assertEqual(opened.call_args.kwargs["title"], "Decidir sobre una entrada cambiada…")
        notice = " ".join(item.text for item in shown.of_kind("label"))
        self.assertTrue(notice.startswith("La entrada «Limites» ha cambiado desde su registro ("),
                        notice)
        self.assertIn("Dependen de ella: 1 dato, 1 operación y 1 cifra. Fecha de la fuente: ",
                      notice)
        self.assertEqual([(item.text, item.enabled) for item in shown.of_kind("prop_enum")],
                         [("Actualizar", True), ("Mantener la copia", True)])
        self.assertEqual([item.target for item in shown.of_kind("prop")], ["reason"])
        self.assertEqual(self.registry_state(project), changed)  # Cancelar: nada cambia

        self.assertEqual(bpy.ops.geoblender.core_resolve_input(input_uid=limits.uid,
                                                               decision="KEEP"), {"FINISHED"})
        kept = self.registry_state(project)
        self.assertEqual(kept[0][0][2:4], ("kept", project.session.user_host))
        self.assertEqual(self.journaled(), ("input", "Limites", True))  # RF-008-32
        self.assertEqual(ui.inputs_text(), "")
        self.assertEqual(self.input_rows(self.show_inputs())[0][1], KEPT)

        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_resolve_input(input_uid=limits.uid, decision="UPDATE")
        self.assertIn("Indique el motivo de la sustitución de la entrada «Limites».",
                      str(caught.exception))
        importer = _module("core.provenance.importer")
        contract = _module("core.provenance.contract")
        real = importer.reimport_input
        asked: list[object] = []

        def reimport(project_: object, uid: str, reason: str, **kwargs: object) -> object:
            asked.append(kwargs.get("settings"))
            if kwargs.get("settings") is None:  # la capa «ya no está»: pide los ajustes
                raise contract.SettingsNeeded(
                    "core.import_layer_missing", needed=("layer",),
                    choices={"layer": (LAYER, "parcelas")}, layer=LAYER, source=source.name,
                    name="Limites", layers=f"«{LAYER}», «parcelas»")
            return real(project_, uid, reason, **kwargs)

        update = {"input_uid": limits.uid, "decision": "UPDATE", "reason": UPDATE_REASON}
        with mock.patch.object(importer, "reimport_input", reimport):
            with self.assertRaises(RuntimeError) as caught:
                bpy.ops.geoblender.core_resolve_input(**update)
            self.assertIn("indique otra vez los ajustes de la importación (la capa)",
                          str(caught.exception))
            with (mock.patch.object(self.session, "_interactive", return_value=True),
                  mock.patch.object(self.session, "_ask_settings") as again):
                self.assertEqual(bpy.ops.geoblender.core_resolve_input(**update),
                                 {"CANCELLED"})
            ((uid, reason, needed), _kwargs) = again.call_args
            self.assertEqual((uid, reason, needed.needed), (limits.uid, UPDATE_REASON,
                                                            ("layer",)))
            self.assertEqual(self.registry_state(project), kept)
            choices = json.dumps({"layer": [LAYER, "parcelas"]})
            _operator, _opened, shown = self.dialog(
                cls, settings=[SimpleNamespace(name="layer", value="")], choices=choices,
                **update)
            texts = shown.texts()
            self.assertIn("Ajustes de la importación que vuelve a pedir el importador", texts)
            self.assertIn("Valores: «limites», «parcelas»", texts)
            self.assertEqual([(item.target, item.text) for item in shown.of_kind("prop")],
                             [("value", "layer"), ("reason", "Motivo")])
            with self.assertRaises(RuntimeError) as caught:  # el ajuste, vacío
                bpy.ops.geoblender.core_resolve_input(
                    settings=[{"name": "layer", "value": " "}], **update)
            self.assertIn("Indique el ajuste de la importación «layer»", str(caught.exception))
            # Volver a abrir el diálogo con lo que pide: en «blender -b», abrirlo lo ejecuta,
            # con el único valor posible ya escrito.
            self.session._ask_settings(limits.uid, UPDATE_REASON, contract.SettingsNeeded(
                "core.import_layer_missing", needed=("layer",), choices={"layer": (LAYER,)},
                layer=LAYER, source=source.name, name="Limites", layers=f"«{LAYER}»"))
        self.assertEqual(asked, [None, None, {"layer": LAYER}])

        inputs, datasets, _operations, _events = self.registry_state(project)
        (old, new) = inputs
        self.assertEqual(old[:3], (limits.uid, "Limites", "superseded"))
        self.assertEqual(old[4], UPDATE_REASON)
        self.assertEqual(new[1:3], ("Limites", "current"))
        self.assertNotEqual(new[8], limits.content_sha256)
        with project.read() as conn:
            previous = conn.execute("SELECT previous_uid FROM gb_input WHERE uid = ?",
                                    (new[0],)).fetchone()[0]
            stale = _module("core.provenance.stale").item_text(conn, "operation", area.uid)
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(previous, limits.uid)
        self.assertEqual(stale, "Obsoleto: se actualizó la entrada «Limites»")
        found = {uid: (status, locator) for uid, _name, status, locator in datasets}
        self.assertEqual(found[imported.uid], ("superseded", imported.locator))
        self.assertLessEqual({locator for _status, locator in found.values()}, tables)
        self.assertEqual(ui.inputs_text(), "")

        project.set_read_only(self.core.ReadOnlyCode.REQUESTED, "prueba")
        self.assertFalse(bpy.ops.geoblender.core_resolve_input.poll())
        with self.assertRaises(RuntimeError):
            bpy.ops.geoblender.core_resolve_input(input_uid=new[0], decision="KEEP")

    def test_discard_and_edit_an_input(self) -> None:
        """RF-008-55, RF-008-07, RF-008-16 (D-11; plan §5.3.2 y §5.4.8): Descartar… pide el
        motivo (sin él se rechaza sin cambiar nada; su diálogo dice que no se borra nada) y
        deja la entrada «descartada · registro, no usar», con lo importado descartado pero en
        el proyecto, y el área calculada con ella, obsoleta. Editar… sale relleno con su nombre
        y su entrega y cambia solo eso: sus ficheros, sus hashes, su estado y lo importado no
        cambian (también la de una descartada); una fecha que no es DD/MM/AAAA se rechaza sin
        cambiar nada. En solo lectura, ninguna de las dos. RF-008-32: las dos se apuntan en el
        diario de Ctrl+Z."""
        demo = self.enterContext(Demo(module_name()).registered())
        project, _source, limits, imported, area = self.boundary_with_area(demo)
        self.ps.attach(project)
        before = self.registry_state(project)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_discard_input(input_uid=limits.uid)
        self.assertIn("Indique el motivo para descartar la entrada «Limites».",
                      str(caught.exception))
        discard = self.session.GEOBLENDER_OT_core_discard_input
        _operator, opened, shown = self.dialog(discard, input_uid=limits.uid)
        self.assertEqual(opened.call_args.kwargs["title"], "Descartar entrada…")
        self.assertIn(f"No se borra nada: la entrada sigue en el registro como «{DISCARDED}»",
                      shown.texts())
        self.assertEqual([item.target for item in shown.of_kind("prop")], ["reason"])
        self.assertEqual(self.registry_state(project), before)

        self.assertEqual(bpy.ops.geoblender.core_discard_input(
            input_uid=limits.uid, reason="Importación equivocada"), {"FINISHED"})
        inputs, datasets, _operations, _events = self.registry_state(project)
        self.assertEqual(inputs[0][2:5], ("discarded", project.session.user_host,
                                          "Importación equivocada"))
        self.assertEqual(self.journaled(), ("input", "Limites", True))  # RF-008-32
        self.assertEqual(datasets[0][:3], (imported.uid, imported.name, "discarded"))
        with project.read() as conn:
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (imported.locator,)).fetchone())
            stale = _module("core.provenance.stale").item_text(conn, "operation", area.uid)
        self.assertEqual(stale, "Obsoleto: se descartó la entrada «Limites»")
        self.assertEqual(self.input_rows(self.show_inputs())[0][1], DISCARDED)

        edit = self.session.GEOBLENDER_OT_core_edit_input
        operator, opened, shown = self.dialog(edit, input_uid=limits.uid)
        self.assertEqual((operator.name, operator.received_at, operator.received_from),
                         ("Limites", "24/09/2026", "La propiedad"))
        self.assertEqual(opened.call_args.kwargs["title"], "Editar entrada…")
        self.assertEqual([item.target for item in shown.of_kind("prop")],
                         ["name", "received_at", "received_from"])
        discarded = self.registry_state(project)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_edit_input(input_uid=limits.uid, received_at="31/02/2026")
        self.assertIn("Fecha de entrega «31/02/2026»: escríbala como DD/MM/AAAA",
                      str(caught.exception))
        self.assertEqual(self.registry_state(project), discarded)
        self.assertEqual(bpy.ops.geoblender.core_edit_input(
            input_uid=limits.uid, name="Limites del cliente", received_at="25/09/2026",
            received_from=""), {"FINISHED"})
        inputs, datasets, operations, events = self.registry_state(project)
        self.assertEqual(inputs[0][1:3], ("Limites del cliente", "discarded"))
        self.assertEqual(self.journaled(), ("input", "Limites del cliente", True))
        self.assertEqual(inputs[0][5:7], ("2026-09-25", None))
        self.assertEqual(inputs[0][7:], discarded[0][0][7:])  # su contenido no cambia
        self.assertEqual((datasets, operations), discarded[1:3])
        self.assertEqual(events[0][0], discarded[3][0][0] + 1)  # input_edited

        project.set_read_only(self.core.ReadOnlyCode.REQUESTED, "prueba")
        self.assertFalse(bpy.ops.geoblender.core_discard_input.poll())
        self.assertFalse(bpy.ops.geoblender.core_edit_input.poll())

    # Recalcular lo obsoleto (T53) -----------------------------------------------------------

    def stockpile_chain(self, demo: Demo) -> object:
        """Un proyecto nuevo con los bancos, los años por banco y los acopios (el grupo
        acoplado) de la demostración, abierto en la sesión (su comprobación de apertura, aún
        pendiente)."""
        project = self.create()
        demo.digitize(project)
        demo.bench_years(project)
        demo.stockpiles(project)
        self.ps.attach(project)
        return project

    @staticmethod
    def change(project: object, key: str, value: float) -> None:
        """Cambia el parámetro ``key`` a ``value`` (ADOPTADO, con su origen y su motivo)."""
        store = _module("core.params").ParameterStore(project)
        with project.write_transaction() as conn:
            store.change(conn, key, value=value, kind="ADOPTADO", source="Plan de labores 2027",
                         source_kind="document", decided_by="la propiedad",
                         reason="Plan revisado")

    def recompute(self, **props: object) -> object:
        """Lanza «Recalcular lo obsoleto» con ``props`` y devuelve el modal en marcha (al
        terminar la prueba, si sigue en marcha, se cancela)."""
        self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT", **props),
                         {"RUNNING_MODAL"})
        return self.running_modal(self.session.GEOBLENDER_OT_core_recompute_stale)

    def running_modal(self, cls: type) -> object:
        """El modal de la orden ``cls`` en marcha (al terminar la prueba, si sigue, se
        cancela)."""
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1)
        operator = found[0]
        self.addCleanup(lambda: operator._steps is None or operator.cancel(bpy.context))
        return operator

    def drive(self, operator: object) -> set[str]:
        """Pasa eventos ``TIMER`` al modal hasta que termina; devuelve su estado."""
        for _ in range(MAX_TICKS):
            state = operator.modal(bpy.context, TIMER)
            if state != {"RUNNING_MODAL"}:
                return state
        self.fail("el recálculo no termina")

    @staticmethod
    def units(operator: object) -> list[tuple[tuple[str, ...], str]]:
        """Las unidades que intentó el modal: sus tipos de operación y cómo terminaron."""
        return [(result.unit.op_types, str(result.status))
                for result in operator.result.results]

    def test_recompute_one_result_a_change_and_everything(self) -> None:
        """RF-008-26, RF-008-25, RF-008-28 (plan §5.3.2 y §5.4.4): con la producción cambiada,
        los años por banco y los dos datos de los acopios están obsoletos («! 3 obsoletos»).
        Recalcular en la fila de los años por banco del panel de lo obsoleto (su elemento)
        rehace solo esa operación; Recalcular lo que depende del cambio de la producción rehace
        después las dos del grupo de los acopios, juntas y en su orden, y la cuenta queda a 0.
        Con la producción y el factor K cambiados otra vez, Recalcular lo obsoleto lo rehace
        todo en orden de dependencia (los años antes que los acopios), con su progreso, como
        operaciones nuevas que sustituyen a las anteriores y leen los parámetros vigentes, y la
        cuenta vuelve a 0. RF-008-32: lo recalculado se apunta en el diario de Ctrl+Z."""
        demo = self.enterContext(Demo(module_name()).registered())
        project = self.stockpile_chain(demo)
        self.run_checks()
        ui = _module("bl.ui.provenance")
        self.change(project, PRODUCTION, 400_000.0)
        ui.refresh(force=True)
        self.assertEqual(ui.stale_text(), "! 3 obsoletos")

        panel = draw(bpy.types.GEOBLENDER_PT_core_stale, bpy.context)
        buttons = [item for item in panel.items if item.target == RECOMPUTE]
        self.assertEqual([item.text for item in buttons], ["Recalcular"] * 3
                         + ["Recalcular lo obsoleto"])
        self.assertTrue(all(item.enabled for item in buttons))
        with project.read() as conn:
            (years,) = conn.execute("SELECT uid FROM gb_dataset WHERE name = ?",
                                    (YEARS_TABLE,)).fetchone()
        row = vars(buttons[0].properties)
        self.assertEqual(row, {"scope": "ITEM", "subject_uid": years})
        operator = self.recompute(**row)
        self.assertEqual(self.drive(operator), {"FINISHED"})
        self.assertEqual(self.units(operator), [((BENCH_YEARS,), "done")])
        self.assertEqual(ui.stale_text(), "! 2 obsoletos")
        self.assertEqual(self.journaled(), ("operation", BENCH_YEARS, True))  # RF-008-32

        production = _module("core.params").ParameterStore(project).get(PRODUCTION).uid
        operator = self.recompute(scope="CAUSE", subject_uid=production)
        self.assertEqual(self.drive(operator), {"FINISHED"})
        self.assertEqual(self.units(operator), [(STOCKPILE_UNIT, "done")])
        self.assertEqual((ui.stale_text(), ui.counts().obsolete), ("", 0))

        self.change(project, PRODUCTION, 300_000.0)
        self.change(project, SWELL_FACTOR, 1.2)
        ui.refresh(force=True)
        self.assertEqual(ui.stale_text(), "! 3 obsoletos")
        with project.read() as conn:
            current = dict(conn.execute("SELECT uid, op_type FROM gb_operation "
                                        "WHERE superseded_by IS NULL"))
        operator = self.recompute()
        self.assertEqual(self.drive(operator), {"FINISHED"})
        self.assertEqual(self.units(operator), [((BENCH_YEARS,), "done"),
                                                (STOCKPILE_UNIT, "done")])
        self.assertEqual(operator.progress_log, [
            f"Recalculando lo obsoleto: {done} de 2… Esc: cancelar" for done in (0, 1, 2)])
        made = [uid for result in operator.result.results for uid in result.operations]
        with project.read() as conn:
            rows = [conn.execute("SELECT op_type, supersedes_uid, fid FROM gb_operation "
                                 "WHERE uid = ?", (uid,)).fetchone() for uid in made]
        self.assertEqual([op_type for op_type, _old, _fid in rows],
                         [BENCH_YEARS, *STOCKPILE_UNIT])
        self.assertEqual([current[old] for _op_type, old, _fid in rows],
                         [BENCH_YEARS, *STOCKPILE_UNIT])  # sustituyen a las anteriores
        self.assertEqual([fid for *_rest, fid in rows], sorted(fid for *_rest, fid in rows))
        figure = demo.current_figure(project, YEARS_FIGURE, {"bench": "B-1"})
        self.assertAlmostEqual(figure.value, 1_250_000.0 / 300_000.0, places=12)
        self.assertEqual((ui.stale_text(), ui.counts().obsolete), ("", 0))
        self.assertIn("Operaciones recalculadas: 3", operator.report_log)

    def test_recompute_cancelled_halfway_and_not_in_read_only(self) -> None:
        """RF-008-26, RF-008-58 (plan §5.4.4): mientras se comprueba el proyecto, Recalcular lo
        obsoleto no empieza (lo dice). Con la producción cambiada, Esc tras recalcular los años
        por banco para antes del grupo de los acopios: lo recalculado queda y los acopios
        siguen obsoletos («! 2 obsoletos»), y lo dice; con un recálculo en marcha no empieza
        otro. En solo lectura no está disponible."""
        demo = self.enterContext(Demo(module_name()).registered())
        project = self.stockpile_chain(demo)
        self.change(project, PRODUCTION, 400_000.0)
        self.assertTrue(self.monitor.running)
        self.assertEqual(bpy.ops.geoblender.core_recompute_stale(), {"CANCELLED"})
        self.run_checks()

        operator = self.recompute()
        self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})  # 0 de 2
        self.assertEqual(bpy.ops.geoblender.core_recompute_stale(), {"CANCELLED"})
        self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})  # los años
        self.assertEqual(operator.modal(bpy.context, ESC), {"CANCELLED"})
        self.assertTrue(operator.result.cancelled)
        self.assertEqual(self.units(operator), [((BENCH_YEARS,), "done")])
        self.assertEqual(_module("bl.ui.provenance").stale_text(), "! 2 obsoletos")
        self.assertIn("Recálculo cancelado: operaciones recalculadas, 1; lo demás sigue "
                      "obsoleto", operator.report_log)

        project.set_read_only(self.core.ReadOnlyCode.REQUESTED, "prueba")
        self.assertFalse(bpy.ops.geoblender.core_recompute_stale.poll())
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_recompute_stale()
        self.assertIn(READ_ONLY, str(caught.exception))

    # Lo que no se puede usar, dar por buena, capas sin registrar y cancelar (T54) ---------

    def check_everything(self) -> None:
        """«Comprobar cambios en las entradas» (también los datos del proyecto), hasta el
        final, y los indicadores al día."""
        self.assertTrue(self.monitor.check_inputs())
        self.run_checks()
        _module("bl.ui.provenance").refresh(force=True)

    @staticmethod
    def status(project: object, uid: str) -> str:
        with project.read() as conn:
            return conn.execute("SELECT status FROM gb_dataset WHERE uid = ?", (uid,)).fetchone()[0]

    def test_blocked_dataset_and_accept_review(self) -> None:
        """RF-008-56, RF-008-21, RF-008-27, RF-008-28 (plan §5.3.2, §5.4.4 y §5.4.9): los años
        por banco editados fuera quedan bloqueados y el panel de lo obsoleto los lista con su
        aviso, Aceptar la edición y Recalcular (Reimportar no se ofrece). Su diálogo sale con
        Aceptar la edición elegida; reimportarlo o aceptar sin motivo se rechaza sin cambiar
        nada. Recalcular repite los años por banco (un modal) y el dato vuelve a vigente, sin
        nada obsoleto. Editado otra vez, aceptar la edición con motivo lo deja vigente y lo que
        lo usaba, obsoleto; con la producción cambiada, la edición espera revisión a mano: el
        panel la lista con «Dar por buena…», cuyo diálogo dice por qué y pide el motivo, y
        darla por buena la sustituye. En solo lectura, ninguna de las dos órdenes."""
        demo = self.enterContext(Demo(module_name()).registered())
        project = self.stockpile_chain(demo)
        self.run_checks()
        ui = _module("bl.ui.provenance")
        with project.read() as conn:
            (years,) = conn.execute("SELECT uid FROM gb_dataset WHERE name = ?",
                                    (YEARS_TABLE,)).fetchone()
        edit = f'UPDATE "{YEARS_TABLE}" SET years = years + 1 WHERE bench = \'B-1\''
        _foreign(project, edit)
        self.check_everything()
        self.assertEqual(self.status(project, years), "blocked")
        self.assertEqual([(row.uid, row.status, row.offers) for row in _view().unusable],
                         [(years, "blocked", "accept,recompute")])
        panel = draw(bpy.types.GEOBLENDER_PT_core_stale, bpy.context)
        self.assertEqual(_buttons(panel, RESOLVE_DATASET), [
            (OFFERS[0], {"dataset_uid": years, "decision": "ACCEPT"}, True),
            (OFFERS[1], {"dataset_uid": years, "decision": "RECOMPUTE"}, True),
        ])
        self.assertIn("Datos que no se pueden usar", panel.texts())
        self.assertIn(BLOCKED, panel.texts())

        cls = self.session.GEOBLENDER_OT_core_resolve_dataset
        operator, opened, shown = self.dialog(cls, dataset_uid=years)
        self.assertEqual(operator.decision, "ACCEPT")
        self.assertEqual(opened.call_args.kwargs["title"], "Decidir sobre un dato editado fuera…")
        self.assertEqual(" ".join(item.text for item in shown.of_kind("label")), BLOCKED)
        self.assertEqual([(item.text, item.enabled) for item in shown.of_kind("prop_enum")],
                         [(OFFERS[0], True), (OFFERS[1], True), (OFFERS[2], False)])
        self.assertEqual([item.target for item in shown.of_kind("prop")], ["reason"])
        before = self.registry_state(project)
        for decision, reason, refused in (
            ("REIMPORT", "Otra entrega", "no se puede reimportar"),
            ("ACCEPT", " ", "Falta el motivo: aceptar la edición externa de «demo_bench_years»"),
        ):
            with self.subTest(decision=decision), self.assertRaises(RuntimeError) as caught:
                bpy.ops.geoblender.core_resolve_dataset(dataset_uid=years, decision=decision,
                                                        reason=reason)
            self.assertIn(refused, str(caught.exception))
        self.assertEqual(self.registry_state(project), before)

        self.assertEqual(bpy.ops.geoblender.core_resolve_dataset(
            "EXEC_DEFAULT", dataset_uid=years, decision="RECOMPUTE"), {"RUNNING_MODAL"})
        modal = self.running_modal(cls)
        self.assertEqual(self.drive(modal), {"FINISHED"})
        self.assertEqual([(result.unit.op_types, str(result.status))
                          for result in modal.result.results], [((BENCH_YEARS,), "done")])
        self.assertEqual(self.status(project, years), "current")
        self.assertEqual((ui.stale_text(), len(_view().unusable)), ("", 0))

        _foreign(project, edit)
        self.check_everything()
        self.assertEqual(bpy.ops.geoblender.core_resolve_dataset(
            dataset_uid=years, decision="ACCEPT", reason="La propiedad corrige B-1"),
            {"FINISHED"})
        self.assertEqual(self.status(project, years), "current")
        self.assertEqual(ui.stale_text(), "! 2 obsoletos")  # los acopios, por el cambio

        self.change(project, PRODUCTION, 400_000.0)
        ui.refresh(force=True)
        ((review, op_type),) = [(row.uid, row.op_type) for row in _view().stale
                                if row.review and row.item_kind == "operation"]
        self.assertEqual(op_type, "core.external_edit")
        panel = draw(bpy.types.GEOBLENDER_PT_core_stale, bpy.context)
        # La de la operación y la del dato que escribió, que también espera la revisión.
        self.assertEqual({(text, props["operation_uid"], on) for text, props, on in
                          _buttons(panel, ACCEPT_REVIEW)}, {("Dar por buena…", review, True)})
        accept = self.session.GEOBLENDER_OT_core_accept_review
        _operator, opened, shown = self.dialog(accept, operation_uid=review)
        self.assertEqual(opened.call_args.kwargs["title"], "Dar por buena…")
        notice = " ".join(item.text for item in shown.of_kind("label"))
        self.assertIn("espera revisión a mano: Obsoleto: cambió Producción (demostración)",
                      notice)
        self.assertEqual([item.target for item in shown.of_kind("prop")], ["reason"])
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_accept_review(operation_uid=review)
        self.assertIn("Falta el motivo: dar por buena la operación «core.external_edit»",
                      str(caught.exception))
        self.assertEqual(bpy.ops.geoblender.core_accept_review(
            operation_uid=review, reason="Revisado con la propiedad"), {"FINISHED"})
        with project.read() as conn:
            accepted = conn.execute("SELECT o.op_type, r.superseded_by = o.uid FROM gb_operation "
                                    "AS o JOIN gb_operation AS r ON r.uid = ? WHERE "
                                    "o.supersedes_uid = r.uid", (review,)).fetchone()
        self.assertEqual(accepted, ("core.accept_review", 1))
        self.assertFalse([row for row in _view().stale if row.review])

        project.set_read_only(self.core.ReadOnlyCode.REQUESTED, "prueba")
        for name in ("core_resolve_dataset", "core_accept_review"):
            with self.subTest(orden=name):
                self.assertFalse(getattr(bpy.ops.geoblender, name).poll())

    def test_missing_damaged_and_unregistered(self) -> None:
        """RF-008-57, RF-008-52, RF-008-62 (plan §5.3.2, §5.4.9 y §5.5): con los años por banco
        eliminados desde QGIS, lo importado de «Limites» sin una de sus columnas y dos capas
        creadas desde QGIS, la comprobación de apertura deja los años «falta» (solo se ofrece
        Recalcular) y lo importado «dañado» (solo Reimportar: aceptar o recalcular se rechaza).
        Recalcular repite los años por banco y vuelven a vigentes; reimportar, con su motivo,
        sustituye la entrada por una nueva y deja el área obsoleta. El registro de entradas
        lista las dos capas con Registrar como entrada… e Ignorar…: registrar una la convierte
        en una entrada del proyecto y la otra se ignora con su motivo; un fichero no se
        registra. En solo lectura, nada de eso se puede."""
        demo = self.enterContext(Demo(module_name()).registered())
        project, _source, limits, imported, area = self.boundary_with_area(demo)
        demo.digitize(project)
        demo.bench_years(project)
        with project.read() as conn:
            (years,) = conn.execute("SELECT uid FROM gb_dataset WHERE name = ?",
                                    (YEARS_TABLE,)).fetchone()
        layers = [(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, '
                   f'nota TEXT)',
                   f"INSERT INTO \"{name}\" (nota) VALUES ('{name}')",
                   "INSERT INTO gpkg_contents (table_name, data_type, identifier) VALUES "
                   f"('{name}', 'attributes', '{name}')") for name in ("capa_qgis", "otra_qgis")]
        _foreign(project, f'DROP TABLE "{YEARS_TABLE}"',
                 f"DELETE FROM gpkg_contents WHERE table_name = '{YEARS_TABLE}'",
                 f'ALTER TABLE "{IMPORTED}" DROP COLUMN tipo', *layers[0], *layers[1])
        self.ps.attach(project)
        self.run_checks()
        _module("bl.ui.provenance").refresh(force=True)
        self.assertEqual([(row.uid, row.status, row.offers) for row in _view().unusable], [
            (imported.uid, "damaged", "reimport"), (years, "missing", "recompute")])
        panel = draw(bpy.types.GEOBLENDER_PT_core_stale, bpy.context)
        self.assertEqual([(text, props["decision"]) for text, props, _on in
                          _buttons(panel, RESOLVE_DATASET)],
                         [(OFFERS[2], "REIMPORT"), (OFFERS[1], "RECOMPUTE")])
        cls = self.session.GEOBLENDER_OT_core_resolve_dataset
        operator, _opened, shown = self.dialog(cls, dataset_uid=imported.uid)
        self.assertEqual(operator.decision, "REIMPORT")
        self.assertEqual([item.enabled for item in shown.of_kind("prop_enum")],
                         [False, False, True])
        before = self.registry_state(project)
        for decision, refused in (("ACCEPT", "solo se puede reimportar"),
                                  ("RECOMPUTE", "no se puede recalcular")):
            with self.subTest(decision=decision), self.assertRaises(RuntimeError) as caught:
                bpy.ops.geoblender.core_resolve_dataset(dataset_uid=imported.uid,
                                                        decision=decision, reason="Sí")
            self.assertIn(refused, str(caught.exception))
        self.assertEqual(self.registry_state(project), before)

        self.assertEqual(bpy.ops.geoblender.core_resolve_dataset(
            "EXEC_DEFAULT", dataset_uid=years, decision="RECOMPUTE"), {"RUNNING_MODAL"})
        self.assertEqual(self.drive(self.running_modal(cls)), {"FINISHED"})
        self.assertEqual(self.status(project, years), "current")
        self.assertEqual(bpy.ops.geoblender.core_resolve_dataset(
            dataset_uid=imported.uid, decision="REIMPORT", reason="Lo importado está dañado"),
            {"FINISHED"})
        inputs, _datasets, _operations, _events = self.registry_state(project)
        self.assertEqual([row[1:3] for row in inputs],
                         [("Limites", "superseded"), ("Limites", "current")])
        self.assertEqual(self.status(project, imported.uid), "superseded")
        with project.read() as conn:
            stale = _module("core.provenance.stale").item_text(conn, "operation", area.uid)
        self.assertEqual(stale, "Obsoleto: se actualizó la entrada «Limites»")
        self.assertEqual(len(_view().unusable), 0)
        self.assertNotEqual(limits.uid, inputs[1][0])

        ui = _module("bl.ui.provenance")
        ui.fill_inputs()
        self.assertEqual([(row.kind, row.name, row.registrable) for row in _view().unregistered],
                         [("table", "capa_qgis", True), ("table", "otra_qgis", True)])
        panel = draw(bpy.types.GEOBLENDER_PT_core_inputs, bpy.context)
        self.assertIn("Capas y tablas del proyecto sin registrar", panel.texts())
        self.assertEqual(_buttons(panel, RESOLVE_UNREGISTERED)[:2], [
            ("Registrar como entrada…",
             {"kind": "TABLE", "name": "capa_qgis", "decision": "REGISTER"}, True),
            ("Ignorar…", {"kind": "TABLE", "name": "capa_qgis", "decision": "IGNORE"}, True),
        ])
        unregistered = self.session.GEOBLENDER_OT_core_resolve_unregistered
        operator, opened, shown = self.dialog(unregistered, kind="TABLE", name="capa_qgis")
        self.assertEqual(operator.decision, "REGISTER")
        self.assertEqual(opened.call_args.kwargs["title"], "Capa o fichero sin registrar…")
        self.assertEqual([(item.text, item.enabled) for item in shown.of_kind("prop_enum")],
                         [("Registrar como entrada", True), ("Ignorar", True)])
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_resolve_unregistered(kind="FILE", name="rasters/a.tif",
                                                         decision="REGISTER")
        self.assertIn("solo se registran como entrada las capas y las tablas",
                      str(caught.exception))
        self.assertEqual(bpy.ops.geoblender.core_resolve_unregistered(
            kind="TABLE", name="capa_qgis", decision="REGISTER"), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.core_resolve_unregistered(
            kind="TABLE", name="otra_qgis", decision="IGNORE", reason="Pruebas de QGIS"),
            {"FINISHED"})
        with project.read() as conn:
            registered = conn.execute("SELECT i.name, f.anchor FROM gb_input AS i JOIN "
                                      "gb_input_file AS f ON f.input_uid = i.uid WHERE "
                                      "i.name = 'capa_qgis'").fetchall()
            ignored = conn.execute("SELECT kind, name, reason FROM gb_ignored").fetchall()
        self.assertEqual(registered, [("capa_qgis", "project_table")])
        self.assertEqual(ignored, [("table", "otra_qgis", "Pruebas de QGIS")])
        self.assertEqual(len(_view().unregistered), 0)

        project.set_read_only(self.core.ReadOnlyCode.REQUESTED, "prueba")
        for name in ("core_resolve_dataset", "core_resolve_unregistered"):
            with self.subTest(orden=name):
                self.assertFalse(getattr(bpy.ops.geoblender, name).poll())
        panel = draw(bpy.types.GEOBLENDER_PT_core_stale, bpy.context)
        self.assertFalse([item for item in panel.of_kind("operator")
                          if item.target == RESOLVE_DATASET and item.enabled])

    def test_cancel_the_checks(self) -> None:
        """RF-008-58, RNF-008-11 (plan §5.3.2): sin una comprobación en marcha, «Cancelar las
        comprobaciones» no está disponible y lo dice; con la de apertura a medias, para enseguida
        (≤ 2 s): no queda nada en marcha, la puerta deja de esperar, se quita el temporizador y
        el campo «Comprobando el proyecto…» desaparece."""
        operator = bpy.ops.geoblender.core_cancel_checks
        self.assertFalse(operator.poll())
        self.ps.attach(self.create())
        self.assertIsNotNone(self.session.check_tick())
        self.assertTrue(self.monitor.running and self.monitor.pending.running)
        ui = _module("bl.ui.provenance")
        self.assertTrue(ui.checking_text())
        self.assertTrue(operator.poll())
        started = time.monotonic()
        self.assertEqual(operator(), {"FINISHED"})
        self.assertLessEqual(time.monotonic() - started, 2.0)
        self.assertFalse(self.monitor.running or self.monitor.pending.running)
        self.assertFalse(bpy.app.timers.is_registered(self.session.check_tick))
        self.assertEqual(ui.checking_text(), "")
        self.assertFalse(operator.poll())


if __name__ == "__main__":
    unittest.main()
