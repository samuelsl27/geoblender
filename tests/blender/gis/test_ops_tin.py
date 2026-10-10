# SPDX-License-Identifier: GPL-3.0-or-later
"""Puntos y líneas de rotura → TIN → rejilla en Blender (spec 006, T29; HU-006-2; plan 006
§5.3.4, §5.3.5 y §5.6.1 a §5.6.4).

Con el proyecto y las fuentes de ``test_ops_dtm`` (``DtmOperatorsCase``): las órdenes
``geoblender.gis_import_points``, ``geoblender.gis_create_tin_from_points`` y
``geoblender.gis_convert_dtm_tin``, operadores de la procedencia de la 008. El TIN es una sola
operación con una cadena de trabajos (``gis_tin_prepare`` → triangulación → ``gis_tin_finish``)
y se incorpora el último; la CDT de Blender corre entre los trabajos desde un temporizador
(que en ``blender -b`` las pruebas avanzan a mano) solo por debajo del umbral, y por encima,
el trabajo ``gis_triangulate``.

- RF-006-12, RF-006-26, RF-008-53: el CSV de puntos (columnas adivinadas por la cabecera)
  queda en ``gis_pts_`` y ``gis_brk_`` con su entrada y su original; el informe dice las filas
  leídas, las rechazadas y los duplicados.
- RF-006-13, RF-006-26: el TIN es el de ``build_tin`` con la CDT de Blender (bit a bit), con
  ``triangulator`` en ``software`` y su procedencia hasta la entrada del CSV.
- RF-006-17: la rejilla del proyecto desde ese TIN es la de ``tin_to_raster``.
- RF-008-26, RF-008-11: el recálculo del TIN y la reimportación del CSV.

:class:`TinOperatorsCase` (la cadena hasta el final) la usan también ``test_ops_tin_conflicts``
(conflictos y políticas, RF-006-14), ``test_ops_tin_threshold`` (dónde se triangula, D-12) y
``test_ops_tin_layers`` (capas, TIN desde curvas y MDT → TIN).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import time
import unittest
from typing import Any

import numpy as np

from tests.blender.gis.test_ops_dtm import JOB_WAIT_S, DtmOperatorsCase, _module

IMPORT_POINTS = "geoblender.gis_import_points"
TIN_POINTS = "geoblender.gis_create_tin_from_points"
CONVERT = "geoblender.gis_convert_dtm_tin"


class TinOperatorsCase(DtmOperatorsCase):
    """Lo de ``DtmOperatorsCase`` con la cadena de un TIN hasta el final."""

    def settle(self) -> None:
        """Avanza a mano el monitor de los trabajos y el temporizador de la triangulación
        hasta que no queda nada en marcha."""
        runner = self.jobs_ops.MONITOR.runner
        deadline = time.monotonic() + JOB_WAIT_S
        idle = 0
        while time.monotonic() < deadline:
            self.jobs_ops.tick()
            self.gis_ops.triangulation_tick()
            busy = (any(snapshot.active for snapshot in runner.snapshots())
                    or self.gis_ops.pending_triangulations())
            idle = 0 if busy else idle + 1
            if idle >= 2:
                return
            time.sleep(0.002)
        self.fail("la cadena del TIN no termina")

    def chain(self, idname: str, **props: Any) -> str:
        """La orden y su cadena de trabajos hasta el final; el uid de su operación."""
        result, op_uid = self.run_op(idname, **props)
        self.assertEqual(result, {"FINISHED"})
        self.assertIsNotNone(op_uid)
        self.settle()
        return op_uid

    def import_csv(self, relative: str, name: str, **props: Any) -> str:
        path = self.source(relative, f"topografia/{relative.rpartition('/')[2]}")
        props.setdefault("crs", "EPSG:25830")
        props.setdefault("vertical", "PROJECT")
        return self.launch(IMPORT_POINTS, filepath=str(path), name=name, encoding="UTF8",
                           separator="SEMICOLON", decimal="COMMA", **props)

    def tin_file(self, name: str) -> Any:
        return _module("gis.store").load_tin(self.project, name)


class PointsTinTest(TinOperatorsCase):
    def test_csv_to_tin_to_grid(self) -> None:
        """RF-006-12, RF-006-13, RF-006-17, RF-006-26, RF-008-53: el CSV de los taludes
        (columnas adivinadas por la cabecera P;X;Y;Z;Código;Línea) queda con su entrada, su
        original y sus 20 puntos y 4 roturas bit a bit; el TIN, triangulado en el hilo con la
        CDT de Blender (sin aviso: menos de 1 s), es el de ``build_tin`` con ella, con el
        triangulador en ``software`` y su procedencia hasta la entrada; la rejilla del
        proyecto desde el TIN es la de ``tin_to_raster``."""
        project = self.open()
        store = _module("gis.store")
        gis = _module("gis")
        triangulator = _module("bl.scene.triangulator")
        op_uid = self.import_csv("points/taludes.csv", "Taludes")
        _type, status, _reason, message, settings, *_ = self.operation(op_uid)
        self.assertEqual(status, "done")
        self.assertIn("filas leídas 44, puntos 20, líneas de rotura 4, rechazadas 0, "
                      "duplicados 0", message)
        self.assertEqual(json.loads(settings)["read"]["columns"],
                         {"point_id": 0, "x": 1, "y": 2, "z": 3, "code": 4, "line": 5})
        (entry,) = self.rows("SELECT uid, reader, original FROM gb_input WHERE name = 'Taludes'")
        self.assertEqual(entry[1:], ("gis.points_text@1", "stored"))
        points = store.load_points(project, "gis_pts_taludes")
        lines = store.load_lines(project, "gis_brk_taludes")
        self.assertEqual((len(points), len(lines)), (20, 4))
        self.ps.take_notices()

        tin_uid = self.chain(TIN_POINTS, points="gis_pts_taludes", breaklines="gis_brk_taludes",
                             name="Taludes")
        notices = " ".join(self.ps.take_notices())
        self.assertNotIn("Triangulando", notices)
        _type, status, _reason, message, settings, software, executor, _ = \
            self.operation(tin_uid)
        self.assertEqual((status, json.loads(software)),
                         ("done", {"triangulator": triangulator.NAME}))
        self.assertIn("TIN «Taludes»", message)
        self.assertEqual(json.loads(settings)["control"]["gis.tin.blender_cdt_max_s"], 2.0)
        expected, _report = gis.build_tin(points, lines,
                                          triangulator=triangulator.BlenderTriangulator(),
                                          origin=project.origin, name="Taludes")
        tin = self.tin_file("gis_tin_taludes")
        for array in ("vertices", "faces", "constraint_edges", "vertex_source"):
            self.assertTrue(np.array_equal(getattr(tin, array), getattr(expected, array)),
                            array)
        self.assertEqual(tin.meta["operation_uid"], tin_uid)
        consumed = self.rows("SELECT role FROM gb_operation_io WHERE operation_uid = ? AND "
                             "direction = 'in' ORDER BY role", tin_uid)
        self.assertEqual(consumed, [("breaklines",), ("points",)])
        lineage = _module("core.provenance.lineage").lineage(project, "gis_tin_taludes")
        self.assertIn(entry[0], lineage.inputs)
        self.assertEqual(dict(lineage.operations[tin_uid].software),
                         {"triangulator": triangulator.NAME})

        grid_uid = self.launch(CONVERT, direction="TIN_TO_DTM", source="gis_tin_taludes",
                               name="Taludes")
        self.assertEqual(self.operation(grid_uid)[:2], ("gis.tin_to_grid", "done"))
        target = _module("gis.grid").project_grid(project.window, project.grid_step_m)
        expected = _module("gis.tin").tin_to_raster(tin, target, crs=self.crs,
                                                    vertical=self.vertical)
        self.assertSameCells(store.load_raster(project, "gis_dtm_taludes"), expected)

        # RF-008-26, RF-008-11: con la tolerancia de duplicados del proyecto cambiada, el
        # recálculo rehace la cadena del TIN (la operación nueva sustituye a la anterior); el
        # TIN sale igual (ningún punto a ≤ 2 mm de otro), así que la rejilla que sale de él
        # deja de estar obsoleta sin recalcularla. Reimportar el CSV lo sustituye.
        params = _module("core.params")
        with project.write_transaction() as conn:
            params.ParameterStore(project).change(
                conn, "gis.points.dup_xy_tol_m", value=0.002, kind="ADOPTADO",
                source="Criterio de la prueba", source_kind="document",
                decided_by="la prueba", reason="Tolerancia del levantamiento")
        steps = _module("core.provenance.recompute").recompute_steps(project)
        for step in steps:
            self.jobs_ops.tick()
            self.gis_ops.triangulation_tick()
            time.sleep(0.002)
        self.assertEqual([str(unit.status) for unit in step.result.results], ["done"])
        (new_tin,) = self.rows("SELECT uid FROM gb_operation WHERE supersedes_uid = ?", tin_uid)
        self.assertEqual(self.rows("SELECT value FROM gb_operation_param WHERE operation_uid = ? "
                                   "AND key = 'gis.points.dup_xy_tol_m'", new_tin[0]),
                         [("0.002",)])
        self.assertEqual(self.operation(new_tin[0])[1], "done")
        self.assertTrue(np.array_equal(self.tin_file("gis_tin_taludes").faces, tin.faces))
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE supersedes_uid = ?",
                                   grid_uid), [(0,)])
        handle = _module("core.provenance.importer").reimport_input(
            project, entry[0], "Nueva entrega del levantamiento")
        self.settle()
        self.assertEqual(self.operation(handle.uid)[1], "done")
        self.assertEqual(self.rows("SELECT status FROM gb_input WHERE uid = ?", entry[0]),
                         [("superseded",)])


if __name__ == "__main__":
    unittest.main()
