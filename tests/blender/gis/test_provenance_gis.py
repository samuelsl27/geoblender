# SPDX-License-Identifier: GPL-3.0-or-later
"""La topografía en la procedencia de la 008, de principio a fin (spec 006, T44; HU-006-1 a
HU-006-6; plan 006 §5.6.1, §5.6.3 y §5.6.8; ADR-0025).

Con el proyecto, las fuentes y las órdenes de ``test_ops_dtm`` y ``test_ops_tin``
(``TinOperatorsCase``): las órdenes de la 006 son operadores de la procedencia de la 008, y
``bl/ops/gis.py`` registra en ``core`` lo que la topografía declara.

- ADR-0025 §2 (principio 8): registrar y desregistrar la 006 deja los registros de ``core``
  (definiciones de parámetros, lectores de contenido y su lector de tablas, tipos de trabajo,
  operaciones, grupos, cifras e importadores) como estaban, también con lo que otro registró
  antes con las mismas claves, que es suyo.
- RF-008-26, RF-008-11, RF-008-61 (contrato de ADR-0025): cada ``OperationDef`` de la 006 tiene
  su versión, sus órdenes en el catálogo (operadores reales de la procedencia) y su recálculo
  si es repetible, y cada lector de importación, su reimportación.
- RF-006-26, RF-008-05, RF-008-10, RF-008-11, RF-008-24, RF-008-26, RF-008-29, D17, D18: en un
  proyecto sintético, MDT → rejilla → curvas y CSV → TIN → curvas. Cambiar la fracción mínima
  del proyecto deja obsoletas la rejilla y sus curvas con esa causa, y no el TIN; «Recalcular
  lo obsoleto» (``plan_recompute`` con las funciones de la 006) las rehace y quita la marca, y
  el recálculo que da el mismo hash no rehace las curvas. Una cota cambiada en el CSV bloquea
  crear el TIN hasta decidir, y «Actualizar» lo reimporta con sus ajustes y deja el TIN
  obsoleto. Los parámetros de control no dejan nada obsoleto; el valor tecleado en las curvas
  es un ajuste; la procedencia de las curvas llega al CSV y al MDT con sus parámetros, y su
  panel enseña los ajustes de cada eslabón con su unidad o su elección (T58).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import json
import os
import re
import time
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender.gis.test_ops_dtm import FRACTION, RESAMPLE, WINDOW, _module
from tests.blender.gis.test_ops_tin import TIN_POINTS, TinOperatorsCase
from tests.support.fake_layout import FakeLayout

CONTOURS = "geoblender.gis_create_contours"
LINEAGE_PANEL = "GEOBLENDER_PT_core_lineage"
OP_TYPE = re.compile(r"\b(gis\.[a-z_]+) \d+\.\d+\b")  # «gis.contours 1.0» en un eslabón
RESOLVE_INPUT = "geoblender.core_resolve_input"
INTERVAL = "gis.contours.interval_m"
MAX_CELLS = "gis.import.max_cells"
CDT_MAX_S = "gis.tin.blender_cdt_max_s"
CONTOUR_PARAMS = ["gis.contours.index_every_m", "gis.contours.index_offset_m",
                  "gis.contours.min_length_m", "gis.contours.simplify_m"]
OURS = ("gis.", "gis_")  # las claves de la 006 en los registros de core
TABLE_READER = "lector de tablas"
COUNTS = {"parámetros": 17, "lectores": 5, TABLE_READER: 0, "trabajos": 13, "operaciones": 11,
          "grupos": 0, "cifras": 0, "importadores": 5}


def _other_table_reader(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("el lector de tablas de otro no se usa en esta prueba")


def _other_reimport(request: Any) -> Any:
    raise AssertionError("la reimportación de otro no se usa en esta prueba")


class GisProvenanceTest(TinOperatorsCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.params = _module("core.params")
        cls.readers = _module("core.content.readers")
        cls.content = _module("gis.content")
        cls.catalog = _module("jobs.catalog")
        cls.contract = _module("core.provenance.contract")
        cls.provenance = _module("gis.provenance")
        cls.stale_mod = _module("core.provenance.stale")
        cls.graph = _module("core.provenance.graph")
        cls.recompute_mod = _module("core.provenance.recompute")
        cls.operations_mod = _module("core.provenance.operations")

    # --- Ayudas -------------------------------------------------------------------------------

    def registries(self) -> dict[str, dict[str, Any]]:
        """Los registros de ``core`` que amplía la 006, por nombre (copias)."""
        return {
            "parámetros": dict(self.params.DEFINITIONS),
            "lectores": dict(self.readers.READERS),
            TABLE_READER: {"": self.content.table_reader()},
            "trabajos": dict(self.catalog.WORKERS),
            "operaciones": dict(self.contract.OPERATIONS),
            "grupos": dict(self.contract.GROUPS),
            "cifras": dict(self.contract.FIGURES),
            "importadores": dict(self.contract.IMPORTERS),
        }

    def assertSameRegistries(self, got: dict[str, dict[str, Any]],
                             expected: dict[str, dict[str, Any]]) -> None:
        """Las mismas claves en cada registro y, en cada una, el mismo objeto."""
        self.assertEqual({name: sorted(found) for name, found in got.items()},
                         {name: sorted(found) for name, found in expected.items()})
        for name, found in got.items():
            for key, item in found.items():
                self.assertIs(item, expected[name][key], f"{name}: {key}")

    @staticmethod
    def without_ours(registries: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        bare = {name: {key: item for key, item in found.items() if not key.startswith(OURS)}
                for name, found in registries.items()}
        bare[TABLE_READER] = {"": None}
        return bare

    def register_others(self) -> list[tuple[str, str, Any]]:
        """Lo que «otro» registra en ``core`` con claves de la 006 antes de habilitarla (una
        definición, un lector, el lector de tablas, un tipo de trabajo, una operación y un
        importador): objetos distintos de los de la 006. Devuelve (registro, clave, objeto)."""
        gis_params = _module("gis.params")
        gis_jobs = _module("gis.jobs")
        definition = dataclasses.replace(gis_params.param(FRACTION))
        reader = dataclasses.replace(self.content.ASC)
        worker = dataclasses.replace(gis_jobs.WORKER_INFOS_BY_NAME["gis_validate"])
        operation = self.provenance.operation_def(self.provenance.IMPORT_DTM)
        importer = self.contract.ImporterDef("gis.asc", _other_reimport)
        self.params.register_definitions([definition])
        self.readers.register_reader(reader)
        self.content.use_table_reader(_other_table_reader)
        self.catalog.register_worker(worker)
        self.contract.register_operation(operation)
        self.contract.register_importer(importer)
        return [("parámetros", definition.key, definition), ("lectores", reader.id, reader),
                (TABLE_READER, "", _other_table_reader), ("trabajos", worker.name, worker),
                ("operaciones", operation.op_type, operation),
                ("importadores", importer.reader_id, importer)]

    def forget_others(self, others: list[tuple[str, str, Any]]) -> Callable[[], None]:
        """Con la 006 quitada, quita lo de «otro» y vuelve a registrar la 006 (la clase sigue
        con la extensión habilitada)."""
        removers = {"parámetros": lambda key: self.params.unregister_definitions("gis"),
                    "lectores": self.readers.unregister_reader,
                    TABLE_READER: lambda key: self.content.use_table_reader(None),
                    "trabajos": self.catalog.unregister_worker,
                    "operaciones": self.contract.unregister_operation,
                    "importadores": self.contract.unregister_importer}

        def forget() -> None:
            self.gis_ops.unregister()
            for name, key, _item in others:
                removers[name](key)
            self.gis_ops.register()

        return forget

    def surface(self) -> Any:
        """El MDT del vuelo: 100 × 80 celdas de 1 m sobre la ventana del proyecto (rejilla de
        2 m), con una celda sin dato en 49 bloques de 2 × 2: con la fracción mínima 1 esas
        celdas del proyecto quedan sin dato; con 0,5 o 0,7 (tres de cuatro), con la media."""
        grid = self.grid.Grid(WINDOW[0], WINDOW[3], 1.0, 1.0, 100, 80)
        rows, cols = np.mgrid[0:80, 0:100].astype(np.float64)
        values = (812.0 + 0.12 * cols + 0.08 * rows
                  + 1.5 * np.sin(cols / 9.0) * np.cos(rows / 7.0))
        for block_row in range(3, 40, 6):
            for block_col in range(4, 50, 7):
                values[2 * block_row, 2 * block_col + 1] = np.nan
        return self.raster.Raster(grid, values, self.crs, self.vertical)

    def change(self, key: str, value: Any, reason: str) -> str:
        """Cambia en el proyecto el parámetro ``key`` (registrado antes con su valor por
        defecto si aún no lo está); devuelve su uid."""
        store = self.params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            store.ensure_default(conn, key,
                                 geoblender_version=self.project.session.geoblender_version)
            store.change(conn, key, value=value, kind="ADOPTADO", source="Criterio de la prueba",
                         source_kind="document", decided_by="la prueba", reason=reason)
        return store.get(key).uid

    def stale(self) -> dict[str, tuple[frozenset[Any], str]]:
        """Lo obsoleto de la lista (RF-008-28): cada dato con sus causas y su texto."""
        report = self.stale_mod.stale_items(self.project)
        return {item.name: (item.causes, item.text) for item in report.items}

    def plan(self) -> Any:
        with self.project.read() as conn:
            return self.recompute_mod.plan_recompute(self.graph.load_graph(conn))

    def recompute(self) -> Any:
        """«Recalcular lo obsoleto» entero, avanzando a mano los trabajos y la triangulación;
        devuelve su ``RecomputeOutcome``."""
        step = None
        for step in self.recompute_mod.recompute_steps(self.project):
            self.jobs_ops.tick()
            self.gis_ops.triangulation_tick()
            self.gis_ops.incorporation_tick()
            time.sleep(0.002)
        return step.result

    def parameter(self, key: str) -> tuple[Any, ...] | None:
        found = self.rows("SELECT value, rev, unconfirmed FROM gb_parameter WHERE key = ?", key)
        return found[0] if found else None

    def consumed(self, op_uid: str) -> list[str]:
        return sorted(key for (key,) in self.rows(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", op_uid))

    def successor(self, op_uid: str) -> str | None:
        found = self.rows("SELECT uid FROM gb_operation WHERE supersedes_uid = ?", op_uid)
        return found[0][0] if found else None

    def input_row(self, name: str, status: str = "current") -> tuple[Any, ...]:
        (row,) = self.rows("SELECT uid, settings, content_sha256, previous_uid FROM gb_input "
                           "WHERE name = ? AND status = ?", name, status)
        return row

    def show_lineage(self, name: str) -> Any:
        """Proyecto ▸ Control ▸ Procedencia y registro ▸ Grafo de operaciones y procedencia
        con la procedencia del dato ``name`` (``wm.call_panel`` sustituido): la vista de
        ``WindowManager`` con sus filas."""
        window = bpy.context.window_manager.windows[0]
        with mock.patch.object(self.session, "_call_panel", return_value={"FINISHED"}) as call:
            with bpy.context.temp_override(window=window):
                self.assertEqual(bpy.ops.geoblender.core_show_lineage(item_uid=name),
                                 {"FINISHED"})
        call.assert_called_once_with(LINEAGE_PANEL)
        return bpy.context.window_manager.geoblender_provenance

    @staticmethod
    def drawn_rows(view: Any) -> list[tuple[int, str, list[str]]]:
        """Lo que dibuja la lista del panel: profundidad, clase y textos de cada fila."""
        found = []
        for index, row in enumerate(view.lineage):
            layout = FakeLayout()
            bpy.types.GEOBLENDER_UL_core_lineage.draw_item(
                SimpleNamespace(), bpy.context, layout, view, row, 0, view, "lineage_index",
                index)
            found.append((row.depth, row.kind, [text for text in layout.texts() if text]))
        return found

    def drawn_settings(self, name: str) -> list[tuple[str, str]]:
        """Las filas de ajustes del panel con la procedencia de ``name``: el tipo del eslabón
        de encima (una fila menos sangrada) y el texto de la fila."""
        rows = self.drawn_rows(self.show_lineage(name))
        found = []
        for index, (depth, kind, texts) in enumerate(rows):
            if kind != "settings":
                continue
            above_depth, above_kind, above = rows[index - 1]
            self.assertEqual((above_depth, above_kind), (depth - 1, "operation"), texts)
            found.append((OP_TYPE.search(above[0]).group(1), " ".join(texts)))
        return found

    # --- Pruebas ------------------------------------------------------------------------------

    def test_register_and_unregister_leave_core_as_it_was(self) -> None:
        """ADR-0025 §2, principio 8 (RF-006-26, RF-008-09): con la extensión habilitada, la 006
        tiene en ``core`` sus 17 definiciones de parámetros, sus 5 lectores y el lector de
        tablas de ``interop``, sus 13 tipos de trabajo, sus 11 operaciones y sus 5
        importadores (ni grupos ni cifras). ``bl/ops/gis.py`` lo quita todo (dos veces: nada
        más cambia) y lo vuelve a poner (dos veces) con los mismos objetos. Con lo que «otro»
        registró antes con las mismas claves, registrar pone solo lo que falta (lo de otro se
        queda) y desregistrar deja los registros exactamente como estaban."""
        enabled = self.registries()
        ours = {name: sorted(key for key in found if key.startswith(OURS))
                for name, found in enabled.items()}
        self.assertEqual({name: len(keys) for name, keys in ours.items()}, COUNTS)
        read_table = _module("interop.csv_tables").read_table
        self.assertIs(self.content.table_reader(), read_table)
        others: list[tuple[str, str, Any]] = []
        self.addCleanup(lambda: self.forget_others(others)())
        for _ in range(2):
            self.gis_ops.unregister()
            self.assertSameRegistries(self.registries(), self.without_ours(enabled))
        for _ in range(2):
            self.gis_ops.register()
            self.assertSameRegistries(self.registries(), enabled)

        self.gis_ops.unregister()
        others.extend(self.register_others())
        before = self.registries()
        self.gis_ops.register()
        after = self.registries()
        self.assertEqual({name: sorted(key for key in found if key.startswith(OURS))
                          for name, found in after.items() if name != TABLE_READER},
                         {name: keys for name, keys in ours.items() if name != TABLE_READER})
        for name, key, item in others:
            with self.subTest(de_otro=f"{name}: {key}"):
                self.assertIs(after[name][key], item)
        self.gis_ops.unregister()
        self.assertSameRegistries(self.registries(), before)

    def test_each_operation_has_its_commands_and_recompute(self) -> None:
        """RF-008-26, RF-008-11, RF-008-61 (contrato de ADR-0025; plan §5.6.3 y §5.6.8): los
        once tipos de operación de la 006 están registrados con la versión 1.0, del módulo
        ``gis``, con ámbito proyecto y sin grupo; cada orden que los lanza está en el catálogo
        de comandos y es el operador real de la procedencia (disponible); los repetibles
        (remuestreo, TIN, conversiones y curvas) llevan su recálculo y los demás no; cada
        lector de importación tiene su reimportación. RF-008-29 (T58): cada tipo salvo las
        conversiones y las exportaciones declara los ajustes que enseña su procedencia, con
        su español."""
        commands = _module("bl.ui.commands")
        cat = commands.catalog()
        aware = self.session.ProvenanceAwareOperator
        found = {op_type: defn for op_type, defn in self.contract.OPERATIONS.items()
                 if defn.module == "gis"}
        self.assertEqual(sorted(found),
                         sorted(declared.op_type for declared in self.provenance.OPERATION_TYPES))
        launched: dict[str, set[str]] = {}
        for op_type, defn in sorted(found.items()):
            with self.subTest(operación=op_type):
                self.assertEqual((defn.version, defn.version_tuple), ("1.0", (1, 0)))
                self.assertEqual((defn.scope, defn.group), ("project", None))
                self.assertTrue(defn.commands)
                for idname in defn.commands:
                    launched.setdefault(idname, set()).add(op_type)
                    self.assertIn(idname, cat.commands)
                    cls = commands.registered_class(idname)
                    self.assertFalse(commands.is_provisional(cls))
                    self.assertTrue(commands.is_available(idname))
                    self.assertTrue(issubclass(cls, aware), idname)
                self.assertEqual(defn.repeatable, op_type in self.provenance.REPEATABLE)
                self.assertEqual(callable(defn.recompute), defn.repeatable)
        for idname, op_types in launched.items():
            declared = commands.registered_class(idname).provenance_op_type
            self.assertIn(declared or next(iter(op_types)), op_types, idname)
        self.assertEqual(sorted(key for key in self.contract.IMPORTERS if key.startswith("gis.")),
                         sorted(self.provenance.IMPORT_READERS))
        for reader_id in self.provenance.IMPORT_READERS:
            importer = self.contract.IMPORTERS[reader_id]
            self.assertEqual(importer.module, "gis")
            self.assertTrue(callable(importer.reimport), reader_id)
        # Lo registrado son las declaraciones del módulo, construidas una vez.
        self.assertEqual(sorted(self.gis_ops.RECOMPUTE), sorted(self.provenance.REPEATABLE))
        for defn in self.gis_ops.OPERATION_DEFS:
            self.assertIs(self.contract.OPERATIONS[defn.op_type], defn)
            self.assertIs(defn.recompute, self.gis_ops.RECOMPUTE.get(defn.op_type))
        for importer in self.gis_ops.IMPORTER_DEFS:
            self.assertIs(self.contract.IMPORTERS[importer.reader_id], importer)
            self.assertIs(importer.reimport, self.gis_ops.REIMPORT[importer.reader_id])
        # RF-008-29 (T58): los ajustes que enseña la procedencia de cada tipo (ninguno en las
        # conversiones y las exportaciones), con su español en el catálogo.
        self.assertEqual({op_type: defn.settings for op_type, defn in found.items()
                          if defn.settings}, dict(self.gis_ops.SETTING_DEFS))
        self.assertEqual(sorted(self.gis_ops.SETTING_DEFS), sorted(
            set(found) - {"gis.grid_to_tin", "gis.tin_to_grid", "gis.export_raster",
                          "gis.export_gpkg"}))
        msgids = {msgid for shown in self.gis_ops.SETTING_DEFS.values() for setting in shown
                  for msgid in (setting.label_msgid, *(name for _v, name in setting.choices))}
        self.assertEqual(_module("core.i18n").untranslated(msgids), [])

    def test_dtm_grid_contours_and_csv_tin_end_to_end(self) -> None:
        """RF-006-26, RF-008-05, RF-008-10, RF-008-11, RF-008-24, RF-008-26, RF-008-29, D17,
        D18 (plan §5.6.1 y §5.6.8): MDT del vuelo → rejilla del proyecto (fracción mínima del
        proyecto, 1, consumida) → curvas con la equidistancia 2 m tecleada (un ajuste: no se
        consume ni cambia el parámetro, 1 m), y CSV de los taludes → TIN → curvas. La
        procedencia de las curvas llega a la entrada del MDT y a la del CSV con los parámetros
        de cada operación; el panel «Grafo de operaciones y procedencia» (RF-006-18, T58)
        enseña debajo de cada eslabón los ajustes de su orden con su unidad o su elección
        («Equidistancia = 2 m»), sin los internos ni rutas, y se pliegan con él. Subir el
        límite de celdas y el umbral de la CDT de Blender (de
        control) no deja nada obsoleto. Con la fracción a 0,5, la rejilla y sus curvas quedan
        obsoletas por ese cambio y el TIN no; recalcular lo obsoleto (el plan: remuestreo y
        curvas) las rehace con los mismos ajustes y nada queda obsoleto. Con la fracción a 0,7
        la rejilla sale con el mismo hash y las curvas dejan de estar obsoletas sin
        rehacerlas. Con una cota cambiada en el CSV fuera de Geoblender, crear el TIN se niega
        («ha cambiado») hasta decidir; «Actualizar» lo reimporta con sus ajustes registrados
        como una entrada nueva que sustituye a la anterior, deja obsoletos el TIN y sus curvas
        («se actualizó la entrada») y no la rejilla, y la puerta deja crear el TIN."""
        project = self.open()
        lineage = _module("core.provenance.lineage").lineage
        cause = self.graph.Cause
        kinds = self.graph.CauseKind
        # MDT → rejilla → curvas (D18: la equidistancia tecleada es un ajuste).
        self.import_dtm(self.written(self.surface(), "mdt/vuelo.tif"), "MDT vuelo")
        grid_op = self.launch(RESAMPLE, source="gis_src_mdt_vuelo", name="Vuelo",
                              min_valid_fraction="1")
        interval = self.parameter(INTERVAL)
        contours_op = self.launch(CONTOURS, source="gis_dtm_vuelo", interval="2", name="Vuelo")
        self.assertEqual(self.operation(contours_op)[1], "done")
        self.assertEqual(json.loads(self.operation(contours_op)[4])["interval_m"], 2.0)
        self.assertEqual(self.consumed(contours_op), CONTOUR_PARAMS)
        self.assertEqual(self.parameter(INTERVAL), interval)
        self.assertEqual(self.consumed(grid_op), [FRACTION])
        # CSV → TIN → curvas.
        self.import_csv("points/taludes.csv", "Taludes")
        tin_op = self.chain(TIN_POINTS, points="gis_pts_taludes", breaklines="gis_brk_taludes",
                            name="Taludes")
        tin_contours_op = self.launch(CONTOURS, source="gis_tin_taludes", name="Taludes")
        self.assertEqual([self.operation(uid)[1] for uid in (tin_op, tin_contours_op)],
                         ["done", "done"])
        self.assertEqual(self.consumed(tin_contours_op), sorted([*CONTOUR_PARAMS, INTERVAL]))

        # RF-008-29, RF-006-26: la procedencia de las curvas, hasta sus entradas.
        mdt_input = self.input_row("MDT vuelo")[0]
        csv_input = self.input_row("Taludes")
        for name, chain, entry, params in (
            ("gis_cnt_vuelo", ["gis.contours", "gis.resample", "gis.import_dtm"], mdt_input,
             {"gis.contours": CONTOUR_PARAMS, "gis.resample": [FRACTION]}),
            ("gis_cnt_taludes", ["gis.contours", "gis.tin_from_points", "gis.import_points"],
             csv_input[0], {"gis.contours": sorted([*CONTOUR_PARAMS, INTERVAL]),
                            "gis.tin_from_points": ["gis.points.dup_xy_tol_m",
                                                    "gis.points.dup_z_tol_m"]}),
        ):
            with self.subTest(procedencia=name):
                tree = lineage(project, name)
                links = list(tree.operations.values())
                self.assertEqual([link.op_type for link in links], chain)
                self.assertEqual(list(tree.inputs), [entry])
                self.assertEqual({link.op_type: sorted(p.key for p in link.params)
                                  for link in links if link.params}, params)
        (fraction,) = [found for link in lineage(project, "gis_cnt_vuelo").operations.values()
                       for found in link.params if found.key == FRACTION]
        self.assertEqual((fraction.value, fraction.unit, fraction.unconfirmed),
                         (1.0, "-", True))

        # RF-008-29, RF-006-18 (T58, M7): el panel de la procedencia enseña, debajo de cada
        # eslabón, los ajustes de su orden con su unidad o su elección (la equidistancia
        # tecleada, 2 m), y no los internos (nombre, fuente, fichero) ni ninguna ruta.
        settings = {name: self.drawn_settings(name)
                    for name in ("gis_cnt_vuelo", "gis_cnt_taludes")}
        self.assertEqual(settings["gis_cnt_vuelo"], [
            ("gis.contours", "Ajustes: Equidistancia = 2 m · Cota base = 0 m"),
            ("gis.resample", "Ajustes: Método = Automático"),
        ])
        self.assertEqual(settings["gis_cnt_taludes"], [
            ("gis.contours", "Ajustes: Cota base = 0 m"),
            ("gis.tin_from_points", "Ajustes: Puntos que coinciden = Preguntar"),
            ("gis.import_points", "Ajustes: Codificación = UTF-8 · Separador = Punto y coma · "
                                  "Separador decimal = Coma · Líneas antes de la cabecera = 0 · "
                                  "Líneas de rotura = Duras"),
        ])
        for name, found in settings.items():
            for op_type, text in found:
                for internal in ("Vuelo", "Taludes", "vuelo", "taludes", "gis_", "{",
                                 str(project.root), os.sep):
                    self.assertNotIn(internal, text, (name, op_type))
        view = self.show_lineage("gis_cnt_vuelo")
        contours_row = [row.kind for row in view.lineage].index("operation")
        self.assertEqual(view.lineage[contours_row + 1].kind, "settings")
        view.lineage[contours_row].expanded = False  # plegar el eslabón de las curvas
        shown = _module("bl.ui.provenance").lineage_visible(view.lineage)
        self.assertEqual(shown[:contours_row + 2], [True] * (contours_row + 1) + [False])

        # D17: los parámetros de control no dejan nada obsoleto.
        self.assertEqual(self.stale(), {})
        # Los dos están en su máximo por defecto (10⁸ celdas, 2 s): se bajan y se suben.
        for key, values in ((MAX_CELLS, (50_000_000, 100_000_000)), (CDT_MAX_S, (1.0, 2.0))):
            for value in values:
                self.change(key, value, "Otro equipo")
                self.assertEqual(self.stale(), {}, (key, value))
        self.assertEqual(self.plan().units, ())

        # RF-008-24, RF-008-26: la fracción mínima cambia la rejilla y sus curvas.
        grid_before = self.dataset("gis_dtm_vuelo")[3]
        contours_before = self.dataset("gis_cnt_vuelo")[3]
        fraction_uid = self.change(FRACTION, 0.5, "Media cobertura")
        stale = self.stale()
        self.assertEqual(sorted(stale), ["gis_cnt_vuelo", "gis_dtm_vuelo"])
        for name, (causes, text) in stale.items():
            self.assertEqual(causes, {cause(kinds.PARAMETER_CHANGED, fraction_uid)}, name)
            self.assertEqual(text, "Obsoleto: cambió Fracción mínima con dato de una celda")
        plan = self.plan()
        self.assertEqual(plan.operations, (grid_op, contours_op))
        self.assertEqual(plan.skipped, ())
        outcome = self.recompute()
        self.assertEqual([str(unit.status) for unit in outcome.results], ["done", "done"])
        self.assertEqual(self.stale(), {})
        new_grid = self.successor(grid_op)
        new_contours = self.successor(contours_op)
        self.assertEqual([self.operation(uid)[1] for uid in (new_grid, new_contours)],
                         ["done", "done"])
        self.assertEqual(self.rows("SELECT value FROM gb_operation_param WHERE operation_uid = ?",
                                   new_grid), [("0.5",)])
        self.assertEqual(json.loads(self.operation(new_contours)[4])["interval_m"], 2.0)
        grid_after = self.dataset("gis_dtm_vuelo")[3]
        self.assertNotEqual(grid_after, grid_before)
        self.assertNotEqual(self.dataset("gis_cnt_vuelo")[3], contours_before)
        values = self.stored("gis_dtm_vuelo").values
        self.assertEqual(int(np.count_nonzero(np.isnan(values))), 0)
        self.assertIsNone(self.successor(tin_op))

        # Un recálculo sin cambios en el resultado da el mismo hash: las curvas no se rehacen.
        self.change(FRACTION, 0.7, "Tres cuartos de celda")
        self.assertEqual(sorted(self.stale()), ["gis_cnt_vuelo", "gis_dtm_vuelo"])
        outcome = self.recompute()
        self.assertEqual([str(unit.status) for unit in outcome.results], ["done"])
        self.assertEqual(self.dataset("gis_dtm_vuelo")[3], grid_after)
        self.assertIsNotNone(self.successor(new_grid))
        self.assertIsNone(self.successor(new_contours))
        self.assertEqual(self.stale(), {})

        # RF-008-10, RF-008-11: una cota cambiada en el CSV bloquea el TIN hasta decidir.
        source = self.sources / "topografia" / "taludes.csv"
        data = source.read_bytes()
        self.assertEqual(data.count(b";821,800;"), 1)
        source.write_bytes(data.replace(b";821,800;", b";822,300;"))
        later = time.time() + 10
        os.utime(source, (later, later))
        operations = self.counts()[0]
        with self.assertRaises(RuntimeError) as caught:
            self.run_op(TIN_POINTS, points="gis_pts_taludes", breaklines="gis_brk_taludes",
                        name="Taludes")
        self.assertIn("La entrada «Taludes» ha cambiado", str(caught.exception))
        self.assertEqual(self.counts()[0], operations)
        self.assertEqual(self.rows("SELECT status FROM gb_input WHERE uid = ?", csv_input[0]),
                         [("changed",)])
        self.assertEqual(bpy.ops.geoblender.core_resolve_input(
            input_uid=csv_input[0], decision="UPDATE",
            reason="Cota corregida en el levantamiento"), {"FINISHED"})
        self.settle()
        updated = self.input_row("Taludes")
        self.assertEqual(updated[3], csv_input[0])
        self.assertEqual(json.loads(updated[1]), json.loads(csv_input[1]))
        self.assertNotEqual(updated[2], csv_input[2])
        self.assertEqual(self.rows("SELECT status FROM gb_input WHERE uid = ?", csv_input[0]),
                         [("superseded",)])
        points = _module("gis.store").load_points(project, "gis_pts_taludes")
        self.assertIn(822.3, points.xyz[:, 2].tolist())
        stale = self.stale()
        self.assertEqual(sorted(stale), ["gis_cnt_taludes", "gis_tin_taludes"])
        for name, (causes, text) in stale.items():
            self.assertEqual({found.kind for found in causes}, {kinds.INPUT_UPDATED}, name)
            self.assertEqual(text, "Obsoleto: se actualizó la entrada «Taludes»")
        uses = [self.operations_mod.Use(self.dataset(name)[0], role) for name, role in
                (("gis_pts_taludes", "points"), ("gis_brk_taludes", "breaklines"))]
        self.assertIsNotNone(self.session.ensure_ready("gis.tin_from_points", uses))


if __name__ == "__main__":
    unittest.main()
