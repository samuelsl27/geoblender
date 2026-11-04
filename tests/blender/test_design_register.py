# SPDX-License-Identifier: GPL-3.0-or-later
"""El registro del diseño en Blender (spec 013, T21; HU-013-1 a HU-013-6; RF-013-33; plan 013
§5.1, §5.2.4, §5.3.3, D-30; ADR-0025 §2, ADR-0027; principio 8).

- ADR-0025 §2, ADR-0027: habilitar registra en ``core`` lo que declara la 013: sus dos
  definiciones de parámetros del proyecto (tolerancia de cara y umbral de aviso de magnitud), sus
  seis familias (los cinco valores de un perfil de banco y el talud impuesto de un sector), sus
  tres tipos de operación (``des.envelope`` y ``des.stepped_design``, de la versión; la edición de
  los perfiles, del proyecto) y sus quince cifras; ``bl/ops/des.py`` lo quita y lo vuelve a poner
  con los mismos objetos y deja lo que otro registró antes con las mismas claves.
- El contrato de registro de la 008 (RF-008-26, RF-009-05, RF-009-11): cada tipo con su versión
  1.0, su ámbito, sus órdenes en el catálogo y, los dos que se repiten, su recálculo (por la cola
  de ``des``), su reproducción (la de ``design.reproduce``, al usarla) y la tolerancia de sus
  cifras; sus textos, en español.
- RF-013-33: las órdenes de Diseño que escriben (las bases :class:`DesignCommand` y
  :class:`DesignCommandAware`) están activas con un proyecto en escritura y la versión activa
  editable o sin versión activa, y desactivadas con su motivo sin proyecto, en solo lectura o con
  la versión activa SUPERADO.
- D-14, RF-013-31: el cálculo abierto (sin registrar) se descarta al cambiar de proyecto y al
  desactivar Geoblender: no deja temporales.
- Principio 8: deshabilitar no deja clases, ``WindowManager.geoblender_design`` ni
  ``geoblender_design_preview``, temporizadores, parámetros, familias, operaciones ni cifras de
  la 013, y la huella entera de Blender vuelve a la del principio de la sesión.

Rejillas mínimas y un solo proyecto por prueba que lo necesita (RNF-001-01). Se ejecuta con
``tools/run_blender_tests.py``.
"""

import dataclasses
import importlib
import sys
import unittest
from collections.abc import Callable, Iterator
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.trees import temp_folder

ENTRY = "013"
ENTRY_TITLE = ("Envelopes and benching", "Envolventes y escalonado")
COUNTS = {"parámetros": 2, "familias": 6, "operaciones": 3, "grupos": 0, "cifras": 15}
"""Lo de ``des`` en ``core``: 2 definiciones, 6 familias, 3 tipos de operación y 15 cifras."""
OURS = ("des.", "des_")  # las claves de la 013 en los registros de core
VERSION_TYPES = ("des.envelope", "des.stepped_design")
PROFILES_TYPE = "des.edit_bench_profiles"
REPRODUCED = {"des.envelope": "reproduce_envelope", "des.stepped_design": "reproduce_design"}
WM_PROPERTY = "geoblender_design"
PREVIEW_PROPERTY = "geoblender_design_preview"
PREVIEW_NAME = "Preview of seeds, domains and constraints"
PREVIEW_ABOUT = "Show the seeds, domains and constraints before computing"
GROUP = "GEOBLENDER_PG_des_panels"
STATUS_MSGID = "Recomputing «{name}»… {percent} %"
STATUS = "Recalculando «{name}»… {percent} %"
DROPPED = "cancelada durante la operación: se desactivó Geoblender antes de empezar"
DELIVERED: frozenset[str] = frozenset({"geoblender.des_edit_bench_profiles",
                                       "geoblender.des_edit_design_sectors",
                                       "geoblender.des_compute_envelope",
                                       "geoblender.des_toggle_preview"})
"""Las cuatro órdenes de Diseño de la 013 (T22 a T25 les dieron su clase real; la T26 las pasó de
R-33 a la entrada «013»)."""
INTERNAL: frozenset[str] = frozenset({"geoblender.des_save_bench_profile",
                                      "geoblender.des_set_sector_slope",
                                      "geoblender.des_export_design_grid"})
