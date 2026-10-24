# SPDX-License-Identifier: GPL-3.0-or-later
"""El registro de la cubicación en Blender (spec 011, T19; HU-011-1; RF-011-20, RF-011-26; plan
011 §5.3.3, D-19, D-36; ADR-0025 §2, ADR-0027; principio 8).

- ADR-0025 §2, ADR-0027 (RF-011-20): habilitar registra en ``core`` lo que declara ``res``: sus
  tres definiciones de parámetros del proyecto, sus cinco familias (la densidad, el K y el
  porcentaje de cada elemento de la columna), sus cinco tipos de operación y sus veintitrés
  cifras; ``bl/ops/res.py`` lo quita y lo vuelve a poner con los mismos objetos y deja lo que
  otro registró antes con las mismas claves.
- El contrato de registro de la 008 (RF-008-26, RF-009-05, RF-009-11; RF-011-20, RF-011-26): cada
  tipo con su versión 1.0, su ámbito (los cuatro de la versión y la columna, del proyecto: la
  versión no editable desactiva sus órdenes), sus órdenes en el catálogo y, si se repite solo, su
  recálculo, su reproducción (la de ``reserves.reproduce``) y la tolerancia de sus cifras; sus
  textos, en español. La entrada «011» del catálogo (D-36), y sus órdenes, aún las provisionales
  de R-38 hasta que llegue la clase real de cada una (T20 a T25).
- D-19 (RF-011-20, RF-008-26): «Recalcular lo obsoleto» de una cubicación obsoleta por un
  parámetro empieza la operación nueva y deja sus pasos en la cola de ``res``, que avanza su
  temporizador (``res_tick``, a mano: en ``blender -b`` no corren los temporizadores) mientras
  ``recompute_steps`` espera; la cola dice su avance en la barra de estado, deja «fallida» la
  operación de unos pasos que fallan, lleva sus avisos al registro de Blender y, al
  desregistrar, cierra lo que espera (como Esc: nada a medias).
- Principio 8: deshabilitar no deja clases, propiedades, temporizadores ni nada de ``res`` en
  los registros.

Rejillas mínimas y un solo proyecto por prueba que lo necesita (RNF-001-01). Se ejecuta con
``tools/run_blender_tests.py``.
"""

import dataclasses
import importlib
import json
import sys
import unittest
from collections.abc import Callable, Iterator
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.trees import temp_folder

ENTRY = "011"
ENTRY_TITLE = ("Volumetrics between surfaces", "Cubicación entre superficies")
OURS = ("res.", "res_")  # las claves de la 011 en los registros de core
COUNTS = {"parámetros": 3, "familias": 5, "operaciones": 5, "grupos": 0, "cifras": 23}
VERSION_TYPES = ("res.volume", "res.tonnage", "res.difference", "res.stages")
REPRODUCED = {"res.volume": "reproduce_volume", "res.difference": "reproduce_volume",
              "res.tonnage": "reproduce_tonnage", "res.stages": "reproduce_stages"}
WM_PROPERTY = "geoblender_res_panels"
PANELS_GROUP = "GEOBLENDER_PG_res_panels"
NAME = "Mensual"
CELLS = 8
FINAL_Z = 100.5
THICKNESS_M = 0.3
REASON = "Prueba del registro de la cubicación"
STATUS_MSGID = "Recomputing «{name}»… {percent} %"
STATUS = "Recalculando «{name}»… {percent} %"
DROPPED = "cancelada durante la operación: se desactivó Geoblender antes de empezar"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _start_values() -> np.ndarray:
    """La superficie de partida: 100 m en el oeste y 0,25 m más por columna."""
    return 100.0 + 0.25 * np.mgrid[0:CELLS, 0:CELLS][1].astype(np.float64)


def _expected(threshold_m: float) -> tuple[float, float]:
    """El desmonte y el terraplén de la partida contra la cota :data:`FINAL_Z` con el espesor
    mínimo ``threshold_m`` (celdas de 1 m²): lo que no pasa del umbral no se mueve."""
    moved = FINAL_Z - _start_values()
    counted = np.abs(moved) > threshold_m
    return (float(-moved[counted & (moved < 0)].sum()),
            float(moved[counted & (moved > 0)].sum()))


