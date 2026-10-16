# SPDX-License-Identifier: GPL-3.0-or-later
"""Los sondeos en la procedencia de la 008, de principio a fin (spec 005, T42; HU-005-1 a
HU-005-5; plan 005 §5.6.4, §5.6.6 y §5.6.10; ADR-0025), como la 006/T44.

Con el proyecto y las ayudas de ``test_dh_import_tabular`` (``DrillholeImportCase``): las bocas
y las desviaciones de ``tests/data/dh/csv_basico`` importadas, su base y su validación, y las
trazas de todos los sondeos. «Recalcular lo obsoleto» (``core.provenance.recompute``) repite la
base, la validación y las trazas con las funciones de recálculo de ``bl/ops/dh.py``
(``RECOMPUTE``). La vista que se carga sola tras las trazas no se carga (T29 la prueba): dos
trabajos menos por cálculo de las trazas (el presupuesto de ``tools/check.py``).

- RF-008-05, RF-008-24, RF-005-22: cambiar ``dh.validation.gap_tolerance_m`` deja obsoleta la
  validación y no las trazas; ``dh.desurvey.trace_step_m``, las trazas; cada una anota los
  parámetros que leyó.
- RF-008-26: «Recalcular lo obsoleto» rehace la validación y las trazas con los parámetros de
  hoy y los mismos ajustes (las trazas, las del dominio con el paso nuevo), como operaciones
  nuevas que sustituyen a las anteriores, y nada queda obsoleto.
- RF-008-29: la procedencia de ``dh_trace`` llega a los dos CSV con los parámetros de la
  desviación y los ajustes de cada orden, sin rutas ni nombres internos.
- RF-008-55, RF-008-26 (plan §5.6.10): un sondeo nuevo (S-20) de otra entrada de bocas pasa a
  la base (las trazas, obsoletas, con S-20 en el detalle); descartar esa entrada deja obsoleta
  la base, y «Recalcular lo obsoleto» la rehace desde todo lo importado vigente (sin S-20): da
  el hash que consumieron la validación y las trazas, que quedan al día sin rehacerse.
- RF-008-10, RF-008-11, RF-005-22: una desviación de S-03 cambiada en el CSV fuera de
  Geoblender impide calcular las trazas hasta decidir; «Actualizar» lo reimporta con sus
  ajustes como una entrada nueva que sustituye a la anterior, la base se reconstruye y solo
  la traza de S-03 queda obsoleta (el detalle de ``dh_collar``) hasta que se recalcula.
- T47 (RF-005-22): la vista de las trazas, cargada una vez, dice lo obsoleto en cuanto el
  temporizador de los indicadores lee el proyecto, sin recalcular nada: «OBSOLETO» sin marcas
  con S-20 (sin traza), otra vez al día al recalcular la base con su mismo hash y «OBSOLETO» con
  la marca de S-03 tras «Actualizar» (``test_dh_view.check_stale_view``).
- T48 (RF-005-23, RF-005-25; M3 y M5 de la comprobación en pantalla del 15/10/2026), con la
  litología y los análisis en columnas también, y la vista que se carga sola, con las barras
  del oro: desactivar Geoblender (cierra el proyecto y olvida lo que dibuja la
  superposición), activarlo y abrir otra vez el proyecto deja la vista con su superposición
  (sus etiquetas y sus leyendas, sin recalcular nada) y con los nombres de la primera carga: la
  recarga sustituye los objetos anteriores sin «.001» en los objetos ni en sus datos; abrirlo
  con la vista ya al día no pone otra recarga. Cambiar el radio del tubo en la representación
  cambia la malla evaluada de los tubos sin otra acción.

Lo que la tarea pide además lo prueban otras: registrar y desregistrar deja los registros de
``core`` como estaban (``test_dh_registration``, T24) y la referencia del azimut con motivo
sustituye la entrada (``test_dh_ops_compute``, T28).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import os
import re
import time
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender.test_dh_import_tabular import (
    HOLES,
    JOB_WAIT_S,
    MAX_TICKS,
    DrillholeImportCase,
    _module,
)
from tests.blender.test_dh_ops_compute import _drive
from tests.blender.test_dh_view import check_stale_view
from tests.support import blender_ext
from tests.support.fake_layout import FakeLayout

FILES = ("bocas.csv", "desviaciones.csv")  # lo que necesitan las trazas
VIEW_FILES = (*FILES, "litologia.csv", "analisis_columnas.csv")  # y la vista con el oro (T48)
VIEW_NAMES = ["Sondeos [VIGENTE]", "Sondeos [VIGENTE] · Au"]  # los tubos y las barras del oro
RADIUS, OTHER_RADIUS = 0.5, 1.25
SUFFIX = re.compile(r"\.\d{3,}$")  # el que pone Blender a un nombre que ya está
GAP = "dh.validation.gap_tolerance_m"
STEP = "dh.desurvey.trace_step_m"
DESURVEY_KEYS = ["dh.desurvey.trace_step_m", "dh.validation.depth_tolerance_m"]
BUILD_BASE = "dh.build_base"
VALIDATE = "dh.validate"
DESURVEY = "dh.desurvey"
LINEAGE_PANEL = "GEOBLENDER_PT_core_lineage"
OP_TYPE = re.compile(r"\b(dh\.[a-z_]+) \d+\.\d+\b")  # «dh.desurvey 1.0» en un eslabón
IMPORT_SETTINGS = ("Ajustes: Papel = {role} · Separador = Punto y coma · Separador decimal = "
                   "Coma · Codificación = UTF-8 · Valores sin dato = Ninguno · Negativo es bajo "
                   "el límite de detección = No · Todos verticales = Sí · Densidad = Adoptada · "
                   "Referencia del azimut = Norte de cuadrícula · Inclinación = Negativa hacia "
                   "abajo")
S03_BEFORE = b"S-03;120,00;359,50;-72,00"
S03_AFTER = b"S-03;120,00;359,50;-71,50"
S20 = "S-20;700100,000;4400100,000;805,000;50,00;;;DD;C-2026;;;no\n"


def _ring_radius(obj: Any) -> float:
    """El radio de los tubos de ``obj`` en su malla evaluada ahora (T48): lo más que se aparta
    de su centro un vértice de la sección del primer punto (``Curve to Mesh`` pone las
    secciones por puntos)."""
    sides = _module("bl.gn.drill_tubes").PROFILE_RESOLUTION
    geometry = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
    mesh = geometry.mesh  # vive mientras ``geometry``
    found = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", found)
    ring = found.reshape(-1, 3)[:sides].astype(np.float64)
    return float(np.linalg.norm(ring - ring.mean(axis=0), axis=1).max())


class DrillholeProvenanceTest(DrillholeImportCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.params = _module("core.params")
        cls.stale_mod = _module("core.provenance.stale")
        cls.graph = _module("core.provenance.graph")
        cls.recompute_mod = _module("core.provenance.recompute")
        cls.store = _module("drillholes.store")

    # --- Ayudas -------------------------------------------------------------------------------

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
        """«Recalcular lo obsoleto» entero, avanzando a mano el monitor de los trabajos y la
        cola de incorporación de los sondeos (los pasos de una incorporación, seguidos);
        devuelve su ``RecomputeOutcome``."""
        step = None
        deadline = time.monotonic() + JOB_WAIT_S
        for step in self.recompute_mod.recompute_steps(self.project):
            self.jobs_ops.tick()
            self.dh_ops.incorporation_tick()
            if not self.dh_ops.pending_incorporations():
                time.sleep(0.002)
            self.assertLess(time.monotonic(), deadline, "el recálculo no termina")
        return step.result

    def last(self, op_type: str) -> str:
        """La última operación hecha de ``op_type``."""
        return self.rows("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' "
                         "ORDER BY fid DESC LIMIT 1", op_type)[0][0]

    def successor(self, op_uid: str) -> str | None:
        found = self.rows("SELECT uid FROM gb_operation WHERE supersedes_uid = ?", op_uid)
        return found[0][0] if found else None

    def settings(self, op_uid: str) -> dict[str, Any]:
        return json.loads(self.rows("SELECT settings FROM gb_operation WHERE uid = ?",
                                    op_uid)[0][0])

    def consumed(self, op_uid: str) -> dict[str, Any]:
        """Los parámetros que leyó la operación ``op_uid`` (RF-008-05), con su valor."""
        return {key: json.loads(value) for key, value in self.rows(
            "SELECT key, value FROM gb_operation_param WHERE operation_uid = ?", op_uid)}

    def digest(self, name: str) -> str:
        return self.rows("SELECT content_sha256 FROM gb_dataset WHERE name = ? AND status = "
                         "'current'", name)[0][0]

    def input_row(self, name: str, status: str = "current") -> tuple[Any, ...]:
        (row,) = self.rows("SELECT uid, settings, content_sha256, previous_uid FROM gb_input "
                           "WHERE name = ? AND status = ?", name, status)
        return row

    def collar_detail(self) -> Any:
        """El detalle del último cambio de ``dh_collar`` (RF-005-22): los sondeos cambiados."""
        detail = self.rows("SELECT c.detail FROM gb_dataset_change c JOIN gb_dataset d ON "
                           "d.uid = c.dataset_uid WHERE d.name = 'dh_collar' ORDER BY c.fid "
                           "DESC LIMIT 1")[0][0]
        return json.loads(detail)

    def holes(self) -> list[str]:
        return [row[0] for row in self.rows("SELECT name FROM dh_collar ORDER BY fid")]

    def traces(self) -> list[tuple[Any, ...]]:
        """Las filas de ``dh_trace``, por su ``fid``."""
        columns = ", ".join(f'"{name}"' for name in
                            _module("drillholes.schema").LAYOUTS["dh_trace"].insert_columns)
        return self.rows(f"SELECT {columns} FROM dh_trace ORDER BY fid")

    def expected_traces(self, step: float) -> list[tuple[Any, ...]]:
        """Las trazas del dominio sobre la base del proyecto (mínima curvatura, la tolerancia
        de profundidad por defecto y el paso ``step``)."""
        params = _module("drillholes.params")
        with self.project.read() as conn:
            dset = _drive(self.store.read_steps(conn))
            hashes = [row[0] for row in conn.execute(
                "SELECT survey_sha256 FROM dh_collar ORDER BY fid")]
        excluded = _module("drillholes.validate").hole_exclusions(
            dset, depth_tolerance_m=params.default(params.DEPTH_TOLERANCE))
        traces = _module("drillholes.desurvey").desurvey(dset, "minimum_curvature",
                                                         holes=~excluded)
        return _module("drillholes.jobs").trace_rows(dset, traces, step, hashes, 25830)

    def show_lineage(self, name: str) -> Any:
        """Proyecto ▸ Control ▸ Procedencia y registro ▸ Grafo de operaciones y procedencia
        con la procedencia del dato ``name`` (``wm.call_panel`` sustituido)."""
        window = bpy.context.window_manager.windows[0]
        with mock.patch.object(self.session, "_call_panel", return_value={"FINISHED"}) as call:
            with bpy.context.temp_override(window=window):
                self.assertEqual(bpy.ops.geoblender.core_show_lineage(item_uid=name),
                                 {"FINISHED"})
        call.assert_called_once_with(LINEAGE_PANEL)
        return bpy.context.window_manager.geoblender_provenance

    def drawn_settings(self, name: str) -> list[tuple[str, str]]:
        """Las filas de ajustes del panel con la procedencia de ``name``: el tipo del eslabón
        de encima y el texto de la fila."""
        view = self.show_lineage(name)
        rows = []
        for index, row in enumerate(view.lineage):
            layout = FakeLayout()
            bpy.types.GEOBLENDER_UL_core_lineage.draw_item(
                SimpleNamespace(), bpy.context, layout, view, row, 0, view, "lineage_index",
                index)
            rows.append((row.depth, row.kind, [text for text in layout.texts() if text]))
        found = []
        for index, (depth, kind, texts) in enumerate(rows):
            if kind != "settings":
                continue
            above_depth, above_kind, above = rows[index - 1]
            self.assertEqual((above_depth, above_kind), (depth - 1, "operation"), texts)
            found.append((OP_TYPE.search(" ".join(above)).group(1), " ".join(texts)))
        return found

    def read_in_thread(self) -> None:
        self.reader = self.catalog.WORKERS[self.dh_jobs.IMPORT_TABULAR]
        super().read_in_thread()

    def read_in_process(self) -> None:
        """La lectura de una tabla, otra vez la que registró ``bl.ops.dh`` (al desactivar
        Geoblender, la quita; T48)."""
        self.catalog.unregister_worker(self.reader.name)
        self.catalog.register_worker(self.reader)

    def view(self) -> tuple[Any, Any]:
        """Los tubos y las barras de la vista de los sondeos del proyecto abierto."""
        objects = _module("bl.scene.dh_view").loaded_objects(self.project)
        tubes = [obj for obj in objects if obj.type == "CURVES"]
        bars = [obj for obj in objects if obj.type == "MESH"]
        self.assertEqual((len(tubes), len(bars), len(objects)), (1, 1, 2))
        return tubes[0], bars[0]

    def reopen(self) -> None:
        """Abre otra vez el proyecto en la sesión, con su comprobación de apertura hecha."""
        root = self.project.root
        self.project = self.core.open_project(root, self.ps.session(), self.ps.userdata()).project
        self.ps.attach(self.project)
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                break

    # --- Las pruebas --------------------------------------------------------------------------

    def test_import_base_validation_and_traces_end_to_end(self) -> None:
        """RF-005-11, RF-005-16, RF-005-20, RF-005-22, RF-008-05, RF-008-10, RF-008-11,
        RF-008-24, RF-008-26, RF-008-29 (plan §5.6.4, §5.6.6 y §5.6.10; ADR-0025): bocas y
        desviaciones de ``csv_basico`` → base → validación → trazas. Cambiar la tolerancia de
        huecos deja obsoleta solo la validación, y el paso de las trazas, las trazas; «Recalcular
        lo obsoleto» las rehace con los parámetros de hoy y los mismos ajustes. La procedencia
        de las trazas llega a los dos CSV con sus parámetros y sus ajustes. Descartar la entrada
        de S-20 lo saca de la base al recalcularla; con el mismo hash que consumieron la
        validación y las trazas, las deja al día sin rehacerlas. Una desviación de S-03
        cambiada fuera de Geoblender impide las trazas hasta decidir; «Actualizar» deja
        obsoleta solo la traza de S-03, hasta que se recalcula. La vista de las trazas lo dice
        en cuanto lo está, sin recalcular nada (T47)."""
        kinds = self.graph.CauseKind
        cause = self.graph.Cause
        # Sin la vista que se carga sola tras las trazas (T29 la prueba).
        self.enterContext(mock.patch.object(self.dh_ops, "start_view",
                                            lambda project, **_: None))
        self.import_all(FILES)
        self.assertEqual(bpy.ops.geoblender.dh_desurvey("EXEC_DEFAULT"), {"FINISHED"})
        self.finish()
        base_op, validate_op, desurvey_op = (self.last(op_type)
                                             for op_type in (BUILD_BASE, VALIDATE, DESURVEY))
        self.assertEqual(self.holes(), list(HOLES))
        self.assertEqual(self.stale(), {})

        # RF-008-05, RF-008-24: la tolerancia de huecos, solo la validación; el paso, las trazas.
        gap_uid = self.change(GAP, 0.02, "Huecos de muestreo admitidos por el laboratorio")
        stale = self.stale()
        self.assertEqual(sorted(stale), ["dh_validation_issue"])
        causes, text = stale["dh_validation_issue"]
        self.assertEqual(causes, {cause(kinds.PARAMETER_CHANGED, gap_uid)})
        self.assertTrue(text.startswith("Obsoleto: cambió "), text)
        step_uid = self.change(STEP, 1.0, "Trazas más finas para el modelo geológico")
        stale = self.stale()
        self.assertEqual(sorted(stale), ["dh_trace", "dh_validation_issue"])
        self.assertEqual(stale["dh_trace"][0], {cause(kinds.PARAMETER_CHANGED, step_uid)})
        self.assertEqual(sorted(self.consumed(desurvey_op)), DESURVEY_KEYS)
        self.assertEqual(self.consumed(desurvey_op)[STEP], 2.0)

        # RF-008-26: la validación y las trazas, otra vez, con los parámetros de hoy.
        self.assertEqual(self.plan().operations, (validate_op, desurvey_op))
        traces_before = self.digest("dh_trace")
        outcome = self.recompute()
        self.assertEqual([(result.unit.op_types, str(result.status))
                          for result in outcome.results],
                         [((VALIDATE,), "done"), ((DESURVEY,), "done")])
        self.assertEqual(self.stale(), {})
        validate_op, desurvey_op = self.successor(validate_op), self.successor(desurvey_op)
        self.assertEqual(self.consumed(validate_op)[GAP], 0.02)
        self.assertEqual(self.consumed(desurvey_op)[STEP], 1.0)
        self.assertEqual(self.settings(desurvey_op), {"method": "minimum_curvature",
                                                      "scope": "all"})
        self.assertNotEqual(self.digest("dh_trace"), traces_before)
        self.assertEqual(self.traces(), self.expected_traces(1.0))
        # T47: la vista de estas trazas (la que se carga sola, aquí a mano: T29), al día.
        self.assertEqual(bpy.ops.geoblender.core_load_into_view("EXEC_DEFAULT",
                                                                datasets="dh_trace"),
                         {"FINISHED"})
        check_stale_view(self, (), stale=False)

        # RF-008-29: la procedencia de las trazas, hasta los dos CSV.
        lineage = _module("core.provenance.lineage").lineage(self.project, "dh_trace")
        links = list(lineage.operations.values())
        self.assertEqual(sorted(link.op_type for link in links),
                         [BUILD_BASE, DESURVEY, "dh.import_tabular", "dh.import_tabular"])
        entries = {name: self.input_row(name)[0] for name in ("bocas", "desviaciones")}
        self.assertEqual(sorted(lineage.inputs), sorted(entries.values()))
        (traced,) = [link for link in links if link.op_type == DESURVEY]
        self.assertEqual(sorted(param.key for param in traced.params), DESURVEY_KEYS)
        (step,) = [param for param in traced.params if param.key == STEP]
        self.assertEqual((step.value, step.unit, step.unconfirmed), (1.0, "m", False))
        settings = self.drawn_settings("dh_trace")
        self.assertEqual(settings, [
            (DESURVEY, "Ajustes: Método = Mínima curvatura · Sondeos = Todos los sondeos"),
            ("dh.import_tabular", IMPORT_SETTINGS.format(role="Bocas")),
            ("dh.import_tabular", IMPORT_SETTINGS.format(role="Desviaciones")),
        ])
        for _op_type, text in settings:
            for internal in ("bocas", "desviaciones", "dh_", "{", str(self.project.root),
                             os.sep):
                self.assertNotIn(internal, text)

        # RF-008-55, RF-008-26 (plan §5.6.10): S-20, de otra entrada de bocas (la base sin su
        # validación, que no hace falta aquí: un trabajo menos), y su entrada descartada: la
        # base vuelve a la de antes, con el mismo hash, y la validación y las trazas, que la
        # consumieron, quedan al día sin rehacerse.
        collar_digest = self.digest("dh_collar")
        (self.sources / "bocas_s20.csv").write_text(
            (self.sources / "bocas.csv").read_text(encoding="utf-8").splitlines()[0] + "\n"
            + S20, encoding="utf-8")
        with mock.patch.object(self.dh_ops, "start_validate", lambda project, **_: None):
            result, _launched = self.run_import(("bocas_s20.csv",),
                                                {"bocas_s20.csv": "collar"})
            self.assertEqual(result, {"FINISHED"})
            self.finish()
        self.assertEqual(self.dh_ops.waiting_imports(), {})
        self.assertEqual(self.holes(), [*HOLES, "S-20"])
        self.assertEqual(sorted(self.stale()), ["dh_trace", "dh_validation_issue"])
        self.assertEqual(self.collar_detail(), {"holes": ["S-20"]})
        check_stale_view(self, (), stale=True)  # T47: obsoletas, sin ningún sondeo marcado
        base_op = self.last(BUILD_BASE)
        self.assertEqual(bpy.ops.geoblender.core_discard_input(
            input_uid="bocas_s20", reason="El sondeo S-20 no se perforó"), {"FINISHED"})
        stale = self.stale()
        (s20_uid,) = self.rows("SELECT uid FROM gb_input WHERE name = 'bocas_s20'")[0]
        self.assertEqual(stale["dh_collar"][0], {cause(kinds.INPUT_DISCARDED, s20_uid)})
        self.assertLessEqual({"dh_collar", "dh_survey", "dh_validation_issue", "dh_trace"},
                             set(stale))
        self.assertEqual(self.plan().operations, (base_op, validate_op, desurvey_op))
        outcome = self.recompute()
        self.assertEqual([(result.unit.operations, str(result.status))
                          for result in outcome.results], [((base_op,), "done")])
        self.assertEqual(self.stale(), {})
        self.assertEqual(self.holes(), list(HOLES))
        self.assertEqual(self.digest("dh_collar"), collar_digest)
        self.assertEqual((self.successor(validate_op), self.successor(desurvey_op)),
                         (None, None))
        check_stale_view(self, (), stale=False)  # T47: otra vez al día, sin recargarla
        consumed = {name for (name,) in self.rows(
            "SELECT d.name FROM gb_operation_io o JOIN gb_dataset d ON d.uid = o.item_uid "
            "WHERE o.operation_uid = ? AND o.direction = 'in'", self.successor(base_op))}
        self.assertTrue(consumed)
        self.assertFalse(any("bocas_s20" in name for name in consumed), consumed)

        # RF-008-10, RF-008-11, RF-005-22: una desviación de S-03 cambiada fuera.
        surveys = self.input_row("desviaciones")
        source = self.sources / "desviaciones.csv"
        data = source.read_bytes()
        self.assertEqual(data.count(S03_BEFORE), 1)
        source.write_bytes(data.replace(S03_BEFORE, S03_AFTER))
        later = time.time() + 10
        os.utime(source, (later, later))
        operations = self.counts()[0]
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.dh_desurvey("EXEC_DEFAULT")
        self.assertIn("La entrada «desviaciones» ha cambiado", str(caught.exception))
        self.assertEqual(self.counts()[0], operations)
        self.assertEqual(self.rows("SELECT status FROM gb_input WHERE uid = ?", surveys[0]),
                         [("changed",)])
        self.assertEqual(bpy.ops.geoblender.core_resolve_input(
            input_uid=surveys[0], decision="UPDATE",
            reason="El contratista corrigió una medida de S-03"), {"FINISHED"})
        self.finish()
        updated = self.input_row("desviaciones")
        self.assertEqual(updated[3], surveys[0])
        self.assertEqual(json.loads(updated[1]), json.loads(surveys[1]))
        self.assertNotEqual(updated[2], surveys[2])
        self.assertEqual(self.rows("SELECT status FROM gb_input WHERE uid = ?", surveys[0]),
                         [("superseded",)])
        # RF-005-11: las desviaciones de S-01 a S-04 en la base, todas de la entrada nueva.
        self.assertEqual(self.rows("SELECT DISTINCT s.input_uid FROM dh_survey s JOIN dh_collar "
                                   "h ON h.fid = s.hole_id WHERE h.name LIKE 'S-0%'"),
                         [(updated[0],)])
        self.assertEqual(sorted(self.stale()), ["dh_trace"])
        with self.project.read() as conn:
            self.assertEqual(self.store.stale_holes(conn), ("S-03",))
        self.assertEqual(self.collar_detail(), {"holes": ["S-03"]})
        check_stale_view(self, ("S-03",), stale=True)  # T47: S-03 marcado, sin recalcular
        uses = self.dh_ops.desurvey_uses()
        self.assertIsNotNone(self.session.ensure_ready(DESURVEY, uses))

        # RF-008-26, RF-005-22: hasta que se recalculan.
        self.assertEqual(self.plan().operations, (desurvey_op,))
        outcome = self.recompute()
        self.assertEqual([(result.unit.op_types, str(result.status))
                          for result in outcome.results], [((DESURVEY,), "done")])
        self.assertEqual(self.stale(), {})
        with self.project.read() as conn:
            self.assertEqual(self.store.stale_holes(conn), ())
        self.assertEqual(self.traces(), self.expected_traces(1.0))

    def test_view_after_reenabling_and_reopening_and_live_radius(self) -> None:
        """RF-005-23, RF-005-25 (T48; M3, M5): tras desactivar Geoblender, activarlo y abrir
        otra vez el proyecto, la vista de los sondeos vuelve con su superposición (las mismas
        etiquetas, leyendas y representación) y los nombres de la primera carga, sin «.001»
        en los objetos ni en sus datos; abrirlo con la vista al día no la recarga. Cambiar el
        radio del tubo cambia la malla evaluada sin otra acción."""
        dh_view = _module("bl.scene.dh_view")
        drill_tubes = _module("bl.gn.drill_tubes")
        views = _module("bl.scene.views")
        ops = self.dh_ops
        # Fuera la vista que otra prueba de la clase dejó en la escena (de su proyecto): sus
        # nombres no se cruzan con los de esta.
        views.unload_datasets(views.loaded_uids(bpy.data.objects))
        self.enterContext(mock.patch.object(ops, "start_validate", lambda project, **_: None))
        self.import_all(VIEW_FILES)
        display = getattr(bpy.context.scene, self.props.SCENE_PROPERTY)
        display.element, display.tube_radius = "Au", RADIUS
        self.assertEqual(bpy.ops.geoblender.dh_desurvey("EXEC_DEFAULT"), {"FINISHED"})
        self.finish()  # las trazas y, después, su vista
        tubes, bars = self.view()
        self.assertEqual([tubes.name, bars.name], VIEW_NAMES)
        self.assertEqual([tubes.data.name, bars.data.name], VIEW_NAMES)
        before = dh_view.overlay_of(tubes)
        self.assertIsNotNone(before)
        self.assertIn("S-12 (160,00 m)", [item.text for item in before.labels])

        # Desactivar (cierra el proyecto y olvida la superposición), activar y abrir otra vez.
        self.read_in_process()
        blender_ext.disable()
        blender_ext.enable()
        self.assertIsNone(dh_view.overlay_of(tubes))
        self.reopen()
        self.finish()  # la recarga de la vista
        tubes, bars = self.view()
        self.assertEqual([tubes.name, bars.name], VIEW_NAMES)
        self.assertEqual([tubes.data.name, bars.data.name], VIEW_NAMES)
        for collection in (bpy.data.hair_curves, bpy.data.meshes):  # ni datos de antes
            self.assertEqual([item.name for item in collection if SUFFIX.search(item.name)], [])
        self.assertEqual(len(bpy.data.hair_curves), 1)
        found = dh_view.overlay_of(tubes)
        self.assertIsNotNone(found)
        self.assertIs(dh_view.overlay_of(bars), found)
        self.assertEqual([(item.text, item.xyz, item.bottom) for item in found.labels],
                         [(item.text, item.xyz, item.bottom) for item in before.labels])
        self.assertEqual((found.lithology, found.element, found.grade, found.marks,
                          found.display_key),
                         (before.lithology, before.element, before.grade, before.marks,
                          before.display_key))
        ops.on_project_changed(self.project)  # al día: no la recarga otra vez
        self.assertEqual(ops.pending_incorporations(), [])

        # El radio, en vivo (M3): la malla evaluada cambia sin otra acción.
        display = getattr(bpy.context.scene, self.props.SCENE_PROPERTY)  # la de su registro
        self.assertEqual(drill_tubes.tube_radius(tubes), RADIUS)
        first = _ring_radius(tubes)
        display.tube_radius = OTHER_RADIUS
        self.assertEqual(drill_tubes.tube_radius(tubes), OTHER_RADIUS)
        self.assertAlmostEqual(_ring_radius(tubes), first * OTHER_RADIUS / RADIUS, delta=1e-4)


if __name__ == "__main__":
    unittest.main()