"""Las órdenes internas de sus ventanas (T22, T23 y T28): sin menú, también de la entrada «013»."""
REASON = "Prueba del registro del diseño"
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class _Modules:
    """Los módulos de la extensión que mira la prueba (los de la habilitación en curso)."""

    def __init__(self) -> None:
        self.des_ops = _module("bl.ops.des")
        self.queue = _module("bl.ops.incorporation")
        self.params = _module("core.params")
        self.contract = _module("core.provenance.contract")
        self.provenance = _module("design.provenance")
        self.profiles = _module("design.profiles")
        self.des_params = _module("design.params")
        self.commands = _module("bl.ui.commands")
        self.i18n = _module("core.i18n")

    def registries(self) -> dict[str, dict[str, Any]]:
        """Los registros de ``core`` que amplía la 013, por nombre (copias)."""
        return {
            "parámetros": dict(self.params.DEFINITIONS),
            "familias": dict(self.params.FAMILIES),
            "operaciones": dict(self.contract.OPERATIONS),
            "grupos": dict(self.contract.GROUPS),
            "cifras": dict(self.contract.FIGURES),
        }

    def ours(self) -> dict[str, list[str]]:
        return {name: sorted(key for key in found if key.startswith(OURS))
                for name, found in self.registries().items()}


class FakeCalculation:
    """Un cálculo abierto de mentira: se descarta una vez y deja de estar abierto."""

    def __init__(self) -> None:
        self.open = True
        self.discarded = 0

    def discard(self) -> None:
        self.discarded += 1
        self.open = False


