# SPDX-License-Identifier: GPL-3.0-or-later
"""El registro de los sondeos en Blender (spec 005, T24; plan 005 §5.1, §5.3.1, §5.5, §5.6.3,
§5.6.4, §5.6.7 y §5.6.8; ADR-0025 §2; principio 8).

- Catálogo de la 003 (contrato 1 del plan 003): cada ``bl_idname`` de la entrada ``005`` es
  la clase real de ``bl/ops/dh.py``, registrada una vez (ninguno provisional), y las órdenes
  de los sondeos de otras entradas (R-78, R-14) siguen provisionales. Mientras su orden no
  llega, cada una no está disponible y dice dónde estará («Disponible en 005 · Sondeos»)
  (la reimportación llega con la referencia del azimut, T28; el cargador de la vista, con la
  vista, T29; los recálculos, T42).
- ``bl/props/dh.py`` y ``bl/ui/dh_panels.py``: la representación en la escena, la
  importación pendiente y la validación en ``WindowManager``, y los tres paneles y la lista
  de incidencias en la pestaña «Sondeos».
- ADR-0025 §2 (RF-005-12, RF-005-16, RF-005-20, RF-005-26; RF-008-01, RF-008-09, RF-008-11,
  RF-008-26, RF-008-29): habilitar registra en ``core`` las ocho definiciones de parámetros,
  los tres lectores de contenido, los siete tipos de trabajo, los seis tipos de operación
  (los repetibles con su recálculo y los ajustes que enseña su procedencia) y los tres
  importadores, y en la vista el cargador ``dh_trace``; quitarlos y ponerlos deja los
  registros como estaban, también con lo que otro registró antes con las mismas claves.
- RNF-005-06 (plan §5.6.7): la cola de incorporación de los sondeos avanza un paso por
  llamada de su temporizador y desregistrar la cierra sin escribir nada más.
- Principio 8: deshabilitar no deja clases, propiedades, tipos de trabajo, temporizadores ni
  nada de los sondeos en los registros.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import importlib
import inspect
import unittest
from collections.abc import Callable, Iterator
from types import ModuleType
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw

ENTRY = "005"
OURS = ("dh.", "dh_", "io.")  # las claves de la 005 en los registros de core y de la vista
COUNTS = {"parámetros": 8, "lectores": 3, "trabajos": 7, "operaciones": 6, "grupos": 0,
          "cifras": 0, "importadores": 3, "cargadores": 1}
PANELS = ("GEOBLENDER_PT_dh_pending", "GEOBLENDER_PT_dh_validation",
          "GEOBLENDER_PT_dh_display")
LIST = "GEOBLENDER_UL_dh_issues"
WITH_SETTINGS = ("dh.import_tabular", "dh.import_recmin", "dh.desurvey")
DELIVERED = frozenset({"geoblender.dh_import_drillholes",  # T25
                       "geoblender.dh_import_recmin_mdb",  # T26
                       "geoblender.dh_validate",  # T27
                       "geoblender.dh_export_validation_report",  # T27
                       "geoblender.dh_desurvey",  # T28
                       "geoblender.dh_set_azimuth_reference",  # T28
                       "geoblender.dh_set_detection_limit_policy",  # T28
                       "geoblender.dh_show_display"})  # T30


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _other_reimport(request: Any) -> Any:
    raise AssertionError("la reimportación de otro no se usa en esta prueba")


def _other_loader(request: Any) -> Any:
    raise AssertionError("el cargador de otro no se usa en esta prueba")


class _Modules:
    """Los módulos de la extensión que mira la prueba (los de la habilitación en curso)."""

    def __init__(self) -> None:
        self.dh_ops = _module("bl.ops.dh")
        self.dh_view = _module("bl.scene.dh_view")
        self.views = _module("bl.scene.views")
        self.params = _module("core.params")
        self.readers = _module("core.content.readers")
        self.catalog = _module("jobs.catalog")
        self.contract = _module("core.provenance.contract")
        self.provenance = _module("drillholes.provenance")
        self.commands = _module("bl.ui.commands")

    def registries(self) -> dict[str, dict[str, Any]]:
        """Los registros de ``core`` y de la vista que amplía la 005, por nombre (copias)."""
        return {
            "parámetros": dict(self.params.DEFINITIONS),
            "lectores": dict(self.readers.READERS),
            "trabajos": dict(self.catalog.WORKERS),
            "operaciones": dict(self.contract.OPERATIONS),
            "grupos": dict(self.contract.GROUPS),
            "cifras": dict(self.contract.FIGURES),
            "importadores": dict(self.contract.IMPORTERS),
            # Un cargador se registra con un objeto nuevo cada vez: cuenta su función.
            "cargadores": {key: found.load for key, found in self.views.loaders().items()},
        }

    def ours(self) -> dict[str, list[str]]:
        return {name: sorted(key for key in found if key.startswith(OURS))
                for name, found in self.registries().items()}


class DrillholesRegisteredTest(unittest.TestCase):
    """Con la extensión habilitada (sin importarla otra vez: ``blender_ext.release``; al
    deshabilitarla, los módulos se quedan, como al desactivarla en las preferencias)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.m = _Modules()
        cls.cat = cls.m.commands.catalog()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    # --- Ayudas -------------------------------------------------------------------------------

    def register_dh(self) -> None:
        self.m.dh_ops.register()
        self.m.dh_view.register()

    def unregister_dh(self) -> None:
        self.m.dh_view.unregister()
        self.m.dh_ops.unregister()

    def assertSameRegistries(self, got: dict[str, dict[str, Any]],
                             expected: dict[str, dict[str, Any]]) -> None:
        """Las mismas claves en cada registro y, en cada una, el mismo objeto."""
        self.assertEqual({name: sorted(found) for name, found in got.items()},
                         {name: sorted(found) for name, found in expected.items()})
        for name, found in got.items():
            for key, item in found.items():
                self.assertIs(item, expected[name][key], f"{name}: {key}")

    def register_others(self) -> list[tuple[str, str, Any]]:
        """Lo que «otro» registra con claves de la 005 antes de habilitarla: objetos distintos
        de los de la 005. Devuelve (registro, clave, objeto)."""
        dh_params = _module("drillholes.params")
        dh_jobs = _module("drillholes.jobs")
        dh_content = _module("interop.dh_content")
        definition = dataclasses.replace(dh_params.param(dh_params.GAP_TOLERANCE))
        reader = dataclasses.replace(dh_content.DH_CSV)
        worker = dataclasses.replace(dh_jobs.WORKER_INFOS_BY_NAME[dh_jobs.VALIDATE])
        operation = self.m.provenance.operation_def(self.m.provenance.IMPORT_TABULAR)
        importer = self.m.contract.ImporterDef("io.dh_csv", _other_reimport)
        self.m.params.register_definitions([definition])
        self.m.readers.register_reader(reader)
        self.m.catalog.register_worker(worker)
        self.m.contract.register_operation(operation)
        self.m.contract.register_importer(importer)
        self.m.views.register_loader("dh_trace", "DRILLHOLES", "Drillholes", _other_loader)
        return [("parámetros", definition.key, definition), ("lectores", reader.id, reader),
                ("trabajos", worker.name, worker),
                ("operaciones", operation.op_type, operation),
                ("importadores", importer.reader_id, importer)]

    def forget_others(self, others: list[tuple[str, str, Any]]) -> Callable[[], None]:
        """Con la 005 quitada, quita lo de «otro» y vuelve a registrar la 005 (la clase sigue
        con la extensión habilitada)."""
        removers = {"parámetros": lambda key: self.m.params.unregister_definitions("dh"),
                    "lectores": self.m.readers.unregister_reader,
                    "trabajos": self.m.catalog.unregister_worker,
                    "operaciones": self.m.contract.unregister_operation,
                    "importadores": self.m.contract.unregister_importer}

        def forget() -> None:
            self.unregister_dh()
            for name, key, _item in others:
                removers[name](key)
            if self.m.views.loaders().get("dh_trace") is not None:
                if self.m.views.loaders()["dh_trace"].load is _other_loader:
                    self.m.views.unregister_loader("dh_trace")
            self.register_dh()

        return forget

    # --- Pruebas ------------------------------------------------------------------------------

    def test_disable_leaves_nothing_of_the_drillholes(self) -> None:
        """Principio 8 (plan 005 §5.6.4; ``geoblender/AGENTS.md``, Registro): habilitada, la
        005 tiene sus clases, sus propiedades en la escena y en ``WindowManager``, sus tipos de
        trabajo, sus declaraciones en ``core`` y su cargador; deshabilitarla, con una
        incorporación esperando, no deja ninguna clase, propiedad, tipo de trabajo, parámetro,
        lector, operación, importador, cargador ni temporizador de los sondeos (la huella entera
        de Blender, ``test_registration``)."""
        props = _module("bl.props.dh")
        panels = _module("bl.ui.dh_panels")
        owned = (*self.m.dh_ops.classes, *props.classes, *panels.classes)
        self.assertTrue(all(cls.is_registered for cls in owned))
        self.assertEqual({name: len(keys) for name, keys in self.m.ours().items()}, COUNTS)
        properties = ((bpy.types.Scene, props.SCENE_PROPERTY),
                      (bpy.types.WindowManager, props.IMPORT_PROPERTY),
                      (bpy.types.WindowManager, props.VALIDATION_PROPERTY))
        for owner, name in properties:
            self.assertTrue(hasattr(owner, name), name)
        self.m.dh_ops.INCORPORATIONS.add("op-1", "bocas", iter([0.5, 1.0]))
        self.assertTrue(bpy.app.timers.is_registered(self.m.dh_ops.incorporation_tick))

        self.addCleanup(blender_ext.enable)  # las demás pruebas de la clase, habilitada
        blender_ext.disable()
        self.assertEqual([cls.__name__ for cls in owned if cls.is_registered], [])
        self.assertEqual([name for name in dir(bpy.types)
                          if name.startswith("GEOBLENDER_") and "_dh_" in name], [])
        for owner, name in properties:
            self.assertFalse(hasattr(owner, name), name)
        self.assertEqual(self.m.ours(), {name: [] for name in COUNTS})
        self.assertEqual(self.m.dh_ops.pending_incorporations(), [])
        self.assertFalse(bpy.app.timers.is_registered(self.m.dh_ops.incorporation_tick))

    def test_each_command_of_005_is_real_and_registered_once(self) -> None:
        """Contrato 1 del plan 003 (plan 005 §5.3.1 y §5.5): cada orden de la entrada 005 del
        catálogo es la clase real de ``bl/ops/dh.py`` (ninguna provisional), en el orden del
        menú Sondeos y registrada una sola vez, con su etiqueta del catálogo en el idioma de
        Geoblender (en el código, su ``msgid``: ``test_ui_register``). Los menús de la 005 (el
        contextual de los sondeos) son los generados del catálogo."""
        ops = _module("bl.ops")
        registry = _module("bl.ui.registry")
        found = [cmd for cmd in self.cat.commands.values() if cmd.entry == ENTRY]
        operators = [cmd.idname for cmd in found if "." in cmd.idname]
        self.assertEqual(sorted(operators), sorted(self.m.dh_ops.COMMANDS))
        self.assertEqual(len(self.m.dh_ops.COMMANDS), 8)
        provisional = {getattr(cls, "bl_idname", cls.__name__)
                       for cls in registry.provisional_classes()}
        for cmd in found:
            with self.subTest(orden=cmd.idname):
                cls = self.m.commands.registered_class(cmd.idname)
                self.assertIsNotNone(cls)
                self.assertFalse(self.m.commands.is_provisional(cls))
                self.assertNotIn(cmd.idname, provisional)
                if "." not in cmd.idname:
                    continue
                self.assertIn(cls, self.m.dh_ops.classes)
                self.assertEqual([c for c in ops.classes if c.bl_idname == cmd.idname], [cls])
                # La registra con su etiqueta en el idioma de Geoblender (bl.ui.registry).
                self.assertEqual(cls.bl_label, self.m.commands.text(cmd.label))
                self.assertEqual(cls.bl_translation_context,
                                 self.m.commands.TRANSLATION_CONTEXT)

    def test_other_drillhole_commands_stay_provisional(self) -> None:
        """Plan 005 §5.3.1 (D-8): las órdenes de los sondeos de otras entradas (R-78: tablas,
        catálogos, congelar, seleccionar, ir al sondeo; R-14: certificados y QA/QC) siguen
        siendo las provisionales de la 003."""
        later = sorted({cmd.idname for cmd in self.cat.commands.values()
                        if cmd.idname.startswith("geoblender.dh_") and cmd.entry != ENTRY})
        self.assertIn("geoblender.dh_show_tables", later)
        self.assertGreaterEqual(len(later), 7)
        for idname in later:
            with self.subTest(orden=idname):
                cls = self.m.commands.registered_class(idname)
                self.assertTrue(self.m.commands.is_provisional(cls))
                self.assertNotIn(cls, self.m.dh_ops.classes)

    def test_undelivered_commands_say_where_they_will_be(self) -> None:
        """RF-003-07 (plan 005 §5.6.10): mientras no llega su orden, cada una no está
        disponible (``poll`` falso) y dice dónde estará, como un provisional («Disponible en
        005 · Sondeos»). Las que ya han llegado (T25: importar tablas; T26: una base de RecMin;
        T27: validar y exportar el informe; T28: las trazas, la referencia del azimut, que es
        la reimportación, y la regla bajo el límite; T30: la representación, con lo que no
        queda ninguna sin entregar) lo están en el catálogo y, sin proyecto, dicen el paso
        previo; el cargador de las trazas en la vista (T29) es el de ``bl.scene.dh_view``, en
        pasos. Los recálculos (T42) los prueba ``tests/blender/dh/test_provenance_dh.py``."""
        catalog = _module("core.catalog")
        i18n = _module("core.i18n")
        self.assertEqual(sorted(self.m.dh_ops.UNDELIVERED),
                         sorted(set(self.m.dh_ops.COMMANDS) - DELIVERED))
        for idname in sorted(DELIVERED):
            with self.subTest(entregada=idname):
                self.assertTrue(self.m.commands.is_available(idname))
                self.assertEqual(self.m.dh_ops.unavailable_reason(idname),
                                 self.m.dh_ops.open_reason())
        for idname in sorted(self.m.dh_ops.UNDELIVERED):
            with self.subTest(orden=idname):
                note = catalog.unavailable_text(self.cat, self.cat.commands[idname],
                                                i18n.language())
                self.assertEqual(self.m.dh_ops.unavailable_reason(idname), note)
                group, _, name = idname.partition(".")
                self.assertFalse(getattr(getattr(bpy.ops, group), name).poll())
        loader = _module("bl.scene.views").loader_for(self.m.dh_view.PREFIX)
        self.assertIs(loader.load, self.m.dh_view.load_traces)
        self.assertTrue(inspect.isgeneratorfunction(loader.load))

    def test_properties_panels_and_list(self) -> None:
        """Plan 005 §5.1 y §5.5: la representación vive en la escena
        (``Scene.geoblender_dh_display``, con sus clases de leyes) y la importación pendiente y
        la validación, en ``WindowManager`` (una vista que no se guarda); los tres paneles de
        la pestaña «Sondeos» y la lista de incidencias están registrados, sin proyecto no se
        muestran y se dibujan sin error."""
        props = _module("bl.props.dh")
        scene = bpy.context.scene
        manager = bpy.context.window_manager
        display = getattr(scene, props.SCENE_PROPERTY)
        self.assertIsInstance(display, props.GEOBLENDER_PG_dh_display)
        self.assertIsInstance(getattr(manager, props.IMPORT_PROPERTY),
                              props.GEOBLENDER_PG_dh_import)
        self.assertIsInstance(getattr(manager, props.VALIDATION_PROPERTY),
                              props.GEOBLENDER_PG_dh_validation)
        for cls in props.classes:
            self.assertTrue(cls.is_registered, cls.__name__)
        display.grade_classes.add().lower = "0,5"
        self.addCleanup(display.grade_classes.clear)
        self.assertEqual(display.grade_classes[0].lower, "0,5")
        session = _module("bl.scene.project_session")
        self.assertIsNone(session.current())
        for name in (*PANELS, LIST):
            with self.subTest(clase=name):
                self.assertTrue(getattr(bpy.types, name).is_registered)
        for name in PANELS:
            with self.subTest(panel=name):
                cls = getattr(bpy.types, name)
                self.assertEqual((cls.bl_space_type, cls.bl_region_type), ("VIEW_3D", "UI"))
                self.assertFalse(cls.poll(bpy.context))
                self.assertTrue(draw(cls, bpy.context).items)

    def test_operations_commands_recompute_settings_and_importers(self) -> None:
        """RF-008-26, RF-008-11, RF-008-29 (contrato de ADR-0025; plan §5.6.4): los seis tipos
        de la 005, versión 1.0, del módulo ``dh``, del proyecto y sin grupo; cada orden que los
        lanza está en el catálogo y es su clase real (las de la procedencia, operadores de la
        008 con su tipo); los repetibles (la base, la validación y las trazas) llevan su
        recálculo y los demás no; cada lector de importación, su reimportación. Las dos
        importaciones y la desviación declaran los ajustes que enseña su procedencia, con su
        español; lo registrado son las declaraciones del módulo, construidas una vez."""
        aware = _module("bl.ops.core_provenance").ProvenanceAwareOperator
        found = {op_type: defn for op_type, defn in self.m.contract.OPERATIONS.items()
                 if defn.module == "dh"}
        self.assertEqual(sorted(found), sorted(declared.op_type for declared
                                               in self.m.provenance.OPERATION_TYPES))
        launched: dict[str, set[str]] = {}
        for op_type, defn in sorted(found.items()):
            with self.subTest(operación=op_type):
                self.assertEqual((defn.version, defn.scope, defn.group), ("1.0", "project", None))
                for idname in defn.commands:
                    launched.setdefault(idname, set()).add(op_type)
                    self.assertIn(idname, self.cat.commands)
                    cls = self.m.commands.registered_class(idname)
                    self.assertIn(cls, self.m.dh_ops.classes)
                    self.assertTrue(issubclass(cls, aware), idname)
                self.assertEqual(defn.repeatable, op_type in self.m.provenance.REPEATABLE)
                self.assertEqual(callable(defn.recompute), defn.repeatable)
        for idname, op_types in launched.items():
            declared = self.m.commands.registered_class(idname).provenance_op_type
            self.assertIn(declared or next(iter(sorted(op_types))), op_types, idname)
        plain = set(self.m.dh_ops.COMMANDS) - set(launched)
        self.assertEqual(sorted(plain), ["geoblender.dh_set_detection_limit_policy",
                                         "geoblender.dh_show_display"])
        for idname in plain:
            self.assertFalse(issubclass(self.m.commands.registered_class(idname), aware))
        self.assertEqual(sorted(key for key in self.m.contract.IMPORTERS
                                if key.startswith("io.")),
                         sorted(self.m.provenance.IMPORT_READERS))
        for importer in self.m.dh_ops.IMPORTER_DEFS:
            self.assertIs(self.m.contract.IMPORTERS[importer.reader_id], importer)
            self.assertIs(importer.reimport, self.m.dh_ops.REIMPORT[importer.reader_id])
            self.assertEqual(importer.module, "io")
        self.assertEqual(sorted(self.m.dh_ops.RECOMPUTE), sorted(self.m.provenance.REPEATABLE))
        for defn in self.m.dh_ops.OPERATION_DEFS:
            self.assertIs(self.m.contract.OPERATIONS[defn.op_type], defn)
            self.assertIs(defn.recompute, self.m.dh_ops.RECOMPUTE.get(defn.op_type))
        self.assertEqual({op_type: defn.settings for op_type, defn in found.items()
                          if defn.settings}, dict(self.m.dh_ops.SETTING_DEFS))
        self.assertEqual(sorted(self.m.dh_ops.SETTING_DEFS), sorted(WITH_SETTINGS))
        msgids = {msgid for shown in self.m.dh_ops.SETTING_DEFS.values() for setting in shown
                  for msgid in (setting.label_msgid, *(name for _v, name in setting.choices))}
        self.assertEqual(_module("core.i18n").untranslated(msgids), [])

    def test_register_and_unregister_leave_core_as_it_was(self) -> None:
        """ADR-0025 §2, principio 8 (RF-005-12, RF-005-26, RF-008-01, RF-008-09): con la
        extensión habilitada, la 005 tiene en ``core`` sus 8 definiciones de parámetros, sus 3
        lectores, sus 7 tipos de trabajo, sus 6 operaciones y sus 3 importadores (ni grupos ni
        cifras), y en la vista el cargador ``dh_trace``. ``bl/ops/dh.py`` y
        ``bl/scene/dh_view.py`` lo quitan todo (dos veces: nada más cambia) y lo vuelven a
        poner (dos veces) con los mismos objetos. Con lo que «otro» registró antes con las
        mismas claves, registrar pone solo lo que falta (lo de otro se queda) y desregistrar
        deja los registros exactamente como estaban; lo que otro pone después en lugar de lo
        suyo, también se queda."""
        enabled = self.m.registries()
        ours = self.m.ours()
        self.assertEqual({name: len(keys) for name, keys in ours.items()}, COUNTS)
        bare = {name: {key: item for key, item in found.items() if not key.startswith(OURS)}
                for name, found in enabled.items()}
        others: list[tuple[str, str, Any]] = []
        self.addCleanup(lambda: self.forget_others(others)())
        for _ in range(2):
            self.unregister_dh()
            self.assertSameRegistries(self.m.registries(), bare)
        for _ in range(2):
            self.register_dh()
            self.assertSameRegistries(self.m.registries(), enabled)

        self.unregister_dh()
        others.extend(self.register_others())
        before = self.m.registries()
        self.register_dh()
        after = self.m.registries()
        self.assertEqual(self.m.ours(), ours)
        for name, key, item in others:
            with self.subTest(de_otro=f"{name}: {key}"):
                self.assertIs(after[name][key], item)
        self.assertIs(after["cargadores"]["dh_trace"], _other_loader)
        self.unregister_dh()
        self.assertSameRegistries(self.m.registries(), before)

        # Lo que otro pone en lugar de lo de la 005 después de registrarla también es suyo.
        self.register_dh()
        dh_jobs = _module("drillholes.jobs")
        replaced = dataclasses.replace(dh_jobs.WORKER_INFOS_BY_NAME[dh_jobs.DESURVEY])
        self.m.catalog.unregister_worker(replaced.name)
        self.m.catalog.register_worker(replaced)
        others.append(("trabajos", replaced.name, replaced))
        self.unregister_dh()
        self.assertIs(self.m.catalog.WORKERS[replaced.name], replaced)

    def test_incorporations_in_steps_and_closed_on_unregister(self) -> None:
        """RNF-005-06 (plan §5.6.7): la cola de incorporación de los sondeos (la suya, aparte
        de la de la topografía) avanza un paso por llamada de su temporizador, con su avance en
        la barra de estado, y la siguiente espera; un paso que falla para la suya y sigue la
        siguiente; desregistrar cierra las que esperan sin dar ni un paso más y quita el
        temporizador."""
        queue_mod = _module("bl.ops.incorporation")
        dh_ops = self.m.dh_ops
        log: list[str] = []

        def steps(name: str, fail: bool = False) -> Iterator[float]:
            try:
                for done in (0.25, 0.5):
                    log.append(f"{name} {done}")
                    yield done
                    if fail:
                        raise RuntimeError("fallo inyectado")
                log.append(f"{name} hecho")
            finally:
                log.append(f"{name} cerrado")

        self.addCleanup(dh_ops.register)
        self.addCleanup(dh_ops.unregister)
        with mock.patch.object(queue_mod, "status_text") as status:
            dh_ops.INCORPORATIONS.add("op-1", "fallo", steps("a", fail=True))
            dh_ops.INCORPORATIONS.add("op-2", "bocas", steps("b"))
            self.assertTrue(bpy.app.timers.is_registered(dh_ops.incorporation_tick))
            self.assertEqual(dh_ops.pending_incorporations(), ["op-1", "op-2"])
            ticks = 0
            with self.assertLogs("geoblender.bl.ops", "ERROR"):
                while dh_ops.incorporation_tick() is not None:
                    ticks += 1
            self.assertEqual(ticks, 4)  # tras el paso que falla, el de la siguiente
            self.assertEqual(log, ["a 0.25", "a cerrado", "b 0.25", "b 0.5", "b hecho",
                                   "b cerrado"])
            self.assertEqual(dh_ops.pending_incorporations(), [])
            shown = [call.args[0] for call in status.call_args_list]
            self.assertIn("Incorporando «bocas» al proyecto… 50 %", shown)
            self.assertIsNone(shown[-1])
            log.clear()
            dh_ops.INCORPORATIONS.add("op-3", "litología", steps("c"))
            dh_ops.incorporation_tick()
            dh_ops.unregister()
        self.assertEqual(log, ["c 0.25", "c cerrado"])
        self.assertEqual(dh_ops.pending_incorporations(), [])
        self.assertFalse(bpy.app.timers.is_registered(dh_ops.incorporation_tick))


if __name__ == "__main__":
    unittest.main()
