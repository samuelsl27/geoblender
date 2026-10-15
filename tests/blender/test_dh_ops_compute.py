# SPDX-License-Identifier: GPL-3.0-or-later
"""Calcular las trazas, la referencia del azimut y la regla bajo el límite de detección en
Blender (spec 005, T28; HU-005-4; plan 005 §5.3.1, §5.6.3, §5.6.4, §5.6.6 y §5.6.10; D-22).

Con el proyecto y las ayudas de ``test_dh_import_tabular`` (``DrillholeImportCase``): las bocas
y las desviaciones de ``tests/data/dh/csv_basico`` importadas y su base (sin su validación, que
prueba T27 y no necesita ninguna de estas órdenes). El oráculo de las trazas es el dominio: la
base leída del proyecto (``drillholes.store.read_steps``), sin los sondeos con errores de
alcance S (``validate.hole_exclusions``), por mínima curvatura (``desurvey.desurvey``) y en
filas de ``dh_trace`` (``jobs.trace_rows``) con la huella de la desviación de cada boca.

- RF-005-20, RF-005-22: ``geoblender.dh_desurvey`` (la operación ``dh.desurvey``, repetible, con
  el método y los sondeos en sus ajustes y sus dos parámetros) escribe exactamente las trazas del
  dominio y consume ``dh_collar`` y ``dh_survey``; lleva ``UNDO`` (rehace la vista), las otras
  dos no. Sin base, no empieza.
- RF-005-22, RF-008-11, RF-008-54 (D-22): ``geoblender.dh_set_azimuth_reference`` es
  «Actualizar» la entrada con la referencia nueva y su motivo (``reimport_input``): una
  sustitución de la entrada que reconstruye la base y deja obsoletas (por ``survey_sha256``)
  solo las trazas de los sondeos de esa entrada; sin motivo, sin referencia, con una entrada
  que no tiene azimuts o con la misma referencia no hace nada. «Solo las obsoletas» las vuelve a
  calcular (las del dominio) y conserva tal cual las demás.
- RF-005-26 (plan §5.6.3): la primera importación registra la regla con su valor por defecto,
  «sin confirmar»; ``geoblender.dh_set_detection_limit_policy`` la registra si falta (no otra
  vez) y abre ``geoblender.core_set_parameter`` con su clave; cambiarla queda en su historial.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import unittest
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import DrillholeImportCase, _module
from tests.support.dh_fakes import FakeCrsService

DESURVEY = "geoblender.dh_desurvey"
AZIMUTH = "geoblender.dh_set_azimuth_reference"
POLICY = "geoblender.dh_set_detection_limit_policy"
SET_PARAMETER = "geoblender.core_set_parameter"
RULE = ("dh.below_dl.method", "dh.below_dl.factor")
FILES = ("bocas.csv", "desviaciones.csv")  # lo que necesitan las trazas
SURVEYED = ("S-01", "S-02", "S-03", "S-04")  # los de desviaciones.csv
REASON = "El cliente midió las desviaciones con el norte geográfico"


def _drive(steps: Any) -> Any:
    """Lo que devuelve un generador de pasos, avanzado hasta el final."""
    try:
        while True:
            next(steps)
    except StopIteration as stop:
        return stop.value


class ComputeOpsTest(DrillholeImportCase):
    # --- Ayudas -------------------------------------------------------------------------------

    def operation(self, op_type: str) -> tuple[str, str, dict[str, Any], str]:
        """La última operación de ``op_type``: su uid, su estado, sus ajustes y su informe."""
        uid, status, settings, message = self.rows(
            "SELECT uid, status, settings, message FROM gb_operation WHERE op_type = ? "
            "ORDER BY fid DESC LIMIT 1", op_type)[0]
        return uid, status, json.loads(settings), message or ""

    def io(self, uid: str, direction: str) -> list[tuple[str, str]]:
        return self.rows("SELECT d.name, o.role FROM gb_operation_io o JOIN gb_dataset d ON "
                         "d.uid = o.item_uid WHERE o.operation_uid = ? AND o.direction = ? "
                         "ORDER BY o.rowid", uid, direction)

    def rule(self) -> dict[str, tuple[Any, ...]]:
        """La regla bajo el límite en el proyecto: su valor, su tipo, «sin confirmar» y las
        acciones de su historial."""
        found = {}
        for key in RULE:
            rows = self.rows("SELECT value, kind, unconfirmed, uid FROM gb_parameter WHERE "
                             "key = ?", key)
            if rows:
                value, kind, unconfirmed, uid = rows[0]
                actions = [row[0] for row in self.rows(
                    "SELECT action FROM gb_parameter_history WHERE parameter_uid = ? "
                    "ORDER BY fid", uid)]
                found[key] = (json.loads(value), kind, unconfirmed, actions)
        return found

    def traces(self) -> list[tuple[Any, ...]]:
        """Las filas de ``dh_trace``, por su ``fid``."""
        columns = ", ".join(f'"{name}"' for name in
                            _module("drillholes.schema").LAYOUTS["dh_trace"].insert_columns)
        return self.rows(f"SELECT {columns} FROM dh_trace ORDER BY fid")

    def expected_traces(self) -> list[tuple[Any, ...]]:
        """Las trazas del dominio sobre la base del proyecto (mínima curvatura, los parámetros
        por defecto)."""
        store = _module("drillholes.store")
        params = _module("drillholes.params")
        with self.project.read() as conn:
            dset = _drive(store.read_steps(conn))
            hashes = [row[0] for row in conn.execute(
                "SELECT survey_sha256 FROM dh_collar ORDER BY fid")]
        excluded = _module("drillholes.validate").hole_exclusions(
            dset, depth_tolerance_m=params.default(params.DEPTH_TOLERANCE))
        traces = _module("drillholes.desurvey").desurvey(dset, "minimum_curvature",
                                                         holes=~excluded)
        return _module("drillholes.jobs").trace_rows(
            dset, traces, params.default(params.TRACE_STEP), hashes, 25830)

    def stale_holes(self) -> tuple[str, ...]:
        with self.project.read() as conn:
            return _module("drillholes.store").stale_holes(conn)

    def refused(self, idname: str, **props: Any) -> str:
        """El error de la orden ``idname`` con ``props``, sin que cambie nada."""
        before = self.counts()
        group, _, name = idname.partition(".")
        with self.assertRaises(RuntimeError) as caught:
            getattr(getattr(bpy.ops, group), name)("EXEC_DEFAULT", **props)
        self.assertEqual(self.counts(), before)
        return str(caught.exception)

    # --- La prueba -----------------------------------------------------------------------------

    def test_traces_azimuth_reference_and_detection_limit_rule(self) -> None:
        """RF-005-20, RF-005-22, RF-005-26 (plan §5.6.3, §5.6.6 y §5.6.10; D-22): las tres
        órdenes están disponibles y solo calcular las trazas lleva ``UNDO``. Sin base, ni las
        trazas ni la referencia del azimut empiezan. La primera importación registra la regla
        bajo el límite «sin confirmar»; la orden de la regla no la registra otra vez y abre el
        diálogo de ``core_set_parameter`` con la clave elegida; cambiarla, al historial. Las
        trazas de todos los sondeos son las del dominio (``dh.desurvey`` con su método, sus
        sondeos y sus parámetros; consume las bocas y las desviaciones). La referencia del
        azimut sin motivo, sin referencia, de una entrada sin azimuts o igual a la registrada no
        cambia nada; con el norte geográfico y su motivo sustituye la entrada de las
        desviaciones, la base gira sus azimuts γ y solo las trazas de S-01 a S-04 quedan
        obsoletas; «solo las obsoletas» las rehace (las del dominio) y conserva tal cual las
        otras dos."""
        ops = self.dh_ops
        # Tras cada base, sin su validación: no la necesita ninguna de estas órdenes (T27 la
        # prueba) y son dos trabajos menos (el presupuesto de tools/check.py).
        self.enterContext(mock.patch.object(ops, "start_validate", lambda project, **_: None))
        # Ni la vista que se carga sola tras las trazas (T29 la prueba): dos trabajos menos.
        self.enterContext(mock.patch.object(ops, "start_view", lambda project: None))
        commands = _module("bl.ui.commands")
        for idname in (DESURVEY, AZIMUTH, POLICY):
            self.assertTrue(commands.is_available(idname), idname)
        self.assertEqual(ops.GEOBLENDER_OT_dh_desurvey.bl_options, {"REGISTER", "UNDO"})
        self.assertEqual(ops.GEOBLENDER_OT_dh_set_azimuth_reference.bl_options, {"REGISTER"})
        self.assertEqual(ops.GEOBLENDER_OT_dh_set_detection_limit_policy.bl_options,
                         {"REGISTER"})
        self.assertIn("importe sondeos", self.refused(DESURVEY))
        self.assertIn("desviaciones", self.refused(AZIMUTH, input_uid="desviaciones",
                                                   azimuth_ref="TRUE", reason=REASON))

        # La primera importación registra la regla (RF-005-26); la orden no, otra vez.
        self.import_all(FILES)
        rule = self.rule()
        self.assertEqual(rule, {"dh.below_dl.method": ("factor", "ADOPTADO", 1, ["default"]),
                                "dh.below_dl.factor": (0.5, "ADOPTADO", 1, ["default"])})
        opened: list[tuple[str, dict[str, Any]]] = []
        with mock.patch.object(ops, "open_later",
                               lambda idname, values: opened.append((idname, dict(values)))):
            self.assertEqual(bpy.ops.geoblender.dh_set_detection_limit_policy("EXEC_DEFAULT"),
                             {"FINISHED"})
            self.assertEqual(bpy.ops.geoblender.dh_set_detection_limit_policy(
                "EXEC_DEFAULT", parameter="FACTOR"), {"FINISHED"})
        self.assertEqual(opened, [(SET_PARAMETER, {"key": RULE[0]}),
                                  (SET_PARAMETER, {"key": RULE[1]})])
        self.assertEqual(self.rule(), rule)
        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            "EXEC_DEFAULT", key=RULE[1], value="0,25", source="Procedimiento de QA/QC",
            decided_by="Jefa de geología", reason="Criterio del procedimiento"), {"FINISHED"})
        self.assertEqual(self.rule()[RULE[1]], (0.25, "ADOPTADO", 0, ["default", "change"]))

        # Las trazas de todos los sondeos: las del dominio (RF-005-20).
        self.assertEqual(bpy.ops.geoblender.dh_desurvey("EXEC_DEFAULT"), {"FINISHED"})
        self.finish()
        uid, status, settings, message = self.operation("dh.desurvey")
        self.assertEqual((status, settings), ("done", {"method": "minimum_curvature",
                                                       "scope": "all"}))
        self.assertEqual(self.io(uid, "in"), [("dh_collar", "collar"), ("dh_survey", "survey")])
        self.assertEqual(self.io(uid, "out"), [("dh_trace", "trace")])
        self.assertEqual(sorted(row[0] for row in self.rows(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid)),
            ["dh.desurvey.trace_step_m", "dh.validation.depth_tolerance_m"])
        self.assertIn("mínima curvatura", message)
        expected = self.expected_traces()
        self.assertEqual(len(expected), 6)
        first = self.traces()
        self.assertEqual(first, expected)
        self.assertEqual(self.stale_holes(), ())

        # La referencia del azimut: lo que no vale no cambia nada (D-22).
        self.assertIn("motivo", self.refused(AZIMUTH, input_uid="desviaciones",
                                             azimuth_ref="TRUE"))
        self.assertIn("referencia del azimut", self.refused(
            AZIMUTH, input_uid="desviaciones", reason=REASON))
        self.assertIn("«bocas», «desviaciones»", self.refused(
            AZIMUTH, input_uid="litologia", azimuth_ref="TRUE", reason=REASON))
        self.assertIn("ya", self.refused(AZIMUTH, input_uid="desviaciones",
                                         azimuth_ref="GRID", reason=REASON))
        self.assertIn("declinación", self.refused(AZIMUTH, input_uid="desviaciones",
                                                  azimuth_ref="MAGNETIC", reason=REASON))

        # Con el norte geográfico: una sustitución de la entrada; la base gira γ (RF-005-27) y
        # solo las trazas de sus sondeos quedan obsoletas (RF-005-22).
        (old_uid, old_op), = self.rows("SELECT uid, operation_uid FROM gb_input WHERE "
                                       "name = 'desviaciones'")
        before = dict(self.rows("SELECT h.name || '@' || s.depth, s.azimuth FROM dh_survey s "
                                "JOIN dh_collar h ON h.fid = s.hole_id"))
        registry = _module("adapters.registry")
        with mock.patch.object(registry, "crs_service", FakeCrsService):
            self.assertEqual(bpy.ops.geoblender.dh_set_azimuth_reference(
                "EXEC_DEFAULT", input_uid="desviaciones", azimuth_ref="TRUE", reason=REASON),
                {"FINISHED"})
            self.finish()
        self.assertEqual(self.rows("SELECT status FROM gb_input WHERE uid = ?", old_uid),
                         [("superseded",)])
        (_uid, previous, settings), = self.rows(
            "SELECT uid, previous_uid, settings FROM gb_input WHERE name = 'desviaciones' "
            "AND status = 'current'")
        self.assertEqual(previous, old_uid)
        values = json.loads(settings)["values"]
        self.assertEqual((values["azimuth_ref"], values["declination_deg"]), ("true", None))
        uid, status, settings, _message = self.operation("dh.import_tabular")
        self.assertEqual((status, settings["azimuth_ref"], settings["name"]),
                         ("done", "true", "desviaciones"))
        self.assertEqual(self.rows("SELECT supersedes_uid FROM gb_operation WHERE uid = ?", uid),
                         [(old_op,)])
        self.assertEqual(self.operation("dh.build_base")[1], "done")
        after = dict(self.rows("SELECT h.name || '@' || s.depth, s.azimuth FROM dh_survey s "
                               "JOIN dh_collar h ON h.fid = s.hole_id"))
        for key, azimuth in before.items():
            if key.partition("@")[0] in SURVEYED:
                self.assertAlmostEqual(after[key], (azimuth - 1.5) % 360.0, places=9, msg=key)
            else:
                self.assertEqual(after[key], azimuth, key)
        self.assertEqual(self.stale_holes(), SURVEYED)
        stale = _module("core.provenance.stale")
        self.assertIn("dh_trace", {item.name for item in stale.stale_items(self.project).items})

        # «Solo las obsoletas»: las de S-01 a S-04 otra vez; las demás, conservadas.
        self.assertEqual(bpy.ops.geoblender.dh_desurvey("EXEC_DEFAULT", scope="STALE"),
                         {"FINISHED"})
        self.finish()
        uid, status, settings, message = self.operation("dh.desurvey")
        self.assertEqual((status, settings), ("done", {"method": "minimum_curvature",
                                                       "scope": "stale"}))
        self.assertIn("4 calculadas", message)
        self.assertIn("2 conservadas", message)
        names = dict(self.rows("SELECT fid, name FROM dh_collar"))
        previous = {row[1]: row for row in first}
        expected = {row[1]: row for row in self.expected_traces()}
        found = {row[1]: row for row in self.traces()}
        self.assertEqual(sorted(found), sorted(expected))
        for hole_id, row in found.items():
            with self.subTest(sondeo=names[hole_id]):
                self.assertEqual(row, expected[hole_id] if names[hole_id] in SURVEYED
                                 else previous[hole_id])
        self.assertNotEqual(found[2], previous[2])  # S-01 giró
        self.assertEqual(self.stale_holes(), ())


if __name__ == "__main__":
    unittest.main()