class DesignRegisteredTest(unittest.TestCase):
    """Con la extensión habilitada (sin importarla otra vez: ``blender_ext.release``)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.m = _Modules()
        cls.cat = cls.m.commands.catalog()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.m.i18n.set_language, self.m.i18n.language())
        self.m.i18n.set_language("es")

    # --- Ayudas -------------------------------------------------------------------------------

    def assertSameRegistries(self, got: dict[str, dict[str, Any]],  # noqa: N802 - unittest
                             expected: dict[str, dict[str, Any]]) -> None:
        """Las mismas claves en cada registro y, en cada una, el mismo objeto."""
        self.assertEqual({name: sorted(found) for name, found in got.items()},
                         {name: sorted(found) for name, found in expected.items()})
        for name, found in got.items():
            for key, item in found.items():
                self.assertIs(item, expected[name][key], f"{name}: {key}")

    def register_others(self) -> list[tuple[str, str, Any]]:
        """Lo que «otro» registra en ``core`` con claves de la 013 antes de registrarla: objetos
        distintos de los suyos. Devuelve (registro, clave, objeto)."""
        m = self.m
        definition = dataclasses.replace(m.des_params.DEFINITIONS[0])
        family = dataclasses.replace(m.des_params.FAMILIES[0])
        operation = dataclasses.replace(m.profiles.OPERATIONS[0])
        figure = dataclasses.replace(m.provenance.FIGURES[0])
        m.params.register_definitions([definition])
        m.params.register_families([family])
        m.contract.register_operation(operation)
        m.contract.register_figure(figure)
        return [("parámetros", definition.key, definition), ("familias", family.pattern, family),
                ("operaciones", operation.op_type, operation), ("cifras", figure.key, figure)]

    def forget_others(self, others: list[tuple[str, str, Any]]) -> Callable[[], None]:
        """Con la 013 quitada, quita lo de «otro» y la vuelve a registrar."""
        m = self.m
        removers = {"parámetros": lambda key: m.params.unregister_definitions("des"),
                    "familias": lambda key: m.params.unregister_families("des"),
                    "operaciones": m.contract.unregister_operation,
                    "cifras": m.contract.unregister_figure}

        def forget() -> None:
            m.des_ops.unregister()
            for name, key, _item in others:
                removers[name](key)
            m.des_ops.register()

        return forget

    def project(self) -> tuple[Any, Any, Any]:
        """Un proyecto nuevo en escritura (fuera de la sesión) con V01 y V02; el proyecto y las
        dos versiones."""
        folder = temp_folder(self, "gb-d21-")
        (folder / "proyectos").mkdir()
        session = _module("bl.scene.project_session")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(700_000.0, 4_400_000.0, 700_024.0, 4_400_024.0), grid_step_m=1.0))
        project = core_project.create_project(folder / "proyectos", settings, session.session(),
                                              session.userdata()).project
        self.addCleanup(project.close)
        store = _module("core.versions.store")
        with project.write_transaction() as conn:
            v01, _revision = store.create_version(conn, project, feature="definitiva",
                                                  title="Definitiva", reason=REASON)
            v02, _revision = store.create_version(conn, project, feature="alternativa",
                                                  title="Alternativa", reason=REASON)
        project.refresh_header()
        return project, v01, v02

    def attach(self, project: Any) -> None:
        """El proyecto como el de la sesión, con su comprobación de apertura hecha (sin
        temporizadores en ``blender -b``)."""
        session = _module("bl.scene.project_session")
        provenance = _module("bl.ops.core_provenance")
        session.attach(project)
        self.addCleanup(session.close)
        for _ in range(2000):
            if provenance.check_tick() is None:
                break

    @staticmethod
    def set_active(version: Any) -> None:
        assert bpy.ops.geoblender.core_set_active_version(
            version_uid="" if version is None else version.uid) == {"FINISHED"}

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_register_and_unregister_leave_core_as_it_was(self) -> None:
        """ADR-0025 §2, ADR-0027, principio 8 (RF-013-33): habilitada, la 013 tiene en ``core``
        sus 2 definiciones de parámetros, sus 6 familias, sus 3 tipos de operación y sus 15
        cifras (ningún grupo acoplado). ``bl/ops/des.py`` lo quita todo (dos veces: nada más
        cambia) y lo vuelve a poner (dos veces) con los mismos objetos. Con lo que «otro»
        registró antes con las mismas claves, registrar pone solo lo que falta (lo de otro se
        queda) y desregistrar deja los registros exactamente como estaban."""
        m = self.m
        enabled = m.registries()
        ours = m.ours()
        self.assertEqual({name: len(keys) for name, keys in ours.items()}, COUNTS)
        self.assertEqual(ours["familias"], sorted(family.pattern for family
                                                  in m.des_params.FAMILIES))
        bare = {name: {key: item for key, item in found.items() if not key.startswith(OURS)}
                for name, found in enabled.items()}
        others: list[tuple[str, str, Any]] = []
        self.addCleanup(lambda: self.forget_others(others)())
        for _ in range(2):
            m.des_ops.unregister()
            self.assertSameRegistries(m.registries(), bare)
        for _ in range(2):
            m.des_ops.register()
            self.assertSameRegistries(m.registries(), enabled)

        m.des_ops.unregister()
        others.extend(self.register_others())
        before = m.registries()
        m.des_ops.register()
        after = m.registries()
        self.assertEqual(m.ours(), ours)
        for name, key, item in others:
            with self.subTest(de_otro=f"{name}: {key}"):
                self.assertIs(after[name][key], item)
        m.des_ops.unregister()
        self.assertSameRegistries(m.registries(), before)

    def test_b_operation_types_follow_the_contract_of_008(self) -> None:
        """RF-013-17, RF-013-31, RF-008-26, RF-009-05, RF-009-11 (contrato de ADR-0025; plan
        §5.2.3, D-26, D-30): los tres tipos de ``des``, versión 1.0, sin grupo; los dos de la
        envolvente y el escalonado, de la versión, repetibles, con el recálculo de
        ``bl/ops/des.py``, la reproducción de ``design.reproduce`` (al usarla) y la tolerancia de
        sus cifras (10⁻⁹), y la edición de los perfiles, del proyecto y sin repetición. Lo
        registrado son las declaraciones del módulo, construidas una vez; sus cifras, las de
        ``design.provenance``; los textos de todo ello, en español. Las cuatro órdenes de
        Diseño y las dos internas de sus ventanas son clases reales (no provisionales) de la
        entrada «013», que entrega sus comandos (RF-013-33, D-31)."""
        m = self.m
        des_ops = m.des_ops
        declared = m.provenance
        session = _module("bl.ops.core_provenance")
        # La reproducción de design.reproduce, sustituida: se importa al usarla (y arrastra la
        # cadena de versiones y de máscaras, que esta prueba no necesita).
        reproduce = SimpleNamespace(**{name: None for name in set(REPRODUCED.values())})
        self.enterContext(mock.patch.dict(sys.modules,
                                          {f"{module_name()}.design.reproduce": reproduce}))
        self.enterContext(mock.patch.object(_module("design"), "reproduce", reproduce,
                                            create=True))
        found = {op_type: defn for op_type, defn in m.contract.OPERATIONS.items()
                 if defn.module == "des"}
        self.assertEqual(sorted(found), sorted((*VERSION_TYPES, PROFILES_TYPE)))
        self.assertEqual(sorted(des_ops.RECOMPUTE), sorted(declared.REPRODUCIBLE))
        self.assertEqual(sorted(des_ops.REPRODUCE), sorted(declared.REPRODUCIBLE))
        self.assertEqual(sorted(defn.op_type for defn in des_ops.OPERATION_DEFS),
                         sorted(found))
        for defn in des_ops.OPERATION_DEFS:
            op_type = defn.op_type
            with self.subTest(operación=op_type):
                self.assertIs(found[op_type], defn)
                repeats = op_type in VERSION_TYPES
                self.assertEqual((defn.version, defn.group, defn.repeatable),
                                 ("1.0", None, repeats))
                self.assertEqual(defn.scope, "version" if repeats else "project")
                self.assertEqual(session.requires_version(op_type), repeats)
                self.assertTrue(defn.commands)
                for idname in defn.commands:
                    self.assertIn(idname, self.cat.commands)
                self.assertIs(defn.recompute, des_ops.RECOMPUTE.get(op_type))
                self.assertIs(defn.reproduce, des_ops.REPRODUCE.get(op_type))
                self.assertEqual(callable(defn.recompute), repeats)
                self.assertEqual(callable(defn.reproduce), repeats)
                self.assertEqual(defn.figure_tolerance,
                                 declared.FIGURE_TOLERANCE if repeats else None)
                if repeats:  # la reproducción es la de design.reproduce, al usarla
                    with mock.patch.object(reproduce, REPRODUCED[op_type],
                                           return_value="pasos") as function:
                        self.assertEqual(defn.reproduce("petición"), "pasos")
                    function.assert_called_once_with("petición")
        for figure in declared.FIGURES:
            self.assertIs(m.contract.FIGURES[figure.key], figure)
        for definition in m.des_params.DEFINITIONS:
            self.assertIs(m.params.DEFINITIONS[definition.key], definition)
        for family in m.des_params.FAMILIES:
            self.assertIs(m.params.FAMILIES[family.pattern], family)
        msgids = {defn.label_msgid for defn in des_ops.OPERATION_DEFS}
        msgids |= {setting.label_msgid for defn in des_ops.OPERATION_DEFS
                   for setting in defn.settings}
        msgids |= {label for defn in des_ops.OPERATION_DEFS for setting in defn.settings
                   for _value, label in setting.choices or ()}
        msgids |= {figure.label_msgid for figure in declared.FIGURES}
        msgids |= {defn.label_msgid for defn in m.des_params.DEFINITIONS}
        msgids |= {family.template.label_msgid for family in m.des_params.FAMILIES}
        self.assertNotIn(None, msgids)
        self.assertEqual(m.i18n.untranslated(msgids), [])
        catalog = _module("design.messages").CATALOG_ES  # los mensajes con código, instalados
        self.assertEqual(m.i18n.untranslated(sorted(catalog)), [])
        self.assertEqual({msgid: m.i18n.translate("es", msgid) for msgid in catalog}, dict(catalog))
        self.assertEqual(m.i18n.untranslated([STATUS_MSGID]), [])
        self.assertEqual(m.i18n.untranslated([PREVIEW_NAME, PREVIEW_ABOUT]), [])

        launched: dict[str, list[str]] = {}  # «Envolventes y escalonado…» lanza dos (D-30)
        for defn in des_ops.OPERATION_DEFS:
            for idname in defn.commands:
                launched.setdefault(idname, []).append(defn.op_type)
        self.assertEqual(sorted(launched), ["geoblender.des_compute_envelope",
                                            "geoblender.des_edit_bench_profiles"])
        self.assertEqual(launched["geoblender.des_compute_envelope"], list(VERSION_TYPES))
        for idname in sorted(launched):
            with self.subTest(orden=idname):
                self.assertIn(idname, DELIVERED)
        entry = self.cat.entries[ENTRY]
        self.assertEqual((entry.title, entry.title_es, entry.delivered), (*ENTRY_TITLE, True))
        for idname in sorted(DELIVERED | INTERNAL):
            with self.subTest(orden=idname):
                cls = m.commands.registered_class(idname)
                self.assertIn(cls, des_ops.classes)
                self.assertFalse(m.commands.is_provisional(cls))
                self.assertFalse(m.commands.is_undelivered(cls))
                self.assertEqual(self.cat.commands[idname].entry, ENTRY)
                self.assertTrue(m.commands.is_available(idname))  # ya no «Disponible en R-33»
        self.assertTrue(m.commands.is_available("GEOBLENDER_MT_des_context_design"))

    def test_c_recompute_goes_through_the_queue_of_des(self) -> None:
        """D-19, RF-013-17, RF-008-24, RF-008-26 (plan §5.3.2): el recálculo de una envolvente o
        de un escalonado empieza la operación nueva con ``design.store.recompute_run`` y deja
        sus pasos en la cola de ``des`` (``des_tick``: un paso por llamada, con su avance en la
        barra de estado); unos pasos que fallan dejan «fallida» la operación y sigue la
        siguiente; desregistrar cierra lo que espera como Esc (la operación, cancelada, sin dar
        ni un paso)."""
        m = self.m
        des_ops = m.des_ops
        progress = _module("core.project.model").Progress
        log: list[str] = []
        failed: list[tuple[str, str]] = []
        cancelled: list[str] = []

        def handle(uid: str, name: str, op_type: str) -> Any:
            return SimpleNamespace(
                uid=uid, op_type=op_type, settings={"name": name},
                fail=lambda reason: failed.append((uid, reason)), cancel=cancelled.append)

        def steps(name: str, *, fail: bool = False) -> Iterator[Any]:
            try:
                log.append(f"{name} 1")
                yield progress("envelope", 1, 2, "…")
                if fail:
                    raise RuntimeError("fallo inyectado")
                log.append(f"{name} 2")
                yield progress("store", 2, 2, "…", SimpleNamespace(handle=None))
            finally:
                log.append(f"{name} cerrado")

        made = {"Fallo": (handle("op-1", "Fallo", "des.envelope"), steps("a", fail=True)),
                "Octubre": (handle("op-2", "Octubre", "des.stepped_design"), steps("b"))}
        calls: list[str] = []

        def recompute_run(request: Any) -> Any:
            calls.append(request.op_type)
            return made[request.name]

        store = SimpleNamespace(recompute_run=recompute_run)
        self.enterContext(mock.patch.dict(sys.modules, {f"{module_name()}.design.store": store}))
        self.enterContext(mock.patch.object(_module("design"), "store", store, create=True))
        self.addCleanup(des_ops.register)
        self.addCleanup(des_ops.unregister)
        with mock.patch.object(m.queue, "status_text") as status:
            first = des_ops.recompute_envelope(SimpleNamespace(op_type="des.envelope",
                                                               name="Fallo"))
            second = des_ops.recompute_design(SimpleNamespace(op_type="des.stepped_design",
                                                              name="Octubre"))
            self.assertEqual((first.uid, second.uid), ("op-1", "op-2"))
            self.assertEqual(calls, ["des.envelope", "des.stepped_design"])
            self.assertTrue(bpy.app.timers.is_registered(des_ops.des_tick))
            self.assertEqual(des_ops.pending_runs(), ["op-1", "op-2"])
            with self.assertLogs("geoblender.bl.ops", "ERROR"):
                while des_ops.des_tick() is not None:
                    pass
            self.assertEqual(log, ["a 1", "a cerrado", "b 1", "b 2", "b cerrado"])
            self.assertEqual([uid for uid, _reason in failed], ["op-1"])
            self.assertIn("RuntimeError: fallo inyectado", failed[0][1])
            shown = [call.args[0] for call in status.call_args_list]
            self.assertIn(STATUS.format(name="Octubre", percent=50), shown)
            self.assertIsNone(shown[-1])
            self.assertEqual(des_ops.pending_runs(), [])
            log.clear()
            made["Noviembre"] = (handle("op-3", "Noviembre", "des.envelope"), steps("c"))
            des_ops.recompute_envelope(SimpleNamespace(op_type="des.envelope", name="Noviembre"))
            des_ops.des_tick()
            made["Diciembre"] = (handle("op-4", "Diciembre", "des.envelope"), steps("d"))
            des_ops.recompute_envelope(SimpleNamespace(op_type="des.envelope", name="Diciembre"))
            des_ops.unregister()
        self.assertEqual(log, ["c 1", "c cerrado"])  # la empezada la cancelan sus pasos
        self.assertEqual(cancelled, [DROPPED])  # la que no empezó queda cancelada
        self.assertEqual([uid for uid, _reason in failed], ["op-1"])
        self.assertEqual(des_ops.pending_runs(), [])
        self.assertFalse(bpy.app.timers.is_registered(des_ops.des_tick))

    def test_d_commands_are_available_with_a_writable_project_and_an_editable_version(
            self) -> None:
        """RF-013-33: las órdenes de Diseño que escriben (``DesignCommandAware``) están activas con
        un proyecto en escritura y la versión activa editable o sin versión activa (la orden que
        calcula la pide al lanzarla); y desactivadas, con su motivo en el idioma de Geoblender,
        sin proyecto («Abra un proyecto»), en solo lectura («Proyecto en solo lectura: …») o con
        la versión activa SUPERADO («V02 está en estado SUPERADO: …»), que también dice su
        descripción."""
        des_ops = self.m.des_ops
        messages: list[str] = []

        class Base:
            """Lo que da ``ProvenanceAwareOperator`` a la descripción de una orden."""

            @classmethod
            def description(cls, context: Any, properties: Any) -> str:
                return "Una orden de prueba"

        class Probe(des_ops.DesignCommandAware, Base):
            """Una orden de prueba."""

            @classmethod
            def poll_message_set(cls, text: str) -> None:
                messages.append(text)

        def poll() -> bool:
            messages.clear()
            return bool(Probe.poll(bpy.context))

        project, v01, v02 = self.project()
        self.assertEqual(des_ops.design_unavailable(), "Abra un proyecto")
        self.assertFalse(poll())
        self.assertEqual(messages, ["Abra un proyecto"])
        self.attach(project)
        self.set_active(None)  # sin versión activa: sigue disponible, la orden la pide
        self.assertIsNone(des_ops.design_unavailable())
        self.assertTrue(poll())
        self.assertEqual(messages, [])
        self.set_active(v01)
        self.addCleanup(self.set_active, None)
        self.assertTrue(poll())
        self.assertEqual(Probe.description(bpy.context, SimpleNamespace()), "Una orden de prueba")

        ps = _module("bl.scene.project_session")
        provenance = _module("bl.ops.core_provenance")
        with mock.patch.object(provenance.SESSION, "_project", None):
            self.assertFalse(poll())
            self.assertEqual(messages, ["Abra un proyecto"])
        with mock.patch.object(project, "_status", project.status):
            project.set_read_only(_module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            reason = des_ops.design_unavailable()
            self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertFalse(poll())
            self.assertEqual(messages, [reason])
        self.assertTrue(poll())

        with project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", (REASON, v02.uid))
        self.set_active(v02)
        self.assertEqual(des_ops.design_unavailable(), NOT_EDITABLE)
        self.assertFalse(poll())
        self.assertEqual(messages, [NOT_EDITABLE])
        self.assertEqual(Probe.description(bpy.context, SimpleNamespace()),
                         f"Una orden de prueba\n{NOT_EDITABLE}")
        self.set_active(v01)
        self.assertTrue(poll())
        self.assertIsNotNone(ps.current())

    def test_e_the_open_calculation_is_discarded_with_the_project_and_with_geoblender(
            self) -> None:
        """RF-013-31, D-14 (plan §5.3.2; T17): el cálculo abierto —hecho y sin registrar, con sus
        rejillas en temporales— es de la sesión: uno nuevo descarta el anterior; ya creado o
        descartado, deja de estar abierto; al cambiar de proyecto (cerrarlo o abrir otro) se
        descarta, y al desactivar Geoblender también. No deja temporales."""
        m = self.m
        des_ops = m.des_ops
        ps = _module("bl.scene.project_session")
        self.assertIn(des_ops.project_changed, ps.listeners())
        self.assertIsNone(des_ops.calculation())
        first, second = FakeCalculation(), FakeCalculation()
        des_ops.hold_calculation(first)
        self.assertIs(des_ops.calculation(), first)
        des_ops.hold_calculation(second)
        self.assertEqual((first.discarded, second.discarded), (1, 0))
        self.assertIs(des_ops.calculation(), second)
        second.open = False  # «Crear» la registró: ya no hay nada que descartar
        self.assertIsNone(des_ops.calculation())
        self.assertEqual(second.discarded, 0)

        project, _v01, _v02 = self.project()
        third = FakeCalculation()
        des_ops.hold_calculation(third)
        self.attach(project)  # otro proyecto: lo abierto era del anterior
        self.assertEqual(third.discarded, 1)
        self.assertIsNone(des_ops.calculation())
        fourth = FakeCalculation()
        des_ops.hold_calculation(fourth)
        ps.close()
        self.assertEqual(fourth.discarded, 1)
        self.assertIsNone(des_ops.calculation())

        fifth = FakeCalculation()
        des_ops.hold_calculation(fifth)
        des_ops.unregister()
        self.addCleanup(des_ops.register)
        self.assertEqual(fifth.discarded, 1)
        self.assertNotIn(des_ops.project_changed, ps.listeners())
        self.assertIsNone(des_ops.calculation())

    def test_z_disable_leaves_nothing_of_the_design(self) -> None:
        """Principio 8, RF-013-33 (``geoblender/AGENTS.md``, Registro; plan §2.1): habilitada, la
        013 tiene sus declaraciones en ``core``, ``WindowManager.geoblender_design`` (un puntero a
        su grupo) y ``geoblender_design_preview`` (un booleano que no se guarda, ``SKIP_SAVE``, y
        empieza apagado); deshabilitarla, con unos pasos esperando en su cola sin haber empezado
        y un cálculo abierto, deja su operación cancelada (no «en curso») sin dar ningún paso, el
        cálculo descartado y no deja ninguna clase, propiedad, temporizador, parámetro, familia,
        operación ni cifra de la 013, y la huella entera de Blender (clases, propiedades,
        manejadores, temporizadores, traducciones…) vuelve a la del principio de la sesión."""
        m = self.m
        props = _module("bl.props.des")
        self.assertTrue(all(cls.is_registered for cls in props.classes))
        rna = bpy.types.WindowManager.bl_rna.properties[WM_PROPERTY]
        self.assertEqual((rna.type, rna.fixed_type.identifier), ("POINTER", GROUP))
        self.assertIsInstance(getattr(bpy.context.window_manager, WM_PROPERTY),
                              props.GEOBLENDER_PG_des_panels)
        preview = bpy.types.WindowManager.bl_rna.properties[PREVIEW_PROPERTY]
        self.assertEqual(preview.type, "BOOLEAN")
        self.assertTrue(preview.is_skip_save)
        self.assertIs(getattr(bpy.context.window_manager, PREVIEW_PROPERTY), False)
        self.assertEqual({name: len(keys) for name, keys in m.ours().items()}, COUNTS)
        closed: list[str] = []
        cancelled: list[str] = []

        def steps() -> Iterator[Any]:
            try:
                yield _module("core.project.model").Progress("envelope", 1, 2, "…")
            finally:
                closed.append("cerrado")

        waiting = SimpleNamespace(uid="op-9", op_type="des.envelope", settings={"name": "X"},
                                  fail=lambda reason: None, cancel=cancelled.append)
        m.des_ops.queue_steps(waiting, steps())
        self.assertTrue(bpy.app.timers.is_registered(m.des_ops.des_tick))
        held = FakeCalculation()
        m.des_ops.hold_calculation(held)

        self.addCleanup(blender_ext.enable)  # las demás pruebas de la clase, habilitada
        blender_ext.disable()
        self.assertEqual([cls.__name__ for cls in props.classes if cls.is_registered], [])
        self.assertEqual([name for name in dir(bpy.types)
                          if name.startswith("GEOBLENDER_") and "_des_" in name], [])
        self.assertFalse(hasattr(bpy.types.WindowManager, WM_PROPERTY))
        self.assertFalse(hasattr(bpy.types.WindowManager, PREVIEW_PROPERTY))
        self.assertEqual(m.ours(), {name: [] for name in COUNTS})
        self.assertEqual(m.des_ops.pending_runs(), [])
        self.assertEqual(closed, [])  # nunca empezó: cerrarlo no da ningún paso
        self.assertEqual(cancelled, [DROPPED])
        self.assertEqual(held.discarded, 1)
        self.assertFalse(bpy.app.timers.is_registered(m.des_ops.des_tick))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(),
                                                      blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