class _Modules:
    """Los módulos de la extensión que mira la prueba (los de la habilitación en curso)."""

    def __init__(self) -> None:
        self.res_ops = _module("bl.ops.res")
        self.queue = _module("bl.ops.incorporation")
        self.params = _module("core.params")
        self.contract = _module("core.provenance.contract")
        self.provenance = _module("reserves.provenance")
        self.res_params = _module("reserves.params")
        self.commands = _module("bl.ui.commands")

    def registries(self) -> dict[str, dict[str, Any]]:
        """Los registros de ``core`` que amplía la 011, por nombre (copias)."""
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


class ResRegisteredTest(unittest.TestCase):
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
        i18n = _module("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")

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
        """Lo que «otro» registra en ``core`` con claves de la 011 antes de registrarla: objetos
        distintos de los suyos. Devuelve (registro, clave, objeto)."""
        res_params = self.m.res_params
        definition = dataclasses.replace(res_params.param(res_params.MIN_THICKNESS))
        family = dataclasses.replace(res_params.FAMILIES[0])
        operation = self.m.provenance.operation_def(self.m.provenance.EDIT_MATERIALS)
        figure = dataclasses.replace(self.m.provenance.FIGURES[0])
        self.m.params.register_definitions([definition])
        self.m.params.register_families([family])
        self.m.contract.register_operation(operation)
        self.m.contract.register_figure(figure)
        return [("parámetros", definition.key, definition), ("familias", family.pattern, family),
                ("operaciones", operation.op_type, operation), ("cifras", figure.key, figure)]

    def forget_others(self, others: list[tuple[str, str, Any]]) -> Callable[[], None]:
        """Con la 011 quitada, quita lo de «otro» y la vuelve a registrar."""
        removers = {"parámetros": lambda key: self.m.params.unregister_definitions("res"),
                    "familias": lambda key: self.m.params.unregister_families("res"),
                    "operaciones": self.m.contract.unregister_operation,
                    "cifras": self.m.contract.unregister_figure}

        def forget() -> None:
            self.m.res_ops.unregister()
            for name, key, _item in others:
                removers[name](key)
            self.m.res_ops.register()

        return forget

    def project(self) -> tuple[Any, Any]:
        """Un proyecto nuevo en escritura (fuera de la sesión) con V01 y la rejilla del proyecto
        «Partida» (:data:`CELLS` × :data:`CELLS` celdas de 1 m), escrita como la deja «Rejilla
        del proyecto desde un MDT» (``gis.resample``); el proyecto y V01."""
        folder = temp_folder(self, "gb-r19-")
        (folder / "proyectos").mkdir()
        session = _module("bl.scene.project_session")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(window=vf.WINDOW,
                                                                  grid_step_m=vf.STEP_M))
        project = core_project.create_project(folder / "proyectos", settings, session.session(),
                                              session.userdata()).project
        self.addCleanup(project.close)
        with project.write_transaction() as conn:
            version, _revision = _module("core.versions.store").create_version(
                conn, project, feature="definitiva", title="Definitiva", reason=REASON)
        project.refresh_header()
        gis_store = _module("gis.store")
        gis_provenance = _module("gis.provenance")
        crs, vertical = gis_store.project_references(project)
        grid = _module("gis.grid").Grid(vf.WEST, vf.SOUTH + CELLS, 1.0, 1.0, CELLS, CELLS)
        raster = _module("gis.raster").Raster(grid, _start_values(), crs, vertical)
        handle = _module("core.provenance.operations").begin_operation(
            project, gis_provenance.RESAMPLE, settings={"nombre": "Partida"}, executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        with gis_store.ResultWriter(project, handle) as out:
            out.raster("Partida", raster)
            out.commit(software={library: library_version}, message=REASON)
        return project, version

    def cubicate(self, project: Any, version: Any) -> str:
        """``res.volume`` de «Partida» contra la cota :data:`FINAL_Z` en ``version``, como la
        lanzará la orden (``begin_operation`` con lo que anotan las ayudas de
        ``reserves.provenance`` y los pasos de ``reserves.store`` hasta el final); su uid."""
        surfaces = _module("reserves.surfaces")
        request = _module("reserves.volumes").VolumeRequest(
            NAME, surfaces.SurfaceRef(dataset="gis_dtm_partida", label="Partida"),
            surfaces.SurfaceRef(elevation=FINAL_Z, label="Cota final"), difference_grid=False)
        declared = self.m.provenance
        handle = _module("core.provenance.operations").begin_operation(
            project, declared.VOLUME, executor="blender", version=version.uid,
            settings=declared.volume_settings(request), inputs=declared.volume_inputs(request),
            params=declared.volume_params(request))
        for _step in _module("reserves.store").volume_run(project, handle, request):
            pass
        return handle.uid

    def change_thickness(self, project: Any) -> None:
        """El espesor mínimo del proyecto a :data:`THICKNESS_M` (ADOPTADO), con su motivo."""
        store = self.m.params.ParameterStore(project)
        with project.write_transaction() as conn:
            store.change(conn, self.m.res_params.MIN_THICKNESS, value=THICKNESS_M,
                         kind="ADOPTADO", source="Criterio de la prueba", source_kind="document",
                         decided_by="la prueba", reason=REASON)

    @staticmethod
    def rows(project: Any, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def figure(self, project: Any, op_uid: str, key: str) -> float:
        (value,) = self.rows(project, "SELECT value FROM gb_figure WHERE operation_uid = ? AND "
                             "key = ? AND scope = ?", op_uid, key,
                             json.dumps({"cubication": NAME}, separators=(",", ":")))[0]
        return value

    # --- Pruebas ------------------------------------------------------------------------------

    def test_register_and_unregister_leave_core_as_it_was(self) -> None:
        """ADR-0025 §2, ADR-0027, principio 8 (RF-011-20): habilitada, la 011 tiene en ``core``
        sus 3 definiciones de parámetros, sus 5 familias, sus 5 tipos de operación y sus 23
        cifras (ningún grupo acoplado). ``bl/ops/res.py`` lo quita todo (dos veces: nada más
        cambia) y lo vuelve a poner (dos veces) con los mismos objetos. Con lo que «otro»
        registró antes con las mismas claves, registrar pone solo lo que falta (lo de otro se
        queda) y desregistrar deja los registros exactamente como estaban."""
        res_ops = self.m.res_ops
        enabled = self.m.registries()
        ours = self.m.ours()
        self.assertEqual({name: len(keys) for name, keys in ours.items()}, COUNTS)
        self.assertEqual(ours["familias"], sorted(family.pattern for family
                                                  in self.m.res_params.FAMILIES))
        bare = {name: {key: item for key, item in found.items() if not key.startswith(OURS)}
                for name, found in enabled.items()}
        others: list[tuple[str, str, Any]] = []
        self.addCleanup(lambda: self.forget_others(others)())
        for _ in range(2):
            res_ops.unregister()
            self.assertSameRegistries(self.m.registries(), bare)
        for _ in range(2):
            res_ops.register()
            self.assertSameRegistries(self.m.registries(), enabled)

        res_ops.unregister()
        others.extend(self.register_others())
        before = self.m.registries()
        res_ops.register()
        after = self.m.registries()
        self.assertEqual(self.m.ours(), ours)
        for name, key, item in others:
            with self.subTest(de_otro=f"{name}: {key}"):
                self.assertIs(after[name][key], item)
        res_ops.unregister()
        self.assertSameRegistries(self.m.registries(), before)

    def test_operation_types_follow_the_contract_of_008(self) -> None:
        """RF-011-20, RF-011-26, RF-008-26, RF-009-05, RF-009-11 (contrato de ADR-0025; plan
        §5.2.3, D-36, D-38): los cinco tipos de ``res``, versión 1.0, sin grupo; los cuatro de
        la cubicación, de la versión (la orden pide una versión editable) y la columna de
        materiales, del proyecto; cada orden que los lanza está en el catálogo; los que se
        repiten llevan el recálculo de ``bl/ops/res.py``, la reproducción de
        ``reserves.reproduce`` y la tolerancia de sus cifras (10⁻⁹), y la columna, ninguno.
        Lo registrado son las declaraciones del módulo, construidas una vez; sus cifras, las de
        ``reserves.provenance``; los textos de todo ello, en español. La entrada «011» está en
        el catálogo y las órdenes de Cubicación siguen siendo las provisionales de R-38."""
        res_ops = self.m.res_ops
        declared = self.m.provenance
        session = _module("bl.ops.core_provenance")
        # La reproducción de reserves.reproduce, sustituida: se importa al usarla, y de verdad
        # arrastra la de la 009 (unos 0,1 s que esta prueba no necesita).
        reproduce = SimpleNamespace(**{name: None for name in set(REPRODUCED.values())})
        self.enterContext(mock.patch.dict(sys.modules,
                                          {f"{module_name()}.reserves.reproduce": reproduce}))
        self.enterContext(mock.patch.object(_module("reserves"), "reproduce", reproduce,
                                            create=True))
        found = {op_type: defn for op_type, defn in self.m.contract.OPERATIONS.items()
                 if defn.module == "res"}
        self.assertEqual(sorted(found), sorted(t.op_type for t in declared.OPERATION_TYPES))
        self.assertEqual(sorted(res_ops.RECOMPUTE), sorted(declared.REPRODUCIBLE))
        self.assertEqual(sorted(res_ops.REPRODUCE), sorted(declared.REPRODUCIBLE))
        for defn in res_ops.OPERATION_DEFS:
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
                self.assertIs(defn.recompute, res_ops.RECOMPUTE.get(op_type))
                self.assertIs(defn.reproduce, res_ops.REPRODUCE.get(op_type))
                self.assertEqual(callable(defn.recompute), repeats)
                self.assertEqual(callable(defn.reproduce), repeats)
                self.assertEqual(defn.figure_tolerance,
                                 declared.FIGURE_TOLERANCE if repeats else None)
                if repeats:  # la reproducción es la de reserves.reproduce, al usarla
                    with mock.patch.object(reproduce, REPRODUCED[op_type],
                                           return_value="pasos") as function:
                        self.assertEqual(defn.reproduce("petición"), "pasos")
                    function.assert_called_once_with("petición")
        for figure in declared.FIGURES:
            self.assertIs(self.m.contract.FIGURES[figure.key], figure)
        msgids = {defn.label_msgid for defn in res_ops.OPERATION_DEFS}
        msgids |= {setting.label_msgid for defn in res_ops.OPERATION_DEFS
                   for setting in defn.settings}
        msgids |= {figure.label_msgid for figure in declared.FIGURES}
        msgids |= {defn.label_msgid for defn in self.m.res_params.DEFINITIONS}
        msgids |= {family.template.label_msgid for family in self.m.res_params.FAMILIES}
        self.assertNotIn(None, msgids)
        self.assertEqual(_module("core.i18n").untranslated(msgids), [])
        self.assertEqual(_module("core.i18n").untranslated([STATUS_MSGID]), [])

        entry = self.cat.entries[ENTRY]
        self.assertEqual((entry.title, entry.title_es, entry.delivered), (*ENTRY_TITLE, True))
        later = sorted({idname for defn in res_ops.OPERATION_DEFS for idname in defn.commands})
        self.assertEqual(len(later), 5)
        for idname in later:  # T20 a T25 las pasan a la 011 con su clase real
            with self.subTest(orden=idname):
                self.assertEqual(self.cat.commands[idname].entry, "R-38")
                self.assertTrue(self.m.commands.is_provisional(
                    self.m.commands.registered_class(idname)))
        self.assertEqual(res_ops.classes, ())

    def test_recompute_a_stale_cubication_by_its_queue(self) -> None:
        """D-19, RF-011-20, RF-011-21, RF-008-24, RF-008-26 (plan A12): una cubicación de V01
        («Partida» contra una cota) queda obsoleta al cambiar el espesor mínimo del proyecto;
        «Recalcular lo obsoleto» llama al recálculo de ``res``, que empieza la operación nueva
        «en curso» y deja sus pasos en la cola de ``res``; ``recompute_steps`` espera
        («Esperando a «res.volume»…») mientras el temporizador de la cola (``res_tick``) los
        avanza, con el avance en la barra de estado; al terminar, la nueva sustituye a la
        anterior en la revisión abierta de V01, con el espesor mínimo nuevo y sus cifras, nada
        queda obsoleto ni en la cola."""
        res_ops = self.m.res_ops
        recompute = _module("core.provenance.recompute")
        graph = _module("core.provenance.graph")
        project, version = self.project()
        first = self.cubicate(project, version)
        self.assertEqual(self.figure(project, first, "res.cut_m3"), _expected(0.0)[0])
        self.change_thickness(project)
        with project.read() as conn:
            self.assertEqual(recompute.plan_recompute(graph.load_graph(conn)).operations,
                             (first,))

        messages: list[str] = []
        waiting: list[list[str]] = []
        last = None
        with mock.patch.object(self.m.queue, "status_text") as status:
            for step in recompute.recompute_steps(project):
                messages.append(step.message)
                if res_ops.pending_runs():
                    waiting.append(res_ops.pending_runs())
                    res_ops.res_tick()  # el temporizador de la cola entre dos del modal
                last = step
        outcome = last.result
        self.assertEqual([(result.unit.op_types, str(result.status))
                          for result in outcome.results], [(("res.volume",), "done")])
        (second,) = outcome.results[0].operations
        self.assertIn("Esperando a «res.volume»…", messages)
        self.assertTrue(waiting)
        self.assertEqual({tuple(uids) for uids in waiting}, {(second,)})
        shown = [call.args[0] for call in status.call_args_list]
        self.assertIn(STATUS.format(name=NAME, percent=100), shown)
        self.assertIsNone(shown[-1])
        self.assertEqual(res_ops.pending_runs(), [])
        self.assertIsNone(res_ops.res_tick())

        (old,) = self.rows(project, "SELECT revision_uid, superseded_by FROM gb_operation "
                           "WHERE uid = ?", first)
        (new,) = self.rows(project, "SELECT status, revision_uid, supersedes_uid FROM "
                           "gb_operation WHERE uid = ?", second)
        self.assertEqual(new, ("done", old[0], first))
        self.assertEqual(old[1], second)
        (value,) = self.rows(project, "SELECT value FROM gb_operation_param WHERE "
                             "operation_uid = ? AND key = ?", second,
                             self.m.res_params.MIN_THICKNESS)[0]
        self.assertEqual(json.loads(value), THICKNESS_M)
        cut, fill = _expected(THICKNESS_M)
        self.assertNotEqual(cut, _expected(0.0)[0])
        self.assertEqual(self.figure(project, second, "res.cut_m3"), cut)
        self.assertEqual(self.figure(project, second, "res.fill_m3"), fill)
        with project.read() as conn:
            self.assertEqual(recompute.plan_recompute(graph.load_graph(conn)).operations, ())

    def test_queue_fails_reports_and_closes(self) -> None:
        """D-19, RF-011-25 (plan §2.1): la cola de ``res`` avanza un paso por llamada de su
        temporizador, uno detrás de otro; unos pasos que fallan dejan «fallida» su operación
        (con el motivo) y sigue la siguiente; los avisos del resultado van al registro de
        Blender (``bl.ops.jobs.report_later``); desregistrar cierra lo que espera sin dar ni un
        paso más (como Esc: la operación queda cancelada y nada a medias) y quita el
        temporizador."""
        res_ops = self.m.res_ops
        jobs_ops = _module("bl.ops.jobs")
        progress = _module("core.project.model").Progress
        notice = _module("reserves.volumes").Notice("res.same_surface", {"surface": "Final"})
        log: list[str] = []
        failed: list[tuple[str, str]] = []

        def handle(uid: str, name: str) -> Any:
            return SimpleNamespace(uid=uid, op_type="res.volume", settings={"name": name},
                                   fail=lambda reason: failed.append((uid, reason)),
                                   cancel=lambda reason: failed.append((uid, reason)))

        def steps(name: str, *, fail: bool = False) -> Iterator[Any]:
            try:
                log.append(f"{name} 1")
                yield progress("bands", 1, 2, "…")
                if fail:
                    raise RuntimeError("fallo inyectado")
                result = SimpleNamespace(result=SimpleNamespace(warnings=(notice,)))
                log.append(f"{name} 2")
                yield progress("save", 2, 2, "…", result)
            finally:
                log.append(f"{name} cerrado")

        self.addCleanup(res_ops.register)
        self.addCleanup(res_ops.unregister)
        with mock.patch.object(self.m.queue, "status_text") as status:
            res_ops.queue_steps(handle("op-1", "Fallo"), steps("a", fail=True))
            res_ops.queue_steps(handle("op-2", "Octubre"), steps("b"))
            self.assertTrue(bpy.app.timers.is_registered(res_ops.res_tick))
            self.assertEqual(res_ops.pending_runs(), ["op-1", "op-2"])
            ticks = 0
            with self.assertLogs("geoblender.bl.ops", "ERROR"):
                while res_ops.res_tick() is not None:
                    ticks += 1
            self.assertEqual(log, ["a 1", "a cerrado", "b 1", "b 2", "b cerrado"])
            self.assertEqual([uid for uid, _reason in failed], ["op-1"])
            self.assertIn("RuntimeError: fallo inyectado", failed[0][1])
            self.assertIn(("WARNING", notice.text("es")), jobs_ops.sent_reports())
            shown = [call.args[0] for call in status.call_args_list]
            self.assertIn(STATUS.format(name="Octubre", percent=50), shown)
            self.assertIsNone(shown[-1])
            log.clear()
            res_ops.queue_steps(handle("op-3", "Noviembre"), steps("c"))
            res_ops.res_tick()
            res_ops.unregister()
        self.assertEqual(log, ["c 1", "c cerrado"])  # la empezada la cancelan sus pasos
        self.assertEqual([uid for uid, _reason in failed], ["op-1"])
        self.assertEqual(res_ops.pending_runs(), [])
        self.assertFalse(bpy.app.timers.is_registered(res_ops.res_tick))

    def test_disable_leaves_nothing_of_res(self) -> None:
        """Principio 8, RF-011-25 (``geoblender/AGENTS.md``, Registro; plan §2.1): habilitada,
        la 011 tiene sus declaraciones en ``core``, ``WindowManager.geoblender_res_panels`` y su
        grupo; deshabilitarla, con unos pasos esperando en su cola sin haber empezado, deja su
        operación cancelada (no «en curso») sin dar ningún paso y no deja ninguna clase,
        propiedad, temporizador, parámetro, familia, operación ni cifra de la cubicación (la
        huella entera de Blender, ``test_registration``)."""
        res_ops = self.m.res_ops
        props = _module("bl.props.res")
        self.assertTrue(all(cls.is_registered for cls in props.classes))
        rna = bpy.types.WindowManager.bl_rna.properties[WM_PROPERTY]
        self.assertEqual((rna.type, rna.fixed_type.identifier), ("POINTER", PANELS_GROUP))
        self.assertIsInstance(getattr(bpy.context.window_manager, WM_PROPERTY),
                              props.GEOBLENDER_PG_res_panels)
        closed: list[str] = []

        def steps() -> Iterator[Any]:
            try:
                yield _module("core.project.model").Progress("bands", 1, 2, "…")
            finally:
                closed.append("cerrado")

        cancelled: list[str] = []
        waiting = SimpleNamespace(uid="op-9", op_type="res.volume", settings={"name": "X"},
                                  fail=lambda reason: None, cancel=cancelled.append)
        res_ops.queue_steps(waiting, steps())
        self.assertTrue(bpy.app.timers.is_registered(res_ops.res_tick))

        self.addCleanup(blender_ext.enable)  # las demás pruebas de la clase, habilitada
        blender_ext.disable()
        self.assertEqual([cls.__name__ for cls in props.classes if cls.is_registered], [])
        self.assertEqual([name for name in dir(bpy.types)
                          if name.startswith("GEOBLENDER_") and "_res_" in name], [])
        self.assertFalse(hasattr(bpy.types.WindowManager, WM_PROPERTY))
        self.assertEqual(self.m.ours(), {name: [] for name in COUNTS})
        self.assertEqual(res_ops.pending_runs(), [])
        self.assertEqual(closed, [])  # nunca empezó: cerrarlo no da ningún paso
        self.assertEqual(cancelled, [DROPPED])
        self.assertFalse(bpy.app.timers.is_registered(res_ops.res_tick))


if __name__ == "__main__":
    unittest.main()
